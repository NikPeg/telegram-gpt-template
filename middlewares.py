"""
Middleware для проверки различных условий перед обработкой сообщений.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message

from config import ADMIN_CHAT, REQUIRED_CHANNELS, logger
from database import ChatVerification, User, user_exists
from handlers.subscription_handlers import send_subscription_request
from utils import is_private_chat


class SubscriptionMiddleware(BaseMiddleware):
    """
    Middleware для проверки подписки пользователя на обязательные каналы.
    Если пользователь не подписан, показывает сообщение с просьбой подписаться.
    """

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any]
    ) -> Any:
        """
        Проверяет подписку перед обработкой сообщения.
        Для личных чатов: проверяет subscription_verified пользователя.
        Для групповых чатов: проверяет наличие записи в chat_verifications.

        Args:
            handler: Следующий обработчик в цепочке
            event: Сообщение от пользователя
            data: Дополнительные данные
        """
        # Пропускаем проверку для админ-чата
        if event.chat.id == ADMIN_CHAT:
            return await handler(event, data)

        # Пропускаем проверку если нет обязательных каналов
        if not REQUIRED_CHANNELS:
            return await handler(event, data)

        # Пропускаем проверку для callback_query (они обрабатываются отдельно)
        if not isinstance(event, Message):
            return await handler(event, data)

        # Пропускаем проверку для команд /start и /help
        # (пользователь должен иметь возможность понять, что делает бот)
        if event.text and event.text.startswith(("/start", "/help")):
            return await handler(event, data)

        # Пропускаем проверку для системных сообщений (добавление/удаление участников и т.д.)
        if event.new_chat_members or event.left_chat_member or event.new_chat_title or event.new_chat_photo:
            return await handler(event, data)

        # Различаем личные чаты и групповые
        if is_private_chat(event):
            # === ЛИЧНЫЙ ЧАТ ===
            # Проверяем, существует ли пользователь в БД
            user_id = event.from_user.id
            if not await user_exists(user_id):
                # Пользователь еще не зарегистрирован, пропускаем проверку
                # (регистрация покажет сообщение о подписке)
                return await handler(event, data)

            # Получаем пользователя из БД
            user = User(user_id)
            await user.get_from_db()

            # Проверяем статус подписки
            if user.subscription_verified == 0:
                # Пользователь не подписан
                logger.info(f"USER{user_id}: попытка использования бота без подписки (ЛС)")

                # Отправляем сообщение с просьбой подписаться
                await send_subscription_request(event.chat.id, event.message_id, is_chat=False)

                # Прерываем обработку
                return None

            # Если subscription_verified == 1 или NULL, продолжаем обработку
            return await handler(event, data)
        # === ГРУППОВОЙ ЧАТ ===
        chat_id = event.chat.id

        # Проверяем, верифицирован ли чат
        is_verified = await ChatVerification.is_chat_verified(chat_id)

        if not is_verified:
            # Чат не верифицирован
            logger.info(f"CHAT{chat_id}: попытка использования бота без верификации")

            # Отправляем сообщение с просьбой подписаться
            await send_subscription_request(chat_id, event.message_id, is_chat=True)

            # Прерываем обработку
            return None

        # Чат верифицирован, продолжаем обработку
        return await handler(event, data)

