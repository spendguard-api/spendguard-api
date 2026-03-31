"""
API key validation for SpendGuard API.

Reads the X-API-Key header, hashes the key using SHA-256,
looks up the hash in the api_keys table via Supabase,
and rejects requests with missing or inactive keys.

NEVER logs raw API keys — only key_id.

Used as a FastAPI dependency on protected routes.
Public routes (health, simulate demo) skip this.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


@dataclass
class AuthenticatedKey:
    """Result of a successful API key validation."""

    key_id: str
    name: str
    rate_limit_rpm: int


def hash_api_key(raw_key: str) -> str:
    """Compute SHA-256 hash of a raw API key for lookup."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


async def require_api_key(request: Request) -> AuthenticatedKey:
    """
    FastAPI dependency that validates the X-API-Key header.

    Flow:
    1. Read X-API-Key header
    2. If missing → 401 unauthorized
    3. Hash the key with SHA-256
    4. Look up hash in api_keys table
    5. If not found → 401 unauthorized
    6. If found but active=False → 401 api_key_inactive
    7. Attach key_id and rate_limit_rpm to request.state

    Returns:
        AuthenticatedKey with key_id, name, and rate_limit_rpm.

    Raises:
        HTTPException 401 if key is missing, invalid, or inactive.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    timestamp = datetime.now(timezone.utc).isoformat()

    # 1. Read header
    raw_key = request.headers.get("X-API-Key")
    if not raw_key:
        logger.warning("Request missing X-API-Key header — request_id=%s", request_id)
        raise HTTPException(status_code=401, detail={
            "error": {
                "code": "unauthorized",
                "message": "Missing API key. Provide your key in the X-API-Key header.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    # 2. Hash the key
    key_hash = hash_api_key(raw_key)

    # 3. Look up in api_keys table
    try:
        from db.client import supabase
        result = (
            supabase.table("api_keys")
            .select("id, key_hash, name, active, rate_limit_rpm")
            .eq("key_hash", key_hash)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.error("API key lookup failed: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "internal_error",
                "message": "Failed to validate API key.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    # 4. Not found
    if not result.data or len(result.data) == 0:
        logger.warning("Invalid API key attempted — hash=%s... request_id=%s", key_hash[:8], request_id)
        raise HTTPException(status_code=401, detail={
            "error": {
                "code": "unauthorized",
                "message": "Invalid API key. Check your key and try again.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    row = result.data[0]

    # 5. Inactive key
    if not row.get("active", False):
        key_id = row.get("id", "unknown")
        logger.warning("Inactive API key used — key_id=%s request_id=%s", key_id, request_id)
        raise HTTPException(status_code=401, detail={
            "error": {
                "code": "api_key_inactive",
                "message": "This API key is inactive. Contact support to reactivate.",
                "request_id": request_id,
                "timestamp": timestamp,
            }
        })

    # 6. Valid — attach to request state
    key_id = str(row["id"])
    auth = AuthenticatedKey(
        key_id=key_id,
        name=row.get("name", ""),
        rate_limit_rpm=row.get("rate_limit_rpm", 100),
    )
    request.state.api_key_id = key_id
    request.state.rate_limit_rpm = auth.rate_limit_rpm

    logger.debug("Authenticated — key_id=%s request_id=%s", key_id, request_id)
    return auth
