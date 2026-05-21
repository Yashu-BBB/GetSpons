"""
brands.py — Brands router for GetSpons.

Exposes:
    GET /brands
        Returns a lightweight list of all brands (no heavy text fields).
        Supports optional query parameters:
            niche          (str) — filter by niche, e.g. ?niche=Finance
            min_followers  (int) — return brands whose min_followers <= this value
        No authentication required.

    GET /brands/{brand_id}
        Returns full brand detail including all new fields.
        No authentication required.
        Returns 404 if the brand is not found.

Column reference
----------------
List   : id, name, niche, min_followers, max_followers, content_types,
         campaign_budget_min, campaign_budget_max, instagram_handle,
         youtube_handle, country, active
Detail : all of the above + description, audience_requirement, contact_email,
         website
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from database import supabase_admin

router = APIRouter()


# ---------------------------------------------------------------------------
# Column sets
# ---------------------------------------------------------------------------

# Lightweight fields returned in the list view — omits description and
# audience_requirement to keep list responses fast and small.
_LIST_COLUMNS = (
    "id, name, niche, min_followers, max_followers, "
    "content_types, campaign_budget_min, campaign_budget_max, "
    "instagram_handle, youtube_handle, country, active"
)

# Full fields returned for a single brand detail view.
_DETAIL_COLUMNS = (
    "id, name, niche, min_followers, max_followers, "
    "content_types, campaign_budget_min, campaign_budget_max, "
    "instagram_handle, youtube_handle, country, active, "
    "description, audience_requirement, contact_email, website"
)


# ---------------------------------------------------------------------------
# GET /brands  — lightweight list
# ---------------------------------------------------------------------------


@router.get("/", response_model=None)
def get_brands(
    niche: Optional[str] = Query(
        default=None,
        description="Filter brands by niche, e.g. Finance, Tech, Beauty",
    ),
    min_followers: Optional[int] = Query(
        default=None,
        description=(
            "Return only brands whose min_followers requirement is <= this value "
            "(i.e. brands the caller's audience size already qualifies for)"
        ),
        ge=0,
    ),
):
    """Return a lightweight list of brands with optional filtering.

    Heavy text fields (``description``, ``audience_requirement``) are
    intentionally excluded — fetch ``GET /brands/{id}`` for full detail.

    Parameters
    ----------
    niche : str, optional
        Case-sensitive niche string matched against the ``niche`` column.
    min_followers : int, optional
        Filters to brands whose ``min_followers`` is <= this value.

    Returns
    -------
    list[dict]
        Light brand objects. Empty list if no brands match.

    Raises
    ------
    HTTPException 500
        If the Supabase query fails.
    """
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
# GET /brands/{brand_id}  — full detail
# ---------------------------------------------------------------------------


@router.get("/{brand_id}", response_model=None)
def get_brand(brand_id: str):
    """Return full detail for a single brand including all fields.

    Parameters
    ----------
    brand_id : str
        UUID of the brand row.

    Returns
    -------
    dict
        Full brand object including ``description``, ``audience_requirement``,
        ``content_types``, ``campaign_budget_min``, ``campaign_budget_max``,
        ``instagram_handle``, ``youtube_handle``, and all original fields.

    Raises
    ------
    HTTPException 404
        If no brand with the given ID exists.
    HTTPException 500
        If the Supabase query fails.
    """
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
            raise HTTPException(
                status_code=404,
                detail=f"Brand with id '{brand_id}' not found.",
            )

        return result.data

    except HTTPException:
        raise
    except Exception as exc:
        error_str = str(exc).lower()
        if "no rows" in error_str or "json object requested" in error_str:
            raise HTTPException(
                status_code=404,
                detail=f"Brand with id '{brand_id}' not found.",
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch brand: {exc}",
        ) from exc