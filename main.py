"""

Smart College Civic Detector — main.py v3.0

Run: python -m uvicorn main:app --reload

Docs: http://127.0.0.1:8000/docs

"""



from ai.severity import calculate_severity

from ai.health_score import get_campus_health, calculate_area_health

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException, Depends

from fastapi.openapi.utils import get_openapi

from fastapi.responses import FileResponse, StreamingResponse

from fastapi.middleware.cors import CORSMiddleware

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from datetime import datetime, timezone, timedelta

from jose import jwt, JWTError

import uuid, os, hashlib, io, csv, smtplib, logging

from logging.handlers import RotatingFileHandler

from email.mime.text import MIMEText

from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv

from routes.feed import router as feed_router

from categories import ALLOWED_CATEGORIES

from password_utils import hash_password, verify_password

from database import complaints, users, db

from yolo import detect_image

from image_verification import check_image_authenticity

from ai.predictor import predict_priority, predict_category

from ai.summarizer import summarize_complaint

from ai.auto_router import auto_assign_department

from fastapi import WebSocket, WebSocketDisconnect

from typing import Dict

from whatsapp import notify_complaint_submitted, notify_status_changed, notify_resolved, notify_escalated

from confirmation import router as confirmation_router

from routes.chatbot import router as chatbot_router

from routes.voice import router as voice_router



load_dotenv()



# ══════════════════════════════════════════════════════════════════

# CONFIG

# ══════════════════════════════════════════════════════════════════

SECRET_KEY          = os.getenv("SECRET_KEY", "shivaji_secret_key_2026")

REFRESH_SECRET_KEY  = os.getenv("REFRESH_SECRET_KEY", "shivaji_refresh_key_2026")

ALGORITHM           = "HS256"

ACCESS_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", 24))

REFRESH_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

UPLOAD_FOLDER       = os.getenv("UPLOAD_FOLDER", "uploads")

MAX_FILE_SIZE       = int(os.getenv("MAX_FILE_SIZE_MB", 5)) * 1024 * 1024

ALLOWED_EXTENSIONS  = [".jpg", ".jpeg", ".png"]

ALLOWED_MIME_TYPES  = ["image/jpeg", "image/png"]

ALLOWED_PRIORITIES  = ["Low", "Medium", "High", "Emergency"]

ALLOWED_STATUSES    = ["Pending", "In Progress", "Resolved", "Rejected", "Reopened"]

MAX_LOGIN_ATTEMPTS  = int(os.getenv("MAX_LOGIN_ATTEMPTS", 5))

LOCKOUT_MINUTES     = int(os.getenv("LOCKOUT_MINUTES", 15))

MAX_PER_DAY         = int(os.getenv("MAX_COMPLAINTS_PER_DAY", 5))

ESCALATION_HOURS    = int(os.getenv("ESCALATION_HOURS", 48))

GEMINI_KEY          = os.getenv("GEMINI_API_KEY", "")

SMTP_HOST           = os.getenv("SMTP_HOST", "smtp.gmail.com")

SMTP_PORT           = int(os.getenv("SMTP_PORT", 587))

SMTP_USER           = os.getenv("SMTP_USER", "")

SMTP_PASS           = os.getenv("SMTP_PASSWORD", "")

FROM_EMAIL          = os.getenv("FROM_EMAIL", "noreply@civic.college.edu")

ALLOWED_ORIGINS     = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")



os.makedirs(UPLOAD_FOLDER, exist_ok=True)

os.makedirs("logs", exist_ok=True)



# ══════════════════════════════════════════════════════════════════

# LOGGING

# ══════════════════════════════════════════════════════════════════

logger = logging.getLogger("civic")

logger.setLevel(logging.DEBUG)

fmt = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", "%Y-%m-%d %H:%M:%S")

fh = RotatingFileHandler("logs/app.log", maxBytes=5*1024*1024, backupCount=5)

fh.setFormatter(fmt); fh.setLevel(logging.INFO)

eh = RotatingFileHandler("logs/errors.log", maxBytes=5*1024*1024, backupCount=3)

eh.setFormatter(fmt); eh.setLevel(logging.ERROR)

ch = logging.StreamHandler()

ch.setFormatter(fmt); ch.setLevel(logging.DEBUG)

logger.addHandler(fh); logger.addHandler(eh); logger.addHandler(ch)



audit_logs        = db["audit_logs"]

notifications_col = db["notifications"]

departments_col   = db["departments"]



# ══════════════════════════════════════════════════════════════════

# APP + CORS

# ══════════════════════════════════════════════════════════════════

app = FastAPI(

    title="Smart College Civic Detector",

    description="""

## AI-Powered Campus Complaint Management System



### Features

- 🤖 AI image verification using YOLOv8

- 📍 GPS location tracking  

- 📊 Real-time analytics dashboard

- 🔐 JWT authentication with refresh tokens

- 📱 Flutter mobile app support

- 🚨 Auto priority and category prediction



### How to use

1. Register as student or admin

2. Login to get JWT token

3. Click the 🔒 Authorize button and paste your token

4. Use any protected route

    """,

    version="3.0",

    contact={

        "name": "Smart Civic Team",

        "email": "support@smartcivic.com"

    },

    license_info={

        "name": "MIT License"

    }

)



router = APIRouter(prefix="/api/v1")



app.add_middleware(

    CORSMiddleware,

    allow_origins=ALLOWED_ORIGINS,

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],

)



security = HTTPBearer()



# ══════════════════════════════════════════════════════════════════

# WEBSOCKET MANAGER

# ══════════════════════════════════════════════════════════════════

class ConnectionManager:



    def __init__(self):

        self.active_connections: Dict[str, WebSocket] = {}



    async def connect(self, student_id: str, websocket: WebSocket):

        await websocket.accept()

        self.active_connections[student_id] = websocket



    def disconnect(self, student_id: str):

        self.active_connections.pop(student_id, None)



    async def send_notification(self, student_id: str, message: dict):

        if student_id in self.active_connections:

            await self.active_connections[student_id].send_json(message)



manager = ConnectionManager()



# ══════════════════════════════════════════════════════════════════

# AUTH HELPERS

# ══════════════════════════════════════════════════════════════════

def create_access_token(data: dict) -> str:

    d = data.copy()

    d["exp"]  = datetime.now(timezone.utc) + timedelta(hours=ACCESS_EXPIRE_HOURS)

    d["type"] = "access"

    return jwt.encode(d, SECRET_KEY, algorithm=ALGORITHM)



