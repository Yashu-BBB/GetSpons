"""
brands.py — Brands router for GetSpons.

Exposes:
    GET /brands              Lightweight list with optional filters.
    GET /brands/{brand_id}   Full brand detail.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from database import supabase_admin
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Column sets
# ---------------------------------------------------------------------------

_LIST_COLUMNS = (
    "id, name, niche, min_followers, max_followers, "
    "content_types, campaign_budget_min, campaign_budget_max, "
    "instagram_handle, youtube_handle, country, active"
)

_DETAIL_COLUMNS = (
    "id, name, niche, min_followers, max_followers, "
    "content_types, campaign_budget_min, campaign_budget_max, "
    "instagram_handle, youtube_handle, country, active, "
    "description, audience_requirement, contact_email, website"
)


# ---------------------------------------------------------------------------
# GET /brands
# ---------------------------------------------------------------------------


@router.get("/", response_model=None)
def get_brands(
    niche: Optional[str] = Query(default=None),
    min_followers: Optional[int] = Query(default=None, ge=0),
):
    """Return a lightweight list of brands with optional filtering."""
    filters = []
    if niche:
        filters.append(f"niche={niche}")
    if min_followers is not None:
        filters.append(f"min_followers<={min_followers}")

    filter_str = ", ".join(filters) if filters else "none"
    log.info("Brands list fetched | filters=[%s]", filter_str)

    try:
        query = supabase_admin.table("brands").select(_LIST_COLUMNS)

        if niche is not None:
            query = query.eq("niche", niche)
        if min_followers is not None:
            query = query.lte("min_followers", min_followers)

        result = query.execute()
        return result.data or []

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch brands: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# GET /brands/{brand_id}
# ---------------------------------------------------------------------------


@router.get("/{brand_id}", response_model=None)
def get_brand(brand_id: str):
    """Return full detail for a single brand."""
    try:
        result = (
            supabase_admin
            .table("brands")
            .select(_DETAIL_COLUMNS)
            .eq("id", brand_id)
            .single()
            .execute()
        )

        if not result.data:
            log.warning("Brand not found | brand_id=%s", brand_id)
            raise HTTPException(
                status_code=404,
                detail=f"Brand with id '{brand_id}' not found.",
            )

        log.info("Single brand fetched | brand_id=%s", brand_id)
        return result.data

    except HTTPException:
        raise
    except Exception as exc:
        error_str = str(exc).lower()
        if "no rows" in error_str or "json object requested" in error_str:
            log.warning("Brand not found | brand_id=%s", brand_id)
            raise HTTPException(
                status_code=404,
                detail=f"Brand with id '{brand_id}' not found.",
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch brand: {exc}",
        ) from exc