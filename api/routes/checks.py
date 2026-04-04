"""
Checks routes for SpendGuard API.

POST /v1/checks      — Run a real-time authorization check against a policy.
                       Runs duplicate guard first, then rule engine.
                       Logs every decision to the audit trail.
                       Handles idempotency_key (24-hour window).
GET  /v1/checks/{id} — Retrieve a past check by ID.

Returns allow / block / escalate. Every block includes violated_rule_id.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from models.check import ActionType, CheckRequest, CheckResponse, Confidence, Decision
from services.audit_logger import (
    compute_raw_input_hash,
    generate_check_id,
    log_check_decision,
    log_violation,
)
from services.duplicate_guard import check_duplicate, get_window_minutes_from_policy
from services.policy_loader import PolicyNotFoundError, get_policy
from services.rule_engine import EngineResult, evaluate_rules

logger = logging.getLogger(__name__)

router = APIRouter(tags=["checks"])


@router.post("/checks", summary="Run an authorization check")
async def create_check(request: Request, body: CheckRequest) -> CheckResponse:
    """
    Evaluates a planned financial action against a policy and returns
    allow, block, or escalate. Every decision is logged to the audit trail.
    """
    start_time = time.perf_counter()

    # 0. Check plan quota before processing
    api_key_id = getattr(request.state, "api_key_id", None)
    if api_key_id:
        from services.billing import check_plan_quota
        within_limit, current_usage, plan_limit = await check_plan_quota(api_key_id)
        if not within_limit:
            raise HTTPException(status_code=402, detail={
                "error": {
                    "code": "over_quota",
                    "message": f"Monthly check limit exceeded ({current_usage}/{plan_limit}). Upgrade your plan or wait until the next billing period.",
                    "request_id": getattr(request.state, "request_id", "unknown"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            })

    # 1. Load policy
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

    # 2. Resolve action_type via intent classifier if missing (D018)
    resolved_confidence = "high"  # Default: explicit action_type = high confidence
    if body.action_type is None:
        from services.intent_classifier import classify_intent
        classification = await classify_intent(body.reason_text)
        body.action_type = ActionType(classification.action_type)
        resolved_confidence = classification.confidence
        logger.info(
            "Intent classifier resolved action_type='%s' (confidence=%s) from reason_text='%s'",
            classification.action_type,
            classification.confidence,
            (body.reason_text or "")[:80],
        )

    # 3. Check idempotency_key — return cached result if exists
    if body.idempotency_key:
        try:
            from db.client import supabase
            existing = (
                supabase.table("checks")
                .select("*")
                .eq("idempotency_key", body.idempotency_key)
                .limit(1)
                .execute()
            )
            if existing.data and len(existing.data) > 0:
                row = existing.data[0]
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                logger.info(
                    "Idempotency hit — returning cached check_id=%s",
                    row["check_id"],
                )
                return CheckResponse(
                    check_id=row["check_id"],
                    decision=Decision(row["decision"]),
                    confidence=Confidence(row["confidence"]),
                    reason_code=None,  # Not stored in DB; original reason_code lost on cache
                    message=row.get("violated_rule_description"),
                    violated_rule_id=row.get("violated_rule_id"),
                    violated_rule_description=row.get("violated_rule_description"),
                    policy_version=row["policy_version"],
                    next_step=None,
                    latency_ms=latency_ms,
                    timestamp=datetime.now(timezone.utc),
                )
        except Exception as e:
            logger.warning("Idempotency key lookup failed: %s", e)

    # 3. Run duplicate guard
    window_minutes = get_window_minutes_from_policy(rules)
    dup_result = await check_duplicate(
        agent_id=body.agent_id,
        action_type=body.action_type.value,
        amount=body.amount,
        counterparty=body.counterparty,
        window_minutes=window_minutes,
        simulation_mode=False,
    )

    if dup_result.is_duplicate:
        engine_result = EngineResult(
            decision="block",
            confidence="high",
            reason_code="duplicate_action_detected",
            message=dup_result.message or "This action was already submitted recently.",
            next_step="Wait for the duplicate window to expire or use a different action.",
        )
    else:
        # 4. Run rule engine
        engine_result = evaluate_rules(
            rules=rules,
            action_type=body.action_type.value,
            amount=body.amount,
            currency=body.currency,
            counterparty=body.counterparty,
            payment_method=body.payment_method,
            merchant_or_vendor=body.merchant_or_vendor,
            metadata=body.metadata or {},
        )

    # 5. Generate IDs and compute hashes
    check_id = generate_check_id()
    raw_hash = compute_raw_input_hash(body.model_dump(mode="json"))
    latency_ms = int((time.perf_counter() - start_time) * 1000)

    # 6. Log to checks table (every decision)
    try:
        await log_check_decision(
            check_id=check_id,
            agent_id=body.agent_id,
            policy_id=body.policy_id,
            policy_version=policy_version,
            action_type=body.action_type.value,
            amount=body.amount,
            currency=body.currency,
            counterparty=body.counterparty,
            payment_method=body.payment_method,
            merchant_or_vendor=body.merchant_or_vendor,
            reason_text=body.reason_text,
            idempotency_key=body.idempotency_key,
            engine_result=engine_result,
            latency_ms=latency_ms,
            raw_input_hash=raw_hash,
        )
    except Exception as e:
        logger.error("Failed to log check decision: %s", e)

    # 7. Log to violations table (block/escalate only)
    if engine_result.decision in ("block", "escalate"):
        try:
            await log_violation(
                check_id=check_id,
                agent_id=body.agent_id,
                policy_id=body.policy_id,
                policy_version=policy_version,
                action_type=body.action_type.value,
                amount=body.amount,
                currency=body.currency,
                counterparty=body.counterparty,
                engine_result=engine_result,
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.error("Failed to log violation: %s", e)

    # 8. Return response
    # If the classifier was used, confidence reflects classification confidence
    # unless the rule engine itself produced a block/escalate (which is always high)
    final_confidence = engine_result.confidence
    if engine_result.decision == "allow" and resolved_confidence != "high":
        final_confidence = resolved_confidence

    response = CheckResponse(
        check_id=check_id,
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
    )

    # 9. Emit usage event (fire-and-forget — never blocks the response)
    if api_key_id:
        try:
            from services.billing import emit_usage_event
            await emit_usage_event(api_key_id)
        except Exception as e:
            logger.error("Failed to emit usage event: %s", e)

    return response


@router.get("/checks/{check_id}", summary="Get a check by ID")
async def get_check(request: Request, check_id: str) -> CheckResponse:
    """Retrieves a past authorization check and its decision by ID."""
    try:
        from db.client import supabase
        result = (
            supabase.table("checks")
            .select("*")
            .eq("check_id", check_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.error("Failed to look up check: %s", e)
        raise HTTPException(status_code=500, detail={
            "error": {
                "code": "internal_error",
                "message": "Failed to retrieve check.",
                "request_id": getattr(request.state, "request_id", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })

    if not result.data or len(result.data) == 0:
        raise HTTPException(status_code=404, detail={
            "error": {
                "code": "check_not_found",
                "message": f"No check found with ID '{check_id}'.",
                "request_id": getattr(request.state, "request_id", "unknown"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        })

    row = result.data[0]
    return CheckResponse(
        check_id=row["check_id"],
        decision=Decision(row["decision"]),
        confidence=Confidence(row["confidence"]),
        reason_code=row.get("violated_rule_id"),
        message=row.get("violated_rule_description"),
        violated_rule_id=row.get("violated_rule_id"),
        violated_rule_description=row.get("violated_rule_description"),
        policy_version=row["policy_version"],
        next_step=None,
        latency_ms=row.get("latency_ms", 0),
        timestamp=row.get("created_at", datetime.now(timezone.utc)),
    )

