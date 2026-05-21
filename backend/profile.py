"""
profile.py — Creator profile router for GetSpons.

Exposes:
    POST /profile/save   Create or update the authenticated creator's profile.
    GET  /profile/me     Fetch the authenticated creator's profile.
"""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, List
from database import supabase, supabase_admin

router = APIRouter()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRESET_NICHES = {
    "Finance",
    "Fitness",
    "Beauty",
    "Tech",
    "Food",
    "Travel",
    "Gaming",
    "Fashion",
    "Education",
    "Entertainment",
}


# ---------------------------------------------------------------------------
# Request model with validation
# ---------------------------------------------------------------------------


class ProfileInput(BaseModel):
    full_name: str
    platform: str
    handle: str
    followers: int
    niche: str
    engagement_rate: float
    bio: str
    past_sponsors: Optional[List[str]] = []
    pricing_min: int
    pricing_max: int

    # ── handle cannot be empty ──────────────────────────────────────
    @field_validator("handle")
    @classmethod
    def handle_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Handle cannot be empty.")
        return v

    # ── followers must be > 0 ───────────────────────────────────────
    @field_validator("followers")
    @classmethod
    def followers_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Followers must be greater than 0.")
        return v

    # ── engagement_rate must be between 0 and 100 ───────────────────
    @field_validator("engagement_rate")
    @classmethod
    def engagement_in_range(cls, v: float) -> float:
        if not (0.0 <= v <= 100.0):
            raise ValueError("Engagement rate must be between 0 and 100.")
        return v

    # ── niche: preset list OR any non-empty custom value ────────────
    # This mirrors a frontend that shows a dropdown with an "Other /
    # Custom" option where the user can type their own niche.
    @field_validator("niche")
    @classmethod
    def niche_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError(
                "Niche cannot be empty. "
                f"Choose one of {sorted(PRESET_NICHES)} or enter a custom niche."
            )
        # Accept any non-empty string — preset OR custom
        return v

    # ── pricing_min must be < pricing_max ───────────────────────────
    @model_validator(mode="after")
    def pricing_range_valid(self) -> "ProfileInput":
        if self.pricing_min is not None and self.pricing_max is not None:
            if self.pricing_min <= 0:
                raise ValueError("Minimum pricing must be greater than 0.")
            if self.pricing_max <= 0:
                raise ValueError("Maximum pricing must be greater than 0.")
            if self.pricing_min >= self.pricing_max:
                raise ValueError(
                    "pricing_min must be strictly less than pricing_max. "
                    f"Got min={self.pricing_min}, max={self.pricing_max}."
                )
        return self


# ---------------------------------------------------------------------------
# POST /profile/save
# ---------------------------------------------------------------------------


@router.post("/save")
def save_profile(data: ProfileInput, authorization: str = Header(...)):
    """Create or update the authenticated creator's profile.

    Parameters
    ----------
    data:
        Validated profile payload.
    authorization:
        ``Authorization: Bearer <jwt>`` header.

    Returns
    -------
    dict
        ``{ success: true }`` on success.

    Raises
    ------
    HTTPException 401   Invalid or expired token.
    HTTPException 422   Pydantic validation error (handled automatically).
    HTTPException 400   Any other error (e.g. database write failure).
    """
    try:
        token = authorization.replace("Bearer ", "").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Missing auth token.")
        user = supabase.auth.get_user(token)
        user_id = user.user.id
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {exc}",
        ) from exc

    try:
        supabase_admin.table("profiles").upsert({
            "user_id": user_id,
            **data.model_dump(),
        }).execute()
        return {"success": True}
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to save profile: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# GET /profile/me
# ---------------------------------------------------------------------------


@router.get("/me")
def get_profile(authorization: str = Header(...)):
    """Fetch the authenticated creator's profile.

    Parameters
    ----------
    authorization:
        ``Authorization: Bearer <jwt>`` header.

    Returns
    -------
    dict
        The profile row from the ``profiles`` table.

    Raises
    ------
    HTTPException 401   Invalid or expired token.
    HTTPException 404   No profile found for this user.
    HTTPException 400   Any other error.
    """
    try:
        token = authorization.replace("Bearer ", "").strip()
        if not token:
            raise HTTPException(status_code=401, detail="Missing auth token.")
        user = supabase_admin.auth.get_user(token)
        user_id = user.user.id
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {exc}",
        ) from exc

    try:
        res = (
            supabase_admin
            .table("profiles")
            .select("*")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if not res.data:
            raise HTTPException(
                status_code=404,
                detail="No profile found. Please complete your creator profile first.",
            )
        return res.data
    except HTTPException:
        raise
    except Exception as exc:
        msg = str(exc).lower()
        if "no rows" in msg or "json object requested" in msg:
            raise HTTPException(
                status_code=404,
                detail="No profile found. Please complete your creator profile first.",
            ) from exc
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch profile: {exc}",
        ) from exc