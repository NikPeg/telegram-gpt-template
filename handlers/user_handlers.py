"""
Обработчики пользовательских команд.
"""

from aiogram import F, types
from aiogram.filters.command import Command
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from core.bot_instance import bot, dp
from core.config import ADMIN_CHAT, MESSAGES, REQUIRED_CHANNELS, logger
from core.database import Conversation, delete_chat_data
from core.filters import OldMessage, UserNotInDB
from core.utils import forward_to_debug
from handlers.subscription_handlers import send_subscription_request


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

        # Создаем запись чата в БД, чтобы обработчик registration не сработал
        chat_conversation = Conversation(chat_id, chat_title)
        await chat_conversation.save_for_db()
        logger.info(f"CHAT{chat_id}: запись создана в БД")

        # Отправляем приветственное сообщение
        welcome_text = MESSAGES["msg_bot_added_to_chat"].format(
            chat_title=chat_title, bot_username=bot_info.username
        )

        await message.answer(welcome_text)

        # Если есть обязательные каналы, отправляем запрос на подписку
        if REQUIRED_CHANNELS:
            logger.info(f"CHAT{chat_id}: bot_added_to_chat отправляет запрос подписки")
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
            logger.error(
                f"CHAT{chat_id}: ошибка при удалении данных - {e}", exc_info=True
            )


@dp.message(UserNotInDB())
async def registration(message: types.Message):
    """Регистрация нового пользователя."""
    chat_id = message.chat.id
    logger.info(
        f"{'CHAT' if chat_id < 0 else 'USER'}{chat_id}: регистрация нового пользователя/чата"
    )

    # Извлекаем реферальный код только из команды /start
    referral_code = None
    if message.text and message.text.startswith("/start"):
        args = message.text.split()
        if len(args) > 1:
            referral_code = args[1]
            logger.info(
                f"{'CHAT' if chat_id < 0 else 'USER'}{chat_id}: переход по реф.ссылке, код: {referral_code}"
            )

    # Определяем имя в зависимости от типа чата
    if chat_id < 0:
        # Для групповых чатов используем название чата
        user_name = message.chat.title or ""
    else:
        # Для личных чатов используем имя пользователя
        user = message.from_user
        user_name = (
            user.first_name
            if user and user.first_name
            else (user.username if user and user.username else "")
        )

    conversation = Conversation(int(message.chat.id), user_name, referral_code=referral_code)
    await conversation.save_for_db()
    builder = ReplyKeyboardBuilder()

    sent_msg = await message.answer(
        MESSAGES["msg_start"], reply_markup=builder.as_markup()
    )

    # Если есть обязательные каналы, показываем сообщение о подписке
    if REQUIRED_CHANNELS and message.chat.id != ADMIN_CHAT:
        logger.info(
            f"{'CHAT' if chat_id < 0 else 'USER'}{chat_id}: регистрация отправляет запрос подписки"
        )
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
        conversation = Conversation(message.chat.id)
        await conversation.get_from_db()

        # Если пользователь не подписан (0) или подписка не проверялась (None), показываем сообщение
        if conversation.subscription_verified != 1:
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
        logger.info(
            f"Сообщение /help успешно отправлено пользователю {message.chat.id}"
        )
    except Exception as e:
        # Если не получилось, пробуем без форматирования
        logger.error(
            f"Ошибка при отправке /help для USER{message.chat.id}: {e}", exc_info=True
        )
        try:
            sent_msg = await message.answer(
                help_message, reply_markup=ReplyKeyboardRemove()
            )
            logger.info(
                f"Сообщение /help отправлено без форматирования пользователю {message.chat.id}"
            )
        except Exception as e2:
            logger.error(
                f"Критическая ошибка при отправке /help для USER{message.chat.id}: {e2}",
                exc_info=True,
            )
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
    conversation = Conversation(message.chat.id)
    await conversation.get_from_db()
    conversation.remind_of_yourself = "0"
    conversation.active_messages_count = 0  # Не передавать сообщения в контекст
    await conversation.update_in_db()

    # Не пересылаем сообщения из админ-чата в админ-чат
    if message.chat.id != ADMIN_CHAT:
        await forward_to_debug(message.chat.id, message.message_id)
        await forward_to_debug(message.chat.id, sent_msg.message_id)
