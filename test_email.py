"""
Test script for email notifications
"""
from dotenv import load_dotenv
load_dotenv()

import os
from utils.email_notifications import send_feeding_notification

print("=" * 50)
print("Email Configuration Test")
print("=" * 50)
print(f"EMAIL_ENABLED: {os.getenv('EMAIL_ENABLED')}")
print(f"SMTP_SERVER: {os.getenv('SMTP_SERVER')}")
print(f"SMTP_PORT: {os.getenv('SMTP_PORT')}")
print(f"SMTP_USERNAME: {os.getenv('SMTP_USERNAME')}")
print(f"EMAIL_FROM: {os.getenv('EMAIL_FROM')}")
print("=" * 50)
print()
print("Sending test email...")

result = send_feeding_notification(
    user_email='joevinansoc870@gmail.com',
    username='Test User',
    amount_grams=50,
    trigger_type='manual'
)

if result:
    print("SUCCESS: Email sent successfully! Check your inbox.")
else:
    print("FAILED: Email could not be sent. Check configuration.")
