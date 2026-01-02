"""
Миграция 013: Удаление deprecated полей из таблицы conversations.

Удаляет неиспользуемые поля:
- prompt (deprecated, используется отдельная таблица messages)
- remind_of_yourself (старая система напоминаний)
- sub_lvl, sub_id, sub_period (старая система подписок)
- is_admin (не используется)
- reminder_time, reminder_weekdays (система напоминаний удалена)
- is_active (не используется в текущей версии)

Оставляет только активно используемые поля:
- id, name, active_messages_count, subscription_verified, referral_code
"""

import aiosqlite

from core.database import DATABASE_NAME

# Уникальный идентификатор миграции
MIGRATION_ID = "migration_013_remove_deprecated_fields"


async def upgrade():
    """Применяет миграцию."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        # Проверяем структуру таблицы
        cursor = await db.execute("PRAGMA table_info(conversations)")
        columns = await cursor.fetchall()
        column_names = [column[1] for column in columns]

        # Проверяем, нужна ли миграция
        # Если старые поля уже удалены (только 5 полей), пропускаем миграцию
        if len(column_names) == 5 and "prompt" not in column_names:
            return "Deprecated поля уже удалены"

        # Создаем новую таблицу с только нужными полями
        await db.execute(
            """
            CREATE TABLE conversations_new (
                id INTEGER PRIMARY KEY,
                name TEXT,
                active_messages_count INTEGER,
                subscription_verified INTEGER,
                referral_code TEXT DEFAULT NULL
            )
            """
        )

        # Копируем данные из старой таблицы в новую
        await db.execute(
            """
            INSERT INTO conversations_new (id, name, active_messages_count, subscription_verified, referral_code)
            SELECT id, name, active_messages_count, subscription_verified, referral_code
            FROM conversations
            """
        )

        # Удаляем старую таблицу
        await db.execute("DROP TABLE conversations")

        # Переименовываем новую таблицу
        await db.execute("ALTER TABLE conversations_new RENAME TO conversations")

        await db.commit()

        return "Удалены deprecated поля: prompt, remind_of_yourself, sub_lvl, sub_id, sub_period, is_admin, reminder_time, reminder_weekdays, is_active"


async def downgrade():
    """Откатывает миграцию."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        # Создаем таблицу со старой структурой
        await db.execute(
            """
            CREATE TABLE conversations_old (
                id INTEGER PRIMARY KEY,
                name TEXT,
                prompt TEXT DEFAULT '[]',
                remind_of_yourself TEXT,
                sub_lvl INTEGER DEFAULT 0,
                sub_id TEXT DEFAULT 0,
                sub_period INTEGER DEFAULT -1,
                is_admin INTEGER DEFAULT 0,
                active_messages_count INTEGER,
                reminder_time TEXT DEFAULT '19:15',
                reminder_weekdays TEXT DEFAULT '[]',
                subscription_verified INTEGER,
                referral_code TEXT DEFAULT NULL,
                is_active INTEGER DEFAULT 1
            )
            """
        )

        # Копируем данные обратно (с дефолтными значениями для удаленных полей)
        await db.execute(
            """
            INSERT INTO conversations_old (id, name, active_messages_count, subscription_verified, referral_code)
            SELECT id, name, active_messages_count, subscription_verified, referral_code
            FROM conversations
            """
        )

        # Удаляем новую таблицу
        await db.execute("DROP TABLE conversations")

        # Переименовываем старую таблицу обратно
        await db.execute("ALTER TABLE conversations_old RENAME TO conversations")

        await db.commit()

        return "Восстановлены deprecated поля"

