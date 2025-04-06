import os
import base64
import aiohttp
import telegram
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

# Создание модели
model = genai.GenerativeModel("gemini-2.0-flash")

# Хранение истории сообщений
user_histories = {}

# Хранение профилей пользователей
user_profiles = {}

# Состояния анкеты
(
    ASK_NAME, ASK_GENDER, ASK_AGE, ASK_WEIGHT, ASK_GOAL,
    ASK_ACTIVITY, ASK_DIET_PREF, ASK_HEALTH, ASK_EQUIPMENT, ASK_TARGET
) = range(10)

# Загрузка и кодирование файла
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

# === Анкета ===

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

# Сброс истории
async def reset(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_histories.pop(user_id, None)
    user_profiles.pop(user_id, None)
    await update.message.reply_text("Контекст сброшен! Начнем с чистого листа 🧼")

# Генерация изображения (заглушка)
async def generate_image(update: Update, context: CallbackContext) -> None:
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Напиши, что ты хочешь сгенерировать! Например:\n/generate_image футуристический бургер")
        return
    await update.message.reply_text("⚙️ Генерация изображения пока недоступна в API Gemini. Ожидаем активации от Google!")

# Основная логика обработки сообщений
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

    history = user_histories.get(user_id, [])

    try:
        history.append({"role": "user", "parts": contents})
        response = model.generate_content(history)
        reply = response.text.strip()

        if "bounding box detections" in reply and "`json" in reply:
            reply = reply.split("bounding box detections")[0].strip()
        if "На этом фото" in reply:
            reply = reply.replace("На этом фото", "\n\nНа этом фото")

        history.append({"role": "model", "parts": [reply]})
        user_histories[user_id] = history[-10:]
        await message.reply_text(f"{reply}")
    except Exception as e:
        await message.reply_text(f"Произошла ошибка: {str(e)}")

# Запуск бота
def main():
    app = Application.builder().token(TOKEN).build()

    questionnaire_handler = ConversationHandler(
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

    app.add_handler(questionnaire_handler)
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("generate_image", generate_image))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("🤖 NutriBot запущен с поддержкой текста, изображений, файлов и контекста + анкетой.")
    app.run_polling()



if __name__ == "__main__":
    main()


import sqlite3
from aiogram.types import Message


# Создаем/подключаемся к базе данных
conn = sqlite3.connect("users.db")
cursor = conn.cursor()

# Создаем таблицу, если она не существует
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    gender TEXT,
    age INTEGER,
    food_preferences TEXT
)
''')
conn.commit()

# Функция для добавления/обновления пользователя
def save_user(user_id, username, full_name):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if user is None:
        cursor.execute("INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
                       (user_id, username, full_name))
        conn.commit()

# Функция для обновления определенного поля
def update_user_field(user_id, field, value):
    cursor.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()

# Функция для получения данных пользователя
def get_user_data(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

def get_user_profile(user_id: int) -> dict:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        keys = ["user_id", "name", "gender", "age", "weight", "goal", "activity", "diet", "health", "equipment", "target_metric"]
        return dict(zip(keys, row))
    return {}

# Пример хендлера, где бот запоминает пользователя при старте
@dp.message_handler(commands=['start'])
async def start_handler(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "none"
    full_name = message.from_user.full_name
    save_user(user_id, username, full_name)
    await message.answer(f"Привет, {full_name}! Я запомню тебя :)")

# Пример: добавление/изменение предпочтений в еде
@dp.message_handler(lambda message: message.text.startswith("Мое любимое блюдо:"))
async def set_food_preference(message: Message):
    user_id = message.from_user.id
    food = message.text.replace("Мое любимое блюдо:", "").strip()
    update_user_field(user_id, "food_preferences", food)
    await message.answer(f"Запомнил, ты любишь {food}")

# Пример: бот вспоминает, что пользователь любит
@dp.message_handler(commands=["что_люблю"])
async def what_do_i_love(message: Message):
    user_data = get_user_data(message.from_user.id)
    if user_data and user_data[5]:  # food_preferences
        await message.answer(f"Ты говорил, что любишь {user_data[5]}")
    else:
        await message.answer("Я пока не знаю, что ты любишь 🙁")

@dp.message_handler(lambda message: message.text.isdigit() and 5 < int(message.text) < 120)
async def set_age(message: Message):
    user_id = message.from_user.id
    age = int(message.text)
    update_user_field(user_id, "age", age)
    await message.answer("Запомнил твой возраст!")


@dp.message_handler(lambda message: message.text.lower() in ["м", "ж", "мужской", "женский"])
async def set_gender(message: Message):
    user_id = message.from_user.id
    gender = message.text.lower()
    update_user_field(user_id, "gender", gender)
    await message.answer("Запомнил твой пол!")


@dp.message_handler(commands=["blank"])
async def show_profile(message: Message):
    user_data = get_user_data(message.from_user.id)
    if user_data:
        user_id, username, full_name, gender, age, food = user_data
        await message.answer(
            f"Вот что я о тебе знаю:\n"
            f"Имя: {full_name}\n"
            f"Пол: {gender or 'не указан'}\n"
            f"Возраст: {age or 'не указан'}\n"
            f"Любимая еда: {food or 'не указана'}"
        )
    else:
        await message.answer("Я пока ничего о тебе не знаю🙁")
