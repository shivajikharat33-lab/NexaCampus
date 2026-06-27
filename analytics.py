from fastapi import APIRouter, Depends
from datetime import datetime, timezone, timedelta
from database import complaints, users, db
from auth_middleware import require_admin
from categories import ALLOWED_CATEGORIES
from config import ALLOWED_PRIORITIES, ALLOWED_STATUSES

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _date_range_count(days_back: int) -> list:
    """Return [{date, count}] for the last N days."""
    now = datetime.now(timezone.utc)
    result = []
    for i in range(days_back - 1, -1, -1):
        day = now - timedelta(days=i)
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end   = day.replace(hour=23, minute=59, second=59, microsecond=999999)
        count = complaints.count_documents({"created_at": {"$gte": start, "$lte": end}})
        result.append({"date": start.strftime("%Y-%m-%d"), "count": count})
    return result


# ── Overview ──────────────────────────────────────────────────────
@router.get("/overview")
def overview():
    return {
        "total":       complaints.count_documents({}),
        "pending":     complaints.count_documents({"status": "Pending"}),
        "in_progress": complaints.count_documents({"status": "In Progress"}),
        "resolved":    complaints.count_documents({"status": "Resolved"}),
        "rejected":    complaints.count_documents({"status": "Rejected"}),
        "escalated":   complaints.count_documents({"escalated": True}),
        "emergency":   complaints.count_documents({"priority": "Emergency"}),
        "high":        complaints.count_documents({"priority": "High"}),
    }


# ── Time Series ───────────────────────────────────────────────────
@router.get("/daily")
def daily(current_user: dict = Depends(require_admin)):
    return {"daily": _date_range_count(7)}


@router.get("/weekly")
def weekly(current_user: dict = Depends(require_admin)):
    return {"weekly": _date_range_count(28)}


@router.get("/monthly")
def monthly(current_user: dict = Depends(require_admin)):
    now = datetime.now(timezone.utc)
    result = []
    for i in range(11, -1, -1):
        month = now.month - i
        year  = now.year
        while month <= 0:
            month += 12
            year  -= 1
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
        count = complaints.count_documents({"created_at": {"$gte": start, "$lt": end}})
        result.append({"month": start.strftime("%Y-%m"), "count": count})
    return {"monthly": result}


@router.get("/yearly")
def yearly(current_user: dict = Depends(require_admin)):
    now = datetime.now(timezone.utc)
    result = []
    for i in range(4, -1, -1):
        year  = now.year - i
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end   = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        count = complaints.count_documents({"created_at": {"$gte": start, "$lt": end}})
        result.append({"year": year, "count": count})
    return {"yearly": result}


# ── Category & Priority ───────────────────────────────────────────
@router.get("/categories")
def category_stats():
    result = {}
    for cat in ALLOWED_CATEGORIES:
        count = complaints.count_documents({"category": cat})
        if count > 0:
            result[cat] = count
    return {"category_stats": result}


@router.get("/priorities")
def priority_stats():
    return {p: complaints.count_documents({"priority": p}) for p in ALLOWED_PRIORITIES}


# ── Location Heatmap ──────────────────────────────────────────────
@router.get("/heatmap")
def heatmap():
    """Return all complaints with GPS coordinates for map heatmap."""
    data = list(complaints.find(
        {"latitude": {"$ne": None}, "longitude": {"$ne": None}},
        {"_id": 0, "complaint_id": 1, "latitude": 1, "longitude": 1,
         "category": 1, "priority": 1, "status": 1, "location": 1}
    ))
    return {"points": data, "total": len(data)}


@router.get("/top-locations")
def top_locations(limit: int = 10):
    pipeline = [
        {"$group": {"_id": "$location", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit}
    ]
    return {"top_locations": [
        {"location": r["_id"], "count": r["count"]}
        for r in complaints.aggregate(pipeline)
    ]}


# ── Department Performance ────────────────────────────────────────
@router.get("/department-performance")
def department_performance(current_user: dict = Depends(require_admin)):
    pipeline = [
        {"$group": {
            "_id": "$assigned_to",
            "total":    {"$sum": 1},
            "resolved": {"$sum": {"$cond": [{"$eq": ["$status", "Resolved"]}, 1, 0]}},
            "pending":  {"$sum": {"$cond": [{"$eq": ["$status", "Pending"]}, 1, 0]}},
            "avg_resolution_hours": {"$avg": "$resolution_time_hours"}
        }},
        {"$sort": {"total": -1}}
    ]
    result = []
    for r in complaints.aggregate(pipeline):
        total    = r["total"]
        resolved = r["resolved"]
        score    = round((resolved / total * 100), 1) if total > 0 else 0
        result.append({
            "department": r["_id"],
            "total": total,
            "resolved": resolved,
            "pending": r["pending"],
            "resolution_rate_%": score,
            "avg_resolution_hours": round(r["avg_resolution_hours"] or 0, 2)
        })
    return {"departments": result}


# ── Resolution Time ───────────────────────────────────────────────
@router.get("/resolution-time")
def resolution_time(current_user: dict = Depends(require_admin)):
    resolved = list(complaints.find(
        {"status": "Resolved", "resolution_time_hours": {"$ne": None}},
        {"resolution_time_hours": 1}
    ))
    if not resolved:
        return {"avg_hours": 0, "min_hours": 0, "max_hours": 0, "total_resolved": 0}
    times = [r["resolution_time_hours"] for r in resolved]
    return {
        "total_resolved": len(times),
        "avg_hours": round(sum(times) / len(times), 2),
        "min_hours": round(min(times), 2),
        "max_hours": round(max(times), 2)
    }


# ── Leaderboard ───────────────────────────────────────────────────
@router.get("/leaderboard")
def leaderboard(limit: int = 10):
    """Top students by number of resolved complaints submitted."""
    pipeline = [
        {"$match": {"status": "Resolved"}},
        {"$group": {"_id": "$student_id", "name": {"$first": "$student_name"}, "resolved": {"$sum": 1}}},
        {"$sort": {"resolved": -1}},
        {"$limit": limit}
    ]
    return {"leaderboard": [
        {"rank": i + 1, "student_id": r["_id"], "name": r["name"], "resolved": r["resolved"]}
        for i, r in enumerate(complaints.aggregate(pipeline))
    ]}


# ── Most Active Students ──────────────────────────────────────────
@router.get("/most-active-students")
def most_active(limit: int = 10, current_user: dict = Depends(require_admin)):
    pipeline = [
        {"$group": {"_id": "$student_id", "name": {"$first": "$student_name"}, "total": {"$sum": 1}}},
        {"$sort": {"total": -1}},
        {"$limit": limit}
    ]
    return {"students": [
        {"student_id": r["_id"], "name": r["name"], "total_complaints": r["total"]}
        for r in complaints.aggregate(pipeline)
    ]}