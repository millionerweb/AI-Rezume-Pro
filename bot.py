import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Токены и ключи из переменных окружения
TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Инициализация Groq
client = Groq(api_key=GROQ_API_KEY)

# Системный промпт для ИИ-продавца
SYSTEM_PROMPT = """
Ты — дружелюбный ИИ-консультант в Telegram-магазине по продаже резюме и сопроводительных писем.

Твоя задача: помогать клиентам выбирать товары, отвечать на вопросы и принимать заказы.

Товары:
1. "Готовое резюме" — 500 рублей (базовый шаблон)
2. "Индивидуальное резюме" — 1500 рублей (составляем под конкретную вакансию)
3. "Сопроводительное письмо" — 800 рублей (индивидуальное)
4. "Пакет 'Успешный старт'" — 2000 рублей (резюме + сопроводительное письмо + советы)

Правила общения:
- Будь вежливым и приветливым
- Отвечай на русском языке
- Если спрашивают про цены — называй сразу
- Если клиент готов купить — попроси написать: название товара, имя и email
- После заказа поблагодари и скажи, что с клиентом свяжутся

Будь полезным и помогай клиентам сделать правильный выбор!
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "👋 Привет! Я ИИ-помощник магазина резюме.\n\n"
        "Я помогу выбрать резюме или сопроводительное письмо. Просто напиши мне, что тебя интересует!"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_message = update.message.text
    user_name = update.message.from_user.first_name
    
    try:
        # Отправляем запрос к Groq
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Имя клиента: {user_name}\nСообщение: {user_message}"}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=500
        )
        
        reply = chat_completion.choices[0].message.content
        await update.message.reply_text(reply)
        
    except Exception as e:
        logger.error(f"Ошибка при обращении к Groq: {e}")
        await update.message.reply_text(
            "Извините, временные проблемы с подключением. Попробуйте позже или напишите 'цены' для получения информации о товарах."
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = """
Доступные команды:
/start - Начать работу
/help - Показать эту справку
/prices - Посмотреть цены
/contacts - Контакты
    """
    await update.message.reply_text(help_text)

async def prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /prices"""
    prices_text = """
💰 **Наши цены:**

• Готовое резюме — 500 ₽
• Индивидуальное резюме — 1500 ₽  
• Сопроводительное письмо — 800 ₽
• Пакет "Успешный старт" — 2000 ₽ (резюме + письмо + советы)

Для заказа напишите мне, что хотите, и укажите ваше имя и email!
    """
    await update.message.reply_text(prices_text, parse_mode='Markdown')

async def contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /contacts"""
    await update.message.reply_text(
        "📧 По вопросам заказов: shop@example.com\n"
        "📱 Поддержка: @support_username"
    )

async def run_bot():
    """Запуск бота с правильным event loop"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("prices", prices))
    application.add_handler(CommandHandler("contacts", contacts))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    logger.info("Бот запущен и готов к работе!")
    
    # Держим бота запущенным
    while True:
        await asyncio.sleep(3600)

def main():
    """Запуск бота"""
    if not TELEGRAM_TOKEN:
        logger.error("Не задан BOT_TOKEN")
        return
    if not GROQ_API_KEY:
        logger.error("Не задан GROQ_API_KEY")
        return
    
    # Запускаем асинхронную функцию
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
