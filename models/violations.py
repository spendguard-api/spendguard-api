"""
Pydantic v2 models for SpendGuard API violation objects.

Covers:
- ViolationRecord        — a single block/escalate audit record
- PaginationInfo         — cursor-based pagination metadata
- ViolationsListResponse — response body for GET /v1/violations

All models are aligned to openapi.yaml schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from models.check import ActionType, Confidence, Decision


class ViolationRecord(BaseModel):
    """A single violation record — block or escalate decisions only."""

    violation_id: str = Field(..., description="Unique violation ID (viol_ prefix)")
    check_id: str = Field(..., description="Links to the originating check")
    agent_id: str = Field(..., description="Agent that made the request")
    policy_id: str = Field(..., description="Policy evaluated against")
    policy_version: int = Field(..., description="Policy version at time of check")
    action_type: str = Field(..., description="Financial action type")
    amount: float = Field(..., description="Dollar amount")
    currency: str = Field(..., description="ISO 4217 currency code")
    counterparty: str = Field(..., description="Customer or vendor ID")
    decision: str = Field(..., description="block or escalate")
    violated_rule_id: str = Field(..., description="Rule that fired")
    violated_rule_description: str = Field(..., description="Human-readable rule description")
    confidence: str = Field(..., description="Confidence level")
    latency_ms: int = Field(..., description="Processing time in milliseconds")
    timestamp: datetime | None = Field(default=None, description="Decision timestamp")

    model_config = {"from_attributes": True}


class PaginationInfo(BaseModel):
    """Cursor-based pagination metadata."""

    next_cursor: str | None = Field(
        default=None, description="Cursor for the next page, null if no more results"
    )
    has_more: bool = Field(..., description="Whether more results exist beyond this page")
    total_count: int = Field(..., description="Total matching records")


class ViolationsListResponse(BaseModel):
    """Response body for GET /v1/violations."""

    data: list[ViolationRecord] = Field(..., description="List of violation records")
    pagination: PaginationInfo = Field(..., description="Pagination metadata")
