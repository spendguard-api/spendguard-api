"""
Immutable audit logger for SpendGuard API.

Writes every check decision to the violations table when decision is block or escalate.
Also writes to the checks table for every decision (allow, block, escalate).

Required fields logged (14 total):
- check_id, agent_id, policy_id, policy_version
- action_type, amount, currency, counterparty
- decision, violated_rule_id, violated_rule_description
- confidence, latency_ms, raw_input_hash, timestamp

Violations table is append-only — never update or delete rows.
Checks table is append-only — never update or delete rows.

# TODO: Loop 3
"""
