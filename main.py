import os
import re
import base64
import aiohttp
import sqlite3
import telegram
from collections import deque
from telegram import Update, File
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, CallbackContext, ConversationHandler
)
import google.generativeai as genai

# Конфигурация
TOKEN = os.getenv("TOKEN")
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

if not TOKEN or not GOOGLE_API_KEY:
    raise ValueError("Отсутствует токен Telegram или Google Gemini API.")

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

user_histories = {}
user_profiles = {}

(
    ASK_NAME, ASK_GENDER, ASK_AGE, ASK_WEIGHT, ASK_HEIGHT, ASK_GOAL,
    ASK_ACTIVITY, ASK_DIET_PREF, ASK_HEALTH, ASK_EQUIPMENT, ASK_TARGET
) = range(11)

def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        gender TEXT,
        age INTEGER,
        weight REAL,
        height REAL,
        goal TEXT,
        activity TEXT,
        diet TEXT,
        health TEXT,
        equipment TEXT,
        target_metric TEXT
    )
    ''')
    conn.commit()
    conn.close()

def save_user_profile(user_id: int, profile: dict):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR REPLACE INTO user_profiles
    (user_id, name, gender, age, weight, height, goal, activity, diet, health, equipment, target_metric)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        profile.get("name"),
        profile.get("gender"),
        profile.get("age"),
        profile.get("weight"),
        profile.get("height"),
        profile.get("goal"),
        profile.get("activity"),
        profile.get("diet"),
        profile.get("health"),
        profile.get("equipment"),
        profile.get("target_metric"),
    ))
    conn.commit()
    conn.close()

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

async def generate_dynamic_prompt(user_id: int, question: str, previous_answer: str = None) -> str:
    profile_info = get_user_profile_text(user_id)
    prompt = f"""
    Ты — NutriBot, профессиональный фитнес-ассистент. Задавай вопросы для анкеты кратко, естественно и с учетом профиля пользователя, если он доступен. Избегай избыточного текста, чрезмерных эмодзи и фраз вроде 'самую лучшую на всем белом свете'. Учитывай предыдущий ответ для контекста.

    Информация о пользователе:
    {profile_info}

    Предыдущий ответ пользователя: {previous_answer or 'Нет ответа'}

    Вопрос: {question}

    Сгенерируй ответ:
    - Краткий и информативный
    - С учетом профиля или предыдущего ответа
    - Без лишних эмоций или юмора
    - Формат: TEXT: ...
    """
    try:
        response = model.generate_content([{"text": prompt}])
        text_match = re.search(r"TEXT:\s*(.+)", response.text, re.DOTALL)
        return text_match.group(1).strip() if text_match else question
    except Exception:
        return question

async def start(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    question = "Как тебя зовут?"
    prompt = await generate_dynamic_prompt(user_id, question)
    await update.message.reply_text(prompt)
    return ASK_NAME

async def ask_gender(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id] = {"name": update.message.text}
    question = "Укажи свой пол (м/ж):"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_GENDER

async def ask_age(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    gender = update.message.text.lower()
    if gender not in ["м", "ж"]:
        await update.message.reply_text("Пожалуйста, укажи только 'м' или 'ж'. Попробуй еще.")
        return ASK_GENDER
    user_profiles[user_id]["gender"] = gender
    question = "Сколько тебе лет?"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_AGE

async def ask_weight(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    try:
        age = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Введите возраст числом. Попробуйте снова.")
        return ASK_AGE
    user_profiles[user_id]["age"] = age
    question = "Какой у тебя текущий вес (в кг)?"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_WEIGHT

async def ask_height(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    try:
        weight = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Введите вес числом. Попробуйте снова.")
        return ASK_WEIGHT
    user_profiles[user_id]["weight"] = weight
    question = "Какой у тебя рост (в см)?"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_HEIGHT

async def ask_goal(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    try:
        height = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Введите рост числом. Попробуйте снова.")
        return ASK_HEIGHT
    user_profiles[user_id]["height"] = height
    question = "Какая у тебя цель? (Похудеть, Набрать массу, Рельеф, Просто ЗОЖ)"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_GOAL

async def ask_activity(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["goal"] = update.message.text
    question = "Какой у тебя уровень активности? (Новичок, Средний, Продвинутый)"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_ACTIVITY

async def ask_diet_pref(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["activity"] = update.message.text
    question = "Есть ли у тебя предпочтения в еде? (Веганство, без глютена и т.д.)"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_DIET_PREF

async def ask_health(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["diet"] = update.message.text
    question = "Есть ли у тебя ограничения по здоровью?"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_HEALTH

async def ask_equipment(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["health"] = update.message.text
    question = "Какой инвентарь или тренажеры у тебя есть?"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_EQUIPMENT

async def ask_target(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["equipment"] = update.message.text
    question = "Какая у тебя конкретная цель по весу или метрикам?"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_TARGET

async def finish_questionnaire(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["target_metric"] = update.message.text
    name = user_profiles[user_id]["name"]
    save_user_profile(user_id, user_profiles[user_id])

    await update.message.reply_text(f"Анкета завершена, {name}. Теперь могу помочь с рекомендациями. Задавай вопросы или отправляй фото!")
    return ConversationHandler.END

async def show_profile(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("Профиль не найден. Пройди анкету с /start.")
        return

    bmi_info = ""
    if row[4] and row[5]:
        try:
            bmi = row[4] / ((row[5] / 100) ** 2)
            bmi_category = "ниже нормы" if bmi < 18.5 else "нормальный" if 18.5 <= bmi < 25 else "избыточный вес" if 25 <= bmi < 30 else "ожирение"
            bmi_info = f"\nИМТ: {bmi:.1f} ({bmi_category})"
        except:
            bmi_info = ""

    profile_text = (
        f"Профиль {row[1]}:\n"
        f"Имя: {row[1]}\nПол: {row[2]}\nВозраст: {row[3]}\nВес: {row[4]} кг\n"
        f"Рост: {row[5]} см{bmi_info}\nЦель: {row[6]}\nАктивность: {row[7]}\n"
        f"Питание: {row[8]}\nЗдоровье: {row[9]}\nИнвентарь: {row[10]}\n"
        f"Целевая метрика: {row[11]}"
    )
    await update.message.reply_text(profile_text)

async def reset(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_histories.pop(user_id, None)
    user_profiles.pop(user_id, None)
    await update.message.reply_text("Контекст сброшен. Начни заново с /start.")

async def generate_image(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Генерация изображений пока недоступна. Ожидайте обновлений.")

def get_user_profile_text(user_id: int) -> str:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return "Профиль пользователя не найден."

    return (
        f"Имя: {row[1]}\n"
        f"Пол: {row[2]}\n"
        f"Возраст: {row[3]}\n"
        f"Вес: {row[4]} кг\n"
        f"Рост: {row[5]} см\n"
        f"Цель: {row[6]}\n"
        f"Активность: {row[7]}\n"
        f"Питание: {row[8]}\n"
        f"Здоровье: {row[9]}\n"
        f"Инвентарь: {row[10]}\n"
        f"Целевая метрика: {row[11]}"
    )

async def handle_message(update: Update, context: CallbackContext) -> None:
    message = update.message
    user_id = message.from_user.id
    user_text = message.caption or message.text or ""
    contents = []

    media_files = message.photo or []
    if message.document:
        media_files.append(message.document)

    for file in media_files:
        try:
            part = await download_and_encode(file)
            contents.append(part)
        except Exception as e:
            await message.reply_text(f"Ошибка при загрузке файла: {e}. Попробуйте другой.")
            return

    if user_text:
        contents.insert(0, {"text": user_text})
    if not contents:
        await update.message.reply_text("Отправьте текст, фото или документ для анализа.")
        return

    profile_info = get_user_profile_text(user_id)
    if profile_info and "не найден" not in profile_info:
        contents.insert(0, {"text": f"Информация о пользователе:\n{profile_info}"})

    if user_id not in user_histories:
        user_histories[user_id] = deque(maxlen=5)
    user_histories[user_id].append(user_text)
    history_messages = list(user_histories[user_id])
    if history_messages:
        history_prompt = "\n".join(f"Пользователь: {msg}" for msg in history_messages)
        contents.insert(0, {"text": f"История сообщений:\n{history_prompt}"})

    GEMINI_SYSTEM_PROMPT = """Ты — NutriBot, профессиональный фитнес-ассистент. Давай краткие, информативные и логичные ответы, основанные на профиле пользователя. Избегай избыточного текста, чрезмерных эмодзи и фраз вроде 'потрясающая тренировка'. 

Сообщения могут быть:
- Вопросами (о питании, тренировках, анализе фото)
- Обновлениями данных (например, 'вес 75 кг', 'добавь гантели')
- Свободным текстом с новыми фактами

База данных user_profiles:
- user_id INTEGER PRIMARY KEY
- name TEXT
- gender TEXT
- age INTEGER
- weight REAL
- height REAL
- goal TEXT
- activity TEXT
- diet TEXT
- health TEXT
- equipment TEXT
- target_metric TEXT

Задачи:
1. Для вопросов: дай точный, полезный ответ, используя профиль (например, советы по питанию или тренировкам). Рассчитывай ИМТ, если есть вес и рост.
2. Для обновлений: определи поле для изменения, предложи SQL-запрос и запроси подтверждение у пользователя.
3. Для изображений с 'добавь в инвентарь': используй описание объекта для equipment и запроси подтверждение.
4. Будь логичен, избегай предположений без данных. Ответ в формате:
   - TEXT: ... (для вопросов)
   - SQL: ... TEXT: ... (для предложений об обновлении)

Обновляй профиль только после явного подтверждения."""
    contents.insert(0, {"text": GEMINI_SYSTEM_PROMPT})

    try:
        response = model.generate_content(contents)
        response_text = response.text.strip()

        sql_match = re.search(r"SQL:\s*(.*?)\nTEXT:", response_text, re.DOTALL)
        text_match = re.search(r"TEXT:\s*(.+)", response_text, re.DOTALL)

        if sql_match:
            sql_query = sql_match.group(1).strip()
            try:
                conn = sqlite3.connect("users.db")
                cursor = conn.cursor()
                if "?" in sql_query:
                    cursor.execute(sql_query, (user_id,))
                else:
                    cursor.execute(sql_query)
                conn.commit()
                conn.close()
            except Exception as e:
                await message.reply_text(f"Ошибка обновления профиля: {e}. Попробуйте снова.")
                return

        if text_match:
            reply_text = text_match.group(1).strip()
            await message.reply_text(reply_text)
        else:
            await message.reply_text(response_text)

    except Exception as e:
        await message.reply_text(f"Ошибка обработки: {e}. Попробуйте еще раз.")

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_gender)],
            ASK_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_age)],
            ASK_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_weight)],
            ASK_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_height)],
            ASK_HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_goal)],
            ASK_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_activity)],
            ASK_ACTIVITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_diet_pref)],
            ASK_DIET_PREF: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_health)],
            ASK_HEALTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_equipment)],
            ASK_EQUIPMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_target)],
            ASK_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_questionnaire)],
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("profile", show_profile))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("generate_image", generate_image))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()
