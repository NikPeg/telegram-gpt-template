"""
Буфер сообщений для предотвращения множественных ответов на быстрые сообщения.
"""

import asyncio
import logging

# Используем стандартный logger вместо config.logger для избежания циклических зависимостей
logger = logging.getLogger(__name__)


class MessageBuffer:
    """
    Буфер для накопления быстрых сообщений от одного пользователя.

    Если пользователь отправляет несколько сообщений подряд, пока бот обрабатывает
    первое, все последующие накапливаются в буфере и обрабатываются одним запросом.
    """

    def __init__(self):
        self.user_states = {}  # {chat_id: {"processing": bool, "buffer": [], "current_task": Task | None}}
        self.locks = {}  # {chat_id: asyncio.Lock}

    def get_lock(self, chat_id: int) -> asyncio.Lock:
        """Получает или создает Lock для конкретного пользователя."""
        if chat_id not in self.locks:
            self.locks[chat_id] = asyncio.Lock()
        return self.locks[chat_id]

    async def add_message(self, chat_id: int, message_text: str) -> bool:
        """
        Добавляет сообщение в буфер.

        Args:
            chat_id: ID чата пользователя
            message_text: Текст сообщения

        Returns:
            True если нужно начать новую обработку, False если обработка уже идет
        """
        async with self.get_lock(chat_id):
            if chat_id not in self.user_states:
                self.user_states[chat_id] = {
                    "processing": False,
                    "buffer": [],
                    "current_task": None,
                }

            self.user_states[chat_id]["buffer"].append(message_text)

            if self.user_states[chat_id]["processing"]:
                # Обработка уже идет, сообщение добавлено в буфер
                logger.info(
                    f"USER{chat_id} сообщение добавлено в буфер "
                    f"(всего в буфере: {len(self.user_states[chat_id]['buffer'])})"
                )
                return False
            # Начинаем новую обработку
            self.user_states[chat_id]["processing"] = True
            return True

    async def peek_buffered_messages(self, chat_id: int) -> list[str]:
        """
        Просматривает накопленные сообщения БЕЗ очистки буфера.

        Args:
            chat_id: ID чата пользователя

        Returns:
            Копия списка накопленных сообщений
        """
        async with self.get_lock(chat_id):
            return self.user_states[chat_id]["buffer"].copy()

    async def clear_buffer(self, chat_id: int):
        """
        Очищает буфер сообщений.

        Args:
            chat_id: ID чата пользователя
        """
        async with self.get_lock(chat_id):
            count = len(self.user_states[chat_id]["buffer"])
            self.user_states[chat_id]["buffer"] = []
            logger.debug(f"USER{chat_id} буфер очищен ({count} сообщений)")

    async def get_buffered_messages(self, chat_id: int) -> list[str]:
        """
        Получает все накопленные сообщения и очищает буфер.

        УСТАРЕВШИЙ метод. Используйте peek_buffered_messages() + clear_buffer().

        Args:
            chat_id: ID чата пользователя

        Returns:
            Список накопленных сообщений
        """
        async with self.get_lock(chat_id):
            messages = self.user_states[chat_id]["buffer"].copy()
            self.user_states[chat_id]["buffer"] = []
            logger.debug(f"USER{chat_id} извлечено {len(messages)} сообщений из буфера")
            return messages

    async def set_current_task(self, chat_id: int, task: asyncio.Task):
        """
        Сохраняет ссылку на текущую задачу обработки.

        Args:
            chat_id: ID чата пользователя
            task: Задача обработки
        """
        async with self.get_lock(chat_id):
            self.user_states[chat_id]["current_task"] = task

    async def has_buffered_messages(self, chat_id: int) -> bool:
        """
        Проверяет, есть ли сообщения в буфере.

        Args:
            chat_id: ID чата пользователя

        Returns:
            True если в буфере есть сообщения
        """
        async with self.get_lock(chat_id):
            return len(self.user_states[chat_id]["buffer"]) > 0

    async def finish_processing(self, chat_id: int) -> bool:
        """
        Завершает текущую обработку и проверяет наличие новых сообщений.

        Args:
            chat_id: ID чата пользователя

        Returns:
            True если в буфере есть новые сообщения (нужно продолжить обработку)
        """
        async with self.get_lock(chat_id):
            has_more = len(self.user_states[chat_id]["buffer"]) > 0

            if has_more:
                logger.debug(
                    f"USER{chat_id} обработка завершена, "
                    f"но есть еще {len(self.user_states[chat_id]['buffer'])} сообщений"
                )
            else:
                logger.debug(f"USER{chat_id} обработка завершена, буфер пуст")
                self.user_states[chat_id]["processing"] = False
                self.user_states[chat_id]["current_task"] = None

            return has_more


# Глобальный экземпляр буфера
message_buffer = MessageBuffer()

