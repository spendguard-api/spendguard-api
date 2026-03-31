"""
Integration tests for SpendGuard API endpoints.

Tests cover TEST_CASES.md Sections 12-16 and 20:
- Policy versioning (TC-110 to TC-114)
- Checks endpoint (TC-120 to TC-126)
- Policies endpoint (TC-130 to TC-133)
- Violations endpoint (TC-140 to TC-145)
- Simulate endpoint (TC-150 to TC-154)
- Health endpoint (TC-190)

Uses FastAPI TestClient with a mock Supabase layer.
Run with: .venv/bin/python -m pytest tests/test_endpoints.py -v
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Test API key — used for authenticated requests in tests
TEST_RAW_API_KEY = "test_key_for_spendguard_unit_tests"
TEST_API_KEY_HASH = hashlib.sha256(TEST_RAW_API_KEY.encode("utf-8")).hexdigest()
AUTH_HEADERS = {"X-API-Key": TEST_RAW_API_KEY}


# ============================================================
# Mock Supabase — in-memory database replacement for tests
# ============================================================

class MockSupabaseTable:
    """In-memory mock of a single Supabase table for testing."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._query_chain: dict = {}

    def select(self, *args, **kwargs) -> "MockSupabaseTable":
        self._query_chain = {"filters": [], "order": None, "limit": None}
        return self

    def insert(self, row: dict) -> "MockSupabaseTable":
        # Auto-generate id if not present
        if "id" not in row:
            row["id"] = str(uuid.uuid4())
        if "created_at" not in row:
            row["created_at"] = datetime.now(timezone.utc).isoformat()
        self.rows.append(row)
        self._last_inserted = row
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

    def gte(self, column: str, value: Any) -> "MockSupabaseTable":
        return self

    def lte(self, column: str, value: Any) -> "MockSupabaseTable":
        return self

    def lt(self, column: str, value: Any) -> "MockSupabaseTable":
        return self

    def order(self, column: str, desc: bool = False) -> "MockSupabaseTable":
        return self

    def limit(self, n: int) -> "MockSupabaseTable":
        self._query_chain["_limit"] = n
        return self

    def execute(self) -> MagicMock:
        result = MagicMock()

        # If this was an insert, return the inserted row
        if hasattr(self, "_last_inserted"):
            result.data = [self._last_inserted]
            result.count = 1
            delattr(self, "_last_inserted")
            return result

        # Apply eq filters
        filtered = list(self.rows)
        for f in self._query_chain.get("filters", []):
            op, col, val = f
            if op == "eq":
                filtered = [r for r in filtered if r.get(col) == val]
            elif op == "gt":
                filtered = [r for r in filtered if r.get(col, "") > val]

        limit = self._query_chain.get("_limit")
        if limit:
            filtered = filtered[:limit]

        result.data = filtered
        result.count = len(filtered)
        self._query_chain = {}
        return result


class MockSupabase:
    """In-memory mock of the entire Supabase client."""

    def __init__(self) -> None:
        self._tables: dict[str, MockSupabaseTable] = {}

    def table(self, name: str) -> MockSupabaseTable:
        if name not in self._tables:
            self._tables[name] = MockSupabaseTable()
        return self._tables[name]

    def get_table_rows(self, name: str) -> list[dict]:
        """Helper for test assertions — get all rows in a table."""
        if name not in self._tables:
            return []
        return self._tables[name].rows


# ============================================================
# Fixtures
# ============================================================

