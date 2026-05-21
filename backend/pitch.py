"""
pitch.py — Pitch generation and management router for GetSpons.

Exposes:
    POST  /pitches/generate              Generate + save a cold-pitch email.
    GET   /pitches/mine                  List all pitches for the logged-in user.
    PATCH /pitches/{pitch_id}            Update pitch status.
    PATCH /pitches/{pitch_id}/content    Edit pitch subject and/or body.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel
from limiter import limiter
from database import supabase, supabase_admin
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_STATUSES = {"draft", "sent", "replied", "deal"}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class GeneratePitchRequest(BaseModel):
    brand_id: str


class UpdatePitchRequest(BaseModel):
    status: str


class UpdatePitchContentRequest(BaseModel):
    subject: Optional[str] = None
    body:    Optional[str] = None


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


def _raise_if_not_found(exc: Exception, label: str) -> None:
    msg = str(exc).lower()
    if "no rows" in msg or "json object requested" in msg:
        raise HTTPException(status_code=404, detail=f"{label} not found.") from exc


def _get_pitch_owned_by(pitch_id: str, user_id: str) -> dict:
    try:
        res = (
            supabase_admin
            .table("pitches")
            .select("*")
            .eq("id", pitch_id)
            .single()
            .execute()
        )
        pitch: dict = res.data
    except Exception as exc:
        _raise_if_not_found(exc, f"Pitch '{pitch_id}'")
        raise HTTPException(status_code=500, detail=f"Failed to fetch pitch: {exc}") from exc

    if not pitch:
        raise HTTPException(status_code=404, detail=f"Pitch '{pitch_id}' not found.")

    if pitch.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=f"Pitch '{pitch_id}' not found.")

    return pitch


# ---------------------------------------------------------------------------
# Mock pitch generator
# ---------------------------------------------------------------------------


def _mock_generate_pitch(
    profile: dict[str, Any],
    brand: dict[str, Any],
) -> dict[str, str]:
    name:        str   = profile.get("full_name")          or "Creator"
    platform:    str   = profile.get("platform")           or "Social Media"
    handle:      str   = profile.get("handle")             or ""
    niche:       str   = profile.get("niche")              or "Lifestyle"
    followers:   int   = int(profile.get("followers")      or 0)
    engagement:  float = float(profile.get("engagement_rate") or 0.0)
    past_sponsors: list = profile.get("past_sponsors")     or []

    brand_name:  str = brand.get("name")    or "Your Brand"
    brand_niche: str = brand.get("niche")   or niche
    website:     str = brand.get("website") or ""

    followers_fmt = _format_followers(followers)

    sponsor_line: str = (
        f"I've previously worked with brands like "
        f"{', '.join(past_sponsors[:2])}, so I understand how to deliver "
        f"sponsor integrations that feel native and drive results."
        if past_sponsors
        else (
            f"I'm selective about the brands I partner with and would love "
            f"{brand_name} to be my first featured collaboration."
        )
    )

    niche_overlap: str = (
        f"Your focus on {brand_niche} aligns perfectly with my audience"
        if brand_niche.lower() != niche.lower()
        else f"As a fellow {niche} brand, you'd speak directly to my community"
    )

    subject: str = (
        f"Partnership Opportunity — {name} x {brand_name} "
        f"({followers_fmt} {platform} followers)"
    )

    body: str = f"""Hi {brand_name} Team,

I'm {name}, a {niche} creator on {platform} ({handle}) with {followers_fmt} followers and a {engagement:.1f}% engagement rate.

{niche_overlap} — my audience trusts my recommendations and actively engages with every post I publish.

{sponsor_line}

I'd love to explore a collaboration where I authentically showcase {brand_name} to my community. Whether that's a dedicated post, an integrated mention, or a full campaign, I'm flexible and happy to work around your goals.

Would you be open to a quick 15-minute call this week to see if we're a good fit?

