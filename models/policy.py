"""
Pydantic v2 models for SpendGuard API policy objects.

Covers:
- PolicyRule          — a single rule within a policy
- PolicyCreateRequest — request body for POST /v1/policies
- PolicyResponse      — response body for policy endpoints

All models are aligned to openapi.yaml schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class PolicyRule(BaseModel):
    """A single authorization rule within a policy."""

    rule_id: str = Field(..., description="Unique rule identifier within the policy")
    rule_type: str = Field(
        ...,
        description="The type of rule",
        pattern=(
            "^(max_amount|refund_age_limit|blocked_categories|vendor_allowlist"
            "|blocked_payment_rails|discount_cap|geography_block|time_restriction"
            "|duplicate_guard|escalate_if)$"
        ),
    )
    description: str | None = Field(
        default=None,
        description="Human-readable description of what this rule does",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Rule-specific parameters. Structure depends on rule_type.",
    )

    model_config = {"extra": "forbid"}


class PolicyCreateRequest(BaseModel):
    """Request body for POST /v1/policies."""

    policy_id: str | None = Field(
        default=None,
        description=(
            "Optional. If provided and a policy with this ID already exists, "
            "a new version is created. If omitted, a new policy_id is generated."
        ),
    )
    name: str = Field(..., description="Human-readable name for the policy")
    description: str | None = Field(
        default=None, description="What this policy is for"
    )
    rules: list[PolicyRule] = Field(
        ...,
        min_length=1,
        description="List of authorization rules. Minimum 1 rule required.",
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional key-value metadata"
    )

    model_config = {"extra": "forbid"}


class PolicyResponse(BaseModel):
    """Response body for policy endpoints."""

    policy_id: str = Field(..., description="Unique policy identifier")
    name: str = Field(..., description="Human-readable name for the policy")
    description: str | None = Field(default=None)
    version: int = Field(..., description="Current version number (starts at 1)")
    rules: list[PolicyRule] = Field(..., description="Rules in this policy version")
    created_at: datetime = Field(..., description="When this policy version was created")
    updated_at: datetime = Field(..., description="When this policy was last updated")
    metadata: dict[str, Any] | None = Field(default=None)

    model_config = {"from_attributes": True}
