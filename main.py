import os
import re
import base64
import aiohttp
import sqlite3
import pytz
import telegram
from datetime import datetime, time
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
    ASK_TARGET, ASK_TIMEZONE, ASK_WAKEUP_TIME, ASK_SLEEP_TIME, ASK_WATER_REMINDERS
) = range(16)

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
        sleep_time TEXT,
        water_reminders INTEGER DEFAULT 1
    )
    ''')
    conn.commit()
    conn.close()

def save_user_profile(user_id: int, profile: dict):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR REPLACE INTO user_profiles
    (user_id, language, name, gender, age, weight, height, goal, activity, diet, health, 
     equipment, target_metric, unique_facts, timezone, wakeup_time, sleep_time, water_reminders)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        profile.get("sleep_time"),
        profile.get("water_reminders", 1),  # По умолчанию напоминания включены
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
        await update.message.reply_text("В каком городе или часовом поясе ты находишься? (Например: Москва, или Europe/Moscow, или UTC+3)")
    else:
        await update.message.reply_text("What city or timezone are you in? (e.g. New York, or America/New_York, or UTC-5)")
    return ASK_TIMEZONE

async def ask_wakeup_time(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    timezone_input = update.message.text.strip()
    
    # Попробуем определить часовой пояс
    try:
        if timezone_input.startswith(("UTC", "GMT")):
            tz = pytz.timezone(timezone_input)
        elif "/" in timezone_input:
            tz = pytz.timezone(timezone_input)
        else:
            # Попробуем найти город
            from timezonefinder import TimezoneFinder
            tf = TimezoneFinder()
            lat, lon = tf.get_lat_long(timezone_input)
            tz = tf.timezone_at(lat=lat, lng=lon)
            if not tz:
                raise ValueError("Не удалось определить часовой пояс")
        
        user_profiles[user_id]["timezone"] = tz.zone
    except Exception as e:
        print(f"Ошибка определения часового пояса: {e}")
        user_profiles[user_id]["timezone"] = timezone_input  # Сохраняем как есть
    
    if language == "ru":
        await update.message.reply_text("Во сколько ты обычно просыпаешься? (Формат: ЧЧ:ММ, например 07:30)")
    else:
        await update.message.reply_text("What time do you usually wake up? (Format: HH:MM, e.g. 07:30)")
    return ASK_WAKEUP_TIME

async def ask_sleep_time(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    
    try:
        wakeup_time = datetime.strptime(update.message.text, "%H:%M").time()
        user_profiles[user_id]["wakeup_time"] = update.message.text
    except ValueError:
        if language == "ru":
            await update.message.reply_text("Пожалуйста, укажи время в формате ЧЧ:ММ (например, 07:30)")
        else:
            await update.message.reply_text("Please enter time in HH:MM format (e.g. 07:30)")
        return ASK_WAKEUP_TIME
    
    if language == "ru":
        await update.message.reply_text("Во сколько ты обычно ложишься спать? (Формат: ЧЧ:ММ, например 23:00)")
    else:
        await update.message.reply_text("What time do you usually go to sleep? (Format: HH:MM, e.g. 23:00)")
    return ASK_SLEEP_TIME

async def ask_water_reminders(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    
    try:
        sleep_time = datetime.strptime(update.message.text, "%H:%M").time()
        user_profiles[user_id]["sleep_time"] = update.message.text
    except ValueError:
        if language == "ru":
            await update.message.reply_text("Пожалуйста, укажи время в формате ЧЧ:ММ (например, 23:00)")
        else:
            await update.message.reply_text("Please enter time in HH:MM format (e.g. 23:00)")
        return ASK_SLEEP_TIME
    
    if language == "ru":
        await update.message.reply_text("Хочешь ли ты получать напоминания пить воду в течение дня? (да/нет)")
    else:
        await update.message.reply_text("Do you want to receive water drinking reminders during the day? (yes/no)")
    return ASK_WATER_REMINDERS

async def finish_questionnaire(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id].get("language", "ru")
    answer = update.message.text.lower()
    
    if language == "ru":
        valid_answers = ["да", "нет"]
    else:
        valid_answers = ["yes", "no"]
    
    if answer not in valid_answers:
        if language == "ru":
            await update.message.reply_text("Пожалуйста, ответь 'да' или 'нет'")
        else:
            await update.message.reply_text("Please answer 'yes' or 'no'")
        return ASK_WATER_REMINDERS
    
    user_profiles[user_id]["water_reminders"] = 1 if answer in ["да", "yes"] else 0
    name = user_profiles[user_id]["name"]
    save_user_profile(user_id, user_profiles[user_id])
    
    # Запускаем задачу проверки времени для напоминаний
    context.job_queue.run_repeating(
        check_water_reminder_time,
        interval=300,  # Проверяем каждые 5 минут
        first=0,
        user_id=user_id,
        chat_id=update.message.chat_id
    )
    
    if language == "ru":
        await update.message.reply_text(
            f"Отлично, {name}! Анкета завершена 🎉\n"
            f"Я буду напоминать тебе пить воду в течение дня, если ты не отключишь эту функцию.\n"
            f"Ты можешь отправлять мне фото, текст или документы — я помогу тебе с анализом и рекомендациями!"
        )
    else:
        await update.message.reply_text(
            f"Great, {name}! Questionnaire completed 🎉\n"
            f"I'll remind you to drink water during the day unless you disable this feature.\n"
            f"You can send me photos, text or documents - I'll help you with analysis and recommendations!"
        )
    return ConversationHandler.END

async def check_water_reminder_time(context: CallbackContext):
    job = context.job
    user_id = job.user_id
    chat_id = job.chat_id
    
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT timezone, wakeup_time, sleep_time, water_reminders, language FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row[4]:  # Если нет данных или языка
        return
    
    timezone_str, wakeup_str, sleep_str, water_reminders, language = row
    
    if not water_reminders:  # Если напоминания отключены
        return
    
    try:
        # Получаем текущее время в часовом поясе пользователя
        if timezone_str:
            try:
                tz = pytz.timezone(timezone_str)
            except pytz.UnknownTimeZoneError:
                # Если часовой пояс не распознан, используем UTC
                tz = pytz.UTC
        else:
            tz = pytz.UTC
            
        now = datetime.now(tz).time()
        wakeup_time = datetime.strptime(wakeup_str, "%H:%M").time()
        sleep_time = datetime.strptime(sleep_str, "%H:%M").time()
        
        # Проверяем, что текущее время между временем подъема и сна
        if wakeup_time <= now <= sleep_time:
            # Проверяем, что сейчас подходящее время для напоминания (каждые 2 часа после подъема)
            wakeup_hour = wakeup_time.hour
            current_hour = now.hour
            hours_since_wakeup = (current_hour - wakeup_hour) % 24
            
            if hours_since_wakeup > 0 and hours_since_wakeup % 2 == 0 and now.minute < 30:
                # Проверяем, не отправляли ли уже напоминание в этот период
                last_reminder_key = f"last_water_reminder_{user_id}"
                last_reminder_hour = context.user_data.get(last_reminder_key, 0)
                
                if last_reminder_hour != hours_since_wakeup:
                    context.user_data[last_reminder_key] = hours_since_wakeup
                    
                    if language == "ru":
                        message = "💧 Не забудь выпить стакан воды! Это поможет поддерживать водный баланс и улучшит твое самочувствие."
                    else:
                        message = "💧 Don't forget to drink a glass of water! It will help maintain hydration and improve your well-being."
                    
                    await context.bot.send_message(chat_id=chat_id, text=message)
    except Exception as e:
        print(f"Ошибка при проверке времени для напоминания: {e}")

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
            f"Напоминания о воде: {'Включены' if row[17] else 'Выключены'}"
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
            f"Wake-up time: {row[15]}\n"
            f"Sleep time: {row[16]}\n"
            f"Water reminders: {'Enabled' if row[17] else 'Disabled'}"
        )
    await update.message.reply_text(profile_text)

async def reset(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    
    # Очищаем временные данные
    user_histories.pop(user_id, None)
    user_profiles.pop(user_id, None)
    
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

async def toggle_water_reminders(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    # Получаем текущее состояние напоминаний
    cursor.execute("SELECT water_reminders, language FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        await update.message.reply_text("Профиль не найден. Пройди анкету с помощью /start.\nProfile not found. Complete the questionnaire with /start.")
        return
    
    current_state, language = row
    new_state = 0 if current_state else 1
    
    # Обновляем состояние в базе данных
    cursor.execute("UPDATE user_profiles SET water_reminders = ? WHERE user_id = ?", (new_state, user_id))
    conn.commit()
    conn.close()
    
    if language == "ru":
        if new_state:
            message = "Напоминания о воде включены! Я буду напоминать тебе пить воду в течение дня."
        else:
            message = "Напоминания о воде отключены. Ты можешь снова включить их через команду /water."
    else:
        if new_state:
            message = "Water reminders enabled! I'll remind you to drink water during the day."
        else:
            message = "Water reminders disabled. You can enable them again with /water command."
    
    await update.message.reply_text(message)

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
            f"Напоминания о воде: {'Включены' if row[17] else 'Выключены'}"
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
            f"Wake-up time: {row[15]}\n"
            f"Sleep time: {row[16]}\n"
            f"Water reminders: {'Enabled' if row[17] else 'Disabled'}"
        )

async def handle_message(update: Update, context: CallbackContext) -> None:
    message = update.message
    user_id = message.from_user.id
    user_text = message.caption or message.text or ""
    contents = []

    # Обработка команды отключения напоминаний
    if user_text.lower() in [
        "больше не нужно мне напоминать о том, что мне нужно регулярно пить воду",
        "не напоминай мне пить воду",
        "отключи напоминания о воде",
        "stop water reminders",
        "don't remind me to drink water",
        "disable water reminders"
    ]:
        await toggle_water_reminders(update, context)
        return

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

    # Системный промпт (изменена только часть про анализ фото)
    GEMINI_SYSTEM_PROMPT = """Ты — умный ассистент, который помогает пользователю и при необходимости обновляет его профиль в базе данных.

Ты получаешь от пользователя сообщения. Они могут быть:
- просто вопросами (например, о питании, тренировках, фото и т.д.)
- обновлениями данных (например, "я набрал 3 кг" или "мне теперь 20 лет")
- сообщениями после изображения (например, "добавь это в инвентарь")
- уникальными фактами о пользователе (например, "я люблю плавание", "у меня была травма колена", "я вегетарианец 5 лет", "люблю кофе по вечерам")

В базе данных есть таблица user_profiles с колонками:
- user_id INTEGER PRIMARY KEY
- language TEXT
- name TEXT
- gender TEXT
- age INTEGER
- weight REAL
- height INTEGER
- goal TEXT
- activity TEXT
- diet TEXT
- health TEXT
- equipment TEXT
- target_metric TEXT
- unique_facts TEXT
- timezone TEXT
- wakeup_time TEXT
- sleep_time TEXT
- water_reminders INTEGER

Твоя задача:

1. Всегда сначала анализируй информацию из профиля пользователя (особенно поля diet, health, activity, unique_facts) и строго учитывай её в ответах.

2. Если в сообщении есть чёткое изменение данных профиля (например: вес, возраст, цели, оборудование и т.п.) — сгенерируй:
    SQL: <SQL-запрос>
    TEXT: <ответ человеку на естественном языке>

3. Если это просто вопрос (например: "что поесть после тренировки?" или "что на фото?") — дай полезный, краткий, но информативный ответ, ОБЯЗАТЕЛЬНО учитывая известные факты о пользователе:
    TEXT: ...

4. Если пользователь отправил изображение — анализируй ТОЛЬКО то, что действительно видно на фото, без домыслов. Если не уверен в деталях — уточни. 
   Если пользователь поправляет тебя (например: "на фото было 2 яйца, а не 3") — СРАЗУ ЖЕ учти это в следующем ответе и извинись за ошибку.

5. Если в сообщении есть уникальные факты о пользователе (увлечения, особенности здоровья, предпочтения, травмы и т.п.), которые не вписываются в стандартные поля профиля, но важны для персонализации:
   - Если факт относится к здоровью — добавь его в поле health
   - Если факт относится к питанию — добавь его в поле diet
   - Если факт относится к оборудованию/инвентарю — добавь его в поле equipment
   - Если факт относится к активности/спорту — добавь его в поле activity
   - Если факт не подходит ни к одной из этих категорий — добавь его в поле unique_facts
   Формат добавления: "Факт: [описание факта]."

   Примеры:
   - "Я люблю кофе по вечерам" → добавляется в diet: "Факт: Любит кофе по вечерам."
   - "У меня болит спина   - "У меня болит спина" → добавляется в health: "Факт: Боль в спине."
   - "Люблю плавать" → добавляется в activity: "Факт: Любит плавание."
   - "Я работаю программистом" → добавляется в unique_facts: "Факт: Работает программистом."
   - "У меня есть собака" → добавляется в unique_facts: "Факт: Есть собака."

6. ⚠️ Если пользователь отправил изображение еды и явно указал, что это его еда — проанализируй еду на фото и ответь в формате:

TEXT:
🔍 Анализ блюда:
(Опиши ТОЛЬКО то, что действительно видно на фото)

🍽 Примерный КБЖУ:
(На основе видимых ингредиентов)

✅ Польза и состав:
(Опиши пользу видимых элементов)

🧠 Мнение бота:
(Учитывая известные предпочтения пользователя)

💡 Совет:
(Если есть что улучшить, учитывая профиль)

7. Если пользователь поправляет тебя в анализе фото (например: "там было 2 яйца, а не 3"):
- Извинись за ошибку
- Немедленно пересмотри свой анализ с учетом новой информации
- Дай обновленный ответ, учитывая уточнение пользователя

8. Если пользователь упоминает, что ты не учел его предпочтения:
- Извинись
- Объясни, почему именно этот вариант может быть полезен
- Предложи адаптировать его под известные предпочтения

9. Если пользователь отправляет сообщение, которое:
- содержит только символ ".",
- не содержит смысла,
- состоит из случайного набора символов,
- является фрагментом фразы без контекста,
- содержит только междометия, сленг, эмоциональные выкрики и т.д.,
то вежливо запроси уточнение.

10. Отвечай приветствием только в тех случаях - когда к тебе самому обращаются с приветствием.

11. Если пользователь просит оценить состав тела по фото:
- Всегда начинай с предупреждения: "Визуальная оценка крайне приблизительна. Погрешность ±5-7%. Для точности нужны замеры (калипер, DEXA)."
- Основные диапазоны для мужчин:
  * Атлетичный: 6-10% жира, мышцы 70-80%
  * Подтянутый: 11-15% жира, мышцы 65-75%
  * Средний: 16-25% жира, мышцы 55-65%
  * Полный: 26-35% жира, мышцы 45-55%
  * Ожирение: 36%+ жира, мышцы 35-45%

- Основные диапазоны для женщин:
  * Атлетичный: 14-18% жира, мышцы 60-70%
  * Подтянутый: 19-23% жира, мышцы 55-65%
  * Средний: 24-30% жира, мышцы 50-60%
  * Полный: 31-38% жира, мышцы 40-50%
  * Ожирение: 39%+ жира, мышцы 30-40%

- Анализируй визуальные признаки:
  * Вены и резкий рельеф → атлетичный уровень
  * Четкие мышцы без вен → подтянутый
  * Мягкие формы → средний/полный
  * Складки жира → ожирение

- Всегда указывай:
  * Примерный % жира и мышц
  * Что кости/кожа составляют ~10-15% массы
  * Что для точности нужны профессиональные замеры

- Пример ответа:
  "По фото: % жира около 12-14% (подтянутый), мышцы ~65-70%. Визуальная оценка может быть неточной - рекомендуются инструментальные измерения."

12. Ответ должен быть естественным, дружелюбным и кратким, как будто ты — заботливый, но профессиональный диетолог.

⚠️ Никогда не выдумывай детали, которых нет в профиле или на фото. Если не уверен — уточни или скажи, что не знаешь.

⚠️ Всегда строго учитывай известные факты о пользователе из его профиля И контекст текущего диалога.

⚠️ Отвечай пользователю на том же языке, на котором он к тебе обращается (учитывай поле language в профиле).

⚠️ Общая длина ответа никогда не должна превышать 4096 символов.

Ответ всегда возвращай строго в формате:
SQL: ...
TEXT: ...
или
TEXT: ...
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
            ASK_TIMEZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_wakeup_time)],
            ASK_WAKEUP_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_sleep_time)],
            ASK_SLEEP_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_water_reminders)],
            ASK_WATER_REMINDERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_questionnaire)],
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("profile", show_profile))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("water", toggle_water_reminders))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()
