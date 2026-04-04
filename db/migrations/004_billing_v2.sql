-- ============================================================
-- SpendGuard API — Migration 004_v2: D022/D023 Billing Columns
-- Run this in the Supabase SQL Editor AFTER 004_billing.sql
-- ============================================================

-- Add overage and signup columns to api_keys
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS overage_enabled BOOLEAN DEFAULT false;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS owner_name TEXT;
