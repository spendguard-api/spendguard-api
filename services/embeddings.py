"""
OpenAI embedding wrapper for SpendGuard API.

Wraps OpenAI text-embedding-3-small for use by the intent classifier.
Used ONLY for semantic classification of ambiguous action_type — not for
making authorization decisions.

Rules decide. Semantics only classify.
"""

from __future__ import annotations

import logging
import os
from openai import OpenAI, OpenAIError

logger = logging.getLogger(__name__)

# Model configuration
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Lazy-initialized client
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Get or create the OpenAI client. Reads OPENAI_API_KEY from env."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY environment variable is not set. "
                "The intent classifier requires an OpenAI API key."
            )
        _client = OpenAI(api_key=api_key)
    return _client


async def get_embedding(text: str) -> list[float] | None:
    """
    Get the embedding vector for a text string.

    Uses OpenAI text-embedding-3-small (1536 dimensions).
    Returns None on failure (fail-open — classification becomes unavailable,
    but the check still proceeds with whatever action_type was provided).

    Args:
        text: The text to embed.

    Returns:
        List of 1536 floats, or None if the API call fails.
    """
    if not text or not text.strip():
        logger.warning("Empty text passed to get_embedding — returning None")
        return None

    try:
        client = _get_client()
        response = client.embeddings.create(
            input=text.strip(),
            model=EMBEDDING_MODEL,
        )
        embedding = response.data[0].embedding
        logger.debug(
            "Embedding generated — tokens=%d, dimensions=%d",
            response.usage.total_tokens,
            len(embedding),
        )
        return embedding
    except OpenAIError as e:
        logger.error("OpenAI embedding API call failed: %s", e)
        return None
    except RuntimeError as e:
        logger.error("Embedding client initialization failed: %s", e)
        return None


async def get_embeddings_batch(texts: list[str]) -> list[list[float] | None]:
    """
    Get embeddings for multiple texts in a single API call.

    More efficient than calling get_embedding() in a loop.
    Returns None for any text that fails.

    Args:
        texts: List of strings to embed.

    Returns:
        List of embedding vectors (or None for failures), same order as input.
    """
    if not texts:
        return []

    clean_texts = [t.strip() for t in texts if t and t.strip()]
    if not clean_texts:
        return [None] * len(texts)

    try:
        client = _get_client()
        response = client.embeddings.create(
            input=clean_texts,
            model=EMBEDDING_MODEL,
        )
        logger.debug(
            "Batch embeddings generated — count=%d, tokens=%d",
            len(response.data),
            response.usage.total_tokens,
        )
        # Sort by index to maintain order
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in sorted_data]
    except OpenAIError as e:
        logger.error("OpenAI batch embedding API call failed: %s", e)
        return [None] * len(texts)
    except RuntimeError as e:
        logger.error("Embedding client initialization failed: %s", e)
        return [None] * len(texts)
