"""
pitch.py — Pitch generation and management router for GetSpons.

Exposes:
    POST /pitch/generate
        Validates JWT, fetches creator profile + brand info, generates a
        cold-pitch email (mock, no API key needed), saves it to the pitches
        table with status "draft", and returns the saved pitch.

    GET /pitches/mine
        Returns all pitches for the authenticated creator, joined with the
        brands table to include the brand name.

    PATCH /pitches/{pitch_id}
        Updates the status of an existing pitch.
        Allowed values: draft | sent | replied | deal
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from database import supabase, supabase_admin

router = APIRouter()

# ---------------------------------------------------------------------------
# Allowed pitch statuses
# ---------------------------------------------------------------------------

ALLOWED_STATUSES = {"draft", "sent", "replied", "deal"}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class GeneratePitchRequest(BaseModel):
    brand_id: str


class UpdatePitchRequest(BaseModel):
    status: str  # validated manually so we can return a clear 422 message


# ---------------------------------------------------------------------------
# Shared auth helper
# ---------------------------------------------------------------------------


def _resolve_user_id(authorization: str) -> str:
    """Validate Bearer token and return Supabase user_id.

    Raises
    ------
    HTTPException 401
        If the token is missing, malformed, or rejected by Supabase Auth.
    """
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


# ---------------------------------------------------------------------------
# Mock pitch generator  (same philosophy as ai.py _mock_generate)
# ---------------------------------------------------------------------------


def _mock_generate_pitch(
    profile: dict[str, Any],
    brand: dict[str, Any],
) -> dict[str, str]:
    """Generate a personalised cold-pitch email from profile + brand data.

    No API key required — produces realistic, variable output by weaving
    the real creator and brand values into templates.

    Parameters
    ----------
    profile:
        Creator profile row from the ``profiles`` table.
    brand:
        Brand row from the ``brands`` table.

    Returns
    -------
    dict with keys ``subject`` and ``body``.
    """
    # ── Extract & normalise creator fields ───────────────────────────
    name: str        = profile.get("full_name") or "Creator"
    platform: str    = profile.get("platform")  or "Social Media"
    handle: str      = profile.get("handle")    or ""
    niche: str       = profile.get("niche")     or "Lifestyle"
    followers: int   = int(profile.get("followers") or 0)
    engagement: float = float(profile.get("engagement_rate") or 0.0)
    past_sponsors: list = profile.get("past_sponsors") or []

    # ── Extract & normalise brand fields ─────────────────────────────
    brand_name: str  = brand.get("name")    or "Your Brand"
    brand_niche: str = brand.get("niche")   or niche
    website: str     = brand.get("website") or ""

    # ── Helpers ───────────────────────────────────────────────────────
    followers_fmt = _format_followers(followers)

    sponsor_line: str = (
        f"I've previously worked with brands like "
        f"{', '.join(past_sponsors[:2])}, so I understand how to "
        f"deliver sponsor integrations that feel native and drive results."
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

    # ── Subject line ──────────────────────────────────────────────────
    subject: str = (
        f"Partnership Opportunity — {name} x {brand_name} "
        f"({followers_fmt} {platform} followers)"
    )

    # ── Body (kept under 200 words) ───────────────────────────────────
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
# POST /pitch/generate
# ---------------------------------------------------------------------------


@router.post("/generate")
def generate_pitch(
    data: GeneratePitchRequest,
    authorization: str = Header(...),
):
    """Generate a cold-pitch email and save it as a draft.

    Flow
    ----
    1. Validate JWT → user_id.
    2. Fetch creator profile from ``profiles``.
    3. Fetch brand from ``brands``.
    4. Generate subject + body via mock generator.
    5. Insert row into ``pitches`` with status ``"draft"``.
    6. Return the saved pitch object.

    Parameters
    ----------
    data:
        JSON body containing ``brand_id`` (UUID string).
    authorization:
        ``Authorization: Bearer <jwt>`` header.

    Returns
    -------
    dict
        ``{ id, subject, body, status }``

    Raises
    ------
    HTTPException 401   Invalid / expired token.
    HTTPException 404   Profile or brand not found.
    HTTPException 500   Generation or database write failed.
    """
    # ── Step 1: auth ─────────────────────────────────────────────────
    user_id = _resolve_user_id(authorization)

    # ── Step 2: fetch creator profile ────────────────────────────────
    try:
        profile_res = (
            supabase_admin
            .table("profiles")
            .select("*")
            .eq("user_id", user_id)
            .single()
            .execute()
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

    # ── Step 3: fetch brand ───────────────────────────────────────────
    try:
        brand_res = (
            supabase_admin
            .table("brands")
            .select("*")
            .eq("id", data.brand_id)
            .single()
            .execute()
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

    # ── Step 4: generate pitch content ───────────────────────────────
    try:
        pitch_content = _mock_generate_pitch(profile, brand)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Pitch generation failed: {exc}",
        ) from exc

    # ── Step 5: save to pitches table ────────────────────────────────
    try:
        insert_res = (
            supabase_admin
            .table("pitches")
            .insert({
                "user_id":  user_id,
                "brand_id": data.brand_id,
                "subject":  pitch_content["subject"],
                "body":     pitch_content["body"],
                "status":   "draft",
            })
            .execute()
        )
        saved: dict = insert_res.data[0]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save pitch: {exc}",
        ) from exc

    # ── Step 6: return ────────────────────────────────────────────────
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
    """Return all pitches for the authenticated creator, with brand name.

    Parameters
    ----------
    authorization:
        ``Authorization: Bearer <jwt>`` header.

    Returns
    -------
    list[dict]
        Each item contains all pitch columns plus a nested ``brands`` object
        with at least ``name``.

    Raises
    ------
    HTTPException 401   Invalid / expired token.
    HTTPException 500   Database query failed.
    """
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
# PATCH /pitches/{pitch_id}
# ---------------------------------------------------------------------------


@router.patch("/{pitch_id}")
def update_pitch_status(
    pitch_id: str,
    data: UpdatePitchRequest,
    authorization: str = Header(...),
):
    """Update the status of a pitch owned by the authenticated creator.

    Parameters
    ----------
    pitch_id:
        UUID of the pitch to update.
    data:
        JSON body containing ``status``.
        Allowed values: ``draft`` | ``sent`` | ``replied`` | ``deal``.
    authorization:
        ``Authorization: Bearer <jwt>`` header.

    Returns
    -------
    dict
        The full updated pitch row.

    Raises
    ------
    HTTPException 401   Invalid / expired token.
    HTTPException 422   Status value not in the allowed set.
    HTTPException 404   Pitch not found or not owned by caller.
    HTTPException 500   Database update failed.
    """
    user_id = _resolve_user_id(authorization)

    # ── Validate status value ─────────────────────────────────────────
    if data.status not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid status '{data.status}'. "
                f"Allowed values: {', '.join(sorted(ALLOWED_STATUSES))}."
            ),
        )

    # ── Verify pitch exists and belongs to this user ──────────────────
    try:
        existing_res = (
            supabase_admin
            .table("pitches")
            .select("id, user_id")
            .eq("id", pitch_id)
            .single()
            .execute()
        )
        existing: dict = existing_res.data
    except Exception as exc:
        _raise_if_not_found(exc, f"Pitch '{pitch_id}'")
        raise HTTPException(status_code=500, detail=f"Failed to fetch pitch: {exc}") from exc

    if not existing:
        raise HTTPException(status_code=404, detail=f"Pitch '{pitch_id}' not found.")

    if existing.get("user_id") != user_id:
        # Return 404 rather than 403 to avoid leaking pitch existence
        raise HTTPException(status_code=404, detail=f"Pitch '{pitch_id}' not found.")

    # ── Perform the update ────────────────────────────────────────────
    try:
        update_res = (
            supabase_admin
            .table("pitches")
            .update({"status": data.status})
            .eq("id", pitch_id)
            .execute()
        )
        updated: dict = update_res.data[0]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update pitch: {exc}",
        ) from exc

    return updated


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _raise_if_not_found(exc: Exception, label: str) -> None:
    """Re-raise as HTTPException 404 when Supabase reports no rows found.

    Supabase raises an exception (not returns None) when ``.single()``
    finds no matching row.  The error message contains ``"no rows"`` or
    ``"JSON object requested"`` in that case.
    """
    msg = str(exc).lower()
    if "no rows" in msg or "json object requested" in msg:
        raise HTTPException(
            status_code=404,
            detail=f"{label} not found.",
        ) from exc


def _format_followers(count: int) -> str:
    """Return a human-readable follower count string (e.g. ``'45K'``, ``'1.2M'``)."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return f"{count:,}"