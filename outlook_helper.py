import os
import requests
from msal import ConfidentialClientApplication
from outlook_imap_smtp import fetch_emails, send_email

# Environment variables for Outlook API
OUTLOOK_CLIENT_ID = os.getenv("OUTLOOK_CLIENT_ID")
OUTLOOK_CLIENT_SECRET = os.getenv("OUTLOOK_CLIENT_SECRET")
OUTLOOK_TENANT_ID = os.getenv("OUTLOOK_TENANT_ID")
SCOPE = ["https://graph.microsoft.com/.default"]

# MSAL app for auth
app = ConfidentialClientApplication(
    OUTLOOK_CLIENT_ID,
    authority=f"https://login.microsoftonline.com/{OUTLOOK_TENANT_ID}",
    client_credential=OUTLOOK_CLIENT_SECRET
)

def get_access_token():
    result = app.acquire_token_for_client(scopes=SCOPE)
    return result.get("access_token")

def fetch_emails(folder="inbox", top=5):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages?$top={top}"
    resp = requests.get(url, headers=headers)
    return resp.json().get("value", [])

def send_email(to_address, subject, body):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = "https://graph.microsoft.com/v1.0/me/sendMail"
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_address}}]
        }
    }
    requests.post(url, headers=headers, json=payload)
