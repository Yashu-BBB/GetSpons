"""
mediakit.py — Media kit generation and management router for GetSpons.

Exposes:
    POST  /mediakit/generate   Generate AI content AND upsert to mediakits table.
    GET   /mediakit/saved      Fetch the saved mediakit for the logged-in user.
    PATCH /mediakit/update     Partially update saved mediakit fields.
    POST  /mediakit/pdf        Generate and return the mediakit as a PDF.

Caching
-------
    GET /mediakit/saved  key: "mediakit_{user_id}"  TTL: 300s
    Cache is cleared on every successful PATCH /mediakit/update
    and on every successful POST /mediakit/generate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from ai import generate_mediakit_content
from cache import cache
from database import supabase, supabase_admin
from limiter import limiter
from logger import get_logger
from pdf import generate_pdf

router = APIRouter()
log = get_logger(__name__)

_MEDIAKIT_TTL = 300   # 5 minutes


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_user_id(authorization: str) -> str:
    try:
        token: str = authorization.replace("Bearer ", "").strip()
        if not token:
            raise ValueError("Empty token")
        user = supabase.auth.get_user(token)
        return user.user.id
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {exc}",
        ) from exc


def _fetch_profile(user_id: str) -> dict:
    try:
        result = (
            supabase_admin
            .table("profiles")
            .select("*")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        profile: dict = result.data
    except Exception as exc:
        msg = str(exc).lower()
        if "no rows" in msg or "json object requested" in msg:
            raise HTTPException(
                status_code=404,
                detail="No profile found. Please complete your creator profile first.",
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch profile: {exc}",
        ) from exc

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile data is empty. Please complete your creator profile first.",
        )
    return profile


def _no_rows(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "no rows" in msg or "json object requested" in msg


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class MediakitUpdateInput(BaseModel):
    headline:             Optional[str]       = None
    bio_short:            Optional[str]       = None
    audience_description: Optional[str]       = None
    content_style:        Optional[str]       = None
    why_partner:          Optional[str]       = None
    cta:                  Optional[str]       = None
    key_stats:            Optional[List[Any]] = None
    pricing_table:        Optional[List[Any]] = None


# ---------------------------------------------------------------------------
# POST /mediakit/generate
# ---------------------------------------------------------------------------


@router.post("/generate")
@limiter.limit("10/hour")
def generate_mediakit(request: Request, authorization: str = Header(...)):
    """Generate AI media-kit content, upsert to DB, and invalidate cache."""
    user_id = _resolve_user_id(authorization)
    profile = _fetch_profile(user_id)

    log.info("Media kit generation started | user_id=%s", user_id)

    # ── Generate ─────────────────────────────────────────────────────
    try:
        mediakit: dict = generate_mediakit_content(profile)
    except Exception as exc:
        log.error("Media kit generation failed | user_id=%s | reason=%s", user_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Media kit generation failed: {exc}",
        ) from exc

    # ── Upsert ───────────────────────────────────────────────────────
    try:
        now = datetime.now(timezone.utc).isoformat()
        supabase_admin.table("mediakits").upsert(
            {
                "user_id":              user_id,
                "headline":             mediakit["headline"],
                "bio_short":            mediakit["bio_short"],
                "key_stats":            mediakit["key_stats"],
                "audience_description": mediakit["audience_description"],
                "content_style":        mediakit["content_style"],
                "why_partner":          mediakit["why_partner"],
                "pricing_table":        mediakit["pricing_table"],
                "cta":                  mediakit["cta"],
                "updated_at":           now,
            },
            on_conflict="user_id",
        ).execute()

        # Invalidate cache so next GET /saved returns fresh data
        cache.delete(f"mediakit_{user_id}")
        log.info("Media kit generated and saved successfully | user_id=%s", user_id)

    except Exception as exc:
        log.error("Media kit save failed | user_id=%s | reason=%s", user_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save media kit: {exc}",
        ) from exc

    return mediakit


# ---------------------------------------------------------------------------
# GET /mediakit/saved
# ---------------------------------------------------------------------------


@router.get("/saved")
def get_saved_mediakit(authorization: str = Header(...)):
    """Fetch the saved media kit for the authenticated user. Cached 300s."""
    user_id = _resolve_user_id(authorization)
    cache_key = f"mediakit_{user_id}"

    # ── Cache hit ─────────────────────────────────────────────────────
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # ── Cache miss — query Supabase ───────────────────────────────────
    try:
        result = (
            supabase_admin
            .table("mediakits")
            .select("*")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        data = result.data
    except Exception as exc:
        if _no_rows(exc):
            raise HTTPException(
                status_code=404,
                detail="No saved media kit found. Generate one first.",
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch media kit: {exc}",
        ) from exc

    if not data:
        raise HTTPException(
            status_code=404,
            detail="No saved media kit found. Generate one first.",
        )

    cache.set(cache_key, data, ttl_seconds=_MEDIAKIT_TTL)
    return data


# ---------------------------------------------------------------------------
# PATCH /mediakit/update
# ---------------------------------------------------------------------------


@router.patch("/update")
def update_mediakit(
    data: MediakitUpdateInput,
    authorization: str = Header(...),
):
    """Partially update the saved media kit and invalidate its cache entry."""
    user_id = _resolve_user_id(authorization)

    updates: dict[str, Any] = {
        k: v for k, v in data.model_dump().items() if v is not None
    }

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update.")

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Verify saved mediakit exists
    try:
        existing = (
            supabase_admin
            .table("mediakits")
            .select("id")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
    except Exception as exc:
        if _no_rows(exc):
            raise HTTPException(
                status_code=404,
                detail="No saved media kit found. Generate one first.",
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to verify media kit: {exc}",
        ) from exc

    if not existing.data:
        raise HTTPException(
            status_code=404,
            detail="No saved media kit found. Generate one first.",
        )

    # Apply update
    try:
        result = (
            supabase_admin
            .table("mediakits")
            .update(updates)
            .eq("user_id", user_id)
            .execute()
        )

        # Invalidate cache so next GET /saved returns the updated data
        cache.delete(f"mediakit_{user_id}")
        return result.data[0]

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update media kit: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# POST /mediakit/pdf
# ---------------------------------------------------------------------------


@router.post("/pdf")
@limiter.limit("5/hour")
def generate_mediakit_pdf(request: Request, authorization: str = Header(...)):
    """Generate and return the media kit as a downloadable PDF.

    Prefers saved (and cached) mediakit content; falls back to fresh
    generation if none exists.
    """
    user_id = _resolve_user_id(authorization)
    profile = _fetch_profile(user_id)

    log.info("PDF generation started | user_id=%s", user_id)

    # Try cache first, then DB, then generate fresh
    mediakit: dict = cache.get(f"mediakit_{user_id}") or {}

    if not mediakit:
        try:
            saved_res = (
                supabase_admin
                .table("mediakits")
                .select("*")
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            mediakit = saved_res.data or {}
        except Exception:
            pass

    if not mediakit:
        try:
            mediakit = generate_mediakit_content(profile)
        except Exception as exc:
            log.error("PDF generation failed (AI step) | user_id=%s | reason=%s", user_id, exc)
            raise HTTPException(
                status_code=500,
                detail=f"Media kit generation failed: {exc}",
            ) from exc

    template_data: dict = {
        "creator_name": profile.get("full_name") or profile.get("name", "Creator"),
        "platform":     profile.get("platform", ""),
        "handle":       profile.get("handle", ""),
        **{
            k: mediakit.get(k, "")
            for k in (
                "headline", "bio_short", "key_stats",
                "audience_description", "content_style",
                "why_partner", "pricing_table", "cta",
            )
        },
    }

    try:
        pdf_bytes: bytes = generate_pdf(template_data)
        log.info("PDF generated successfully | user_id=%s", user_id)
    except Exception as exc:
        log.error("PDF generation failed (render step) | user_id=%s | reason=%s", user_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"PDF rendering failed: {exc}",
        ) from exc

    safe_name = template_data["creator_name"].replace(" ", "_")
    filename = f"{safe_name}_media_kit.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )