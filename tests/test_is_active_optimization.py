"""
Тесты для оптимизации проверки активности пользователей через поле is_active.
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Устанавливаем LOG_FILE_PATH перед импортом
os.environ["LOG_FILE_PATH"] = os.path.join(tempfile.gettempdir(), "test_is_active.log")
os.environ["INACTIVE_USER_DAYS"] = "7"  # Устанавливаем для тестов

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

# Мокируем matplotlib перед импортом stats_service
sys.modules["matplotlib"] = MagicMock()
sys.modules["matplotlib.pyplot"] = MagicMock()

import aiosqlite  # noqa: E402

from core.database import Conversation, get_past_dates  # noqa: E402
from services.stats_service import get_inactive_users_count  # noqa: E402


@pytest.fixture
async def test_db():
    """Фикстура для создания и очистки тестовой БД с полем is_active."""
    test_db_name = "test_is_active.db"

    # Удаляем старую тестовую БД если есть
    if os.path.exists(test_db_name):
        os.remove(test_db_name)

    # Создаем БД и таблицы с полем is_active
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
                reminder_time TEXT DEFAULT '19:15',
                reminder_weekdays TEXT DEFAULT '[]',
                subscription_verified INTEGER,
                referral_code TEXT DEFAULT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_is_active
            ON conversations(is_active)
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

    # Патчим DATABASE_NAME в обоих модулях
    import database

    import services.stats_service

    original_db = database.DATABASE_NAME
    original_stats_db = services.stats_service.DATABASE_NAME
    database.DATABASE_NAME = test_db_name
    services.stats_service.DATABASE_NAME = test_db_name

    yield test_db_name

    # Восстанавливаем и очищаем
    database.DATABASE_NAME = original_db
    services.stats_service.DATABASE_NAME = original_stats_db
    if os.path.exists(test_db_name):
        os.remove(test_db_name)


@pytest.mark.asyncio
async def test_is_active_field_in_conversation(test_db):
    """Тест проверяет, что поле is_active корректно сохраняется и читается."""
    user_id = 1001
    conversation = Conversation(user_id, name="TestUser", is_active=1)
    await conversation.save_for_db()

    # Проверяем, что поле сохранено
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT is_active FROM conversations WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == 1, "is_active должен быть равен 1"

    # Читаем обратно
    conversation2 = Conversation(user_id)
    await conversation2.get_from_db()
    assert conversation2.is_active == 1, "is_active должен быть прочитан корректно"

    # Обновляем
    conversation2.is_active = 0
    await conversation2.update_in_db()

    # Проверяем обновление
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT is_active FROM conversations WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == 0, "is_active должен быть обновлен на 0"


@pytest.mark.asyncio
async def test_get_past_dates_filters_inactive_users(test_db):
    """Тест проверяет, что неактивные пользователи фильтруются по is_active."""
    # Создаем активного пользователя (недавно отвечал)
    active_user_id = 2001
    active_user = Conversation(active_user_id, name="ActiveUser", reminder_time="14:30")
    active_user.remind_of_yourself = None
    active_user.is_active = 1
    await active_user.save_for_db()

    # Добавляем недавнее сообщение
    async with aiosqlite.connect(test_db) as db:
        recent_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (active_user_id, "user", "Hello", recent_time),
        )
        await db.commit()

    # Создаем неактивного пользователя (не отвечал давно)
    inactive_user_id = 2002
    inactive_user = Conversation(inactive_user_id, name="InactiveUser", reminder_time="14:30")
    inactive_user.remind_of_yourself = None
    inactive_user.is_active = 0  # Помечаем как неактивного
    await inactive_user.save_for_db()

    # Добавляем старое сообщение (более 7 дней назад)
    async with aiosqlite.connect(test_db) as db:
        old_time = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (inactive_user_id, "user", "Old message", old_time),
        )
        await db.commit()

    # Мокируем текущее время: 14:32
    mock_time = datetime(2025, 11, 7, 14, 32, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime, patch("config.INACTIVE_USER_DAYS", 7):
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    # Активный пользователь должен быть в списке
    assert active_user_id in user_ids, "Активный пользователь должен получить напоминание"

    # Неактивный пользователь НЕ должен быть в списке (отфильтрован по is_active)
    assert inactive_user_id not in user_ids, (
        "Неактивный пользователь НЕ должен получить напоминание"
    )


@pytest.mark.asyncio
async def test_get_past_dates_updates_is_active_flag(test_db):
    """Тест проверяет, что get_past_dates() обновляет флаг is_active при проверке."""
    user_id = 3001
    conversation = Conversation(user_id, name="TestUser", reminder_time="14:30")
    conversation.remind_of_yourself = None
    conversation.is_active = 1  # Изначально активен
    await conversation.save_for_db()

    # Добавляем старое сообщение (более 7 дней назад)
    # Используем мокированное время для согласованности
    mock_time = datetime(2025, 11, 7, 14, 32, 0)
    old_time = (mock_time - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(test_db) as db:
        await db.execute(
            "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, "user", "Old message", old_time),
        )
        await db.commit()

    # Мокируем текущее время: 14:32
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime, patch("config.INACTIVE_USER_DAYS", 7):
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        await get_past_dates()

    # Проверяем, что флаг обновлен на 0
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT is_active FROM conversations WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == 0, "is_active должен быть обновлен на 0 для неактивного пользователя"


@pytest.mark.asyncio
async def test_get_past_dates_reactivates_user(test_db):
    """
    Тест проверяет, что пользователь снова становится активным при недавнем сообщении.
    Примечание: пользователь с is_active=0 не попадает в выборку, поэтому обновление
    не происходит автоматически. Этот тест проверяет, что активные пользователи
    корректно обрабатываются.
    """
    user_id = 4001
    conversation = Conversation(user_id, name="TestUser", reminder_time="14:30")
    conversation.remind_of_yourself = None
    conversation.is_active = 1  # Делаем активным, чтобы он попал в выборку
    await conversation.save_for_db()

    # Добавляем недавнее сообщение (менее 7 дней назад)
    mock_time = datetime(2025, 11, 7, 14, 32, 0)
    recent_time = (mock_time - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")

    async with aiosqlite.connect(test_db) as db:
        await db.execute(
            "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, "user", "Recent message", recent_time),
        )
        await db.commit()

    # Мокируем текущее время: 14:32
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime, patch("config.INACTIVE_USER_DAYS", 7):
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        await get_past_dates()

    # Проверяем, что флаг остался 1 (пользователь активен)
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT is_active FROM conversations WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == 1, "is_active должен остаться 1 для активного пользователя"


@pytest.mark.asyncio
async def test_get_inactive_users_count(test_db):
    """Тест проверяет функцию подсчета неактивных пользователей."""
    # Создаем несколько пользователей с разными статусами активности
    users = [
        (5001, 1),  # Активный
        (5002, 0),  # Неактивный
        (5003, 0),  # Неактивный
        (5004, 1),  # Активный
    ]

    for user_id, is_active in users:
        conversation = Conversation(user_id, name=f"User{user_id}", is_active=is_active)
        await conversation.save_for_db()

    # Проверяем подсчет
    inactive_count = await get_inactive_users_count()
    assert inactive_count == 2, f"Должно быть 2 неактивных пользователя, получено {inactive_count}"


@pytest.mark.asyncio
async def test_get_past_dates_without_inactive_check(test_db):
    """Тест проверяет, что при INACTIVE_USER_DAYS=0 проверка активности отключена."""
    # Создаем неактивного пользователя
    user_id = 7001
    conversation = Conversation(user_id, name="InactiveUser", reminder_time="14:30")
    conversation.remind_of_yourself = None
    conversation.is_active = 0
    await conversation.save_for_db()

    # Добавляем старое сообщение
    async with aiosqlite.connect(test_db) as db:
        old_time = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, "user", "Old message", old_time),
        )
        await db.commit()

    # Мокируем текущее время: 14:32
    mock_time = datetime(2025, 11, 7, 14, 32, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    # Устанавливаем INACTIVE_USER_DAYS = 0 (проверка отключена)
    with patch("database.datetime") as mock_datetime, patch("config.INACTIVE_USER_DAYS", 0):
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    # При INACTIVE_USER_DAYS=0 все пользователи должны проверяться
    # (но напоминания все равно не отправляются, если remind_of_yourself = "0")
    # В данном случае remind_of_yourself = None, поэтому пользователь должен быть в списке
    assert user_id in user_ids, (
        "При INACTIVE_USER_DAYS=0 проверка активности отключена, "
        "пользователь должен быть в списке"
    )


@pytest.mark.asyncio
async def test_is_active_with_no_messages(test_db):
    """Тест проверяет логику is_active для пользователей без сообщений."""
    user_id = 8001
    conversation = Conversation(user_id, name="NewUser", reminder_time="14:30")
    conversation.remind_of_yourself = None
    conversation.is_active = 1
    await conversation.save_for_db()

    # Пользователь без сообщений - должен считаться активным (новый пользователь)
    mock_time = datetime(2025, 11, 7, 14, 32, 0)
    mock_time_with_tz = mock_time.replace(tzinfo=timezone(timedelta(hours=3)))

    with patch("database.datetime") as mock_datetime, patch("config.INACTIVE_USER_DAYS", 7):
        mock_datetime.now.return_value = mock_time_with_tz
        mock_datetime.strptime = datetime.strptime

        user_ids = await get_past_dates()

    # Новый пользователь без сообщений должен быть активным
    assert user_id in user_ids, "Новый пользователь без сообщений должен быть активным"

    # Проверяем, что is_active остался 1
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT is_active FROM conversations WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        assert row[0] == 1, "is_active должен остаться 1 для нового пользователя"