def create_refresh_token(data: dict) -> str:

    d = data.copy()

    d["exp"]  = datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE_DAYS)

    d["type"] = "refresh"

    return jwt.encode(d, REFRESH_SECRET_KEY, algorithm=ALGORITHM)



def create_reset_token(email: str) -> str:

    return jwt.encode(

        {"email": email, "type": "reset",

         "exp": datetime.now(timezone.utc) + timedelta(minutes=30)},

        SECRET_KEY, algorithm=ALGORITHM

    )



def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):

    try:

        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])

        if payload.get("type") != "access":

            raise HTTPException(status_code=401, detail="Invalid token type")

        email = payload.get("email")

        if not email:

            raise HTTPException(status_code=401, detail="Invalid token")

    except JWTError:

        raise HTTPException(status_code=401, detail="Token expired or invalid")

    user = users.find_one({"email": email}, {"_id": 0, "password": 0})

    if not user:

        raise HTTPException(status_code=401, detail="User not found")

    return user



def require_admin(u: dict = Depends(get_current_user)):

    if u.get("role") != "admin":

        raise HTTPException(status_code=403, detail="Admin access required")

    return u



def require_student(u: dict = Depends(get_current_user)):

    if u.get("role") not in ["student", "admin"]:

        raise HTTPException(status_code=403, detail="Access denied")

    return u



def is_locked(user: dict) -> bool:

    lu = user.get("locked_until")

    if lu:

        if isinstance(lu, str): lu = datetime.fromisoformat(lu)

        if lu.tzinfo is None: lu = lu.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) < lu: return True

    return False



# ══════════════════════════════════════════════════════════════════

# UTILITY HELPERS

# ══════════════════════════════════════════════════════════════════

def log_audit(actor, action, complaint_id=None, target=None, details=None):

    try:

        audit_logs.insert_one({

            "actor_email": actor, "action": action,

            "complaint_id": complaint_id, "target": target,

            "details": details or {}, "created_at": datetime.now(timezone.utc)

        })

    except Exception as e:

        logger.error(f"Audit log failed: {e}")



def push_notification(student_id, complaint_id, message, notif_type="update"):

    notifications_col.insert_one({

        "student_id": student_id, "complaint_id": complaint_id,

        "message": message, "type": notif_type,

        "is_read": False, "created_at": datetime.now(timezone.utc)

    })



def send_email(to, subject, body):

    if not SMTP_USER or not SMTP_PASS:

        return

    try:

        msg = MIMEMultipart("alternative")

        msg["From"] = FROM_EMAIL; msg["To"] = to; msg["Subject"] = subject

        msg.attach(MIMEText(

            f"<html><body style='font-family:Arial;padding:20px'>"

            f"<h2 style='color:#2563eb'>Civic Detector</h2><p>{body}</p>"

            f"<p style='color:#999;font-size:12px'>Automated notification.</p>"

            f"</body></html>", "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:

            s.starttls(); s.login(SMTP_USER, SMTP_PASS)

            s.sendmail(FROM_EMAIL, to, msg.as_string())

        logger.info(f"Email sent to {to}")

    except Exception as e:

        logger.error(f"Email failed to {to}: {e}")



def check_rate_limit(student_id):

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    count = complaints.count_documents({"student_id": student_id, "created_at": {"$gte": today}})

    if count >= MAX_PER_DAY:

        raise HTTPException(status_code=429, detail=f"Daily limit: max {MAX_PER_DAY} complaints per day")



def _get_or_404(complaint_id):

    item = complaints.find_one({"complaint_id": complaint_id})

    if not item:

        raise HTTPException(status_code=404, detail="Complaint not found")

    return item



def find_similar(description, category):

    recent = list(complaints.find(

        {"category": category, "status": {"$nin": ["Rejected"]}},

        {"complaint_id": 1, "description": 1, "status": 1}

    ).sort("created_at", -1).limit(100))

    set1 = set(description.lower().split())

    similar = []

    for c in recent:

        set2 = set(c.get("description", "").lower().split())

        if not set2: continue

        sim = len(set1 & set2) / len(set1 | set2)

        if sim >= 0.5:

            similar.append({"complaint_id": c["complaint_id"], "similarity": round(sim, 2), "status": c.get("status")})

    return sorted(similar, key=lambda x: x["similarity"], reverse=True)[:3]



def _fmt(v):

    if isinstance(v, datetime): return v.strftime("%Y-%m-%d %H:%M")

    return str(v) if v is not None else ""



# ══════════════════════════════════════════════════════════════════

# HEALTH

# ══════════════════════════════════════════════════════════════════

@router.get("/", tags=["Health"])

def home():

    return {"message": "Smart College Civic Detector Running", "version": "3.0", "docs": "/docs"}



@router.get("/health", tags=["Health"])

def health():

    from database import client

    try: client.admin.command("ping"); db_ok = "connected"

    except: db_ok = "disconnected"

    return {"status": "healthy", "database": db_ok, "version": "3.0"}



@router.get("/categories", tags=["Health"])

def get_categories():

    return {"count": len(ALLOWED_CATEGORIES), "categories": ALLOWED_CATEGORIES}



@router.get("/images/{filename}", tags=["Health"])

def get_image(filename: str):

    path = os.path.join(UPLOAD_FOLDER, filename)

    if not os.path.exists(path):

        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(path)



# ══════════════════════════════════════════════════════════════════

# USERS

# ══════════════════════════════════════════════════════════════════

@router.post("/register", tags=["Users"])

def register(name: str, email: str, password: str, college_name: str,

             student_id: str = None, department: str = None,

             year: str = None, phone: str = None):

    import re

    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):

        raise HTTPException(status_code=400, detail="Invalid email format")

    if len(password) < 8:

        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    if not re.search(r"[A-Z]", password):

        raise HTTPException(status_code=400, detail="Password must contain an uppercase letter")

    if not re.search(r"[0-9]", password):

        raise HTTPException(status_code=400, detail="Password must contain a number")

    if users.find_one({"email": email}):

        raise HTTPException(status_code=400, detail="Email already registered")

    college_id = re.sub(r'[^a-z0-9]', '', college_name.lower().strip())

    users.insert_one({

        "name": name, "email": email, "password": hash_password(password),

        "college_name": college_name.strip(), "college_id": college_id,

        "student_id": student_id, "department": department, "year": year,

        "phone": phone, "role": "student", "failed_attempts": 0,

        "locked_until": None, "last_login": None,

        "created_at": datetime.now(timezone.utc)

    })

    logger.info(f"Registered: {email}")

    return {"message": "User registered successfully"}



@router.post("/login", tags=["Users"])

def login(email: str, password: str):

    user = users.find_one({"email": email})

    if not user:

        raise HTTPException(status_code=401, detail="Invalid email or password")

    if is_locked(user):

        raise HTTPException(status_code=423, detail=f"Account locked until {user.get('locked_until')}")

    if not verify_password(password, user["password"]):

        attempts = user.get("failed_attempts", 0) + 1

        upd = {"failed_attempts": attempts}

        if attempts >= MAX_LOGIN_ATTEMPTS:

            upd["locked_until"] = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)

        users.update_one({"email": email}, {"$set": upd})

        remaining = max(0, MAX_LOGIN_ATTEMPTS - attempts)

        raise HTTPException(status_code=401, detail=f"Invalid password. {remaining} attempts left")

    users.update_one({"email": email}, {"$set": {

        "failed_attempts": 0, "locked_until": None,

        "last_login": datetime.now(timezone.utc)

    }})

    return {

        "access_token":  create_access_token({"email": user["email"], "role": user["role"], "college_id": user.get("college_id")}),    



        "refresh_token": create_refresh_token({"email": user["email"], "role": user["role"], "college_id": user.get("college_id")}),

        "token_type": "bearer", "role": user["role"], "name": user["name"],

        "college_id": user.get("college_id"), "college_name": user.get("college_name")

    }

