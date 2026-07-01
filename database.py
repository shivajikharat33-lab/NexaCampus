from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure
import os
from config import MONGO_URL, DB_NAME   # ← removed the broken await line

try:
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    db = client[DB_NAME]

    # Collections
    complaints = db["complaints"]
    users = db["users"]
    chat_logs = db["chat_logs"]          # ← add this

    # Complaint Indexes
    complaints.create_index("complaint_id", unique=True)
    complaints.create_index("student_id")
    complaints.create_index("category")
    complaints.create_index("status")
    complaints.create_index("priority")
    complaints.create_index("location")
    complaints.create_index("image_hash")
    complaints.create_index("created_at")
    complaints.create_index([("status", ASCENDING), ("priority", ASCENDING)])
    complaints.create_index([("category", "text"), ("description", "text")])
    complaints.create_index([("created_at", DESCENDING)])

    # User Indexes
    users.create_index("email", unique=True)
    users.create_index("role")
    users.create_index("created_at")

    # Chat Log Indexes                   # ← add this
    chat_logs.create_index([("student_id", ASCENDING), ("timestamp", DESCENDING)])

    print("MongoDB Connected ✅")

except ConnectionFailure:
    print("MongoDB Connection Failed ❌")
    raise