"""
Duplicate guard service for SpendGuard API.

Computes SHA-256 fingerprint of: f"{agent_id}|{action_type}|{str(amount)}|{counterparty}"
Checks the duplicate_guard table for a matching fingerprint within the TTL window.
If found: returns block with reason_code=duplicate_action_detected.
If not found: inserts the fingerprint and TTL, then proceeds to rule engine.

Default TTL: 5 minutes (configurable per policy via duplicate_guard rule window_minutes).

In simulation mode: read-only evaluation — fingerprint is never written.

# TODO: Loop 3
"""
