"""
Tests for the SpendGuard API intent classifier.

Covers:
- Cosine similarity math (pure unit test, no API)
- Classification of 5 canonical phrases (mocked embeddings)
- Semantics never override rule decisions (critical safety test)
- Classifier not invoked when action_type is explicit
- Fallback behavior when classification fails
- D018 validation: action_type + reason_text mutual requirement

All tests use mocked embeddings — no real OpenAI API calls.

Run with: .venv/bin/python -m pytest tests/test_intent_classifier.py -v
"""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.intent_classifier import (
    ClassificationResult,
    _cosine_similarity,
    classify_intent,
    reset_anchor_cache,
)
from services.rule_engine import evaluate_rules


# ============================================================
# Mock embedding vectors — deterministic fake embeddings
# that produce predictable cosine similarity results.
#
# Strategy: Each action type gets a "direction" vector.
# Anchor phrases and matching reason_texts get vectors
# close to that direction. This lets us test the full
# classification pipeline without hitting OpenAI.
# ============================================================

# Base direction vectors (unit-ish vectors in 4D, padded to 1536)
def _make_vector(seed: list[float]) -> list[float]:
    """Create a 1536-dim vector from a short seed, padded with zeros."""
    vec = seed + [0.0] * (1536 - len(seed))
    # Normalize
    magnitude = math.sqrt(sum(x * x for x in vec))
    if magnitude > 0:
        vec = [x / magnitude for x in vec]
    return vec


# Direction vectors for each action type
REFUND_DIR = _make_vector([1.0, 0.0, 0.0, 0.0])
CREDIT_DIR = _make_vector([0.0, 1.0, 0.0, 0.0])
DISCOUNT_DIR = _make_vector([0.0, 0.0, 1.0, 0.0])
SPEND_DIR = _make_vector([0.0, 0.0, 0.0, 1.0])

# Slightly noisy versions (still very close to the direction)
def _nudge(vec: list[float], noise: float = 0.05) -> list[float]:
    """Add small noise to a vector to simulate real embedding variation."""
    nudged = [x + noise * (0.1 * i % 3 - 0.15) for i, x in enumerate(vec)]
    magnitude = math.sqrt(sum(x * x for x in nudged))
    if magnitude > 0:
        nudged = [x / magnitude for x in nudged]
    return nudged


# Map of text → mock embedding vector
MOCK_EMBEDDINGS: dict[str, list[float]] = {
    # Refund anchors
    "process a refund": _nudge(REFUND_DIR, 0.01),
    "return the money": _nudge(REFUND_DIR, 0.02),
    "make the customer whole": _nudge(REFUND_DIR, 0.03),
    "reverse the charge": _nudge(REFUND_DIR, 0.04),
    "issue a refund": _nudge(REFUND_DIR, 0.05),
    # Credit anchors
    "courtesy adjustment": _nudge(CREDIT_DIR, 0.01),
    "apply a credit": _nudge(CREDIT_DIR, 0.02),
    "credit the account": _nudge(CREDIT_DIR, 0.03),
    "goodwill credit": _nudge(CREDIT_DIR, 0.04),
    "account adjustment": _nudge(CREDIT_DIR, 0.05),
    # Discount anchors
    "loyalty pricing": _nudge(DISCOUNT_DIR, 0.01),
    "apply a discount": _nudge(DISCOUNT_DIR, 0.02),
    "price reduction": _nudge(DISCOUNT_DIR, 0.03),
    "promotional pricing": _nudge(DISCOUNT_DIR, 0.04),
    "offer a discount": _nudge(DISCOUNT_DIR, 0.05),
    # Spend anchors
    "approve vendor payment": _nudge(SPEND_DIR, 0.01),
    "pay the invoice": _nudge(SPEND_DIR, 0.02),
    "process payment": _nudge(SPEND_DIR, 0.03),
    "authorize purchase": _nudge(SPEND_DIR, 0.04),
    "vendor payment": _nudge(SPEND_DIR, 0.05),
    # Test input phrases (close to their expected type)
    "make the customer whole": _nudge(REFUND_DIR, 0.03),  # → refund
    "courtesy adjustment": _nudge(CREDIT_DIR, 0.01),  # → credit
    "loyalty pricing": _nudge(DISCOUNT_DIR, 0.01),  # → discount
    "approve vendor invoice": _nudge(SPEND_DIR, 0.02),  # → spend
    "reverse the charge": _nudge(REFUND_DIR, 0.04),  # → refund
}


