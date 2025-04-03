import os
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Получаем токены из переменных окружения
TOKEN = os.getenv("TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TOKEN or not GEMINI_API_KEY:
    raise ValueError("Отсутствует токен Telegram или Google Gemini API.")

# Инициализируем Gemini API
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-pro")

async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Привет! Я бот, который использует Google Gemini API.")

async def handle_message(update: Update, context: CallbackContext) -> None:
    user_message = update.message.text
    
    try:
        response = model.generate_content(user_message)
        reply_text = response.text  # Получаем текст из ответа
    except Exception as e:
        reply_text = f"Ошибка: {str(e)}"

    await update.message.reply_text(reply_text)

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
