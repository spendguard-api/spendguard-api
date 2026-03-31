"""
Supabase database client for SpendGuard API.

Provides a singleton Supabase client shared across all services.
Credentials are read exclusively from environment variables — never hardcoded.
Raises a clear error at startup if required env vars are missing (fail fast).
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

logger = logging.getLogger(__name__)


def _build_client() -> Client:
    """
    Build and return a Supabase client using environment variables.

    Raises:
        RuntimeError: If SUPABASE_URL or SUPABASE_KEY are missing.
    """
    url: str | None = os.getenv("SUPABASE_URL")
    key: str | None = os.getenv("SUPABASE_KEY")

    if not url:
        raise RuntimeError(
            "SUPABASE_URL environment variable is not set. "
            "Copy .env.example to .env and fill in your Supabase project URL."
        )
    if not key:
        raise RuntimeError(
            "SUPABASE_KEY environment variable is not set. "
            "Copy .env.example to .env and fill in your Supabase anon key."
        )

    # Log that we're connecting but NEVER log the key value
    logger.info("Initialising Supabase client for project: %s", url)

    return create_client(url, key)


# Module-level singleton — imported once, shared across all services.
# Import this in service files: from db.client import supabase
supabase: Client = _build_client()

