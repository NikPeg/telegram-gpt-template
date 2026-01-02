import asyncio
import os
from datetime import UTC, datetime

import aiosqlite
from dotenv import load_dotenv

load_dotenv()
LLM_TOKEN = os.environ.get("LLM_TOKEN")
DEBUG = bool(os.environ.get("DEBUG"))
ADMIN_CHAT = int(os.environ.get("ADMIN_CHAT") or "0")
DATABASE_NAME = os.environ.get("DATABASE_NAME", "users.db")
MAX_CONTEXT = int(os.environ.get("MAX_CONTEXT") or "10")
MAX_STORAGE = int(os.environ.get("MAX_STORAGE", "100"))


class Conversation:
    """
    Модель для хранения контекста беседы с ботом.

    Используется как для личных диалогов с пользователями (id > 0),
    так и для групповых чатов (id < 0). Название "Conversation" отражает
    суть: это не просто пользователь, а контекст беседы с определенными
    настройками, историей сообщений и параметрами взаимодействия.

    Attributes:
        id: Идентификатор беседы (положительный для пользователей, отрицательный для чатов)
        name: Имя пользователя или название чата
        active_messages_count: Количество активных сообщений в контексте (NULL = все, 0 = забыть, N = последние N)
        subscription_verified: Статус верификации подписки (NULL = не проверялось, 0 = не подписан, 1 = подписан)
        referral_code: Реферальный код, по которому пользователь перешел в бота
    """

    def __init__(
        self,
        id,
        name=None,
        active_messages_count=None,
        subscription_verified=None,
        referral_code=None,
    ):
        self.id = id
        self.name = name
        self.active_messages_count = active_messages_count
        self.subscription_verified = subscription_verified
        self.referral_code = referral_code

    def __repr__(self):
        return f"Conversation(id={self.id}, name={self.name}, active_messages_count={self.active_messages_count}, subscription_verified={self.subscription_verified}, referral_code={self.referral_code})"

    async def get_from_db(self):
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            sql = "SELECT id, name, active_messages_count, subscription_verified, referral_code FROM conversations WHERE id = ?"
            await cursor.execute(sql, (self.id,))
            row = await cursor.fetchone()
            if row:
                self.id = row[0]
                self.name = row[1]
                self.active_messages_count = row[2]
                self.subscription_verified = row[3]
                self.referral_code = row[4]

    async def __call__(self, user_id):
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            sql = "SELECT id, name, active_messages_count, subscription_verified, referral_code FROM conversations WHERE id = ?"
            await cursor.execute(sql, (user_id,))
            row = await cursor.fetchone()
            if row:
                return Conversation(
                    id=row[0],
                    name=row[1],
                    active_messages_count=row[2],
                    subscription_verified=row[3],
                    referral_code=row[4],
                )
            return None

    async def get_ids_from_table():
        async with (
            aiosqlite.connect(DATABASE_NAME) as db,
            db.execute("SELECT id FROM conversations") as cursor,
        ):
            rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def save_for_db(self):
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            sql_insert = """
                        INSERT INTO conversations (id, name, active_messages_count, subscription_verified, referral_code)
                        VALUES (?, ?, ?, ?, ?)
                    """
            values = (
                self.id,
                self.name,
                self.active_messages_count,
                self.subscription_verified,
                self.referral_code,
            )
            await cursor.execute(sql_insert, values)
            await db.commit()
            await cursor.close()

    async def update_prompt(self, role, new_request):
        """
        Добавляет новое сообщение в таблицу messages.
        Старые сообщения (больше MAX_STORAGE) автоматически удаляются.
        """
        # Получаем текущее время в UTC
        current_time = datetime.now(UTC)
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")

        async with aiosqlite.connect(DATABASE_NAME) as db:
            # Добавляем новое сообщение
            await db.execute(
                """
                INSERT INTO messages (user_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (self.id, role, new_request, timestamp),
            )

            # Проверяем количество сообщений и удаляем старые, если превышен лимит
            async with db.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = ?", (self.id,)
            ) as cursor:
                count = (await cursor.fetchone())[0]

            if count > MAX_STORAGE:
                # Удаляем самые старые сообщения, оставляя только MAX_STORAGE последних
                await db.execute(
                    """
                    DELETE FROM messages
                    WHERE user_id = ?
                    AND id NOT IN (
                        SELECT id FROM messages
                        WHERE user_id = ?
                        ORDER BY id DESC
                        LIMIT ?
                    )
                    """,
                    (self.id, self.id, MAX_STORAGE),
                )

            await db.commit()

    async def get_context_for_llm(self):
        """
        Возвращает сообщения для отправки в LLM с учетом active_messages_count:
        - NULL: возвращает последние MAX_CONTEXT сообщений
        - 0: возвращает пустой список (забыть всё)
        - N: возвращает последние N сообщений (но не больше MAX_CONTEXT)
        """
        async with aiosqlite.connect(DATABASE_NAME) as db:
            # Определяем сколько сообщений нужно получить
            if self.active_messages_count == 0:
                # Забыть всё
                return []
            if self.active_messages_count is None:
                # Все сообщения (но не больше MAX_CONTEXT)
                limit = MAX_CONTEXT
            else:
                # Последние N сообщений (но не больше MAX_CONTEXT)
                limit = min(self.active_messages_count, MAX_CONTEXT)

            # Получаем сообщения
            async with db.execute(
                """
                SELECT role, content, timestamp
                FROM messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (self.id, limit),
            ) as cursor:
                rows = await cursor.fetchall()

            # Переворачиваем список (самые старые сначала)
            return [
                {"role": row[0], "content": row[1], "timestamp": row[2]}
                for row in reversed(rows)
            ]

    async def update_in_db(self):
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            sql_query = """
                UPDATE conversations
                SET name = ?, active_messages_count = ?, subscription_verified = ?, referral_code = ?
                WHERE id = ?
            """
            values = (
                self.name,
                self.active_messages_count,
                self.subscription_verified,
                self.referral_code,
                self.id,
            )
            await cursor.execute(sql_query, values)
            await db.commit()
            await cursor.close()

    async def delete_from_db(self):
        """Удаляет беседу и все её сообщения из базы данных."""
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()

            # Удаляем сообщения беседы
            await cursor.execute("DELETE FROM messages WHERE user_id = ?", (self.id,))

            # Удаляем саму беседу
            await cursor.execute("DELETE FROM conversations WHERE id = ?", (self.id,))

            await db.commit()
            await cursor.close()


