"""
Email service for SpendGuard API using Resend.

Sends transactional emails:
- Welcome email on free tier signup (D023)

Uses Resend HTTP API directly — no SDK needed.
RESEND_API_KEY from environment.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "SpendGuard <onboarding@resend.dev>")


async def send_welcome_email(to_email: str, owner_name: str, api_key_preview: str) -> bool:
    """
    Send a welcome email after free tier signup.

    Args:
        to_email: Customer's email address.
        owner_name: Customer's name.
        api_key_preview: First 20 chars of the API key for reference (NOT the full key).

    Returns:
        True if sent successfully, False on failure.
    """
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping welcome email to %s", to_email)
        return False

    subject = "Welcome to SpendGuard — your API key is ready"
    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 560px; margin: 0 auto; padding: 40px 20px;">
      <h1 style="font-size: 24px; color: #1e293b; margin-bottom: 8px;">Welcome to SpendGuard, {owner_name}!</h1>
      <p style="color: #64748b; font-size: 15px; line-height: 1.6;">Your free API key is active and ready to use. You have <strong>1,000 checks per month</strong> on the free tier.</p>

      <div style="background: #f1f5f9; border-radius: 8px; padding: 16px; margin: 24px 0; font-family: monospace; font-size: 13px; color: #334155;">
        Your key starts with: <strong>{api_key_preview}...</strong>
      </div>

      <h2 style="font-size: 18px; color: #1e293b; margin-top: 32px;">Get started in 5 minutes</h2>
      <ol style="color: #64748b; font-size: 14px; line-height: 2;">
        <li><a href="https://spendguard.mintlify.app/guides/quickstart" style="color: #2563eb;">Follow the Quickstart Guide</a></li>
        <li>Create your first policy</li>
        <li>Run your first check</li>
      </ol>

      <div style="margin-top: 32px; padding-top: 24px; border-top: 1px solid #e2e8f0;">
        <a href="https://spendguard.mintlify.app" style="display: inline-block; background: #2563eb; color: white; padding: 10px 24px; border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 600;">Read the Docs</a>
      </div>

      <p style="color: #94a3b8; font-size: 12px; margin-top: 32px;">SpendGuard — Real-time authorization for AI agent financial actions.</p>
    </div>
    """

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": FROM_EMAIL,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_body,
                },
            )

        if resp.status_code in (200, 201):
            logger.info("Welcome email sent to %s", to_email)
            return True
        else:
            logger.error("Resend API error — status=%d body=%s", resp.status_code, resp.text)
            return False

    except Exception as e:
        logger.error("Failed to send welcome email to %s: %s", to_email, e)
        return False
