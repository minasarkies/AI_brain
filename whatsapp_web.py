from playwright.sync_api import sync_playwright
from memory import add_memory, query_memory
import openai
import time
import os

openai.api_key = os.getenv("OPENAI_API_KEY")

def start_whatsapp():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://web.whatsapp.com")

        print("Scan QR code manually on WhatsApp Web...")
        time.sleep(15)  # give time to scan QR code

        while True:
            messages = page.query_selector_all(".message-in")  # incoming messages
            for msg in messages:
                text = msg.inner_text()
                if text:
                    # query memory
                    context_mem = "\n".join(query_memory(text))
                    prompt = f"Relevant memory:\n{context_mem}\n\nUser says: {text}"

                    response = openai.ChatCompletion.create(
                        model="gpt-4.1-mini",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    reply = response.choices[0].message["content"]

                    # store memory
                    add_memory(text, meta={"type": "user_input"})
                    add_memory(reply, meta={"type": "ai_response"})

                    # send reply
                    msg_box = page.query_selector("div[contenteditable='true']")
                    msg_box.fill(reply)
                    page.keyboard.press("Enter")
            time.sleep(5)
