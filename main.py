import os
import re
import base64
import aiohttp
import sqlite3
import pytz
import telegram
import json
import pymysql
import uuid
import random
from typing import Dict, Optional
from enum import Enum
from pymysql.cursors import DictCursor
from datetime import datetime, time, date
from collections import deque
from telegram import Update, File, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Message, BotCommandScopeChat
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, CallbackContext, ConversationHandler, CallbackQueryHandler
)
import google.generativeai as genai
from datetime import datetime, time, timedelta


# Конфигурация
TOKEN = os.getenv("TOKEN")
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")

SUBSCRIPTION_PRICES = {
    '1_month': 1,
    '6_months': 1299,
    '12_months': 2299
}

FREE_TRIAL_HOURS = 24  # Продолжительность бесплатного периода в часах
PERMANENT_ACCESS_CODE = "S05D"  # Код для перманентного доступа

# Ключи ЮКассы (из secret.txt)
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY")
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID")

# Класс для статусов подписки
class SubscriptionStatus(Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    PERMANENT = "permanent"



if not TOKEN or not GOOGLE_API_KEY:
    raise ValueError("Отсутствует токен Telegram или Google Gemini API.")

INACTIVITY_REMINDER_HOURS = 4

genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

user_histories = {}
user_profiles = {}

(
    ASK_LANGUAGE, ASK_NAME, ASK_GENDER, ASK_AGE, ASK_WEIGHT, ASK_HEIGHT,
    ASK_GOAL, ASK_ACTIVITY, ASK_DIET_PREF, ASK_HEALTH, ASK_EQUIPMENT, 
    ASK_TARGET, ASK_TIMEZONE, ASK_WAKEUP_TIME, ASK_SLEEP_TIME, ASK_WATER_REMINDERS,
    WORKOUT_LOCATION, WORKOUT_DURATION, WORKOUT_SPECIAL_REQUESTS, WORKOUT_GENERATE
) = range(20)



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
            # Сначала получаем список существующих колонок
            cursor.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'user_profiles'
            """)
            existing_columns = {row['COLUMN_NAME'] for row in cursor.fetchall()}
            
            # Если таблица не существует, создаем ее полностью
            if not existing_columns:
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
                        reminders TEXT,
                        meal_history JSON,
                        subscription_status ENUM('trial', 'active', 'expired', 'permanent') DEFAULT 'trial',
                        subscription_type VARCHAR(20),
                        subscription_start DATETIME,
                        subscription_end DATETIME,
                        trial_start DATETIME,
                        trial_end DATETIME,
                        payment_id VARCHAR(50),
                        payment_notified TINYINT DEFAULT 0,
                        last_activity_time DATETIME
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
            else:
                # Если таблица существует, добавляем только отсутствующие колонки
                columns_to_add = [
                    ('subscription_status', "ALTER TABLE user_profiles ADD COLUMN subscription_status ENUM('trial', 'active', 'expired', 'permanent') DEFAULT 'trial'"),
                    ('subscription_type', "ALTER TABLE user_profiles ADD COLUMN subscription_type VARCHAR(20)"),
                    ('subscription_start', "ALTER TABLE user_profiles ADD COLUMN subscription_start DATETIME"),
                    ('subscription_end', "ALTER TABLE user_profiles ADD COLUMN subscription_end DATETIME"),
                    ('trial_start', "ALTER TABLE user_profiles ADD COLUMN trial_start DATETIME"),
                    ('trial_end', "ALTER TABLE user_profiles ADD COLUMN trial_end DATETIME"),
                    ('payment_id', "ALTER TABLE user_profiles ADD COLUMN payment_id VARCHAR(50)"),
                    ('payment_notified', "ALTER TABLE user_profiles ADD COLUMN payment_notified TINYINT DEFAULT 0"),
                    ('last_activity_time', "ALTER TABLE user_profiles ADD COLUMN last_activity_time DATETIME"),
                    ('last_meal_reminder_time', "ALTER TABLE user_profiles ADD COLUMN last_meal_reminder_time DATETIME")
                ]
                
                for column_name, alter_query in columns_to_add:
                    if column_name not in existing_columns:
                        cursor.execute(alter_query)
            
        conn.commit()
    except Exception as e:
        print(f"Ошибка при инициализации базы данных: {e}")
        raise
    finally:
        conn.close()

def save_user_profile(user_id: int, profile: dict):
    conn = None
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
            reminders = json.dumps(profile.get("reminders", []))
            meal_history = json.dumps(profile.get("meal_history", {}))
            
            cursor.execute('''
            INSERT INTO user_profiles (
                user_id, language, name, gender, age, weight, height, goal, activity, diet, 
                health, equipment, target_metric, unique_facts, timezone, wakeup_time, sleep_time,
                water_reminders, water_drunk_today, last_water_notification,
                calories_today, proteins_today, fats_today, carbs_today, last_nutrition_update, 
                reminders, meal_history
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
                %s, %s, %s, %s, %s, %s, %s, 
                %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
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
                reminders = VALUES(reminders),
                meal_history = VALUES(meal_history)
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
                reminders,
                meal_history
            ))
        conn.commit()
    except Exception as e:
        print(f"Ошибка при сохранении профиля: {e}")
        raise
    finally:
        if conn:
            conn.close()

async def check_access(user_id: int) -> bool:
    """Проверяет, есть ли у пользователя доступ к функциям бота"""
    subscription = await check_subscription(user_id)
    return subscription['status'] != 'expired'

async def check_subscription(user_id: int) -> Dict[str, Optional[str]]:
    """Проверяет статус подписки пользователя с учетом времени"""
    conn = None
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
            cursor.execute("""
                SELECT 
                    subscription_status, 
                    subscription_type,
                    trial_end,
                    subscription_end
                FROM user_profiles 
                WHERE user_id = %s
            """, (user_id,))
            result = cursor.fetchone()

            if not result:
                return {"status": "expired", "type": None, "end_date": None}

            status = result['subscription_status']
            sub_type = result['subscription_type']
            trial_end = result['trial_end']
            sub_end = result['subscription_end']
            now = datetime.now(pytz.timezone('Europe/Moscow'))

            moscow_tz = pytz.timezone('Europe/Moscow')
            now = datetime.now(moscow_tz)

            if trial_end and isinstance(trial_end, datetime):
                trial_end = moscow_tz.localize(trial_end) if trial_end.tzinfo is None else trial_end.astimezone(moscow_tz)

            if sub_end and isinstance(sub_end, datetime):
                sub_end = moscow_tz.localize(sub_end) if sub_end.tzinfo is None else sub_end.astimezone(moscow_tz)

            # Перманентный доступ - пропускаем все проверки
            if status == 'permanent':
                return {"status": status, "type": sub_type, "end_date": None}

            # Проверка trial периода
            if status == 'trial' and trial_end and now > trial_end:
                cursor.execute("""
                    UPDATE user_profiles
                    SET 
                        subscription_status = 'expired',
                        subscription_type = 'expired'
                    WHERE user_id = %s
                """, (user_id,))
                conn.commit()
                return {"status": "expired", "type": "expired", "end_date": trial_end}

            # Проверка платной подписки (если вдруг добавлена)
            if status == 'active' and sub_end and now > sub_end:
                cursor.execute("""
                    UPDATE user_profiles
                    SET 
                        subscription_status = 'expired',
                        subscription_type = 'expired'
                    WHERE user_id = %s
                """, (user_id,))
                conn.commit()
                return {"status": "expired", "type": "expired", "end_date": sub_end}

            return {
                "status": status,
                "type": sub_type,
                "end_date": trial_end if status == 'trial' else sub_end
            }
            
    except Exception as e:
        print(f"Ошибка при проверке подписки: {e}")
        return {"status": "expired", "type": None, "end_date": None}
    finally:
        if conn:
            conn.close()

async def start_trial_period(user_id: int):
    """Начинает бесплатный пробный период для пользователя с учётом часового пояса"""
    moscow_tz = pytz.timezone('Europe/Moscow')
    trial_start = datetime.now(moscow_tz)
    trial_end = trial_start + timedelta(hours=FREE_TRIAL_HOURS)

    conn = None
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
            cursor.execute("""
                UPDATE user_profiles
                SET
                    subscription_status = 'trial',
                    subscription_type = 'trial',
                    trial_start = %s,
                    trial_end = %s,
                    subscription_start = %s,
                    subscription_end = %s,
                    payment_id = NULL
                WHERE user_id = %s
            """, (
                trial_start.replace(tzinfo=None),  # Убираем tzinfo для MySQL
                trial_end.replace(tzinfo=None),
                trial_start.replace(tzinfo=None),
                trial_end.replace(tzinfo=None),
                user_id
            ))
            conn.commit()
            
    except Exception as e:
        print(f"Ошибка при установке пробного периода: {e}")
        raise
    finally:
        if conn:
            conn.close()

async def activate_subscription(user_id: int, sub_type: str, payment_id: str):
    """Активирует платную подписку для пользователя"""
    sub_start = datetime.now()

    if sub_type == '1_month':
        sub_end = sub_start + timedelta(days=30)
    elif sub_type == '6_months':
        sub_end = sub_start + timedelta(days=180)
    elif sub_type == '12_months':
        sub_end = sub_start + timedelta(days=365)
    else:
        raise ValueError("Неверный тип подписки")

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
                UPDATE user_profiles
                SET
                    subscription_status = 'active',
                    subscription_type = %s,
                    subscription_start = %s,
                    subscription_end = %s,
                    payment_id = %s
                WHERE user_id = %s
            """, (sub_type, sub_start, sub_end, payment_id, user_id))
            conn.commit()
    except Exception as e:
        print(f"Ошибка при активации подписки: {e}")
        raise
    finally:
        conn.close()

async def grant_permanent_access(user_id: int):
    """Дает пользователю перманентный доступ"""
    conn = None
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
            cursor.execute("""
                UPDATE user_profiles
                SET
                    subscription_status = 'permanent',
                    subscription_type = 'permanent',
                    trial_start = NULL,
                    trial_end = NULL,
                    subscription_start = NULL,
                    subscription_end = NULL,
                    payment_id = NULL
                WHERE user_id = %s
            """, (user_id,))
            conn.commit()
    except Exception as e:
        print(f"Ошибка при установке перманентного доступа: {e}")
        raise
    finally:
        if conn:
            conn.close()



