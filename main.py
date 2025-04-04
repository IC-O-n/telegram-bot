import os
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Настройка ключа Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# Telegram токен
TELEGRAM_TOKEN = os.getenv("TOKEN")

# Хранилище последних фото от пользователя
user_last_photo = {}

async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Привет! Отправь мне изображение, текст или и то, и другое.")

async def handle_message(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id

    # Если приходит только изображение — запомним
    if update.message.photo:
        photo = update.message.photo[-1]  # самое крупное
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        user_last_photo[user_id] = photo_bytes
        await update.message.reply_text("Изображение получено. Теперь можешь написать вопрос к нему.")
        return

    # Если приходит только текст
    if update.message.text:
        user_text = update.message.text
        photo_bytes = user_last_photo.get(user_id)

        # Если фото тоже было отправлено ранее
        if photo_bytes:
            response = model.generate_content([
                {"mime_type": "image/jpeg", "data": photo_bytes},
                {"text": user_text}
            ])
            # Сбросим фото, чтобы не использовать его снова
            user_last_photo.pop(user_id, None)
        else:
            # Только текст
            response = model.generate_content(user_text)

        await update.message.reply_text(response.text)
        return

    await update.message.reply_text("Пожалуйста, отправь текст или изображение.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
