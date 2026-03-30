"""
Violations routes for SpendGuard API.

GET /v1/violations — Returns the audit log of block and escalate decisions.
                     Supports filtering by agent_id, action_type, decision, from, to.
                     Supports cursor-based pagination (limit, cursor).

Violations table is append-only — never update or delete rows.

# TODO: Loop 4
"""
