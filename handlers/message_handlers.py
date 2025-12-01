"""
Обработчики текстовых сообщений.
"""

import asyncio

from aiogram import F, types
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError

from bot_instance import bot, dp
from config import ADMIN_CHAT, MESSAGES, logger
from database import User
from services.llm_service import (
    get_llm_response,
    process_user_image,
    process_user_video,
    save_to_context_and_format,
)
from services.message_buffer import message_buffer
from utils import forward_to_debug, keep_typing, should_respond_in_chat


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_message(message: types.Message):
    """Обработка текстовых сообщений через LLM (исключая команды)."""
    # Игнорируем сообщения из ADMIN_CHAT - не обрабатываем их через LLM
    if message.chat.id == ADMIN_CHAT:
        return

    # В групповых чатах отвечаем только на упоминания
    if not await should_respond_in_chat(message):
        logger.debug(f"CHAT{message.chat.id}: сообщение без упоминания бота, игнорируем")
        return

    logger.info(f"USER{message.chat.id}TOLLM:{message.text}")
    await forward_to_debug(message.chat.id, message.message_id)

    # Обновляем имя пользователя в базе данных (если изменилось)
    user_obj = User(message.chat.id)
    await user_obj.get_from_db()
    if message.from_user:
        new_name = (
            message.from_user.first_name
            if message.from_user.first_name
            else (
                message.from_user.username
                if message.from_user.username
                else "Not_of_registration"
            )
        )
        if user_obj.name != new_name and new_name != "Not_of_registration":
            user_obj.name = new_name
            await user_obj.update_in_db()
            logger.debug(f"USER{message.chat.id} имя обновлено: {new_name}")

    # Добавляем сообщение в буфер
    should_process = await message_buffer.add_message(message.chat.id, message.text)

    if not should_process:
        # Обработка уже идет, сообщение добавлено в буфер
        # Индикатор "печатает..." уже активен, ничего не делаем
        return

    # Запускаем индикатор печати ОДИН РАЗ для всей серии сообщений
    typing_task = asyncio.create_task(keep_typing(message.chat.id))

    try:
        # Цикл обработки: обрабатываем пока есть сообщения в буфере
        while True:
            # ПРОСМАТРИВАЕМ все накопленные сообщения БЕЗ очистки буфера
            messages = await message_buffer.peek_buffered_messages(message.chat.id)
            combined_text = "\n".join(messages)

            logger.info(f"USER{message.chat.id}TOLLM (объединено {len(messages)} сообщений): {combined_text}")

            # Создаем задачу для получения ответа от LLM
            llm_task = asyncio.create_task(get_llm_response(message.chat.id, combined_text))
            await message_buffer.set_current_task(message.chat.id, llm_task)

            # Периодически проверяем, не пришли ли новые сообщения
            was_interrupted = False
            while not llm_task.done():
                await asyncio.sleep(0.1)

                # Сравниваем текущий буфер с тем, что мы начали обрабатывать
                current_buffer = await message_buffer.peek_buffered_messages(message.chat.id)
                if len(current_buffer) > len(messages):
                    # Пришли новые сообщения! НЕ ждем текущий ответ
                    logger.info(
                        f"USER{message.chat.id} пришли новые сообщения "
                        f"({len(current_buffer) - len(messages)} новых), "
                        f"прерываем ожидание текущего ответа"
                    )
                    was_interrupted = True
                    # Прерываем ожидание (задача продолжит работать в фоне, но результат нам не нужен)
                    break

            # Если задача завершилась БЕЗ прерывания
            if llm_task.done() and not was_interrupted:
                # Проверяем еще раз буфер (могло прийти сообщение в последний момент)
                current_buffer = await message_buffer.peek_buffered_messages(message.chat.id)
                if len(current_buffer) == len(messages):
                    # Все хорошо, используем полученный ответ
                    llm_response, user = await llm_task

                    if llm_response is None:
                        await message.answer(
                            "Прости, твое сообщение вызвало у меня ошибку(( "
                            "Пожалуйста попробуй снова"
                        )
                        # Очищаем буфер и завершаем обработку
                        await message_buffer.clear_buffer(message.chat.id)
                        await message_buffer.finish_processing(message.chat.id)
                        return

                    # Сохраняем в контекст и форматируем
                    converted_response = await save_to_context_and_format(
                        message.chat.id, user, combined_text, llm_response
                    )

                    # Отправляем ответ пользователю (с разбивкой на части если нужно)
                    start = 0
                    while start < len(converted_response):
                        chunk = converted_response[start : start + 4096]
                        try:
                            generated_message = await message.answer(
                                chunk, parse_mode=ParseMode.MARKDOWN_V2
                            )
                            await forward_to_debug(message.chat.id, generated_message.message_id)
                        except TelegramForbiddenError:
                            user.remind_of_yourself = 0
                            await user.update_in_db()
                            logger.warning(f"USER{message.chat.id} заблокировал чатбота")
                            return
                        except Exception as e:
                            # Пробуем отправить без форматирования
                            try:
                                generated_message = await message.answer(chunk)
                                await forward_to_debug(
                                    message.chat.id, generated_message.message_id
                                )
                            except Exception:
                                pass
                            logger.error(f"LLM{message.chat.id} - {e}", exc_info=True)

                        start += 4096

                    logger.info(f"LLM{message.chat.id} - {converted_response}")

                    # ТОЛЬКО СЕЙЧАС очищаем буфер после успешной обработки
                    await message_buffer.clear_buffer(message.chat.id)
                else:
                    # Пришли новые сообщения в последний момент
                    logger.info(
                        f"USER{message.chat.id} получен ответ от LLM, "
                        f"но игнорируем его из-за новых сообщений "
                        f"(было {len(messages)}, стало {len(current_buffer)})"
                    )
                    # НЕ очищаем буфер, НЕ сохраняем в контекст, продолжаем цикл
            elif was_interrupted:
                # Прерывание - не очищаем буфер, в нем остались все сообщения
                logger.debug(f"USER{message.chat.id} буфер НЕ очищен из-за прерывания")

            # Проверяем, есть ли еще сообщения для обработки
            has_more = await message_buffer.finish_processing(message.chat.id)
            if not has_more:
                # Буфер пуст, завершаем обработку
                break

            # Если есть еще сообщения, продолжаем цикл while True

    finally:
        typing_task.cancel()


