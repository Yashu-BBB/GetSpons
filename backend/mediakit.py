"""
mediakit.py — Media kit generation router for GetSpons.

Exposes:
    POST /mediakit/generate
        Validates the caller's JWT, fetches their creator profile from
        Supabase, runs AI content generation, and returns the result as JSON.

    POST /mediakit/pdf
        Same auth + data flow as /generate, but returns the media kit
        rendered as a downloadable PDF file.
"""

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response

from database import supabase, supabase_admin
from ai import generate_mediakit_content
from pdf import generate_pdf

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_user_id(authorization: str) -> str:
    """Validate the Bearer token and return the Supabase user_id.

    Raises
    ------
    HTTPException 401
        If the token is missing, malformed, or rejected.
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


def _fetch_profile(user_id: str) -> dict:
    """Fetch the creator profile row for *user_id*.

    Raises
    ------
    HTTPException 404
        If no profile row is found or the row is empty.
    """
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

    return profile


# ---------------------------------------------------------------------------
# POST /mediakit/generate  — returns JSON
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
    user_id = _resolve_user_id(authorization)
    profile = _fetch_profile(user_id)

    try:
        mediakit: dict = generate_mediakit_content(profile)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Media kit generation failed: {exc}",
        ) from exc

    return mediakit


# ---------------------------------------------------------------------------
# POST /mediakit/pdf  — returns a downloadable PDF
# ---------------------------------------------------------------------------


@router.post("/pdf")
def generate_mediakit_pdf(authorization: str = Header(...)):
    """Generate and return the media kit as a downloadable PDF.

    Flow
    ----
    1. Validate the Bearer token → ``user_id``.
    2. Fetch the creator's profile from Supabase.
    3. Run AI content generation (same logic as ``/generate``).
    4. Merge profile fields with AI content into a single template dict.
    5. Render ``templates/mediakit.html`` and convert to PDF bytes.
    6. Return the PDF with ``Content-Disposition: attachment``.

    Parameters
    ----------
    authorization:
        HTTP ``Authorization`` header in the format ``Bearer <jwt>``.

    Returns
    -------
    fastapi.responses.Response
        ``application/pdf`` response with the filename
        ``<creator_name>_media_kit.pdf``.

    Raises
    ------
    HTTPException 401
        If the token is missing, malformed, or rejected.
    HTTPException 404
        If no profile exists for the user.
    HTTPException 500
        If AI generation or PDF rendering fails.
    """
    # ── Step 1: auth ────────────────────────────────────────────────
    user_id = _resolve_user_id(authorization)

    # ── Step 2: profile ─────────────────────────────────────────────
    profile = _fetch_profile(user_id)

    # ── Step 3: AI content generation ───────────────────────────────
    try:
        mediakit: dict = generate_mediakit_content(profile)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Media kit generation failed: {exc}",
        ) from exc

    # ── Step 4: build template context ──────────────────────────────
    # Pull the fields the template needs from profile, with safe fallbacks.
    template_data: dict = {
        # Profile-sourced fields
        "creator_name":  profile.get("full_name") or profile.get("name", "Creator"),
        "platform":      profile.get("platform", ""),
        "handle":        profile.get("handle", ""),
        # AI-generated fields (all present if generate_mediakit_content succeeded)
        **mediakit,
    }

    # ── Step 5: render to PDF ────────────────────────────────────────
    try:
        pdf_bytes: bytes = generate_pdf(template_data)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"PDF rendering failed: {exc}",
        ) from exc

    # ── Step 6: stream back as downloadable file ─────────────────────
    safe_name = template_data["creator_name"].replace(" ", "_")
    filename = f"{safe_name}_media_kit.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )