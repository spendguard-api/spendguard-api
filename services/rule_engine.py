"""
Deterministic rule engine for SpendGuard API.

Evaluates all rules in a policy against a check request.
Returns allow / block / escalate.

Rule precedence: block > escalate > allow.
Duplicate guard runs before all rules (see duplicate_guard.py).

Evaluation is:
- Deterministic — same input always produces same output
- Stateless — no side effects during rule evaluation
- Order-independent — rule ordering does not change the final decision
- Fast — target under 50ms

Rules decide. Semantics only classify action_type. Never the other way around.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RuleResult:
    """Result of evaluating a single rule."""

    triggered: bool
    decision: str = "allow"  # allow / block / escalate
    rule_id: str | None = None
    rule_description: str | None = None
    reason_code: str | None = None
    message: str | None = None
    next_step: str | None = None


@dataclass
class EngineResult:
    """Final result of evaluating all rules in a policy."""

    decision: str  # allow / block / escalate
    confidence: str = "high"  # deterministic rules always = high
    violated_rule_id: str | None = None
    violated_rule_description: str | None = None
    reason_code: str | None = None
    message: str | None = None
    next_step: str | None = None


def evaluate_rules(
    rules: list[dict[str, Any]],
    action_type: str,
    amount: float,
    currency: str,
    counterparty: str,
    payment_method: str | None = None,
    merchant_or_vendor: str | None = None,
    metadata: dict[str, Any] | None = None,
    evaluation_time: datetime | None = None,
) -> EngineResult:
    """
    Evaluate all rules in a policy against the check request.

    Precedence:
      - If ANY rule returns block → overall = block (first triggered block wins)
      - If no block, but any escalate → overall = escalate (first triggered escalate)
      - If nothing triggers → overall = allow

    Args:
        rules: List of rule dicts from the policy.
        action_type: refund / credit / discount / spend.
        amount: Dollar amount.
        currency: ISO 4217 currency code.
        counterparty: Customer or vendor ID.
        payment_method: Optional payment method string.
        merchant_or_vendor: Optional merchant or vendor string.
        metadata: Optional dict of additional context (days_since_purchase, etc.).
        evaluation_time: UTC datetime for time_restriction evaluation. Defaults to now.

    Returns:
        EngineResult with the final decision and the triggered rule info.
    """
    if metadata is None:
        metadata = {}
    if evaluation_time is None:
        evaluation_time = datetime.now(timezone.utc)

    block_results: list[RuleResult] = []
    escalate_results: list[RuleResult] = []

    for rule in rules:
        rule_type = rule.get("rule_type", "")
        rule_id = rule.get("rule_id", "unknown")
        rule_desc = rule.get("description", "")
        params = rule.get("parameters", {})

        # Skip the duplicate_guard config rule — it's handled upstream
        if rule_type == "duplicate_guard":
            continue

        result = _evaluate_single_rule(
            rule_type=rule_type,
            rule_id=rule_id,
            rule_description=rule_desc,
            params=params,
            action_type=action_type,
            amount=amount,
            currency=currency,
            counterparty=counterparty,
            payment_method=payment_method,
            merchant_or_vendor=merchant_or_vendor,
            metadata=metadata,
            evaluation_time=evaluation_time,
        )

        if result.triggered:
            if result.decision == "block":
                block_results.append(result)
            elif result.decision == "escalate":
                escalate_results.append(result)

    # Block takes precedence over escalate — return first triggered block
    if block_results:
        first = block_results[0]
        return EngineResult(
            decision="block",
            confidence="high",
            violated_rule_id=first.rule_id,
            violated_rule_description=first.rule_description,
            reason_code=first.reason_code,
            message=first.message,
            next_step=first.next_step,
        )

    # Escalate takes precedence over allow
    if escalate_results:
        first = escalate_results[0]
        return EngineResult(
            decision="escalate",
            confidence="high",
            violated_rule_id=first.rule_id,
            violated_rule_description=first.rule_description,
            reason_code=first.reason_code,
            message=first.message,
            next_step=first.next_step,
        )

    # No rules triggered — allow
    return EngineResult(
        decision="allow",
        confidence="high",
        message="Action is within policy. Proceed.",
        next_step="Proceed with the action.",
    )


def _evaluate_single_rule(
    rule_type: str,
    rule_id: str,
    rule_description: str,
    params: dict[str, Any],
    action_type: str,
    amount: float,
    currency: str,
    counterparty: str,
    payment_method: str | None,
    merchant_or_vendor: str | None,
    metadata: dict[str, Any],
    evaluation_time: datetime,
) -> RuleResult:
    """Route to the correct rule evaluator by rule_type."""
    evaluator = RULE_EVALUATORS.get(rule_type)
    if evaluator is None:
        logger.warning("Unknown rule_type '%s' (rule_id=%s) — skipping", rule_type, rule_id)
        return RuleResult(triggered=False)

    return evaluator(
        rule_id=rule_id,
        rule_description=rule_description,
        params=params,
        action_type=action_type,
        amount=amount,
        currency=currency,
        counterparty=counterparty,
        payment_method=payment_method,
        merchant_or_vendor=merchant_or_vendor,
        metadata=metadata,
        evaluation_time=evaluation_time,
    )


# ==============================================================
# Individual rule evaluators
# ==============================================================


def _eval_max_amount(*, rule_id: str, rule_description: str, params: dict,
                     amount: float, currency: str, **kwargs: Any) -> RuleResult:
    """Block if amount exceeds the configured limit."""
    limit = params.get("limit", 0)
    if amount > limit:
        return RuleResult(
            triggered=True,
            decision="block",
            rule_id=rule_id,
            rule_description=rule_description,
            reason_code="max_amount_exceeded",
            message=f"Amount ${amount:.2f} exceeds the policy limit of ${limit:.2f}.",
            next_step=f"Reduce the amount to ${limit:.2f} or below, or escalate to a manager.",
        )
    return RuleResult(triggered=False)


def _eval_refund_age_limit(*, rule_id: str, rule_description: str, params: dict,
                           action_type: str, metadata: dict, **kwargs: Any) -> RuleResult:
    """Block refunds on old purchases. Only applies to action_type=refund."""
    if action_type != "refund":
        return RuleResult(triggered=False)

    max_days = params.get("max_days", 30)
    days_since = metadata.get("days_since_purchase")

    if days_since is None:
        return RuleResult(triggered=False)

    if days_since > max_days:
        return RuleResult(
            triggered=True,
            decision="block",
            rule_id=rule_id,
            rule_description=rule_description,
            reason_code="refund_age_limit_exceeded",
            message=f"Refund requested for an order {days_since} days old. Policy limit is {max_days} days.",
            next_step="Inform the customer the return window has closed.",
        )
    return RuleResult(triggered=False)


def _eval_blocked_categories(*, rule_id: str, rule_description: str, params: dict,
                             metadata: dict, merchant_or_vendor: str | None,
                             **kwargs: Any) -> RuleResult:
    """Block actions in prohibited categories."""
    blocked = params.get("categories", [])

    # Check metadata.category
    category = metadata.get("category", "")
    if category and category in blocked:
        return RuleResult(
            triggered=True,
            decision="block",
            rule_id=rule_id,
            rule_description=rule_description,
            reason_code="blocked_category",
            message=f"Category '{category}' is blocked by policy.",
            next_step="This category is not permitted. Choose a different category.",
        )

    # Check merchant_or_vendor for blocked category substrings
    if merchant_or_vendor:
        for cat in blocked:
            if cat.lower() in merchant_or_vendor.lower():
                return RuleResult(
                    triggered=True,
                    decision="block",
                    rule_id=rule_id,
                    rule_description=rule_description,
                    reason_code="blocked_category",
                    message=f"Merchant/vendor '{merchant_or_vendor}' matches blocked category '{cat}'.",
                    next_step="This merchant or vendor is in a blocked category.",
                )

    return RuleResult(triggered=False)


def _eval_vendor_allowlist(*, rule_id: str, rule_description: str, params: dict,
                           action_type: str, counterparty: str,
                           **kwargs: Any) -> RuleResult:
    """Block payments to vendors not on the approved list. Only applies to spend."""
    if action_type != "spend":
        return RuleResult(triggered=False)

    allowed_vendors = params.get("vendors", [])
    if counterparty not in allowed_vendors:
        return RuleResult(
            triggered=True,
            decision="block",
            rule_id=rule_id,
            rule_description=rule_description,
            reason_code="vendor_not_on_allowlist",
            message=f"Vendor '{counterparty}' is not on the approved vendor list.",
            next_step="Request vendor approval before proceeding.",
        )
    return RuleResult(triggered=False)


def _eval_blocked_payment_rails(*, rule_id: str, rule_description: str, params: dict,
                                payment_method: str | None,
                                **kwargs: Any) -> RuleResult:
    """Block specific payment methods."""
    if payment_method is None:
        return RuleResult(triggered=False)

    blocked_rails = params.get("rails", [])
    if payment_method.lower() in [r.lower() for r in blocked_rails]:
        return RuleResult(
            triggered=True,
            decision="block",
            rule_id=rule_id,
            rule_description=rule_description,
            reason_code="blocked_payment_rail",
            message=f"Payment method '{payment_method}' is blocked by policy.",
            next_step="Use an approved payment method (e.g., card or ACH).",
        )
    return RuleResult(triggered=False)


def _eval_discount_cap(*, rule_id: str, rule_description: str, params: dict,
                       action_type: str, metadata: dict,
                       **kwargs: Any) -> RuleResult:
    """Block discounts above a percentage cap. Only applies to discount."""
    if action_type != "discount":
        return RuleResult(triggered=False)

    max_percent = params.get("max_percent", 100)
    discount_percent = metadata.get("discount_percent")

    if discount_percent is None:
        return RuleResult(triggered=False)

    if discount_percent > max_percent:
        return RuleResult(
            triggered=True,
            decision="block",
            rule_id=rule_id,
            rule_description=rule_description,
            reason_code="discount_cap_exceeded",
            message=f"Discount of {discount_percent}% exceeds the policy cap of {max_percent}%.",
            next_step=f"Reduce the discount to {max_percent}% or below.",
        )
    return RuleResult(triggered=False)


def _eval_geography_block(*, rule_id: str, rule_description: str, params: dict,
                          metadata: dict, **kwargs: Any) -> RuleResult:
    """Block actions from certain countries."""
    blocked_countries = params.get("blocked_countries", [])
    country = metadata.get("country", "")

    if country and country.upper() in [c.upper() for c in blocked_countries]:
        return RuleResult(
            triggered=True,
            decision="block",
            rule_id=rule_id,
            rule_description=rule_description,
            reason_code="blocked_geography",
            message=f"Actions from country '{country}' are blocked by policy.",
            next_step="This geographic region is not permitted.",
        )
    return RuleResult(triggered=False)


def _eval_time_restriction(*, rule_id: str, rule_description: str, params: dict,
                           evaluation_time: datetime,
                           **kwargs: Any) -> RuleResult:
    """Block actions outside allowed days/hours."""
    allowed_days = params.get("allowed_days", [])
    allowed_hours_str = params.get("allowed_hours_utc", "00:00-23:59")

    # Parse day name — mon, tue, wed, thu, fri, sat, sun
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    current_day = day_names[evaluation_time.weekday()]

    if allowed_days and current_day not in [d.lower() for d in allowed_days]:
        return RuleResult(
            triggered=True,
            decision="block",
            rule_id=rule_id,
            rule_description=rule_description,
            reason_code="time_restriction_violated",
            message=f"Actions on {current_day.capitalize()} are outside the allowed window.",
            next_step="Retry during permitted business days.",
        )

    # Parse hour range — e.g. "09:00-17:00"
    try:
        start_str, end_str = allowed_hours_str.split("-")
        start_hour = int(start_str.split(":")[0])
        end_hour = int(end_str.split(":")[0])
        current_hour = evaluation_time.hour

        if current_hour < start_hour or current_hour >= end_hour:
            return RuleResult(
                triggered=True,
                decision="block",
                rule_id=rule_id,
                rule_description=rule_description,
                reason_code="time_restriction_violated",
                message=(
                    f"Actions at {current_hour:02d}:00 UTC are outside the allowed window "
                    f"of {start_str}-{end_str} UTC."
                ),
                next_step=f"Retry between {start_str} and {end_str} UTC.",
            )
    except (ValueError, IndexError):
        logger.warning("Invalid allowed_hours_utc format: '%s'", allowed_hours_str)

    return RuleResult(triggered=False)


def _eval_escalate_if(*, rule_id: str, rule_description: str, params: dict,
                      action_type: str, amount: float,
                      **kwargs: Any) -> RuleResult:
    """Escalate (not block) if amount exceeds threshold for specified action types."""
    threshold = params.get("amount_above", float("inf"))
    target_types = params.get("action_types", [])

    if action_type not in target_types:
        return RuleResult(triggered=False)

    if amount > threshold:
        return RuleResult(
            triggered=True,
            decision="escalate",
            rule_id=rule_id,
            rule_description=rule_description,
            reason_code="escalation_threshold_exceeded",
            message=(
                f"{action_type.capitalize()} of ${amount:.2f} exceeds the escalation "
                f"threshold of ${threshold:.2f}."
            ),
            next_step="Route to human approval before proceeding.",
        )
    return RuleResult(triggered=False)


# ==============================================================
# Rule type → evaluator function mapping
# ==============================================================

RULE_EVALUATORS: dict[str, Any] = {
    "max_amount": _eval_max_amount,
    "refund_age_limit": _eval_refund_age_limit,
    "blocked_categories": _eval_blocked_categories,
    "vendor_allowlist": _eval_vendor_allowlist,
    "blocked_payment_rails": _eval_blocked_payment_rails,
    "discount_cap": _eval_discount_cap,
    "geography_block": _eval_geography_block,
    "time_restriction": _eval_time_restriction,
    "escalate_if": _eval_escalate_if,
}
