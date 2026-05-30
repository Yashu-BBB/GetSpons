"""
ai.py — AI content generation utilities for GetSpons.

This module is responsible for all LLM-powered content generation.

Functions
---------
generate_mediakit_content(profile)     → media kit copy for a creator
generate_campaign_brief(brand_profile) → professional campaign brief for a brand

Set MOCK_AI=false and ANTHROPIC_API_KEY=<key> in .env to switch to real Claude.
"""

from __future__ import annotations

import json
import os
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MOCK_AI: bool = os.getenv("MOCK_AI", "true").lower() != "false"


# ===========================================================================
# generate_mediakit_content
# ===========================================================================


def generate_mediakit_content(profile: dict[str, Any]) -> dict[str, Any]:
    """Generate AI-written media-kit copy for a creator's profile.

    Parameters
    ----------
    profile:
        Creator profile dict.  Expected keys (all optional):
        full_name, platform, handle, followers, niche, engagement_rate,
        bio, past_sponsors, pricing_min, pricing_max.

    Returns
    -------
    dict
        Keys: headline, bio_short, key_stats, audience_description,
              content_style, why_partner, pricing_table, cta.
    """
    if MOCK_AI:
        return _mock_mediakit(profile)
    return _claude_mediakit(profile)


# ===========================================================================
# generate_campaign_brief
# ===========================================================================


def generate_campaign_brief(brand_profile: dict[str, Any]) -> dict[str, Any]:
    """Generate a professional campaign brief for a brand.

    Parameters
    ----------
    brand_profile:
        Brand profile dict.  Expected keys (all optional):
        company_name, niche, campaign_goal, target_audience, content_type,
        key_message, budget_min, budget_max, campaign_timeline,
        description, website, preferred_platforms.

    Returns
    -------
    dict
        Keys: brief_title, executive_summary, campaign_objectives,
              target_audience, content_requirements, deliverables,
              timeline, budget_range, success_metrics, brand_guidelines.
    """
    if MOCK_AI:
        return _mock_campaign_brief(brand_profile)
    return _claude_campaign_brief(brand_profile)


# ===========================================================================
# Mock — media kit
# ===========================================================================


def _mock_mediakit(profile: dict[str, Any]) -> dict[str, Any]:
    """Return realistic, profile-aware mock media-kit content."""
    name: str        = profile.get("full_name") or "Creator"
    platform: str    = profile.get("platform") or "Social Media"
    handle: str      = profile.get("handle") or ""
    followers: int   = int(profile.get("followers") or 0)
    niche: str       = profile.get("niche") or "Lifestyle"
    engagement: float= float(profile.get("engagement_rate") or 0.0)
    bio: str         = profile.get("bio") or ""
    past_sponsors    = profile.get("past_sponsors") or []
    pricing_min: int = int(profile.get("pricing_min") or 500)
    pricing_max: int = int(profile.get("pricing_max") or 2000)

    followers_fmt = _fmt_followers(followers)
    mid_price     = (pricing_min + pricing_max) // 2
    sponsor_line  = (
        f"Previous brand partners include {', '.join(past_sponsors[:3])}."
        if past_sponsors
        else "Ready to build first-time brand partnerships."
    )

    return {
        "headline": f"Meet {name} — {platform}'s Leading Voice in {niche}",
        "bio_short": (
            f"{name} is a {niche} creator on {platform} "
            f"with {followers_fmt} engaged followers. "
            f"{bio.rstrip('.')}. {sponsor_line}"
        ),
        "key_stats": [
            {"label": "Followers / Subscribers", "value": followers_fmt},
            {"label": "Engagement Rate",         "value": f"{engagement:.1f}%"},
            {"label": "Primary Platform",        "value": platform},
            {"label": "Content Niche",           "value": niche},
        ],
        "audience_description": (
            f"{name}'s audience on {platform} is primarily composed of "
            f"{niche.lower()} enthusiasts aged 18–35 who are highly active online. "
            f"With an engagement rate of {engagement:.1f}%, followers actively like, "
            f"comment, and share content — signalling a community that trusts "
            f"{name}'s recommendations and acts on them."
        ),
        "content_style": (
            f"{name} produces {niche.lower()} content that blends authenticity with "
            f"high production value. The {platform} channel ({handle}) is known for "
            f"in-depth analysis, honest opinions, and a conversational tone that "
            f"resonates strongly with its audience."
        ),
        "why_partner": (
            f"Partnering with {name} gives your brand direct access to "
            f"{followers_fmt} targeted {niche.lower()} consumers on {platform}. "
            f"An engagement rate of {engagement:.1f}% means your message will be acted on. "
            f"{sponsor_line}"
        ),
        "pricing_table": [
            {"package": "Starter", "deliverable": f"1 dedicated {platform} post / mention",            "price": f"₹{pricing_min:,}"},
            {"package": "Growth",  "deliverable": "1 dedicated post + story / reel feature",           "price": f"₹{mid_price:,}"},
            {"package": "Premium", "deliverable": "Full campaign: post, story, newsletter & rights",   "price": f"₹{pricing_max:,}"},
        ],
        "cta": (
            f"Ready to reach {followers_fmt} passionate {niche.lower()} fans? "
            f"Let's build something great together — get in touch with {name} today."
        ),
    }


