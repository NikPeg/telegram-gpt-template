"""
Обработчики пользовательских команд.
"""

from aiogram import F, types
from aiogram.filters.command import Command
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from bot_instance import bot, dp
from config import ADMIN_CHAT, MESSAGES, REQUIRED_CHANNELS, logger
from database import User, delete_chat_data
from filters import OldMessage, UserNotInDB
from handlers.subscription_handlers import send_subscription_request
from utils import forward_to_debug


@dp.message(OldMessage())
async def spam(message: types.Message):
    """Игнорирует старые сообщения (старше 1 минуты)."""


@dp.message(F.new_chat_members)
async def bot_added_to_chat(message: types.Message):
    """Обработчик добавления бота в групповой чат."""
    # Проверяем, что бот был добавлен в чат
    bot_info = await bot.get_me()
    bot_added = any(member.id == bot_info.id for member in message.new_chat_members)

    if bot_added:
        chat_id = message.chat.id
        chat_title = message.chat.title or "этот чат"
        logger.info(f"CHAT{chat_id}: бот добавлен в чат '{chat_title}'")

        # Отправляем приветственное сообщение
        welcome_text = (
            f"👋 Привет! Спасибо, что добавили меня в '{chat_title}'!\n\n"
            f"Я - Эдичка, твой супер-дружелюбный чатбот с искусственным интеллектом! 😃\n\n"
            f"✨ Что я умею:\n"
            f"• 💬 Поддерживаю живые беседы и запоминаю контекст\n"
            f"• 📸 Понимаю картинки\n"
            f"• 🎥 Смотрю видео\n"
            f"• 🎯 Всегда рад поболтать\n\n"
            f"Упомяните меня в сообщении (@{bot_info.username}) или ответьте на моё сообщение, "
            f"чтобы начать общение! 😊\n\n"
            f"Команды: /help"
        )

        await message.answer(welcome_text)

        # Если есть обязательные каналы, отправляем запрос на подписку
        if REQUIRED_CHANNELS:
            await send_subscription_request(chat_id, message.message_id, is_chat=True)


@dp.message(F.left_chat_member)
async def bot_removed_from_chat(message: types.Message):
    """Обработчик удаления бота из группового чата."""
    # Проверяем, что бот был удален из чата
    bot_info = await bot.get_me()
    bot_removed = message.left_chat_member.id == bot_info.id

    if bot_removed:
        chat_id = message.chat.id
        chat_title = message.chat.title or "чат"
        logger.info(f"CHAT{chat_id}: бот удален из чата '{chat_title}'")

        # Удаляем все данные чата из БД
        try:
            await delete_chat_data(chat_id)
            logger.info(f"CHAT{chat_id}: все данные успешно удалены")
        except Exception as e:
            logger.error(f"CHAT{chat_id}: ошибка при удалении данных - {e}", exc_info=True)


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

    # Если есть обязательные каналы, показываем сообщение о подписке
    if REQUIRED_CHANNELS and message.chat.id != ADMIN_CHAT:
        await send_subscription_request(message.chat.id)

    # Не пересылаем сообщения из админ-чата в админ-чат
    if message.chat.id != ADMIN_CHAT:
        await forward_to_debug(message.chat.id, message.message_id)
        await forward_to_debug(message.chat.id, sent_msg.message_id)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start - приветствие."""
    sent_msg = await message.answer(
        MESSAGES["msg_start"], reply_markup=ReplyKeyboardRemove()
    )

    # Проверяем статус подписки, если есть обязательные каналы
    if REQUIRED_CHANNELS and message.chat.id != ADMIN_CHAT:
        user = User(message.chat.id)
        await user.get_from_db()

        # Если пользователь не подписан (0) или подписка не проверялась (None), показываем сообщение
        if user.subscription_verified != 1:
            await send_subscription_request(message.chat.id)

    # Не пересылаем сообщения из админ-чата в админ-чат
    if message.chat.id != ADMIN_CHAT:
        await forward_to_debug(message.chat.id, message.message_id)
        await forward_to_debug(message.chat.id, sent_msg.message_id)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Команда /help - справка (обычная или админская)."""
    # Проверяем, является ли пользователь администратором
    is_admin = message.chat.id == ADMIN_CHAT

    # Логируем вызов команды
    if is_admin:
        logger.info(f"Команда /help получена от администратора {message.chat.id}")
    else:
        logger.debug(f"Команда /help получена от пользователя {message.chat.id}")

    # Выбираем соответствующее сообщение
    help_message = MESSAGES["msg_help_admin"] if is_admin else MESSAGES["msg_help"]

    try:
        # Для админа отправляем без Markdown (только эмодзи и структурированный текст)
        if is_admin:
            sent_msg = await message.answer(
                help_message, reply_markup=ReplyKeyboardRemove()
            )
        else:
            # Для обычных пользователей используем Markdown
            sent_msg = await message.answer(
                help_message, reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown"
            )
        logger.info(f"Сообщение /help успешно отправлено пользователю {message.chat.id}")
    except Exception as e:
        # Если не получилось, пробуем без форматирования
        logger.error(f"Ошибка при отправке /help для USER{message.chat.id}: {e}", exc_info=True)
        try:
            sent_msg = await message.answer(
                help_message, reply_markup=ReplyKeyboardRemove()
            )
            logger.info(f"Сообщение /help отправлено без форматирования пользователю {message.chat.id}")
        except Exception as e2:
            logger.error(f"Критическая ошибка при отправке /help для USER{message.chat.id}: {e2}", exc_info=True)
            return

    # Не пересылаем сообщения из админ-чата в админ-чат
    if not is_admin:
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

    # Не пересылаем сообщения из админ-чата в админ-чат
    if message.chat.id != ADMIN_CHAT:
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

    # Не пересылаем сообщения из админ-чата в админ-чат
    if message.chat.id != ADMIN_CHAT:
        await forward_to_debug(message.chat.id, message.message_id)
        await forward_to_debug(message.chat.id, sent_msg.message_id)
