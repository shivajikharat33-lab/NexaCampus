"""
AI Severity Scorer
Calculates a severity score (0-100) for a complaint based on:
- Priority level
- Category risk
- YOLO detected objects
- Description keywords
- Escalation status
"""

# Priority base scores
PRIORITY_SCORES = {
    "Emergency": 90,
    "High":      70,
    "Medium":    45,
    "Low":       20
}

# Category risk multipliers
CATEGORY_RISK = {
    "Electrical":      1.4,
    "Infrastructure":  1.3,
    "Plumbing":        1.2,
    "Security":        1.4,
    "Cleanliness":     1.0,
    "IT":              0.9,
    "Canteen":         1.0,
    "General":         0.8
}

# High risk keywords that boost score
DANGER_KEYWORDS = [
    "fire", "flood", "collapse", "danger", "electric shock",
    "gas leak", "explosion", "injury", "blood", "broken wire",
    "exposed wire", "short circuit", "sparks", "smoke",
    "unsafe", "hazard", "emergency", "critical"
]

# YOLO objects that indicate danger
DANGER_OBJECTS = {"fire", "smoke", "knife", "person", "car", "truck"}


def calculate_severity(
    priority: str,
    category: str,
    description: str,
    yolo_objects: list = None,
    escalated: bool = False,
    upvotes: int = 0
) -> dict:
    """
    Returns severity score (0-100) and label.

    Score ranges:
    0-25   → Low
    26-50  → Medium
    51-75  → High
    76-100 → Critical
    """
    # Base score from priority
    base = PRIORITY_SCORES.get(priority, 45)

    # Category risk multiplier
    multiplier = CATEGORY_RISK.get(category, 1.0)

    # Keyword boost (max +15)
    desc_lower = description.lower()
    keyword_hits = sum(1 for kw in DANGER_KEYWORDS if kw in desc_lower)
    keyword_boost = min(keyword_hits * 5, 15)

    # YOLO object boost (max +10)
    yolo_names = {o.get("object_name", "").lower() for o in (yolo_objects or [])}
    yolo_boost = 10 if yolo_names & DANGER_OBJECTS else 0

    # Escalation boost
    escalation_boost = 10 if escalated else 0

    # Upvotes boost (community agrees it's serious, max +5)
    upvote_boost = min(upvotes * 1, 5)

    # Final score
    raw_score = (base + keyword_boost + yolo_boost + escalation_boost + upvote_boost) * multiplier
    score = min(int(raw_score), 100)

    # Label
    if score >= 76:
        label = "Critical"
        color = "#DC2626"  # red
    elif score >= 51:
        label = "High"
        color = "#EA580C"  # orange
    elif score >= 26:
        label = "Medium"
        color = "#CA8A04"  # yellow
    else:
        label = "Low"
        color = "#16A34A"  # green

    return {
        "score":    score,
        "label":    label,
        "color":    color,
        "breakdown": {
            "base_priority":   base,
            "keyword_boost":   keyword_boost,
            "yolo_boost":      yolo_boost,
            "escalation_boost": escalation_boost,
            "upvote_boost":    upvote_boost,
            "multiplier":      multiplier
        }
    }