"""
Тесты для проверки системы напоминаний.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Устанавливаем LOG_FILE_PATH перед импортом, чтобы избежать создания /app/logs
os.environ["LOG_FILE_PATH"] = os.path.join(tempfile.gettempdir(), "test_reminders.log")

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiosqlite

from database import Conversation, get_past_dates


@pytest.fixture
async def test_db():
    """Фикстура для создания и очистки тестовой БД."""
    test_db_name = "test_reminders.db"

    # Удаляем старую тестовую БД если есть
    if os.path.exists(test_db_name):
        os.remove(test_db_name)

    # Создаем БД и таблицы
    async with aiosqlite.connect(test_db_name) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY,
                name TEXT,
                prompt JSON,
                remind_of_yourself TEXT,
                sub_lvl INTEGER,
                sub_id TEXT,
                sub_period INTEGER,
                is_admin INTEGER,
                active_messages_count INTEGER,
                reminder_times TEXT,
                subscription_verified INTEGER,
                referral_code TEXT DEFAULT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)

        await db.commit()

    # Патчим DATABASE_NAME
    import database

    original_db = database.DATABASE_NAME
    database.DATABASE_NAME = test_db_name

    yield test_db_name

    # Восстанавливаем и очищаем
    database.DATABASE_NAME = original_db
    if os.path.exists(test_db_name):
        os.remove(test_db_name)


@pytest.mark.asyncio
async def test_reminders_at_correct_time(test_db):
    """
    Тест проверяет, что напоминание отправляется в правильное время.
    """
    # Создаем пользователя с временем напоминания 14:30
    user_id = 11111
    conversation = Conversation(user_id, name="TestUser", reminder_times=["14:30"])
    conversation.remind_of_yourself = None  # Еще не получал напоминаний
    await conversation.save_for_db()

    # Мокируем текущее время: 14:32 (попадает в окно 14:30 ± 15 минут)
    mock_time = datetime(2025, 11, 7, 14, 32, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    assert user_id in user_ids, "Пользователь должен быть в списке для отправки"


@pytest.mark.asyncio
async def test_reminders_outside_time_window(test_db):
    """
    Тест проверяет, что напоминание НЕ отправляется вне временного окна.
    """
    # Создаем пользователя с временем напоминания 14:30
    user_id = 22222
    conversation = Conversation(user_id, name="TestUser2", reminder_times=["14:30"])
    conversation.remind_of_yourself = None
    await conversation.save_for_db()

    # Мокируем текущее время: 15:00 (не попадает в окно 14:30-14:45)
    mock_time = datetime(2025, 11, 7, 15, 0, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    assert user_id not in user_ids, (
        "Пользователь НЕ должен быть в списке (время не подходит)"
    )


@pytest.mark.asyncio
async def test_reminders_disabled_users(test_db):
    """
    Тест проверяет, что пользователи с отключенными напоминаниями не получают их.
    """
    # Создаем пользователя с отключенными напоминаниями
    user_id = 33333
    conversation = Conversation(user_id, name="TestUser3", reminder_times=["14:30"])
    conversation.remind_of_yourself = "0"  # Напоминания отключены
    await conversation.save_for_db()

    # Мокируем текущее время: 14:32 (попадает в окно)
    mock_time = datetime(2025, 11, 7, 14, 32, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    assert user_id not in user_ids, (
        "Пользователь с отключенными напоминаниями НЕ должен быть в списке"
    )


@pytest.mark.asyncio
async def test_reminders_recently_sent(test_db):
    """
    Тест проверяет, что напоминание не отправляется повторно,
    если прошло менее часа с последнего.
    """
    # Создаем пользователя с временем напоминания 14:30
    user_id = 44444
    conversation = Conversation(user_id, name="TestUser4", reminder_times=["14:30"])

    # Последнее напоминание было 30 минут назад
    last_reminder = datetime(2025, 11, 7, 14, 2, 0)
    conversation.remind_of_yourself = last_reminder.strftime("%Y-%m-%d %H:%M:%S")
    await conversation.save_for_db()

    # Текущее время: 14:32 (прошло только 30 минут)
    mock_time = datetime(2025, 11, 7, 14, 32, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    assert user_id not in user_ids, (
        "Пользователь НЕ должен получить напоминание (прошло менее часа)"
    )


@pytest.mark.asyncio
async def test_reminders_after_one_hour(test_db):
    """
    Тест проверяет, что напоминание отправляется,
    если прошло больше часа с последнего.
    """
    # Создаем пользователя с временем напоминания 14:30
    user_id = 55555
    conversation = Conversation(user_id, name="TestUser5", reminder_times=["14:30"])

    # Последнее напоминание было 2 часа назад
    last_reminder = datetime(2025, 11, 7, 12, 30, 0)
    conversation.remind_of_yourself = last_reminder.strftime("%Y-%m-%d %H:%M:%S")
    await conversation.save_for_db()

    # Текущее время: 14:32 (прошло 2 часа)
    mock_time = datetime(2025, 11, 7, 14, 32, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    assert user_id in user_ids, (
        "Пользователь должен получить напоминание (прошло больше часа)"
    )


@pytest.mark.asyncio
async def test_reminders_multiple_times(test_db):
    """
    Тест проверяет работу с несколькими временами напоминаний.
    """
    # Создаем пользователя с несколькими временами
    user_id = 66666
    conversation = Conversation(
        user_id, name="TestUser6", reminder_times=["09:00", "14:30", "19:15"]
    )
    conversation.remind_of_yourself = None
    await conversation.save_for_db()

    # Текущее время: 14:32 (попадает в окно второго времени)
    mock_time = datetime(2025, 11, 7, 14, 32, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    assert user_id in user_ids, (
        "Пользователь должен быть в списке (подходит второе время)"
    )


@pytest.mark.asyncio
async def test_reminders_null_vs_disabled(test_db):
    """
    Тест проверяет разницу между NULL (никогда не отправлялось)
    и "0" (отключено).
    """
    # Пользователь 1: NULL - еще не получал
    user1_id = 77777
    user1 = Conversation(user1_id, name="UserNull", reminder_times=["14:30"])
    user1.remind_of_yourself = None
    await user1.save_for_db()

    # Пользователь 2: "0" - отключены напоминания
    user2_id = 88888
    user2 = Conversation(user2_id, name="UserDisabled", reminder_times=["14:30"])
    user2.remind_of_yourself = "0"
    await user2.save_for_db()

    # Текущее время: 14:32
    mock_time = datetime(2025, 11, 7, 14, 32, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    assert user1_id in user_ids, "Пользователь с NULL должен получить напоминание"
    assert user2_id not in user_ids, "Пользователь с '0' НЕ должен получить напоминание"


@pytest.mark.asyncio
async def test_reminders_default_time(test_db):
    """
    Тест проверяет работу с дефолтным временем напоминания (19:15).
    """
    # Создаем пользователя без указания reminder_times (должно быть ["19:15"])
    user_id = 99999
    conversation = Conversation(user_id, name="TestUserDefault")
    conversation.remind_of_yourself = None
    await conversation.save_for_db()

    # Проверяем, что в БД сохранилось дефолтное время
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT reminder_times FROM conversations WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        reminder_times = json.loads(row[0]) if row[0] else ["19:15"]
        assert reminder_times == ["19:15"], "Дефолтное время должно быть 19:15"

    # Текущее время: 19:17 (попадает в окно)
    mock_time = datetime(2025, 11, 7, 19, 17, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    assert user_id in user_ids, (
        "Пользователь с дефолтным временем должен получить напоминание"
    )


@pytest.mark.asyncio
async def test_reminders_edge_of_time_window(test_db):
    """
    Тест проверяет граничные случаи временного окна (0 и 14 минут).
    """
    # Создаем двух пользователей
    user1_id = 100001
    user1 = Conversation(user1_id, name="EdgeStart", reminder_times=["14:30"])
    user1.remind_of_yourself = None
    await user1.save_for_db()

    user2_id = 100002
    user2 = Conversation(user2_id, name="EdgeEnd", reminder_times=["14:30"])
    user2.remind_of_yourself = None
    await user2.save_for_db()

    # Тест 1: Ровно в 14:30 (разница = 0 минут) - должно сработать
    mock_time = datetime(2025, 11, 7, 14, 30, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    assert user1_id in user_ids, "В 14:30 (разница=0) должно сработать"

    # Тест 2: В 14:44 (разница = 14 минут) - должно сработать
    mock_time = datetime(2025, 11, 7, 14, 44, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    assert user2_id in user_ids, "В 14:44 (разница=14) должно сработать"

    # Тест 3: В 14:45 (разница = 15 минут) - НЕ должно сработать
    user3_id = 100003
    user3 = Conversation(user3_id, name="OutOfWindow", reminder_times=["14:30"])
    user3.remind_of_yourself = None
    await user3.save_for_db()

    mock_time = datetime(2025, 11, 7, 14, 45, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime:
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    assert user3_id not in user_ids, "В 14:45 (разница=15) НЕ должно сработать"
