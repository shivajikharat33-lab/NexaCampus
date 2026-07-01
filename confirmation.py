"""
Student Confirmation Before Closing
====================================
Flow:
1. Admin clicks "Resolve" → status becomes "Pending Confirmation"
2. Student gets notified → "Please confirm your issue is fixed"
3. Student confirms → status becomes "Resolved"
4. Student rejects → status goes back to "In Progress" + admin notified
5. If no response in 48hrs → auto-resolved
"""

from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone, timedelta
from database import complaints, users, db
from auth_middleware import require_admin, require_student
from notifications import create_notification, send_email
from logger import logger, log_audit

router = APIRouter(tags=["Student Confirmation"])

# Separate collection for confirmation requests
confirmations = db["confirmations"]
confirmations.create_index("complaint_id", unique=True)
confirmations.create_index("student_id")
confirmations.create_index("expires_at")
confirmations.create_index("status")


def _get_or_404(complaint_id: str) -> dict:
    item = complaints.find_one({"complaint_id": complaint_id})
    if not item:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return item


# ── Admin requests confirmation ───────────────────────────────────
@router.post("/complaints/{complaint_id}/request-confirmation")
def request_confirmation(
    complaint_id: str,
    resolution_note: str = None,
    u: dict = Depends(require_admin)
):
    """
    Admin calls this instead of directly resolving.
    Sets status to 'Pending Confirmation' and notifies student.
    """
    item = _get_or_404(complaint_id)

    if item["status"] == "Resolved":
        raise HTTPException(status_code=400, detail="Complaint already resolved")

    now     = datetime.now(timezone.utc)
    expires = now + timedelta(hours=48)

    # Update complaint status
    complaints.update_one({"complaint_id": complaint_id}, {
        "$set": {
            "status":          "Pending Confirmation",
            "updated_at":      now,
            "resolution_note": resolution_note
        },
        "$push": {"timeline": {
            "status": "Pending Confirmation",
            "time":   now,
            "by":     u["email"],
            "note":   resolution_note
        }}
    })

    # Create confirmation request
    confirmations.update_one(
        {"complaint_id": complaint_id},
        {"$set": {
            "complaint_id":    complaint_id,
            "student_id":      item["student_id"],
            "requested_by":    u["email"],
            "requested_at":    now,
            "expires_at":      expires,
            "status":          "pending",
            "resolution_note": resolution_note,
            "student_response": None,
            "responded_at":    None
        }},
        upsert=True
    )

    # Notify student
    create_notification(
        item["student_id"], complaint_id,
        f"Please confirm: Is your complaint {complaint_id} resolved? You have 48 hours to respond.",
        "confirmation_request"
    )

    # Send email if student has email
    student = users.find_one({"student_id": item["student_id"]}, {"email": 1})
    if student and student.get("email"):
        send_email(
            student["email"],
            f"Please confirm resolution — {complaint_id}",
            f"The maintenance team says your complaint <b>{complaint_id}</b> has been resolved.<br><br>"
            f"<b>Issue:</b> {item.get('description', '')}<br>"
            f"<b>Location:</b> {item.get('location', '')}<br><br>"
            f"Please confirm at: <a href='http://localhost:3000/confirm/{complaint_id}'>Click here</a><br><br>"
            f"You have <b>48 hours</b> to respond. If no response, complaint will be auto-resolved."
        )

    log_audit(u["email"], "CONFIRMATION_REQUESTED", complaint_id=complaint_id)
    return {
        "message":    "Confirmation request sent to student",
        "expires_at": expires,
        "complaint_id": complaint_id
    }


