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

router = APIRouter()


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
    """Register a new user with email and password.

    Returns
    -------
    dict
        ``{ success, user_id }`` on success, ``{ error }`` on failure.
    """
    try:
        res = supabase.auth.sign_up({
            "email": data.email,
            "password": data.password,
        })
        return {"success": True, "user_id": res.user.id}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


@router.post("/login")
def login(data: AuthInput):
    """Sign in with email and password.

    Returns
    -------
    dict
        ``{ access_token, user_id }`` on success, ``{ error }`` on failure.
    """
    try:
        res = supabase.auth.sign_in_with_password({
            "email": data.email,
            "password": data.password,
        })
        return {
            "access_token": res.session.access_token,
            "user_id": res.user.id,
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# POST /auth/forgot-password
# ---------------------------------------------------------------------------


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordInput):
    """Send a password-reset email to the given address.

    Supabase emails the user a link that contains a short-lived reset token.
    The link redirects to your frontend where the user sets a new password
    (handled by POST /auth/reset-password).

    Parameters
    ----------
    data:
        JSON body containing ``email``.

    Returns
    -------
    dict
        ``{ success: true, message: "Reset email sent" }``

    Raises
    ------
    HTTPException 400
        If the email address is invalid, not registered, or Supabase
        returns any other error.
    """
    try:
        supabase.auth.reset_password_email(data.email)
        return {"success": True, "message": "Reset email sent"}
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to send reset email: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# POST /auth/reset-password
# ---------------------------------------------------------------------------


@router.post("/reset-password")
def reset_password(data: ResetPasswordInput):
    """Set a new password using the access token from the reset email.

    Flow
    ----
    1. The user clicks the reset link in their email.
    2. Supabase redirects to your frontend with an ``access_token`` in the
       URL fragment (e.g. ``/#access_token=...&type=recovery``).
    3. Your frontend extracts the token and POSTs it here along with the
       new password chosen by the user.
    4. This endpoint calls ``supabase.auth.set_session()`` to activate the
       token, then ``supabase.auth.update_user()`` to persist the new password.

    Parameters
    ----------
    data:
        JSON body containing ``access_token`` and ``new_password``.

    Returns
    -------
    dict
        ``{ success: true, message: "Password updated" }``

    Raises
    ------
    HTTPException 400
        If the token is invalid, expired, or the password update fails.
    """
    try:
        # Activate the recovery session with the token from the reset email
        supabase.auth.set_session(data.access_token, data.access_token)

        # Update the user's password within that session
        supabase.auth.update_user({"password": data.new_password})

        return {"success": True, "message": "Password updated"}

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to reset password: {exc}",
        ) from exc