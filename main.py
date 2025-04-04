import os
import base64
import aiohttp
import telegram
from telegram import Update, File
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import google.generativeai as genai

# Конфигурация
TOKEN = os.getenv("TOKEN")
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

if not TOKEN or not GOOGLE_API_KEY:
    raise ValueError("Отсутствует токен Telegram или Google Gemini API.")

genai.configure(api_key=GOOGLE_API_KEY)

# Создание модели
model = genai.GenerativeModel("gemini-2.0-flash")

# Хранение истории сообщений
user_histories = {}

# Загрузка и кодирование файла
async def download_and_encode(file: File) -> dict:
    telegram_file = await file.get_file()
    async with aiohttp.ClientSession() as session:
        async with session.get(telegram_file.file_path) as resp:
            data = await resp.read()
    mime_type = file.mime_type or "application/octet-stream"

    return {
        "inline_data": {
            "mime_type": mime_type,
            "data": base64.b64encode(data).decode("utf-8"),
        }
    }

# Команда /start
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Привет! Я NutriBot 🤖\nОтправь мне фото, текст или документ — и я помогу!\n\nЯ помню контекст и умею анализировать изображения.")

# Основная логика
async def handle_message(update: Update, context: CallbackContext) -> None:
    message = update.message
    user_id = message.from_user.id
    user_text = message.caption or message.text or ""
    contents = []

    # Собираем все файлы (фото и документы)
    media_files = message.photo or []
    if message.document:
        media_files.append(message.document)

    # Кодируем все файлы
    for file in media_files:
        try:
            part = await download_and_encode(file)
            contents.append(part)
        except Exception as e:
            await message.reply_text(f"Ошибка при загрузке файла: {str(e)}")
            return

    # Добавляем текст, если есть
    if user_text:
        contents.insert(0, {"text": user_text})

    if not contents:
        await message.reply_text("Пожалуйста, отправь текст, изображение или документ.")
        return

    # Загружаем историю (если есть)
    history = user_histories.get(user_id, [])

    try:
        # Добавляем новое сообщение в историю
        history.append({"role": "user", "parts": contents})
        response = model.generate_content(history)

        # Ответ и фильтрация
        reply = response.text.strip()
        if "bounding box detections" in reply and "`json" in reply:
            reply = reply.split("bounding box detections")[0].strip()

        # Сохраняем ответ в историю
        history.append({"role": "model", "parts": [reply]})
        user_histories[user_id] = history[-10:]  # ограничиваем историю (последние 10)

        await message.reply_text(f"NutriBot:\n{reply}")

    except Exception as e:
        await message.reply_text(f"Произошла ошибка: {str(e)}")

# Команда для сброса истории
async def reset(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_histories.pop(user_id, None)
    await update.message.reply_text("Контекст сброшен! Начнем с чистого листа 🧼")

# Команда для будущей генерации изображений (заглушка)
async def generate_image(update: Update, context: CallbackContext) -> None:
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Напиши, что ты хочешь сгенерировать! Например:\n/generate_image футуристический бургер")
        return

    await update.message.reply_text("⚙️ Генерация изображения пока недоступна в API Gemini. Ожидаем активации от Google!")

# Запуск бота
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("generate_image", generate_image))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    print("🤖 NutriBot запущен с поддержкой текста, изображений, файлов и контекста.")
    app.run_polling()

if __name__ == "__main__":
    main()
