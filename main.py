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
    text = update.message.text.strip()
    text_lower = text.lower()
    user = get_user(user_id)
    question_index = user.get("question_index", 0)

    # --- Если заполняем анкету ---
    if isinstance(question_index, int) and question_index < len(QUESTION_FLOW):
        key, _ = QUESTION_FLOW[question_index]
        update_user(user_id, {key: text})

        question_index += 1
        if question_index < len(QUESTION_FLOW):
            next_question = QUESTION_FLOW[question_index][1]
            update_user(user_id, {"question_index": question_index})
            await update.message.reply_text(next_question)
        else:
            update_user(user_id, {"question_index": None})
            await update.message.reply_text(
                "Спасибо! Я записал твою анкету 🎯 Готов помогать тебе достигать цели!"
            )
        return

    # --- Если анкета завершена, но пользователь сообщает новую инфу ---
    updates = {}

    # Пример: Я вешу 70 кг / Текущий вес 72
    weight_match = re.search(r"(вешу|вес)\s*(\d{2,3})", text_lower)
    if weight_match:
        updates["current_weight"] = weight_match.group(2)

    # Пример: Мне 25 лет
    age_match = re.search(r"мне\s*(\d{1,2})\s*лет", text_lower)
    if age_match:
        updates["age"] = age_match.group(1)

    # Пример: Я парень / Я девушка
    if "я парень" in text_lower or "я мужчина" in text_lower:
        updates["gender"] = "м"
    elif "я девушка" in text_lower or "я женщина" in text_lower:
        updates["gender"] = "ж"

    # Если есть что обновить
    if updates:
        update_user(user_id, updates)
        await update.message.reply_text("Понял, записал! Спасибо за уточнение.")
        return

    # Примитивная обработка вопросов: "Какой у меня вес", "Сколько мне лет", и т.п.
    response_map = {
        "цель": "goal",
        "опыт": "experience",
        "еда": "food_prefs",
        "инвентарь": "equipment",
        "здоровье": "health_limits",
        "метрики": "metrics",
        "имя": "name",
        "возраст": "age",
        "лет": "age",
        "пол": "gender",
        "вес": "current_weight"
    }

    for keyword, key in response_map.items():
        if keyword in text_lower:
            value = user.get(key)
            if value:
                await update.message.reply_text(f"{key.capitalize()}: {value}")
            else:
                await update.message.reply_text("У меня пока нет этой информации. Можешь сказать, и я запомню!")
            return

    # Если ничего не подошло — общий ответ
    await update.message.reply_text("Расскажи что-нибудь или спроси — я постараюсь помочь!")

# --- Запуск бота ---
if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("generate_image", generate_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 NutriBot запущен с поддержкой текста, изображений, файлов и анкетирования.")
    app.run_polling()
