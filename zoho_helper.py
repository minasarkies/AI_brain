import os
import requests

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
ZOHO_ACCOUNT_ID = os.getenv("ZOHO_ACCOUNT_ID")  # Add your Zoho account ID in Railway env

def get_access_token():
    url = "https://accounts.zoho.com/oauth/v2/token"
    params = {
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token"
    }
    resp = requests.post(url, params=params)
    return resp.json().get("access_token")

def fetch_emails(top=5):
    token = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    url = f"https://mail.zoho.com/api/accounts/{ZOHO_ACCOUNT_ID}/messages?limit={top}"
    resp = requests.get(url, headers=headers)
    return resp.json().get("data", [])

def send_email(to_address, subject, body):
    token = get_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}", "Content-Type": "application/json"}
    url = f"https://mail.zoho.com/api/accounts/{ZOHO_ACCOUNT_ID}/messages"
    payload = {
        "fromAddress": "mina.sarkies@techinspira.com",  # replace with your Zoho email
        "toAddress": to_address,
        "subject": subject,
        "content": body
    }
    requests.post(url, headers=headers, json=payload)
