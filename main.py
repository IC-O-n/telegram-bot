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
    ASK_NAME, ASK_GENDER, ASK_AGE, ASK_WEIGHT, ASK_GOAL,
    ASK_ACTIVITY, ASK_DIET_PREF, ASK_HEALTH, ASK_EQUIPMENT, ASK_TARGET
) = range(10)

GEMINI_SYSTEM_PROMPT = """
Ты — умный ассистент. На вход ты получаешь сообщение от пользователя, которое может содержать обновление профиля (например, он сообщает, что его вес изменился или он стал веганом). 

Если в сообщении содержится информация, которую нужно обновить в базе данных, сгенерируй:
- SQL-запрос, который вносит это изменение.
- Человеческий ответ, который бот должен отправить пользователю.

Пример:
Пользователь: "Я набрал 3 кг"
Ответ:
SQL: UPDATE user_profiles SET weight = weight + 3 WHERE user_id = ?
TEXT: Хорошо, я обновил твой вес — добавил 3 кг.

Если изменений не требуется, просто ответь человеку без SQL.

Ответ возвращай строго в формате:
SQL: ...
TEXT: ...
"""



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
    (user_id, name, gender, age, weight, goal, activity, diet, health, equipment, target_metric)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        profile.get("name"),
        profile.get("gender"),
        profile.get("age"),
        profile.get("weight"),
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

async def start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Привет! Я твой персональный фитнес-ассистент NutriBot. Давай начнем с короткой анкеты 🙌\n\nКак тебя зовут?")
    return ASK_NAME

async def ask_gender(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id] = {"name": update.message.text}
    await update.message.reply_text("Укажи свой пол (м/ж):")
    return ASK_GENDER

async def ask_age(update: Update, context: CallbackContext) -> int:
    gender = update.message.text.lower()
    if gender not in ["м", "ж"]:
        await update.message.reply_text("Пожалуйста, укажи только 'м' или 'ж'.")
        return ASK_GENDER
    user_profiles[update.message.from_user.id]["gender"] = gender
    await update.message.reply_text("Сколько тебе лет?")
    return ASK_AGE

async def ask_weight(update: Update, context: CallbackContext) -> int:
    try:
        age = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажи возраст числом.")
        return ASK_AGE
    user_profiles[update.message.from_user.id]["age"] = age
    await update.message.reply_text("Какой у тебя текущий вес (в кг)?")
    return ASK_WEIGHT

async def ask_goal(update: Update, context: CallbackContext) -> int:
    try:
        weight = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажи вес числом.")
        return ASK_WEIGHT
    user_profiles[update.message.from_user.id]["weight"] = weight
    await update.message.reply_text("Какая у тебя цель? (Похудеть, Набрать массу, Рельеф, Просто ЗОЖ)")
    return ASK_GOAL

async def ask_activity(update: Update, context: CallbackContext) -> int:
    user_profiles[update.message.from_user.id]["goal"] = update.message.text
    await update.message.reply_text("Какой у тебя уровень активности/опыта? (Новичок, Средний, Продвинутый)")
    return ASK_ACTIVITY

async def ask_diet_pref(update: Update, context: CallbackContext) -> int:
    user_profiles[update.message.from_user.id]["activity"] = update.message.text
    await update.message.reply_text("Есть ли у тебя предпочтения в еде? (Веганство, без глютена и т.п.)")
    return ASK_DIET_PREF

async def ask_health(update: Update, context: CallbackContext) -> int:
    user_profiles[update.message.from_user.id]["diet"] = update.message.text
    await update.message.reply_text("Есть ли у тебя ограничения по здоровью?")
    return ASK_HEALTH

async def ask_equipment(update: Update, context: CallbackContext) -> int:
    user_profiles[update.message.from_user.id]["health"] = update.message.text
    await update.message.reply_text("Какой инвентарь/тренажёры у тебя есть?")
    return ASK_EQUIPMENT

async def ask_target(update: Update, context: CallbackContext) -> int:
    user_profiles[update.message.from_user.id]["equipment"] = update.message.text
    await update.message.reply_text("Какая у тебя конкретная цель по весу или другим метрикам?")
    return ASK_TARGET

async def finish_questionnaire(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["target_metric"] = update.message.text
    name = user_profiles[user_id]["name"]
    save_user_profile(user_id, user_profiles[user_id])
    await update.message.reply_text(f"Отлично, {name}! Анкета завершена 🎉 Ты можешь отправлять мне фото, текст или документы — я помогу тебе с анализом и рекомендациями!")
    return ConversationHandler.END

async def show_profile(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("Профиль не найден. Пройди анкету с помощью /start.")
        return

    profile_text = (
        f"Твой профиль:\n\n"
        f"Имя: {row[1]}\nПол: {row[2]}\nВозраст: {row[3]}\nВес: {row[4]} кг\n"
        f"Цель: {row[5]}\nАктивность: {row[6]}\nПитание: {row[7]}\n"
        f"Здоровье: {row[8]}\nИнвентарь: {row[9]}\nЦелевая метрика: {row[10]}"
    )
    await update.message.reply_text(profile_text)

async def reset(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_histories.pop(user_id, None)
    user_profiles.pop(user_id, None)
    await update.message.reply_text("Контекст сброшен! Начнем с чистого листа 🧼")

async def generate_image(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Генерация изображений пока недоступна. Ждём обновления API Gemini 🎨")

async def handle_message(update: Update, context: CallbackContext) -> None:
    message = update.message
    user_id = message.from_user.id
    user_text = message.caption or message.text or ""
    contents = []

    # Обработка медиа
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

    # Получение профиля
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        profile_prompt = (
            f"Это пользователь по имени {row[1]}, пол: {row[2]}, возраст: {row[3]}, вес: {row[4]} кг, цель: {row[5]}, "
            f"уровень активности: {row[6]}, диета: {row[7]}, ограничения: {row[8]}, инвентарь: {row[9]}, целевая метрика: {row[10]}."
        )
        contents.insert(0, {"text": profile_prompt})

    # История сообщений
    if user_id not in user_histories:
        user_histories[user_id] = deque(maxlen=5)
    user_histories[user_id].append(user_text)
    history_messages = list(user_histories[user_id])
    if history_messages:
        history_prompt = "\n".join(f"Пользователь: {msg}" for msg in history_messages)
        contents.insert(0, {"text": f"История последних сообщений:\n{history_prompt}"})

    try:
        response = model.generate_content(contents)
        text = response.text

        # Попытка распарсить SQL и текст
        match = re.search(r"SQL:\s*(.*?)\nTEXT:\s*(.*)", text, re.DOTALL)
        if match:
            sql_query = match.group(1).strip()
            reply_text = match.group(2).strip()

            if sql_query.lower().startswith("update") or sql_query.lower().startswith("insert"):
                try:
                    conn = sqlite3.connect("users.db")
                    cursor = conn.cursor()
                    cursor.execute(sql_query, (user_id,))
                    conn.commit()
                    conn.close()
                except Exception as db_error:
                    await message.reply_text(f"Ошибка при выполнении SQL-запроса: {db_error}")
                    return

            await message.reply_text(reply_text)
        else:
            # Если нет SQL, просто шлём ответ как есть
            await message.reply_text(text)

    except Exception as e:
        await message.reply_text(f"Ошибка при генерации ответа: {e}")

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_gender)],
            ASK_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_age)],
            ASK_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_weight)],
            ASK_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_goal)],
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
