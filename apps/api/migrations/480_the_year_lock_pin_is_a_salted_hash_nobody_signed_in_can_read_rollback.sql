-- Rollback for 480. IT CANNOT RESTORE THE PINS.
--
-- Migration 480 replaced each firm's plaintext PIN with a salted hash and emptied
-- firms.lock_pin. A hash cannot be turned back into the PIN, so this file only
-- takes the new machinery away: it drops the firms_lock_pin_retired CHECK (so the
-- column can be written again) and drops public.firm_lock_pins together with every
-- hash in it.
--
-- WHAT THAT MEANS ON A DATABASE THAT HAD PINS: after this rollback every firm reads
-- as "no PIN set", because firms.lock_pin is NULL and the table is gone. The next
-- time a Partner locks or unlocks a year, the supplied PIN is adopted as the firm's
-- new PIN (the pre-480 behaviour, in firms.lock_pin, in plaintext, readable by
-- every member of the firm). Years that were locked stay locked: locked_financial_years
-- was never touched, and unlocking one needs a PIN only if one is set.
--
-- Roll the API back with this file. The 480 API reads firm_lock_pins and fails every
-- year-lock request once it is gone.
--
-- Do not run it to "put the hole back" outside a test: the hole it puts back is that
-- every member of the firm can read the PIN.

BEGIN;

ALTER TABLE public.firms DROP CONSTRAINT IF EXISTS firms_lock_pin_retired;
COMMENT ON COLUMN public.firms.lock_pin IS NULL;
DROP TABLE IF EXISTS public.firm_lock_pins;

COMMIT;
