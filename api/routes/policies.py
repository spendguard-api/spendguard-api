"""
Policies routes for SpendGuard API.

POST /v1/policies  — Create a new policy or a new version of an existing policy.
GET  /v1/policies/{id} — Retrieve a policy by ID (latest version by default,
                          specific version via ?version=N).

Delegates to services/policy_loader.py for data access.
Policy versioning is mandatory: every update creates version N+1.

# TODO: Loop 4
"""