async def reset_daily_nutrition_if_needed(user_id: int):
    conn = None
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
            # Получаем timezone и sleep_time пользователя
            cursor.execute("SELECT timezone, sleep_time, last_nutrition_update FROM user_profiles WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            
            if not result:
                return
                
            user_timezone = pytz.timezone(result['timezone']) if result['timezone'] else pytz.UTC
            now = datetime.now(user_timezone)
            today = now.date()
            
            # Получаем время сна пользователя
            sleep_time = datetime.strptime(result['sleep_time'], "%H:%M").time()
            sleep_dt = datetime.combine(now.date(), sleep_time).astimezone(user_timezone)
            
            # Если время сна переходит через полночь
            if sleep_time.hour < 12:  # Например, если сон в 01:00-12:00
                sleep_dt += timedelta(days=1)
            
            # Проверяем, что текущее время после времени сна
            if now < sleep_dt:
                # Если еще не время сна, но last_nutrition_update не сегодня - все равно сбрасываем
                if result['last_nutrition_update']:
                    last_update = result['last_nutrition_update']
                    if isinstance(last_update, str):
                        last_update = date.fromisoformat(last_update)
                    
                    if last_update < today:
                        # Гарантированный сброс, если дата последнего обновления не сегодня
                        cursor.execute('''
                            UPDATE user_profiles 
                            SET 
                                calories_today = 0,
                                proteins_today = 0,
                                fats_today = 0,
                                carbs_today = 0,
                                water_drunk_today = 0,
                                last_nutrition_update = %s
                            WHERE user_id = %s
                        ''', (today.isoformat(), user_id))
                        conn.commit()
                        print(f"Сброшены дневные показатели для пользователя {user_id} (timezone: {user_timezone.zone})")
                else:
                    # Если last_nutrition_update NULL, устанавливаем текущую дату
                    cursor.execute('''
                        UPDATE user_profiles 
                        SET last_nutrition_update = %s
                        WHERE user_id = %s
                    ''', (today.isoformat(), user_id))
                    conn.commit()
                return
            
            # Оригинальная логика сброса
            if result['last_nutrition_update']:
                last_update = result['last_nutrition_update']
                if isinstance(last_update, str):
                    last_update = date.fromisoformat(last_update)
                
                if last_update < today:
                    cursor.execute('''
                        UPDATE user_profiles 
                        SET 
                            calories_today = 0,
                            proteins_today = 0,
                            fats_today = 0,
                            carbs_today = 0,
                            water_drunk_today = 0,
                            last_nutrition_update = %s
                        WHERE user_id = %s
                    ''', (today.isoformat(), user_id))
                    conn.commit()
                    print(f"Сброшены дневные показатели для пользователя {user_id} (timezone: {user_timezone.zone})")
            else:
                # Если last_nutrition_update NULL, устанавливаем текущую дату
                cursor.execute('''
                    UPDATE user_profiles 
                    SET last_nutrition_update = %s
                    WHERE user_id = %s
                ''', (today.isoformat(), user_id))
                conn.commit()
    except Exception as e:
        print(f"Ошибка при сбросе дневного питания: {e}")
    finally:
        if conn:
            conn.close()


async def update_user_activity(user_id: int):
    """Обновляет время последней активности пользователя с учетом timezone"""
    conn = None
    try:
        # Получаем timezone пользователя
        user_timezone = await get_user_timezone(user_id)
        now = datetime.now(user_timezone)
        
        conn = pymysql.connect(
            host='x91345bo.beget.tech',
            user='x91345bo_nutrbot',
            password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
            database='x91345bo_nutrbot',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE user_profiles
                SET last_activity_time = %s
                WHERE user_id = %s
            """, (now.replace(tzinfo=None), user_id))
        conn.commit()
        print(f"Обновлено время активности для пользователя {user_id}: {now}")
    except Exception as e:
        print(f"Ошибка при обновлении времени активности: {e}")
    finally:
        if conn:
            conn.close()

# Добавим функцию для проверки неактивных пользователей и отправки напоминаний
async def check_inactive_users(context: CallbackContext):
    """Проверяет неактивных пользователей и отправляет напоминания"""
    print(f"\n{datetime.now()}: Запущена проверка неактивных пользователей")  # Логирование с временем
    
    conn = None
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
            cursor.execute("""
                SELECT 
                    user_id, 
                    last_activity_time, 
                    timezone,
                    language,
                    wakeup_time,
                    sleep_time,
                    last_meal_reminder_time
                FROM user_profiles
                WHERE last_activity_time IS NOT NULL
            """)
            users = cursor.fetchall()

        for user in users:
            try:
                subscription = await check_subscription(user['user_id'])
                if subscription['status'] == 'expired':
                    continue

                # Получаем часовой пояс пользователя
                tz = pytz.timezone(user['timezone']) if user['timezone'] else pytz.UTC
                now = datetime.now(tz)
                last_activity = user['last_activity_time']
                
                # Конвертируем last_activity_time в aware datetime
                if last_activity.tzinfo is None:
                    last_activity = tz.localize(last_activity)
                else:
                    last_activity = last_activity.astimezone(tz)
                
                inactivity_hours = (now - last_activity).total_seconds() / 3600
                print(f"Пользователь {user['user_id']}: неактивен {inactivity_hours:.2f} часов")  # Логирование
                
                # Получаем время пробуждения и сна
                wakeup_time = datetime.strptime(user['wakeup_time'], "%H:%M").time()
                sleep_time = datetime.strptime(user['sleep_time'], "%H:%M").time()
                current_time = now.time()
                
                # Определяем, какой сейчас день с учетом времени сна
                if current_time < sleep_time:
                    today = (now - timedelta(days=1)).date()
                    print(f"Пользователь {user['user_id']} еще не спал, считаем за предыдущий день {today}")
                else:
                    today = now.date()
                
                # Проверяем, что сейчас время бодрствования пользователя
                wakeup_dt = datetime.combine(today, wakeup_time).astimezone(tz)
                sleep_dt = datetime.combine(today, sleep_time).astimezone(tz)
                current_dt = datetime.combine(today, current_time).astimezone(tz)
                
                if sleep_time < wakeup_time:
                    sleep_dt += timedelta(days=1)
                
                is_active_time = wakeup_dt <= current_dt <= sleep_dt
                
                if not is_active_time:
                    print(f"Текущее время {current_time} вне периода активности пользователя {user['user_id']} ({wakeup_time}-{sleep_time})")
                    continue
                
                # Проверяем время последнего напоминания
                last_reminder = user['last_meal_reminder_time']
                if last_reminder:
                    if last_reminder.tzinfo is None:
                        last_reminder = tz.localize(last_reminder)
                    else:
                        last_reminder = last_reminder.astimezone(tz)
                    hours_since_last_reminder = (now - last_reminder).total_seconds() / 3600
                else:
                    hours_since_last_reminder = INACTIVITY_REMINDER_HOURS + 1  # Чтобы отправить первое напоминание
                
                print(f"Часов с последнего напоминания: {hours_since_last_reminder:.2f}")
                
                if inactivity_hours >= INACTIVITY_REMINDER_HOURS and hours_since_last_reminder >= INACTIVITY_REMINDER_HOURS:
                    print(f"Пользователь {user['user_id']} неактивен более {INACTIVITY_REMINDER_HOURS} часов")  # Логирование
                    
                    # Получаем историю питания
                    with conn.cursor() as cursor:
                        cursor.execute("""
                            SELECT meal_history FROM user_profiles 
                            WHERE user_id = %s
                        """, (user['user_id'],))
                        result = cursor.fetchone()
                    
                    meal_history = json.loads(result['meal_history']) if result and result['meal_history'] else {}
                    today_str = today.isoformat()
                    today_meals = meal_history.get(today_str, {})
                    print(f"Приемы пищи сегодня: {list(today_meals.keys())}")  # Логирование
                    
                    # Определяем, какой прием пищи пропущен
                    question = None
                    if user['language'] == "ru":
                        meals_order = ["завтрак", "обед", "ужин", "перекус"]
                    else:
                        meals_order = ["breakfast", "lunch", "dinner", "snack"]
                    
                    for meal in meals_order:
                        if not any(m.startswith(meal) for m in today_meals.keys()):
                            question = meal
                            break
                    
                    if question:
                        print(f"Пользователь {user['user_id']} пропустил {question}")  # Логирование
                        
                        # Формируем сообщение
                        if user['language'] == "ru":
                            if question == "завтрак":
                                messages = [
                                    "Привет! Не забыл ли ты позавтракать сегодня? Расскажи, что ты ел на завтрак! 🍳",
                                    "Утро - лучшее время для завтрака! Поделись, чем ты сегодня завтракал? 🥞",
                                    "Завтрак - самый важный прием пищи! Что сегодня было у тебя на тарелке? 🍽",
                                    "Не пропускай завтрак - он дает энергию на весь день! Что ты сегодня съел? 🍳",
                                    "Твой организм ждет завтрака! Чем ты его порадуешь сегодня? 🥐"
                                ]
                            elif question == "обед":
                                messages = [
                                    "Привет! Как насчет обеда? Уже поел? Расскажи, что было на обед! 🍲",
                                    "Обеденное время - отличный повод подкрепиться! Что ты сегодня ел на обед? 🍛",
                                    "Не забудь про обед - он помогает сохранить энергию до вечера! Чем ты сегодня пообедал? 🍜",
                                    "Обед - важный прием пищи! Поделись, что сегодня у тебя было на обед? 🥗",
                                    "Твой организм нуждается в подкреплении! Что ты сегодня выбрал на обед? 🍱"
                                ]
                            else:  # ужин
                                messages = [
                                    "Привет! Уже думал об ужине? Поделись, что планируешь на ужин! 🍽",
                                    "Вечер - время для вкусного ужина! Что сегодня будешь есть? 🍲",
                                    "Ужин - последний прием пищи за день! Чем ты сегодня порадуешь себя? 🍛",
                                    "Не пропускай ужин - он важен для восстановления! Что сегодня на ужин? 🍜",
                                    "Твой организм заслужил хороший ужин! Что ты сегодня приготовил? 🍱"
                                ]
                        else:
                            if question == "breakfast":
                                messages = [
                                    "Hi! Did you have breakfast today? Tell me what you ate for breakfast! 🍳",
                                    "Morning is the best time for breakfast! What did you have today? 🥞",
                                    "Breakfast is the most important meal! What was on your plate today? 🍽",
                                    "Don't skip breakfast - it gives energy for the whole day! What did you eat today? 🍳",
                                    "Your body is waiting for breakfast! What will you treat it with today? 🥐"
                                ]
                            elif question == "lunch":
                                messages = [
                                    "Hi! How about lunch? Have you eaten yet? Tell me what you had for lunch! 🍲",
                                    "Lunch time - a great reason to refuel! What did you have for lunch today? 🍛",
                                    "Don't forget about lunch - it helps maintain energy until evening! What was your lunch today? 🍜",
                                    "Lunch is an important meal! Share what you had for lunch today? 🥗",
                                    "Your body needs refueling! What did you choose for lunch today? 🍱"
                                ]
                            else:  # dinner
                                messages = [
                                    "Hi! Have you thought about dinner? Share what you're planning for dinner! 🍽",
                                    "Evening is time for a delicious dinner! What will you eat today? 🍲",
                                    "Dinner is the last meal of the day! What will you treat yourself to today? 🍛",
                                    "Don't skip dinner - it's important for recovery! What's for dinner today? 🍜",
                                    "Your body deserves a good dinner! What did you prepare today? 🍱"
                                ]
                        
                        # Выбираем случайное сообщение
                        message = random.choice(messages)
                        
                        try:
                            await context.bot.send_message(
                                chat_id=user['user_id'],
                                text=message
                            )
                            print(f"Отправлено напоминание о {question} пользователю {user['user_id']}")
                            
                            # Обновляем время последнего напоминания (но не время активности!)
                            with conn.cursor() as update_cursor:
                                update_cursor.execute("""
                                    UPDATE user_profiles
                                    SET last_meal_reminder_time = %s
                                    WHERE user_id = %s
                                """, (now.replace(tzinfo=None), user['user_id']))
                            conn.commit()
                            
                        except Exception as e:
                            print(f"Ошибка при отправке сообщения пользователю {user['user_id']}: {e}")
                    
            except Exception as e:
                print(f"Ошибка при проверке пользователя {user['user_id']}: {e}")
                
    except Exception as e:
        print(f"Ошибка при проверке неактивных пользователей: {e}")
    finally:
        if conn:
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
    user_id = update.message.from_user.id
    
    try:
        # Подключаемся к базе данных
        conn = pymysql.connect(
            host='x91345bo.beget.tech',
            user='x91345bo_nutrbot',
            password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
            database='x91345bo_nutrbot',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with conn.cursor() as cursor:
            # Проверяем, есть ли запись о пользователе
            cursor.execute("SELECT * FROM user_profiles WHERE user_id = %s", (user_id,))
            existing_profile = cursor.fetchone()
            
            if not existing_profile:
                # Если профиля нет, создаем его с минимальными данными
                cursor.execute("""
                    INSERT INTO user_profiles (user_id) 
                    VALUES (%s)
                """, (user_id,))
                conn.commit()
                
                # Устанавливаем trial период для нового пользователя
                await start_trial_period(user_id)
            else:
                # Если профиль уже существует, не изменяем данные о подписке
                pass
            
        # Продолжаем стандартный процесс
        await update.message.reply_text(
            "Привет! Я твой персональный фитнес-ассистент NutriBot. Пожалуйста, выбери язык общения / Hello! I'm your personal fitness assistant NutriBot. Please choose your preferred language:\n\n"
            "🇷🇺 Русский - отправь 'ru'\n"
            "🇬🇧 English - send 'en'\n\n"
        )
        return ASK_LANGUAGE
        
    except Exception as e:
        print(f"Ошибка при старте: {e}")
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте позже.")
        return ConversationHandler.END
    finally:
        if 'conn' in locals():
            conn.close()

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
        await update.message.reply_text("В каком часовом поясе ты находишься? (Например: UTC+3)")
    else:
        await update.message.reply_text("What timezone are you in? (e.g. UTC-5)")
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
    
    # Первое сообщение - завершение анкеты
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
    
    # Второе сообщение - инструкция по использованию бота
    if language == "ru":
        usage_text = (
            "📚 Как пользоваться NutriBot — вашим персональным фитнес AI-ассистентом\n\n"
            "NutriBot — это умный AI-помощник, который поможет вам следить за питанием, тренировками и здоровыми привычками. Вот как им пользоваться:\n\n"
            "🍎 Анализ питания по фото\n"
            "Отправьте боту фотографию вашего блюда, и он проведет детальный анализ:\n"
            "🔹 Состав и калории — белки, жиры, углеводы и общая калорийность.\n"
            "🔹 Скрытые ингредиенты — сахар, соль, трансжиры.\n"
            "🔹 Рекомендации — как улучшить блюдо под ваши цели (похудение, набор массы, ЗОЖ).\n"
            "🔹 Опасные сочетания — если в блюде есть несовместимые продукты.\n\n"
            "📌 Пример:\n"
            "👉 Отправьте фото тарелки с завтраком → бот разберет его на компоненты и даст советы.\n\n"
            "📊 Полный анализ питания\n"
            "Хотите узнать, как питались за последние дни? Напишите:\n"
            "🔸 \"Анализ питания\" — и бот предоставит:\n\n"
            "Среднесуточные калории и БЖУ.\n\n"
            "Паттерны питания (когда и что вы едите).\n\n"
            "Рекомендации по улучшению рациона.\n\n"
            "📌 Пример:\n"
            "👉 Напишите \"Анализ питания\" → получите отчет за 7 дней с советами.\n\n"
            "⏰ Умные напоминания\n"
            "Бот может напоминать вам о важных действиях. Просто скажите:\n"
            "🔹 \"Напоминай [что-то] каждый день в [время]\"\n\n"
            "Например:\n\n"
            "\"Напоминай пить рыбий жир каждый день в 9:00\"\n\n"
            "\"Напоминай принимать витамины в 12:00\"\n\n"
            "📌 Чтобы отменить напоминание, напишите:\n"
            "👉 \"Хватит напоминать про рыбий жир\"\n\n"
            "💧 Контроль водного баланса\n"
            "Бот автоматически рассчитывает вашу норму воды (30 мл на 1 кг веса) и напоминает пить.\n"
            "🔹 Как использовать:\n\n"
            "Нажмите кнопку \"Выпил 250 мл\" или напишите \"Я выпил стакан воды\".\n\n"
            "Отправьте команду /water, чтобы включить/выключить напоминания.\n\n"
            "🏋️ Персональные тренировки\n"
            "Хотите план тренировок? Используйте команду /menu → \"Начать тренировку\".\n"
            "🔹 Бот учтет:\n\n"
            "Ваше оборудование (дом, зал, улица).\n\n"
            "Цели (похудение, рельеф, сила).\n\n"
            "Особые пожелания (\"без прыжков\", \"упор на спину\").\n\n"
            "📌 Пример:\n"
            "👉 Выберите \"Дома\" → укажите длительность → получите готовый план.\n\n\n"
            "💡 Дополнительные функции\n"
            "🔸 Оценка состава тела по фото — отправьте фото, и бот даст приблизительную оценку % жира и мышц.\n"
            "🔸 Советы по продуктам — спросите: \"Чем полезен творог?\" → получите развернутый ответ.\n"
            "🔸 Анализ настроения — если напишете \"Я в стрессе\", бот предложит рекомендации.\n\n"
            "🚀 Начните прямо сейчас!\n"
            "Отправьте фото еды или запрос — бот поможет с анализом.\n\n"
            "Используйте команды для удобства."
        )
    else:
        usage_text = (
            "📚 How to use NutriBot — your personal fitness AI-assistant\n\n"
            "NutriBot is a smart AI companion that helps you track nutrition, workouts, and healthy habits. Here's how to use it:\n\n"
            "🍎 Food analysis by photo\n"
            "Send a photo of your meal, and the bot will analyze it in detail:\n"
            "🔹 Composition and calories - proteins, fats, carbs, and total calories.\n"
            "🔹 Hidden ingredients - sugar, salt, trans fats.\n"
            "🔹 Recommendations - how to improve the meal for your goals (weight loss, muscle gain, healthy lifestyle).\n"
            "🔹 Dangerous combinations - if the dish contains incompatible foods.\n\n"
            "📌 Example:\n"
            "👉 Send a photo of your breakfast → the bot will break it down and give advice.\n\n"
            "📊 Complete nutrition analysis\n"
            "Want to know your eating patterns? Type:\n"
            "🔸 \"Nutrition analysis\" to get:\n\n"
            "Daily average calories and macros\n\n"
            "Eating patterns (when and what you eat)\n\n"
            "Personalized improvement recommendations\n\n"
            "📌 Example:\n"
            "👉 Type \"Nutrition analysis\" → get a 7-day report with advice.\n\n"
            "⏰ Smart reminders\n"
            "The bot can remind you about important actions. Just say:\n"
            "🔹 \"Remind me to [something] every day at [time]\"\n\n"
            "Examples:\n\n"
            "\"Remind me to take fish oil every day at 9:00\"\n\n"
            "\"Remind me to take vitamins at 12:00\"\n\n"
            "📌 To cancel a reminder, type:\n"
            "👉 \"Stop reminding me about fish oil\"\n\n"
            "💧 Water balance tracking\n"
            "The bot automatically calculates your water norm (30 ml per 1 kg of weight) and reminds you to drink.\n"
            "🔹 How to use:\n\n"
            "Click \"Drank 250 ml\" or type \"I drank a glass of water\".\n\n"
            "Use /water command to enable/disable reminders.\n\n"
            "🏋️ Personalized workouts\n"
            "Need a workout plan? Use /menu → \"Start Workout\".\n"
            "🔹 The bot considers:\n\n"
            "Your equipment (home, gym, outdoor)\n\n"
            "Goals (weight loss, toning, strength)\n\n"
            "Special requests (\"no jumps\", \"focus on back\")\n\n"
            "📌 Example:\n"
            "👉 Choose \"Home\" → set duration → get a ready-made plan.\n\n\n"
            "💡 Additional features\n"
            "🔸 Body composition estimation by photo - send a photo for approximate fat/muscle %\n"
            "🔸 Food advice - ask: \"What are the benefits of cottage cheese?\"\n"
            "🔸 Mood analysis - if you type \"I'm stressed\", the bot will offer recommendations\n\n"
            "🚀 Start right now!\n"
            "Send food photos or requests - the bot will help with analysis.\n\n"
            "Use commands for convenience."
        )
    
    await update.message.reply_text(usage_text)
    
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

    subscription = await check_subscription(user_id)
    if subscription['status'] == 'expired':
        # Удаляем job для этого пользователя
        job.schedule_removal()
        print(f"Удалена задача напоминаний для пользователя {user_id} (подписка истекла)")
        return
    
    # Сначала проверяем и сбрасываем дневные показатели, если нужно
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
        
        # Проверяем, включены ли напоминания (добавлена дополнительная проверка)
        if not row.get('water_reminders', 0):
            print(f"Напоминания отключены для пользователя {user_id}")
            return
        
        weight = row.get('weight') or 70
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
                    
                    # Создаем кнопку для подтверждения выпитой воды
                    button_text = f"Выпил {water_to_drink_now} мл" if row['language'] == "ru" else f"Drank {water_to_drink_now} ml"
                    keyboard = [
                        [telegram.InlineKeyboardButton(
                            button_text, 
                            callback_data=f"water_{water_to_drink_now}"
                        )]
                    ]
                    reply_markup = telegram.InlineKeyboardMarkup(keyboard)
                    
                   
                    reminder_choice = random.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

                    if row['language'] == "ru":
                        if reminder_choice == 1:
                            message = (
                                f"💧 Не забудь выпить воду! Сейчас рекомендуется выпить {water_to_drink_now} мл.\n"
                                f"📊 Сегодня выпито: {row['water_drunk_today']} мл из {recommended_water} мл\n"
                                f"🚰 Осталось выпить: {remaining_water} мл\n\n"
                                f"После того как выпьешь воду, нажми кнопку ниже или отправь мне сообщение в формате:\n"
                                f"'Выпил 250 мл' или 'Drank 300 ml'"
                            )
                        elif reminder_choice == 2:
                            message = (
                                f"⏰ Время пить воду! Твой организм нуждается в {water_to_drink_now} мл прямо сейчас.\n"
                                f"💦 Прогресс сегодня: {row['water_drunk_today']}/{recommended_water} мл ({remaining_water} мл осталось)\n\n"
                                f"Подтверди, когда выпьешь, нажав кнопку или написав 'Выпил Х мл'"
                            )
                        elif reminder_choice == 3:
                            message = (
                                f"🚀 Гидратация - ключ к энергии! Выпей {water_to_drink_now} мл воды для бодрости.\n"
                                f"📈 Текущий баланс: {row['water_drunk_today']} из {recommended_water} мл\n"
                                f"🔋 Осталось до цели: {remaining_water} мл\n\n"
                                f"Сообщи мне, когда попьешь, чтобы я мог обновить твои показатели!"
                            )
                        elif reminder_choice == 4:
                            message = (
                                f"🌡️ Знаешь ли ты, что теплая вода с лимоном утром:\n"
                                f"- Ускоряет метаболизм на 20-30%\n"
                                f"- Помогает пищеварению\n"
                                f"- Очищает организм\n\n"
                                f"Попробуй! А сейчас выпей {water_to_drink_now} мл чистой воды 💧"
                            )
                        elif reminder_choice == 5:
                            message = (
                                f"🧠 Наш мозг на 75% состоит из воды! Даже легкое обезвоживание (1-2%) снижает:\n"
                                f"- Когнитивные функции на 5-10%\n"
                                f"- Концентрацию на 15%\n"
                                f"- Настроение на 20%\n\n"
                                f"Восполни баланс - выпей {water_to_drink_now} мл прямо сейчас!"
                            )
                        elif reminder_choice == 6:
                           message = (
                                f"💪 Вода и тренировки:\n"
                                f"- Потеря всего 2% воды снижает эффективность тренировки на 10%\n"
                                f"- Достаточное питье ускоряет восстановление мышц\n"
                                f"- Вода помогает доставлять питательные вещества\n\n"
                                f"Выпей {water_to_drink_now} мл для максимальных результатов!"
                            )
                        elif reminder_choice == 7:
                            message = (
                                f"🌿 Натуральный детокс: вода выводит токсины и:\n"
                                f"- Улучшает цвет кожи на 30%\n"
                                f"- Снижает усталость на 25%\n"
                                f"- Уменьшает головные боли на 15%\n\n"
                                f"Твой следующий шаг к здоровью - {water_to_drink_now} мл воды!"
                            )
                        elif reminder_choice == 8:
                            message = (
                                f"⚖️ Интересный факт:\n"
                                f"Каждые 500 мл выпитой воды ускоряют метаболизм на 24-30% в течение часа!\n"
                                f"Это как мини-тренировка без усилий 😉\n\n"
                                f"Выпей {water_to_drink_now} мл для ускорения обмена веществ!"
                            )
                        elif reminder_choice == 9:
                            message = (
                                f"🔄 Вода и вес:\n"
                                f"- 2 стакана воды перед едой снижают потребление калорий на 13%\n"
                                f"- Достаточное питье уменьшает ложное чувство голода\n"
                                f"- Вода участвует в расщеплении жиров\n\n"
                                f"Сделай глоток ({water_to_drink_now} мл) для своего тела!"
                            )
                        else:
                            message = (
                                f"💫 Вода - это жизнь! Сегодня ты уже выпил {row['water_drunk_today']} мл.\n"
                                f"Напомню:\n"
                                f"- 1% обезвоживания = 10% снижения продуктивности\n"
                                f"- 2% обезвоживания = заметная жажда\n"
                                f"- 5% обезвоживания = усталость и головокружение\n\n"
                                f"Поддержи баланс - выпей {water_to_drink_now} мл сейчас!"
                            )
                    else:
                        if reminder_choice == 1:
                            message = (
                                f"💧 Don't forget to drink water! Now it's recommended to drink {water_to_drink_now} ml.\n"
                                f"📊 Today drunk: {row['water_drunk_today']} ml of {recommended_water} ml\n"
                                f"🚰 Remaining: {remaining_water} ml\n\n"
                                f"After drinking water, click the button below or send me a message in the format:\n"
                                f"'Drank 300 ml' or 'Выпил 250 мл'"
                            )
                        elif reminder_choice == 2:
                            message = (
                                f"⏰ Time to hydrate! Your body needs {water_to_drink_now} ml right now.\n"
                                f"💦 Today's progress: {row['water_drunk_today']}/{recommended_water} ml ({remaining_water} ml left)\n\n"
                                f"Confirm when you drink by clicking the button or typing 'Drank X ml'"
                            )
                        elif reminder_choice == 3:
                            message = (
                                f"🚀 Hydration is the key to energy! Drink {water_to_drink_now} ml of water for vitality.\n"
                                f"📈 Current balance: {row['water_drunk_today']} of {recommended_water} ml\n"
                                f"🔋 Left to goal: {remaining_water} ml\n\n"
                                f"Let me know when you drink so I can update your stats!"
                            )
                        elif reminder_choice == 4:
                            message = (
                                f"🌡️ Did you know that warm water with lemon in the morning:\n"
                                f"- Boosts metabolism by 20-30%\n"
                                f"- Aids digestion\n"
                                f"- Detoxifies the body\n\n"
                                f"Try it! And now drink {water_to_drink_now} ml of pure water 💧"
                            )
                        elif reminder_choice == 5:
                            message = (
                                f"🧠 Our brain is 75% water! Even mild dehydration (1-2%) reduces:\n"
                                f"- Cognitive functions by 5-10%\n"
                                f"- Concentration by 15%\n"
                                f"- Mood by 20%\n\n"
                                f"Replenish your balance - drink {water_to_drink_now} ml right now!"
                            )
                        elif reminder_choice == 6:
                            message = (
                                f"💪 Water and workouts:\n"
                                f"- Losing just 2% of water reduces workout efficiency by 10%\n"
                                f"- Proper hydration speeds up muscle recovery\n"
                                f"- Water helps deliver nutrients\n\n"
                                f"Drink {water_to_drink_now} ml for maximum results!"
                            )
                        elif reminder_choice == 7:
                            message = (
                                f"🌿 Natural detox: water removes toxins and:\n"
                                f"- Improves skin tone by 30%\n"
                                f"- Reduces fatigue by 25%\n"
                                f"- Decreases headaches by 15%\n\n"
                                f"Your next step to health - {water_to_drink_now} ml of water!"
                            )
                        elif reminder_choice == 8:
                            message = (
                                f"⚖️ Interesting fact:\n"
                                f"Every 500 ml of water you drink boosts metabolism by 24-30% for an hour!\n"
                                f"It's like a mini-workout without effort 😉\n\n"
                                f"Drink {water_to_drink_now} ml to speed up your metabolism!"
                            )
                        elif reminder_choice == 9:
                            message = (
                                f"🔄 Water and weight:\n"
                                f"- 2 glasses of water before meals reduce calorie intake by 13%\n"
                                f"- Proper hydration decreases false hunger\n"
                                f"- Water participates in fat breakdown\n\n"
                                f"Take a sip ({water_to_drink_now} ml) for your body!"
                            )
                        else:
                            message = (
                                f"💫 Water is life! Today you've already drunk {row['water_drunk_today']} ml.\n"
                                f"Remember:\n"
                                f"- 1% dehydration = 10% productivity loss\n"
                                f"- 2% dehydration = noticeable thirst\n"
                                f"- 5% dehydration = fatigue and dizziness\n\n"
                                f"Maintain your balance - drink {water_to_drink_now} ml now!"
                            )
                    
                    await context.bot.send_message(
                        chat_id=chat_id, 
                        text=message,
                        reply_markup=reply_markup
                    )
                    print(f"Напоминание отправлено пользователю {user_id} в {now}")
        
        except Exception as e:
            print(f"Ошибка при проверке времени для напоминания пользователю {user_id}: {str(e)}")
    finally:
        conn.close()

async def show_profile(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id

    if not await check_access(user_id):
        await info(update, context)  # Показываем информацию о подписке
        return

    await reset_daily_nutrition_if_needed(user_id)
    
    conn = None
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
        weight = row['weight'] if row['weight'] is not None else 0
        recommended_water = int(weight * 30) if weight else 0
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
    except Exception as e:
        print(f"Ошибка при получении профиля: {e}")
        await update.message.reply_text("Произошла ошибка при получении профиля. Пожалуйста, попробуйте позже.")
    finally:
        if conn:
            conn.close()


async def reset(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_histories.pop(user_id, None)
    user_profiles.pop(user_id, None)
    
    conn = None
    try:
        conn = pymysql.connect(
            host='x91345bo.beget.tech',
            user='x91345bo_nutrbot',
            password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
            database='x91345bo_nutrbot',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        # Получаем текущие данные о подписке
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT subscription_status, subscription_type, subscription_start, subscription_end, trial_start, trial_end, payment_id 
                FROM user_profiles 
                WHERE user_id = %s
            """, (user_id,))
            subscription_data = cursor.fetchone()
            
        # Сбрасываем все данные, кроме информации о подписке
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE user_profiles 
                SET 
                    language = NULL,
                    name = NULL,
                    gender = NULL,
                    age = NULL,
                    weight = NULL,
                    height = NULL,
                    goal = NULL,
                    activity = NULL,
                    diet = NULL,
                    health = NULL,
                    equipment = NULL,
                    target_metric = NULL,
                    unique_facts = NULL,
                    timezone = NULL,
                    wakeup_time = NULL,
                    sleep_time = NULL,
                    water_reminders = 1,
                    water_drunk_today = 0,
                    last_water_notification = NULL,
                    calories_today = 0,
                    proteins_today = 0,
                    fats_today = 0,
                    carbs_today = 0,
                    last_nutrition_update = NULL,
                    reminders = NULL,
                    meal_history = NULL
                WHERE user_id = %s
            """, (user_id,))
        conn.commit()
        
        # Восстанавливаем данные о подписке
        if subscription_data:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE user_profiles 
                    SET 
                        subscription_status = %s,
                        subscription_type = %s,
                        subscription_start = %s,
                        subscription_end = %s,
                        trial_start = %s,
                        trial_end = %s,
                        payment_id = %s
                    WHERE user_id = %s
                """, (
                    subscription_data['subscription_status'],
                    subscription_data['subscription_type'],
                    subscription_data['subscription_start'],
                    subscription_data['subscription_end'],
                    subscription_data['trial_start'],
                    subscription_data['trial_end'],
                    subscription_data['payment_id'],
                    user_id
                ))
                conn.commit()
        
        # Получаем язык для ответа
        with conn.cursor() as cursor:
            cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
        
        language = row['language'] if row and row['language'] else "ru"
        
        if language == "ru":
            await update.message.reply_text("Все данные успешно сброшены! Начнем с чистого листа 🧼")
        else:
            await update.message.reply_text("All data has been reset! Let's start fresh 🧼")
            
    except Exception as e:
        print(f"Ошибка при сбросе данных: {e}")
        if language == "ru":
            await update.message.reply_text(f"Произошла ошибка при сбросе данных: {e}")
        else:
            await update.message.reply_text(f"An error occurred while resetting data: {e}")
    finally:
        if conn:
            conn.close()


