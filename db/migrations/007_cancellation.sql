-- Migration 007: Subscription cancellation tracking (D025)
--
-- Adds two columns to api_keys so we can store the scheduled cancellation
-- state locally instead of calling Stripe on every dashboard load.
--
-- cancel_at_period_end  — true when the user has clicked "Cancel" and Stripe
--                         has scheduled the cancellation for the end of the
--                         current billing period. Reverts to false if they
--                         change their mind and click "Keep my plan".
--
-- current_period_end    — the timestamp when the current paid period ends.
--                         This is the date shown to the user ("Your Pro plan
--                         will cancel on April 30, 2026"). Populated by the
--                         customer.subscription.updated webhook handler.
--
-- Both columns are nullable so existing rows keep working without changes.

ALTER TABLE api_keys
  ADD COLUMN IF NOT EXISTS cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE api_keys
  ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ;
