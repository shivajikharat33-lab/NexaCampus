from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
import re


# ── Auth Models ───────────────────────────────────────────────────
class RegisterModel(BaseModel):
    name: str
    email: EmailStr
    password: str
    college_name: str
    student_id: Optional[str] = None
    department: Optional[str] = None
    year: Optional[str] = None
    phone: Optional[str] = None

    @field_validator("college_name")
    @classmethod
    def college_valid(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError("College name required")
        return v

    @field_validator("name")
    @classmethod
    def name_valid(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Name must be at least 2 characters")
        if len(v) > 100:
            raise ValueError("Name too long")
        return v

    @field_validator("password")
    @classmethod
    def password_strong(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one number")
        if not re.search(r"[^a-zA-Z0-9]", v):
            raise ValueError("Password must contain at least one special character")
        return v

    @field_validator("student_id")
    @classmethod
    def student_id_format(cls, v):
        if v is None:
            return v
        v = v.strip().upper()
        # Accepts formats like: 22CS001, 2022BCE0045, STU-001
        if not re.match(r"^[A-Z0-9\-]{3,20}$", v):
            raise ValueError("Invalid student ID format")
        return v

    @field_validator("phone")
    @classmethod
    def phone_valid(cls, v):
        if v is None:
            return v
        digits = re.sub(r"[\s\-\+\(\)]", "", v)
        if not re.match(r"^\d{10,13}$", digits):
            raise ValueError("Invalid phone number")
        return digits


class LoginModel(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordModel(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strong(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Must contain uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Must contain a number")
        if not re.search(r"[^a-zA-Z0-9]", v):
            raise ValueError("Must contain a special character")
        return v


class ForgotPasswordModel(BaseModel):
    email: EmailStr


class ResetPasswordModel(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strong(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class RefreshTokenModel(BaseModel):
    refresh_token: str


# ── User Models ───────────────────────────────────────────────────
class UpdateProfileModel(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    department: Optional[str] = None
    year: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, v):
        if v is None:
            return v
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Name too short")
        return v


# ── Complaint Models ──────────────────────────────────────────────
class CommentModel(BaseModel):
    comment: str

    @field_validator("comment")
    @classmethod
    def comment_valid(cls, v):
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Comment too short")
        if len(v) > 1000:
            raise ValueError("Comment too long (max 1000 chars)")
        return v


class StatusUpdateModel(BaseModel):
    status: str
    note: Optional[str] = None


class AdminNoteModel(BaseModel):
    note: str

    @field_validator("note")
    @classmethod
    def note_valid(cls, v):
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Note too short")
        if len(v) > 2000:
            raise ValueError("Note too long")
        return v


class ReopenModel(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def reason_valid(cls, v):
        v = v.strip()
        if len(v) < 10:
            raise ValueError("Please provide a reason (min 10 characters)")
        return v


class AssignModel(BaseModel):
    assigned_to: str
    note: Optional[str] = None


class BulkStatusModel(BaseModel):
    complaint_ids: list[str]
    status: str

    @field_validator("complaint_ids")
    @classmethod
    def ids_not_empty(cls, v):
        if not v:
            raise ValueError("No complaint IDs provided")
        if len(v) > 100:
            raise ValueError("Max 100 complaints at once")
        return v


class BulkDeleteModel(BaseModel):
    complaint_ids: list[str]


class BulkAssignModel(BaseModel):
    complaint_ids: list[str]
    assigned_to: str


# ── Department Models ─────────────────────────────────────────────

class DepartmentModel(BaseModel):
    name: str
    code: str
    head: Optional[str] = None
    email: Optional[EmailStr] = None
    categories: list[str] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def code_upper(cls, v):
        return v.strip().upper()


class UpdateDepartmentModel(BaseModel):
    name: Optional[str] = None
    head: Optional[str] = None
    email: Optional[EmailStr] = None
    categories: Optional[list[str]] = None