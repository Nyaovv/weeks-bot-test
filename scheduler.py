import asyncio
from datetime import datetime
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from database import get_all_users, update_last_notified_week
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")
logger = logging.getLogger(__name__)

async def load_blocked_users():
    """Загружает список заблокированных пользователей из файла."""
    blocked_users = {}
    try:
        with open("blocked_users.txt", "r") as f:
            for line in f.readlines():
                try:
                    user_id, block_time = line.strip().split(":")
                    blocked_users[int(user_id)] = block_time
                except ValueError:
                    logger.warning(f"Некорректная строка в файле blocked_users.txt: {line.strip()}")
                    continue
    except FileNotFoundError:
        logger.info("Файл blocked_users.txt не найден. Создаем новый.")
    return blocked_users

async def save_blocked_users(blocked_users):
    """Сохраняет список заблокированных пользователей в файл."""
    with open("blocked_users.txt", "w") as f:
        for user_id, block_time in blocked_users.items():
            f.write(f"{user_id}:{block_time}\n")

async def check_blocked_users(bot: Bot):
    """Проверяет статус пользователей и обновляет список заблокированных."""
    while True:
        users = await get_all_users()
        blocked_users = await load_blocked_users()

        for user_id, name, birthdate, last_week, username in users:
            try:
                # Проверяем статус пользователя
                await bot.get_chat(user_id)
                
                # Если пользователь был заблокирован, но теперь разблокировал бота
                if user_id in blocked_users:
                    del blocked_users[user_id]
                    logger.info(f"Пользователь {user_id} разблокировал бота. Удален из списка заблокированных.")
            except TelegramForbiddenError:
                # Пользователь заблокировал бота
                if user_id not in blocked_users:
                    block_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    blocked_users[user_id] = block_time
                    logger.warning(f"Пользователь {user_id} заблокировал бота. Добавлен в список заблокированных.")
            except Exception as e:
                logger.error(f"Ошибка при проверке блокировки пользователя {user_id}: {e}")

        # Сохраняем обновленный список заблокированных пользователей
        await save_blocked_users(blocked_users)
        
        logger.info("Файл blocked_users.txt успешно обновлен.")
        await asyncio.sleep(86400)  # Проверяем раз в день

async def send_weekly_notifications(bot: Bot):
    """Отправляет уведомления о прожитых неделях."""
    try:
        users = await get_all_users()
        for user_id, name, birthdate, last_week, username in users:
            try:
                # Пытаемся преобразовать дату из формата DD.MM.YYYY
                birthdate_dt = datetime.strptime(birthdate, "%d.%m.%Y")
            except ValueError:
                # Если дата уже в формате YYYY-MM-DD, преобразуем её
                birthdate_dt = datetime.strptime(birthdate, "%Y-%m-%d")
            
            weeks_lived = (datetime.now().date() - birthdate_dt.date()).days // 7
            if last_week is None or weeks_lived > last_week:
                message = f"Привет, {name}! Ты прожил {weeks_lived} недель. Продолжай жить на максимум! 🚀"
                try:
                    await bot.send_message(user_id, message)
                    await update_last_notified_week(user_id, weeks_lived)
                except TelegramForbiddenError:
                    # Пользователь заблокировал бота
                    blocked_users = await load_blocked_users()
                    if user_id not in blocked_users:
                        blocked_users[user_id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        await save_blocked_users(blocked_users)
                        logger.warning(f"Пользователь {user_id} заблокировал бота. Добавлен в список заблокированных.")
                except Exception as e:
                    logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений: {e}")

async def scheduler(bot: Bot):
    """Планировщик задач."""
    while True:
        await send_weekly_notifications(bot)
        await asyncio.sleep(604800)  # Ждем неделю (7 дней * 24 часа * 60 мин * 60 сек)
