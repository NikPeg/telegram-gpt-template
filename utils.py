"""
Вспомогательные утилиты.
"""

import asyncio

from aiogram.exceptions import TelegramMigrateToChat

from bot_instance import bot
from config import ADMIN_CHAT, logger


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

    Args:
        message_chat_id: ID чата с сообщением
        message_id: ID сообщения
    """
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
