"""
Smart Campus Features:
- QR Code generation for complaint submission
- Live complaint status tracking
- GPS coordinate-based nearby complaints
- Notifications routes
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone
import io

from database import complaints, db
from auth_middleware import get_current_user, require_student
from notifications import notifications

router = APIRouter(tags=["Campus & Notifications"])


# ── QR Code Generation ────────────────────────────────────────────
@router.get("/qr/complaint/{complaint_id}")
def get_complaint_qr(complaint_id: str):
    """Generate a QR code that links to the complaint tracking page."""
    try:
        import qrcode
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="qrcode not installed. Run: pip install qrcode[pil]"
        )

    # URL your frontend will use to show complaint status
    url = f"http://localhost:3000/track/{complaint_id}"

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    output = io.BytesIO()
    img.save(output, format="PNG")
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename=qr_{complaint_id}.png"}
    )


@router.get("/qr/submit")
def get_submit_qr():
    """QR code for the complaint submission page — put this on campus notice boards."""
    try:
        import qrcode
    except ImportError:
        raise HTTPException(status_code=500, detail="qrcode not installed. Run: pip install qrcode[pil]")

    url = "http://localhost:3000/submit"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1D4ED8", back_color="white")

    output = io.BytesIO()
    img.save(output, format="PNG")
    output.seek(0)
    return StreamingResponse(output, media_type="image/png")


# ── Live Complaint Tracking ───────────────────────────────────────
@router.get("/track/{complaint_id}")
def track_complaint(complaint_id: str):
    """
    Public tracking endpoint — students can check status with just the complaint ID.
    Returns status + timeline only (no sensitive data).
    """
    item = complaints.find_one(
        {"complaint_id": complaint_id},
        {"_id": 0, "complaint_id": 1, "category": 1, "location": 1,
         "status": 1, "priority": 1, "timeline": 1, "created_at": 1,
         "assigned_to": 1, "ai_summary": 1}
    )
    if not item:
        raise HTTPException(status_code=404, detail="Complaint not found")

    return {
        "complaint_id": item["complaint_id"],
        "category":     item.get("category"),
        "location":     item.get("location"),
        "status":       item.get("status"),
        "priority":     item.get("priority"),
        "assigned_to":  item.get("assigned_to"),
        "summary":      item.get("ai_summary"),
        "timeline":     item.get("timeline", []),
        "submitted_on": item.get("created_at")
    }


# ── Nearby Complaints (GPS) ───────────────────────────────────────
@router.get("/complaints/nearby")
def nearby_complaints(lat: float, lon: float, radius_km: float = 1.0):
    """
    Find complaints within radius_km of given GPS coordinates.
    Uses MongoDB $geoNear approximation via bounding box.
    """
    # 1 degree lat ≈ 111 km
    delta = radius_km / 111.0

    data = list(complaints.find(
        {
            "latitude":  {"$gte": lat - delta, "$lte": lat + delta},
            "longitude": {"$gte": lon - delta, "$lte": lon + delta},
        },
        {"_id": 0, "complaint_id": 1, "category": 1, "location": 1,
         "status": 1, "priority": 1, "latitude": 1, "longitude": 1}
    ).limit(50))

    return {"radius_km": radius_km, "total": len(data), "complaints": data}


# ── Notifications ─────────────────────────────────────────────────
@router.get("/notifications/{student_id}")
def get_notifications(student_id: str, current_user: dict = Depends(require_student)):
    data = list(
        notifications.find({"student_id": student_id}, {"_id": 0})
        .sort("created_at", -1)
        .limit(50)
    )
    unread = sum(1 for n in data if not n["is_read"])
    return {"student_id": student_id, "unread": unread, "notifications": data}


@router.patch("/notifications/{student_id}/read-all")
def mark_all_read(student_id: str, current_user: dict = Depends(require_student)):
    notifications.update_many(
        {"student_id": student_id, "is_read": False},
        {"$set": {"is_read": True}}
    )
    return {"message": "All notifications marked as read"}


@router.patch("/notifications/{notification_id}/read")
def mark_one_read(notification_id: str, current_user: dict = Depends(require_student)):
    from bson import ObjectId
    try:
        notifications.update_one(
            {"_id": ObjectId(notification_id)},
            {"$set": {"is_read": True}}
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid notification ID")
    return {"message": "Marked as read"}