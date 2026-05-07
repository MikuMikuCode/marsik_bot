import aiosqlite
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes, CommandHandler

CHANGE_TAGS = 0

def register_statistics_handlers(app, DB_PATH):

    async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT role FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                row = await cursor.fetchone()
                role = row[0] if row else "user"
        if role not in ["senior_user", "admin"]:
            await update.message.reply_text("Недостаточно прав.")
            return

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name, tg_tag, balance FROM users ORDER BY balance DESC LIMIT 5") as cursor:
                rows = await cursor.fetchall()

        text = "🏆 Топ 5 пользователей по Марсикам:\n\n"
        for i, (name, tg_tag, balance) in enumerate(rows, 1):
            text += f"{i}. {name} | {tg_tag} — {balance} MT\n"

        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Конкретный пользователь", callback_data="user_stats")]])
        await update.message.reply_text(text, reply_markup=keyboard)

    async def user_stats_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="cancel")]])
        await query.message.reply_text("Введите тег пользователя (например @user1):", reply_markup=keyboard)
        return CHANGE_TAGS

    async def user_stats_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE):
        tag = update.message.text.strip()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name, tg_tag, position, balance FROM users WHERE tg_tag = ?", (tag,)) as cursor:
                row = await cursor.fetchone()
        if not row:
            await update.message.reply_text("Пользователь не найден или тег введен неверно.")
            return ConversationHandler.END
        name, tg_tag, position, balance = row
        text = f"📊 Статистика пользователя:\nИмя: {name}\nТег: {tg_tag}\nДолжность: {position}\nБаланс: {balance} MT"
        await update.message.reply_text(text)
        return ConversationHandler.END

    async def cancel_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query if update.callback_query else None
        if query:
            await query.answer()
            await query.message.reply_text("Действие отменено.")
        else:
            await update.message.reply_text("Действие отменено.")
        return ConversationHandler.END

    # --- ConversationHandler для конкретного пользователя ---
    stats_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(user_stats_start, pattern="user_stats")],
        states={
            CHANGE_TAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_stats_fetch)]
        },
        fallbacks=[CallbackQueryHandler(cancel_stats, pattern="cancel")]
    )

    app.add_handler(MessageHandler(filters.Regex("Статистика"), show_statistics))
    app.add_handler(stats_conv)