"""
Persistent rate limiting for SpendGuard API.

Supabase-backed sliding window rate limiter. Survives Railway restarts.

Two modes:
- Authenticated: per API key, default 100 RPM (configurable via api_keys.rate_limit_rpm)
- Unauthenticated: per IP, fixed 10 RPM (demo simulate only)

Returns 429 with standard headers on breach:
- Retry-After
- X-RateLimit-Limit
- X-RateLimit-Remaining
- X-RateLimit-Reset
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# Default limits
DEFAULT_AUTH_RPM = 100
DEFAULT_DEMO_RPM = 10
WINDOW_SECONDS = 60


def _get_supabase():
    """Lazy import of the Supabase client."""
    from db.client import supabase
    return supabase


def _record_and_count(limiter_key: str, limit: int) -> tuple[bool, int, int, int]:
    """
    Record a request and count events in the window.

    Inserts a row, counts recent events, and cleans up old ones.
    Returns (allowed, remaining, limit, reset_timestamp).

    On database error: fails open (allows the request).
    """
    now = time.time()
    reset_at = int(now + WINDOW_SECONDS)

    try:
        supabase = _get_supabase()

        # Insert this request event
        supabase.table("rate_limit_events").insert({
            "limiter_key": limiter_key,
        }).execute()

        # Count events in the last 60 seconds
        cutoff = datetime.fromtimestamp(now - WINDOW_SECONDS, tz=timezone.utc).isoformat()
        count_result = (
            supabase.table("rate_limit_events")
            .select("id", count="exact")
            .eq("limiter_key", limiter_key)
            .gt("created_at", cutoff)
            .execute()
        )
        current_count = count_result.count if count_result.count is not None else len(count_result.data)

        # Cleanup: delete events older than 120 seconds to prevent bloat
        cleanup_cutoff = datetime.fromtimestamp(now - 120, tz=timezone.utc).isoformat()
        try:
            supabase.table("rate_limit_events").delete().eq(
                "limiter_key", limiter_key
            ).lt("created_at", cleanup_cutoff).execute()
        except Exception as e:
            logger.warning("Rate limit cleanup failed (non-critical): %s", e)

        remaining = max(0, limit - current_count)

        if current_count > limit:
            return False, 0, limit, reset_at

        return True, remaining, limit, reset_at

    except Exception as e:
        # Fail open — allow the request if DB is down
        logger.error("Rate limit DB error (failing open): %s", e)
        return True, limit, limit, reset_at


async def check_rate_limit_auth(request: Request) -> None:
    """
    Rate limit check for authenticated requests.

    Uses the API key ID from request.state (set by auth middleware).
    Limit is from api_keys.rate_limit_rpm (default 100).
    """
    key_id = getattr(request.state, "api_key_id", None)
    if not key_id:
        return

    limit = getattr(request.state, "rate_limit_rpm", DEFAULT_AUTH_RPM)
    allowed, remaining, rate_limit, reset_at = _record_and_count(f"key:{key_id}", limit)

    if not allowed:
        request_id = getattr(request.state, "request_id", "unknown")
        retry_after = max(1, reset_at - int(time.time()))
        logger.warning(
            "Rate limit exceeded — key_id=%s limit=%d request_id=%s",
            key_id, limit, request_id,
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": f"Too many requests. Limit is {limit} per minute. Retry after {retry_after} seconds.",
                    "request_id": request_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(rate_limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_at),
            },
        )


async def check_rate_limit_demo(request: Request) -> None:
    """
    Rate limit check for unauthenticated (demo) requests.

    Uses client IP address. Fixed limit of 10 RPM.
    """
    client_ip = request.client.host if request.client else "unknown"
    limit = DEFAULT_DEMO_RPM

    allowed, remaining, rate_limit, reset_at = _record_and_count(f"ip:{client_ip}", limit)

    if not allowed:
        request_id = getattr(request.state, "request_id", "unknown")
        retry_after = max(1, reset_at - int(time.time()))
        logger.warning(
            "Demo rate limit exceeded — ip=%s request_id=%s",
            client_ip, request_id,
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": f"Too many requests. Demo limit is {limit} per minute. Retry after {retry_after} seconds.",
                    "request_id": request_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(rate_limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_at),
            },
        )