class ChatVerification:
    """
    Класс для хранения информации о верификации чата.
    Чат считается верифицированным, если хотя бы один участник подтвердил подписку.
    """

    def __init__(
        self,
        chat_id: int,
        verified_by_user_id: int = None,
        verified_at: str = None,
        user_name: str = None,
    ):
        self.chat_id = chat_id  # Отрицательный ID чата
        self.verified_by_user_id = (
            verified_by_user_id  # ID пользователя, который подтвердил
        )
        self.verified_at = verified_at  # Дата верификации
        self.user_name = user_name  # Имя верификатора

    def __repr__(self):
        return f"ChatVerification(chat_id={self.chat_id}, verified_by={self.verified_by_user_id}, at={self.verified_at})"

    async def get_from_db(self):
        """Загружает информацию о верификации чата из БД."""
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            await cursor.execute(
                "SELECT chat_id, verified_by_user_id, verified_at, user_name FROM chat_verifications WHERE chat_id = ?",
                (self.chat_id,),
            )
            row = await cursor.fetchone()
            if row:
                self.chat_id = row[0]
                self.verified_by_user_id = row[1]
                self.verified_at = row[2]
                self.user_name = row[3]
                return True
            return False

    async def save_to_db(self):
        """Сохраняет информацию о верификации чата в БД."""
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            await cursor.execute(
                """
                INSERT OR REPLACE INTO chat_verifications (chat_id, verified_by_user_id, verified_at, user_name)
                VALUES (?, ?, ?, ?)
                """,
                (
                    self.chat_id,
                    self.verified_by_user_id,
                    self.verified_at,
                    self.user_name,
                ),
            )
            await db.commit()
            await cursor.close()

    async def delete_from_db(self):
        """Удаляет информацию о верификации чата из БД."""
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            await cursor.execute(
                "DELETE FROM chat_verifications WHERE chat_id = ?", (self.chat_id,)
            )
            await db.commit()
            await cursor.close()

    @staticmethod
    async def is_chat_verified(chat_id: int) -> bool:
        """
        Проверяет, верифицирован ли чат.

        Args:
            chat_id: ID чата (отрицательное число)

        Returns:
            True если чат верифицирован, False иначе
        """
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            await cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM chat_verifications WHERE chat_id = ?)",
                (chat_id,),
            )
            result = (await cursor.fetchone())[0]
            await cursor.close()
        return bool(result)


async def delete_chat_data(chat_id: int):
    """
    Удаляет все данные чата из БД (верификацию, сообщения, пользователя).

    Args:
        chat_id: ID чата (отрицательное число)
    """
    from config import logger

    async with aiosqlite.connect(DATABASE_NAME) as db:
        cursor = await db.cursor()

        # Удаляем верификацию чата
        await cursor.execute(
            "DELETE FROM chat_verifications WHERE chat_id = ?", (chat_id,)
        )
        logger.debug(f"CHAT{chat_id}: верификация удалена из БД")

        # Удаляем все сообщения чата
        await cursor.execute("DELETE FROM messages WHERE user_id = ?", (chat_id,))
        logger.debug(f"CHAT{chat_id}: сообщения удалены из БД")

        # Удаляем запись о чате из таблицы conversations (если есть)
        await cursor.execute("DELETE FROM conversations WHERE id = ?", (chat_id,))
        logger.debug(f"CHAT{chat_id}: запись беседы удалена из БД")

        await db.commit()
        await cursor.close()

    logger.info(f"CHAT{chat_id}: все данные удалены из БД")


async def check_db():
    async with aiosqlite.connect(DATABASE_NAME) as db:
        async with db.cursor() as cursor:
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    active_messages_count INTEGER,
                    subscription_verified INTEGER,
                    referral_code TEXT DEFAULT NULL
                )
                """
            )
        await db.commit()
        return "Бд подгружена успешно"


async def user_exists(user_id):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        cursor = await db.cursor()
        sql = "SELECT EXISTS(SELECT 1 FROM conversations WHERE id = ?)"
        await cursor.execute(sql, (user_id,))
        result = (await cursor.fetchone())[0]
        await cursor.close()
    await db.close()

    return bool(result)


async def main():
    print(await Conversation.get_ids_from_table())


if __name__ == "__main__":
    asyncio.run(main())
