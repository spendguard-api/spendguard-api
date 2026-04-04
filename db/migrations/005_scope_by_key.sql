-- ============================================================
-- SpendGuard API — Migration 005: Scope checks/violations by API key
-- Adds api_key_id to checks and violations tables for per-user filtering
-- Run this in the Supabase SQL Editor
-- ============================================================

ALTER TABLE checks ADD COLUMN IF NOT EXISTS api_key_id TEXT;
ALTER TABLE violations ADD COLUMN IF NOT EXISTS api_key_id TEXT;

CREATE INDEX IF NOT EXISTS idx_checks_api_key ON checks (api_key_id);
CREATE INDEX IF NOT EXISTS idx_violations_api_key ON violations (api_key_id);
