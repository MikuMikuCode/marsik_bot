import aiosqlite
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import MessageHandler, filters, ConversationHandler, CallbackQueryHandler, ContextTypes

CONFIRM_POST, ENTER_TEXT = range(2)

def register_post_handlers(app, DB_PATH):
    # --- Старт публикации ---
    async def start_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id

        # проверяем роль
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT role FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                row = await cursor.fetchone()
                role = row[0] if row else "user"
        if role != "admin":
            await update.message.reply_text("Недостаточно прав.")
            return ConversationHandler.END

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Да", callback_data="post_yes"),
             InlineKeyboardButton("Отмена", callback_data="cancel")]
        ])
        await update.message.reply_text(
            "При публикации пост увидят все пользователи бота. Редактировать после отправки его будет нельзя. Продолжить?",
            reply_markup=keyboard
        )
        return CONFIRM_POST

    # --- Подтверждение публикации ---
    async def confirm_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.message.reply_text(
            "Напишите текст сообщения:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="cancel")]])
        )
        return ENTER_TEXT

    # --- Получение текста поста ---
    async def receive_post_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        await update.message.reply_text("Пост отправляется всем пользователям...")

        # добавляем заголовок "Глобальное сообщение:"
        broadcast_text = f"📢 Глобальное сообщение:\n\n{text}"

        # отправка всем активным пользователям
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT telegram_id FROM users WHERE active=1") as cursor:
                rows = await cursor.fetchall()

        for (user_id,) in rows:
            try:
                await context.bot.send_message(chat_id=user_id, text=broadcast_text)
            except:
                pass  # игнорируем ошибки если пользователь заблокировал бота

        await update.message.reply_text("✅ Пост отправлен всем пользователям.")
        return ConversationHandler.END

    # --- Отмена ---
    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query if update.callback_query else None
        if query:
            await query.answer()
            await query.message.reply_text("Действие отменено.")
        else:
            await update.message.reply_text("Действие отменено.")
        return ConversationHandler.END

    # --- ConversationHandler ---
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("Пост"), start_post)],
        states={
            CONFIRM_POST: [CallbackQueryHandler(confirm_post, pattern="post_yes")],
            ENTER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_post_text)]
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern="cancel")]
    )
    app.add_handler(conv)