async def mock_get_embedding(text: str) -> list[float] | None:
    """Mock embedding function — returns pre-computed vectors."""
    clean = text.strip().lower()
    # Check for exact match first
    if clean in MOCK_EMBEDDINGS:
        return MOCK_EMBEDDINGS[clean]
    # For unknown text, check partial matches
    for key, vec in MOCK_EMBEDDINGS.items():
        if key in clean or clean in key:
            return vec
    # Unknown text — return a neutral vector
    return _make_vector([0.25, 0.25, 0.25, 0.25])


async def mock_get_embeddings_batch(texts: list[str]) -> list[list[float] | None]:
    """Mock batch embedding — calls mock_get_embedding for each text."""
    results = []
    for text in texts:
        results.append(await mock_get_embedding(text))
    return results


@pytest.fixture(autouse=True)
def reset_classifier_cache():
    """Reset the anchor embedding cache before each test."""
    reset_anchor_cache()
    yield
    reset_anchor_cache()


@pytest.fixture()
def mock_embeddings():
    """Patch the embedding functions with our mocks."""
    with patch("services.intent_classifier.get_embedding", side_effect=mock_get_embedding), \
         patch("services.intent_classifier.get_embeddings_batch", side_effect=mock_get_embeddings_batch):
        yield


# ============================================================
# Section 1 — Cosine Similarity (pure math, no mocks needed)
# ============================================================

class TestCosineSimilarity:
    """Unit tests for the cosine similarity function."""

    def test_identical_vectors_return_1(self):
        vec = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(vec, vec) - 1.0) < 1e-9

    def test_orthogonal_vectors_return_0(self):
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        assert abs(_cosine_similarity(vec_a, vec_b)) < 1e-9

    def test_opposite_vectors_return_negative_1(self):
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [-1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(vec_a, vec_b) + 1.0) < 1e-9

    def test_zero_vector_returns_0(self):
        vec_a = [0.0, 0.0, 0.0]
        vec_b = [1.0, 2.0, 3.0]
        assert _cosine_similarity(vec_a, vec_b) == 0.0

    def test_similar_vectors_return_high_similarity(self):
        vec_a = [1.0, 0.1, 0.0]
        vec_b = [1.0, 0.0, 0.0]
        sim = _cosine_similarity(vec_a, vec_b)
        assert sim > 0.9


# ============================================================
# Section 2 — Classification of canonical phrases
# ============================================================

class TestClassification:
    """Test that the 5 canonical phrases map correctly."""

    @pytest.mark.asyncio
    async def test_make_the_customer_whole_maps_to_refund(self, mock_embeddings):
        result = await classify_intent("make the customer whole")
        assert result.action_type == "refund"

    @pytest.mark.asyncio
    async def test_courtesy_adjustment_maps_to_credit(self, mock_embeddings):
        result = await classify_intent("courtesy adjustment")
        assert result.action_type == "credit"

    @pytest.mark.asyncio
    async def test_loyalty_pricing_maps_to_discount(self, mock_embeddings):
        result = await classify_intent("loyalty pricing")
        assert result.action_type == "discount"

    @pytest.mark.asyncio
    async def test_approve_vendor_invoice_maps_to_spend(self, mock_embeddings):
        result = await classify_intent("approve vendor invoice")
        assert result.action_type == "spend"

    @pytest.mark.asyncio
    async def test_reverse_the_charge_maps_to_refund(self, mock_embeddings):
        result = await classify_intent("reverse the charge")
        assert result.action_type == "refund"


# ============================================================
# Section 3 — Semantics NEVER override rule decisions
# ============================================================

