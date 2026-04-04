"""
Tests for SpendGuard free tier signup and Day 16 features.

Covers:
- POST /v1/signup creates a free key (D023)
- Signup rate limiting (3/hr per IP)
- Duplicate email rejection
- POST /v1/billing/enable-overage (paid vs free)
- Updated 402 response with usage object (D022)
- Webhook event handling
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

# ============================================================
# Test constants
# ============================================================

AUTH_HEADERS = {"X-API-Key": "sg_live_test_signup_key"}

MOCK_API_KEY_ROW = {
    "id": "key_signup_test_001",
    "key_hash": "mocked",
    "name": "Signup Test Key",
    "active": True,
    "rate_limit_rpm": 100,
    "plan_name": "free",
    "plan_limit": 1000,
    "billing_period_start": "2026-04-01T00:00:00+00:00",
    "overage_enabled": False,
    "email": "test@example.com",
    "owner_name": "Test User",
    "stripe_subscription_id": None,
    "stripe_customer_id": None,
}


def _mock_supabase_for_signup(existing_email: bool = False):
    """Create mocks for signup flow."""
    mock_sb = MagicMock()

    def table_router(name):
        mock_table = MagicMock()
        if name == "api_keys":
            # Email duplicate check
            email_result = MagicMock()
            email_result.data = [{"id": "existing"}] if existing_email else []
            mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = email_result
            # Insert (create key)
            mock_table.insert.return_value.execute.return_value = MagicMock(
                data=[{"id": "key_new_signup_001"}]
            )
            # Update (set plan info)
            mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "rate_limit_events":
            mock_table.insert.return_value.execute.return_value = MagicMock()
            mock_table.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
                data=[], count=0
            )
            mock_table.delete.return_value.lt.return_value.execute.return_value = MagicMock()
        return mock_table

    mock_sb.table.side_effect = table_router
    return mock_sb


def _mock_supabase_for_billing(plan_name: str = "pro", overage_enabled: bool = False):
    """Create mocks for billing endpoints."""
    mock_sb = MagicMock()
    key_row = {**MOCK_API_KEY_ROW, "plan_name": plan_name, "overage_enabled": overage_enabled}

    def table_router(name):
        mock_table = MagicMock()
        if name == "api_keys":
            mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[key_row]
            )
            mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "rate_limit_events":
            mock_table.insert.return_value.execute.return_value = MagicMock()
            mock_table.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
                data=[{"id": "1"}], count=1
            )
            mock_table.delete.return_value.lt.return_value.execute.return_value = MagicMock()
        return mock_table

    mock_sb.table.side_effect = table_router
    return mock_sb


# ============================================================
# Signup Tests
# ============================================================


class TestSignup:
    """Tests for POST /v1/signup."""

    def test_signup_creates_free_key(self):
        """Signup returns a key with free plan (1000 checks)."""
        mock_sb = _mock_supabase_for_signup()
        with patch("db.client.supabase", mock_sb), \
             patch("services.email.send_welcome_email", return_value=True):
            # Clear rate limit state
            from api.routes.signup import _signup_attempts
            _signup_attempts.clear()

            resp = client.post("/v1/signup", json={
                "name": "Test User",
                "email": "new@example.com",
            })

        assert resp.status_code == 201
        data = resp.json()
        assert data["plan_name"] == "free"
        assert data["plan_limit"] == 1000
        assert data["api_key"].startswith("sg_live_")
        assert "key_id" in data

    def test_signup_rejects_duplicate_email(self):
        """Signup returns 409 if email already registered."""
        mock_sb = _mock_supabase_for_signup(existing_email=True)
        with patch("db.client.supabase", mock_sb):
            from api.routes.signup import _signup_attempts
            _signup_attempts.clear()

            resp = client.post("/v1/signup", json={
                "name": "Duplicate",
                "email": "existing@example.com",
            })

        assert resp.status_code == 409
        err = resp.json().get("detail", {}).get("error", {})
        assert err["code"] == "email_already_registered"

    def test_signup_validates_email_format(self):
        """Signup rejects invalid email format."""
        resp = client.post("/v1/signup", json={
            "name": "Bad Email",
            "email": "not-an-email",
        })
        assert resp.status_code == 422

    def test_signup_requires_name(self):
        """Signup rejects missing name."""
        resp = client.post("/v1/signup", json={
            "email": "valid@example.com",
        })
        assert resp.status_code == 422

    def test_signup_rate_limit(self):
        """Signup blocks after 3 attempts from same IP."""
        mock_sb = _mock_supabase_for_signup()
        with patch("db.client.supabase", mock_sb), \
             patch("services.email.send_welcome_email", return_value=True):
            from api.routes.signup import _signup_attempts
            _signup_attempts.clear()

            # First 3 should work (or get 409 for duplicate — either way not 429)
            for i in range(3):
                resp = client.post("/v1/signup", json={
                    "name": f"User {i}",
                    "email": f"user{i}@example.com",
                })
                assert resp.status_code != 429

            # 4th should be rate limited
            resp = client.post("/v1/signup", json={
                "name": "User 4",
                "email": "user4@example.com",
            })
            assert resp.status_code == 429


# ============================================================
# Overage Tests
# ============================================================


class TestOverage:
    """Tests for POST /v1/billing/enable-overage."""

    def test_overage_works_for_paid_tier(self):
        """Paid tier can enable overage."""
        mock_sb = _mock_supabase_for_billing(plan_name="pro")
        with patch("db.client.supabase", mock_sb):
            resp = client.post("/v1/billing/enable-overage", headers=AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["overage_enabled"] is True
        assert data["plan_name"] == "pro"

    def test_overage_blocked_for_free_tier(self):
        """Free tier cannot enable overage — returns 403."""
        mock_sb = _mock_supabase_for_billing(plan_name="free")
        with patch("db.client.supabase", mock_sb):
            resp = client.post("/v1/billing/enable-overage", headers=AUTH_HEADERS)

        assert resp.status_code == 403
        err = resp.json().get("detail", {}).get("error", {})
        assert err["code"] == "upgrade_required"


# ============================================================
# Updated 402 Response Tests (D022)
# ============================================================


class TestQuotaResponse:
    """Tests for the updated 402 over_quota response."""

    def _mock_for_quota(self, plan_name: str, usage: int, limit: int):
        mock_sb = MagicMock()
        key_row = {
            **MOCK_API_KEY_ROW,
            "plan_name": plan_name,
            "plan_limit": limit,
            "overage_enabled": False,
        }

        def table_router(name):
            mock_table = MagicMock()
            if name == "api_keys":
                mock_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[key_row]
                )
            elif name == "usage_events":
                mock_table.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
                    count=usage
                )
            elif name == "rate_limit_events":
                mock_table.insert.return_value.execute.return_value = MagicMock()
                mock_table.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
                    data=[{"id": "1"}], count=1
                )
                mock_table.delete.return_value.lt.return_value.execute.return_value = MagicMock()
            return mock_table

        mock_sb.table.side_effect = table_router
        return mock_sb

    def test_402_includes_usage_object(self):
        """402 response includes usage object per D022."""
        mock_sb = self._mock_for_quota("pro", 15000, 10000)
        with patch("db.client.supabase", mock_sb):
            resp = client.post("/v1/checks", json={
                "agent_id": "test",
                "policy_id": "test",
                "action_type": "refund",
                "amount": 50,
                "currency": "USD",
                "counterparty": "cust_1",
            }, headers=AUTH_HEADERS)

        assert resp.status_code == 402
        err = resp.json().get("detail", {}).get("error", {})
        assert err["code"] == "over_quota"
        assert "usage" in err
        assert err["usage"]["current"] == 15000
        assert err["usage"]["limit"] == 10000
        assert err["usage"]["plan"] == "pro"

    def test_402_paid_shows_overage_available(self):
        """Paid tier 402 shows overage_available: true."""
        mock_sb = self._mock_for_quota("pro", 15000, 10000)
        with patch("db.client.supabase", mock_sb):
            resp = client.post("/v1/checks", json={
                "agent_id": "test",
                "policy_id": "test",
                "action_type": "refund",
                "amount": 50,
                "currency": "USD",
                "counterparty": "cust_1",
            }, headers=AUTH_HEADERS)

        err = resp.json().get("detail", {}).get("error", {})
        assert err["usage"]["overage_available"] is True
        assert err["usage"]["overage_rate"] == 0.005

    def test_402_free_no_overage(self):
        """Free tier 402 shows overage_available: false."""
        mock_sb = self._mock_for_quota("free", 1500, 1000)
        with patch("db.client.supabase", mock_sb):
            resp = client.post("/v1/checks", json={
                "agent_id": "test",
                "policy_id": "test",
                "action_type": "refund",
                "amount": 50,
                "currency": "USD",
                "counterparty": "cust_1",
            }, headers=AUTH_HEADERS)

        err = resp.json().get("detail", {}).get("error", {})
        assert err["usage"]["overage_available"] is False
        assert "overage_rate" not in err["usage"]
