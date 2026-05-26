"""
social_auth.py — Instagram & YouTube OAuth router for GetSpons.

Exposes:
    GET  /social/instagram/connect       Redirect to Instagram OAuth
    GET  /social/instagram/callback      Exchange code → token, save stats
    GET  /social/youtube/connect         Redirect to Google OAuth
    GET  /social/youtube/callback        Exchange code → token, save stats
    GET  /social/connections             List creator's connected accounts
    DELETE /social/{platform}/disconnect Remove a connection, recheck verified

Placeholder config (add real keys to .env later):
    INSTAGRAM_CLIENT_ID, INSTAGRAM_CLIENT_SECRET, INSTAGRAM_REDIRECT_URI
    YOUTUBE_CLIENT_ID,   YOUTUBE_CLIENT_SECRET,   YOUTUBE_REDIRECT_URI
"""

from __future__ import annotations

import os
import urllib.parse
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from database import supabase, supabase_admin
from logger import get_logger
from social_stats import fetch_instagram_stats, fetch_youtube_stats

router = APIRouter()
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_IG_CLIENT_ID     = os.getenv("INSTAGRAM_CLIENT_ID",    "placeholder_instagram_client_id")
_IG_CLIENT_SECRET = os.getenv("INSTAGRAM_CLIENT_SECRET", "placeholder_instagram_client_secret")
_IG_REDIRECT      = os.getenv("INSTAGRAM_REDIRECT_URI",  "http://localhost:8000/api/social/instagram/callback")

_YT_CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID",      "placeholder_youtube_client_id")
_YT_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET",  "placeholder_youtube_client_secret")
_YT_REDIRECT      = os.getenv("YOUTUBE_REDIRECT_URI",   "http://localhost:8000/api/social/youtube/callback")

_FRONTEND_BASE    = os.getenv("FRONTEND_BASE_URL",      "http://localhost:5500")

_IG_SCOPE = "instagram_basic,instagram_manage_insights,pages_show_list"
_YT_SCOPE = (
    "https://www.googleapis.com/auth/youtube.readonly "
    "https://www.googleapis.com/auth/yt-analytics.readonly"
)


def _is_placeholder(val: str) -> bool:
    v = val.strip().lower()
    return not v or v.startswith(("placeholder", "your_", "xxx"))


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _resolve_creator_user_id(authorization: str) -> str:
    """Validate JWT and return the creator's Supabase user_id."""
    try:
        token = authorization.replace("Bearer ", "").strip()
        if not token:
            raise ValueError("Empty token")
        user = supabase.auth.get_user(token)
        return user.user.id
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {exc}") from exc


# ---------------------------------------------------------------------------
# Helper: recompute is_verified flag
# ---------------------------------------------------------------------------


