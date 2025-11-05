"""
Главный файл приложения - точка входа для запуска бота.
"""

import asyncio
import contextlib

import database

# Импортируем все обработчики (чтобы они зарегистрировались)
from bot_instance import bot, dp
from config import DEBUG, DEBUG_CHAT, logger
from handlers import admin_handlers, message_handlers, user_handlers  # noqa: F401
from services.reminder_service import reminder_loop


async def main():
    """Главная функция запуска бота."""
    # Инициализация базы данных
    print(await database.check_db())
    print("Основная часть запущена")
    print("Нажмите Ctrl-C для остановки бота\n")

    # Создаем задачу для напоминаний
    reminder_task = asyncio.create_task(reminder_loop())

    try:
        # Запускаем polling - он сам обрабатывает сигналы
        await dp.start_polling(bot)
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Получен сигнал остановки")
    except Exception as e:
        print(f"Ошибка: {e}")
        if DEBUG:
            await bot.send_message(DEBUG_CHAT, f"Произошла ошибка: '{e}'")
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
