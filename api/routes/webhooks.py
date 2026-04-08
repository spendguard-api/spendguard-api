"""
Stripe webhook handler for SpendGuard API.

POST /v1/webhooks/stripe — Receives Stripe events and updates API key state.

Handles:
- customer.subscription.created → activate key, set plan
- customer.subscription.updated → update plan if changed
- customer.subscription.deleted → downgrade to free (D16-8, not deactivate)
- invoice.paid → reset billing period + reset overage_enabled (D16-7)
- invoice.payment_failed → log warning, do NOT deactivate

No standard auth — uses Stripe webhook signature verification instead.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

# Map Stripe product/price to our plan names
# These are checked against subscription metadata or price lookup
PLAN_MAP = {
    "pro": {"plan_name": "pro", "plan_limit": 10000},
    "growth": {"plan_name": "growth", "plan_limit": 100000},
}


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> JSONResponse:
    """
    Handle incoming Stripe webhook events.

    Verifies the webhook signature, then routes to the appropriate handler.
    Returns 200 to acknowledge receipt (Stripe retries on non-2xx).
    """
    request_id = getattr(request.state, "request_id", "unknown")

    # Read raw body for signature verification
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    if not sig_header:
        logger.warning("Stripe webhook missing signature — request_id=%s", request_id)
        raise HTTPException(status_code=400, detail={
            "error": {
                "code": "bad_request",
                "message": "Missing Stripe-Signature header.",
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })

    # Verify signature
    try:
        from services.stripe_client import verify_webhook_signature

        event = verify_webhook_signature(payload, sig_header)
    except ValueError as e:
        logger.warning("Stripe webhook signature invalid: %s", e)
        raise HTTPException(status_code=400, detail={
            "error": {
                "code": "bad_request",
                "message": "Invalid webhook signature.",
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })

    event_type = event.get("type", "")
    logger.info("Stripe webhook received — type=%s event_id=%s", event_type, event.get("id"))

    try:
        if event_type == "customer.subscription.created":
            await _handle_subscription_created(event)
        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(event)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(event)
        elif event_type == "invoice.paid":
            await _handle_invoice_paid(event)
        elif event_type == "invoice.payment_failed":
            await _handle_invoice_payment_failed(event)
        else:
            logger.debug("Unhandled Stripe event type: %s", event_type)
    except Exception as e:
        logger.error("Error processing Stripe event %s: %s", event_type, e)
        # Still return 200 so Stripe doesn't retry endlessly
        return JSONResponse(
            status_code=200,
            content={"received": True, "error": str(e)},
        )

    return JSONResponse(status_code=200, content={"received": True})


async def _handle_subscription_created(event: dict) -> None:
    """
    Activate key and set plan when a new subscription is created.

    Looks up the API key by the customer email or metadata.api_key_id.
    Sends an upgrade confirmation email after the row is updated (D024).
    """
    subscription = event["data"]["object"]
    customer_id = subscription.get("customer", "")
    metadata = subscription.get("metadata", {})
    api_key_id = metadata.get("api_key_id")

    # Determine plan from the subscription
    plan_info = _resolve_plan(subscription)

    from db.client import supabase

    if api_key_id:
        # Update by key ID from metadata
        supabase.table("api_keys").update({
            "active": True,
            "plan_name": plan_info["plan_name"],
            "plan_limit": plan_info["plan_limit"],
            "stripe_customer_id": customer_id,
            "stripe_subscription_id": subscription["id"],
            "billing_period_start": datetime.now(timezone.utc).isoformat(),
            "overage_enabled": False,
        }).eq("id", api_key_id).execute()
    else:
        # Try to find by stripe_customer_id
        supabase.table("api_keys").update({
            "active": True,
            "plan_name": plan_info["plan_name"],
            "plan_limit": plan_info["plan_limit"],
            "stripe_subscription_id": subscription["id"],
            "billing_period_start": datetime.now(timezone.utc).isoformat(),
            "overage_enabled": False,
        }).eq("stripe_customer_id", customer_id).execute()

    logger.info(
        "Subscription created — customer=%s plan=%s key_id=%s",
        customer_id, plan_info["plan_name"], api_key_id,
    )

    # Send upgrade confirmation email (D024). Wrapped in try/except so a failed
    # email never breaks the webhook — Stripe must always get a 200 back.
    try:
        await _send_upgrade_email_for_key(
            api_key_id=api_key_id,
            customer_id=customer_id,
            plan_name=plan_info["plan_name"],
            plan_limit=plan_info["plan_limit"],
        )
    except Exception as e:
        logger.error("Failed to send upgrade email after subscription created: %s", e)


async def _send_upgrade_email_for_key(
    api_key_id: str | None,
    customer_id: str,
    plan_name: str,
    plan_limit: int,
) -> None:
    """
    Look up the customer's email and name, then send the upgrade confirmation.

    Tries the api_key_id first (preferred — set in checkout metadata), then
    falls back to looking up by stripe_customer_id.
    """
    from db.client import supabase
    from services.email import send_upgrade_email

    row = None
    if api_key_id:
        result = (
            supabase.table("api_keys")
            .select("email, owner_name")
            .eq("id", api_key_id)
            .limit(1)
            .execute()
        )
        if result.data:
            row = result.data[0]

    if not row and customer_id:
        result = (
            supabase.table("api_keys")
            .select("email, owner_name")
            .eq("stripe_customer_id", customer_id)
            .limit(1)
            .execute()
        )
        if result.data:
            row = result.data[0]

    if not row:
        logger.warning(
            "Cannot send upgrade email — no matching api_keys row "
            "(api_key_id=%s, customer_id=%s)",
            api_key_id, customer_id,
        )
        return

    email = row.get("email")
    owner_name = row.get("owner_name") or "there"

    if not email:
        logger.warning("Cannot send upgrade email — api_keys row has no email")
        return

    await send_upgrade_email(
        to_email=email,
        owner_name=owner_name,
        plan_name=plan_name,
        plan_limit=plan_limit,
    )


async def _handle_subscription_updated(event: dict) -> None:
    """Update plan if the subscription plan changed."""
    subscription = event["data"]["object"]
    customer_id = subscription.get("customer", "")
    plan_info = _resolve_plan(subscription)

    from db.client import supabase

    supabase.table("api_keys").update({
        "plan_name": plan_info["plan_name"],
        "plan_limit": plan_info["plan_limit"],
    }).eq("stripe_customer_id", customer_id).execute()

    logger.info(
        "Subscription updated — customer=%s new_plan=%s",
        customer_id, plan_info["plan_name"],
    )


async def _handle_subscription_deleted(event: dict) -> None:
    """
    Downgrade to free tier when subscription is cancelled (D16-8).

    Does NOT deactivate the key — keeps access at the free tier level.
    """
    subscription = event["data"]["object"]
    customer_id = subscription.get("customer", "")

    from db.client import supabase

    supabase.table("api_keys").update({
        "plan_name": "free",
        "plan_limit": 1000,
        "stripe_subscription_id": None,
        "overage_enabled": False,
        "billing_period_start": datetime.now(timezone.utc).isoformat(),
    }).eq("stripe_customer_id", customer_id).execute()

    logger.info("Subscription deleted — customer=%s downgraded to free", customer_id)


async def _handle_invoice_paid(event: dict) -> None:
    """
    Reset billing period and overage on successful payment (D16-7).

    overage_enabled resets to false each period — customer must opt in again.
    """
    invoice = event["data"]["object"]
    customer_id = invoice.get("customer", "")
    subscription_id = invoice.get("subscription", "")

    if not subscription_id:
        logger.debug("Invoice paid without subscription — skipping (one-time charge?)")
        return

    from db.client import supabase

    supabase.table("api_keys").update({
        "billing_period_start": datetime.now(timezone.utc).isoformat(),
        "overage_enabled": False,
    }).eq("stripe_customer_id", customer_id).execute()

    logger.info(
        "Invoice paid — customer=%s billing period reset, overage disabled",
        customer_id,
    )


async def _handle_invoice_payment_failed(event: dict) -> None:
    """
    Log warning but do NOT deactivate the key.

    Stripe will retry failed payments. Only subscription.deleted should downgrade.
    """
    invoice = event["data"]["object"]
    customer_id = invoice.get("customer", "")
    logger.warning(
        "Invoice payment failed — customer=%s. Stripe will retry. No action taken.",
        customer_id,
    )


def _resolve_plan(subscription: dict) -> dict:
    """Resolve the plan name and limit from a Stripe subscription object."""
    metadata = subscription.get("metadata", {})

    # Check metadata first
    plan_name = metadata.get("plan")
    if plan_name and plan_name in PLAN_MAP:
        return PLAN_MAP[plan_name]

    # Default to pro if we can't determine
    return PLAN_MAP.get("pro", {"plan_name": "pro", "plan_limit": 10000})