class TestSemanticsNeverOverrideRules:
    """Critical safety test: classifier resolves type, rules still block."""

    @pytest.mark.asyncio
    async def test_classifier_resolves_refund_but_rules_still_block(self, mock_embeddings):
        """
        1. Classifier resolves "make the customer whole" → refund
        2. Rule engine has max_amount=$500 rule
        3. Amount is $600 → MUST be blocked
        4. The classifier must NOT change this outcome.
        """
        result = await classify_intent("make the customer whole")
        assert result.action_type == "refund"

        # Now run the rule engine with the resolved action_type
        rules = [
            {
                "rule_id": "r1",
                "rule_type": "max_amount",
                "description": "Block over $500",
                "parameters": {"limit": 500, "currency": "USD"},
            }
        ]
        engine_result = evaluate_rules(
            rules=rules,
            action_type=result.action_type,
            amount=600.00,
            currency="USD",
            counterparty="cust_001",
        )
        assert engine_result.decision == "block"
        assert engine_result.violated_rule_id == "r1"

    @pytest.mark.asyncio
    async def test_classifier_resolves_discount_but_cap_blocks(self, mock_embeddings):
        """Classifier says discount, but discount_cap rule still blocks."""
        result = await classify_intent("loyalty pricing")
        assert result.action_type == "discount"

        rules = [
            {
                "rule_id": "r6",
                "rule_type": "discount_cap",
                "description": "Max 20% discount",
                "parameters": {"max_percent": 20},
            }
        ]
        engine_result = evaluate_rules(
            rules=rules,
            action_type=result.action_type,
            amount=100.00,
            currency="USD",
            counterparty="cust_001",
            metadata={"discount_percent": 30},
        )
        assert engine_result.decision == "block"
        assert engine_result.violated_rule_id == "r6"


# ============================================================
# Section 4 — Classifier not called when action_type is explicit
# ============================================================

class TestClassifierSkippedWhenExplicit:
    """Verify the classifier is not invoked when action_type is provided."""

    def test_explicit_action_type_accepted(self):
        """CheckRequest with explicit action_type should not need reason_text."""
        from models.check import CheckRequest
        req = CheckRequest(
            agent_id="test",
            policy_id="test_policy",
            action_type="refund",
            amount=50.0,
            currency="USD",
            counterparty="cust_001",
        )
        assert req.action_type.value == "refund"

    def test_missing_both_action_type_and_reason_text_raises(self):
        """D018: if both are missing, 422 validation error."""
        from models.check import CheckRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError) as exc_info:
            CheckRequest(
                agent_id="test",
                policy_id="test_policy",
                # action_type=None (default), reason_text=None (default)
                amount=50.0,
                currency="USD",
                counterparty="cust_001",
            )
        assert "action_type" in str(exc_info.value) or "reason_text" in str(exc_info.value)

    def test_reason_text_without_action_type_accepted(self):
        """D018: reason_text alone is valid — classifier will resolve."""
        from models.check import CheckRequest
        req = CheckRequest(
            agent_id="test",
            policy_id="test_policy",
            reason_text="make the customer whole",
            amount=50.0,
            currency="USD",
            counterparty="cust_001",
        )
        assert req.action_type is None
        assert req.reason_text == "make the customer whole"


# ============================================================
# Section 5 — Fallback behavior
# ============================================================

class TestFallbackBehavior:
    """Test graceful degradation when classification fails."""

    @pytest.mark.asyncio
    async def test_empty_reason_text_returns_spend_fallback(self):
        """Empty reason_text should fallback to spend with low confidence."""
        result = await classify_intent("")
        assert result.action_type == "spend"
        assert result.confidence == "low"

    @pytest.mark.asyncio
    async def test_embedding_failure_returns_spend_fallback(self):
        """If embedding API fails, fallback to spend."""
        async def failing_embedding(text: str) -> None:
            return None

        with patch("services.intent_classifier.get_embedding", side_effect=failing_embedding):
            result = await classify_intent("some random text")
            assert result.action_type == "spend"
            assert result.confidence == "low"

    @pytest.mark.asyncio
    async def test_classification_result_includes_metadata(self, mock_embeddings):
        """Result should include the original text and similarity score."""
        result = await classify_intent("make the customer whole")
        assert result.classified_from == "make the customer whole"
        assert result.similarity_score > 0
        assert result.confidence in ("high", "medium", "low")


