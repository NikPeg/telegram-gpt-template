"""
Конфигурация приложения и настройка логирования.
"""

import contextlib
import json
import logging
import logging.handlers
import os

from dotenv import load_dotenv
from telegramify_markdown import customize

# Загружаем переменные окружения
load_dotenv()

# Telegram конфигурация
TG_TOKEN = os.environ.get("TG_TOKEN")
DEBUG_CHAT = int(os.environ.get("DEBUG_CHAT"))

# Кастомный уровень логирования FULL (ниже DEBUG)
FULL_LEVEL = 5
logging.addLevelName(FULL_LEVEL, "FULL")

# LLM конфигурация
LLM_TOKEN = os.environ.get("LLM_TOKEN")

# База данных
DATABASE_NAME = os.environ.get("DATABASE_NAME")
TABLE_NAME = os.environ.get("TABLE_NAME")
MAX_CONTEXT = int(os.environ.get("MAX_CONTEXT"))
MAX_STORAGE = int(os.environ.get("MAX_STORAGE", "100"))  # Количество сообщений в БД

# Напоминания
DELAYED_REMINDERS_HOURS = int(os.environ.get("DELAYED_REMINDERS_HOURS"))
DELAYED_REMINDERS_MINUTES = int(os.environ.get("DELAYED_REMINDERS_MINUTES"))
TIMEZONE_OFFSET = int(os.environ.get("TIMEZONE_OFFSET"))
FROM_TIME = int(os.environ.get("FROM_TIME"))
TO_TIME = int(os.environ.get("TO_TIME"))

# Администраторы
ADMIN_LIST_STR = os.environ.get("ADMIN_LIST")
ADMIN_LIST = list(map(int, ADMIN_LIST_STR.split(","))) if ADMIN_LIST_STR else set()

# Загрузка промптов и сообщений
with open("config/prompts.json", encoding="utf-8") as f:
    PROMPTS = json.load(f)
    DEFAULT_PROMPT = PROMPTS["DEFAULT_PROMPT"]
    REMINDER_PROMPT = PROMPTS["REMINDER_PROMPT"]

with open("config/messages.json", encoding="utf-8") as f:
    MESSAGES = json.load(f)


class TelegramLogsHandler(logging.Handler):
    """Handler для отправки логов в Telegram чат."""

    def __init__(self, bot, chat_id):
        super().__init__()
        self.bot = bot
        self.chat_id = chat_id
        self._migration_warned = False  # Флаг для однократного предупреждения

    def emit(self, record):
        """Отправка лог-записи в Telegram."""
        try:
            import asyncio

            log_entry = self.format(record)
            # Отправляем асинхронно
            asyncio.create_task(self._send_log(log_entry))
        except Exception:
            self.handleError(record)

    async def _send_log(self, log_entry):
        """Асинхронная отправка лога с обработкой ошибок."""
        try:
            from aiogram.exceptions import TelegramMigrateToChat

            await self.bot.send_message(self.chat_id, log_entry)
        except TelegramMigrateToChat as e:
            # Чат мигрирован, пробуем отправить в новый
            if not self._migration_warned:
                self._migration_warned = True
                # Предупреждение будет записано в файловый лог
                print(
                    f"⚠️ DEBUG чат мигрирован: старый={self.chat_id}, "
                    f"новый={e.migrate_to_chat_id}"
                )
            with contextlib.suppress(Exception):
                await self.bot.send_message(e.migrate_to_chat_id, log_entry)
        except Exception:
            # Игнорируем все остальные ошибки отправки в Telegram
            pass


def setup_logger():
    """Настройка логирования с поддержкой уровней из .env"""
    logger = logging.getLogger(__name__)

    # Получаем уровни логирования из переменных окружения
    file_log_level_str = os.environ.get("FILE_LOG_LEVEL", "INFO").upper()
    telegram_log_level_str = os.environ.get("TELEGRAM_LOG_LEVEL", "DISABLED").upper()

    # Преобразуем строки в уровни логирования
    log_levels = {
        "DISABLED": 100,  # Выше CRITICAL, ничего не логируется
        "FULL": FULL_LEVEL,
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    file_level = log_levels.get(file_log_level_str, logging.INFO)
    telegram_level = log_levels.get(telegram_log_level_str, 100)

    # Устанавливаем минимальный уровень для логгера
    logger.setLevel(min(file_level, telegram_level, logging.ERROR))

    # Console handler - только для ERROR и выше (для traceback)
    ch = logging.StreamHandler()
    ch.setLevel(logging.ERROR)
    formatter_console = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter_console)
    logger.addHandler(ch)

    # File handler
    if file_level < 100:  # Если не DISABLED
        # Путь к файлу логов (можно настроить через переменную окружения)
        log_file_path = os.environ.get("LOG_FILE_PATH", "/app/logs/debug.log")
        log_dir = os.path.dirname(log_file_path)

        # Создаем директорию для логов если её нет
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        # Используем TimedRotatingFileHandler для ротации по времени
        # when='midnight' - новый файл каждую полночь
        # interval=1 - каждые 1 день
        # backupCount=1 - хранить 1 старый файл (итого логи за 2 суток)
        fh = logging.handlers.TimedRotatingFileHandler(
            log_file_path,
            when="midnight",
            interval=1,
            backupCount=1,
            encoding="utf8",
            utc=False,  # Использовать локальное время
        )
        fh.setLevel(file_level)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    # Сохраняем настройки для Telegram handler (добавим позже, когда bot будет доступен)
    logger._telegram_level = telegram_level
    logger._file_level = file_level

    # Логируем настройки в файл
    logger.info(
        f"Logger initialized: FILE={file_log_level_str}, TELEGRAM={telegram_log_level_str}"
    )

    return logger


def add_telegram_handler(logger, bot):
    """Добавляет Telegram handler к логгеру после инициализации бота."""
    telegram_level = getattr(logger, "_telegram_level", 100)

    if telegram_level < 100:  # Если не DISABLED
        th = TelegramLogsHandler(bot, DEBUG_CHAT)
        th.setLevel(telegram_level)
        formatter = logging.Formatter("%(levelname)s: %(message)s")
        th.setFormatter(formatter)
        logger.addHandler(th)
        logger.info("Telegram logging handler enabled")


# Настройка telegramify_markdown
customize.strict_markdown = True
customize.cite_expandable = True

# Создаем логгер
logger = setup_logger()
