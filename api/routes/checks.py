"""
Checks routes for SpendGuard API.

POST /v1/checks      — Run a real-time authorization check against a policy.
                       Runs duplicate guard first, then rule engine.
                       Logs every decision to the audit trail.
                       Handles idempotency_key (24-hour window).
GET  /v1/checks/{id} — Retrieve a past check by ID.

Returns allow / block / escalate. Every block includes violated_rule_id.

# TODO: Loop 4
"""
