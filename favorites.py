import aiosqlite
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import MessageHandler, CallbackQueryHandler, filters, ConversationHandler, CommandHandler, ContextTypes

FAV_ACTION, FAV_TAGS = range(2)

def register_favorites_handlers(app, DB_PATH):
    async def get_user_role(telegram_id):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT role FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                role_row = await cursor.fetchone()
                return role_row[0] if role_row else "user"

    async def get_favorites_text(telegram_id):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("""
                SELECT u.name, u.tg_tag, u.balance, u.position
                FROM favorites f
                JOIN users u ON u.telegram_id = f.user_id
                WHERE f.owner_id = ?
            """, (telegram_id,)) as cursor:
                rows = await cursor.fetchall()

        text = "Избранное:\n\n"
        if not rows:
            text += "Список пуст."
        else:
            for name, tg_tag, balance, position in rows:
                text += f"{name} | {tg_tag}\n{balance} MT\n{position}\n---\n"
        return text

    async def show_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id
        role = await get_user_role(telegram_id)
        if role not in ["senior_user", "admin"]:
            await update.message.reply_text("Недостаточно прав.")
            return

        text = await get_favorites_text(telegram_id)
        text += '\nЧтобы начислить или вычесть баллы у пользователя, нажмите "Изменить баланс". Изменять баланс можно всем'

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Редактировать", callback_data="fav_edit")],
            [InlineKeyboardButton("Изменить баланс", callback_data="balance_change")]
        ])
        await update.message.reply_text(text, reply_markup=keyboard)

    async def show_favorites_editor(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        telegram_id = update.effective_user.id
        role = await get_user_role(telegram_id)
        if role not in ["senior_user", "admin"]:
            await query.message.reply_text("Недостаточно прав.")
            return ConversationHandler.END

        text = await get_favorites_text(telegram_id)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Добавить", callback_data="fav_add")],
            [InlineKeyboardButton("Убрать", callback_data="fav_remove")]
        ])
        await query.message.reply_text(text, reply_markup=keyboard)

    async def fav_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        context.user_data["fav_action"] = query.data  # fav_add или fav_remove
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data="cancel")]])
        await query.message.reply_text("Введите теги пользователей через запятую:", reply_markup=keyboard)
        return FAV_TAGS

    async def fav_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
        telegram_id = update.effective_user.id
        tags_input = update.message.text.split(",")
        tags = [t.strip() for t in tags_input if t.strip()]
        if not tags:
            await update.message.reply_text("Не указан ни один тег.")
            return FAV_TAGS

        valid_users = []
        async with aiosqlite.connect(DB_PATH) as db:
            for t in tags:
                async with db.execute("SELECT telegram_id FROM users WHERE tg_tag = ?", (t,)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        valid_users.append(row[0])
                    else:
                        await update.message.reply_text(f"Пользователь {t} не найден. Действие отменено.")
                        return ConversationHandler.END

            if context.user_data.get("fav_action") == "fav_add":
                for user_id in valid_users:
                    await db.execute("INSERT OR IGNORE INTO favorites(owner_id, user_id) VALUES (?, ?)", (telegram_id, user_id))
            elif context.user_data.get("fav_action") == "fav_remove":
                for user_id in valid_users:
                    await db.execute("DELETE FROM favorites WHERE owner_id = ? AND user_id = ?", (telegram_id, user_id))
            await db.commit()

            # Вывод обновленного списка
            async with db.execute("""
                SELECT u.name, u.tg_tag, u.balance, u.position
                FROM favorites f
                JOIN users u ON u.telegram_id = f.user_id
                WHERE f.owner_id = ?
            """, (telegram_id,)) as cursor:
                rows = await cursor.fetchall()

        text = "Избранное:\n\n"
        if not rows:
            text += "Список пуст."
        else:
            for name, tg_tag, balance, position in rows:
                text += f"{name} | {tg_tag}\n{balance} MT\n{position}\n---\n"

        await update.message.reply_text(text)
        return ConversationHandler.END

    async def cancel_fav(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query if update.callback_query else None
        if query:
            await query.answer()
            await query.message.reply_text("Действие отменено.")
        else:
            await update.message.reply_text("Действие отменено.")
        return ConversationHandler.END

    # --- ConversationHandler ---
    fav_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^Баллы$"), show_points),
            CallbackQueryHandler(show_favorites_editor, pattern="^fav_edit$"),
            CallbackQueryHandler(fav_action, pattern="^fav_(add|remove)$"),
        ],
        states={
            FAV_TAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, fav_tags)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_fav),
            CallbackQueryHandler(cancel_fav, pattern="^cancel$"),
        ]
    )
    app.add_handler(fav_conv)