@dp.message(F.photo)
async def handle_photo_message(message: types.Message):
    """Обработка фотографий через vision модель."""
    # Игнорируем сообщения из ADMIN_CHAT
    if message.chat.id == ADMIN_CHAT:
        return

    # В групповых чатах отвечаем только на упоминания
    if not await should_respond_in_chat(message):
        logger.debug(f"CHAT{message.chat.id}: фото без упоминания бота, игнорируем")
        return

    logger.info(f"USER{message.chat.id} отправил изображение")
    await forward_to_debug(message.chat.id, message.message_id)

    # Обновляем имя пользователя в базе данных (если изменилось)
    user_obj = User(message.chat.id)
    await user_obj.get_from_db()
    if message.from_user:
        new_name = (
            message.from_user.first_name
            if message.from_user.first_name
            else (
                message.from_user.username
                if message.from_user.username
                else "Not_of_registration"
            )
        )
        if user_obj.name != new_name and new_name != "Not_of_registration":
            user_obj.name = new_name
            await user_obj.update_in_db()
            logger.debug(f"USER{message.chat.id} имя обновлено: {new_name}")

    # Запускаем индикатор печати
    typing_task = asyncio.create_task(keep_typing(message.chat.id))

    try:
        # Получаем самое большое фото (последнее в списке)
        photo = message.photo[-1]

        # Скачиваем файл
        file = await bot.get_file(photo.file_id)
        image_bytes = await bot.download_file(file.file_path)

        # Определяем MIME-тип (Telegram обычно отправляет в JPEG)
        image_mime_type = "image/jpeg"

        # Обрабатываем изображение через vision модель и LLM
        converted_response = await process_user_image(
            message.chat.id, image_bytes.read(), image_mime_type
        )

        if converted_response is None:
            await message.answer(
                "Прости, твое изображение вызвало у меня ошибку(( "
                "Пожалуйста попробуй снова"
            )
            return

        # Отправляем ответ пользователю (с разбивкой на части если нужно)
        start = 0
        while start < len(converted_response):
            chunk = converted_response[start : start + 4096]
            try:
                generated_message = await message.answer(
                    chunk, parse_mode=ParseMode.MARKDOWN_V2
                )
                await forward_to_debug(message.chat.id, generated_message.message_id)
            except TelegramForbiddenError:
                user = User(message.chat.id)
                await user.get_from_db()
                user.remind_of_yourself = 0
                await user.update_in_db()
                logger.warning(f"USER{message.chat.id} заблокировал чатбота")
                return
            except Exception as e:
                # Пробуем отправить без форматирования
                try:
                    generated_message = await message.answer(chunk)
                    await forward_to_debug(
                        message.chat.id, generated_message.message_id
                    )
                except Exception:
                    pass
                logger.error(f"LLM{message.chat.id} - {e}", exc_info=True)

            start += 4096

        logger.info(f"LLM{message.chat.id} - {converted_response}")

    finally:
        typing_task.cancel()