# ===========================================================================
# Mock — campaign brief
# ===========================================================================


def _mock_campaign_brief(bp: dict[str, Any]) -> dict[str, Any]:
    """Return a realistic, data-driven mock campaign brief."""
    company: str       = bp.get("company_name") or "Your Brand"
    niche: str         = bp.get("niche") or "Lifestyle"
    goal: str          = bp.get("campaign_goal") or "Increase brand awareness"
    audience: str      = bp.get("target_audience") or "Young adults aged 18–35"
    content_type: str  = bp.get("content_type") or "Short-form video"
    key_message: str   = bp.get("key_message") or f"Discover what makes {company} different"
    budget_min: int    = int(bp.get("budget_min") or 10000)
    budget_max: int    = int(bp.get("budget_max") or 50000)
    timeline: str      = bp.get("campaign_timeline") or "4 weeks"
    description: str   = bp.get("description") or ""
    platforms: list    = bp.get("preferred_platforms") or ["Instagram", "YouTube"]
    platforms_str: str = " and ".join(platforms) if platforms else "social media"

    budget_mid = (budget_min + budget_max) // 2

    return {
        "brief_title": (
            f"{company} × Creator Campaign — {niche} {content_type} Push"
        ),

        "executive_summary": (
            f"{company} is launching a {timeline} influencer marketing campaign "
            f"focused on {niche.lower()} audiences across {platforms_str}. "
            f"The campaign aims to {goal.lower()} by partnering with authentic creators "
            f"who can communicate the core message: '{key_message}'. "
            f"{'With a background in ' + description.split('.')[0].lower() + ', ' if description else ''}"
            f"this brief outlines all requirements, expectations, and success benchmarks "
            f"for participating creators."
        ),

        "campaign_objectives": [
            f"Primary: {goal}",
            f"Drive measurable engagement among {audience}",
            f"Generate high-quality {content_type.lower()} content across {platforms_str}",
            f"Build long-term creator relationships aligned with the {niche.lower()} space",
            f"Increase brand search volume and organic mentions by 20% over campaign period",
        ],

        "target_audience": {
            "description":    audience,
            "interests":      [niche, "lifestyle", "value-for-money products", "peer recommendations"],
            "platforms":      platforms,
            "behaviour":      (
                f"Highly active on {platforms_str}, relies on creator recommendations before "
                f"purchase decisions, engages with authentic storytelling over polished ads."
            ),
        },

        "content_requirements": {
            "format":          content_type,
            "platforms":       platforms,
            "tone":            f"Authentic, conversational, and aligned with {niche.lower()} culture",
            "key_message":     key_message,
            "must_include":    [
                f"Brand name '{company}' mentioned at least once",
                "Clear call-to-action (link in bio / swipe up / discount code)",
                "Disclosure: #ad or #sponsored as per platform guidelines",
            ],
            "must_avoid":      [
                "Competitor brand mentions",
                "Unverified claims or medical/financial advice",
                "Low-resolution or poorly lit visuals",
            ],
            "approval_process": (
                "Creators submit draft content for brand review 48 hours before posting. "
                "One round of revisions permitted. Final approval in writing required."
            ),
        },

        "deliverables": [
            {
                "item":     f"1× {content_type} (primary deliverable)",
                "platform": platforms[0] if platforms else "Instagram",
                "due":      "Week 2 of campaign",
            },
            {
                "item":     "1× Supporting story / short post",
                "platform": platforms[-1] if platforms else "Instagram",
                "due":      "Within 3 days of primary post",
            },
            {
                "item":     "Performance screenshot (reach, impressions, engagement)",
                "platform": "All",
                "due":      "7 days after final post",
            },
        ],

        "timeline": {
            "total_duration": timeline,
            "phases": [
                {"phase": "Briefing & onboarding",   "duration": "Days 1–3"},
                {"phase": "Content creation",         "duration": "Days 4–10"},
                {"phase": "Brand review & approval",  "duration": "Days 11–13"},
                {"phase": "Publishing window",        "duration": "Days 14–21"},
                {"phase": "Reporting & wrap-up",      "duration": "Days 22–28"},
            ],
        },

        "budget_range": {
            "min":      f"₹{budget_min:,}",
            "max":      f"₹{budget_max:,}",
            "mid":      f"₹{budget_mid:,}",
            "note": (
                f"Budget covers creator fees for {content_type.lower()} deliverables. "
                f"Usage rights and boosting fees are negotiated separately. "
                f"Payment released within 14 days of approved content going live."
            ),
        },

        "success_metrics": [
            {"metric": "Total reach",          "target": f"≥ 5× budget spend (₹{budget_min * 5:,})"},
            {"metric": "Engagement rate",      "target": "≥ 3.5% across all posts"},
            {"metric": "Click-through / link visits", "target": "≥ 500 unique visits"},
            {"metric": "Brand mentions / saves",      "target": "≥ 200"},
            {"metric": "Content pieces submitted on time", "target": "100%"},
        ],

        "brand_guidelines": {
            "tone":        f"Professional yet approachable. Reflect {company}'s {niche.lower()} expertise.",
            "visual_style": "On-brand colours preferred. Clean backgrounds. Avoid heavy filters.",
            "hashtags":    [f"#{company.replace(' ', '')}", f"#{niche}Creator", "#GetSpons"],
            "dos":   [f"Show the product/service in a real-life {niche.lower()} context",
                      "Be honest about your experience", "Tag @" + company.replace(" ", "").lower()],
            "donts": ["Do not alter the brand logo", "Do not post before brand approval",
                      "Do not make price or discount promises not agreed in writing"],
        },
    }