# ── Student confirms ──────────────────────────────────────────────
@router.post("/complaints/{complaint_id}/confirm")
def student_confirm(
    complaint_id: str,
    confirmed: bool,
    feedback: str = None,
    u: dict = Depends(require_student)
):
    """
    Student confirms (True) or rejects (False) the resolution.
    """
    item = _get_or_404(complaint_id)

    if item["status"] != "Pending Confirmation":
        raise HTTPException(
            status_code=400,
            detail="No pending confirmation for this complaint"
        )

    conf = confirmations.find_one({"complaint_id": complaint_id})
    if not conf:
        raise HTTPException(status_code=404, detail="Confirmation request not found")

    # Check expiry
    expires = conf.get("expires_at")
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires and datetime.now(timezone.utc) > expires:
        raise HTTPException(status_code=400, detail="Confirmation request has expired")

    now = datetime.now(timezone.utc)

    if confirmed:
        # Student confirms → mark as Resolved
        created = item.get("created_at")
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        resolution_hours = round((now - created).total_seconds() / 3600, 2) if created else 0

        complaints.update_one({"complaint_id": complaint_id}, {
            "$set": {
                "status":                "Resolved",
                "resolved_at":           now,
                "resolution_time_hours": resolution_hours,
                "student_confirmed":     True,
                "student_feedback":      feedback,
                "updated_at":            now
            },
            "$push": {"timeline": {
                "status": "Resolved",
                "time":   now,
                "by":     u["email"],
                "note":   f"Student confirmed. Feedback: {feedback}" if feedback else "Student confirmed"
            }}
        })

        confirmations.update_one({"complaint_id": complaint_id}, {
            "$set": {
                "status":           "confirmed",
                "student_response": True,
                "responded_at":     now,
                "feedback":         feedback
            }
        })

        # Notify admin
        admin_users = list(users.find({"role": "admin"}, {"email": 1}))
        for admin in admin_users:
            create_notification(
                admin.get("email", "admin"), complaint_id,
                f"Student confirmed resolution of complaint {complaint_id}",
                "student_confirmed"
            )

        logger.info(f"Complaint {complaint_id} confirmed by student {u['email']}")
        return {
            "message":  "Thank you! Complaint marked as Resolved.",
            "status":   "Resolved",
            "feedback": feedback
        }

    else:
        # Student rejects → reopen as In Progress
        complaints.update_one({"complaint_id": complaint_id}, {
            "$set": {
                "status":            "In Progress",
                "student_confirmed": False,
                "student_feedback":  feedback,
                "updated_at":        now
            },
            "$push": {"timeline": {
                "status": "Reopened by Student",
                "time":   now,
                "by":     u["email"],
                "note":   f"Student rejected resolution. Reason: {feedback}" if feedback else "Student rejected resolution"
            }}
        })

        confirmations.update_one({"complaint_id": complaint_id}, {
            "$set": {
                "status":           "rejected",
                "student_response": False,
                "responded_at":     now,
                "feedback":         feedback
            }
        })

        # Notify admin
        admin_users = list(users.find({"role": "admin"}, {"email": 1}))
        for admin in admin_users:
            create_notification(
                admin.get("email", "admin"), complaint_id,
                f"Student rejected resolution of {complaint_id}. Reason: {feedback or 'Not specified'}",
                "student_rejected"
            )

        logger.info(f"Complaint {complaint_id} rejected by student {u['email']}")
        return {
            "message":  "Complaint reopened. Admin has been notified.",
            "status":   "In Progress",
            "feedback": feedback
        }


# ── Get confirmation status ───────────────────────────────────────
@router.get("/complaints/{complaint_id}/confirmation-status")
def confirmation_status(complaint_id: str):
    conf = confirmations.find_one({"complaint_id": complaint_id}, {"_id": 0})
    if not conf:
        raise HTTPException(status_code=404, detail="No confirmation request found")
    return conf


# ── Auto-resolve expired confirmations (call from cron) ──────────
@router.post("/admin/auto-resolve-expired")
def auto_resolve_expired(u: dict = Depends(require_admin)):
    """
    Auto-resolve complaints where student didn't respond in 48 hours.
    Call from cron every hour.
    """
    now     = datetime.now(timezone.utc)
    expired = list(confirmations.find({
        "status":     "pending",
        "expires_at": {"$lt": now}
    }))

    resolved_count = 0
    for conf in expired:
        cid   = conf["complaint_id"]
        item  = complaints.find_one({"complaint_id": cid})
        if not item or item["status"] != "Pending Confirmation":
            continue

        created = item.get("created_at")
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        resolution_hours = round((now - created).total_seconds() / 3600, 2) if created else 0

        complaints.update_one({"complaint_id": cid}, {
            "$set": {
                "status":                "Resolved",
                "resolved_at":           now,
                "resolution_time_hours": resolution_hours,
                "student_confirmed":     None,
                "updated_at":            now
            },
            "$push": {"timeline": {
                "status": "Resolved",
                "time":   now,
                "by":     "system",
                "note":   "Auto-resolved: student did not respond within 48 hours"
            }}
        })

        confirmations.update_one({"complaint_id": cid}, {
            "$set": {"status": "auto_resolved"}
        })

        create_notification(
            conf["student_id"], cid,
            f"Your complaint {cid} was auto-resolved as no response was received in 48 hours.",
            "auto_resolved"
        )
        resolved_count += 1

    logger.info(f"Auto-resolved {resolved_count} expired confirmations")
    return {"auto_resolved": resolved_count}


# ── Pending confirmations list (admin) ────────────────────────────
@router.get("/admin/pending-confirmations")
def pending_confirmations(u: dict = Depends(require_admin)):
    data = list(confirmations.find(
        {"status": "pending"},
        {"_id": 0}
    ).sort("expires_at", 1))
    return {"total": len(data), "pending_confirmations": data}