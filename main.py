import nest_asyncio
nest_asyncio.apply()

import logging
import os
import requests
import random
import feedparser
import string
import asyncio
from datetime import time

from dotenv import load_dotenv
load_dotenv()  # Загружает переменные из файла .env

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ------------------ Настройка логирования ------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------ Конфигурация ------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
BASE_CURRENCY = "RUB"  # для курсов валют

# ------------------ Глобальные хранилища ------------------
todo_tasks = {}           # {chat_id: [task, ...]}
user_settings = {}        # {chat_id: {"city": "..." }}
subscriptions = {}        # {(chat_id, subscription_type): job}
quiz_questions = [
    {"question": "Сколько будет 2+2?", "options": ["3", "4", "5"], "answer": "4"},
    {"question": "Столица Франции?", "options": ["Берлин", "Париж", "Рим"], "answer": "Париж"},
    {"question": "Какой фрукт бывает красным, зелёным и жёлтым одновременно?", "options": ["Яблоко", "Банан", "Апельсин"], "answer": "Яблоко"},
    {"question": "Что всегда идёт, но никогда не приходит?", "options": ["Круг", "Время", "Река"], "answer": "Время"},
    {"question": "Какая река считается самой длинной в мире?", "options": ["Амазонка", "Нил", "Миссисипи"], "answer": "Нил"},
    {"question": "Сколько дней в високосном году?", "options": ["365", "366", "367"], "answer": "366"},
    {"question": "Какой цвет получается при смешивании синего и жёлтого?", "options": ["Зелёный", "Фиолетовый", "Оранжевый"], "answer": "Зелёный"},
    {"question": "Что всегда растёт, но не стареет?", "options": ["Дерево", "Растение", "Возраст"], "answer": "Возраст"}
]

# Словарь языков для переводчика с флагами
LANGUAGES = {
    "ru": {"name": "Русский", "flag": "🇷🇺"},
    "en": {"name": "Английский", "flag": "🇬🇧"},
    "zh-CN": {"name": "Китайский", "flag": "🇨🇳"},
    "ar": {"name": "Арабский", "flag": "🇸🇦"},
    "es": {"name": "Испанский", "flag": "🇪🇸"},
    "pt": {"name": "Португальский", "flag": "🇵🇹"},
    "fr": {"name": "Французский", "flag": "🇫🇷"},
    "de": {"name": "Немецкий", "flag": "🇩🇪"},
    "it": {"name": "Итальянский", "flag": "🇮🇹"},
    "tr": {"name": "Турецкий", "flag": "🇹🇷"}
}

# ------------------ Функции команд ------------------

