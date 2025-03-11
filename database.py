import aiosqlite
from config import DB_PATH
from datetime import datetime

# Глобальное соединение с базой данных
_db_connection = None

async def get_db_connection():
    global _db_connection
    if _db_connection is None:
        _db_connection = await aiosqlite.connect(DB_PATH)
        await _db_connection.execute("PRAGMA foreign_keys = ON")
    return _db_connection

async def close_db_connection():
    global _db_connection
    if _db_connection is not None:
        await _db_connection.close()
        _db_connection = None

async def init_db():
    db = await get_db_connection()
    await db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        birthdate DATE NOT NULL,
        last_notified_week INTEGER DEFAULT 0,
        username TEXT
    )
    """)
    await db.commit()

async def add_user(user_id, name, birthdate, username):
    # Преобразуем дату в формат YYYY-MM-DD для хранения в базе данных
    try:
        birthdate_dt = datetime.strptime(birthdate, "%d.%m.%Y")
        birthdate_db_format = birthdate_dt.strftime("%Y-%m-%d")
    except ValueError:
        # Если дата уже в формате YYYY-MM-DD, оставляем её как есть
        birthdate_db_format = birthdate
    
    db = await get_db_connection()
    await db.execute("INSERT INTO users (user_id, name, birthdate, username) VALUES (?, ?, ?, ?)", (user_id, name, birthdate_db_format, username))
    await db.commit()

async def get_user(user_id):
    db = await get_db_connection()
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

async def delete_user(user_id):
    db = await get_db_connection()
    await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    await db.commit()

async def update_last_notified_week(user_id, weeks_lived):
    db = await get_db_connection()
    await db.execute("UPDATE users SET last_notified_week = ? WHERE user_id = ?", (weeks_lived, user_id))
    await db.commit()

async def get_all_users():
    db = await get_db_connection()
    cursor = await db.execute("SELECT user_id, name, birthdate, last_notified_week, username FROM users")
    users = await cursor.fetchall()
    # Преобразуем дату обратно в формат DD.MM.YYYY
    formatted_users = []
    for user_id, name, birthdate, last_notified_week, username in users:
        try:
            # Пытаемся преобразовать дату из формата YYYY-MM-DD
            birthdate_dt = datetime.strptime(birthdate, "%Y-%m-%d")
            birthdate_user_format = birthdate_dt.strftime("%d.%m.%Y")
        except ValueError:
            # Если дата уже в формате DD.MM.YYYY, оставляем её как есть
            birthdate_user_format = birthdate
        formatted_users.append((user_id, name, birthdate_user_format, last_notified_week, username))
    return formatted_users