@router.post("/refresh", tags=["Users"])

def refresh(refresh_token: str):

    try:

        payload = jwt.decode(refresh_token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])

        if payload.get("type") != "refresh":

            raise HTTPException(status_code=401, detail="Invalid token type")

    except JWTError:

        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    return {

        "access_token":  create_access_token({"email": payload["email"], "role": payload["role"]}),

        "refresh_token": create_refresh_token({"email": payload["email"], "role": payload["role"]}),

        "token_type": "bearer"

    }



@router.get("/me", tags=["Users"])

def get_me(u: dict = Depends(get_current_user)):

    return u



@router.patch("/me/profile", tags=["Users"])

def update_profile(name: str = None, phone: str = None,

                   department: str = None, year: str = None,

                   u: dict = Depends(get_current_user)):

    upd = {k: v for k, v in {"name": name, "phone": phone, "department": department, "year": year}.items() if v}

    if not upd: raise HTTPException(status_code=400, detail="Nothing to update")

    upd["updated_at"] = datetime.now(timezone.utc)

    users.update_one({"email": u["email"]}, {"$set": upd})

    return {"message": "Profile updated"}



@router.patch("/me/change-password", tags=["Users"])

def change_password(old_password: str, new_password: str, u: dict = Depends(get_current_user)):

    user = users.find_one({"email": u["email"]})

    if not verify_password(old_password, user["password"]):

        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if len(new_password) < 8:

        raise HTTPException(status_code=400, detail="Password too short")

    users.update_one({"email": u["email"]}, {"$set": {"password": hash_password(new_password)}})

    log_audit(u["email"], "PASSWORD_CHANGED")

    return {"message": "Password changed successfully"}



@router.post("/forgot-password", tags=["Users"])

def forgot_password(email: str):

    user = users.find_one({"email": email})

    if user:

        token = create_reset_token(email)

        send_email(email, "Reset Your Password",

                   f"Reset link (valid 30 min): <a href='http://localhost:3000/reset-password?token={token}'>Click here</a>")

    return {"message": "If that email exists, a reset link has been sent"}



@router.post("/reset-password", tags=["Users"])

def reset_password(token: str, new_password: str):

    try:

        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        if payload.get("type") != "reset":

            raise HTTPException(status_code=400, detail="Invalid token")

        email = payload["email"]

    except JWTError:

        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if len(new_password) < 8:

        raise HTTPException(status_code=400, detail="Password too short")

    users.update_one({"email": email}, {"$set": {

        "password": hash_password(new_password),

        "failed_attempts": 0, "locked_until": None

    }})

    log_audit(email, "PASSWORD_RESET")

    return {"message": "Password reset successfully"}



# ══════════════════════════════════════════════════════════════════

# UPLOAD

# ══════════════════════════════════════════════════════════════════

@router.post("/upload", tags=["Complaints"])

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

    u: dict = Depends(require_student)

):

    check_rate_limit(student_id)



    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:

        raise HTTPException(status_code=400, detail="Only JPG, JPEG, PNG allowed")

    if priority not in ALLOWED_PRIORITIES:

        raise HTTPException(status_code=400, detail="Invalid priority")

    if category not in ALLOWED_CATEGORIES:

        raise HTTPException(status_code=400, detail="Invalid category")



    contents = await file.read()

    if len(contents) > MAX_FILE_SIZE:

        raise HTTPException(status_code=400, detail="File exceeds 5MB")



    try:

        import magic

        mime = magic.from_buffer(contents, mime=True)

        if mime not in ALLOWED_MIME_TYPES:

            raise HTTPException(status_code=400, detail=f"Invalid file type: {mime}")

    except ImportError:

        pass



    image_hash = hashlib.md5(contents).hexdigest()

    existing = complaints.find_one({"image_hash": image_hash})

    if existing:

        raise HTTPException(status_code=400, detail={

            "message": "Duplicate image already submitted",

            "existing_complaint": existing.get("complaint_id")

        })



    similar = find_similar(description, category)



    complaint_id    = "CMP-" + str(uuid.uuid4())[:8].upper()

    unique_filename = str(uuid.uuid4()) + ext

    path            = os.path.join(UPLOAD_FOLDER, unique_filename)

    with open(path, "wb") as f:

        f.write(contents)



    verification = check_image_authenticity(path)

    if not verification["is_real"]:

        os.remove(path)

        raise HTTPException(status_code=400, detail={"message": "Fake image rejected", "verification": verification})



    try:

        ai_result = detect_image(path)

    except Exception as e:

        ai_result = {"valid": False, "objects": [], "message": str(e)}

        logger.error(f"YOLO error: {e}")



    ai_priority = predict_priority(description, ai_result.get("objects", []))

    ai_category = predict_category(description)

    ai_summary  = summarize_complaint(description, category, location)

    auto_dept   = auto_assign_department(category)



    now      = datetime.now(timezone.utc)

    due_date = now + timedelta(hours=ESCALATION_HOURS)



    doc = {

        "complaint_id": complaint_id, "student_id": student_id,

        "student_name": student_name, "department": department,

        "college_id": u.get("college_id"), "college_name": u.get("college_name"),

        "year": year, "category": category, "description": description,

        "location": location, "latitude": latitude, "longitude": longitude,

        "priority": priority, "image": unique_filename, "image_hash": image_hash,

        "verification": verification, "ai_result": ai_result,

        "ai_priority": ai_priority, "ai_category": ai_category, "ai_summary": ai_summary,

        "status": "Pending", "assigned_to": auto_dept,

        "admin_notes": [], "comments": [],

        "timeline": [{"status": "Pending", "time": now, "by": "system"}],

        "upvotes": 0, "upvoted_by": [], "due_date": due_date,

        "escalated": False, "resolved_at": None, "resolution_time_hours": None,

        "created_at": now, "updated_at": now

    }



    complaints.insert_one(doc)

    logger.info(f"Complaint created: {complaint_id} by {student_id}")

    return {

        "message": "Complaint submitted successfully",

        "complaint_id": complaint_id,

        "ai_priority": ai_priority, "ai_category": ai_category,

        "ai_summary": ai_summary, "auto_assigned_to": auto_dept,

        "similar_complaints": similar, "verification": verification

    }



