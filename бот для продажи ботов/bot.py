import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, MenuButtonCommands, BotCommand
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

from config import BOT_TOKEN, DATABASE_URL, BOT_USERNAME, hashids, ADMIN_IDS, FEEDBACK_CHANNEL_ID

# ---------- СОСТОЯНИЯ FSM ----------
class FeedbackStates(StatesGroup):
    waiting_for_feedback = State()
    waiting_for_order = State()

# ---------- БАЗА ДАННЫХ ----------
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String)
    full_name = Column(String)
    subscribed_warming = Column(Boolean, default=True)
    referrer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# ---------- MIDDLEWARE ----------
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit=0.5):
        self.rate_limit = rate_limit
        self.last_time = defaultdict(float)

    async def __call__(self, handler, event, data):
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        if user_id:
            now = time.time()
            if now - self.last_time[user_id] < self.rate_limit:
                return
            self.last_time[user_id] = now
        return await handler(event, data)

# ---------- КЛАВИАТУРЫ ----------
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[

        [InlineKeyboardButton(text="🔗 Реферальная программа", callback_data="referral")],
        [InlineKeyboardButton(text="🤖 Заказать бота", callback_data="order_bot")],
        [InlineKeyboardButton(text="✍️ Оставить отзыв", callback_data="feedback")],
        [InlineKeyboardButton(text="💬 Написать создателю", url=f"https://t.me/Mark212935")],
    ])

def back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def referral_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

# ---------- РЕФЕРАЛЫ ----------
def generate_referral_link(user_id: int) -> str:
    code = hashids.encode(user_id)
    return f"https://t.me/{BOT_USERNAME}?start={code}"

def decode_referral_code(code: str) -> int | None:
    decoded = hashids.decode(code)
    return decoded[0] if decoded else None

async def get_referral_stats(user_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.referrer_id == user_id))
        referrals = result.scalars().all()
        count = len(referrals)
        bonus = count * 10
        return {"count": count, "bonus": bonus}

# ---------- ОБРАБОТЧИКИ ----------
dp = Dispatcher(storage=MemoryStorage())

@dp.message(Command("start"))
async def start_command(message: Message):
    args = message.text.split()
    referrer_id = None
    if len(args) > 1:
        referrer_id = decode_referral_code(args[1])

    async with AsyncSessionLocal() as session:
        # Проверяем, есть ли пользователь в базе
        stmt = select(User).where(User.telegram_id == message.from_user.id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            # Новый пользователь — создаём
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
                referrer_id=referrer_id
            )
            session.add(user)
        else:
            # Существующий — обновляем данные и активность
            user.username = message.from_user.username
            user.full_name = message.from_user.full_name
            user.last_active = datetime.utcnow()
            # referrer_id не меняем при повторном /start

        await session.commit()

    await message.answer(
        f"👋 Привет, {message.from_user.full_name}!\nВыберите действие:",
        reply_markup=main_menu_keyboard()
    )

@dp.message(Command("broadcast"))
async def broadcast_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У вас нет прав для этой команды.")
        return
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("Укажите текст рассылки: /broadcast текст")
        return
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
        success_count = 0
        fail_count = 0
        for user in users:
            try:
                await message.bot.send_message(user.telegram_id, text)
                success_count += 1
            except Exception as e:
                fail_count += 1
                print(f"Не удалось отправить {user.telegram_id}: {e}")
        await message.answer(f"Рассылка завершена: отправлено {success_count}, неудачно {fail_count}.")

@dp.message(Command("reply"))
async def reply_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У вас нет прав для этой команды.")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Формат: /reply @username текст или /reply user_id текст")
        return
    target = args[1]
    text = args[2]
    user_id = None
    if target.startswith('@'):
        username = target[1:]  # убираем @
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
            if user:
                user_id = user.telegram_id
            else:
                await message.answer(f"Пользователь @{username} не найден.")
                return
    else:
        try:
            user_id = int(target)
        except ValueError:
            await message.answer("Неверный формат: укажите @username или user_id.")
            return
    try:
        await message.bot.send_message(user_id, f"Ответ от администратора:\n{text}")
        await message.answer("Ответ отправлен.")
    except Exception:
        await message.answer("Не удалось отправить.")

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "referral")
async def referral_menu(callback: CallbackQuery):
    stats = await get_referral_stats(callback.from_user.id)
    link = generate_referral_link(callback.from_user.id)
    text = (
        f"🔗 Ваша реферальная ссылка:\n`{link}`\n\n"
        f"👥 Приглашено: {stats['count']}\n"
        f"🎁 Бонусов: {stats['bonus']}"
    )
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=referral_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "feedback")
async def feedback_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("✍️ Напишите ваш отзыв одним сообщением:", reply_markup=back_keyboard())
    await state.set_state(FeedbackStates.waiting_for_feedback)
    await callback.answer()

@dp.callback_query(F.data == "order_bot")
async def order_bot_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🤖 Опишите, какой бот вам нужен (функции, платформа и т.д.):", reply_markup=back_keyboard())
    await state.set_state(FeedbackStates.waiting_for_order)
    await callback.answer()

@dp.message(FeedbackStates.waiting_for_feedback)
async def process_feedback(message: Message, state: FSMContext):
    feedback_text = message.text
    # Отправляем отзыв администраторам
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, f"Новый отзыв от {message.from_user.full_name} (@{message.from_user.username}):\n{feedback_text}")
        except Exception as e:
            print(f"Не удалось отправить отзыв админу {admin_id}: {e}")
    # Отправляем в канал обратной связи, если указан
    if FEEDBACK_CHANNEL_ID:
        try:
            await message.bot.send_message(FEEDBACK_CHANNEL_ID, f"Новый отзыв от {message.from_user.full_name} (@{message.from_user.username}):\n{feedback_text}")
        except Exception as e:
            print(f"Не удалось отправить в канал: {e}")
    await message.answer("Спасибо за ваш отзыв! Он отправлен администраторам.")
    await state.clear()

@dp.message(FeedbackStates.waiting_for_order)
async def process_order(message: Message, state: FSMContext):
    order_text = message.text
    # Отправляем заказ администраторам
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, f"Новый заказ на бота от {message.from_user.full_name} (@{message.from_user.username}):\n{order_text}")
        except Exception as e:
            print(f"Не удалось отправить заказ админу {admin_id}: {e}")
    await message.answer("Спасибо! Ваш заказ отправлен создателю. Ожидайте ответа.")
    await state.clear()

async def warming_scheduler(bot: Bot):
    while True:
        await asyncio.sleep(86400)
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.subscribed_warming == True))
            users = result.scalars().all()
            for user in users:
                try:
                    await bot.send_message(user.telegram_id, "🔥 Ежедневный прогрев: Не забудьте воспользоваться ботом!")
                except Exception:
                    pass

# ---------- ЗАПУСК ----------
async def main():
    await init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp.message.middleware(ThrottlingMiddleware(rate_limit=0.7))
    dp.callback_query.middleware(ThrottlingMiddleware(rate_limit=0.7))
    # Устанавливаем команды меню
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="broadcast", description="Рассылка (только админ)"),
        BotCommand(command="reply", description="Ответить пользователю (только админ)"),
    ]
    await bot.set_my_commands(commands)
    asyncio.create_task(warming_scheduler(bot))
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