# ===========================================================================
# Real Claude API — media kit
# ===========================================================================


def _claude_mediakit(profile: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
    """Call Claude to generate media-kit content. Active when MOCK_AI=false."""
    client = _get_claude_client()

    prompt = f"""
You are a professional copywriter specialising in influencer media kits.

Given the creator profile below, generate compelling media-kit copy and return
it as a single JSON object with EXACTLY these keys:
  headline, bio_short, key_stats (list of 4 objects with label & value),
  audience_description, content_style, why_partner,
  pricing_table (list of objects with package, deliverable, price), cta.

Return ONLY the JSON object — no markdown fences, no extra text.

CREATOR PROFILE:
  Name:            {profile.get('full_name', 'N/A')}
  Platform:        {profile.get('platform', 'N/A')}
  Handle:          {profile.get('handle', 'N/A')}
  Followers:       {profile.get('followers', 0):,}
  Niche:           {profile.get('niche', 'N/A')}
  Engagement Rate: {profile.get('engagement_rate', 0)}%
  Bio:             {profile.get('bio', 'N/A')}
  Past Sponsors:   {', '.join(profile.get('past_sponsors') or []) or 'None'}
  Pricing Min:     ₹{profile.get('pricing_min', 0):,}
  Pricing Max:     ₹{profile.get('pricing_max', 0):,}
""".strip()

    return _call_claude(client, prompt)


# ===========================================================================
# Real Claude API — campaign brief
# ===========================================================================


def _claude_campaign_brief(bp: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
    """Call Claude to generate a campaign brief. Active when MOCK_AI=false."""
    client = _get_claude_client()

    platforms_str = ", ".join(bp.get("preferred_platforms") or ["Instagram", "YouTube"])

    prompt = f"""
You are a senior brand strategist specialising in influencer marketing campaigns.

Given the brand profile below, generate a professional campaign brief and return
it as a single JSON object with EXACTLY these keys:
  brief_title          (str)
  executive_summary    (str, 3-4 sentences)
  campaign_objectives  (list of 5 strings)
  target_audience      (object: description, interests list, platforms list, behaviour)
  content_requirements (object: format, platforms list, tone, key_message,
                        must_include list, must_avoid list, approval_process)
  deliverables         (list of objects: item, platform, due)
  timeline             (object: total_duration, phases list of {{phase, duration}})
  budget_range         (object: min, max, mid, note)
  success_metrics      (list of objects: metric, target)
  brand_guidelines     (object: tone, visual_style, hashtags list, dos list, donts list)

Return ONLY the JSON object — no markdown fences, no extra text.

BRAND PROFILE:
  Company:           {bp.get('company_name', 'N/A')}
  Niche:             {bp.get('niche', 'N/A')}
  Campaign Goal:     {bp.get('campaign_goal', 'N/A')}
  Target Audience:   {bp.get('target_audience', 'N/A')}
  Content Type:      {bp.get('content_type', 'N/A')}
  Key Message:       {bp.get('key_message', 'N/A')}
  Budget Min:        ₹{int(bp.get('budget_min') or 0):,}
  Budget Max:        ₹{int(bp.get('budget_max') or 0):,}
  Campaign Timeline: {bp.get('campaign_timeline', 'N/A')}
  Description:       {bp.get('description', 'N/A')}
  Platforms:         {platforms_str}
  Website:           {bp.get('website', 'N/A')}
""".strip()

    return _call_claude(client, prompt)


# ===========================================================================
# Shared Claude helpers
# ===========================================================================


def _get_claude_client():  # pragma: no cover
    """Import anthropic and return an authenticated client.

    Raises
    ------
    RuntimeError   If the package is missing or ANTHROPIC_API_KEY is not set.
    """
    try:
        import anthropic  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "The 'anthropic' package is required. Install it: pip install anthropic"
        ) from exc

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to .env or use MOCK_AI=true."
        )

    import anthropic  # noqa: PLC0415 — re-import after guard
    return anthropic.Anthropic(api_key=api_key)


def _call_claude(client, prompt: str) -> dict[str, Any]:  # pragma: no cover
    """Send a prompt to Claude and parse the JSON response.

    Raises
    ------
    RuntimeError   If the API call fails or the response is not valid JSON.
    """
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw: str = message.content[0].text
    # Strip accidental markdown fences if present
    clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude returned invalid JSON: {exc}\nRaw response:\n{raw}") from exc


# ===========================================================================
# Private helpers
# ===========================================================================


def _fmt_followers(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return f"{count:,}"


# Keep old name as alias so existing imports don't break
_format_followers = _fmt_followers