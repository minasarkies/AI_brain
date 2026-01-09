import os
import time
from openai import OpenAI

from memory import add_memory, query_memory

# If you are using Zoho only, import Zoho here.
# If you want email disabled for now, you can comment out the import and loop usage.
from zoho_helper import fetch_emails as fetch_zoho

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_KEY:
    raise ValueError("Missing OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_KEY)

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
EMAIL_POLL_INTERVAL = int(os.getenv("EMAIL_POLL_INTERVAL", "300"))


def start_email_loop() -> None:
    print("Email loop started (Zoho)")

    namespace = "email:default"

    while True:
        try:
            emails = fetch_zoho(top=5) or []

            for email_obj in emails:
                subject = email_obj.get("subject", "")
                body = ""

                # Zoho helper formats may vary; this keeps it defensive.
                if isinstance(email_obj.get("body"), dict):
                    body = email_obj.get("body", {}).get("content", "") or ""
                else:
                    body = email_obj.get("content", "") or email_obj.get("summary", "") or ""

                if not body.strip():
                    continue

                mem = query_memory(body, namespace=namespace, n_results=5)
                mem_text = "\n".join(mem).strip()

                system = "Draft a professional, concise email reply."
                prompt = f"Relevant memory:\n{mem_text}\n\nEmail subject:\n{subject}\n\nEmail body:\n{body}"

                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.4,
                    timeout=25,
                )

                draft = (resp.choices[0].message.content or "").strip()
                if not draft:
                    continue

                add_memory(body, {"type": "email_received", "namespace": namespace, "subject": subject})
                add_memory(draft, {"type": "email_draft", "namespace": namespace, "subject": subject})

        except Exception as e:
            print(f"[Email loop error] {e}")

        time.sleep(EMAIL_POLL_INTERVAL)
