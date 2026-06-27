from database import complaints
from logger import logger


def _jaccard_similarity(text1: str, text2: str) -> float:
    set1 = set(text1.lower().split())
    set2 = set(text2.lower().split())
    if not set1 or not set2:
        return 0.0
    intersection = set1 & set2
    union = set1 | set2
    return len(intersection) / len(union)


def find_similar_complaints(description: str, category: str, threshold: float = 0.5) -> list:
    recent = list(
        complaints.find(
            {"category": category, "status": {"$nin": ["Rejected"]}},
            {"complaint_id": 1, "description": 1, "status": 1, "created_at": 1}
        ).sort("created_at", -1).limit(100)
    )

    similar = []
    for c in recent:
        sim = _jaccard_similarity(description, c.get("description", ""))
        if sim >= threshold:
            similar.append({
                "complaint_id": c["complaint_id"],
                "similarity_score": round(sim, 2),
                "status": c.get("status"),
                "description_preview": c.get("description", "")[:100]
            })

    similar.sort(key=lambda x: x["similarity_score"], reverse=True)
    return similar[:5]


def compute_phash(image_path: str):
    try:
        import imagehash
        from PIL import Image
        img = Image.open(image_path)
        return str(imagehash.phash(img))
    except ImportError:
        logger.warning("imagehash not installed — skipping")
        return None
    except Exception as e:
        logger.error(f"pHash error: {e}")
        return None