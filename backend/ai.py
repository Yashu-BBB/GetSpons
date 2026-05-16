"""
ai.py — AI content generation utilities for GetSpons.

This module is responsible for all LLM-powered content generation.
Currently it runs in MOCK mode so the rest of the application can be
developed and tested without a live API key.

#TODO: Replace mock with real Claude API call when API key is available
"""

from __future__ import annotations

import os
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# When MOCK_AI is True (the default until a real key is wired up) the
# function returns deterministic, realistic data built from the profile
# values instead of hitting the Claude API.
MOCK_AI: bool = os.getenv("MOCK_AI", "true").lower() != "false"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_mediakit_content(profile: dict[str, Any]) -> dict[str, Any]:
    """Generate AI-written media-kit copy for a creator's profile.

    Parameters
    ----------
    profile:
        A dictionary representing a creator profile.  Expected keys (all
        optional — the function degrades gracefully if any are absent):

        - ``full_name``      (str)   Creator's display name.
        - ``platform``       (str)   Primary platform, e.g. ``"YouTube"``.
        - ``handle``         (str)   @handle / channel name.
        - ``followers``      (int)   Total follower / subscriber count.
        - ``niche``          (str)   Content niche, e.g. ``"Tech & Gadgets"``.
        - ``engagement_rate``(float) Engagement rate as a percentage (0–100).
        - ``bio``            (str)   Short creator bio written by the user.
        - ``past_sponsors``  (list)  List of previous sponsor brand names.
        - ``pricing_min``    (int)   Minimum sponsorship price in USD.
        - ``pricing_max``    (int)   Maximum sponsorship price in USD.

    Returns
    -------
    dict
        A dictionary with the following keys:

        - ``headline``            (str)  Punchy one-liner for the media kit cover.
        - ``bio_short``           (str)  Polished 2-3 sentence creator bio.
        - ``key_stats``           (list) Four ``{"label": ..., "value": ...}``
                                         objects highlighting top metrics.
        - ``audience_description``(str)  One paragraph describing the audience.
        - ``content_style``       (str)  One paragraph on content tone & style.
        - ``why_partner``         (str)  Persuasive pitch to potential sponsors.
        - ``pricing_table``       (list) Sponsorship packages, each with
                                         ``{"package": ..., "deliverable": ...,
                                            "price": ...}``.
        - ``cta``                 (str)  Call-to-action closing line.

    Raises
    ------
    RuntimeError
        If the real Claude API is enabled (``MOCK_AI=false``) but the call
        fails for any reason.

    Examples
    --------
    >>> profile = {
    ...     "full_name": "Alex Rivera",
    ...     "platform": "YouTube",
    ...     "handle": "@alexreviews",
    ...     "followers": 250000,
    ...     "niche": "Tech & Gadgets",
    ...     "engagement_rate": 4.8,
    ...     "bio": "I review the latest tech so you don't have to.",
    ...     "past_sponsors": ["Squarespace", "NordVPN"],
    ...     "pricing_min": 1500,
    ...     "pricing_max": 5000,
    ... }
    >>> result = generate_mediakit_content(profile)
    >>> "headline" in result
    True
    """
    if MOCK_AI:
        return _mock_generate(profile)

    # ------------------------------------------------------------------
    # Real Claude API path (activated when MOCK_AI=false)
    # ------------------------------------------------------------------
    return _claude_generate(profile)  # pragma: no cover


# ---------------------------------------------------------------------------
# Mock implementation
# ---------------------------------------------------------------------------


