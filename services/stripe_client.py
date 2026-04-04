"""
Stripe client wrapper for SpendGuard API.

Handles:
- Webhook signature verification
- Checkout session creation (free → paid upgrade)
- Overage usage reporting (metered billing)

All Stripe calls use the stripe Python SDK.
STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET from environment.
"""

from __future__ import annotations

import logging
import os

import stripe

logger = logging.getLogger(__name__)

# Configure Stripe SDK
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

# Plan mapping — Stripe price IDs set via env vars
PLAN_PRICES = {
    "pro": os.getenv("STRIPE_PRICE_PRO", ""),
    "growth": os.getenv("STRIPE_PRICE_GROWTH", ""),
}

PLAN_LIMITS = {
    "free": 1000,
    "pro": 10000,
    "growth": 100000,
}


def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    """
    Verify a Stripe webhook signature and return the parsed event.

    Args:
        payload: Raw request body bytes.
        sig_header: Value of the Stripe-Signature header.

    Returns:
        Parsed Stripe event dict.

    Raises:
        ValueError: If signature verification fails.
    """
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        return event
    except stripe.error.SignatureVerificationError as e:
        logger.warning("Stripe webhook signature verification failed: %s", e)
        raise ValueError(f"Invalid signature: {e}")


def create_checkout_session(
    plan: str,
    customer_email: str | None = None,
    success_url: str = "https://spendguardapi.com/?checkout=success",
    cancel_url: str = "https://spendguardapi.com/?checkout=cancel",
    metadata: dict | None = None,
) -> str:
    """
    Create a Stripe Checkout session for upgrading to a paid plan.

    Args:
        plan: "pro" or "growth".
        customer_email: Pre-fill the email field.
        success_url: Redirect URL after successful payment.
        cancel_url: Redirect URL if customer cancels.
        metadata: Optional metadata to attach to the subscription.

    Returns:
        Stripe Checkout URL.

    Raises:
        ValueError: If plan is invalid or price ID is not configured.
    """
    price_id = PLAN_PRICES.get(plan)
    if not price_id:
        raise ValueError(f"Invalid plan '{plan}' or price ID not configured. Set STRIPE_PRICE_{plan.upper()} env var.")

    session_params = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
    }

    if customer_email:
        session_params["customer_email"] = customer_email

    if metadata:
        session_params["subscription_data"] = {"metadata": metadata}

    session = stripe.checkout.Session.create(**session_params)
    logger.info("Checkout session created — plan=%s session_id=%s", plan, session.id)
    return session.url


def report_overage_usage(subscription_id: str, quantity: int = 1) -> None:
    """
    Report metered overage usage to Stripe.

    This creates a usage record on the subscription's metered item.
    Called after each check when overage_enabled=True and over the plan limit.

    Args:
        subscription_id: Stripe subscription ID.
        quantity: Number of overage checks to report (usually 1).
    """
    if not subscription_id:
        logger.warning("Cannot report overage — no subscription_id")
        return

    try:
        # Get the subscription to find the metered item
        subscription = stripe.Subscription.retrieve(subscription_id)
        for item in subscription["items"]["data"]:
            # Report usage on the first item (we only have one per subscription)
            stripe.SubscriptionItem.create_usage_record(
                item["id"],
                quantity=quantity,
                action="increment",
            )
            logger.info(
                "Overage usage reported — subscription=%s quantity=%d",
                subscription_id, quantity,
            )
            return
    except Exception as e:
        logger.error("Failed to report overage usage: %s", e)
