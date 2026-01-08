import imaplib, smtplib, email
from email.mime.text import MIMEText
import os

OUTLOOK_EMAIL = os.getenv("OUTLOOK_EMAIL")
OUTLOOK_PASSWORD = os.getenv("OUTLOOK_APP_PASSWORD")  # App Password

# Fetch emails
def fetch_emails(folder="INBOX", top=5):
    mail = imaplib.IMAP4_SSL("outlook.office365.com")
    mail.login(OUTLOOK_EMAIL, OUTLOOK_PASSWORD)
    mail.select(folder)
    _, data = mail.search(None, "ALL")
    email_ids = data[0].split()[-top:]
    messages = []
    for eid in email_ids:
        _, msg_data = mail.fetch(eid, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body += part.get_payload(decode=True).decode()
        else:
            body = msg.get_payload(decode=True).decode()
        messages.append({"subject": msg["subject"], "body": {"content": body}})
    mail.logout()
    return messages

# Send email
def send_email(to_address, subject, body):
    msg = MIMEText(body)
    msg["From"] = OUTLOOK_EMAIL
    msg["To"] = to_address
    msg["Subject"] = subject
    with smtplib.SMTP("smtp.office365.com", 587) as server:
        server.starttls()
        server.login(OUTLOOK_EMAIL, OUTLOOK_PASSWORD)
        server.send_message(msg)
