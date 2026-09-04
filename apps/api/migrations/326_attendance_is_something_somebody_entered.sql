-- Migration 326: attendance is something SOMEBODY ENTERED, and the five
-- numbers on a row have to add up.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS BROKEN — THE SAVE BUTTON WROTE THE WHOLE ROSTER
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 324 gave payroll_slips an `attendance_entered` flag so a run could
-- say which employees nobody had entered anything for, and PR #410 put the
-- gaps on the screen. The distinction it drew — "a human confirmed a full
-- month" versus "nobody told us" — was already being erased upstream, by the
-- only screen that writes this table.
--
-- app/payroll/attendance/page.tsx seeds its editor with a DEFAULT ROW for every
-- employee in the firm that has none (26 working, 26 present, 0 leave), and
-- saveAttendance() upserts `Object.values(attendance)` — all of them, touched
-- or not. So pressing Save once wrote an explicit, confident "26 / 26 / no
-- loss of pay" for the entire firm's roster, for that month, in one statement.
--
-- After that there is no gap to report, ever: a row exists for everybody, so
-- attendance_entered reads true for everybody, and the flag migration 324 added
-- says a human confirmed something no human ever looked at. It fails silently,
-- in the employee's favour, and it makes the ECR's NCP_DAYS = 0 look right.
--
-- The endpoint that replaces that write path (PUT /api/payroll/attendance)
-- writes ONLY the employees in the request, and this migration is what makes
-- the row carry the evidence.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- 1. WHO SAID SO, AND WHEN
-- ═══════════════════════════════════════════════════════════════════════════
-- attendance had created_at and nothing else — no author. For a figure that
-- decides what somebody is paid, and that a payslip then prints to them as
-- fact, "a row exists" is not the same as "a person put it there", and only
-- one of those is worth anything when a deduction is questioned three months
-- later.
--
-- NULLABLE, NO DEFAULT, NO BACKFILL — the same reasoning as
-- payroll_slips.attendance_entered (migration 324). Every row already in this
-- table was written by the bulk upsert described above, and the honest answer
-- to "who entered this" for those rows is that nobody knows. Stamping them
-- with any user id would be asserting authorship that did not happen.

BEGIN;

ALTER TABLE public.attendance
  ADD COLUMN IF NOT EXISTS entered_by uuid REFERENCES public.users(id),
  ADD COLUMN IF NOT EXISTS entered_at timestamptz;

COMMENT ON COLUMN public.attendance.entered_by IS
    'The internal users.id of whoever entered this month''s attendance for this '
    'employee — NOT the Supabase auth id. NULL means the row predates migration '
    '326, which in practice means it came from the bulk save that wrote the '
    'whole roster whether or not anybody looked at it. Never defaulted: '
    'authorship is a fact, and inventing one is worse than admitting it is '
    'unknown.';

COMMENT ON COLUMN public.attendance.entered_at IS
    'When this row was entered or last amended, in UTC. Distinct from '
    'created_at, which is when the ROW first appeared: a correction made on the '
    '9th to a row created on the 1st moves this and not that.';

CREATE INDEX IF NOT EXISTS attendance_firm_period_idx
  ON public.attendance (firm_id, year, month);

-- ═══════════════════════════════════════════════════════════════════════════
-- 2. THE FIVE NUMBERS HAVE TO ADD UP
-- ═══════════════════════════════════════════════════════════════════════════
-- The identity the frontend's own calcLOP() has always implied:
--
--     lop = working_days - days_present - casual - sick - earned
--
-- rearranged, and with the crucial difference that it is now ENFORCED rather
-- than computed and floored:
--
--     days_present + casual + sick + earned + lop = working_days
--
-- Days present are days AT WORK. Casual, sick and earned leave are paid and
-- are counted separately. Loss of pay is the remainder — the days nobody was
-- at work and nobody is paying for.
--
-- WHY THE FLOOR WAS THE BUG. calcLOP() ends `Math.max(0, lop)`, so when the
-- days entered add up to MORE than the month contains — 26 present plus 4
-- days' casual leave in a 26-day month — the negative remainder becomes 0 and
-- the employee is paid a full month on inputs that do not add up. A floor is
-- the same species of silent default as the 26/26 row itself: it converts a
-- contradiction into a confident number instead of a question.
--
-- And the arithmetic is not decorative. routers/payroll.py::_compute_slip
-- prorates on `working_days - lop_days`, so every rupee of basic, HRA, DA, LTA
-- and medical on the payslip comes off this identity.
--
-- NOT VALID, deliberately. Existing rows were written by the bulk save and
-- some of them will not satisfy this — precisely because the floor let them
-- through. NOT VALID guards every future write while leaving history alone,
-- the same choice migration 112 made for the PAN, GSTIN and pincode formats.
-- Validating would fail the migration on data this constraint exists to stop
-- being created, which would leave the constraint unapplied and the bug open.
--
-- Bounds first, then the sum: 31 is the longest month there is, and a
-- working_days of 0 would make the proration divide by zero (it is floored at
-- 1 in Python precisely because nothing stopped it here).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'attendance_days_are_within_a_month') THEN
    ALTER TABLE public.attendance
      ADD CONSTRAINT attendance_days_are_within_a_month
      CHECK (working_days BETWEEN 1 AND 31
             AND days_present  >= 0 AND casual_leaves >= 0
             AND sick_leaves   >= 0 AND earned_leaves >= 0
             AND lop_days      >= 0) NOT VALID;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'attendance_days_add_up_to_the_working_days') THEN
    ALTER TABLE public.attendance
      ADD CONSTRAINT attendance_days_add_up_to_the_working_days
      CHECK (days_present + casual_leaves + sick_leaves + earned_leaves + lop_days
             = working_days) NOT VALID;
  END IF;
