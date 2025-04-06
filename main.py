import os
import re
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
user_states = {}
user_histories = {}

QUESTION_FLOW = [
    ("name", "Как тебя зовут?"),
    ("age", "Сколько тебе лет?"),
    ("gender", "Какой у тебя пол? (м/ж)"),
    ("current_weight", "Сколько ты сейчас весишь?"),
    ("goal", "Какая у тебя цель? (похудеть, набрать массу, просто ЗОЖ и т.п.)"),
    ("experience", "Какой у тебя уровень активности и тренировочного опыта?"),
    ("food_prefs", "Есть ли предпочтения в еде? (веганство, без глютена и т.п.)"),
    ("health_limits", "Есть ли ограничения по здоровью?"),
    ("equipment", "Есть ли у тебя дома тренажёры или инвентарь?"),
    ("metrics", "Какая у тебя цель по весу или другим метрикам?")
]

# --- Команда /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    update_user(user_id, {"question_index": 0})
    first_question = QUESTION_FLOW[0][1]
    
    await update.message.reply_text(
        "NutriBot:\nПривет! Я твой персональный фитнес-ассистент NutriBot. "
        "Давай начнем с короткой анкеты 🙌"
    )
    await update.message.reply_text(first_question)

# --- Сброс истории ---
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories.pop(user_id, None)
    await update.message.reply_text("Контекст сброшен! Начнем с чистого листа 🧼")

# --- Заглушка генерации изображения ---
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

# --- Обработка обычных сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip().lower()
    user = get_user(user_id)

    question_index = user.get("question_index", 0)

    # Если анкета не завершена — продолжаем её
    if question_index is not None and question_index < len(QUESTION_FLOW):
        key, _ = QUESTION_FLOW[question_index]
        update_user(user_id, {key: update.message.text.strip()})

        question_index += 1
        if question_index < len(QUESTION_FLOW):
            next_question = QUESTION_FLOW[question_index][1]
            update_user(user_id, {"question_index": question_index})
            await update.message.reply_text(next_question)
        else:
            update_user(user_id, {"question_index": None})
            await update.message.reply_text("Спасибо! Я записал твою анкету 🎯")
            await update.message.reply_text("Хочешь, я подскажу план тренировок или рацион на день?")
        return

    # Естественные вопросы после анкеты
    if "сколько мне лет" in text:
        age = user.get("age")
        if age:
            await update.message.reply_text(f"Ты писал(а), что тебе {age} лет.")
        else:
            await update.message.reply_text("Я пока не знаю твой возраст. Хочешь, я задам тебе анкету заново? (/start)")
        return

    if "какая у меня цель" in text:
        goal = user.get("goal")
        if goal:
            await update.message.reply_text(f"Ты упоминал(а), что твоя цель — {goal}.")
        else:
            await update.message.reply_text("Я пока не знаю твою цель. Напиши /start, чтобы пройти анкету.")
        return

    if "вешу" in text or "мой вес" in text:
        weight = user.get("current_weight")
        if weight:
            await update.message.reply_text(f"Ты писал(а), что сейчас весишь {weight} кг.")
        else:
            await update.message.reply_text("Я пока не знаю твой текущий вес.")
        return

    # Дальнейший диалог — передаем в ИИ (позже можно подключить Gemini)
    await update.message.reply_text("Я помню твою анкету! Спроси меня о чём-нибудь или напиши /reset, чтобы начать заново.")

# --- Запуск бота ---
if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("generate_image", generate_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 NutriBot запущен с поддержкой текста, изображений, файлов и анкетирования.")
    app.run_polling()
