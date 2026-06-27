from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from datetime import datetime, timezone
import uuid, os

from database import complaints
from auth_middleware import require_admin, require_student
from notifications import create_notification
from config import UPLOAD_FOLDER, ALLOWED_EXTENSIONS, MAX_FILE_SIZE

router = APIRouter(
    prefix="/api/v1",
    tags=["Feed"]
)

def _get_or_404(complaint_id):
    item = complaints.find_one({"complaint_id": complaint_id})
    if not item:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return item


@router.post("/complaints/{complaint_id}/after-image")
async def upload_after_image(
    complaint_id: str,
    file: UploadFile = File(...),
    note: str = Form(None),
    u: dict = Depends(require_admin)
):
    item = _get_or_404(complaint_id)
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only JPG, JPEG, PNG allowed")
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 5MB")
    unique_filename = "after_" + str(uuid.uuid4()) + ext
    path = os.path.join(UPLOAD_FOLDER, unique_filename)
    with open(path, "wb") as f:
        f.write(contents)
    now = datetime.now(timezone.utc)
    complaints.update_one({"complaint_id": complaint_id}, {
        "$set": {
            "after_image":       unique_filename,
            "after_uploaded_by": u["email"],
            "after_uploaded_at": now,
            "after_note":        note,
            "resolution_proof":  True,
            "updated_at":        now
        }
    })
    create_notification(
        item["student_id"], complaint_id,
        f"Resolution proof uploaded for complaint {complaint_id}",
        "resolution_proof"
    )
    return {
        "message":      "After image uploaded successfully",
        "after_image":  unique_filename,
        "before_image": item.get("image"),
        "complaint_id": complaint_id
    }


@router.get("/complaints/{complaint_id}/before-after")
def get_before_after(complaint_id: str):
    item = complaints.find_one({"complaint_id": complaint_id}, {"_id": 0})
    if not item:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return {
        "complaint_id": complaint_id,
        "category":     item.get("category"),
        "location":     item.get("location"),
        "status":       item.get("status"),
        "before": {
            "image":       item.get("image"),
            "url":         f"/images/{item.get('image')}",
            "uploaded_at": item.get("created_at"),
            "description": item.get("description")
        },
        "after": {
            "image":       item.get("after_image"),
            "url":         f"/images/{item.get('after_image')}" if item.get("after_image") else None,
            "uploaded_at": item.get("after_uploaded_at"),
            "note":        item.get("after_note"),
            "uploaded_by": item.get("after_uploaded_by")
        },
        "resolution_proof":      item.get("resolution_proof", False),
        "resolution_time_hours": item.get("resolution_time_hours")
    }


@router.get("/feed/improvements")
def improvements_feed(page: int = 1, limit: int = 10):
    skip  = (page - 1) * limit
    query = {"status": "Resolved", "after_image": {"$exists": True, "$ne": None}}
    total = complaints.count_documents(query)
    data  = list(complaints.find(query, {
        "_id": 0, "complaint_id": 1, "category": 1, "location": 1,
        "image": 1, "after_image": 1, "after_note": 1,
        "description": 1, "ai_summary": 1,
        "resolution_time_hours": 1, "resolved_at": 1,
        "created_at": 1, "feed_likes": 1, "feed_comments": 1
    }).sort("resolved_at", -1).skip(skip).limit(limit))
    for item in data:
        item["before_url"] = f"/images/{item.get('image')}"
        item["after_url"]  = f"/images/{item.get('after_image')}"
        item["likes"]      = item.pop("feed_likes", 0)
        item["comments"]   = item.pop("feed_comments", [])
    return {"page": page, "limit": limit, "total": total, "feed": data}


@router.patch("/feed/{complaint_id}/like")
def like_improvement(complaint_id: str, u: dict = Depends(require_student)):
    item     = _get_or_404(complaint_id)
    email    = u["email"]
    liked_by = item.get("feed_liked_by", [])
    if email in liked_by:
        complaints.update_one({"complaint_id": complaint_id}, {
            "$inc":  {"feed_likes": -1},
            "$pull": {"feed_liked_by": email}
        })
        return {"message": "Like removed"}
    complaints.update_one({"complaint_id": complaint_id}, {
        "$inc":  {"feed_likes": 1},
        "$push": {"feed_liked_by": email}
    })
    return {"message": "Liked!"}


@router.post("/feed/{complaint_id}/comment")
def feed_comment(
    complaint_id: str,
    comment: str,
    u: dict = Depends(require_student)
):
    if len(comment.strip()) < 2:
        raise HTTPException(status_code=400, detail="Comment too short")
    now = datetime.now(timezone.utc)
    complaints.update_one({"complaint_id": complaint_id}, {
        "$push": {"feed_comments": {
            "text":       comment,
            "by":         u["email"],
            "name":       u.get("name", "Student"),
            "created_at": now
        }}
    })
    return {"message": "Comment added to feed"}


@router.get("/feed/stats")
def feed_stats():
    total      = complaints.count_documents({"status": "Resolved"})
    with_proof = complaints.count_documents({
        "status": "Resolved",
        "after_image": {"$exists": True, "$ne": None}
    })
    avg_q = list(complaints.aggregate([
        {"$match": {"status": "Resolved", "resolution_time_hours": {"$ne": None}}},
        {"$group": {"_id": None, "avg": {"$avg": "$resolution_time_hours"}}}
    ]))
    return {
        "total_resolved":       total,
        "with_proof":           with_proof,
        "avg_resolution_hours": round(avg_q[0]["avg"], 2) if avg_q else 0,
        "proof_percentage":     round(with_proof / total * 100, 1) if total else 0
    }