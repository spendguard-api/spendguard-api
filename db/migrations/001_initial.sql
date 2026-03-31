-- ============================================================
-- SpendGuard API — Migration 001: Initial Schema
-- Run this in the Supabase SQL Editor BEFORE 002_indexes.sql
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- TABLE 1: api_keys
-- Stores hashed API keys for authentication.
-- Raw keys are NEVER stored — only SHA-256 hashes.
-- ============================================================
CREATE TABLE IF NOT EXISTS api_keys (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash        TEXT        NOT NULL UNIQUE,
    name            TEXT        NOT NULL,
    active          BOOLEAN     NOT NULL DEFAULT TRUE,
    rate_limit_rpm  INTEGER     NOT NULL DEFAULT 100,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  api_keys IS 'Hashed API keys for SpendGuard authentication. Raw keys never stored.';
COMMENT ON COLUMN api_keys.key_hash IS 'SHA-256 hash of the raw API key. Used for lookup on every request.';


-- ============================================================
-- TABLE 2: policies
-- Stores every version of every policy rulebook.
-- Rows are NEVER updated or deleted — a new row is inserted
-- on every policy update (version N+1).
-- ============================================================
CREATE TABLE IF NOT EXISTS policies (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id   TEXT        NOT NULL,
    name        TEXT        NOT NULL,
    description TEXT,
    version     INTEGER     NOT NULL DEFAULT 1,
    rules_json  JSONB       NOT NULL DEFAULT '[]'::jsonb,
    metadata    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT policies_policy_id_version_unique UNIQUE (policy_id, version)
);

COMMENT ON TABLE  policies IS 'Versioned policy rulebooks. Append-only — never update or delete rows.';
COMMENT ON COLUMN policies.policy_id IS 'Human-readable policy identifier e.g. support_refund_policy.';
COMMENT ON COLUMN policies.version   IS 'Version number starting at 1. Increments on every update.';
COMMENT ON COLUMN policies.rules_json IS 'Array of rule objects. See BUILD_BRIEF.md for rule type definitions.';


-- ============================================================
-- TABLE 3: checks
-- Every single authorization decision ever made.
-- APPEND-ONLY — never update or delete rows.
-- ============================================================
CREATE TABLE IF NOT EXISTS checks (
    id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    check_id                  TEXT        NOT NULL UNIQUE,
    agent_id                  TEXT        NOT NULL,
    policy_id                 TEXT        NOT NULL,
    policy_version            INTEGER     NOT NULL,
    action_type               TEXT        NOT NULL,
    amount                    NUMERIC(14, 4) NOT NULL,
    currency                  CHAR(3)     NOT NULL,
    counterparty              TEXT        NOT NULL,
    payment_method            TEXT,
    merchant_or_vendor        TEXT,
    reason_text               TEXT,
    decision                  TEXT        NOT NULL CHECK (decision IN ('allow', 'block', 'escalate')),
    violated_rule_id          TEXT,
    violated_rule_description TEXT,
    confidence                TEXT        NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    latency_ms                INTEGER     NOT NULL,
    raw_input_hash            TEXT        NOT NULL,
    idempotency_key           TEXT        UNIQUE,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  checks IS 'All authorization decisions. Append-only — never update or delete rows.';
COMMENT ON COLUMN checks.check_id         IS 'Unique check identifier prefixed chk_';
COMMENT ON COLUMN checks.raw_input_hash   IS 'SHA-256 of the full request body for tamper detection.';
COMMENT ON COLUMN checks.idempotency_key  IS 'Client-supplied key for safe retries. Null or unique.';
COMMENT ON COLUMN checks.violated_rule_id IS 'ID of the rule that caused block/escalate. NULL on allow.';


-- ============================================================
-- TABLE 4: violations
-- Immutable audit log of block and escalate decisions only.
-- APPEND-ONLY — never update or delete rows.
-- ============================================================
CREATE TABLE IF NOT EXISTS violations (
    id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    violation_id              TEXT        NOT NULL UNIQUE,
    check_id                  TEXT        NOT NULL,
    agent_id                  TEXT        NOT NULL,
    policy_id                 TEXT        NOT NULL,
    policy_version            INTEGER     NOT NULL,
    action_type               TEXT        NOT NULL,
    amount                    NUMERIC(14, 4) NOT NULL,
    currency                  CHAR(3)     NOT NULL,
    counterparty              TEXT        NOT NULL,
    decision                  TEXT        NOT NULL CHECK (decision IN ('block', 'escalate')),
    violated_rule_id          TEXT        NOT NULL,
    violated_rule_description TEXT        NOT NULL,
    confidence                TEXT        NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    latency_ms                INTEGER     NOT NULL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  violations IS 'Immutable audit log of block and escalate decisions. Append-only.';
COMMENT ON COLUMN violations.violation_id IS 'Unique violation identifier prefixed viol_';
COMMENT ON COLUMN violations.check_id     IS 'Links to checks.check_id for the originating check.';
COMMENT ON COLUMN violations.decision     IS 'Only block or escalate — allow decisions are never violations.';


-- ============================================================
-- TABLE 5: duplicate_guard
-- Rolling fingerprint window to detect duplicate agent actions.
-- Fingerprint = SHA-256("agent_id|action_type|amount|counterparty")
-- Default TTL: 5 minutes (configurable per policy).
-- ============================================================
CREATE TABLE IF NOT EXISTS duplicate_guard (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    fingerprint TEXT        NOT NULL UNIQUE,
    agent_id    TEXT        NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  duplicate_guard IS 'Rolling fingerprint cache for duplicate action detection.';
COMMENT ON COLUMN duplicate_guard.fingerprint IS 'SHA-256 of agent_id|action_type|str(amount)|counterparty';
COMMENT ON COLUMN duplicate_guard.expires_at  IS 'When this fingerprint expires. Rows past expires_at are ignored.';


-- ============================================================
-- TABLE 6: usage_events
-- Per-check usage tracking for billing metering (Week 3).
-- ============================================================
CREATE TABLE IF NOT EXISTS usage_events (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key_id  TEXT        NOT NULL,
    event_type  TEXT        NOT NULL DEFAULT 'check',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  usage_events IS 'Usage metering events per API key. Used for Stripe billing in Week 3.';
COMMENT ON COLUMN usage_events.api_key_id  IS 'References api_keys.id (text, not FK to avoid cascade risk).';
COMMENT ON COLUMN usage_events.event_type  IS 'Type of billable event — currently always check.';

