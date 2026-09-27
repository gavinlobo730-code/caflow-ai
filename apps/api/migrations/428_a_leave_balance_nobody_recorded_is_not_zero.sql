-- 428: a leave allocation nobody recorded can be stored as not recorded.
--
-- WHY
--   public.leave_balances holds ONE row per employee per year with three
--   allocations -- casual, sick and earned -- and migration 027 declared all
--   three `INTEGER NOT NULL DEFAULT 12 / 12 / 15`. Those defaults are the
--   invented entitlements PAY-24 took off the attendance screen: a CA could
--   not tell a figure their firm had agreed from one the product had made up,
--   and "Remaining" was measured against the invention. The screen stopped
--   inventing them; the SCHEMA never did.
--
--   The leave editor records the three separately, and a CA who knows only
--   the casual allocation (the common case in the first month of an
--   engagement) left the other two boxes blank. With the columns as 027 left
--   them, a blank had exactly two ways to reach the table and both were wrong:
--
--     sent as NULL   -> 23502 not_null_violation, so the save failed -- and
--                       the screen closed the editor anyway, because it never
--                       read the upsert's error;
--     sent as 0      -> what apps/web/app/payroll/attendance/page.tsx did:
--                       "no sick leave, no earned leave", an entitlement of
--                       NONE that nobody gave, shown to the employee on the
--                       portal as a red 0;
--     omitted        -> the DEFAULT put back 12 and 15, the PAY-24 invention
--                       one layer down.
--
--   "Not recorded" is a different fact from zero and could not be stored at
--   all. This makes it storable.
--
-- WHAT THIS DOES
--   Drops NOT NULL and DEFAULT on the three allocation columns. Nothing else.
--
--   * It RELAXES only. Every row that satisfied 027 satisfies this, so it
--     cannot fail on existing data, and it rewrites none: a row already
--     holding 12/12/15 or a 0 keeps it. Which of those were agreed and which
--     were written by the old defaults cannot be told apart from here, so
--     nothing is guessed back to NULL -- that is the CA's (or the owner's)
--     call, row by row.
--   * No backend code reads leave_balances (grep of apps/api). Its readers
--     are the attendance screen, which already treats NULL as "not recorded"
--     (PAY-24), and the employee portal, which renders it "Not recorded".
--   * The DEFAULT goes too, deliberately: a DEFAULT on a column the screen
--     writes explicitly only ever fires for a writer that OMITS the field, and
--     for that writer 12/15 is the invention again. With it gone an omitted
--     allocation is NULL, which is what an omission means.
--   * Migration 262's employee-portal RLS and 260/261's role-aware write
--     policies are row-level and do not mention these columns; they are
--     untouched.

BEGIN;

ALTER TABLE public.leave_balances
    ALTER COLUMN casual_leave_balance DROP NOT NULL,
    ALTER COLUMN casual_leave_balance DROP DEFAULT,
    ALTER COLUMN sick_leave_balance   DROP NOT NULL,
    ALTER COLUMN sick_leave_balance   DROP DEFAULT,
    ALTER COLUMN earned_leave_balance DROP NOT NULL,
    ALTER COLUMN earned_leave_balance DROP DEFAULT;

COMMENT ON COLUMN public.leave_balances.casual_leave_balance IS
    'Days of casual leave allotted for the year. NULL = not recorded, which '
    'is not zero. Migration 428 dropped 027''s NOT NULL DEFAULT 12.';

COMMENT ON COLUMN public.leave_balances.sick_leave_balance IS
    'Days of sick leave allotted for the year. NULL = not recorded, which '
    'is not zero. Migration 428 dropped 027''s NOT NULL DEFAULT 12.';

COMMENT ON COLUMN public.leave_balances.earned_leave_balance IS
    'Days of earned leave allotted for the year. NULL = not recorded, which '
    'is not zero. Migration 428 dropped 027''s NOT NULL DEFAULT 15.';

COMMIT;
