from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from jose import JWTError

from database import users
from auth import (
    create_access_token, create_refresh_token, decode_refresh_token,
    create_reset_token, decode_reset_token,
    is_account_locked, get_lockout_update, reset_login_attempts
)
from auth_middleware import get_current_user
from password_utils import hash_password, verify_password
from notifications import send_email
from models import (
    RegisterModel, LoginModel, ChangePasswordModel,
    ForgotPasswordModel, ResetPasswordModel,
    RefreshTokenModel, UpdateProfileModel
)
from logger import logger, log_audit

router = APIRouter(tags=["Users"])


@router.post("/register")
def register(body: RegisterModel):
    if users.find_one({"email": body.email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    users.insert_one({
        "name": body.name,
        "email": body.email,
        "password": hash_password(body.password),
        "student_id": body.student_id,
        "department": body.department,
        "year": body.year,
        "phone": body.phone,
        "role": "student",
        "failed_attempts": 0,
        "locked_until": None,
        "last_login": None,
        "created_at": datetime.now(timezone.utc)
    })
    logger.info(f"New user registered: {body.email}")
    return {"message": "User registered successfully"}


@router.post("/login")
def login(body: LoginModel):
    user = users.find_one({"email": body.email})

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Check account lockout
    if is_account_locked(user):
        raise HTTPException(
            status_code=423,
            detail=f"Account locked. Try again after {user.get('locked_until')}"
        )

    if not verify_password(body.password, user["password"]):
        # Increment failed attempts
        update = get_lockout_update(user.get("failed_attempts", 0))
        users.update_one({"email": body.email}, {"$set": update})
        remaining = max(0, 5 - update["failed_attempts"])
        raise HTTPException(
            status_code=401,
            detail=f"Invalid password. {remaining} attempts remaining"
        )

    # Success — reset lockout counter
    users.update_one({"email": body.email}, {"$set": reset_login_attempts()})

    access_token  = create_access_token({"email": user["email"], "role": user["role"]})
    refresh_token = create_refresh_token({"email": user["email"], "role": user["role"]})

    logger.info(f"Login: {body.email}")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "role": user["role"],
        "name": user["name"]
    }


@router.post("/refresh")
def refresh_token(body: RefreshTokenModel):
    try:
        payload = decode_refresh_token(body.refresh_token)
        email = payload.get("email")
        role  = payload.get("role")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    new_access  = create_access_token({"email": email, "role": role})
    new_refresh = create_refresh_token({"email": email, "role": role})

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer"
    }


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.patch("/me/profile")
def update_profile(body: UpdateProfileModel, current_user: dict = Depends(get_current_user)):
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = datetime.now(timezone.utc)
    users.update_one({"email": current_user["email"]}, {"$set": update})
    return {"message": "Profile updated"}


@router.patch("/me/change-password")
def change_password(body: ChangePasswordModel, current_user: dict = Depends(get_current_user)):
    user = users.find_one({"email": current_user["email"]})
    if not verify_password(body.old_password, user["password"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    users.update_one(
        {"email": current_user["email"]},
        {"$set": {"password": hash_password(body.new_password)}}
    )
    log_audit(current_user["email"], "PASSWORD_CHANGED")
    return {"message": "Password changed successfully"}


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordModel):
    user = users.find_one({"email": body.email})
    # Always return success to avoid email enumeration
    if user:
        token = create_reset_token(body.email)
        reset_link = f"http://localhost:3000/reset-password?token={token}"
        send_email(
            body.email,
            "Reset Your Password",
            f"Click this link to reset your password (valid 30 minutes):<br><br>"
            f"<a href='{reset_link}'>{reset_link}</a><br><br>"
            f"If you did not request this, ignore this email."
        )
        logger.info(f"Password reset requested for {body.email}")
    return {"message": "If that email exists, a reset link has been sent"}


@router.post("/reset-password")
def reset_password(body: ResetPasswordModel):
    try:
        email = decode_reset_token(body.token)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    users.update_one(
        {"email": email},
        {"$set": {"password": hash_password(body.new_password), "failed_attempts": 0, "locked_until": None}}
    )
    log_audit(email, "PASSWORD_RESET")
    return {"message": "Password reset successfully"}