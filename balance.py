import aiosqlite
from telegram import Update
from telegram.ext import MessageHandler, filters, ConversationHandler, CommandHandler, ContextTypes

CHANGE_TAGS, CHANGE_AMOUNT, CHANGE_REASON = range(3)

def register_balance_handlers(app, DB_PATH):
    async def change_balance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT role FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                role = (await cursor.fetchone())[0]
        if role not in ["senior_user", "admin"]:
            await update.message.reply_text("Недостаточно прав.")
            return ConversationHandler.END
        await update.message.reply_text("Введите теги пользователей через запятую (например: @user1, @user2):")
        return CHANGE_TAGS

    async def get_change_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
        tags_input = update.message.text.split(",")
        tags = [t.strip() for t in tags_input if t.strip()]
        if not tags:
            await update.message.reply_text("Не указан ни один тег.")
            return CHANGE_TAGS
        valid_tags = []
        async with aiosqlite.connect(DB_PATH) as db:
            for t in tags:
                async with db.execute("SELECT telegram_id FROM users WHERE tg_tag = ?", (t,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        valid_tags.append((t, row[0]))
                    else:
                        await update.message.reply_text(f"Пользователь {t} не найден. Действие отменено.")
                        return ConversationHandler.END
        context.user_data["change_tags"] = valid_tags
        await update.message.reply_text("Сколько Марсиков добавить/убрать (введите число, отрицательное для снятия):")
        return CHANGE_AMOUNT

    async def get_change_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            amount = int(update.message.text)
        except:
            await update.message.reply_text("Введите корректное число.")
            return CHANGE_AMOUNT
        context.user_data["change_amount"] = amount
        await update.message.reply_text("Укажите причину транзакции:")
        return CHANGE_REASON

    async def finalize_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
        reason = update.message.text
        tags = context.user_data["change_tags"]
        amount = context.user_data["change_amount"]

        await update.message.reply_text("⏳ Обрабатываю транзакции...")

        async with aiosqlite.connect(DB_PATH) as db:
            for tag, target_id in tags:
                async with db.execute("SELECT balance FROM users WHERE telegram_id = ?", (target_id,)) as cursor:
                    balance = (await cursor.fetchone())[0] or 0
                    new_balance = max(0, balance + amount)
                    await db.execute("UPDATE users SET balance = ? WHERE telegram_id = ?", (new_balance, target_id))
            await db.commit()

        await update.message.reply_text("✅ Транзакции завершены.")
        return ConversationHandler.END

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("Изменить баллы"), change_balance_start)],
        states={
            CHANGE_TAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_change_tags)],
            CHANGE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_change_amount)],
            CHANGE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_change)]
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    )
    app.add_handler(conv)