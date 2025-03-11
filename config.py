import os
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Токен Telegram бота
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # ID администратора
