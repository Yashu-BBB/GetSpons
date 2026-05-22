"""
brand_auth.py — Brand authentication router for GetSpons.

Brands are separate from creators and have their own auth tables:
    brand_users    — stores brand user records (user_id, email, company_name)
    brand_profiles — stores extended brand profile data (managed elsewhere)

Exposes:
    POST /brand-auth/register        Register a new brand account.
    POST /brand-auth/login           Sign in and receive a JWT.
    POST /brand-auth/forgot-password Send a password-reset email.

Helper (importable by other brand routers):
    get_brand_user_id(token)         Validate token + verify brand user exists.

brand_users table schema expected:
    id           UUID PK default gen_random_uuid()
    user_id      UUID (references auth.users)
    email        TEXT
    company_name TEXT
    created_at   TIMESTAMPTZ default now()
"""

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr

from database import supabase, supabase_admin
from limiter import limiter
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class BrandRegisterInput(BaseModel):
    email:        EmailStr
    password:     str
    company_name: str


class BrandLoginInput(BaseModel):
    email:    EmailStr
    password: str


class BrandForgotPasswordInput(BaseModel):
    email: EmailStr


# ---------------------------------------------------------------------------
# Shared helper — importable by other brand routers
# ---------------------------------------------------------------------------


def get_brand_user_id(authorization: str) -> str:
    """Validate a Bearer token and confirm the caller is a brand user.

    Performs two checks:
    1. Token is valid Supabase JWT → resolves ``auth_user_id``.
    2. A row exists in ``brand_users`` for that ``auth_user_id``.

    Parameters
    ----------
    authorization:
        Raw value of the ``Authorization`` header, e.g. ``"Bearer <jwt>"``.

    Returns
    -------
    str
        The ``id`` (primary key) of the brand_users row — **not** the
        Supabase auth UUID.  Use this as the foreign key in all brand
        tables.

    Raises
    ------
    HTTPException 401
        If the token is missing, malformed, expired, or the caller has no
        entry in brand_users.
    """
    # ── Step 1: validate JWT ──────────────────────────────────────────
    try:
        token: str = authorization.replace("Bearer ", "").strip()
        if not token:
            raise ValueError("Empty token")
        user = supabase.auth.get_user(token)
        auth_user_id: str = user.user.id
    except Exception as exc:
        log.warning("Brand token validation failed | reason=%s", exc)
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {exc}",
        ) from exc

    # ── Step 2: confirm caller exists in brand_users ──────────────────
    try:
        result = (
            supabase_admin
            .table("brand_users")
            .select("id")
            .eq("user_id", auth_user_id)
            .single()
            .execute()
        )
        brand_user = result.data
    except Exception as exc:
        msg = str(exc).lower()
        if "no rows" in msg or "json object requested" in msg:
            log.warning(
                "Brand auth check failed — not a brand user | auth_user_id=%s",
                auth_user_id,
            )
            raise HTTPException(
                status_code=401,
                detail="Not authorised as a brand user.",
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to verify brand user: {exc}",
        ) from exc

    if not brand_user:
        log.warning(
            "Brand auth check failed — no brand_users row | auth_user_id=%s",
            auth_user_id,
        )
        raise HTTPException(
            status_code=401,
            detail="Not authorised as a brand user.",
        )

    return brand_user["id"]


# ---------------------------------------------------------------------------
# POST /brand-auth/register  — 5/hour per IP
# ---------------------------------------------------------------------------