# /start и /help – выводит список команд и кнопочное меню
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = (
        "<b>Добро пожаловать в Супер-Бота!</b>\n\n"
        "Я умею выполнять множество полезных функций:\n\n"
        "• <b>/reminder &lt;секунды&gt; &lt;текст&gt;</b> — установить напоминание\n"
        "• <b>/weather &lt;город&gt;</b> — текущая погода\n"
        "• <b>/forecast [&lt;город&gt;]</b> — прогноз погоды\n"
        "• <b>/rates</b> — курсы валют и криптовалют (базовая: RUB)\n"
        "• <b>/search &lt;запрос&gt;</b> — поиск в Wikipedia\n"
        "• <b>/convert &lt;значение&gt; &lt;из_единицы&gt; to &lt;в_единице&gt;</b> — конвертер\n"
        "• <b>/translate_interactive</b> — интерактивный переводчик\n"
        "• <b>/todo</b> — задачи (add, list, remove)\n"
        "• <b>/quiz</b> — викторина\n"
        "• <b>/settings</b> — настройки (например, город по умолчанию)\n"
        "• <b>/subscribe</b> и <b>/unsubscribe</b> — подписка на уведомления\n"
        "• <b>/top_quiz</b> — таблица лидеров по квизу\n\n"
        "Нажмите кнопку ниже для выбора функции:"
    )
    keyboard = [
        [InlineKeyboardButton("Напоминание", callback_data="menu_reminder")],
        [InlineKeyboardButton("Погода", callback_data="menu_weather"),
         InlineKeyboardButton("Прогноз", callback_data="menu_forecast")],
        [InlineKeyboardButton("Курсы валют", callback_data="menu_rates"),
         InlineKeyboardButton("Поиск", callback_data="menu_search")],
        [InlineKeyboardButton("Конвертер", callback_data="menu_convert"),
         InlineKeyboardButton("Перевод", callback_data="menu_translate")],
        [InlineKeyboardButton("To-Do", callback_data="menu_todo"),
         InlineKeyboardButton("Викторина", callback_data="menu_quiz")],
        [InlineKeyboardButton("Настройки", callback_data="menu_settings"),
         InlineKeyboardButton("Подписки", callback_data="menu_subscribe")],
        [InlineKeyboardButton("Топ квиз", callback_data="menu_top_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

# Напоминание
async def reminder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /reminder <секунды> <текст>")
        return
    try:
        seconds = int(context.args[0])
        if seconds <= 0:
            await update.message.reply_text("Укажите число секунд больше 0.")
            return
        text = " ".join(context.args[1:])
        context.job_queue.run_once(send_reminder, seconds, data={'chat_id': update.effective_chat.id, 'text': text})
        await update.message.reply_text(f"Напоминание установлено через {seconds} секунд.")
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажите корректное число секунд.")
    except Exception as e:
        logger.error("Ошибка в /reminder: %s", e)
        await update.message.reply_text("Ошибка при установке напоминания.")

async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    job_data = context.job.data
    await context.bot.send_message(chat_id=job_data['chat_id'], text=f"⏰ Напоминание: {job_data['text']}")

# Погода и прогноз
async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    city = " ".join(context.args) if context.args else user_settings.get(update.effective_chat.id, {}).get("city")
    if not city:
        await update.message.reply_text("Укажите город: /weather <город> или задайте город по умолчанию через /settings city <город>")
        return
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
        data = requests.get(url).json()
        if data.get("cod") != 200:
            await update.message.reply_text(f"Город не найден: {city}")
            return
        desc = data["weather"][0]["description"].capitalize()
        temp = data["main"]["temp"]
        humidity = data["main"]["humidity"]
        message = f"Погода в <b>{city}</b>:\nУсловия: {desc}\nТемпература: {temp}°C\nВлажность: {humidity}%"
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Ошибка в /weather: %s", e)
        await update.message.reply_text("Ошибка при получении данных о погоде.")

async def forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    city = " ".join(context.args) if context.args else user_settings.get(update.effective_chat.id, {}).get("city")
    if not city:
        await update.message.reply_text("Укажите город: /forecast <город> или установите город по умолчанию через /settings city <город>")
        return
    try:
        url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
        data = requests.get(url).json()
        if data.get("cod") != "200":
            await update.message.reply_text(f"Не удалось получить прогноз для: {city}")
            return
        message = f"<b>Прогноз погоды в {city} на ближайшие 24 часа:</b>\n"
        for entry in data["list"][:8]:
            dt = entry["dt_txt"]
            temp = entry["main"]["temp"]
            desc = entry["weather"][0]["description"].capitalize()
            message += f"{dt}: {temp}°C, {desc}\n"
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Ошибка в /forecast: %s", e)
        await update.message.reply_text("Ошибка при получении прогноза.")

# Курсы валют и криптовалют
async def rates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        fiat_url = "https://api.exchangerate-api.com/v4/latest/RUB"
        fiat_data = requests.get(fiat_url).json()
        fiat_currencies = ["USD", "EUR", "GBP", "JPY", "CNY"]
        fiat_message = "<b>Фиатные валюты (базовая: RUB):</b>\n"
        for cur in fiat_currencies:
            rate = fiat_data["rates"].get(cur)
            if rate:
                fiat_message += f"{cur}: {rate:.2f}\n"
        crypto_ids = "bitcoin,ethereum,binancecoin,ripple,cardano"
        crypto_url = f"https://api.coingecko.com/api/v3/simple/price?ids={crypto_ids}&vs_currencies=rub"
        crypto_data = requests.get(crypto_url).json()
        crypto_message = "\n<b>Криптовалюты (цена в RUB):</b>\n"
        mapping = {"bitcoin": "Bitcoin (BTC)", "ethereum": "Ethereum (ETH)",
                   "binancecoin": "Binance Coin (BNB)", "ripple": "Ripple (XRP)",
                   "cardano": "Cardano (ADA)"}
        for coin, name in mapping.items():
            price = crypto_data.get(coin, {}).get("rub")
            if price:
                crypto_message += f"{name}: {price:,} RUB\n"
        await update.message.reply_text(f"{fiat_message}{crypto_message}", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Ошибка в /rates: %s", e)
        await update.message.reply_text("Ошибка при получении курсов валют/криптовалют.")

# Поиск в Wikipedia
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Использование: /search <запрос>")
        return
    try:
        query = " ".join(context.args)
        url = f"https://ru.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=3&namespace=0&format=json"
        data = requests.get(url).json()
        if len(data) >= 4 and data[3]:
            results = "\n".join(data[3])
            message = f"<b>Найденные ссылки по запросу «{query}»:</b>\n{results}"
        else:
            message = f"По запросу «{query}» ничего не найдено."
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Ошибка в /search: %s", e)
        await update.message.reply_text("Ошибка при поиске информации.")

# Конвертер единиц
async def convert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 4 or "to" not in context.args:
        await update.message.reply_text(
            "Использование: /convert <значение> <из_единицы> to <в_единице>\nПримеры:\n• /convert 100 kg to lb\n• /convert 10 km to mi\n• /convert 20 C to F\n• /convert 68 F to C"
        )
        return
    try:
        to_index = context.args.index("to")
        value = float(context.args[0])
        from_unit = context.args[1].lower()
        to_unit = context.args[to_index + 1].lower()
        if from_unit in ["kg", "кг"] and to_unit in ["lb", "фунт", "фунты"]:
            converted = value * 2.20462
            message = f"{value} кг = {converted:.2f} фунтов"
        elif from_unit in ["km", "километр", "километры"] and to_unit in ["mi", "miles", "мил", "мили"]:
            converted = value * 0.621371
            message = f"{value} км = {converted:.2f} миль"
        elif from_unit in ["c", "°c", "celsius"] and to_unit in ["f", "°f", "fahrenheit"]:
            converted = value * 9/5 + 32
            message = f"{value}°C = {converted:.2f}°F"
        elif from_unit in ["f", "°f", "fahrenheit"] and to_unit in ["c", "°c", "celsius"]:
            converted = (value - 32) * 5/9
            message = f"{value}°F = {converted:.2f}°C"
        else:
            message = "Конвертация для данных единиц не поддерживается."
        await update.message.reply_text(message)
    except ValueError:
        await update.message.reply_text("Пожалуйста, укажите корректное числовое значение.")
    except Exception as e:
        logger.error("Ошибка в /convert: %s", e)
        await update.message.reply_text("Ошибка при выполнении конвертации.")

# Интерактивный переводчик
async def translate_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = []
    for code, info in LANGUAGES.items():
        button_text = f"{info['name']} {info['flag']}"
        keyboard.append(InlineKeyboardButton(button_text, callback_data=f"src_{code}"))
    rows = [keyboard[i:i+3] for i in range(0, len(keyboard), 3)]
    reply_markup = InlineKeyboardMarkup(rows)
    await update.message.reply_text("Выберите, с какого языка переводить текст:", reply_markup=reply_markup)

async def translation_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    if data.startswith("src_"):
        src_code = data.split("_")[1]
        context.user_data["src_lang"] = src_code
        keyboard = []
        for code, info in LANGUAGES.items():
            button_text = f"{info['name']} {info['flag']}"
            keyboard.append(InlineKeyboardButton(button_text, callback_data=f"tgt_{code}"))
        rows = [keyboard[i:i+3] for i in range(0, len(keyboard), 3)]
        reply_markup = InlineKeyboardMarkup(rows)
        await query.edit_message_text("Выберите, на какой язык переводить текст:", reply_markup=reply_markup)
    elif data.startswith("tgt_"):
        tgt_code = data.split("_")[1]
        context.user_data["target_lang"] = tgt_code
        context.user_data["awaiting_translation"] = True
        await query.edit_message_text("Введите текст для перевода:")

async def translation_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("awaiting_translation"):
        text = update.message.text
        src_lang = context.user_data.get("src_lang")
        target_lang = context.user_data.get("target_lang")
        url = f"https://api.mymemory.translated.net/get?q={text}&langpair={src_lang}|{target_lang}"
        data = requests.get(url).json()
        translation = data.get("responseData", {}).get("translatedText")
        if translation:
            reply = "Вот ваш текст!\n```\n" + translation + "\n```"
            await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("Не удалось получить перевод.")
        context.user_data.pop("awaiting_translation", None)
        context.user_data.pop("src_lang", None)
        context.user_data.pop("target_lang", None)

# Управление задачами (To-Do)
async def todo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        keyboard = [
            [InlineKeyboardButton("Добавить", callback_data="todo_add")],
            [InlineKeyboardButton("Показать", callback_data="todo_list")],
            [InlineKeyboardButton("Удалить", callback_data="todo_remove")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Выберите действие с задачами:", reply_markup=reply_markup)
        return
    subcommand = context.args[0].lower()
    if subcommand == "add":
        task = " ".join(context.args[1:])
        if not task:
            await update.message.reply_text("Укажите текст задачи после add.")
            return
        todo_tasks.setdefault(chat_id, []).append(task)
        await update.message.reply_text(f"Задача добавлена: {task}")
    elif subcommand == "list":
        tasks = todo_tasks.get(chat_id, [])
        if not tasks:
            await update.message.reply_text("Список задач пуст.")
            return
        message = "<b>Ваш список задач:</b>\n"
        for i, task in enumerate(tasks, 1):
            message += f"{i}. {task}\n"
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    elif subcommand == "remove":
        try:
            index = int(context.args[1]) - 1
            tasks = todo_tasks.get(chat_id, [])
            if 0 <= index < len(tasks):
                removed = tasks.pop(index)
                await update.message.reply_text(f"Задача удалена: {removed}")
            else:
                await update.message.reply_text("Некорректный номер задачи.")
        except (IndexError, ValueError):
            await update.message.reply_text("Использование: /todo remove <номер задачи>")
    else:
        await update.message.reply_text("Используйте subcommand add, list или remove.")

# Викторина (Quiz)
async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question_index = random.randrange(len(quiz_questions))
    question = quiz_questions[question_index]
    text = f"<b>Вопрос:</b> {question['question']}"
    buttons = [
        [InlineKeyboardButton(opt, callback_data=f"quiz|{question_index}|{opt}")]
        for opt in question["options"]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

# Настройки пользователя
async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        keyboard = [
            [InlineKeyboardButton("Показать настройки", callback_data="settings_show")],
            [InlineKeyboardButton("Установить город вручную", callback_data="settings_city")],
            [InlineKeyboardButton("Установить по геолокации", callback_data="settings_geoloc")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
        return
    subcommand = context.args[0].lower()
    if subcommand == "show":
        settings_data = user_settings.get(chat_id, {})
        city = settings_data.get("city", "не задан")
        await update.message.reply_text(f"Ваши настройки:\nГород по умолчанию: {city}")
    elif subcommand == "city":
        city = " ".join(context.args[1:])
        if city:
            user_settings.setdefault(chat_id, {})["city"] = city
            await update.message.reply_text(f"Город по умолчанию установлен: {city}")
        else:
            await update.message.reply_text("Укажите город после команды /settings city")
    else:
        await update.message.reply_text("Неизвестная настройка. Используйте show или city.")

# Функция запроса геолокации для установки города по умолчанию
async def request_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = ReplyKeyboardMarkup([[KeyboardButton("Отправить местоположение", request_location=True)]],
                                   one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("Нажмите кнопку ниже, чтобы отправить своё местоположение:", reply_markup=keyboard)

# Обработчик полученной геолокации
async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude
        url = f"http://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={lon}&limit=1&appid={OPENWEATHER_API_KEY}"
        data = requests.get(url).json()
        if data and isinstance(data, list) and data[0].get("name"):
            city = data[0]["name"]
            user_settings[update.effective_chat.id] = {"city": city}
            await update.message.reply_text(f"Город по умолчанию установлен: {city}")
        else:
            await update.message.reply_text("Не удалось определить город по вашей геолокации.")
    else:
        await update.message.reply_text("Местоположение не получено.")

# Подписки на уведомления
async def daily_weather(context: ContextTypes.DEFAULT_TYPE) -> None:
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    city = user_settings.get(chat_id, {}).get("city")
    if not city:
        await context.bot.send_message(chat_id, text="[Подписка] Город по умолчанию не установлен. Используйте /settings для установки.")
        return
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
        data = requests.get(url).json()
        if data.get("cod") != 200:
            message = f"[Подписка] Не удалось получить погоду для {city}."
        else:
            desc = data["weather"][0]["description"].capitalize()
            temp = data["main"]["temp"]
            message = f"[Подписка] Погода в {city}:\n{desc}, {temp}°C"
        await context.bot.send_message(chat_id, text=message)
    except Exception as e:
        logger.error("Ошибка в daily_weather: %s", e)

async def daily_news(context: ContextTypes.DEFAULT_TYPE) -> None:
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    try:
        feed_url = "http://feeds.bbci.co.uk/russian/rss.xml"
        feed = feedparser.parse(feed_url)
        if feed.entries:
            message = "<b>[Подписка] Последние новости:</b>\n"
            for entry in feed.entries[:5]:
                message += f"<a href='{entry.link}'>{entry.title}</a>\n"
        else:
            message = "[Подписка] Не удалось получить новости."
        await context.bot.send_message(chat_id, text=message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.error("Ошибка в daily_news: %s", e)

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /subscribe <weather|news> <HH:MM>")
        return
    sub_type = context.args[0].lower()
    time_str = context.args[1]
    try:
        hour, minute = map(int, time_str.split(":"))
        scheduled_time = time(hour, minute)
    except Exception:
        await update.message.reply_text("Неверный формат времени. Используйте HH:MM (например, 08:30)")
        return
    chat_id = update.effective_chat.id
    if sub_type == "weather":
        job = context.job_queue.run_daily(daily_weather, scheduled_time, data={"chat_id": chat_id})
        subscriptions[(chat_id, "weather")] = job
        await update.message.reply_text(f"Подписка на погоду установлена на {time_str}.")
    elif sub_type == "news":
        job = context.job_queue.run_daily(daily_news, scheduled_time, data={"chat_id": chat_id})
        subscriptions[(chat_id, "news")] = job
        await update.message.reply_text(f"Подписка на новости установлена на {time_str}.")
    else:
        await update.message.reply_text("Тип подписки должен быть weather или news.")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 1:
        await update.message.reply_text("Использование: /unsubscribe <weather|news>")
        return
    sub_type = context.args[0].lower()
    chat_id = update.effective_chat.id
    key = (chat_id, sub_type)
    job = subscriptions.pop(key, None)
    if job:
        job.schedule_removal()
        await update.message.reply_text(f"Подписка на {sub_type} отменена.")
    else:
        await update.message.reply_text(f"Подписка на {sub_type} не найдена.")

# Интерактивное меню с кнопками для всех функций
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Напоминание", callback_data="menu_reminder")],
        [InlineKeyboardButton("Погода", callback_data="menu_weather"),
         InlineKeyboardButton("Прогноз", callback_data="menu_forecast")],
        [InlineKeyboardButton("Курсы валют", callback_data="menu_rates"),
         InlineKeyboardButton("Поиск", callback_data="menu_search")],
        [InlineKeyboardButton("Конвертер", callback_data="menu_convert"),
         InlineKeyboardButton("Перевод", callback_data="menu_translate")],
        [InlineKeyboardButton("To-Do", callback_data="menu_todo"),
         InlineKeyboardButton("Викторина", callback_data="menu_quiz")],
        [InlineKeyboardButton("Настройки", callback_data="menu_settings"),
         InlineKeyboardButton("Подписки", callback_data="menu_subscribe")],
        [InlineKeyboardButton("Топ квиз", callback_data="menu_top_quiz")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите опцию:", reply_markup=reply_markup)

# Callback handler для меню, викторины, переводчика и настроек
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("menu_"):
        option = data.split("_")[1]
        if option == "reminder":
            await query.edit_message_text("Для установки напоминания используйте: /reminder <секунды> <текст>")
        elif option == "weather":
            chat_id = query.message.chat.id
            city = user_settings.get(chat_id, {}).get("city")
            if not city:
                await query.edit_message_text("Город по умолчанию не установлен. Используйте /settings city <город> или выберите по геолокации.")
            else:
                try:
                    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
                    data_weather = requests.get(url).json()
                    if data_weather.get("cod") != 200:
                        message = f"Город не найден: {city}"
                    else:
                        desc = data_weather["weather"][0]["description"].capitalize()
                        temp = data_weather["main"]["temp"]
                        humidity = data_weather["main"]["humidity"]
                        message = f"Погода в <b>{city}</b>:\nУсловия: {desc}\nТемпература: {temp}°C\nВлажность: {humidity}%"
                    await query.edit_message_text(message, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error("Ошибка в меню погода: %s", e)
                    await query.edit_message_text("Ошибка при получении данных о погоде.")
        elif option == "forecast":
            chat_id = query.message.chat.id
            city = user_settings.get(chat_id, {}).get("city")
            if not city:
                await query.edit_message_text("Город по умолчанию не установлен. Используйте /settings city <город>.")
            else:
                try:
                    url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={OPENWEATHER_API_KEY}&units=metric&lang=ru"
                    data_forecast = requests.get(url).json()
                    if data_forecast.get("cod") != "200":
                        message = f"Не удалось получить прогноз для: {city}"
                    else:
                        message = f"<b>Прогноз погоды в {city} на ближайшие 24 часа:</b>\n"
                        for entry in data_forecast["list"][:8]:
                            dt = entry["dt_txt"]
                            temp = entry["main"]["temp"]
                            desc = entry["weather"][0]["description"].capitalize()
                            message += f"{dt}: {temp}°C, {desc}\n"
                    await query.edit_message_text(message, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error("Ошибка в меню прогноз: %s", e)
                    await query.edit_message_text("Ошибка при получении прогноза.")
        elif option == "rates":
            try:
                fiat_url = "https://api.exchangerate-api.com/v4/latest/RUB"
                fiat_data = requests.get(fiat_url).json()
                fiat_currencies = ["USD", "EUR", "GBP", "JPY", "CNY"]
                fiat_message = "<b>Фиатные валюты (базовая: RUB):</b>\n"
                for cur in fiat_currencies:
                    rate = fiat_data["rates"].get(cur)
                    if rate:
                        fiat_message += f"{cur}: {rate:.2f}\n"
                crypto_ids = "bitcoin,ethereum,binancecoin,ripple,cardano"
                crypto_url = f"https://api.coingecko.com/api/v3/simple/price?ids={crypto_ids}&vs_currencies=rub"
                crypto_data = requests.get(crypto_url).json()
                crypto_message = "\n<b>Криптовалюты (цена в RUB):</b>\n"
                mapping = {"bitcoin": "Bitcoin (BTC)", "ethereum": "Ethereum (ETH)",
                           "binancecoin": "Binance Coin (BNB)", "ripple": "Ripple (XRP)",
                           "cardano": "Cardano (ADA)"}
                for coin, name in mapping.items():
                    price = crypto_data.get(coin, {}).get("rub")
                    if price:
                        crypto_message += f"{name}: {price:,} RUB\n"
                message = fiat_message + crypto_message
                await query.edit_message_text(message, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error("Ошибка в меню rates: %s", e)
                await query.edit_message_text("Ошибка при получении курсов валют/криптовалют.")
        elif option == "search":
            await query.edit_message_text("Для поиска используйте: /search <запрос>")
        elif option == "convert":
            await query.edit_message_text("Для конвертации используйте: /convert <значение> <из_единицы> to <в_единице>")
        elif option == "translate":
            keyboard = []
            for code, info in LANGUAGES.items():
                button_text = f"{info['name']} {info['flag']}"
                keyboard.append(InlineKeyboardButton(button_text, callback_data=f"src_{code}"))
            rows = [keyboard[i:i+3] for i in range(0, len(keyboard), 3)]
            reply_markup = InlineKeyboardMarkup(rows)
            await query.edit_message_text("Выберите, с какого языка переводить текст:", reply_markup=reply_markup)
        elif option == "todo":
            tasks = todo_tasks.get(query.message.chat.id, [])
            if tasks:
                message = "<b>Ваш список задач:</b>\n" + "\n".join(f"{i+1}. {task}" for i, task in enumerate(tasks))
            else:
                message = "Список задач пуст. Добавьте задачу командой /todo add <текст>"
            await query.edit_message_text(message, parse_mode=ParseMode.HTML)
        elif option == "quiz":
            await quiz(update, context)
        elif option == "settings":
            chat_id = query.message.chat.id
            settings_data = user_settings.get(chat_id, {})
            city = settings_data.get("city", "не задан")
            keyboard = [
                [InlineKeyboardButton("Показать настройки", callback_data="settings_show")],
                [InlineKeyboardButton("Установить город вручную", callback_data="settings_city")],
                [InlineKeyboardButton("Установить по геолокации", callback_data="settings_geoloc")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            message = f"Ваши настройки:\nГород по умолчанию: {city}\nВыберите действие:"
            await query.edit_message_text(message, reply_markup=reply_markup)
        elif option == "subscribe":
            keyboard = [
                [InlineKeyboardButton("Погода", callback_data="subscribe_weather"),
                 InlineKeyboardButton("Новости", callback_data="subscribe_news")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("Выберите тип подписки:", reply_markup=reply_markup)
        elif option == "top_quiz":
            await query.edit_message_text("Функция /top_quiz пока в разработке.")
        else:
            await query.edit_message_text("Неизвестная опция.")
    elif data.startswith("quiz|"):
        parts = data.split("|")
        if len(parts) < 3:
            return
        q_index = int(parts[1])
        selected = parts[2]
        correct = quiz_questions[q_index]["answer"]
        response = "✅ Верно!" if selected == correct else f"❌ Неверно. Правильный ответ: {correct}"
        await query.edit_message_text(text=response)
    elif data.startswith("settings_"):
        sub = data.split("_")[1]
        if sub == "show":
            chat_id = query.message.chat.id
            settings_data = user_settings.get(chat_id, {})
            city = settings_data.get("city", "не задан")
            await query.edit_message_text(f"Ваши настройки:\nГород по умолчанию: {city}")
        elif sub == "city":
            await query.edit_message_text("Введите город для установки вручную через: /settings city <город>")
        elif sub == "geoloc":
            keyboard = ReplyKeyboardMarkup([[KeyboardButton("Отправить местоположение", request_location=True)]],
                                           one_time_keyboard=True, resize_keyboard=True)
            await query.edit_message_text("Нажмите кнопку ниже, чтобы отправить своё местоположение:")
            await query.message.reply_text("Отправьте своё местоположение:", reply_markup=keyboard)
    elif data.startswith("subscribe_"):
        sub = data.split("_")[1]
        if sub == "weather":
            await query.edit_message_text("Для подписки на погоду используйте: /subscribe weather <HH:MM>")
        elif sub == "news":
            await query.edit_message_text("Для подписки на новости используйте: /subscribe news <HH:MM>")
    elif data.startswith("src_") or data.startswith("tgt_"):
        await translation_callback_handler(update, context)

# Обработчик текстовых сообщений для интерактивного переводчика
async def translation_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("awaiting_translation"):
        text = update.message.text
        src_lang = context.user_data.get("src_lang")
        target_lang = context.user_data.get("target_lang")
        url = f"https://api.mymemory.translated.net/get?q={text}&langpair={src_lang}|{target_lang}"
        data = requests.get(url).json()
        translation = data.get("responseData", {}).get("translatedText")
        if translation:
            reply = "Вот ваш текст!\n```\n" + translation + "\n```"
            await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("Не удалось получить перевод.")
        context.user_data.pop("awaiting_translation", None)
        context.user_data.pop("src_lang", None)
        context.user_data.pop("target_lang", None)

# Обработчик геолокации для установки города по умолчанию
async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude
        url = f"http://api.openweathermap.org/geo/1.0/reverse?lat={lat}&lon={lon}&limit=1&appid={OPENWEATHER_API_KEY}"
        data = requests.get(url).json()
        if data and isinstance(data, list) and data[0].get("name"):
            city = data[0]["name"]
            user_settings[update.effective_chat.id] = {"city": city}
            await update.message.reply_text(f"Город по умолчанию установлен: {city}")
        else:
            await update.message.reply_text("Не удалось определить город по вашей геолокации.")
    else:
        await update.message.reply_text("Местоположение не получено.")

# ------------------ Основная функция ------------------
async def main() -> None:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Регистрация команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("reminder", reminder))
    app.add_handler(CommandHandler("weather", weather))
    app.add_handler(CommandHandler("forecast", forecast))
    app.add_handler(CommandHandler("rates", rates))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("convert", convert))
    app.add_handler(CommandHandler("translate_interactive", translate_interactive))
    app.add_handler(CommandHandler("todo", todo))
    app.add_handler(CommandHandler("quiz", quiz))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("top_quiz", lambda update, context: update.message.reply_text("Функция /top_quiz пока в разработке.")))
    
    # Обработчик callback'ов от inline-кнопок
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Обработчик текстовых сообщений для интерактивного переводчика
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, translation_text_handler))
    # Обработчик для геолокации
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))

    logger.info("Бот запущен")
    await app.run_polling(close_loop=False)

if __name__ == '__main__':
    asyncio.run(main())
