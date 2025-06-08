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
    ASK_LANGUAGE, ASK_NAME, ASK_GENDER, ASK_AGE, ASK_WEIGHT, ASK_HEIGHT,
    ASK_GOAL, ASK_ACTIVITY, ASK_DIET_PREF, ASK_HEALTH, ASK_EQUIPMENT, ASK_TARGET
) = range(12)

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
        unique_facts TEXT
    )
    ''')
    conn.commit()
    conn.close()

def save_user_profile(user_id: int, profile: dict):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR REPLACE INTO user_profiles
    (user_id, language, name, gender, age, weight, height, goal, activity, diet, health, equipment, target_metric, unique_facts)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        "Привет! Я твой персональный фитнес-ассистент NutriBot. Пожалуйста, выбери язык общения:\n"
        "🇷🇺 Русский - нажми /ru\n"
        "🇬🇧 English - press /en\n\n"
        "Hello! I'm your personal fitness assistant NutriBot. Please choose your preferred language:\n"
        "🇷🇺 Russian - press /ru\n"
        "🇬🇧 English - press /en"
    )
    return ASK_LANGUAGE

async def ask_language(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language_choice = update.message.text.lower().strip()
    
    if language_choice not in ["/ru", "/en"]:
        await update.message.reply_text(
            "Пожалуйста, выберите язык командой:\n"
            "/ru - для русского\n"
            "/en - для английского\n\n"
            "Please select language with command:\n"
            "/ru - for Russian\n"
            "/en - for English"
        )
        return ASK_LANGUAGE
    
    if language_choice == "/ru":
        user_profiles[user_id] = {"language": "Russian"}
        await update.message.reply_text("Отлично! Давай начнем с короткой анкеты 🙌\n\nКак тебя зовут?")
    else:
        user_profiles[user_id] = {"language": "English"}
        await update.message.reply_text("Great! Let's start with a short questionnaire 🙌\n\nWhat's your name?")
    
    return ASK_NAME

async def ask_gender(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["name"] = update.message.text
    
    if user_profiles[user_id]["language"] == "English":
        await update.message.reply_text("What's your gender? (m/f)")
    else:
        await update.message.reply_text("Укажи свой пол (м/ж):")
    
    return ASK_GENDER

async def ask_age(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    gender = update.message.text.lower()
    language = user_profiles[user_id]["language"]
    
    if language == "English":
        if gender not in ["m", "f"]:
            await update.message.reply_text("Please specify only 'm' or 'f'.")
            return ASK_GENDER
    else:
        if gender not in ["м", "ж"]:
            await update.message.reply_text("Пожалуйста, укажи только 'м' или 'ж'.")
            return ASK_GENDER
    
    user_profiles[user_id]["gender"] = gender
    
    if language == "English":
        await update.message.reply_text("How old are you?")
    else:
        await update.message.reply_text("Сколько тебе лет?")
    
    return ASK_AGE

async def ask_weight(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id]["language"]
    
    try:
        age = int(update.message.text)
    except ValueError:
        if language == "English":
            await update.message.reply_text("Please enter your age as a number.")
        else:
            await update.message.reply_text("Пожалуйста, укажи возраст числом.")
        return ASK_AGE
    
    user_profiles[user_id]["age"] = age
    
    if language == "English":
        await update.message.reply_text("What's your current weight (in kg)?")
    else:
        await update.message.reply_text("Какой у тебя текущий вес (в кг)?")
    
    return ASK_WEIGHT

async def ask_height(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id]["language"]
    
    try:
        weight = float(update.message.text.replace(",", "."))
    except ValueError:
        if language == "English":
            await update.message.reply_text("Please enter your weight as a number.")
        else:
            await update.message.reply_text("Пожалуйста, укажи вес числом.")
        return ASK_WEIGHT
    
    user_profiles[user_id]["weight"] = weight
    
    if language == "English":
        await update.message.reply_text("What's your height (in cm)?")
    else:
        await update.message.reply_text("Какой у тебя рост (в см)?")
    
    return ASK_HEIGHT

async def ask_goal(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id]["language"]
    
    try:
        height = int(update.message.text)
        if height < 100 or height > 250:
            if language == "English":
                await update.message.reply_text("Please enter a realistic height (100-250 cm).")
            else:
                await update.message.reply_text("Пожалуйста, укажи реальный рост (от 100 до 250 см).")
            return ASK_HEIGHT
    except ValueError:
        if language == "English":
            await update.message.reply_text("Please enter your height as a whole number in centimeters.")
        else:
            await update.message.reply_text("Пожалуйста, укажи рост целым числом в сантиметрах.")
        return ASK_HEIGHT
    
    user_profiles[user_id]["height"] = height
    
    if language == "English":
        await update.message.reply_text("What's your goal? (Lose weight, Gain mass, Get toned, Just healthy lifestyle)")
    else:
        await update.message.reply_text("Какая у тебя цель? (Похудеть, Набрать массу, Рельеф, Просто ЗОЖ)")
    
    return ASK_GOAL

async def ask_activity(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id]["language"]
    user_profiles[user_id]["goal"] = update.message.text
    
    if language == "English":
        await update.message.reply_text("What's your activity/experience level? (Beginner, Intermediate, Advanced)")
    else:
        await update.message.reply_text("Какой у тебя уровень активности/опыта? (Новичок, Средний, Продвинутый)")
    
    return ASK_ACTIVITY

async def ask_diet_pref(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id]["language"]
    user_profiles[user_id]["activity"] = update.message.text
    
    if language == "English":
        await update.message.reply_text("Do you have any dietary preferences? (Vegan, gluten-free, etc.)")
    else:
        await update.message.reply_text("Есть ли у тебя предпочтения в еде? (Веганство, без глютена и т.п.)")
    
    return ASK_DIET_PREF

async def ask_health(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id]["language"]
    user_profiles[user_id]["diet"] = update.message.text
    
    if language == "English":
        await update.message.reply_text("Do you have any health restrictions?")
    else:
        await update.message.reply_text("Есть ли у тебя ограничения по здоровью?")
    
    return ASK_HEALTH

async def ask_equipment(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id]["language"]
    user_profiles[user_id]["health"] = update.message.text
    
    if language == "English":
        await update.message.reply_text("What equipment do you have available?")
    else:
        await update.message.reply_text("Какой инвентарь/тренажёры у тебя есть?")
    
    return ASK_EQUIPMENT

async def ask_target(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    language = user_profiles[user_id]["language"]
    user_profiles[user_id]["equipment"] = update.message.text
    
    if language == "English":
        await update.message.reply_text("What's your specific weight or other metric goal?")
    else:
        await update.message.reply_text("Какая у тебя конкретная цель по весу или другим метрикам?")
    
    return ASK_TARGET

async def finish_questionnaire(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_profiles[user_id]["target_metric"] = update.message.text
    name = user_profiles[user_id]["name"]
    language = user_profiles[user_id]["language"]
    
    save_user_profile(user_id, user_profiles[user_id])
    
    if language == "English":
        await update.message.reply_text(f"Great, {name}! Questionnaire completed 🎉 You can send me photos, text or documents - I'll help you with analysis and recommendations!")
    else:
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
        await update.message.reply_text("Profile not found. Complete the questionnaire with /start.")
        return
    
    language = row[1] if row[1] else "Russian"
    
    if language == "English":
        profile_text = (
            f"Your profile:\n\n"
            f"Language: {row[1]}\nName: {row[2]}\nGender: {row[3]}\nAge: {row[4]}\n"
            f"Weight: {row[5]} kg\nHeight: {row[6]} cm\n"
            f"Goal: {row[7]}\nActivity: {row[8]}\nDiet: {row[9]}\n"
            f"Health: {row[10]}\nEquipment: {row[11]}\nTarget metric: {row[12]}\n"
            f"Unique facts: {row[13]}"
        )
    else:
        profile_text = (
            f"Твой профиль:\n\n"
            f"Язык: {row[1]}\nИмя: {row[2]}\nПол: {row[3]}\nВозраст: {row[4]}\n"
            f"Вес: {row[5]} кг\nРост: {row[6]} см\n"
            f"Цель: {row[7]}\nАктивность: {row[8]}\nПитание: {row[9]}\n"
            f"Здоровье: {row[10]}\nИнвентарь: {row[11]}\nЦелевая метрика: {row[12]}\n"
            f"Уникальные факты: {row[13]}"
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
        await update.message.reply_text("All data has been successfully reset! Let's start fresh 🧼")
    except Exception as e:
        await update.message.reply_text(f"An error occurred while resetting data: {e}")

async def generate_image(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Image generation is currently unavailable.")


def get_user_profile_text(user_id: int) -> str:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return "User profile not found."

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
        f"Unique facts: {row[13]}"
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
            await message.reply_text(f"Error loading file: {str(e)}")
            return

    if user_text:
        contents.insert(0, {"text": user_text})
    if not contents:
        await message.reply_text("Please send text, image or document.")
        return

    # Профиль пользователя
    profile_info = get_user_profile_text(user_id)
    if profile_info and "not found" not in profile_info:
        contents.insert(0, {"text": f"User information:\n{profile_info}"})

    # История - увеличиваем размер очереди до 10 сообщений
    if user_id not in user_histories:
        user_histories[user_id] = deque(maxlen=10)
    user_histories[user_id].append(f"User: {user_text}")
    
    # Добавляем предыдущие ответы бота в историю
    if 'last_bot_reply' in context.user_data:
        user_histories[user_id].append(f"Bot: {context.user_data['last_bot_reply']}")
    
    history_messages = list(user_histories[user_id])
    if history_messages:
        history_prompt = "\n".join(history_messages)
        contents.insert(0, {"text": f"Current dialog context (recent messages):\n{history_prompt}"})

    # Системный промпт (изменена только часть про анализ фото)
    GEMINI_SYSTEM_PROMPT = """You are a smart assistant that helps the user and updates their profile in the database when necessary.

You receive messages from the user. They can be:
- just questions (e.g., about nutrition, workouts, photos, etc.)
- data updates (e.g., "I gained 3 kg" or "I'm now 20 years old")
- messages after images (e.g., "add this to equipment")
- unique facts about the user (e.g., "I like swimming", "I had a knee injury", "I've been vegetarian for 5 years", "I like coffee in the evenings")

The database has a user_profiles table with columns:
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

Your task:

1. Always first analyze the information from the user's profile (especially diet, health, activity, unique_facts fields) and strictly consider it in your responses.

2. If the message contains a clear profile data change (e.g.: weight, age, goals, equipment, etc.) — generate:
    SQL: <SQL query>
    TEXT: <response to the person in natural language>

3. If it's just a question (e.g.: "what to eat after workout?" or "what's in the photo?") — give a useful, concise but informative answer, MANDATORILY considering known facts about the user:
    TEXT: ...

4. If the user sent an image — analyze ONLY what is really visible in the photo, without assumptions. If unsure about details — ask for clarification. 
   If the user corrects you (e.g.: "there were 2 eggs in the photo, not 3") — IMMEDIATELY consider this in the next response and apologize for the mistake.

5. If the message contains unique facts about the user (hobbies, health features, preferences, injuries, etc.) that don't fit into standard profile fields but are important for personalization:
   - If the fact relates to health — add it to the health field
   - If the fact relates to nutrition — add it to the diet field
   - If the fact relates to equipment — add it to the equipment field
   - If the fact relates to activity/sports — add it to the activity field
   - If the fact doesn't fit any of these categories — add it to the unique_facts field
   Format for adding: "Fact: [fact description]."

   Examples:
   - "I like coffee in the evenings" → added to diet: "Fact: Likes coffee in the evenings."
   - "I have back pain" → added to health: "Fact: Back pain."
   - "I like swimming" → added to activity: "Fact: Likes swimming."
   - "I work as a programmer" → added to unique_facts: "Fact: Works as a programmer."
   - "I have a dog" → added to unique_facts: "Fact: Has a dog."

6. ⚠️ If the user sent a food photo and explicitly indicated it's their food — analyze the food in the photo and respond in the format:

TEXT:
🔍 Food analysis:
(Describe ONLY what is really visible in the photo)

🍽 Approximate nutrition:
(Based on visible ingredients)

✅ Benefits and composition:
(Describe the benefits of visible elements)

🧠 Bot's opinion:
(Considering known user preferences)

💡 Advice:
(If there's room for improvement, considering the profile)

7. If the user corrects you in photo analysis (e.g.: "there were 2 eggs, not 3"):
- Apologize for the mistake
- Immediately revise your analysis with the new information
- Give an updated response considering the user's clarification

8. If the user mentions you didn't consider their preferences:
- Apologize
- Explain why this option might be useful
- Suggest adapting it to known preferences

9. If the user sends a message that:
- contains only the symbol ".",
- makes no sense,
- consists of random characters,
- is a phrase fragment without context,
- contains only interjections, slang, emotional outbursts, etc.,
then politely ask for clarification.

10. The response should be natural, friendly and concise, as if you are a caring but professional nutritionist.

⚠️ Never invent details that aren't in the profile or photo. If unsure — ask or say you don't know.

⚠️ Always strictly consider known facts about the user from their profile AND the current dialog context.

⚠️ Respond to the user in the same language they use to address you.

⚠️ The total response length should never exceed 4096 characters.

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
                await message.reply_text(f"Error updating profile: {e}")
                return

        if text_match:
            reply_text = text_match.group(1).strip()
            await message.reply_text(reply_text)
        else:
            # Если текстового ответа не найдено — просто верни всё как есть
            await message.reply_text(response_text)

    except Exception as e:
        await message.reply_text(f"Error generating response: {e}")


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_language)],
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
