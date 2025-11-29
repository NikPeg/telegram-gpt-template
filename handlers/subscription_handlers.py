"""
Обработчики для проверки подписки на спонсорские каналы.
"""

from datetime import datetime, timedelta, timezone

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot_instance import bot, dp
from config import MESSAGES, REQUIRED_CHANNELS, TIMEZONE_OFFSET, logger
from database import ChatVerification, User
from services.subscription_service import is_user_subscribed_to_all
from utils import is_private_chat


def get_subscription_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру с кнопками для подписки на каналы.
    """
    buttons = []

    # Добавляем кнопки со ссылками на каналы
    for channel in REQUIRED_CHANNELS:
        if channel.startswith("@"):
            channel_name = channel[1:]
            button = InlineKeyboardButton(
                text=f"📢 {channel_name}",
                url=f"https://t.me/{channel_name}"
            )
            buttons.append([button])

    # Добавляем кнопку "Я подписался"
    check_button = InlineKeyboardButton(
        text=MESSAGES["btn_check_subscription"],
        callback_data="check_subscription"
    )
    buttons.append([check_button])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_subscription_request(chat_id: int, message_id: int = None, is_chat: bool = False):
    """
    Отправляет сообщение с просьбой подписаться на каналы.

    Args:
        chat_id: ID чата
        message_id: ID сообщения для ответа (опционально)
        is_chat: True если это групповой чат, False если ЛС
    """
    # Выбираем правильное сообщение в зависимости от типа чата
    message_text = MESSAGES["msg_subscription_required_chat"] if is_chat else MESSAGES["msg_subscription_required"]
    keyboard = get_subscription_keyboard()

    if message_id:
        await bot.send_message(
            chat_id=chat_id,
            text=message_text,
            reply_to_message_id=message_id,
            reply_markup=keyboard
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=message_text,
            reply_markup=keyboard
        )


@dp.callback_query(lambda c: c.data == "check_subscription")
async def process_subscription_check(callback_query: types.CallbackQuery):
    """
    Обработчик нажатия на кнопку "Я подписался".
    Проверяет подписку пользователя на все обязательные каналы.
    Для групповых чатов: сохраняет верификацию чата.
    Для личных чатов: обновляет subscription_verified пользователя.
    """
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    is_chat = not is_private_chat(callback_query.message)

    logger.info(f"USER{user_id}: запрос проверки подписки ({'чат' if is_chat else 'ЛС'})")

    # Показываем индикатор загрузки
    await callback_query.answer("Проверяю подписку...", show_alert=False)

    try:
        # Проверяем подписку
        is_subscribed = await is_user_subscribed_to_all(bot, user_id)

        if is_subscribed:
            # Пользователь подписан на все каналы
            logger.info(f"USER{user_id}: подписка подтверждена")

            if is_chat:
                # === ГРУППОВОЙ ЧАТ ===
                # Создаем/обновляем запись о верификации чата
                current_time = datetime.now(timezone(timedelta(hours=TIMEZONE_OFFSET)))
                timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")

                # Получаем имя пользователя
                user_name = callback_query.from_user.first_name or callback_query.from_user.username or "Неизвестный"

                chat_verification = ChatVerification(
                    chat_id=chat_id,
                    verified_by_user_id=user_id,
                    verified_at=timestamp,
                    user_name=user_name
                )
                await chat_verification.save_to_db()

                # Удаляем сообщение с просьбой подписаться
                await callback_query.message.delete()

                # Отправляем подтверждение В ЧАТ
                await bot.send_message(
                    chat_id=chat_id,
                    text=MESSAGES["msg_subscription_verified_chat"].format(user_name=user_name)
                )

                logger.info(f"CHAT{chat_id}: верифицирован пользователем {user_name} (ID: {user_id})")
            else:
                # === ЛИЧНЫЙ ЧАТ ===
                # Обновляем статус в БД
                user = User(user_id)
                await user.get_from_db()
                user.subscription_verified = 1
                await user.update_in_db()

                # Удаляем сообщение с просьбой подписаться
                await callback_query.message.delete()

                # Отправляем подтверждение в ЛС
                await bot.send_message(
                    chat_id=user_id,
                    text=MESSAGES["msg_subscription_verified"]
                )

        else:
            # Пользователь еще не подписан на все каналы
            logger.info(f"USER{user_id}: подписка не подтверждена")

            # Показываем уведомление
            error_message = MESSAGES["msg_subscription_check_failed"]

            await callback_query.answer(
                "❌ Вы еще не подписаны на все каналы",
                show_alert=True
            )

            # Обновляем сообщение
            await callback_query.message.edit_text(
                text=error_message,
                reply_markup=get_subscription_keyboard()
            )

    except Exception as e:
        logger.error(f"Ошибка при проверке подписки USER{user_id}: {e}", exc_info=True)
        await callback_query.answer(
            "⚠️ Произошла ошибка при проверке подписки. Попробуйте позже.",
            show_alert=True
        )

