"""
API key management routes for SpendGuard API.

POST /v1/keys — Create a new API key. Requires X-Admin-Key header.
               Returns the raw key exactly once — only the hash is stored.

This endpoint is NOT behind the standard X-API-Key auth middleware.
It uses its own admin key check via the ADMIN_API_KEY env var.
"""

from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from services.key_manager import create_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["keys"])


class KeyCreateRequest(BaseModel):
    """Request body for POST /v1/keys."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable name for this API key",
    )
    rate_limit_rpm: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Requests per minute limit",
    )

    model_config = {"extra": "forbid"}


class KeyCreateResponse(BaseModel):
    """Response body for POST /v1/keys."""

    key_id: str
    name: str
    api_key: str  # Raw key — shown once, never stored
    rate_limit_rpm: int
    created_at: str


@router.post("/keys", response_model=KeyCreateResponse, status_code=201)
async def create_key(
    request: Request,
    body: KeyCreateRequest,
    x_admin_key: str = Header(..., alias="X-Admin-Key"),
) -> KeyCreateResponse:
    """
    Create a new API key.

    Requires the X-Admin-Key header matching the ADMIN_API_KEY env var.
    Returns the raw API key exactly once — it is never stored.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    timestamp = datetime.now(timezone.utc).isoformat()

    # Verify admin key
    admin_key = os.environ.get("ADMIN_API_KEY", "")
    if not admin_key or not hmac.compare_digest(x_admin_key, admin_key):
        logger.warning("Invalid admin key attempt — request_id=%s", request_id)
        raise HTTPException(status_code=401, detail={
            "error": {
                "code": "unauthorized",
                "message": "Invalid or missing admin key.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    try:
        result = await create_api_key(
            name=body.name,
            rate_limit_rpm=body.rate_limit_rpm,
        )
    except Exception as e:
        logger.error("Failed to create API key: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "internal_error",
                "message": "Failed to create API key.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    # Log key_id only — NEVER the raw key
    logger.info("API key created via endpoint — key_id=%s name=%s", result["key_id"], result["name"])

    return KeyCreateResponse(**result)
