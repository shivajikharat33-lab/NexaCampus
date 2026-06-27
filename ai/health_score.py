"""
Campus Area Health Score Calculator
Calculates a health score (0-100) for each campus area/location.

Score = 100 - penalty
Higher score = healthier area (fewer/less severe complaints)

Example output:
{
    "Main Gate":    {"score": 72, "grade": "B", "color": "#CA8A04"},
    "Library":      {"score": 91, "grade": "A", "color": "#16A34A"},
    "Parking Area": {"score": 65, "grade": "C", "color": "#EA580C"}
}
"""

from database import complaints
from datetime import datetime, timezone, timedelta


# Penalty points per complaint status + priority
STATUS_PENALTY = {
    "Pending":     15,
    "In Progress":  8,
    "Resolved":     0,
    "Rejected":     2,
    "Reopened":    12,
    "Escalated":   20
}

PRIORITY_PENALTY = {
    "Emergency": 25,
    "High":      15,
    "Medium":     8,
    "Low":        3
}


def _grade(score: int) -> str:
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    if score >= 50: return "D"
    return "F"


def _color(score: int) -> str:
    if score >= 80: return "#16A34A"   # green
    if score >= 60: return "#CA8A04"   # yellow
    if score >= 40: return "#EA580C"   # orange
    return "#DC2626"                   # red


def calculate_area_health(location: str, days: int = 30) -> dict:
    """
    Calculate health score for a single location.
    Looks at complaints from the last `days` days.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    area_complaints = list(complaints.find(
        {"location": location, "created_at": {"$gte": since}},
        {"status": 1, "priority": 1, "escalated": 1, "upvotes": 1}
    ))

    if not area_complaints:
        return {
            "location":        location,
            "score":           100,
            "grade":           "A+",
            "color":           "#16A34A",
            "total_complaints": 0,
            "penalty":         0,
            "status":          "No issues reported"
        }

    total_penalty = 0
    for c in area_complaints:
        status   = c.get("status", "Pending")
        priority = c.get("priority", "Medium")
        escalated = c.get("escalated", False)
        upvotes  = c.get("upvotes", 0)

        penalty  = STATUS_PENALTY.get(status, 10)
        penalty += PRIORITY_PENALTY.get(priority, 8)
        if escalated:
            penalty += 10
        penalty += min(upvotes, 5)  # community-confirmed issues
        total_penalty += penalty

    # Normalize: cap penalty at 200 for score calculation
    normalized_penalty = min(total_penalty, 200)
    score = max(0, int(100 - (normalized_penalty / 2)))

    return {
        "location":         location,
        "score":            score,
        "grade":            _grade(score),
        "color":            _color(score),
        "total_complaints": len(area_complaints),
        "total_penalty":    total_penalty,
        "status":           _status_label(score)
    }


def _status_label(score: int) -> str:
    if score >= 80: return "Good condition"
    if score >= 60: return "Needs attention"
    if score >= 40: return "Poor condition"
    return "Critical — immediate action needed"


def get_campus_health(days: int = 30) -> dict:
    """
    Calculate health scores for ALL locations in the database.
    Returns sorted list (worst first) + overall campus score.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Get all unique locations
    locations = complaints.distinct("location", {"created_at": {"$gte": since}})

    if not locations:
        return {
            "overall_score": 100,
            "overall_grade": "A+",
            "areas": [],
            "summary": "No complaints in the last {} days".format(days)
        }

    area_scores = []
    for loc in locations:
        if loc:
            area_scores.append(calculate_area_health(loc, days))

    # Sort worst first
    area_scores.sort(key=lambda x: x["score"])

    # Overall campus score = average of all areas
    overall = int(sum(a["score"] for a in area_scores) / len(area_scores))

    return {
        "overall_score": overall,
        "overall_grade": _grade(overall),
        "overall_color": _color(overall),
        "overall_status": _status_label(overall),
        "period_days":   days,
        "total_areas":   len(area_scores),
        "areas":         area_scores,
        "worst_area":    area_scores[0]["location"] if area_scores else None,
        "best_area":     area_scores[-1]["location"] if area_scores else None
    }