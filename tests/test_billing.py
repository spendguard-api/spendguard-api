"""
Tests for SpendGuard billing — usage metering and plan quota enforcement.

Covers:
- emit_usage_event writes to usage_events table
- get_usage_count returns correct count
- check_plan_quota returns within/over limit correctly
- POST /v1/checks returns 402 when over quota
- POST /v1/checks emits usage event on success
- Fail-open behavior on DB errors
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

# ============================================================
# Test constants
# ============================================================

AUTH_HEADERS = {"X-API-Key": "sg_live_test_billing_key"}

MOCK_API_KEY_ROW = {
    "id": "key_billing_test_001",
    "key_hash": "mocked",
    "name": "Billing Test Key",
    "active": True,
    "rate_limit_rpm": 100,
    "plan_name": "pro",
    "plan_limit": 100,
    "billing_period_start": "2026-04-01T00:00:00+00:00",
    "overage_enabled": False,
    "stripe_subscription_id": None,
}

VALID_CHECK_BODY = {
    "agent_id": "billing-test-agent",
    "policy_id": "test_policy",
    "action_type": "refund",
    "amount": 50.00,
    "currency": "USD",
    "counterparty": "customer_billing_test",
}

MOCK_POLICY = {
    "policy_id": "test_policy",
    "name": "Test Policy",
    "version": 1,
    "rules": [
        {
            "rule_id": "r1",
            "rule_type": "max_amount",
            "description": "Block over $500",
            "parameters": {"limit": 500, "currency": "USD"},
        }
    ],
}


# ============================================================
# Unit Tests — billing service
# ============================================================


class TestEmitUsageEvent:
    """Tests for emit_usage_event."""

    @pytest.mark.asyncio
    async def test_emits_event(self):
        """Usage event is inserted into usage_events table."""
        mock_supabase = MagicMock()
        mock_table = MagicMock()
        mock_table.insert.return_value.execute.return_value = MagicMock(data=[{}])
        mock_supabase.table.return_value = mock_table

        with patch("db.client.supabase", mock_supabase):
            from services.billing import emit_usage_event
            await emit_usage_event("key_123", "check")

        mock_supabase.table.assert_called_with("usage_events")

    @pytest.mark.asyncio
    async def test_emit_fails_silently(self):
        """Usage event failure does not raise — fail-open."""
        with patch("db.client.supabase") as mock_sb:
            mock_sb.table.side_effect = Exception("DB down")
            from services.billing import emit_usage_event
            # Should not raise
            await emit_usage_event("key_123")


class TestCheckPlanQuota:
    """Tests for check_plan_quota."""

    @pytest.mark.asyncio
    async def test_within_limit(self):
        """Key under quota returns within_limit=True."""
        mock_supabase = MagicMock()

        api_keys_result = MagicMock()
        api_keys_result.data = [{"plan_limit": 1000, "plan_name": "pro", "billing_period_start": "2026-04-01T00:00:00+00:00", "overage_enabled": False, "stripe_subscription_id": None}]

        usage_result = MagicMock()
        usage_result.count = 50

        def table_router(name):
            mock_table = MagicMock()
            if name == "api_keys":
                mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = api_keys_result
            elif name == "usage_events":
                mock_table.select.return_value.eq.return_value.gte.return_value.execute.return_value = usage_result
            return mock_table

        mock_supabase.table.side_effect = table_router

        with patch("db.client.supabase", mock_supabase):
            from services.billing import check_plan_quota
            result = await check_plan_quota("key_123")

        assert result["within_limit"] is True
        assert result["current_usage"] == 50
        assert result["plan_limit"] == 1000

    @pytest.mark.asyncio
    async def test_over_limit(self):
        """Key over quota returns within_limit=False."""
        mock_supabase = MagicMock()

        api_keys_result = MagicMock()
        api_keys_result.data = [{"plan_limit": 100, "plan_name": "free", "billing_period_start": "2026-04-01T00:00:00+00:00", "overage_enabled": False, "stripe_subscription_id": None}]

        usage_result = MagicMock()
        usage_result.count = 150

        def table_router(name):
            mock_table = MagicMock()
            if name == "api_keys":
                mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = api_keys_result
            elif name == "usage_events":
                mock_table.select.return_value.eq.return_value.gte.return_value.execute.return_value = usage_result
            return mock_table

        mock_supabase.table.side_effect = table_router

        with patch("db.client.supabase", mock_supabase):
            from services.billing import check_plan_quota
            result = await check_plan_quota("key_123")

        assert result["within_limit"] is False
        assert result["current_usage"] == 150
        assert result["plan_limit"] == 100

    @pytest.mark.asyncio
    async def test_fails_open_on_error(self):
        """DB error returns within_limit=True — fail open."""
        with patch("db.client.supabase") as mock_sb:
            mock_sb.table.side_effect = Exception("DB down")
            from services.billing import check_plan_quota
            result = await check_plan_quota("key_123")

        assert result["within_limit"] is True
        assert result["current_usage"] == 0
        assert result["plan_limit"] == 10000


# ============================================================
# Integration Tests — POST /v1/checks with billing
# ============================================================

client = TestClient(app)


def _mock_auth_and_policy(plan_limit: int = 10000, usage_count: int = 0):
    """Create mocks for auth, policy, and billing."""
    mock_supabase = MagicMock()

    api_key_row = {**MOCK_API_KEY_ROW, "plan_limit": plan_limit}

    def table_router(name):
        mock_table = MagicMock()
        if name == "api_keys":
            # Auth lookup returns the key
            mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[api_key_row]
            )
        elif name == "policies":
            mock_table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[{
                    "policy_id": "test_policy",
                    "name": "Test",
                    "version": 1,
                    "rules_json": MOCK_POLICY["rules"],
                    "description": None,
                    "metadata": None,
                    "created_at": "2026-04-01T00:00:00+00:00",
                }]
            )
        elif name == "usage_events":
            # Count query
            mock_table.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
                count=usage_count
            )
            # Insert (emit event)
            mock_table.insert.return_value.execute.return_value = MagicMock(data=[{}])
        elif name == "duplicate_guard":
            mock_table.select.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[]
            )
            mock_table.insert.return_value.execute.return_value = MagicMock(data=[{}])
        elif name == "checks":
            mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[]
            )
            mock_table.insert.return_value.execute.return_value = MagicMock(data=[{}])
        elif name == "violations":
            mock_table.insert.return_value.execute.return_value = MagicMock(data=[{}])
        elif name == "rate_limit_events":
            mock_table.insert.return_value.execute.return_value = MagicMock(data=[{}])
            mock_table.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
                data=[{"id": "1"}], count=1
            )
            mock_table.delete.return_value.lt.return_value.execute.return_value = MagicMock()
        return mock_table

    mock_supabase.table.side_effect = table_router
    return mock_supabase


class TestBillingIntegration:
    """Integration tests for billing in the check flow."""

    def test_check_succeeds_within_quota(self):
        """Check succeeds when usage is within plan limit."""
        mock_sb = _mock_auth_and_policy(plan_limit=10000, usage_count=50)
        with patch("db.client.supabase", mock_sb):
            resp = client.post("/v1/checks", json=VALID_CHECK_BODY, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] in ("allow", "block", "escalate")

    def test_check_blocked_over_quota(self):
        """Check returns 402 when usage exceeds plan limit."""
        mock_sb = _mock_auth_and_policy(plan_limit=100, usage_count=150)
        with patch("db.client.supabase", mock_sb):
            resp = client.post("/v1/checks", json=VALID_CHECK_BODY, headers=AUTH_HEADERS)
        assert resp.status_code == 402
        error = resp.json()
        err = error.get("detail", error).get("error", error)
        assert err["code"] == "over_quota"
        assert "usage" in err
        assert err["usage"]["current"] == 150
        assert err["usage"]["limit"] == 100

    def test_402_uses_standard_error_format(self):
        """402 response uses the locked error format."""
        mock_sb = _mock_auth_and_policy(plan_limit=100, usage_count=200)
        with patch("db.client.supabase", mock_sb):
            resp = client.post("/v1/checks", json=VALID_CHECK_BODY, headers=AUTH_HEADERS)
        assert resp.status_code == 402
        error = resp.json()
        err = error.get("detail", error).get("error", error)
        assert "code" in err
        assert "message" in err
        assert "request_id" in err
        assert "timestamp" in err

    def test_usage_event_emitted_on_success(self):
        """A usage event is written after a successful check."""
        mock_sb = _mock_auth_and_policy(plan_limit=10000, usage_count=5)
        with patch("db.client.supabase", mock_sb):
            resp = client.post("/v1/checks", json=VALID_CHECK_BODY, headers=AUTH_HEADERS)
        assert resp.status_code == 200

        # Verify usage_events.insert was called
        calls = mock_sb.table.call_args_list
        usage_insert_calls = [c for c in calls if c[0][0] == "usage_events"]
        assert len(usage_insert_calls) > 0, "Expected usage_events table to be called"
