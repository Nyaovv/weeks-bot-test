import aiosqlite
import asyncio
import logging
import random
from config import BOT_TOKEN, ADMIN_ID
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
from scheduler import scheduler, check_blocked_users  # Импортируем check_blocked_users
import aiocron
import os

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Числа от 1 до 9 в текст
def number_to_text(number: int, case: str = "именительный") -> str:
    number_words = {
        1: {"именительный": "одна", "винительный": "одну"},
        2: {"именительный": "две", "винительный": "две"},
        3: {"именительный": "три", "винительный": "три"},
        4: {"именительный": "четыре", "винительный": "четыре"},
        5: {"именительный": "пять", "винительный": "пять"},
        6: {"именительный": "шесть", "винительный": "шесть"},
        7: {"именительный": "семь", "винительный": "семь"},
        8: {"именительный": "восемь", "винительный": "восемь"},
        9: {"именительный": "девять", "винительный": "девять"}
    }
    return number_words.get(number, {}).get(case, str(number))

# Функция для правильного склонения слова "неделя"
def get_weeks_text(weeks: int, case: str = "именительный", use_text: bool = False) -> str:
    if use_text and 1 <= weeks <= 9:
        weeks_word = number_to_text(weeks, case)
    else:
        weeks_word = str(weeks)

    if weeks % 10 == 1 and weeks % 100 != 11:
        return f"{weeks_word} неделя" if case == "именительный" else f"{weeks_word} неделю"
    elif 2 <= weeks % 10 <= 4 and (weeks % 100 < 12 or weeks % 100 > 14):
        return f"{weeks_word} недели" if case == "именительный" else f"{weeks_word} недели"
    else:
        return f"{weeks_word} недель"

# Загружаем токен из .env
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")
logger = logging.getLogger(__name__)

# Хранение состояний пользователей
waiting_for_name = {}
waiting_for_birthdate = {}

# Глобальный словарь для хранения оставшихся фактов для каждого пользователя
user_facts = {}

# Клавиатура с кнопками
update_button = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📜 Получить случайную цитату")],
        [KeyboardButton(text="📊 Статус")],
        [KeyboardButton(text="Перезаписать данные")]
    ],
    resize_keyboard=True
)

