"""
inbox.py — Sponsorship inbox router for GetSpons.

Handles the message thread between a creator (who pitches) and the brand
that receives the pitch.  The inbox sits on top of the pitches table —
a creator first generates a pitch, then sends it to the brand's inbox via
POST /api/inbox/send.

Table: inbox_messages
---------------------
    id              UUID PK  default gen_random_uuid()
    pitch_id        UUID     REFERENCES pitches(id)
    creator_id      UUID     (Supabase auth user id of the creator)
    brand_user_id   UUID     REFERENCES brand_users(id)
    brand_response  TEXT     default 'pending'
                             one of: pending | accepted | rejected | negotiating
    response_note   TEXT     nullable
    created_at      TIMESTAMPTZ  default now()
    updated_at      TIMESTAMPTZ  default now()

Exposes
-------
    POST  /api/inbox/send                 Creator sends a pitch to a brand's inbox.
    GET   /api/inbox/brand                Brand views all received messages.
    PATCH /api/inbox/{message_id}/respond Brand responds to a message.
    GET   /api/inbox/creator              Creator views all their sent messages + responses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from brand_auth import get_brand_user_id
from cache import cache
from database import supabase, supabase_admin
from limiter import limiter
from logger import get_logger

router = APIRouter()
log    = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_RESPONSES = {"accepted", "rejected", "negotiating"}

_INBOX_BRAND_TTL   = 60    # 1 minute  — brand inbox refreshes fast
_INBOX_CREATOR_TTL = 60    # 1 minute  — creator view refreshes fast


# ---------------------------------------------------------------------------
# Shared helper — resolve creator user_id from Bearer token
# ---------------------------------------------------------------------------


def _resolve_creator_id(authorization: str) -> str:
    """Validate a creator Bearer token and return their Supabase auth user id.

    Raises
    ------
    HTTPException 401   Token missing, malformed, or expired.
    """
    try:
        token = authorization.replace("Bearer ", "").strip()
        if not token:
            raise ValueError("Empty token")
        user = supabase.auth.get_user(token)
        return user.user.id
    except Exception as exc:
        log.warning("Creator token validation failed | reason=%s", exc)
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SendInboxInput(BaseModel):
    pitch_id: str


class RespondInput(BaseModel):
    brand_response: Literal["accepted", "rejected", "negotiating"]
    response_note:  Optional[str] = None


# ---------------------------------------------------------------------------
# POST /api/inbox/send  — creator sends a pitch into a brand's inbox
# ---------------------------------------------------------------------------


@router.post("/send")
@limiter.limit("20/hour")
def send_to_inbox(request: Request, data: SendInboxInput, authorization: str = Header(...)):
    """Send a pitch to the corresponding brand's inbox.

    Flow
    ----
    1.  Resolve creator from token.
    2.  Fetch pitch — confirm it exists and belongs to the creator.
    3.  Get brand_id from pitch → look up brand's contact_email from brands table.
    4.  Find brand_user_id in brand_users by matching that contact_email.
    5.  Guard against duplicate sends (same pitch_id already in inbox).
    6.  Insert inbox_messages row and return message_id.

    Returns
    -------
    { success: true, message_id: str }
    """
    creator_id = _resolve_creator_id(authorization)
    log.info("Inbox send attempt | creator_id=%s | pitch_id=%s", creator_id, data.pitch_id)

    # ── Step 1: fetch and verify the pitch ───────────────────────────
    try:
        pitch_res = (
            supabase_admin
            .table("pitches")
            .select("id, user_id, brand_id, subject")
            .eq("id", data.pitch_id)
            .single()
            .execute()
        )
        pitch = pitch_res.data
    except Exception as exc:
        msg = str(exc).lower()
        if "no rows" in msg or "json object requested" in msg:
            log.warning(
                "Inbox send failed — pitch not found | pitch_id=%s | creator_id=%s",
                data.pitch_id, creator_id,
            )
            raise HTTPException(status_code=404, detail="Pitch not found.") from exc
        raise HTTPException(status_code=500, detail=f"Failed to fetch pitch: {exc}") from exc

    if not pitch:
        raise HTTPException(status_code=404, detail="Pitch not found.")

    if pitch["user_id"] != creator_id:
        log.warning(
            "Inbox send rejected — pitch does not belong to creator | "
            "pitch_id=%s | creator_id=%s | actual_owner=%s",
            data.pitch_id, creator_id, pitch["user_id"],
        )
        raise HTTPException(status_code=403, detail="This pitch does not belong to you.")

    brand_id = pitch["brand_id"]

    # ── Step 2: get brand's contact_email from brands table ──────────
    try:
        brand_res = (
            supabase_admin
            .table("brands")
            .select("id, name, contact_email")
            .eq("id", brand_id)
            .single()
            .execute()
        )
        brand = brand_res.data
    except Exception as exc:
        msg = str(exc).lower()
        if "no rows" in msg or "json object requested" in msg:
            log.warning(
                "Inbox send failed — brand not found | brand_id=%s", brand_id,
            )
            raise HTTPException(status_code=404, detail="Brand not found.") from exc
        raise HTTPException(status_code=500, detail=f"Failed to fetch brand: {exc}") from exc

    if not brand or not brand.get("contact_email"):
        raise HTTPException(
            status_code=422,
            detail="Brand has no contact email — cannot route inbox message.",
        )

    contact_email = brand["contact_email"]

    # ── Step 3: find brand_user_id matching contact_email ────────────
    try:
        bu_res = (
            supabase_admin
            .table("brand_users")
            .select("id, email")
            .eq("email", contact_email)
            .single()
            .execute()
        )
        brand_user = bu_res.data
    except Exception as exc:
        msg = str(exc).lower()
        if "no rows" in msg or "json object requested" in msg:
            log.warning(
                "Inbox send failed — no brand_users row for email=%s | brand_id=%s",
                contact_email, brand_id,
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    "The brand you're pitching hasn't created a GetSpons account yet. "
                    "They need to register before you can send them a message."
                ),
            ) from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to look up brand user: {exc}",
        ) from exc

    if not brand_user:
        raise HTTPException(
            status_code=422,
            detail="Brand account not found on GetSpons.",
        )

    brand_user_id = brand_user["id"]

    # ── Step 4: prevent duplicate sends ──────────────────────────────
    try:
        dup_res = (
            supabase_admin
            .table("inbox_messages")
            .select("id")
            .eq("pitch_id", data.pitch_id)
            .eq("creator_id", creator_id)
            .execute()
        )
        if dup_res.data:
            log.warning(
                "Inbox send rejected — duplicate | pitch_id=%s | creator_id=%s",
                data.pitch_id, creator_id,
            )
            raise HTTPException(
                status_code=409,
                detail="You have already sent this pitch to the brand's inbox.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check for duplicate message: {exc}",
        ) from exc

    # ── Step 5: insert inbox_messages row ────────────────────────────
    try:
        now = datetime.now(timezone.utc).isoformat()
        insert_res = (
            supabase_admin
            .table("inbox_messages")
            .insert({
                "pitch_id":      data.pitch_id,
                "creator_id":    creator_id,
                "brand_user_id": brand_user_id,
                "brand_response": "pending",
                "response_note": None,
                "created_at":    now,
                "updated_at":    now,
            })
            .execute()
        )
        message = insert_res.data[0]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create inbox message: {exc}",
        ) from exc

    # Bust brand's inbox cache so they see the new message immediately
    cache.delete(f"inbox_brand_{brand_user_id}")

    log.info(
        "Inbox message created | message_id=%s | pitch_id=%s | "
        "creator_id=%s | brand_user_id=%s",
        message["id"], data.pitch_id, creator_id, brand_user_id,
    )
    return {"success": True, "message_id": message["id"]}


# ---------------------------------------------------------------------------
# GET /api/inbox/brand  — brand views all received pitches
# ---------------------------------------------------------------------------


@router.get("/brand")
def get_brand_inbox(authorization: str = Header(...)):
    """Return all inbox messages addressed to the authenticated brand.

    Each message includes full pitch details and the creator's profile.

    Returns
    -------
    list[dict]
        Sorted by created_at DESC.
    """
    brand_user_id = get_brand_user_id(authorization)
    log.info("Brand inbox fetch | brand_user_id=%s", brand_user_id)

    cache_key = f"inbox_brand_{brand_user_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        log.debug("Brand inbox cache hit | brand_user_id=%s", brand_user_id)
        return cached

    # ── Fetch raw inbox rows ──────────────────────────────────────────
    try:
        inbox_res = (
            supabase_admin
            .table("inbox_messages")
            .select("id, pitch_id, creator_id, brand_response, response_note, created_at, updated_at")
            .eq("brand_user_id", brand_user_id)
            .order("created_at", desc=True)
            .execute()
        )
        messages = inbox_res.data or []
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch brand inbox: {exc}",
        ) from exc

    if not messages:
        cache.set(cache_key, [], ttl_seconds=_INBOX_BRAND_TTL)
        return []

    # ── Enrich each message with pitch + creator profile ─────────────
    pitch_ids   = list({m["pitch_id"]   for m in messages})
    creator_ids = list({m["creator_id"] for m in messages})

    try:
        pitches_res = (
            supabase_admin
            .table("pitches")
            .select("id, subject, body, created_at")
            .in_("id", pitch_ids)
            .execute()
        )
        pitches_map: dict[str, dict] = {p["id"]: p for p in (pitches_res.data or [])}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch pitch details: {exc}",
        ) from exc

    try:
        profiles_res = (
            supabase_admin
            .table("profiles")
            .select(
                "user_id, full_name, handle, platform, followers, "
                "niche, engagement_rate, pricing_min, pricing_max"
            )
            .in_("user_id", creator_ids)
            .execute()
        )
        profiles_map: dict[str, dict] = {
            p["user_id"]: p for p in (profiles_res.data or [])
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch creator profiles: {exc}",
        ) from exc

    result = []
    for msg in messages:
        pitch   = pitches_map.get(msg["pitch_id"],   {})
        profile = profiles_map.get(msg["creator_id"], {})
        result.append({
            "message_id":     msg["id"],
            "brand_response": msg["brand_response"],
            "response_note":  msg["response_note"],
            "created_at":     msg["created_at"],
            "updated_at":     msg["updated_at"],
            # pitch
            "pitch": {
                "id":         msg["pitch_id"],
                "subject":    pitch.get("subject"),
                "body":       pitch.get("body"),
                "created_at": pitch.get("created_at"),
            },
            # creator
            "creator": {
                "user_id":        msg["creator_id"],
                "full_name":      profile.get("full_name"),
                "handle":         profile.get("handle"),
                "platform":       profile.get("platform"),
                "followers":      profile.get("followers"),
                "niche":          profile.get("niche"),
                "engagement_rate":profile.get("engagement_rate"),
                "pricing_min":    profile.get("pricing_min"),
                "pricing_max":    profile.get("pricing_max"),
            },
        })

    cache.set(cache_key, result, ttl_seconds=_INBOX_BRAND_TTL)
    log.info(
        "Brand inbox returned %d messages | brand_user_id=%s",
        len(result), brand_user_id,
    )
    return result


# ---------------------------------------------------------------------------
# PATCH /api/inbox/{message_id}/respond  — brand responds to a message
# ---------------------------------------------------------------------------


@router.patch("/{message_id}/respond")
def respond_to_message(
    message_id: str,
    data:        RespondInput,
    authorization: str = Header(...),
):
    """Allow a brand to accept, reject, or open negotiation on a message.

    Only the brand that owns the message may respond.

    Returns
    -------
    dict   The updated inbox_messages row.
    """
    brand_user_id = get_brand_user_id(authorization)
    log.info(
        "Brand respond attempt | message_id=%s | brand_user_id=%s | response=%s",
        message_id, brand_user_id, data.brand_response,
    )

    # ── Verify the message exists and belongs to this brand ──────────
    try:
        msg_res = (
            supabase_admin
            .table("inbox_messages")
            .select("id, brand_user_id, creator_id, pitch_id")
            .eq("id", message_id)
            .single()
            .execute()
        )
        message = msg_res.data
    except Exception as exc:
        msg_str = str(exc).lower()
        if "no rows" in msg_str or "json object requested" in msg_str:
            raise HTTPException(status_code=404, detail="Message not found.") from exc
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch message: {exc}",
        ) from exc

    if not message:
        raise HTTPException(status_code=404, detail="Message not found.")

    if message["brand_user_id"] != brand_user_id:
        log.warning(
            "Brand respond rejected — wrong owner | message_id=%s | "
            "brand_user_id=%s | actual_owner=%s",
            message_id, brand_user_id, message["brand_user_id"],
        )
        raise HTTPException(
            status_code=403,
            detail="You are not authorised to respond to this message.",
        )

    # ── Build update payload ──────────────────────────────────────────
    updates: dict = {
        "brand_response": data.brand_response,
        "updated_at":     datetime.now(timezone.utc).isoformat(),
    }
    if data.response_note is not None:
        updates["response_note"] = data.response_note.strip()

    # ── Apply update ─────────────────────────────────────────────────
    try:
        update_res = (
            supabase_admin
            .table("inbox_messages")
            .update(updates)
            .eq("id", message_id)
            .execute()
        )
        updated = update_res.data[0]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update message: {exc}",
        ) from exc

    # Bust caches for both sides
    cache.delete(f"inbox_brand_{brand_user_id}")
    cache.delete(f"inbox_creator_{message['creator_id']}")

    log.info(
        "Brand responded | message_id=%s | response=%s | brand_user_id=%s",
        message_id, data.brand_response, brand_user_id,
    )
    return updated


# ---------------------------------------------------------------------------
# GET /api/inbox/creator  — creator views all sent messages + brand responses
# ---------------------------------------------------------------------------


@router.get("/creator")
def get_creator_inbox(authorization: str = Header(...)):
    """Return all inbox messages sent by the authenticated creator.

    Includes brand company details and the current response status.
    Sorted by updated_at DESC so the most recently responded messages
    float to the top.

    Returns
    -------
    list[dict]
    """
    creator_id = _resolve_creator_id(authorization)
    log.info("Creator inbox fetch | creator_id=%s", creator_id)

    cache_key = f"inbox_creator_{creator_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        log.debug("Creator inbox cache hit | creator_id=%s", creator_id)
        return cached

    # ── Fetch raw inbox rows ──────────────────────────────────────────
    try:
        inbox_res = (
            supabase_admin
            .table("inbox_messages")
            .select(
                "id, pitch_id, brand_user_id, brand_response, "
                "response_note, created_at, updated_at"
            )
            .eq("creator_id", creator_id)
            .order("updated_at", desc=True)
            .execute()
        )
        messages = inbox_res.data or []
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch creator inbox: {exc}",
        ) from exc

    if not messages:
        cache.set(cache_key, [], ttl_seconds=_INBOX_CREATOR_TTL)
        return []

    # ── Collect ids for batch lookups ─────────────────────────────────
    pitch_ids        = list({m["pitch_id"]        for m in messages})
    brand_user_ids   = list({m["brand_user_id"]   for m in messages})

    # ── Fetch pitch subjects ──────────────────────────────────────────
    try:
        pitches_res = (
            supabase_admin
            .table("pitches")
            .select("id, subject")
            .in_("id", pitch_ids)
            .execute()
        )
        pitches_map: dict[str, dict] = {
            p["id"]: p for p in (pitches_res.data or [])
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch pitch subjects: {exc}",
        ) from exc

    # ── Fetch brand_users rows to get brand_id link ───────────────────
    try:
        bu_res = (
            supabase_admin
            .table("brand_users")
            .select("id, email, company_name")
            .in_("id", brand_user_ids)
            .execute()
        )
        bu_map: dict[str, dict] = {
            bu["id"]: bu for bu in (bu_res.data or [])
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch brand user details: {exc}",
        ) from exc

    # ── Fetch brand profiles for niche + website ──────────────────────
    # brand_profiles links via brand_user_id
    try:
        bp_res = (
            supabase_admin
            .table("brand_profiles")
            .select("brand_user_id, company_name, niche, website")
            .in_("brand_user_id", brand_user_ids)
            .execute()
        )
        bp_map: dict[str, dict] = {
            bp["brand_user_id"]: bp for bp in (bp_res.data or [])
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch brand profiles: {exc}",
        ) from exc

    # ── Assemble response ─────────────────────────────────────────────
    result = []
    for msg in messages:
        buid    = msg["brand_user_id"]
        bu      = bu_map.get(buid, {})
        bp      = bp_map.get(buid, {})
        pitch   = pitches_map.get(msg["pitch_id"], {})

        result.append({
            "message_id":     msg["id"],
            "brand_response": msg["brand_response"],
            "response_note":  msg["response_note"],
            "created_at":     msg["created_at"],
            "updated_at":     msg["updated_at"],
            # pitch summary
            "pitch": {
                "id":      msg["pitch_id"],
                "subject": pitch.get("subject"),
            },
            # brand details — prefer brand_profiles, fall back to brand_users
            "brand": {
                "brand_user_id": buid,
                "company_name":  bp.get("company_name") or bu.get("company_name"),
                "niche":         bp.get("niche"),
                "website":       bp.get("website"),
            },
        })

    cache.set(cache_key, result, ttl_seconds=_INBOX_CREATOR_TTL)
    log.info(
        "Creator inbox returned %d messages | creator_id=%s",
        len(result), creator_id,
    )
    return result