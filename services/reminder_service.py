"""
Сервис для отправки напоминаний пользователям.
"""

import asyncio
import random
from datetime import datetime, timedelta, timezone

import telegramify_markdown
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError

import database
from bot_instance import bot
from config import (
    DEFAULT_PROMPT,
    REMINDER_PROMPTS,
    TIMEZONE_OFFSET,
    logger,
)
from database import User, delete_chat_data
from services.llm_client import send_request_to_openrouter
from services.llm_service import log_prompt
from utils import forward_to_debug

# Названия дней недели на русском
WEEKDAY_NAMES = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}

# Пользовательские запросы для разных типов напоминаний
USER_PROMPTS_BY_TYPE = {
    "interests": "Привет! Спроси у меня, чем интересным я занимаюсь в последнее время",
    "situational": "Привет! Спроси у меня, как проходит мой день",
    "humor": "Привет! Расскажи мне что-нибудь забавное или интересное",
    "how_are_you": "Привет! Спроси у меня как у меня дела",
    "compliment": "Привет! Поддержи меня и скажи что-нибудь приятное",
    "plans": "Привет! Спроси у меня про мои планы",
}


async def send_reminder_to_user(user_id: int):
    """
    Отправляет напоминание конкретному пользователю.

    Args:
        user_id: ID пользователя
    """
    user = User(user_id)
    await user.get_from_db()

    # Подготавливаем контекст (только последние MAX_CONTEXT сообщений)
    context_messages = await user.get_context_for_llm()

    # Получаем текущую дату и день недели
    now_msk = datetime.now(timezone(timedelta(hours=TIMEZONE_OFFSET)))
    current_date = now_msk.strftime("%Y-%m-%d %H:%M:%S")
    weekday = WEEKDAY_NAMES[now_msk.weekday()]

    # Формируем информацию об имени пользователя если она доступна
    username_replacement = ""
    if user.name and user.name != "Not_of_registration":
        username_replacement = f"Имя пользователя: {user.name}"

    # Выбираем случайный тип напоминания
    reminder_type = random.choice(list(REMINDER_PROMPTS.keys()))
    reminder_prompt = REMINDER_PROMPTS[reminder_type]

    logger.info(f"USER{user_id} - Отправляю напоминание типа [{reminder_type.upper()}]")
    logger.debug(f"USER{user_id} - Выбран тип напоминания: {reminder_type}")

    # Заменяем плейсхолдеры в выбранном REMINDER_PROMPT
    reminder_content = reminder_prompt.replace("{CURRENTDATE}", current_date)
    reminder_content = reminder_content.replace("{WEEKDAY}", weekday)
    reminder_content = reminder_content.replace("{USERNAME}", username_replacement)

    # Заменяем плейсхолдеры в DEFAULT_PROMPT
    default_content = DEFAULT_PROMPT.replace("{CURRENTDATE}", current_date)
    default_content = default_content.replace("{USERNAME}", username_replacement)

    # Формируем финальный промпт: системные промпты ПЕРВЫМИ, затем история сообщений
    prompt_for_request = [
        {"role": "system", "content": default_content},
        {"role": "system", "content": reminder_content},
    ]

    # Добавляем сообщения из истории (убираем timestamp, он не нужен для LLM API)
    for msg in context_messages:
        prompt_for_request.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    # Добавляем явный user запрос, если нет сообщений в истории или последнее не от user
    # Это необходимо, чтобы модель понимала что нужно ответить
    if not context_messages or context_messages[-1]["role"] != "user":
        user_prompt = USER_PROMPTS_BY_TYPE.get(reminder_type, "Привет! Напомни мне о себе")
        prompt_for_request.append({
            "role": "user",
            "content": user_prompt
        })

    # Логируем промпт перед отправкой
    log_prompt(user_id, prompt_for_request, f"REMINDER_{reminder_type.upper()}")

    # Запрашиваем ответ от LLM
    try:
        llm_msg = await send_request_to_openrouter(prompt_for_request)
    except Exception as e:
        logger.error(f"LLM{user_id} - Критическая ошибка: {e}", exc_info=True)
        raise  # Выбрасываем исключение для корректного подсчета ошибок

    if llm_msg is None or llm_msg.strip() == "":
        logger.error(f"LLM{user_id} - пустой ответ от LLM")
        raise ValueError(f"Empty response from LLM for user {user_id}")

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
                # Проверяем, это чат или пользователь
                if user_id < 0:
                    # Это чат - удаляем все данные
                    logger.warning(f"CHAT{user_id} заблокировал бота или бот был удален из чата")
                    try:
                        await delete_chat_data(user_id)
                        logger.info(f"CHAT{user_id}: все данные удалены из БД")
                    except Exception as e:
                        logger.error(f"CHAT{user_id}: ошибка при удалении данных - {e}", exc_info=True)
                else:
                    # Это пользователь - отключаем напоминания
                    user.remind_of_yourself = 0
                    await user.update_in_db()
                    logger.warning(f"USER{user_id} заблокировал чатбота")
                raise  # Выбрасываем исключение для корректного подсчета
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
                logger.error(f"LLM{user_id} - {e}", exc_info=True)

            start += 4096

        # Сохраняем ответ в историю ПОСЛЕ успешной отправки
        await user.update_prompt("assistant", llm_msg)
        logger.debug(f"LLM_RAWOUTPUT{user_id}:{llm_msg}")

        # Обновляем время последнего напоминания (используется для предотвращения дублей)
        now_msk = datetime.now(timezone(timedelta(hours=TIMEZONE_OFFSET)))
        user.remind_of_yourself = now_msk.strftime("%Y-%m-%d %H:%M:%S")
        await user.update_in_db()

        logger.info(f"LLM{user_id}REMINDER[{reminder_type.upper()}] - {generated_message.text}")

    except Exception as e:
        logger.error(f"Ошибка при отправке напоминания пользователю {user_id}: {e}", exc_info=True)
        raise  # Выбрасываем исключение для корректного подсчета ошибок


async def check_and_send_reminders():
    """
    Проверяет пользователей, которым нужно отправить напоминание,
    и отправляет им напоминания.
    """
    logger.info("🔔 Начинаю проверку времен уведомлений...")

    user_ids = await database.get_past_dates()

    if not user_ids:
        logger.info("✅ Проверка завершена: никому не нужно отправлять уведомления")
        return

    logger.info(f"📨 Найдено пользователей для отправки напоминаний: {len(user_ids)}")

    success_count = 0
    error_count = 0

    for user_id in user_ids:
        try:
            await send_reminder_to_user(user_id)
            success_count += 1
        except Exception as e:
            error_count += 1
            logger.error(f"Ошибка при обработке напоминания для {user_id}: {e}")

    logger.info(f"✅ Проверка завершена: отправлено {success_count} напоминаний, ошибок: {error_count}")


async def reminder_loop():
    """
    Бесконечный цикл для периодической проверки и отправки напоминаний.
    """
    logger.info("🔄 Фоновая задача напоминаний запущена (интервал: 15 минут)")

    while True:
        try:
            await check_and_send_reminders()
            logger.info("⏳ Следующая проверка через 15 минут...")
            await asyncio.sleep(900)  # 15 минут = 900 секунд
        except asyncio.CancelledError:
            logger.info("🛑 Цикл напоминаний остановлен")
            break
        except Exception as e:
            logger.error(f"Ошибка в цикле напоминаний: {e}")
            await asyncio.sleep(900)  # 15 минут = 900 секунд