@dp.message(F.video | F.video_note)
async def handle_video_message(message: types.Message):
    """Обработка видео и кружочков через vision модель."""
    # Игнорируем сообщения из ADMIN_CHAT
    if message.chat.id == ADMIN_CHAT:
        return

    # В групповых чатах отвечаем только на упоминания
    if not await should_respond_in_chat(message):
        logger.debug(f"CHAT{message.chat.id}: видео без упоминания бота, игнорируем")
        return

    logger.info(f"USER{message.chat.id} отправил видео (тип: {message.content_type})")

    # Пересылаем в чат админов
    await forward_to_debug(message.chat.id, message.message_id)

    # Обновляем имя пользователя в базе данных (если изменилось)
    user_obj = User(message.chat.id)
    await user_obj.get_from_db()
    if message.from_user:
        new_name = (
            message.from_user.first_name
            if message.from_user.first_name
            else (
                message.from_user.username
                if message.from_user.username
                else "Not_of_registration"
            )
        )
        if user_obj.name != new_name and new_name != "Not_of_registration":
            user_obj.name = new_name
            await user_obj.update_in_db()
            logger.debug(f"USER{message.chat.id} имя обновлено: {new_name}")

    # Запускаем индикатор печати
    typing_task = asyncio.create_task(keep_typing(message.chat.id))

    try:
        # Получаем видео (для video_note используем video_note, для video - video)
        video = message.video_note if message.video_note else message.video

        if not video:
            logger.error(f"USER{message.chat.id} - не удалось получить видео объект")
            await message.answer(
                "Прости, не удалось обработать твоё видео. Попробуй ещё раз."
            )
            return

        # Скачиваем файл
        file = await bot.get_file(video.file_id)
        video_bytes = await bot.download_file(file.file_path)

        # Получаем длительность видео (если доступна)
        video_duration = getattr(video, "duration", None)

        # Обрабатываем видео через vision модель и LLM
        converted_response = await process_user_video(
            message.chat.id, video_bytes.read(), video_duration
        )

        if converted_response is None:
            await message.answer(
                "Прости, твоё видео вызвало у меня ошибку(( "
                "Пожалуйста попробуй снова"
            )
            return

        # Отправляем ответ пользователю (с разбивкой на части если нужно)
        start = 0
        while start < len(converted_response):
            chunk = converted_response[start : start + 4096]
            try:
                generated_message = await message.answer(
                    chunk, parse_mode=ParseMode.MARKDOWN_V2
                )
                await forward_to_debug(message.chat.id, generated_message.message_id)
            except TelegramForbiddenError:
                user = User(message.chat.id)
                await user.get_from_db()
                user.remind_of_yourself = 0
                await user.update_in_db()
                logger.warning(f"USER{message.chat.id} заблокировал чатбота")
                return
            except Exception as e:
                # Пробуем отправить без форматирования
                try:
                    generated_message = await message.answer(chunk)
                    await forward_to_debug(
                        message.chat.id, generated_message.message_id
                    )
                except Exception:
                    pass
                logger.error(f"LLM{message.chat.id} - {e}", exc_info=True)

            start += 4096

        logger.info(f"LLM{message.chat.id} - {converted_response}")

    finally:
        typing_task.cancel()


