"""
WhatsApp Notifications using Twilio WhatsApp API
================================================
Setup (Free Sandbox):
1. Go to https://www.twilio.com/try-twilio (free account)
2. Go to Messaging → Try it out → Send a WhatsApp message
3. Your sandbox number: whatsapp:+14155238886
4. Student sends "join <your-word>" to that number to opt in
5. Add to .env:
   TWILIO_ACCOUNT_SID=your_sid
   TWILIO_AUTH_TOKEN=your_token
   TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
"""

import os
from logger import logger
from dotenv import load_dotenv

load_dotenv()

TWILIO_SID       = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN     = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WA_FROM   = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")


# ── Message Templates ─────────────────────────────────────────────
def _status_message(complaint_id: str, status: str, category: str, location: str) -> str:
    emoji = {
        "Pending":     "⏳",
        "In Progress": "🔧",
        "Resolved":    "✅",
        "Rejected":    "❌",
        "Reopened":    "🔄",
        "Escalated":   "🚨"
    }.get(status, "📋")

    return (
        f"*Smart College Civic Detector* 🏫\n\n"
        f"{emoji} *Complaint Update*\n\n"
        f"📋 ID: `{complaint_id}`\n"
        f"📂 Category: {category}\n"
        f"📍 Location: {location}\n"
        f"🔄 New Status: *{status}*\n\n"
        f"Track your complaint:\n"
        f"http://localhost:3000/track/{complaint_id}\n\n"
        f"_Smart College Civic Detector_"
    )


def _submission_message(complaint_id: str, category: str, location: str, ai_priority: str) -> str:
    return (
        f"*Smart College Civic Detector* 🏫\n\n"
        f"✅ *Complaint Submitted Successfully!*\n\n"
        f"📋 ID: `{complaint_id}`\n"
        f"📂 Category: {category}\n"
        f"📍 Location: {location}\n"
        f"🤖 AI Priority: *{ai_priority}*\n\n"
        f"Your complaint has been received and assigned to the concerned department.\n\n"
        f"Track status:\n"
        f"http://localhost:3000/track/{complaint_id}\n\n"
        f"_Smart College Civic Detector_"
    )


def _escalation_message(complaint_id: str, category: str, location: str) -> str:
    return (
        f"*Smart College Civic Detector* 🏫\n\n"
        f"🚨 *Complaint Escalated!*\n\n"
        f"📋 ID: `{complaint_id}`\n"
        f"📂 Category: {category}\n"
        f"📍 Location: {location}\n\n"
        f"⚠️ Your complaint has been escalated to *Emergency* priority "
        f"because it was not resolved in time.\n\n"
        f"The administration has been notified.\n\n"
        f"_Smart College Civic Detector_"
    )


def _resolved_message(complaint_id: str, category: str, resolution_hours: float) -> str:
    return (
        f"*Smart College Civic Detector* 🏫\n\n"
        f"🎉 *Complaint Resolved!*\n\n"
        f"📋 ID: `{complaint_id}`\n"
        f"📂 Category: {category}\n"
        f"⏱️ Resolved in: *{resolution_hours} hours*\n\n"
        f"Thank you for reporting this issue. "
        f"Your campus has been improved! 🏫\n\n"
        f"Rate your experience:\n"
        f"http://localhost:3000/track/{complaint_id}\n\n"
        f"_Smart College Civic Detector_"
    )


# ── Core Send Function ────────────────────────────────────────────
def send_whatsapp(to_phone: str, message: str) -> bool:
    """
    Send WhatsApp message to a phone number.
    to_phone format: "9284959966" or "+919284959966"
    Returns True if sent, False if failed.
    """
    if not TWILIO_SID or not TWILIO_TOKEN:
        logger.warning("WhatsApp not configured — add TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN to .env")
        return False

    if not to_phone:
        logger.warning("WhatsApp: no phone number provided")
        return False

    try:
        from twilio.rest import Client

        # Format phone number
        phone = to_phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = "+91" + phone  # Default India country code
        to_wa = f"whatsapp:{phone}"

        client = Client(TWILIO_SID, TWILIO_TOKEN)
        msg = client.messages.create(
            body=message,
            from_=TWILIO_WA_FROM,
            to=to_wa
        )
        logger.info(f"WhatsApp sent to {phone} | SID: {msg.sid}")
        return True

    except ImportError:
        logger.error("Twilio not installed. Run: pip install twilio")
        return False
    except Exception as e:
        logger.error(f"WhatsApp failed to {to_phone}: {e}")
        return False


# ── Convenience Functions ─────────────────────────────────────────
def notify_complaint_submitted(phone: str, complaint_id: str, category: str,
                                location: str, ai_priority: str):
    """Send WhatsApp when student submits a complaint."""
    msg = _submission_message(complaint_id, category, location, ai_priority)
    send_whatsapp(phone, msg)


def notify_status_changed(phone: str, complaint_id: str, status: str,
                           category: str, location: str):
    """Send WhatsApp when admin changes complaint status."""
    msg = _status_message(complaint_id, status, category, location)
    send_whatsapp(phone, msg)


def notify_resolved(phone: str, complaint_id: str, category: str,
                    resolution_hours: float):
    """Send WhatsApp when complaint is resolved."""
    msg = _resolved_message(complaint_id, category, resolution_hours)
    send_whatsapp(phone, msg)


def notify_escalated(phone: str, complaint_id: str, category: str, location: str):
    """Send WhatsApp when complaint is escalated to Emergency."""
    msg = _escalation_message(complaint_id, category, location)
    send_whatsapp(phone, msg)