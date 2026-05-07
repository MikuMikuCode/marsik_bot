import aiosqlite
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler, CommandHandler

BUY_NAME, CONFIRM = range(2)

def register_rewards_handlers(app, DB_PATH):

    # --- Магазин с картинкой ---
    async def show_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
        image_url = "https://i.postimg.cc/B6njFZ8v/Magazin.png"

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name, description, cost FROM rewards ORDER BY cost ASC") as cursor:
                rewards = await cursor.fetchall()

        text = "<b>Магазин Марсика!</b>\n\n"
        for name, description, cost in rewards:
            text += f"{cost} MT — <b>«{name}»</b>\n<i>{description}</i>\n\n"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("За что получить?", callback_data="how_to_earn")],
            [InlineKeyboardButton("Купить", callback_data="buy_reward")]
        ])

        await update.message.reply_photo(photo=image_url, caption=text, parse_mode="HTML", reply_markup=keyboard)

    # --- За что получить? через базу earn_rewards ---
    async def show_how_to_earn(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS earn_rewards (
                    name TEXT PRIMARY KEY,
                    description TEXT,
                    cost INTEGER
                )
            """)
            await db.commit()

            async with db.execute("SELECT name, description, cost FROM earn_rewards ORDER BY cost ASC") as cursor:
                rewards_list = await cursor.fetchall()

        if not rewards_list:
            await query.message.reply_text("Список пока пуст.")
            return

        text = "<b>За что получить Марсики:</b>\n\n"
        for name, description, cost in rewards_list:
            text += f"<b>«{name}»</b> — {cost} MT\n<i>{description}</i>\n\n"

        await query.message.reply_text(text, parse_mode="HTML")

    # --- Покупка ---
    async def start_buy_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query:
            await query.answer()
            msg = query.message
        else:
            msg = update.message
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="cancel")]])
        await msg.reply_text("Напишите название награды, которую хотите купить:", reply_markup=keyboard)
        return BUY_NAME

    async def get_reward_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
        reward_name = update.message.text.strip()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT description, cost FROM rewards WHERE name = ?", (reward_name,)) as cursor:
                row = await cursor.fetchone()

        if not row:
            await update.message.reply_text("Такой награды нет. Попробуйте ещё раз или /cancel.")
            return BUY_NAME

        description, cost = row
        context.user_data["reward_name"] = reward_name
        context.user_data["reward_description"] = description
        context.user_data["reward_cost"] = cost

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Да", callback_data="confirm_buy")],
            [InlineKeyboardButton("Отмена", callback_data="cancel")]
        ])
        await update.message.reply_text(
            f"«{reward_name}» — {cost} 🪙\n<i>{description}</i>\nУверены, что хотите купить?",
            reply_markup=keyboard, parse_mode="HTML"
        )
        return CONFIRM

    async def confirm_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        reward_name = context.user_data["reward_name"]
        cost = context.user_data["reward_cost"]
        telegram_id = query.from_user.id

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                row = await cursor.fetchone()
                balance = row[0] if row else 0

            if balance < cost:
                await query.message.reply_text(
                    f"Недостаточно Марсиков. Баланс: {balance} 🪙, а награда стоит {cost} 🪙"
                )
                return ConversationHandler.END

            new_balance = balance - cost
            await db.execute("UPDATE users SET balance = ? WHERE telegram_id = ?", (new_balance, telegram_id))
            await db.commit()

        await query.message.reply_text(f"Спасибо за покупку! 🎉\nНовый баланс: {new_balance} 🪙")
        return ConversationHandler.END

    async def cancel_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query if update.callback_query else None
        if query:
            await query.answer()
            await query.message.reply_text("Действие отменено.")
        else:
            await update.message.reply_text("Действие отменено.")
        return ConversationHandler.END

    # --- Добавляем обработчики ---
    app.add_handler(MessageHandler(filters.Regex("Награды"), show_rewards))
    app.add_handler(CallbackQueryHandler(show_how_to_earn, pattern="how_to_earn"))

    buy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_buy_reward, pattern="buy_reward")],
        states={
            BUY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_reward_name),
                       CallbackQueryHandler(cancel_buy, pattern="cancel")],
            CONFIRM: [CallbackQueryHandler(confirm_buy, pattern="confirm_buy"),
                      CallbackQueryHandler(cancel_buy, pattern="cancel")]
        },
        fallbacks=[CommandHandler("cancel", cancel_buy)]
    )
    app.add_handler(buy_conv)