def recompute_verified(user_id: str) -> bool:
    """Check if creator has ≥1 active social connection; update profiles.is_verified."""
    try:
        res = (
            supabase_admin
            .table("social_connections")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        is_verified = bool(res.data)
        supabase_admin.table("profiles").update(
            {"is_verified": is_verified}
        ).eq("user_id", user_id).execute()
        log.info("Verified status updated | user_id=%s | is_verified=%s", user_id, is_verified)
        return is_verified
    except Exception as exc:
        log.warning("Failed to recompute verified status | user_id=%s | reason=%s", user_id, exc)
        return False


# ---------------------------------------------------------------------------
# GET /social/instagram/connect
# ---------------------------------------------------------------------------


@router.get("/instagram/connect")
def instagram_connect(authorization: str = Header(...)):
    """Redirect the creator to Instagram's OAuth authorization page."""
    if _is_placeholder(_IG_CLIENT_ID):
        raise HTTPException(
            status_code=503,
            detail="Instagram API not configured. Add INSTAGRAM_CLIENT_ID to .env.",
        )

    user_id = _resolve_creator_user_id(authorization)

    params = {
        "client_id":     _IG_CLIENT_ID,
        "redirect_uri":  _IG_REDIRECT,
        "scope":         _IG_SCOPE,
        "response_type": "code",
        "state":         user_id,  # pass user_id through OAuth state
    }
    auth_url = "https://api.instagram.com/oauth/authorize?" + urllib.parse.urlencode(params)
    log.info("Instagram OAuth redirect | user_id=%s", user_id)
    return RedirectResponse(url=auth_url)


# ---------------------------------------------------------------------------
# GET /social/instagram/callback
# ---------------------------------------------------------------------------


@router.get("/instagram/callback")
def instagram_callback(
    code:  str = Query(...),
    state: str = Query(...),  # user_id
    error: str = Query(default=None),
):
    """Handle Instagram OAuth callback. Exchange code for token and save stats."""
    if error:
        log.warning("Instagram OAuth error | state=%s | error=%s", state, error)
        return RedirectResponse(url=f"{_FRONTEND_BASE}/dashboard?social_error=instagram")

    user_id = state
    log.info("Instagram callback received | user_id=%s", user_id)

    # ── Exchange code for access token ────────────────────────────────
    try:
        token_resp = requests.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id":     _IG_CLIENT_ID,
                "client_secret": _IG_CLIENT_SECRET,
                "grant_type":    "authorization_code",
                "redirect_uri":  _IG_REDIRECT,
                "code":          code,
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        token_data    = token_resp.json()
        access_token  = token_data["access_token"]
        ig_user_id    = str(token_data["user_id"])
    except Exception as exc:
        log.error("Instagram token exchange failed | user_id=%s | reason=%s", user_id, exc)
        return RedirectResponse(url=f"{_FRONTEND_BASE}/dashboard?social_error=instagram_token")

    # ── Exchange for long-lived token (60 days) ───────────────────────
    try:
        ll_resp = requests.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type":        "ig_exchange_token",
                "client_secret":     _IG_CLIENT_SECRET,
                "access_token":      access_token,
            },
            timeout=10,
        )
        ll_resp.raise_for_status()
        ll_data      = ll_resp.json()
        access_token = ll_data.get("access_token", access_token)
    except Exception:
        pass  # Use short-lived token if exchange fails

    # ── Fetch handle (username) ───────────────────────────────────────
    try:
        me_resp = requests.get(
            f"https://graph.instagram.com/v18.0/{ig_user_id}",
            params={"fields": "username", "access_token": access_token},
            timeout=10,
        )
        me_resp.raise_for_status()
        handle = "@" + me_resp.json().get("username", ig_user_id)
    except Exception:
        handle = f"@ig_{ig_user_id}"

    # ── Fetch live stats ──────────────────────────────────────────────
    stats = fetch_instagram_stats(access_token, ig_user_id)

    # ── Upsert into social_connections ───────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    try:
        supabase_admin.table("social_connections").upsert({
            "user_id":          user_id,
            "platform":         "instagram",
            "access_token":     access_token,
            "platform_user_id": ig_user_id,
            "handle":           handle,
            "followers":        stats.get("followers", 0),
            "engagement_rate":  stats.get("engagement_rate", 0.0),
            "avg_views":        stats.get("avg_views", 0),
            "demographics":     stats.get("demographics", {}),
            "last_refreshed_at": now,
        }, on_conflict="user_id,platform").execute()
        log.info("Instagram connected | user_id=%s | handle=%s", user_id, handle)
    except Exception as exc:
        log.error("Instagram connection save failed | user_id=%s | reason=%s", user_id, exc)
        return RedirectResponse(url=f"{_FRONTEND_BASE}/dashboard?social_error=instagram_save")

    # ── Update profiles with live stats + verified badge ─────────────
    try:
        supabase_admin.table("profiles").update({
            "followers":       stats.get("followers", 0),
            "engagement_rate": stats.get("engagement_rate", 0.0),
        }).eq("user_id", user_id).execute()
    except Exception:
        pass

    recompute_verified(user_id)

    return RedirectResponse(url=f"{_FRONTEND_BASE}/dashboard?social_connected=instagram")


# ---------------------------------------------------------------------------
# GET /social/youtube/connect
# ---------------------------------------------------------------------------


