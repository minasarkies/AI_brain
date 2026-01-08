import sqlite3
import datetime

conn = sqlite3.connect("brain.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY,
    text TEXT,
    due_at TEXT,
    sent INTEGER DEFAULT 0
)
""")
conn.commit()

def add_reminder(text: str, due_at: str):
    cursor.execute("INSERT INTO reminders (text, due_at) VALUES (?, ?)", (text, due_at))
    conn.commit()

def check_due_reminders():
    now = datetime.datetime.utcnow().isoformat()
    cursor.execute("SELECT id, text FROM reminders WHERE sent = 0 AND due_at <= ?", (now,))
    results = cursor.fetchall()
    for r in results:
        print(f"[REMINDER DUE] {r[1]}")
        cursor.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (r[0],))
    conn.commit()
