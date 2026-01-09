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

# Fallback timezone if we cannot infer from user/location:
DEFAULT_TZ = os.getenv("DEFAULT_TIMEZONE", "Asia/Dubai")

_last_update_id = None
_tzf = TimezoneFinder()


# -------------------------
# Telegram helpers
# -------------------------
def send_message(chat_id: int, text: str) -> None:
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )


# -------------------------
# Per-chat settings storage (timezone)
# Uses SQLite in brain.db (same DB you already use)
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
    # Validate tzname
    try:
        ZoneInfo(tzname)
    except Exception:
        raise ValueError(f"Invalid timezone: {tzname}")

    _cur.execute(
        "INSERT OR REPLACE INTO chat_prefs (chat_id, timezone) VALUES (?, ?)",
        (str(chat_id), tzname),
    )
    _conn.commit()


def try_autodetect_timezone_from_location(chat_id: int, msg: dict) -> bool:
    """
    If user shares a Telegram 'location', infer timezone and store it.
    Returns True if timezone was set.
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
        set_chat_timezone(chat_id, tzname)
        send_message(chat_id, f"Timezone detected and saved: {tzname}")
        return True

    return False


def try_set_timezone_from_text(chat_id: int, user_text: str) -> bool:
    """
    Natural language timezone setting:
      - "my timezone is Asia/Dubai"
      - "set timezone to Europe/London"
    Returns True if set.
    """
    t = user_text.strip()

    # Look for an IANA timezone pattern like "Europe/London"
    m = re.search(r"\b([A-Za-z]+\/[A-Za-z_\-]+)\b", t)
    if not m:
        return False

    # Only treat it as intent if user mentions timezone keywords
    intent_keywords = ["timezone", "time zone", "tz"]
    if not any(k in t.lower() for k in intent_keywords):
        return False

    tzname = m.group(1)
    try:
        set_chat_timezone(chat_id, tzname)
        send_message(chat_id, f"Saved timezone for this chat: {tzname}")
        return True
    except Exception:
        send_message(chat_id, f"That timezone does not look valid: {tzname}. Example: Asia/Dubai or Europe/London")
        return True


# -------------------------
# Natural-language reminders
# -------------------------
_REMINDER_INTENT = [
    "remind me",
    "set a reminder",
    "set reminder",
    "reminder",
    "don't let me forget",
    "dont let me forget",
    "please remind me",
]


def try_parse_reminder(user_text: str, tzname: str):
    """
    Returns (due_at_utc_iso, reminder_text_clean, local_dt_str) if reminder detected and parsed
    else None.

    - tzname is per-chat timezone
    - we store due_at as UTC ISO string (naive UTC), consistent with reminders.py
    """
    text = user_text.strip()
    lower = text.lower()

    if not any(k in lower for k in _REMINDER_INTENT):
        return None

    # Parse date/time using dateparser with local timezone context
    settings = {
        "PREFER_DATES_FROM": "future",
        "TIMEZONE": tzname,
        "RETURN_AS_TIMEZONE_AWARE": True,
    }

    dt = dateparser.parse(text, settings=settings)
    if not dt:
        return None

    # Convert to UTC ISO (naive) for DB storage
    dt_utc = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    due_at = dt_utc.isoformat()

    # Keep reminder message useful (best-effort):
    # Strip leading intent phrase "remind me" etc, but keep the rest intact.
    reminder_text = text
    for k in _REMINDER_INTENT:
        idx = lower.find(k)
        if idx != -1:
            reminder_text = text[idx + len(k):].strip(" ,:-")
            if reminder_text:
                break

    if not reminder_text:
        reminder_text = text

    # Also produce a user-friendly local time string
    try:
        local_dt = dt.astimezone(ZoneInfo(tzname))
        local_dt_str = local_dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        local_dt_str = dt.strftime("%Y-%m-%d %H:%M")

    return due_at, reminder_text, f"{local_dt_str} ({tzname})"


# -------------------------
# Linking commands (optional)
# -------------------------
def handle_linking_commands(chat_id: int, user_text: str) -> bool:
    lower = user_text.strip().lower()

    if lower in ("/help", "/start"):
        send_message(
            chat_id,
            "You can talk naturally.\n\n"
            "Reminders (natural language):\n"
            "- Remind me tomorrow at 9am to send the invoice\n"
            "- Don't let me forget in 30 minutes to call Ali\n\n"
            "Timezone:\n"
            "- Share a location in Telegram to auto-detect\n"
            "- Or say: My timezone is Europe/London\n\n"
            "Optional linking:\n"
            "/link  (create a shared memory code)\n"
            "/join <code>\n"
            "/unlink\n",
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


# -------------------------
# Main loop
# -------------------------
def start_telegram() -> None:
    global _last_update_id

    print("Telegram bot started (polling mode)")

    while True:
        # Avoid unbound local errors in exception logging
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

                # Timezone auto-detection from Telegram location message (one-tap share)
                # If the message has a location, we set timezone and continue.
                if try_autodetect_timezone_from_location(chat_id, msg):
                    continue

                user_text = msg.get("text")
                if not user_text:
                    # ignore non-text messages (stickers, photos, etc.)
                    continue

                user_text = user_text.strip()
                if not user_text:
                    continue

                print(f"[TG] chat_id={chat_id} text={user_text!r}")

                # Natural language timezone setting
                if try_set_timezone_from_text(chat_id, user_text):
                    continue

                # Optional linking commands (kept explicit; remove if you want)
                if handle_linking_commands(chat_id, user_text):
                    continue

                # Determine namespace for isolation
                namespace = get_namespace_for_chat(chat_id)

                # Natural-language reminder handling (no model call)
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
                    send_message(chat_id, f"Confirmed. I’ll remind you at {local_dt_str}.\nReminder: {reminder_text}")
                    continue

                # Memory context (isolated by namespace)
                memories = query_memory(user_text, namespace=namespace, n_results=MAX_MEMORY_SNIPPETS)
                mem_text = "\n".join(memories[:MAX_MEMORY_SNIPPETS]).strip()

                system = (
                    "You are Mina's personal AI brain.\n"
                    "Be direct, concise, and action-oriented.\n"
                    "Do not repeat an intro message.\n"
                    "If the user asks to set a reminder, comply by confirming the time and message.\n"
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

                # Persist memory with namespace
                add_memory(user_text, {"type": "telegram_user", "chat_id": str(chat_id), "namespace": namespace})
                add_memory(reply, {"type": "telegram_ai", "chat_id": str(chat_id), "namespace": namespace})

                send_message(chat_id, reply)

        except Exception as e:
            print(f"[Telegram loop error] {e} | chat_id={chat_id} | user_text={repr(user_text)}")

        time.sleep(POLL_SLEEP_SECONDS)
