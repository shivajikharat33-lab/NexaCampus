"""
Rule-based AI predictor for priority and category.
No external API needed — works offline.
Can be upgraded to an ML model later.
"""

# ── Priority Keywords ─────────────────────────────────────────────
PRIORITY_KEYWORDS = {
    "Emergency": [
        "fire", "flood", "collapse", "danger", "accident", "injury", "blood",
        "electric shock", "gas leak", "emergency", "urgent", "critical", "broken wire",
        "water burst", "explosion", "toxic", "fumes"
    ],
    "High": [
        "broken", "damage", "crack", "not working", "overflow", "leaking", "leak",
        "blocked", "hazard", "unsafe", "falling", "broken glass", "no power",
        "power cut", "no water", "theft", "missing"
    ],
    "Medium": [
        "dirty", "garbage", "waste", "trash", "smell", "odor", "pothole",
        "damaged road", "graffiti", "noise", "littering", "stray", "pest",
        "mosquito", "rats", "maintenance needed"
    ],
    "Low": [
        "minor", "small", "suggestion", "request", "improve", "change",
        "feedback", "paint", "signage", "renovation"
    ]
}

# ── Category Keywords ─────────────────────────────────────────────
CATEGORY_KEYWORDS = {
    "Infrastructure": [
        "road", "pothole", "building", "wall", "ceiling", "floor", "crack",
        "broken", "damage", "construction", "bridge", "ramp", "stairs"
    ],
    "Electrical": [
        "light", "electricity", "power", "wire", "switch", "fan", "ac",
        "socket", "bulb", "generator", "electric", "short circuit"
    ],
    "Plumbing": [
        "water", "leak", "pipe", "tap", "drain", "toilet", "flush",
        "sewage", "overflow", "tank", "plumbing"
    ],
    "Cleanliness": [
        "garbage", "trash", "waste", "dirty", "clean", "litter", "dustbin",
        "smell", "odor", "hygiene", "sweep", "sweeping"
    ],
    "Security": [
        "theft", "missing", "broken gate", "unsafe", "intruder", "cctv",
        "camera", "lock", "security", "suspicious"
    ],
    "IT": [
        "wifi", "internet", "computer", "printer", "server", "network",
        "slow internet", "no wifi", "system"
    ],
    "Canteen": [
        "food", "canteen", "cafeteria", "mess", "quality", "menu",
        "price", "hygiene food", "cook", "kitchen"
    ]
}

# ── YOLO Object → Priority Boost ─────────────────────────────────
YOLO_EMERGENCY_OBJECTS = {"fire", "smoke", "person", "knife"}
YOLO_HIGH_OBJECTS      = {"car", "truck", "motorcycle", "flood", "bottle", "garbage"}


def predict_priority(description: str, yolo_objects: list = None) -> str:
    """
    Returns predicted priority: Emergency / High / Medium / Low
    Based on description keywords + YOLO detected objects.
    """
    desc_lower = description.lower()
    yolo_names = {obj.get("object_name", "").lower() for obj in (yolo_objects or [])}

    # YOLO emergency override
    if yolo_names & YOLO_EMERGENCY_OBJECTS:
        return "Emergency"

    # Keyword scoring
    scores = {}
    for level, keywords in PRIORITY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in desc_lower)
        if level == "High" and yolo_names & YOLO_HIGH_OBJECTS:
            score += 2
        scores[level] = score

    # Return highest scoring level, default Medium
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "Medium"
    return best


def predict_category(description: str, yolo_objects: list = None) -> str:
    """
    Returns predicted category from description keywords.
    """
    desc_lower = description.lower()
    scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in keywords if kw in desc_lower)

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "General"
    return best