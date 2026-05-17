"""
pdf.py — PDF generation for GetSpons media kits.

Uses Jinja2 to render templates/mediakit.html with creator data,
then converts the rendered HTML to PDF bytes via WeasyPrint.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML


# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

# Resolve templates/ relative to this file's parent directory (backend/).
# Adjust BASE_DIR if your folder layout differs.
BASE_DIR = Path(__file__).resolve().parent.parent   # project root
TEMPLATES_DIR = BASE_DIR / "templates"


# ---------------------------------------------------------------------------
# Jinja2 environment (module-level singleton for efficiency)
# ---------------------------------------------------------------------------

_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_pdf(data: dict) -> bytes:
    """Render the media-kit HTML template and convert it to PDF bytes.

    Parameters
    ----------
    data : dict
        Combined dict of creator profile fields **and** AI-generated content.
        Expected keys (all strings unless noted):

        From creator profile
        --------------------
        creator_name   – display name, e.g. "Jane Smith"
        platform       – primary platform, e.g. "Instagram"
        handle         – @handle, e.g. "@janesmith"

        From AI generation
        ------------------
        headline           – punchy one-liner
        bio_short          – 2-3 sentence bio
        key_stats          – list[dict] with keys ``label`` and ``value``
        audience_description – paragraph about the audience
        content_style        – paragraph about content approach
        why_partner          – paragraph on brand fit
        pricing_table        – list[dict] with keys ``package``,
                               ``deliverable``, ``price``
        cta                  – call-to-action string

    Returns
    -------
    bytes
        Raw PDF bytes, ready to stream directly as an HTTP response.

    Raises
    ------
    KeyError
        If a required template variable is missing from *data*.
    jinja2.TemplateNotFound
        If ``templates/mediakit.html`` cannot be located.
    weasyprint.html.HTMLParseError
        If the rendered HTML is malformed (should not happen in normal use).
    """
    # ── 1. Load and render the Jinja2 template ──────────────────────
    template = _jinja_env.get_template("mediakit.html")
    rendered_html: str = template.render(**data)

    # ── 2. Convert rendered HTML → PDF via WeasyPrint ───────────────
    #   base_url tells WeasyPrint where to resolve relative asset paths
    #   (e.g. inline images or fonts you may add later).
    pdf_bytes: bytes = (
        HTML(string=rendered_html, base_url=str(TEMPLATES_DIR))
        .write_pdf()
    )

    return pdf_bytes