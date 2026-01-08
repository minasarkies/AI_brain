import requests
import time
import os
import openai

from memory import add_memory, query_memory
from reminders import add_reminder

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
openai.api_key = os.getenv("OPENAI_API_KEY")

API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

last_update_id = None

def send_message(chat_id, text):
    requests.post(
        f"{API_URL}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

def start_telegram():
    global last_update_id
    print("Telegram bot started")

    while True:
        params = {"timeout": 30}
        if last_update_id:
            params["offset"] = last_update_id + 1

        resp = requests.get(f"{API_URL}/getUpdates", params=params).json()

        for update in resp.get("result", []):
            last_update_id = update["update_id"]

            if "message" not in update:
                continue

            msg = update["message"]
            chat_id = msg["chat"]["id"]
            text = msg.get("text", "")

            if not text:
                continue

            # Memory context
            memories = query_memory(text)
            flat = memories[0] if memories and isinstance(memories[0], list) else memories
            context = "\n".join(query_memory(text))

            prompt = f"""
Relevant memory:
{context}

User message:
{text}
"""

            response = openai.ChatCompletion.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}]
            )

            reply = response.choices[0].message["content"]

            add_memory(text, {"type": "telegram_user"})
            add_memory(reply, {"type": "telegram_ai"})

            send_message(chat_id, reply)

        time.sleep(1)
