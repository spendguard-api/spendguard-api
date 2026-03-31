"""
Policies routes for SpendGuard API.

POST /v1/policies  — Create a new policy or a new version of an existing policy.
GET  /v1/policies/{id} — Retrieve a policy by ID (latest version by default,
                          specific version via ?version=N).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from models.policy import PolicyCreateRequest, PolicyResponse, PolicyRule
from services.policy_loader import PolicyNotFoundError, create_policy, get_policy

logger = logging.getLogger(__name__)

router = APIRouter(tags=["policies"])


@router.post("/policies", status_code=201, summary="Create a policy")
async def create_policy_route(request: Request, body: PolicyCreateRequest) -> PolicyResponse:
    """
    Creates a new financial authorization policy with a set of rules.
    If a policy_id is provided and already exists, a new version is created.
    Previous versions are preserved.
    """
    # Generate policy_id if not provided
    policy_id = body.policy_id or f"policy_{uuid.uuid4().hex[:12]}"

    # Convert rules to list of dicts for storage
    rules_dicts = [rule.model_dump() for rule in body.rules]

    try:
        result = await create_policy(
            policy_id=policy_id,
            name=body.name,
            rules=rules_dicts,
            description=body.description,
            metadata=body.metadata,
        )
    except Exception as e:
        logger.error("Failed to create policy: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "internal_error",
                "message": "Failed to create policy.",
                "request_id": getattr(request.state, "request_id", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })

    # Build response
    rules_parsed = [PolicyRule(**r) for r in result.get("rules", rules_dicts)]
    now = datetime.now(timezone.utc)

    return PolicyResponse(
        policy_id=result.get("policy_id", policy_id),
        name=result.get("name", body.name),
        description=result.get("description", body.description),
        version=result.get("version", 1),
        rules=rules_parsed,
        created_at=result.get("created_at", now),
        updated_at=result.get("created_at", now),
        metadata=body.metadata,
    )


@router.get("/policies/{policy_id}", summary="Get a policy")
async def get_policy_route(
    request: Request,
    policy_id: str,
    version: int | None = Query(default=None, ge=1, description="Specific version to retrieve"),
) -> PolicyResponse:
    """
    Retrieves a policy by ID. Returns the latest version by default.
    Use the version query parameter to retrieve a specific version.
    """
    try:
        result = await get_policy(policy_id=policy_id, version=version)
    except PolicyNotFoundError:
        raise HTTPException(status_code=404, detail={
            "error": {
                "code": "policy_not_found",
                "message": f"No policy found with ID '{policy_id}'.",
                "request_id": getattr(request.state, "request_id", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })
    except Exception as e:
        logger.error("Failed to get policy: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "internal_error",
                "message": "Failed to retrieve policy.",
                "request_id": getattr(request.state, "request_id", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })

    rules_parsed = [PolicyRule(**r) for r in result.get("rules", [])]
    created_at = result.get("created_at", datetime.now(timezone.utc))

    return PolicyResponse(
        policy_id=result["policy_id"],
        name=result["name"],
        description=result.get("description"),
        version=result["version"],
        rules=rules_parsed,
        created_at=created_at,
        updated_at=created_at,
        metadata=result.get("metadata"),
    )

