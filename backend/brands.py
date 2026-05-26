"""
brands.py — Brands router for GetSpons.

Exposes:
    GET /brands              Lightweight list with optional filters. Cached 600s.
    GET /brands/{brand_id}   Full brand detail. Cached 600s.

Caching
-------
    List   key: "brands_list_{niche}_{min_followers}"
    Detail key: "brand_detail_{brand_id}"
    TTL: 600 seconds (10 minutes)

Sample Data
-----------
    When the Supabase brands table is empty (or unreachable),
    SAMPLE_BRANDS is returned so the UI is always functional during dev/demo.
"""

from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional

from cache import cache
from database import supabase_admin
from limiter import limiter
from logger import get_logger

router = APIRouter()
log = get_logger(__name__)

_BRANDS_TTL = 600   # 10 minutes cache

# ---------------------------------------------------------------------------
# Column sets
# ---------------------------------------------------------------------------

_LIST_COLUMNS = (
    "id, name, niche, min_followers, max_followers, "
    "content_types, campaign_budget_min, campaign_budget_max, "
    "instagram_handle, youtube_handle, country, active"
)

_DETAIL_COLUMNS = (
    "id, name, niche, min_followers, max_followers, "
    "content_types, campaign_budget_min, campaign_budget_max, "
    "instagram_handle, youtube_handle, country, active, "
    "description, audience_requirement, contact_email, website"
)

# ---------------------------------------------------------------------------
# Sample brands — shown when DB table is empty (demo / dev mode)
# ---------------------------------------------------------------------------

SAMPLE_BRANDS = [
    {
        "id": "sample-001",
        "name": "Mamaearth",
        "niche": "Beauty",
        "country": "India",
        "min_followers": 5000,
        "max_followers": 500000,
        "campaign_budget_min": 3000,
        "campaign_budget_max": 25000,
        "instagram_handle": "@mamaearth",
        "youtube_handle": "@MamaearthOfficial",
        "content_types": ["Instagram Reel", "YouTube Review", "Stories"],
        "audience_requirement": "Primarily female audience aged 18–35 interested in skincare and wellness.",
        "description": "India's leading toxin-free beauty brand. We craft products with natural goodness — no harmful chemicals. Looking for authentic micro-creators who can showcase real results.",
        "contact_email": "influencer@mamaearth.in",
        "website": "https://mamaearth.in",
        "active": True,
    },
    {
        "id": "sample-002",
        "name": "boAt Lifestyle",
        "niche": "Tech",
        "country": "India",
        "min_followers": 10000,
        "max_followers": 1000000,
        "campaign_budget_min": 8000,
        "campaign_budget_max": 50000,
        "instagram_handle": "@boat.nirvana",
        "youtube_handle": "@boAtNirvana",
        "content_types": ["YouTube Review", "Instagram Reel", "Unboxing"],
        "audience_requirement": "Tech-savvy audience aged 18–30, interested in audio & wearables.",
        "description": "India's #1 audio and wearables brand. We're disrupting the consumer electronics market with affordable, stylish products. We partner with tech enthusiasts and lifestyle creators.",
        "contact_email": "collab@boat-lifestyle.com",
        "website": "https://www.boat-lifestyle.com",
        "active": True,
    },
    {
        "id": "sample-003",
        "name": "Rage Coffee",
        "niche": "Food",
        "country": "India",
        "min_followers": 3000,
        "max_followers": 200000,
        "campaign_budget_min": 2000,
        "campaign_budget_max": 15000,
        "instagram_handle": "@rage.coffee",
        "youtube_handle": None,
        "content_types": ["Instagram Reel", "Stories", "Blog Post"],
        "audience_requirement": "Coffee lovers, working professionals, fitness enthusiasts aged 22–40.",
        "description": "India's fastest-growing specialty coffee brand. From cold brews to instant espresso, we're redefining the coffee culture. Looking for creators passionate about food, fitness, or productivity.",
        "contact_email": "partnerships@ragecoffee.com",
        "website": "https://www.ragecoffee.com",
        "active": True,
    },
    {
        "id": "sample-004",
        "name": "Cult.fit",
        "niche": "Fitness",
        "country": "India",
        "min_followers": 8000,
        "max_followers": 750000,
        "campaign_budget_min": 5000,
        "campaign_budget_max": 40000,
        "instagram_handle": "@cult.official",
        "youtube_handle": "@CultFit",
        "content_types": ["YouTube Vlog", "Instagram Reel", "Live Session"],
        "audience_requirement": "Health-conscious audience aged 20–40 who are gym-goers or interested in home workouts.",
        "description": "India's largest fitness platform — gym memberships, live classes, mental wellness, and healthy food all in one. We want creators who live the fit life.",
        "contact_email": "creator@cult.fit",
        "website": "https://www.cult.fit",
        "active": True,
    },
    {
        "id": "sample-005",
        "name": "Niyo",
        "niche": "Finance",
        "country": "India",
        "min_followers": 15000,
        "max_followers": 500000,
        "campaign_budget_min": 10000,
        "campaign_budget_max": 60000,
        "instagram_handle": "@niyomoney",
        "youtube_handle": "@NiyoMoney",
        "content_types": ["YouTube Explainer", "Instagram Carousel", "Podcast"],
        "audience_requirement": "Working professionals, students, frequent travellers aged 22–40 interested in personal finance.",
        "description": "Next-gen neo-banking platform. Niyo offers zero-forex cards, salary accounts, and smart savings tools. We're looking for fintech-savvy creators who can make finance cool.",
        "contact_email": "influencer@goniyo.com",
        "website": "https://www.goniyo.com",
        "active": True,
    },
    {
        "id": "sample-006",
        "name": "The Souled Store",
        "niche": "Fashion",
        "country": "India",
        "min_followers": 5000,
        "max_followers": 400000,
        "campaign_budget_min": 3000,
        "campaign_budget_max": 20000,
        "instagram_handle": "@thesouledstore",
        "youtube_handle": "@TheSouledStore",
        "content_types": ["Instagram Reel", "Try-on Haul", "Stories"],
        "audience_requirement": "Pop culture fans, gamers, anime lovers aged 16–35.",
        "description": "India's most loved pop-culture apparel brand. From Bollywood to Marvel, we celebrate what you're passionate about. Looking for creators who wear their personality on their sleeve.",
        "contact_email": "collab@thesouledstore.com",
        "website": "https://www.thesouledstore.com",
        "active": True,
    },
]


