import sqlite3

conn = sqlite3.connect("users.db")
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    gender TEXT,
    age INTEGER,
    weight REAL,
    goal TEXT,
    activity TEXT,
    diet_pref TEXT,
    health TEXT,
    equipment TEXT,
    target_metric TEXT
)
''')

conn.commit()
conn.close()
