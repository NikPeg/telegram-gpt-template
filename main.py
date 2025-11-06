"""
Главный файл приложения - точка входа для запуска бота.
"""

# ruff: noqa: I001 - порядок импортов handlers критичен для работы бота
import asyncio
import contextlib

import database
from migrations.migration_manager import run_migrations

# Импортируем все обработчики (чтобы они зарегистрировались)
# ВАЖНО: порядок имеет значение! Сначала специфичные (команды), потом общие
from bot_instance import bot, dp
from config import ADMIN_CHAT, add_telegram_handler, logger

# isort: off - не сортировать этот блок, порядок критичен!
from handlers import user_handlers  # noqa: F401
from handlers import admin_handlers  # noqa: F401
from handlers import message_handlers  # noqa: F401
# isort: on

from services.reminder_service import reminder_loop


async def main():
    """Главная функция запуска бота."""
    # Инициализация базы данных
    db_status = await database.check_db()

    # Применяем миграции
    await run_migrations()

    # Добавляем Telegram handler после инициализации бота
    add_telegram_handler(logger, bot)

    # Простые сообщения для docker logs (в консоль)
    print("=" * 50)
    print("🤖 БОТ ЗАПУЩЕН")
    print("=" * 50)
    print(f"Database: {db_status}")
    print(f"Admin chat: {ADMIN_CHAT}")
    print("Нажмите Ctrl-C для остановки бота")
    print("=" * 50 + "\n")

    # Создаем задачу для напоминаний
    reminder_task = asyncio.create_task(reminder_loop())

    try:
        # Запускаем polling - он сам обрабатывает сигналы
        await dp.start_polling(bot)
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Получен сигнал остановки")
    except Exception as e:
        logger.critical(f"CRITICAL_ERROR: {e}", exc_info=True)
    finally:
        print("Останавливаем бота...")
        reminder_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reminder_task
        await bot.session.close()
        print("✅ Бот остановлен")


async def run_with_restart():
    """Запуск с автоматическим перезапуском при ошибках."""
    while True:
        try:
            await main()
            break  # Нормальное завершение - выходим из цикла
        except (KeyboardInterrupt, SystemExit):
            print("👋 Завершение работы")
            break
        except Exception as e:
            print(f"main() завершился с ошибкой: {e}. Перезапуск через 5 секунд...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(run_with_restart())
    except (KeyboardInterrupt, SystemExit):
        print("👋 Программа завершена")
