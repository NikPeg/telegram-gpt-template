import asyncio
from datetime import datetime, timezone, timedelta
import json
import logging
import logging.handlers
import os
import signal

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Filter
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from llm_client import send_request_to_openrouter

import telegramify_markdown 
from telegramify_markdown import customize

import database  
from database import User


load_dotenv()
TG_TOKEN = os.environ.get("TG_TOKEN")
LLM_TOKEN = os.environ.get("LLM_TOKEN")
DEBUG = bool(int(os.environ.get("DEBUG")))
DEBUG_CHAT = int(os.environ.get("DEBUG_CHAT"))
DATABASE_NAME = os.environ.get("DATABASE_NAME")
TABLE_NAME = os.environ.get("TABLE_NAME")
DELAYED_REMINDERS_HOURS = int(os.environ.get("DELAYED_REMINDERS_HOURS"))
DELAYED_REMINDERS_MINUTES = int(os.environ.get("DELAYED_REMINDERS_MINUTES"))
TIMEZONE_OFFSET = int(os.environ.get("TIMEZONE_OFFSET"))
FROM_TIME = int(os.environ.get("FROM_TIME"))
TO_TIME = int(os.environ.get("TO_TIME"))
ADMIN_LIST_STR = os.environ.get("ADMIN_LIST")
if ADMIN_LIST_STR:
    ADMIN_LIST = list(map(int, ADMIN_LIST_STR.split(",")))
else:
    ADMIN_LIST = set()

with open("config/prompts.json", encoding="utf-8") as ofile:
    PROMPTS = json.load(ofile)
    DEFAULT_PROMPT = PROMPTS["DEFAULT_PROMPT"]
    REMINDER_PROMPT = PROMPTS["REMINDER_PROMPT"]
with open("config/messages.json", encoding="utf-8") as ofile:
    MESSAGES = json.load(ofile)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
fh = logging.handlers.RotatingFileHandler(
    "debug.log", maxBytes=1024 * 1024, backupCount=5, encoding="utf8"
)
fh.setLevel(logging.DEBUG)  #
formatter_console = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter_console)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
fh.setFormatter(formatter)
logger.addHandler(ch)
logger.addHandler(fh)

customize.strict_markdown = True
customize.cite_expandable = True


bot = Bot(token=TG_TOKEN)
dp = Dispatcher()


class ADMINKA_despatch(StatesGroup):
    adminka_input_id = State()
    adminka_input_text = State()
    
class ADMINKA_despatch_all(StatesGroup):
    adminka_input_text = State()

class UserNotInDB(Filter):
    async def __call__(self, message: types.Message) -> bool:
        user_id = message.chat.id
        return not await database.user_exists(user_id)


class UserHaveSubLevel(Filter):
    def __init__(self, required_sub_lvl: int):
        self.required_sub_lvl = required_sub_lvl

    async def __call__(self, message: types.Message) -> bool:
        user = User(message.chat.id)
        await user.get_from_db()

        if user:
            return user.sub_lvl >= self.required_sub_lvl
        else:
            return False


class UserIsAdmin(Filter):
    async def __call__(self, message: types.Message) -> bool:
        if message.chat.id in ADMIN_LIST:
            return True
        else:
            False
        


class OldMessage(Filter):
    async def __call__(self, message: types.Message) -> bool:
        now = datetime.now(tz=timezone.utc)
        message_time = message.date.replace(tzinfo=timezone.utc)
        time_difference = now - message_time
        return time_difference >= timedelta(minutes=1)


async def keep_typing(chat_id):
    """
    Периодически показывает статус "печатает..." для чат-бота.
    """
    for i in range(10):
        await bot.send_chat_action(chat_id=chat_id, action="typing")
        await asyncio.sleep(3)


async def f_debug(message_chat_id, message_id):
    if DEBUG:
        await bot.forward_message(
            chat_id=DEBUG_CHAT, from_chat_id=message_chat_id, message_id=message_id
        )


@dp.message(F.chat.id == DEBUG_CHAT)
async def test(message):
    pass


@dp.message(
    OldMessage()
)  # чтобы не отвечал на сообщения которым больше минуты с момента обработки
async def spam(message):
    pass


@dp.message(UserNotInDB())
async def registration(message):
    args = message.text.split()
    
    if len(args) > 1:
        referral_code = args[1]
        await bot.send_message(DEBUG_CHAT, f"Переход по реф.ссылке, код: {referral_code}")
    user = message.from_user
    if user and user.username != None:
        username = user.username
    else:
        username = "Not_of_registration"
    user = User(int(message.chat.id), username)
    await user.save_for_db()
    builder = ReplyKeyboardBuilder()

    sent_msg = await message.answer(
        MESSAGES["msg_start"], reply_markup=builder.as_markup()
    )
    await f_debug(message.chat.id, message.message_id)
    await f_debug(message.chat.id, sent_msg.message_id)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    sent_msg = await message.answer(
        MESSAGES["msg_start"], reply_markup=ReplyKeyboardRemove()
    )
    await f_debug(message.chat.id, message.message_id)
    await f_debug(message.chat.id, sent_msg.message_id)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    sent_msg = await message.answer(
        MESSAGES["msg_help"], reply_markup=ReplyKeyboardRemove()
    )
    await f_debug(message.chat.id, message.message_id)
    await f_debug(message.chat.id, sent_msg.message_id)


