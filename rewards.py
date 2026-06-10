from datetime import datetime
from html import escape

import aiosqlite
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler, CommandHandler

BUY_NAME, CONFIRM = range(2)
PROMO_ACTION, PROMO_REWARD, PROMO_PERCENT = range(3)
SHOP_ACTION, SHOP_ADD_ITEMS, SHOP_REMOVE_ITEMS = range(3)


def register_rewards_handlers(app, DB_PATH):
    async def ensure_reward_tables(db):
        await db.execute("""
            CREATE TABLE IF NOT EXISTS active_promotions (
                reward_name TEXT PRIMARY KEY,
                discount_percent INTEGER NOT NULL
            )
        """)

    async def get_user_role(telegram_id):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT role FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else "user"

    async def require_admin(update: Update):
        if await get_user_role(update.effective_user.id) != "admin":
            await update.message.reply_text("Недостаточно прав.")
            return False
        return True

    def discounted_cost(cost, discount_percent):
        if not discount_percent:
            return cost
        return max(0, cost * (100 - discount_percent) // 100)

    def format_reward_price(cost, discount_percent):
        final_cost = discounted_cost(cost, discount_percent)
        if discount_percent:
            return f"<s>{cost} MT</s> {final_cost} MT (скидка {discount_percent}%)"
        return f"{cost} MT"

    async def notify_purchase(context, buyer_tag, reward_name, cost):
        text = (
            "🛒 Новая покупка в магазине\n\n"
            f"Кто: {buyer_tag}\n"
            f"Что купили: {reward_name}\n"
            f"Стоимость: {cost} MT"
        )

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                """
                SELECT telegram_id
                FROM users
                WHERE role IN ('admin', 'senior_user') AND active = 1
                """,
            ) as cursor:
                recipients = await cursor.fetchall()

        for (chat_id,) in recipients:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text)
            except Exception:
                pass

    # --- Магазин с картинкой ---
    async def show_rewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
        image_url = "https://i.postimg.cc/B6njFZ8v/Magazin.png"

        async with aiosqlite.connect(DB_PATH) as db:
            await ensure_reward_tables(db)
            await db.commit()
            async with db.execute("""
                SELECT r.name, r.description, r.cost, p.discount_percent
                FROM rewards r
                LEFT JOIN active_promotions p ON p.reward_name = r.name
                ORDER BY r.cost ASC
            """) as cursor:
                rewards = await cursor.fetchall()

        text = "<b>Магазин Марсика!</b>\n\n"
        for name, description, cost, discount_percent in rewards:
            price = format_reward_price(cost, discount_percent)
            text += f"{price} — <b>«{escape(name)}»</b>\n<i>{escape(description or '')}</i>\n\n"

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
            text += f"<b>«{escape(name)}»</b> — {cost} MT\n<i>{escape(description or '')}</i>\n\n"

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
            await ensure_reward_tables(db)
            await db.commit()
            async with db.execute(
                """
                SELECT r.description, r.cost, p.discount_percent
                FROM rewards r
                LEFT JOIN active_promotions p ON p.reward_name = r.name
                WHERE r.name = ?
                """,
                (reward_name,),
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            await update.message.reply_text("Такой награды нет. Попробуйте ещё раз или /cancel.")
            return BUY_NAME

        description, cost, discount_percent = row
        final_cost = discounted_cost(cost, discount_percent)
        context.user_data["reward_name"] = reward_name
        context.user_data["reward_description"] = description
        context.user_data["reward_cost"] = final_cost
        context.user_data["reward_original_cost"] = cost
        context.user_data["reward_discount_percent"] = discount_percent

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Да", callback_data="confirm_buy")],
            [InlineKeyboardButton("Отмена", callback_data="cancel")]
        ])
        await update.message.reply_text(
            f"«{escape(reward_name)}» — {format_reward_price(cost, discount_percent)}\n"
            f"<i>{escape(description or '')}</i>\nУверены, что хотите купить?",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return CONFIRM

    async def confirm_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        reward_name = context.user_data["reward_name"]
        cost = context.user_data["reward_cost"]
        telegram_id = query.from_user.id

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT balance, tg_tag FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                row = await cursor.fetchone()
                balance = row[0] if row else 0
                user_tag = row[1] if row and row[1] else f"id:{telegram_id}"

            if balance < cost:
                await query.message.reply_text(
                    f"Недостаточно Марсиков. Баланс: {balance} 🪙, а награда стоит {cost} 🪙"
                )
                return ConversationHandler.END

            new_balance = balance - cost
            await db.execute("UPDATE users SET balance = ? WHERE telegram_id = ?", (new_balance, telegram_id))
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
            await db.execute(
                """
                INSERT INTO transactions (created_at, actor_tag, target_tag, amount, comment)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().strftime("%d.%m.%Y %H:%M"),
                    user_tag,
                    user_tag,
                    -cost,
                    f"Покупка награды: {reward_name}",
                ),
            )
            await db.commit()

        await notify_purchase(context, user_tag, reward_name, cost)
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

    # --- Акции ---
    async def promo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await require_admin(update):
            return ConversationHandler.END

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Добавить новую акцию", callback_data="promo_add")],
            [InlineKeyboardButton("Удалить все старые", callback_data="promo_clear")]
        ])
        await update.message.reply_text("Что сделать с акциями?", reply_markup=keyboard)
        return PROMO_ACTION

    async def promo_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if query.data == "promo_clear":
            async with aiosqlite.connect(DB_PATH) as db:
                await ensure_reward_tables(db)
                await db.execute("DELETE FROM active_promotions")
                await db.commit()
            await query.message.reply_text("Все старые акции удалены.")
            return ConversationHandler.END

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name FROM rewards ORDER BY cost ASC") as cursor:
                rewards = [row[0] for row in await cursor.fetchall()]

        if not rewards:
            await query.message.reply_text("Магазин пуст. Сначала добавь позиции через /shop.")
            return ConversationHandler.END

        reward_list = "\n".join(f"- {name}" for name in rewards)
        await query.message.reply_text(f"Напиши название позиции для акции:\n\n{reward_list}")
        return PROMO_REWARD

    async def promo_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
        reward_name = update.message.text.strip()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name FROM rewards WHERE name = ?", (reward_name,)) as cursor:
                row = await cursor.fetchone()

        if not row:
            await update.message.reply_text("Такой позиции нет. Напиши название точно как в магазине.")
            return PROMO_REWARD

        context.user_data["promo_reward_name"] = reward_name
        await update.message.reply_text("Сколько процентов скидка? Например: 10")
        return PROMO_PERCENT

    async def promo_percent(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            percent = int(update.message.text.strip())
        except ValueError:
            await update.message.reply_text("Введите число от 1 до 99.")
            return PROMO_PERCENT

        if percent < 1 or percent > 99:
            await update.message.reply_text("Скидка должна быть от 1 до 99%.")
            return PROMO_PERCENT

        reward_name = context.user_data["promo_reward_name"]
        async with aiosqlite.connect(DB_PATH) as db:
            await ensure_reward_tables(db)
            await db.execute(
                """
                INSERT OR REPLACE INTO active_promotions (reward_name, discount_percent)
                VALUES (?, ?)
                """,
                (reward_name, percent),
            )
            await db.commit()

        await update.message.reply_text(f"Акция добавлена: «{reward_name}» со скидкой {percent}%.")
        return ConversationHandler.END

    # --- Редактура магазина ---
    async def shop_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await require_admin(update):
            return ConversationHandler.END

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Добавить позиции", callback_data="shop_add")],
            [InlineKeyboardButton("Удалить позиции", callback_data="shop_remove")]
        ])
        await update.message.reply_text("Что сделать с магазином?", reply_markup=keyboard)
        return SHOP_ACTION

    async def shop_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if query.data == "shop_add":
            await query.message.reply_text(
                "Отправь позиции, каждую с новой строки:\n\n"
                "Название | Описание | Стоимость\n\n"
                "Пример:\n"
                "Кофе | Сертификат на кофе | 100\n"
                "Мерч | Фирменная вещь | 500"
            )
            return SHOP_ADD_ITEMS

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name FROM rewards ORDER BY cost ASC") as cursor:
                rewards = [row[0] for row in await cursor.fetchall()]

        reward_list = "\n".join(f"- {name}" for name in rewards) if rewards else "Магазин пуст."
        await query.message.reply_text(
            "Напиши названия позиций для удаления через запятую или каждую с новой строки:\n\n"
            f"{reward_list}"
        )
        return SHOP_REMOVE_ITEMS

    async def shop_add_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
        lines = [line.strip() for line in update.message.text.splitlines() if line.strip()]
        added = []
        skipped = []

        async with aiosqlite.connect(DB_PATH) as db:
            for line in lines:
                parts = [part.strip() for part in line.split("|", 2)]
                if len(parts) != 3:
                    skipped.append(line)
                    continue

                name, description, raw_cost = parts
                try:
                    cost = int(raw_cost)
                except ValueError:
                    skipped.append(line)
                    continue

                if cost < 0:
                    skipped.append(line)
                    continue

                async with db.execute("SELECT 1 FROM rewards WHERE name = ?", (name,)) as cursor:
                    exists = await cursor.fetchone()
                if exists:
                    skipped.append(f"{name} уже есть")
                    continue

                await db.execute(
                    "INSERT INTO rewards (name, description, cost) VALUES (?, ?, ?)",
                    (name, description, cost),
                )
                added.append(name)
            await db.commit()

        text = "Готово.\n"
        if added:
            text += "Добавлено:\n" + "\n".join(f"- {name}" for name in added)
        if skipped:
            text += "\n\nНе добавлено:\n" + "\n".join(f"- {item}" for item in skipped)
        await update.message.reply_text(text)
        return ConversationHandler.END

    async def shop_remove_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
        raw_items = update.message.text.replace("\n", ",").split(",")
        names = [item.strip() for item in raw_items if item.strip()]
        if not names:
            await update.message.reply_text("Не указана ни одна позиция.")
            return SHOP_REMOVE_ITEMS

        removed = []
        missing = []
        async with aiosqlite.connect(DB_PATH) as db:
            for name in names:
                cursor = await db.execute("DELETE FROM rewards WHERE name = ?", (name,))
                await db.execute("DELETE FROM active_promotions WHERE reward_name = ?", (name,))
                if cursor.rowcount:
                    removed.append(name)
                else:
                    missing.append(name)
            await db.commit()

        text = "Готово.\n"
        if removed:
            text += "Удалено:\n" + "\n".join(f"- {name}" for name in removed)
        if missing:
            text += "\n\nНе найдено:\n" + "\n".join(f"- {name}" for name in missing)
        await update.message.reply_text(text)
        return ConversationHandler.END

    async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query if update.callback_query else None
        if query:
            await query.answer()
            await query.message.reply_text("Действие отменено.")
        else:
            await update.message.reply_text("Действие отменено.")
        return ConversationHandler.END

    # --- Добавляем обработчики ---
    app.add_handler(MessageHandler(filters.Regex("Награды"), show_rewards))
    app.add_handler(CallbackQueryHandler(show_how_to_earn, pattern="^how_to_earn$"))

    buy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_buy_reward, pattern="^buy_reward$")],
        states={
            BUY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_reward_name),
                       CallbackQueryHandler(cancel_buy, pattern="^cancel$")],
            CONFIRM: [CallbackQueryHandler(confirm_buy, pattern="^confirm_buy$"),
                      CallbackQueryHandler(cancel_buy, pattern="^cancel$")]
        },
        fallbacks=[CommandHandler("cancel", cancel_buy)]
    )
    app.add_handler(buy_conv)

    promo_conv = ConversationHandler(
        entry_points=[CommandHandler(["promo", "akcia"], promo_start)],
        states={
            PROMO_ACTION: [CallbackQueryHandler(promo_action, pattern="^promo_(add|clear)$")],
            PROMO_REWARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_reward)],
            PROMO_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_percent)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_action),
            CallbackQueryHandler(cancel_action, pattern="^cancel$"),
        ],
    )
    app.add_handler(promo_conv)

    shop_conv = ConversationHandler(
        entry_points=[CommandHandler("shop", shop_start)],
        states={
            SHOP_ACTION: [CallbackQueryHandler(shop_action, pattern="^shop_(add|remove)$")],
            SHOP_ADD_ITEMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, shop_add_items)],
            SHOP_REMOVE_ITEMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, shop_remove_items)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_action),
            CallbackQueryHandler(cancel_action, pattern="^cancel$"),
        ],
    )
    app.add_handler(shop_conv)
