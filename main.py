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
        f"Цель: {row[5]}\n"
        f"Активность: {row[6]}\n"
        f"Питание: {row[7]}\n"
        f"Здоровье: {row[8]}\n"
        f"Инвентарь: {row[9]}\n"
        f"Целевая метрика: {row[10]}"
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
            await message.reply_text(f"Ошибка при загрузке файла: {str(e)}")
            return

    if user_text:
        contents.insert(0, {"text": user_text})
    if not contents:
        await message.reply_text("Пожалуйста, отправь текст, изображение или документ.")
        return

    # Профиль пользователя
    profile_info = get_user_profile_text(user_id)
    if profile_info and "не найден" not in profile_info:
        contents.insert(0, {"text": f"Информация о пользователе:\n{profile_info}"})

    # История
    if user_id not in user_histories:
        user_histories[user_id] = deque(maxlen=5)
    user_histories[user_id].append(user_text)
    history_messages = list(user_histories[user_id])
    if history_messages:
        history_prompt = "\n".join(f"Пользователь: {msg}" for msg in history_messages)
        contents.insert(0, {"text": f"История последних сообщений:\n{history_prompt}"})

    # Системный промпт
    GEMINI_SYSTEM_PROMPT = """
    You are a smart assistant who helps the user and, if necessary, updates his profile in the database.

You receive messages from the user. They can be:
- just questions (for example, about nutrition, workouts, photos, etc.)
- data updates (for example, "I gained 3 kg" or "I'm 20 years old now")
- messages after the image (for example, "add this to the inventory" or "here's my dinner")

The database has a user_profiles table with columns:
- user_id INTEGER PRIMARY KEY
- name TEXT
- gender TEXT
- age INTEGER
- weight REAL
- goal TEXT
- activity TEXT
- diet TEXT
- health TEXT
- equipment TEXT
- target_metric TEXT

Your task:

1. If there is a clear change in profile data in the message (for example: weight, age, goals, equipment, etc.) — generate:
    SQL: <SQL-request>
    TEXT: <reply to a person in natural language>

2. If it's just a question (for example: "what to eat after a workout?" or "what's in the photo?") — don't create SQL. Just give a useful, concise, but informative answer in the block.:
    TEXT: ...

3. If the user sent an image and then says "add this to my inventory", use the description of the object from the last image (for example, "Stern mountain bike"), rather than the word "image".

4. ⚠️ If the user sent an image of food and explicitly indicated that it was his food (for example, he wrote: "my breakfast", "what do you think about my lunch?", "evaluation of my dinner", "here's what I ate") — analyze the food in the photo and answer in the format:

TEXT:
🔍 Dish analysis:
(Describe what exactly is in the photo, with approximate weights/ingredients)

🍽 Approximate CPFC:
- Calories: ...
- Proteins: ...
- Fats: ...
- Carbohydrates: …

✅ Benefits and composition:
(Describe the benefits of each food element: protein, fiber, trace elements, etc.)

🧠 Bot's opinion:
(Briefly evaluate the meal: is it useful, suitable for weight loss / weight gain / balance, what can be improved or added)

💡 Advice (optional):
(Add a little advice if there is anything to improve)

5.If the user sends a message that:

- contains only the "." symbol,
- does not contain meaning,
- consists of a random set of characters,
- is a fragment of a phrase without context,
- contains only interjections, slang, emotional shouts, etc.,

then you should politely request clarification, for example:

"Hello there! Can you clarify what you wanted to say?"
"I don't think I quite understood. Could you reformulate?"
"I want to help, but I need a little more context. 😊"
"It looks like something went wrong, please clarify your request."

The answer should be natural, friendly, and concise, as if you were a caring but professional nutritionist.

⚠️ Never update your profile without explicitly indicating this (for example: "change", "add", "my weight is now...", etc.)

⚠️ Reply to the user in the same language in which he addresses you.

⚠️ The total length of the response **should never exceed 4096 characters** in order for the message to be sent correctly to Telegram. Shorten it if necessary, but keep it useful and structured.

Always return the response strictly in the format:
SQL: ...
TEXT: ...
or
TEXT: ...
"""
    contents.insert(0, {"text": GEMINI_SYSTEM_PROMPT})

    try:
        response = model.generate_content(contents)
        response_text = response.text.strip()

        # Разделим SQL и TEXT
        sql_match = re.search(r"SQL:\s*(.*?)\nTEXT:", response_text, re.DOTALL)
        text_match = re.search(r"TEXT:\s*(.+)", response_text, re.DOTALL)

        if sql_match:
            sql_query = sql_match.group(1).strip()

            try:
                conn = sqlite3.connect("users.db")
                cursor = conn.cursor()

                # Проверка: содержит ли SQL-запрос знак вопроса
                if "?" in sql_query:
                    cursor.execute(sql_query, (user_id,))
                else:
                    cursor.execute(sql_query)

                conn.commit()
                conn.close()
            except Exception as e:
                await message.reply_text(f"Ошибка при обновлении профиля: {e}")
                return

        if text_match:
            reply_text = text_match.group(1).strip()
            await message.reply_text(reply_text)
        else:
            # Если текстового ответа не найдено — просто верни всё как есть
            await message.reply_text(response_text)

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
