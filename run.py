import threading
import time

from telegram_bot import start_telegram
from main import start_email_loop
from reminders import start_reminders

if __name__ == "__main__":
    print("AI Brain starting (Telegram mode)")

    threading.Thread(target=start_telegram, daemon=True).start()
    #threading.Thread(target=start_email_loop, daemon=True).start()
    threading.Thread(target=start_reminders, daemon=True).start()

    while True:
        time.sleep(60)
