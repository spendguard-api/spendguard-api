"""
Billing routes for SpendGuard API.

POST /v1/billing/enable-overage — Enable pay-per-check overage for paid tiers (D022).
POST /v1/checkout              — Create a Stripe Checkout session for upgrading.
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
