"""
Обработчики пользовательских команд.
"""

from aiogram import types
from aiogram.filters.command import Command
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from bot_instance import dp
from config import ADMIN_CHAT, MESSAGES, logger
from database import User
from filters import OldMessage, UserNotInDB
from utils import forward_to_debug


@dp.message(OldMessage())
async def spam(message: types.Message):
    """Игнорирует старые сообщения (старше 1 минуты)."""


@dp.message(UserNotInDB())
async def registration(message: types.Message):
    """Регистрация нового пользователя."""
    args = message.text.split()

    if len(args) > 1:
        referral_code = args[1]
        logger.info(f"Переход по реф.ссылке, код: {referral_code}")

    user = message.from_user
    # Используем имя пользователя (first_name), если нет - username, если и его нет - placeholder
    user_name = (
        user.first_name
        if user and user.first_name
        else (user.username if user and user.username else "Not_of_registration")
    )

    user = User(int(message.chat.id), user_name)
    await user.save_for_db()
    builder = ReplyKeyboardBuilder()

    sent_msg = await message.answer(
        MESSAGES["msg_start"], reply_markup=builder.as_markup()
    )
    await forward_to_debug(message.chat.id, message.message_id)
    await forward_to_debug(message.chat.id, sent_msg.message_id)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start - приветствие."""
    sent_msg = await message.answer(
        MESSAGES["msg_start"], reply_markup=ReplyKeyboardRemove()
    )
    await forward_to_debug(message.chat.id, message.message_id)
    await forward_to_debug(message.chat.id, sent_msg.message_id)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Команда /help - справка (обычная или админская)."""
    # Проверяем, является ли пользователь администратором
    is_admin = message.chat.id == ADMIN_CHAT

    # Выбираем соответствующее сообщение
    help_message = MESSAGES["msg_help_admin"] if is_admin else MESSAGES["msg_help"]

    sent_msg = await message.answer(
        help_message, reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown"
    )
    await forward_to_debug(message.chat.id, message.message_id)
    await forward_to_debug(message.chat.id, sent_msg.message_id)


@dp.message(Command("forget"))
async def cmd_forget(message: types.Message):
    """
    Команда /forget - сброс контекста диалога.
    Сообщения сохраняются в БД для статистики, но не передаются в LLM.
    """
    sent_msg = await message.answer(
        MESSAGES["msg_forget"], reply_markup=ReplyKeyboardRemove()
    )
    user = User(message.chat.id)
    await user.get_from_db()
    user.remind_of_yourself = "0"
    user.active_messages_count = 0  # Не передавать сообщения в контекст
    await user.update_in_db()

    await forward_to_debug(message.chat.id, message.message_id)
    await forward_to_debug(message.chat.id, sent_msg.message_id)


@dp.message(Command("mute"))
async def cmd_mute(message: types.Message):
    """Команда /mute - отключение напоминаний."""
    sent_msg = await message.answer(
        MESSAGES["msg_mute"], reply_markup=ReplyKeyboardRemove()
    )
    user = User(message.chat.id)
    await user.get_from_db()
    user.remind_of_yourself = "0"
    await user.update_in_db()

    await forward_to_debug(message.chat.id, message.message_id)
    await forward_to_debug(message.chat.id, sent_msg.message_id)
