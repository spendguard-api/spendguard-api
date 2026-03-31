"""
Rate limiting for SpendGuard API.

In-memory sliding window rate limiter.

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
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# Default limits (from CLAUDE.md and .env)
DEFAULT_AUTH_RPM = 100
DEFAULT_DEMO_RPM = 10
WINDOW_SECONDS = 60


class RateLimiter:
    """In-memory sliding window rate limiter."""

    def __init__(self) -> None:
        # key → list of request timestamps (epoch seconds)
        self._requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str, limit: int) -> tuple[bool, int, int, int]:
        """
        Check if a request is within the rate limit.

        Args:
            key: The rate limit key (API key ID or IP address).
            limit: Maximum requests per minute.

        Returns:
            Tuple of (allowed, remaining, limit, reset_timestamp).
        """
        now = time.time()
        window_start = now - WINDOW_SECONDS

        # Prune old timestamps
        self._requests[key] = [
            ts for ts in self._requests[key] if ts > window_start
        ]

        current_count = len(self._requests[key])
        remaining = max(0, limit - current_count)

        # Reset time = earliest timestamp + window, or now + window if empty
        if self._requests[key]:
            reset_at = int(self._requests[key][0] + WINDOW_SECONDS)
        else:
            reset_at = int(now + WINDOW_SECONDS)

        if current_count >= limit:
            return False, 0, limit, reset_at

        # Record this request
        self._requests[key].append(now)
        remaining = max(0, limit - current_count - 1)

        return True, remaining, limit, reset_at

    def reset(self) -> None:
        """Clear all rate limit state. Used in testing."""
        self._requests.clear()


# Global rate limiter instance
_limiter = RateLimiter()


def get_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    return _limiter


async def check_rate_limit_auth(request: Request) -> None:
    """
    Rate limit check for authenticated requests.

    Uses the API key ID from request.state (set by auth middleware).
    Limit is from api_keys.rate_limit_rpm (default 100).

    Raises HTTPException 429 if rate limit exceeded.
    """
    key_id = getattr(request.state, "api_key_id", None)
    if not key_id:
        return  # No auth = skip (handled by demo limiter)

    limit = getattr(request.state, "rate_limit_rpm", DEFAULT_AUTH_RPM)
    allowed, remaining, rate_limit, reset_at = _limiter.check(f"key:{key_id}", limit)

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

    Raises HTTPException 429 if rate limit exceeded.
    """
    # Get client IP
    client_ip = request.client.host if request.client else "unknown"
    limit = DEFAULT_DEMO_RPM

    allowed, remaining, rate_limit, reset_at = _limiter.check(f"ip:{client_ip}", limit)

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
