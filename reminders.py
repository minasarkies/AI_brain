import os
import time
import sqlite3
import datetime
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}" if TELEGRAM_TOKEN else None

conn = sqlite3.connect("brain.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY,
    chat_id TEXT NOT NULL,
    text TEXT NOT NULL,
    due_at TEXT NOT NULL,
    sent INTEGER DEFAULT 0
)
""")
conn.commit()


def add_reminder(chat_id: int, text: str, due_at: str) -> None:
    cursor.execute(
        "INSERT INTO reminders (chat_id, text, due_at) VALUES (?, ?, ?)",
        (str(chat_id), text, due_at),
    )
    conn.commit()


def _send_telegram(chat_id: str, text: str) -> None:
    if not API_URL:
        # If token missing, fail silently (but don't crash worker)
        print(f"[REMINDER] TELEGRAM_BOT_TOKEN missing. Reminder for chat_id={chat_id}: {text}")
        return

    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": int(chat_id), "text": f"⏰ Reminder: {text}"},
        timeout=15,
    )


def start_reminders() -> None:
    print("Reminder loop started")

    while True:
        try:
            now = datetime.datetime.utcnow().isoformat()
            cursor.execute(
                "SELECT id, chat_id, text FROM reminders WHERE sent = 0 AND due_at <= ?",
                (now,),
            )
            rows = cursor.fetchall()

            for reminder_id, chat_id, text in rows:
                _send_telegram(chat_id, text)
                cursor.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
                conn.commit()

        except Exception as e:
            print(f"[Reminder loop error] {e}")

        time.sleep(5)
