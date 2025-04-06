import os
import difflib
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
        "Привет! Я твой персональный фитнес-ассистент NutriBot. "
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

def extract_user_facts(text: str) -> dict:
    facts = {}

    weight_match = re.search(r'вешу\s*(\d{2,3})', text)
    if weight_match:
        facts["current_weight"] = weight_match.group(1)

    age_match = re.search(r'мне\s*(\d{1,2})\s*лет', text)
    if age_match:
        facts["age"] = age_match.group(1)

    goal_match = re.search(r'цель.*?(похудеть|набрать|поддерживать)', text)
    if goal_match:
        facts["goal"] = goal_match.group(1)

    return facts

def interpret_answer(key: str, user_input: str) -> str:
    input_lower = user_input.lower().strip()

    if key == "goal":
        # Примеры целей
        goals = {
            "похудеть": ["похудеть", "сбросить вес", "уменьшить жир", "похудание"],
            "набрать мышечную массу": ["набрать массу", "набрать мышечную массу", "набрать вес", "набор массы", "нобрать мышичную массу"],
            "поддерживать форму": ["поддерживать", "поддерживать форму", "оставаться в форме"]
        }
        for clean_goal, variations in goals.items():
            for variant in variations:
                if variant in input_lower:
                    return clean_goal
        return "другая цель"

    if key == "activity":
        levels = {
            "низкий": ["не тренируюсь", "редко", "низкий", "почти не двигаюсь"],
            "средний": ["иногда", "несколько раз", "средний", "тренируюсь 2-3 раза в неделю"],
            "высокий": ["тренируюсь часто", "высокий", "каждый день", "тренируюсь регулярно"]
        }
        for level, phrases in levels.items():
            for phrase in phrases:
                if phrase in input_lower:
                    return level
        return "неизвестно"

    if key in ["age", "current_weight", "desired_weight"]:
        numbers = re.findall(r'\d{2,3}', input_lower)
        if numbers:
            return numbers[0]

    if key == "gender":
        if "жен" in input_lower:
            return "женский"
        if "муж" in input_lower:
            return "мужской"
        return "не указан"

    return user_input.strip()

def detect_correction(text: str):
    corrections = ["ой", "вернее", "на самом деле", "не", "точнее", "ошибся", "имел в виду"]
    return any(phrase in text.lower() for phrase in corrections)

def guess_corrected_field(text: str, user_data: dict):
    text = text.lower()
    if "зовут" in text or "я" in text and len(text.split()) == 2:
        return "name"
    if any(word in text for word in ["лет", "возраст", "мне", "года", "году"]):
        return "age"
    if "вешу" in text or "вес" in text:
        return "current_weight"
    if "цель" in text or "хочу" in text:
        return "goal"
    if "м" in text or "ж" in text or "пол" in text:
        return "gender"
    return None

# --- Обработка обычных сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    if detect_correction(text):
        field = guess_corrected_field(text, user)
        if field:
            new_value = interpret_answer(field, text)
            update_user(user_id, {field: new_value})
            await update.message.reply_text(f"Понял, обновил {field}: {new_value}")

            # Продолжим анкету с нужного места
            question_index = get_question_index(field)
            if question_index < len(QUESTION_FLOW):
                update_user(user_id, {"question_index": question_index})
                await update.message.reply_text(QUESTION_FLOW[question_index][1])
            return
    text_lower = text.lower()
    user = get_user(user_id)

    question_index = user.get("question_index", 0)

    # Этап анкеты
    if question_index is not None and question_index < len(QUESTION_FLOW):
        key, _ = QUESTION_FLOW[question_index]
        cleaned_value = interpret_answer(key, text)
        update_user(user_id, {key: cleaned_value})

        question_index += 1
        if question_index < len(QUESTION_FLOW):
            next_question = QUESTION_FLOW[question_index][1]
            update_user(user_id, {"question_index": question_index})
            await update.message.reply_text(next_question)
        else:
            update_user(user_id, {"question_index": None})
            await update.message.reply_text("Спасибо! Я записал твою анкету 🎯")
            await update.message.reply_text("Хочешь, я помогу составить рацион или тренировку?")
        return
    # Извлечение и сохранение фактов из произвольных фраз
    extracted = extract_user_facts(text_lower)
    if extracted:
        update_user(user_id, extracted)
        await update.message.reply_text("Я запомнил это!")

    # Примеры пользовательских запросов
    if "сколько мне лет" in text_lower:
        age = user.get("age") or extracted.get("age")
        if age:
            await update.message.reply_text(f"Ты писал(а), что тебе {age} лет.")
        else:
            await update.message.reply_text("Я пока не знаю твой возраст.")
        return

    if "вешу" in text_lower or "мой вес" in text_lower:
        weight = user.get("current_weight") or extracted.get("current_weight")
        if weight:
            await update.message.reply_text(f"Ты писал(а), что весишь {weight} кг.")
        else:
            await update.message.reply_text("Я пока не знаю твой вес.")
        return

    # Пример диалога после анкеты
    await update.message.reply_text(
        "Интересно! Хочешь узнать, сколько калорий тебе нужно или какие тренировки подойдут?")

# --- Запуск бота ---
if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("generate_image", generate_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 NutriBot запущен с поддержкой текста, изображений, файлов и анкетирования.")
    app.run_polling()
