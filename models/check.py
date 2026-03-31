"""
Pydantic v2 models for SpendGuard API check objects.

Covers:
- ActionType    — enum of V1 financial action types
- Decision      — enum of possible authorization decisions
- Confidence    — enum of decision confidence levels
- CheckRequest  — request body for POST /v1/checks
- CheckResponse — response body for check endpoints

All models are aligned to openapi.yaml schemas.
V1 action types: refund, credit, discount, spend — exactly these four.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ActionType(str, Enum):
    """
    V1 supported financial action types.
    Exactly four values. Do not add others without a PM decision entry in DECISIONS.md.
    """

    refund = "refund"
    credit = "credit"
    discount = "discount"
    spend = "spend"


class Decision(str, Enum):
    """The authorization decision returned by the rule engine."""

    allow = "allow"
    block = "block"
    escalate = "escalate"


class Confidence(str, Enum):
    """Confidence level of the authorization decision."""

    high = "high"
    medium = "medium"
    low = "low"


class CheckRequest(BaseModel):
    """
    Request body for POST /v1/checks.

    Required fields: agent_id, policy_id, action_type, amount, currency, counterparty.
    """

    agent_id: str = Field(..., description="ID of the agent making the request")
    policy_id: str = Field(..., description="Policy to evaluate against")
    action_type: ActionType | None = Field(
        default=None,
        description=(
            "The type of financial action. Optional if reason_text is provided — "
            "the intent classifier will resolve it."
        ),
    )
    amount: float = Field(
        ..., ge=0, description="Dollar amount of the action (must be >= 0)"
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code (exactly 3 characters)",
    )
    counterparty: str = Field(
        ..., description="Customer ID, vendor ID, or counterparty identifier"
    )
    payment_method: str | None = Field(
        default=None, description="Payment method or rail (e.g., card, ach, wire)"
    )
    merchant_or_vendor: str | None = Field(
        default=None, description="Merchant or vendor identifier"
    )
    reason_text: str | None = Field(
        default=None,
        description="Human or agent-provided reason for the action. Used by semantic classifier if action_type is ambiguous.",
    )
    idempotency_key: str | None = Field(
        default=None,
        description="Unique key to safely retry without double-logging (24-hour window)",
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Additional context fields used by rule evaluation "
            "(e.g., days_since_purchase, customer_lifetime_value, country)"
        ),
    )

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def require_action_type_or_reason_text(self) -> "CheckRequest":
        """Either action_type or reason_text must be provided (D018)."""
        if self.action_type is None and (self.reason_text is None or not self.reason_text.strip()):
            raise ValueError(
                "Either action_type or reason_text is required. "
                "Provide action_type directly, or provide reason_text "
                "so the intent classifier can resolve it."
            )
        return self


class CheckResponse(BaseModel):
    """
    Response body for POST /v1/checks and GET /v1/checks/{id}.

    Always includes: check_id, decision, confidence, policy_version, latency_ms, timestamp.
    On block/escalate: violated_rule_id and violated_rule_description are non-null.
    On allow: violated_rule_id is null.
    """

    check_id: str = Field(..., description="Unique check identifier (format: chk_...)")
    decision: Decision = Field(..., description="Authorization decision")
    confidence: Confidence = Field(..., description="Confidence level of the decision")
    reason_code: str | None = Field(
        default=None, description="Machine-readable reason code (snake_case)"
    )
    message: str | None = Field(
        default=None, description="Human-readable explanation of the decision"
    )
    violated_rule_id: str | None = Field(
        default=None,
        description="ID of the rule that caused block or escalate. Null on allow.",
    )
    violated_rule_description: str | None = Field(
        default=None, description="Human-readable description of the violated rule"
    )
    policy_version: int = Field(
        ..., description="Policy version that was evaluated at time of check"
    )
    next_step: str | None = Field(
        default=None, description="Recommended next action for the agent"
    )
    latency_ms: int = Field(
        ..., description="Total end-to-end processing time in milliseconds"
    )
    timestamp: datetime = Field(..., description="Decision timestamp (UTC ISO 8601)")

    model_config = {"from_attributes": True}
