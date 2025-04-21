import os
import re
import base64
import aiohttp
import sqlite3
import telegram
from collections import deque
from telegram import Update, File
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler
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

(ASK_NAME, ASK_GENDER, ASK_AGE, ASK_WEIGHT, ASK_GOAL, ASK_ACTIVITY, ASK_DIET_PREF, ASK_HEALTH, ASK_EQUIPMENT, ASK_TARGET) = range(10)

def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    # Создаем основную таблицу профилей
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
    
    # Создаем таблицу для дополнительных данных пользователя
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_additional_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        data_type TEXT,
        data_value TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES user_profiles(user_id)
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

def save_additional_user_data(user_id: int, data_type: str, data_value: str):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO user_additional_data (user_id, data_type, data_value)
    VALUES (?, ?, ?)
    ''', (user_id, data_type, data_value))
    
    conn.commit()
    conn.close()

def get_additional_user_data(user_id: int) -> str:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT data_type, data_value 
    FROM user_additional_data 
    WHERE user_id = ?
    ORDER BY timestamp DESC
    LIMIT 10
    ''', (user_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return ""
    
    return "\n".join([f"{row[0]}: {row[1]}" for row in rows])

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
    
    # Получаем основной профиль
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        await update.message.reply_text("Профиль не найден. Пройди анкету с помощью /start.")
        return
    
    # Получаем дополнительные данные
    additional_data = get_additional_user_data(user_id)
    
    profile_text = (
        f"Твой профиль:\n\n"
        f"Имя: {row[1]}\nПол: {row[2]}\nВозраст: {row[3]}\nВес: {row[4]} кг\n"
        f"Цель: {row[5]}\nАктивность: {row[6]}\nПитание: {row[7]}\n"
        f"Здоровье: {row[8]}\nИнвентарь: {row[9]}\nЦелевая метрика: {row[10]}"
    )
    
    if additional_data:
        profile_text += "\n\nДополнительные данные:\n" + additional_data
    
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
    
    # Получаем основной профиль
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        return "Профиль пользователя не найден."
    
    # Получаем дополнительные данные
    additional_data = get_additional_user_data(user_id)
    
    profile_text = (
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
    
    if additional_data:
        profile_text += "\n\nДополнительные данные:\n" + additional_data
    
    return profile_text

async def handle_message(update: Update, context: CallbackContext) -> None:
    message = update.message
    user_id = message.from_user.id
    user_text = message.caption or message.text or ""
    
    contents = []
    
    # Обработка медиафайлов
    media_files = message.photo or []
    if message.document:
        media_files.append(message.document)
    
    media_description = ""
    for file in media_files:
        try:
            part = await download_and_encode(file)
            contents.append(part)
            
            # Получаем описание изображения отдельно
            media_response = model.generate_content([part, {"text": "Что изображено на фото? Ответь только названием объекта, без дополнительных слов."}])
            media_description = media_response.text.strip()
        except Exception as e:
            await message.reply_text(f"Ошибка при загрузке файла: {str(e)}")
            return
    
    if user_text:
        contents.insert(0, {"text": user_text})
    
    if not contents:
        await message.reply_text("Пожалуйста, отправь текст, изображение или документ.")
        return
    
    # Добавляем описание медиа в историю
    if media_description:
        if user_id not in user_histories:
            user_histories[user_id] = deque(maxlen=5)
        user_histories[user_id].append(f"На фото: {media_description}")
    
    # Профиль пользователя
    profile_info = get_user_profile_text(user_id)
    if profile_info and "не найден" not in profile_info:
        contents.insert(0, {"text": f"Информация о пользователе:\n{profile_info}"})
    
    # История сообщений
    if user_id in user_histories:
        history_messages = list(user_histories[user_id])
        if history_messages:
            history_prompt = "\n".join(f"Пользователь: {msg}" for msg in history_messages)
            contents.insert(0, {"text": f"История последних сообщений:\n{history_prompt}"})
    
    # Улучшенный системный промпт
    GEMINI_SYSTEM_PROMPT = """Ты — фитнес-ассистент, работающий с базой данных. Твои задачи:

1. При запросе "добавь это в мой спортивный инвентарь":
   - Если было фото: используй последнее описание из истории ("На фото: ...")
   - Сгенерируй:
     SQL: UPDATE user_profiles SET equipment = CASE WHEN equipment IS NULL OR equipment = '' THEN ? ELSE equipment || ', ' || ? END WHERE user_id = ?
     PARAMS: ["название предмета", "название предмета", user_id]
     ADDITIONAL: equipment:название предмета
     TEXT: Конкретный ответ (например: "Добавил горный велосипед в ваш спортивный инвентарь")

2. Для других обновлений:
   SQL: соответствующий запрос
   TEXT: ответ

3. Для вопросов:
   TEXT: ответ

Формат ответа строго:
SQL: ...
PARAMS: ...
ADDITIONAL: ...
TEXT: ...
"""
    
    contents.insert(0, {"text": GEMINI_SYSTEM_PROMPT})
    
    try:
        response = model.generate_content(contents)
        response_text = response.text.strip()
        print("Ответ Gemini:", response_text)  # Отладочная информация
        
        # Обработка SQL
        sql_match = re.search(r"SQL:\s*(.*?)\nPARAMS:", response_text, re.DOTALL)
        params_match = re.search(r"PARAMS:\s*(.*?)\n(?:ADDITIONAL|TEXT):", response_text, re.DOTALL)
        
        if sql_match and params_match:
            sql_query = sql_match.group(1).strip()
            try:
                params = eval(params_match.group(1).strip())
                conn = sqlite3.connect("users.db")
                cursor = conn.cursor()
                cursor.execute(sql_query, params)
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"SQL error: {e}")
        
        # Обработка дополнительных данных
        additional_match = re.search(r"ADDITIONAL:\s*(.*?)\nTEXT:", response_text, re.DOTALL)
        if additional_match:
            additional_data = additional_match.group(1).strip()
            try:
                data_type, data_value = additional_data.split(":", 1)
                save_additional_user_data(user_id, data_type.strip(), data_value.strip())
            except Exception as e:
                print(f"Additional data error: {e}")
        
        # Отправка ответа
        text_match = re.search(r"TEXT:\s*(.+)", response_text, re.DOTALL)
        if text_match:
            reply_text = text_match.group(1).strip()
            await message.reply_text(reply_text)
        else:
            await message.reply_text("Готово! Могу чем-то еще помочь?")
    
    except Exception as e:
        await message.reply_text(f"Произошла ошибка: {str(e)}")

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