@router.get("/youtube/connect")
def youtube_connect(authorization: str = Header(...)):
    """Redirect the creator to Google's OAuth authorization page."""
    if _is_placeholder(_YT_CLIENT_ID):
        raise HTTPException(
            status_code=503,
            detail="YouTube API not configured. Add YOUTUBE_CLIENT_ID to .env.",
        )

    user_id = _resolve_creator_user_id(authorization)

    params = {
        "client_id":       _YT_CLIENT_ID,
        "redirect_uri":    _YT_REDIRECT,
        "scope":           _YT_SCOPE,
        "response_type":   "code",
        "access_type":     "offline",
        "prompt":          "consent",
        "state":           user_id,
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    log.info("YouTube OAuth redirect | user_id=%s", user_id)
    return RedirectResponse(url=auth_url)


# ---------------------------------------------------------------------------
# GET /social/youtube/callback
# ---------------------------------------------------------------------------


@router.get("/youtube/callback")
def youtube_callback(
    code:  str = Query(...),
    state: str = Query(...),
    error: str = Query(default=None),
):
    """Handle YouTube/Google OAuth callback. Exchange code for token and save stats."""
    if error:
        log.warning("YouTube OAuth error | state=%s | error=%s", state, error)
        return RedirectResponse(url=f"{_FRONTEND_BASE}/dashboard?social_error=youtube")

    user_id = state
    log.info("YouTube callback received | user_id=%s", user_id)

    # ── Exchange code for token ───────────────────────────────────────
    try:
        token_resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code":          code,
                "client_id":     _YT_CLIENT_ID,
                "client_secret": _YT_CLIENT_SECRET,
                "redirect_uri":  _YT_REDIRECT,
                "grant_type":    "authorization_code",
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        token_data    = token_resp.json()
        access_token  = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
    except Exception as exc:
        log.error("YouTube token exchange failed | user_id=%s | reason=%s", user_id, exc)
        return RedirectResponse(url=f"{_FRONTEND_BASE}/dashboard?social_error=youtube_token")

    # ── Fetch channel ID ──────────────────────────────────────────────
    try:
        ch_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "id,snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        ch_resp.raise_for_status()
        items      = ch_resp.json().get("items", [])
        channel_id = items[0]["id"] if items else user_id
        handle     = "@" + items[0]["snippet"].get("customUrl", channel_id).lstrip("@") if items else f"@yt_{user_id}"
    except Exception:
        channel_id = user_id
        handle     = f"@yt_{user_id}"

    # ── Fetch live stats ──────────────────────────────────────────────
    stats = fetch_youtube_stats(access_token, channel_id)

    # ── Upsert into social_connections ───────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    try:
        supabase_admin.table("social_connections").upsert({
            "user_id":          user_id,
            "platform":         "youtube",
            "access_token":     access_token,
            "refresh_token":    refresh_token,
            "platform_user_id": channel_id,
            "handle":           handle,
            "followers":        stats.get("followers", 0),
            "engagement_rate":  stats.get("engagement_rate", 0.0),
            "avg_views":        stats.get("avg_views", 0),
            "demographics":     stats.get("demographics", {}),
            "last_refreshed_at": now,
        }, on_conflict="user_id,platform").execute()
        log.info("YouTube connected | user_id=%s | channel_id=%s", user_id, channel_id)
    except Exception as exc:
        log.error("YouTube connection save failed | user_id=%s | reason=%s", user_id, exc)
        return RedirectResponse(url=f"{_FRONTEND_BASE}/dashboard?social_error=youtube_save")

    # ── Update profiles with live stats ───────────────────────────────
    try:
        supabase_admin.table("profiles").update({
            "followers":       stats.get("followers", 0),
            "engagement_rate": stats.get("engagement_rate", 0.0),
        }).eq("user_id", user_id).execute()
    except Exception:
        pass

    recompute_verified(user_id)

    return RedirectResponse(url=f"{_FRONTEND_BASE}/dashboard?social_connected=youtube")


# ---------------------------------------------------------------------------
# GET /social/connections
# ---------------------------------------------------------------------------


@router.get("/connections")
def get_connections(authorization: str = Header(...)):
    """Return all connected social accounts for the authenticated creator."""
    user_id = _resolve_creator_user_id(authorization)

    try:
        res = (
            supabase_admin
            .table("social_connections")
            .select(
                "id, platform, handle, followers, engagement_rate, "
                "avg_views, demographics, last_refreshed_at, created_at"
            )
            .eq("user_id", user_id)
            .execute()
        )
        return {"connections": res.data or []}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch connections: {exc}") from exc


# ---------------------------------------------------------------------------
# DELETE /social/{platform}/disconnect
# ---------------------------------------------------------------------------


@router.delete("/{platform}/disconnect")
def disconnect_platform(platform: str, authorization: str = Header(...)):
    """Remove a social connection and recompute the verified badge."""
    if platform not in ("instagram", "youtube"):
        raise HTTPException(status_code=400, detail="Platform must be 'instagram' or 'youtube'.")

    user_id = _resolve_creator_user_id(authorization)

    try:
        supabase_admin.table("social_connections").delete(
        ).eq("user_id", user_id).eq("platform", platform).execute()
        log.info("Social disconnected | user_id=%s | platform=%s", user_id, platform)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to disconnect: {exc}") from exc

    is_verified = recompute_verified(user_id)
    return {"success": True, "is_verified": is_verified}


# ---------------------------------------------------------------------------
# POST /social/refresh  — manual refresh (rate limited)
# ---------------------------------------------------------------------------


from fastapi import Request as FastAPIRequest
from limiter import limiter


@router.post("/refresh")
@limiter.limit("2/hour")
def manual_refresh(request: FastAPIRequest, authorization: str = Header(...)):
    """Manually trigger a stats refresh for the authenticated creator's accounts."""
    from social_stats import _refresh_single_connection

    user_id = _resolve_creator_user_id(authorization)

    try:
        res = (
            supabase_admin
            .table("social_connections")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        connections = res.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch connections: {exc}") from exc

    if not connections:
        raise HTTPException(status_code=404, detail="No social accounts connected.")

    refreshed = []
    for conn in connections:
        _refresh_single_connection(conn)
        refreshed.append(conn.get("platform"))

    return {"success": True, "refreshed": refreshed}
