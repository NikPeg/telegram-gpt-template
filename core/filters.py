"""
Пользовательские фильтры для обработки сообщений.
"""

from datetime import UTC, datetime, timedelta

from aiogram import types
from aiogram.filters import Filter

import core.database as database
from core.config import ADMIN_CHAT, FULL_LEVEL, logger


class UserNotInDB(Filter):
    """Фильтр для проверки, что пользователь не зарегистрирован в БД."""

    async def __call__(self, message: types.Message) -> bool:
        user_id = message.chat.id
        return not await database.user_exists(user_id)


class UserIsAdmin(Filter):
    """Фильтр для проверки, является ли пользователь администратором."""

    async def __call__(self, message: types.Message) -> bool:
        # Проверяем, что сообщение из ADMIN чата
        is_admin = message.chat.id == ADMIN_CHAT
        logger.log(
            FULL_LEVEL,
            f"UserIsAdmin проверка для {message.chat.id}: {is_admin} "
            f"(ADMIN_CHAT={ADMIN_CHAT})",
        )
        return is_admin


class OldMessage(Filter):
    """Фильтр для отсеивания старых сообщений (старше 1 минуты)."""

    async def __call__(self, message: types.Message) -> bool:
        now = datetime.now(tz=UTC)
        message_time = message.date.replace(tzinfo=UTC)
        time_difference = now - message_time
        return time_difference >= timedelta(minutes=1)

