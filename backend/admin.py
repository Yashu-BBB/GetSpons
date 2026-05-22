"""
admin.py — Admin utility router for GetSpons.

All endpoints are protected by the X-Admin-Key header whose value must
match the ADMIN_KEY environment variable.

Exposes:
    POST  /admin/cache/clear              Clear entire in-memory cache.
    GET   /admin/users                    List all creators with plan info.
    GET   /admin/brands                   List all brand users with profile info.
    PATCH /admin/users/{user_id}/plan     Update a creator's subscription plan.
    PATCH /admin/brands/{brand_id}/approve  Approve or deactivate a brand.
    GET   /admin/stats                    Platform-wide counts.

Tables accessed
---------------
    profiles        — creator profiles
    user_settings   — creator plan (free / pro / agency)
    brand_users     — brand accounts
    brand_profiles  — brand profile + active flag
    pitches         — pitch rows
    mediakits       — media kit rows
"""

from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from cache import cache
from database import supabase_admin
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Allowed plan values
# ---------------------------------------------------------------------------

ALLOWED_PLANS = {"free", "pro", "agency"}


# ---------------------------------------------------------------------------
# Shared admin-key guard
# ---------------------------------------------------------------------------


def _verify_admin_key(x_admin_key: str) -> None:
    """Raise 401/500 if the provided key does not match ADMIN_KEY env var.

    Raises
    ------
    HTTPException 500   ADMIN_KEY not set in environment.
    HTTPException 401   Provided key is wrong.
    """
    admin_key = os.getenv("ADMIN_KEY", "").strip()
    if not admin_key:
        log.error("ADMIN_KEY is not set in environment")
        raise HTTPException(
            status_code=500,
            detail="Admin key not configured. Set ADMIN_KEY in your .env file.",
        )
    if x_admin_key != admin_key:
        log.warning(
            "Unauthorized admin request | provided_key=%s***",
            x_admin_key[:6] if len(x_admin_key) >= 6 else "???",
        )
        raise HTTPException(status_code=401, detail="Invalid admin key.")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class UpdatePlanInput(BaseModel):
    plan: str   # validated manually for a clear error message


class ApproveInput(BaseModel):
    active: bool


# ---------------------------------------------------------------------------
# POST /admin/cache/clear
# ---------------------------------------------------------------------------


