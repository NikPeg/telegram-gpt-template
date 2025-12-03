"""
Сервис для работы с LLM.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import cv2
import telegramify_markdown

from config import (
    DEFAULT_PROMPT,
    FULL_LEVEL,
    logger,
)
from database import Conversation
from services.llm_client import send_image_to_vision_model, send_request_to_openrouter


def log_prompt(chat_id: int, prompt: list[dict], prompt_type: str = "MESSAGE"):
    """
    Логирует промпт с разными уровнями детализации.

    Args:
        chat_id: ID чата пользователя
        prompt: Список сообщений промпта
        prompt_type: Тип промпта (MESSAGE или REMINDER)
    """
    # Системные промпты без истории (DEBUG уровень)
    system_prompts = [msg for msg in prompt if msg.get("role") == "system"]
    logger.debug(
        f"PROMPT_SYSTEM_{prompt_type}{chat_id}: {json.dumps(system_prompts, ensure_ascii=False)}"
    )

    # Полный промпт со всей историей (FULL уровень)
    logger.log(
        FULL_LEVEL,
        f"PROMPT_FULL_{prompt_type}{chat_id}: {json.dumps(prompt, ensure_ascii=False, indent=2)}",
    )


async def get_llm_response(
    chat_id: int, message_text: str
) -> tuple[str | None, Conversation]:
    """
    Получает ответ от LLM БЕЗ сохранения в контекст.

    Эта функция НЕ сохраняет диалог в базу данных. Используйте save_to_context_and_format()
    для сохранения результата после подтверждения, что ответ нужен пользователю.

    Args:
        chat_id: ID чата пользователя
        message_text: Текст сообщения

    Returns:
        (ответ от LLM, объект пользователя) или (None, объект пользователя) при ошибке
    """
    conversation = Conversation(chat_id)
    await conversation.get_from_db()

    # ВАЖНО: Получаем контекст ДО сохранения текущего сообщения
    # Чтобы текущее сообщение не попало в контекст дважды
    context_messages = await conversation.get_context_for_llm()

    # Формируем системный промпт с подстановкой данных
    current_date = datetime.now(timezone(timedelta(hours=3))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    system_content = DEFAULT_PROMPT.replace("{CURRENTDATE}", current_date)

    # Добавляем имя пользователя/чата если оно известно
    if conversation.name:
        username_info = f"6. Имя собеседника: {conversation.name}"
        system_content = system_content.replace("{USERNAME}", username_info)
    else:
        system_content = system_content.replace("{USERNAME}", "")

    # Формируем финальный промпт: системный промпт ПЕРВЫМ, затем история сообщений
    prompt_for_request = [
        {
            "role": "system",
            "content": system_content,
        }
    ]

    # Добавляем сообщения из истории (убираем timestamp, он не нужен для LLM API)
    for msg in context_messages:
        prompt_for_request.append({"role": msg["role"], "content": msg["content"]})

    # Добавляем текущее сообщение пользователя в промпт
    prompt_for_request.append({"role": "user", "content": message_text})

    # Логируем промпт перед отправкой
    log_prompt(chat_id, prompt_for_request, "MESSAGE")

    # Запрашиваем ответ от LLM
    try:
        llm_msg = await send_request_to_openrouter(prompt_for_request)
    except Exception as e:
        logger.error(f"LLM{chat_id} - Критическая ошибка: {e}", exc_info=True)
        return None, conversation

    if llm_msg is None or llm_msg.strip() == "":
        logger.error(f"LLM{chat_id} - пустой ответ от LLM")
        return None, conversation

    logger.debug(f"LLM_RAWOUTPUT{chat_id}:{llm_msg}")

    return llm_msg, conversation


async def save_to_context_and_format(
    chat_id: int, conversation: Conversation, user_message: str, llm_response: str
) -> str:
    """
    Сохраняет диалог в контекст и форматирует ответ для Telegram.

    Вызывайте эту функцию ТОЛЬКО если уверены, что ответ будет показан пользователю.

    Args:
        chat_id: ID чата пользователя
        conversation: Объект беседы
        user_message: Исходное сообщение пользователя
        llm_response: Ответ от LLM

    Returns:
        Отформатированный ответ для Telegram
    """
    # Сохраняем сообщение пользователя и ответ в историю
    await conversation.update_prompt("user", user_message)
    await conversation.update_prompt("assistant", llm_response)

    # Конвертируем в Telegram Markdown
    converted = telegramify_markdown.markdownify(
        llm_response,
        max_line_length=None,
        normalize_whitespace=False,
    )

    # Увеличиваем счетчик активных сообщений (если он используется)
    # +2 потому что добавили пару: user message + assistant message
    if conversation.active_messages_count is not None:
        conversation.active_messages_count += 2
        logger.debug(
            f"USER{chat_id} active_messages_count увеличен до {conversation.active_messages_count}"
        )

    # remind_of_yourself обновляется только при отправке напоминания (в reminder_service.py)
    await conversation.update_in_db()

    return converted


async def process_user_message(chat_id: int, message_text: str) -> str | None:
    """
    Обрабатывает сообщение пользователя через LLM.

    УСТАРЕВШАЯ функция для обратной совместимости.
    Для новой логики с буфером используйте get_llm_response() + save_to_context_and_format().

    Args:
        chat_id: ID чата пользователя
        message_text: Текст сообщения

    Returns:
        Отформатированный ответ от LLM или None при ошибке
    """
    llm_response, user = await get_llm_response(chat_id, message_text)

    if llm_response is None:
        return None

    return await save_to_context_and_format(chat_id, user, message_text, llm_response)


async def process_user_image(
    chat_id: int, image_bytes: bytes, image_mime_type: str = "image/jpeg"
) -> str | None:
    """
    Обрабатывает изображение от пользователя через vision модель и отправляет описание в LLM.

    Args:
        chat_id: ID чата пользователя
        image_bytes: Байты изображения
        image_mime_type: MIME-тип изображения

    Returns:
        Отформатированный ответ от LLM или None при ошибке
    """
    logger.info(f"USER{chat_id}TOLLM: [ИЗОБРАЖЕНИЕ]")

    # Шаг 1: Получаем описание изображения от vision модели
    try:
        image_description = await send_image_to_vision_model(
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
        )
    except Exception as e:
        logger.error(f"VISION{chat_id} - Критическая ошибка: {e}", exc_info=True)
        return None

    if image_description is None or image_description.strip() == "":
        logger.error(f"VISION{chat_id} - пустой ответ от vision модели")
        return None

    logger.info(f"VISION{chat_id} - описание получено: {image_description}")

    # Шаг 2: Отправляем описание в основную LLM от лица пользователя
    # Формируем сообщение как будто пользователь описал картинку
    message_text = f"[Пользователь отправил изображение. Описание изображения: {image_description}]"

    # Используем существующую функцию для обработки текстового сообщения
    return await process_user_message(chat_id, message_text)


async def process_user_video(
    chat_id: int, video_bytes: bytes, video_duration: int | None = None
) -> str | None:
    """
    Обрабатывает видео от пользователя через vision модель и отправляет описание в LLM.

    Извлекает 3 кадра (первый, средний, последний), отправляет их в VISION_MODEL,
    затем отправляет описания в MODEL для получения общего описания процесса на видео.

    Args:
        chat_id: ID чата пользователя
        video_bytes: Байты видео
        video_duration: Длительность видео в секундах (опционально)

    Returns:
        Отформатированный ответ от LLM или None при ошибке
    """
    logger.info(f"USER{chat_id}TOLLM: [ВИДЕО]")

    # Создаем временный файл для видео
    temp_video_path = None
    try:
        # Сохраняем видео во временный файл
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_video:
            temp_video.write(video_bytes)
            temp_video_path = temp_video.name

        logger.debug(
            f"VIDEO{chat_id} - видео сохранено во временный файл: {temp_video_path}"
        )

        # Открываем видео через OpenCV
        cap = cv2.VideoCapture(temp_video_path)

        if not cap.isOpened():
            logger.error(f"VIDEO{chat_id} - не удалось открыть видео файл")
            return None

        # Получаем информацию о видео
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)

        if total_frames == 0:
            logger.error(f"VIDEO{chat_id} - видео не содержит кадров")
            cap.release()
            return None

        # Вычисляем длительность если не передана
        if video_duration is None and fps > 0:
            video_duration = int(total_frames / fps)

        logger.info(
            f"VIDEO{chat_id} - всего кадров: {total_frames}, "
            f"FPS: {fps}, длительность: {video_duration}с"
        )

        # Определяем индексы кадров: первый, средний, последний
        frame_indices = [
            0,  # первый кадр
            total_frames // 2,  # средний кадр
            total_frames - 1,  # последний кадр
        ]

        frames = []

        # Извлекаем кадры
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()

            if ret:
                # Конвертируем кадр в JPEG
                _, buffer = cv2.imencode(".jpg", frame)
                frames.append(buffer.tobytes())
                logger.debug(f"VIDEO{chat_id} - извлечен кадр #{idx}")
            else:
                logger.warning(f"VIDEO{chat_id} - не удалось извлечь кадр #{idx}")

        cap.release()

        if len(frames) == 0:
            logger.error(f"VIDEO{chat_id} - не удалось извлечь ни одного кадра")
            return None

        logger.info(f"VIDEO{chat_id} - извлечено {len(frames)} кадров")

        # Отправляем каждый кадр в vision модель
        frame_descriptions = []
        frame_labels = ["начало видео", "середина видео", "конец видео"]

        for i, frame_bytes in enumerate(frames):
            try:
                description = await send_image_to_vision_model(
                    image_bytes=frame_bytes,
                    image_mime_type="image/jpeg",
                    prompt=f"Опиши подробно этот кадр из видео ({frame_labels[i]}) на русском языке. "
                    f"Что происходит, какие объекты, люди, действия, детали.",
                )

                if description and description.strip():
                    frame_descriptions.append(
                        f"{frame_labels[i].capitalize()}: {description}"
                    )
                    logger.debug(
                        f"VISION{chat_id} - описание кадра {i + 1}: {description[:100]}..."
                    )
                else:
                    logger.warning(
                        f"VISION{chat_id} - пустое описание для кадра {i + 1}"
                    )

            except Exception as e:
                logger.error(
                    f"VISION{chat_id} - ошибка обработки кадра {i + 1}: {e}",
                    exc_info=True,
                )

        if len(frame_descriptions) == 0:
            logger.error(
                f"VISION{chat_id} - не удалось получить описание ни одного кадра"
            )
            return None

        # Формируем общее описание видео
        duration_text = f" длиной {video_duration} секунд" if video_duration else ""
        combined_description = "\n\n".join(frame_descriptions)

        # Отправляем описания кадров в основную LLM для анализа процесса
        conversation = Conversation(chat_id)
        await conversation.get_from_db()

        context_messages = await conversation.get_context_for_llm()

        current_date = datetime.now(timezone(timedelta(hours=3))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        system_content = DEFAULT_PROMPT.replace("{CURRENTDATE}", current_date)

        # Добавляем имя пользователя/чата если оно известно
        if conversation.name:
            username_info = f"6. Имя собеседника: {conversation.name}"
            system_content = system_content.replace("{USERNAME}", username_info)
        else:
            system_content = system_content.replace("{USERNAME}", "")

        prompt_for_request = [
            {
                "role": "system",
                "content": system_content,
            }
        ]

        for msg in context_messages:
            prompt_for_request.append({"role": msg["role"], "content": msg["content"]})

        # Формируем запрос к MODEL для анализа процесса на видео
        video_analysis_prompt = (
            f"[Пользователь отправил видео{duration_text}. "
            f"Вот описания трёх ключевых кадров из этого видео:\n\n"
            f"{combined_description}\n\n"
            f"На основе этих кадров опиши процесс, который происходит на видео. "
            f"Что делает человек/объект, как развивается действие от начала к концу.]"
        )

        prompt_for_request.append({"role": "user", "content": video_analysis_prompt})

        log_prompt(chat_id, prompt_for_request, "VIDEO")

        # Запрашиваем ответ от LLM
        try:
            llm_msg = await send_request_to_openrouter(prompt_for_request)
        except Exception as e:
            logger.error(
                f"LLM{chat_id} - Критическая ошибка при обработке видео: {e}",
                exc_info=True,
            )
            return None

        if llm_msg is None or llm_msg.strip() == "":
            logger.error(f"LLM{chat_id} - пустой ответ от LLM при обработке видео")
            return None

        # Сохраняем в историю как сообщение от пользователя и ответ бота
        # Сохраняем исходный промпт с описаниями кадров
        await conversation.update_prompt("user", video_analysis_prompt)
        await conversation.update_prompt("assistant", llm_msg)
        logger.debug(f"LLM_RAWOUTPUT{chat_id}:{llm_msg}")

        # Конвертируем в Telegram Markdown
        converted = telegramify_markdown.markdownify(
            llm_msg,
            max_line_length=None,
            normalize_whitespace=False,
        )

        # Увеличиваем счетчик активных сообщений
        if conversation.active_messages_count is not None:
            conversation.active_messages_count += 2
            logger.debug(
                f"USER{chat_id} active_messages_count увеличен до {conversation.active_messages_count}"
            )

        await conversation.update_in_db()

        return converted

    except Exception as e:
        logger.error(
            f"VIDEO{chat_id} - критическая ошибка обработки видео: {e}", exc_info=True
        )
        return None

    finally:
        # Удаляем временный файл
        if temp_video_path and os.path.exists(temp_video_path):
            try:
                os.unlink(temp_video_path)
                logger.debug(
                    f"VIDEO{chat_id} - временный файл удален: {temp_video_path}"
                )
            except Exception as e:
                logger.warning(
                    f"VIDEO{chat_id} - не удалось удалить временный файл: {e}"
                )
