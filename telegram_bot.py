import os
import time
import re
import datetime
from zoneinfo import ZoneInfo

import requests
import dateparser
from timezonefinder import TimezoneFinder
from openai import OpenAI

from memory import add_memory, query_memory
from reminders import add_reminder
from links import get_namespace_for_chat, create_link_for_chat, join_link_for_chat, unlink_chat

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN in environment variables")
if not OPENAI_KEY:
    raise ValueError("Missing OPENAI_API_KEY in environment variables")

client = OpenAI(api_key=OPENAI_KEY)
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
MAX_MEMORY_SNIPPETS = int(os.getenv("MAX_MEMORY_SNIPPETS", "5"))
OPENAI_TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "25"))
POLL_SLEEP_SECONDS = float(os.getenv("POLL_SLEEP_SECONDS", "0.5"))

DEFAULT_TZ = os.getenv("DEFAULT_TIMEZONE", "Asia/Dubai")

_last_update_id = None
_tzf = TimezoneFinder()

# Reminder intent phrases (natural language)
_REMINDER_INTENT = [
    "remind me",
    "set a reminder",
    "set reminder",
    "reminder",
    "don't let me forget",
    "dont let me forget",
    "please remind me",
]


def send_message(chat_id: int, text: str) -> None:
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )


# -------------------------
# Per-chat timezone (SQLite)
# -------------------------
import sqlite3
_DB_PATH = os.getenv("BRAIN_DB_PATH", "brain.db")
_conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
_cur = _conn.cursor()

_cur.execute("""
CREATE TABLE IF NOT EXISTS chat_prefs (
    chat_id TEXT PRIMARY KEY,
    timezone TEXT
)
""")
_conn.commit()


def get_chat_timezone(chat_id: int) -> str:
    _cur.execute("SELECT timezone FROM chat_prefs WHERE chat_id = ?", (str(chat_id),))
    row = _cur.fetchone()
    if row and row[0]:
        return row[0]
    return DEFAULT_TZ


def set_chat_timezone(chat_id: int, tzname: str) -> None:
    # Validate timezone string
    ZoneInfo(tzname)
    _cur.execute(
        "INSERT OR REPLACE INTO chat_prefs (chat_id, timezone) VALUES (?, ?)",
        (str(chat_id), tzname),
    )
    _conn.commit()


def try_autodetect_timezone_from_location(chat_id: int, msg: dict) -> bool:
    """
    If user shares a Telegram 'location', infer timezone from lat/lon and store it.
    """
    loc = msg.get("location")
    if not loc:
        return False

    lat = loc.get("latitude")
    lon = loc.get("longitude")
    if lat is None or lon is None:
        return False

    tzname = _tzf.timezone_at(lat=float(lat), lng=float(lon))
    if tzname:
        try:
            set_chat_timezone(chat_id, tzname)
            send_message(chat_id, f"Timezone detected and saved: {tzname}")
            return True
        except Exception:
            return False

    return False


def try_set_timezone_from_text(chat_id: int, user_text: str) -> bool:
    """
    Natural language timezone setting:
      - "my timezone is Asia/Dubai"
      - "set timezone to Europe/London"
    """
    t = user_text.strip()
    lower = t.lower()
    if not any(k in lower for k in ["timezone", "time zone", "tz"]):
        return False

    m = re.search(r"\b([A-Za-z]+\/[A-Za-z_\-]+)\b", t)
    if not m:
        return False

    tzname = m.group(1)
    try:
        set_chat_timezone(chat_id, tzname)
        send_message(chat_id, f"Saved timezone for this chat: {tzname}")
    except Exception:
        send_message(chat_id, f"Invalid timezone: {tzname}. Example: Asia/Dubai or Europe/London")
    return True


def handle_linking_commands(chat_id: int, user_text: str) -> bool:
    """
    Optional: shared memory linking.
    """
    lower = user_text.strip().lower()

    if lower in ("/help", "/start"):
        send_message(
            chat_id,
            "Talk naturally.\n\n"
            "Reminders examples:\n"
            "- Remind me in 10 seconds that this is a test\n"
            "- Remind me tomorrow at 9am to send the invoice\n\n"
            "Timezone:\n"
            "- Share a location to auto-detect\n"
            "- Or say: My timezone is Europe/London\n\n"
            "Optional linking:\n"
            "/link\n"
            "/join <code>\n"
            "/unlink\n"
        )
        return True

    if lower == "/link":
        code = create_link_for_chat(chat_id)
        send_message(chat_id, f"Link code created: {code}\nShare it and run /join {code} in the other chat.")
        return True

    if lower.startswith("/join "):
        parts = user_text.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            send_message(chat_id, "Usage: /join <code>")
            return True
        code = parts[1].strip()
        join_link_for_chat(chat_id, code)
        send_message(chat_id, f"Joined shared memory space: {code}")
        return True

    if lower == "/unlink":
        unlink_chat(chat_id)
        send_message(chat_id, "This chat is private again (no shared memory).")
        return True

    return False


