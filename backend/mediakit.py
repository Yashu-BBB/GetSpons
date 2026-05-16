"""
mediakit.py — Media kit generation router for GetSpons.

Exposes:
    POST /mediakit/generate
        Validates the caller's JWT, fetches their creator profile from
        Supabase, runs AI content generation, and returns the result.
"""

from fastapi import APIRouter, Header, HTTPException
from database import supabase, supabase_admin
from ai import generate_mediakit_content

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /mediakit/generate
# ---------------------------------------------------------------------------


@router.post("/generate")
def generate_mediakit(authorization: str = Header(...)):
    """Generate an AI-written media kit for the authenticated creator.

    Flow
    ----
    1. Extract the Bearer token from the ``Authorization`` header.
    2. Validate the token with Supabase Auth to obtain the ``user_id``.
    3. Fetch the creator's profile row from the ``profiles`` table.
    4. Pass the profile dict to ``generate_mediakit_content``.
    5. Return the generated media-kit JSON to the caller.

    Parameters
    ----------
    authorization:
        HTTP ``Authorization`` header in the format ``Bearer <jwt>``.

    Returns
    -------
    dict
        Generated media-kit content with keys: ``headline``, ``bio_short``,
        ``key_stats``, ``audience_description``, ``content_style``,
        ``why_partner``, ``pricing_table``, ``cta``.

    Raises
    ------
    HTTPException 401
        If the token is missing, malformed, or rejected by Supabase Auth.
    HTTPException 404
        If no profile row exists for the authenticated user.
    HTTPException 500
        If AI generation fails for any unexpected reason.
    """
    # ------------------------------------------------------------------
    # Step 1 — Validate token & resolve user_id
    # ------------------------------------------------------------------
    try:
        token: str = authorization.replace("Bearer ", "").strip()
        if not token:
            raise ValueError("Empty token")
        user = supabase.auth.get_user(token)
        user_id: str = user.user.id
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid or expired token: {exc}",
        ) from exc

    # ------------------------------------------------------------------
    # Step 2 — Fetch creator profile from Supabase
    # ------------------------------------------------------------------
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
        # Supabase raises when .single() finds no row
        raise HTTPException(
            status_code=404,
            detail=(
                "No profile found for this user. "
                "Please complete your creator profile first."
            ),
        ) from exc

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile data is empty. Please complete your creator profile first.",
        )

    # ------------------------------------------------------------------
    # Step 3 — Generate media-kit content
    # ------------------------------------------------------------------
    try:
        mediakit: dict = generate_mediakit_content(profile)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Media kit generation failed: {exc}",
        ) from exc

    return mediakit
