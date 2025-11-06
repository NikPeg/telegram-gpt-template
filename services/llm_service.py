"""
Сервис для работы с LLM.
"""

import json
from datetime import datetime, timedelta, timezone

import telegramify_markdown

import database
from config import (
    DEFAULT_PROMPT,
    DELAYED_REMINDERS_HOURS,
    DELAYED_REMINDERS_MINUTES,
    FROM_TIME,
    FULL_LEVEL,
    TIMEZONE_OFFSET,
    TO_TIME,
    logger,
)
from database import User
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


async def process_user_message(chat_id: int, message_text: str) -> str | None:
    """
    Обрабатывает сообщение пользователя через LLM.

    Args:
        chat_id: ID чата пользователя
        message_text: Текст сообщения

    Returns:
        Отформатированный ответ от LLM или None при ошибке
    """
    user = User(chat_id)
    await user.get_from_db()

    # Добавляем сообщение пользователя в историю
    await user.update_prompt("user", message_text)

    # Подготавливаем промпт для запроса (только последние MAX_CONTEXT сообщений)
    context_messages = await user.get_context_for_llm()

    # Формируем системный промпт с подстановкой данных
    current_date = datetime.now(timezone(timedelta(hours=3))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    system_content = DEFAULT_PROMPT.replace("{CURRENTDATE}", current_date)

    # Добавляем имя пользователя если оно есть и не "Not_of_registration"
    if user.name and user.name != "Not_of_registration":
        username_info = f"6. Имя пользователя: {user.name}"
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
        prompt_for_request.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    # Логируем промпт перед отправкой
    log_prompt(chat_id, prompt_for_request, "MESSAGE")

    # Запрашиваем ответ от LLM
    try:
        llm_msg = await send_request_to_openrouter(prompt_for_request)
    except Exception as e:
        logger.error(f"LLM{chat_id} - Критическая ошибка: {e}", exc_info=True)
        return None

    if llm_msg is None or llm_msg.strip() == "":
        logger.error(f"LLM{chat_id} - пустой ответ от LLM")
        return None

    # Сохраняем ответ в историю
    await user.update_prompt("assistant", llm_msg)
    logger.debug(f"LLM_RAWOUTPUT{chat_id}:{llm_msg}")

    # Конвертируем в Telegram Markdown
    converted = telegramify_markdown.markdownify(
        llm_msg,
        max_line_length=None,
        normalize_whitespace=False,
    )

    # Обновляем время следующего напоминания
    user.remind_of_yourself = await database.time_after(
        DELAYED_REMINDERS_HOURS,
        DELAYED_REMINDERS_MINUTES,
        TIMEZONE_OFFSET,
        FROM_TIME,
        TO_TIME,
    )
    await user.update_in_db()

    return converted


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
