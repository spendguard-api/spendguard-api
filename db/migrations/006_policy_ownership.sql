-- ============================================================
-- SpendGuard API — Migration 006: Policy Ownership
-- Adds api_key_id to policies so each customer only sees their own.
-- Run this in the Supabase SQL Editor.
-- ============================================================

ALTER TABLE policies ADD COLUMN IF NOT EXISTS api_key_id TEXT;
CREATE INDEX IF NOT EXISTS idx_policies_api_key ON policies (api_key_id);