# ══════════════════════════════════════════════════════════════════

# COMPLAINTS — READ

# ══════════════════════════════════════════════════════════════════



@router.get("/complaints", tags=["Complaints"])

def get_all(page: int = 1, limit: int = 10, u: dict = Depends(get_current_user)):

    q = {"college_id": u.get("college_id")}

    skip  = (page - 1) * limit

    total = complaints.count_documents(q)

    data  = list(complaints.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit))

    return {"page": page, "limit": limit, "total": total, "complaints": data}

@router.get("/complaints/search", tags=["Complaints"])

def search_by_category(category: str):

    data = list(complaints.find({"category": category}, {"_id": 0}).sort("created_at", -1))

    return {"complaints": data}



@router.get("/complaints/search/text", tags=["Complaints"])

def search_text(text: str):

    data = list(complaints.find({"$text": {"$search": text}}, {"_id": 0}))

    return {"results": data}



@router.get("/complaints/filter/priority", tags=["Complaints"])

def by_priority(priority: str):

    if priority not in ALLOWED_PRIORITIES:

        raise HTTPException(status_code=400, detail="Invalid priority")

    data = list(complaints.find({"priority": priority}, {"_id": 0}).sort("created_at", -1))

    return {"priority": priority, "complaints": data}



@router.get("/complaints/filter/status", tags=["Complaints"])

def by_status(status: str):

    if status not in ALLOWED_STATUSES:

        raise HTTPException(status_code=400, detail="Invalid status")

    data = list(complaints.find({"status": status}, {"_id": 0}).sort("created_at", -1))

    return {"status": status, "complaints": data}



@router.get("/complaints/filter/category", tags=["Complaints"])

def by_category(category: str):

    data = list(complaints.find({"category": category}, {"_id": 0}).sort("created_at", -1))

    return {"category": category, "complaints": data}



@router.get("/complaints/filter/location", tags=["Complaints"])

def by_location(location: str):

    data = list(complaints.find({"location": location}, {"_id": 0}).sort("created_at", -1))

    return {"location": location, "complaints": data}



@router.get("/complaints/nearby", tags=["Complaints"])

def nearby(lat: float, lon: float, radius_km: float = 1.0):

    d = radius_km / 111.0

    data = list(complaints.find(

        {"latitude": {"$gte": lat-d, "$lte": lat+d}, "longitude": {"$gte": lon-d, "$lte": lon+d}},

        {"_id": 0, "complaint_id": 1, "category": 1, "location": 1,

         "status": 1, "priority": 1, "latitude": 1, "longitude": 1}

    ).limit(50))

    return {"radius_km": radius_km, "total": len(data), "complaints": data}



@router.get("/complaints/student/{student_id}", tags=["Complaints"])

def by_student(student_id: str, u: dict = Depends(get_current_user)):

    data = list(complaints.find({"student_id": student_id}, {"_id": 0}).sort("created_at", -1))

    if not data: raise HTTPException(status_code=404, detail="No complaints found")

    return {"student_id": student_id, "complaints": data}



@router.get("/complaints/{complaint_id}", tags=["Complaints"])

def get_one(complaint_id: str):

    item = complaints.find_one({"complaint_id": complaint_id}, {"_id": 0})

    if not item: raise HTTPException(status_code=404, detail="Complaint not found")

    return item



# ══════════════════════════════════════════════════════════════════

# COMPLAINTS — ACTIONS

# ══════════════════════════════════════════════════════════════════

@router.patch("/complaints/{complaint_id}/edit", tags=["Complaints"])

def edit_complaint(complaint_id: str, description: str = None, location: str = None,

                   u: dict = Depends(require_student)):

    item = _get_or_404(complaint_id)

    if item["status"] != "Pending" and u["role"] != "admin":

        raise HTTPException(status_code=400, detail="Can only edit Pending complaints")

    upd = {}

    if description: upd["description"] = description

    if location:    upd["location"]    = location

    if not upd:     raise HTTPException(status_code=400, detail="Nothing to update")

    upd["updated_at"] = datetime.now(timezone.utc)

    complaints.update_one({"complaint_id": complaint_id}, {"$set": upd})

    return {"message": "Complaint updated"}



@router.patch("/complaints/{complaint_id}/upvote", tags=["Complaints"])

def upvote(complaint_id: str, u: dict = Depends(require_student)):

    item  = _get_or_404(complaint_id)

    email = u["email"]

    if email in item.get("upvoted_by", []):

        complaints.update_one({"complaint_id": complaint_id}, {

            "$inc": {"upvotes": -1}, "$pull": {"upvoted_by": email},

            "$set": {"updated_at": datetime.now(timezone.utc)}})

        return {"message": "Upvote removed"}

    complaints.update_one({"complaint_id": complaint_id}, {

        "$inc": {"upvotes": 1}, "$push": {"upvoted_by": email},

        "$set": {"updated_at": datetime.now(timezone.utc)}})

    return {"message": "Upvoted"}



@router.post("/complaints/{complaint_id}/comment", tags=["Complaints"])

def add_comment(complaint_id: str, comment: str, u: dict = Depends(require_student)):

    if len(comment.strip()) < 3:

        raise HTTPException(status_code=400, detail="Comment too short")

    now    = datetime.now(timezone.utc)

    result = complaints.update_one({"complaint_id": complaint_id}, {

        "$push": {"comments": {"text": comment, "by": u["email"], "role": u["role"], "created_at": now}},

        "$set":  {"updated_at": now}})

    if result.matched_count == 0:

        raise HTTPException(status_code=404, detail="Complaint not found")

    if u["role"] == "admin":

        item = complaints.find_one({"complaint_id": complaint_id})

        if item:

            push_notification(item["student_id"], complaint_id,

                              f"Admin commented on your complaint {complaint_id}", "comment")

    return {"message": "Comment added"}



