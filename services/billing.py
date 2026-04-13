"""
Usage metering and plan quota enforcement for SpendGuard API.

- emit_usage_event: logs a billable event after every successful check
- get_usage_count: counts events for a key within the current billing period
- check_plan_quota: returns whether a key is within its monthly limit (D022)

The usage_events table is append-only. Plan limits are stored on the api_keys table.
Overage: if overage_enabled=True and over limit, checks are allowed and billed at $0.005.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

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


async def check_plan_quota(api_key_id: str) -> dict[str, Any]:
    """
    Check if a key is within its monthly plan quota (D022).

    Returns dict with:
        - within_limit: True if usage < plan_limit OR overage is enabled
        - current_usage: number of checks used this period
        - plan_limit: maximum checks allowed per period
        - plan_name: free, pro, or growth
        - overage_enabled: whether overage billing is active
        - is_overage: True if currently in overage territory
        - stripe_subscription_id: for reporting overage to Stripe
    """
    default_result = {
        "within_limit": False,
        "current_usage": 0,
        "plan_limit": 1000,
        "plan_name": "free",
        "overage_enabled": False,
        "is_overage": False,
        "stripe_subscription_id": None,
    }

    try:
        from db.client import supabase

        # Fetch plan info from api_keys
        result = (
            supabase.table("api_keys")
            .select("plan_limit, plan_name, billing_period_start, overage_enabled, stripe_subscription_id")
            .eq("id", api_key_id)
            .limit(1)
            .execute()
        )

        if not result.data:
            logger.warning("Key not found for quota check — key_id=%s", api_key_id)
            return default_result

        row = result.data[0]
        plan_limit = row.get("plan_limit") or 10000
        plan_name = row.get("plan_name") or "starter"
        overage_enabled = row.get("overage_enabled") or False
        stripe_sub_id = row.get("stripe_subscription_id")
        period_start = row.get("billing_period_start")

        if not period_start:
            now = datetime.now(timezone.utc)
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

        current_usage = await get_usage_count(api_key_id, period_start)
        over_limit = current_usage >= plan_limit

        # If over limit but overage is enabled → allow (they'll be billed)
        within_limit = not over_limit or overage_enabled

        if over_limit and not overage_enabled:
            logger.info(
                "Quota exceeded — key_id=%s usage=%d limit=%d plan=%s",
                api_key_id, current_usage, plan_limit, plan_name,
            )

        return {
            "within_limit": within_limit,
            "current_usage": current_usage,
            "plan_limit": plan_limit,
            "plan_name": plan_name,
            "overage_enabled": overage_enabled,
            "is_overage": over_limit and overage_enabled,
            "stripe_subscription_id": stripe_sub_id,
        }

    except Exception as e:
        logger.error("Quota check failed — key_id=%s error=%s", api_key_id, e)
        return default_result
