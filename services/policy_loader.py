"""
Policy loader service for SpendGuard API.

Fetches policies from the Supabase policies table.
Supports loading by policy_id (latest version) or by specific version number.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PolicyNotFoundError(Exception):
    """Raised when a requested policy does not exist."""

    def __init__(self, policy_id: str, version: int | None = None) -> None:
        self.policy_id = policy_id
        self.version = version
        if version is not None:
            msg = f"No policy found with ID '{policy_id}' version {version}."
        else:
            msg = f"No policy found with ID '{policy_id}'."
        super().__init__(msg)


async def get_policy(
    policy_id: str,
    version: int | None = None,
    supabase_client: Any | None = None,
) -> dict[str, Any]:
    """
    Fetch a policy from Supabase by policy_id.

    Args:
        policy_id: The human-readable policy identifier.
        version: Optional specific version number. If None, latest version is returned.
        supabase_client: Supabase client. If None, imports the singleton.

    Returns:
        Dict with keys: policy_id, name, description, version, rules (list of dicts),
        created_at, metadata.

    Raises:
        PolicyNotFoundError: If the policy or version does not exist.
    """
    if supabase_client is None:
        from db.client import supabase
        supabase_client = supabase

    query = (
        supabase_client.table("policies")
        .select("*")
        .eq("policy_id", policy_id)
    )

    if version is not None:
        # Fetch a specific version
        query = query.eq("version", version)
    else:
        # Fetch the latest version (highest version number)
        query = query.order("version", desc=True).limit(1)

    try:
        result = query.execute()
    except Exception as e:
        logger.error("Failed to query policy from database: %s", e)
        raise

    if not result.data or len(result.data) == 0:
        raise PolicyNotFoundError(policy_id, version)

    row = result.data[0]

    # Parse rules_json from JSONB back to list of dicts
    rules = row.get("rules_json", [])
    if isinstance(rules, str):
        import json
        rules = json.loads(rules)

    return {
        "policy_id": row["policy_id"],
        "name": row["name"],
        "description": row.get("description"),
        "version": row["version"],
        "rules": rules,
        "created_at": row["created_at"],
        "metadata": row.get("metadata"),
    }


async def create_policy(
    policy_id: str,
    name: str,
    rules: list[dict[str, Any]],
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    api_key_id: str | None = None,
    supabase_client: Any | None = None,
) -> dict[str, Any]:
    """
    Create a new policy or a new version of an existing policy.

    If policy_id already exists, creates version N+1.
    If policy_id is new, creates version 1.

    Args:
        policy_id: Human-readable policy identifier.
        name: Human-readable name for the policy.
        rules: List of rule dicts.
        description: Optional description.
        metadata: Optional key-value metadata.
        api_key_id: Owner's API key ID for multi-tenant isolation.
        supabase_client: Supabase client.

    Returns:
        Dict of the newly created policy row.
    """
    if supabase_client is None:
        from db.client import supabase
        supabase_client = supabase

    # Determine the next version number
    try:
        existing = (
            supabase_client.table("policies")
            .select("version")
            .eq("policy_id", policy_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        if existing.data and len(existing.data) > 0:
            next_version = existing.data[0]["version"] + 1
        else:
            next_version = 1
    except Exception as e:
        logger.error("Failed to check existing policy versions: %s", e)
        raise

    import json

    row = {
        "policy_id": policy_id,
        "name": name,
        "description": description,
        "version": next_version,
        "rules_json": json.dumps(rules),
        "metadata": json.dumps(metadata) if metadata else None,
        "api_key_id": api_key_id,
    }

    try:
        result = supabase_client.table("policies").insert(row).execute()
        logger.info(
            "Policy created — policy_id=%s version=%d",
            policy_id,
            next_version,
        )
    except Exception as e:
        logger.error("Failed to create policy in database: %s", e)
        raise

    created_row = result.data[0] if result.data else row
    created_row["rules"] = rules
    return created_row
