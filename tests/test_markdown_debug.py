"""
Тесты для отладки отправки сообщений с ошибками форматирования markdown.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

# Добавляем корневую директорию проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.mark.asyncio
async def test_markdown_debug_to_admin_chat():
    """
    Тест проверяет, что при ошибке форматирования markdown
    в админский чат отправляются отладочные сообщения:
    1. Описание ошибки с ID чата
    2. Оригинальный текст (до исправлений)
    3. Текст после всех исправлений
    """
    # Импортируем модули с моками
    from unittest.mock import patch

    with patch.dict(
        "sys.modules",
        {"core.config": MagicMock(), "core.bot_instance": MagicMock()},
    ):
        # Настраиваем моки
        mock_config = sys.modules["core.config"]
        mock_config.ADMIN_CHAT = 123456
        mock_config.MESSAGES_LEVEL = 20
        mock_config.logger = MagicMock()

        # Импортируем utils после настройки моков
        from core import utils

        # Создаем мок бота
        mock_bot = AsyncMock()
        utils.bot = mock_bot

        # Счетчик вызовов send_message
        send_message_calls = []

        # Функция, имитирующая ошибку при отправке с markdown
        async def mock_send_message(chat_id, text, parse_mode=None, **kwargs):
            call_info = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
            send_message_calls.append(call_info)

            # Если это попытка отправить с markdown в обычный чат
            if parse_mode == ParseMode.MARKDOWN_V2 and chat_id != mock_config.ADMIN_CHAT:
                raise TelegramBadRequest(
                    method="sendMessage",
                    message="Can't parse entities: Can't find end of the entity starting at byte offset 42",
                )

            # Для админского чата или без parse_mode - успешно
            return MagicMock(message_id=999)

        mock_bot.send_message = mock_send_message

        # Текст с проблемным markdown
        test_text = "Тест *жирный _курсив* неправильно_"
        test_chat_id = 7554526253

        # Отправляем сообщение
        result = await utils.send_message_with_fallback(
            chat_id=test_chat_id, text=test_text
        )

        # Проверяем, что сообщение успешно отправлено
        assert result.message_id == 999

        # Проверяем, что были вызовы к админскому чату
        admin_calls = [
            call for call in send_message_calls if call["chat_id"] == mock_config.ADMIN_CHAT
        ]

        # Должно быть минимум 3 сообщения в админский чат
        assert len(admin_calls) >= 3, f"Expected at least 3 messages to admin chat, got {len(admin_calls)}"

        # Проверяем содержимое сообщений
        texts = [call["text"] for call in admin_calls]

        # Должно быть сообщение с описанием ошибки
        has_error_desc = any("MARKDOWN FIX FAILED" in text for text in texts)
        assert has_error_desc, "Error description not found in admin messages"

        # Должно быть сообщение "ОРИГИНАЛЬНЫЙ ТЕКСТ"
        has_original_marker = any(
            "ОРИГИНАЛЬНЫЙ" in text or "оригинал" in text.lower() for text in texts
        )
        assert has_original_marker, "Original text marker not found in admin messages"

        # Должно быть сообщение "ТЕКСТ ПОСЛЕ ВСЕХ ИСПРАВЛЕНИЙ"
        has_fixed_marker = any(
            "ПОСЛЕ ВСЕХ ИСПРАВЛЕНИЙ" in text or "после" in text.lower() for text in texts
        )
        assert has_fixed_marker, "Fixed text marker not found in admin messages"

        # Проверяем, что оригинальный текст был отправлен
        has_original_text = any(test_text in text for text in texts)
        assert has_original_text, "Original text not found in admin messages"


@pytest.mark.asyncio
async def test_no_debug_messages_on_success():
    """
    Тест проверяет, что при успешной отправке сообщения
    отладочные сообщения НЕ отправляются в админский чат.
    """
    from unittest.mock import patch

    with patch.dict(
        "sys.modules",
        {"core.config": MagicMock(), "core.bot_instance": MagicMock()},
    ):
        mock_config = sys.modules["core.config"]
        mock_config.ADMIN_CHAT = 777777
        mock_config.MESSAGES_LEVEL = 20
        mock_config.logger = MagicMock()

        from core import utils

        mock_bot = AsyncMock()
        utils.bot = mock_bot

        send_message_calls = []

        async def mock_send_message(chat_id, text, parse_mode=None, **kwargs):
            call_info = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
            send_message_calls.append(call_info)
            # Всегда успешно
            return MagicMock(message_id=555)

        mock_bot.send_message = mock_send_message

        test_text = "Обычный текст без проблем"
        test_chat_id = 9876543

        result = await utils.send_message_with_fallback(
            chat_id=test_chat_id, text=test_text
        )

        assert result.message_id == 555

        # Проверяем, что в админский чат НИЧЕГО не отправлено
        admin_calls = [
            call for call in send_message_calls if call["chat_id"] == mock_config.ADMIN_CHAT
        ]

        assert len(admin_calls) == 0, "No debug messages should be sent on success"


if __name__ == "__main__":
    # Для быстрого запуска тестов
    pytest.main([__file__, "-v"])

