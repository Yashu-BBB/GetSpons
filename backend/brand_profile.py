"""
brand_profile.py — Brand profile router for GetSpons.

Exposes:
    POST /brand-profile/save   Upsert brand profile for the logged-in brand.
    GET  /brand-profile/me     Fetch brand profile for the logged-in brand.

Caching
-------
    GET  /brand-profile/me  key: "brand_profile_{brand_user_id}"  TTL: 300s
    Cache is cleared on every successful POST /brand-profile/save.
    match.py also clears "match_{brand_user_id}" on save so stale
    match results are not served after a profile update.

brand_profiles table schema expected
-------------------------------------
    id                  UUID PK default gen_random_uuid()
    brand_user_id       UUID REFERENCES brand_users(id) ON DELETE CASCADE
    company_name        TEXT
    contact_person      TEXT
    contact_email       TEXT
    niche               TEXT
    secondary_niches    TEXT[]  default '{}'
    budget_min          INT
    budget_max          INT
    min_followers       INT
    max_followers       INT
    preferred_platforms TEXT[]
    description         TEXT
    website             TEXT
    instagram_handle    TEXT
    created_at          TIMESTAMPTZ default now()
    updated_at          TIMESTAMPTZ default now()
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr, field_validator, model_validator

from brand_auth import get_brand_user_id
from cache import cache
from database import supabase_admin
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)

_BRAND_PROFILE_TTL = 300   # 5 minutes

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRESET_NICHES = {
    "Finance", "Fitness", "Beauty", "Tech", "Food",
    "Travel", "Gaming", "Fashion", "Education", "Entertainment",
}

ALLOWED_PLATFORMS = {"Instagram", "YouTube", "Both"}


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class BrandProfileInput(BaseModel):
    company_name:        str
    contact_person:      str
    contact_email:       EmailStr
    niche:               str
    secondary_niches:    Optional[List[str]] = []
    budget_min:          int
    budget_max:          int
    min_followers:       int
    max_followers:       int
    preferred_platforms: Optional[List[str]] = []
    description:         Optional[str]       = ""
    website:             Optional[str]       = ""
    instagram_handle:    Optional[str]       = ""

    # ── niche must be from preset list ──────────────────────────────
    @field_validator("niche")
    @classmethod
    def niche_valid(cls, v: str) -> str:
        v = v.strip()
        if v not in PRESET_NICHES:
            raise ValueError(
                f"Invalid niche '{v}'. Must be one of: {sorted(PRESET_NICHES)}."
            )
        return v

    # ── secondary_niches: max 3, preset only, no overlap with primary
    @field_validator("secondary_niches")
    @classmethod
    def secondary_niches_valid(cls, v: Optional[List[str]]) -> List[str]:
        if not v:
            return []
        if len(v) > 3:
            raise ValueError(
                f"secondary_niches can contain at most 3 items. Got {len(v)}."
            )
        invalid = [n for n in v if n not in PRESET_NICHES]
        if invalid:
            raise ValueError(
                f"Invalid secondary niche(s): {invalid}. "
                f"Must be one of: {sorted(PRESET_NICHES)}."
            )
        if len(v) != len(set(v)):
            raise ValueError("secondary_niches cannot contain duplicate values.")
        return v

    # ── preferred_platforms must be valid values ────────────────────
    @field_validator("preferred_platforms")
    @classmethod
    def platforms_valid(cls, v: Optional[List[str]]) -> List[str]:
        if not v:
            return []
        invalid = [p for p in v if p not in ALLOWED_PLATFORMS]
        if invalid:
            raise ValueError(
                f"Invalid platform(s): {invalid}. "
                f"Allowed: {sorted(ALLOWED_PLATFORMS)}."
            )
        if len(v) != len(set(v)):
            raise ValueError("preferred_platforms cannot contain duplicate values.")
        return v

    # ── cross-field checks ──────────────────────────────────────────
    @model_validator(mode="after")
    def cross_field_checks(self) -> "BrandProfileInput":
        # budget_min < budget_max
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min <= 0:
                raise ValueError("budget_min must be greater than 0.")
            if self.budget_max <= 0:
                raise ValueError("budget_max must be greater than 0.")
            if self.budget_min >= self.budget_max:
                raise ValueError(
                    "budget_min must be strictly less than budget_max. "
                    f"Got min={self.budget_min}, max={self.budget_max}."
                )

        # min_followers < max_followers
        if self.min_followers is not None and self.max_followers is not None:
            if self.min_followers < 0:
                raise ValueError("min_followers cannot be negative.")
            if self.max_followers <= 0:
                raise ValueError("max_followers must be greater than 0.")
            if self.min_followers >= self.max_followers:
                raise ValueError(
                    "min_followers must be strictly less than max_followers. "
                    f"Got min={self.min_followers}, max={self.max_followers}."
                )

        # secondary_niches cannot overlap with primary niche
        if self.secondary_niches and self.niche in self.secondary_niches:
            raise ValueError(
                f"secondary_niches cannot contain the primary niche ('{self.niche}')."
            )

        return self


# ---------------------------------------------------------------------------
# POST /brand-profile/save
# ---------------------------------------------------------------------------


@router.post("/save")
def save_brand_profile(
    data: BrandProfileInput,
    authorization: str = Header(...),
):
    """Upsert brand profile for the authenticated brand user.

    Clears both the brand profile cache and any cached match results
    so stale data is never served after an update.

    Returns
    -------
    dict  { success: true }

    Raises
    ------
    HTTPException 401   Invalid token or not a brand user.
    HTTPException 500   Database write failed.
    """
    brand_user_id = get_brand_user_id(authorization)
    log.info("Brand profile save attempt | brand_user_id=%s", brand_user_id)

    try:
        now = datetime.now(timezone.utc).isoformat()
        supabase_admin.table("brand_profiles").upsert(
            {
                "brand_user_id":      brand_user_id,
                "updated_at":         now,
                **data.model_dump(),
            },
            on_conflict="brand_user_id",
        ).execute()

        # Invalidate profile cache and match cache for this brand
        cache.delete(f"brand_profile_{brand_user_id}")
        cache.delete(f"match_{brand_user_id}")

        log.info("Brand profile saved successfully | brand_user_id=%s", brand_user_id)
        return {"success": True}

    except Exception as exc:
        log.error(
            "Brand profile save failed | brand_user_id=%s | reason=%s",
            brand_user_id, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save brand profile: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# GET /brand-profile/me
# ---------------------------------------------------------------------------


@router.get("/me")
def get_brand_profile(authorization: str = Header(...)):
    """Fetch the brand profile for the authenticated brand user.

    Returns the full brand_profiles row. Cached for 300 seconds.

    Raises
    ------
    HTTPException 401   Invalid token or not a brand user.
    HTTPException 404   No profile saved yet.
    HTTPException 500   Database read failed.
    """
    brand_user_id = get_brand_user_id(authorization)
    cache_key = f"brand_profile_{brand_user_id}"

    # ── Cache hit ─────────────────────────────────────────────────────
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # ── Cache miss — query Supabase ───────────────────────────────────
    log.info("Brand profile fetch | brand_user_id=%s", brand_user_id)

    try:
        result = (
            supabase_admin
            .table("brand_profiles")
            .select("*")
            .eq("brand_user_id", brand_user_id)
            .single()
            .execute()
        )
        data = result.data
    except Exception as exc:
        msg = str(exc).lower()
        if "no rows" in msg or "json object requested" in msg:
            raise HTTPException(
                status_code=404,
                detail="No brand profile found. Please complete your brand profile first.",
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch brand profile: {exc}",
        ) from exc

    if not data:
        raise HTTPException(
            status_code=404,
            detail="No brand profile found. Please complete your brand profile first.",
        )

    cache.set(cache_key, data, ttl_seconds=_BRAND_PROFILE_TTL)
    return data