@router.post("/complaints/{complaint_id}/admin-note", tags=["Complaints"])

def admin_note(complaint_id: str, note: str, u: dict = Depends(require_admin)):

    now    = datetime.now(timezone.utc)

    result = complaints.update_one({"complaint_id": complaint_id}, {

        "$push": {"admin_notes": {"note": note, "by": u["email"], "created_at": now}},

        "$set":  {"updated_at": now}})

    if result.matched_count == 0:

        raise HTTPException(status_code=404, detail="Complaint not found")

    log_audit(u["email"], "ADMIN_NOTE_ADDED", complaint_id=complaint_id)

    return {"message": "Note added"}



@router.patch("/complaints/{complaint_id}/assign", tags=["Complaints"])

def assign_complaint(complaint_id: str, assigned_to: str, u: dict = Depends(require_admin)):

    item = _get_or_404(complaint_id)

    now  = datetime.now(timezone.utc)

    complaints.update_one({"complaint_id": complaint_id}, {

        "$set":  {"assigned_to": assigned_to, "updated_at": now},

        "$push": {"timeline": {"status": f"Assigned to {assigned_to}", "time": now, "by": u["email"]}}})

    push_notification(item["student_id"], complaint_id,

                      f"Your complaint {complaint_id} assigned to {assigned_to}", "assigned")

    log_audit(u["email"], "COMPLAINT_ASSIGNED", complaint_id=complaint_id, details={"to": assigned_to})

    return {"message": f"Assigned to {assigned_to}"}



@router.post("/complaints/{complaint_id}/reopen", tags=["Complaints"])

def reopen_complaint(complaint_id: str, reason: str, u: dict = Depends(require_student)):

    item = _get_or_404(complaint_id)

    if item["status"] not in ["Rejected", "Resolved"]:

        raise HTTPException(status_code=400, detail="Only Rejected or Resolved complaints can be reopened")

    if len(reason.strip()) < 10:

        raise HTTPException(status_code=400, detail="Please provide a reason (min 10 characters)")

    now = datetime.now(timezone.utc)

    complaints.update_one({"complaint_id": complaint_id}, {

        "$set":  {"status": "Reopened", "updated_at": now},

        "$push": {"timeline": {"status": "Reopened", "time": now, "by": u["email"], "reason": reason}}})

    return {"message": "Complaint reopened successfully"}



@router.patch("/complaints/{complaint_id}/status", tags=["Complaints"])

async def update_status(complaint_id: str, status: str, note: str = None,

                        u: dict = Depends(require_admin)):

    if status not in ALLOWED_STATUSES:

        raise HTTPException(status_code=400, detail="Invalid status")

    item = _get_or_404(complaint_id)

    now  = datetime.now(timezone.utc)

    upd  = {"status": status, "updated_at": now}

    if status == "Resolved":

        upd["resolved_at"] = now

        created = item.get("created_at")

        if created:

            if created.tzinfo is None: created = created.replace(tzinfo=timezone.utc)

            upd["resolution_time_hours"] = round((now - created).total_seconds() / 3600, 2)

    complaints.update_one({"complaint_id": complaint_id}, {

        "$set":  upd,

        "$push": {"timeline": {"status": status, "time": now, "by": u["email"], "note": note}}})

    push_notification(item["student_id"], complaint_id,

                      f"Your complaint {complaint_id} status changed to '{status}'", "status_update")

    student = users.find_one({"student_id": item.get("student_id")}, {"email": 1})

    if student:

        send_email(student["email"], f"Complaint {complaint_id} — {status}",

                   f"Your complaint <b>{complaint_id}</b> has been updated to <b>{status}</b>.")

    log_audit(u["email"], "STATUS_CHANGED", complaint_id=complaint_id,

              details={"from": item["status"], "to": status})



    await manager.send_notification(

        item["student_id"],

        {

            "type": "status_update",

            "complaint_id": complaint_id,

            "new_status": status,

            "message": f"Your complaint {complaint_id} is now {status}"

        }

    )



    return {"message": f"Status updated to {status}"}



@router.delete("/complaints/{complaint_id}", tags=["Complaints"])

def delete_complaint(complaint_id: str, u: dict = Depends(require_admin)):

    item = _get_or_404(complaint_id)

    img  = os.path.join(UPLOAD_FOLDER, item["image"])

    if os.path.exists(img): os.remove(img)

    complaints.delete_one({"complaint_id": complaint_id})

    log_audit(u["email"], "COMPLAINT_DELETED", complaint_id=complaint_id)

    return {"message": "Complaint deleted"}



# ══════════════════════════════════════════════════════════════════

# ADMIN

# ══════════════════════════════════════════════════════════════════

@router.get("/admin/complaints", tags=["Admin"])

def admin_complaints(page: int = 1, limit: int = 20, status: str = None,

                     priority: str = None, category: str = None,

                     assigned_to: str = None, u: dict = Depends(require_admin)):

    q = {"college_id": u.get("college_id")}

    if status:      q["status"]      = status

    if priority:    q["priority"]    = priority

    if category:    q["category"]    = category

    if assigned_to: q["assigned_to"] = assigned_to

    skip  = (page - 1) * limit

    total = complaints.count_documents(q)

    data  = list(complaints.find(q, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit))

    return {"page": page, "limit": limit, "total": total, "complaints": data}



@router.patch("/admin/complaints/bulk-status", tags=["Admin"])

def bulk_status(complaint_ids: list[str], status: str, u: dict = Depends(require_admin)):

    if status not in ALLOWED_STATUSES:

        raise HTTPException(status_code=400, detail="Invalid status")

    now    = datetime.now(timezone.utc)

    result = complaints.update_many(

        {"complaint_id": {"$in": complaint_ids}},

        {"$set":  {"status": status, "updated_at": now},

         "$push": {"timeline": {"status": status, "time": now, "by": u["email"]}}})

    log_audit(u["email"], "BULK_STATUS_UPDATE", details={"count": result.modified_count, "status": status})

    return {"message": f"Updated {result.modified_count} complaints to {status}"}



@router.delete("/admin/complaints/bulk-delete", tags=["Admin"])

