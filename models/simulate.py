"""
Pydantic v2 models for SpendGuard API simulation objects.

Covers:
- SimulationMode    — enum for demo vs authenticated simulation mode
- SimulateRequest   — request body for POST /v1/simulate
- SimulateSummary   — summary counts of simulation results
- SimulateResponse  — full response body for POST /v1/simulate

All models are aligned to openapi.yaml schemas.

Key rules:
- Demo mode (no auth): max 10 actions per request
- Authenticated mode: max 100 actions per request
- Simulation is ALWAYS side-effect free — nothing is written anywhere
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from models.check import CheckRequest, CheckResponse


class SimulationMode(str, Enum):
    """Whether the simulation ran in public demo mode or authenticated batch mode."""

    demo = "demo"
    simulation = "simulation"


class SimulateRequest(BaseModel):
    """
    Request body for POST /v1/simulate.

    Max 10 actions in demo mode (no auth).
    Max 100 actions in authenticated batch mode.
    The limit is enforced at the route handler level based on auth status.
    """

    policy_id: str = Field(..., description="Policy to simulate against")
    actions: list[CheckRequest] = Field(
        ...,
        min_length=1,
        max_length=100,
        description=(
            "Actions to simulate. Max 10 in demo mode, max 100 with auth. "
            "No side effects — nothing is written."
        ),
    )

    model_config = {"extra": "forbid"}


class SimulateSummary(BaseModel):
    """Aggregate counts of decisions across all simulated actions."""

    total: int = Field(..., description="Total number of actions simulated")
    allowed: int = Field(..., description="Number of actions that would be allowed")
    blocked: int = Field(..., description="Number of actions that would be blocked")
    escalated: int = Field(
        ..., description="Number of actions that would be escalated"
    )


class SimulateResponse(BaseModel):
    """
    Response body for POST /v1/simulate.

    Returns individual results for each action plus an aggregate summary.
    mode=demo for unauthenticated requests, mode=simulation for authenticated.
    """

    mode: SimulationMode = Field(
        ...,
        description="demo (no auth) or simulation (authenticated)",
    )
    policy_id: str = Field(..., description="Policy that was evaluated")
    policy_version: int = Field(
        ..., description="Policy version used for this simulation"
    )
    results: list[CheckResponse] = Field(
        ..., description="Individual decision for each simulated action"
    )
    summary: SimulateSummary = Field(
        ..., description="Aggregate counts across all simulated actions"
    )
