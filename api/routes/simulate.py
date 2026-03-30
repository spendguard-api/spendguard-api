"""
Simulate route for SpendGuard API.

POST /v1/simulate — Run one or more authorization checks with NO side effects.
                    Nothing is written to checks, violations, or duplicate_guard tables.

Demo mode (no X-API-Key): up to 10 actions, response includes mode="demo".
Authenticated mode (with X-API-Key): up to 100 actions, response includes mode="simulation".

Rule engine runs identically to POST /v1/checks.
Duplicate guard runs in read-only mode (no fingerprint written).

# TODO: Loop 4
"""
