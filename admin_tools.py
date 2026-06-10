import aiosqlite
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


def register_admin_handlers(app, DB_PATH):
    async def get_role(telegram_id):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT role FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else "user"

    def normalize_role(raw_role):
        role = raw_role.lower().strip()
        if role in ["admin", "админ"]:
            return "admin"
        if role in ["senior", "senior_user", "старший"]:
            return "senior_user"
        return None

    async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
        actor_role = await get_role(update.effective_user.id)
        if actor_role != "admin":
            await update.message.reply_text("Недостаточно прав.")
            return

        if len(context.args) != 2:
            await update.message.reply_text(
                "Использование: /setrole @user admin\n"
                "Или: /setrole @user senior"
            )
            return

        tag = context.args[0].strip()
        role = normalize_role(context.args[1])
        if not tag.startswith("@") or not role:
            await update.message.reply_text(
                "Проверь формат: /setrole @user admin или /setrole @user senior"
            )
            return

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT telegram_id FROM users WHERE tg_tag = ?", (tag,)) as cursor:
                row = await cursor.fetchone()
            if not row:
                await update.message.reply_text("Пользователь не найден. Он должен хотя бы раз нажать /start у бота.")
                return

            await db.execute("UPDATE users SET role = ? WHERE tg_tag = ?", (role, tag))
            await db.commit()

        role_title = "админом" if role == "admin" else "старшим пользователем"
        await update.message.reply_text(f"{tag} теперь является {role_title}.")

    app.add_handler(CommandHandler("setrole", set_role))
