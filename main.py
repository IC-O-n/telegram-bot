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
        target_metric TEXT,
        custom_facts TEXT
    )
    ''')
    conn.commit()
    conn.close()
    migrate_db()

def save_user_profile(user_id: int, profile: dict):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    # Получаем текущие custom_facts
    cursor.execute("SELECT custom_facts FROM user_profiles WHERE user_id = ?", (user_id,))
    existing_facts = cursor.fetchone()
    current_facts = existing_facts[0] if existing_facts and existing_facts[0] else ""
    
    # Объединяем с новыми фактами, если они есть
    new_facts = profile.get("custom_facts", "")
    if new_facts and current_facts:
        combined_facts = f"{current_facts}\n{new_facts}"
    elif new_facts:
        combined_facts = new_facts
    else:
        combined_facts = current_facts
    
    cursor.execute('''
    INSERT OR REPLACE INTO user_profiles
    (user_id, name, gender, age, weight, goal, activity, diet, health, equipment, target_metric, custom_facts)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        combined_facts
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

async def validate_response(prompt: str, user_response: str, current_state: int) -> tuple:
    """Валидация ответа пользователя с помощью Gemini"""
    validation_prompts = {
        ASK_NAME: "Пользователь должен ввести своё имя. Это строка, которая выглядит как человеческое имя. Ответь только 'VALID' если это имя, или 'INVALID' если это не имя.",
        ASK_GENDER: "Пользователь должен указать свой пол. Допустимые ответы: 'м' или 'ж'. Ответь только 'VALID' если ответ корректный, или 'INVALID' если нет.",
        ASK_AGE: "Пользователь должен указать свой возраст числом от 10 до 120. Ответь только 'VALID' если это число в этом диапазоне, или 'INVALID' если нет.",
        ASK_WEIGHT: "Пользователь должен указать свой вес в кг (число от 20 до 300). Ответь только 'VALID' если это число в этом диапазоне, или 'INVALID' если нет.",
        ASK_GOAL: "Пользователь должен указать свою цель: 'Похудеть', 'Набрать массу', 'Рельеф' или 'Просто ЗОЖ'. Ответь только 'VALID' если ответ корректный, или 'INVALID' если нет.",
        ASK_ACTIVITY: "Пользователь должен указать уровень активности: 'Новичок', 'Средний' или 'Продвинутый'. Ответь только 'VALID' если ответ корректный, или 'INVALID' если нет.",
        ASK_DIET_PREF: "Пользователь должен указать свои предпочтения в еде. Любой текст считается валидным, если он не пустой. Ответь только 'VALID' если текст не пустой, или 'INVALID' если пустой.",
        ASK_HEALTH: "Пользователь должен указать свои ограничения по здоровью. Любой текст считается валидным, если он не пустой. Ответь только 'VALID' если текст не пустой, или 'INVALID' если пустой.",
        ASK_EQUIPMENT: "Пользователь должен указать свой инвентарь. Любой текст считается валидным, если он не пустой. Ответь только 'VALID' если текст не пустой, или 'INVALID' если пустой.",
        ASK_TARGET: "Пользователь должен указать свою целевую метрику. Любой текст считается валидным, если он не пустой. Ответь только 'VALID' если текст не пустой, или 'INVALID' если пустой.",
    }
    
    response = model.generate_content([
        {"text": validation_prompts[current_state]},
        {"text": f"Пользователь ответил: {user_response}"}
    ])
    
    return "VALID" in response.text

async def check_profile_update(message: str) -> tuple:
    """Проверяет, хочет ли пользователь обновить профиль"""
    response = model.generate_content([
        {"text": """Проанализируй сообщение пользователя. Если он явно хочет обновить какие-то данные в своём профиле (например, имя, возраст, вес и т.д.), ответь в формате:
FIELD: <поле для обновления>
VALUE: <новое значение>
Если это не обновление профиля, ответь 'NO'"""},
        {"text": message}
    ])
    
    if "FIELD:" in response.text and "VALUE:" in response.text:
        field = response.text.split("FIELD:")[1].split("VALUE:")[0].strip()
        value = response.text.split("VALUE:")[1].strip()
        return (field, value)
    return None

async def check_custom_fact(message: str) -> str:
    """Проверяет, содержит ли сообщение уникальный факт о пользователе"""
    response = model.generate_content([
        {"text": """Определи, содержит ли это сообщение уникальный факт о пользователе, который стоит сохранить (например, "у меня нет ноги", "я люблю смотреть фильмы по вечерам"). 
Если содержит - верни этот факт. Если нет - верни 'NO'."""},
        {"text": message}
    ])
    
    return response.text if response.text != "NO" else None

