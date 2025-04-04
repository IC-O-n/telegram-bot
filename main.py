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

# Создание моделей
model_text = genai.GenerativeModel("gemini-2.0-flash")  # для обработки текста и изображений
model_image = genai.GenerativeModel("imagen-3.0-generate-002")  # для генерации изображений

# Хранение истории сообщений
user_histories = {}

# Загрузка и кодирование файла
async def download_and_encode(file: File) -> dict:
    telegram_file = await file.get_file()
    async with aiohttp.ClientSession() as session:
        async with session.get(telegram_file.file_path) as resp:
            data = await resp.read()
    mime_type = file.mime_type if hasattr(file, 'mime_type') else "image/jpeg"  # Используем image/jpeg как дефолт

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
        response = model_text.generate_content(history)

        # Ответ и фильтрация
        reply = response.text.strip()

        # Объединяем описание всех изображений в одно сообщение
        if "bounding box detections" in reply and "`json" in reply:
            reply = reply.split("bounding box detections")[0].strip()

        # Если на фото несколько объектов, это нужно объединить в одно сообщение
        if "На этом фото" in reply:
            reply = reply.replace("На этом фото", "\n\nНа этом фото")

        # Сохраняем ответ в историю
        history.append({"role": "model", "parts": [reply]})
        user_histories[user_id] = history[-10:]  # ограничиваем историю (последние 10)

        await message.reply_text(f"{reply}")

    except Exception as e:
        await message.reply_text(f"Произошла ошибка: {str(e)}")

# Генерация изображения по запросу
async def generate_image(update: Update, context: CallbackContext) -> None:
    prompt = update.message.text  # Получаем текст сообщения

    # Если текст запроса указывает на генерацию изображения, вызываем модель "imagen-3.0-generate-002"
    if prompt.lower().find("сгенерируй") != -1 or prompt.lower().find("изображение") != -1:
        try:
            # Генерация изображения с помощью "imagen-3.0-generate-002"
            response = model_image.generate_content([
                {"text": prompt}
            ])
            # Отправляем сгенерированное изображение
            image_data = response.images[0].image_data
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            await update.message.reply_photo(photo=image_base64, caption=f"Вот твоё изображение по запросу: {prompt}")
        except Exception as e:
            await update.message.reply_text(f"Произошла ошибка при генерации изображения: {str(e)}")
    else:
        await update.message.reply_text("Я не понял, что ты хочешь сгенерировать. Попробуй уточнить запрос.")

# Команда для сброса истории
async def reset(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_histories.pop(user_id, None)
    await update.message.reply_text("Контекст сброшен! Начнем с чистого листа 🧼")

# Запуск бота
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, generate_image))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("🤖 NutriBot запущен с поддержкой текста, изображений, файлов и контекста.")
    app.run_polling()

if __name__ == "__main__":
    main()