Looking forward to hearing from you,
{name}
{platform}: {handle}
{f"Website: {website}" if website else ""}""".strip()

    return {"subject": subject, "body": body}


# ---------------------------------------------------------------------------
# POST /pitches/generate
# ---------------------------------------------------------------------------


@router.post("/generate")
@limiter.limit("20/hour")
def generate_pitch(
    request: Request,
    data: GeneratePitchRequest,
    authorization: str = Header(...),
):
    """Generate a cold-pitch email and save it as a draft."""
    user_id = _resolve_user_id(authorization)
    log.info("Pitch generation started | user_id=%s | brand_id=%s", user_id, data.brand_id)

    # Fetch profile
    try:
        profile_res = (
            supabase_admin.table("profiles")
            .select("*").eq("user_id", user_id).single().execute()
        )
        profile: dict = profile_res.data
    except Exception as exc:
        _raise_if_not_found(exc, "Creator profile")
        raise HTTPException(status_code=500, detail=f"Failed to fetch profile: {exc}") from exc

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="No profile found. Please complete your creator profile first.",
        )

    # Fetch brand
    try:
        brand_res = (
            supabase_admin.table("brands")
            .select("*").eq("id", data.brand_id).single().execute()
        )
        brand: dict = brand_res.data
    except Exception as exc:
        _raise_if_not_found(exc, f"Brand '{data.brand_id}'")
        raise HTTPException(status_code=500, detail=f"Failed to fetch brand: {exc}") from exc

    if not brand:
        raise HTTPException(
            status_code=404,
            detail=f"Brand with id '{data.brand_id}' not found.",
        )

    # Generate
    try:
        pitch_content = _mock_generate_pitch(profile, brand)
    except Exception as exc:
        log.error(
            "Pitch generation failed | user_id=%s | brand_id=%s | reason=%s",
            user_id, data.brand_id, exc,
        )
        raise HTTPException(status_code=500, detail=f"Pitch generation failed: {exc}") from exc

    # Save
    try:
        insert_res = (
            supabase_admin.table("pitches").insert({
                "user_id":  user_id,
                "brand_id": data.brand_id,
                "subject":  pitch_content["subject"],
                "body":     pitch_content["body"],
                "status":   "draft",
            }).execute()
        )
        saved: dict = insert_res.data[0]
        log.info(
            "Pitch generated and saved successfully | user_id=%s | pitch_id=%s",
            user_id, saved["id"],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save pitch: {exc}") from exc

    return {
        "id":      saved["id"],
        "subject": saved["subject"],
        "body":    saved["body"],
        "status":  saved["status"],
    }


# ---------------------------------------------------------------------------
# GET /pitches/mine
# ---------------------------------------------------------------------------


@router.get("/mine")
def get_my_pitches(authorization: str = Header(...)):
    """Return all pitches for the authenticated creator, with brand name."""
    user_id = _resolve_user_id(authorization)

    try:
        res = (
            supabase_admin
            .table("pitches")
            .select("id, user_id, brand_id, subject, body, status, created_at, brands(name)")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch pitches: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# PATCH /pitches/{pitch_id}  — update status
# ---------------------------------------------------------------------------


@router.patch("/{pitch_id}")
def update_pitch_status(
    pitch_id: str,
    data: UpdatePitchRequest,
    authorization: str = Header(...),
):
    """Update the status of a pitch owned by the authenticated creator."""
    user_id = _resolve_user_id(authorization)

    if data.status not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid status '{data.status}'. "
                f"Allowed values: {', '.join(sorted(ALLOWED_STATUSES))}."
            ),
        )

    _get_pitch_owned_by(pitch_id, user_id)

    try:
        result = (
            supabase_admin
            .table("pitches")
            .update({"status": data.status})
            .eq("id", pitch_id)
            .execute()
        )
        log.info(
            "Pitch status updated | pitch_id=%s | new_status=%s | user_id=%s",
            pitch_id, data.status, user_id,
        )
        return result.data[0]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update pitch: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# PATCH /pitches/{pitch_id}/content  — edit subject and/or body
# ---------------------------------------------------------------------------


@router.patch("/{pitch_id}/content")
def update_pitch_content(
    pitch_id: str,
    data: UpdatePitchContentRequest,
    authorization: str = Header(...),
):
    """Edit the subject and/or body of an existing pitch."""
    user_id = _resolve_user_id(authorization)

    updates: dict[str, str] = {}
    if data.subject is not None:
        updates["subject"] = data.subject.strip()
    if data.body is not None:
        updates["body"] = data.body.strip()

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="At least one of 'subject' or 'body' must be provided.",
        )

    _get_pitch_owned_by(pitch_id, user_id)

    try:
        result = (
            supabase_admin
            .table("pitches")
            .update(updates)
            .eq("id", pitch_id)
            .execute()
        )
        log.info(
            "Pitch content edited | pitch_id=%s | fields=%s | user_id=%s",
            pitch_id, list(updates.keys()), user_id,
        )
        return result.data[0]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update pitch content: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _format_followers(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return f"{count:,}"