def _mock_generate(profile: dict[str, Any]) -> dict[str, Any]:
    """Return realistic, profile-aware mock content without an API call.

    All values are constructed from the real profile data so that the mock
    response looks exactly like what the AI would produce for that creator.
    """
    # --- extract & normalise profile fields ----------------------------
    name: str = profile.get("full_name") or "Creator"
    platform: str = profile.get("platform") or "Social Media"
    handle: str = profile.get("handle") or ""
    followers: int = int(profile.get("followers") or 0)
    niche: str = profile.get("niche") or "Lifestyle"
    engagement: float = float(profile.get("engagement_rate") or 0.0)
    bio: str = profile.get("bio") or ""
    past_sponsors: list = profile.get("past_sponsors") or []
    pricing_min: int = int(profile.get("pricing_min") or 500)
    pricing_max: int = int(profile.get("pricing_max") or 2000)

    # Helpers
    followers_fmt: str = _format_followers(followers)
    mid_price: int = (pricing_min + pricing_max) // 2
    sponsor_line: str = (
        f"Previous brand partners include {', '.join(past_sponsors[:3])}."
        if past_sponsors
        else "Ready to build first-time brand partnerships."
    )

    # --- build each section -------------------------------------------

    headline: str = (
        f"Meet {name} — {platform}'s Leading Voice in {niche}"
    )

    bio_short: str = (
        f"{name} is a {niche} creator on {platform} "
        f"with {followers_fmt} engaged followers. "
        f"{bio.rstrip('.')}. "
        f"{sponsor_line}"
    )

    key_stats: list[dict[str, str]] = [
        {"label": "Followers / Subscribers", "value": followers_fmt},
        {"label": "Engagement Rate",         "value": f"{engagement:.1f}%"},
        {"label": "Primary Platform",        "value": platform},
        {"label": "Content Niche",           "value": niche},
    ]

    audience_description: str = (
        f"{name}'s audience on {platform} is primarily composed of "
        f"{niche.lower()} enthusiasts aged 18–35 who are highly active online. "
        f"With an engagement rate of {engagement:.1f}%, followers actively like, "
        f"comment, and share content — signalling a community that trusts "
        f"{name}'s recommendations and acts on them."
    )

    content_style: str = (
        f"{name} produces {niche.lower()} content that blends authenticity with "
        f"high production value. The {platform} channel ({handle}) is known for "
        f"in-depth analysis, honest opinions, and a conversational tone that "
        f"resonates strongly with its audience. Every piece of sponsored content "
        f"is seamlessly integrated to feel native rather than interruptive."
    )

    why_partner: str = (
        f"Partnering with {name} gives your brand direct access to "
        f"{followers_fmt} targeted {niche.lower()} consumers on {platform}. "
        f"An engagement rate of {engagement:.1f}% — well above the platform "
        f"average — means your message won't just be seen; it will be acted on. "
        f"{sponsor_line} "
        f"All sponsorships are crafted collaboratively to align with your brand "
        f"voice and campaign goals."
    )

    pricing_table: list[dict[str, str]] = [
        {
            "package":     "Starter",
            "deliverable": f"1 dedicated {platform} post / mention",
            "price":       f"₹{pricing_min:,}",
        },
        {
            "package":     "Growth",
            "deliverable": f"1 dedicated post + story / reel feature",
            "price":       f"₹{mid_price:,}",
        },
        {
            "package":     "Premium",
            "deliverable": f"Full campaign: post, story, newsletter mention & usage rights",
            "price":       f"₹{pricing_max:,}",
        },
    ]

    cta: str = (
        f"Ready to reach {followers_fmt} passionate {niche.lower()} fans? "
        f"Let's build something great together — get in touch with {name} today."
    )

    return {
        "headline":             headline,
        "bio_short":            bio_short,
        "key_stats":            key_stats,
        "audience_description": audience_description,
        "content_style":        content_style,
        "why_partner":          why_partner,
        "pricing_table":        pricing_table,
        "cta":                  cta,
    }


# ---------------------------------------------------------------------------
# Real Claude API implementation (stub — not yet active)
# ---------------------------------------------------------------------------


def _claude_generate(profile: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
    """Call the Anthropic Claude API to generate media-kit content.

    This function is intentionally left as a stub.  Wire it up once an
    ``ANTHROPIC_API_KEY`` is available in the environment.

    #TODO: Replace mock with real Claude API call when API key is available

    Parameters
    ----------
    profile:
        Same shape as described in :func:`generate_mediakit_content`.

    Returns
    -------
    dict
        Parsed JSON response from Claude matching the expected schema.
    """
    try:
        import anthropic  # noqa: PLC0415 — optional dependency
    except ImportError as exc:
        raise RuntimeError(
            "The 'anthropic' package is required for real AI generation. "
            "Install it with: pip install anthropic"
        ) from exc

    api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Set it or use MOCK_AI=true for development."
        )

    client = anthropic.Anthropic(api_key=api_key)

    prompt: str = _build_prompt(profile)

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    import json  # noqa: PLC0415
    raw: str = message.content[0].text
    return json.loads(raw)


def _build_prompt(profile: dict[str, Any]) -> str:
    """Construct the Claude prompt from a profile dictionary.

    Parameters
    ----------
    profile:
        Creator profile dictionary.

    Returns
    -------
    str
        A fully formatted prompt string ready to send to Claude.
    """
    return f"""
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
  Pricing Min:     ${profile.get('pricing_min', 0):,}
  Pricing Max:     ${profile.get('pricing_max', 0):,}
""".strip()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _format_followers(count: int) -> str:
    """Return a human-readable follower count string.

    Parameters
    ----------
    count:
        Raw follower integer.

    Returns
    -------
    str
        Examples: ``"1.2M"``, ``"850K"``, ``"9,500"``.
    """
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return f"{count:,}"