def bulk_delete(complaint_ids: list[str], u: dict = Depends(require_admin)):

    items = list(complaints.find({"complaint_id": {"$in": complaint_ids}}))

    for item in items:

        p = os.path.join(UPLOAD_FOLDER, item.get("image", ""))

        if os.path.exists(p): os.remove(p)

    result = complaints.delete_many({"complaint_id": {"$in": complaint_ids}})

    log_audit(u["email"], "BULK_DELETE", details={"count": result.deleted_count})

    return {"message": f"Deleted {result.deleted_count} complaints"}



@router.patch("/admin/complaints/bulk-assign", tags=["Admin"])

def bulk_assign(complaint_ids: list[str], assigned_to: str, u: dict = Depends(require_admin)):

    result = complaints.update_many(

        {"complaint_id": {"$in": complaint_ids}},

        {"$set": {"assigned_to": assigned_to, "updated_at": datetime.now(timezone.utc)}})

    log_audit(u["email"], "BULK_ASSIGN", details={"count": result.modified_count, "to": assigned_to})

    return {"message": f"Assigned {result.modified_count} complaints to {assigned_to}"}



@router.post("/admin/escalate-overdue", tags=["Admin"])

def escalate_overdue(u: dict = Depends(require_admin)):

    now    = datetime.now(timezone.utc)

    result = complaints.update_many(

        {"status": {"$in": ["Pending", "In Progress"]}, "due_date": {"$lt": now}, "escalated": False},

        {"$set":  {"priority": "Emergency", "escalated": True, "updated_at": now},

         "$push": {"timeline": {"status": "Escalated", "time": now, "by": "system"}}})

    return {"escalated": result.modified_count}



@router.get("/admin/users", tags=["Admin"])

def get_users(u: dict = Depends(require_admin)):

    data = list(users.find({"college_id": u.get("college_id")}, {"_id": 0, "password": 0}))

    return {"total": len(data), "users": data}





@router.patch("/admin/users/{email}/role", tags=["Admin"])

def change_role(email: str, role: str, u: dict = Depends(require_admin)):

    if role not in ["student", "admin"]:

        raise HTTPException(status_code=400, detail="Role must be student or admin")

    result = users.update_one({"email": email}, {"$set": {"role": role}})

    if result.matched_count == 0:

        raise HTTPException(status_code=404, detail="User not found")

    log_audit(u["email"], "ROLE_CHANGED", target=email, details={"role": role})

    return {"message": f"{email} role set to {role}"}



@router.delete("/admin/users/{email}", tags=["Admin"])

def delete_user(email: str, u: dict = Depends(require_admin)):

    result = users.delete_one({"email": email})

    if result.deleted_count == 0:

        raise HTTPException(status_code=404, detail="User not found")

    log_audit(u["email"], "USER_DELETED", target=email)

    return {"message": f"User {email} deleted"}



@router.get("/admin/departments", tags=["Admin"])

def list_departments(u: dict = Depends(require_admin)):

    return {"departments": list(departments_col.find({}, {"_id": 0}))}



@router.post("/admin/departments", tags=["Admin"])

def create_dept(name: str, code: str, head: str = None, email: str = None,

                u: dict = Depends(require_admin)):

    if departments_col.find_one({"code": code.upper()}):

        raise HTTPException(status_code=400, detail="Department code already exists")

    departments_col.insert_one({"name": name, "code": code.upper(), "head": head,

                                 "email": email, "created_at": datetime.now(timezone.utc)})

    return {"message": "Department created"}



@router.delete("/admin/departments/{code}", tags=["Admin"])

def delete_dept(code: str, u: dict = Depends(require_admin)):

    result = departments_col.delete_one({"code": code.upper()})

    if result.deleted_count == 0:

        raise HTTPException(status_code=404, detail="Department not found")

    return {"message": "Department deleted"}



@router.get("/admin/audit-logs", tags=["Admin"])

def get_audit_logs(page: int = 1, limit: int = 50, u: dict = Depends(require_admin)):

    skip  = (page - 1) * limit

    total = audit_logs.count_documents({})

    data  = list(audit_logs.find({}, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit))

    return {"page": page, "total": total, "logs": data}



# ══════════════════════════════════════════════════════════════════

# ANALYTICS

# ══════════════════════════════════════════════════════════════════

@router.get("/stats", tags=["Analytics"])

def stats():

    return {

        "total":       complaints.count_documents({}),

        "pending":     complaints.count_documents({"status": "Pending"}),

        "in_progress": complaints.count_documents({"status": "In Progress"}),

        "resolved":    complaints.count_documents({"status": "Resolved"}),

        "rejected":    complaints.count_documents({"status": "Rejected"}),

        "emergency":   complaints.count_documents({"priority": "Emergency"}),

        "high":        complaints.count_documents({"priority": "High"}),

        "escalated":   complaints.count_documents({"escalated": True}),

    }



@router.get("/stats/categories", tags=["Analytics"])

def category_stats():

    result = {cat: complaints.count_documents({"category": cat}) for cat in ALLOWED_CATEGORIES}

    return {"category_stats": {k: v for k, v in result.items() if v > 0}}



@router.get("/analytics/daily", tags=["Analytics"])

def daily(u: dict = Depends(require_admin)):

    now = datetime.now(timezone.utc)

    out = []

    for i in range(6, -1, -1):

        d = now - timedelta(days=i)

        s = d.replace(hour=0,  minute=0,  second=0,  microsecond=0)

        e = d.replace(hour=23, minute=59, second=59, microsecond=999999)

        out.append({"date": s.strftime("%Y-%m-%d"),

                    "count": complaints.count_documents({"created_at": {"$gte": s, "$lte": e}})})

    return {"daily": out}



@router.get("/analytics/weekly", tags=["Analytics"])

def weekly(u: dict = Depends(require_admin)):

    now = datetime.now(timezone.utc)

    out = []

    for i in range(27, -1, -1):

        d = now - timedelta(days=i)

        s = d.replace(hour=0,  minute=0,  second=0,  microsecond=0)

        e = d.replace(hour=23, minute=59, second=59, microsecond=999999)

        out.append({"date": s.strftime("%Y-%m-%d"),

                    "count": complaints.count_documents({"created_at": {"$gte": s, "$lte": e}})})

    return {"weekly": out}



@router.get("/analytics/monthly", tags=["Analytics"])

