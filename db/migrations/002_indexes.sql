-- ============================================================
-- SpendGuard API — Migration 002: Performance Indexes
-- Run this AFTER 001_initial.sql
-- ============================================================

-- ============================================================
-- api_keys indexes
-- ============================================================

-- Fast auth key lookup on every authenticated request
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash
    ON api_keys (key_hash);


-- ============================================================
-- policies indexes
-- ============================================================

-- Look up all versions of a policy by policy_id
CREATE INDEX IF NOT EXISTS idx_policies_policy_id
    ON policies (policy_id);

-- Look up a specific policy version (used by GET /v1/policies/{id}?version=N)
CREATE INDEX IF NOT EXISTS idx_policies_policy_id_version
    ON policies (policy_id, version DESC);


-- ============================================================
-- checks indexes
-- ============================================================

-- Look up a check by its chk_ ID (GET /v1/checks/{id})
CREATE INDEX IF NOT EXISTS idx_checks_check_id
    ON checks (check_id);

-- Filter checks by agent (violations endpoint filtering)
CREATE INDEX IF NOT EXISTS idx_checks_agent_id
    ON checks (agent_id);

-- Filter checks by policy
CREATE INDEX IF NOT EXISTS idx_checks_policy_id
    ON checks (policy_id);

-- Fast idempotency lookup — check if this key was used in the last 24 hours
CREATE INDEX IF NOT EXISTS idx_checks_idempotency_key
    ON checks (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- Date range queries (from/to filtering on audit log)
CREATE INDEX IF NOT EXISTS idx_checks_created_at
    ON checks (created_at DESC);


-- ============================================================
-- violations indexes
-- ============================================================

-- Filter violations by agent (GET /v1/violations?agent_id=...)
CREATE INDEX IF NOT EXISTS idx_violations_agent_id
    ON violations (agent_id);

-- Filter violations by action type (GET /v1/violations?action_type=refund)
CREATE INDEX IF NOT EXISTS idx_violations_action_type
    ON violations (action_type);

-- Filter by decision type (GET /v1/violations?decision=block)
CREATE INDEX IF NOT EXISTS idx_violations_decision
    ON violations (decision);

-- Date range queries and default sort order (newest first)
CREATE INDEX IF NOT EXISTS idx_violations_created_at
    ON violations (created_at DESC);

-- Cursor-based pagination — look up a specific violation_id cursor
CREATE INDEX IF NOT EXISTS idx_violations_violation_id
    ON violations (violation_id);


-- ============================================================
-- duplicate_guard indexes
-- ============================================================

-- Fast fingerprint lookup — the most performance-critical query in the system
-- (runs on EVERY check before rule evaluation)
CREATE INDEX IF NOT EXISTS idx_duplicate_guard_fingerprint
    ON duplicate_guard (fingerprint);

-- Cleanup expired fingerprints efficiently
CREATE INDEX IF NOT EXISTS idx_duplicate_guard_expires_at
    ON duplicate_guard (expires_at);


-- ============================================================
-- usage_events indexes
-- ============================================================

-- Look up usage by API key for billing metering (Week 3)
CREATE INDEX IF NOT EXISTS idx_usage_events_api_key_id
    ON usage_events (api_key_id);

-- Time-based usage aggregation
CREATE INDEX IF NOT EXISTS idx_usage_events_created_at
    ON usage_events (created_at DESC);

