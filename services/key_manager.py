"""
API key generation and storage for SpendGuard API.

Generates secure API keys with the sg_live_ prefix.
Only the SHA-256 hash is stored — the raw key is returned once and never persisted.

Key format: sg_live_ + 32 random hex chars (74 chars total)
ID format:  key_ + 16 random hex chars
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def generate_api_key() -> tuple[str, str]:
    """
    Generate a new API key.

    Returns:
        Tuple of (raw_key, sha256_hash).
        Raw key format: sg_live_ + 32 random hex chars.
        Only the hash should be stored. The raw key is shown once.
    """
    raw = f"sg_live_{secrets.token_hex(32)}"
    hashed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, hashed


async def create_api_key(
    name: str,
    rate_limit_rpm: int = 100,
    supabase_client: Any | None = None,
) -> dict[str, Any]:
    """
    Create a new API key and store the hash in Supabase.

    Args:
        name: Human-readable name for this key.
        rate_limit_rpm: Requests per minute limit.
        supabase_client: Supabase client (for testing injection).

    Returns:
        Dict with key_id, name, api_key (raw, shown once), rate_limit_rpm, created_at.
    """
    if supabase_client is None:
        from db.client import supabase
        supabase_client = supabase

    raw, hashed = generate_api_key()
    key_id = f"key_{secrets.token_hex(8)}"
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "key_hash": hashed,
        "name": name,
        "active": True,
        "rate_limit_rpm": rate_limit_rpm,
    }

    supabase_client.table("api_keys").insert(record).execute()

    # Log key_id only — NEVER log the raw key
    logger.info("API key created — key_id=%s name=%s", key_id, name)

    return {
        "key_id": key_id,
        "name": name,
        "api_key": raw,  # Shown once, never stored
        "rate_limit_rpm": rate_limit_rpm,
        "created_at": now,
    }
