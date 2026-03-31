"""
Security tests for SpendGuard API.

Covers TEST_CASES.md Sections 17-19:
- Authentication (TC-160 to TC-163)
- Rate limiting (TC-170, TC-171)
- Error format (TC-180)
- Idempotency (TC-124)

Uses FastAPI TestClient with a mock Supabase layer.
Run with: .venv/bin/python -m pytest tests/test_security.py -v
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ============================================================
# Test API keys
# ============================================================

TEST_RAW_KEY = "test_key_security_suite"
TEST_KEY_HASH = hashlib.sha256(TEST_RAW_KEY.encode("utf-8")).hexdigest()
AUTH_HEADERS = {"X-API-Key": TEST_RAW_KEY}

INACTIVE_RAW_KEY = "inactive_key_security_suite"
INACTIVE_KEY_HASH = hashlib.sha256(INACTIVE_RAW_KEY.encode("utf-8")).hexdigest()

# Low RPM for rate limit tests (avoids sending 100+ requests)
TEST_RATE_LIMIT_RPM = 3


# ============================================================
# Mock Supabase with delete/lt/count support
# ============================================================

class MockSupabaseTable:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._query_chain: dict = {}
        self._is_delete: bool = False

    def select(self, *args, **kwargs) -> "MockSupabaseTable":
        self._query_chain = {"filters": []}
        self._is_delete = False
        return self

    def insert(self, row: dict) -> "MockSupabaseTable":
        if "id" not in row:
            row["id"] = str(uuid.uuid4())
        if "created_at" not in row:
            row["created_at"] = datetime.now(timezone.utc).isoformat()
        self.rows.append(row)
        self._last_inserted = row
        self._is_delete = False
        return self

    def delete(self) -> "MockSupabaseTable":
        self._query_chain = {"filters": []}
        self._is_delete = True
        return self

    def eq(self, column: str, value: Any) -> "MockSupabaseTable":
        if "filters" not in self._query_chain:
            self._query_chain["filters"] = []
        self._query_chain["filters"].append(("eq", column, value))
        return self

    def gt(self, column: str, value: Any) -> "MockSupabaseTable":
        if "filters" not in self._query_chain:
            self._query_chain["filters"] = []
        self._query_chain["filters"].append(("gt", column, value))
        return self

    def lt(self, column: str, value: Any) -> "MockSupabaseTable":
        if "filters" not in self._query_chain:
            self._query_chain["filters"] = []
        self._query_chain["filters"].append(("lt", column, value))
        return self

    def gte(self, column: str, value: Any) -> "MockSupabaseTable":
        return self

    def lte(self, column: str, value: Any) -> "MockSupabaseTable":
        return self

    def order(self, column: str, desc: bool = False) -> "MockSupabaseTable":
        return self

    def limit(self, n: int) -> "MockSupabaseTable":
        self._query_chain["_limit"] = n
        return self

    def execute(self) -> MagicMock:
        result = MagicMock()

        # Handle delete
        if self._is_delete:
            filtered = self._apply_filters(list(self.rows))
            self.rows = [r for r in self.rows if r not in filtered]
            result.data = filtered
            result.count = len(filtered)
            self._query_chain = {}
            self._is_delete = False
            return result

        # Handle insert
        if hasattr(self, "_last_inserted"):
            result.data = [self._last_inserted]
            result.count = 1
            delattr(self, "_last_inserted")
            return result

        # Handle select
        filtered = self._apply_filters(list(self.rows))
        limit_val = self._query_chain.get("_limit")
        if limit_val:
            filtered = filtered[:limit_val]
        result.data = filtered
        result.count = len(filtered)
        self._query_chain = {}
        return result

    def _apply_filters(self, rows: list[dict]) -> list[dict]:
        """Apply stored filters to a list of rows."""
        filtered = rows
        for f in self._query_chain.get("filters", []):
            op, col, val = f
            if op == "eq":
                filtered = [r for r in filtered if r.get(col) == val]
            elif op == "gt":
                filtered = [r for r in filtered if r.get(col, "") > val]
            elif op == "lt":
                filtered = [r for r in filtered if r.get(col, "") < val]
        return filtered


class MockSupabase:
    def __init__(self) -> None:
        self._tables: dict[str, MockSupabaseTable] = {}

    def table(self, name: str) -> MockSupabaseTable:
        if name not in self._tables:
            self._tables[name] = MockSupabaseTable()
        return self._tables[name]


# ============================================================
# Fixtures
# ============================================================

def seed_active_key(mock_db: MockSupabase) -> None:
    mock_db.table("api_keys").rows.append({
        "id": str(uuid.uuid4()),
        "key_hash": TEST_KEY_HASH,
        "name": "Active Test Key",
        "active": True,
        "rate_limit_rpm": TEST_RATE_LIMIT_RPM,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def seed_inactive_key(mock_db: MockSupabase) -> None:
    mock_db.table("api_keys").rows.append({
        "id": str(uuid.uuid4()),
        "key_hash": INACTIVE_KEY_HASH,
        "name": "Inactive Test Key",
        "active": False,
        "rate_limit_rpm": 100,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def seed_policy(mock_db: MockSupabase) -> None:
    mock_db.table("policies").rows.append({
        "id": str(uuid.uuid4()),
        "policy_id": "test_policy",
        "name": "Test Policy",
        "description": "Test",
        "version": 1,
        "rules_json": [
            {
                "rule_id": "r1",
                "rule_type": "max_amount",
                "description": "Block over $500",
                "parameters": {"limit": 500, "currency": "USD"},
            },
        ],
        "metadata": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


@pytest.fixture()
def mock_db():
    db = MockSupabase()
    seed_active_key(db)
    seed_inactive_key(db)
    seed_policy(db)
    return db


@pytest.fixture()
def client(mock_db):
    with patch("db.client.supabase", mock_db), \
         patch("services.policy_loader.supabase", mock_db, create=True), \
         patch("services.audit_logger.supabase", mock_db, create=True), \
         patch("services.duplicate_guard.supabase", mock_db, create=True):
        import db.client
        db.client.supabase = mock_db

        from main import app
        yield TestClient(app)


# ============================================================
# Section 17 — Authentication
# ============================================================

class TestAuthentication:
    """TC-160 to TC-163."""

    def test_tc160_missing_api_key(self, client):
        resp = client.post("/v1/checks", json={
            "agent_id": "test_agent", "policy_id": "test_policy",
            "action_type": "refund", "amount": 50.00, "currency": "USD",
            "counterparty": "cust_001",
        })
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"]["code"] == "unauthorized"

    def test_tc161_invalid_api_key(self, client):
        resp = client.post("/v1/checks", headers={"X-API-Key": "invalid_key_xyz"}, json={
            "agent_id": "test_agent", "policy_id": "test_policy",
            "action_type": "refund", "amount": 50.00, "currency": "USD",
            "counterparty": "cust_001",
        })
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"]["code"] == "unauthorized"

    def test_tc162_health_no_auth_required(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_tc163_simulate_demo_no_auth_required(self, client):
        resp = client.post("/v1/simulate", json={
            "policy_id": "test_policy",
            "actions": [{
                "agent_id": "agent_1", "policy_id": "test_policy",
                "action_type": "refund", "amount": 50.00, "currency": "USD",
                "counterparty": "cust_001",
            }],
        })
        assert resp.status_code == 200
        assert resp.json()["mode"] == "demo"

    def test_inactive_api_key_returns_401(self, client):
        resp = client.post("/v1/checks", headers={"X-API-Key": INACTIVE_RAW_KEY}, json={
            "agent_id": "test_agent", "policy_id": "test_policy",
            "action_type": "refund", "amount": 50.00, "currency": "USD",
            "counterparty": "cust_001",
        })
        assert resp.status_code == 401
        assert resp.json()["detail"]["error"]["code"] == "api_key_inactive"

    def test_valid_key_passes_auth(self, client):
        resp = client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "test_agent", "policy_id": "test_policy",
            "action_type": "refund", "amount": 50.00, "currency": "USD",
            "counterparty": "cust_001",
        })
        assert resp.status_code == 200
        assert resp.json()["decision"] == "allow"

    def test_policies_require_auth(self, client):
        resp = client.get("/v1/policies/test_policy")
        assert resp.status_code == 401

    def test_violations_require_auth(self, client):
        resp = client.get("/v1/violations")
        assert resp.status_code == 401


# ============================================================
# Section 18 — Rate Limiting (uses low RPM=3 for fast tests)
# ============================================================

class TestRateLimiting:
    """TC-170, TC-171."""

    def test_tc170_auth_rate_limit_exceeded(self, client):
        """More than RPM requests → 429."""
        # Send RPM requests (should all pass)
        for i in range(TEST_RATE_LIMIT_RPM):
            resp = client.post("/v1/checks", headers=AUTH_HEADERS, json={
                "agent_id": f"agent_{i}", "policy_id": "test_policy",
                "action_type": "refund", "amount": 50.00, "currency": "USD",
                "counterparty": f"cust_{i}",
            })
            assert resp.status_code == 200, f"Request {i+1} failed with {resp.status_code}"

        # Next request should be rate limited
        resp = client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "agent_overflow", "policy_id": "test_policy",
            "action_type": "refund", "amount": 50.00, "currency": "USD",
            "counterparty": "cust_overflow",
        })
        assert resp.status_code == 429
        detail = resp.json()["detail"]
        assert detail["error"]["code"] == "rate_limit_exceeded"
        assert "Retry-After" in resp.headers
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Reset" in resp.headers

    def test_tc171_demo_rate_limit_exceeded(self, client):
        """More than 10 simulate requests per minute from same IP → 429."""
        for i in range(10):
            resp = client.post("/v1/simulate", json={
                "policy_id": "test_policy",
                "actions": [{
                    "agent_id": f"agent_{i}", "policy_id": "test_policy",
                    "action_type": "refund", "amount": 50.00, "currency": "USD",
                    "counterparty": f"cust_{i}",
                }],
            })
            assert resp.status_code == 200, f"Request {i+1} failed with {resp.status_code}"

        resp = client.post("/v1/simulate", json={
            "policy_id": "test_policy",
            "actions": [{
                "agent_id": "agent_overflow", "policy_id": "test_policy",
                "action_type": "refund", "amount": 50.00, "currency": "USD",
                "counterparty": "cust_overflow",
            }],
        })
        assert resp.status_code == 429
        assert resp.json()["detail"]["error"]["code"] == "rate_limit_exceeded"

    def test_rate_limit_headers_present(self, client):
        """429 response includes all required rate limit headers."""
        for i in range(TEST_RATE_LIMIT_RPM + 1):
            resp = client.post("/v1/checks", headers=AUTH_HEADERS, json={
                "agent_id": f"a{i}", "policy_id": "test_policy",
                "action_type": "refund", "amount": 50.00, "currency": "USD",
                "counterparty": f"c{i}",
            })
        # Last response should be 429
        assert resp.status_code == 429
        assert int(resp.headers["Retry-After"]) > 0
        assert int(resp.headers["X-RateLimit-Limit"]) == TEST_RATE_LIMIT_RPM
        assert int(resp.headers["X-RateLimit-Remaining"]) == 0
        assert int(resp.headers["X-RateLimit-Reset"]) > 0

    def test_rate_limit_events_persist_in_db(self, mock_db, client):
        """Rate limit events are written to the rate_limit_events table."""
        client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "test", "policy_id": "test_policy",
            "action_type": "refund", "amount": 50.00, "currency": "USD",
            "counterparty": "cust_001",
        })
        events = mock_db.table("rate_limit_events").rows
        assert len(events) > 0
        assert any("key:" in e.get("limiter_key", "") for e in events)


# ============================================================
# Section 19 — Error Format
# ============================================================

class TestErrorFormat:
    """TC-180: all errors use the standard locked format."""

    def test_tc180_401_uses_standard_format(self, client):
        resp = client.post("/v1/checks", json={
            "agent_id": "test", "policy_id": "test",
            "action_type": "refund", "amount": 50, "currency": "USD",
            "counterparty": "test",
        })
        assert resp.status_code == 401
        error = resp.json()["detail"]["error"]
        assert "code" in error
        assert "message" in error
        assert "request_id" in error
        assert "timestamp" in error
        assert error["request_id"].startswith("req_")

    def test_tc180_422_uses_standard_format(self, client):
        resp = client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "test",
        })
        assert resp.status_code == 422
        error = resp.json()["error"]
        assert error["code"] == "validation_error"
        assert "message" in error
        assert "request_id" in error
        assert "timestamp" in error

    def test_tc180_404_uses_standard_format(self, client):
        resp = client.get("/v1/policies/nonexistent_id", headers=AUTH_HEADERS)
        assert resp.status_code == 404
        error = resp.json()["detail"]["error"]
        assert error["code"] == "policy_not_found"
        assert "request_id" in error
        assert "timestamp" in error


# ============================================================
# Idempotency (TC-124)
# ============================================================

class TestIdempotency:
    """TC-124: repeated request with same idempotency_key returns cached result."""

    def test_tc124_idempotency_returns_same_check_id(self, client):
        payload = {
            "agent_id": "test_agent", "policy_id": "test_policy",
            "action_type": "refund", "amount": 50.00, "currency": "USD",
            "counterparty": "cust_001", "idempotency_key": "idem_test_001",
        }
        resp1 = client.post("/v1/checks", headers=AUTH_HEADERS, json=payload)
        assert resp1.status_code == 200
        check_id_1 = resp1.json()["check_id"]

        resp2 = client.post("/v1/checks", headers=AUTH_HEADERS, json=payload)
        assert resp2.status_code == 200
        check_id_2 = resp2.json()["check_id"]

        assert check_id_1 == check_id_2

    def test_idempotency_does_not_create_duplicate_records(self, client, mock_db):
        payload = {
            "agent_id": "test_agent", "policy_id": "test_policy",
            "action_type": "refund", "amount": 50.00, "currency": "USD",
            "counterparty": "cust_001", "idempotency_key": "idem_test_002",
        }
        client.post("/v1/checks", headers=AUTH_HEADERS, json=payload)
        client.post("/v1/checks", headers=AUTH_HEADERS, json=payload)

        checks = [
            r for r in mock_db.table("checks").rows
            if r.get("idempotency_key") == "idem_test_002"
        ]
        assert len(checks) == 1
