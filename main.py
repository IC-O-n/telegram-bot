import os
import re
import sqlite3
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    ConversationHandler,
)
import google.generativeai as genai

# Конфигурация
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-pro")

# Состояния анкеты
QUESTIONNAIRE_STATES = range(10)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id INTEGER PRIMARY KEY,
        name TEXT DEFAULT NULL,
        gender TEXT DEFAULT NULL,
        age INTEGER DEFAULT NULL,
        weight REAL DEFAULT NULL,
        goal TEXT DEFAULT NULL,
        activity TEXT DEFAULT NULL,
        diet TEXT DEFAULT NULL,
        health TEXT DEFAULT NULL,
        equipment TEXT DEFAULT NULL,
        target_metric TEXT DEFAULT NULL
    )
    """)
    conn.commit()
    conn.close()

def get_user_profile(user_id: int) -> dict:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))
    columns = [column[0] for column in cursor.description]
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(zip(columns, row))
    return None

def update_user_profile(user_id: int, updates: dict):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    # Получаем текущий профиль
    profile = get_user_profile(user_id) or {}
    
    # Обновляем только указанные поля
    for key, value in updates.items():
        profile[key] = value
    
    # Сохраняем обновленный профиль
    cursor.execute("""
    INSERT OR REPLACE INTO user_profiles 
    (user_id, name, gender, age, weight, goal, activity, diet, health, equipment, target_metric)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
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
    user_id = update.message.from_user.id
    
    # Инициализируем профиль пользователя
    update_user_profile(user_id, {
        "name": None,
        "gender": None,
        "age": None,
        "weight": None,
        "goal": None,
        "activity": None,
        "diet": None,
        "health": None,
        "equipment": None,
        "target_metric": None
    })
    
    await update.message.reply_text(
        "Привет! Я твой персональный фитнес-ассистент NutriBot. "
        "Давай начнем с короткой анкеты.\n\nКак тебя зовут?"
    )
    return 0  # Первое состояние - запрос имени

async def handle_questionnaire_response(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    user_response = update.message.text
    current_state = context.user_data.get("question_state", 0)
    
    # Получаем текущий профиль пользователя
    profile = get_user_profile(user_id)
    
    # Формируем запрос к Gemini
    prompt = f"""
    Ты помогаешь заполнить анкету для фитнес-бота. Текущие данные пользователя:
    {profile}
    
    Пользователь прислал ответ: "{user_response}"
    
    Определи:
    1. Какое поле анкеты нужно обновить (name, gender, age, weight, goal, activity, diet, health, equipment, target_metric)
    2. Корректность ответа
    3. Новое значение для поля
    
    Верни ответ в формате JSON:
    {{
        "field": "название_поля",
        "valid": true/false,
        "value": "новое_значение",
        "message": "сообщение_пользователю"
    }}
    """
    
    try:
        # Получаем ответ от Gemini
        response = model.generate_content(prompt)
        response_text = response.text
        
        # Парсим JSON ответ (может потребоваться дополнительная обработка)
        import json
        try:
            data = json.loads(response_text.strip("```json\n").strip("```"))
        except:
            # Если не удалось распарсить JSON, попробуем извлечь его из текста
            try:
                json_str = re.search(r'\{.*\}', response_text, re.DOTALL).group()
                data = json.loads(json_str)
            except:
                data = {
                    "field": None,
                    "valid": False,
                    "value": None,
                    "message": "Не удалось обработать ответ. Попробуйте еще раз."
                }
        
        if not data.get("valid", False):
            await update.message.reply_text(data.get("message", "Некорректный ответ. Попробуйте еще раз."))
            return current_state
        
        # Обновляем профиль
        update_user_profile(user_id, {data["field"]: data["value"]})
        
        # Отправляем сообщение пользователю
        if data.get("message"):
            await update.message.reply_text(data["message"])
        
        # Определяем следующий вопрос
        next_question = get_next_question(data["field"])
        if next_question:
            await update.message.reply_text(next_question)
            context.user_data["question_state"] = current_state + 1
            return current_state + 1
        else:
            # Анкета завершена
            await update.message.reply_text(
                "Спасибо! Анкета заполнена. Теперь я могу давать персонализированные рекомендации."
            )
            return ConversationHandler.END
            
    except Exception as e:
        print(f"Ошибка при обработке ответа: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте еще раз.")
        return current_state

def get_next_question(current_field: str) -> str:
    questions_flow = {
        "name": "Укажите ваш пол (м/ж):",
        "gender": "Сколько вам лет?",
        "age": "Ваш текущий вес (кг)?",
        "weight": "Ваша цель (похудеть, набрать массу, рельеф, поддержание)?",
        "goal": "Уровень активности (новичок, средний, продвинутый)?",
        "activity": "Предпочтения в питании?",
        "diet": "Ограничения по здоровью?",
        "health": "Какой инвентарь у вас есть?",
        "equipment": "Конкретная цель по весу/метрикам?",
        "target_metric": None  # Конец анкеты
    }
    return questions_flow.get(current_field)

async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Анкета прервана. Вы всегда можете начать заново с /start")
    return ConversationHandler.END

def main():
    init_db()
    
    app = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            0: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire_response)],
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire_response)],
            2: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire_response)],
            3: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire_response)],
            4: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire_response)],
            5: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire_response)],
            6: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire_response)],
            7: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire_response)],
            8: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire_response)],
            9: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_questionnaire_response)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
