import random

from telegram.ext import ContextTypes, MessageHandler, filters

STICKER_SET_NAME = "MarsikWoW"


def register_sticker_handlers(app):
    async def reply_random_marsik_sticker(update, context: ContextTypes.DEFAULT_TYPE):
        sticker_set = await context.bot.get_sticker_set(STICKER_SET_NAME)
        sticker = random.choice(sticker_set.stickers)
        await update.message.reply_sticker(sticker.file_id)

    app.add_handler(MessageHandler(filters.Sticker.ALL, reply_random_marsik_sticker))
