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
    Ты — умный и дружелюбный фитнес-ассистент NutriBot. Твоя цель — задавать вопросы для анкеты так, чтобы они звучали естественно, мотивирующе и с ноткой индивидуальности. Используй информацию о пользователе, если она доступна, чтобы сделать вопрос более персонализированным. Если пользователь уже ответил на предыдущий вопрос, учти это в формулировке (например, добавь похвалу или комментарий).

    Информация о пользователе:
    {profile_info}

    Предыдущий ответ пользователя (если есть): {previous_answer or 'Нет ответа'}

    Вопрос для анкеты: {question}

    Сгенерируй текст вопроса, который:
    - Звучит дружелюбно и естественно
    - Учитывает профиль пользователя (если он не пустой)
    - Может включать эмодзи, мотивационные фразы или лёгкий юмор
    - Если это уместно, добавь короткий комментарий или совет, связанный с предыдущим ответом

    Ответ верни в формате:
    TEXT: ...
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
        await update.message.reply_text("Ой, кажется, я жду только 'м' или 'ж' 😊 Попробуй ещё раз!")
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
        await update.message.reply_text("Хм, возраст нужен в цифрах 😄 Например, 25. Давай ещё раз!")
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
        await update.message.reply_text("Вес нужен в цифрах, например, 70.5 😊 Попробуй снова!")
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
        await update.message.reply_text("Рост нужен в цифрах, например, 175 😄 Давай ещё раз!")
        return ASK_HEIGHT
    user_profiles[user_id]["height"] = height
    question = "Какая у тебя цель? (Похудеть, Набрать массу, Рельеф, Просто ЗОЖ)"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_GOAL

