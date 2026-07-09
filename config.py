from dotenv import load_dotenv
import os

load_dotenv()

# ── JWT ───────────────────────────────────────────────────────────
SECRET_KEY            = os.getenv("SECRET_KEY", "shivaji_secret_key_2026")
REFRESH_SECRET_KEY    = os.getenv("REFRESH_SECRET_KEY", "shivaji_refresh_key_2026")
ALGORITHM             = "HS256"
ACCESS_TOKEN_EXPIRE   = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", 24))
REFRESH_TOKEN_EXPIRE  = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

# ── MongoDB ───────────────────────────────────────────────────────
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017/")
DB_NAME   = os.getenv("DB_NAME", "civic_detector")
# ── Upload ────────────────────────────────────────────────────────
UPLOAD_FOLDER      = os.getenv("UPLOAD_FOLDER", "uploads")
MAX_FILE_SIZE_MB   = int(os.getenv("MAX_FILE_SIZE_MB", 5))
MAX_FILE_SIZE      = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_EXTENSIONS = [".jpg", ".jpeg", ".png"]
ALLOWED_MIME_TYPES = ["image/jpeg", "image/png"]

# ── Security ──────────────────────────────────────────────────────
MAX_LOGIN_ATTEMPTS   = int(os.getenv("MAX_LOGIN_ATTEMPTS", 5))
LOCKOUT_MINUTES      = int(os.getenv("LOCKOUT_MINUTES", 15))
MAX_COMPLAINTS_PER_DAY = int(os.getenv("MAX_COMPLAINTS_PER_DAY", 5))

# ── Email (SMTP) ──────────────────────────────────────────────────
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", 587))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_EMAIL    = os.getenv("FROM_EMAIL", "noreply@civic.college.edu")

# ── Twilio (SMS) ──────────────────────────────────────────────────
TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM  = os.getenv("TWILIO_PHONE", "")

# ── AI ────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── CORS ──────────────────────────────────────────────────────────
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5173"
).split(",")

# ── Complaint ─────────────────────────────────────────────────────
ALLOWED_PRIORITIES = ["Low", "Medium", "High", "Emergency"]
ALLOWED_STATUSES   = ["Pending", "In Progress", "Resolved", "Rejected", "Reopened"]
ESCALATION_HOURS   = int(os.getenv("ESCALATION_HOURS", 48))