END $$;

-- ═══════════════════════════════════════════════════════════════════════════
-- 3. WHO MAY WRITE IT
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 027's only policy is firm_staff_manage_attendance — FOR ALL, scoped
-- by firm and by nothing else. So a Reviewer, whose whole role is to look, could
-- change what somebody is paid, straight from the browser: CLAUDE.md records
-- that ~83 tables are written directly through PostgREST where rbac() never
-- runs, and this is one of them.
--
-- payroll:write is Manager+ (core/permissions.py), which is what the new
-- endpoint requires. RESTRICTIVE so these NARROW the firm policy rather than
-- granting alongside it — a permissive policy here would OR with it and widen
-- access, which reads identically in pg_policies and is why migration 260 set
-- this shape.

DROP POLICY IF EXISTS "attendance_role_insert" ON public.attendance;
CREATE POLICY "attendance_role_insert" ON public.attendance
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.my_role_at_least('Manager'));

DROP POLICY IF EXISTS "attendance_role_update" ON public.attendance;
CREATE POLICY "attendance_role_update" ON public.attendance
  AS RESTRICTIVE FOR UPDATE
  USING (public.my_role_at_least('Manager'))
  WITH CHECK (public.my_role_at_least('Manager'));

DROP POLICY IF EXISTS "attendance_role_delete" ON public.attendance;
CREATE POLICY "attendance_role_delete" ON public.attendance
  AS RESTRICTIVE FOR DELETE
  USING (public.my_role_at_least('Manager'));

-- ═══════════════════════════════════════════════════════════════════════════
-- 4. THE NAMED CUT-OFF
-- ═══════════════════════════════════════════════════════════════════════════
-- A bureau's month starts with chasing the client for inputs, and "have they
-- sent them yet" is only answerable against a date somebody agreed. The day of
-- the month is the whole setting: payroll cut-offs are stated that way ("we
-- need your LOP by the 5th"), they do not move with the calendar, and storing
-- a date per month would need a row per client per month to say the same thing.
--
-- 1..28 because every month has a 28th and no month has a 29th, 30th or 31st
-- reliably — a cut-off of the 30th would silently not exist in February.
--
-- NULLABLE with no default, again. A firm that has not agreed a cut-off with
-- this client has not agreed one; a default of the 5th would put a date on the
-- screen that nobody promised and let the CA chase against it.
--
-- One row per client, and deliberately its own table rather than a column on
-- `clients`: v1 item 12 adds per-client payroll enablement, which belongs
-- beside this and not in the core client record every module reads.

CREATE TABLE IF NOT EXISTS public.client_payroll_settings (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id    uuid NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id  uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  inputs_due_day smallint CHECK (inputs_due_day IS NULL
                                 OR inputs_due_day BETWEEN 1 AND 28),

  note        text,
  updated_by  uuid REFERENCES public.users(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),

  UNIQUE (firm_id, client_id)
);

COMMENT ON TABLE public.client_payroll_settings IS
    'Per-client payroll configuration. Today: inputs_due_day, the agreed day of '
    'the month by which this client sends attendance and other inputs. One row '
    'per client. Migration 326.';

COMMENT ON COLUMN public.client_payroll_settings.inputs_due_day IS
    'Day of the month (1-28) the client has agreed to send payroll inputs by. '
    'Capped at 28 because a cut-off of the 30th does not exist in February. '
    'NULL means no cut-off has been agreed — never defaulted, because a date '
    'nobody promised is not a date a CA can chase against.';

ALTER TABLE public.client_payroll_settings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_payroll_settings" ON public.client_payroll_settings;
CREATE POLICY "firm_payroll_settings" ON public.client_payroll_settings
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

DO $$
DECLARE t text := 'client_payroll_settings';
BEGIN
  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT '
    'WITH CHECK (public.my_role_at_least(%L))', t || '_role_insert', t, 'Manager');

  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE '
    'USING (public.my_role_at_least(%L)) WITH CHECK (public.my_role_at_least(%L))',
    t || '_role_update', t, 'Manager', 'Manager');

  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE '
    'USING (public.my_role_at_least(%L))', t || '_role_delete', t, 'Manager');
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_payroll_settings TO authenticated;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column'
                                     AND pronamespace = 'public'::regnamespace) THEN
    DROP TRIGGER IF EXISTS client_payroll_settings_updated_at ON public.client_payroll_settings;
    CREATE TRIGGER client_payroll_settings_updated_at
      BEFORE UPDATE ON public.client_payroll_settings
      FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
  END IF;
END $$;

COMMIT;
