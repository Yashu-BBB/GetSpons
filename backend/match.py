"""
match.py — Creator matching engine router for GetSpons.

Exposes:
    GET /match/creators
        Returns creators matching the authenticated brand's requirements,
        split into primary and secondary matches.

Matching logic
--------------
Primary match (all conditions must be true):
    creator.niche          == brand.niche
    creator.followers      >= brand.min_followers
    creator.followers      <= brand.max_followers
    creator.pricing_min    <= brand.budget_max

Secondary match (all conditions must be true, primary creators excluded):
    brand.niche in creator.secondary_niches
    creator.followers   >= brand.min_followers
    creator.followers   <= brand.max_followers
    creator.pricing_min <= brand.budget_max

Both groups are sorted by pricing_min ASC.
Primary matches are listed first in the combined response.

Privacy
-------
Only safe creator fields are returned — no user_id or internal data.

Caching
-------
    key: "match_{brand_user_id}"  TTL: 300s
    Cleared by brand_profile.py on every successful profile save.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from brand_auth import get_brand_user_id
from cache import cache
from database import supabase_admin
from limiter import limiter
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)

_MATCH_TTL = 300   # 5 minutes

# Fields returned for each creator — no user_id or internal data
_CREATOR_FIELDS = (
    "full_name, handle, platform, followers, niche, secondary_niches, "
    "engagement_rate, bio, pricing_min, pricing_max, past_sponsors"
)


# ---------------------------------------------------------------------------
# GET /match/creators
# ---------------------------------------------------------------------------


@router.get("/creators")
@limiter.limit("30/hour")
def match_creators(request: Request, authorization: str = Header(...)):
    """Return creators matching the authenticated brand's requirements.

    Response shape
    --------------
    {
        "primary":   [ { ...creator_fields, "match_type": "primary"   }, ... ],
        "secondary": [ { ...creator_fields, "match_type": "secondary" }, ... ],
        "total":     int
    }

    Raises
    ------
    HTTPException 401   Invalid token or not a brand user.
    HTTPException 404   Brand has no saved profile yet.
    HTTPException 500   Database query failed.
    """
    brand_user_id = get_brand_user_id(authorization)
    cache_key = f"match_{brand_user_id}"

    # ── Cache hit ─────────────────────────────────────────────────────
    cached = cache.get(cache_key)
    if cached is not None:
        log.info(
            "Match results served from cache | brand_user_id=%s", brand_user_id
        )
        return cached

    # ── Fetch brand profile ───────────────────────────────────────────
    try:
        bp_res = (
            supabase_admin
            .table("brand_profiles")
            .select(
                "niche, secondary_niches, budget_max, "
                "min_followers, max_followers"
            )
            .eq("brand_user_id", brand_user_id)
            .single()
            .execute()
        )
        brand = bp_res.data
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

    if not brand:
        raise HTTPException(
            status_code=404,
            detail="No brand profile found. Please complete your brand profile first.",
        )

    brand_niche:       str = brand.get("niche", "")
    budget_max:        int = int(brand.get("budget_max") or 0)
    min_followers:     int = int(brand.get("min_followers") or 0)
    max_followers:     int = int(brand.get("max_followers") or 0)

    log.info(
        "Match query started | brand_user_id=%s | niche=%s | followers=%d-%d | budget_max=%d",
        brand_user_id, brand_niche, min_followers, max_followers, budget_max,
    )

    # ── Step 1: Primary matches ───────────────────────────────────────
    # creator.niche == brand.niche  AND  follower + price filters
    primary_creators: list[dict[str, Any]] = []
    primary_ids:      set[str] = set()

    try:
        primary_res = (
            supabase_admin
            .table("profiles")
            .select(_CREATOR_FIELDS)
            .eq("niche", brand_niche)
            .gte("followers", min_followers)
            .lte("followers", max_followers)
            .lte("pricing_min", budget_max)
            .order("pricing_min", desc=False)
            .execute()
        )

        for creator in (primary_res.data or []):
            creator["match_type"] = "primary"
            primary_creators.append(creator)
            # Use handle as a deduplication key (user_id is intentionally
            # not exposed in the response, but we need something unique)
            primary_ids.add(creator.get("handle", ""))

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch primary matches: {exc}",
        ) from exc

    log.info(
        "Primary matches found | brand_user_id=%s | count=%d",
        brand_user_id, len(primary_creators),
    )

    # ── Step 2: Secondary matches ─────────────────────────────────────
    # brand.niche in creator.secondary_niches  AND  same follower/price filters
    # Exclude creators already in primary results
    secondary_creators: list[dict[str, Any]] = []

    try:
        # PostgREST array-contains operator: cs (contains)
        secondary_res = (
            supabase_admin
            .table("profiles")
            .select(_CREATOR_FIELDS)
            .contains("secondary_niches", [brand_niche])   # brand niche in creator's secondary list
            .gte("followers", min_followers)
            .lte("followers", max_followers)
            .lte("pricing_min", budget_max)
            .order("pricing_min", desc=False)
            .execute()
        )

        for creator in (secondary_res.data or []):
            handle = creator.get("handle", "")
            if handle in primary_ids:
                continue   # already in primary results
            creator["match_type"] = "secondary"
            secondary_creators.append(creator)

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch secondary matches: {exc}",
        ) from exc

    log.info(
        "Secondary matches found | brand_user_id=%s | count=%d",
        brand_user_id, len(secondary_creators),
    )

    # ── Build response ────────────────────────────────────────────────
    response = {
        "primary":   primary_creators,
        "secondary": secondary_creators,
        "total":     len(primary_creators) + len(secondary_creators),
    }

    cache.set(cache_key, response, ttl_seconds=_MATCH_TTL)
    log.info(
        "Match results cached | brand_user_id=%s | total=%d",
        brand_user_id, response["total"],
    )

    return response