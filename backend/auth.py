"""
auth.py — Authentication router for GetSpons.

Exposes:
    POST /auth/signup            Register a new user.
    POST /auth/login             Sign in and receive a JWT.
    POST /auth/forgot-password   Send a password-reset email via Supabase.
    POST /auth/reset-password    Set a new password using a reset token.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from database import supabase
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class AuthInput(BaseModel):
    email: str
    password: str


class ForgotPasswordInput(BaseModel):
    email: EmailStr


class ResetPasswordInput(BaseModel):
    access_token: str
    new_password: str


# ---------------------------------------------------------------------------
# POST /auth/signup
# ---------------------------------------------------------------------------


@router.post("/signup")
def signup(data: AuthInput):
    log.info("Signup attempt | email=%s", data.email)
    try:
        res = supabase.auth.sign_up({
            "email": data.email,
            "password": data.password,
        })
        user_id = res.user.id
        log.info("Signup successful | email=%s | user_id=%s", data.email, user_id)
        return {"success": True, "user_id": user_id}
    except Exception as exc:
        log.warning("Signup failed | email=%s | reason=%s", data.email, exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


@router.post("/login")
def login(data: AuthInput):
    log.info("Login attempt | email=%s", data.email)
    try:
        res = supabase.auth.sign_in_with_password({
            "email": data.email,
            "password": data.password,
        })
        user_id = res.user.id
        log.info("Login successful | email=%s | user_id=%s", data.email, user_id)
        return {
            "access_token": res.session.access_token,
            "user_id": user_id,
        }
    except Exception as exc:
        log.warning("Login failed | email=%s | reason=%s", data.email, exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# POST /auth/forgot-password
# ---------------------------------------------------------------------------


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordInput):
    log.info("Password reset requested | email=%s", data.email)
    try:
        supabase.auth.reset_password_email(data.email)
        log.info("Password reset email sent | email=%s", data.email)
        return {"success": True, "message": "Reset email sent"}
    except Exception as exc:
        log.warning("Password reset failed | email=%s | reason=%s", data.email, exc)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to send reset email: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# POST /auth/reset-password
# ---------------------------------------------------------------------------


@router.post("/reset-password")
def reset_password(data: ResetPasswordInput):
    log.info("Password reset attempt with token")
    try:
        supabase.auth.set_session(data.access_token, data.access_token)
        supabase.auth.update_user({"password": data.new_password})
        log.info("Password reset successful")
        return {"success": True, "message": "Password updated"}
    except Exception as exc:
        log.warning("Password reset failed | reason=%s", exc)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to reset password: {exc}",
        ) from exc