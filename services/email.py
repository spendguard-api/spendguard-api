"""
Email service for SpendGuard API using Resend.

Sends transactional emails:
- Welcome email on free tier signup (D023)
- Upgrade confirmation email on paid plan activation (D024)

Uses Resend HTTP API directly — no SDK needed.
RESEND_API_KEY from environment.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

PLAN_DISPLAY_NAMES = {
    "pro": "Pro",
    "growth": "Growth",
}

PLAN_PRICES_DISPLAY = {
    "pro": "$49/month",
    "growth": "$199/month",
}


def _get_resend_key() -> str:
    return os.getenv("RESEND_API_KEY", "")

def _get_from_email() -> str:
    return os.getenv("FROM_EMAIL", "SpendGuard <noreply@spendguardapi.com>")

def _get_billing_from_email() -> str:
    return os.getenv("BILLING_FROM_EMAIL", "SpendGuard Billing <billing@spendguardapi.com>")


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
    resend_key = _get_resend_key()
    if not resend_key:
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
        from_email = _get_from_email()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": from_email,
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


async def send_upgrade_email(
    to_email: str,
    owner_name: str,
    plan_name: str,
    plan_limit: int,
) -> bool:
    """
    Send a confirmation email after a paid plan is activated.

    Triggered by the Stripe customer.subscription.created webhook (D024).
    Free tier signups receive the welcome email instead — this function is
    only called for pro and growth tiers.

    Args:
        to_email: Customer's email address.
        owner_name: Customer's name.
        plan_name: "pro" or "growth".
        plan_limit: Monthly check limit for the plan (e.g. 10000, 100000).

    Returns:
        True if sent successfully, False on failure.
    """
    resend_key = _get_resend_key()
    if not resend_key:
        logger.warning("RESEND_API_KEY not set — skipping upgrade email to %s", to_email)
        return False

    plan_display = PLAN_DISPLAY_NAMES.get(plan_name, plan_name.title())
    plan_price = PLAN_PRICES_DISPLAY.get(plan_name, "")
    formatted_limit = f"{plan_limit:,}"

    now = datetime.now(timezone.utc)
    next_billing = now + timedelta(days=30)
    billing_date = now.strftime("%B %-d, %Y")
    next_billing_date = next_billing.strftime("%B %-d, %Y")

    subject = f"Your SpendGuard {plan_display} plan is active"
    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 560px; margin: 0 auto; padding: 40px 20px; color: #1e293b;">
      <h1 style="font-size: 22px; font-weight: 700; margin: 0 0 8px 0;">Your upgrade is complete</h1>
      <p style="color: #64748b; font-size: 15px; line-height: 1.6; margin: 0 0 24px 0;">Hi {owner_name}, thank you for upgrading to SpendGuard {plan_display}. Your new plan is now active and ready to use.</p>

      <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin: 24px 0;">
        <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
          <tr>
            <td style="padding: 6px 0; color: #64748b;">Plan</td>
            <td style="padding: 6px 0; text-align: right; font-weight: 600; color: #1e293b;">{plan_display}{(' — ' + plan_price) if plan_price else ''}</td>
          </tr>
          <tr>
            <td style="padding: 6px 0; color: #64748b;">Monthly limit</td>
            <td style="padding: 6px 0; text-align: right; font-weight: 600; color: #1e293b;">{formatted_limit} checks</td>
          </tr>
          <tr>
            <td style="padding: 6px 0; color: #64748b;">Activation date</td>
            <td style="padding: 6px 0; text-align: right; font-weight: 600; color: #1e293b;">{billing_date}</td>
          </tr>
          <tr>
            <td style="padding: 6px 0; color: #64748b;">Next billing date</td>
            <td style="padding: 6px 0; text-align: right; font-weight: 600; color: #1e293b;">{next_billing_date}</td>
          </tr>
        </table>
      </div>

      <p style="color: #64748b; font-size: 14px; line-height: 1.6;">Your existing API key works without any changes — no need to regenerate it. The new limits and features are already applied to your account.</p>

      <div style="margin-top: 28px; text-align: center;">
        <a href="https://spendguardapi.com/dashboard/" style="display: inline-block; background: #2563eb; color: white; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 600;">Open Dashboard</a>
      </div>

      <p style="color: #94a3b8; font-size: 13px; margin-top: 32px; line-height: 1.6;">You can manage your subscription, download invoices, or change your plan at any time from your dashboard. Questions about billing? Reply to this email and we'll help.</p>

      <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 32px 0 16px 0;">
      <p style="color: #94a3b8; font-size: 12px; margin: 0;">SpendGuard — Real-time authorization for AI agent financial actions.</p>
    </div>
    """

    try:
        from_email = _get_billing_from_email()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": from_email,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_body,
                },
            )

        if resp.status_code in (200, 201):
            logger.info("Upgrade email sent to %s — plan=%s", to_email, plan_name)
            return True
        else:
            logger.error("Resend API error (upgrade) — status=%d body=%s", resp.status_code, resp.text)
            return False

    except Exception as e:
        logger.error("Failed to send upgrade email to %s: %s", to_email, e)
        return False


