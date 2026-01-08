# AI_brain
setup.py → installs dependencies and prepares folders

run.py → starts the backend automatically

main.py, memory.py, reminders.py, and all helper modules → access credentials via os.getenv("VARIABLE_NAME")

Railway environment variables → used for OpenAI, Twilio, Outlook, Zoho, etc.

No secrets are hard-coded or stored in the repo