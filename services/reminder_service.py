"""
Сервис для отправки напоминаний пользователям.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import telegramify_markdown
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError

import database
from bot_instance import bot
from config import (
    DEBUG_CHAT,
    DEFAULT_PROMPT,
    DELAYED_REMINDERS_HOURS,
    DELAYED_REMINDERS_MINUTES,
    FROM_TIME,
    REMINDER_PROMPT,
    TIMEZONE_OFFSET,
    TO_TIME,
    logger,
)
from database import User
from services.llm_client import send_request_to_openrouter
from services.llm_service import log_prompt
from utils import forward_to_debug


async def send_reminder_to_user(user_id: int):
    """
    Отправляет напоминание конкретному пользователю.

    Args:
        user_id: ID пользователя
    """
    user = User(user_id)
    await user.get_from_db()

    # Очищаем дубликаты ассистента в истории
    if (
        user.prompt
        and len(user.prompt) >= 2
        and user.prompt[-2]["role"] == "assistant"
        and user.prompt[-1]["role"] == "assistant"
    ):
        user.prompt.pop()

    # Подготавливаем промпт для напоминания
    prompt_for_request = user.prompt.copy()
    current_date = datetime.now(timezone(timedelta(hours=3))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Формируем информацию об имени пользователя если она доступна
    username_replacement = ""
    if user.name and user.name != "Not_of_registration":
        username_replacement = f"6. Имя пользователя: {user.name}"

    # Заменяем плейсхолдеры в REMINDER_PROMPT
    reminder_content = REMINDER_PROMPT.replace("{CURRENTDATE}", current_date)
    reminder_content = reminder_content.replace("{USERNAME}", username_replacement)

    # Заменяем плейсхолдеры в DEFAULT_PROMPT
    default_content = DEFAULT_PROMPT.replace("{CURRENTDATE}", current_date)
    default_content = default_content.replace("{USERNAME}", username_replacement)

    prompt_for_request.append(
        {
            "role": "system",
            "content": reminder_content,
        }
    )
    prompt_for_request.insert(0, {"role": "system", "content": default_content})

    # Логируем промпт перед отправкой
    log_prompt(user_id, prompt_for_request, "REMINDER")

    # Запрашиваем ответ от LLM
    try:
        llm_msg = await send_request_to_openrouter(prompt_for_request)
    except Exception as e:
        await bot.send_message(DEBUG_CHAT, f"LLM{user_id} - Критическая ошибка: {e}")
        return

    if llm_msg is None or llm_msg.strip() == "":
        await bot.send_message(DEBUG_CHAT, f"LLM{user_id} - пустой ответ от LLM")
        return

    # Сохраняем ответ в историю
    await user.update_prompt("assistant", llm_msg)
    logger.debug(f"LLM_RAWOUTPUT{user_id}:{llm_msg}")

    # Конвертируем в Telegram Markdown
    converted = telegramify_markdown.markdownify(
        llm_msg,
        max_line_length=None,
        normalize_whitespace=False,
    )

    # Отправляем сообщение пользователю
    try:
        start = 0
        while start < len(converted):
            chunk = converted[start : start + 4096]
            try:
                generated_message = await bot.send_message(
                    chat_id=user_id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                await forward_to_debug(user_id, generated_message.message_id)
            except TelegramForbiddenError:
                user.remind_of_yourself = 0
                await user.update_in_db()
                await bot.send_message(
                    DEBUG_CHAT, f"USER{user_id} заблокировал чатбота"
                )
                return
            except Exception as e:
                # Пробуем отправить без форматирования
                try:
                    generated_message = await bot.send_message(
                        chat_id=user_id,
                        text=chunk,
                    )
                    await forward_to_debug(user_id, generated_message.message_id)
                except Exception:
                    pass
                await bot.send_message(DEBUG_CHAT, f"LLM{user_id} - {e}")
                logger.error(f"LLM{user_id} - {e}")

            start += 4096

        # Обновляем время следующего напоминания
        user.remind_of_yourself = await database.time_after(
            DELAYED_REMINDERS_HOURS,
            DELAYED_REMINDERS_MINUTES,
            TIMEZONE_OFFSET,
            FROM_TIME,
            TO_TIME,
        )
        await user.update_in_db()

        logger.info(f"LLM{user_id}REMINDER - {generated_message.text}")

    except Exception as e:
        logger.error(f"Ошибка при отправке напоминания пользователю {user_id}: {e}")


async def check_and_send_reminders():
    """
    Проверяет пользователей, которым нужно отправить напоминание,
    и отправляет им напоминания.
    """
    user_ids = await database.get_past_dates()

    for user_id in user_ids:
        try:
            await send_reminder_to_user(user_id)
        except Exception as e:
            logger.error(f"Ошибка при обработке напоминания для {user_id}: {e}")


async def reminder_loop():
    """
    Бесконечный цикл для периодической проверки и отправки напоминаний.
    """
    while True:
        try:
            await check_and_send_reminders()
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            print("Цикл напоминаний остановлен")
            break
        except Exception as e:
            logger.error(f"Ошибка в цикле напоминаний: {e}")
            await asyncio.sleep(30)