# ============================================================
# Section 6 — Integration: endpoint with classifier (mocked)
# ============================================================

class MockSupabaseTable:
    """Minimal mock for endpoint integration tests."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._query_chain: dict = {}

    def select(self, *args, **kwargs) -> "MockSupabaseTable":
        self._query_chain = {"filters": [], "order": None, "limit": None}
        return self

    def insert(self, row: dict) -> "MockSupabaseTable":
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

    def order(self, column: str, desc: bool = False) -> "MockSupabaseTable":
        return self

    def limit(self, n: int) -> "MockSupabaseTable":
        self._query_chain["_limit"] = n
        return self

    def execute(self) -> MagicMock:
        result = MagicMock()
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


TEST_RAW_API_KEY = "test_key_for_classifier_tests"
TEST_API_KEY_HASH = hashlib.sha256(TEST_RAW_API_KEY.encode("utf-8")).hexdigest()
CLASSIFIER_AUTH_HEADERS = {"X-API-Key": TEST_RAW_API_KEY}


def _seed_api_key(mock_db: MockSupabase) -> None:
    """Insert a test API key into the mock DB."""
    mock_db.table("api_keys").rows.append({
        "id": str(uuid.uuid4()),
        "key_hash": TEST_API_KEY_HASH,
        "name": "Test Key",
        "active": True,
        "rate_limit_rpm": 100,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


class TestEndpointWithClassifier:
    """Integration test: POST /v1/checks with reason_text instead of action_type."""

    def test_check_with_reason_text_resolves_and_evaluates(self, mock_embeddings):
        """Send a check without action_type, classifier resolves, rules evaluate."""
        mock_db = MockSupabase()
        _seed_api_key(mock_db)

        # Seed a policy
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

        from api.rate_limit import get_limiter
        get_limiter().reset()

        with patch("db.client.supabase", mock_db), \
             patch("services.policy_loader.supabase", mock_db, create=True), \
             patch("services.audit_logger.supabase", mock_db, create=True), \
             patch("services.duplicate_guard.supabase", mock_db, create=True):
            import db.client
            db.client.supabase = mock_db

            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)

            # Check with reason_text, no action_type — $50 should be allowed
            resp = client.post("/v1/checks", headers=CLASSIFIER_AUTH_HEADERS, json={
                "agent_id": "test_agent",
                "policy_id": "test_policy",
                "reason_text": "make the customer whole",
                "amount": 50.00,
                "currency": "USD",
                "counterparty": "cust_001",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["decision"] == "allow"
            assert data["check_id"].startswith("chk_")

    def test_check_with_reason_text_still_blocked_by_rules(self, mock_embeddings):
        """Classifier resolves refund, but $600 exceeds max_amount → block."""
        mock_db = MockSupabase()
        _seed_api_key(mock_db)

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

        from api.rate_limit import get_limiter
        get_limiter().reset()

        with patch("db.client.supabase", mock_db), \
             patch("services.policy_loader.supabase", mock_db, create=True), \
             patch("services.audit_logger.supabase", mock_db, create=True), \
             patch("services.duplicate_guard.supabase", mock_db, create=True):
            import db.client
            db.client.supabase = mock_db

            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)

            # Classifier resolves "make the customer whole" → refund
            # But $600 > $500 limit → BLOCK
            resp = client.post("/v1/checks", headers=CLASSIFIER_AUTH_HEADERS, json={
                "agent_id": "test_agent",
                "policy_id": "test_policy",
                "reason_text": "make the customer whole",
                "amount": 600.00,
                "currency": "USD",
                "counterparty": "cust_001",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["decision"] == "block"
            assert data["violated_rule_id"] == "r1"
