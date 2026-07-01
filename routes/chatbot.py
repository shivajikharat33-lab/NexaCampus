# routes/chatbot.py

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
import requests, re

from database import db, complaints
from auth_middleware import get_current_user
from config import GEMINI_API_KEY
from logger import logger

router = APIRouter(prefix="/api/v1/chatbot", tags=["Chatbot"])


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    intent: str
    complaint_created: bool = False
    complaint_id: str | None = None


INTENTS = {
    "track_complaint": [
        r"cmp-\d+", r"complaint status", r"my complaint", r"status of",
        r"track complaint", r"complaint id"
    ],
    "create_complaint": [
        r"not working", r"broken", r"issue", r"problem", r"damaged",
        r"leaking", r"dirty", r"no water", r"wifi", r"light", r"fan",
        r"report", r"complaint about", r"please fix"
    ],
    "how_to": [
        r"how (do|to|can)", r"steps", r"guide", r"help", r"submit",
        r"use the app", r"what is", r"how does"
    ],
    "location": [
        r"where is", r"location of", r"nearest", r"find", r"block [a-z]",
        r"floor \d", r"washroom", r"canteen", r"library", r"lab"
    ],
}


def detect_intent(message: str) -> str:
    msg = message.lower()
    for intent, patterns in INTENTS.items():
        if any(re.search(p, msg) for p in patterns):
            return intent
    return "general"


# ✅ FIXED: Using direct REST API instead of google.genai library
def gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        return "AI is not configured. Please set GEMINI_API_KEY in .env"
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 500, "temperature": 0.7}
        }
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return "I'm having trouble connecting to AI. Please try again."


def get_student_id(current_user: dict) -> str:
    return str(
        current_user.get("student_id") or
        current_user.get("email")
    )


def build_system_prompt(context: dict) -> str:
    return f"""
You are NexaBot, the smart assistant for NexaCampus — a campus complaint management system.
You help students track complaints, file new ones, and navigate the campus.

RULES:
- Be concise. Max 3-4 lines per reply.
- Always be helpful and friendly.
- If creating a complaint, confirm the category and priority clearly.
- Never make up complaint IDs — use only the ones provided in context.
- If you don't know something, say so honestly.

CAMPUS CONTEXT:
- Blocks: A (Admin), B (Labs + Classrooms), C (Hostel), D (Library + Canteen)
- Washrooms: Every floor, near staircases
- WiFi zones: All blocks, Library, Canteen, Hostel common areas
- Working hours: 8am-6pm weekdays, 9am-1pm Saturday

STUDENT CONTEXT:
{context}

RESPONSE FORMAT:
- For complaint status: show ID, status, department, and expected resolution
- For new complaints: confirm category, ID, and priority
- For location: give block, floor, and landmark
- For how-to: give numbered steps, max 4 steps
""".strip()


def handle_track_complaint(message: str, student_id: str) -> dict:
    match = re.search(r"(CMP-[A-Z0-9]+)", message.upper())
    context = {}
    if match:
        complaint = complaints.find_one(
            {"complaint_id": match.group(1), "student_id": student_id},
            {"_id": 0, "complaint_id": 1, "status": 1, "category": 1,
             "assigned_to": 1, "priority": 1, "created_at": 1, "description": 1}
        )
        if complaint:
            context["complaint"] = complaint
        else:
            context["error"] = f"{match.group(1)} not found or does not belong to you"
    else:
        recent = list(complaints.find(
            {"student_id": student_id},
            {"_id": 0, "complaint_id": 1, "status": 1, "category": 1, "created_at": 1}
        ).sort("created_at", -1).limit(3))
        context["recent_complaints"] = recent if recent else "No complaints filed yet"
    return context


def handle_create_complaint(message: str, student_id: str, current_user: dict) -> dict:
    extract_prompt = f"""
Extract complaint info from this student message: "{message}"

Respond ONLY in this exact format (no extra text):
CATEGORY: <category name matching campus complaint types>
PRIORITY: <Low|Medium|High|Emergency>
SUMMARY: <one line description>
"""
    raw = gemini(extract_prompt)

    category, priority, summary = "Other", "Medium", message[:100]
    for line in raw.splitlines():
        if line.startswith("CATEGORY:"):
            category = line.replace("CATEGORY:", "").strip()
        elif line.startswith("PRIORITY:"):
            priority = line.replace("PRIORITY:", "").strip()
        elif line.startswith("SUMMARY:"):
            summary = line.replace("SUMMARY:", "").strip()

    import uuid
    complaint_id = "CMP-" + str(uuid.uuid4())[:8].upper()
    now = datetime.utcnow()

    new_complaint = {
        "complaint_id":  complaint_id,
        "student_id":    student_id,
        "student_name":  current_user.get("name", "Student"),
        "description":   summary,
        "category":      category,
        "priority":      priority,
        "status":        "Pending",
        "source":        "chatbot",
        "created_at":    now,
        "updated_at":    now,
        "assigned_to":   None,
        "comments":      [],
        "upvotes":       0,
    }

    complaints.insert_one(new_complaint)
    logger.info(f"Chatbot created complaint {complaint_id} for student {student_id}")

    return {
        "complaint_id":      complaint_id,
        "category":          category,
        "priority":          priority,
        "summary":           summary,
        "complaint_created": True,
    }


@router.post("/", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user)
):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    student_id        = get_student_id(current_user)
    message           = request.message.strip()
    intent            = detect_intent(message)
    complaint_created = False
    new_complaint_id  = None
    context           = {}

    try:
        if intent == "track_complaint":
            context = handle_track_complaint(message, student_id)
        elif intent == "create_complaint":
            context = handle_create_complaint(message, student_id, current_user)
            complaint_created = context.pop("complaint_created", False)
            new_complaint_id  = context.pop("complaint_id", None)
            context["new_complaint_id"] = new_complaint_id

        system_prompt = build_system_prompt(context)
        reply = gemini(f"{system_prompt}\n\nStudent message: {message}")

    except Exception as e:
        logger.error(f"Chatbot error for student {student_id}: {e}")
        reply  = "Sorry, I ran into an issue. Please try again or contact support."
        intent = "error"

    db["chat_logs"].insert_one({
        "student_id":        student_id,
        "message":           message,
        "intent":            intent,
        "reply":             reply,
        "complaint_created": complaint_created,
        "complaint_id":      new_complaint_id,
        "timestamp":         datetime.utcnow(),
    })

    return ChatResponse(
        reply=reply,
        intent=intent,
        complaint_created=complaint_created,
        complaint_id=new_complaint_id,
    )


@router.get("/history")
def chat_history(
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    student_id = get_student_id(current_user)
    logs = list(db["chat_logs"].find(
        {"student_id": student_id},
        {"_id": 0, "message": 1, "reply": 1, "intent": 1,
         "complaint_created": 1, "complaint_id": 1, "timestamp": 1}
    ).sort("timestamp", -1).limit(limit))
    return {"history": logs[::-1]}