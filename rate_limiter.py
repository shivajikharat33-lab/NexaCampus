from fastapi import HTTPException
from database import complaints
from datetime import datetime, timezone
from config import MAX_COMPLAINTS_PER_DAY


def check_rate_limit(student_id: str):
    """Raise 429 if student has submitted >= MAX_COMPLAINTS_PER_DAY today."""
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    count = complaints.count_documents({
        "student_id": student_id,
        "created_at": {"$gte": today}
    })
    if count >= MAX_COMPLAINTS_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail=f"Daily limit reached: max {MAX_COMPLAINTS_PER_DAY} complaints per day"
        )