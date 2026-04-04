"""
Usage metering and plan quota enforcement for SpendGuard API.

- emit_usage_event: logs a billable event after every successful check
- get_usage_count: counts events for a key within the current billing period
- check_plan_quota: returns whether a key is within its monthly limit

The usage_events table is append-only. Plan limits are stored on the api_keys table.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def emit_usage_event(api_key_id: str, event_type: str = "check") -> None:
    """
    Record a billable usage event. Called after every successful check.
    Fire-and-forget — failures are logged but never block the response.
    """
    try:
        from db.client import supabase

        supabase.table("usage_events").insert({
            "id": str(uuid.uuid4()),
            "api_key_id": api_key_id,
            "event_type": event_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        logger.debug("Usage event recorded — key_id=%s type=%s", api_key_id, event_type)
    except Exception as e:
        logger.error("Failed to emit usage event — key_id=%s error=%s", api_key_id, e)


async def get_usage_count(api_key_id: str, period_start: str) -> int:
    """
    Count usage events for a key since the billing period start.

    Args:
        api_key_id: The API key's UUID.
        period_start: ISO 8601 timestamp for the start of the billing period.

    Returns:
        Number of usage events since period_start.
    """
    try:
        from db.client import supabase

        result = (
            supabase.table("usage_events")
            .select("id", count="exact")
            .eq("api_key_id", api_key_id)
            .gte("created_at", period_start)
            .execute()
        )
        return result.count if result.count is not None else 0
    except Exception as e:
        logger.error("Failed to count usage — key_id=%s error=%s", api_key_id, e)
        return 0


async def check_plan_quota(api_key_id: str) -> tuple[bool, int, int]:
    """
    Check if a key is within its monthly plan quota.

    Returns:
        (within_limit, current_usage, plan_limit)
        - within_limit: True if usage < plan_limit
        - current_usage: number of checks used this period
        - plan_limit: maximum checks allowed per period
    """
    try:
        from db.client import supabase

        # Fetch plan info from api_keys
        result = (
            supabase.table("api_keys")
            .select("plan_limit, billing_period_start")
            .eq("id", api_key_id)
            .limit(1)
            .execute()
        )

        if not result.data:
            logger.warning("Key not found for quota check — key_id=%s", api_key_id)
            return True, 0, 10000  # Fail open with default limit

        row = result.data[0]
        plan_limit = row.get("plan_limit") or 10000
        period_start = row.get("billing_period_start")

        if not period_start:
            # No billing period set — use beginning of current month
            now = datetime.now(timezone.utc)
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

        current_usage = await get_usage_count(api_key_id, period_start)
        within_limit = current_usage < plan_limit

        if not within_limit:
            logger.info(
                "Quota exceeded — key_id=%s usage=%d limit=%d",
                api_key_id, current_usage, plan_limit,
            )

        return within_limit, current_usage, plan_limit

    except Exception as e:
        logger.error("Quota check failed — key_id=%s error=%s", api_key_id, e)
        return True, 0, 10000  # Fail open on error