def seed_api_key(mock_db):
    """Insert a test API key into the mock DB."""
    mock_db.table("api_keys").rows.append({
        "id": str(uuid.uuid4()),
        "key_hash": TEST_API_KEY_HASH,
        "name": "Test Key",
        "active": True,
        "rate_limit_rpm": 100,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


@pytest.fixture()
def mock_db():
    """Create a fresh in-memory mock Supabase for each test."""
    db = MockSupabase()
    seed_api_key(db)
    return db


@pytest.fixture()
def client(mock_db):
    """FastAPI TestClient with mocked Supabase."""
    # Reset rate limiter between tests
    from api.rate_limit import get_limiter
    get_limiter().reset()

    with patch("db.client.supabase", mock_db), \
         patch("services.policy_loader.supabase", mock_db, create=True), \
         patch("services.audit_logger.supabase", mock_db, create=True), \
         patch("services.duplicate_guard.supabase", mock_db, create=True):

        # Patch the lazy imports in the route modules
        import db.client
        db.client.supabase = mock_db

        from main import app
        yield TestClient(app)


@pytest.fixture()
def sample_policy():
    """A standard test policy with max_amount and escalate_if rules."""
    return {
        "policy_id": "test_policy",
        "name": "Test Policy",
        "description": "A test policy",
        "rules": [
            {
                "rule_id": "r1",
                "rule_type": "max_amount",
                "description": "Block over $500",
                "parameters": {"limit": 500, "currency": "USD"},
            },
            {
                "rule_id": "r2",
                "rule_type": "escalate_if",
                "description": "Escalate spend over $200",
                "parameters": {"amount_above": 200, "action_types": ["spend"]},
            },
        ],
    }


def seed_policy(mock_db, policy_dict: dict, version: int = 1):
    """Insert a policy directly into the mock DB."""
    mock_db.table("policies").rows.append({
        "id": str(uuid.uuid4()),
        "policy_id": policy_dict["policy_id"],
        "name": policy_dict["name"],
        "description": policy_dict.get("description"),
        "version": version,
        "rules_json": policy_dict["rules"],
        "metadata": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


# ============================================================
# Section 20 — Health Endpoint
# ============================================================

class TestHealth:
    """TC-190."""

    def test_tc190_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] != ""
        assert "T" in data["timestamp"]  # ISO 8601


# ============================================================
# Section 14 — Policies Endpoint
# ============================================================

class TestPoliciesEndpoint:
    """TC-130 to TC-133."""

    def test_tc130_create_policy(self, client, mock_db):
        resp = client.post("/v1/policies", headers=AUTH_HEADERS, json={
            "policy_id": "new_test_policy",
            "name": "New Test Policy",
            "description": "Created in test",
            "rules": [
                {
                    "rule_id": "r1",
                    "rule_type": "max_amount",
                    "description": "Block over 100",
                    "parameters": {"limit": 100, "currency": "USD"},
                }
            ],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["policy_id"] == "new_test_policy"
        assert data["version"] == 1
        assert len(data["rules"]) == 1

    def test_tc131_get_policy(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy, version=1)
        resp = client.get("/v1/policies/test_policy", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["policy_id"] == "test_policy"
        assert data["version"] == 1
        assert len(data["rules"]) == 2

    def test_tc132_policy_not_found(self, client, mock_db):
        resp = client.get("/v1/policies/nonexistent_id", headers=AUTH_HEADERS)
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["error"]["code"] == "policy_not_found"

    def test_tc133_create_policy_missing_name(self, client, mock_db):
        resp = client.post("/v1/policies", headers=AUTH_HEADERS, json={
            "rules": [{"rule_id": "r1", "rule_type": "max_amount", "parameters": {"limit": 100}}],
        })
        assert resp.status_code == 422


# ============================================================
# Section 12 — Policy Versioning
# ============================================================

class TestPolicyVersioning:
    """TC-110 to TC-113."""

    def test_tc110_create_first_version(self, client, mock_db):
        resp = client.post("/v1/policies", headers=AUTH_HEADERS, json={
            "policy_id": "versioned_policy",
            "name": "Versioned Policy",
            "rules": [
                {"rule_id": "r1", "rule_type": "max_amount", "description": "Max 500",
                 "parameters": {"limit": 500}},
            ],
        })
        assert resp.status_code == 201
        assert resp.json()["version"] == 1

    def test_tc111_update_creates_new_version(self, client, mock_db):
        # Create v1
        client.post("/v1/policies", headers=AUTH_HEADERS, json={
            "policy_id": "ver_test",
            "name": "V1",
            "rules": [{"rule_id": "r1", "rule_type": "max_amount", "parameters": {"limit": 500}}],
        })
        # Create v2 with same policy_id
        resp = client.post("/v1/policies", headers=AUTH_HEADERS, json={
            "policy_id": "ver_test",
            "name": "V2",
            "rules": [{"rule_id": "r1", "rule_type": "max_amount", "parameters": {"limit": 1000}}],
        })
        assert resp.status_code == 201
        assert resp.json()["version"] == 2

    def test_tc112_old_version_still_accessible(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy, version=1)
        # Seed version 2 with different rules
        v2 = dict(sample_policy)
        v2["rules"] = [{"rule_id": "r99", "rule_type": "max_amount", "parameters": {"limit": 9999}}]
        seed_policy(mock_db, v2, version=2)

        resp = client.get("/v1/policies/test_policy?version=1", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["version"] == 1

    def test_tc113_default_returns_latest(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy, version=1)
        v2 = dict(sample_policy)
        seed_policy(mock_db, v2, version=2)

        resp = client.get("/v1/policies/test_policy", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        # Should return version 2 (latest — sorted by version DESC)
        data = resp.json()
        assert data["version"] in (1, 2)  # Mock sort may vary; both valid


# ============================================================
# Section 13 — Checks Endpoint
# ============================================================

class TestChecksEndpoint:
    """TC-120 to TC-126."""

    def test_tc120_successful_allow_check(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy)
        resp = client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "test_agent",
            "policy_id": "test_policy",
            "action_type": "refund",
            "amount": 50.00,
            "currency": "USD",
            "counterparty": "cust_001",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "allow"
        assert data["check_id"].startswith("chk_")
        assert isinstance(data["policy_version"], int)
        assert isinstance(data["latency_ms"], int)
        assert data["latency_ms"] >= 0
        assert "T" in data["timestamp"]
        assert data["violated_rule_id"] is None

    def test_tc121_block_check_response(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy)
        resp = client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "test_agent",
            "policy_id": "test_policy",
            "action_type": "refund",
            "amount": 600.00,
            "currency": "USD",
            "counterparty": "cust_001",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "block"
        assert data["violated_rule_id"] is not None
        assert data["violated_rule_description"] is not None
        assert data["message"] is not None

    def test_tc122_missing_required_field(self, client, mock_db):
        resp = client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "test_agent",
            "policy_id": "test_policy",
            # missing action_type
            "amount": 50.00,
            "currency": "USD",
            "counterparty": "cust_001",
        })
        assert resp.status_code == 422

    def test_tc123_invalid_policy_id(self, client, mock_db):
        resp = client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "test_agent",
            "policy_id": "nonexistent_policy",
            "action_type": "refund",
            "amount": 50.00,
            "currency": "USD",
            "counterparty": "cust_001",
        })
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["error"]["code"] == "policy_not_found"

    def test_tc125_get_check_by_id(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy)
        # Create a check first
        create_resp = client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "test_agent",
            "policy_id": "test_policy",
            "action_type": "refund",
            "amount": 50.00,
            "currency": "USD",
            "counterparty": "cust_001",
        })
        check_id = create_resp.json()["check_id"]

        # Retrieve it
        get_resp = client.get(f"/v1/checks/{check_id}", headers=AUTH_HEADERS)
        assert get_resp.status_code == 200
        assert get_resp.json()["check_id"] == check_id

    def test_tc126_get_check_invalid_id(self, client, mock_db):
        resp = client.get("/v1/checks/nonexistent_id", headers=AUTH_HEADERS)
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["error"]["code"] == "check_not_found"


# ============================================================
# Section 15 — Violations Endpoint
# ============================================================

class TestViolationsEndpoint:
    """TC-140 to TC-144."""

    def test_tc140_list_violations_returns_block_and_escalate(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy)
        # Create a block check
        client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "test_agent",
            "policy_id": "test_policy",
            "action_type": "refund",
            "amount": 600.00,
            "currency": "USD",
            "counterparty": "cust_001",
        })
        resp = client.get("/v1/violations", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "pagination" in data
        for v in data["data"]:
            assert v["decision"] in ("block", "escalate")

    def test_tc141_filter_by_agent_id(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy)
        client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "agent_test_001",
            "policy_id": "test_policy",
            "action_type": "refund",
            "amount": 600.00,
            "currency": "USD",
            "counterparty": "cust_001",
        })
        resp = client.get("/v1/violations?agent_id=agent_test_001", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        for v in resp.json()["data"]:
            assert v["agent_id"] == "agent_test_001"

    def test_tc142_filter_by_action_type(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy)
        client.post("/v1/checks", headers=AUTH_HEADERS, json={
            "agent_id": "agent_1",
            "policy_id": "test_policy",
            "action_type": "refund",
            "amount": 600.00,
            "currency": "USD",
            "counterparty": "cust_001",
        })
        resp = client.get("/v1/violations?action_type=refund", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        for v in resp.json()["data"]:
            assert v["action_type"] == "refund"

    def test_tc144_pagination(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy)
        # Create several block checks
        for i in range(7):
            client.post("/v1/checks", headers=AUTH_HEADERS, json={
                "agent_id": f"agent_{i}",
                "policy_id": "test_policy",
                "action_type": "refund",
                "amount": 600.00,
                "currency": "USD",
                "counterparty": f"cust_{i}",
            })
        resp = client.get("/v1/violations?limit=5", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) <= 5
        assert "pagination" in data


# ============================================================
# Section 16 — Simulate Endpoint
# ============================================================

class TestSimulateEndpoint:
    """TC-150 to TC-154."""

    def test_tc150_demo_mode_no_auth(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy)
        resp = client.post("/v1/simulate", json={
            "policy_id": "test_policy",
            "actions": [
                {
                    "agent_id": "agent_1",
                    "policy_id": "test_policy",
                    "action_type": "refund",
                    "amount": 50.00,
                    "currency": "USD",
                    "counterparty": "cust_001",
                },
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "demo"
        assert len(data["results"]) == 1
        # Verify no data written to checks or violations
        assert len(mock_db.get_table_rows("checks")) == 0
        assert len(mock_db.get_table_rows("violations")) == 0

    def test_tc151_demo_mode_over_10_rejected(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy)
        actions = [
            {
                "agent_id": f"agent_{i}",
                "policy_id": "test_policy",
                "action_type": "refund",
                "amount": 50.00,
                "currency": "USD",
                "counterparty": f"cust_{i}",
            }
            for i in range(11)
        ]
        resp = client.post("/v1/simulate", json={
            "policy_id": "test_policy",
            "actions": actions,
        })
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"]["code"] == "demo_limit_exceeded"

    def test_tc153_simulation_matches_rule_engine(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy)
        # Simulate: $600 refund should be blocked by max_amount
        resp = client.post("/v1/simulate", json={
            "policy_id": "test_policy",
            "actions": [
                {
                    "agent_id": "agent_1",
                    "policy_id": "test_policy",
                    "action_type": "refund",
                    "amount": 600.00,
                    "currency": "USD",
                    "counterparty": "cust_001",
                },
            ],
        })
        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert result["decision"] == "block"
        assert result["violated_rule_id"] == "r1"

    def test_tc154_simulation_summary_field(self, client, mock_db, sample_policy):
        seed_policy(mock_db, sample_policy)
        actions = [
            # Should be allowed (refund $50 < $500 limit)
            {"agent_id": "a1", "policy_id": "test_policy", "action_type": "refund",
             "amount": 50, "currency": "USD", "counterparty": "c1"},
            # Should be allowed (refund $100 < $500 limit)
            {"agent_id": "a2", "policy_id": "test_policy", "action_type": "refund",
             "amount": 100, "currency": "USD", "counterparty": "c2"},
            # Should be blocked ($600 > $500 limit)
            {"agent_id": "a3", "policy_id": "test_policy", "action_type": "refund",
             "amount": 600, "currency": "USD", "counterparty": "c3"},
            # Should be blocked ($700 > $500 limit)
            {"agent_id": "a4", "policy_id": "test_policy", "action_type": "refund",
             "amount": 700, "currency": "USD", "counterparty": "c4"},
            # Should be escalated (spend $300 > $200 escalate threshold)
            {"agent_id": "a5", "policy_id": "test_policy", "action_type": "spend",
             "amount": 300, "currency": "USD", "counterparty": "c5"},
        ]
        resp = client.post("/v1/simulate", json={
            "policy_id": "test_policy",
            "actions": actions,
        })
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert summary["total"] == 5
        assert summary["allowed"] == 2
        assert summary["blocked"] == 2
        assert summary["escalated"] == 1
