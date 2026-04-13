"""
Free tier signup route for SpendGuard API.

POST /v1/signup — Create a free API key with name + email only.
No credit card required. Returns the raw key exactly once.

Rate limited to 3 signups per hour per IP (D023).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from services.key_manager import create_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["signup"])


class SignupRequest(BaseModel):
    """Request body for POST /v1/signup."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Your name",
    )
    email: EmailStr = Field(
        ...,
        description="Your email address",
    )

    model_config = {"extra": "forbid"}


class SignupResponse(BaseModel):
    """Response body for POST /v1/signup."""

    key_id: str
    name: str
    email: str
    api_key: str  # Raw key — shown once, never stored
    plan_name: str
    plan_limit: int
    message: str
    created_at: str


# In-memory signup rate limiter (per IP, 3/hour)
# For production, this should use the Supabase-backed rate limiter
_signup_attempts: dict[str, list[float]] = {}
SIGNUP_RATE_LIMIT = 3
SIGNUP_WINDOW_SECONDS = 3600  # 1 hour


def _check_signup_rate_limit(ip: str) -> bool:
    """Check if this IP has exceeded the signup rate limit. Returns True if allowed."""
    import time

    now = time.time()
    attempts = _signup_attempts.get(ip, [])
    # Remove attempts older than the window
    attempts = [t for t in attempts if now - t < SIGNUP_WINDOW_SECONDS]
    _signup_attempts[ip] = attempts

    if len(attempts) >= SIGNUP_RATE_LIMIT:
        return False

    attempts.append(now)
    _signup_attempts[ip] = attempts
    return True


@router.post("/signup", response_model=SignupResponse, status_code=201)
async def signup(request: Request, body: SignupRequest) -> SignupResponse:
    """
    Create a free SpendGuard API key.

    No credit card required. Returns the raw key exactly once.
    Free tier includes 1,000 checks per month.
    Rate limited to 3 signups per hour per IP.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    timestamp = datetime.now(timezone.utc).isoformat()

    # Rate limit check
    client_ip = request.client.host if request.client else "unknown"
    if not _check_signup_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail={
            "error": {
                "code": "rate_limit_exceeded",
                "message": "Too many signup attempts. Maximum 3 per hour. Please try again later.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    # Check for duplicate email
    try:
        from db.client import supabase

        existing = (
            supabase.table("api_keys")
            .select("id")
            .eq("email", body.email)
            .limit(1)
            .execute()
        )
        if existing.data and len(existing.data) > 0:
            raise HTTPException(status_code=409, detail={
                "error": {
                    "code": "email_already_registered",
                    "message": "An API key already exists for this email. Contact support if you need help.",
                    "request_id": request_id,
                    "timestamp": timestamp,
                }
            })
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Email duplicate check failed: %s", e)
        raise HTTPException(status_code=503, detail={
            "error": {
                "code": "internal_error",
                "message": "Unable to verify email availability. Please try again in a moment.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    # Create the API key with free plan
    try:
        result = await create_api_key(
            name=body.name,
            rate_limit_rpm=100,
        )
    except Exception as e:
        logger.error("Failed to create signup key: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "internal_error",
                "message": "Failed to create API key. Please try again.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    # Update the key with free plan info + email + name
    try:
        from db.client import supabase

        supabase.table("api_keys").update({
            "plan_name": "free",
            "plan_limit": 1000,
            "email": body.email,
            "owner_name": body.name,
            "billing_period_start": datetime.now(timezone.utc).isoformat(),
        }).eq("id", result["key_id"]).execute()
    except Exception as e:
        logger.error("Failed to update key with plan info: %s", e)

    # Send welcome email (fire-and-forget)
    try:
        from services.email import send_welcome_email

        raw_key = result["api_key"]
        await send_welcome_email(
            to_email=body.email,
            owner_name=body.name,
            api_key_preview=raw_key[:20],
        )
    except Exception as e:
        logger.error("Failed to send welcome email: %s", e)

    logger.info("Free signup — key_id=%s email=%s", result["key_id"], body.email)

    return SignupResponse(
        key_id=result["key_id"],
        name=body.name,
        email=body.email,
        api_key=result["api_key"],
        plan_name="free",
        plan_limit=1000,
        message="Your free API key is ready. You have 1,000 checks per month. Copy your key now — you won't see it again.",
        created_at=result["created_at"],
    )
