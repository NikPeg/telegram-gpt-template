"""
Пользовательские фильтры для обработки сообщений.
"""

from datetime import UTC, datetime, timedelta

from aiogram import types
from aiogram.filters import Filter

import database
from config import ADMIN_LIST, DEBUG_CHAT
from database import User


class UserNotInDB(Filter):
    """Фильтр для проверки, что пользователь не зарегистрирован в БД."""

    async def __call__(self, message: types.Message) -> bool:
        user_id = message.chat.id
        return not await database.user_exists(user_id)


class UserHaveSubLevel(Filter):
    """Фильтр для проверки уровня подписки пользователя."""

    def __init__(self, required_sub_lvl: int):
        self.required_sub_lvl = required_sub_lvl

    async def __call__(self, message: types.Message) -> bool:
        user = User(message.chat.id)
        await user.get_from_db()

        if user:
            return user.sub_lvl >= self.required_sub_lvl
        return False


class UserIsAdmin(Filter):
    """Фильтр для проверки, является ли пользователь администратором."""

    async def __call__(self, message: types.Message) -> bool:
        # Проверяем, что сообщение либо из DEBUG чата, либо от админа
        return message.chat.id == DEBUG_CHAT or message.chat.id in ADMIN_LIST


class OldMessage(Filter):
    """Фильтр для отсеивания старых сообщений (старше 1 минуты)."""

    async def __call__(self, message: types.Message) -> bool:
        now = datetime.now(tz=UTC)
        message_time = message.date.replace(tzinfo=UTC)
        time_difference = now - message_time
        return time_difference >= timedelta(minutes=1)
