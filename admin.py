from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from database import complaints, users, db
from auth_middleware import require_admin
from logger import log_audit
from models import BulkStatusModel, BulkDeleteModel, BulkAssignModel, DepartmentModel, UpdateDepartmentModel
from config import ALLOWED_STATUSES
import os
from config import UPLOAD_FOLDER

router = APIRouter(prefix="/admin", tags=["Admin"])

departments = db["departments"]
departments.create_index("code", unique=True)
departments.create_index("name")


# ── Complaints ────────────────────────────────────────────────────
@router.get("/complaints")
def admin_get_all(
    page: int = 1, limit: int = 20,
    status: str = None, priority: str = None,
    category: str = None, assigned_to: str = None,
    current_user: dict = Depends(require_admin)
):
    query = {}
    if status:      query["status"]      = status
    if priority:    query["priority"]    = priority
    if category:    query["category"]    = category
    if assigned_to: query["assigned_to"] = assigned_to

    skip  = (page - 1) * limit
    total = complaints.count_documents(query)
    data  = list(complaints.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit))
    return {"page": page, "limit": limit, "total": total, "complaints": data}


@router.patch("/complaints/bulk-status")
def bulk_status(body: BulkStatusModel, current_user: dict = Depends(require_admin)):
    if body.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    now = datetime.now(timezone.utc)
    result = complaints.update_many(
        {"complaint_id": {"$in": body.complaint_ids}},
        {
            "$set": {"status": body.status, "updated_at": now},
            "$push": {"timeline": {"status": body.status, "time": now, "by": current_user["email"]}}
        }
    )
    log_audit(current_user["email"], "BULK_STATUS_UPDATE",
              details={"count": result.modified_count, "status": body.status})
    return {"message": f"Updated {result.modified_count} complaints to {body.status}"}


@router.delete("/complaints/bulk-delete")
def bulk_delete(body: BulkDeleteModel, current_user: dict = Depends(require_admin)):
    items = list(complaints.find({"complaint_id": {"$in": body.complaint_ids}}))
    for item in items:
        img = os.path.join(UPLOAD_FOLDER, item.get("image", ""))
        if os.path.exists(img):
            os.remove(img)
    result = complaints.delete_many({"complaint_id": {"$in": body.complaint_ids}})
    log_audit(current_user["email"], "BULK_DELETE", details={"count": result.deleted_count})
    return {"message": f"Deleted {result.deleted_count} complaints"}


@router.patch("/complaints/bulk-assign")
def bulk_assign(body: BulkAssignModel, current_user: dict = Depends(require_admin)):
    now = datetime.now(timezone.utc)
    result = complaints.update_many(
        {"complaint_id": {"$in": body.complaint_ids}},
        {"$set": {"assigned_to": body.assigned_to, "updated_at": now}}
    )
    log_audit(current_user["email"], "BULK_ASSIGN",
              details={"count": result.modified_count, "to": body.assigned_to})
    return {"message": f"Assigned {result.modified_count} complaints to {body.assigned_to}"}


# ── Users ─────────────────────────────────────────────────────────
@router.get("/users")
def get_users(current_user: dict = Depends(require_admin)):
    data = list(users.find({}, {"_id": 0, "password": 0}))
    return {"total": len(data), "users": data}


@router.patch("/users/{email}/role")
def change_role(email: str, role: str, current_user: dict = Depends(require_admin)):
    if role not in ["student", "admin"]:
        raise HTTPException(status_code=400, detail="Role must be student or admin")
    result = users.update_one({"email": email}, {"$set": {"role": role}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    log_audit(current_user["email"], "ROLE_CHANGED", target=email, details={"role": role})
    return {"message": f"{email} role set to {role}"}


@router.delete("/users/{email}")
def delete_user(email: str, current_user: dict = Depends(require_admin)):
    result = users.delete_one({"email": email})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    log_audit(current_user["email"], "USER_DELETED", target=email)
    return {"message": f"User {email} deleted"}


# ── Departments ───────────────────────────────────────────────────
@router.get("/departments")
def list_departments(current_user: dict = Depends(require_admin)):
    data = list(departments.find({}, {"_id": 0}))
    return {"departments": data}


@router.post("/departments")
def create_department(body: DepartmentModel, current_user: dict = Depends(require_admin)):
    if departments.find_one({"code": body.code}):
        raise HTTPException(status_code=400, detail="Department code already exists")
    departments.insert_one({**body.model_dump(), "created_at": datetime.now(timezone.utc)})
    log_audit(current_user["email"], "DEPARTMENT_CREATED", details={"code": body.code})
    return {"message": "Department created"}


@router.patch("/departments/{code}")
def update_department(code: str, body: UpdateDepartmentModel, current_user: dict = Depends(require_admin)):
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    result = departments.update_one({"code": code}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Department not found")
    return {"message": "Department updated"}


@router.delete("/departments/{code}")
def delete_department(code: str, current_user: dict = Depends(require_admin)):
    result = departments.delete_one({"code": code})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Department not found")
    log_audit(current_user["email"], "DEPARTMENT_DELETED", details={"code": code})
    return {"message": "Department deleted"}


# ── Audit Logs ────────────────────────────────────────────────────
@router.get("/audit-logs")
def get_audit_logs(
    page: int = 1,
    limit: int = 50,
    current_user: dict = Depends(require_admin)
):
    from logger import audit_logs
    skip  = (page - 1) * limit
    total = audit_logs.count_documents({})
    data  = list(audit_logs.find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit))
    return {"page": page, "total": total, "logs": data}