async def start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Привет! Я твой персональный фитнес-ассистент NutriBot. Давай начнем с короткой анкеты 🙌\n\nКак тебя зовут?")
    return ASK_NAME


def migrate_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    # Проверяем существование столбца custom_facts
    cursor.execute("PRAGMA table_info(user_profiles)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if "custom_facts" not in columns:
        try:
            cursor.execute("ALTER TABLE user_profiles ADD COLUMN custom_facts TEXT")
            conn.commit()
            print("База данных успешно мигрирована: добавлен столбец custom_facts")
        except Exception as e:
            print(f"Ошибка при миграции базы данных: {e}")
    
    conn.close()


async def handle_questionnaire(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_response = update.message.text
    current_state = context.user_data.get("current_state", ASK_NAME)
    
    try:
        # Проверяем, не хочет ли пользователь обновить предыдущие данные
        profile_update = await check_profile_update(user_response)
        if profile_update:
            field, value = profile_update
            if user_id not in user_profiles:
                user_profiles[user_id] = {}
            user_profiles[user_id][field] = value
            save_user_profile(user_id, {field: value})
            await update.message.reply_text(f"Обновил {field} на '{value}'! Продолжим анкету.")
            return current_state

        # Проверяем на уникальные факты
        custom_fact = await check_custom_fact(user_response)
        if custom_fact:
            try:
                save_user_profile(user_id, {"custom_facts": custom_fact})
                await update.message.reply_text("Запомнил эту информацию о тебе! Продолжим анкету.")
                return current_state
            except Exception as e:
                await update.message.reply_text("Произошла ошибка при сохранении данных. Попробуй еще раз.")
                return current_state

        # Валидация ответа
        is_valid = await validate_response(user_response, user_response, current_state)
        
        if not is_valid:
            error_messages = {
                ASK_NAME: "Это не похоже на имя. Пожалуйста, введи своё настоящее имя.",
                ASK_GENDER: "Пожалуйста, укажи только 'м' или 'ж'.",
                ASK_AGE: "Пожалуйста, укажи возраст числом от 10 до 120.",
                ASK_WEIGHT: "Пожалуйста, укажи вес числом от 20 до 300 кг.",
                ASK_GOAL: "Пожалуйста, выбери одну из целей: 'Похудеть', 'Набрать массу', 'Рельеф' или 'Просто ЗОЖ'.",
                ASK_ACTIVITY: "Пожалуйста, выбери уровень: 'Новичок', 'Средний' или 'Продвинутый'.",
                ASK_DIET_PREF: "Пожалуйста, укажи свои предпочтения в еде.",
                ASK_HEALTH: "Пожалуйста, укажи свои ограничения по здоровью.",
                ASK_EQUIPMENT: "Пожалуйста, укажи свой инвентарь.",
                ASK_TARGET: "Пожалуйста, укажи свою целевую метрику.",
            }
            await update.message.reply_text(error_messages[current_state])
            
            # Повторно задаем вопрос
            question_messages = {
                ASK_NAME: "Как тебя зовут?",
                ASK_GENDER: "Укажи свой пол (м/ж):",
                ASK_AGE: "Сколько тебе лет?",
                ASK_WEIGHT: "Какой у тебя текущий вес (в кг)?",
                ASK_GOAL: "Какая у тебя цель? (Похудеть, Набрать массу, Рельеф, Просто ЗОЖ)",
                ASK_ACTIVITY: "Какой у тебя уровень активности/опыта? (Новичок, Средний, Продвинутый)",
                ASK_DIET_PREF: "Есть ли у тебя предпочтения в еде? (Веганство, без глютена и т.п.)",
                ASK_HEALTH: "Есть ли у тебя ограничения по здоровью?",
                ASK_EQUIPMENT: "Какой инвентарь/тренажёры у тебя есть?",
                ASK_TARGET: "Какая у тебя конкретная цель по весу или другим метрикам?",
            }
            await update.message.reply_text(question_messages[current_state])
            return current_state

        # Если ответ валиден, сохраняем и переходим к следующему вопросу
        if user_id not in user_profiles:
            user_profiles[user_id] = {}
        
        field_names = {
            ASK_NAME: "name",
            ASK_GENDER: "gender",
            ASK_AGE: "age",
            ASK_WEIGHT: "weight",
            ASK_GOAL: "goal",
            ASK_ACTIVITY: "activity",
            ASK_DIET_PREF: "diet",
            ASK_HEALTH: "health",
            ASK_EQUIPMENT: "equipment",
            ASK_TARGET: "target_metric",
        }

        field_name = field_names[current_state]
        user_profiles[user_id][field_name] = user_response.lower() if current_state == ASK_GENDER else user_response

        # Переход к следующему вопросу или завершение анкеты
        next_questions = {
            ASK_NAME: ("Укажи свой пол (м/ж):", ASK_GENDER),
            ASK_GENDER: ("Сколько тебе лет?", ASK_AGE),
            ASK_AGE: ("Какой у тебя текущий вес (в кг)?", ASK_WEIGHT),
            ASK_WEIGHT: ("Какая у тебя цель? (Похудеть, Набрать массу, Рельеф, Просто ЗОЖ)", ASK_GOAL),
            ASK_GOAL: ("Какой у тебя уровень активности/опыта? (Новичок, Средний, Продвинутый)", ASK_ACTIVITY),
            ASK_ACTIVITY: ("Есть ли у тебя предпочтения в еде? (Веганство, без глютена и т.п.)", ASK_DIET_PREF),
            ASK_DIET_PREF: ("Есть ли у тебя ограничения по здоровью?", ASK_HEALTH),
            ASK_HEALTH: ("Какой инвентарь/тренажёры у тебя есть?", ASK_EQUIPMENT),
            ASK_EQUIPMENT: ("Какая у тебя конкретная цель по весу или другим метрикам?", ASK_TARGET),
            ASK_TARGET: ("", None),  # Конец анкеты
        }

        next_question, next_state = next_questions[current_state]

        if next_state is None:
            # Завершение анкеты
            save_user_profile(user_id, user_profiles[user_id])
            name = user_profiles[user_id]["name"]
            await update.message.reply_text(f"Отлично, {name}! Анкета завершена 🎉 Ты можешь отправлять мне фото, текст или документы — я помогу тебе с анализом и рекомендациями!")
            return ConversationHandler.END
        else:
            await update.message.reply_text(next_question)
            context.user_data["current_state"] = next_state
            return next_state

    except Exception as e:
        print(f"Ошибка в handle_questionnaire: {e}")
        await update.message.reply_text("Произошла непредвиденная ошибка. Давай попробуем еще раз.")
        return current_state


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
        f"Здоровье: {row[8]}\nИнвентарь: {row[9]}\nЦелевая метрика: {row[10]}\n"
        f"\nДополнительные факты:\n{row[11] if row[11] else 'Нет дополнительной информации'}"
    )
    await update.message.reply_text(profile_text)

async def reset(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_histories.pop(user_id, None)
    user_profiles.pop(user_id, None)
    await update.message.reply_text("Контекст сброшен! Начнем с чистого листа 🧼")

async def generate_image(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Генерация изображений пока недоступна. Ждём обновления API Gemini �")

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
        f"Целевая метрика: {row[10]}\n"
        f"Дополнительные факты: {row[11] if row[11] else 'Нет'}"
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
    GEMINI_SYSTEM_PROMPT = """Ты — умный ассистент, который помогает пользователю и при необходимости обновляет его профиль в базе данных.

Ты получаешь от пользователя сообщения. Они могут быть:
- просто вопросами (например, о питании, тренировках, фото и т.д.)
- обновлениями данных (например, "я набрал 3 кг" или "мне теперь 20 лет")
- сообщениями после изображения (например, "добавь это в инвентарь")

В базе данных есть таблица user_profiles с колонками:
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
- custom_facts TEXT

Твоя задача:

1. Если в сообщении есть чёткое изменение данных профиля (например: вес, возраст, цели, оборудование и т.п.) — сгенерируй:
    SQL: <SQL-запрос>
    TEXT: <ответ человеку на естественном языке>

2. Если это просто вопрос (например: "что поесть после тренировки?" или "что на фото?") — не создавай SQL. Просто дай полезный, краткий, но информативный ответ в блоке:
    TEXT: ...

3. Если пользователь отправил изображение, а затем говорит "добавь это в мой инвентарь" — используй описание объекта с последнего изображения (например, "горный велосипед Stern"), а не слово "изображение".

4. Если сообщение содержит уникальный факт о пользователе (например, "у меня нет ноги", "я люблю смотреть фильмы по вечерам"), добавь его в custom_facts.

5. Ответ должен быть достаточно кратким, но не чрезмерно коротким. Старайся сделать его информативным и естественным для человека.

⚠️ Никогда не обновляй профиль без явного указания на это (например: "измени", "добавь", "мой вес теперь..." и т.п.)

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
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire)],
            ASK_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire)],
            ASK_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire)],
            ASK_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire)],
            ASK_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire)],
            ASK_ACTIVITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire)],
            ASK_DIET_PREF: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire)],
            ASK_HEALTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire)],
            ASK_EQUIPMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire)],
            ASK_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire)],
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
