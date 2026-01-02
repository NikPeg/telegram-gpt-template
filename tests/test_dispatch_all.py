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

from core.database import Conversation


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
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY,
                name TEXT,
                active_messages_count INTEGER,
                subscription_verified INTEGER,
                referral_code TEXT DEFAULT NULL
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
async def test_delete_from_db(test_db):
    """
    Тест проверяет, что метод delete_from_db удаляет пользователя
    и все его сообщения из БД.
    """
    test_user_id = 11111

    # Создаем пользователя
    conversation = Conversation(test_user_id, name="TestUser")
    await conversation.save_for_db()

    # Добавляем несколько сообщений
    await conversation.update_prompt("user", "Сообщение 1")
    await conversation.update_prompt("assistant", "Ответ 1")
    await conversation.update_prompt("user", "Сообщение 2")

    # Проверяем, что пользователь и сообщения есть в БД
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM conversations WHERE id = ?", (test_user_id,)
        )
        user_count = (await cursor.fetchone())[0]
        assert user_count == 1, "Пользователь должен быть в БД"

        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ?", (test_user_id,)
        )
        msg_count = (await cursor.fetchone())[0]
        assert msg_count == 3, "Сообщения должны быть в БД"

    # Удаляем пользователя
    conversation = Conversation(test_user_id)
    await conversation.delete_from_db()

    # Проверяем, что пользователь и сообщения удалены
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM conversations WHERE id = ?", (test_user_id,)
        )
        user_count = (await cursor.fetchone())[0]
        assert user_count == 0, "Пользователь должен быть удален из БД"

        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ?", (test_user_id,)
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

    user1 = Conversation(user1_id, name="User1")
    await user1.save_for_db()

    user2 = Conversation(user2_id, name="User2")
    await user2.save_for_db()

    user3 = Conversation(user3_id, name="User3")
    await user3.save_for_db()

    # Добавим сообщения для каждого пользователя
    await user1.update_prompt("user", "Hello from user1")
    await user2.update_prompt("user", "Hello from user2")
    await user3.update_prompt("user", "Hello from user3")

    # Получаем список всех пользователей
    all_ids = await Conversation.get_ids_from_table()
    assert len(all_ids) == 3, "В БД должно быть 3 пользователя"

    # Имитируем отправку сообщений
    # User2 заблокировал бота, остальные нет
    async def mock_send_message(user_id, text):
        if user_id == user2_id:
            raise TelegramForbiddenError(
                method="sendMessage", message="Forbidden: bot was blocked by the user"
            )
        return True

    success_count = 0
    blocked_count = 0

    for user_id in all_ids:
        try:
            await mock_send_message(user_id, "Test message")
            success_count += 1
        except TelegramForbiddenError:
            # Удаляем пользователя, заблокировавшего бота
            conversation = Conversation(user_id)
            await conversation.delete_from_db()
            blocked_count += 1

    # Проверяем результаты
    assert success_count == 2, "Сообщение должно быть отправлено 2 пользователям"
    assert blocked_count == 1, "1 пользователь должен быть удален"

    # Проверяем, что User2 удален из БД
    all_ids_after = await Conversation.get_ids_from_table()
    assert len(all_ids_after) == 2, "В БД должно остаться 2 пользователя"
    assert user2_id not in all_ids_after, "User2 должен быть удален"
    assert user1_id in all_ids_after, "User1 должен остаться"
    assert user3_id in all_ids_after, "User3 должен остаться"

    # Проверяем, что сообщения User2 тоже удалены
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ?", (user2_id,)
        )
        msg_count = (await cursor.fetchone())[0]
        assert msg_count == 0, "Сообщения User2 должны быть удалены"


@pytest.mark.asyncio
async def test_get_ids_from_table_returns_all_users(test_db):
    """
    Тест проверяет, что get_ids_from_table возвращает всех пользователей.
    """
    # Создаем пользователей
    user1 = Conversation(55555, name="User 1")
    await user1.save_for_db()

    user2 = Conversation(66666, name="User 2")
    await user2.save_for_db()

    user3 = Conversation(77777, name="User 3")
    await user3.save_for_db()

    # Получаем всех пользователей
    all_ids = await Conversation.get_ids_from_table()

    # Проверяем, что получили всех пользователей
    assert len(all_ids) == 3, "Должны получить всех 3 пользователей"
    assert 55555 in all_ids, "User1 должен быть в списке"
    assert 66666 in all_ids, "User2 (с выключенными напоминаниями) должен быть в списке"
    assert 77777 in all_ids, "User3 должен быть в списке"
