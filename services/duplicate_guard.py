"""
Duplicate guard service for SpendGuard API.

Computes SHA-256 fingerprint of: f"{agent_id}|{action_type}|{str(amount)}|{counterparty}"
Checks the duplicate_guard table for a matching fingerprint within the TTL window.
If found: returns block with reason_code=duplicate_action_detected.
If not found: inserts the fingerprint and TTL, then proceeds to rule engine.

Default TTL: 5 minutes (configurable per policy via duplicate_guard rule window_minutes).

In simulation mode: read-only evaluation — fingerprint is never written.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_MINUTES: int = 5


@dataclass
class DuplicateCheckResult:
    """Result of a duplicate guard check."""

    is_duplicate: bool
    fingerprint: str
    message: str | None = None


def compute_fingerprint(
    agent_id: str,
    action_type: str,
    amount: float,
    counterparty: str,
) -> str:
    """
    Compute the SHA-256 fingerprint for duplicate detection.

    Uses pipe-delimited concatenation per D014 in DECISIONS.md:
    SHA-256(f"{agent_id}|{action_type}|{str(amount)}|{counterparty}")

    Args:
        agent_id: The agent making the request.
        action_type: The financial action type (refund/credit/discount/spend).
        amount: The dollar amount.
        counterparty: The customer or vendor identifier.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    raw = f"{agent_id}|{action_type}|{str(amount)}|{counterparty}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def check_duplicate(
    agent_id: str,
    action_type: str,
    amount: float,
    counterparty: str,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    simulation_mode: bool = False,
    supabase_client: Any | None = None,
) -> DuplicateCheckResult:
    """
    Check whether this action is a duplicate of a recent submission.

    Steps:
      1. Compute fingerprint from the four key fields.
      2. Query duplicate_guard table for matching fingerprint where expires_at > now.
      3. If found → return is_duplicate=True.
      4. If not found AND not simulation_mode → INSERT the fingerprint with TTL.
      5. Return is_duplicate=False.

    Args:
        agent_id: Agent identifier.
        action_type: Financial action type.
        amount: Dollar amount.
        counterparty: Customer or vendor ID.
        window_minutes: TTL window in minutes (default 5, configurable per policy).
        simulation_mode: If True, never write to the database (side-effect free).
        supabase_client: Supabase client instance. If None, import the singleton.

    Returns:
        DuplicateCheckResult with is_duplicate flag and fingerprint.
    """
    fingerprint = compute_fingerprint(agent_id, action_type, amount, counterparty)

    if supabase_client is None:
        from db.client import supabase
        supabase_client = supabase

    now_utc = datetime.now(timezone.utc).isoformat()

    # Check for an existing non-expired fingerprint
    try:
        result = (
            supabase_client.table("duplicate_guard")
            .select("id, fingerprint, expires_at")
            .eq("fingerprint", fingerprint)
            .gt("expires_at", now_utc)
            .limit(1)
            .execute()
        )

        if result.data and len(result.data) > 0:
            logger.info(
                "Duplicate detected — fingerprint=%s agent=%s",
                fingerprint[:16],
                agent_id,
            )
            return DuplicateCheckResult(
                is_duplicate=True,
                fingerprint=fingerprint,
                message=(
                    f"This exact action was already submitted within the last "
                    f"{window_minutes} minutes."
                ),
            )
    except Exception as e:
        # If the DB query fails, log the error but do NOT block the request.
        # Failing open is safer than blocking legitimate transactions.
        logger.error("Duplicate guard DB read failed: %s", e)

    # Not a duplicate — insert fingerprint if not in simulation mode
    if not simulation_mode:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=window_minutes)
        try:
            supabase_client.table("duplicate_guard").insert({
                "fingerprint": fingerprint,
                "agent_id": agent_id,
                "expires_at": expires_at.isoformat(),
            }).execute()
            logger.debug(
                "Fingerprint inserted — fingerprint=%s expires=%s",
                fingerprint[:16],
                expires_at.isoformat(),
            )
        except Exception as e:
            # If insert fails (e.g. unique constraint on retry), log but proceed.
            logger.warning("Duplicate guard DB insert failed: %s", e)

    return DuplicateCheckResult(
        is_duplicate=False,
        fingerprint=fingerprint,
    )


def get_window_minutes_from_policy(rules: list[dict]) -> int:
    """
    Extract the duplicate_guard window_minutes from a policy's rules.

    Searches the rules list for a rule with rule_type='duplicate_guard'
    and reads 'window_minutes' from its parameters.

    Args:
        rules: List of rule dicts from the policy.

    Returns:
        The configured window_minutes, or DEFAULT_WINDOW_MINUTES if not found.
    """
    for rule in rules:
        if rule.get("rule_type") == "duplicate_guard":
            params = rule.get("parameters", {})
            return params.get("window_minutes", DEFAULT_WINDOW_MINUTES)
    return DEFAULT_WINDOW_MINUTES
