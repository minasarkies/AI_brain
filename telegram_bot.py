import os
import time
import requests
import datetime
from openai import OpenAI

from memory import add_memory, query_memory
from links import get_namespace_for_chat, create_link_for_chat, join_link_for_chat, unlink_chat
from reminders import add_reminder

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN")
if not OPENAI_KEY:
    raise ValueError("Missing OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_KEY)
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
MAX_MEMORY_SNIPPETS = int(os.getenv("MAX_MEMORY_SNIPPETS", "5"))
OPENAI_TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "25"))

_last_update_id = None


def send_message(chat_id: int, text: str) -> None:
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )


def _handle_commands(chat_id: int, user_text: str) -> bool:
    """
    Return True if a command was handled (caller should continue).
    """
    lower = user_text.strip().lower()

    if lower in ("/help", "help", "/start"):
        send_message(
            chat_id,
            "Commands:\n"
            "/remind <seconds> <message>\n"
            "  Example: /remind 30 test this\n"
            "/link  (create a shared memory code)\n"
            "/join <code> (join shared memory)\n"
            "/unlink (return to private memory)\n"
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

    if lower.startswith("/remind"):
        parts = user_text.split(maxsplit=2)
        if len(parts) < 3:
            send_message(chat_id, "Usage: /remind <seconds> <message>\nExample: /remind 30 test this")
            return True

        try:
            seconds = int(parts[1])
            msg = parts[2].strip()
            if seconds <= 0 or not msg:
                raise ValueError("Invalid reminder format")

            due_at = (datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)).isoformat()
            add_reminder(chat_id=chat_id, text=msg, due_at=due_at)
            send_message(chat_id, f"Reminder set for {seconds} seconds from now: {msg}")
        except Exception:
            send_message(chat_id, "Usage: /remind <seconds> <message>\nExample: /remind 30 test this")
        return True

    return False


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

                user_text = msg.get("text")
                if not user_text:
                    continue

                user_text = user_text.strip()
                if not user_text:
                    continue

                print(f"[TG] chat_id={chat_id} text={user_text!r}")

                # Deterministic commands first (no model)
                if _handle_commands(chat_id, user_text):
                    continue

                namespace = get_namespace_for_chat(chat_id)

                memories = query_memory(user_text, namespace=namespace, n_results=MAX_MEMORY_SNIPPETS)
                mem_text = "\n".join(memories[:MAX_MEMORY_SNIPPETS]).strip()

                system = (
                    "You are Mina's personal AI brain.\n"
                    "Be direct, concise, and action-oriented.\n"
                    "Do not repeat an intro message.\n"
                    "If the user wants a reminder, instruct them to use: /remind <seconds> <message>.\n"
                )

                prompt = f"Relevant memory:\n{mem_text}\n\nUser message:\n{user_text}"

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

        time.sleep(0.5)