@router.post("/register")
@limiter.limit("5/hour")
def brand_register(request: Request, data: BrandRegisterInput):
    """Register a new brand account.

    Flow
    ----
    1. Create a Supabase auth user with email + password.
    2. Insert a row into brand_users with user_id, email, company_name.
    3. Return success + brand_user_id.

    Parameters
    ----------
    data:
        JSON body: { email, password, company_name }

    Returns
    -------
    dict
        ``{ success: true, brand_user_id }``

    Raises
    ------
    HTTPException 400
        If Supabase auth signup fails (e.g. email already registered).
    HTTPException 500
        If the brand_users insert fails after auth user creation.
    """
    log.info("Brand register attempt | email=%s | company=%s", data.email, data.company_name)

    # ── Step 1: create Supabase auth user ────────────────────────────
    try:
        auth_res = supabase.auth.sign_up({
            "email":    data.email,
            "password": data.password,
        })
        auth_user_id: str = auth_res.user.id
        log.info("Brand Supabase auth user created | auth_user_id=%s", auth_user_id)
    except Exception as exc:
        log.warning(
            "Brand register failed (auth step) | email=%s | reason=%s",
            data.email, exc,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Registration failed: {exc}",
        ) from exc

    # ── Step 2: insert into brand_users ──────────────────────────────
    try:
        insert_res = (
            supabase_admin
            .table("brand_users")
            .insert({
                "user_id":      auth_user_id,
                "email":        data.email,
                "company_name": data.company_name,
            })
            .execute()
        )
        brand_user_id: str = insert_res.data[0]["id"]
    except Exception as exc:
        log.error(
            "Brand register failed (db insert) | auth_user_id=%s | reason=%s",
            auth_user_id, exc,
        )
        # Auth user was created but brand_users insert failed.
        # Attempt to clean up the orphaned auth user so the email is free to retry.
        try:
            supabase_admin.auth.admin.delete_user(auth_user_id)
            log.info("Orphaned auth user cleaned up | auth_user_id=%s", auth_user_id)
        except Exception as cleanup_exc:
            log.error(
                "Orphaned auth user cleanup failed | auth_user_id=%s | reason=%s",
                auth_user_id, cleanup_exc,
            )
        raise HTTPException(
            status_code=500,
            detail=f"Account created but profile save failed: {exc}",
        ) from exc

    log.info(
        "Brand register successful | email=%s | brand_user_id=%s",
        data.email, brand_user_id,
    )
    return {"success": True, "brand_user_id": brand_user_id}


# ---------------------------------------------------------------------------
# POST /brand-auth/login  — 10/hour per IP
# ---------------------------------------------------------------------------


@router.post("/login")
@limiter.limit("10/hour")
def brand_login(request: Request, data: BrandLoginInput):
    """Sign in a brand user and return a JWT.

    Flow
    ----
    1. Authenticate via Supabase (email + password).
    2. Verify the caller has a row in brand_users.
    3. Return access_token + brand_user_id.

    Parameters
    ----------
    data:
        JSON body: { email, password }

    Returns
    -------
    dict
        ``{ access_token, brand_user_id }``

    Raises
    ------
    HTTPException 401
        If credentials are wrong or user is not in brand_users.
    """
    log.info("Brand login attempt | email=%s", data.email)

    # ── Step 1: authenticate ─────────────────────────────────────────
    try:
        auth_res = supabase.auth.sign_in_with_password({
            "email":    data.email,
            "password": data.password,
        })
        access_token:  str = auth_res.session.access_token
        auth_user_id:  str = auth_res.user.id
    except Exception as exc:
        log.warning("Brand login failed (auth step) | email=%s | reason=%s", data.email, exc)
        raise HTTPException(
            status_code=401,
            detail=f"Login failed: {exc}",
        ) from exc

    # ── Step 2: verify brand_users membership ────────────────────────
    try:
        result = (
            supabase_admin
            .table("brand_users")
            .select("id")
            .eq("user_id", auth_user_id)
            .single()
            .execute()
        )
        brand_user = result.data
    except Exception as exc:
        msg = str(exc).lower()
        if "no rows" in msg or "json object requested" in msg:
            log.warning(
                "Brand login rejected — not a brand user | email=%s",
                data.email,
            )
            raise HTTPException(
                status_code=401,
                detail="This account is not registered as a brand.",
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to verify brand user: {exc}",
        ) from exc

    if not brand_user:
        log.warning("Brand login rejected — no brand_users row | email=%s", data.email)
        raise HTTPException(
            status_code=401,
            detail="This account is not registered as a brand.",
        )

    brand_user_id: str = brand_user["id"]
    log.info(
        "Brand login successful | email=%s | brand_user_id=%s",
        data.email, brand_user_id,
    )
    return {
        "access_token":  access_token,
        "brand_user_id": brand_user_id,
    }


# ---------------------------------------------------------------------------
# POST /brand-auth/forgot-password  — 3/hour per IP
# ---------------------------------------------------------------------------


@router.post("/forgot-password")
@limiter.limit("3/hour")
def brand_forgot_password(request: Request, data: BrandForgotPasswordInput):
    """Send a password-reset email to the given brand email address.

    Parameters
    ----------
    data:
        JSON body: { email }

    Returns
    -------
    dict
        ``{ success: true, message: "Reset email sent" }``

    Raises
    ------
    HTTPException 400
        If Supabase fails to send the reset email.
    """
    log.info("Brand password reset requested | email=%s", data.email)

    try:
        supabase.auth.reset_password_email(data.email)
        log.info("Brand password reset email sent | email=%s", data.email)
        return {"success": True, "message": "Reset email sent"}
    except Exception as exc:
        log.warning(
            "Brand password reset failed | email=%s | reason=%s",
            data.email, exc,
        )
        raise HTTPException(
            status_code=400,
            detail=f"Failed to send reset email: {exc}",
        ) from exc