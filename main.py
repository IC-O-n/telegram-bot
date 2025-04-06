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

def detect_correction(text: str) -> bool:
    correction_phrases = ["ой", "на самом деле", "вернее", "точнее", "неправильно", "исправлюсь"]
    return any(phrase in text.lower() for phrase in correction_phrases)

def guess_corrected_field(text: str, user: dict) -> str:
    text_lower = text.lower()

    if "зовут" in text_lower or (text_lower.startswith("я ") and not any(char.isdigit() for char in text)):
        return "name"

    if "лет" in text_lower or ("мне" in text_lower and any(char.isdigit() for char in text)):
        return "age"

    if "вешу" in text_lower or "вес" in text_lower or "кг" in text_lower:
        return "current_weight"

    if "пол" in text_lower or text_lower in ["м", "ж", "муж", "жен", "мужчина", "женщина"]:
        return "gender"

    if "цель" in text_lower or any(x in text_lower for x in ["похудеть", "масса", "накачаться", "зож", "сушиться"]):
        return "goal"

    if "активн" in text_lower or "уровень" in text_lower or "опыт" in text_lower or "начинающ" in text_lower or "трен" in text_lower:
        return "activity_level"

    if "предпочт" in text_lower or "еда" in text_lower or "питание" in text_lower or any(x in text_lower for x in ["веган", "мясо", "без мяса", "не ем"]):
        return "food_preference"

    if "аллерг" in text_lower or "не переношу" in text_lower or "не могу" in text_lower:
        return "allergies"

    return None

# --- Определения выше ---
def get_question_index(field_name):
    for idx, (key, _) in enumerate(QUESTION_FLOW):
        if key == field_name:
            return idx
    return None

field_names = {
    "name": "имя",
    "age": "возраст",
    "gender": "пол",
    "goal": "цель",
    "current_weight": "вес",
    "experience": "уровень активности",
    "food_prefs": "пищевые предпочтения",
    "health_limits": "ограничения по здоровью",
    "equipment": "инвентарь",
    "metrics": "метрики"
}

def process_answer(answer: str, user: dict, field: str) -> tuple[str, dict]:
    parsed_value = interpret_answer(field, answer)
    if parsed_value is None:
        return (f"Не удалось распознать значение для {field}. Попробуй ещё раз.", user)

    user[field] = parsed_value

    # Поиск следующего незаполненного вопроса
    for idx, (next_key, _) in enumerate(QUESTION_FLOW):
        if not user.get(next_key):
            user["question_index"] = idx
            return (QUESTION_FLOW[idx][1], user)

    user["question_index"] = None
    user["pending_action"] = "ask_help"  # <--- Ключевой момент!
    return ("Спасибо! Я записал твою анкету 🎯\nХочешь, я помогу составить рацион или тренировку?", user)

# --- Обработка обычных сообщений ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # Списки для распознавания "да"/"нет"
    yes_words = ["да", "хочу", "ага", "давай", "можно", "я хочу", "поехали", "вперёд"]
    no_words = ["нет", "не", "потом", "не хочу", "позже"]

    # Пассивное извлечение фактов
    extracted = extract_user_facts(text.lower())
    if extracted:
        update_user(user_id, extracted)
        await update.message.reply_text("Я запомнил это!")

    # Обработка после анкеты
    if user.get("pending_action") == "ask_help":
        if any(word in text.lower() for word in yes_words):
            update_user(user_id, {"pending_action": "choose_plan"})
            await update.message.reply_text("Окей! Начнём с питания или тренировок?")
            return
        elif any(word in text.lower() for word in no_words):
            update_user(user_id, {"pending_action": None})
            await update.message.reply_text("Окей! Если передумаешь — просто напиши.")
            return

    if user.get("pending_action") == "choose_plan":
        if "питан" in text or "рацион" in text:
            update_user(user_id, {"pending_action": None})
            await update.message.reply_text("Супер! Сейчас подберу тебе рацион...")
            # generate_nutrition_plan(user)
            return
        elif "трениров" in text or "физ" in text or "спорт" in text:
            update_user(user_id, {"pending_action": None})
            await update.message.reply_text("Отлично! Сейчас подберу тренировку...")
            # generate_workout_plan(user)
            return

    # Обработка прямых вопросов
    if "сколько мне лет" in text.lower():
        age = user.get("age") or extracted.get("age")
        if age:
            await update.message.reply_text(f"Ты писал(а), что тебе {age} лет.")
        else:
            await update.message.reply_text("Я пока не знаю твой возраст.")
        return
    if "вешу" in text.lower() or "мой вес" in text.lower():
        weight = user.get("current_weight") or extracted.get("current_weight")
        if weight:
            await update.message.reply_text(f"Ты писал(а), что весишь {weight} кг.")
        else:
            await update.message.reply_text("Я пока не знаю твой вес.")
        return

    # Анализ намерений (если выше ничего не сработало)
    intent = analyze_intent(text, user)
    if intent:
        await update.message.reply_text(intent)
        return

    # Ответ по умолчанию
    await update.message.reply_text("Интересно! Хочешь узнать, сколько калорий тебе нужно или какие тренировки подойдут?")
        
# --- Запуск бота ---
if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("generate_image", generate_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 NutriBot запущен с поддержкой текста, изображений, файлов и анкетирования.")
    app.run_polling()
