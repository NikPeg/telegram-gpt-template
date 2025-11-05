"""
Миграция: Добавление поля timestamp к сообщениям в истории.

Для существующих сообщений timestamp будет установлен в null.
Новые сообщения будут иметь timestamp с учетом часового пояса.
"""

import json
import os

import aiosqlite
from dotenv import load_dotenv

load_dotenv()
TABLE_NAME = os.environ.get("TABLE_NAME", "users")


async def migrate(db: aiosqlite.Connection):
    """
    Добавляет поле timestamp ко всем сообщениям в истории пользователей.

    Args:
        db: Соединение с базой данных
    """
    print("  📝 Добавляем timestamp к сообщениям...")

    # Получаем всех пользователей с их историей сообщений
    async with db.execute(f"SELECT id, prompt FROM {TABLE_NAME}") as cursor:
        users = await cursor.fetchall()

    updated_count = 0
    message_count = 0

    for user_id, prompt_json in users:
        if not prompt_json:
            continue

        try:
            prompt = json.loads(prompt_json)

            # Проверяем, нужно ли обновлять
            needs_update = False
            for message in prompt:
                if "timestamp" not in message:
                    needs_update = True
                    message["timestamp"] = None  # Для старых сообщений ставим null
                    message_count += 1

            if needs_update:
                # Сохраняем обновленную историю
                updated_prompt = json.dumps(prompt)
                await db.execute(
                    f"UPDATE {TABLE_NAME} SET prompt = ? WHERE id = ?",
                    (updated_prompt, user_id)
                )
                updated_count += 1

        except json.JSONDecodeError:
            print(f"  ⚠️  Ошибка парсинга JSON для пользователя {user_id}")
            continue

    await db.commit()

    print(f"  ✅ Обновлено {updated_count} пользователей, {message_count} сообщений получили timestamp=null")