@dp.message(F.sticker)
async def handle_sticker_message(message: types.Message):
    """Обработка стикеров."""
    # Игнорируем сообщения из ADMIN_CHAT
    if message.chat.id == ADMIN_CHAT:
        return

    # В групповых чатах отвечаем только на упоминания
    if not await should_respond_in_chat(message):
        logger.debug(f"CHAT{message.chat.id}: стикер без упоминания бота, игнорируем")
        return

    logger.info(f"USER{message.chat.id} отправил стикер, не обрабатываем")
    await message.answer(
        "Извини, я пока не умею обрабатывать стикеры. Отправь мне текстовое сообщение или фотографию."
    )


@dp.message(F.voice | F.audio)
async def handle_voice_message(message: types.Message):
    """Обработка голосовых сообщений и аудио."""
    # Игнорируем сообщения из ADMIN_CHAT
    if message.chat.id == ADMIN_CHAT:
        return

    # В групповых чатах отвечаем только на упоминания
    if not await should_respond_in_chat(message):
        logger.debug(f"CHAT{message.chat.id}: аудио без упоминания бота, игнорируем")
        return

    logger.info(
        f"USER{message.chat.id} отправил аудио (тип: {message.content_type}), не обрабатываем"
    )
    await message.answer(
        "Извини, я пока не умею обрабатывать голосовые сообщения и аудио. "
        "Отправь мне текстовое сообщение или фотографию."
    )


@dp.message(F.animation)
async def handle_animation_message(message: types.Message):
    """Обработка GIF-анимаций."""
    # Игнорируем сообщения из ADMIN_CHAT
    if message.chat.id == ADMIN_CHAT:
        return

    # В групповых чатах отвечаем только на упоминания
    if not await should_respond_in_chat(message):
        logger.debug(f"CHAT{message.chat.id}: GIF без упоминания бота, игнорируем")
        return

    logger.info(f"USER{message.chat.id} отправил GIF, не обрабатываем")
    await message.answer(MESSAGES["unknown_message"])


@dp.message(F.document)
async def handle_document_message(message: types.Message):
    """Обработка документов и файлов."""
    # Игнорируем сообщения из ADMIN_CHAT
    if message.chat.id == ADMIN_CHAT:
        return

    # В групповых чатах отвечаем только на упоминания
    if not await should_respond_in_chat(message):
        logger.debug(f"CHAT{message.chat.id}: документ без упоминания бота, игнорируем")
        return

    logger.info(f"USER{message.chat.id} отправил документ, не обрабатываем")
    await message.answer(MESSAGES["unknown_message"])


@dp.message()
async def unknown_message(message: types.Message):
    """Обработка неизвестных типов сообщений."""
    # Игнорируем сообщения из ADMIN_CHAT
    if message.chat.id == ADMIN_CHAT:
        logger.debug(f"Игнорируем сообщение из ADMIN_CHAT: {message.text}")
        return

    # В групповых чатах отвечаем только на упоминания
    if not await should_respond_in_chat(message):
        logger.debug(
            f"CHAT{message.chat.id}: неизвестный тип ({message.content_type}) "
            f"без упоминания бота, игнорируем"
        )
        return

    logger.warning(
        f"Unknown message от {message.chat.id}, "
        f"тип: {message.content_type}, текст: {message.text}"
    )
    await message.answer(MESSAGES["unknown_message"])
