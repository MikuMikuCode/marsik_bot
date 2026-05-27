import os
import asyncio
import aiosqlite
from telegram import ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler

from config import BOT_TOKEN

from profile import register_profile_handlers
from rewards import register_rewards_handlers
from balance import register_balance_handlers
from statistics import register_statistics_handlers
from post import register_post_handlers
from favorites import register_favorites_handlers 
from stickers import register_sticker_handlers

DB_PATH = os.path.join(os.path.dirname(__file__), "marsik_bot.db")

# --- Создание приложения ---
app = ApplicationBuilder().token(BOT_TOKEN).build()

# --- Инициализация базы данных ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                tg_tag TEXT UNIQUE,
                role TEXT DEFAULT 'user',
                name TEXT,
                position TEXT,
                balance INTEGER DEFAULT 0,
                active BOOLEAN DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rewards (
                name TEXT PRIMARY KEY,
                description TEXT,
                cost INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                owner_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY (owner_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                actor_tag TEXT,
                target_tag TEXT,
                amount INTEGER NOT NULL,
                comment TEXT
            )
        """)
        await db.commit()

asyncio.run(init_db())

# --- /start с динамическим меню ---
async def start(update, context):
    telegram_id = update.effective_user.id
    tg_tag = f"@{update.effective_user.username}" if update.effective_user.username else None
    first_name = update.effective_user.first_name

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (telegram_id, tg_tag, name) VALUES (?, ?, ?)",
            (telegram_id, tg_tag, first_name)
        )
        await db.commit()
        async with db.execute("SELECT role FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            role = row[0] if row else "user"

    # --- формируем клавиатуру ---
    buttons = ["Награды", "Профиль"]
    if role in ["senior_user", "admin"]:
        buttons.append("Баллы")
        buttons.append("Статистика")
    if role == "admin":
        buttons.append("Пост")

    keyboard = ReplyKeyboardMarkup([buttons], resize_keyboard=True)
    await update.message.reply_text(f"Привет, {first_name}! Выбери действие:", reply_markup=keyboard)

app.add_handler(CommandHandler("start", start))

# --- Подключение всех вкладок ---
register_profile_handlers(app, DB_PATH)      # Профиль
register_rewards_handlers(app, DB_PATH)      # Награды
register_balance_handlers(app, DB_PATH)      # Баланс
register_favorites_handlers(app, DB_PATH)    
register_statistics_handlers(app, DB_PATH)   # Статистика
register_post_handlers(app, DB_PATH)         # Пост для админов
register_sticker_handlers(app)               # Ответ случайным стикером

# --- Запуск бота ---
app.run_polling()