async def toggle_water_reminders(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id

    if not await check_access(user_id):
        await info(update, context)  # Показываем информацию о подписке
        return

    conn = None
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
            cursor.execute("SELECT water_reminders, language FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
        
        if not row:
            await update.message.reply_text("Профиль не найден. Пройди анкету с помощью /start.\nProfile not found. Complete the questionnaire with /start.")
            return
        
        new_state = 0 if row['water_reminders'] else 1
        
        with conn.cursor() as update_cursor:
            update_cursor.execute("UPDATE user_profiles SET water_reminders = %s WHERE user_id = %s", (new_state, user_id))
        conn.commit()
        
        # Удаляем старые задачи для этого пользователя, если они есть
        current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
        for job in current_jobs:
            job.schedule_removal()
        
        # Если напоминания включаются, создаем новую задачу
        if new_state:
            context.job_queue.run_repeating(
                check_water_reminder_time,
                interval=300,
                first=10,
                chat_id=update.message.chat_id,
                user_id=user_id,
                name=str(user_id)
                )
            print(f"Создана задача напоминаний для пользователя {user_id}")
            
        
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
    except Exception as e:
        print(f"Ошибка при переключении напоминаний о воде: {e}")
        await update.message.reply_text("Произошла ошибка. Пожалуйста, попробуйте позже.")
    finally:
        if conn:
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
        weight = row['weight'] if row['weight'] is not None else 0
        recommended_water = int(weight * 30) if weight else 0
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

async def update_meal_history(user_id: int, meal_data: dict):
    """Обновляет историю питания пользователя с учетом timezone"""
    conn = None
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
            # Получаем текущую историю
            cursor.execute("SELECT meal_history FROM user_profiles WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            current_history = json.loads(result['meal_history']) if result and result['meal_history'] else {}
            
            # Получаем текущую дату с учетом timezone пользователя
            user_timezone = await get_user_timezone(user_id)
            current_date = datetime.now(user_timezone).date().isoformat()
            
            # Если для текущей даты еще нет записей, создаем пустой словарь
            if current_date not in current_history:
                current_history[current_date] = {}
            
            # Добавляем все новые приемы пищи
            for meal_type, meal_info in meal_data.items():
                # Генерируем уникальный ключ для приема пищи (тип + timestamp)
                meal_key = f"{meal_type}_{datetime.now(user_timezone).strftime('%H%M%S')}"
                current_history[current_date][meal_key] = meal_info
            
            # Сохраняем обновленную историю
            cursor.execute("""
                UPDATE user_profiles 
                SET meal_history = %s 
                WHERE user_id = %s
            """, (json.dumps(current_history), user_id))
            
            conn.commit()
    except Exception as e:
        print(f"Ошибка при обновлении истории питания: {e}")
        raise
    finally:
        if conn:
            conn.close()


async def get_meal_history(user_id: int) -> dict:
    """Возвращает историю питания пользователя с проверкой данных"""
    conn = None
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
            cursor.execute("SELECT meal_history FROM user_profiles WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            
            if result and result['meal_history']:
                try:
                    history = json.loads(result['meal_history'])
                    # Проверяем и корректируем структуру данных
                    cleaned_history = {}
                    for date_str, meals in history.items():
                        if isinstance(meals, dict):
                            cleaned_meals = {}
                            for meal_key, meal_data in meals.items():
                                if isinstance(meal_data, dict):
                                    cleaned_meals[meal_key] = {
                                        'time': meal_data.get('time', '?'),
                                        'food': meal_data.get('food', ''),
                                        'calories': meal_data.get('calories', 0),
                                        'proteins': meal_data.get('proteins', 0),
                                        'fats': meal_data.get('fats', 0),
                                        'carbs': meal_data.get('carbs', 0)
                                    }
                            cleaned_history[date_str] = cleaned_meals
                    return cleaned_history
                except json.JSONDecodeError:
                    print("Ошибка декодирования meal_history")
                    return {}
            return {}
    except Exception as e:
        print(f"Ошибка при получении истории питания: {e}")
        return {}
    finally:
        if conn:
            conn.close()

async def delete_meal_entry(user_id: int, date_str: str, meal_type: str = None, food_description: str = None):
    """Удаляет запись о приеме пищи по типу или описанию еды"""
    conn = None
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
            # Получаем текущую историю питания
            cursor.execute("SELECT meal_history FROM user_profiles WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            
            if not result or not result['meal_history']:
                print("История питания пуста")
                return False
                
            history = json.loads(result['meal_history'])
            
            if date_str not in history:
                print(f"Нет записей за {date_str}")
                return False
                
            deleted = False
            
            # Создаем список ключей для удаления
            keys_to_delete = []
            
            # Если указан тип приема пищи
            if meal_type:
                for meal_key in list(history[date_str].keys()):
                    if meal_key.startswith(meal_type + '_'):
                        keys_to_delete.append(meal_key)
            
            # Если указано описание еды
            elif food_description:
                for meal_key, meal_data in list(history[date_str].items()):
                    if food_description.lower() in meal_data.get('food', '').lower():
                        keys_to_delete.append(meal_key)
            
            # Удаляем найденные записи
            for meal_key in keys_to_delete:
                meal_data = history[date_str][meal_key]
                # Вычитаем КБЖУ
                cursor.execute("""
                    UPDATE user_profiles 
                    SET 
                        calories_today = GREATEST(0, calories_today - %s),
                        proteins_today = GREATEST(0, proteins_today - %s),
                        fats_today = GREATEST(0, fats_today - %s),
                        carbs_today = GREATEST(0, carbs_today - %s)
                    WHERE user_id = %s
                """, (
                    meal_data.get('calories', 0),
                    meal_data.get('proteins', 0),
                    meal_data.get('fats', 0),
                    meal_data.get('carbs', 0),
                    user_id
                ))
                # Удаляем запись
                del history[date_str][meal_key]
                deleted = True
            
            # Если дата пустая, удаляем её полностью
            if date_str in history and not history[date_str]:
                del history[date_str]
                
            # Сохраняем обновленную историю
            cursor.execute("""
                UPDATE user_profiles 
                SET meal_history = %s 
                WHERE user_id = %s
            """, (json.dumps(history), user_id))
            
            conn.commit()
            return deleted
            
    except Exception as e:
        print(f"Ошибка при удалении записи: {e}")
        raise
    finally:
        if conn:
            conn.close()

async def update_meal_calories(user_id: int, meal_type: str, new_calories: int, language: str, context: CallbackContext):
    """Обновляет калорийность приема пищи"""
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
            cursor.execute("SELECT meal_history FROM user_profiles WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            if not result or not result['meal_history']:
                return
                
            history = json.loads(result['meal_history'])
            date_str = date.today().isoformat()
            
            if date_str in history and meal_type in history[date_str]:
                old_calories = history[date_str][meal_type].get('calories', 0)
                history[date_str][meal_type]['calories'] = new_calories
                
                # Обновляем разницу в БД
                cursor.execute("""
                    UPDATE user_profiles 
                    SET calories_today = calories_today - %s + %s 
                    WHERE user_id = %s
                """, (old_calories, new_calories, user_id))
                
                # Сохраняем историю
                cursor.execute("""
                    UPDATE user_profiles 
                    SET meal_history = %s 
                    WHERE user_id = %s
                """, (json.dumps(history), user_id))
                
                conn.commit()
                
                if language == "ru":
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Обновил калорийность {meal_type}: теперь {new_calories} ккал"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Updated {meal_type} calories: now {new_calories} kcal"
                    )
    finally:
        conn.close()

async def change_meal_type(user_id: int, old_type: str, new_type: str, language: str, context: CallbackContext):
    """Изменяет тип приема пищи"""
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
            cursor.execute("SELECT meal_history FROM user_profiles WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            if not result or not result['meal_history']:
                return
                
            history = json.loads(result['meal_history'])
            date_str = date.today().isoformat()
            
            if date_str in history and old_type in history[date_str]:
                meal_data = history[date_str][old_type]
                del history[date_str][old_type]
                
                if date_str not in history:
                    history[date_str] = {}
                history[date_str][new_type] = meal_data
                
                # Сохраняем историю
                cursor.execute("""
                    UPDATE user_profiles 
                    SET meal_history = %s 
                    WHERE user_id = %s
                """, (json.dumps(history), user_id))
                
                conn.commit()
                
                if language == "ru":
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Изменил тип приема пищи с '{old_type}' на '{new_type}'"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Changed meal type from '{old_type}' to '{new_type}'"
                    )
    finally:
        conn.close()

async def delete_meal(user_id: int, meal_type: str, language: str, context: CallbackContext):
    """Удаляет прием пищи"""
    await delete_meal_entry(user_id, date.today().isoformat(), meal_type)
    
    if language == "ru":
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Удалил {meal_type} из вашей истории питания"
        )
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Deleted {meal_type} from your meal history"
        )

async def get_user_timezone(user_id: int) -> pytz.timezone:
    """Возвращает timezone пользователя"""
    conn = None
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
            cursor.execute("SELECT timezone FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            
        if row and row['timezone']:
            return pytz.timezone(row['timezone'])
        return pytz.UTC  # fallback
    except Exception as e:
        print(f"Ошибка при получении timezone: {e}")
        return pytz.UTC
    finally:
        if conn:
            conn.close()



async def check_and_create_water_job(context: CallbackContext):
    """Проверяет пользователей с включенными напоминаниями и создает job, если его нет"""
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
                SELECT user_id FROM user_profiles 
                WHERE water_reminders = 1
            """)
            users = cursor.fetchall()
            
        for user in users:
            user_id = user['user_id']

            subscription = await check_subscription(user_id)
            if subscription['status'] == 'expired':
                continue

            # Проверяем, есть ли уже job для этого пользователя
            current_jobs = context.job_queue.get_jobs_by_name(str(user_id))
            if not current_jobs:
                # Создаем новую задачу для напоминаний
                context.job_queue.run_repeating(
                    check_water_reminder_time,
                    interval=300,
                    first=10,
                    chat_id=user_id,  # Для отправки сообщений нужен chat_id
                    user_id=user_id,
                    name=str(user_id)
                )
                print(f"Создана задача напоминаний для пользователя {user_id} при перезагрузке")
    except Exception as e:
        print(f"Ошибка при проверке напоминаний: {e}")
    finally:
        conn.close()


async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if query.data not in ["subscribe", "sub_1_month", "sub_6_months", "sub_12_months"]:
        if not await check_access(user_id):
            await info(update, context)  # Показываем информацию о подписке
            return

    if query.data == "start_workout":
        return await start_workout(update, context)

    if query.data == "bot_features":
        # Получаем язык пользователя
        language = "ru"
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
                cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
                row = cursor.fetchone()
                if row and row['language']:
                    language = row['language']
        except Exception as e:
            print(f"Ошибка при получении языка: {e}")
        finally:
            if conn:
                conn.close()

        if language == "ru":
            features_text = (
                "🌟 *NutriBot - ваш персональный фитнес AI-компаньон!* 🌟\n\n"
                "Я помогу вам достичь ваших целей в здоровье и фитнесе с помощью:\n\n"
                "💪 *Персональные тренировки*\n"
                "- Генерация программ под ваш уровень и оборудование\n"
                "- Учет особенностей здоровья и травм\n"
                "- Рекомендации по технике выполнения\n\n"
                "🍏 *Умный анализ питания*\n"
                "- Подсчет КБЖУ по фото еды\n"
                "- Персонализированные рекомендации\n"
                "- Анализ пищевых привычек\n\n"
                "💧 *Контроль водного баланса*\n"
                "- Автоматические напоминания\n"
                "- Точный расчет нормы воды\n"
                "- Отслеживание прогресса\n\n"
                "📊 *Полная статистика*\n"
                "- История питания\n"
                "- Анализ прогресса\n"
                "- Рекомендации по улучшению\n\n"
                "🔍 *Анализ состава тела*\n"
                "- Оценка по фото (приблизительная)\n"
                "- Рекомендации по коррекции\n"
                "- Отслеживание изменений\n\n"
                "⏰ *Умные напоминания*\n"
                "- Прием воды\n"
                "- Прием пищи\n"
                "- Прием добавок\n\n"
                "🚀 Начните прямо!"
            )
        else:
            features_text = (
                "🌟 *NutriBot - Your Personal Fitness AI-Companion!* 🌟\n\n"
                "I'll help you achieve your health and fitness goals with:\n\n"
                "💪 *Personalized Workouts*\n"
                "- Custom programs for your level and equipment\n"
                "- Health condition and injury considerations\n"
                "- Exercise technique recommendations\n\n"
                "🍏 *Smart Nutrition Analysis*\n"
                "- Calories and macros calculation from food photos\n"
                "- Personalized recommendations\n"
                "- Eating habits analysis\n\n"
                "💧 *Water Balance Control*\n"
                "- Automatic reminders\n"
                "- Precise water intake calculation\n"
                "- Progress tracking\n\n"
                "📊 *Complete Statistics*\n"
                "- Nutrition history\n"
                "- Progress analysis\n"
                "- Improvement recommendations\n\n"
                "🔍 *Body Composition Analysis*\n"
                "- Photo-based estimation (approximate)\n"
                "- Correction recommendations\n"
                "- Change tracking\n\n"
                "⏰ *Smart Reminders*\n"
                "- Water intake\n"
                "- Meals\n"
                "- Supplements\n\n"
                "🚀 Start right now!"
            )

        await query.edit_message_text(
            features_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏋️ Начать тренировку" if language == "ru" else "🏋️ Start Workout", callback_data="start_workout")],
                [InlineKeyboardButton("🔙 Назад" if language == "ru" else "🔙 Back", callback_data="back_to_menu")]
            ])
        )
        return

    if query.data == "back_to_menu":
        language = "ru"
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
                cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (query.from_user.id,))
                row = cursor.fetchone()
                if row and row['language']:
                    language = row['language']
        except Exception as e:
            print(f"Ошибка при получении языка: {e}")
        finally:
            if conn:
                conn.close()

        keyboard = [
            [InlineKeyboardButton("🏋️ Начать тренировку" if language == "ru" else "🏋️ Start Workout", callback_data="start_workout")],
            [InlineKeyboardButton("✨ О возможностях бота" if language == "ru" else "✨ About bot features", callback_data="bot_features")],
            [InlineKeyboardButton("📚 Как пользоваться" if language == "ru" else "📚 How to use", callback_data="bot_usage")]
        ]
    
        reply_markup = InlineKeyboardMarkup(keyboard)
    
        await query.edit_message_text(
            "📱 *Меню управления ботом*\n\n"
            "Здесь вы можете управлять основными функциями" if language == "ru" else "📱 *Bot Control Menu*\n\nHere you can manage main functions",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    
    if query.data == "bot_usage":
        # Получаем язык пользователя
        language = "ru"
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
                cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
                row = cursor.fetchone()
                if row and row['language']:
                    language = row['language']
        except Exception as e:
            print(f"Ошибка при получении языка: {e}")
        finally:
            if conn:
                conn.close()

        if language == "ru":
            usage_text = (
        "📚 Как пользоваться NutriBot — вашим персональным фитнес AI-ассистентом\n\n"
        "NutriBot — это умный AI-помощник, который поможет вам следить за питанием, тренировками и здоровыми привычками. Вот как им пользоваться:\n\n"
        "🍎 Анализ питания по фото\n"
        "Отправьте боту фотографию вашего блюда, и он проведет детальный анализ:\n"
        "🔹 Состав и калории — белки, жиры, углеводы и общая калорийность.\n"
        "🔹 Скрытые ингредиенты — сахар, соль, трансжиры.\n"
        "🔹 Рекомендации — как улучшить блюдо под ваши цели (похудение, набор массы, ЗОЖ).\n"
        "🔹 Опасные сочетания — если в блюде есть несовместимые продукты.\n\n"
        "📌 Пример:\n"
        "👉 Отправьте фото тарелки с завтраком → бот разберет его на компоненты и даст советы.\n\n"
        "📊 Полный анализ питания\n"
        "Хотите узнать, как питались за последние дни? Напишите:\n"
        "🔸 \"Анализ питания\" — и бот предоставит:\n\n"
        "Среднесуточные калории и БЖУ.\n\n"
        "Паттерны питания (когда и что вы едите).\n\n"
        "Рекомендации по улучшению рациона.\n\n"
        "📌 Пример:\n"
        "👉 Напишите \"Анализ питания\" → получите отчет за 7 дней с советами.\n\n"
        "⏰ Умные напоминания\n"
        "Бот может напоминать вам о важных действиях. Просто скажите:\n"
        "🔹 \"Напоминай [что-то] каждый день в [время]\"\n\n"
        "Например:\n\n"
        "\"Напоминай пить рыбий жир каждый день в 9:00\"\n\n"
        "\"Напоминай принимать витамины в 12:00\"\n\n"
        "📌 Чтобы отменить напоминание, напишите:\n"
        "👉 \"Хватит напоминать про рыбий жир\"\n\n"
        "💧 Контроль водного баланса\n"
        "Бот автоматически рассчитывает вашу норму воды (30 мл на 1 кг веса) и напоминает пить.\n"
        "🔹 Как использовать:\n\n"
        "Нажмите кнопку \"Выпил 250 мл\" или напишите \"Я выпил стакан воды\".\n\n"
        "Отправьте команду /water, чтобы включить/выключить напоминания.\n\n"
        "🏋️ Персональные тренировки\n"
        "Хотите план тренировок? Используйте команду /menu → \"Начать тренировку\".\n"
        "🔹 Бот учтет:\n\n"
        "Ваше оборудование (дом, зал, улица).\n\n"
        "Цели (похудение, рельеф, сила).\n\n"
        "Особые пожелания (\"без прыжков\", \"упор на спину\").\n\n"
        "📌 Пример:\n"
        "👉 Выберите \"Дома\" → укажите длительность → получите готовый план.\n\n\n"
        "💡 Дополнительные функции\n"
        "🔸 Оценка состава тела по фото — отправьте фото, и бот даст приблизительную оценку % жира и мышц.\n"
        "🔸 Советы по продуктам — спросите: \"Чем полезен творог?\" → получите развернутый ответ.\n"
        "🔸 Анализ настроения — если напишете \"Я в стрессе\", бот предложит рекомендации.\n\n"
        "🚀 Начните прямо сейчас!\n"
        "Отправьте фото еды или запрос — бот поможет с анализом.\n\n"
        "Используйте команды для удобства."
            )
        else:
            usage_text = (
        "📚 How to use NutriBot — your personal fitness AI-assistant\n\n"
        "NutriBot is a smart AI companion that helps you track nutrition, workouts, and healthy habits. Here's how to use it:\n\n"
        "🍎 Food analysis by photo\n"
        "Send a photo of your meal, and the bot will analyze it in detail:\n"
        "🔹 Composition and calories - proteins, fats, carbs, and total calories.\n"
        "🔹 Hidden ingredients - sugar, salt, trans fats.\n"
        "🔹 Recommendations - how to improve the meal for your goals (weight loss, muscle gain, healthy lifestyle).\n"
        "🔹 Dangerous combinations - if the dish contains incompatible foods.\n\n"
        "📌 Example:\n"
        "👉 Send a photo of your breakfast → the bot will break it down and give advice.\n\n"
        "📊 Complete nutrition analysis\n"
        "Want to know your eating patterns? Type:\n"
        "🔸 \"Nutrition analysis\" to get:\n\n"
        "Daily average calories and macros\n\n"
        "Eating patterns (when and what you eat)\n\n"
        "Personalized improvement recommendations\n\n"
        "📌 Example:\n"
        "👉 Type \"Nutrition analysis\" → get a 7-day report with advice.\n\n"
        "⏰ Smart reminders\n"
        "The bot can remind you about important actions. Just say:\n"
        "🔹 \"Remind me to [something] every day at [time]\"\n\n"
        "Examples:\n\n"
        "\"Remind me to take fish oil every day at 9:00\"\n\n"
        "\"Remind me to take vitamins at 12:00\"\n\n"
        "📌 To cancel a reminder, type:\n"
        "👉 \"Stop reminding me about fish oil\"\n\n"
        "💧 Water balance tracking\n"
        "The bot automatically calculates your water norm (30 ml per 1 kg of weight) and reminds you to drink.\n"
        "🔹 How to use:\n\n"
        "Click \"Drank 250 ml\" or type \"I drank a glass of water\".\n\n"
        "Use /water command to enable/disable reminders.\n\n"
        "🏋️ Personalized workouts\n"
        "Need a workout plan? Use /menu → \"Start Workout\".\n"
        "🔹 The bot considers:\n\n"
        "Your equipment (home, gym, outdoor)\n\n"
        "Goals (weight loss, toning, strength)\n\n"
        "Special requests (\"no jumps\", \"focus on back\")\n\n"
        "📌 Example:\n"
        "👉 Choose \"Home\" → set duration → get a ready-made plan.\n\n\n"
        "💡 Additional features\n"
        "🔸 Body composition estimation by photo - send a photo for approximate fat/muscle %\n"
        "🔸 Food advice - ask: \"What are the benefits of cottage cheese?\"\n"
        "🔸 Mood analysis - if you type \"I'm stressed\", the bot will offer recommendations\n\n"
        "🚀 Start right now!\n"
        "Send food photos or requests - the bot will help with analysis.\n\n"
        "Use commands for convenience."
            )

        await query.edit_message_text(
            usage_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад" if language == "ru" else "🔙 Back", callback_data="back_to_menu")]
            ])
        )
        return


    # Обработка кнопки воды
    if query.data.startswith("water_"):
        try:
            amount = int(query.data.split("_")[1])

            # Получаем язык пользователя
            conn = pymysql.connect(
                host='x91345bo.beget.tech',
                user='x91345bo_nutrbot',
                password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
                database='x91345bo_nutrbot',
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )

            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE user_profiles
                    SET water_drunk_today = water_drunk_today + %s
                    WHERE user_id = %s
                """, (amount, user_id))
                conn.commit()

                # Получаем обновленные данные
                cursor.execute("""
                    SELECT water_drunk_today, weight, language
                    FROM user_profiles
                    WHERE user_id = %s
                """, (user_id,))
                row = cursor.fetchone()

            recommended_water = int(row['weight'] * 30) if row['weight'] else 2100
            remaining = max(0, recommended_water - row['water_drunk_today'])

            if row['language'] == "ru":
                message = (
                    f"✅ Записал! Выпито {row['water_drunk_today']} мл из {recommended_water} мл.\n"
                    f"Осталось выпить: {remaining} мл."
                )
            else:
                message = (
                    f"✅ Recorded! Drank {row['water_drunk_today']} ml of {recommended_water} ml.\n"
                    f"Remaining: {remaining} ml."
                )

            await query.edit_message_text(text=message)

        except Exception as e:
            print(f"Ошибка обработки кнопки воды: {e}")
            await query.edit_message_text("Произошла ошибка. Попробуйте позже.")
        finally:
            if conn:
                conn.close()
        return

    subscription = await check_subscription(user_id)
    
    # Получаем язык пользователя
    language = "ru"
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
            cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row and row['language']:
                language = row['language']
    except Exception as e:
        print(f"Ошибка при получении языка: {e}")
    finally:
        if conn:
            conn.close()
    
    if query.data == "subscribe":
        if language == "ru":
            text = "Выберите тариф подписки:"
            buttons = [
                [
                    telegram.InlineKeyboardButton("1 месяц", callback_data="sub_1_month"),
                    telegram.InlineKeyboardButton("6 месяцев", callback_data="sub_6_months"),
                    telegram.InlineKeyboardButton("12 месяцев", callback_data="sub_12_months")
                ]
            ]
        else:
            text = "Choose subscription plan:"
            buttons = [
                [
                    telegram.InlineKeyboardButton("1 month", callback_data="sub_1_month"),
                    telegram.InlineKeyboardButton("6 months", callback_data="sub_6_months"),
                    telegram.InlineKeyboardButton("12 months", callback_data="sub_12_months")
                ]
            ]
        
        reply_markup = telegram.InlineKeyboardMarkup(buttons)
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    
    elif query.data.startswith("sub_"):
        sub_type = query.data[4:]  # Получаем тип подписки (1_month, 6_months, 12_months)
        payment_id = str(uuid.uuid4())
        amount = SUBSCRIPTION_PRICES[sub_type] * 100  # Сумма в копейках
        
        # Получаем язык пользователя
        language = "ru"
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
                cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
                row = cursor.fetchone()
                if row and row['language']:
                    language = row['language']
        except Exception as e:
            print(f"Ошибка при получении языка: {e}")
        finally:
            if conn:
                conn.close()

        # Создаем платеж в ЮKassa
        headers = {
            "Content-Type": "application/json",
            "Idempotence-Key": str(uuid.uuid4())
        }
        auth = aiohttp.BasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
        
        payload = {
            "amount": {
                "value": str(SUBSCRIPTION_PRICES[sub_type]),
                "currency": "RUB"
            },
            "payment_method_data": {
                "type": "bank_card"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/eatsmart_ai_bot"
            },
            "description": f"Подписка {sub_type.replace('_', ' ')} на NutriBot",
            "metadata": {
                "user_id": user_id,
                "subscription_type": sub_type
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.yookassa.ru/v3/payments",
                    json=payload,
                    headers=headers,
                    auth=auth
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        payment_url = data['confirmation']['confirmation_url']
                        
                        # Сохраняем payment_id в базу
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
                                cursor.execute("""
                                    UPDATE user_profiles 
                                    SET 
                                        payment_id = %s,
                                        subscription_type = %s
                                    WHERE user_id = %s
                                """, (data['id'], sub_type, user_id))
                                conn.commit()
                        except Exception as e:
                            print(f"Ошибка при сохранении payment_id: {e}")
                            await query.edit_message_text(
                                "Произошла ошибка. Пожалуйста, попробуйте позже." if language == "ru" 
                                else "An error occurred. Please try again later."
                            )
                            return
                        
                        # Формируем сообщение с кнопкой для оплаты
                        if language == "ru":
                            text = (
                                f"Вы выбрали тариф: {sub_type.replace('_', ' ')}\n"
                                f"Стоимость: {SUBSCRIPTION_PRICES[sub_type]}₽\n\n"
                                "Для оплаты нажмите кнопку ниже 👇"
                            )
                        else:
                            text = (
                                f"You selected: {sub_type.replace('_', ' ')}\n"
                                f"Price: {SUBSCRIPTION_PRICES[sub_type]}₽\n\n"
                                "Click the button below to pay 👇"
                            )
                        
                        keyboard = [
                            [InlineKeyboardButton(
                                "Оплатить" if language == "ru" else "Pay", 
                                url=payment_url
                            )]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        await query.edit_message_text(
                            text=text,
                            reply_markup=reply_markup
                        )
                    else:
                        error_text = await response.text()
                        print(f"Ошибка при создании платежа: {error_text}")
                        await query.edit_message_text(
                            "Ошибка при создании платежа. Попробуйте позже." if language == "ru" 
                            else "Payment creation error. Please try again later."
                        )
        except Exception as e:
            print(f"Ошибка при создании платежа: {e}")
            await query.edit_message_text(
                "Произошла ошибка. Пожалуйста, попробуйте позже." if language == "ru" 
                else "An error occurred. Please try again later."
            )


async def info(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    subscription = await check_subscription(user_id)
    
    # Получаем язык пользователя
    language = "ru"
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
            cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row and row['language']:
                language = row['language']
    except Exception as e:
        print(f"Ошибка при получении языка: {e}")
    finally:
        if conn:
            conn.close()
    
    # Формируем текст о подписке (без Markdown разметки)
    if language == "ru":
        if subscription['status'] == SubscriptionStatus.TRIAL.value:
            sub_text = f"🆓 У вас активен пробный период до {subscription['end_date'].strftime('%d.%m.%Y %H:%M')}"
        elif subscription['status'] == SubscriptionStatus.ACTIVE.value:
            sub_text = f"✅ У вас активна подписка {subscription['type']} до {subscription['end_date'].strftime('%d.%m.%Y %H:%M')}"
        elif subscription['status'] == SubscriptionStatus.PERMANENT.value:
            sub_text = "🌟 У вас перманентный доступ к боту!"
        else:
            sub_text = "❌ У вас нет активной подписки"
            
        info_text = (
            f"NutriBot - ваш персональный фитнес AI-ассистент\n\n"
            f"{sub_text}\n\n"
            "Я помогу вам:\n"
            "• Следить за питанием и считать КБЖУ 🍎\n"
            "• Напоминать пить воду 💧\n"
            "• Давать персонализированные рекомендации по тренировкам 🏋️\n"
            "• Анализировать ваши фото еды и оценивать состав тела 📸\n"
            "• Создавать индивидуальные планы питания и тренировок 📝\n\n"
            "Тарифы:\n"
            f"• 1 месяц - {SUBSCRIPTION_PRICES['1_month']}₽\n"
            f"• 6 месяцев - {SUBSCRIPTION_PRICES['6_months']}₽ (экономия {SUBSCRIPTION_PRICES['1_month']*6 - SUBSCRIPTION_PRICES['6_months']}₽)\n"
            f"• 12 месяцев - {SUBSCRIPTION_PRICES['12_months']}₽ (экономия {SUBSCRIPTION_PRICES['1_month']*12 - SUBSCRIPTION_PRICES['12_months']}₽)\n\n"
            "Для оформления подписки нажмите кнопку ниже 👇"
        )
    else:
        if subscription['status'] == SubscriptionStatus.TRIAL.value:
            sub_text = f"🆓 You have an active trial period until {subscription['end_date'].strftime('%d.%m.%Y %H:%M')}"
        elif subscription['status'] == SubscriptionStatus.ACTIVE.value:
            sub_text = f"✅ You have an active {subscription['type']} subscription until {subscription['end_date'].strftime('%d.%m.%Y %H:%M')}"
        elif subscription['status'] == SubscriptionStatus.PERMANENT.value:
            sub_text = "🌟 You have permanent access to the bot!"
        else:
            sub_text = "❌ You don't have an active subscription"
            
        info_text = (
            f"NutriBot - your personal fitness AI-assistant\n\n"
            f"{sub_text}\n\n"
            "I can help you with:\n"
            "• Tracking nutrition and counting calories 🍎\n"
            "• Reminding to drink water 💧\n"
            "• Providing personalized workout recommendations 🏋️\n"
            "• Analyzing your food photos and body composition 📸\n"
            "• Creating individual meal and workout plans 📝\n\n"
            "Subscription plans:\n"
            f"• 1 month - {SUBSCRIPTION_PRICES['1_month']}₽\n"
            f"• 6 months - {SUBSCRIPTION_PRICES['6_months']}₽ (save {SUBSCRIPTION_PRICES['1_month']*6 - SUBSCRIPTION_PRICES['6_months']}₽)\n"
            f"• 12 months - {SUBSCRIPTION_PRICES['12_months']}₽ (save {SUBSCRIPTION_PRICES['1_month']*12 - SUBSCRIPTION_PRICES['12_months']}₽)\n\n"
            "Click the button below to subscribe 👇"
        )
    
    keyboard = [
        [telegram.InlineKeyboardButton(
            "Оформить подписку" if language == "ru" else "Subscribe", 
            callback_data="subscribe"
        )]
    ]
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)
    
    # Отправляем сообщение без parse_mode или с правильной разметкой
    await update.message.reply_text(
        info_text,
        reply_markup=reply_markup
    )


async def check_payment_status(context: CallbackContext):
    conn = None
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
            # Проверяем сначала, есть ли колонка payment_notified
            cursor.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'user_profiles'
                AND COLUMN_NAME = 'payment_notified'
            """)
            column_exists = cursor.fetchone()
            
            if not column_exists:
                # Если колонки нет - создаем ее
                cursor.execute("""
                    ALTER TABLE user_profiles 
                    ADD COLUMN payment_notified TINYINT DEFAULT 0
                """)
                conn.commit()
            
            # Ищем пользователей с неуведомленными платежами
            cursor.execute("""
                SELECT user_id FROM user_profiles 
                WHERE payment_id IS NOT NULL 
                AND subscription_status = 'active'
                AND payment_notified = 0
                LIMIT 10
            """)
            users = cursor.fetchall()
            
            for user in users:
                try:
                    # Получаем язык пользователя для персонализации сообщения
                    cursor.execute("""
                        SELECT language FROM user_profiles 
                        WHERE user_id = %s
                    """, (user['user_id'],))
                    user_lang = cursor.fetchone().get('language', 'ru')
                    
                    message_text = (
                        "✅ Ваша подписка активирована! Спасибо за оплату." 
                        if user_lang == 'ru' else 
                        "✅ Your subscription has been activated! Thank you for payment."
                    )
                    
                    await context.bot.send_message(
                        chat_id=user['user_id'],
                        text=message_text
                    )
                    
                    # Помечаем как уведомленного
                    cursor.execute("""
                        UPDATE user_profiles 
                        SET payment_notified = 1 
                        WHERE user_id = %s
                    """, (user['user_id'],))
                    conn.commit()
                    
                except Exception as e:
                    print(f"Ошибка уведомления пользователя {user['user_id']}: {e}")
                    # Пропускаем этого пользователя и продолжаем с остальными
                    continue
                    
    except Exception as e:
        print(f"Ошибка в check_payment_status: {e}")
    finally:
        if conn:
            conn.close()


def clean_markdown(text):
    """Удаляет или экранирует непарные символы Markdown"""
    # Экранируем символы, которые могут быть ошибочно интерпретированы как разметка
    for char in ['*', '_', '`', '[']:
        if text.count(char) % 2 != 0:
            text = text.replace(char, f'\\{char}')
    return text


async def post_init(application: Application) -> None:
    """Функция для настройки бота после инициализации"""
    # Получаем список всех пользователей с их языками
    conn = None
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
            cursor.execute("SELECT user_id, language FROM user_profiles WHERE language IS NOT NULL")
            users = cursor.fetchall()
            
            # Создаем словарь языков для пользователей
            user_languages = {user['user_id']: user['language'] for user in users}
            
            # Устанавливаем команды для каждого пользователя
            for user_id, language in user_languages.items():
                if language == "ru":
                    commands = [
                        BotCommand("drank", "💧 Выпил 250мл воды"),
                        BotCommand("menu", "⚙ Меню"),
                        BotCommand("info", "💳 Подписка"),
                        BotCommand("water", "🚰 Напоминания о воде"),
                    ]
                else:
                    commands = [
                        BotCommand("drank", "💧 Drank 250ml water"),
                        BotCommand("menu", "⚙ Menu"),
                        BotCommand("info", "💳 Subscription"),
                        BotCommand("water", "🚰 Water reminders"),
                    ]
                
                try:
                    await application.bot.set_my_commands(commands, scope=BotCommandScopeChat(user_id))
                except Exception as e:
                    print(f"Ошибка при установке команд для пользователя {user_id}: {e}")
            
        # Устанавливаем команды по умолчанию на русском и английском
        await application.bot.set_my_commands([
            BotCommand("drank", "💧 Выпил 250мл воды / Drank 250ml water"),
            BotCommand("menu", "⚙ Меню / Menu"),
            BotCommand("info", "💳 Подписка / Subscription"),
            BotCommand("water", "🚰 Напоминания о воде / Water reminders"),
        ])
        
    except Exception as e:
        print(f"Ошибка в post_init: {e}")
        # Устанавливаем команды по умолчанию на случай ошибки
        await application.bot.set_my_commands([
            BotCommand("drank", "💧 Выпил 250мл воды / Drank 250ml water"),
            BotCommand("menu", "⚙ Меню / Menu"),
            BotCommand("info", "💳 Подписка / Subscription"),
            BotCommand("water", "🚰 Напоминания о воде / Water reminders"),
        ])
    finally:
        if conn:
            conn.close()


async def menu_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /menu - показывает меню управления с краткой статистикой"""
    user_id = update.message.from_user.id

    if not await check_access(user_id):
        await info(update, context)  # Показываем информацию о подписке
        return

    # Получаем данные пользователя
    conn = None
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
            # Получаем основную информацию о пользователе
            cursor.execute("""
                SELECT 
                    language, name, age, weight, water_drunk_today, calories_today,
                    proteins_today, fats_today, carbs_today, reminders,
                    subscription_status, subscription_type, subscription_end,
                    wakeup_time, sleep_time
                FROM user_profiles 
                WHERE user_id = %s
            """, (user_id,))
            profile = cursor.fetchone()

            if not profile:
                await update.message.reply_text("Профиль не найден. Пройди анкету с помощью /start.\nProfile not found. Complete the questionnaire with /start.")
                return

            language = profile['language'] or "ru"
            name = profile['name'] or ""
            age = profile['age'] or ""
            weight = profile['weight'] or 70
            recommended_water = int(weight * 30)
            water_drunk = profile['water_drunk_today'] or 0
            remaining_water = max(0, recommended_water - water_drunk)
            
            calories = profile['calories_today'] or 0
            proteins = profile['proteins_today'] or 0
            fats = profile['fats_today'] or 0
            carbs = profile['carbs_today'] or 0
            
            # Получаем время пробуждения и сна
            wakeup_time = profile['wakeup_time'] or "07:00"
            sleep_time = profile['sleep_time'] or "23:00"
            
            # Обработка напоминаний
            reminders = []
            if profile['reminders']:
                try:
                    reminders = json.loads(profile['reminders'])
                except:
                    reminders = []
            
            # Формируем текст статистики
            if language == "ru":
                stats_text = (
                    f"👤 *{name}* • {age} лет • {weight} кг\n\n"
                    f"💧 *Вода сегодня:* {water_drunk}/{recommended_water} мл ({remaining_water} мл осталось)\n\n"
                    f"🍽 *Питание сегодня:*\n"
                    f"• Калории: {calories} ккал\n"
                    f"• Белки: {proteins} г\n"
                    f"• Жиры: {fats} г\n"
                    f"• Углеводы: {carbs} г\n\n"
                    f"⏰ *Активные напоминания:*\n"
                )
                
                if reminders:
                    for rem in reminders:
                        stats_text += f"• {rem['text']} в {rem['time']}\n"
                else:
                    stats_text += "Нет активных напоминаний\n"
                
                # Добавляем информацию о времени пробуждения и сне
                stats_text += f"\n🌅 *Время пробуждения:* {wakeup_time}\n"
                stats_text += f"🌙 *Время сна:* {sleep_time}\n"
                
                # Добавляем информацию о подписке
                subscription = await check_subscription(user_id)
                if subscription['status'] == 'trial':
                    stats_text += f"\n🆓 *Пробный период до:* {subscription['end_date'].strftime('%d.%m.%Y %H:%M')}"
                elif subscription['status'] == 'active':
                    stats_text += f"\n✅ *Подписка {subscription['type'].replace('_', ' ')} до:* {subscription['end_date'].strftime('%d.%m.%Y %H:%M')}"
                elif subscription['status'] == 'permanent':
                    stats_text += "\n🌟 *Перманентный доступ*"
                else:
                    stats_text += "\n❌ *Нет активной подписки*"
                
            else:
                stats_text = (
                    f"👤 *{name}* • {age} y.o. • {weight} kg\n\n"
                    f"💧 *Water today:* {water_drunk}/{recommended_water} ml ({remaining_water} ml left)\n\n"
                    f"🍽 *Nutrition today:*\n"
                    f"• Calories: {calories} kcal\n"
                    f"• Proteins: {proteins} g\n"
                    f"• Fats: {fats} g\n"
                    f"• Carbs: {carbs} g\n\n"
                    f"⏰ *Active reminders:*\n"
                )
                
                if reminders:
                    for rem in reminders:
                        stats_text += f"• {rem['text']} at {rem['time']}\n"
                else:
                    stats_text += "No active reminders\n"
                
                # Добавляем информацию о времени пробуждения и сне
                stats_text += f"\n🌅 *Wake-up time:* {wakeup_time}\n"
                stats_text += f"🌙 *Sleep time:* {sleep_time}\n"
                
                # Добавляем информацию о подписке
                subscription = await check_subscription(user_id)
                if subscription['status'] == 'trial':
                    stats_text += f"\n🆓 *Trial until:* {subscription['end_date'].strftime('%d.%m.%Y %H:%M')}"
                elif subscription['status'] == 'active':
                    stats_text += f"\n✅ *{subscription['type'].replace('_', ' ')} subscription until:* {subscription['end_date'].strftime('%d.%m.%Y %H:%M')}"
                elif subscription['status'] == 'permanent':
                    stats_text += "\n🌟 *Permanent access*"
                else:
                    stats_text += "\n❌ *No active subscription*"
            
            # Формируем клавиатуру меню
            keyboard = [
                [InlineKeyboardButton("🏋️ Начать тренировку" if language == "ru" else "🏋️ Start Workout", callback_data="start_workout")],
                [InlineKeyboardButton("✨ О возможностях бота" if language == "ru" else "✨ About bot features", callback_data="bot_features")],
                [InlineKeyboardButton("📚 Как пользоваться" if language == "ru" else "📚 How to use", callback_data="bot_usage")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                stats_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            
    except Exception as e:
        print(f"Ошибка при получении данных для меню: {e}")
        language = profile.get('language', 'ru') if profile else 'ru'
        error_msg = "Произошла ошибка при загрузке данных. Пожалуйста, попробуйте позже."
        if language == "en":
            error_msg = "An error occurred while loading data. Please try again later."
        await update.message.reply_text(error_msg)
    finally:
        if conn:
            conn.close()


async def start_workout(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id

    if not await check_access(user_id):
        await info(update, context)  # Показываем информацию о подписке
        return ConversationHandler.END

    language = "ru"  # Получаем из базы данных
    
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
            cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row and row['language']:
                language = row['language']
    except Exception as e:
        print(f"Ошибка при получении языка: {e}")
    finally:
        if conn:
            conn.close()
    
    keyboard = [
        [
            InlineKeyboardButton("В зале", callback_data="gym"),
            InlineKeyboardButton("На природе", callback_data="outdoor"),
        ],
        [
            InlineKeyboardButton("На спортплощадке", callback_data="playground"),
            InlineKeyboardButton("Дома", callback_data="home"),
        ]
    ]
    
    if language == "en":
        keyboard = [
            [
                InlineKeyboardButton("Gym", callback_data="gym"),
                InlineKeyboardButton("Outdoor", callback_data="outdoor"),
            ],
            [
                InlineKeyboardButton("Playground", callback_data="playground"),
                InlineKeyboardButton("Home", callback_data="home"),
            ]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if language == "ru":
        text = "🏋️ Где будет проходить тренировка?"
    else:
        text = "🏋️ Where will the workout take place?"
    
    await query.edit_message_text(text=text, reply_markup=reply_markup)
    return WORKOUT_LOCATION

async def select_workout_duration(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    context.user_data['workout_location'] = query.data
    
    language = "ru"  # Получаем из базы данных
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
            cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row and row['language']:
                language = row['language']
    except Exception as e:
        print(f"Ошибка при получении языка: {e}")
    finally:
        if conn:
            conn.close()
    
    keyboard = [
        [
            InlineKeyboardButton("15 мин", callback_data="15"),
            InlineKeyboardButton("30 мин", callback_data="30"),
            InlineKeyboardButton("1 час", callback_data="60"),
        ],
        [
            InlineKeyboardButton("1.5 часа", callback_data="90"),
            InlineKeyboardButton("2 часа", callback_data="120"),
        ]
    ]
    
    if language == "en":
        keyboard = [
            [
                InlineKeyboardButton("15 min", callback_data="15"),
                InlineKeyboardButton("30 min", callback_data="30"),
                InlineKeyboardButton("1 hour", callback_data="60"),
            ],
            [
                InlineKeyboardButton("1.5 hours", callback_data="90"),
                InlineKeyboardButton("2 hours", callback_data="120"),
            ]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if language == "ru":
        text = "⏱ Выберите продолжительность тренировки:"
    else:
        text = "⏱ Choose workout duration:"
    
    await query.edit_message_text(text=text, reply_markup=reply_markup)
    return WORKOUT_DURATION

async def ask_special_requests(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    context.user_data['workout_duration'] = query.data
    
    language = "ru"  # Получаем из базы данных
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
            cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row and row['language']:
                language = row['language']
    except Exception as e:
        print(f"Ошибка при получении языка: {e}")
    finally:
        if conn:
            conn.close()
    
    keyboard = [
        [
            InlineKeyboardButton("Да", callback_data="yes"),
            InlineKeyboardButton("Нет", callback_data="no"),
        ]
    ]
    
    if language == "en":
        keyboard = [
            [
                InlineKeyboardButton("Yes", callback_data="yes"),
                InlineKeyboardButton("No", callback_data="no"),
            ]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if language == "ru":
        text = "❓ Есть особые пожелания к тренировке?"
    else:
        text = "❓ Any special requests for the workout?"
    
    await query.edit_message_text(text=text, reply_markup=reply_markup)
    return WORKOUT_SPECIAL_REQUESTS

async def get_special_requests(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "no":
        # Если нет пожеланий, удаляем возможные предыдущие пожелания
        if 'workout_special_requests' in context.user_data:
            del context.user_data['workout_special_requests']
        
        # Отправляем сообщение о генерации
        language = "ru"  # Можно добавить проверку языка из профиля
        if language == "ru":
            generating_msg = await query.edit_message_text("⚙ Генерация тренировки...")
        else:
            generating_msg = await query.edit_message_text("⚙ Generating workout...")
        
        # Сохраняем ID сообщения для последующего удаления
        context.user_data['generating_msg_id'] = generating_msg.message_id
        
        return await generate_workout(update, context)

    # Запрашиваем пожелания
    user_id = query.from_user.id
    language = "ru"
    
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
            cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row and row['language']:
                language = row['language']
    except Exception as e:
        print(f"Ошибка при получении языка: {e}")
    finally:
        if conn:
            conn.close()

    if language == "ru":
        text = "📝 Напишите ваши пожелания к тренировке (например: 'хочу проработать спину', 'без прыжков' и т.д.):\n\nЭти пожелания будут учтены только для текущей тренировки."
    else:
        text = "📝 Write your special requests for the workout (e.g. 'focus on back', 'no jumps' etc.):\n\nThese requests will be considered only for this workout."

    await query.edit_message_text(text=text)
    
    # Сохраняем данные для следующего шага
    context.user_data['awaiting_special_requests'] = True
    return WORKOUT_GENERATE

async def generate_workout(update: Update, context: CallbackContext) -> int:
    # Определяем, откуда пришел запрос
    if context.user_data.get('awaiting_special_requests', False):
        user_input = update.message.text
        context.user_data['workout_special_requests'] = user_input
        context.user_data['awaiting_special_requests'] = False
        chat_id = update.message.chat_id
        from_query = False
    else:
        query = update.callback_query
        if query:
            await query.answer()
        chat_id = query.message.chat_id if query else update.message.chat_id
        from_query = bool(query)

    user_id = update.effective_user.id
    
    try:
        # Удаляем сообщение "Генерация тренировки..." если оно есть
        if 'generating_msg_id' in context.user_data:
            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=context.user_data['generating_msg_id']
                )
            except Exception as e:
                print(f"Не удалось удалить сообщение: {e}")
            finally:
                del context.user_data['generating_msg_id']

        # Получаем данные пользователя
        conn = pymysql.connect(
            host='x91345bo.beget.tech',
            user='x91345bo_nutrbot',
            password='E8G5RsAboc8FJrzmqbp4GAMbRZ',
            database='x91345bo_nutrbot',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT language, gender, activity, equipment, health, goal 
                FROM user_profiles 
                WHERE user_id = %s
            """, (user_id,))
            row = cursor.fetchone()

        if not row:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Профиль не найден. Пожалуйста, завершите анкету с помощью /start"
            )
            return ConversationHandler.END

        language = row['language'] or "ru"
        gender = row['gender'] or ("m" if language == "en" else "м")
        activity = row['activity'] or ("Intermediate" if language == "en" else "Средний")
        equipment = row['equipment'] or ""
        health = row['health'] or ""
        goal = row['goal'] or ("Healthy lifestyle" if language == "en" else "ЗОЖ")
        
        # Получаем параметры тренировки из context.user_data
        location = context.user_data.get('workout_location', 'playground')
        duration = context.user_data.get('workout_duration', '90')
        special_requests = context.user_data.get('workout_special_requests', '')
        
        # Очищаем пожелания после использования
        if 'workout_special_requests' in context.user_data:
            del context.user_data['workout_special_requests']

        # Формируем промпт для Gemini с учетом языка и пожеланий
        if location == 'home':
            equipment = row['equipment'] or ("no equipment" if language == "en" else "без инвентаря")
        elif location in ['gym', 'playground', 'outdoor']:
            if language == "en":
                equipment = {
                    'gym': "any gym equipment",
                    'playground': "pull-up bar and parallel bars",
                    'outdoor': "body weight"
                }[location]
            else:
                equipment = {
                    'gym': "любое оборудование зала",
                    'playground': "турник и брусья",
                    'outdoor': "вес тела"
                }[location]
    
        # Формируем строгий промпт с учетом языка
        if language == "en":
            prompt = f"""
            Generate a workout STRICTLY according to the following rules:
            - Location: {location} ({equipment})
            - Duration: {duration} minutes
            - Level: {activity}
            - Gender: {gender}
            - Goal: {goal}
            - User requests: {special_requests if special_requests else "no special requests"}
            - The output format MUST BE EXACTLY as in the example below

            Example:
            🏋️ Workout Name

            📍 Location: {location}
            ⏱ Duration: {duration} minutes
            🎯 Focus: [goal]
            💬 Requests: {special_requests if special_requests else "no special requests"}

            🔥 Warm-up:
            - [Exercise] - [time/reps]
            - [Exercise] - [time/reps]

            💪 Main part:
            - [Exercise] - [sets]x[reps]
            - [Exercise] - [sets]x[reps]

            🧘 Cool-down:
            - [Stretch] - [time]
            - [Stretch] - [time]

            💡 Recommendations:
            - [1 tip]
            - [1 tip]
            """
        else:
            prompt = f"""
            Сгенерируй тренировку СТРОГО по следующим правилам:
            - Место: {location} ({equipment})
            - Длительность: {duration} минут
            - Уровень: {activity}
            - Пол: {gender}
            - Цель: {goal}
            - Пожелания пользователя: {special_requests if special_requests else "нет особых пожеланий"}
            - Формат вывода ДОЛЖЕН БЫТЬ ТОЧНО как в примере ниже

            Пример:
            🏋️ Название

            📍 Место: {location}
            ⏱ Длительность: {duration} минут
            🎯 Фокус: [цель]
            💬 Пожелания: {special_requests if special_requests else "нет особых пожеланий"}

            🔥 Разминка:
            - [Упражнение] - [число] повторений/минут
            - [Упражнение] - [число] повторений/минут

            💪 Основная часть:
            - [Упражнение] - [подходы]x[повторы]
            - [Упражнение] - [подходы]x[повторы]

            🧘 Заминка:
            - [Растяжка] - [число] секунд
            - [Растяжка] - [число] секунд

            💡 Рекомендации:
            - [1 совет]
            - [1 совет]
            """
    
        # Отправляем запрос к Gemini
        response = model.generate_content(prompt)
        
        if response.text:
            # Очищаем текст от проблемных символов Markdown
            cleaned_text = clean_markdown(response.text)
            
            try:
                # Пробуем отправить с разметкой Markdown
                if from_query:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=query.message.message_id,
                        text=cleaned_text,
                        parse_mode="Markdown"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=cleaned_text,
                        parse_mode="Markdown"
                    )
            except Exception as e:
                print(f"Ошибка при отправке с Markdown: {e}")
                # Если не получилось, отправляем без разметки
                if from_query:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=query.message.message_id,
                        text=cleaned_text
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=cleaned_text
                    )
        else:
            raise ValueError("Пустой ответ от модели")

    except Exception as e:
        print(f"Ошибка при генерации тренировки: {e}")
        error_msg = "Произошла ошибка при генерации тренировки. Пожалуйста, попробуйте позже."
        if language == "en":
            error_msg = "An error occurred while generating the workout. Please try again later."
        
        if from_query:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=query.message.message_id,
                text=error_msg
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=error_msg
            )
    finally:
        if conn:
            conn.close()

    # Очищаем все данные о тренировке после генерации
    for key in ['workout_location', 'workout_duration', 'workout_special_requests', 'awaiting_special_requests']:
        if key in context.user_data:
            del context.user_data[key]

    return ConversationHandler.END

async def drank_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /drank - фиксирует выпитые 250 мл воды"""
    user_id = update.message.from_user.id

    if not await check_access(user_id):
        await info(update, context)  # Показываем информацию о подписке
        return
    
    # Получаем язык пользователя
    language = "ru"  # дефолтное значение
    conn = None
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
            cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row and row['language']:
                language = row['language']
    except Exception as e:
        print(f"Ошибка при получении языка пользователя: {e}")
    finally:
        if conn:
            conn.close()

    # Обновляем количество выпитой воды
    amount = 250
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
            cursor.execute("""
                UPDATE user_profiles
                SET water_drunk_today = water_drunk_today + %s
                WHERE user_id = %s
            """, (amount, user_id))
            conn.commit()

            # Получаем обновленные данные
            cursor.execute("""
                SELECT water_drunk_today, weight
                FROM user_profiles
                WHERE user_id = %s
            """, (user_id,))
            row = cursor.fetchone()

        recommended_water = int(row['weight'] * 30) if row['weight'] else 2100
        remaining = max(0, recommended_water - row['water_drunk_today'])

        if language == "ru":
            message = (
                f"✅ Записал! Выпито {row['water_drunk_today']} мл из {recommended_water} мл.\n"
                f"Осталось выпить: {remaining} мл."
            )
        else:
            message = (
                f"✅ Recorded! Drank {row['water_drunk_today']} ml of {recommended_water} ml.\n"
                f"Remaining: {remaining} ml."
            )

        await update.message.reply_text(message)

    except Exception as e:
        print(f"Ошибка обработки команды /drank: {e}")
        error_msg = "Произошла ошибка. Пожалуйста, попробуйте позже."
        if language == "en":
            error_msg = "An error occurred. Please try again later."
        await update.message.reply_text(error_msg)
    finally:
        if conn:
            conn.close()





async def handle_message(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id

    await update_user_activity(user_id)
    message_text = update.message.text or ""
    
    # Проверка на "секретный" код
    if message_text.strip() == PERMANENT_ACCESS_CODE:
        await grant_permanent_access(user_id)
        await update.message.reply_text("🌟 Вам предоставлен перманентный доступ к боту!")
        return
    
    # Проверка подписки перед обработкой сообщения
    subscription = await check_subscription(user_id)
    
    if subscription['status'] == 'expired':
        language = "ru"  # Можно добавить проверку языка из профиля
        if language == "ru":
            await update.message.reply_text(
                "🙏 Спасибо, что попробовали NutriBot!\n\n"
                "Ваш пробный период подошел к концу. Мы видели, как Вы старались и прогрессировали!\n\n"
                "Чтобы продолжить это путешествие к здоровью вместе с нами, оформите подписку через /info\n\n"
                "💖 Ваше здоровье - лучшая инвестиция!"
            )
        else:
            await update.message.reply_text(
                "🙏 Thank you for trying NutriBot!\n\n"
                "Your free trial has come to an end. We've seen how hard You've worked and the progress You've made!\n\n"
                "To continue this health journey with us, subscribe using /info\n\n"
                "💖 Your health is the best investment!"
            )
        return


    # Оригинальная логика обработки сообщений
    message = update.message
    user_text = message.caption or message.text or ""
    contents = []
    response_text = ""  # Инициализируем переменную заранее

    # Проверяем и сбрасываем дневные показатели, если нужно
    await reset_daily_nutrition_if_needed(user_id)

    # Получаем язык пользователя
    language = "ru"  # дефолтное значение
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
            cursor.execute("SELECT language FROM user_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row and row['language']:
                language = row['language']
    except Exception as e:
        print(f"Ошибка при получении языка пользователя: {e}")
    finally:
        if conn:
            conn.close()

    # Обработка фото/документов
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

    # Определяем тип приема пищи если это фото еды
    meal_type = None
    meal_keywords = {
        "ru": ["завтрак", "обед", "ужин", "перекус", "снек", "ланч", "ужин"],
        "en": ["breakfast", "lunch", "dinner", "snack", "supper", "brunch"]
    }
    
    # Проверяем текст на указание типа приема пищи
    for word in meal_keywords[language]:
        if word in user_text.lower():
            meal_type = word
            break
    
    # Если тип не указан, определяем по времени
    if not meal_type and (message.photo or ("калории" in user_text.lower())):
        user_timezone = "UTC"
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
                cursor.execute("SELECT timezone FROM user_profiles WHERE user_id = %s", (user_id,))
                row = cursor.fetchone()
                if row and row['timezone']:
                    user_timezone = row['timezone']
        except Exception as e:
            print(f"Ошибка при получении часового пояса: {e}")
        finally:
            if conn:
                conn.close()
        
        tz = pytz.timezone(user_timezone)
        now = datetime.now(tz)
        current_hour = now.hour
        
        if 5 <= current_hour < 11:
            meal_type = "завтрак" if language == "ru" else "breakfast"
        elif 11 <= current_hour < 16:
            meal_type = "обед" if language == "ru" else "lunch"
        elif 16 <= current_hour < 21:
            meal_type = "ужин" if language == "ru" else "dinner"
        else:
            meal_type = "перекус" if language == "ru" else "snack"

    # Добавляем информацию о приеме пищи в контекст
    if meal_type:
        contents.insert(0, {"text": f"Прием пищи: {meal_type}"})

    # Профиль пользователя
    profile_info = get_user_profile_text(user_id)
    if profile_info and "не найден" not in profile_info and "not found" not in profile_info:
        contents.insert(0, {"text": f"Информация о пользователе / User information:\n{profile_info}"})

    # История диалога
    if user_id not in user_histories:
        user_histories[user_id] = deque(maxlen=10)
    user_histories[user_id].append(f"Пользователь / User: {user_text}")
    
    if 'last_bot_reply' in context.user_data:
        user_histories[user_id].append(f"Бот / Bot: {context.user_data['last_bot_reply']}")
    
    history_messages = list(user_histories[user_id])
    if history_messages:
        history_prompt = "\n".join(history_messages)
        contents.insert(0, {"text": f"Контекст текущего диалога / Current dialog context (последние сообщения / recent messages):\n{history_prompt}"})

    # Проверяем, запрашивает ли пользователь анализ питания
        is_nutrition_analysis = ("анализ питания" in user_text.lower()) or ("nutrition analysis" in user_text.lower())

    # Если запрошен анализ питания, добавляем meal_history в контекст
    if is_nutrition_analysis:
        meal_history = await get_meal_history(user_id)
        if meal_history:
            try:
                # Проверяем и удаляем записи старше 7 дней
                current_date = date.today()
                dates_to_delete = []
            
                for day_str in list(meal_history.keys()):
                    try:
                        day_date = date.fromisoformat(day_str)
                        if (current_date - day_date).days > 7:
                            dates_to_delete.append(day_str)
                    except ValueError:
                        # Если дата в неправильном формате, пропускаем
                        continue
            
                # Удаляем старые записи
                for old_date in dates_to_delete:
                    del meal_history[old_date]
                    print(f"Удалена запись за {old_date} (старше 7 дней) для пользователя {user_id}")
            
                # Если были удалены старые записи, обновляем базу данных
                if dates_to_delete:
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
                                UPDATE user_profiles 
                                SET meal_history = %s 
                                WHERE user_id = %s
                            """, (json.dumps(meal_history), user_id))
                        conn.commit()
                    except Exception as e:
                        print(f"Ошибка при обновлении истории питания после удаления старых записей: {e}")
                    finally:
                        if conn:
                            conn.close()
            
                meals_text = "🍽 История вашего питания / Your meal history:\n"
    
                # Сортируем даты по убыванию (новые сверху)
                sorted_dates = sorted(meal_history.keys(), reverse=True)
        
                for day in sorted_dates[:7]:  # Последние 7 дней
                    meals_text += f"\n📅 {day}:\n"
                    day_meals = meal_history[day]
                    if isinstance(day_meals, dict):
                        for meal_key, meal_data in day_meals.items():
                            if isinstance(meal_data, dict):
                                meals_text += f"  - {meal_key.split('_')[0]} в {meal_data.get('time', '?')}: {meal_data.get('food', '')}\n"
                                meals_text += f"    🧪 КБЖУ: {meal_data.get('calories', 0)} ккал | "
                                meals_text += f"Б: {meal_data.get('proteins', 0)}г | "
                                meals_text += f"Ж: {meal_data.get('fats', 0)}г | "
                                meals_text += f"У: {meal_data.get('carbs', 0)}г\n"
                            else:
                                print(f"Некорректные данные о приеме пищи для {meal_key}")
                    else:
                        print(f"Некорректный формат данных за день {day}")
    
                contents.insert(0, {"text": meals_text})
            except Exception as e:
                print(f"Ошибка при формировании истории питания: {e}")
                if language == "ru":
                    await update.message.reply_text("Произошла ошибка при анализе истории питания. Попробуйте позже.")
                else:
                    await update.message.reply_text("Error analyzing meal history. Please try again later.")
                return
        else:
            if language == "ru":
                await update.message.reply_text("История питания не найдена. Начните добавлять приемы пищи.")
            else:
                await update.message.reply_text("No meal history found. Start adding meals.")
            return
    
    # Обновленный системный промпт с добавлением функционала КБЖУ
    GEMINI_SYSTEM_PROMPT = """Ты — умный ассистент, который помогает пользователю и при необходимости обновляет его профиль в базе данных.

Ты получаешь от пользователя сообщения. Они могут быть:
- просто вопросами (например, о питании, тренировках, фото и т.д.)
- обновлениями данных (например, "я набрал 3 кг" или "мне теперь 20 лет")
- сообщениями после изображения (например, "добавь это в инвентарь")
- уникальными фактами о пользователе (например, "я люблю плавание", "у меня была травма колена", "я вегетарианец 5 лет", "люблю кофе по вечерам")

Важные правила:
1. Ты выполняешь роль диетолога и фитнес-эксперта, поэтому НИКОГДА не рекомендуешь консультироваться с диетологом или врачом - ты сам предоставляешь профессиональные рекомендации.
2. Если вопрос касается серьезных медицинских проблем, ты можешь порекомендовать обратиться к врачу, но не к диетологу.
3. Для вопросов о питании, тренировках и здоровом образе жизни ты всегда даешь максимально полные ответы без отсылок к другим специалистам.

В базе данных MySQL есть таблица user_profiles с колонками:
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



6. ⚠️ Если пользователь отправляет еду и явно указывает, что он съест/ест/съел её (например: "мой завтрак", "это мой обед", "сегодня на ужин", "я съел 2 яйца и тост"):
   - Для фото: анализируй визуальное содержимое
   - Для текста: анализируй описание
   - Определи примерный состав блюда/продуктов   
   - Рассчитай КБЖУ (калории, белки, жиры, углеводы) для этого приема пищи
   - Проведи "ДНК-анализ" блюда:
     1. 🔍 Микроанализ состава:
        * Выяви скрытые ингредиенты (сахар, соль, трансжиры)
        * Определи недостающие элементы (белки, клетчатка)
     2. 💡 Персональные рекомендации:
        * Как адаптировать блюдо под цели пользователя
        * Чем заменить проблемные компоненты
     3. ⚠️ Опасные сочетания:
        * Несовместимые продукты (если есть)
        * Риски для здоровья (если выявлены)
   - Обнови соответствующие поля в базе данных (только если пользователь НЕ просил оценивать его блюдо):
     SQL: UPDATE user_profiles SET calories_today = calories_today + [калории], proteins_today = proteins_today + [белки], fats_today = fats_today + [жиры], carbs_today = carbs_today + [углеводы], last_nutrition_update = CURRENT_DATE WHERE user_id = %s
   - Ответь в формате:
     TEXT: 
     🔍 Анализ блюда:
     (Опиши ТОЛЬКО то, что действительно видно на фото. Для текста - опиши содержимое)

     🧪 ДНК-анализ:
     • Скрытые компоненты: [сахар/соль/трансжиры]
     • Дефицит: [недостающие элементы]
     • Рекомендации: [как улучшить]
     • Опасности: [если есть]
     
     🍽 Примерный КБЖУ:
     Калории: [X] ккал | Белки: [A] г | Жиры: [B] г | Углеводы: [C] г
     
     📊 Сегодня: [общая сумма калорий] ккал | [общая сумма белков] г белков | [общая сумма жиров] г жиров | [общая сумма углеводов] г углеводов
     
     (Для продуктов с разной степенью полезности:
     - Если продукт полезный:
       ✅ Полезные компоненты:
       (Опиши полезные элементы и их воздействие)
       
       💊 Витамины и минералы:
       • [Витамин/минерал] - [количество] - [польза для организма]
       • [Витамин/минерал] - [количество] - [польза для организма]
     
     - Если продукт нейтральный:
       🔄 Состав и воздействие:
       (Опиши основные компоненты и их влияние)
       
       💊 Питательные вещества:
       • [Компонент] - [нейтральное описание]
       • [Компонент] - [нейтральное описание]
     
     - Если продукт вредный:
       ⚠️ Вредные компоненты:
       • [Компонент 1] - [в чем конкретно вред]
       • [Компонент 2] - [в чем конкретно вред]
       
       ☠️ Опасные вещества:
       • [Вредное вещество] - [как влияет на организм]
       • [Дефицит полезных веществ] - [к чему приводит]
       • [Последствия при регулярном употреблении]
     )

     🧠 Мнение бота:
     (Учитывая известные предпочтения пользователя)
     
     💡 Совет:
     (Если есть что улучшить, учитывая профиль)

     📈 Для полного анализа вашего питания за несколько дней отправьте команду "Анализ питания"

   - Если пользователь ЯВНО запрашивает оценку/анализ (например: "оцени", "сколько тут калорий?", "разбери состав"):
     1. Проведи анализ (калории, БЖУ, состав)
     2. НИКОГДА не обновляй базу данных
     3. НИКОГДА не добавляй в meal_history
     4. Формат ответа только:
        TEXT:
     Evaluation

     🔍 Анализ блюда:
     (Опиши ТОЛЬКО то, что действительно видно на фото. Для текста - опиши содержимое)

     🧪 ДНК-анализ:
     • Скрытые компоненты: [сахар/соль/трансжиры]
     • Дефицит: [недостающие элементы]
     • Рекомендации: [как улучшить]
     • Опасности: [если есть]
     
     🍽 Примерный КБЖУ: Калории: [X] ккал | Белки: [A] г | Жиры: [B] г | Углеводы: [C] г
     
     (Для продуктов с разной степенью полезности:
     - Если продукт полезный:
       ✅ Полезные компоненты:
       (Опиши полезные элементы и их воздействие)
       
       💊 Витамины и минералы:
       • [Витамин/минерал] - [количество] - [польза для организма]
       • [Витамин/минерал] - [количество] - [польза для организма]
     
     - Если продукт нейтральный:
       🔄 Состав и воздействие:
       (Опиши основные компоненты и их влияние)
       
       💊 Питательные вещества:
       • [Компонент] - [нейтральное описание]
       • [Компонент] - [нейтральное описание]
     
     - Если продукт вредный:
       ⚠️ Вредные компоненты:
       • [Компонент 1] - [в чем конкретно вред]
       • [Компонент 2] - [в чем конкретно вред]
       
       ☠️ Опасные вещества:
       • [Вредное вещество] - [как влияет на организм]
       • [Дефицит полезных веществ] - [к чему приводит]
       • [Последствия при регулярном употреблении]
     )

     🧠 Мнение бота:
     (Учитывая известные предпочтения пользователя)
     
     💡 Совет:
     (Если есть что улучшить, учитывая профиль)

   - Если пользователь просто задает вопрос о еде (например: "что изображено на фото?", "что это за блюдо?", "как называется это блюдо?", "стоит ли мне это есть?", "хороший ли это вариант еды?"):
     1. Дайте прямой ответ на вопрос, без анализа КБЖУ и состава
     2. Не обновляйте базу данных
     3. Формат ответа:
        TEXT: [естественный ответ, соответствующий контексту вопроса]

   - Если вопрос эмоциональный ("красиво?", "свежее?", "нравится?"):
     1. Дайте ответ по сути вопроса
     2. Не включайте анализ КБЖУ
     3. Формат ответа:
        TEXT: [Ответ должен соответствовать контексту вопроса без автоматического анализа]
      

7. Если пользователь поправляет тебя в анализе фото (например: "там было 2 яйца, а не 3"):
   - Извинись за ошибку
   - Немедленно пересмотри свой анализ с учетом новой информации
   - Дай обновленный ответ, учитывая уточнение пользователя
   - В начале ответа добавь фразу "Correction:"
   - Обязательно укажи обновленные значения КБЖУ за сегодня
   - Формат ответа:
     TEXT: 
     Correction:
     Извините за ошибку! Я пересмотрел анализ с учетом вашей поправки.
     
     🔍 Исправленный анализ блюда:
     [описание с учетом поправки]

     🧪 ДНК-анализ:
     • Скрытые компоненты: [сахар/соль/трансжиры]
     • Дефицит: [недостающие элементы]
     • Рекомендации: [как улучшить]
     • Опасности: [если есть]
     
     🍽 Примерный КБЖУ:
     Калории: [X] ккал | Белки: [A] г | Жиры: [B] г | Углеводы: [C] г
     
     📊 Сегодня: [общая сумма калорий] ккал | [общая сумма белков] г белков | [общая сумма жиров] г жиров | [общая сумма углеводов] г углеводов
     ✅ Польза и состав:
     (Опиши пользу видимых элементов)

     🧠 Мнение бота:
     (Учитывая известные предпочтения пользователя)

     💡 Совет:
     (Если есть что улучшить, учитывая профиль)

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
   - Всегда начинай с предупреждения: \"⚠️ Внимание: Визуальная оценка крайне приблизительна и может иметь погрешность ±5-7%. Для точных результатов рекомендуются профессиональные методы (калипер, DEXA, биоимпеданс).\"
   
   - Основные диапазоны для мужчин:
     * Экстремально низкий (профессиональные бодибилдеры): 3-5% жира
     * Очень низкий (атлетичный): 6-10% жира
     * Низкий (подтянутый): 11-15% жира
     * Здоровый (средний): 16-20% жира
     * Выше среднего: 21-25% жира
     * Повышенный: 26-30% жира
     * Высокий (полный): 31-35% жира
     * Очень высокий (ожирение): 36%+ жира

   - Основные диапазоны для женщин:
     * Экстремально низкий (профессиональные спортсменки): 10-13% жира
     * Очень низкий (атлетичный): 14-18% жира
     * Низкий (подтянутый): 19-22% жира
     * Здоровый (средний): 23-27% жира
     * Выше среднего: 28-32% жира
     * Повышенный: 33-37% жира
     * Высокий (полный): 38-42% жира
     * Очень высокий (ожирение): 43%+ жира

   - Критерии визуальной оценки:
     * Для мужчин:
       - Видны все мышцы, вены по всему телу → 6-10%
       - Четкий пресс, видны вены на руках → 11-15%
       - Пресс виден при напряжении → 16-20%
       - Мягкие формы, пресс не виден → 21-25%
       - Заметные жировые отложения → 26-30%
       - Явные жировые складки → 31%+
     * Для женщин:
       - Видны мышцы, вены на руках → 14-18%
       - Четкие формы без вен → 19-22%
       - Мягкие изгибы, пресс при напряжении → 23-27%
       - Округлые формы → 28-32%
       - Заметные жировые отложения → 33-37%
       - Явные жировые складки → 38%+

   - Формат ответа ДОЛЖЕН БЫТЬ:
     TEXT:
     ⚠️ Визуальная оценка крайне приблизительна (погрешность ±5-7%). Для точности нужны профессиональные замеры.

     🔍 Оценка состава тела:
     • Пол: [определенный по фото]
     • Примерный % жира: [X]% ([уровень: атлетичный/подтянутый/средний и т.д.])
     • Примерный % мышц: [Y]%
     • Кости/вода/органы: ~15-20% массы

     📊 Визуальные признаки:
     - [Основной признак 1]
     - [Основной признак 2]
     - [Основной признак 3]

     💡 Рекомендации:
     - [Рекомендация 1 с учетом цели]
     - [Рекомендация 2]

     🏆 Здоровые диапазоны:
     - Мужчины: 10-20% жира
     - Женщины: 18-28% жира

     📌 Для точной оценки используйте: калипер, DEXA-сканирование или биоимпеданс.

12. Если пользователь сообщает о выпитой воде (в любом формате, например: "я выпил 300 мл", "только что 2 стакана воды", "drank 500ml"):
   - Извлеки количество воды из сообщения (в мл)
   - Обнови поле water_drunk_today в базе данных
     SQL: UPDATE user_profiles SET water_drunk_today = water_drunk_today + %s WHERE user_id = %s
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
     SQL: UPDATE user_profiles SET calories_today = calories_today - [старые калории] + [новые калории], proteins_today = proteins_today - [старые белки] + [новые белки], fats_today = fats_today - [старые жиры] + [новые жиры], carbs_today = carbs_today - [старые углеводы] + [новые углеводы] WHERE user_id = %s
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
     SQL: UPDATE user_profiles SET reminders = %s WHERE user_id = %s
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

22. Учет приемов пищи:
   - Если пользователь явно указывает тип приема пищи (завтрак/обед/ужин/перекус):
     * Записывать в meal_history с указанным типом
     * Формат хранения:
       {
         "дата": {
           "тип_приема_пищи": {
             "time": "ЧЧ:ММ",
             "food": "описание",
             "calories": X,
             "proteins": A,
             "fats": B,
             "carbs": C
           }
         }
       }
   - Если тип не указан, определять по времени:
     * 05:00-11:00 → завтрак
     * 11:00-16:00 → обед
     * 16:00-21:00 → ужин
     * остальное → перекус

23. Метаболизм-хаки (анализ питания):
   Анализ питания проводи ТОЛЬКО если пользователь явно запросил "анализ питания" или "nutrition analysis".
   В этом случае:
   1. Проанализируй данные за 7 дней из meal_history
   2. Выявляй паттерны:
      - Интервалы между приемами пищи
      - Баланс нутриентов по времени суток
      - Соотношение БЖУ в разные периоды
      - Пропуски приемов пищи
      - Преобладающие продукты
      - Время наибольшего потребления калорий

   3. Формируй персонализированные рекомендации на основе:
      - Целей пользователя (похудение/набор массы)
      - Уровня активности
      - Известных предпочтений и ограничений
      - Временных паттернов питания

   4. Формат ответа при анализе:
     TEXT:
     🔬 Полный анализ питания (последние 7 дней):
     
     📊 Основные показатели:
     • Среднесуточные калории: [X] ккал (рекомендуется [Y] ккал)
     • Соотношение БЖУ: [A]% белков, [B]% жиров, [C]% углеводов
     • Время наибольшего потребления калорий: [время]
     • Самый обильный прием пищи: [тип приема пищи]
     
     🔍 Ключевые наблюдения:
     1. [Наблюдение 1: например, "68% углеводов потребляется после 18:00"]
     2. [Наблюдение 2: например, "Дефицит белка утром: -15г от нормы"]
     3. [Наблюдение 3: например, "Пропущено 23% завтраков"]
     
     💡 Персональные рекомендации:
     1. [Рекомендация 1 с объяснением пользы]
     2. [Рекомендация 2 с объяснением пользы]
     3. [Рекомендация 3 с объяснением пользы]
     
     🛒 Что добавить в рацион:
     • [Продукт 1]: [чем полезен для пользователя]
     • [Продукт 2]: [чем полезен для пользователя]
     
     ⚠️ На что обратить внимание:
     • [Проблемный аспект 1]
     • [Проблемный аспект 2]

24. Коррекция данных:
   - Если пользователь говорит "вчера на ужин было не 500 ккал, а 300":
     1. Найдите запись
     2. Обновите КБЖУ:
        SQL: UPDATE user_profiles 
             SET calories_today = calories_today - (500 - 300) 
             WHERE user_id = %s
     3. Обновите meal_history
     4. Ответьте:
        TEXT: "Исправил данные по вашему ужину. Новые значения: 300 ккал."

25. Отображение ингредиентов со смайликами:
   - При упоминании любых ингредиентов в ответе добавляй соответствующие смайлики:
     * Овощи: 🥕 (морковь), 🥦 (брокколи), 🥒 (огурец), 🍅 (помидор), 🥬 (салат), 🫑 (перец), 🧅 (лук), 🧄 (чеснок), 🥔 (картофель)
     * Фрукты: 🍎 (яблоко), 🍐 (груша), 🍊 (апельсин), 🍋 (лимон), 🍌 (банан), 🍉 (арбуз), 🍇 (виноград), 🍓 (клубника), 🫐 (черника), 🍍 (ананас), 🥝 (киви)
     * Мясо/рыба: 🥩 (мясо), 🍗 (курица), 🥓 (бекон), 🍖 (кости), 🦴 (кость), 🐟 (рыба), 🐠 (рыба), 🦐 (креветка), 🦞 (лобстер), 🦀 (краб)
     * Молочные продукты: 🧀 (сыр), 🥛 (молоко), 🧈 (масло), 🥚 (яйцо)
     * Зерновые: 🍞 (хлеб), 🥐 (круассан), 🥖 (багет), 🍚 (рис), 🍜 (лапша), 🍝 (паста), 🥣 (каша)
     * Орехи/семена: 🥜 (арахис), 🌰 (орех), 🫘 (бобовые)
     * Напитки: ☕ (кофе), 🍵 (чай), 🧃 (сок), 🥤 (напиток), 🍷 (вино), 🍺 (пиво), 🥃 (алкоголь)
     * Сладости: 🍰 (торт), 🎂 (торт), 🍮 (пудинг), 🍭 (леденец), 🍫 (шоколад), 🍬 (конфета), 🍩 (пончик), 🍪 (печенье)
     * Специи/травы: 🌿 (зелень), 🍯 (мед), 🧂 (соль), 🧄 (чеснок), 🧅 (лук)
     * Разное: 🍕 (пицца), 🌭 (хот-дог), 🍔 (бургер), 🍟 (фри), 🥗 (салат), 🥙 (шаурма), 🌮 (тако), 🌯 (буррито), 🍣 (суши), 🍤 (креветки), 🥟 (пельмени), 🍦 (мороженое), 🍧 (щербет), 🍨 (мороженое), 🥮 (лунный пирог), 🍢 (оден), 🍙 (онигири), 🍘 (рисовый крекер), 🍥 (рыбный пирог), 🥠 (печенье-предсказание), 🥡 (еда на вынос)
   - Примеры:
     * "В вашем салате есть 🥬 салат, 🍅 помидоры и 🥒 огурцы"
     * "Рекомендую добавить 🍗 куриную грудку и 🥦 брокколи"
     * "На десерт можно 🍎 яблоко или 🍌 банан"

26. ⚠️ ВАЖНО: У тебя есть полная история питания пользователя (meal_history), содержащая:
- Даты и время всех приемов пищи
- Конкретные названия блюд
- Подробный состав КБЖУ для каждого приема пищи
- Тип приема пищи (завтрак/обед/ужин/перекус)

Всегда используй эту информацию при ответах на вопросы о:
- Что пользователь ел в конкретный день
- В какое время обычно ест
- Какие продукты преобладают в рационе
- Анализе пищевых привычек

27. Если пользователь просит включить напоминания о воде (например: "включи напоминания о воде", "хочу получать напоминания пить воду", "enable water reminders"):
   - Всегда отвечай, что для включения напоминаний нужно использовать команду /water
   - Не выполняй SQL-запросы для включения напоминаний напрямую
   - Формат ответа:
     TEXT: "Для включения напоминаний о воде используйте команду /water в чате. Это создаст необходимые системные напоминания."
     или
     TEXT: "To enable water reminders, please use the /water command in chat. This will create the necessary system reminders."
     (в зависимости от языка пользователя)


28. Анализ настроения:
   - Если пользователь указывает на свое эмоциональное состояние (например: "я в стрессе", "чувствую усталость", "сегодня грустно", "нет настроения", "я злюсь"):
     1. Определи тип эмоционального состояния:
        * Стресс/тревога
        * Усталость/истощение
        * Грусть/апатия
        * Раздражение/гнев
        * Радость/подъем
     2. В зависимости от состояния дай соответствующие рекомендации:
        * Для стресса:
          - Дыхательные упражнения (4-7-8: вдох 4 сек, задержка 7, выдох 8)
          - Прогулка на свежем воздухе
          - Продукты с магнием (шпинат, орехи, бананы)
          - Травяные чаи (ромашка, мята)
        * Для усталости:
          - Короткий сон (20-30 мин)
          - Легкая растяжка
          - Продукты с железом и B12 (печень, яйца, гранат)
          - Контрастный душ
        * Для грусти:
          - Физическая активность (выброс эндорфинов)
          - Социальное взаимодействие
          - Темный шоколад (70%+ какао)
          - Музыкотерапия
        * Для гнева:
          - Физическая активность (бокс, бег)
          - Техника "10 глубоких вдохов"
          - Холодная вода на запястья
          - Продукты с омега-3 (лосось, грецкие орехи)
        * Для радости:
          - Закрепление позитивного состояния
          - Благодарность (записи 3-х хороших вещей за день)
          - Совместные активности
     3. Формат ответа:
        TEXT: 
        🧠 Анализ настроения:
        Я заметил(а), что вы испытываете [тип состояния]. Это совершенно нормально!

        💡 Рекомендации:
        1. [Рекомендация 1]
        2. [Рекомендация 2]
        3. [Рекомендация 3]

        🍏 Питание:
        • [Продукт 1] - [чем поможет]
        • [Продукт 2] - [чем поможет]

        ⚠️ Важно: Если состояние сохраняется более 2 недель — обратитесь к специалисту.

   - Все рекомендации должны учитывать:
     * Известные предпочтения пользователя (diet, health)
     * Текущие цели (goal)
     * Доступное оборудование (equipment)
     * Временные ограничения (если указаны)


29. Генерация тренировок:
    ⚠️ Общая длина ответа НЕ ДОЛЖНА превышать 1000 символов.
    ⚠️ Формат ответа ДОЛЖЕН БЫТЬ ТОЧНО таким:
    
    🏋️ Название тренировки

    📍 Место: [Спортплощадка/Тренажерный зал/Природа/Дом]
    ⏱ Длительность: [время]
    🎯 Фокус: [цель]

    🔥 Разминка:
    - [Упражнение] - [время/повторы]
    - [Упражнение] - [время/повторы]

    💪 Основная часть:
    - [Упражнение] - [подходыхповторы]
    - [Упражнение] - [подходыхповторы]
    - [Упражнение] - [подходыхповторы]

    🧘 Заминка:
    - [Растяжка] - [время]
    - [Растяжка] - [время]

    💡 Рекомендации:
    - [Совет 1]
    - [Совет 2]

    СТРОГИЕ ПРАВИЛА:
    1. НИКАКИХ вступительных или заключительных фраз типа "Отлично!", "Удачи!" и т.п.
    2. Для Спортплощадки - ТОЛЬКО упражнения с весом тела, турником и брусьями.
    3. Каждое упражнение начинается с "-" и занимает ОДНУ строку.
    4. Описание техники ДОЛЖНО быть не более 3-5 слов в скобках.
    5. Рекомендации - не более 2 пунктов.
    6. НИКАКИХ звездочек (*) для выделения текста.
    7. Для разминки/заминки указывать только время выполнения (в минутах) или количество повторений.
    8. Для основной части - только подходы и повторения в формате "3x12".
    9. Названия упражнений должны быть КРАТКИМИ без лишних слов.
    10. НИКАКИХ дополнительных пояснений вне указанного формата.

    Пример ПРАВИЛЬНОГО ответа:
    🏋️ Тренировка на Спортплощадке

    📍 Место: Спортплощадка
    ⏱ Длительность: 30 минут
    🎯 Фокус: Верх тела и пресс

    🔥 Разминка:
    - Бег на месте - 2 минуты
    - Вращения руками - 1 минута
    - Наклоны в стороны - 1 минута

    💪 Основная часть:
    - Подтягивания - 3x8 (хват шире плеч)
    - Отжимания на брусьях - 3x10
    - Подъемы ног в висе - 3x12
    - Отжимания от пола - 3x15

    🧘 Заминка:
    - Растяжка плеч - 30 секунд
    - Растяжка спины - 30 секунд

    💡 Рекомендации:
    - Отдых между подходами 60 сек
    - Следить за техникой


30. Ответы о пользе продуктов:
   - Если пользователь спрашивает о пользе какого-либо продукта (например: "в чем польза дыни?", "можно ли есть малину перед сном?", "полезен ли творог на ужин?"):
     1. Всегда отвечай развернуто, структурированно и с научным обоснованием.
     2. Формат ответа ДОЛЖЕН БЫТЬ:
        TEXT:
        [Название продукта и краткое предисловие]

        ### 1. Богат витаминами и минералами
        - [Витамин/минерал] – [польза, например: "укрепляет иммунитет"]
        - [Витамин/минерал] – [польза]

        ### 2. [Основная категория пользы, например: "Улучшает пищеварение"]
        - [Конкретный эффект, например: "Содержит клетчатку, которая помогает при запорах"]
        - [Дополнительная информация]

        ### 3. [Другая категория пользы]
        - [Конкретные преимущества]
        - [Научные факты]

        ### 4. Дополнительные преимущества
        - [Интересный факт]
        - [Практический совет по употреблению]

        ⚠️ Осторожно:
        - [Предостережение, если есть]
        - [Кому стоит ограничить потребление]

        💡 Вывод: [Краткое резюме]. [Рекомендация по употреблению].

     3. Всегда указывай конкретные цифры (например: "содержит 30% дневной нормы витамина C").
     4. Добавляй смайлы для наглядности (🍎💪🧠).
     5. Если продукт имеет особенности употребления (например, не рекомендуется на ночь) — обязательно укажи это.
     6. Для сезонных продуктов добавляй информацию о лучшем времени употребления.
     7. Если есть исследования — ссылайся на них (например: "Исследования Harvard University показали...").

   Пример ПРАВИЛЬНОГО ответа:
   TEXT:
   🍈 Дыня не только вкусная, но и очень полезная. Вот её основные преимущества для здоровья:

   ### 1. Богата витаминами и минералами
   - Витамин C – укрепляет иммунитет, улучшает состояние кожи (30% дневной нормы в 100 г)
   - Витамин A (бета-каротин) – полезен для зрения и кожи
   - Калий – поддерживает сердце и нормализует давление
   - Фолиевая кислота – важна для беременных

   ### 2. Улучшает пищеварение
   - Содержит клетчатку, которая помогает при запорах
   - Легко усваивается, но в больших количествах может вызвать тяжесть

   ### 3. Поддерживает сердце
   - Снижает уровень "плохого" холестерина
   - Калий и магний помогают нормализовать давление

   ### 4. Дополнительные преимущества
   - Низкокалорийная (всего 35 ккал на 100 г)
   - Обладает мочегонным эффектом (выводит лишнюю воду)

   ⚠️ Осторожно:
   - Не стоит есть натощак
   - Диабетикам нужно ограничивать из-за высокого ГИ

   💡 Вывод: Дыня — это витаминная бомба, которая помогает сердцу, коже и пищеварению! Лучше употреблять между приемами пищи.

31. Ответы на вопросы вне основной специализации:
   - Никогда не отказывайся отвечать на вопросы, даже если они выходят за рамки основной специализации
   - Всегда предоставляй максимально полную, структурированную и полезную информацию
   - Если не уверен в точности данных - предупреди об этом, но все равно дай максимально полный ответ
   - Если пользователь задает вопрос, не связанный напрямую с питанием, фитнесом или здоровьем:
     1. Всегда давай максимально информативный и структурированный ответ
     2. Никогда не говори "это не моя специализация" или "я могу отвечать только о питании"
     3. Формат ответа должен быть:
        TEXT:
        🔍 [Краткое введение в тему вопроса]
        
        ### 1. Основные аспекты
        - [Ключевой аспект 1] - [подробное объяснение]
        - [Ключевой аспект 2] - [подробное объяснение]
        
        ### 2. Важные критерии выбора/оценки
        - [Критерий 1] - [как оценивать]
        - [Критерий 2] - [как оценивать]
        
        ### 3. Популярные варианты
        - [Вариант 1] - [плюсы/минусы]
        - [Вариант 2] - [плюсы/минусы]
        
        ### 4. Рекомендации
        - Для [цель/ситуация X] лучше подойдет [вариант] потому что...
        - Для [цель/ситуация Y] предпочтительнее [вариант] так как...
        
        💡 Вывод:
        [Обобщенная рекомендация с учетом всех факторов]
        
     4. Если тема требует специальных знаний (медицина, юриспруденция) - добавляй предупреждение:
        ⚠️ Важно: Для точной информации рекомендуется консультация специалиста [указать какого]
        
     5. Всегда сохраняй:
        - Объективность (не выдумывай факты)
        - Структурированность (четкие разделы)
        - Практическую пользу (конкретные рекомендации)
        - Учет доступных данных (если есть информация о пользователе)

32. Ответы на общие вопросы:
   - Если пользователь задает общий вопрос, не связанный с питанием, тренировками или анализом фото:
     1. Никогда не упоминай в ответе что-либо про "прием пищи", "удаление записей" или другие технические термины базы данных
     2. Давай прямой, полезный ответ на поставленный вопрос
     3. Если вопрос медицинский - дай общую информацию, но укажи, что для точного диагноза нужно обратиться к врачу
     4. Формат ответа:
        TEXT: [четкий ответ на вопрос]
        ⚠️ Если вопрос медицинский, добавь:
        "Для точного диагноза и лечения рекомендуется обратиться к врачу."

   Примеры правильных ответов:
   - На вопрос "Скажи, если при заложенном носе пожевать гвоздику - поможет ли?"
     TEXT: Гвоздика содержит эвгенол, который может временно облегчить заложенность носа благодаря своим противовоспалительным и антисептическим свойствам. Однако это не заменяет полноценного лечения. Для хронических проблем с носом лучше обратиться к ЛОРу.
     ⚠️ Для точного диагноза и лечения рекомендуется обратиться к врачу.

   - На вопрос "Как настроить гитару?"
     TEXT: Настройка гитары стандартным строем (EADGBE):
     1. Используйте тюнер или приложение-тюнер
     2. Начинайте с самой толстой струны (6-я)
     3. Настройте по порядку: E (ми), A (ля), D (ре), G (соль), B (си), E (ми)
     4. Проверьте звучание аккордов


33. Улучшение коммуникации:
    1. **Тон и стиль:**
    - Всегда отвечай дружелюбным, но профессиональным тоном, как заботливый эксперт.
    - Используй естественные разговорные конструкции, избегай шаблонных фраз.
    - Допустимы уместные шутки и легкая самоирония, но без фамильярности.

    2. **Эмпатия:**
    - Если пользователь делится достижениями ("сбросил 2 кг") — искренне радуйся🎉
    - Если пользователь расстроен — прояви поддержку

    3. **Персонализация:**
    - Обращайся по имени (если оно известно):
        "Алексей, для вашей цели набора массы я бы рекомендовал..."
    - Упоминай уникальные факты о пользователе:
        "Как вы упоминали, вам нравится плавание — это отлично дополняет ваши тренировки!"

    4. **Естественность:**
    - Допустимы междометия в меру: "Хм, интересный вопрос!", "О, это мой любимый продукт!"
    - Используй разговорные сокращения где уместно: "вас" вместо "Вас", "давайте" вместо "Давайте".
    - Избегай канцеляризмов — говори как живой человек.

    5. **Ошибки и уточнения:**
    - Если ошибся — извиняйся естественно:
        "Ой, кажется я misunderstood! Спасибо что поправили, учту."
    - При уточнении — мягкие формулировки:
        "Чтобы дать точный совет, уточните пожалуйста..."

    Примеры улучшенных ответов:
    - Вместо: "Рекомендую употреблять 200 г куриной грудки." →
    "Отличный выбор! 🍗 Куриная грудка (200 г) даст вам около 40 г белка — идеально после тренировки."
    - Вместо: "Ваш вес обновлен в базе." →
    "Записал ваш новый вес! Вижу прогресс — вы на верном пути 💪"

34. Удаление крайнего приема пищи:
   - Если пользователь явно просит удалить крайний прием пищи (например: "удали последний прием пищи", "отмени мой последний обед", "убери запись о последнем ужине"):
     1. Ответь пользователю в формате:
        TEXT: 
        Removal
        Готово! 🎯 Запись о последнем приеме пищи удалена. Если нужно что-то уточнить или исправить — просто скажите! Всегда рад помочь. 💪


        
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

        # Обработка SQL команд из ответа Gemini
        sql_part = None
        text_part = None

        # Обработка случая Correction (когда бот корректирует дневные показатели и последний прием пищи)
        if "Correction" in response_text:
            # Парсим обновленные значения КБЖУ
            today_match = re.search(
                r'📊 Сегодня:\s*(\d+)\s*ккал\s*\|\s*(\d+)\s*г\s*белков\s*\|\s*(\d+)\s*г\s*жиров\s*\|\s*(\d+)\s*г\s*углеводов',
                response_text
            )
            
            if today_match:
                calories = int(today_match.group(1))
                proteins = int(today_match.group(2))
                fats = int(today_match.group(3))
                carbs = int(today_match.group(4))
                
                # 1. Обновляем дневные показатели в базе данных
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
                        # Обновляем основные показатели
                        cursor.execute("""
                            UPDATE user_profiles 
                            SET 
                                calories_today = %s,
                                proteins_today = %s,
                                fats_today = %s,
                                carbs_today = %s
                            WHERE user_id = %s
                        """, (calories, proteins, fats, carbs, user_id))
                        
                        # 2. Обновляем последний прием пищи в meal_history
                        # Получаем текущую историю питания
                        cursor.execute("""
                            SELECT meal_history FROM user_profiles 
                            WHERE user_id = %s
                        """, (user_id,))
                        result = cursor.fetchone()
                        
                        if result and result['meal_history']:
                            meal_history = json.loads(result['meal_history'])
                            today_str = date.today().isoformat()
                            
                            if today_str in meal_history and meal_history[today_str]:
                                # Находим последний прием пищи за сегодня
                                last_meal_key = sorted(meal_history[today_str].keys())[-1]
                                last_meal = meal_history[today_str][last_meal_key]
                                
                                # Парсим новое описание еды из ответа
                                food_match = re.search(r'🔍 Исправленное блюдо:\s*(.*?)(?=\n\n|$)', response_text, re.DOTALL)
                                if food_match:
                                    last_meal['food'] = food_match.group(1).strip()
                                
                                # Обновляем КБЖУ последнего приема пищи
                                last_meal.update({
                                    'calories': calories,
                                    'proteins': proteins,
                                    'fats': fats,
                                    'carbs': carbs
                                })
                                
                                # Сохраняем обновленную историю
                                cursor.execute("""
                                    UPDATE user_profiles 
                                    SET meal_history = %s 
                                    WHERE user_id = %s
                                """, (json.dumps(meal_history), user_id))
                        
                        conn.commit()
                        print(f"Обновлены КБЖУ и последний прием пищи после коррекции для пользователя {user_id}")
                finally:
                    if conn:
                        conn.close()

        # Обработка случая Evaluation (когда пользователь просто оценивает блюдо, а не добавляет его)
        elif "Evaluation" in response_text:
            # Парсим примерные значения КБЖУ из ответа
            kbju_match = re.search(
                r'🍽 Примерный КБЖУ:\s*Калории:\s*(\d+)\s*ккал\s*\|\s*Белки:\s*(\d+)\s*г\s*\|\s*Жиры:\s*(\d+)\s*г\s*\|\s*Углеводы:\s*(\d+)\s*г',
                response_text
            )
            
            if kbju_match:
                # Получаем значения КБЖУ, но НЕ изменяем дневные показатели
                calories = int(kbju_match.group(1))
                proteins = int(kbju_match.group(2))
                fats = int(kbju_match.group(3))
                carbs = int(kbju_match.group(4))
                
                print(f"Оценка блюда: {calories} ккал, {proteins} белки, {fats} жиры, {carbs} углеводы (не изменяем дневные показатели)")

        # Обработка случая Removal (когда бот удаляет последний прием пищи)
        elif "Removal" in response_text:
            # 1. Получаем последний прием пищи из meal_history
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
                    # Получаем текущую историю питания
                    cursor.execute("""
                        SELECT meal_history FROM user_profiles 
                        WHERE user_id = %s
                    """, (user_id,))
                    result = cursor.fetchone()
                    
                    if result and result['meal_history']:
                        meal_history = json.loads(result['meal_history'])
                        today_str = date.today().isoformat()
                        
                        if today_str in meal_history and meal_history[today_str]:
                            # Получаем все ключи приемов пищи за сегодня
                            meal_keys = list(meal_history[today_str].keys())
                            
                            # Сортируем по времени добавления (по timestamp в ключе)
                            meal_keys_sorted = sorted(
                                meal_keys,
                                key=lambda x: int(x.split('_')[-1]) if '_' in x else 0,
                                reverse=True
                            )
                            
                            if meal_keys_sorted:
                                # Берем самый последний добавленный прием пищи
                                last_meal_key = meal_keys_sorted[0]
                                last_meal = meal_history[today_str][last_meal_key]
                                
                                # Получаем КБЖУ последнего приема пищи
                                calories = last_meal.get('calories', 0)
                                proteins = last_meal.get('proteins', 0)
                                fats = last_meal.get('fats', 0)
                                carbs = last_meal.get('carbs', 0)
                                
                                # 2. Вычитаем КБЖУ из дневных показателей
                                cursor.execute("""
                                    UPDATE user_profiles 
                                    SET 
                                        calories_today = GREATEST(0, calories_today - %s),
                                        proteins_today = GREATEST(0, proteins_today - %s),
                                        fats_today = GREATEST(0, fats_today - %s),
                                        carbs_today = GREATEST(0, carbs_today - %s)
                                    WHERE user_id = %s
                                """, (
                                    calories,
                                    proteins,
                                    fats,
                                    carbs,
                                    user_id
                                ))
                                
                                # 3. Удаляем последний прием пищи из истории
                                del meal_history[today_str][last_meal_key]
                                
                                # Если день пустой, удаляем его полностью
                                if not meal_history[today_str]:
                                    del meal_history[today_str]
                                
                                # Сохраняем обновленную историю
                                cursor.execute("""
                                    UPDATE user_profiles 
                                    SET meal_history = %s 
                                    WHERE user_id = %s
                                """, (json.dumps(meal_history), user_id))
                                
                                conn.commit()
                                print(f"Удален последний прием пищи ({last_meal_key}) и скорректированы КБЖУ для пользователя {user_id}")
            finally:
                if conn:
                    conn.close()


        # Разделяем SQL и TEXT части ответа
        sql_match = re.search(r'SQL:(.*?)(?=TEXT:|$)', response_text, re.DOTALL)
        if sql_match:
            sql_part = sql_match.group(1).strip()
            
            # Пропускаем SQL-запросы, связанные с nutrition_update и meal_history,
            # так как они обрабатываются отдельно
            if not any(keyword in sql_part.lower() for keyword in ['nutrition_update', 'meal_history', 'calories_today', 'proteins_today', 'fats_today', 'carbs_today']):
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
                        sql_part = sql_part.replace('?', '%s')
                        if "%s" in sql_part:
                            cursor.execute(sql_part, (user_id,))
                        else:
                            cursor.execute(sql_part)
                        conn.commit()
                        print(f"Выполнен SQL: {sql_part}")
                except Exception as e:
                    print(f"Ошибка при выполнении SQL: {e}")
                finally:
                    if conn:
                        conn.close()

        # Извлекаем текст для пользователя
        text_matches = re.findall(r'TEXT:(.*?)(?=SQL:|$)', response_text, re.DOTALL)
        if text_matches:
            text_part = text_matches[-1].strip()
        else:
            text_part = re.sub(r'SQL:.*?(?=TEXT:|$)', '', response_text, flags=re.DOTALL).strip()

        if not text_part:
            text_part = "Я обработал ваш запрос. Нужна дополнительная информация?"

        
        # Если это был прием пищи и НЕ оценка (Evaluation), сохраняем данные
        if meal_type and ("калории" in response_text.lower() or "calories" in response_text.lower()) and "Evaluation" not in response_text:
            # Парсим КБЖУ из ответа
            calories_match = re.search(r'Калории:\s*(\d+)', response_text) or re.search(r'Calories:\s*(\d+)', response_text)
            proteins_match = re.search(r'Белки:\s*(\d+)', response_text) or re.search(r'Proteins:\s*(\d+)', response_text)
            fats_match = re.search(r'Жиры:\s*(\d+)', response_text) or re.search(r'Fats:\s*(\d+)', response_text)
            carbs_match = re.search(r'Углеводы:\s*(\d+)', response_text) or re.search(r'Carbs:\s*(\d+)', response_text)
    
            if calories_match and proteins_match and fats_match and carbs_match:
                try:
                    calories = int(calories_match.group(1))
                    proteins = int(proteins_match.group(1))
                    fats = int(fats_match.group(1))
                    carbs = int(carbs_match.group(1))
                    
                    # Получаем описание еды
                    food_description = None
                    analysis_match = re.search(r'🔍 Анализ блюда:\s*(.*?)(?=\n\n|$)', response_text, re.DOTALL)
                    if analysis_match:
                        food_description = analysis_match.group(1).strip()
                    else:
                        food_description = " ".join([part for part in response_text.split("\n") if part and not part.startswith(("SQL:", "TEXT:", "🔍", "🧪", "🍽", "📊"))][:3])
                    
                    # Получаем текущее время пользователя
                    user_timezone = await get_user_timezone(user_id)
                    current_time = datetime.now(user_timezone).strftime("%H:%M")
                    
                    # 1. Обновляем meal_history
                    date_str = date.today().isoformat()
                    meal_data = {
                        "time": current_time,
                        "food": food_description or user_text,
                        "calories": calories,
                        "proteins": proteins,
                        "fats": fats,
                        "carbs": carbs
                    }
                    
                    await update_meal_history(user_id, {
                        meal_type: meal_data
                    })
                    
                    # 2. Обновляем основные поля КБЖУ
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
                                UPDATE user_profiles 
                                SET 
                                    calories_today = calories_today + %s,
                                    proteins_today = proteins_today + %s,
                                    fats_today = fats_today + %s,
                                    carbs_today = carbs_today + %s,
                                    last_nutrition_update = %s
                                WHERE user_id = %s
                            """, (
                                calories,
                                proteins,
                                fats,
                                carbs,
                                date_str,
                                user_id
                            ))
                            conn.commit()
                            print(f"Обновлены КБЖУ для пользователя {user_id}: +{calories} ккал")
                    finally:
                        if conn:
                            conn.close()
                        
                except Exception as e:
                    print(f"Ошибка при сохранении данных о приеме пищи: {e}")


        await update.message.reply_text(text_part)

    except Exception as e:
        error_message = "Произошла ошибка при обработке запроса. Пожалуйста, попробуйте еще раз."
        if language == "en":
            error_message = "An error occurred while processing your request. Please try again."
        await update.message.reply_text(error_message)
        print(f"Ошибка при генерации ответа: {e}")


def main():
    init_db()
    
    # Создаем Application с post_init обработчиком
    app = Application.builder() \
        .token(TOKEN) \
        .post_init(post_init) \
        .build()

    # Добавляем job для проверки неактивных пользователей
    app.job_queue.run_repeating(
        check_inactive_users,
        interval=600,
        first=10
    )

    # Добавляем job для проверки напоминаний
    app.job_queue.run_repeating(
        check_reminders,
        interval=60,  # Проверяем каждую минуту
        first=10      # Первая проверка через 10 секунд
    )
    
    # Проверяем и создаем jobs для напоминаний о воде при старте
    app.job_queue.run_once(
        lambda ctx: check_and_create_water_job(ctx),
        when=5  # Через 5 секунд после старта
    )

    app.job_queue.run_once(
        lambda ctx: check_inactive_users(ctx),
        when=5
    )

    app.job_queue.run_repeating(
        check_payment_status, 
        interval=300, 
        first=10
    )

    workout_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_workout, pattern="^start_workout$")],
        states={
            WORKOUT_LOCATION: [CallbackQueryHandler(select_workout_duration)],
            WORKOUT_DURATION: [CallbackQueryHandler(ask_special_requests)],
            WORKOUT_SPECIAL_REQUESTS: [
                CallbackQueryHandler(get_special_requests, pattern="^yes$"),
                CallbackQueryHandler(generate_workout, pattern="^no$"),
            ],
            WORKOUT_GENERATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, generate_workout)],
        },
        fallbacks=[],
    )

    app.add_handler(workout_conv_handler)

    # Добавляем обработчик кнопок
    app.add_handler(CallbackQueryHandler(button_handler))

    # Добавляем обработчик команды /drank
    app.add_handler(CommandHandler("drank", drank_command))

    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    

    # Остальной код остается без изменений
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
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("water", toggle_water_reminders))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()









