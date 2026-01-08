import os
import time
from openai import OpenAI
import os


from memory import add_memory, query_memory
from outlook_imap_smtp import fetch_emails

# Load OpenAI key
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


EMAIL_POLL_INTERVAL = 300  # seconds (5 minutes)


def process_email(email_obj):
    """
    Takes a single email object and generates an AI draft reply.
    Stores both email content and AI draft into memory.
    """

    subject = email_obj.get("subject", "")
    body = email_obj.get("body", {}).get("content", "")

    if not body:
        return

    # Retrieve relevant memory
    memory_context = query_memory(body)
    memory_text = "\n".join(memory_context)

    prompt = f"""
You are my personal AI assistant.

Relevant memory:
{memory_text}

Incoming email:
Subject: {subject}

Body:
{body}

Draft a professional, concise reply.
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
    )
    reply = response.choices[0].message.content


    # Store in memory
    add_memory(body, {"type": "email_received", "subject": subject})
    add_memory(reply, {"type": "email_draft", "subject": subject})


def start_email_loop():
    """
    Background loop:
    - Polls Outlook inbox via IMAP
    - Generates AI draft replies
    - Stores everything in memory
    """

    print("📧 Email loop started (IMAP/SMTP)")

    while True:
        try:
            emails = fetch_emails(top=5)

            for email_obj in emails:
                process_email(email_obj)

        except Exception as e:
            # Never crash Railway
            print(f"[Email loop error] {e}")

        time.sleep(EMAIL_POLL_INTERVAL)
