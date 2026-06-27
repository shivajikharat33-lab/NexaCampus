import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from database import db

# ── File + Console Logger ─────────────────────────────────────────
os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("civic")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Rotating file — 5MB max, keep 5 backups
file_handler = RotatingFileHandler(
    "logs/app.log", maxBytes=5 * 1024 * 1024, backupCount=5
)
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.INFO)

error_handler = RotatingFileHandler(
    "logs/errors.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
error_handler.setFormatter(formatter)
error_handler.setLevel(logging.ERROR)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.DEBUG)

logger.addHandler(file_handler)
logger.addHandler(error_handler)
logger.addHandler(console_handler)


# ── Audit Log (MongoDB) ───────────────────────────────────────────
audit_logs = db["audit_logs"]
audit_logs.create_index("actor_email")
audit_logs.create_index("action")
audit_logs.create_index("created_at")
audit_logs.create_index("complaint_id")


def log_audit(
    actor_email: str,
    action: str,
    target: str = None,
    complaint_id: str = None,
    details: dict = None
):
    """
    Record an admin or system action to the audit_logs collection.
    Examples:
        log_audit("admin@x.com", "STATUS_CHANGED", complaint_id="CMP-123", details={"to": "Resolved"})
        log_audit("admin@x.com", "USER_ROLE_CHANGED", target="student@x.com", details={"role": "admin"})
    """
    entry = {
        "actor_email": actor_email,
        "action": action,
        "target": target,
        "complaint_id": complaint_id,
        "details": details or {},
        "created_at": datetime.now(timezone.utc)
    }
    try:
        audit_logs.insert_one(entry)
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")

    logger.info(f"AUDIT | {actor_email} | {action} | target={target} | complaint={complaint_id}")