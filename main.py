import os
import re
import base64
import aiohttp
import sqlite3
import pytz
import telegram
import json
import pymysql
from pymysql.cursors import DictCursor
from datetime import datetime, time, date
from collections import deque
from telegram import Update, File
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, CallbackContext, ConversationHandler
)
import google.generativeai as genai
from datetime import datetime, time, timedelta


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
    conn = pymysql.connect(
        host='x91345bo.beget.tech',
        user='x91345bo_nutrbot',
        password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
        database='x91345bo_nutrbot',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        with conn.cursor() as cursor:
            # Сначала проверяем существование таблицы
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id BIGINT PRIMARY KEY,
                    language VARCHAR(10),
                    name VARCHAR(100),
                    gender VARCHAR(10),
                    age INT,
                    weight FLOAT,
                    height INT,
                    goal TEXT,
                    activity TEXT,
                    diet TEXT,
                    health TEXT,
                    equipment TEXT,
                    target_metric TEXT,
                    unique_facts TEXT,
                    timezone VARCHAR(50),
                    wakeup_time VARCHAR(5),
                    sleep_time VARCHAR(5),
                    water_reminders TINYINT DEFAULT 1,
                    water_drunk_today INT DEFAULT 0,
                    last_water_notification TEXT,
                    calories_today INT DEFAULT 0,
                    proteins_today INT DEFAULT 0,
                    fats_today INT DEFAULT 0,
                    carbs_today INT DEFAULT 0,
                    last_nutrition_update DATE,
                    reminders TEXT
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            
            # Проверяем существование колонок и добавляем их, если нужно
            cursor.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'user_profiles'
            """)
            existing_columns = {row['COLUMN_NAME'] for row in cursor.fetchall()}
            
            # Добавляем недостающие колонки
            if 'reminders' not in existing_columns:
                cursor.execute("ALTER TABLE user_profiles ADD COLUMN reminders TEXT")
            
        conn.commit()
    except Exception as e:
        print(f"Ошибка при инициализации базы данных: {e}")
        raise
    finally:
        conn.close()


def save_user_profile(user_id: int, profile: dict):
    conn = pymysql.connect(
        host='x91345bo.beget.tech',
        user='x91345bo_nutrbot',
        password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
        database='x91345bo_nutrbot',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        with conn.cursor() as cursor:
            # Очищаем текстовые поля от старых "Факт:" перед сохранением
            for field in ['diet', 'health', 'equipment', 'unique_facts']:
                if field in profile and isinstance(profile[field], str):
                    if profile[field].startswith("Нет") or profile[field].startswith("Ничего"):
                        profile[field] = ""
            
            reminders = json.dumps(profile.get("reminders", []))
            
            cursor.execute('''
            INSERT INTO user_profiles (
                user_id, language, name, gender, age, weight, height, goal, activity, diet, 
                health, equipment, target_metric, unique_facts, timezone, wakeup_time, sleep_time,
                water_reminders, water_drunk_today, last_water_notification,
                calories_today, proteins_today, fats_today, carbs_today, last_nutrition_update, reminders
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
                %s, %s, %s, %s, %s, %s, %s, 
                %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                language = VALUES(language),
                name = VALUES(name),
                gender = VALUES(gender),
                age = VALUES(age),
                weight = VALUES(weight),
                height = VALUES(height),
                goal = VALUES(goal),
                activity = VALUES(activity),
                diet = VALUES(diet),
                health = VALUES(health),
                equipment = VALUES(equipment),
                target_metric = VALUES(target_metric),
                unique_facts = VALUES(unique_facts),
                timezone = VALUES(timezone),
                wakeup_time = VALUES(wakeup_time),
                sleep_time = VALUES(sleep_time),
                water_reminders = VALUES(water_reminders),
                water_drunk_today = VALUES(water_drunk_today),
                last_water_notification = VALUES(last_water_notification),
                calories_today = VALUES(calories_today),
                proteins_today = VALUES(proteins_today),
                fats_today = VALUES(fats_today),
                carbs_today = VALUES(carbs_today),
                last_nutrition_update = VALUES(last_nutrition_update),
                reminders = VALUES(reminders)
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
                profile.get("water_reminders", 1),
                profile.get("water_drunk_today", 0),
                profile.get("last_water_notification", ""),
                profile.get("calories_today", 0),
                profile.get("proteins_today", 0),
                profile.get("fats_today", 0),
                profile.get("carbs_today", 0),
                profile.get("last_nutrition_update", date.today().isoformat()),
                reminders
            ))
        conn.commit()
    except Exception as e:
        print(f"Ошибка при сохранении профиля: {e}")
        raise
    finally:
        conn.close()


async def reset_daily_nutrition_if_needed(user_id: int):
    conn = pymysql.connect(
        host='x91345bo.beget.tech',
        user='x91345bo_nutrbot',
        password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
        database='x91345bo_nutrbot',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT last_nutrition_update FROM user_profiles WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            
            if result and result['last_nutrition_update']:
                last_update = result['last_nutrition_update']
                if last_update < date.today():
                    cursor.execute('''
                        UPDATE user_profiles 
                        SET calories_today = 0, proteins_today = 0, fats_today = 0, carbs_today = 0,
                            last_nutrition_update = %s, water_drunk_today = 0
                        WHERE user_id = %s
                    ''', (date.today().isoformat(), user_id))
                    conn.commit()
    finally:
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
    
    # Упрощенная обработка часового пояса
    try:
        if timezone_input.startswith(("UTC+", "UTC-", "GMT+", "GMT-")):
            # Преобразуем UTC+3 в Etc/GMT-3 (знаки обратные)
            offset_str = timezone_input[3:]
            offset = int(offset_str) if offset_str else 0
            tz = pytz.timezone(f"Etc/GMT{-offset}" if offset > 0 else f"Etc/GMT{+offset}")
        elif timezone_input.startswith("+"):
            # Обработка формата "+3"
            offset = int(timezone_input[1:])
            tz = pytz.timezone(f"Etc/GMT{-offset}")
        elif timezone_input.startswith("-"):
            # Обработка формата "-5"
            offset = int(timezone_input[1:])
            tz = pytz.timezone(f"Etc/GMT{+offset}")
        elif "/" in timezone_input:
            tz = pytz.timezone(timezone_input)
        else:
            # Попробуем найти город в базе данных pytz
            try:
                tz = pytz.timezone(timezone_input)
            except pytz.UnknownTimeZoneError:
                # Если город не найден, используем UTC как fallback
                tz = pytz.UTC
        
        user_profiles[user_id]["timezone"] = tz.zone
        print(f"Установлен часовой пояс для пользователя {user_id}: {tz.zone}")
    except Exception as e:
        print(f"Ошибка определения часового пояса: {e}")
        # Используем UTC как fallback
        user_profiles[user_id]["timezone"] = "UTC"
    
    if language == "ru":
        await update.message.reply_text("Во сколько ты обычно просыпаешься? (Формат: ЧЧ:ММ, например 07:30)")
    else:
        await update.message.reply_text("What time do you usually wake up? (Format: HH:MM, e.g. 07:30)")
    return ASK_WAKEUP_TIME


async def ask_sleep_time(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    
    # First try in-memory storage
    if user_id not in user_profiles:
        # Fallback to database
        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("SELECT language FROM user_profiles WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            # Reconstruct minimal profile from database
            user_profiles[user_id] = {"language": row[0]}
        else:
            # If not found anywhere, restart questionnaire
            await update.message.reply_text("Сессия устарела. Пожалуйста, начните заново с /start\nSession expired. Please start again with /start")
            return ConversationHandler.END
    
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
    user_profiles[user_id]["water_drunk_today"] = 0
    user_profiles[user_id]["reminders"] = []  # Инициализируем пустой список напоминаний
    
    name = user_profiles[user_id]["name"]
    weight = user_profiles[user_id]["weight"]
    recommended_water = int(weight * 30)
    save_user_profile(user_id, user_profiles[user_id])
    
    # Удаляем старые задачи для этого пользователя, если они есть
    current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
    for job in current_jobs:
        job.schedule_removal()
    
    # Создаем новую задачу для напоминаний
    if user_profiles[user_id]["water_reminders"]:
        context.job_queue.run_repeating(
            check_water_reminder_time,
            interval=300,
            first=10,
            chat_id=update.message.chat_id,
            user_id=user_id,
            name=str(user_id)
        )
        print(f"Создана задача напоминаний для пользователя {user_id}")
    
    if language == "ru":
        await update.message.reply_text(
            f"Отлично, {name}! Анкета завершена 🎉\n"
            f"На основе твоего веса ({weight} кг) тебе рекомендуется выпивать {recommended_water} мл воды в день.\n"
            f"Я буду напоминать тебе пить воду в течение дня, если ты не отключишь эту функцию.\n"
            f"Ты можешь отправлять мне фото, текст или документы — я помогу тебе с анализом и рекомендациями!"
        )
    else:
        await update.message.reply_text(
            f"Great, {name}! Questionnaire completed 🎉\n"
            f"Based on your weight ({weight} kg), your recommended daily water intake is {recommended_water} ml.\n"
            f"I'll remind you to drink water during the day unless you disable this feature.\n"
            f"You can send me photos, text or documents - I'll help you with analysis and recommendations!"
        )
    return ConversationHandler.END


async def check_reminders(context: CallbackContext):
    conn = pymysql.connect(
        host='x91345bo.beget.tech',
        user='x91345bo_nutrbot',
        password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
        database='x91345bo_nutrbot',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT user_id, reminders, timezone, language 
                FROM user_profiles 
                WHERE reminders != '[]' AND reminders IS NOT NULL
            """)
            users = cursor.fetchall()

        for user in users:
            try:
                if not user['reminders'] or user['reminders'] == '[]':
                    continue
                    
                reminders = json.loads(user['reminders'])
                tz = pytz.timezone(user['timezone']) if user['timezone'] else pytz.UTC
                now = datetime.now(tz)
                current_time = now.strftime("%H:%M")

                for reminder in reminders:
                    if reminder["time"] == current_time and reminder.get("last_sent") != now.date().isoformat():
                        try:
                            if user['language'] == "ru":
                                message = (
                                    f"⏰ Напоминание: {reminder['text']}\n\n"
                                    f"(Отправьте 'хватит напоминать мне {reminder['text']}' чтобы отключить это напоминание)"
                                )
                            else:
                                message = (
                                    f"⏰ Reminder: {reminder['text']}\n\n"
                                    f"(Send 'stop reminding me {reminder['text']}' to disable this reminder)"
                                )

                            await context.bot.send_message(chat_id=user['user_id'], text=message)

                            # Обновляем дату последней отправки
                            reminder["last_sent"] = now.date().isoformat()
                            with conn.cursor() as update_cursor:
                                update_cursor.execute(
                                    "UPDATE user_profiles SET reminders = %s WHERE user_id = %s",
                                    (json.dumps(reminders), user['user_id'])
                                )
                            conn.commit()
                            
                        except Exception as e:
                            print(f"Ошибка при отправке напоминания пользователю {user['user_id']}: {e}")
            except Exception as e:
                print(f"Ошибка при обработке напоминаний для пользователя {user['user_id']}: {e}")
                print(f"Reminders JSON: {user['reminders']}")
                print(f"Error details: {str(e)}")
    finally:
        conn.close()


