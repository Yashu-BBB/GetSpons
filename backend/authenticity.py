"""
authenticity.py — Fake follower detection router for GetSpons.

Pure math — no AI required. Uses engagement rate, follower count, and
like-to-comment ratio against industry benchmarks to produce a 0-100
authenticity score.

Exposes:
    GET /authenticity/{creator_handle}   Score by handle
    GET /authenticity/id/{user_id}       Score by internal user_id

Benchmark tiers (by follower count):
    Nano  (<10K)     : healthy engagement ≥ 5.0%
    Micro (10K-100K) : healthy engagement ≥ 3.0%
    Macro (100K-1M)  : healthy engagement ≥ 1.5%
    Mega  (1M+)      : healthy engagement ≥ 0.5%

Score labels:
    80-100 : Highly Authentic
    60-79  : Mostly Authentic
    40-59  : Suspicious
    0-39   : Likely Fake
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from database import supabase_admin
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Benchmark tables
# ---------------------------------------------------------------------------

# (min_followers, max_followers, expected_min_engagement_pct, weight_label)
_ENGAGEMENT_BENCHMARKS = [
    (0,        10_000,     5.0,  "Nano"),
    (10_000,   100_000,    3.0,  "Micro"),
    (100_000,  1_000_000,  1.5,  "Macro"),
    (1_000_000, None,      0.5,  "Mega"),
]

# Industry average like:comment ratio range (healthy = 50-200 likes per comment)
_LIKE_COMMENT_RATIO_MIN = 20
_LIKE_COMMENT_RATIO_MAX = 500


# ---------------------------------------------------------------------------
# Score computation (pure math)
# ---------------------------------------------------------------------------


def compute_authenticity_score(
    followers:       int,
    engagement_rate: float,
    avg_views:       int = 0,
    demographics:    dict | None = None,
) -> dict[str, Any]:
    """Compute a 0-100 authenticity score for a creator.

    Parameters
    ----------
    followers:       Total follower/subscriber count.
    engagement_rate: Engagement rate as a percentage (0-100).
    avg_views:       Average views per post/video (0 if unavailable).
    demographics:    Audience demographics dict (from social_connections).

    Returns
    -------
    dict
        { score: int, label: str, breakdown: { ... }, explanation: str }
    """
    followers       = max(followers, 0)
    engagement_rate = max(engagement_rate, 0.0)

    # ── Component 1: Engagement rate vs benchmark (40 pts) ────────────
    expected = _expected_engagement(followers)
    if expected > 0:
        ratio = engagement_rate / expected
        # Perfect = 1.0x, capped at 2x for max score
        engagement_score = min(ratio, 2.0) / 2.0 * 40
    else:
        engagement_score = 20.0  # neutral if no benchmark

    # ── Component 2: Engagement rate raw sanity check (25 pts) ────────
    # Extremely high engagement (>50%) is suspicious (bots like/comment farming)
    if engagement_rate > 50:
        raw_score = 0
    elif engagement_rate == 0:
        raw_score = 0
    elif engagement_rate >= expected:
        raw_score = 25
    else:
        raw_score = (engagement_rate / expected) * 25

    # ── Component 3: Follower-to-views ratio (20 pts) ─────────────────
    # If avg_views > 0, view-to-follower ratio should be reasonable
    view_score = 20.0
    if avg_views > 0 and followers > 0:
        view_ratio = avg_views / followers
        if view_ratio < 0.005:
            # Very low view rate — suspicious (ghost followers)
            view_score = 5.0
        elif view_ratio < 0.02:
            view_score = 12.0
        elif view_ratio < 0.5:
            view_score = 20.0
        else:
            # Viral-level views per follower — slightly suspicious
            view_score = 15.0

    # ── Component 4: Demographic diversity (15 pts) ────────────────────
    demo_score = 15.0
    if demographics:
        location_data = demographics.get("location", {})
        if location_data:
            values     = list(location_data.values())
            total      = sum(values)
            top_pct    = max(values) / max(total, 1) * 100
            # Highly concentrated audience (>80% one location) = suspicious
            if top_pct > 80:
                demo_score = 5.0
            elif top_pct > 60:
                demo_score = 10.0
            else:
                demo_score = 15.0

    # ── Final score ────────────────────────────────────────────────────
    total = int(round(engagement_score + raw_score + view_score + demo_score))
    total = max(0, min(100, total))

    label = _score_label(total)

    explanation = (
        f"Engagement rate of {engagement_rate:.1f}% is "
        f"{'above' if engagement_rate >= expected else 'below'} the "
        f"{_tier_label(followers)} creator average of {expected:.1f}%. "
        f"Score factors: engagement benchmark ({int(engagement_score)}/40), "
        f"engagement sanity ({int(raw_score)}/25), "
        f"view ratio ({int(view_score)}/20), "
        f"audience diversity ({int(demo_score)}/15)."
    )

    return {
        "score": total,
        "label": label,
        "breakdown": {
            "engagement_benchmark_score": int(engagement_score),
            "engagement_sanity_score":    int(raw_score),
            "view_ratio_score":           int(view_score),
            "demographic_diversity_score": int(demo_score),
        },
        "tier":           _tier_label(followers),
        "expected_engagement": expected,
        "actual_engagement":   engagement_rate,
        "explanation":    explanation,
    }


def _expected_engagement(followers: int) -> float:
    for min_f, max_f, expected, _ in _ENGAGEMENT_BENCHMARKS:
        if max_f is None or followers < max_f:
            if followers >= min_f:
                return expected
    return 1.5


def _tier_label(followers: int) -> str:
    for min_f, max_f, _, label in _ENGAGEMENT_BENCHMARKS:
        if max_f is None or followers < max_f:
            if followers >= min_f:
                return label
    return "Macro"


def _score_label(score: int) -> str:
    if score >= 80:
        return "Highly Authentic"
    elif score >= 60:
        return "Mostly Authentic"
    elif score >= 40:
        return "Suspicious"
    else:
        return "Likely Fake"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_score_for_profile(profile: dict) -> dict:
    """Pull stats from a profile row and social_connections and compute score."""
    user_id         = profile.get("user_id")
    followers       = int(profile.get("followers", 0) or 0)
    engagement_rate = float(profile.get("engagement_rate", 0.0) or 0.0)
    avg_views       = 0
    demographics    = {}

    # Try to enrich from social_connections
    if user_id:
        try:
            sc_res = (
                supabase_admin
                .table("social_connections")
                .select("followers, engagement_rate, avg_views, demographics")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if sc_res.data:
                sc = sc_res.data[0]
                followers       = int(sc.get("followers", 0) or 0) or followers
                engagement_rate = float(sc.get("engagement_rate", 0.0) or 0.0) or engagement_rate
                avg_views       = int(sc.get("avg_views", 0) or 0)
                demographics    = sc.get("demographics") or {}
        except Exception:
            pass

    result = compute_authenticity_score(followers, engagement_rate, avg_views, demographics)
    result["creator_handle"]  = profile.get("handle", "")
    result["creator_name"]    = profile.get("full_name", "")
    result["followers"]       = followers
    result["engagement_rate"] = engagement_rate
    return result


# ---------------------------------------------------------------------------
# GET /authenticity/{creator_handle}
# ---------------------------------------------------------------------------


@router.get("/{creator_handle}")
def score_by_handle(creator_handle: str):
    """Return the authenticity score for a creator identified by their handle."""
    handle = creator_handle.lstrip("@").strip()

    try:
        res = (
            supabase_admin
            .table("profiles")
            .select("*")
            .ilike("handle", f"%{handle}%")
            .limit(1)
            .execute()
        )
        profiles = res.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}") from exc

    if not profiles:
        raise HTTPException(
            status_code=404,
            detail=f"No creator found with handle '{creator_handle}'.",
        )

    return _build_score_for_profile(profiles[0])


# ---------------------------------------------------------------------------
# GET /authenticity/id/{user_id}
# ---------------------------------------------------------------------------


@router.get("/id/{user_id}")
def score_by_user_id(user_id: str):
    """Return the authenticity score for a creator by their internal user_id."""
    try:
        res = (
            supabase_admin
            .table("profiles")
            .select("*")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        profile = res.data
    except Exception as exc:
        msg = str(exc).lower()
        if "no rows" in msg or "json object requested" in msg:
            raise HTTPException(status_code=404, detail="Creator not found.") from exc
        raise HTTPException(status_code=500, detail=f"Database query failed: {exc}") from exc

    if not profile:
        raise HTTPException(status_code=404, detail="Creator not found.")

    return _build_score_for_profile(profile)