async def ask_activity(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["goal"] = update.message.text
    question = "Какой у тебя уровень активности/опыта? (Новичок, Средний, Продвинутый)"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_ACTIVITY

async def ask_diet_pref(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["activity"] = update.message.text
    question = "Есть ли у тебя предпочтения в еде? (Веганство, без глютена и т.п.)"
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
    question = "Какой инвентарь/тренажёры у тебя есть?"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_EQUIPMENT

async def ask_target(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["equipment"] = update.message.text
    question = "Какая у тебя конкретная цель по весу или другим метрикам?"
    prompt = await generate_dynamic_prompt(user_id, question, update.message.text)
    await update.message.reply_text(prompt)
    return ASK_TARGET

async def finish_questionnaire(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["target_metric"] = update.message.text
    name = user_profiles[user_id]["name"]
    save_user_profile(user_id, user_profiles[user_id])

    # Generate a personalized completion message
    profile_info = get_user_profile_text(user_id)
    prompt = f"""
    Ты — NutriBot, дружелюбный фитнес-ассистент. Пользователь только что завершил анкету. Сгенерируй мотивирующее и персонализированное сообщение о завершении анкеты, используя данные профиля. Упомяни имя пользователя и хотя бы одну деталь из профиля (например, цель или активность). Добавь эмодзи и немного энтузиазма!

    Информация о пользователе:
    {profile_info}

    Ответ верни в формате:
    TEXT: ...
    """
    try:
        response = model.generate_content([{"text": prompt}])
        text_match = re.search(r"TEXT:\s*(.+)", response.text, re.DOTALL)
        reply_text = text_match.group(1).strip() if text_match else f"Отлично, {name}! Анкета завершена 🎉 Теперь я знаю всё, чтобы помочь тебе на пути к цели! Отправляй фото, текст или вопросы — я всегда тут! 💪"
    except Exception:
        reply_text = f"Отлично, {name}! Анкета завершена 🎉 Теперь я знаю всё, чтобы помочь тебе на пути к цели! Отправляй фото, текст или вопросы — я всегда тут! 💪"
    
    await update.message.reply_text(reply_text)
    return ConversationHandler.END

async def show_profile(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("Ой, твой профиль пока пуст 😔 Пройди анкету с помощью /start, и я помогу тебе начать! 🚀")
        return

    # Calculate BMI if height and weight are available
    bmi_info = ""
    if row[4] and row[5]:
        try:
            bmi = row[4] / ((row[5] / 100) ** 2)
            bmi_category = (
                "ниже нормы" if bmi < 18.5 else
                "нормальный" if 18.5 <= bmi < 25 else
                "избыточный вес" if 25 <= bmi < 30 else
                "ожирение"
            )
            bmi_info = f"\nИМТ: {bmi:.1f} ({bmi_category})"
        except:
            bmi_info = "\nИМТ: не удалось рассчитать"

    profile_text = (
        f"Твой профиль, {row[1]}:\n\n"
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
    await update.message.reply_text("Всё сброшено, как будто мы только познакомились! 😄 Начнём заново? Используй /start! 🚀")

async def generate_image(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Генерация изображений пока в разработке, но я уже мечтаю нарисовать тебе идеальный план тренировок! 😎 Жди обновлений!")

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
            await message.reply_text(f"Ой, что-то пошло не так с файлом 😕 Попробуй другой или напиши текст! Ошибка: {str(e)}")
            return

    if user_text:
        contents.insert(0, {"text": user_text})
    if not contents:
        await message.reply_text("Хм, отправь мне текст, фото или документ, и я помогу! 😊 Например, расскажи о своей тренировке или спроси про питание!")
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
    GEMINI_SYSTEM_PROMPT = """Ты — NutriBot, умный, дружелюбный и мотивирующий фитнес-ассистент, который помогает пользователям достигать их целей в фитнесе и здоровом образе жизни. Твои ответы должны быть информативными, основанными на научных данных, и при этом понятными и мотивирующими. Используй эмодзи, лёгкий юмор и персонализированный подход, чтобы сделать общение живым и приятным.

Ты получаешь от пользователя сообщения. Они могут быть:
- Вопросами о питании, тренировках, здоровье или анализе фото/документов
- Обновлениями данных профиля (например, "мой вес теперь 75 кг" или "добавь гантели в инвентарь")
- Свободной беседой, где могут упоминаться новые факты о пользователе

В базе данных есть таблица user_profiles с колонками:
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

Твоя задача:
1. Если пользователь задаёт вопрос (например, "что поесть после тренировки?" или "анализируй фото еды"):
   - Дай подробный, полезный и мотивирующий ответ, основанный на профиле пользователя (если доступен).
   - Если вопрос связан с питанием или тренировками, предложи конкретные рекомендации (например, блюда, упражнения), учитывая цель, активность, диету и здоровье.
   - Добавь мотивацию или интересный факт, связанный с фитнесом/питанием.
   - Формат: TEXT: ...

2. Если пользователь упоминает новые данные (например, "мой вес 70 кг", "я теперь веган", "у меня есть штанга"):
   - Определи, к какой колонке профиля относится информация.
   - Сгенерируй SQL-запрос для обновления только этой колонки.
   - Подтверди у пользователя, хочет ли он обновить профиль, предложив конкретное изменение.
   - Формат: 
     SQL: <SQL-запрос>
     TEXT: <Ответ с подтверждением, например, "Ты сказал, что твой вес теперь 70 кг. Обновить профиль?">

3. Если пользователь отправил изображение, а затем говорит "добавь это в мой инвентарь":
   - Используй описание объекта с изображения (например, "гантели 10 кг") для обновления поля equipment.
   - Подтверди обновление у пользователя.

4. Дополнительно:
   - Если есть данные о весе и росте, рассчитай ИМТ и добавь его в ответ, если это уместно.
   - Если пользователь новичок, дай более простые советы; для продвинутых — более сложные и специфичные.
   - Всегда старайся быть мотивирующим, добавляй эмодзи и лёгкий юмор, но не переборщи.
   - Если данные неясны, задай уточняющий вопрос вместо предположений.

⚠️ Обновляй профиль только после явного подтверждения пользователем или чёткого указания на изменение (например, "мой вес теперь...").

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

        # Разделим SQL и TEXT
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
                await message.reply_text(f"Ой, не удалось обновить профиль 😕 Ошибка: {e}. Напиши ещё раз, я разберусь! 😊")
                return

        if text_match:
            reply_text = text_match.group(1).strip()
            await message.reply_text(reply_text)
        else:
            await message.reply_text(response_text)

    except Exception as e:
        await message.reply_text(f"Упс, что-то пошло не так 😅 Ошибка: {e}. Давай попробуем ещё раз? Напиши свой вопрос или отправь фото!")

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
