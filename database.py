import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import aiosqlite
from dotenv import load_dotenv

load_dotenv()
LLM_TOKEN = os.environ.get("LLM_TOKEN")
DEBUG = bool(os.environ.get("DEBUG"))
ADMIN_CHAT = int(os.environ.get("ADMIN_CHAT") or "0")
DATABASE_NAME = os.environ.get("DATABASE_NAME", "users.db")
TABLE_NAME = os.environ.get("TABLE_NAME", "users")
MAX_CONTEXT = int(os.environ.get("MAX_CONTEXT") or "10")
MAX_STORAGE = int(os.environ.get("MAX_STORAGE", "100"))
DELAYED_REMINDERS_HOURS = int(os.environ.get("DELAYED_REMINDERS_HOURS") or "2")
DELAYED_REMINDERS_MINUTES = int(os.environ.get("DELAYED_REMINDERS_MINUTES") or "0")
TIMEZONE_OFFSET = int(os.environ.get("TIMEZONE_OFFSET") or "3")
FROM_TIME = int(os.environ.get("FROM_TIME") or "9")
TO_TIME = int(os.environ.get("TO_TIME") or "23")


class User:
    def __init__(
        self,
        id,
        name=None,
        prompt=None,
        remind_of_yourself=None,
        sub_lvl=0,
        sub_id=0,
        sub_period=-1,
        is_admin=0,
        active_messages_count=None,
        reminder_times=None,
        subscription_verified=None,
    ):
        if prompt is None:
            prompt = []
        if reminder_times is None:
            reminder_times = ["19:15"]
        self.id = id
        self.name = name
        self.prompt = prompt  # Оставляем для обратной совместимости
        self.remind_of_yourself = remind_of_yourself  # NULL = не отправлялось, "0" = отключено, иначе timestamp
        self.sub_lvl = sub_lvl
        self.sub_id = sub_id
        self.sub_period = sub_period
        self.is_admin = is_admin
        self.active_messages_count = active_messages_count  # NULL = все, 0 = забыть, N = последние N
        self.reminder_times = reminder_times  # Список времен напоминаний в формате HH:MM (МСК)
        self.subscription_verified = subscription_verified  # NULL = не проверялось, 0 = не подписан, 1 = подписан

    def __repr__(self):
        return f"User(id={self.id}, \n name={self.name}, \n prompt={self.prompt}, \n remind_of_yourself={self.remind_of_yourself}, \n sub_lvl={self.sub_lvl}, \n sub_id={self.sub_id}, \n sub_period={self.sub_period}, \n is_admin={self.is_admin})"

    async def get_from_db(self):
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            sql = f"SELECT * FROM {TABLE_NAME} WHERE id = ?"
            await cursor.execute(sql, (self.id,))
            row = await cursor.fetchone()
            if row:
                self.id = row[0]
                self.name = row[1]
                self.prompt = json.loads(row[2])
                self.remind_of_yourself = row[3]
                self.sub_lvl = row[4]
                self.sub_id = row[5]
                self.sub_period = row[6]
                self.is_admin = row[7]
                self.active_messages_count = row[8] if len(row) > 8 else None
                self.reminder_times = json.loads(row[9]) if len(row) > 9 and row[9] else ["19:15"]
                self.subscription_verified = row[10] if len(row) > 10 else None

    async def __call__(self, user_id):
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            sql = f"SELECT * FROM {TABLE_NAME} WHERE id = ?"
            await cursor.execute(sql, (user_id,))
            row = await cursor.fetchone()
            if row:
                return User(
                    id=row[0],
                    name=row[1],
                    prompt=json.loads(row[2]),
                    remind_of_yourself=row[3],
                    sub_lvl=row[4],
                    sub_id=row[5],
                    sub_period=row[6],
                    is_admin=row[7],
                    active_messages_count=row[8] if len(row) > 8 else None,
                    reminder_times=json.loads(row[9]) if len(row) > 9 and row[9] else ["19:15"],
                    subscription_verified=row[10] if len(row) > 10 else None,
                )
            return None

    async def get_ids_from_table():
        async with (
            aiosqlite.connect(DATABASE_NAME) as db,
            db.execute(f"SELECT id FROM {TABLE_NAME}") as cursor,
        ):
            rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def save_for_db(self):
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            sql_insert = f"""
                        INSERT INTO {TABLE_NAME} (id, name, prompt, remind_of_yourself, sub_lvl, sub_id, sub_period, is_admin, active_messages_count, reminder_times, subscription_verified)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
            values = (
                self.id,
                self.name,
                json.dumps(self.prompt),
                self.remind_of_yourself,
                self.sub_lvl,
                self.sub_id,
                self.sub_period,
                self.is_admin,
                self.active_messages_count,
                json.dumps(self.reminder_times),
                self.subscription_verified,
            )
            await cursor.execute(sql_insert, values)
            await db.commit()
            await cursor.close()

    async def update_prompt(self, role, new_request):
        """
        Добавляет новое сообщение в таблицу messages.
        Старые сообщения (больше MAX_STORAGE) автоматически удаляются.
        """
        # Получаем текущее время с учетом часового пояса
        current_time = datetime.now(timezone(timedelta(hours=TIMEZONE_OFFSET)))
        timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")

        async with aiosqlite.connect(DATABASE_NAME) as db:
            # Добавляем новое сообщение
            await db.execute(
                """
                INSERT INTO messages (user_id, role, content, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (self.id, role, new_request, timestamp)
            )

            # Проверяем количество сообщений и удаляем старые, если превышен лимит
            async with db.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = ?",
                (self.id,)
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
                    (self.id, self.id, MAX_STORAGE)
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
                (self.id, limit)
            ) as cursor:
                rows = await cursor.fetchall()

            # Переворачиваем список (самые старые сначала)
            return [
                {
                    "role": row[0],
                    "content": row[1],
                    "timestamp": row[2]
                }
                for row in reversed(rows)
            ]

    async def update_in_db(self):
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            sql_query = f"""
                UPDATE {TABLE_NAME}
                SET name = ?, prompt = ?, remind_of_yourself = ?, sub_lvl = ?, sub_id = ?, sub_period = ?, is_admin = ?, active_messages_count = ?, reminder_times = ?, subscription_verified = ?
                WHERE id = ?
            """
            values = (
                self.name,
                json.dumps(self.prompt),
                self.remind_of_yourself,
                self.sub_lvl,
                self.sub_id,
                self.sub_period,
                self.is_admin,
                self.active_messages_count,
                json.dumps(self.reminder_times),
                self.subscription_verified,
                self.id,
            )
            await cursor.execute(sql_query, values)
            await db.commit()
            await cursor.close()

    async def delete_from_db(self):
        """Удаляет пользователя и все его сообщения из базы данных."""
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()

            # Удаляем сообщения пользователя
            await cursor.execute("DELETE FROM messages WHERE user_id = ?", (self.id,))

            # Удаляем самого пользователя
            await cursor.execute(f"DELETE FROM {TABLE_NAME} WHERE id = ?", (self.id,))

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
        self.verified_by_user_id = verified_by_user_id  # ID пользователя, который подтвердил
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
                (self.chat_id,)
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
                (self.chat_id, self.verified_by_user_id, self.verified_at, self.user_name)
            )
            await db.commit()
            await cursor.close()

    async def delete_from_db(self):
        """Удаляет информацию о верификации чата из БД."""
        async with aiosqlite.connect(DATABASE_NAME) as db:
            cursor = await db.cursor()
            await cursor.execute(
                "DELETE FROM chat_verifications WHERE chat_id = ?",
                (self.chat_id,)
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
                (chat_id,)
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
            "DELETE FROM chat_verifications WHERE chat_id = ?",
            (chat_id,)
        )
        logger.debug(f"CHAT{chat_id}: верификация удалена из БД")

        # Удаляем все сообщения чата
        await cursor.execute(
            "DELETE FROM messages WHERE user_id = ?",
            (chat_id,)
        )
        logger.debug(f"CHAT{chat_id}: сообщения удалены из БД")

        # Удаляем запись о чате из таблицы users (если есть)
        await cursor.execute(
            "DELETE FROM users WHERE id = ?",
            (chat_id,)
        )
        logger.debug(f"CHAT{chat_id}: запись пользователя удалена из БД")

        await db.commit()
        await cursor.close()

    logger.info(f"CHAT{chat_id}: все данные удалены из БД")


