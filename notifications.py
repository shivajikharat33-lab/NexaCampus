import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from database import db
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, FROM_EMAIL, TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM
from logger import logger

notifications = db["notifications"]
notifications.create_index("student_id")
notifications.create_index("is_read")
notifications.create_index("created_at")


def create_notification(student_id, complaint_id, message, notif_type="status_update"):
    notifications.insert_one({
        "student_id": student_id,
        "complaint_id": complaint_id,
        "message": message,
        "type": notif_type,
        "is_read": False,
        "created_at": datetime.now(timezone.utc)
    })


def send_email(to_email, subject, body):
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("Email not configured — skipping")
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = FROM_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject
        html = f"""<html><body style="font-family:Arial,sans-serif;padding:20px">
          <div style="max-width:500px;margin:auto;border:1px solid #eee;border-radius:8px;padding:24px">
            <h2 style="color:#2563eb">Smart College Civic Detector</h2>
            <p>{body}</p>
            <hr style="border:none;border-top:1px solid #eee;margin:20px 0">
            <p style="font-size:12px;color:#888">Automated notification. Do not reply.</p>
          </div></body></html>"""
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())
        logger.info(f"Email sent to {to_email}")
    except Exception as e:
        logger.error(f"Email failed to {to_email}: {e}")


def send_sms(to_phone, message):
    if not TWILIO_SID or not TWILIO_TOKEN or not to_phone:
        logger.warning("SMS not configured — skipping")
        return
    try:
        from twilio.rest import Client
        Client(TWILIO_SID, TWILIO_TOKEN).messages.create(
            body=message, from_=TWILIO_FROM, to=to_phone
        )
        logger.info(f"SMS sent to {to_phone}")
    except Exception as e:
        logger.error(f"SMS failed to {to_phone}: {e}")


def notify(student_id, complaint_id, message, notif_type, email=None, phone=None, email_subject=None):
    create_notification(student_id, complaint_id, message, notif_type)
    if email:
        send_email(email, email_subject or "Complaint Update", message)
    if phone:
        send_sms(phone, f"[Civic Detector] {message}")