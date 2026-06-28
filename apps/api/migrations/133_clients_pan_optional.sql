-- Migration 133: PAN is OPTIONAL at client creation.
--
-- ROOT CAUSE of the "Convert to Client" failure
--   null value in column "pan" of relation "clients" violates not-null constraint
-- clients.pan was NOT NULL, but the product collects/verifies PAN during
-- ONBOARDING — the "Obtain PAN copy" and "PAN verification" steps run AFTER a
-- lead becomes a client — and both the UI ("PAN (optional)") and the convert API
-- (which maps an empty PAN to None) treat it as optional. The schema was the only
-- layer that disagreed. This aligns it.
--
-- The existing clients_pan_check (pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$') still enforces
-- the FORMAT whenever a PAN is supplied: a regex match against NULL evaluates to
-- NULL, and a CHECK constraint passes on NULL — so the column now means
-- "absent, OR a well-formed PAN", never a malformed one.
--
-- Safe for existing data: every current row already holds a non-null PAN (the
-- column was NOT NULL), so dropping the constraint changes nothing for them.
-- GSTIN is already nullable, so no change is needed there.

ALTER TABLE public.clients ALTER COLUMN pan DROP NOT NULL;
