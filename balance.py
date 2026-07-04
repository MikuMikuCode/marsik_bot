from datetime import datetime

import aiosqlite
from telegram import Update
from telegram.ext import CallbackQueryHandler, MessageHandler, filters, ConversationHandler, CommandHandler, ContextTypes

from balance_utils import get_user_balance
from sheets_sync import append_transaction_to_sheet

CHANGE_TAGS, CHANGE_AMOUNT, CHANGE_REASON = range(3)

def register_balance_handlers(app, DB_PATH):
    async def change_balance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query:
            await query.answer()

        telegram_id = update.effective_user.id
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT role FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                role_row = await cursor.fetchone()
                role = role_row[0] if role_row else "user"
        if role not in ["senior_user", "admin"]:
            target = query.message if query else update.message
            await target.reply_text("Недостаточно прав.")
            return ConversationHandler.END

        target = query.message if query else update.message
        await target.reply_text("Введите теги пользователей через запятую (например: @user1, @user2):")
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
        actor_id = update.effective_user.id

        await update.message.reply_text("⏳ Обрабатываю транзакции...")

        sheet_transactions = []
        balance_notifications = []
        async with aiosqlite.connect(DB_PATH) as db:
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
            async with db.execute("SELECT tg_tag FROM users WHERE telegram_id = ?", (actor_id,)) as cursor:
                actor_row = await cursor.fetchone()
                actor_tag = actor_row[0] if actor_row and actor_row[0] else f"id:{actor_id}"

            for tag, target_id in tags:
                balance = await get_user_balance(db, target_id)
                new_balance = max(0, balance + amount)
                actual_amount = new_balance - balance
                created_at = datetime.now().strftime("%d.%m.%Y %H:%M")
                await db.execute("UPDATE users SET balance = ? WHERE telegram_id = ?", (new_balance, target_id))
                cursor = await db.execute(
                    """
                    INSERT INTO transactions (created_at, actor_tag, target_tag, amount, comment)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        created_at,
                        actor_tag,
                        tag,
                        actual_amount,
                        reason,
                    ),
                )
                sheet_transactions.append((
                    cursor.lastrowid,
                    created_at,
                    actor_tag,
                    tag,
                    actual_amount,
                    reason,
                ))
                if actual_amount:
                    balance_notifications.append((
                        target_id,
                        tag,
                        actual_amount,
                        new_balance,
                    ))
            await db.commit()

        notification_failures = []
        for target_id, tag, actual_amount, new_balance in balance_notifications:
            if actual_amount > 0:
                action = "начислено"
            else:
                action = "списано"

            text = (
                f"Вам {action} {abs(actual_amount)} MT от {actor_tag}\n"
                f"Комментарий: {reason}"
            )
            try:
                await context.bot.send_message(chat_id=target_id, text=text)
            except Exception:
                notification_failures.append(tag)

        for transaction in sheet_transactions:
            await append_transaction_to_sheet(*transaction)

        if notification_failures:
            failed = ", ".join(notification_failures)
            await update.message.reply_text(
                f"✅ Транзакции завершены.\n"
                f"Не удалось отправить уведомления: {failed}"
            )
        else:
            await update.message.reply_text("✅ Транзакции завершены.")
        return ConversationHandler.END

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^Изменить баллы$"), change_balance_start),
            CallbackQueryHandler(change_balance_start, pattern="^balance_change$"),
        ],
        states={
            CHANGE_TAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_change_tags)],
            CHANGE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_change_amount)],
            CHANGE_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_change)]
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)]
    )
    app.add_handler(conv)
