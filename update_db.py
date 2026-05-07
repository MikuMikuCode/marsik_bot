import sqlite3

conn = sqlite3.connect("marsik_bot.db")
cursor = conn.cursor()

# Создаём таблицу users, если её ещё нет
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    role TEXT DEFAULT 'user',
    name TEXT,
    position TEXT,
    balance INTEGER DEFAULT 0,
    active BOOLEAN DEFAULT 1
)
""")

# Проверяем и добавляем столбцы, если их нет
try:
    cursor.execute("ALTER TABLE users ADD COLUMN name TEXT")
except sqlite3.OperationalError:
    pass  # уже есть

try:
    cursor.execute("ALTER TABLE users ADD COLUMN position TEXT")
except sqlite3.OperationalError:
    pass  # уже есть

conn.commit()
conn.close()
print("База обновлена: теперь есть name и position")