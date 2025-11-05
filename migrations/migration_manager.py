"""
Менеджер для управления миграциями базы данных.
"""

import asyncio
import os
from pathlib import Path

import aiosqlite
from dotenv import load_dotenv

load_dotenv()
DATABASE_NAME = os.environ.get("DATABASE_NAME", "users.db")


async def get_applied_migrations(db: aiosqlite.Connection) -> set[str]:
    """
    Получает список уже примененных миграций.

    Args:
        db: Соединение с базой данных

    Returns:
        Множество имен примененных миграций
    """
    # Создаем таблицу миграций, если её нет
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.commit()

    # Получаем список примененных миграций
    async with db.execute("SELECT name FROM migrations") as cursor:
        rows = await cursor.fetchall()

    return {row[0] for row in rows}


async def mark_migration_applied(db: aiosqlite.Connection, migration_name: str):
    """
    Отмечает миграцию как примененную.

    Args:
        db: Соединение с базой данных
        migration_name: Имя миграции
    """
    await db.execute(
        "INSERT INTO migrations (name) VALUES (?)",
        (migration_name,)
    )
    await db.commit()


async def run_migrations():
    """
    Запускает все неприменённые миграции.
    """
    print("🔄 Начинаем проверку миграций...")

    # Путь к папке с миграциями
    migrations_dir = Path(__file__).parent

    # Получаем список файлов миграций
    migration_files = sorted([
        f for f in migrations_dir.glob("*.py")
        if f.name.startswith("migration_") and f.name != "migration_manager.py"
    ])

    if not migration_files:
        print("✅ Миграций не найдено")
        return

    async with aiosqlite.connect(DATABASE_NAME) as db:
        # Получаем список уже примененных миграций
        applied = await get_applied_migrations(db)

        # Применяем каждую неприменённую миграцию
        for migration_file in migration_files:
            migration_name = migration_file.stem  # Имя файла без расширения

            if migration_name in applied:
                print(f"⏭️  Пропускаем {migration_name} (уже применена)")
                continue

            print(f"🔧 Применяем миграцию: {migration_name}")

            try:
                # Динамически импортируем модуль миграции
                import importlib.util
                spec = importlib.util.spec_from_file_location(migration_name, migration_file)
                migration_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(migration_module)

                # Запускаем функцию migrate
                if hasattr(migration_module, "migrate"):
                    await migration_module.migrate(db)
                    await mark_migration_applied(db, migration_name)
                    print(f"✅ Миграция {migration_name} применена успешно")
                else:
                    print(f"⚠️  Миграция {migration_name} не содержит функцию migrate()")

            except Exception as e:
                print(f"❌ Ошибка при применении миграции {migration_name}: {e}")
                raise

    print("✅ Все миграции применены успешно")


if __name__ == "__main__":
    asyncio.run(run_migrations())

