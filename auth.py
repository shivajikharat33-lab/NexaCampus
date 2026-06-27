from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from config import (
    SECRET_KEY, REFRESH_SECRET_KEY, ALGORITHM,
    ACCESS_TOKEN_EXPIRE, REFRESH_TOKEN_EXPIRE,
    MAX_LOGIN_ATTEMPTS, LOCKOUT_MINUTES
)


# ── Token Creation ────────────────────────────────────────────────
def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE)
    to_encode["type"] = "access"
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE)
    to_encode["type"] = "refresh"
    return jwt.encode(to_encode, REFRESH_SECRET_KEY, algorithm=ALGORITHM)


def decode_refresh_token(token: str) -> dict:
    return jwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])


def create_reset_token(email: str) -> str:
    """Short-lived 30-minute token for password reset."""
    payload = {
        "email": email,
        "type": "reset",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_reset_token(token: str) -> str:
    """Returns email if token valid, raises JWTError otherwise."""
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("type") != "reset":
        raise ValueError("Not a reset token")
    return payload["email"]


# ── Account Lockout ───────────────────────────────────────────────
def is_account_locked(user: dict) -> bool:
    """Return True if user is currently locked out."""
    locked_until = user.get("locked_until")
    if locked_until:
        # Handle both datetime and string
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until)
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < locked_until:
            return True
    return False


def get_lockout_update(failed_attempts: int) -> dict:
    """Return MongoDB $set update dict based on failed attempt count."""
    new_count = failed_attempts + 1
    update = {"failed_attempts": new_count}
    if new_count >= MAX_LOGIN_ATTEMPTS:
        update["locked_until"] = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
    return update


def reset_login_attempts() -> dict:
    """MongoDB $set dict to clear lockout after successful login."""
    return {
        "failed_attempts": 0,
        "locked_until": None,
        "last_login": datetime.now(timezone.utc)
    }