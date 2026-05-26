"""
resend_email.py — Centralised email-sending utility for GetSpons.

All modules that need to send email import from here. Handles:
  - Sending HTML emails via the Resend API
  - Injecting a 1×1 tracking pixel into outbound emails
  - Building mailto: payloads for the frontend to open the native email app

Configuration (all in .env)
----------------------------
    RESEND_API_KEY     — Resend API key (set to placeholder to disable sending)
    RESEND_FROM_EMAIL  — "From" address, e.g. noreply@getspons.com
    APP_BASE_URL       — Public base URL for tracking pixel, e.g. https://api.getspons.com

If RESEND_API_KEY is missing or a placeholder the send is skipped and a
warning is logged — the rest of the application continues normally.
"""

from __future__ import annotations

import os
from typing import Optional

import requests

from logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_API_KEY: str = os.getenv("RESEND_API_KEY", "")
_FROM:    str = os.getenv("RESEND_FROM_EMAIL", "noreply@getspons.com")
_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")

_RESEND_ENDPOINT = "https://api.resend.com/emails"

# Placeholder sentinel values — treat as "not configured"
_PLACEHOLDER_PREFIXES = ("placeholder", "your_", "xxx", "")


def _is_configured() -> bool:
    key = _API_KEY.strip().lower()
    return bool(key) and not any(key.startswith(p) for p in _PLACEHOLDER_PREFIXES)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def send_email(
    to: str | list[str],
    subject: str,
    html_body: str,
    pixel_id: Optional[str] = None,
    cc: Optional[list[str]] = None,
) -> bool:
    """Send an HTML email via Resend.

    Parameters
    ----------
    to:
        Recipient email address(es).
    subject:
        Email subject line.
    html_body:
        Full HTML body of the email.
    pixel_id:
        If provided, a 1×1 transparent PNG tracking pixel is injected
        at the bottom of the HTML body before the closing </body> tag.
        The pixel URL is: {APP_BASE_URL}/api/pitches/track/{pixel_id}
    cc:
        Optional list of CC recipients.

    Returns
    -------
    bool
        True if email was sent successfully, False if skipped or failed.
    """
    if not _is_configured():
        log.warning(
            "Resend API key not configured — email skipped | to=%s | subject=%s",
            to, subject,
        )
        return False

    # Inject tracking pixel
    if pixel_id:
        pixel_url = f"{_BASE_URL}/api/pitches/track/{pixel_id}"
        pixel_tag = (
            f'<img src="{pixel_url}" width="1" height="1" '
            f'style="display:none;" alt="" />'
        )
        if "</body>" in html_body:
            html_body = html_body.replace("</body>", f"{pixel_tag}</body>")
        else:
            html_body += pixel_tag

    payload: dict = {
        "from":    _FROM,
        "to":      [to] if isinstance(to, str) else to,
        "subject": subject,
        "html":    html_body,
    }
    if cc:
        payload["cc"] = cc

    try:
        resp = requests.post(
            _RESEND_ENDPOINT,
            json=payload,
            headers={
                "Authorization": f"Bearer {_API_KEY}",
                "Content-Type":  "application/json",
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            log.info("Email sent successfully | to=%s | subject=%s", to, subject)
            return True
        else:
            log.warning(
                "Resend API error | status=%d | body=%s", resp.status_code, resp.text
            )
            return False
    except Exception as exc:
        log.error("Email send failed | to=%s | reason=%s", to, exc)
        return False


def build_mailto_payload(
    to: str,
    subject: str,
    plain_body: str,
) -> dict:
    """Build a mailto: link payload for the frontend.

    The frontend opens: mailto:<to>?subject=<subject>&body=<body>

    Parameters
    ----------
    to:
        Recipient email.
    subject:
        Email subject.
    plain_body:
        Plain-text version of the email body (mailto: does not support HTML).

    Returns
    -------
    dict
        { "to": str, "subject": str, "body": str, "mailto": str }
        The ``mailto`` key is a ready-to-use href string.
    """
    from urllib.parse import quote

    mailto = (
        f"mailto:{quote(to)}"
        f"?subject={quote(subject)}"
        f"&body={quote(plain_body)}"
    )
    return {
        "to":      to,
        "subject": subject,
        "body":    plain_body,
        "mailto":  mailto,
    }


# ---------------------------------------------------------------------------
# Pre-built email templates
# ---------------------------------------------------------------------------


def send_pitch_accepted_email(creator_email: str, creator_name: str, brand_name: str) -> bool:
    """Send a congratulations email to a creator when their pitch is accepted."""
    subject = f"🎉 Your pitch was accepted by {brand_name}!"
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:auto;padding:32px;">
      <h2 style="color:#7C3AED;">Congratulations, {creator_name}! 🎉</h2>
      <p style="font-size:16px;color:#374151;">
        Great news — <strong>{brand_name}</strong> has <strong>accepted your pitch</strong>
        on GetSpons!
      </p>
      <p style="font-size:16px;color:#374151;">
        Head over to your GetSpons inbox to start the conversation and discuss
        campaign details.
      </p>
      <a href="{_BASE_URL}/pitches"
         style="display:inline-block;margin-top:16px;padding:12px 24px;
                background:#7C3AED;color:#fff;border-radius:8px;
                text-decoration:none;font-weight:600;">
        Open My Pitches
      </a>
      <p style="margin-top:32px;font-size:13px;color:#9CA3AF;">
        — The GetSpons Team
      </p>
    </div>
    """
    return send_email(creator_email, subject, html)


def send_pitch_rejected_email(creator_email: str, creator_name: str, brand_name: str) -> bool:
    """Send a polite rejection email to a creator."""
    subject = f"Update on your pitch to {brand_name}"
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:auto;padding:32px;">
      <h2 style="color:#374151;">Hi {creator_name},</h2>
      <p style="font-size:16px;color:#374151;">
        Thank you for your interest in partnering with <strong>{brand_name}</strong>.
        After careful review, they have decided not to move forward with this collaboration
        at this time.
      </p>
      <p style="font-size:16px;color:#374151;">
        Don't be discouraged — there are hundreds of brands on GetSpons looking for
        creators just like you. Keep pitching!
      </p>
      <a href="{_BASE_URL}/brands"
         style="display:inline-block;margin-top:16px;padding:12px 24px;
                background:#7C3AED;color:#fff;border-radius:8px;
                text-decoration:none;font-weight:600;">
        Discover More Brands
      </a>
      <p style="margin-top:32px;font-size:13px;color:#9CA3AF;">
        — The GetSpons Team
      </p>
    </div>
    """
    return send_email(creator_email, subject, html)


def send_outreach_email(
    creator_email: str,
    creator_name: str,
    brand_name: str,
    subject: str,
    body_html: str,
) -> bool:
    """Send a brand-to-creator outreach email."""
    wrapped = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:auto;padding:32px;">
      {body_html}
      <hr style="margin-top:32px;border:none;border-top:1px solid #E5E7EB;" />
      <p style="font-size:12px;color:#9CA3AF;">
        This message was sent via <strong>GetSpons</strong> — the creator sponsorship platform.
        <a href="{_BASE_URL}">Visit GetSpons</a>
      </p>
    </div>
    """
    return send_email(creator_email, subject, wrapped)