def monthly(u: dict = Depends(require_admin)):

    now = datetime.now(timezone.utc)

    out = []

    for i in range(11, -1, -1):

        m = now.month - i; y = now.year

        while m <= 0: m += 12; y -= 1

        s = datetime(y, m, 1, tzinfo=timezone.utc)

        e = datetime(y, m+1, 1, tzinfo=timezone.utc) if m < 12 else datetime(y+1, 1, 1, tzinfo=timezone.utc)

        out.append({"month": s.strftime("%Y-%m"),

                    "count": complaints.count_documents({"created_at": {"$gte": s, "$lt": e}})})

    return {"monthly": out}



@router.get("/analytics/yearly", tags=["Analytics"])

def yearly(u: dict = Depends(require_admin)):

    now = datetime.now(timezone.utc)

    out = []

    for i in range(4, -1, -1):

        y = now.year - i

        s = datetime(y, 1, 1, tzinfo=timezone.utc)

        e = datetime(y+1, 1, 1, tzinfo=timezone.utc)

        out.append({"year": y, "count": complaints.count_documents({"created_at": {"$gte": s, "$lt": e}})})

    return {"yearly": out}



@router.get("/analytics/top-locations", tags=["Analytics"])

def top_locations():

    pipeline = [{"$group": {"_id": "$location", "count": {"$sum": 1}}},

                {"$sort": {"count": -1}}, {"$limit": 10}]

    return {"top_locations": [{"location": r["_id"], "count": r["count"]}

                               for r in complaints.aggregate(pipeline)]}



@router.get("/analytics/heatmap", tags=["Analytics"])

def heatmap():

    data = list(complaints.find(

        {"latitude": {"$ne": None}, "longitude": {"$ne": None}},

        {"_id": 0, "complaint_id": 1, "latitude": 1, "longitude": 1,

         "category": 1, "priority": 1, "status": 1}))

    return {"points": data, "total": len(data)}



@router.get("/analytics/leaderboard", tags=["Analytics"])

def leaderboard():

    pipeline = [{"$match": {"status": "Resolved"}},

                {"$group": {"_id": "$student_id", "name": {"$first": "$student_name"}, "resolved": {"$sum": 1}}},

                {"$sort": {"resolved": -1}}, {"$limit": 10}]

    return {"leaderboard": [{"rank": i+1, "student_id": r["_id"], "name": r["name"], "resolved": r["resolved"]}

                             for i, r in enumerate(complaints.aggregate(pipeline))]}



@router.get("/analytics/department-performance", tags=["Analytics"])

def dept_performance(u: dict = Depends(require_admin)):

    pipeline = [{"$group": {"_id": "$assigned_to", "total": {"$sum": 1},

                             "resolved": {"$sum": {"$cond": [{"$eq": ["$status", "Resolved"]}, 1, 0]}},

                             "avg_hours": {"$avg": "$resolution_time_hours"}}},

                {"$sort": {"total": -1}}]

    out = []

    for r in complaints.aggregate(pipeline):

        t = r["total"]; res = r["resolved"]

        out.append({"department": r["_id"], "total": t, "resolved": res,

                    "resolution_rate_%": round(res/t*100, 1) if t else 0,

                    "avg_resolution_hours": round(r["avg_hours"] or 0, 2)})

    return {"departments": out}



@router.get("/profile/{student_id}", tags=["Analytics"])

def profile(student_id: str, u: dict = Depends(require_student)):

    return {

        "student_id": student_id,

        "total":    complaints.count_documents({"student_id": student_id}),

        "pending":  complaints.count_documents({"student_id": student_id, "status": "Pending"}),

        "resolved": complaints.count_documents({"student_id": student_id, "status": "Resolved"}),

        "rejected": complaints.count_documents({"student_id": student_id, "status": "Rejected"}),

    }



# ══════════════════════════════════════════════════════════════════

# REPORTS

# ══════════════════════════════════════════════════════════════════

REPORT_FIELDS = ["complaint_id", "student_id", "student_name", "department",

                 "category", "description", "location", "priority", "status",

                 "assigned_to", "upvotes", "resolution_time_hours", "created_at", "updated_at"]



@router.get("/reports/export/csv", tags=["Reports"])

def export_csv(status: str = None, department: str = None, u: dict = Depends(require_admin)):

    q = {}

    if status:     q["status"]      = status

    if department: q["assigned_to"] = department

    data   = list(complaints.find(q, {"_id": 0}))

    output = io.StringIO()

    writer = csv.DictWriter(output, fieldnames=REPORT_FIELDS, extrasaction="ignore")

    writer.writeheader()

    for row in data:

        writer.writerow({f: _fmt(row.get(f)) for f in REPORT_FIELDS})

    output.seek(0)

    fname = f"complaints_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"

    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",

                             headers={"Content-Disposition": f"attachment; filename={fname}"})



@router.get("/reports/export/excel", tags=["Reports"])

def export_excel(status: str = None, department: str = None, u: dict = Depends(require_admin)):

    try: import openpyxl; from openpyxl.styles import Font, PatternFill, Alignment

    except ImportError: raise HTTPException(status_code=500, detail="Run: pip install openpyxl")

    q = {}

    if status:     q["status"]      = status

    if department: q["assigned_to"] = department

    data = list(complaints.find(q, {"_id": 0}))

    wb   = openpyxl.Workbook(); ws = wb.active; ws.title = "Complaints"

    hfill = PatternFill("solid", fgColor="2563EB"); hfont = Font(bold=True, color="FFFFFF")

    STATUS_COLORS = {"Pending": "FFF3CD", "In Progress": "CCE5FF",

                     "Resolved": "D4EDDA", "Rejected": "F8D7DA"}

    for col, f in enumerate(REPORT_FIELDS, 1):

        c = ws.cell(row=1, column=col, value=f.replace("_", " ").title())

        c.fill = hfill; c.font = hfont; c.alignment = Alignment(horizontal="center")

    for ri, item in enumerate(data, 2):

        for col, f in enumerate(REPORT_FIELDS, 1):

            ws.cell(row=ri, column=col, value=_fmt(item.get(f)))

        color = STATUS_COLORS.get(item.get("status", ""))

        if color:

            fill = PatternFill("solid", fgColor=color)

            for col in range(1, len(REPORT_FIELDS)+1): ws.cell(row=ri, column=col).fill = fill

    for col in ws.columns:

        ws.column_dimensions[col[0].column_letter].width = min(

            max(len(str(c.value or "")) for c in col) + 4, 40)

    out = io.BytesIO(); wb.save(out); out.seek(0)

    fname = f"complaints_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

    return StreamingResponse(out,

        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",

        headers={"Content-Disposition": f"attachment; filename={fname}"})



@router.get("/reports/export/pdf", tags=["Reports"])

