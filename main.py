import os
import re
import base64
import aiohttp
import sqlite3
import random
from datetime import datetime, timedelta
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
    ASK_LANGUAGE, ASK_NAME, ASK_GENDER, ASK_AGE, ASK_WEIGHT, ASK_HEIGHT,
    ASK_GOAL, ASK_ACTIVITY, ASK_DIET_PREF, ASK_HEALTH, ASK_EQUIPMENT,
    ASK_TARGET, ASK_TIMEZONE, ASK_WAKEUP, ASK_BEDTIME
) = range(15)

def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id INTEGER PRIMARY KEY,
        language TEXT,
        name TEXT,
        gender TEXT,
        age INTEGER,
        weight REAL,
        height INTEGER,
        goal TEXT,
        activity TEXT,
        diet TEXT,
        health TEXT,
        equipment TEXT,
        target_metric TEXT,
        unique_facts TEXT,
        timezone TEXT,
        wakeup_time TEXT,
        bedtime_time TEXT,
        water_intake REAL,
        last_water_reminder TEXT
    )
    ''')
    conn.commit()
    conn.close()

def save_user_profile(user_id: int, profile: dict):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR REPLACE INTO user_profiles
    (user_id, language, name, gender, age, weight, height, goal, activity, diet, 
     health, equipment, target_metric, unique_facts, timezone, wakeup_time, 
     bedtime_time, water_intake, last_water_reminder)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        profile.get("language"),
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
        profile.get("unique_facts"),
        profile.get("timezone"),
        profile.get("wakeup_time"),
        profile.get("bedtime_time"),
        profile.get("water_intake"),
        profile.get("last_water_reminder"),
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
    await update.message.reply_text(
        "Привет! Я твой персональный фитнес-ассистент NutriBot. Пожалуйста, выбери язык общения / Hello! I'm your personal fitness assistant NutriBot. Please choose your preferred language:\n\n"
        "🇷🇺 Русский - отправь 'ru'\n"
        "🇬🇧 English - send 'en'"
    )
    return ASK_LANGUAGE

async def ask_name(update: Update, context: CallbackContext) -> int:
    language = update.message.text.lower()
    if language not in ["ru", "en"]:
        await update.message.reply_text(
            "Пожалуйста, выбери 'ru' для русского или 'en' для английского / Please choose 'ru' for Russian or 'en' for English"
        )
        return ASK_LANGUAGE
    
    user_id = update.message.from_user.id
    user_profiles[user_id] = {"language": language}
    
    if language == "ru":
        await update.message.reply_text("Как тебя зовут?")
    else:
        await update.message.reply_text("What's your name?")
    return ASK_NAME

async def ask_gender(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    user_profiles[user_id]["name"] = update.message.text
    
    if language == "ru":
        await update.message.reply_text("Укажи свой пол (м/ж):")
    else:
        await update.message.reply_text("Specify your gender (m/f):")
    return ASK_GENDER

async def ask_age(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    gender = update.message.text.lower()
    
    if language == "ru":
        valid_genders = ["м", "ж"]
        error_msg = "Пожалуйста, укажи только 'м' или 'ж'."
    else:
        valid_genders = ["m", "f"]
        error_msg = "Please specify only 'm' or 'f'."
    
    if gender not in valid_genders:
        await update.message.reply_text(error_msg)
        return ASK_GENDER
    
    user_profiles[user_id]["gender"] = gender
    
    if language == "ru":
        await update.message.reply_text("Сколько тебе лет?")
    else:
        await update.message.reply_text("How old are you?")
    return ASK_AGE

async def ask_weight(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    
    try:
        age = int(update.message.text)
    except ValueError:
        if language == "ru":
            await update.message.reply_text("Пожалуйста, укажи возраст числом.")
        else:
            await update.message.reply_text("Please enter your age as a number.")
        return ASK_AGE
    
    user_profiles[user_id]["age"] = age
    
    if language == "ru":
        await update.message.reply_text("Какой у тебя текущий вес (в кг)?")
    else:
        await update.message.reply_text("What's your current weight (in kg)?")
    return ASK_WEIGHT

async def ask_height(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    
    try:
        weight = float(update.message.text.replace(",", "."))
    except ValueError:
        if language == "ru":
            await update.message.reply_text("Пожалуйста, укажи вес числом.")
        else:
            await update.message.reply_text("Please enter your weight as a number.")
        return ASK_WEIGHT
    
    user_profiles[user_id]["weight"] = weight
    
    if language == "ru":
        await update.message.reply_text("Какой у тебя рост (в см)?")
    else:
        await update.message.reply_text("What's your height (in cm)?")
    return ASK_HEIGHT

async def ask_goal(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    
    try:
        height = int(update.message.text)
        if height < 100 or height > 250:
            if language == "ru":
                await update.message.reply_text("Пожалуйста, укажи реальный рост (от 100 до 250 см).")
            else:
                await update.message.reply_text("Please enter a realistic height (100-250 cm).")
            return ASK_HEIGHT
    except ValueError:
        if language == "ru":
            await update.message.reply_text("Пожалуйста, укажи рост целым числом в сантиметрах.")
        else:
            await update.message.reply_text("Please enter your height as a whole number in centimeters.")
        return ASK_HEIGHT
    
    user_profiles[user_id]["height"] = height
    
    if language == "ru":
        await update.message.reply_text("Какая у тебя цель? (Похудеть, Набрать массу, Рельеф, Просто ЗОЖ)")
    else:
        await update.message.reply_text("What's your goal? (Lose weight, Gain mass, Get toned, Just healthy lifestyle)")
    return ASK_GOAL

async def ask_activity(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    user_profiles[user_id]["goal"] = update.message.text
    
    if language == "ru":
        await update.message.reply_text("Какой у тебя уровень активности/опыта? (Новичок, Средний, Продвинутый)")
    else:
        await update.message.reply_text("What's your activity/experience level? (Beginner, Intermediate, Advanced)")
    return ASK_ACTIVITY

async def ask_diet_pref(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    user_profiles[user_id]["activity"] = update.message.text
    
    if language == "ru":
        await update.message.reply_text("Есть ли у тебя предпочтения в еде? (Веганство, без глютена и т.п.)")
    else:
        await update.message.reply_text("Do you have any dietary preferences? (Vegan, gluten-free, etc.)")
    return ASK_DIET_PREF

async def ask_health(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    user_profiles[user_id]["diet"] = update.message.text
    
    if language == "ru":
        await update.message.reply_text("Есть ли у тебя ограничения по здоровью?")
    else:
        await update.message.reply_text("Do you have any health restrictions?")
    return ASK_HEALTH

async def ask_equipment(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    user_profiles[user_id]["health"] = update.message.text
    
    if language == "ru":
        await update.message.reply_text("Какой инвентарь/тренажёры у тебя есть?")
    else:
        await update.message.reply_text("What equipment do you have available?")
    return ASK_EQUIPMENT

async def ask_target(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    user_profiles[user_id]["equipment"] = update.message.text
    
    if language == "ru":
        await update.message.reply_text("Какая у тебя конкретная цель по весу или другим метрикам?")
    else:
        await update.message.reply_text("What's your specific weight or other metric target?")
    return ASK_TARGET

async def ask_timezone(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    user_profiles[user_id]["target_metric"] = update.message.text
    
    if language == "ru":
        await update.message.reply_text(
            "Укажите ваш часовой пояс (например, +3 для Москвы):\n"
            "Это нужно для правильного времени напоминаний."
        )
    else:
        await update.message.reply_text(
            "Enter your timezone (e.g., +3 for Moscow):\n"
            "This is needed for proper reminder timing."
        )
    return ASK_TIMEZONE

async def ask_wakeup(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    
    # Проверяем корректность часового пояса
    try:
        timezone = int(update.message.text)
        if not (-12 <= timezone <= 14):
            raise ValueError
    except ValueError:
        if language == "ru":
            await update.message.reply_text("Пожалуйста, введите корректный часовой пояс (от -12 до +14)")
            return ASK_TIMEZONE
        else:
            await update.message.reply_text("Please enter a valid timezone (from -12 to +14)")
            return ASK_TIMEZONE
    
    user_profiles[user_id]["timezone"] = str(timezone)
    
    if language == "ru":
        await update.message.reply_text("Во сколько вы обычно просыпаетесь? (Формат ЧЧ:MM, например 08:00)")
    else:
        await update.message.reply_text("What time do you usually wake up? (Format HH:MM, e.g. 08:00)")
    return ASK_WAKEUP

async def ask_bedtime(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    
    # Проверяем корректность времени подъема
    if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$', update.message.text):
        if language == "ru":
            await update.message.reply_text("Пожалуйста, введите время в формате ЧЧ:MM (например, 08:00)")
            return ASK_WAKEUP
        else:
            await update.message.reply_text("Please enter time in HH:MM format (e.g., 08:00)")
            return ASK_WAKEUP
    
    user_profiles[user_id]["wakeup_time"] = update.message.text
    
    if language == "ru":
        await update.message.reply_text("Во сколько вы обычно ложитесь спать? (Формат ЧЧ:MM, например 23:00)")
    else:
        await update.message.reply_text("What time do you usually go to bed? (Format HH:MM, e.g. 23:00)")
    return ASK_BEDTIME

async def finish_questionnaire(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    
    # Проверяем корректность времени отхода ко сну
    if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$', update.message.text):
        if language == "ru":
            await update.message.reply_text("Пожалуйста, введите время в формате ЧЧ:MM (например, 23:00)")
            return ASK_BEDTIME
        else:
            await update.message.reply_text("Please enter time in HH:MM format (e.g., 23:00)")
            return ASK_BEDTIME
    
    user_profiles[user_id]["bedtime_time"] = update.message.text
    
    # Рассчитываем норму воды (35 мл на 1 кг веса)
    weight = user_profiles[user_id].get("weight", 70)  # 70 кг по умолчанию
    water_intake = weight * 35 / 1000  # в литрах
    user_profiles[user_id]["water_intake"] = round(water_intake, 1)
    
    save_user_profile(user_id, user_profiles[user_id])
    
    # Запускаем фоновую задачу для проверки времени
    context.job_queue.run_repeating(
        callback=check_time_and_send_reminders,
        interval=300,  # Проверка каждые 5 минут
        first=10,       # Первая проверка через 10 секунд
        user_id=user_id,
        chat_id=update.effective_chat.id,
        name=str(user_id)  # Имя задачи для последующего удаления
        )
    
    if language == "ru":
        await update.message.reply_text(
            f"Отлично! Анкета завершена 🎉\n"
            f"Ваша норма воды: ~{water_intake:.1f} л/день.\n"
            f"Напоминания будут приходить с {user_profiles[user_id]['wakeup_time']} до {user_profiles[user_id]['bedtime_time']} по вашему времени."
        )
    else:
        await update.message.reply_text(
            f"Great! Questionnaire completed 🎉\n"
            f"Your water intake: ~{water_intake:.1f} l/day.\n"
            f"Reminders will be sent from {user_profiles[user_id]['wakeup_time']} to {user_profiles[user_id]['bedtime_time']} your local time."
        )
    return ConversationHandler.END

async def check_time_and_send_reminders(context: CallbackContext):
    job = context.job
    user_id = job.user_id
    chat_id = job.chat_id
    
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT language, timezone, wakeup_time, bedtime_time, water_intake, last_water_reminder FROM user_profiles WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return
    
    language, timezone_str, wakeup, bedtime, water_intake, last_reminder = row
    
    try:
        timezone = int(timezone_str)
    except (ValueError, TypeError):
        timezone = 3  # По умолчанию Московское время
    
    # Получаем текущее время в UTC
    utc_now = datetime.utcnow()
    
    # Вычисляем "локальное" время пользователя
    user_hour = (utc_now.hour + timezone) % 24
    user_minute = utc_now.minute
    current_time_str = f"{user_hour:02d}:{user_minute:02d}"
    
    # Проверяем, находится ли текущее время между временем подъема и отхода ко сну
    if not (wakeup <= current_time_str < bedtime):
        return
    
    # Проверяем, когда было последнее напоминание
    if last_reminder:
        last_time = datetime.strptime(last_reminder, "%Y-%m-%d %H:%M:%S")
        if (utc_now - last_time) < timedelta(hours=1):  # Не чаще чем раз в час
            return
    
    # Отправляем напоминание
    remaining = max(0, water_intake - 0.25)  # Предполагаем 250 мл за стакан
    
    if language == "ru":
        message = f"⏰ Напоминание о воде: сейчас хорошее время выпить стакан воды (~250 мл). Осталось сегодня: ~{remaining:.1f} л."
    else:
        message = f"⏰ Water reminder: now is a good time to drink a glass (~250 ml). Remaining today: ~{remaining:.1f} l."
    
    await context.bot.send_message(chat_id=chat_id, text=message)
    
    # Обновляем время последнего напоминания
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE user_profiles SET last_water_reminder = ?, water_intake = ? WHERE user_id = ?",
        (utc_now.strftime("%Y-%m-%d %H:%M:%S"), remaining, user_id)
    )
    conn.commit()
    conn.close()

async def show_profile(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        language = user_profiles.get(user_id, {}).get("language", "ru")
        if language == "ru":
            await update.message.reply_text("Профиль не найден. Пройди анкету с помощью /start.")
        else:
            await update.message.reply_text("Profile not found. Complete the questionnaire with /start.")
        return

    language = row[1]  # language is the second column in the database
    
    if language == "ru":
        profile_text = (
            f"Твой профиль:\n\n"
            f"Язык: {row[1]}\n"
            f"Имя: {row[2]}\n"
            f"Пол: {row[3]}\n"
            f"Возраст: {row[4]}\n"
            f"Вес: {row[5]} кг\n"
            f"Рост: {row[6]} см\n"
            f"Цель: {row[7]}\n"
            f"Активность: {row[8]}\n"
            f"Питание: {row[9]}\n"
            f"Здоровье: {row[10]}\n"
            f"Инвентарь: {row[11]}\n"
            f"Целевая метрика: {row[12]}\n"
            f"Уникальные факты: {row[13]}\n"
            f"Часовой пояс: {row[14]}\n"
            f"Время подъема: {row[15]}\n"
            f"Время сна: {row[16]}\n"
            f"Норма воды: {row[17]} л/день"
        )
    else:
        profile_text = (
            f"Your profile:\n\n"
            f"Language: {row[1]}\n"
            f"Name: {row[2]}\n"
            f"Gender: {row[3]}\n"
            f"Age: {row[4]}\n"
            f"Weight: {row[5]} kg\n"
            f"Height: {row[6]} cm\n"
            f"Goal: {row[7]}\n"
            f"Activity: {row[8]}\n"
            f"Diet: {row[9]}\n"
            f"Health: {row[10]}\n"
            f"Equipment: {row[11]}\n"
            f"Target metric: {row[12]}\n"
            f"Unique facts: {row[13]}\n"
            f"Timezone: {row[14]}\n"
            f"Wakeup time: {row[15]}\n"
            f"Bedtime: {row[16]}\n"
            f"Water intake: {row[17]} l/day"
        )
    await update.message.reply_text(profile_text)

async def reset(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    
    # Очищаем временные данные
    user_histories.pop(user_id, None)
    user_profiles.pop(user_id, None)
    
    # Удаляем все запланированные задачи для этого пользователя
    jobs = context.job_queue.get_jobs_by_name(str(user_id))
    for job in jobs:
        job.schedule_removal()
    
    # Удаляем пользователя из базы данных
    try:
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text("Все данные успешно сброшены! Начнем с чистого листа 🧼\nAll data has been reset! Let's start fresh 🧼")
    except Exception as e:
        await update.message.reply_text(f"Произошла ошибка при сбросе данных: {e}\nAn error occurred while resetting data: {e}")

async def water_now(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT language, water_intake FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        language = user_profiles.get(user_id, {}).get("language", "ru")
        if language == "ru":
            await update.message.reply_text("Сначала пройди анкету с помощью /start")
        else:
            await update.message.reply_text("Please complete the questionnaire with /start first")
        return
    
    language, water_intake = row
    
    if language == "ru":
        await update.message.reply_text(
            f"Твоя рекомендуемая норма воды: ~{water_intake:.1f} л/день. "
            "Сейчас хорошее время выпить стакан воды (~250 мл)."
        )
    else:
        await update.message.reply_text(
            f"Your recommended water intake: ~{water_intake:.1f} l/day. "
            "Now is a good time to drink a glass of water (~250 ml)."
        )

async def stop_water_reminders(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    # Удаляем все запланированные работы для этого пользователя
    jobs = context.job_queue.get_jobs_by_name(str(user_id))
    for job in jobs:
        job.schedule_removal()
    
    language = user_profiles.get(user_id, {}).get("language", "ru")
    if language == "ru":
        await update.message.reply_text("Напоминания о воде остановлены. Чтобы возобновить, используйте /start")
    else:
        await update.message.reply_text("Water reminders stopped. Use /start to resume")

def get_user_profile_text(user_id: int) -> str:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return "Профиль пользователя не найден / User profile not found."

    language = row[1]  # language is the second column in the database
    
    if language == "ru":
        return (
            f"Язык: {row[1]}\n"
            f"Имя: {row[2]}\n"
            f"Пол: {row[3]}\n"
            f"Возраст: {row[4]}\n"
            f"Вес: {row[5]} кг\n"
            f"Рост: {row[6]} см\n"
            f"Цель: {row[7]}\n"
            f"Активность: {row[8]}\n"
            f"Питание: {row[9]}\n"
            f"Здоровье: {row[10]}\n"
            f"Инвентарь: {row[11]}\n"
            f"Целевая метрика: {row[12]}\n"
            f"Уникальные факты: {row[13]}\n"
            f"Часовой пояс: {row[14]}\n"
            f"Время подъема: {row[15]}\n"
            f"Время сна: {row[16]}\n"
            f"Норма воды: {row[17]} л/день"
        )
    else:
        return (
            f"Language: {row[1]}\n"
            f"Name: {row[2]}\n"
            f"Gender: {row[3]}\n"
            f"Age: {row[4]}\n"
            f"Weight: {row[5]} kg\n"
            f"Height: {row[6]} cm\n"
            f"Goal: {row[7]}\n"
            f"Activity: {row[8]}\n"
            f"Diet: {row[9]}\n"
            f"Health: {row[10]}\n"
            f"Equipment: {row[11]}\n"
            f"Target metric: {row[12]}\n"
            f"Unique facts: {row[13]}\n"
            f"Timezone: {row[14]}\n"
            f"Wakeup time: {row[15]}\n"
            f"Bedtime: {row[16]}\n"
            f"Water intake: {row[17]} l/day"
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
            await message.reply_text(f"Ошибка при загрузке файла: {str(e)}\nError loading file: {str(e)}")
            return

    if user_text:
        contents.insert(0, {"text": user_text})
    if not contents:
        await message.reply_text("Пожалуйста, отправь текст, изображение или документ.\nPlease send text, image or document.")
        return

    # Профиль пользователя
    profile_info = get_user_profile_text(user_id)
    if profile_info and "не найден" not in profile_info and "not found" not in profile_info:
        contents.insert(0, {"text": f"Информация о пользователе / User information:\n{profile_info}"})

    # История - увеличиваем размер очереди до 10 сообщений
    if user_id not in user_histories:
        user_histories[user_id] = deque(maxlen=10)
    user_histories[user_id].append(f"Пользователь / User: {user_text}")
    
    # Добавляем предыдущие ответы бота в историю
    if 'last_bot_reply' in context.user_data:
        user_histories[user_id].append(f"Бот / Bot: {context.user_data['last_bot_reply']}")
    
    history_messages = list(user_histories[user_id])
    if history_messages:
        history_prompt = "\n".join(history_messages)
        contents.insert(0, {"text": f"Контекст текущего диалога / Current dialog context (последние сообщения / recent messages):\n{history_prompt}"})

    # Системный промпт
    GEMINI_SYSTEM_PROMPT = """Ты — умный ассистент, который помогает пользователю и при необходимости обновляет его профиль в базе данных.

[Остальной системный промпт остается без изменений]
"""
    contents.insert(0, {"text": GEMINI_SYSTEM_PROMPT})

    try:
        response = model.generate_content(contents)
        response_text = response.text.strip()

        # Сохраняем последний ответ бота в контексте
        context.user_data['last_bot_reply'] = response_text

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
                await message.reply_text(f"Ошибка при обновлении профиля: {e}\nError updating profile: {e}")
                return

        if text_match:
            reply_text = text_match.group(1).strip()
            await message.reply_text(reply_text)
        else:
            # Если текстового ответа не найдено — просто верни всё как есть
            await message.reply_text(response_text)

    except Exception as e:
        await message.reply_text(f"Ошибка при генерации ответа: {e}\nError generating response: {e}")

async def generate_image(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Генерация изображений пока недоступна.\nImage generation is not available yet.")

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
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
            ASK_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_timezone)],
            ASK_TIMEZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_wakeup)],
            ASK_WAKEUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_bedtime)],
            ASK_BEDTIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_questionnaire)],
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
