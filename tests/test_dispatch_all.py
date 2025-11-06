"""
Тесты для проверки команды /dispatch_all и удаления заблокировавших бота пользователей.
"""

import os
import sys
from pathlib import Path

import pytest

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiosqlite
from aiogram.exceptions import TelegramForbiddenError

from database import User


@pytest.fixture
async def test_db():
    """Фикстура для создания и очистки тестовой БД."""
    test_db_name = "test_dispatch_all.db"

    # Удаляем старую тестовую БД если есть
    if os.path.exists(test_db_name):
        os.remove(test_db_name)

    # Создаем БД и таблицы
    async with aiosqlite.connect(test_db_name) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT,
                prompt JSON,
                remind_of_yourself TEXT,
                sub_lvl INTEGER,
                sub_id TEXT,
                sub_period INTEGER,
                is_admin INTEGER,
                active_messages_count INTEGER,
                reminder_times JSON
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

    # Патчим DATABASE_NAME и TABLE_NAME
    import database
    original_db = database.DATABASE_NAME
    original_table = database.TABLE_NAME
    database.DATABASE_NAME = test_db_name
    database.TABLE_NAME = "users"

    yield test_db_name

    # Восстанавливаем и очищаем
    database.DATABASE_NAME = original_db
    database.TABLE_NAME = original_table
    if os.path.exists(test_db_name):
        os.remove(test_db_name)


@pytest.mark.asyncio
async def test_delete_from_db(test_db):
    """
    Тест проверяет, что метод delete_from_db удаляет пользователя
    и все его сообщения из БД.
    """
    test_user_id = 11111

    # Создаем пользователя
    user = User(test_user_id, name="TestUser")
    await user.save_for_db()

    # Добавляем несколько сообщений
    await user.update_prompt("user", "Сообщение 1")
    await user.update_prompt("assistant", "Ответ 1")
    await user.update_prompt("user", "Сообщение 2")

    # Проверяем, что пользователь и сообщения есть в БД
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE id = ?",
            (test_user_id,)
        )
        user_count = (await cursor.fetchone())[0]
        assert user_count == 1, "Пользователь должен быть в БД"

        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ?",
            (test_user_id,)
        )
        msg_count = (await cursor.fetchone())[0]
        assert msg_count == 3, "Сообщения должны быть в БД"

    # Удаляем пользователя
    user = User(test_user_id)
    await user.delete_from_db()

    # Проверяем, что пользователь и сообщения удалены
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE id = ?",
            (test_user_id,)
        )
        user_count = (await cursor.fetchone())[0]
        assert user_count == 0, "Пользователь должен быть удален из БД"

        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ?",
            (test_user_id,)
        )
        msg_count = (await cursor.fetchone())[0]
        assert msg_count == 0, "Сообщения должны быть удалены из БД"


@pytest.mark.asyncio
async def test_dispatch_all_removes_blocked_users(test_db):
    """
    Тест проверяет, что при рассылке пользователи, заблокировавшие бота,
    удаляются из БД.
    """
    # Создаем трех тестовых пользователей
    user1_id = 22222
    user2_id = 33333
    user3_id = 44444

    user1 = User(user1_id, name="User1")
    await user1.save_for_db()

    user2 = User(user2_id, name="User2")
    await user2.save_for_db()

    user3 = User(user3_id, name="User3")
    await user3.save_for_db()

    # Добавим сообщения для каждого пользователя
    await user1.update_prompt("user", "Hello from user1")
    await user2.update_prompt("user", "Hello from user2")
    await user3.update_prompt("user", "Hello from user3")

    # Получаем список всех пользователей
    all_ids = await User.get_ids_from_table()
    assert len(all_ids) == 3, "В БД должно быть 3 пользователя"

    # Имитируем отправку сообщений
    # User2 заблокировал бота, остальные нет
    async def mock_send_message(user_id, text):
        if user_id == user2_id:
            raise TelegramForbiddenError(method="sendMessage", message="Forbidden: bot was blocked by the user")
        return True

    success_count = 0
    blocked_count = 0

    for user_id in all_ids:
        try:
            await mock_send_message(user_id, "Test message")
            success_count += 1
        except TelegramForbiddenError:
            # Удаляем пользователя, заблокировавшего бота
            user = User(user_id)
            await user.delete_from_db()
            blocked_count += 1

    # Проверяем результаты
    assert success_count == 2, "Сообщение должно быть отправлено 2 пользователям"
    assert blocked_count == 1, "1 пользователь должен быть удален"

    # Проверяем, что User2 удален из БД
    all_ids_after = await User.get_ids_from_table()
    assert len(all_ids_after) == 2, "В БД должно остаться 2 пользователя"
    assert user2_id not in all_ids_after, "User2 должен быть удален"
    assert user1_id in all_ids_after, "User1 должен остаться"
    assert user3_id in all_ids_after, "User3 должен остаться"

    # Проверяем, что сообщения User2 тоже удалены
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ?",
            (user2_id,)
        )
        msg_count = (await cursor.fetchone())[0]
        assert msg_count == 0, "Сообщения User2 должны быть удалены"


@pytest.mark.asyncio
async def test_get_ids_from_table_returns_all_users(test_db):
    """
    Тест проверяет, что get_ids_from_table возвращает всех пользователей,
    независимо от статуса напоминаний.
    """
    # Создаем пользователей с разными настройками
    user1 = User(55555, name="User with reminders")
    user1.remind_of_yourself = "2025-01-01 10:00:00"  # Напоминания включены
    await user1.save_for_db()

    user2 = User(66666, name="User without reminders")
    user2.remind_of_yourself = "0"  # Напоминания выключены
    await user2.save_for_db()

    user3 = User(77777, name="Another user with reminders")
    user3.remind_of_yourself = "2025-01-01 15:00:00"  # Напоминания включены
    await user3.save_for_db()

    # Получаем всех пользователей
    all_ids = await User.get_ids_from_table()

    # Проверяем, что получили всех пользователей
    assert len(all_ids) == 3, "Должны получить всех 3 пользователей"
    assert 55555 in all_ids, "User1 должен быть в списке"
    assert 66666 in all_ids, "User2 (с выключенными напоминаниями) должен быть в списке"
    assert 77777 in all_ids, "User3 должен быть в списке"

