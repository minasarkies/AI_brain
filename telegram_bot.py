# telegram_bot.py
import os
import time
import requests
import datetime
from openai import OpenAI

from memory import add_memory, query_memory
from reminders import add_reminder
from links import (
    get_namespace_for_chat,
    create_link_for_chat,
    join_link_for_chat,
    unlink_chat,
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN in environment variables")
if not OPENAI_KEY:
    raise ValueError("Missing OPENAI_API_KEY in environment variables")

client = OpenAI(api_key=OPENAI_KEY)

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Tuning knobs
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
MAX_MEMORY_SNIPPETS = int(os.getenv("MAX_MEMORY_SNIPPETS", "5"))
OPENAI_TIMEOUT_SECONDS = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "25"))
POLL_SLEEP_SECONDS = float(os.getenv("POLL_SLEEP_SECONDS", "0.5"))

# In-process update offset (optional: persist in DB later)
_last_update_id = None


def send_message(chat_id: int, text: str) -> None:
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )


def _parse_remind_command(user_text: str):
    """
    /remind <seconds> <message>
    Returns (seconds:int, message:str) or raises ValueError.
    """
    parts = user_text.split(maxsplit=2)
    if len(parts) < 3:
        raise ValueError("Usage: /remind <seconds> <message>")
    seconds = int(parts[1])
    message = parts[2].strip()
    if seconds <= 0:
        raise ValueError("Seconds must be > 0")
    if not message:
        raise ValueError("Reminder message cannot be empty")
    return seconds, message


def _build_prompt(namespace: str, user_text: str) -> list[dict]:
    mem_docs = query_memory(user_text, namespace=namespace, n_results=MAX_MEMORY_SNIPPETS)
    mem_text = "\n".join(mem_docs[:MAX_MEMORY_SNIPPETS]).strip()

    system = (
        "You are Mina's personal AI brain.\n"
        "Be direct, concise, and action-oriented.\n"
        "Do not repeat an intro message. Answer the user's latest message.\n"
        "If you need clarification, ask ONE short question.\n"
        "If the user requests a reminder, instruct them to use /remind <seconds> <message>.\n"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Namespace: {namespace}\n\nRelevant memory:\n{mem_text}\n\nUser message:\n{user_text}"},
    ]


def _handle_commands(chat_id: int, user_text: str) -> bool:
    """
    Returns True if handled (and the caller should continue), else False.
    """
    lower = user_text.lower().strip()

    # Help
    if lower in ("/help", "help"):
        send_message(
            chat_id,
            "Commands:\n"
            "/remind <seconds> <message>\n"
            "  Example: /remind 30 test this\n"
            "/link  (create a shared memory code)\n"
            "/join <code> (join shared memory)\n"
            "/unlink (return to private memory)\n",
        )
        return True

    # Reminders
    if lower.startswith("/remind"):
        try:
            seconds, msg = _parse_remind_command(user_text)
            due_at = (datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)).isoformat()

            # Store reminder; reminders.py should be updated to deliver to Telegram using chat_id
            # For now we store text with due_at; if your reminders table supports chat_id, include it there.
            add_reminder(msg, due_at)

            send_message(chat_id, f"Reminder set for {seconds} seconds from now: {msg}")
        except Exception as e:
            send_message(chat_id, f"Could not set reminder. {e}\nUsage: /remind <seconds> <message>")
        return True

    # Link / join / unlink for shared memory
    if lower == "/link":
        code = create_link_for_chat(chat_id)
        send_message(chat_id, f"Link code created: {code}\nShare this code and use /join {code} in another chat.")
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
        send_message(chat_id, "This chat is now private again (no shared memory).")
        return True

    return False


def start_telegram() -> None:
    global _last_update_id

    print("Telegram bot started (polling mode)")

    while True:
        # Define these each loop so exception logs never reference unbound locals
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
                    # Ignore stickers/photos/voice for now
                    continue

                user_text = user_text.strip()
                if not user_text:
                    continue

                # Debug: confirm correct input is received
                print(f"[TG] chat_id={chat_id} text={user_text!r}")

                # Commands are handled deterministically (no OpenAI needed)
                if _handle_commands(chat_id, user_text):
                    continue

                # Namespace isolation (private per chat unless joined via link code)
                namespace = get_namespace_for_chat(chat_id)

                # Build prompt with namespace + filtered memory
                messages = _build_prompt(namespace, user_text)

                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    temperature=0.4,
                    timeout=OPENAI_TIMEOUT_SECONDS,
                )
                reply = (resp.choices[0].message.content or "").strip()
                if not reply:
                    reply = "I received your message. Please rephrase it in one sentence."

                # Store memory in the correct namespace
                add_memory(user_text, {"type": "telegram_user", "chat_id": str(chat_id), "namespace": namespace})
                add_memory(reply, {"type": "telegram_ai", "chat_id": str(chat_id), "namespace": namespace})

                send_message(chat_id, reply)

        except Exception as e:
            print(f"[Telegram loop error] {e} | chat_id={chat_id} | user_text={repr(user_text)}")

        time.sleep(POLL_SLEEP_SECONDS)
