"""
brands.py — Brands router for GetSpons.

Exposes:
    GET /brands
        Returns all brands from the Supabase brands table.
        Supports optional query parameters:
            niche          (str) — filter by niche, e.g. ?niche=Finance
            min_followers  (int) — filter by minimum follower requirement,
                                   e.g. ?min_followers=10000
        No authentication required.

    GET /brands/{brand_id}
        Returns a single brand by its ID.
        No authentication required.
        Returns 404 if the brand is not found.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from database import supabase_admin

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /brands
# ---------------------------------------------------------------------------


@router.get("/", response_model=None)
def get_brands(
    niche: Optional[str] = Query(
        default=None,
        description="Filter brands by niche, e.g. Finance, Tech, Lifestyle",
    ),
    min_followers: Optional[int] = Query(
        default=None,
        description="Return only brands whose min_followers is <= this value",
        ge=0,
    ),
):
    """Return all brands, with optional filtering by niche and follower count.

    Parameters
    ----------
    niche : str, optional
        Case-sensitive niche string to match against the ``niche`` column.
    min_followers : int, optional
        When provided, only brands whose ``min_followers`` is less than or
        equal to this value are returned — i.e. brands the caller's audience
        size already satisfies.

    Returns
    -------
    list[dict]
        A list of brand objects. Empty list if no brands match the filters.

    Raises
    ------
    HTTPException 500
        If the Supabase query fails for any unexpected reason.
    """
    try:
        query = supabase_admin.table("brands").select(
            "id, name, niche, min_followers, max_followers, "
            "contact_email, website, country, active"
        )

        # ── Optional filters ─────────────────────────────────────────
        if niche is not None:
            query = query.eq("niche", niche)

        if min_followers is not None:
            # Brands whose minimum follower requirement the caller can meet:
            # brand.min_followers <= caller's follower count
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
    """Return a single brand by its ID.

    Parameters
    ----------
    brand_id : str
        The UUID (or integer PK, depending on your schema) of the brand row.

    Returns
    -------
    dict
        The brand object.

    Raises
    ------
    HTTPException 404
        If no brand with the given ID exists.
    HTTPException 500
        If the Supabase query fails for any unexpected reason.
    """
    try:
        result = (
            supabase_admin
            .table("brands")
            .select(
                "id, name, niche, min_followers, max_followers, "
                "contact_email, website, country, active"
            )
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
        # Re-raise 404s without wrapping them in a 500
        raise
    except Exception as exc:
        # Supabase raises an exception (not just returns None) when
        # .single() finds no row, so we catch that here too.
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