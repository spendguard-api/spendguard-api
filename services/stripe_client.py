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
    success_url: str | None = None,
    cancel_url: str = "https://spendguardapi.com/?checkout=cancel",
    metadata: dict | None = None,
) -> str:
    """
    Create a Stripe Checkout session for upgrading to a paid plan.

    Args:
        plan: "pro" or "growth".
        customer_email: Pre-fill the email field.
        success_url: Redirect URL after successful payment. Defaults to dashboard
            with ?upgraded={plan} so the dashboard can show a confirmation banner.
        cancel_url: Redirect URL if customer cancels.
        metadata: Optional metadata to attach to the subscription. The plan name
            is automatically merged in so the webhook can resolve the correct tier.

    Returns:
        Stripe Checkout URL.

    Raises:
        ValueError: If plan is invalid or price ID is not configured.
    """
    price_id = PLAN_PRICES.get(plan)
    if not price_id:
        raise ValueError(f"Invalid plan '{plan}' or price ID not configured. Set STRIPE_PRICE_{plan.upper()} env var.")

    if success_url is None:
        success_url = f"https://spendguardapi.com/dashboard/?upgraded={plan}&session_id={{CHECKOUT_SESSION_ID}}"

    # Always include the plan in subscription metadata so the webhook handler
    # can resolve the correct tier (D023 fix — previously every upgrade defaulted to pro).
    subscription_metadata = {"plan": plan}
    if metadata:
        subscription_metadata.update(metadata)

    session_params = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "subscription_data": {"metadata": subscription_metadata},
    }

    if customer_email:
        session_params["customer_email"] = customer_email

    session = stripe.checkout.Session.create(**session_params)
    logger.info("Checkout session created — plan=%s session_id=%s", plan, session.id)
    return session.url


def change_subscription_plan(subscription_id: str, new_plan: str) -> dict:
    """
    Switch an existing subscription from one plan to another (D026).

    Behavior:
    - The subscription ID stays the same — no second subscription is created.
    - billing_cycle_anchor='now' resets the billing cycle so the user gets a
      fresh 30 days of the new plan starting today.
    - proration_behavior='always_invoice' charges the difference immediately
      (full new plan price minus credit for unused old plan time).
    - If the subscription was previously scheduled to cancel at period end,
      modifying it implicitly un-schedules the cancellation.

    Args:
        subscription_id: Stripe subscription ID (starts with "sub_").
        new_plan: "pro" or "growth".

    Returns:
        Dict with the modified subscription's plan, period_end, and item id.

    Raises:
        ValueError: If subscription cannot be retrieved/modified or plan is invalid.
    """
    if not subscription_id:
        raise ValueError("subscription_id is required")

    new_price_id = PLAN_PRICES.get(new_plan)
    if not new_price_id:
        raise ValueError(f"Invalid plan '{new_plan}' or price ID not configured")

    try:
        # Fetch the existing subscription so we know which item to swap
        subscription = stripe.Subscription.retrieve(subscription_id)
        items = subscription.get("items", {}).get("data", [])
        if not items:
            raise ValueError(f"Subscription {subscription_id} has no items")

        # Replace the price on the first (and normally only) item
        first_item = items[0]
        existing_item_id = first_item["id"]
        existing_price_id = first_item.get("price", {}).get("id")

        if existing_price_id == new_price_id:
            # Same plan — no-op (caller should have checked, but be defensive)
            raise ValueError("Subscription is already on this plan")

        updated = stripe.Subscription.modify(
            subscription_id,
            items=[{"id": existing_item_id, "price": new_price_id}],
            proration_behavior="always_invoice",
            billing_cycle_anchor="now",
            metadata={"plan": new_plan},
            cancel_at_period_end=False,  # Un-schedule any pending cancellation
        )

        period_end_unix = updated.get("current_period_end")
        logger.info(
            "Subscription plan changed — id=%s new_plan=%s period_end=%s",
            subscription_id, new_plan, period_end_unix,
        )

        return {
            "subscription_id": subscription_id,
            "new_plan": new_plan,
            "current_period_end": period_end_unix,
            "cancel_at_period_end": False,
        }

    except stripe.error.StripeError as e:
        logger.error("Failed to change plan for %s: %s", subscription_id, e)
        raise ValueError(f"Failed to change subscription plan: {e}")


def cancel_subscription_at_period_end(subscription_id: str) -> dict:
    """
    Schedule a Stripe subscription to cancel at the end of the current period.

    The subscription remains active (and the user keeps their paid plan) until
    the current billing period ends. At that point Stripe fires
    customer.subscription.deleted and our webhook drops them to the free tier.

    Args:
        subscription_id: Stripe subscription ID (starts with "sub_").

    Returns:
        Dict with "current_period_end" (unix timestamp) and "cancel_at_period_end" (bool).

    Raises:
        ValueError: If the subscription cannot be found or updated.
    """
    if not subscription_id:
        raise ValueError("subscription_id is required")

    try:
        subscription = stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True,
        )
        logger.info(
            "Subscription scheduled to cancel — id=%s period_end=%s",
            subscription_id, subscription.get("current_period_end"),
        )
        return {
            "current_period_end": subscription.get("current_period_end"),
            "cancel_at_period_end": subscription.get("cancel_at_period_end", True),
        }
    except stripe.error.StripeError as e:
        logger.error("Failed to cancel subscription %s: %s", subscription_id, e)
        raise ValueError(f"Failed to cancel subscription: {e}")


def reactivate_subscription(subscription_id: str) -> dict:
    """
    Undo a scheduled cancellation, reactivating the subscription.

    Only works while the subscription is still in the current paid period
    (i.e. before Stripe has actually cancelled it). After cancellation has
    taken effect, the user must purchase a new subscription.

    Args:
        subscription_id: Stripe subscription ID.

    Returns:
        Dict with "current_period_end" and "cancel_at_period_end" (should be False).

    Raises:
        ValueError: If the subscription cannot be found or updated.
    """
    if not subscription_id:
        raise ValueError("subscription_id is required")

    try:
        subscription = stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=False,
        )
        logger.info("Subscription reactivated — id=%s", subscription_id)
        return {
            "current_period_end": subscription.get("current_period_end"),
            "cancel_at_period_end": subscription.get("cancel_at_period_end", False),
        }
    except stripe.error.StripeError as e:
        logger.error("Failed to reactivate subscription %s: %s", subscription_id, e)
        raise ValueError(f"Failed to reactivate subscription: {e}")


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
