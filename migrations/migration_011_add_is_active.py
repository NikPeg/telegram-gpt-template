"""
Миграция 011: Добавление поля is_active для оптимизации проверки активности пользователей.

Добавляет поле is_active в таблицу conversations для хранения флага активности пользователя.
Это поле используется для оптимизации проверки активности - вместо запросов к таблице messages
каждый раз, мы обновляем флаг при проверке напоминаний.

Изменения:
- Добавление колонки is_active INTEGER DEFAULT 1 в таблицу conversations
- Добавление индекса на is_active для ускорения фильтрации
- Инициализация значений:
  - is_active = 1 для пользователей с remind_of_yourself != "0" (напоминания включены)
  - is_active = 0 для пользователей с remind_of_yourself = "0" (напоминания отключены)
- Для существующих пользователей вычисляется is_active на основе последнего сообщения
"""

from datetime import datetime, timedelta

import aiosqlite

from database import DATABASE_NAME

# Уникальный идентификатор миграции
MIGRATION_ID = "migration_011_add_is_active"

# Количество дней неактивности по умолчанию (можно переопределить через env)
INACTIVE_USER_DAYS = 7


async def upgrade():
    """Применяет миграцию."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        # Проверяем, существует ли уже колонка
        cursor = await db.execute("PRAGMA table_info(conversations)")
        columns = await cursor.fetchall()
        column_names = [column[1] for column in columns]

        if "is_active" in column_names:
            return "Колонка is_active уже существует"

        # Добавляем колонку is_active с дефолтным значением 1
        await db.execute(
            "ALTER TABLE conversations ADD COLUMN is_active INTEGER DEFAULT 1"
        )
        await db.commit()

        # Добавляем индекс для ускорения фильтрации
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_is_active ON conversations(is_active)"
        )
        await db.commit()

        # Инициализируем значения is_active для существующих пользователей
        # Сначала устанавливаем is_active = 0 для пользователей с отключенными напоминаниями
        await db.execute(
            "UPDATE conversations SET is_active = 0 WHERE remind_of_yourself = '0'"
        )

        # Для остальных пользователей проверяем активность на основе последнего сообщения
        # Получаем всех пользователей с включенными напоминаниями
        cursor = await db.execute(
            "SELECT id, remind_of_yourself FROM conversations WHERE remind_of_yourself != '0' OR remind_of_yourself IS NULL"
        )
        users = await cursor.fetchall()

        # Вычисляем пороговую дату для активности
        now = datetime.now()
        threshold_date = now - timedelta(days=INACTIVE_USER_DAYS)

        updated_count = 0
        for user_id, remind_of_yourself in users:
            # Проверяем последнее сообщение пользователя
            cursor = await db.execute(
                """
                SELECT MAX(timestamp) FROM messages
                WHERE user_id = ? AND role = 'user' AND timestamp IS NOT NULL
                """,
                (user_id,),
            )
            result = await cursor.fetchone()
            last_message_time = result[0] if result else None

            is_active = 1  # По умолчанию активен

            if last_message_time:
                # Есть сообщения - проверяем дату последнего
                try:
                    last_dt = datetime.strptime(last_message_time, "%Y-%m-%d %H:%M:%S")
                    if last_dt < threshold_date:
                        is_active = 0  # Неактивен
                except (ValueError, TypeError):
                    # Некорректный формат - используем remind_of_yourself как fallback
                    if remind_of_yourself:
                        try:
                            remind_dt = datetime.strptime(
                                remind_of_yourself, "%Y-%m-%d %H:%M:%S"
                            )
                            if remind_dt < threshold_date:
                                is_active = 0
                        except (ValueError, TypeError):
                            pass
            elif remind_of_yourself:
                # Нет сообщений, но есть remind_of_yourself - используем его
                try:
                    remind_dt = datetime.strptime(
                        remind_of_yourself, "%Y-%m-%d %H:%M:%S"
                    )
                    if remind_dt < threshold_date:
                        is_active = 0
                except (ValueError, TypeError):
                    # Некорректный формат - считаем активным (новый пользователь)
                    pass
            # Если нет ни сообщений, ни remind_of_yourself - считаем активным (новый пользователь)

            # Обновляем флаг
            await db.execute(
                "UPDATE conversations SET is_active = ? WHERE id = ?",
                (is_active, user_id),
            )
            updated_count += 1

        await db.commit()

        return (
            f"Добавлена колонка is_active в таблицу conversations. "
            f"Инициализировано {updated_count} пользователей."
        )


async def downgrade():
    """
    Откатывает миграцию.

    Примечание: SQLite не поддерживает DROP COLUMN напрямую,
    поэтому откат требует пересоздания таблицы.
    """
    async with aiosqlite.connect(DATABASE_NAME) as db:
        # Проверяем, существует ли колонка
        cursor = await db.execute("PRAGMA table_info(conversations)")
        columns = await cursor.fetchall()
        column_names = [column[1] for column in columns]

        if "is_active" not in column_names:
            return "Колонка is_active не существует"

        # Удаляем индекс
        await db.execute("DROP INDEX IF EXISTS idx_conversations_is_active")
        await db.commit()

        # Создаем временную таблицу без колонки is_active
        await db.execute(
            """
            CREATE TABLE conversations_temp (
                id INTEGER PRIMARY KEY,
                name TEXT,
                prompt JSON,
                remind_of_yourself TEXT,
                sub_lvl INTEGER,
                sub_id TEXT,
                sub_period INTEGER,
                is_admin INTEGER,
                active_messages_count INTEGER,
                reminder_times TEXT DEFAULT '["19:15"]',
                subscription_verified INTEGER,
                referral_code TEXT DEFAULT NULL
            )
            """
        )

        # Копируем данные (без is_active)
        await db.execute(
            """
            INSERT INTO conversations_temp
            SELECT id, name, prompt, remind_of_yourself, sub_lvl, sub_id,
                   sub_period, is_admin, active_messages_count, reminder_times,
                   subscription_verified, referral_code
            FROM conversations
            """
        )

        # Удаляем старую таблицу
        await db.execute("DROP TABLE conversations")

        # Переименовываем временную таблицу
        await db.execute("ALTER TABLE conversations_temp RENAME TO conversations")

        await db.commit()

        return "Колонка is_active удалена из таблицы conversations"

