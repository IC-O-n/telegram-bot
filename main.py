import os
import openai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Получаем токены из переменных окружения
TOKEN = os.getenv("TOKEN")
openai.api_key = os.getenv("OPENAI_API_KEY")

if not TOKEN or not openai.api_key:
    raise ValueError("Отсутствует токен Telegram или OpenAI API.")

async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("Привет! Я бот, который использует OpenAI.")

async def handle_message(update: Update, context: CallbackContext) -> None:
    user_message = update.message.text
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": user_message}]
    )
    reply_text = response["choices"][0]["message"]["content"]
    await update.message.reply_text(reply_text)

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