async def check_water_reminder_time(context: CallbackContext):
    job = context.job
    user_id = job.user_id
    chat_id = job.chat_id
    
    conn = pymysql.connect(
        host='x91345bo.beget.tech',
        user='x91345bo_nutrbot',
        password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
        database='x91345bo_nutrbot',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT timezone, wakeup_time, sleep_time, water_reminders, language, 
                       water_drunk_today, last_water_notification, weight 
                FROM user_profiles 
                WHERE user_id = %s
            """, (user_id,))
            row = cursor.fetchone()
        
        if not row:
            print(f"Профиль пользователя {user_id} не найден")
            return
        
        if not row['water_reminders']:
            print(f"Напоминания отключены для пользователя {user_id}")
            return
        
        recommended_water = int(row['weight'] * 30)
        
        if row['water_drunk_today'] >= recommended_water:
            print(f"Пользователь {user_id} уже выпил достаточное количество воды")
            return  

        try:
            tz = pytz.timezone(row['timezone']) if row['timezone'] else pytz.UTC
            now = datetime.now(tz)
            current_time = now.time()
            today = now.date()
            
            if row['last_water_notification']:
                try:
                    last_notif_datetime = datetime.strptime(row['last_water_notification'], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
                    time_since_last = now - last_notif_datetime
                    if time_since_last.total_seconds() < 3600:
                        print(f"Слишком рано для нового напоминания пользователю {user_id}")
                        return
                except ValueError as e:
                    print(f"Ошибка парсинга времени последнего уведомления: {e}")
            
            wakeup_time = datetime.strptime(row['wakeup_time'], "%H:%M").time()
            sleep_time = datetime.strptime(row['sleep_time'], "%H:%M").time()
            
            wakeup_dt = datetime.combine(today, wakeup_time).astimezone(tz)
            sleep_dt = datetime.combine(today, sleep_time).astimezone(tz)
            current_dt = datetime.combine(today, current_time).astimezone(tz)
            
            if sleep_time < wakeup_time:
                sleep_dt += timedelta(days=1)
            
            is_active_time = wakeup_dt <= current_dt <= sleep_dt
            
            if not is_active_time:
                print(f"Текущее время {current_time} вне периода активности пользователя {user_id} ({wakeup_time}-{sleep_time})")
                return
            
            remaining_water = max(0, recommended_water - row['water_drunk_today'])
            time_since_wakeup = current_dt - wakeup_dt
            hours_since_wakeup = time_since_wakeup.total_seconds() / 3600
            
            reminder_interval = 2
            if hours_since_wakeup >= 0 and hours_since_wakeup % reminder_interval <= 0.1:
                last_notif_hour = None
                if row['last_water_notification']:
                    try:
                        last_notif_datetime = datetime.strptime(row['last_water_notification'], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
                        last_notif_since_wakeup = last_notif_datetime - wakeup_dt
                        last_notif_hour = last_notif_since_wakeup.total_seconds() / 3600
                    except ValueError as e:
                        print(f"Ошибка парсинга времени последнего уведомления: {e}")
                
                if last_notif_hour is None or (hours_since_wakeup - last_notif_hour) >= (reminder_interval - 0.1):
                    with conn.cursor() as update_cursor:
                        update_cursor.execute("""
                            UPDATE user_profiles 
                            SET last_water_notification = %s 
                            WHERE user_id = %s
                        """, (now.strftime("%Y-%m-%d %H:%M:%S"), user_id))
                    conn.commit()
                    
                    water_to_drink_now = min(250, max(150, recommended_water // 8))
                    
                    if row['language'] == "ru":
                        message = (
                            f"💧 Не забудь выпить воду! Сейчас рекомендуется выпить {water_to_drink_now} мл.\n"
                            f"📊 Сегодня выпито: {row['water_drunk_today']} мл из {recommended_water} мл\n"
                            f"🚰 Осталось выпить: {remaining_water} мл\n\n"
                            f"После того как выпьешь воду, отправь мне сообщение в формате:\n"
                            f"'Выпил 250 мл' или 'Drank 300 ml'"
                        )
                    else:
                        message = (
                            f"💧 Don't forget to drink water! Now it's recommended to drink {water_to_drink_now} ml.\n"
                            f"📊 Today drunk: {row['water_drunk_today']} ml of {recommended_water} ml\n"
                            f"🚰 Remaining: {remaining_water} ml\n\n"
                            f"After drinking water, send me a message in the format:\n"
                            f"'Drank 300 ml' or 'Выпил 250 мл'"
                        )
                    
                    await context.bot.send_message(chat_id=chat_id, text=message)
                    print(f"Напоминание отправлено пользователю {user_id} в {now}")
        
        except Exception as e:
            print(f"Ошибка при проверке времени для напоминания пользователю {user_id}: {str(e)}")
    finally:
        conn.close()


async def show_profile(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    await reset_daily_nutrition_if_needed(user_id)
    
    conn = pymysql.connect(
        host='x91345bo.beget.tech',
        user='x91345bo_nutrbot',
        password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
        database='x91345bo_nutrbot',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()

        if not row:
            language = user_profiles.get(user_id, {}).get("language", "ru")
            if language == "ru":
                await update.message.reply_text("Профиль не найден. Пройди анкету с помощью /start.")
            else:
                await update.message.reply_text("Profile not found. Complete the questionnaire with /start.")
            return

        language = row['language']
        weight = row['weight']
        recommended_water = int(weight * 30)
        water_drunk = row['water_drunk_today'] if row['water_drunk_today'] is not None else 0
        remaining_water = max(0, recommended_water - water_drunk)
        
        calories = row['calories_today'] if row['calories_today'] is not None else 0
        proteins = row['proteins_today'] if row['proteins_today'] is not None else 0
        fats = row['fats_today'] if row['fats_today'] is not None else 0
        carbs = row['carbs_today'] if row['carbs_today'] is not None else 0
        
        if language == "ru":
            profile_text = (
                f"Твой профиль:\n\n"
                f"Язык: {row['language']}\n"
                f"Имя: {row['name']}\n"
                f"Пол: {row['gender']}\n"
                f"Возраст: {row['age']}\n"
                f"Вес: {row['weight']} кг\n"
                f"Рост: {row['height']} см\n"
                f"Цель: {row['goal']}\n"
                f"Активность: {row['activity']}\n"
                f"Питание: {row['diet']}\n"
                f"Здоровье: {row['health']}\n"
                f"Инвентарь: {row['equipment']}\n"
                f"Целевая метрика: {row['target_metric']}\n"
                f"Уникальные факты: {row['unique_facts']}\n"
                f"Часовой пояс: {row['timezone']}\n"
                f"Время подъема: {row['wakeup_time']}\n"
                f"Время сна: {row['sleep_time']}\n"
                f"Напоминания о воде: {'Включены' if row['water_reminders'] else 'Выключены'}\n"
                f"💧 Водный баланс:\n"
                f"  Рекомендуется: {recommended_water} мл/день\n"
                f"  Выпито сегодня: {water_drunk} мл\n"
                f"  Осталось выпить: {remaining_water} мл\n"
                f"🍽 Питание сегодня:\n"
                f"  Калории: {calories} ккал\n"
                f"  Белки: {proteins} г\n"
                f"  Жиры: {fats} г\n"
                f"  Углеводы: {carbs} г"
            )
        else:
            profile_text = (
                f"Your profile:\n\n"
                f"Language: {row['language']}\n"
                f"Name: {row['name']}\n"
                f"Gender: {row['gender']}\n"
                f"Age: {row['age']}\n"
                f"Weight: {row['weight']} kg\n"
                f"Height: {row['height']} cm\n"
                f"Goal: {row['goal']}\n"
                f"Activity: {row['activity']}\n"
                f"Diet: {row['diet']}\n"
                f"Health: {row['health']}\n"
                f"Equipment: {row['equipment']}\n"
                f"Target metric: {row['target_metric']}\n"
                f"Unique facts: {row['unique_facts']}\n"
                f"Timezone: {row['timezone']}\n"
                f"Wake-up time: {row['wakeup_time']}\n"
                f"Sleep time: {row['sleep_time']}\n"
                f"Water reminders: {'Enabled' if row['water_reminders'] else 'Disabled'}\n"
                f"💧 Water balance:\n"
                f"  Recommended: {recommended_water} ml/day\n"
                f"  Drunk today: {water_drunk} ml\n"
                f"  Remaining: {remaining_water} ml\n"
                f"🍽 Nutrition today:\n"
                f"  Calories: {calories} kcal\n"
                f"  Proteins: {proteins} g\n"
                f"  Fats: {fats} g\n"
                f"  Carbs: {carbs} g"
            )
        await update.message.reply_text(profile_text)
    finally:
        conn.close()


async def reset(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_histories.pop(user_id, None)
    user_profiles.pop(user_id, None)
    
    try:
        conn = pymysql.connect(
            host='x91345bo.beget.tech',
            user='x91345bo_nutrbot',
            password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
            database='x91345bo_nutrbot',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM user_profiles WHERE user_id = %s", (user_id,))
        conn.commit()
        await update.message.reply_text("Все данные успешно сброшены! Начнем с чистого листа 🧼\nAll data has been reset! Let's start fresh 🧼")
    except Exception as e:
        await update.message.reply_text(f"Произошла ошибка при сбросе данных: {e}\nAn error occurred while resetting data: {e}")
    finally:
        conn.close()


async def toggle_water_reminders(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    conn = pymysql.connect(
        host='x91345bo.beget.tech',
        user='x91345bo_nutrbot',
        password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
        database='x91345bo_nutrbot',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT water_reminders, language FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
        
        if not row:
            await update.message.reply_text("Профиль не найден. Пройди анкету с помощью /start.\nProfile not found. Complete the questionnaire with /start.")
            return
        
        new_state = 0 if row['water_reminders'] else 1
        
        with conn.cursor() as update_cursor:
            update_cursor.execute("UPDATE user_profiles SET water_reminders = %s WHERE user_id = %s", (new_state, user_id))
        conn.commit()
        
        if row['language'] == "ru":
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
    finally:
        conn.close()


def get_user_profile_text(user_id: int) -> str:
    conn = pymysql.connect(
        host='x91345bo.beget.tech',
        user='x91345bo_nutrbot',
        password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
        database='x91345bo_nutrbot',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()

        if not row:
            return "Профиль пользователя не найден / User profile not found."

        language = row['language']
        weight = row['weight']
        recommended_water = int(weight * 30)
        water_drunk = row['water_drunk_today'] if row['water_drunk_today'] is not None else 0
        remaining_water = max(0, recommended_water - water_drunk)
        
        calories = row['calories_today'] if row['calories_today'] is not None else 0
        proteins = row['proteins_today'] if row['proteins_today'] is not None else 0
        fats = row['fats_today'] if row['fats_today'] is not None else 0
        carbs = row['carbs_today'] if row['carbs_today'] is not None else 0
        
        # Обработка поля reminders
        reminders = []
        if row['reminders']:
            try:
                reminders = json.loads(row['reminders'])
            except:
                reminders = []
        
        if language == "ru":
            profile_text = (
                f"Твой профиль:\n\n"
                f"Язык: {row['language']}\n"
                f"Имя: {row['name']}\n"
                f"Пол: {row['gender']}\n"
                f"Возраст: {row['age']}\n"
                f"Вес: {row['weight']} кг\n"
                f"Рост: {row['height']} см\n"
                f"Цель: {row['goal']}\n"
                f"Активность: {row['activity']}\n"
                f"Питание: {row['diet']}\n"
                f"Здоровье: {row['health']}\n"
                f"Инвентарь: {row['equipment']}\n"
                f"Целевая метрика: {row['target_metric']}\n"
                f"Уникальные факты: {row['unique_facts']}\n"
                f"Часовой пояс: {row['timezone']}\n"
                f"Время подъема: {row['wakeup_time']}\n"
                f"Время сна: {row['sleep_time']}\n"
                f"Напоминания о воде: {'Включены' if row['water_reminders'] else 'Выключены'}\n"
                f"Активные напоминания: {len(reminders)}\n"
                f"💧 Водный баланс:\n"
                f"  Рекомендуется: {recommended_water} мл/день\n"
                f"  Выпито сегодня: {water_drunk} мл\n"
                f"  Осталось выпить: {remaining_water} мл\n"
                f"🍽 Питание сегодня:\n"
                f"  Калории: {calories} ккал\n"
                f"  Белки: {proteins} г\n"
                f"  Жиры: {fats} г\n"
                f"  Углеводы: {carbs} г\n"
                f"  Последнее обновление: {row['last_nutrition_update'] if row['last_nutrition_update'] else 'сегодня'}"
            )
        else:
            profile_text = (
                f"Your profile:\n\n"
                f"Language: {row['language']}\n"
                f"Name: {row['name']}\n"
                f"Gender: {row['gender']}\n"
                f"Age: {row['age']}\n"
                f"Weight: {row['weight']} kg\n"
                f"Height: {row['height']} cm\n"
                f"Goal: {row['goal']}\n"
                f"Activity: {row['activity']}\n"
                f"Diet: {row['diet']}\n"
                f"Health: {row['health']}\n"
                f"Equipment: {row['equipment']}\n"
                f"Target metric: {row['target_metric']}\n"
                f"Unique facts: {row['unique_facts']}\n"
                f"Timezone: {row['timezone']}\n"
                f"Wake-up time: {row['wakeup_time']}\n"
                f"Sleep time: {row['sleep_time']}\n"
                f"Water reminders: {'Enabled' if row['water_reminders'] else 'Disabled'}\n"
                f"Active reminders: {len(reminders)}\n"
                f"💧 Water balance:\n"
                f"  Recommended: {recommended_water} ml/day\n"
                f"  Drunk today: {water_drunk} ml\n"
                f"  Remaining: {remaining_water} ml\n"
                f"🍽 Nutrition today:\n"
                f"  Calories: {calories} kcal\n"
                f"  Proteins: {proteins} g\n"
                f"  Fats: {fats} g\n"
                f"  Carbs: {carbs} g\n"
                f"  Last update: {row['last_nutrition_update'] if row['last_nutrition_update'] else 'today'}"
            )
        return profile_text
    except Exception as e:
        print(f"Ошибка при получении профиля: {e}")
        return f"Ошибка при получении профиля / Error getting profile: {e}"
    finally:
        conn.close()


async def handle_message(update: Update, context: CallbackContext) -> None:
    message = update.message
    user_id = message.from_user.id
    user_text = message.caption or message.text or ""
    contents = []

    # Проверяем и сбрасываем дневные показатели, если нужно
    await reset_daily_nutrition_if_needed(user_id)

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

    # Обновленный системный промпт с добавлением функционала КБЖУ
    GEMINI_SYSTEM_PROMPT = """Ты — умный ассистент, который помогает пользователю и при необходимости обновляет его профиль в базе данных.

Ключевые правила для SQL-запросов:
1. Всегда используй параметры с %s вместо значений
2. Для INSERT используй формат:
   SQL: INSERT INTO user_profiles (user_id, поле) VALUES (%s, %s)
3. Для UPDATE используй формат:
   SQL: UPDATE user_profiles SET поле = %s WHERE user_id = %s
4. Всегда указывай user_id как последний параметр
5. Для числовых полей не используй кавычки вокруг %s
6. Для текстовых полей используй значения в кавычках в TEXT части, но не в SQL

Примеры корректных запросов:
-- Обновление имени
SQL: UPDATE user_profiles SET name = %s WHERE user_id = %s
TEXT: Имя обновлено на 'Роман'

-- Обновление возраста
SQL: UPDATE user_profiles SET age = %s WHERE user_id = %s
TEXT: Возраст обновлен на 21

-- Добавление факта о здоровье
SQL: UPDATE user_profiles SET health = %s WHERE user_id = %s
TEXT: Факт о здоровье добавлен: 'Аллергия на пыльцу'

-- Обновление воды
SQL: UPDATE user_profiles SET water_drunk_today = water_drunk_today + %s WHERE user_id = %s
TEXT: Выпито 250 мл воды

Важно:
1. Всегда генерируй SQL и TEXT части
2. В SQL используй только %s для параметров
3. В TEXT указывай значения в читаемом формате
4. Для числовых полей не используй кавычки
5. Для INSERT всегда указывай user_id первым параметром
6. Для UPDATE всегда указывай user_id последним параметром
7. Если обновляешь несколько полей, передавай значения для всех полей перед user_id

Ты получаешь от пользователя сообщения. Они могут быть:
- просто вопросами (например, о питании, тренировках, фото и т.д.)
- обновлениями данных (например, "я набрал 3 кг" или "мне теперь 20 лет")
- сообщениями после изображения (например, "добавь это в инвентарь")
- уникальными фактами о пользователе (например, "я люблю плавание", "у меня была травма колена", "я вегетарианец 5 лет", "люблю кофе по вечерам")

Ключевые изменения для MySQL:
1. Используй `%s` вместо `?` для параметров
2. Для обновления при дубликате ключа применяй `ON DUPLICATE KEY UPDATE`
3. Типы данных: `INT` вместо `INTEGER`, `VARCHAR(255)` вместо `TEXT` для коротких полей
4. Для JSON-полей используй `TEXT` с хранением в формате JSON

Примеры запросов:
-- Вставка с обновлением при дубликате
INSERT INTO user_profiles (user_id, name)
VALUES (%s, %s)
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- Обновление JSON-поля
UPDATE user_profiles
SET reminders = %s
WHERE user_id = %s;

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
- water_drunk_today INTEGER
- last_water_notification TEXT
- calories_today INTEGER
- proteins_today INTEGER
- fats_today INTEGER
- carbs_today INTEGER
- last_nutrition_update DATE
- reminders TEXT

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

6. ⚠️ Если пользователь отправил изображение еды и явно указал, что это его еда (например: "мой завтрак", "это мой обед", "сегодня на ужин"):
   - Проанализируй фото и определи примерный состав блюда
   - Рассчитай КБЖУ (калории, белки, жиры, углеводы) для этого приема пищи
   - Обнови соответствующие поля в базе данных:
     SQL: UPDATE user_profiles SET calories_today = calories_today + [калории], proteins_today = proteins_today + [белки], fats_today = fats_today + [жиры], carbs_today = carbs_today + [углеводы], last_nutrition_update = CURRENT_DATE WHERE user_id = ?
   - Ответь в формате:
     TEXT: 
     🔍 Анализ блюда:
     (Опиши ТОЛЬКО то, что действительно видно на фото)
     
     🍽 Примерный КБЖУ:
     Калории: [X] ккал | Белки: [A] г | Жиры: [B] г | Углеводы: [C] г
     
     📊 Сегодня: [общая сумма калорий] ккал | [общая сумма белков] г белков | [общая сумма жиров] г жиров | [общая сумма углеводов] г углеводов
     
     ✅ Польза и состав:
     (Опиши пользу видимых элементов)
     
     🧠 Мнение бота:
     (Учитывая известные предпочтения пользователя)
     
     💡 Совет:
     (Если есть что улучшить, учитывая профиль)

7. Если пользователь поправляет тебя в анализе фото (например: "там было 2 яйца, а не 3"):
   - Извинись за ошибку
   - Немедленно пересмотри свой анализ с учетом новой информации
   - Вычти предыдущие значения КБЖУ из базы и добавь новые
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

12. Если пользователь сообщает о выпитой воде (в любом формате, например: "я выпил 300 мл", "только что 2 стакана воды", "drank 500ml"):
   - Извлеки количество воды из сообщения (в мл)
   - Обнови поле water_drunk_today в базе данных
     SQL: UPDATE user_profiles SET water_drunk_today = water_drunk_today + ? WHERE user_id = ?
   - Проверь, не превышает ли выпитое количество дневную норму (30 мл на 1 кг веса)
   - Если норма достигнута или превышена, отключи напоминания на сегодня
   - Ответь пользователю в формате:
     TEXT: [естественный ответ с текущей статистикой по воде]

13. Если пользователь запрашивает информацию о своем дневном питании (например: "сколько я сегодня съел", "мое питание за сегодня", "дневная статистика"):
   - Предоставь сводку по дневному КБЖУ в понятном формате
   - Учитывай цель пользователя (похудение/набор массы) при комментариях
   - Формат ответа:
     TEXT: "📊 Ваше дневное питание:
           Калории: [X] ккал (рекомендуется [Y] ккал)
           Белки: [A] г | Жиры: [B] г | Углеводы: [C] г
           [Комментарий или совет с учетом цели]"

14. Если пользователь поправляет тебя в анализе КБЖУ (например: "там было 200 г гречки, а не 150"):
   - Извинись за ошибку
   - Пересчитай КБЖУ с учетом уточнения
   - Обнови данные в базе, вычтя старые значения и добавив новые
     SQL: UPDATE user_profiles SET calories_today = calories_today - [старые калории] + [новые калории], proteins_today = proteins_today - [старые белки] + [новые белки], fats_today = fats_today - [старые жиры] + [новые жиры], carbs_today = carbs_today - [старые углеводы] + [новые углеводы] WHERE user_id = ?
   - Ответь с обновленной информацией

15. В полночь (по времени пользователя) все дневные показатели (калории, белки, жиры, углеводы, вода) должны автоматически обнуляться:
   SQL: UPDATE user_profiles SET calories_today = 0, proteins_today = 0, fats_today = 0, carbs_today = 0, water_drunk_today = 0 WHERE last_nutrition_update < CURRENT_DATE

16. Ответ должен быть естественным, дружелюбным и кратким, как будто ты — заботливый, но профессиональный диетолог.

17. Никогда не объясняй пользователю, какие SQL-запросы ты генерируешь - это внутренняя логика системы.

18. Всегда проверяй, что после TEXT: идет чистый ответ для пользователя без технических деталей.

19. Если пользователь просит установить напоминание (например: "напоминай мне пить омега-3 в 09:00", "напоминай принимать инсулин каждый день в 17:00"):
   - Извлеки текст напоминания и время из сообщения
   - Проверь, есть ли уже такое напоминание в базе (поле reminders в формате JSON)
   - Если напоминание уже существует - обнови его время
   - Если это новое напоминание - добавь его в список
   - Формат хранения в базе:
     [{"text": "текст напоминания", "time": "ЧЧ:ММ", "last_sent": "дата последней отправки"}]
   - SQL для добавления/обновления:
     SQL: UPDATE user_profiles SET reminders = ? WHERE user_id = ?
   - Ответь пользователю:
     TEXT: [подтверждение установки напоминания]

20. Если пользователь просит удалить напоминание (например: "хватит напоминать мне омега-3", "больше не напоминай про инсулин"):
   - Найди соответствующее напоминание в списке (поле reminders)
   - Удали его из списка
   - SQL для обновления:
     SQL: UPDATE user_profiles SET reminders = ? WHERE user_id = ?
   - Ответь пользователю:
     TEXT: [подтверждение удаления напоминания]

21. Если пользователь запрашивает список своих напоминаний:
   - Извлеки список из поля reminders
   - Сформируй понятный ответ с перечнем напоминаний
   - Формат ответа:
     TEXT: "📅 Ваши текущие напоминания:
           - [текст напоминания 1] в [время]
           - [текст напоминания 2] в [время]"

⚠️ Никогда не выдумывай детали, которых нет в профиле или на фото. Если не уверен — уточни или скажи, что не знаешь.

⚠️ Всегда строго учитывай известные факты о пользователе из его профиля И контекст текущего диалога.

⚠️ Отвечай пользователю на том же языке, на котором он к тебе обращается (учитывай поле language в профиле).

⚠️ Важно: SQL-запросы никогда не должны показываться пользователю! Они выполняются автоматически и только для обновления базы данных.

⚠️ Общая длина ответа никогда не должна превышать 4096 символов.

⚠️ Важно: SQL-запросы должны быть строго отделены от текста для пользователя и НИКОГДА не показываться ему. Формат ответа должен быть:

SQL: [запрос для базы данных, только если нужно обновить данные]
TEXT: [ответ пользователю, всегда на его языке]

ИЛИ (если не нужно обновлять базу):

TEXT: [ответ пользователю]

Никогда не смешивай эти части и не показывай SQL пользователю!

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
        context.user_data['last_bot_reply'] = response_text

        # Разделяем SQL и TEXT части ответа
        sql_part = None
        text_part = None

        # Ищем SQL часть
        sql_match = re.search(r'SQL:(.*?)(?=TEXT:|$)', response_text, re.DOTALL)
        if sql_match:
            sql_part = sql_match.group(1).strip()
            try:
                conn = pymysql.connect(
                    host='x91345bo.beget.tech',
                    user='x91345bo_nutrbot',
                    password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
                    database='x91345bo_nutrbot',
                    charset='utf8mb4',
                    cursorclass=pymysql.cursors.DictCursor
                )
                cursor = conn.cursor()

                # Заменяем ? на %s для MySQL
                sql_part = sql_part.replace('?', '%s')
                
                # Извлекаем параметры из текста ответа
                params = []
                if "%s" in sql_part:
                    # Для простых обновлений (name, age и т.д.)
                    value_match = re.search(r"=\s*%s", sql_part)
                    if value_match:
                        # Ищем значение в тексте ответа
                        text_value_match = re.search(r"'([^']*)'", response_text)
                        if text_value_match:
                            params.append(text_value_match.group(1))
                    
                    # Для обновления воды (числовое значение)
                    if "water_drunk_today" in sql_part:
                        water_match = re.search(r"(\d+)\s*мл", user_text)
                        if water_match:
                            params.insert(0, int(water_match.group(1)))
                    
                    # Для обновления КБЖУ (числовые значения)
                    if "calories_today" in sql_part:
                        # Здесь нужно более сложное извлечение значений из анализа фото
                        # Пока просто добавляем user_id
                        pass
                    
                    # Всегда добавляем user_id в конец
                    params.append(user_id)

                print(f"Executing SQL: {sql_part}")
                print(f"With params: {params}")
                
                if params:
                    cursor.execute(sql_part, params)
                else:
                    cursor.execute(sql_part)

                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Ошибка при выполнении SQL: {e}")
                print(f"SQL запрос: {sql_part}")
                print(f"Параметры: {params}")

        # Извлекаем TEXT часть для ответа пользователю
        text_matches = re.findall(r'TEXT:(.*?)(?=SQL:|$)', response_text, re.DOTALL)
        if text_matches:
            text_part = text_matches[-1].strip()
        else:
            text_part = re.sub(r'SQL:.*?(?=TEXT:|$)', '', response_text, flags=re.DOTALL).strip()

        if not text_part:
            text_part = "Я обработал ваш запрос. Нужна дополнительная информация?"

        await message.reply_text(text_part)

    except Exception as e:
        error_message = "Произошла ошибка при обработке запроса. Пожалуйста, попробуйте еще раз."
        if user_profiles.get(user_id, {}).get("language", "ru") == "en":
            error_message = "An error occurred while processing your request. Please try again."
        await message.reply_text(error_message)
        print(f"Ошибка при генерации ответа: {e}")



def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # Добавляем job для проверки напоминаний
    app.job_queue.run_repeating(
        check_reminders,
        interval=60,  # Проверяем каждую минуту
        first=10      # Первая проверка через 10 секунд
    )

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