def export_pdf(status: str = None, department: str = None, u: dict = Depends(require_admin)):

    try:

        from reportlab.lib.pagesizes import A4, landscape

        from reportlab.lib import colors

        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

        from reportlab.lib.styles import getSampleStyleSheet

        from reportlab.lib.units import mm

    except ImportError:

        raise HTTPException(status_code=500, detail="Run: pip install reportlab")

    q = {}

    if status:     q["status"]      = status

    if department: q["assigned_to"] = department

    data = list(complaints.find(q, {"_id": 0}))

    out  = io.BytesIO()

    doc  = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=10*mm, rightMargin=10*mm)

    styles = getSampleStyleSheet(); elems = []

    elems.append(Paragraph("Smart College Civic Detector — Complaints Report", styles["Title"]))

    elems.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | Total: {len(data)}", styles["Normal"]))

    elems.append(Spacer(1, 6*mm))

    short = ["complaint_id", "student_name", "category", "location", "priority", "status", "assigned_to", "created_at"]

    tdata = [[f.replace("_", " ").title() for f in short]]

    for item in data: tdata.append([_fmt(item.get(f)) for f in short])

    t = Table(tdata, colWidths=[35*mm,30*mm,28*mm,30*mm,20*mm,22*mm,28*mm,28*mm], repeatRows=1)

    t.setStyle(TableStyle([

        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2563EB")),

        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),

        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),

        ("FONTSIZE",   (0,0), (-1,-1), 8),

        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F8F9FA")]),

        ("GRID", (0,0), (-1,-1), 0.3, colors.grey),

        ("TOPPADDING",    (0,0), (-1,-1), 4),

        ("BOTTOMPADDING", (0,0), (-1,-1), 4),

    ]))

    elems.append(t); doc.build(elems); out.seek(0)

    fname = f"complaints_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    return StreamingResponse(out, media_type="application/pdf",

                             headers={"Content-Disposition": f"attachment; filename={fname}"})



@router.get("/reports/monthly", tags=["Reports"])

def monthly_report(year: int = None, month: int = None, u: dict = Depends(require_admin)):

    now = datetime.now(timezone.utc); y = year or now.year; m = month or now.month

    s = datetime(y, m, 1, tzinfo=timezone.utc)

    e = datetime(y, m+1, 1, tzinfo=timezone.utc) if m < 12 else datetime(y+1, 1, 1, tzinfo=timezone.utc)

    q = {"created_at": {"$gte": s, "$lt": e}}

    return {"period": f"{y}-{m:02d}",

            "total":    complaints.count_documents(q),

            "resolved": complaints.count_documents({**q, "status": "Resolved"}),

            "pending":  complaints.count_documents({**q, "status": "Pending"}),

            "rejected": complaints.count_documents({**q, "status": "Rejected"}),

            "emergency": complaints.count_documents({**q, "priority": "Emergency"})}



# ══════════════════════════════════════════════════════════════════

# NOTIFICATIONS

# ══════════════════════════════════════════════════════════════════

@router.get("/notifications/{student_id}", tags=["Notifications"])

def get_notifications(student_id: str, u: dict = Depends(require_student)):

    data = list(notifications_col.find({"student_id": student_id}, {"_id": 0})

                .sort("created_at", -1).limit(50))

    return {"student_id": student_id,

            "unread": sum(1 for n in data if not n["is_read"]),

            "notifications": data}



@router.patch("/notifications/{student_id}/read-all", tags=["Notifications"])

def mark_all_read(student_id: str, u: dict = Depends(require_student)):

    notifications_col.update_many(

        {"student_id": student_id, "is_read": False}, {"$set": {"is_read": True}})

    return {"message": "All notifications marked as read"}



# ══════════════════════════════════════════════════════════════════

# SMART CAMPUS

# ══════════════════════════════════════════════════════════════════

@router.get("/track/{complaint_id}", tags=["Campus"])

def track_complaint(complaint_id: str):

    item = complaints.find_one({"complaint_id": complaint_id},

        {"_id": 0, "complaint_id": 1, "category": 1, "location": 1,

         "status": 1, "priority": 1, "timeline": 1, "created_at": 1,

         "assigned_to": 1, "ai_summary": 1})

    if not item: raise HTTPException(status_code=404, detail="Complaint not found")

    return item



@router.get("/qr/{complaint_id}", tags=["Campus"])

def get_qr(complaint_id: str):

    try: import qrcode

    except ImportError:

        raise HTTPException(status_code=500, detail="Run: pip install qrcode[pil]")

    qr = qrcode.QRCode(version=1, box_size=10, border=4)

    qr.add_data(f"http://localhost:3000/track/{complaint_id}")

    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)

    return StreamingResponse(out, media_type="image/png")



@router.get("/analytics/campus-health", tags=["Map"])

def campus_health(days: int = 30):

    from ai.health_score import get_campus_health

    return get_campus_health(days=days)



@router.get("/analytics/area-health/{location}", tags=["Map"])

def area_health(location: str, days: int = 30):

    from ai.health_score import calculate_area_health

    return calculate_area_health(location=location, days=days)



@router.get("/complaints/{complaint_id}/severity", tags=["Map"])

def complaint_severity(complaint_id: str):

    from ai.severity import calculate_severity

    item = complaints.find_one({"complaint_id": complaint_id}, {"_id": 0})

    if not item:

        raise HTTPException(status_code=404, detail="Complaint not found")

    severity = calculate_severity(

        priority=item.get("priority", "Medium"),

        category=item.get("category", "General"),

        description=item.get("description", ""),

        yolo_objects=item.get("ai_result", {}).get("objects", []),

        escalated=item.get("escalated", False),

        upvotes=item.get("upvotes", 0)

    )

    return {"complaint_id": complaint_id, "severity": severity}



# ══════════════════════════════════════════════════════════════════

# WEBSOCKET

# ══════════════════════════════════════════════════════════════════

@app.websocket("/ws/{student_id}")

async def websocket_endpoint(

    websocket: WebSocket,

    student_id: str

):

    await manager.connect(student_id, websocket)

    try:

        while True:

            await websocket.receive_text()

    except WebSocketDisconnect:

        manager.disconnect(student_id)



# ══════════════════════════════════════════════════════════════════

# START

# ══════════════════════════════════════════════════════════════════

app.include_router(confirmation_router, prefix="/api/v1")

logger.info("Smart College Civic Detector v3.0 started")

app.include_router(router)

app.include_router(feed_router)

app.include_router(chatbot_router)

app.include_router(voice_router)