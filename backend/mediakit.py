"""
mediakit.py — Media kit generation and management router for GetSpons.

Exposes:
    POST  /mediakit/generate   Generate AI content AND upsert to mediakits table.
    GET   /mediakit/saved      Fetch the saved mediakit for the logged-in user.
    PATCH /mediakit/update     Partially update saved mediakit fields.
    POST  /mediakit/pdf        Generate and return the mediakit as a PDF.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ai import generate_mediakit_content
from database import supabase, supabase_admin
from pdf import generate_pdf

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_user_id(authorization: str) -> str:
    """Validate Bearer token and return Supabase user_id."""
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
    """Fetch creator profile row for user_id."""
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
    """Return True when a Supabase .single() exception means no rows found."""
    msg = str(exc).lower()
    return "no rows" in msg or "json object requested" in msg


# ---------------------------------------------------------------------------
# Request model for PATCH /mediakit/update
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
def generate_mediakit(authorization: str = Header(...)):
    """Generate AI media-kit content and upsert it to the mediakits table.

    Flow
    ----
    1. Validate JWT → user_id.
    2. Fetch creator profile.
    3. Run AI content generation.
    4. Upsert into mediakits (on_conflict = user_id).
    5. Return the generated JSON.

    Returns
    -------
    dict
        Keys: headline, bio_short, key_stats, audience_description,
        content_style, why_partner, pricing_table, cta.

    Raises
    ------
    HTTPException 401 / 404 / 500
    """
    user_id = _resolve_user_id(authorization)
    profile = _fetch_profile(user_id)

    # ── Generate ─────────────────────────────────────────────────────
    try:
        mediakit: dict = generate_mediakit_content(profile)
    except Exception as exc:
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
    except Exception as exc:
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
    """Fetch the saved media kit for the authenticated user.

    Returns
    -------
    dict
        The full mediakits row.

    Raises
    ------
    HTTPException 401 / 404 / 500
    """
    user_id = _resolve_user_id(authorization)

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

    return data


# ---------------------------------------------------------------------------
# PATCH /mediakit/update
# ---------------------------------------------------------------------------


@router.patch("/update")
def update_mediakit(
    data: MediakitUpdateInput,
    authorization: str = Header(...),
):
    """Partially update the saved media kit for the authenticated user.

    Only fields explicitly provided in the request body are written.
    ``updated_at`` is always refreshed automatically.

    Parameters
    ----------
    data:
        Any subset of: headline, bio_short, audience_description,
        content_style, why_partner, cta, key_stats, pricing_table.

    Returns
    -------
    dict
        The full updated mediakits row.

    Raises
    ------
    HTTPException 400   No fields provided.
    HTTPException 401   Bad token.
    HTTPException 404   No saved media kit to update.
    HTTPException 500   Database error.
    """
    user_id = _resolve_user_id(authorization)

    # Build payload from only the fields that were actually provided
    updates: dict[str, Any] = {
        k: v
        for k, v in data.model_dump().items()
        if v is not None
    }

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="No fields provided to update.",
        )

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Verify a saved mediakit exists before attempting update
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
def generate_mediakit_pdf(authorization: str = Header(...)):
    """Generate and return the media kit as a downloadable PDF.

    Prefers saved mediakit content; falls back to fresh generation if none
    exists yet. Profile fields (name, platform, handle) are always pulled
    from the profiles table.

    Returns
    -------
    Response
        application/pdf with Content-Disposition: attachment.

    Raises
    ------
    HTTPException 401 / 404 / 500
    """
    user_id = _resolve_user_id(authorization)
    profile = _fetch_profile(user_id)

    # Prefer saved content, fall back to fresh generation
    mediakit: dict = {}
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
    except Exception as exc:
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