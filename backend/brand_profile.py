"""
brand_profile.py — Brand profile router for GetSpons.

Exposes:
    POST  /brand-profile/save              Upsert brand profile.
    GET   /brand-profile/me                Fetch brand profile.
    POST  /brand-profile/generate-brief    AI-generate and save campaign brief.
    GET   /brand-profile/brief             Return saved campaign brief.

Caching
-------
    GET /brand-profile/me     key: "brand_profile_{brand_user_id}"   TTL: 300s
    GET /brand-profile/brief  key: "campaign_brief_{brand_user_id}"  TTL: 300s
    Both caches are cleared on every successful save / generate.

brand_profiles table schema (including new campaign columns)
-------------------------------------------------------------
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
    campaign_brief      TEXT    (JSON string of the full brief object)
    campaign_goal       TEXT
    target_audience     TEXT
    content_type        TEXT
    key_message         TEXT
    campaign_timeline   TEXT
    created_at          TIMESTAMPTZ default now()
    updated_at          TIMESTAMPTZ default now()
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, field_validator, model_validator

from ai import generate_campaign_brief
from brand_auth import get_brand_user_id
from cache import cache
from database import supabase_admin
from limiter import limiter
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)

_BRAND_PROFILE_TTL = 300   # 5 minutes
_BRIEF_TTL         = 300   # 5 minutes

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PRESET_NICHES = {
    "Finance", "Fitness", "Beauty", "Tech", "Food",
    "Travel", "Gaming", "Fashion", "Education", "Entertainment",
}

ALLOWED_PLATFORMS = {"Instagram", "YouTube", "Both"}


# ---------------------------------------------------------------------------
# Request models
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

    @field_validator("niche")
    @classmethod
    def niche_valid(cls, v: str) -> str:
        v = v.strip()
        if v not in PRESET_NICHES:
            raise ValueError(
                f"Invalid niche '{v}'. Must be one of: {sorted(PRESET_NICHES)}."
            )
        return v

    @field_validator("secondary_niches")
    @classmethod
    def secondary_niches_valid(cls, v: Optional[List[str]]) -> List[str]:
        if not v:
            return []
        if len(v) > 3:
            raise ValueError(f"secondary_niches can contain at most 3 items. Got {len(v)}.")
        invalid = [n for n in v if n not in PRESET_NICHES]
        if invalid:
            raise ValueError(
                f"Invalid secondary niche(s): {invalid}. "
                f"Must be one of: {sorted(PRESET_NICHES)}."
            )
        if len(v) != len(set(v)):
            raise ValueError("secondary_niches cannot contain duplicate values.")
        return v

    @field_validator("preferred_platforms")
    @classmethod
    def platforms_valid(cls, v: Optional[List[str]]) -> List[str]:
        if not v:
            return []
        invalid = [p for p in v if p not in ALLOWED_PLATFORMS]
        if invalid:
            raise ValueError(
                f"Invalid platform(s): {invalid}. Allowed: {sorted(ALLOWED_PLATFORMS)}."
            )
        if len(v) != len(set(v)):
            raise ValueError("preferred_platforms cannot contain duplicate values.")
        return v

    @model_validator(mode="after")
    def cross_field_checks(self) -> "BrandProfileInput":
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min <= 0:
                raise ValueError("budget_min must be greater than 0.")
            if self.budget_max <= 0:
                raise ValueError("budget_max must be greater than 0.")
            if self.budget_min >= self.budget_max:
                raise ValueError(
                    f"budget_min must be strictly less than budget_max. "
                    f"Got min={self.budget_min}, max={self.budget_max}."
                )
        if self.min_followers is not None and self.max_followers is not None:
            if self.min_followers < 0:
                raise ValueError("min_followers cannot be negative.")
            if self.max_followers <= 0:
                raise ValueError("max_followers must be greater than 0.")
            if self.min_followers >= self.max_followers:
                raise ValueError(
                    f"min_followers must be strictly less than max_followers. "
                    f"Got min={self.min_followers}, max={self.max_followers}."
                )
        if self.secondary_niches and self.niche in self.secondary_niches:
            raise ValueError(
                f"secondary_niches cannot contain the primary niche ('{self.niche}')."
            )
        return self


class GenerateBriefInput(BaseModel):
    campaign_goal:     str
    target_audience:   str
    content_type:      str
    key_message:       str
    budget_min:        int
    budget_max:        int
    campaign_timeline: str

    @field_validator("campaign_goal", "target_audience", "content_type",
                     "key_message", "campaign_timeline")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Field cannot be empty.")
        return v

    @model_validator(mode="after")
    def budget_order(self) -> "GenerateBriefInput":
        if self.budget_min <= 0:
            raise ValueError("budget_min must be greater than 0.")
        if self.budget_max <= 0:
            raise ValueError("budget_max must be greater than 0.")
        if self.budget_min >= self.budget_max:
            raise ValueError(
                f"budget_min must be strictly less than budget_max. "
                f"Got min={self.budget_min}, max={self.budget_max}."
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

    Clears both the brand profile cache and any cached match results.

    Returns  { success: true }
    """
    brand_user_id = get_brand_user_id(authorization)
    log.info("Brand profile save attempt | brand_user_id=%s", brand_user_id)

    try:
        now = datetime.now(timezone.utc).isoformat()
        supabase_admin.table("brand_profiles").upsert(
            {
                "brand_user_id": brand_user_id,
                "updated_at":    now,
                **data.model_dump(),
            },
            on_conflict="brand_user_id",
        ).execute()

        cache.delete(f"brand_profile_{brand_user_id}")
        cache.delete(f"match_{brand_user_id}")

        log.info("Brand profile saved | brand_user_id=%s", brand_user_id)
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
    """Fetch the brand profile for the authenticated brand user. Cached 300s.

    Raises  404 if no profile has been saved yet.
    """
    brand_user_id = get_brand_user_id(authorization)
    cache_key = f"brand_profile_{brand_user_id}"

    cached = cache.get(cache_key)
    if cached is not None:
        return cached

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


