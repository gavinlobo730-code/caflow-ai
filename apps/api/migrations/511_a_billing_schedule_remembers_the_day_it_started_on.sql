-- Migration 511: a billing schedule remembers the day it started on.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ledger POST-A-215, observed on 8 October 2026 while writing docs/architecture/11)
-- ═══════════════════════════════════════════════════════════════════════════
-- `billing_service.next_run_after` advanced a schedule with its own `_add_months`, which capped the day at 28 and stepped from
-- the PREVIOUS run date: a monthly retainer set to run on the 31st ran 31 Oct, 28 Nov, 28 Dec, 28 Jan for ever, three days
-- early from the first short month on. `domain/recurrence.py` (the engine recurring invoices and journals use) clamps the
-- day against the ORIGINAL start date instead, so a short month borrows nothing from the months after it. The billing
-- schedule could not use it because it holds only `next_run_date`, which is the already-clamped date, and not the day it
-- began on.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- Adds `billing_schedules.anchor_date`, the date the schedule's cadence is measured from. The API writes it when a schedule
-- is created (the first run date) and whenever a schedule's next run date is edited by hand (the CA re-bases it), and
-- advances a schedule with `domain/recurrence.next_occurrence(cadence, anchor_date, after=next_run_date)`.
--
-- BACKFILL, AND ITS LIMIT. Existing rows get `anchor_date = next_run_date`. For a schedule whose day was already clamped to the
-- 28th that is the 28th it already runs on, so nothing moves; the day it ORIGINALLY started on is not recorded anywhere and is
-- not invented. A row with no next run date (a closed one-time schedule) keeps a NULL anchor, which the code reads as
-- "measure from the next run date".
--
-- No policy, grant or trigger changes. Rollback: migration 511_..._rollback.sql drops the column (the API tolerates a missing
-- value, but a deployed API that WRITES the column fails once it is gone, so roll the API back first).

ALTER TABLE public.billing_schedules ADD COLUMN IF NOT EXISTS anchor_date date;

UPDATE public.billing_schedules
   SET anchor_date = next_run_date
 WHERE anchor_date IS NULL AND next_run_date IS NOT NULL;

COMMENT ON COLUMN public.billing_schedules.anchor_date IS
    'POST-A-215. The date the schedule''s cadence is measured from (month ends clamp against THIS day, not the previous run). '
    'Set on create and when the next run date is edited by hand. NULL means measure from next_run_date. Migration 511.';
