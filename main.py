from fastapi import FastAPI
from memory import add_memory, query_memory
from reminders import check_due_reminders
from outlook_imap_smtp import fetch_emails, send_email
from zoho_helper import fetch_emails as fetch_zoho
import openai, threading, time, os

app = FastAPI()
openai.api_key = os.getenv("OPENAI_API_KEY")

# Background reminders
def reminder_loop():
    while True:
        check_due_reminders()
        time.sleep(60)

# Background email fetch & AI draft
def email_loop():
    while True:
        for email in fetch_outlook() + fetch_zoho():
            subject = email.get("subject")
            body = email.get("body", {}).get("content", "")
            context = "\n".join(query_memory(body))
            prompt = f"Relevant memory:\n{context}\n\nEmail content:\n{body}"
            response = openai.ChatCompletion.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}]
            )
            draft_reply = response.choices[0].message["content"]
            add_memory(body, meta={"type": "email_received"})
            add_memory(draft_reply, meta={"type": "email_draft"})
        time.sleep(300)

threading.Thread(target=reminder_loop, daemon=True).start()
threading.Thread(target=email_loop, daemon=True).start()
