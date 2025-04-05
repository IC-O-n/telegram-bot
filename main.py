import os
import base64
import aiohttp
import telegram
from telegram import Update, File
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from user_data_manager import get_user, update_user

# --- Конфигурация ---
TOKEN = os.getenv("TOKEN")
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

if not TOKEN or not GOOGLE_API_KEY:
    raise ValueError("Отсутствует токен Telegram или Google Gemini API.")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# --- Хранилище состояний и истории ---
user_states = {}       # Для анкеты
user_histories = {}    # Для общения с ИИ

# --- Команда /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)

    if user_data.get("goal"):
        await update.message.reply_text(f"Привет снова, {user_data.get('name', 'друг')}! Готов продолжить?")
        return

    await update.message.reply_text("Привет! Я твой персональный фитнес-ассистент NutriBot. Давай начнем с короткой анкеты 🙌")
    user_states[user_id] = {"step": "name"}
    await update.message.reply_text("Как тебя зовут?")

# --- Сброс истории (/reset) ---
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories.pop(user_id, None)
    await update.message.reply_text("Контекст сброшен! Начнем с чистого листа 🧼")

# --- Генерация изображения (заглушка) ---
async def generate_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ Генерация изображения пока недоступна в API Gemini. Ожидаем активации от Google!")

# --- Загрузка и кодирование файла ---
async def download_and_encode(file: File) -> dict:
    telegram_file = await file.get_file()
    async with aiohttp.ClientSession() as session:
        async with session.get(telegram_file.file_path) as resp:
            data = await resp.read()
    mime_type = file.mime_type if hasattr(file, 'mime_type') else "image/jpeg"
    return {
        "inline_data": {
            "mime_type": mime_type,
            "data": base64.b64encode(data).decode("utf-8"),
        }
    }

# --- Обработка всех сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    message = update.message
    user_id = message.from_user.id
    user_text = message.text or message.caption or ""

    # === Анкетная логика ===
    if user_id in user_states:
        state = user_states[user_id]
        step = state.get("step")

        if step == "name":
            user_states[user_id]["name"] = user_text
            user_states[user_id]["step"] = "goal"
            await message.reply_text(f"Приятно познакомиться, {user_text}! 💪 Какая у тебя цель?")
            return

        elif step == "goal":
            name = user_states[user_id]["name"]
            goal = user_text
            update_user(user_id, {"name": name, "goal": goal})
            user_states.pop(user_id, None)
            await message.reply_text(f"Отлично, {name}! Я помогу тебе достичь цели: {goal}")
            return

    # === Логика общения с ИИ ===
    contents = []

    media_files = message.photo or []
    if message.document:
        media_files.append(message.document)

    for file in media_files:
        try:
            part = await download_and_encode(file)
            contents.append(part)
        except Exception as e:
            await message.reply_text(f"Ошибка при загрузке файла: {str(e)}")
            return

    if user_text:
        contents.insert(0, {"text": user_text})

    if not contents:
        await message.reply_text("Пожалуйста, отправь текст, изображение или документ.")
        return

    history = user_histories.get(user_id, [])
    history.append({"role": "user", "parts": contents})

    try:
        response = model.generate_content(history)
        reply = response.text.strip()
        # Очистка/преобразование
        if "bounding box detections" in reply and "`json" in reply:
            reply = reply.split("bounding box detections")[0].strip()
        if "На этом фото" in reply:
            reply = reply.replace("На этом фото", "\n\nНа этом фото")

        history.append({"role": "model", "parts": [reply]})
        user_histories[user_id] = history[-10:]  # ограничение по длине истории

        await message.reply_text(reply)
    except Exception as e:
        await message.reply_text(f"Произошла ошибка: {str(e)}")

# --- Основной запуск ---
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("generate_image", generate_image))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("🤖 NutriBot запущен с поддержкой текста, изображений, файлов и анкетирования.")
    app.run_polling()

if __name__ == "__main__":
    main()