@router.post("/cache/clear")
def clear_cache(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    """Clear the entire in-memory cache.

    Returns
    -------
    dict  { success, message, entries_removed }
    """
    _verify_admin_key(x_admin_key)
    removed = cache.clear_all()
    log.info("Admin cache clear | entries_removed=%d", removed)
    return {
        "success":         True,
        "message":         "Cache cleared",
        "entries_removed": removed,
    }


# ---------------------------------------------------------------------------
# GET /admin/users
# ---------------------------------------------------------------------------


@router.get("/users")
def list_users(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    """Return all creators from the profiles table, with their current plan.

    Fetches profiles and user_settings separately, then merges by user_id.
    Returns ``plan: null`` for creators who have no user_settings row.

    Returns
    -------
    list[dict]
        Each item: user_id, full_name, platform, followers, niche,
        pricing_min, pricing_max, created_at, plan.
    """
    _verify_admin_key(x_admin_key)
    log.info("Admin: listing all creators")

    # ── Fetch profiles ────────────────────────────────────────────────
    try:
        profiles_res = (
            supabase_admin
            .table("profiles")
            .select(
                "user_id, full_name, platform, followers, niche, "
                "pricing_min, pricing_max, created_at"
            )
            .order("created_at", desc=True)
            .execute()
        )
        profiles: list[dict] = profiles_res.data or []
    except Exception as exc:
        log.error("Admin: failed to fetch profiles | reason=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch creators: {exc}",
        ) from exc

    if not profiles:
        return []

    # ── Fetch user_settings for plan info ─────────────────────────────
    try:
        settings_res = (
            supabase_admin
            .table("user_settings")
            .select("user_id, plan")
            .execute()
        )
        # Build lookup: { user_id: plan }
        plan_map: dict[str, str] = {
            row["user_id"]: row.get("plan", "free")
            for row in (settings_res.data or [])
        }
    except Exception as exc:
        log.error("Admin: failed to fetch user_settings | reason=%s", exc)
        # Non-fatal — return profiles with plan=null rather than failing
        plan_map = {}

    # ── Merge plan into each profile ──────────────────────────────────
    for profile in profiles:
        profile["plan"] = plan_map.get(profile["user_id"], None)

    log.info("Admin: creators listed | count=%d", len(profiles))
    return profiles


# ---------------------------------------------------------------------------
# GET /admin/brands
# ---------------------------------------------------------------------------


@router.get("/brands")
def list_brands(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    """Return all brand accounts with their profile info if it exists.

    Fetches brand_users and brand_profiles separately, merges by brand_user_id.
    Returns ``niche: null, budget_min: null, budget_max: null, active: null``
    for brands that have not yet saved a profile.

    Returns
    -------
    list[dict]
        Each item: id, email, company_name, created_at,
        niche, budget_min, budget_max, active.
    """
    _verify_admin_key(x_admin_key)
    log.info("Admin: listing all brands")

    # ── Fetch brand_users ─────────────────────────────────────────────
    try:
        bu_res = (
            supabase_admin
            .table("brand_users")
            .select("id, email, company_name, created_at")
            .order("created_at", desc=True)
            .execute()
        )
        brands: list[dict] = bu_res.data or []
    except Exception as exc:
        log.error("Admin: failed to fetch brand_users | reason=%s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch brands: {exc}",
        ) from exc

    if not brands:
        return []

    # ── Fetch brand_profiles for niche, budget, active ───────────────
    try:
        bp_res = (
            supabase_admin
            .table("brand_profiles")
            .select("brand_user_id, niche, budget_min, budget_max, active")
            .execute()
        )
        # Build lookup: { brand_user_id: { niche, budget_min, budget_max, active } }
        profile_map: dict[str, dict] = {
            row["brand_user_id"]: {
                "niche":      row.get("niche"),
                "budget_min": row.get("budget_min"),
                "budget_max": row.get("budget_max"),
                "active":     row.get("active"),
            }
            for row in (bp_res.data or [])
        }
    except Exception as exc:
        log.error("Admin: failed to fetch brand_profiles | reason=%s", exc)
        # Non-fatal — return brands with null profile fields
        profile_map = {}

    # ── Merge profile info into each brand ────────────────────────────
    for brand in brands:
        pdata = profile_map.get(brand["id"], {})
        brand["niche"]      = pdata.get("niche")
        brand["budget_min"] = pdata.get("budget_min")
        brand["budget_max"] = pdata.get("budget_max")
        brand["active"]     = pdata.get("active")

    log.info("Admin: brands listed | count=%d", len(brands))
    return brands


# ---------------------------------------------------------------------------
# PATCH /admin/users/{user_id}/plan
# ---------------------------------------------------------------------------


@router.patch("/users/{user_id}/plan")
def update_user_plan(
    user_id: str,
    data: UpdatePlanInput,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    """Update or insert a creator's subscription plan in user_settings.

    Parameters
    ----------
    user_id:
        The UUID from the profiles / auth.users table.
    data:
        JSON body: { "plan": "free" | "pro" | "agency" }

    Returns
    -------
    dict  { success, user_id, plan }

    Raises
    ------
    HTTPException 422   Plan value is not in the allowed set.
    HTTPException 500   Database write failed.
    """
    _verify_admin_key(x_admin_key)

    if data.plan not in ALLOWED_PLANS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid plan '{data.plan}'. "
                f"Allowed values: {', '.join(sorted(ALLOWED_PLANS))}."
            ),
        )

    log.info("Admin: updating plan | user_id=%s | plan=%s", user_id, data.plan)

    try:
        supabase_admin.table("user_settings").upsert(
            {"user_id": user_id, "plan": data.plan},
            on_conflict="user_id",
        ).execute()
    except Exception as exc:
        log.error(
            "Admin: plan update failed | user_id=%s | reason=%s", user_id, exc
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update plan: {exc}",
        ) from exc

    # Invalidate profile cache so any cached GET /profile/me reflects the
    # new plan on the next fetch (if plan is included in that response).
    cache.delete(f"profile_{user_id}")

    log.info("Admin: plan updated | user_id=%s | plan=%s", user_id, data.plan)
    return {"success": True, "user_id": user_id, "plan": data.plan}


# ---------------------------------------------------------------------------
# PATCH /admin/brands/{brand_id}/approve
# ---------------------------------------------------------------------------


@router.patch("/brands/{brand_id}/approve")
def approve_brand(
    brand_id: str,
    data: ApproveInput,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
):
    """Set the active flag on a brand's profile row.

    ``brand_id`` is the UUID from brand_users.id (same as
    brand_profiles.brand_user_id).

    Parameters
    ----------
    brand_id:
        UUID of the brand_users row.
    data:
        JSON body: { "active": true | false }

    Returns
    -------
    dict  { success, brand_id, active }

    Raises
    ------
    HTTPException 404   No brand_profiles row found for this brand_id.
    HTTPException 500   Database write failed.
    """
    _verify_admin_key(x_admin_key)
    log.info(
        "Admin: brand approve/deactivate | brand_id=%s | active=%s",
        brand_id, data.active,
    )

    # Verify brand_profiles row exists before updating
    try:
        check_res = (
            supabase_admin
            .table("brand_profiles")
            .select("brand_user_id")
            .eq("brand_user_id", brand_id)
            .single()
            .execute()
        )
        existing = check_res.data
    except Exception as exc:
        msg = str(exc).lower()
        if "no rows" in msg or "json object requested" in msg:
            raise HTTPException(
                status_code=404,
                detail=f"No brand profile found for brand_id '{brand_id}'.",
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to verify brand profile: {exc}",
        ) from exc

    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"No brand profile found for brand_id '{brand_id}'.",
        )

    # Apply update
    try:
        supabase_admin.table("brand_profiles").update(
            {"active": data.active}
        ).eq("brand_user_id", brand_id).execute()
    except Exception as exc:
        log.error(
            "Admin: brand approval failed | brand_id=%s | reason=%s",
            brand_id, exc,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update brand active status: {exc}",
        ) from exc

    # Invalidate brand profile cache
    cache.delete(f"brand_profile_{brand_id}")

    log.info(
        "Admin: brand active updated | brand_id=%s | active=%s",
        brand_id, data.active,
    )
    return {"success": True, "brand_id": brand_id, "active": data.active}


# ---------------------------------------------------------------------------
# GET /admin/stats
# ---------------------------------------------------------------------------


@router.get("/stats")
def get_stats(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    """Return platform-wide aggregate counts.

    Runs five separate COUNT queries against:
        profiles, brand_users, pitches, mediakits, user_settings.

    Returns
    -------
    dict
        total_creators, total_brands, total_pitches,
        total_mediakits, pro_users.
    """
    _verify_admin_key(x_admin_key)
    log.info("Admin: fetching platform stats")

    def _count(table: str, filters: dict | None = None) -> int:
        """Return row count for *table*, optionally filtered."""
        try:
            q = supabase_admin.table(table).select("*", count="exact", head=True)
            if filters:
                for col, val in filters.items():
                    q = q.eq(col, val)
            res = q.execute()
            return res.count or 0
        except Exception as exc:
            log.error("Admin: count failed | table=%s | reason=%s", table, exc)
            return 0

    # pro_users = rows in user_settings where plan is 'pro' OR 'agency'
    # Supabase doesn't support OR filters cleanly in a single .eq(),
    # so we fetch both and sum.
    def _count_pro() -> int:
        try:
            pro_res = (
                supabase_admin
                .table("user_settings")
                .select("plan")
                .in_("plan", ["pro", "agency"])
                .execute()
            )
            return len(pro_res.data or [])
        except Exception as exc:
            log.error("Admin: pro_users count failed | reason=%s", exc)
            return 0

    stats = {
        "total_creators":  _count("profiles"),
        "total_brands":    _count("brand_users"),
        "total_pitches":   _count("pitches"),
        "total_mediakits": _count("mediakits"),
        "pro_users":       _count_pro(),
    }

    log.info("Admin: stats fetched | %s", stats)
    return stats