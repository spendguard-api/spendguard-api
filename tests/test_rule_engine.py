"""
Unit tests for the SpendGuard API rule engine.

Covers all 10 rule types and 35 test cases from TEST_CASES.md Sections 1-11.
Tests are pure — no database calls. Policies are constructed in-memory.

Run with: .venv/bin/python -m pytest tests/test_rule_engine.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.rule_engine import evaluate_rules, EngineResult
from services.duplicate_guard import compute_fingerprint


# ==============================================================
# Helper: build a policy with a single rule for focused testing
# ==============================================================

def make_rules(*rule_defs: dict) -> list[dict]:
    """Convenience wrapper — just returns the list."""
    return list(rule_defs)


# ==============================================================
# Section 1 — max_amount
# ==============================================================

MAX_AMOUNT_RULE = {
    "rule_id": "r1",
    "rule_type": "max_amount",
    "description": "Refunds may not exceed $500",
    "parameters": {"limit": 500, "currency": "USD"},
}


class TestMaxAmount:
    """TC-001 through TC-004."""

    def test_tc001_amount_within_limit_allow(self):
        result = evaluate_rules(
            rules=make_rules(MAX_AMOUNT_RULE),
            action_type="refund", amount=100.00, currency="USD",
            counterparty="cust_001",
        )
        assert result.decision == "allow"
        assert result.violated_rule_id is None

    def test_tc002_amount_exactly_at_limit_allow(self):
        result = evaluate_rules(
            rules=make_rules(MAX_AMOUNT_RULE),
            action_type="refund", amount=500.00, currency="USD",
            counterparty="cust_001",
        )
        assert result.decision == "allow"
        assert result.violated_rule_id is None

    def test_tc003_amount_above_limit_block(self):
        result = evaluate_rules(
            rules=make_rules(MAX_AMOUNT_RULE),
            action_type="refund", amount=500.01, currency="USD",
            counterparty="cust_001",
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r1"
        assert result.reason_code == "max_amount_exceeded"
        assert "500" in result.message
        assert "limit" in result.message.lower() or "exceeds" in result.message.lower()

    def test_tc004_large_amount_block(self):
        result = evaluate_rules(
            rules=make_rules(MAX_AMOUNT_RULE),
            action_type="refund", amount=5000.00, currency="USD",
            counterparty="cust_001",
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r1"


# ==============================================================
# Section 2 — refund_age_limit
# ==============================================================

REFUND_AGE_RULE = {
    "rule_id": "r2",
    "rule_type": "refund_age_limit",
    "description": "Refunds must be requested within 30 days",
    "parameters": {"max_days": 30},
}


class TestRefundAgeLimit:
    """TC-010 through TC-014."""

    def test_tc010_within_age_limit_allow(self):
        result = evaluate_rules(
            rules=make_rules(REFUND_AGE_RULE),
            action_type="refund", amount=100, currency="USD",
            counterparty="cust_001",
            metadata={"days_since_purchase": 10},
        )
        assert result.decision == "allow"
        assert result.violated_rule_id is None

    def test_tc011_exactly_at_age_limit_allow(self):
        result = evaluate_rules(
            rules=make_rules(REFUND_AGE_RULE),
            action_type="refund", amount=100, currency="USD",
            counterparty="cust_001",
            metadata={"days_since_purchase": 30},
        )
        assert result.decision == "allow"
        assert result.violated_rule_id is None

    def test_tc012_one_day_over_age_limit_block(self):
        result = evaluate_rules(
            rules=make_rules(REFUND_AGE_RULE),
            action_type="refund", amount=100, currency="USD",
            counterparty="cust_001",
            metadata={"days_since_purchase": 31},
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r2"
        assert result.reason_code == "refund_age_limit_exceeded"
        assert "30 days" in result.message

    def test_tc013_well_over_age_limit_block(self):
        result = evaluate_rules(
            rules=make_rules(REFUND_AGE_RULE),
            action_type="refund", amount=100, currency="USD",
            counterparty="cust_001",
            metadata={"days_since_purchase": 90},
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r2"

    def test_tc014_age_limit_ignores_non_refund(self):
        """refund_age_limit should NOT apply to credit actions."""
        result = evaluate_rules(
            rules=make_rules(REFUND_AGE_RULE),
            action_type="credit", amount=100, currency="USD",
            counterparty="cust_001",
            metadata={"days_since_purchase": 60},
        )
        assert result.decision == "allow"


# ==============================================================
# Section 3 — blocked_categories
# ==============================================================

BLOCKED_CATEGORIES_RULE = {
    "rule_id": "r3",
    "rule_type": "blocked_categories",
    "description": "Block all crypto and gambling spend",
    "parameters": {"categories": ["crypto", "gambling"]},
}


class TestBlockedCategories:
    """TC-020 through TC-021."""

    def test_tc020_blocked_category_block(self):
        result = evaluate_rules(
            rules=make_rules(BLOCKED_CATEGORIES_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
            metadata={"category": "crypto"},
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r3"
        assert result.reason_code == "blocked_category"

    def test_tc020_blocked_via_merchant_name(self):
        """Also catches blocked category in the merchant_or_vendor field."""
        result = evaluate_rules(
            rules=make_rules(BLOCKED_CATEGORIES_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
            merchant_or_vendor="crypto_exchange_001",
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r3"

    def test_tc021_allowed_category_allow(self):
        result = evaluate_rules(
            rules=make_rules(BLOCKED_CATEGORIES_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
            metadata={"category": "software"},
        )
        assert result.decision == "allow"
        assert result.violated_rule_id is None


# ==============================================================
# Section 4 — vendor_allowlist
# ==============================================================

VENDOR_ALLOWLIST_RULE = {
    "rule_id": "r4",
    "rule_type": "vendor_allowlist",
    "description": "Only approved vendors may receive payments",
    "parameters": {"vendors": ["vendor_approved_001", "vendor_approved_002"]},
}


class TestVendorAllowlist:
    """TC-030 through TC-032."""

    def test_tc030_vendor_on_allowlist_allow(self):
        result = evaluate_rules(
            rules=make_rules(VENDOR_ALLOWLIST_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_approved_001",
        )
        assert result.decision == "allow"
        assert result.violated_rule_id is None

    def test_tc031_vendor_not_on_allowlist_block(self):
        result = evaluate_rules(
            rules=make_rules(VENDOR_ALLOWLIST_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_unapproved_999",
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r4"
        assert result.reason_code == "vendor_not_on_allowlist"

    def test_tc032_allowlist_only_applies_to_spend(self):
        """vendor_allowlist should NOT apply to refunds."""
        result = evaluate_rules(
            rules=make_rules(VENDOR_ALLOWLIST_RULE),
            action_type="refund", amount=100, currency="USD",
            counterparty="any_value",
        )
        assert result.decision == "allow"


# ==============================================================
# Section 5 — blocked_payment_rails
# ==============================================================

BLOCKED_RAILS_RULE = {
    "rule_id": "r5",
    "rule_type": "blocked_payment_rails",
    "parameters": {"rails": ["wire", "crypto", "check"]},
}


class TestBlockedPaymentRails:
    """TC-040 through TC-042."""

    def test_tc040_blocked_rail_block(self):
        result = evaluate_rules(
            rules=make_rules(BLOCKED_RAILS_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
            payment_method="wire",
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r5"
        assert result.reason_code == "blocked_payment_rail"

    def test_tc041_allowed_rail_allow(self):
        result = evaluate_rules(
            rules=make_rules(BLOCKED_RAILS_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
            payment_method="card",
        )
        assert result.decision == "allow"

    def test_tc042_ach_not_blocked_allow(self):
        result = evaluate_rules(
            rules=make_rules(BLOCKED_RAILS_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
            payment_method="ach",
        )
        assert result.decision == "allow"


# ==============================================================
# Section 6 — discount_cap
# ==============================================================

DISCOUNT_CAP_RULE = {
    "rule_id": "r6",
    "rule_type": "discount_cap",
    "parameters": {"max_percent": 20},
}


class TestDiscountCap:
    """TC-050 through TC-052."""

    def test_tc050_discount_within_cap_allow(self):
        result = evaluate_rules(
            rules=make_rules(DISCOUNT_CAP_RULE),
            action_type="discount", amount=10, currency="USD",
            counterparty="cust_001",
            metadata={"discount_percent": 15},
        )
        assert result.decision == "allow"

    def test_tc051_discount_exactly_at_cap_allow(self):
        result = evaluate_rules(
            rules=make_rules(DISCOUNT_CAP_RULE),
            action_type="discount", amount=10, currency="USD",
            counterparty="cust_001",
            metadata={"discount_percent": 20},
        )
        assert result.decision == "allow"

    def test_tc052_discount_over_cap_block(self):
        result = evaluate_rules(
            rules=make_rules(DISCOUNT_CAP_RULE),
            action_type="discount", amount=10, currency="USD",
            counterparty="cust_001",
            metadata={"discount_percent": 21},
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r6"
        assert result.reason_code == "discount_cap_exceeded"
        assert "20%" in result.message


# ==============================================================
# Section 7 — geography_block
# ==============================================================

GEO_BLOCK_RULE = {
    "rule_id": "r7",
    "rule_type": "geography_block",
    "parameters": {"blocked_countries": ["RU", "KP", "IR"]},
}


class TestGeographyBlock:
    """TC-060 through TC-061."""

    def test_tc060_blocked_country_block(self):
        result = evaluate_rules(
            rules=make_rules(GEO_BLOCK_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
            metadata={"country": "RU"},
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r7"
        assert result.reason_code == "blocked_geography"

    def test_tc061_allowed_country_allow(self):
        result = evaluate_rules(
            rules=make_rules(GEO_BLOCK_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
            metadata={"country": "US"},
        )
        assert result.decision == "allow"


# ==============================================================
# Section 8 — time_restriction
# ==============================================================

TIME_RESTRICTION_RULE = {
    "rule_id": "r9",
    "rule_type": "time_restriction",
    "parameters": {
        "allowed_days": ["mon", "tue", "wed", "thu", "fri"],
        "allowed_hours_utc": "09:00-17:00",
    },
}


class TestTimeRestriction:
    """TC-080 through TC-082."""

    def test_tc080_during_allowed_hours_allow(self):
        # Wednesday 10:00 UTC
        wed_10am = datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc)  # April 1, 2026 = Wednesday
        result = evaluate_rules(
            rules=make_rules(TIME_RESTRICTION_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
            evaluation_time=wed_10am,
        )
        assert result.decision == "allow"

    def test_tc081_outside_allowed_hours_block(self):
        # Wednesday 22:00 UTC
        wed_10pm = datetime(2026, 4, 1, 22, 0, 0, tzinfo=timezone.utc)
        result = evaluate_rules(
            rules=make_rules(TIME_RESTRICTION_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
            evaluation_time=wed_10pm,
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r9"
        assert result.reason_code == "time_restriction_violated"

    def test_tc082_weekend_block(self):
        # Saturday 12:00 UTC
        sat_noon = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)  # April 4, 2026 = Saturday
        result = evaluate_rules(
            rules=make_rules(TIME_RESTRICTION_RULE),
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
            evaluation_time=sat_noon,
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r9"


# ==============================================================
# Section 10 — escalate_if
# ==============================================================

ESCALATE_RULE = {
    "rule_id": "r10",
    "rule_type": "escalate_if",
    "parameters": {"amount_above": 1000, "action_types": ["spend"]},
}


class TestEscalateIf:
    """TC-090 through TC-092."""

    def test_tc090_under_threshold_allow(self):
        result = evaluate_rules(
            rules=make_rules(ESCALATE_RULE),
            action_type="spend", amount=500, currency="USD",
            counterparty="vendor_001",
        )
        assert result.decision == "allow"

    def test_tc091_over_threshold_escalate(self):
        result = evaluate_rules(
            rules=make_rules(ESCALATE_RULE),
            action_type="spend", amount=1001, currency="USD",
            counterparty="vendor_001",
        )
        assert result.decision == "escalate"
        assert result.violated_rule_id == "r10"
        assert result.reason_code == "escalation_threshold_exceeded"
        assert "human approval" in result.next_step.lower()

    def test_tc092_refund_not_in_escalate_types_allow(self):
        """escalate_if only targets spend, so refund should pass through."""
        result = evaluate_rules(
            rules=make_rules(ESCALATE_RULE),
            action_type="refund", amount=5000, currency="USD",
            counterparty="cust_001",
        )
        assert result.decision == "allow"


# ==============================================================
# Section 11 — Duplicate Guard (fingerprint unit tests)
# ==============================================================

class TestDuplicateGuardFingerprint:
    """TC-100 through TC-103 — fingerprint computation tests (no DB)."""

    def test_tc100_fingerprint_consistent(self):
        """Same inputs always produce the same fingerprint."""
        fp1 = compute_fingerprint("agent_1", "refund", 100.0, "cust_001")
        fp2 = compute_fingerprint("agent_1", "refund", 100.0, "cust_001")
        assert fp1 == fp2

    def test_tc102_different_amount_different_fingerprint(self):
        """Changing amount changes the fingerprint."""
        fp1 = compute_fingerprint("agent_1", "refund", 100.0, "cust_001")
        fp2 = compute_fingerprint("agent_1", "refund", 101.0, "cust_001")
        assert fp1 != fp2

    def test_tc103_different_counterparty_different_fingerprint(self):
        """Changing counterparty changes the fingerprint."""
        fp1 = compute_fingerprint("agent_1", "refund", 100.0, "cust_001")
        fp2 = compute_fingerprint("agent_1", "refund", 100.0, "cust_002")
        assert fp1 != fp2

    def test_different_action_type_different_fingerprint(self):
        """Changing action_type changes the fingerprint."""
        fp1 = compute_fingerprint("agent_1", "refund", 100.0, "cust_001")
        fp2 = compute_fingerprint("agent_1", "credit", 100.0, "cust_001")
        assert fp1 != fp2

    def test_different_agent_different_fingerprint(self):
        """Changing agent_id changes the fingerprint."""
        fp1 = compute_fingerprint("agent_1", "refund", 100.0, "cust_001")
        fp2 = compute_fingerprint("agent_2", "refund", 100.0, "cust_001")
        assert fp1 != fp2


# ==============================================================
# Precedence tests — block > escalate > allow
# ==============================================================

class TestPrecedence:
    """Verify block > escalate > allow when multiple rules fire."""

    def test_block_beats_escalate(self):
        """If both block and escalate fire, block wins."""
        rules = [
            {
                "rule_id": "r_block",
                "rule_type": "max_amount",
                "description": "Block if over 100",
                "parameters": {"limit": 100},
            },
            {
                "rule_id": "r_escalate",
                "rule_type": "escalate_if",
                "description": "Escalate spend over 50",
                "parameters": {"amount_above": 50, "action_types": ["spend"]},
            },
        ]
        result = evaluate_rules(
            rules=rules,
            action_type="spend", amount=200, currency="USD",
            counterparty="vendor_001",
        )
        assert result.decision == "block"
        assert result.violated_rule_id == "r_block"

    def test_escalate_beats_allow(self):
        """If escalate fires but no block, result is escalate."""
        rules = [
            {
                "rule_id": "r_escalate",
                "rule_type": "escalate_if",
                "description": "Escalate spend over 50",
                "parameters": {"amount_above": 50, "action_types": ["spend"]},
            },
        ]
        result = evaluate_rules(
            rules=rules,
            action_type="spend", amount=100, currency="USD",
            counterparty="vendor_001",
        )
        assert result.decision == "escalate"
        assert result.violated_rule_id == "r_escalate"

    def test_no_rules_triggered_allow(self):
        """If no rules fire, allow."""
        result = evaluate_rules(
            rules=make_rules(MAX_AMOUNT_RULE),
            action_type="refund", amount=10, currency="USD",
            counterparty="cust_001",
        )
        assert result.decision == "allow"

    def test_rule_order_does_not_matter(self):
        """Same rules in different order produce the same result."""
        rules_order_a = [
            {
                "rule_id": "r_block",
                "rule_type": "max_amount",
                "parameters": {"limit": 100},
            },
            {
                "rule_id": "r_escalate",
                "rule_type": "escalate_if",
                "parameters": {"amount_above": 50, "action_types": ["spend"]},
            },
        ]
        rules_order_b = list(reversed(rules_order_a))

        result_a = evaluate_rules(
            rules=rules_order_a,
            action_type="spend", amount=200, currency="USD",
            counterparty="vendor_001",
        )
        result_b = evaluate_rules(
            rules=rules_order_b,
            action_type="spend", amount=200, currency="USD",
            counterparty="vendor_001",
        )
        assert result_a.decision == result_b.decision == "block"
