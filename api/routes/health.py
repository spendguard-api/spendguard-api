"""
Health check route for SpendGuard API.

GET /health — public, no authentication required.
Returns: { "status": "ok", "version": "1.0.0", "timestamp": "<UTC ISO 8601>" }
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Health check")
async def health() -> dict:
    """
    Returns service health status.
    No authentication required.
    """
    return {
        "status": "ok",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

