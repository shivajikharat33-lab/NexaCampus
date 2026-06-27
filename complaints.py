from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse
from datetime import datetime, timezone, timedelta
import uuid, os, hashlib

from database import complaints
from auth_middleware import get_current_user, require_admin, require_student
from notifications import notify
from logger import logger, log_audit
from models import CommentModel, StatusUpdateModel, AdminNoteModel, ReopenModel, AssignModel
from config import (
    UPLOAD_FOLDER, ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE, ALLOWED_PRIORITIES, ALLOWED_STATUSES, ESCALATION_HOURS
)
from categories import ALLOWED_CATEGORIES
from yolo import detect_image
from image_verification import check_image_authenticity
from ai.predictor import predict_priority, predict_category
from ai.summarizer import summarize_complaint
from ai.auto_router import auto_assign_department

# ✅ FIX 2: Removed top-level "import magic" — moved inside try block below

router = APIRouter(tags=["Complaints"])

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _complaint_or_404(complaint_id: str) -> dict:
    item = complaints.find_one({"complaint_id": complaint_id})
    if not item:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return item


# ── Upload ────────────────────────────────────────────────────────
@router.post("/upload")
async def upload(
    student_id:   str   = Form(...),
    student_name: str   = Form(...),
    department:   str   = Form(...),
    year:         str   = Form(...),
    category:     str   = Form(...),
    description:  str   = Form(...),
    location:     str   = Form(...),
    priority:     str   = Form(...),
    latitude:     float = Form(None),
    longitude:    float = Form(None),
    file: UploadFile = File(...),
    current_user: dict = Depends(require_student)
):
    from rate_limiter import check_rate_limit
    check_rate_limit(student_id)

    extension = os.path.splitext(file.filename)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only JPG, JPEG, PNG allowed")

    if priority not in ALLOWED_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")
    if category not in ALLOWED_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")

    contents = await file.read()

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 5MB")

    # ✅ FIX 2: import magic inside try — app won't crash if library missing
    try:
        import magic
        mime = magic.from_buffer(contents, mime=True)
        if mime not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid file type: {mime}")
    except ImportError:
        pass  # python-magic not installed — skip MIME check

    image_hash = hashlib.md5(contents).hexdigest()
    existing = complaints.find_one({"image_hash": image_hash})
    if existing:
        raise HTTPException(status_code=400, detail={
            "message": "Duplicate image already submitted",
            "existing_complaint": existing.get("complaint_id")
        })

    complaint_id    = "CMP-" + str(uuid.uuid4())[:8].upper()
    unique_filename = str(uuid.uuid4()) + extension
    path            = os.path.join(UPLOAD_FOLDER, unique_filename)
    with open(path, "wb") as f:
        f.write(contents)

    verification = check_image_authenticity(path)
    if not verification["is_real"]:
        os.remove(path)
        raise HTTPException(status_code=400, detail={
            "message": "Fake image rejected", "verification": verification
        })

    try:
        ai_result = detect_image(path)
    except Exception as e:
        ai_result = {"valid": False, "objects": [], "message": str(e)}
        logger.error(f"YOLO error: {e}")

    ai_priority = predict_priority(description, ai_result.get("objects", []))

    # ✅ FIX 3: predict_category only accepts (description) — removed second arg
    ai_category = predict_category(description)

    ai_summary  = summarize_complaint(description, category, location)
    auto_dept   = auto_assign_department(category)

    now      = datetime.now(timezone.utc)
    due_date = now + timedelta(hours=ESCALATION_HOURS)

    complaint_data = {
        "complaint_id":          complaint_id,
        "student_id":            student_id,
        "student_name":          student_name,
        "department":            department,
        "year":                  year,
        "category":              category,
        "description":           description,
        "location":              location,
        "latitude":              latitude,
        "longitude":             longitude,
        "priority":              priority,
        "image":                 unique_filename,
        "image_hash":            image_hash,
        "verification":          verification,
        "ai_result":             ai_result,
        "ai_priority":           ai_priority,
        "ai_category":           ai_category,
        "ai_summary":            ai_summary,
        "status":                "Pending",
        "assigned_to":           auto_dept,
        "admin_notes":           [],
        "comments":              [],
        "timeline":              [{"status": "Pending", "time": now, "by": "system"}],
        "upvotes":               0,
        "upvoted_by":            [],
        "due_date":              due_date,
        "escalated":             False,
        "resolved_at":           None,
        "resolution_time_hours": None,
        "created_at":            now,
        "updated_at":            now
    }

    complaints.insert_one(complaint_data)
    logger.info(f"Complaint created: {complaint_id} by {student_id}")

    return {
        "message":          "Complaint submitted successfully",
        "complaint_id":     complaint_id,
        "ai_priority":      ai_priority,
        "ai_category":      ai_category,
        "ai_summary":       ai_summary,
        "auto_assigned_to": auto_dept,
        "verification":     verification
    }


