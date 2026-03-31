-- ============================================================
-- SpendGuard API — Migration 003: Rate Limit Events
-- Run this in the Supabase SQL Editor AFTER 002_indexes.sql
-- ============================================================

-- Persistent rate limit tracking.
-- Replaces the in-memory rate limiter to survive Railway restarts.

CREATE TABLE IF NOT EXISTS rate_limit_events (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    limiter_key TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_rate_limit_key_time ON rate_limit_events (limiter_key, created_at DESC);

COMMENT ON TABLE  rate_limit_events IS 'Persistent rate limit event tracking. One row per request.';
COMMENT ON COLUMN rate_limit_events.limiter_key IS 'Rate limit key: key:{key_id} for auth, ip:{address} for demo.';
