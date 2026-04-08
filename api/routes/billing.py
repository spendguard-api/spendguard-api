"""
Billing routes for SpendGuard API.

POST /v1/billing/enable-overage — Enable pay-per-check overage for paid tiers (D022).
POST /v1/checkout              — Create a Stripe Checkout session for upgrading.
POST /v1/billing/cancel        — Schedule subscription cancellation at period end (D025).
POST /v1/billing/reactivate    — Undo a scheduled cancellation (D025).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])


# ============================================================
# Enable Overage
# ============================================================


class OverageResponse(BaseModel):
    """Response for overage enable/disable."""

    overage_enabled: bool
    plan_name: str
    message: str


@router.post("/billing/enable-overage", response_model=OverageResponse)
async def enable_overage(request: Request) -> OverageResponse:
    """
    Enable pay-per-check overage for the current billing period.

    Paid tiers only ($0.005/check beyond plan limit).
    Free tier returns 403 — must upgrade first.
    Resets to disabled on each new billing period (invoice.paid webhook).
    """
    request_id = getattr(request.state, "request_id", "unknown")
    timestamp = datetime.now(timezone.utc).isoformat()
    api_key_id = getattr(request.state, "api_key_id", None)

    if not api_key_id:
        raise HTTPException(status_code=401, detail={
            "error": {
                "code": "unauthorized",
                "message": "Authentication required.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    try:
        from db.client import supabase

        # Get current plan
        result = (
            supabase.table("api_keys")
            .select("plan_name, overage_enabled")
            .eq("id", api_key_id)
            .limit(1)
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail={
                "error": {
                    "code": "not_found",
                    "message": "API key not found.",
                    "request_id": request_id,
                    "timestamp": timestamp,
                }
            })

        row = result.data[0]
        plan_name = row.get("plan_name", "free")

        # Free tier cannot enable overage
        if plan_name == "free":
            raise HTTPException(status_code=403, detail={
                "error": {
                    "code": "upgrade_required",
                    "message": "Overage is not available on the free tier. Upgrade to Pro ($49/month) or Growth ($199/month) to enable pay-per-check overage.",
                    "request_id": request_id,
                    "timestamp": timestamp,
                }
            })

        # Enable overage
        supabase.table("api_keys").update({
            "overage_enabled": True,
        }).eq("id", api_key_id).execute()

        logger.info("Overage enabled — key_id=%s plan=%s", api_key_id, plan_name)

        return OverageResponse(
            overage_enabled=True,
            plan_name=plan_name,
            message="Overage enabled for this billing period. Each check beyond your plan limit will be billed at $0.005. Overage resets when your next billing period starts.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to enable overage: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "internal_error",
                "message": "Failed to enable overage.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })


# ============================================================
# Checkout
# ============================================================


class CheckoutRequest(BaseModel):
    """Request body for POST /v1/checkout."""

    plan: str = Field(
        ...,
        pattern="^(pro|growth)$",
        description="Plan to upgrade to: 'pro' or 'growth'",
    )

    model_config = {"extra": "forbid"}


class CheckoutResponse(BaseModel):
    """Response body for POST /v1/checkout."""

    checkout_url: str
    plan: str
    message: str


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(request: Request, body: CheckoutRequest) -> CheckoutResponse:
    """
    Create a Stripe Checkout session to upgrade from free to a paid plan.

    Returns a Stripe-hosted checkout URL. Redirect the user there to complete payment.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    timestamp = datetime.now(timezone.utc).isoformat()
    api_key_id = getattr(request.state, "api_key_id", None)

    # Get customer email for pre-filling checkout
    customer_email = None
    if api_key_id:
        try:
            from db.client import supabase

            result = (
                supabase.table("api_keys")
                .select("email")
                .eq("id", api_key_id)
                .limit(1)
                .execute()
            )
            if result.data:
                customer_email = result.data[0].get("email")
        except Exception as e:
            logger.warning("Could not fetch email for checkout: %s", e)

    try:
        from services.stripe_client import create_checkout_session

        checkout_url = create_checkout_session(
            plan=body.plan,
            customer_email=customer_email,
            metadata={"api_key_id": api_key_id} if api_key_id else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={
            "error": {
                "code": "bad_request",
                "message": str(e),
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })
    except Exception as e:
        logger.error("Failed to create checkout session: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "internal_error",
                "message": "Failed to create checkout session.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    return CheckoutResponse(
        checkout_url=checkout_url,
        plan=body.plan,
        message=f"Redirect to the checkout URL to complete your {body.plan} plan upgrade.",
    )


# ============================================================
# Cancel / Reactivate Subscription (D025)
# ============================================================


class CancelResponse(BaseModel):
    """Response for cancel/reactivate subscription."""

    cancel_at_period_end: bool
    current_period_end: str | None
    plan_name: str
    message: str


def _fetch_key_row(api_key_id: str) -> dict | None:
    """Fetch the api_keys row for a given id. Returns None if not found."""
    from db.client import supabase

    result = (
        supabase.table("api_keys")
        .select("plan_name, stripe_subscription_id, cancel_at_period_end, current_period_end")
        .eq("id", api_key_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


@router.post("/billing/cancel", response_model=CancelResponse)
async def cancel_subscription(request: Request) -> CancelResponse:
    """
    Schedule the current subscription to cancel at the end of the billing period.

    The user retains full paid access until the current_period_end timestamp.
    At that point, Stripe fires customer.subscription.deleted and the webhook
    handler drops the account to the free tier.

    Returns 403 on the free tier (nothing to cancel). Returns 409 if the
    subscription is already scheduled to cancel.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    timestamp = datetime.now(timezone.utc).isoformat()
    api_key_id = getattr(request.state, "api_key_id", None)

    if not api_key_id:
        raise HTTPException(status_code=401, detail={
            "error": {
                "code": "unauthorized",
                "message": "Authentication required.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    row = _fetch_key_row(api_key_id)
    if not row:
        raise HTTPException(status_code=404, detail={
            "error": {
                "code": "not_found",
                "message": "API key not found.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    plan_name = row.get("plan_name", "free")
    subscription_id = row.get("stripe_subscription_id")
    already_scheduled = row.get("cancel_at_period_end", False)

    if plan_name == "free" or not subscription_id:
        raise HTTPException(status_code=403, detail={
            "error": {
                "code": "no_active_subscription",
                "message": "You do not have an active paid subscription to cancel.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    if already_scheduled:
        raise HTTPException(status_code=409, detail={
            "error": {
                "code": "already_scheduled",
                "message": "Your subscription is already scheduled to cancel.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    # Ask Stripe to schedule the cancellation
    try:
        from services.stripe_client import cancel_subscription_at_period_end

        result = cancel_subscription_at_period_end(subscription_id)
    except ValueError as e:
        logger.error("Failed to cancel subscription: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "stripe_error",
                "message": "Failed to cancel subscription with Stripe.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    # Convert Stripe's unix timestamp to an ISO string for our DB and response
    period_end_unix = result.get("current_period_end")
    period_end_iso = None
    if period_end_unix:
        period_end_iso = datetime.fromtimestamp(period_end_unix, tz=timezone.utc).isoformat()

    # Update our row immediately so the dashboard reflects the cancellation
    # without waiting for the webhook. The webhook will still fire but is
    # now a no-op for state — it remains as a safety net for out-of-band
    # cancellations (e.g. from the Stripe dashboard directly).
    try:
        from db.client import supabase

        supabase.table("api_keys").update({
            "cancel_at_period_end": True,
            "current_period_end": period_end_iso,
        }).eq("id", api_key_id).execute()
    except Exception as e:
        logger.error("Failed to update api_keys after cancel: %s", e)

    logger.info(
        "Subscription scheduled to cancel — key_id=%s plan=%s period_end=%s",
        api_key_id, plan_name, period_end_iso,
    )

    # Send the confirmation email directly from the endpoint so we don't
    # depend on the webhook's transition detection (which races with the
    # DB update above). Wrapped in try/except so a failed email never
    # blocks the cancellation itself.
    try:
        from db.client import supabase
        from services.email import send_cancellation_email

        profile_result = (
            supabase.table("api_keys")
            .select("email, owner_name")
            .eq("id", api_key_id)
            .limit(1)
            .execute()
        )
        if profile_result.data and period_end_iso:
            profile = profile_result.data[0]
            email = profile.get("email")
            owner_name = profile.get("owner_name") or "there"
            if email:
                await send_cancellation_email(
                    to_email=email,
                    owner_name=owner_name,
                    plan_name=plan_name,
                    cancel_date_iso=period_end_iso,
                )
    except Exception as e:
        logger.error("Failed to send cancellation email from endpoint: %s", e)

    return CancelResponse(
        cancel_at_period_end=True,
        current_period_end=period_end_iso,
        plan_name=plan_name,
        message=f"Your {plan_name} plan is scheduled to cancel. You will retain access until {period_end_iso}.",
    )


@router.post("/billing/reactivate", response_model=CancelResponse)
async def reactivate_subscription_endpoint(request: Request) -> CancelResponse:
    """
    Undo a scheduled cancellation while still within the current billing period.

    Only works if cancel_at_period_end is currently true AND the subscription
    has not yet been cancelled by Stripe. After the period ends, the user must
    purchase a new subscription through the normal upgrade flow.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    timestamp = datetime.now(timezone.utc).isoformat()
    api_key_id = getattr(request.state, "api_key_id", None)

    if not api_key_id:
        raise HTTPException(status_code=401, detail={
            "error": {
                "code": "unauthorized",
                "message": "Authentication required.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    row = _fetch_key_row(api_key_id)
    if not row:
        raise HTTPException(status_code=404, detail={
            "error": {
                "code": "not_found",
                "message": "API key not found.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    plan_name = row.get("plan_name", "free")
    subscription_id = row.get("stripe_subscription_id")
    is_scheduled = row.get("cancel_at_period_end", False)

    if plan_name == "free" or not subscription_id:
        raise HTTPException(status_code=403, detail={
            "error": {
                "code": "no_active_subscription",
                "message": "You do not have an active subscription.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    if not is_scheduled:
        raise HTTPException(status_code=409, detail={
            "error": {
                "code": "not_scheduled",
                "message": "Your subscription is not scheduled to cancel.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    try:
        from services.stripe_client import reactivate_subscription as stripe_reactivate

        result = stripe_reactivate(subscription_id)
    except ValueError as e:
        logger.error("Failed to reactivate subscription: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "stripe_error",
                "message": "Failed to reactivate subscription with Stripe.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    period_end_unix = result.get("current_period_end")
    period_end_iso = None
    if period_end_unix:
        period_end_iso = datetime.fromtimestamp(period_end_unix, tz=timezone.utc).isoformat()

    try:
        from db.client import supabase

        supabase.table("api_keys").update({
            "cancel_at_period_end": False,
            "current_period_end": period_end_iso,
        }).eq("id", api_key_id).execute()
    except Exception as e:
        logger.error("Failed to update api_keys after reactivate: %s", e)

    logger.info(
        "Subscription reactivated — key_id=%s plan=%s",
        api_key_id, plan_name,
    )

    return CancelResponse(
        cancel_at_period_end=False,
        current_period_end=period_end_iso,
        plan_name=plan_name,
        message=f"Your {plan_name} plan has been reactivated.",
    )
