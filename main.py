import os
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Настройка API Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# Telegram Token
TELEGRAM_TOKEN = os.getenv("TOKEN")

# Хранилище последних медиа от пользователя
user_last_media = {}

# Поддерживаемые типы файлов
SUPPORTED_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".mp4": "video/mp4",
    ".mp3": "video/mp4"
}


def guess_mime_type(file_path: str) -> str:
    for ext, mime in SUPPORTED_MIME_TYPES.items():
        if file_path.lower().endswith(ext):
            return mime
    return "application/octet-stream"  # fallback


async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Привет! Отправь мне изображение, документ, текст или всё вместе — я всё пойму! 💡")


async def handle_message(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    media_parts = []

    # 1. Обработка фото
    if update.message.photo:
        for photo in update.message.photo:
            file = await context.bot.get_file(photo.file_id)
            photo_bytes = await file.download_as_bytearray()
            media_parts.append({
                "mime_type": "image/jpeg",
                "data": bytes(photo_bytes)
            })

    # 2. Обработка документов
    if update.message.document:
        document = update.message.document
        file = await context.bot.get_file(document.file_id)
        doc_bytes = await file.download_as_bytearray()
        filename = document.file_name
        mime_type = guess_mime_type(filename)
        media_parts.append({
            "mime_type": mime_type,
            "data": bytes(doc_bytes)
        })

    # 3. Текст
    text = update.message.caption or update.message.text
    if text:
        media_parts.append({"text": text})

    # 4. Если есть что-то — отправим в Gemini
    if media_parts:
        response = model.generate_content(media_parts)
        await update.message.reply_text(response.text)
        return

    # 5. Если ничего нет, но ранее было изображение/файл
    if not media_parts and text:
        if user_id in user_last_media:
            parts = user_last_media[user_id] + [{"text": text}]
            response = model.generate_content(parts)
            await update.message.reply_text(response.text)
            user_last_media.pop(user_id, None)
            return

    # 6. Если только медиа (без текста) — запоминаем
    if media_parts and not text:
        user_last_media[user_id] = media_parts
        await update.message.reply_text("Файл(ы) получены. Теперь напиши, что ты хочешь узнать.")
        return

    await update.message.reply_text("Пожалуйста, отправь текст, изображение или документ.")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
