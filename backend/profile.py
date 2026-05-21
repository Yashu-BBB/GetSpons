"""
profile.py — Creator profile router for GetSpons.

Exposes:
    POST /profile/save   Create or update the authenticated creator's profile.
    GET  /profile/me     Fetch the authenticated creator's profile.

Caching
-------
    GET /profile/me  key: "profile_{user_id}"  TTL: 300s
    Cache is cleared on every successful POST /profile/save.
"""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, List

from cache import cache
from database import supabase, supabase_admin
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)

_PROFILE_TTL = 300   # 5 minutes

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRESET_NICHES = {
    "Finance", "Fitness", "Beauty", "Tech", "Food",
    "Travel", "Gaming", "Fashion", "Education", "Entertainment",
}


# ---------------------------------------------------------------------------
# Request model with validation
# ---------------------------------------------------------------------------


class ProfileInput(BaseModel):
    full_name:       str
    platform:        str
    handle:          str
    followers:       int
    niche:           str
    engagement_rate: float
    bio:             str
    past_sponsors:   Optional[List[str]] = []
    pricing_min:     int
    pricing_max:     int

    @field_validator("handle")
    @classmethod
    def handle_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Handle cannot be empty.")
        return v

    @field_validator("followers")
    @classmethod
    def followers_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Followers must be greater than 0.")
        return v

    @field_validator("engagement_rate")
    @classmethod
    def engagement_in_range(cls, v: float) -> float:
        if not (0.0 <= v <= 100.0):
            raise ValueError("Engagement rate must be between 0 and 100.")
        return v

    @field_validator("niche")
    @classmethod
    def niche_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError(
                "Niche cannot be empty. "
                f"Choose one of {sorted(PRESET_NICHES)} or enter a custom niche."
            )
        return v

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

    Clears the profile cache for this user on success so the next
    GET /profile/me fetches fresh data.
    """
    # ── Auth ─────────────────────────────────────────────────────────
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

    log.info("Profile save attempt | user_id=%s", user_id)

    # ── Save ─────────────────────────────────────────────────────────
    try:
        supabase_admin.table("profiles").upsert({
            "user_id": user_id,
            **data.model_dump(),
        }).execute()

        # Invalidate cached profile so next read is fresh
        cache.delete(f"profile_{user_id}")
        log.info("Profile saved successfully | user_id=%s", user_id)
        return {"success": True}

    except Exception as exc:
        log.error("Profile save failed | user_id=%s | reason=%s", user_id, exc)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to save profile: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# GET /profile/me
# ---------------------------------------------------------------------------


@router.get("/me")
def get_profile(authorization: str = Header(...)):
    """Fetch the authenticated creator's profile. Cached for 300 seconds."""
    # ── Auth ─────────────────────────────────────────────────────────
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

    cache_key = f"profile_{user_id}"

    # ── Cache hit ─────────────────────────────────────────────────────
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # ── Cache miss — query Supabase ───────────────────────────────────
    log.info("Profile fetch | user_id=%s", user_id)

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

        cache.set(cache_key, res.data, ttl_seconds=_PROFILE_TTL)
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