import subprocess, threading, os
from whatsapp_web import start_whatsapp

# 1. Setup project
subprocess.run([os.sys.executable, "setup.py"])

# 2. Start WhatsApp Web listener in a thread
whatsapp_thread = threading.Thread(target=start_whatsapp, daemon=True)
whatsapp_thread.start()

# 3. Start FastAPI backend (emails, reminders, docs)
subprocess.run([os.sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"])