@dp.message(Command("forget"))
async def cmd_forget(message: types.Message):
    sent_msg = await message.answer(
        MESSAGES["msg_forget"], reply_markup=ReplyKeyboardRemove()
    )
    user = User(message.chat.id)
    await user.get_from_db()
    user.remind_of_yourself = "0"
    user.prompt = []
    await user.update_in_db()

    await f_debug(message.chat.id, message.message_id)
    await f_debug(message.chat.id, sent_msg.message_id)

@dp.message(ADMINKA_despatch.adminka_input_text)
async def cmd_dispatch_input_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    id = data.get("id")
    try:
        await bot.send_message(int(id), text = message.text)
    except Exception as e:
        await bot.send_message(
            DEBUG_CHAT, f"LLM{message.chat.id} - ошибка при отправке {e}. Вы в главном меню"
        )
        await message.answer(f"LLM{message.chat.id} - ошибка при отправке {e}. Вы в главном меню")
        await state.clear() 
        return
    await message.answer(MESSAGES["adminka_dispatch3"])
    await state.clear() 

@dp.message(ADMINKA_despatch.adminka_input_id)
async def cmd_dispatch_input_id(message: types.Message, state: FSMContext):
    user_input = message.text
    await state.update_data(id=user_input)
    await message.answer(MESSAGES["adminka_dispatch2"])
    await state.set_state(ADMINKA_despatch.adminka_input_text)

