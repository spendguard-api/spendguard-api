"""
Dashboard data routes for SpendGuard API.

GET /v1/usage    — Usage summary for the authenticated key.
GET /v1/policies — List all policies (paginated).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])


@router.get("/usage", summary="Get usage summary")
async def get_usage(request: Request) -> dict:
    """
    Returns usage summary for the authenticated API key.
    Powers the dashboard home page.
    """
    api_key_id = getattr(request.state, "api_key_id", None)
    if not api_key_id:
        raise HTTPException(status_code=401)

    try:
        from db.client import supabase

        # Get key info
        key_result = (
            supabase.table("api_keys")
            .select("plan_name, plan_limit, billing_period_start, overage_enabled, owner_name, email, cancel_at_period_end, current_period_end, stripe_subscription_id")
            .eq("id", api_key_id)
            .limit(1)
            .execute()
        )

        if not key_result.data:
            raise HTTPException(status_code=404)

        key = key_result.data[0]
        plan_name = key.get("plan_name", "free")
        plan_limit = key.get("plan_limit", 1000)
        period_start = key.get("billing_period_start")
        overage_enabled = key.get("overage_enabled", False)
        cancel_at_period_end = key.get("cancel_at_period_end", False)
        current_period_end = key.get("current_period_end")
        stripe_subscription_id = key.get("stripe_subscription_id")

        # Lazy backfill: if the user is on a paid plan but current_period_end is
        # missing (subscription was created before the field existed), fetch it
        # from Stripe once and persist it. This is a one-time per-user heal that
        # makes the dashboard "next billing date" populate without manual SQL.
        if plan_name != "free" and stripe_subscription_id and not current_period_end:
            try:
                import stripe
                import os
                stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
                sub = stripe.Subscription.retrieve(stripe_subscription_id)
                period_end_unix = sub.get("current_period_end")
                fetched_cancel_flag = bool(sub.get("cancel_at_period_end", False))
                if period_end_unix:
                    current_period_end = datetime.fromtimestamp(
                        period_end_unix, tz=timezone.utc
                    ).isoformat()
                    update_payload = {"current_period_end": current_period_end}
                    # Also sync cancel flag in case it drifted
                    if fetched_cancel_flag != cancel_at_period_end:
                        update_payload["cancel_at_period_end"] = fetched_cancel_flag
                        cancel_at_period_end = fetched_cancel_flag
                    supabase.table("api_keys").update(update_payload).eq("id", api_key_id).execute()
                    logger.info("Backfilled current_period_end for key_id=%s from Stripe", api_key_id)
            except Exception as e:
                # Backfill is best-effort — don't break /v1/usage if Stripe is down
                logger.warning("Failed to backfill current_period_end for key_id=%s: %s", api_key_id, e)

        if not period_start:
            now = datetime.now(timezone.utc)
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

        # Count usage this period
        period_result = (
            supabase.table("usage_events")
            .select("id", count="exact")
            .eq("api_key_id", api_key_id)
            .gte("created_at", period_start)
            .execute()
        )
        current_period_usage = period_result.count if period_result.count is not None else 0

        # Count checks today
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_result = (
            supabase.table("usage_events")
            .select("id", count="exact")
            .eq("api_key_id", api_key_id)
            .gte("created_at", today_start)
            .execute()
        )
        checks_today = today_result.count if today_result.count is not None else 0

        # Count violations today (scoped to current user)
        violations_result = (
            supabase.table("violations")
            .select("id", count="exact")
            .eq("api_key_id", api_key_id)
            .gte("created_at", today_start)
            .execute()
        )
        violations_today = violations_result.count if violations_result.count is not None else 0

        return {
            "current_period_usage": current_period_usage,
            "plan_limit": plan_limit,
            "plan_name": plan_name,
            "period_start": period_start,
            "checks_today": checks_today,
            "violations_today": violations_today,
            "overage_enabled": overage_enabled,
            "owner_name": key.get("owner_name"),
            "email": key.get("email"),
            "cancel_at_period_end": cancel_at_period_end,
            "current_period_end": current_period_end,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get usage: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "internal_error",
                "message": "Failed to retrieve usage data.",
                "request_id": getattr(request.state, "request_id", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })


@router.get("/policies", summary="List all policies")
async def list_policies(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict:
    """
    List all policies, paginated, sorted by created_at DESC.
    """
    try:
        from db.client import supabase

        query = supabase.table("policies").select("*", count="exact")

        # Scope to current user's policies + shared templates (no owner)
        user_key_id = getattr(request.state, "api_key_id", None)
        if user_key_id:
            query = query.or_(f"api_key_id.eq.{user_key_id},api_key_id.is.null")

        if cursor:
            query = query.lt("created_at", cursor)

        query = query.order("created_at", desc=True).limit(limit + 1)
        result = query.execute()

        rows = result.data or []
        total_count = result.count if result.count is not None else len(rows)
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        next_cursor = rows[-1]["created_at"] if has_more and rows else None

        # Deduplicate — only return latest version of each policy_id
        seen = {}
        policies = []
        for row in rows:
            pid = row["policy_id"]
            if pid not in seen:
                seen[pid] = True
                # Ensure rules is always a list (rules_json can be string or list from Supabase)
                rules_raw = row.get("rules_json", [])
                if isinstance(rules_raw, str):
                    import json as _json
                    try:
                        rules_raw = _json.loads(rules_raw)
                    except (ValueError, TypeError):
                        rules_raw = []
                if not isinstance(rules_raw, list):
                    rules_raw = []

                policies.append({
                    "policy_id": row["policy_id"],
                    "name": row["name"],
                    "description": row.get("description"),
                    "version": row["version"],
                    "rules": rules_raw,
                    "created_at": row.get("created_at"),
                })

        return {
            "data": policies,
            "pagination": {
                "next_cursor": next_cursor,
                "has_more": has_more,
                "total_count": total_count,
            },
        }

    except Exception as e:
        logger.error("Failed to list policies: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "internal_error",
                "message": "Failed to retrieve policies.",
                "request_id": getattr(request.state, "request_id", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })
