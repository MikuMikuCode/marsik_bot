import aiosqlite
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import ConversationHandler, MessageHandler, filters, CallbackQueryHandler, CommandHandler, ContextTypes

from balance_utils import get_user_balance

NAME, POSITION = range(2)

def register_profile_handlers(app, DB_PATH):
    async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT name, position FROM users WHERE telegram_id = ?",
                (update.effective_user.id,)
            ) as cursor:
                row = await cursor.fetchone()
                name, position = row if row else ("Не задано", "Не задано")
            balance = await get_user_balance(db, update.effective_user.id)

        text = f"Имя: {name}\nДолжность: {position}\nБаланс: {balance} MT"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Изменить", callback_data="edit_profile")]])

        # Отправляем изображение профиля с подписью
        await update.message.reply_photo(
            photo="https://i.postimg.cc/d1VhCQ72/Profil'.png",
            caption=text,
            reply_markup=keyboard
        )

    async def start_edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.message.reply_text("Введите имя:")
        return NAME

    async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["name"] = update.message.text
        await update.message.reply_text("Введите должность:")
        return POSITION

    async def get_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
        position = update.message.text
        name = context.user_data["name"]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET name = ?, position = ? WHERE telegram_id = ?", 
                (name, position, update.effective_user.id)
            )
            await db.commit()
        await update.message.reply_text("Профиль обновлён ✅")
        return ConversationHandler.END

    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Действие отменено")
        return ConversationHandler.END

    # --- ConversationHandler для редактирования профиля ---
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_edit_profile, pattern="edit_profile")],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            POSITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_position)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(conv)

    # --- Обработчик для отображения профиля ---
    app.add_handler(MessageHandler(filters.Regex("Профиль"), show_profile))
