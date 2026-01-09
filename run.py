import threading
import time

from telegram_bot import start_telegram
from reminders import start_reminders

# If you have email enabled, you can add it back later:
# from main import start_email_loop

if __name__ == "__main__":
    print("AI Brain starting (Telegram + Reminders)")

    threading.Thread(target=start_telegram, daemon=True).start()
    threading.Thread(target=start_reminders, daemon=True).start()

    # If needed later:
    # threading.Thread(target=start_email_loop, daemon=True).start()

    while True:
        time.sleep(60)
