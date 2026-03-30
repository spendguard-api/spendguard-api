"""
Deterministic rule engine for SpendGuard API.

Evaluates all rules in a policy against a check request.
Returns allow / block / escalate.

Rule precedence: block > escalate > allow.
Duplicate guard runs before all rules (see duplicate_guard.py).

Supported rule types:
- max_amount
- refund_age_limit
- blocked_categories
- vendor_allowlist
- blocked_payment_rails
- discount_cap
- geography_block
- time_restriction
- duplicate_guard (TTL config reader)
- escalate_if

Rules decide. Semantics only classify action_type. Never the other way around.

# TODO: Loop 3
"""