def try_parse_reminder(user_text: str, tzname: str):
    """
    Returns (due_at_utc_iso, reminder_text, local_dt_str) if reminder detected and parsed, else None.

    - Stores due_at as UTC ISO string (naive)
    - local_dt_str used for user-facing confirmation and later reminder formatting
    """
    text = user_text.strip()
    lower = text.lower()

    if not any(k in lower for k in _REMINDER_INTENT):
        return None

    # Deterministic fallback: "in N seconds/minutes/hours/days"
    m = re.search(r"\bin\s+(\d+)\s*(second|seconds|minute|minutes|hour|hours|day|days)\b", lower)
    if m:
        n = int(m.group(1))
        unit = m.group(2)

        if "second" in unit:
            delta = datetime.timedelta(seconds=n)
        elif "minute" in unit:
            delta = datetime.timedelta(minutes=n)
        elif "hour" in unit:
            delta = datetime.timedelta(hours=n)
        else:
            delta = datetime.timedelta(days=n)

        now_local = datetime.datetime.now(ZoneInfo(tzname))
        dt_local = now_local + delta

        dt_utc = dt_local.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        due_at = dt_utc.isoformat()

        reminder_text = text
        for k in _REMINDER_INTENT:
            idx = lower.find(k)
            if idx != -1:
                reminder_text = text[idx + len(k):].strip(" ,:-")
                break
        if not reminder_text:
            reminder_text = text

        local_dt_str = dt_local.strftime("%Y-%m-%d %H:%M:%S")
        return due_at, reminder_text, f"{local_dt_str} ({tzname})"

    # dateparser fallback for everything else
    settings = {
        "PREFER_DATES_FROM": "future",
        "TIMEZONE": tzname,
        "RETURN_AS_TIMEZONE_AWARE": True,
    }
    dt = dateparser.parse(text, settings=settings)
    if not dt:
        return None

    dt_local = dt.astimezone(ZoneInfo(tzname))
    dt_utc = dt_local.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    due_at = dt_utc.isoformat()

    reminder_text = text
    for k in _REMINDER_INTENT:
        idx = lower.find(k)
        if idx != -1:
            reminder_text = text[idx + len(k):].strip(" ,:-")
            if reminder_text:
                break
    if not reminder_text:
        reminder_text = text

    local_dt_str = dt_local.strftime("%Y-%m-%d %H:%M:%S")
    return due_at, reminder_text, f"{local_dt_str} ({tzname})"


def start_telegram() -> None:
    global _last_update_id
    print("Telegram bot started (polling mode)")

    while True:
        chat_id = None
        user_text = None

        try:
            params = {"timeout": 30}
            if _last_update_id is not None:
                params["offset"] = _last_update_id + 1

            r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
            data = r.json()

            for update in data.get("result", []):
                _last_update_id = update.get("update_id", _last_update_id)

                msg = update.get("message")
                if not msg:
                    continue

                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                if chat_id is None:
                    continue

                # Location-based timezone autodetection
                if try_autodetect_timezone_from_location(chat_id, msg):
                    continue

                user_text = msg.get("text")
                if not user_text:
                    continue

                user_text = user_text.strip()
                if not user_text:
                    continue

                print(f"[TG] chat_id={chat_id} text={user_text!r}")

                # Natural language timezone set
                if try_set_timezone_from_text(chat_id, user_text):
                    continue

                # Optional linking commands
                if handle_linking_commands(chat_id, user_text):
                    continue

                # Determine isolation namespace
                namespace = get_namespace_for_chat(chat_id)

                # Natural language reminders (no model call)
                tzname = get_chat_timezone(chat_id)
                parsed = try_parse_reminder(user_text, tzname)
                if parsed:
                    due_at, reminder_text, local_dt_str = parsed
                    add_reminder(
                        chat_id=chat_id,
                        text=reminder_text,
                        due_at=due_at,
                        timezone=tzname,
                        due_local=local_dt_str,
                    )
                    print(f"[REMINDER-SET] chat_id={chat_id} due_at_utc={due_at} tz={tzname} text={reminder_text!r}")
                    send_message(chat_id, f"Confirmed. I’ll remind you at {local_dt_str}.\nReminder: {reminder_text}")
                    continue

                # Memory context (namespaced)
                memories = query_memory(user_text, namespace=namespace, n_results=MAX_MEMORY_SNIPPETS)
                mem_text = "\n".join(memories[:MAX_MEMORY_SNIPPETS]).strip()

                system = (
                    "You are Mina's personal AI brain.\n"
                    "Be direct, concise, and action-oriented.\n"
                    "Do not repeat an intro message.\n"
                    "If the user asks for reminders, comply by confirming time and message.\n"
                )

                prompt = (
                    f"Relevant memory:\n{mem_text}\n\n"
                    f"User timezone: {tzname}\n\n"
                    f"User message:\n{user_text}"
                )

                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.4,
                    timeout=OPENAI_TIMEOUT_SECONDS,
                )

                reply = (resp.choices[0].message.content or "").strip()
                if not reply:
                    reply = "I received your message. Please rephrase it in one sentence."

                add_memory(user_text, {"type": "telegram_user", "chat_id": str(chat_id), "namespace": namespace})
                add_memory(reply, {"type": "telegram_ai", "chat_id": str(chat_id), "namespace": namespace})

                send_message(chat_id, reply)

        except Exception as e:
            print(f"[Telegram loop error] {e} | chat_id={chat_id} | user_text={repr(user_text)}")

        time.sleep(POLL_SLEEP_SECONDS)
