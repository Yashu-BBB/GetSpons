"""
social_stats.py — Social media stat fetching and background refresh for GetSpons.

Handles:
  - Fetching live stats from Instagram Graph API
  - Fetching live stats from YouTube Data API v3
  - 12-hour background refresh job (called by APScheduler in main.py)

All API credentials live in .env. If not configured, functions return
placeholder data and log a warning — no crash.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import requests

from database import supabase_admin
from logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_IG_CLIENT_ID     = os.getenv("INSTAGRAM_CLIENT_ID", "")
_IG_CLIENT_SECRET = os.getenv("INSTAGRAM_CLIENT_SECRET", "")

_YT_CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID", "")
_YT_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")

_REFRESH_INTERVAL_HOURS = 12


def _placeholder(key: str) -> bool:
    v = key.strip().lower()
    return not v or v.startswith(("placeholder", "your_", "xxx"))


# ---------------------------------------------------------------------------
# Instagram stat fetching
# ---------------------------------------------------------------------------


def fetch_instagram_stats(access_token: str, ig_user_id: str) -> dict[str, Any]:
    """Fetch live stats from Instagram Graph API.

    Returns
    -------
    dict with keys: followers, following, engagement_rate, avg_views,
                    demographics (age, gender, location), media_count
    """
    if _placeholder(_IG_CLIENT_ID):
        log.warning("Instagram API not configured — returning placeholder stats")
        return _placeholder_ig_stats()

    base = "https://graph.instagram.com/v18.0"

    try:
        # ── Basic profile stats ────────────────────────────────────────
        profile_resp = requests.get(
            f"{base}/{ig_user_id}",
            params={
                "fields":       "followers_count,follows_count,media_count",
                "access_token": access_token,
            },
            timeout=10,
        )
        profile_resp.raise_for_status()
        profile = profile_resp.json()

        followers   = profile.get("followers_count", 0)
        media_count = profile.get("media_count", 0)

        # ── Recent media engagement ────────────────────────────────────
        media_resp = requests.get(
            f"{base}/{ig_user_id}/media",
            params={
                "fields":       "like_count,comments_count,media_type",
                "limit":        20,
                "access_token": access_token,
            },
            timeout=10,
        )
        media_resp.raise_for_status()
        media_items = media_resp.json().get("data", [])

        total_likes    = sum(m.get("like_count", 0)    for m in media_items)
        total_comments = sum(m.get("comments_count", 0) for m in media_items)
        avg_engagement = (
            ((total_likes + total_comments) / len(media_items) / max(followers, 1)) * 100
            if media_items else 0.0
        )
        avg_views = int((total_likes + total_comments) / max(len(media_items), 1))

        # ── Audience demographics (requires Business/Creator account) ──
        demographics = _fetch_ig_demographics(base, ig_user_id, access_token)

        return {
            "followers":       followers,
            "following":       profile.get("follows_count", 0),
            "media_count":     media_count,
            "engagement_rate": round(avg_engagement, 2),
            "avg_views":       avg_views,
            "demographics":    demographics,
        }

    except Exception as exc:
        log.warning("Instagram stats fetch failed | ig_user_id=%s | reason=%s", ig_user_id, exc)
        return _placeholder_ig_stats()


def _fetch_ig_demographics(base: str, ig_user_id: str, access_token: str) -> dict:
    """Fetch audience demographics from Instagram Insights API."""
    try:
        resp = requests.get(
            f"{base}/{ig_user_id}/insights",
            params={
                "metric":       "audience_gender_age,audience_country,audience_city",
                "period":       "lifetime",
                "access_token": access_token,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])

        demographics: dict = {"age": {}, "gender": {}, "location": {}}
        for item in data:
            name   = item.get("name", "")
            values = item.get("values", [{}])
            value  = values[-1].get("value", {}) if values else {}

            if name == "audience_gender_age":
                # Aggregate by gender and age bucket
                gender_totals: dict = {}
                age_totals:    dict = {}
                for key, count in value.items():
                    parts = key.split(".")  # e.g. "F.25-34"
                    if len(parts) == 2:
                        g, age = parts
                        gender_totals[g]   = gender_totals.get(g, 0)   + count
                        age_totals[age]    = age_totals.get(age, 0)     + count
                demographics["gender"] = gender_totals
                demographics["age"]    = age_totals

            elif name == "audience_country":
                demographics["location"] = dict(
                    sorted(value.items(), key=lambda x: x[1], reverse=True)[:10]
                )

        return demographics

    except Exception as exc:
        log.debug("IG demographics fetch failed: %s", exc)
        return {"age": {}, "gender": {}, "location": {}}


def _placeholder_ig_stats() -> dict:
    return {
        "followers":       0,
        "following":       0,
        "media_count":     0,
        "engagement_rate": 0.0,
        "avg_views":       0,
        "demographics":    {"age": {}, "gender": {}, "location": {}},
    }


# ---------------------------------------------------------------------------
# YouTube stat fetching
# ---------------------------------------------------------------------------


def fetch_youtube_stats(access_token: str, channel_id: str) -> dict[str, Any]:
    """Fetch live stats from YouTube Data API v3.

    Returns
    -------
    dict with keys: followers (subscribers), engagement_rate, avg_views,
                    total_views, video_count, demographics
    """
    if _placeholder(_YT_CLIENT_ID):
        log.warning("YouTube API not configured — returning placeholder stats")
        return _placeholder_yt_stats()

    base = "https://www.googleapis.com/youtube/v3"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        # ── Channel stats ──────────────────────────────────────────────
        ch_resp = requests.get(
            f"{base}/channels",
            params={
                "part": "statistics,snippet",
                "id":   channel_id,
            },
            headers=headers,
            timeout=10,
        )
        ch_resp.raise_for_status()
        items = ch_resp.json().get("items", [])
        if not items:
            return _placeholder_yt_stats()

        stats       = items[0].get("statistics", {})
        subscribers = int(stats.get("subscriberCount", 0))
        total_views = int(stats.get("viewCount", 0))
        video_count = int(stats.get("videoCount", 0))

        # ── Recent video performance ───────────────────────────────────
        search_resp = requests.get(
            f"{base}/search",
            params={
                "part":       "id",
                "channelId":  channel_id,
                "maxResults": 10,
                "order":      "date",
                "type":       "video",
            },
            headers=headers,
            timeout=10,
        )
        search_resp.raise_for_status()
        video_ids = [
            item["id"]["videoId"]
            for item in search_resp.json().get("items", [])
            if item.get("id", {}).get("videoId")
        ]

        avg_views       = 0
        avg_engagement  = 0.0

        if video_ids:
            vid_resp = requests.get(
                f"{base}/videos",
                params={
                    "part": "statistics",
                    "id":   ",".join(video_ids),
                },
                headers=headers,
                timeout=10,
            )
            vid_resp.raise_for_status()
            vid_items = vid_resp.json().get("items", [])

            total_v    = sum(int(v["statistics"].get("viewCount",    0)) for v in vid_items)
            total_l    = sum(int(v["statistics"].get("likeCount",    0)) for v in vid_items)
            total_c    = sum(int(v["statistics"].get("commentCount", 0)) for v in vid_items)
            n          = len(vid_items)

            avg_views       = total_v // max(n, 1)
            avg_engagement  = (
                (total_l + total_c) / max(total_v, 1) * 100
                if total_v > 0 else 0.0
            )

        # ── Demographics via YouTube Analytics API ────────────────────
        demographics = _fetch_yt_demographics(access_token, channel_id)

        return {
            "followers":       subscribers,
            "total_views":     total_views,
            "video_count":     video_count,
            "engagement_rate": round(avg_engagement, 2),
            "avg_views":       avg_views,
            "demographics":    demographics,
        }

    except Exception as exc:
        log.warning("YouTube stats fetch failed | channel_id=%s | reason=%s", channel_id, exc)
        return _placeholder_yt_stats()


def _fetch_yt_demographics(access_token: str, channel_id: str) -> dict:
    """Fetch audience demographics from YouTube Analytics API."""
    try:
        from datetime import date
        today     = date.today().isoformat()
        start     = (date.today() - timedelta(days=90)).isoformat()

        resp = requests.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            params={
                "ids":        f"channel=={channel_id}",
                "startDate":  start,
                "endDate":    today,
                "metrics":    "viewerPercentage",
                "dimensions": "ageGroup,gender",
            },
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        rows = resp.json().get("rows", [])

        age_map: dict    = {}
        gender_map: dict = {}

        for row in rows:
            age, gender, pct = row[0], row[1], row[2]
            age_map[age]       = age_map.get(age, 0) + pct
            gender_map[gender] = gender_map.get(gender, 0) + pct

        return {"age": age_map, "gender": gender_map, "location": {}}

    except Exception as exc:
        log.debug("YT demographics fetch failed: %s", exc)
        return {"age": {}, "gender": {}, "location": {}}


def _placeholder_yt_stats() -> dict:
    return {
        "followers":       0,
        "total_views":     0,
        "video_count":     0,
        "engagement_rate": 0.0,
        "avg_views":       0,
        "demographics":    {"age": {}, "gender": {}, "location": {}},
    }


# ---------------------------------------------------------------------------
# Background refresh — called every 12 hours by APScheduler
# ---------------------------------------------------------------------------


def refresh_all_social_stats() -> None:
    """Iterate every social_connections row and refresh stats if stale (>12h).

    Called automatically by APScheduler. Safe to call manually too.
    """
    log.info("Social stats background refresh started")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=_REFRESH_INTERVAL_HOURS)
    cutoff_iso = cutoff.isoformat()

    try:
        res = (
            supabase_admin
            .table("social_connections")
            .select("id, user_id, platform, access_token, platform_user_id, last_refreshed_at")
            .lt("last_refreshed_at", cutoff_iso)
            .execute()
        )
        rows = res.data or []
    except Exception as exc:
        log.error("Social refresh: failed to fetch connections | reason=%s", exc)
        return

    log.info("Social stats refresh | %d connections to refresh", len(rows))

    for row in rows:
        _refresh_single_connection(row)

    log.info("Social stats background refresh complete")


def _refresh_single_connection(row: dict) -> None:
    """Refresh stats for one social_connections row."""
    platform  = row.get("platform", "")
    conn_id   = row.get("id")
    token     = row.get("access_token", "")
    platform_user_id = row.get("platform_user_id", "")

    try:
        if platform == "instagram":
            stats = fetch_instagram_stats(token, platform_user_id)
        elif platform == "youtube":
            stats = fetch_youtube_stats(token, platform_user_id)
        else:
            log.warning("Unknown platform in social_connections | id=%s | platform=%s", conn_id, platform)
            return

        now = datetime.now(timezone.utc).isoformat()
        supabase_admin.table("social_connections").update({
            "followers":        stats.get("followers", 0),
            "engagement_rate":  stats.get("engagement_rate", 0.0),
            "avg_views":        stats.get("avg_views", 0),
            "demographics":     stats.get("demographics", {}),
            "last_refreshed_at": now,
        }).eq("id", conn_id).execute()

        log.info(
            "Social stats refreshed | id=%s | platform=%s | followers=%d",
            conn_id, platform, stats.get("followers", 0),
        )

    except Exception as exc:
        log.error(
            "Social stats refresh failed | id=%s | platform=%s | reason=%s",
            conn_id, platform, exc,
        )


def get_best_social_stats(user_id: str) -> Optional[dict]:
    """Return the richest available social stats for a creator.

    Prefers Instagram; falls back to YouTube. Returns None if no connections.
    """
    try:
        res = (
            supabase_admin
            .table("social_connections")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        connections = res.data or []
    except Exception:
        return None

    if not connections:
        return None

    # Prefer Instagram, then YouTube
    for preferred_platform in ("instagram", "youtube"):
        for conn in connections:
            if conn.get("platform") == preferred_platform:
                return conn

    return connections[0] if connections else None