# ── Read ──────────────────────────────────────────────────────────
# ✅ FIX 1: ALL static routes are registered BEFORE /{complaint_id}
#           Order: /complaints → /search → /filter/... → /student/... → /{id}

@router.get("/complaints")
def get_all(page: int = 1, limit: int = 10):
    skip  = (page - 1) * limit
    total = complaints.count_documents({})
    data  = list(complaints.find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit))
    return {"page": page, "limit": limit, "total": total, "complaints": data}


@router.get("/complaints/search")              # ✅ static — before /{complaint_id}
def search_text(text: str):
    data = list(complaints.find({"$text": {"$search": text}}, {"_id": 0}))
    return {"results": data}


@router.get("/complaints/filter/priority")     # ✅ static — before /{complaint_id}
def by_priority(priority: str):
    if priority not in ALLOWED_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")
    data = list(complaints.find({"priority": priority}, {"_id": 0}).sort("created_at", -1))
    return {"priority": priority, "complaints": data}


@router.get("/complaints/filter/status")       # ✅ static — before /{complaint_id}
def by_status(status: str):
    if status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    data = list(complaints.find({"status": status}, {"_id": 0}).sort("created_at", -1))
    return {"status": status, "complaints": data}


@router.get("/complaints/filter/category")     # ✅ static — before /{complaint_id}
def by_category(category: str):
    data = list(complaints.find({"category": category}, {"_id": 0}).sort("created_at", -1))
    return {"category": category, "complaints": data}


@router.get("/complaints/filter/location")     # ✅ static — before /{complaint_id}
def by_location(location: str):
    data = list(complaints.find({"location": location}, {"_id": 0}).sort("created_at", -1))
    return {"location": location, "complaints": data}


@router.get("/complaints/student/{student_id}")  # ✅ two-segment — before /{complaint_id}
def by_student(student_id: str, current_user: dict = Depends(get_current_user)):
    data = list(complaints.find({"student_id": student_id}, {"_id": 0}).sort("created_at", -1))
    if not data:
        raise HTTPException(status_code=404, detail="No complaints found")
    return {"student_id": student_id, "complaints": data}


