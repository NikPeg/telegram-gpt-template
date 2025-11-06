"""
Обработчики текстовых сообщений.
"""

import asyncio

from aiogram import F, types
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError

from bot_instance import dp
from config import ADMIN_CHAT, MESSAGES, logger
from database import User
from services.llm_service import process_user_message
from utils import forward_to_debug, keep_typing


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_message(message: types.Message):
    """Обработка текстовых сообщений через LLM (исключая команды)."""
    # Игнорируем сообщения из ADMIN_CHAT - не обрабатываем их через LLM
    if message.chat.id == ADMIN_CHAT:
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

    # Запускаем индикатор печати
    typing_task = asyncio.create_task(keep_typing(message.chat.id))

    try:
        # Обрабатываем сообщение через LLM
        converted_response = await process_user_message(message.chat.id, message.text)

        if converted_response is None:
            await message.answer(
                "Прости, твое сообщение вызвало у меня ошибку(( "
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


@dp.message()
async def unknown_message(message: types.Message):
    """Обработка неизвестных типов сообщений."""
    # Игнорируем сообщения из ADMIN_CHAT
    if message.chat.id == ADMIN_CHAT:
        logger.debug(f"Игнорируем сообщение из ADMIN_CHAT: {message.text}")
        return

    logger.warning(
        f"Unknown message от {message.chat.id}, "
        f"тип: {message.content_type}, текст: {message.text}"
    )
    await message.answer(MESSAGES["unknown_message"])