async def check_db():
    async with aiosqlite.connect(DATABASE_NAME) as db:
        async with db.cursor() as cursor:
            await cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    id INTEGER PRIMARY KEY,  --  ID is now the PRIMARY KEY and NOT AUTOINCREMENT
                    name TEXT,
                    prompt JSON,
                    remind_of_yourself TEXT,
                    sub_lvl INTEGER,
                    sub_id TEXT,
                    sub_period INTEGER,
                    is_admin INTEGER
                )
                """
            )
        await db.commit()
        return "Бд подгружена успешно"


async def user_exists(user_id):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        cursor = await db.cursor()
        sql = f"SELECT EXISTS(SELECT 1 FROM {TABLE_NAME} WHERE id = ?)"
        await cursor.execute(sql, (user_id,))
        result = (await cursor.fetchone())[0]
        await cursor.close()
    await db.close()

    return bool(result)


async def get_past_dates():
    """
    Получает список пользователей, которым нужно отправить напоминание.
    Проверяет, наступило ли время из списка reminder_times для ежедневных напоминаний.

    Логика:
    - remind_of_yourself = "0" -> напоминания отключены
    - remind_of_yourself = NULL -> еще не отправлялось, можно отправить
    - remind_of_yourself = timestamp -> проверяем, что прошел минимум 1 час

    Returns:
        Список user_id пользователей, которым нужно отправить напоминание
    """
    from config import logger

    past_user_ids = []
    async with aiosqlite.connect(DATABASE_NAME) as db:
        async with db.execute("PRAGMA journal_mode=WAL;") as cursor:
            await cursor.fetchone()

        # Получаем текущее время в МСК
        now_msk = datetime.now(timezone(timedelta(hours=TIMEZONE_OFFSET)))
        current_hour = now_msk.hour
        current_minute = now_msk.minute

        logger.debug(f"Текущее время МСК: {now_msk.strftime('%Y-%m-%d %H:%M:%S')} ({current_hour:02d}:{current_minute:02d})")

        query = f"SELECT id, reminder_times, remind_of_yourself FROM {TABLE_NAME}"

        async with db.execute(query) as cursor:
            results = await cursor.fetchall()

        logger.debug(f"Всего пользователей в БД: {len(results)}")

        for row in results:
            user_id = row[0]
            reminder_times_json = row[1]
            remind_of_yourself = row[2]

            # Пропускаем пользователей с отключенными напоминаниями
            if remind_of_yourself == "0":
                logger.debug(f"USER{user_id}: напоминания отключены")
                continue

            # Парсим список времен напоминаний
            try:
                reminder_times = json.loads(reminder_times_json) if reminder_times_json else ["19:15"]
            except json.JSONDecodeError:
                reminder_times = ["19:15"]

            logger.debug(f"USER{user_id}: времена напоминаний {reminder_times}, последнее: {remind_of_yourself}")

            # Проверяем, наступило ли одно из времен напоминаний
            for reminder_time in reminder_times:
                try:
                    reminder_hour, reminder_minute = map(int, reminder_time.split(":"))

                    # Проверяем, что текущее время находится в пределах 15 минут от времени напоминания
                    # (так как проверка происходит каждые 15 минут)
                    time_diff = (current_hour * 60 + current_minute) - (reminder_hour * 60 + reminder_minute)

                    # Если время напоминания наступило (в пределах последних 15 минут)
                    if 0 <= time_diff < 15:
                        logger.debug(f"USER{user_id}: время {reminder_time} подходит (разница: {time_diff} мин)")

                        # Проверяем, можно ли отправить напоминание
                        can_send = False

                        if remind_of_yourself is None:
                            # Еще никогда не отправлялось
                            logger.debug(f"USER{user_id}: еще не получал напоминаний")
                            can_send = True
                        else:
                            # Пытаемся распарсить timestamp
                            try:
                                last_reminder = datetime.strptime(remind_of_yourself, "%Y-%m-%d %H:%M:%S")
                                time_since_last = (now_msk.replace(tzinfo=None) - last_reminder).total_seconds()

                                # Минимум 1 час между напоминаниями (чтобы избежать дублей в одном временном окне)
                                if time_since_last >= 3600:
                                    logger.debug(f"USER{user_id}: прошло {int(time_since_last/60)} мин с последнего")
                                    can_send = True
                                else:
                                    logger.debug(f"USER{user_id}: недавно отправлялось ({int(time_since_last/60)} мин назад)")
                            except (ValueError, TypeError) as e:
                                # Некорректный формат - считаем что можно отправить
                                logger.warning(f"USER{user_id}: некорректный формат времени '{remind_of_yourself}': {e}")
                                can_send = True

                        if can_send:
                            logger.info(f"USER{user_id}: добавлен в очередь на отправку (время {reminder_time})")
                            past_user_ids.append(user_id)
                            break  # Нашли подходящее время, выходим из цикла

                except (ValueError, AttributeError) as e:
                    logger.debug(f"USER{user_id}: ошибка при обработке времени {reminder_time}: {e}")
                    continue

    return past_user_ids


async def main():
    print(await User.get_ids_from_table())


if __name__ == "__main__":
    asyncio.run(main())
