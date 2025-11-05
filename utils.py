"""
Вспомогательные утилиты.
"""

import asyncio
import contextlib

from bot_instance import bot
from config import DEBUG_CHAT


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
    # Игнорируем ошибки пересылки (например, если бот заблокирован в DEBUG_CHAT)
    with contextlib.suppress(Exception):
        # Отправляем метку с USER ID перед пересылкой
        await bot.send_message(DEBUG_CHAT, f"USER{message_chat_id}")
        # Пересылаем сообщение
        await bot.forward_message(
            chat_id=DEBUG_CHAT, from_chat_id=message_chat_id, message_id=message_id
        )
