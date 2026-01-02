"""
Тесты для проверки работы команды /forget и контекста сообщений.
"""

import os
import sys
from pathlib import Path

import pytest

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiosqlite

from core.database import Conversation


@pytest.fixture
async def test_db():
    """Фикстура для создания и очистки тестовой БД."""
    test_db_name = "test_users_pytest.db"

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
async def test_forget_first_message_in_context(test_db):
    """
    Тест проверяет, что после /forget первое сообщение пользователя
    попадает в промпт для LLM.
    """
    test_user_id = 12345

    # Создаем пользователя
    conversation = Conversation(test_user_id, name="TestUser")
    await conversation.save_for_db()

    # Эмулируем команду /forget
    conversation = Conversation(test_user_id)
    await conversation.get_from_db()
    conversation.active_messages_count = 0
    await conversation.update_in_db()

    # Первое сообщение после /forget
    message1 = "Привет! Меня зовут Тест."

    conversation = Conversation(test_user_id)
    await conversation.get_from_db()

    # Получаем контекст (должен быть пустым)
    context_before = await conversation.get_context_for_llm()
    assert len(context_before) == 0, (
        "Контекст должен быть пустым при active_messages_count = 0"
    )

    # Формируем промпт как в реальном коде
    prompt_for_request = [{"role": "system", "content": "Системный промпт"}]

    for msg in context_before:
        prompt_for_request.append({"role": msg["role"], "content": msg["content"]})

    # Добавляем текущее сообщение пользователя
    prompt_for_request.append({"role": "user", "content": message1})

    # Проверяем: в промпте должно быть текущее сообщение
    user_messages_in_prompt = [
        msg for msg in prompt_for_request if msg["role"] == "user"
    ]
    assert len(user_messages_in_prompt) == 1, "В промпте должно быть 1 user сообщение"
    assert user_messages_in_prompt[0]["content"] == message1, (
        "Текст сообщения должен совпадать"
    )


@pytest.mark.asyncio
async def test_forget_second_message_has_context(test_db):
    """
    Тест проверяет, что второе сообщение после /forget
    получает контекст из первого сообщения.
    """
    test_user_id = 23456

    # Создаем пользователя и эмулируем /forget
    conversation = Conversation(test_user_id, name="TestUser2")
    await conversation.save_for_db()

    conversation = Conversation(test_user_id)
    await conversation.get_from_db()
    conversation.active_messages_count = 0
    await conversation.update_in_db()

    # Первое сообщение
    message1 = "Привет! Меня зовут Тест."
    llm_response1 = "Привет, Тест! Рад познакомиться!"

    # Сохраняем первую пару сообщений
    conversation = Conversation(test_user_id)
    await conversation.get_from_db()
    await conversation.update_prompt("user", message1)
    await conversation.update_prompt("assistant", llm_response1)
    if conversation.active_messages_count is not None:
        conversation.active_messages_count += 2
    await conversation.update_in_db()

    # Второе сообщение
    message2 = "Как меня зовут?"

    conversation = Conversation(test_user_id)
    await conversation.get_from_db()

    # Получаем контекст (должен содержать предыдущую пару)
    context_before = await conversation.get_context_for_llm()
    assert len(context_before) == 2, "Контекст должен содержать 2 сообщения"
    assert context_before[0]["role"] == "user", "Первое сообщение должно быть от user"
    assert context_before[0]["content"] == message1, (
        "Содержимое первого сообщения должно совпадать"
    )
    assert context_before[1]["role"] == "assistant", (
        "Второе сообщение должно быть от assistant"
    )
    assert context_before[1]["content"] == llm_response1, (
        "Содержимое второго сообщения должно совпадать"
    )

    # Формируем промпт
    prompt_for_request = [{"role": "system", "content": "Системный промпт"}]

    for msg in context_before:
        prompt_for_request.append({"role": msg["role"], "content": msg["content"]})

    prompt_for_request.append({"role": "user", "content": message2})

    # Проверяем: в промпте должны быть оба user сообщения
    user_messages_in_prompt = [
        msg for msg in prompt_for_request if msg["role"] == "user"
    ]
    assert len(user_messages_in_prompt) == 2, "В промпте должно быть 2 user сообщения"
    assert user_messages_in_prompt[0]["content"] == message1, (
        "Первое user сообщение должно быть в контексте"
    )
    assert user_messages_in_prompt[1]["content"] == message2, (
        "Второе user сообщение - текущее"
    )


@pytest.mark.asyncio
async def test_forget_counter_increments(test_db):
    """
    Тест проверяет, что счетчик active_messages_count
    правильно увеличивается после каждой пары сообщений.
    """
    test_user_id = 34567

    # Создаем пользователя
    conversation = Conversation(test_user_id, name="TestUser3")
    await conversation.save_for_db()

    # Эмулируем /forget
    conversation = Conversation(test_user_id)
    await conversation.get_from_db()
    conversation.active_messages_count = 0
    await conversation.update_in_db()

    # Проверяем начальное значение
    conversation = Conversation(test_user_id)
    await conversation.get_from_db()
    assert conversation.active_messages_count == 0, (
        "После /forget счетчик должен быть 0"
    )

    # Первая пара сообщений
    await conversation.update_prompt("user", "Сообщение 1")
    await conversation.update_prompt("assistant", "Ответ 1")
    if conversation.active_messages_count is not None:
        conversation.active_messages_count += 2
    await conversation.update_in_db()

    conversation = Conversation(test_user_id)
    await conversation.get_from_db()
    assert conversation.active_messages_count == 2, (
        "После первой пары счетчик должен быть 2"
    )

    # Вторая пара сообщений
    await conversation.update_prompt("user", "Сообщение 2")
    await conversation.update_prompt("assistant", "Ответ 2")
    if conversation.active_messages_count is not None:
        conversation.active_messages_count += 2
    await conversation.update_in_db()

    conversation = Conversation(test_user_id)
    await conversation.get_from_db()
    assert conversation.active_messages_count == 4, (
        "После второй пары счетчик должен быть 4"
    )


@pytest.mark.asyncio
async def test_forget_messages_saved_in_db(test_db):
    """
    Тест проверяет, что все сообщения сохраняются в БД,
    даже после команды /forget.
    """
    test_user_id = 45678

    # Создаем пользователя
    conversation = Conversation(test_user_id, name="TestUser4")
    await conversation.save_for_db()

    # Добавляем несколько сообщений до /forget
    await conversation.update_prompt("user", "Старое сообщение 1")
    await conversation.update_prompt("assistant", "Старый ответ 1")

    # Эмулируем /forget
    conversation = Conversation(test_user_id)
    await conversation.get_from_db()
    conversation.active_messages_count = 0
    await conversation.update_in_db()

    # Добавляем новые сообщения
    await conversation.update_prompt("user", "Новое сообщение 1")
    await conversation.update_prompt("assistant", "Новый ответ 1")

    # Проверяем что все сообщения в БД
    async with aiosqlite.connect(test_db) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ?", (test_user_id,)
        )
        count = (await cursor.fetchone())[0]

    assert count == 4, "Все 4 сообщения должны быть сохранены в БД"

    # Но в контекст попадают только последние 2
    context = await conversation.get_context_for_llm()
    assert len(context) == 0, (
        "Контекст должен быть пустым при active_messages_count = 0"
    )
