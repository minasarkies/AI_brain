import os
import time
import requests
from openai import OpenAI
import datetime
from reminders import add_reminder

from memory import add_memory, query_memory

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN in environment variables")
if not OPENAI_KEY:
    raise ValueError("Missing OPENAI_API_KEY in environment variables")

client = OpenAI(api_key=OPENAI_KEY)

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Persist offset in memory (in-process). Optional: persist to file/DB later.
_last_update_id = None

# Keep replies snappy
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
MAX_MEMORY_SNIPPETS = 5
OPENAI_TIMEOUT_SECONDS = 25


def _flatten_docs(docs):
    # Chroma often returns nested lists: [[...]]
    if docs and isinstance(docs[0], list):
        return docs[0]
    return docs or []


def send_message(chat_id: int, text: str):
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )


def start_telegram():
    global _last_update_id

    print("Telegram bot started (polling mode)")

    while True:
        try:
            params = {"timeout": 30}
            if _last_update_id is not None:
                params["offset"] = _last_update_id + 1

            r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
            data = r.json()
            # --- COMMAND: /remind <seconds> <text> ---
            # Examples:
            # /remind 30 test this
            # /remind 3600 follow up with Sam
            if user_text.lower().startswith("/remind"):
                parts = user_text.split(maxsplit=2)
                if len(parts) < 3:
                    send_message(chat_id, "Usage: /remind <seconds> <message>\nExample: /remind 30 test this")
                    continue

                try:
                    seconds = int(parts[1])
                    reminder_text = parts[2].strip()
                    due_at = (datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)).isoformat()

                    add_reminder(reminder_text, due_at)
                    send_message(chat_id, f"Reminder set for {seconds} seconds from now: {reminder_text}")
                except ValueError:
                    send_message(chat_id, "Seconds must be a number. Example: /remind 30 test this")
                continue

            for update in data.get("result", []):
                _last_update_id = update["update_id"]

                msg = update.get("message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                user_text = msg.get("text", "").strip()

                # Ignore non-text messages for now
                if not user_text:
                    continue

                # Quick debug log so you can confirm real content is received
                print(f"[TG] chat_id={chat_id} text={user_text!r}")

                # Retrieve memory based on the user text
                mem_docs = _flatten_docs(query_memory(user_text, n_results=MAX_MEMORY_SNIPPETS))
                mem_text = "\n".join(mem_docs[:MAX_MEMORY_SNIPPETS]).strip()

                system = (
                    "You are Mina's personal AI brain.\n"
                    "Be direct, concise, and action-oriented.\n"
                    "Do not repeat an intro message. Answer the user's latest message.\n"
                    "If you need clarification, ask ONE short question.\n"
                )

                # IMPORTANT: include the real user text here; this is where many bugs occur
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Relevant memory:\n{mem_text}\n\nUser message:\n{user_text}"},
                ]

                # Call OpenAI
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    temperature=0.4,
                    timeout=OPENAI_TIMEOUT_SECONDS,
                )
                reply = (resp.choices[0].message.content or "").strip()

                # Fallback if empty
                if not reply:
                    reply = "I received your message. Please rephrase it in one sentence."

                # Store interaction in memory (optional)
                add_memory(user_text, {"type": "telegram_user", "chat_id": str(chat_id)})
                add_memory(reply, {"type": "telegram_ai", "chat_id": str(chat_id)})

                send_message(chat_id, reply)

        except Exception as e:
            # Never kill the bot; log and continue
            print(f"[Telegram loop error] {e}")

        time.sleep(0.5)