# Инициализация базы данных
async def init_db():
    async with aiosqlite.connect("users.db") as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            birthdate TEXT,
            last_notified_week INTEGER,
            username TEXT  -- Новый столбец
        )
        """)
        await db.commit()

# Добавление пользователя в базу данных
async def add_user(user_id, name, birthdate, username):
    async with aiosqlite.connect("users.db") as db:
        await db.execute("INSERT INTO users (user_id, name, birthdate, username) VALUES (?, ?, ?, ?)", (user_id, name, birthdate, username))
        await db.commit()

# Получение данных пользователя
async def get_user(user_id):
    async with aiosqlite.connect("users.db") as db:
        cursor = await db.execute("SELECT name, birthdate, username FROM users WHERE user_id = ?", (user_id,))
        result = await cursor.fetchone()
        if result:
            name, birthdate, username = result
            try:
                # Пытаемся преобразовать дату из формата YYYY-MM-DD
                birthdate_dt = datetime.strptime(birthdate, "%Y-%m-%d")
                birthdate_user_format = birthdate_dt.strftime("%d.%m.%Y")
            except ValueError:
                # Если дата уже в формате DD.MM.YYYY, оставляем её как есть
                birthdate_user_format = birthdate
            return name, birthdate_user_format, username
        return None

# Удаление пользователя
async def delete_user(user_id):
    async with aiosqlite.connect("users.db") as db:
        await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        await db.commit()

# Обновление последней уведомлённой недели
async def update_last_notified_week(user_id, weeks_lived):
    async with aiosqlite.connect("users.db") as db:
        await db.execute("UPDATE users SET last_notified_week = ? WHERE user_id = ?", (weeks_lived, user_id))
        await db.commit()

# Получение всех пользователей
async def get_all_users():
    async with aiosqlite.connect("users.db") as db:
        cursor = await db.execute("SELECT user_id, name, birthdate, last_notified_week, username FROM users")
        return await cursor.fetchall()

# Обработчик команды /start
@dp.message(Command("start"))
async def start_handler(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if user:
        name, birthdate, username = user
        try:
            birthdate_dt = datetime.strptime(birthdate, "%d.%m.%Y")
            weeks_lived = (datetime.now() - birthdate_dt).days // 7
            weeks_text = get_weeks_text(weeks_lived)
            await message.answer(f"Привет, {name}! 👋 Вы прожили {weeks_text}. Ваша дата рождения: {birthdate}.", reply_markup=update_button)
        except ValueError:
            await message.answer("Ошибка в сохранённой дате рождения! Попробуйте ввести её заново.")
    else:
        await message.answer("Здравствуйте! Я бот, который будет присылать вам уведомление о каждой прожитой неделе. Давайте познакомимся. Как вас зовут?")
        waiting_for_name[user_id] = None

# Обработчик ввода имени
@dp.message(lambda message: message.from_user.id in waiting_for_name)
async def handle_name_input(message: Message):
    user_id = message.from_user.id
    name = message.text.strip()

    if not name or len(name) < 2 or len(name) > 50:
        await message.answer("Имя должно содержать от 2 до 50 символов! Попробуйте снова.")
        return

    # Удаляем пользователя из списка ожидания имени
    waiting_for_name.pop(user_id)

    # Добавляем пользователя в список ожидания даты рождения
    waiting_for_birthdate[user_id] = name

    await message.answer(f"Приятно познакомиться, {name}! Теперь укажите вашу дату рождения в формате ДД.ММ.ГГГГ.")

# Обработчик ввода даты рождения
@dp.message(lambda message: message.from_user.id in waiting_for_birthdate)
async def handle_birthdate_input(message: Message):
    user_id = message.from_user.id
    birthdate = message.text.strip()
    name = waiting_for_birthdate[user_id]
    username = message.from_user.username

    try:
        birthdate_dt = datetime.strptime(birthdate, "%d.%m.%Y")
        now = datetime.now()

        # Проверяем, что дата рождения не позже текущей даты
        if birthdate_dt > now:
            await message.answer("Вы не могли родиться в будущем. Попробуйте снова.")
            return

        # Проверяем, что год рождения не раньше 1900
        if birthdate_dt.year < 1900:
            await message.answer("Год рождения не может быть раньше 1900 года. Попробуйте снова.")
            return

        day_of_week = birthdate_dt.strftime("%A").lower()
    except ValueError:
        await message.answer("Ошибка! Введите дату в формате ДД.ММ.ГГГГ")
        return

    await add_user(user_id, name, birthdate, username)
    waiting_for_birthdate.pop(user_id, None)

    weeks_lived = (now - birthdate_dt).days // 7
    weeks_text = get_weeks_text(weeks_lived, case="винительный")
    await message.answer(f"Отлично, {name}! 🎉 Вы прожили {weeks_text}. Теперь я буду напоминать вам о каждой новой неделе!", reply_markup=update_button)

    # Создаем задачу для отправки уведомлений в день недели пользователя
    create_weekly_notification_task(user_id, name, birthdate, day_of_week)

# Функция для создания задачи уведомления
def create_weekly_notification_task(user_id, name, birthdate, day_of_week):
    @aiocron.crontab(f'0 9 * * {day_of_week[:3]}')
    async def weekly_notification_task():
        now = datetime.now()
        birthdate_dt = datetime.strptime(birthdate, "%d.%m.%Y")
        weeks_lived = (now - birthdate_dt).days // 7

        # Получаем последнюю уведомлённую неделю
        async with aiosqlite.connect("users.db") as db:
            cursor = await db.execute("SELECT last_notified_week FROM users WHERE user_id = ?", (user_id,))
            last_week = await cursor.fetchone()

        if last_week is None or weeks_lived > last_week[0]:
            await update_last_notified_week(user_id, weeks_lived)
            weeks_text = get_weeks_text(weeks_lived)
            await bot.send_message(user_id, f"Здравствуйте, {name}. Вы прожили {weeks_text}. 🎉")

# Обработчик запроса цитаты
@dp.message(lambda message: message.text == "📜 Получить случайную цитату")
async def handle_quote_request(message: Message):
    try:
        with open("quotes.txt", "r", encoding="utf-8") as file:
            quotes = file.readlines()
        if quotes:
            random_quote = random.choice(quotes).strip()
            await message.answer(f"✨\n\n {random_quote} ")
        else:
            await message.answer("Файл с цитатами пуст. Добавьте цитаты и попробуйте снова.")
    except FileNotFoundError:
        await message.answer("⚠️ Файл с цитатами не найден. Убедитесь, что он существует.")

# Обработчик нажатия кнопки "Перезаписать данные"
@dp.message(lambda message: message.text == "Перезаписать данные")
async def handle_update_request(message: Message):
    user_id = message.from_user.id
    await delete_user(user_id)

    waiting_for_name.pop(user_id, None)
    waiting_for_birthdate.pop(user_id, None)

    await message.answer("Давайте обновим ваши данные! Как вас зовут?")
    waiting_for_name[user_id] = None

# Рандомный факт в статусе
def get_random_fact(birthdate, user_id):
    now = datetime.now()
    birthdate_dt = datetime.strptime(birthdate, "%d.%m.%Y")

    # Если у пользователя нет списка фактов, создаем его
    if user_id not in user_facts or not user_facts[user_id]:
        # Создаем список всех возможных фактов
        facts = []

        # 1. Сколько недель до следующего "круглого" возраста (30, 40, 50 лет)
        age = (now - birthdate_dt).days // 365
        next_rounded_age = ((age // 10) + 1) * 10
        next_rounded_age_date = datetime(birthdate_dt.year + next_rounded_age, birthdate_dt.month, birthdate_dt.day)
        weeks_to_next_age = (next_rounded_age_date - now).days // 7
        weeks_text = get_weeks_text(weeks_to_next_age)
        facts.append(f"Осталось {weeks_text} до {next_rounded_age} лет!")

        # 2. Сколько недель до 18 лет (если пользователь младше 18)
        if age < 18:
            adult_date = datetime(birthdate_dt.year + 18, birthdate_dt.month, birthdate_dt.day)
            weeks_to_adult = (adult_date - now).days // 7
            weeks_text = get_weeks_text(weeks_to_adult)
            facts.append(f"Осталось {weeks_text} до совершеннолетия (18 лет)!")

        # 3. Сколько недель до следующего дня рождения
        next_birthday = datetime(now.year, birthdate_dt.month, birthdate_dt.day)
        if next_birthday < now:  # Если ДР уже был в этом году, берем следующий год
            next_birthday = datetime(now.year + 1, birthdate_dt.month, birthdate_dt.day)
        weeks_to_birthday = (next_birthday - now).days // 7
        weeks_text = get_weeks_text(weeks_to_birthday)
        facts.append(f"До следующего дня рождения осталось {weeks_text}!")

        # 4. Сколько недель прошло в этом году
        first_day_of_year = datetime(now.year, 1, 1)
        weeks_passed_this_year = (now - first_day_of_year).days // 7
        weeks_text = get_weeks_text(weeks_passed_this_year)
        facts.append(f"В этом году уже прошло {weeks_text}!")

        # 5. Сколько недель до Нового года
        new_year = datetime(now.year + 1, 1, 1)
        weeks_to_new_year = (new_year - now).days // 7
        weeks_text = get_weeks_text(weeks_to_new_year)
        facts.append(f"До Нового года осталось {weeks_text}!")

        # 6. Сколько недель до среднего возраста в мире (73 года)
        average_lifespan = 73
        if age < average_lifespan:
            average_lifespan_date = datetime(birthdate_dt.year + average_lifespan, birthdate_dt.month, birthdate_dt.day)
            weeks_to_average_lifespan = (average_lifespan_date - now).days // 7
            weeks_text = get_weeks_text(weeks_to_average_lifespan)
            facts.append(f"Осталось {weeks_text} до среднего возраста в мире (73 года)!")
        else:
            facts.append(f"Вы уже достигли среднего возраста в мире (73 года)!")

        # Сохраняем список фактов для пользователя
        user_facts[user_id] = facts

    # Выбираем случайный факт из оставшихся
    fact = random.choice(user_facts[user_id])
    # Удаляем показанный факт из списка
    user_facts[user_id].remove(fact)

    return fact

# Обработчик нажатия кнопки "📊 Статус"
@dp.message(lambda message: message.text == "📊 Статус")
async def handle_status_request(message: Message):
    user_id = message.from_user.id
    user = await get_user(user_id)

    if user:
        name, birthdate, username = user
        try:
            birthdate_dt = datetime.strptime(birthdate, "%d.%m.%Y")
            weeks_lived = (datetime.now() - birthdate_dt).days // 7
            weeks_text = get_weeks_text(weeks_lived, case="винительный", use_text=True)

            # Получаем случайный факт
            random_fact = get_random_fact(birthdate, user_id)

            await message.answer(f"{name}, вы прожили {weeks_text}. Ваша дата рождения: {birthdate}. 🎉\n\n{random_fact}")
        except ValueError:
            await message.answer("Ошибка в сохранённой дате рождения! Попробуйте ввести её заново.")
    else:
        await message.answer("Я вас не знаю, напишите /start для знакомства!")

# Обработчик команды /бан-лист
@dp.message(Command("бан-лист"))
async def handle_ban_list(message: Message):
    # Проверяем, что команду вызвал админ
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return

    try:
        # Читаем файл с заблокированными пользователями
        with open("blocked_users.txt", "r") as f:
            blocked_users = f.readlines()
        
        if not blocked_users:
            await message.answer("Нет пользователей, заблокировавших бота.")
            return

        # Убираем дубликаты и обрабатываем данные
        unique_blocked_users = {}
        for line in blocked_users:
            try:
                user_id, block_time = line.strip().split(":")
                user_id = int(user_id)  # Преобразуем ID в число
                
                # Если пользователь уже есть в словаре, пропускаем дубликат
                if user_id not in unique_blocked_users:
                    unique_blocked_users[user_id] = block_time
            except ValueError:
                # Пропускаем строки с некорректным форматом
                logger.warning(f"Некорректная строка в файле blocked_users.txt: {line.strip()}")
                continue

        # Формируем сообщение с данными о заблокированных пользователях
        response = "Заблокировавшие бота пользователи:\n\n"
        for user_id, block_time in unique_blocked_users.items():
            try:
                # Пытаемся получить данные пользователя из базы данных
                user_data = await get_user(user_id)
                if user_data:
                    name, birthdate, username = user_data
                    response += (
                        f"👤 Имя: {name}\n"
                        f"📅 Дата рождения: {birthdate}\n"
                        f"🆔 ID: {user_id}\n"
                        f"👤 Логин: @{username}\n"
                        f"⏰ Дата блокировки: {block_time}\n\n"
                    )
                else:
                    # Если данные пользователя не найдены в базе
                    response += (
                        f"🆔 ID: {user_id}\n"
                        f"⏰ Дата блокировки: {block_time}\n"
                        f"⚠️ Данные пользователя не найдены в базе.\n\n"
                    )
            except Exception as e:
                # Логируем ошибку и добавляем информацию в ответ
                logger.error(f"Ошибка при обработке данных пользователя {user_id}: {e}")
                response += (
                    f"🆔 ID: {user_id}\n"
                    f"⏰ Дата блокировки: {block_time}\n"
                    f"❌ Ошибка при получении данных: {e}\n\n"
                )

        await message.answer(response)
    except FileNotFoundError:
        await message.answer("Файл с заблокированными пользователями не найден.")
    except Exception as e:
        logger.error(f"Ошибка при обработке команды /бан-лист: {e}")
        await message.answer("Произошла ошибка при получении списка заблокированных пользователей.")
        
# Запуск бота
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")
    logger = logging.getLogger(__name__)

    logger.info("Бот запущен")
    await init_db()  # Инициализация базы данных

    # Запуск планировщика и задачи проверки блокировок
    asyncio.create_task(scheduler(bot))
    asyncio.create_task(check_blocked_users(bot))  # Добавляем задачу проверки блокировок

    # Запуск бота
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        # Закрываем соединение с базой данных при завершении работы
        await close_db_connection()

if __name__ == "__main__":
    asyncio.run(main())
