"""
Simulate route for SpendGuard API.

POST /v1/simulate — Run one or more authorization checks with NO side effects.
                    Nothing is written to checks, violations, or duplicate_guard tables.

Demo mode (no X-API-Key): up to 10 actions, response includes mode="demo".
Authenticated mode (with X-API-Key): up to 100 actions, response includes mode="simulation".
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from models.check import ActionType, CheckResponse, Confidence, Decision
from models.simulate import SimulateRequest, SimulateResponse, SimulateSummary, SimulationMode
from services.audit_logger import generate_check_id
from services.duplicate_guard import check_duplicate, get_window_minutes_from_policy
from services.policy_loader import PolicyNotFoundError, get_policy
from services.rule_engine import EngineResult, evaluate_rules

logger = logging.getLogger(__name__)

router = APIRouter(tags=["simulate"])

DEMO_MAX_ACTIONS = 10


@router.post("/simulate", summary="Simulate authorization checks")
async def simulate(request: Request, body: SimulateRequest) -> SimulateResponse:
    """
    Runs one or more checks against a policy with no side effects.
    Nothing is written to any table.

    Demo mode (no auth): max 10 actions, mode="demo".
    Authenticated mode (with auth): max 100 actions, mode="simulation".
    """
    # Determine mode based on auth header presence
    api_key = request.headers.get("X-API-Key")
    mode = SimulationMode.simulation if api_key else SimulationMode.demo

    # Enforce demo limit
    if mode == SimulationMode.demo and len(body.actions) > DEMO_MAX_ACTIONS:
        raise HTTPException(status_code=422, detail={
            "error": {
                "code": "demo_limit_exceeded",
                "message": f"Demo mode allows a maximum of {DEMO_MAX_ACTIONS} actions. You submitted {len(body.actions)}.",
                "request_id": getattr(request.state, "request_id", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })

    # Load policy
    try:
        policy = await get_policy(policy_id=body.policy_id)
    except PolicyNotFoundError:
        raise HTTPException(status_code=404, detail={
            "error": {
                "code": "policy_not_found",
                "message": f"No policy found with ID '{body.policy_id}'.",
                "request_id": getattr(request.state, "request_id", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })

    policy_version = policy["version"]
    rules = policy["rules"]
    window_minutes = get_window_minutes_from_policy(rules)

    # Process each action — NO WRITES
    results: list[CheckResponse] = []
    allowed = 0
    blocked = 0
    escalated = 0

    # Track fingerprints within this simulation batch for in-batch duplicate detection
    seen_fingerprints: set[str] = set()

    for action in body.actions:
        action_start = time.perf_counter()

        # Resolve action_type via intent classifier if missing (D018)
        resolved_confidence = "high"
        if action.action_type is None:
            from services.intent_classifier import classify_intent
            classification = await classify_intent(action.reason_text)
            action.action_type = ActionType(classification.action_type)
            resolved_confidence = classification.confidence

        # Run duplicate guard in read-only mode
        dup_result = await check_duplicate(
            agent_id=action.agent_id,
            action_type=action.action_type.value,
            amount=action.amount,
            counterparty=action.counterparty,
            window_minutes=window_minutes,
            simulation_mode=True,  # NEVER writes
        )

        # Also check for duplicates within this simulation batch
        from services.duplicate_guard import compute_fingerprint
        fp = compute_fingerprint(
            action.agent_id, action.action_type.value, action.amount, action.counterparty
        )
        in_batch_dup = fp in seen_fingerprints
        seen_fingerprints.add(fp)

        if dup_result.is_duplicate or in_batch_dup:
            engine_result = EngineResult(
                decision="block",
                confidence="high",
                reason_code="duplicate_action_detected",
                message="This action was already submitted recently (or earlier in this batch).",
                next_step="Wait for the duplicate window to expire or change the action.",
            )
        else:
            engine_result = evaluate_rules(
                rules=rules,
                action_type=action.action_type.value,
                amount=action.amount,
                currency=action.currency,
                counterparty=action.counterparty,
                payment_method=action.payment_method,
                merchant_or_vendor=action.merchant_or_vendor,
                metadata=action.metadata or {},
            )

        latency_ms = int((time.perf_counter() - action_start) * 1000)

        # Count decisions for summary
        if engine_result.decision == "allow":
            allowed += 1
        elif engine_result.decision == "block":
            blocked += 1
        elif engine_result.decision == "escalate":
            escalated += 1

        # If classifier was used, reflect its confidence on allow decisions
        final_confidence = engine_result.confidence
        if engine_result.decision == "allow" and resolved_confidence != "high":
            final_confidence = resolved_confidence

        results.append(CheckResponse(
            check_id=generate_check_id(),
            decision=Decision(engine_result.decision),
            confidence=Confidence(final_confidence),
            reason_code=engine_result.reason_code,
            message=engine_result.message,
            violated_rule_id=engine_result.violated_rule_id,
            violated_rule_description=engine_result.violated_rule_description,
            policy_version=policy_version,
            next_step=engine_result.next_step,
            latency_ms=latency_ms,
            timestamp=datetime.now(timezone.utc),
        ))

    return SimulateResponse(
        mode=mode,
        policy_id=body.policy_id,
        policy_version=policy_version,
        results=results,
        summary=SimulateSummary(
            total=len(results),
            allowed=allowed,
            blocked=blocked,
            escalated=escalated,
        ),
    )

