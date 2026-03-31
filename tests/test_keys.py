"""
Tests for the SpendGuard API key creation endpoint.

POST /v1/keys — Create a new API key with X-Admin-Key auth.

Covers:
- Valid admin key + valid body → 201 with key details
- Missing/wrong X-Admin-Key → 401
- Missing name → 422
- Key format: sg_live_ prefix, 74 chars
- key_id starts with key_
- Error responses use standard format

Run with: .venv/bin/python -m pytest tests/test_keys.py -v
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

TEST_ADMIN_KEY = "test_admin_key_for_unit_tests"


# ============================================================
# Mock Supabase (minimal for key tests)
# ============================================================

class MockSupabaseTable:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._query_chain: dict = {}

    def select(self, *args, **kwargs) -> "MockSupabaseTable":
        self._query_chain = {"filters": []}
        return self

    def insert(self, row: dict) -> "MockSupabaseTable":
        if "id" not in row:
            row["id"] = str(uuid.uuid4())
        if "created_at" not in row:
            row["created_at"] = datetime.now(timezone.utc).isoformat()
        self.rows.append(row)
        self._last_inserted = row
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
        if getattr(self, "_is_delete", False):
            self._is_delete = False
            result.data = []
            result.count = 0
            self._query_chain = {}
            return result
        if hasattr(self, "_last_inserted"):
            result.data = [self._last_inserted]
            result.count = 1
            delattr(self, "_last_inserted")
            return result
        filtered = list(self.rows)
        for f in self._query_chain.get("filters", []):
            op, col, val = f
            if op == "eq":
                filtered = [r for r in filtered if r.get(col) == val]
            elif op == "gt":
                filtered = [r for r in filtered if r.get(col, "") > val]
            elif op == "lt":
                filtered = [r for r in filtered if r.get(col, "") < val]
        limit_val = self._query_chain.get("_limit")
        if limit_val:
            filtered = filtered[:limit_val]
        result.data = filtered
        result.count = len(filtered)
        self._query_chain = {}
        return result


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

@pytest.fixture()
def mock_db():
    return MockSupabase()


@pytest.fixture()
def client(mock_db):
    with patch("db.client.supabase", mock_db), \
         patch("services.policy_loader.supabase", mock_db, create=True), \
         patch("services.audit_logger.supabase", mock_db, create=True), \
         patch("services.duplicate_guard.supabase", mock_db, create=True), \
         patch.dict(os.environ, {"ADMIN_API_KEY": TEST_ADMIN_KEY}):
        import db.client
        db.client.supabase = mock_db

        from main import app
        yield TestClient(app)


# ============================================================
# Tests
# ============================================================

class TestKeyCreation:
    """POST /v1/keys tests."""

    def test_valid_admin_key_creates_key(self, client):
        """Valid admin key + valid body → 201 with key details."""
        resp = client.post("/v1/keys", headers={"X-Admin-Key": TEST_ADMIN_KEY}, json={
            "name": "Test Key",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "key_id" in data
        assert "api_key" in data
        assert "name" in data
        assert data["name"] == "Test Key"
        assert "rate_limit_rpm" in data
        assert "created_at" in data

    def test_key_starts_with_sg_live(self, client):
        """Returned api_key starts with sg_live_ and is 74 chars."""
        resp = client.post("/v1/keys", headers={"X-Admin-Key": TEST_ADMIN_KEY}, json={
            "name": "Format Test",
        })
        assert resp.status_code == 201
        api_key = resp.json()["api_key"]
        assert api_key.startswith("sg_live_")
        assert len(api_key) == 72  # sg_live_ (8) + 64 hex chars

    def test_key_id_starts_with_key_prefix(self, client):
        """key_id starts with key_."""
        resp = client.post("/v1/keys", headers={"X-Admin-Key": TEST_ADMIN_KEY}, json={
            "name": "ID Test",
        })
        assert resp.status_code == 201
        assert resp.json()["key_id"].startswith("key_")

    def test_missing_admin_key_returns_401(self, client):
        """Missing X-Admin-Key header → 422 (FastAPI requires it)."""
        resp = client.post("/v1/keys", json={"name": "Test"})
        assert resp.status_code == 422

    def test_wrong_admin_key_returns_401(self, client):
        """Wrong X-Admin-Key → 401 unauthorized."""
        resp = client.post("/v1/keys", headers={"X-Admin-Key": "wrong_key"}, json={
            "name": "Test",
        })
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail["error"]["code"] == "unauthorized"

    def test_missing_name_returns_422(self, client):
        """Missing name field → 422 validation error."""
        resp = client.post("/v1/keys", headers={"X-Admin-Key": TEST_ADMIN_KEY}, json={})
        assert resp.status_code == 422

    def test_custom_rate_limit(self, client):
        """Custom rate_limit_rpm is accepted."""
        resp = client.post("/v1/keys", headers={"X-Admin-Key": TEST_ADMIN_KEY}, json={
            "name": "Custom RPM",
            "rate_limit_rpm": 500,
        })
        assert resp.status_code == 201
        assert resp.json()["rate_limit_rpm"] == 500

    def test_key_hash_stored_not_raw(self, client, mock_db):
        """Only the hash is stored in the database, not the raw key."""
        resp = client.post("/v1/keys", headers={"X-Admin-Key": TEST_ADMIN_KEY}, json={
            "name": "Hash Test",
        })
        assert resp.status_code == 201
        raw_key = resp.json()["api_key"]

        # Check what's in the mock DB
        api_keys_rows = mock_db.table("api_keys").rows
        stored_row = api_keys_rows[-1]  # Last inserted
        assert "key_hash" in stored_row
        assert stored_row["key_hash"] != raw_key  # Hash, not raw
        assert "sg_live_" not in stored_row["key_hash"]  # Not the raw key

    def test_error_format_on_401(self, client):
        """401 error uses standard error format."""
        resp = client.post("/v1/keys", headers={"X-Admin-Key": "bad"}, json={
            "name": "Test",
        })
        assert resp.status_code == 401
        error = resp.json()["detail"]["error"]
        assert "code" in error
        assert "message" in error
        assert "request_id" in error
        assert "timestamp" in error