async def send_cancellation_email(
    to_email: str,
    owner_name: str,
    plan_name: str,
    cancel_date_iso: str,
) -> bool:
    """
    Send a cancellation confirmation email when the user schedules a cancel (D025).

    This fires when the user clicks "Cancel subscription" on the dashboard and
    Stripe sets cancel_at_period_end=true. The plan remains active until the
    cancel date — this email confirms the scheduled cancellation and tells the
    user exactly when their access ends.

    Args:
        to_email: Customer's email address.
        owner_name: Customer's name.
        plan_name: "pro" or "growth".
        cancel_date_iso: ISO timestamp when the plan cancels (current_period_end).

    Returns:
        True if sent successfully, False on failure.
    """
    resend_key = _get_resend_key()
    if not resend_key:
        logger.warning("RESEND_API_KEY not set — skipping cancellation email to %s", to_email)
        return False

    plan_display = PLAN_DISPLAY_NAMES.get(plan_name, plan_name.title())

    try:
        cancel_dt = datetime.fromisoformat(cancel_date_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        cancel_dt = datetime.now(timezone.utc) + timedelta(days=30)
    formatted_cancel_date = cancel_dt.strftime("%B %-d, %Y")

    subject = f"Your SpendGuard {plan_display} cancellation is confirmed"
    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 560px; margin: 0 auto; padding: 40px 20px; color: #1e293b;">
      <h1 style="font-size: 22px; font-weight: 700; margin: 0 0 8px 0;">Your cancellation is confirmed</h1>
      <p style="color: #64748b; font-size: 15px; line-height: 1.6; margin: 0 0 24px 0;">Hi {owner_name}, your SpendGuard {plan_display} plan is scheduled to cancel. This email confirms the details below.</p>

      <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin: 24px 0;">
        <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
          <tr>
            <td style="padding: 6px 0; color: #64748b;">Current plan</td>
            <td style="padding: 6px 0; text-align: right; font-weight: 600; color: #1e293b;">{plan_display}</td>
          </tr>
          <tr>
            <td style="padding: 6px 0; color: #64748b;">Access ends on</td>
            <td style="padding: 6px 0; text-align: right; font-weight: 600; color: #1e293b;">{formatted_cancel_date}</td>
          </tr>
          <tr>
            <td style="padding: 6px 0; color: #64748b;">After cancellation</td>
            <td style="padding: 6px 0; text-align: right; font-weight: 600; color: #1e293b;">Free plan — 1,000 checks/month</td>
          </tr>
        </table>
      </div>

      <p style="color: #64748b; font-size: 14px; line-height: 1.6;">You will retain full access to your {plan_display} plan until {formatted_cancel_date}. After that date, your account will automatically revert to the free plan with a limit of 1,000 checks per month. Your API key and policies will remain intact — only the plan limit changes.</p>

      <p style="color: #64748b; font-size: 14px; line-height: 1.6; margin-top: 16px;">Changed your mind? You can reactivate your subscription any time before {formatted_cancel_date} from your dashboard. After that date, you will need to purchase a new subscription.</p>

      <div style="margin-top: 28px; text-align: center;">
        <a href="https://spendguardapi.com/dashboard/" style="display: inline-block; background: #2563eb; color: white; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 600;">Open Dashboard</a>
      </div>

      <p style="color: #94a3b8; font-size: 13px; margin-top: 32px; line-height: 1.6;">Questions about your cancellation or billing? Reply to this email and we will help.</p>

      <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 32px 0 16px 0;">
      <p style="color: #94a3b8; font-size: 12px; margin: 0;">SpendGuard — Real-time authorization for AI agent financial actions.</p>
    </div>
    """

    try:
        from_email = _get_billing_from_email()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": from_email,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_body,
                },
            )

        if resp.status_code in (200, 201):
            logger.info("Cancellation email sent to %s — plan=%s", to_email, plan_name)
            return True
        else:
            logger.error("Resend API error (cancellation) — status=%d body=%s", resp.status_code, resp.text)
            return False

    except Exception as e:
        logger.error("Failed to send cancellation email to %s: %s", to_email, e)
        return False
