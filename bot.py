import os
import time
import re
import logging
import threading
from flask import Flask
import telebot
from groq import Groq
from yoomoney import Client, Quickpay
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime, timedelta

# ===== ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (задаются на Render) =====
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
YOOMONEY_TOKEN = os.environ.get("YOOMONEY_TOKEN")
WALLET = os.environ.get("WALLET")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 0))
PRICE = int(os.environ.get("PRICE", 700))

# Проверка наличия токенов
if not TELEGRAM_TOKEN or not GROQ_API_KEY or not YOOMONEY_TOKEN or not WALLET:
    raise ValueError("Не заданы обязательные переменные окружения")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY)
yoo_client = Client(YOOMONEY_TOKEN)

# Flask для healthcheck (чтобы Render видел, что приложение живо)
app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running", 200

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

user_sessions = {}

STEPS_RESUME = [
    """✨ Итак, начнём!

Я помогу Вам создать *резюме в стиле 2026* (ATS‑дружелюбное).  
В подарок после оплаты — *сопроводительное письмо* и *подготовка к собеседованию*.

📚 А ещё у нас есть блог с карьерными советами — /blog  
🎁 **Гарантия качества:** Если в готовом резюме будут ошибки, вы можете бесплатно перегенерировать его до оплаты (кнопка «Перегенерировать»).

Как это работает:
1. Ответьте на вопросы — я сгенерирую резюме.
2. Если нужно, перегенерируйте резюме кнопкой ниже.
3. Когда результат устроит, оплатите 700₽ и нажмите «Проверить оплату».
4. Получите бонусы бесплатно.

Первый вопрос: Как Вас зовут?""",
    "🎯 Какая у Вас цель? (желаемая должность)\n\n✏️ Если ошиблись или хотите дополнить ответ, напишите /back",
    "💼 Опишите Ваш опыт работы (места, годы, обязанности)\n\n📌 Вы можете перечислить несколько мест в одном сообщении, каждое с новой строки. Чтобы перейти на новую строку, нажмите Shift+Enter.\n\n✏️ Если ошиблись или хотите дополнить ответ, напишите /back (опыт не удалится, вы сможете дописать).\n\n➡️ После завершения опроса вы сможете добавить ещё места через команду /add_experience",
    "⚡ Перечислите ключевые навыки (через запятую)\n\n✏️ Если ошиблись или хотите дополнить ответ, напишите /back",
    "📞 Контактная информация (email, Telegram или телефон)\n\n✏️ Если ошиблись или хотите дополнить ответ, напишите /back"
]

STEPS_COVER = [
    "📝 Создадим сопроводительное письмо. Как Вас зовут?\n\n✏️ Если ошиблись или хотите дополнить ответ, напишите /back",
    "🏢 На какую должность и в какую компанию Вы претендуете?\n\n✏️ Если ошиблись или хотите дополнить ответ, напишите /back",
    "💡 Почему Вы заинтересованы именно в этой роли / компании? (кратко)\n\n✏️ Если ошиблись или хотите дополнить ответ, напишите /back",
    "🔑 Какие ключевые навыки или достижения стоит выделить?\n\n✏️ Если ошиблись или хотите дополнить ответ, напишите /back",
    "📞 Контактная информация (email, Telegram или телефон)\n\n✏️ Если ошиблись или хотите дополнить ответ, напишите /back"
]

def get_pay_link(user_id):
    quickpay = Quickpay(receiver=WALLET, quickpay_form="button", targets="Оплата резюме", paymentType="SB", sum=PRICE, label=str(user_id))
    return quickpay.base_url

def check_payment(user_id):
    try:
        history = yoo_client.operation_history(label=str(user_id))
        cutoff = datetime.now() - timedelta(minutes=30)
        for op in history.operations:
            if op.status == "success":
                op_date = datetime.strptime(op.datetime, "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None)
                if op_date > cutoff:
                    return True
    except Exception as e:
        logger.error(f"Ошибка проверки оплаты: {e}")
    return False

def generate_resume_text(user_data):
    prompt = f"""
    Создай резюме в дружеском современном стиле 2026 на русском языке **от первого лица**.
    Данные: имя {user_data.get('name', '')}, цель {user_data.get('position', '')}, опыт {user_data.get('experience', '')}, навыки {user_data.get('skills', '')}, контакты {user_data.get('contacts', '')}.
    Формат: заголовок, краткое описание, опыт списком (через дефис), навыки списком, контакты. Не используй символы форматирования. Пиши обычный текст.
    """
    try:
        response = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.7)
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка генерации: {e}"

def generate_cover_text(user_data):
    prompt = f"""
    Напиши сопроводительное письмо от первого лица, дружеский стиль. Данные: имя {user_data.get('name', '')}, должность/компания {user_data.get('target', '')}, мотивация {user_data.get('motivation', '')}, навыки {user_data.get('skills', '')}, контакты {user_data.get('contacts', '')}. 
    Не выдумывай, не используй форматирование, объём 150-250 слов.
    """
    try:
        response = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.7)
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка генерации: {e}"

