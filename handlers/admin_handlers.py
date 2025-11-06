"""
Обработчики администраторских команд.
"""

import contextlib
import re

from aiogram import types
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, ReplyKeyboardRemove

from bot_instance import bot, dp
from config import DEBUG_CHAT, MESSAGES, logger
from database import User
from filters import UserIsAdmin
from services.stats_service import generate_user_stats
from states import AdminDispatch, AdminDispatchAll


@dp.message(AdminDispatch.input_text)
async def cmd_dispatch_input_text(message: types.Message, state: FSMContext):
    """Обработка ввода текста для отправки конкретному пользователю."""
    data = await state.get_data()
    user_id = data.get("id")

    try:
        await bot.send_message(int(user_id), text=message.text)
    except Exception as e:
        error_msg = f"LLM{message.chat.id} - ошибка при отправке {e}. Вы в главном меню"
        logger.error(error_msg, exc_info=True)

        with contextlib.suppress(Exception):
            await bot.send_message(DEBUG_CHAT, error_msg)

        await message.answer(error_msg)
        await state.clear()
        return

    await message.answer(MESSAGES["adminka_dispatch3"])
    await state.clear()


@dp.message(AdminDispatch.input_id)
async def cmd_dispatch_input_id(message: types.Message, state: FSMContext):
    """Обработка ввода ID пользователя для отправки сообщения."""
    user_input = message.text
    await state.update_data(id=user_input)
    await message.answer(MESSAGES["adminka_dispatch2"])
    await state.set_state(AdminDispatch.input_text)


@dp.message(UserIsAdmin(), Command("dispatch"))
async def cmd_dispatch(message: types.Message, state: FSMContext):
    """Команда /dispatch - отправка сообщения конкретному пользователю."""
    await message.answer(
        MESSAGES["adminka_dispatch1"], reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AdminDispatch.input_id)


@dp.message(AdminDispatchAll.input_text)
async def cmd_dispatch_all_input_text(message: types.Message, state: FSMContext):
    """Обработка ввода текста для массовой рассылки."""
    try:
        all_ids = await User.get_ids_from_table()
        success_dispatch = 0

        for user_id in all_ids:
            try:
                await bot.send_message(user_id, message.text)
                success_dispatch += 1
            except Exception:
                continue

        result_msg = f"Сообщение отправлено {success_dispatch} пользователям"
        logger.info(result_msg)

        with contextlib.suppress(Exception):
            await bot.send_message(DEBUG_CHAT, result_msg)

        await bot.send_message(message.chat.id, result_msg)

    except Exception as e:
        error_msg = f"USER{message.chat.id} - ошибка при отправке {e}. Вы в главном меню"
        logger.error(error_msg, exc_info=True)

        with contextlib.suppress(Exception):
            await bot.send_message(DEBUG_CHAT, error_msg)

        await message.answer(error_msg)
        await state.clear()
        return

    await message.answer(MESSAGES["adminka_dispatch3"])
    await state.clear()


@dp.message(UserIsAdmin(), Command("dispatch_all"))
async def cmd_dispatch_all(message: types.Message, state: FSMContext):
    """Команда /dispatch_all - массовая рассылка всем пользователям."""
    await message.answer(
        MESSAGES["adminka_dispatch_all"], reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AdminDispatchAll.input_text)


@dp.message(UserIsAdmin(), Command("stats"))
async def cmd_stats(message: types.Message):
    """Команда /stats - просмотр статистики пользователя или всех пользователей."""
    logger.info(f"Команда /stats получена от пользователя {message.chat.id}")
    user_id = None

    # Проверяем, является ли сообщение ответом на другое сообщение
    if message.reply_to_message and message.reply_to_message.text:
        # Пытаемся извлечь USER ID из текста сообщения
        replied_text = message.reply_to_message.text
        logger.debug(f"Проверяем replied_text: {replied_text}")
        match = re.search(r"USER(\d+)", replied_text)
        if match:
            user_id = int(match.group(1))
            logger.info(f"Извлечен user_id: {user_id}")

    # Отправляем сообщение о начале обработки
    if user_id:
        status_msg = await message.answer(
            f"⏳ Собираю статистику для пользователя USER{user_id}..."
        )
    else:
        status_msg = await message.answer(
            "⏳ Собираю статистику по всем пользователям..."
        )

    try:
        # Генерируем статистику
        hourly_graph, weekly_graph, total_messages, total_users = await generate_user_stats(user_id)

        if hourly_graph is None:
            await status_msg.edit_text(
                "❌ Нет данных для отображения статистики. "
                "Возможно, пользователь не отправлял сообщений."
            )
            return

        # Формируем текст с результатами
        if user_id:
            result_text = (
                f"📊 Статистика пользователя USER{user_id}\n"
                f"Всего сообщений: {total_messages}"
            )
        else:
            result_text = (
                f"📊 Общая статистика всех пользователей\n"
                f"Всего пользователей: {total_users}\n"
                f"Всего сообщений: {total_messages}"
            )

        # Отправляем текстовое сообщение
        await status_msg.edit_text(result_text)

        # Отправляем графики
        hourly_file = BufferedInputFile(
            hourly_graph.read(), filename="hourly_stats.png"
        )
        weekly_file = BufferedInputFile(
            weekly_graph.read(), filename="weekly_stats.png"
        )

        await message.answer_photo(
            hourly_file, caption="Средняя статистика по часам суток"
        )
        await message.answer_photo(
            weekly_file, caption="Средняя статистика по дням недели"
        )

    except Exception as e:
        error_msg = f"❌ Ошибка при генерации статистики: {e}"
        await status_msg.edit_text(error_msg)
        # Логируем ошибку
        logger.error(f"Ошибка в cmd_stats: {e}", exc_info=True)

        # Пытаемся отправить в DEBUG чат (с обработкой ошибок)
        try:
            await bot.send_message(DEBUG_CHAT, f"Ошибка в cmd_stats: {e}")
        except Exception as debug_error:
            logger.warning(f"Не удалось отправить ошибку в DEBUG чат: {debug_error}")