@dp.message(UserIsAdmin(), Command("dispatch"))
async def cmd_dispatch(message: types.Message, state: FSMContext):
    sent_msg = await message.answer(
        MESSAGES["adminka_dispatch1"], reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(ADMINKA_despatch.adminka_input_id)

@dp.message(ADMINKA_despatch_all.adminka_input_text)
async def cmd_dispatch_all_input_text(message: types.Message, state: FSMContext):
    try:
        all_ids = await User.get_ids_from_table()
        success_dispatch = 0
        for id in all_ids:
            try:
                await bot.send_message(id, message.text)
                success_dispatch = success_dispatch + 1
            except:
                continue
        await bot.send_message(
            DEBUG_CHAT, f"Сообщение отправлено {success_dispatch} пользователям"
        )
        await bot.send_message(
            message.chat.id, f"Сообщение отправлено {success_dispatch} пользователям"
        )
    except Exception as e:
        await bot.send_message(
            DEBUG_CHAT, f"USER{message.chat.id} - ошибка при отправке {e}. Вы в главном меню"
        )
        await message.answer(f"USER{message.chat.id} - ошибка при отправке {e}. Вы в главном меню")
        await state.clear() 
        return
    await message.answer(MESSAGES["adminka_dispatch3"])
    await state.clear() 

@dp.message(UserIsAdmin(), Command("dispatch_all"))
async def cmd_dispatch_all(message: types.Message, state: FSMContext):
    sent_msg = await message.answer(
        MESSAGES["adminka_dispatch_all"], reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(ADMINKA_despatch_all.adminka_input_text)


@dp.message(Command("reminder"))
async def cmd_reminder(message: types.Message):
    sent_msg = await message.answer(
        MESSAGES["msg_reminder"], reply_markup=ReplyKeyboardRemove()
    )
    user = User(message.chat.id)
    await user.get_from_db()
    user.remind_of_yourself = "0"
    await user.update_in_db()
    await f_debug(message.chat.id, message.message_id)
    await f_debug(message.chat.id, sent_msg.message_id)


@dp.message(F.text)
async def LLM_request(message: types.Message):
    if DEBUG:
        await bot.send_message(DEBUG_CHAT, f"USER{message.chat.id}:")
    logger.info(f"USER{message.chat.id}TOLLM:{message.text}")
    await f_debug(message.chat.id, message.message_id)
    typing_task = asyncio.create_task(keep_typing(message.chat.id))
    user = User(message.chat.id)
    await user.get_from_db()
    await user.update_prompt("user", message.text)
    prompt_for_request = user.prompt.copy()
    prompt_for_request.append({"role": "system", "content": DEFAULT_PROMPT.replace("{CURRENTDATE}", datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S"))})

    try:
        llm_msg = await send_request_to_openrouter(prompt_for_request)
    except Exception as e:
        await bot.send_message(DEBUG_CHAT, f"LLM{message.chat.id} - Критическая ошибка: {e}")
        await message.answer("Прости, твое сообщение вызвало у меня ошибку(( Пожалуйста попробуй снова")
        return

    if llm_msg is None or llm_msg.strip() == "":
        await bot.send_message(DEBUG_CHAT, f"LLM{message.chat.id} - пустой ответ от LLM")
        await message.answer("Прости, твое сообщение вызвало у меня ошибку(( Пожалуйста попробуй снова")
        return

    await user.update_prompt("assistant", llm_msg)
    logger.debug(f"LLM_RAWOUTPUT{message.chat.id}:{llm_msg}")

    converted = telegramify_markdown.markdownify(
        llm_msg,
        max_line_length=None,
        normalize_whitespace=False,
    )

    try:
        start = 0
        while start < len(converted):
            chunk = converted[start:start + 4096]
            generated_message = await message.answer(chunk, parse_mode=ParseMode.MARKDOWN_V2)
            start += 4096
            await f_debug(message.chat.id, generated_message.message_id)
    except TelegramForbiddenError:
        user.remind_of_yourself = 0
        await user.update_in_db()
        await bot.send_message(DEBUG_CHAT, f"USER{id} заблокировал чатбота")
        typing_task.cancel()
        return
    except Exception as e:
        start = 0
        while start < len(llm_msg):
            chunk = converted[start:start + 4096]
            generated_message = await message.answer(chunk, parse_mode=ParseMode.MARKDOWN_V2)
            start += 4096
            await f_debug(message.chat.id, generated_message.message_id)
        await bot.send_message(DEBUG_CHAT, f"LLM{message.chat.id} - {e}")
        typing_task.cancel()
    typing_task.cancel()
    user.remind_of_yourself = await database.time_after(
        DELAYED_REMINDERS_HOURS,
        DELAYED_REMINDERS_MINUTES,
        TIMEZONE_OFFSET,
        FROM_TIME,
        TO_TIME,
    )
    await user.update_in_db()
    
    logger.info(f"LLM{message.chat.id} - {converted}")

@dp.message()
async def unknown_message(message: types.Message):
    await message.answer(MESSAGES["unknown_message"])

async def reminder():
    for id in await database.get_past_dates():
        user = User(id)
        await user.get_from_db()
        if user.prompt:
            if len(user.prompt) >= 2:
                if user.prompt[-2]["role"] == "assistant":
                    if user.prompt[-1]["role"] == "assistant":
                        user.prompt.pop()
        prompt_for_request = user.prompt.copy()
        prompt_for_request.append({"role": "system", "content": REMINDER_PROMPT.replace("{CURRENTDATE}", datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S"))})
        prompt_for_request.insert(0, ({"role": "system", "content": DEFAULT_PROMPT}))
        try:
            llm_msg = await send_request_to_openrouter(prompt_for_request)
        except Exception as e:
            await bot.send_message(DEBUG_CHAT, f"LLM{id} - Критическая ошибка: {e}")
        if llm_msg is None or llm_msg.strip() == "":
            await bot.send_message(DEBUG_CHAT, f"LLM{id} - пустой ответ от LLM")
            return
        await user.update_prompt("assistant", llm_msg)

        logger.debug(f"LLM_RAWOUTPUT{id}:{llm_msg}")

        converted = telegramify_markdown.markdownify(
            llm_msg,
            max_line_length=None,
            normalize_whitespace=False,
        )

        try:
            start = 0
            while start < len(converted):
                chunk = converted[start:start + 4096]
                generated_message = await bot.send_message(
                    chat_id=id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                start += 4096
                await f_debug(id, generated_message.message_id)
        except TelegramForbiddenError:
            user.remind_of_yourself = 0
            await user.update_in_db()
            await bot.send_message(DEBUG_CHAT, f"USER{id} заблокировал чатбота")
            return
        except Exception as e:
            await bot.send_message(DEBUG_CHAT, f"LLM{id} - {e}")
            logger.error(f"LLM{id} - {e}")
            start = 0
            while start < len(converted):
                chunk = converted[start:start + 4096]
                generated_message = await bot.send_message(
                    chat_id=id,
                    text=chunk,
                )
                start += 4096
                await f_debug(id, generated_message.message_id)
        user.remind_of_yourself = await database.time_after(
            DELAYED_REMINDERS_HOURS,
            DELAYED_REMINDERS_MINUTES,
            TIMEZONE_OFFSET,
            FROM_TIME,
            TO_TIME,
        )
        await user.update_in_db()
        logger.info(f"LLM{id}REMINDER - {generated_message.text}")


async def reminder_loop():
    """Отдельная задача для напоминаний"""
    while True:
        try:
            await reminder()
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            print("Цикл напоминаний остановлен")
            break
        except Exception as e:
            logger.error(f"Ошибка в цикле напоминаний: {e}")
            await asyncio.sleep(30)


async def main():
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
        try:
            await reminder_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        print("✅ Бот остановлен")  


async def run_with_restart():
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
