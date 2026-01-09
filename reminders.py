import os
import time
import sqlite3
import datetime
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}" if TELEGRAM_TOKEN else None

DB_PATH = os.getenv("BRAIN_DB_PATH", "brain.db")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()


def _table_exists(name: str) -> bool:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cursor.fetchone() is not None


def _get_columns(table: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _ensure_schema() -> None:
    if not _table_exists("reminders"):
        cursor.execute("""
        CREATE TABLE reminders (
            id INTEGER PRIMARY KEY,
            chat_id TEXT NOT NULL,
            text TEXT NOT NULL,
            due_at TEXT NOT NULL,          -- UTC ISO string (naive)
            timezone TEXT,
            due_local TEXT,
            sent INTEGER DEFAULT 0
        )
        """)
        conn.commit()
        return

    cols = _get_columns("reminders")

    if "chat_id" not in cols:
        cursor.execute("ALTER TABLE reminders ADD COLUMN chat_id TEXT")
        conn.commit()

    if "text" not in cols:
        cursor.execute("ALTER TABLE reminders ADD COLUMN text TEXT")
        conn.commit()

    if "due_at" not in cols:
        cursor.execute("ALTER TABLE reminders ADD COLUMN due_at TEXT")
        conn.commit()

    if "timezone" not in cols:
        cursor.execute("ALTER TABLE reminders ADD COLUMN timezone TEXT")
        conn.commit()

    if "due_local" not in cols:
        cursor.execute("ALTER TABLE reminders ADD COLUMN due_local TEXT")
        conn.commit()

    if "sent" not in cols:
        cursor.execute("ALTER TABLE reminders ADD COLUMN sent INTEGER DEFAULT 0")
        conn.commit()


_ensure_schema()
print(f"Reminder worker token loaded: {bool(TELEGRAM_TOKEN)}")


def add_reminder(chat_id: int, text: str, due_at: str, timezone: str | None = None, due_local: str | None = None) -> None:
    cursor.execute(
        "INSERT INTO reminders (chat_id, text, due_at, timezone, due_local, sent) VALUES (?, ?, ?, ?, ?, 0)",
        (str(chat_id), text, due_at, timezone, due_local),
    )
    conn.commit()


def _send_telegram(chat_id: str, text: str) -> None:
    if not API_URL:
        print(f"[REMINDER] TELEGRAM_BOT_TOKEN missing. chat_id={chat_id} text={text}")
        return

    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": int(chat_id), "text": text},
        timeout=15,
    )


def start_reminders() -> None:
    print("Reminder loop started")

    while True:
        try:
            now = datetime.datetime.utcnow().isoformat()

            cursor.execute(
                "SELECT id, chat_id, text, due_local, timezone FROM reminders "
                "WHERE sent = 0 AND due_at <= ? AND chat_id IS NOT NULL",
                (now,),
            )
            rows = cursor.fetchall()

            if rows:
                print(f"[REMINDER-DUE] found={len(rows)} now_utc={now}")

            for reminder_id, chat_id, text, due_local, timezone in rows:
                if due_local:
                    msg = f"⏰ Reminder ({due_local}): {text}"
                elif timezone:
                    msg = f"⏰ Reminder ({timezone}): {text}"
                else:
                    msg = f"⏰ Reminder: {text}"

                _send_telegram(chat_id, msg)
                print(f"[REMINDER-SENT] id={reminder_id} chat_id={chat_id}")

                cursor.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
                conn.commit()

        except Exception as e:
            print(f"[Reminder loop error] {e}")

        time.sleep(2)
