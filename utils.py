"""
Вспомогательные утилиты.
"""

import asyncio

from aiogram import types
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramMigrateToChat

from bot_instance import bot
from config import ADMIN_CHAT, MESSAGES_LEVEL, logger


async def keep_typing(chat_id: int, duration: int = 30):
    """
    Периодически показывает статус "печатает..." для чат-бота.

    Args:
        chat_id: ID чата
        duration: Продолжительность в секундах (по умолчанию 30)
    """
    iterations = duration // 3
    for _ in range(iterations):
        await bot.send_chat_action(chat_id=chat_id, action="typing")
        await asyncio.sleep(3)


async def forward_to_debug(message_chat_id: int, message_id: int):
    """
    Пересылает сообщение в отладочный чат с меткой USER ID.
    Пересылка происходит только если TELEGRAM_LOG_LEVEL <= MESSAGES (25).

    Args:
        message_chat_id: ID чата с сообщением
        message_id: ID сообщения
    """
    # Проверяем уровень Telegram логирования
    telegram_level = getattr(logger, "_telegram_level", 100)

    # Пересылаем только если уровень <= MESSAGES (включая INFO, DEBUG, FULL)
    if telegram_level > MESSAGES_LEVEL:
        return

    try:
        # Отправляем метку с USER ID перед пересылкой
        await bot.send_message(ADMIN_CHAT, f"USER{message_chat_id}")
        # Пересылаем сообщение
        await bot.forward_message(
            chat_id=ADMIN_CHAT, from_chat_id=message_chat_id, message_id=message_id
        )
    except TelegramMigrateToChat as e:
        # Чат был преобразован в супергруппу
        new_chat_id = e.migrate_to_chat_id
        logger.warning(
            f"⚠️ ADMIN чат был преобразован в супергруппу!\n"
            f"Старый ID: {ADMIN_CHAT}\n"
            f"Новый ID: {new_chat_id}\n"
            f"❗ Обновите переменную ADMIN_CHAT в .env или GitHub Secrets"
        )
        # Пытаемся отправить в новый чат
        try:
            await bot.send_message(new_chat_id, f"USER{message_chat_id}")
            await bot.forward_message(
                chat_id=new_chat_id, from_chat_id=message_chat_id, message_id=message_id
            )
            logger.info(f"✅ Сообщение успешно отправлено в новый чат {new_chat_id}")
        except Exception as e2:
            logger.error(
                f"❌ Не удалось отправить сообщение в новый чат {new_chat_id}: {e2}"
            )
    except Exception as e:
        # Любые другие ошибки (бот не добавлен в чат, чат не существует и т.д.)
        logger.warning(
            f"⚠️ Не удалось переслать сообщение в ADMIN чат (ID: {ADMIN_CHAT}): {e}\n"
            f"Проверьте:\n"
            f"1. Бот добавлен в ADMIN чат\n"
            f"2. ADMIN_CHAT ID корректный\n"
            f"3. У бота есть права на отправку сообщений"
        )


def is_private_chat(message: types.Message) -> bool:
    """
    Проверяет, является ли сообщение из личного чата.

    Args:
        message: Сообщение от пользователя

    Returns:
        True если это личный чат, False если группа/супергруппа/канал
    """
    return message.chat.type == "private"


async def should_respond_in_chat(message: types.Message) -> bool:
    """
    Проверяет, должен ли бот ответить на сообщение в групповом чате.
    Бот отвечает только если:
    - Сообщение является ответом на сообщение бота
    - Бот упомянут в тексте через @username
    - Бот упомянут через entities (mention/text_mention)

    Args:
        message: Сообщение от пользователя

    Returns:
        True если бот должен ответить, False иначе
    """
    # Если это личный чат, всегда отвечаем
    if is_private_chat(message):
        return True

    # Получаем информацию о боте
    bot_info = await bot.get_me()
    bot_username = bot_info.username

    # Проверяем, является ли сообщение ответом на сообщение бота
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.is_bot
        and message.reply_to_message.from_user.id == bot_info.id
    ):
        return True

    # Проверяем упоминание бота в тексте
    if message.text and f"@{bot_username}" in message.text:
        return True

    # Проверяем упоминание через entities
    if message.entities:
        for entity in message.entities:
            if entity.type == "mention":
                # Извлекаем упомянутое имя
                mentioned = message.text[entity.offset : entity.offset + entity.length]
                if mentioned == f"@{bot_username}":
                    return True
            elif entity.type == "text_mention":
                # Прямое упоминание пользователя (может быть и ботом)
                if entity.user and entity.user.id == bot_info.id:
                    return True

    # Проверяем упоминание в caption (для фото/видео)
    if message.caption:
        if f"@{bot_username}" in message.caption:
            return True

        # Проверяем entities в caption
        if message.caption_entities:
            for entity in message.caption_entities:
                if entity.type == "mention":
                    mentioned = message.caption[
                        entity.offset : entity.offset + entity.length
                    ]
                    if mentioned == f"@{bot_username}":
                        return True
                elif entity.type == "text_mention":
                    if entity.user and entity.user.id == bot_info.id:
                        return True

    return False


async def send_message_with_fallback(
    chat_id: int, text: str, **kwargs
) -> types.Message:
    """
    Отправляет сообщение с MARKDOWN_V2 форматированием.
    Если возникает ошибка парсинга, отправляет тот же текст без форматирования
    (с видимыми экранирующими символами).

    Args:
        chat_id: ID чата для отправки
        text: Текст сообщения (уже сконвертированный через telegramify_markdown)
        **kwargs: Дополнительные параметры для send_message

    Returns:
        Отправленное сообщение

    Raises:
        Exception: Если не удалось отправить сообщение ни с одним вариантом
    """
    try:
        return await bot.send_message(
            chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN_V2, **kwargs
        )
    except Exception as e:
        # Пробуем отправить без форматирования (с видимым экранированием)
        try:
            logger.warning(
                f"CHAT{chat_id} - ошибка парсинга Markdown, "
                f"отправляем с экранированием: {e}"
            )
            # Убираем parse_mode из kwargs если он там есть
            kwargs.pop("parse_mode", None)
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception:
            # Если и это не сработало - пробрасываем исходную ошибку
            logger.error(f"CHAT{chat_id} - не удалось отправить сообщение: {e}")
            raise
