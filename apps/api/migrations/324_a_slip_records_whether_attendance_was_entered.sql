-- Migration 324: a payroll slip records whether attendance was ENTERED.
--
-- WHAT WAS BROKEN
--   routers/payroll.py::_compute_slip defaults working_days and days_present to
--   26 and lop_days to 0 when no attendance row exists, and public.attendance's
--   own columns default the same way (migration 027). So a client who sent
--   NOTHING produced a run that paid every employee a full month, and a slip
--   indistinguishable from one where a human had confirmed full attendance.
--
--   It failed silently and in the employee's favour, which is the direction
--   nobody complains about until the year-end reconciliation. And it compounded
--   with the ECR: a full-month default means no loss-of-pay, so NCP_DAYS = 0
--   looked consistent with the slip it was built from.
--
-- NULLABLE, NO DEFAULT, AND THAT IS THE POINT
--   Three states, not two:
--     true   an attendance row existed and was used
--     false  none existed; the 26/26 default was assumed and nobody said so
--     NULL   the slip predates this column and we genuinely do not know
--
--   A DEFAULT of either value would erase the distinction on every existing
--   row — asserting about historical runs something no one recorded — which is
--   the same class of error as the 26/26 default itself.
--
--   Backfilling is deliberately NOT attempted. public.attendance rows can be
--   edited or deleted after a run, so "does a row exist today" does not answer
--   "did one exist when this slip was computed". NULL is the honest answer for
--   everything already in the table.

ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS attendance_entered BOOLEAN;

COMMENT ON COLUMN public.payroll_slips.attendance_entered IS
  'Whether an attendance row existed for this employee-month when the slip was '
  'computed. false means the 26/26 working-day default was assumed and nobody '
  'entered anything; NULL means the slip predates migration 324. Never given a '
  'default: "nobody told us" and "a human confirmed a full month" are different '
  'facts and the run must be able to say which.';
