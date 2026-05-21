"""
admin.py — Admin utility router for GetSpons.

Exposes:
    POST /admin/cache/clear
        Clears the entire in-memory cache.
        Protected by X-Admin-Key header (value must match ADMIN_KEY env var).
"""

import os

from fastapi import APIRouter, Header, HTTPException

from cache import cache
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# POST /admin/cache/clear
# ---------------------------------------------------------------------------


@router.post("/cache/clear")
def clear_cache(x_admin_key: str = Header(..., alias="X-Admin-Key")):
    """Clear the entire in-memory cache.

    Parameters
    ----------
    x_admin_key:
        Must match the ``ADMIN_KEY`` environment variable.
        Pass it as the ``X-Admin-Key`` HTTP header.

    Returns
    -------
    dict
        ``{ success: true, message: "Cache cleared", entries_removed: int }``

    Raises
    ------
    HTTPException 401
        If the admin key is missing or incorrect.
    HTTPException 500
        If ADMIN_KEY is not configured in the environment.
    """
    admin_key = os.getenv("ADMIN_KEY", "").strip()

    if not admin_key:
        log.error("ADMIN_KEY is not set in environment — cache/clear endpoint is locked")
        raise HTTPException(
            status_code=500,
            detail="Admin key not configured. Set ADMIN_KEY in your .env file.",
        )

    if x_admin_key != admin_key:
        log.warning("Unauthorized cache clear attempt | provided_key=%s", x_admin_key[:6] + "***")
        raise HTTPException(
            status_code=401,
            detail="Invalid admin key.",
        )

    removed = cache.clear_all()
    log.info("Admin cache clear | entries_removed=%d", removed)

    return {
        "success":         True,
        "message":         "Cache cleared",
        "entries_removed": removed,
    }