"""
Violations routes for SpendGuard API.

GET /v1/violations — Returns the audit log of block and escalate decisions.
                     Supports filtering by agent_id, action_type, decision, from, to.
                     Supports cursor-based pagination (limit, cursor).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from models.violations import PaginationInfo, ViolationRecord, ViolationsListResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["violations"])


@router.get("/violations", summary="List violations")
async def list_violations(
    request: Request,
    agent_id: str | None = Query(default=None, description="Filter by agent ID"),
    action_type: str | None = Query(default=None, description="Filter by action type"),
    decision: str | None = Query(default=None, description="Filter: block or escalate"),
    from_date: str | None = Query(default=None, alias="from", description="Start date (ISO 8601 UTC)"),
    to_date: str | None = Query(default=None, alias="to", description="End date (ISO 8601 UTC)"),
    limit: int = Query(default=20, ge=1, le=100, description="Results per page"),
    cursor: str | None = Query(default=None, description="Pagination cursor"),
) -> ViolationsListResponse:
    """
    Returns an audit log of block and escalate decisions.
    Supports filtering and cursor-based pagination.
    """
    try:
        from db.client import supabase

        # Build query
        query = supabase.table("violations").select("*", count="exact")

        # Apply filters
        if agent_id:
            query = query.eq("agent_id", agent_id)
        if action_type:
            query = query.eq("action_type", action_type)
        if decision:
            query = query.eq("decision", decision)
        if from_date:
            query = query.gte("created_at", from_date)
        if to_date:
            query = query.lte("created_at", to_date)

        # Cursor-based pagination: if cursor provided, fetch rows after it
        if cursor:
            query = query.lt("violation_id", cursor)

        # Sort newest first, fetch limit+1 to check has_more
        query = query.order("created_at", desc=True).limit(limit + 1)

        result = query.execute()

    except Exception as e:
        logger.error("Failed to query violations: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "internal_error",
                "message": "Failed to retrieve violations.",
                "request_id": getattr(request.state, "request_id", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })

    rows = result.data or []
    total_count = result.count if result.count is not None else len(rows)

    # Determine if more pages exist
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]  # Trim the extra row

    # Build next_cursor from last row
    next_cursor = rows[-1]["violation_id"] if has_more and rows else None

    # Parse rows into ViolationRecord models
    records = []
    for row in rows:
        records.append(ViolationRecord(
            violation_id=row["violation_id"],
            check_id=row["check_id"],
            agent_id=row["agent_id"],
            policy_id=row["policy_id"],
            policy_version=row["policy_version"],
            action_type=row["action_type"],
            amount=float(row["amount"]),
            currency=row["currency"],
            counterparty=row["counterparty"],
            decision=row["decision"],
            violated_rule_id=row["violated_rule_id"],
            violated_rule_description=row["violated_rule_description"],
            confidence=row["confidence"],
            latency_ms=row["latency_ms"],
            timestamp=row.get("created_at"),
        ))

    return ViolationsListResponse(
        data=records,
        pagination=PaginationInfo(
            next_cursor=next_cursor,
            has_more=has_more,
            total_count=total_count,
        ),
    )