def generate_interview_prep(user_data):
    prompt = f"""
    Составь 10 вопросов и ответов для собеседования на основе данных: имя {user_data.get('name', '')}, цель {user_data.get('position', '')}, опыт {user_data.get('experience', '')}, навыки {user_data.get('skills', '')}. Формат: 1. Вопрос? Ответ: ...
    """
    try:
        response = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], temperature=0.7)
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка генерации: {e}"

def resume_actions_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔄 Перегенерировать", callback_data="regenerate_resume"),
        InlineKeyboardButton("💳 Оплатить 700₽", callback_data="pay_now"),
        InlineKeyboardButton("✅ Проверить оплату", callback_data="check_pay")
    )
    return markup

def bonus_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("/cover"), KeyboardButton("/interview"), KeyboardButton("/edit_resume"), KeyboardButton("/edit_cover"), KeyboardButton("/blog"))
    return markup

# --- ОБРАБОТЧИКИ КОМАНД ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    chat_id = message.chat.id
    user_sessions[chat_id] = {"mode": "resume", "step": 0, "data": {}}
    bot.send_message(chat_id, STEPS_RESUME[0], parse_mode='Markdown')

@bot.message_handler(commands=['add_experience'])
def add_experience(message):
    chat_id = message.chat.id
    session = user_sessions.get(chat_id)
    if session and session.get("mode") == "resume" and not session.get("paid"):
        session["adding_experience"] = True
        bot.send_message(chat_id, "✏️ Введите дополнительное место работы (годы, компания, обязанности). Когда закончите, напишите 'готово'.")
    else:
        bot.send_message(chat_id, "Эта команда доступна только после создания резюме (до оплаты).")

@bot.message_handler(commands=['cover'])
def cover_handler(message):
    chat_id = message.chat.id
    session = user_sessions.get(chat_id)
    if session and session.get("paid"):
        user_sessions[chat_id] = {"mode": "cover", "step": 0, "data": session.get("data", {}), "paid": True}
        bot.send_message(chat_id, STEPS_COVER[0])
    else:
        user_sessions[chat_id] = {"mode": "cover", "step": 0, "data": {}}
        bot.send_message(chat_id, STEPS_COVER[0])

@bot.message_handler(commands=['stats'])
def stats_handler(message):
    if message.chat.id == ADMIN_CHAT_ID:
        bot.send_message(message.chat.id, "Статистика: смотрите логи на Render.")
    else:
        bot.send_message(message.chat.id, "Нет прав.")

@bot.message_handler(commands=['blog'])
def blog_handler(message):
    bot.send_message(message.chat.id, "📚 Подписывайтесь на наш Telegram-канал: https://t.me/resumeprochannel")

@bot.message_handler(commands=['interview'])
def interview_handler(message):
    chat_id = message.chat.id
    session = user_sessions.get(chat_id)
    if session and session.get("paid"):
        bot.send_message(chat_id, "🎓 Готовлю вопросы...")
        interview_text = generate_interview_prep(session["data"])
        bot.send_message(chat_id, interview_text[:4000])
    else:
        bot.send_message(chat_id, "Доступно после оплаты.")

@bot.message_handler(commands=['edit_resume'])
def edit_resume_handler(message):
    chat_id = message.chat.id
    session = user_sessions.get(chat_id)
    if session and session.get("paid"):
        bot.send_message(chat_id, "🔄 Перегенерирую резюме...")
        new_resume = generate_resume_text(session["data"])
        bot.send_message(chat_id, new_resume[:4000])
    else:
        bot.send_message(chat_id, "Доступно после оплаты.")

@bot.message_handler(commands=['edit_cover'])
def edit_cover_handler(message):
    chat_id = message.chat.id
    session = user_sessions.get(chat_id)
    if session and session.get("paid"):
        bot.send_message(chat_id, "🔄 Перегенерирую письмо...")
        new_cover = generate_cover_text(session["data"])
        bot.send_message(chat_id, new_cover[:4000])
    else:
        bot.send_message(chat_id, "Доступно после оплаты.")

@bot.message_handler(commands=['back'])
def back_handler(message):
    chat_id = message.chat.id
    session = user_sessions.get(chat_id)
    if session:
        mode = session.get("mode")
        if mode == "resume":
            step = session.get("step", 0)
            if step > 0:
                if step - 1 not in (2, 3):
                    keys = list(session["data"].keys())
                    if keys:
                        del session["data"][keys[-1]]
                session["step"] = step - 1
                bot.send_message(chat_id, STEPS_RESUME[session["step"]])
            else:
                bot.send_message(chat_id, "Вы уже на первом шаге.")
        elif mode == "cover":
            step = session.get("step", 0)
            if step > 0:
                keys = list(session["data"].keys())
                if keys:
                    del session["data"][keys[-1]]
                session["step"] = step - 1
                bot.send_message(chat_id, STEPS_COVER[session["step"]])
            else:
                bot.send_message(chat_id, "Вы уже на первом шаге.")
    else:
        bot.send_message(chat_id, "Нет активной сессии. Напишите /start или /cover.")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    chat_id = message.chat.id
    text = message.text.strip()
    if chat_id not in user_sessions:
        bot.send_message(chat_id, "Напишите /start или /cover")
        return
    session = user_sessions[chat_id]
    if session.get("adding_experience"):
        if text.lower() == "готово":
            session.pop("adding_experience", None)
            bot.send_message(chat_id, "✅ Опыт дополнен. Обновляю резюме...")
            new_resume = generate_resume_text(session["data"])
            bot.send_message(chat_id, new_resume[:4000])
            bot.send_message(chat_id, "Что дальше?", reply_markup=resume_actions_keyboard())
        else:
            current_exp = session["data"].get("experience", "")
            session["data"]["experience"] = current_exp + "\n" + text if current_exp else text
            bot.send_message(chat_id, "✅ Добавлено. Чтобы закончить, напишите 'готово'.")
        return
    mode = session["mode"]
    step = session["step"]
    data = session["data"]
    if mode == "resume":
        steps = STEPS_RESUME
        if step >= len(steps):
            bot.send_message(chat_id, "Резюме готово. Используйте кнопки или /add_experience для дополнения.")
            return
        if step == 0: data["name"] = text
        elif step == 1: data["position"] = text
        elif step == 2:
            has_years = re.search(r'\d{4}', text)
            if not has_years:
                session["temp_experience"] = text
                bot.send_message(chat_id, "📅 Вы не указали годы. Дополните или отправьте /skip")
                session["waiting_for_years"] = True
                return
            else:
                if "experience" in data and data["experience"]:
                    data["experience"] = data["experience"] + "\n" + text
                else:
                    data["experience"] = text
        elif step == 3: data["skills"] = text
        elif step == 4: data["contacts"] = text
        session["step"] += 1
        if session["step"] < len(steps):
            bot.send_message(chat_id, steps[session["step"]])
        else:
            bot.send_message(chat_id, "✅ Создаю резюме...")
            resume_text = generate_resume_text(data)
            bot.send_message(chat_id, resume_text[:4000])
            bot.send_message(chat_id, "Что дальше?", reply_markup=resume_actions_keyboard())
    elif mode == "cover":
        steps = STEPS_COVER
        if step >= len(steps):
            bot.send_message(chat_id, "Письмо готово.")
            return
        if step == 0: data["name"] = text
        elif step == 1: data["target"] = text
        elif step == 2: data["motivation"] = text
        elif step == 3: data["skills"] = text
        elif step == 4: data["contacts"] = text
        session["step"] += 1
        if session["step"] < len(steps):
            bot.send_message(chat_id, steps[session["step"]])
        else:
            bot.send_message(chat_id, "✅ Создаю письмо...")
            cover_text = generate_cover_text(data)
            bot.send_message(chat_id, cover_text[:4000])
            if not session.get("paid"):
                bot.send_message(chat_id, "Оплатите резюме для получения бонусов.", reply_markup=resume_actions_keyboard())
            else:
                bot.send_message(chat_id, "🎁 Письмо бесплатно. /interview для бонуса.", reply_markup=bonus_keyboard())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    chat_id = call.message.chat.id
    data = call.data
    session = user_sessions.get(chat_id)
    if data == "regenerate_resume":
        if session and session.get("mode") == "resume" and not session.get("paid"):
            bot.send_message(chat_id, "🔄 Перегенерирую...")
            new_resume = generate_resume_text(session["data"])
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Резюме перегенерировано:")
            bot.send_message(chat_id, new_resume[:4000])
            bot.send_message(chat_id, "Что дальше?", reply_markup=resume_actions_keyboard())
        else:
            bot.answer_callback_query(call.id, "Недоступно.")
    elif data == "pay_now":
        pay_url = get_pay_link(chat_id)
        bot.send_message(chat_id, f"💳 Оплатите {PRICE}₽ по ссылке:\n{pay_url}\n\nПосле оплаты нажмите «Проверить оплату».")
    elif data == "check_pay":
        if session:
            if session.get("paid"):
                bot.answer_callback_query(call.id, "Бонусы уже активированы.", show_alert=False)
            else:
                if check_payment(chat_id):
                    session["paid"] = True
                    bot.send_message(chat_id, "✅ Оплата подтверждена! Бонусы активированы.\n/cover, /interview, /edit_resume, /edit_cover, /blog", reply_markup=bonus_keyboard())
                    try:
                        bot.send_message(ADMIN_CHAT_ID, f"✅ ОПЛАТА!\n👤 @{call.from_user.first_name} (ID: {chat_id})")
                    except:
                        pass
                    bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id, reply_markup=None)
                    bot.answer_callback_query(call.id, "Оплата подтверждена!")
                else:
                    bot.answer_callback_query(call.id, "Платёж не найден. Попробуйте позже.", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "Сессия не активна. Напишите /start заново.", show_alert=True)
    bot.answer_callback_query(call.id)

# Запуск бота в отдельном потоке, а Flask в основном
def run_bot():
    bot.infinity_polling()

if __name__ == "__main__":
    # Запускаем бота в фоне
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    # Запускаем Flask для healthcheck
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