# ---------------------------------------------------------------------------
# POST /brand-profile/generate-brief
# ---------------------------------------------------------------------------


@router.post("/generate-brief")
@limiter.limit("10/hour")
def generate_brief(
    request:       Request,
    data:          GenerateBriefInput,
    authorization: str = Header(...),
):
    """Generate an AI-powered campaign brief and persist it.

    Flow
    ----
    1.  Authenticate brand user.
    2.  Fetch existing brand profile to enrich the brief context.
    3.  Call generate_campaign_brief() with merged data.
    4.  Serialise brief to JSON string and save to brand_profiles.campaign_brief,
        also updating the campaign_* columns for future reference.
    5.  Bust profile and brief caches.
    6.  Return the generated brief dict.

    Rate limit: 10/hour per IP (AI call is expensive).

    Returns  { brief } — the full campaign brief object.
    """
    brand_user_id = get_brand_user_id(authorization)
    log.info("Campaign brief generation started | brand_user_id=%s", brand_user_id)

    # ── Fetch existing brand profile for enrichment context ──────────
    try:
        profile_res = (
            supabase_admin
            .table("brand_profiles")
            .select(
                "company_name, niche, description, website, "
                "budget_min, budget_max, preferred_platforms"
            )
            .eq("brand_user_id", brand_user_id)
            .single()
            .execute()
        )
        existing_profile = profile_res.data or {}
    except Exception:
        # No existing profile is fine — we'll use the brief input data alone
        existing_profile = {}
        log.info(
            "No existing brand profile found for brief context | brand_user_id=%s",
            brand_user_id,
        )

    # ── Merge brief input with existing profile data ──────────────────
    merged: dict = {
        **existing_profile,               # base context (company_name, niche, etc.)
        "campaign_goal":     data.campaign_goal,
        "target_audience":   data.target_audience,
        "content_type":      data.content_type,
        "key_message":       data.key_message,
        "budget_min":        data.budget_min,
        "budget_max":        data.budget_max,
        "campaign_timeline": data.campaign_timeline,
    }

    # ── Generate brief via AI ─────────────────────────────────────────
    try:
        brief = generate_campaign_brief(merged)
    except Exception as exc:
        log.error(
            "Campaign brief AI generation failed | brand_user_id=%s | reason=%s",
            brand_user_id, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate campaign brief: {exc}",
        ) from exc

    log.info("Campaign brief generated | brand_user_id=%s", brand_user_id)

    # ── Persist to brand_profiles ─────────────────────────────────────
    try:
        now = datetime.now(timezone.utc).isoformat()
        supabase_admin.table("brand_profiles").upsert(
            {
                "brand_user_id":     brand_user_id,
                "campaign_brief":    json.dumps(brief),   # stored as JSON string
                "campaign_goal":     data.campaign_goal,
                "target_audience":   data.target_audience,
                "content_type":      data.content_type,
                "key_message":       data.key_message,
                "campaign_timeline": data.campaign_timeline,
                "updated_at":        now,
            },
            on_conflict="brand_user_id",
        ).execute()
    except Exception as exc:
        log.error(
            "Campaign brief DB save failed | brand_user_id=%s | reason=%s",
            brand_user_id, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Brief generated but failed to save: {exc}",
        ) from exc

    # Bust both caches
    cache.delete(f"brand_profile_{brand_user_id}")
    cache.delete(f"campaign_brief_{brand_user_id}")

    log.info("Campaign brief saved | brand_user_id=%s", brand_user_id)
    return {"brief": brief}


