"""
Semantic intent classifier for SpendGuard API.

Used ONLY when action_type is missing or None.
Maps reason_text to a canonical action_type using cosine similarity
against anchor embeddings for each action type.

Canonical action types: refund, credit, discount, spend.

Examples:
- "make the customer whole"  → refund
- "courtesy adjustment"      → credit
- "loyalty pricing"          → discount
- "approve vendor invoice"   → spend

IMPORTANT: Semantics classify. Rules decide.
This service NEVER overrides a rule engine decision.
It only resolves an ambiguous action_type before the rule engine runs.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from services.embeddings import get_embedding, get_embeddings_batch

logger = logging.getLogger(__name__)

# ============================================================
# Anchor phrases — representative text for each action type.
# Embeddings are computed once on first call, then cached.
# ============================================================

ANCHOR_PHRASES: dict[str, list[str]] = {
    "refund": [
        "process a refund",
        "return the money",
        "make the customer whole",
        "reverse the charge",
        "issue a refund",
    ],
    "credit": [
        "courtesy adjustment",
        "apply a credit",
        "credit the account",
        "goodwill credit",
        "account adjustment",
    ],
    "discount": [
        "loyalty pricing",
        "apply a discount",
        "price reduction",
        "promotional pricing",
        "offer a discount",
    ],
    "spend": [
        "approve vendor payment",
        "pay the invoice",
        "process payment",
        "authorize purchase",
        "vendor payment",
    ],
}

# Confidence thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.85
MEDIUM_CONFIDENCE_THRESHOLD = 0.70

# Default fallback when confidence is too low
DEFAULT_ACTION_TYPE = "spend"

# In-memory cache for anchor embeddings
_anchor_embeddings: dict[str, list[list[float]]] | None = None


@dataclass
class ClassificationResult:
    """Result of intent classification."""

    action_type: str  # refund / credit / discount / spend
    confidence: str  # high / medium / low
    similarity_score: float  # raw cosine similarity (0-1)
    classified_from: str  # the reason_text that was classified


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Compute cosine similarity between two vectors.

    Returns a value between -1 and 1 (typically 0-1 for embeddings).
    Uses pure Python — no numpy dependency.
    """
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    magnitude_a = math.sqrt(sum(a * a for a in vec_a))
    magnitude_b = math.sqrt(sum(b * b for b in vec_b))

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


async def _load_anchor_embeddings() -> dict[str, list[list[float]]]:
    """
    Compute and cache anchor embeddings for all action types.

    Called once on first classification request, then cached for
    the process lifetime.
    """
    global _anchor_embeddings
    if _anchor_embeddings is not None:
        return _anchor_embeddings

    logger.info("Computing anchor embeddings for intent classifier (one-time)...")

    anchors: dict[str, list[list[float]]] = {}

    for action_type, phrases in ANCHOR_PHRASES.items():
        embeddings = await get_embeddings_batch(phrases)
        # Filter out any None results
        valid_embeddings = [e for e in embeddings if e is not None]
        if not valid_embeddings:
            logger.error(
                "Failed to compute anchor embeddings for action_type '%s'",
                action_type,
            )
            continue
        anchors[action_type] = valid_embeddings

    if len(anchors) < 4:
        logger.error(
            "Only %d/4 action types have anchor embeddings — "
            "classifier may produce unreliable results",
            len(anchors),
        )

    _anchor_embeddings = anchors
    logger.info(
        "Anchor embeddings cached — %d action types, %d total phrases",
        len(anchors),
        sum(len(v) for v in anchors.values()),
    )
    return anchors


async def classify_intent(reason_text: str) -> ClassificationResult:
    """
    Classify reason_text into a canonical action_type.

    Method:
    1. Embed the reason_text using OpenAI text-embedding-3-small.
    2. Compute cosine similarity against all anchor embeddings.
    3. The action_type with the highest average similarity wins.
    4. Apply confidence thresholds.

    Args:
        reason_text: The agent's reason for the financial action.

    Returns:
        ClassificationResult with action_type, confidence, and similarity score.
        Falls back to "spend" with "low" confidence if classification fails.
    """
    # Fail-safe default
    fallback = ClassificationResult(
        action_type=DEFAULT_ACTION_TYPE,
        confidence="low",
        similarity_score=0.0,
        classified_from=reason_text,
    )

    if not reason_text or not reason_text.strip():
        logger.warning("Empty reason_text — returning fallback '%s'", DEFAULT_ACTION_TYPE)
        return fallback

    # Get the embedding for the input text
    input_embedding = await get_embedding(reason_text)
    if input_embedding is None:
        logger.warning("Failed to embed reason_text — returning fallback '%s'", DEFAULT_ACTION_TYPE)
        return fallback

    # Load anchor embeddings (cached after first call)
    anchors = await _load_anchor_embeddings()
    if not anchors:
        logger.warning("No anchor embeddings available — returning fallback '%s'", DEFAULT_ACTION_TYPE)
        return fallback

    # Compute average cosine similarity against each action type's anchors
    best_type = DEFAULT_ACTION_TYPE
    best_score = 0.0

    for action_type, anchor_vecs in anchors.items():
        similarities = [
            _cosine_similarity(input_embedding, anchor)
            for anchor in anchor_vecs
        ]
        avg_similarity = sum(similarities) / len(similarities)

        logger.debug(
            "Similarity for '%s' → %s: %.4f (max=%.4f)",
            reason_text[:50],
            action_type,
            avg_similarity,
            max(similarities),
        )

        if avg_similarity > best_score:
            best_score = avg_similarity
            best_type = action_type

    # Determine confidence level
    if best_score >= HIGH_CONFIDENCE_THRESHOLD:
        confidence = "high"
    elif best_score >= MEDIUM_CONFIDENCE_THRESHOLD:
        confidence = "medium"
    else:
        confidence = "low"
        best_type = DEFAULT_ACTION_TYPE  # Fall back to spend if too uncertain

    logger.info(
        "Classified '%s' → %s (confidence=%s, score=%.4f)",
        reason_text[:80],
        best_type,
        confidence,
        best_score,
    )

    return ClassificationResult(
        action_type=best_type,
        confidence=confidence,
        similarity_score=best_score,
        classified_from=reason_text,
    )


def reset_anchor_cache() -> None:
    """Clear the cached anchor embeddings. Used in testing."""
    global _anchor_embeddings
    _anchor_embeddings = None
