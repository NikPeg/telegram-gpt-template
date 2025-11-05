"""
Конфигурация приложения и настройка логирования.
"""

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
DEBUG = bool(int(os.environ.get("DEBUG")))
DEBUG_CHAT = int(os.environ.get("DEBUG_CHAT"))

# LLM конфигурация
LLM_TOKEN = os.environ.get("LLM_TOKEN")

# База данных
DATABASE_NAME = os.environ.get("DATABASE_NAME")
TABLE_NAME = os.environ.get("TABLE_NAME")
MAX_CONTEXT = int(os.environ.get("MAX_CONTEXT"))

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


def setup_logger():
    """Настройка логирования с поддержкой уровней из .env"""
    logger = logging.getLogger(__name__)
    
    # Получаем уровни логирования из переменных окружения
    log_level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    console_log_level_str = os.environ.get("CONSOLE_LOG_LEVEL", log_level_str).upper()
    file_log_level_str = os.environ.get("FILE_LOG_LEVEL", "DEBUG").upper()
    
    # Преобразуем строки в уровни логирования
    log_levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    
    main_level = log_levels.get(log_level_str, logging.INFO)
    console_level = log_levels.get(console_log_level_str, logging.INFO)
    file_level = log_levels.get(file_log_level_str, logging.DEBUG)
    
    # Устанавливаем минимальный уровень, чтобы handlers могли фильтровать сами
    logger.setLevel(min(main_level, console_level, file_level))

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    formatter_console = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter_console)

    # File handler
    fh = logging.handlers.RotatingFileHandler(
        "debug.log", maxBytes=1024 * 1024, backupCount=5, encoding="utf8"
    )
    fh.setLevel(file_level)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh.setFormatter(formatter)

    logger.addHandler(ch)
    logger.addHandler(fh)
    
    # Выводим информацию о настройках логирования
    logger.info(f"Logger initialized: LOG_LEVEL={log_level_str}, CONSOLE={console_log_level_str}, FILE={file_log_level_str}")

    return logger


# Настройка telegramify_markdown
customize.strict_markdown = True
customize.cite_expandable = True

# Создаем логгер
logger = setup_logger()