# ---------------------------------------------------------------------------
# GET /brand-profile/brief
# ---------------------------------------------------------------------------


@router.get("/brief")
def get_campaign_brief(authorization: str = Header(...)):
    """Return the saved campaign brief for the authenticated brand.

    The brief is stored as a JSON string in brand_profiles.campaign_brief
    and returned as a parsed dict.

    Returns  { brief, campaign_goal, target_audience, content_type,
               key_message, campaign_timeline }

    Raises   404 if no brief has been generated yet.
    """
    brand_user_id = get_brand_user_id(authorization)
    cache_key = f"campaign_brief_{brand_user_id}"

    cached = cache.get(cache_key)
    if cached is not None:
        log.debug("Campaign brief cache hit | brand_user_id=%s", brand_user_id)
        return cached

    log.info("Campaign brief fetch | brand_user_id=%s", brand_user_id)

    try:
        result = (
            supabase_admin
            .table("brand_profiles")
            .select(
                "campaign_brief, campaign_goal, target_audience, "
                "content_type, key_message, campaign_timeline"
            )
            .eq("brand_user_id", brand_user_id)
            .single()
            .execute()
        )
        row = result.data
    except Exception as exc:
        msg = str(exc).lower()
        if "no rows" in msg or "json object requested" in msg:
            raise HTTPException(
                status_code=404,
                detail="No campaign brief found. Generate one first.",
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch campaign brief: {exc}",
        ) from exc

    if not row or not row.get("campaign_brief"):
        raise HTTPException(
            status_code=404,
            detail="No campaign brief found. Use POST /brand-profile/generate-brief first.",
        )

    # Parse the stored JSON string back into a dict
    try:
        brief_dict = json.loads(row["campaign_brief"])
    except (json.JSONDecodeError, TypeError) as exc:
        log.error(
            "Campaign brief JSON parse error | brand_user_id=%s | reason=%s",
            brand_user_id, exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Stored campaign brief is malformed. Please regenerate it.",
        ) from exc

    response = {
        "brief":             brief_dict,
        "campaign_goal":     row.get("campaign_goal"),
        "target_audience":   row.get("target_audience"),
        "content_type":      row.get("content_type"),
        "key_message":       row.get("key_message"),
        "campaign_timeline": row.get("campaign_timeline"),
    }

    cache.set(cache_key, response, ttl_seconds=_BRIEF_TTL)
    return response