@router.get("/complaints/{complaint_id}")      # ✅ dynamic — always LAST among GETs
def get_one(complaint_id: str):
    item = complaints.find_one({"complaint_id": complaint_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return item


@router.get("/images/{filename}")
def get_image(filename: str):
    path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path)


# ── Edit (student, Pending only) ──────────────────────────────────
@router.patch("/complaints/{complaint_id}/edit")
def edit_complaint(
    complaint_id: str,
    description: str = None,
    location: str = None,
    current_user: dict = Depends(require_student)
):
    item = _complaint_or_404(complaint_id)
    if item["status"] != "Pending" and current_user["role"] != "admin":
        raise HTTPException(status_code=400, detail="Can only edit Pending complaints")
    update = {}
    if description: update["description"] = description
    if location:    update["location"]    = location
    if not update:  raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = datetime.now(timezone.utc)
    complaints.update_one({"complaint_id": complaint_id}, {"$set": update})
    return {"message": "Complaint updated"}


# ── Upvote toggle ─────────────────────────────────────────────────
@router.patch("/complaints/{complaint_id}/upvote")
def upvote(complaint_id: str, current_user: dict = Depends(require_student)):
    item  = _complaint_or_404(complaint_id)
    email = current_user["email"]
    if email in item.get("upvoted_by", []):
        complaints.update_one({"complaint_id": complaint_id}, {
            "$inc": {"upvotes": -1},
            "$pull": {"upvoted_by": email},
            "$set":  {"updated_at": datetime.now(timezone.utc)}
        })
        return {"message": "Upvote removed"}
    complaints.update_one({"complaint_id": complaint_id}, {
        "$inc": {"upvotes": 1},
        "$push": {"upvoted_by": email},
        "$set":  {"updated_at": datetime.now(timezone.utc)}
    })
    return {"message": "Upvoted"}


# ── Comment ───────────────────────────────────────────────────────
@router.post("/complaints/{complaint_id}/comment")
def add_comment(complaint_id: str, body: CommentModel, current_user: dict = Depends(require_student)):
    now    = datetime.now(timezone.utc)
    result = complaints.update_one({"complaint_id": complaint_id}, {
        "$push": {"comments": {
            "text":       body.comment,
            "by":         current_user["email"],
            "role":       current_user["role"],
            "created_at": now
        }},
        "$set": {"updated_at": now}
    })
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if current_user["role"] == "admin":
        item = complaints.find_one({"complaint_id": complaint_id})
        if item:
            notify(item["student_id"], complaint_id,
                   f"Admin commented on your complaint {complaint_id}", "comment")
    return {"message": "Comment added"}


# ── Admin note ────────────────────────────────────────────────────
@router.post("/complaints/{complaint_id}/admin-note")
def admin_note(complaint_id: str, body: AdminNoteModel, current_user: dict = Depends(require_admin)):
    now    = datetime.now(timezone.utc)
    result = complaints.update_one({"complaint_id": complaint_id}, {
        "$push": {"admin_notes": {
            "note":       body.note,
            "by":         current_user["email"],
            "created_at": now
        }},
        "$set": {"updated_at": now}
    })
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Complaint not found")
    log_audit(current_user["email"], "ADMIN_NOTE_ADDED", complaint_id=complaint_id)
    return {"message": "Note added"}


# ── Status update (admin only) ────────────────────────────────────
@router.patch("/complaints/{complaint_id}/status")
def update_status(
    complaint_id: str,
    body: StatusUpdateModel,
    current_user: dict = Depends(require_admin)
):
    if body.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    item = _complaint_or_404(complaint_id)
    now  = datetime.now(timezone.utc)

    update_fields = {"status": body.status, "updated_at": now}

    if body.status == "Resolved":
        update_fields["resolved_at"] = now
        created = item.get("created_at")
        if created:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            update_fields["resolution_time_hours"] = round(
                (now - created).total_seconds() / 3600, 2
            )

    complaints.update_one({"complaint_id": complaint_id}, {
        "$set":  update_fields,
        "$push": {"timeline": {
            "status": body.status,
            "time":   now,
            "by":     current_user["email"],
            "note":   body.note
        }}
    })

    notify(item["student_id"], complaint_id,
           f"Your complaint {complaint_id} status changed to '{body.status}'",
           "status_update")

    log_audit(current_user["email"], "STATUS_CHANGED", complaint_id=complaint_id,
              details={"from": item["status"], "to": body.status})
    return {"message": f"Status updated to {body.status}"}


# ── Assign (admin only) ───────────────────────────────────────────
@router.patch("/complaints/{complaint_id}/assign")
def assign_complaint(
    complaint_id: str,
    body: AssignModel,
    current_user: dict = Depends(require_admin)
):
    item = _complaint_or_404(complaint_id)
    now  = datetime.now(timezone.utc)
    complaints.update_one({"complaint_id": complaint_id}, {
        "$set":  {"assigned_to": body.assigned_to, "updated_at": now},
        "$push": {"timeline": {
            "status": f"Assigned to {body.assigned_to}",
            "time":   now,
            "by":     current_user["email"]
        }}
    })
    notify(item["student_id"], complaint_id,
           f"Your complaint {complaint_id} assigned to {body.assigned_to}", "assigned")
    log_audit(current_user["email"], "COMPLAINT_ASSIGNED", complaint_id=complaint_id,
              details={"to": body.assigned_to})
    return {"message": f"Assigned to {body.assigned_to}"}


# ── Reopen ────────────────────────────────────────────────────────
@router.post("/complaints/{complaint_id}/reopen")
def reopen_complaint(
    complaint_id: str,
    body: ReopenModel,
    current_user: dict = Depends(require_student)
):
    item = _complaint_or_404(complaint_id)
    if item["status"] not in ["Rejected", "Resolved"]:
        raise HTTPException(status_code=400, detail="Only Rejected or Resolved complaints can be reopened")
    now = datetime.now(timezone.utc)
    complaints.update_one({"complaint_id": complaint_id}, {
        "$set":  {"status": "Reopened", "updated_at": now},
        "$push": {"timeline": {
            "status": "Reopened",
            "time":   now,
            "by":     current_user["email"],
            "reason": body.reason
        }}
    })
    return {"message": "Complaint reopened successfully"}


# ── Delete (admin only) ───────────────────────────────────────────
@router.delete("/complaints/{complaint_id}")
def delete_complaint(complaint_id: str, current_user: dict = Depends(require_admin)):
    item = _complaint_or_404(complaint_id)
    image_path = os.path.join(UPLOAD_FOLDER, item["image"])
    if os.path.exists(image_path):
        os.remove(image_path)
    complaints.delete_one({"complaint_id": complaint_id})
    log_audit(current_user["email"], "COMPLAINT_DELETED", complaint_id=complaint_id)
    return {"message": "Complaint deleted"}


# ✅ FIX 4: Moved from /complaints/escalate-overdue → /admin/escalate-overdue
#           Old URL was caught by /{complaint_id} as complaint_id="escalate-overdue"
@router.post("/admin/escalate-overdue")
def escalate_overdue(current_user: dict = Depends(require_admin)):
    """
    Auto-escalate overdue Pending/In-Progress complaints to Emergency priority.
    Call this from a cron job every hour:
        curl -X POST http://localhost:8000/admin/escalate-overdue -H "Authorization: Bearer <token>"
    """
    now    = datetime.now(timezone.utc)
    result = complaints.update_many(
        {
            "status":    {"$in": ["Pending", "In Progress"]},
            "due_date":  {"$lt": now},
            "escalated": False
        },
        {
            "$set":  {"priority": "Emergency", "escalated": True, "updated_at": now},
            "$push": {"timeline": {"status": "Escalated", "time": now, "by": "system"}}
        }
    )
    logger.info(f"Escalated {result.modified_count} complaints")
    return {"escalated": result.modified_count}