# ---------------------------------------------------------------------------
# GET /brands  — lightweight list, cached
# ---------------------------------------------------------------------------


@router.get("/", response_model=None)
@limiter.limit("60/hour")
def get_brands(
    request: Request,
    niche: Optional[str] = Query(default=None),
    min_followers: Optional[int] = Query(default=None, ge=0),
):
    """Return a lightweight list of brands with optional filtering.

    Falls back to SAMPLE_BRANDS when the DB table is empty or unavailable,
    ensuring the UI always has data to display.
    """
    cache_key = f"brands_list_{niche}_{min_followers}"

    # ── Cache hit ─────────────────────────────────────────────────────
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # ── Cache miss — query Supabase ───────────────────────────────────
    filter_str = f"niche={niche}, min_followers={min_followers}"
    log.info("Brands list fetched | filters=[%s]", filter_str)

    try:
        query = supabase_admin.table("brands").select(_LIST_COLUMNS)

        if niche is not None:
            query = query.eq("niche", niche)
        if min_followers is not None:
            query = query.lte("min_followers", min_followers)

        result = query.execute()
        data = result.data or []

    except Exception as exc:
        log.warning("Brands DB query failed, using sample data: %s", exc)
        data = []

    # ── Fall back to sample brands if DB is empty ─────────────────────
    if not data:
        log.info("No brands in DB — serving sample data")
        data = _apply_sample_filters(SAMPLE_BRANDS, niche, min_followers)

    cache.set(cache_key, data, ttl_seconds=_BRANDS_TTL)
    return data


# ---------------------------------------------------------------------------
# GET /brands/{brand_id}  — full detail, cached
# ---------------------------------------------------------------------------


@router.get("/{brand_id}", response_model=None)
def get_brand(brand_id: str):
    """Return full detail for a single brand. Falls back to sample data."""
    cache_key = f"brand_detail_{brand_id}"

    # ── Cache hit ─────────────────────────────────────────────────────
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # ── Cache miss — query Supabase ───────────────────────────────────
    try:
        result = (
            supabase_admin
            .table("brands")
            .select(_DETAIL_COLUMNS)
            .eq("id", brand_id)
            .single()
            .execute()
        )

        if result.data:
            log.info("Single brand fetched from DB | brand_id=%s", brand_id)
            cache.set(cache_key, result.data, ttl_seconds=_BRANDS_TTL)
            return result.data

    except Exception as exc:
        error_str = str(exc).lower()
        # 404 from Supabase — fall through to sample lookup below
        if "no rows" not in error_str and "json object requested" not in error_str:
            log.warning("Brand DB fetch error, trying sample: %s", exc)

    # ── Fall back to sample data by id ────────────────────────────────
    sample = next((b for b in SAMPLE_BRANDS if b["id"] == brand_id), None)
    if sample:
        log.info("Serving sample brand | brand_id=%s", brand_id)
        cache.set(cache_key, sample, ttl_seconds=_BRANDS_TTL)
        return sample

    log.warning("Brand not found | brand_id=%s", brand_id)
    raise HTTPException(
        status_code=404,
        detail=f"Brand with id '{brand_id}' not found.",
    )


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _apply_sample_filters(brands: list, niche: Optional[str], min_followers: Optional[int]) -> list:
    """Apply niche and min_followers filters to the sample brand list."""
    result = brands
    if niche:
        result = [b for b in result if b.get("niche") == niche]
    if min_followers is not None:
        result = [b for b in result if (b.get("min_followers") or 0) <= min_followers]
    return result