"""
Immutable audit logger for SpendGuard API.

Writes every check decision to the checks table.
Writes block/escalate decisions to the violations table.

Both tables are append-only — this module ONLY inserts. Never update. Never delete.

Required fields logged (14 total):
- check_id, agent_id, policy_id, policy_version
- action_type, amount, currency, counterparty
- decision, violated_rule_id, violated_rule_description
- confidence, latency_ms, raw_input_hash, timestamp
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from services.rule_engine import EngineResult

logger = logging.getLogger(__name__)


def generate_check_id() -> str:
    """Generate a unique check ID with chk_ prefix."""
    return f"chk_{uuid.uuid4().hex[:12]}"


def generate_violation_id() -> str:
    """Generate a unique violation ID with viol_ prefix."""
    return f"viol_{uuid.uuid4().hex[:12]}"


def compute_raw_input_hash(request_data: dict[str, Any]) -> str:
    """
    Compute SHA-256 of the full request body for tamper detection.

    Args:
        request_data: Dict of the original request payload.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    # Sort keys for deterministic serialization
    raw = json.dumps(request_data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def log_check_decision(
    check_id: str,
    agent_id: str,
    policy_id: str,
    policy_version: int,
    action_type: str,
    amount: float,
    currency: str,
    counterparty: str,
    payment_method: str | None,
    merchant_or_vendor: str | None,
    reason_text: str | None,
    idempotency_key: str | None,
    engine_result: EngineResult,
    latency_ms: int,
    raw_input_hash: str,
    supabase_client: Any | None = None,
) -> None:
    """
    Write a check decision to the checks table.

    This is called for EVERY decision: allow, block, and escalate.
    Append-only — never update or delete rows.

    Args:
        check_id: The generated chk_ ID.
        agent_id: Agent making the request.
        policy_id: Policy evaluated against.
        policy_version: Version of the policy used.
        action_type: Financial action type.
        amount: Dollar amount.
        currency: ISO 4217 code.
        counterparty: Customer/vendor ID.
        payment_method: Optional payment rail.
        merchant_or_vendor: Optional merchant.
        reason_text: Optional free-text reason from agent.
        idempotency_key: Optional client-supplied retry key.
        engine_result: The EngineResult from rule evaluation.
        latency_ms: Processing time in milliseconds.
        raw_input_hash: SHA-256 of the request body.
        supabase_client: Supabase client instance.
    """
    if supabase_client is None:
        from db.client import supabase
        supabase_client = supabase

    row = {
        "check_id": check_id,
        "agent_id": agent_id,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "action_type": action_type,
        "amount": float(amount),
        "currency": currency,
        "counterparty": counterparty,
        "payment_method": payment_method,
        "merchant_or_vendor": merchant_or_vendor,
        "reason_text": reason_text,
        "decision": engine_result.decision,
        "violated_rule_id": engine_result.violated_rule_id,
        "violated_rule_description": engine_result.violated_rule_description,
        "confidence": engine_result.confidence,
        "latency_ms": latency_ms,
        "raw_input_hash": raw_input_hash,
        "idempotency_key": idempotency_key,
    }

    try:
        supabase_client.table("checks").insert(row).execute()
        logger.info(
            "Check logged — check_id=%s decision=%s latency=%dms",
            check_id,
            engine_result.decision,
            latency_ms,
        )
    except Exception as e:
        logger.error("Failed to log check to database: %s", e)
        raise


async def log_violation(
    check_id: str,
    agent_id: str,
    policy_id: str,
    policy_version: int,
    action_type: str,
    amount: float,
    currency: str,
    counterparty: str,
    engine_result: EngineResult,
    latency_ms: int,
    supabase_client: Any | None = None,
) -> str:
    """
    Write a block/escalate decision to the violations table.

    Called ONLY when decision is block or escalate — never for allow.
    Append-only — never update or delete rows.

    Args:
        check_id: The generated chk_ ID (links to checks table).
        agent_id: Agent making the request.
        policy_id: Policy evaluated against.
        policy_version: Version of the policy used.
        action_type: Financial action type.
        amount: Dollar amount.
        currency: ISO 4217 code.
        counterparty: Customer/vendor ID.
        engine_result: The EngineResult from rule evaluation.
        latency_ms: Processing time in milliseconds.
        supabase_client: Supabase client instance.

    Returns:
        The generated violation_id.
    """
    if supabase_client is None:
        from db.client import supabase
        supabase_client = supabase

    violation_id = generate_violation_id()

    row = {
        "violation_id": violation_id,
        "check_id": check_id,
        "agent_id": agent_id,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "action_type": action_type,
        "amount": float(amount),
        "currency": currency,
        "counterparty": counterparty,
        "decision": engine_result.decision,
        "violated_rule_id": engine_result.violated_rule_id,
        "violated_rule_description": engine_result.violated_rule_description,
        "confidence": engine_result.confidence,
        "latency_ms": latency_ms,
    }

    try:
        supabase_client.table("violations").insert(row).execute()
        logger.info(
            "Violation logged — violation_id=%s check_id=%s decision=%s",
            violation_id,
            check_id,
            engine_result.decision,
        )
    except Exception as e:
        logger.error("Failed to log violation to database: %s", e)
        raise

    return violation_id
