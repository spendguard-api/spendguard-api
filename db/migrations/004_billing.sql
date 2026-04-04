-- ============================================================
-- SpendGuard API — Migration 004: Billing Columns
-- Run this in the Supabase SQL Editor
-- ============================================================

-- Add billing columns to api_keys
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS plan_name TEXT DEFAULT 'starter';
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS plan_limit INTEGER DEFAULT 10000;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS billing_period_start TIMESTAMPTZ DEFAULT now();

-- Index for fast usage counting
CREATE INDEX IF NOT EXISTS idx_usage_events_key_time
ON usage_events (api_key_id, created_at DESC);
