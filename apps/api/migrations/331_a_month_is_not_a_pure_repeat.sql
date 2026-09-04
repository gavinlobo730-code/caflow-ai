-- Migration 331: a month is not a pure repeat — one-time and variable earnings,
-- and the three statutory questions each one has to answer.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IS MISSING
-- ═══════════════════════════════════════════════════════════════════════════
-- A payroll run today computes a slip out of the employee master and a salary
-- revision: basic, HRA, DA, LTA, medical, special, other allowances. Every one
-- of those is a MONTHLY RATE, prorated by attendance. There is nowhere at all
-- to put an amount that is decided once — a Diwali bonus, a quarterly
-- incentive, ex-gratia, arrears of a backdated revision, a referral award.
--
-- That is not an edge case a bureau meets in year two. A December cohort hits
-- a festival bonus in its first month. The only way to pay one on the software
-- as it stands is to inflate `special_allowance_paise` for one month and then
-- remember to put it back, which is wrong four separate ways: it is prorated
-- by LOP when a decided amount should not be, it enters PF wages when a bonus
-- is expressly excluded from them, it enters ESI wages when an annual payment
-- is expressly excluded from those too, and — worst — §192 then projects it
-- across every remaining month of the year and withholds tax on a bonus the
-- employee will be paid once.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- 1. THE THREE QUESTIONS, AND WHY THEY ARE COLUMNS AND NOT A LOOKUP
-- ═══════════════════════════════════════════════════════════════════════════
-- Every extra rupee paid to an employee has to answer three questions
-- separately, and the answers genuinely differ between two payments that a
-- payslip would print with almost the same word on them:
--
--   PF wages?   EPF Act §2(b) defines "basic wages" and expressly EXCLUDES
--               "any bonus, commission or any other similar allowance payable
--               to the employee in respect of his employment". So a bonus,
--               an incentive and a commission are not PF wages. ARREARS of
--               basic or DA are — they are the same wages, paid late, and
--               EPFO takes contributions on them in the month of payment.
--
--   ESI wages?  ESI Act §2(22) includes "any additional remuneration ... paid
--               at intervals NOT EXCEEDING TWO MONTHS". That is an interval
--               test, not a name test: a monthly or quarterly incentive is ESI
--               wages and an annual bonus is not, even though both are
--               "incentive-ish" payments to the same employee. The proviso is
--               why `payment_interval_months` exists on this table at all.
--
--   §17(1)?     IT Act §17(1)(iv) brings in "any fees, commissions,
--               perquisites or profits in lieu of or in addition to any salary
--               or wages", and §17(1)(iv)/(v) bonus. In practice every earning
--               recorded here is salary and is taxable; the column exists
--               because a genuine reimbursement of expenditure is not, and a
--               CA who records one needs to be able to say so rather than
--               being forced to overstate §17(1) on the employee's Form 16.
--
-- These are stored AS DECIDED, per row, rather than derived from `kind` at
-- read time. Two reasons. The interval test means `kind` alone cannot answer
-- the ESI question — "incentive" is ESI wages at one client and not at
-- another. And a slip is evidence: what the run applied has to still be
-- readable in March when somebody asks why this employee's PF wages jumped in
-- October, and a lookup table that has since been edited cannot answer that.
-- domain/payroll/one_time_earnings.py proposes the defaults from the kind and
-- the interval; this table records what was actually saved.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- 2. WHY (client, employee, MONTH) AND NOT A DATE
-- ═══════════════════════════════════════════════════════════════════════════
-- Payroll's grain everywhere else in this schema is the month: payroll_runs is
-- UNIQUE (firm, client, month), attendance is keyed (employee, year, month).
-- An earning is paid IN a payroll month; the day inside it is not a fact
-- anybody has. `month` is DATE and pinned to the first of the month by a CHECK
-- so it sorts and joins as a date without inviting a day-of-month that would
-- silently split one month's earnings into two buckets.

BEGIN;

CREATE TABLE IF NOT EXISTS public.payroll_one_time_earnings (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id     uuid NOT NULL REFERENCES public.firms(id)             ON DELETE CASCADE,
  client_id   uuid NOT NULL REFERENCES public.clients(id)           ON DELETE CASCADE,
  employee_id uuid NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,

  month  date NOT NULL,
  kind   text NOT NULL,
  label  text,

  amount_paise bigint NOT NULL,

  -- The three answers, recorded rather than looked up. NOT NULL with no
  -- default: a row that does not say whether it is PF wages has not answered
  -- the question, and a default would answer it silently in one direction.
  pf_wages    boolean NOT NULL,
  esi_wages   boolean NOT NULL,
  taxable     boolean NOT NULL,

  -- ESI Act §2(22): the interval decides, so it is stored. NULL means "paid
  -- once, not at an interval" — a joining bonus or ex-gratia — which is the
  -- same side of the two-month line as an annual payment.
  payment_interval_months smallint,

  note        text,
  entered_by  uuid REFERENCES public.users(id),
  entered_at  timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT payroll_one_time_earning_month_is_a_month
    CHECK (date_trunc('month', month)::date = month),

  -- Signed on purpose: a negative row is a RECOVERY of something overpaid in
  -- an earlier month, which is a real thing a bureau does and which must not
  -- be recorded as a positive deduction elsewhere. Zero is refused because a
  -- zero-rupee earning is a row somebody forgot to fill in, not a decision.
  CONSTRAINT payroll_one_time_earning_is_an_amount
    CHECK (amount_paise <> 0),

  CONSTRAINT payroll_one_time_earning_interval_is_sane
    CHECK (payment_interval_months IS NULL
           OR payment_interval_months BETWEEN 1 AND 12),

  CONSTRAINT payroll_one_time_earning_kind_is_known
    CHECK (kind IN ('incentive', 'bonus', 'ex_gratia', 'arrears',
                    'commission', 'reimbursement', 'other'))
);

COMMENT ON TABLE public.payroll_one_time_earnings IS
    'Amounts paid to an employee in one payroll month that are NOT a monthly '
    'rate — incentive, bonus, ex-gratia, arrears, commission. One row per '
    'employee per month per kind of payment; several rows in a month are '
    'summed. Never prorated by attendance: a decided amount is not a rate. '
    'Migration 331, payroll v1 item 7.';

COMMENT ON COLUMN public.payroll_one_time_earnings.month IS
    'The payroll month this is paid in, pinned to the first of the month. The '
    'grain payroll uses everywhere else; the day inside the month is not a '
    'fact anybody holds.';

COMMENT ON COLUMN public.payroll_one_time_earnings.amount_paise IS
    'Integer paise. Signed: a negative row recovers an earlier overpayment of '
    'the same kind. Never zero.';

COMMENT ON COLUMN public.payroll_one_time_earnings.pf_wages IS
    'Whether this amount enters PF wages. EPF Act §2(b) excludes bonus, '
    'commission and similar allowances from basic wages, so an incentive or a '
    'festival bonus is FALSE; arrears of basic or DA are the same wages paid '
    'late and are TRUE. Recorded as decided, not derived at read time — a slip '
    'has to stay readable after the defaults change.';

COMMENT ON COLUMN public.payroll_one_time_earnings.esi_wages IS
    'Whether this amount enters ESI wages. ESI Act §2(22) includes additional '
    'remuneration paid at intervals NOT EXCEEDING TWO MONTHS, so a monthly or '
    'bi-monthly incentive is TRUE and an annual bonus is FALSE. An INTERVAL '
    'test, not a name test — which is why payment_interval_months is stored '
    'beside it.';

COMMENT ON COLUMN public.payroll_one_time_earnings.taxable IS
    'Whether this amount is salary under IT Act §17(1) and so enters the §192 '
    'projection and Form 16. TRUE for every earning; FALSE only for a genuine '
    'reimbursement of expenditure, which is not the employee''s income.';

COMMENT ON COLUMN public.payroll_one_time_earnings.payment_interval_months IS
    'How often this payment recurs, in months, where it recurs at all. NULL '
    'means paid once and not at an interval. Exists because ESI Act §2(22) '
    'draws its line at two months; it does NOT make the payment recur in the '
    '§192 projection — see domain/payroll/one_time_earnings.py.';

CREATE INDEX IF NOT EXISTS payroll_one_time_earnings_run_lookup_idx
  ON public.payroll_one_time_earnings (firm_id, client_id, month);

CREATE INDEX IF NOT EXISTS payroll_one_time_earnings_employee_idx
  ON public.payroll_one_time_earnings (employee_id, month);

-- ═══════════════════════════════════════════════════════════════════════════
-- 3. THE SLIP HAS TO RECONCILE
-- ═══════════════════════════════════════════════════════════════════════════
-- payroll_slips already stores every earning component so the payslip's
-- earnings block adds up to gross (migration 222's whole point). Folding a
-- one-time amount into gross without storing it would break exactly that: the
-- PDF would print seven lines summing to less than the gross printed under
-- them, with no line to point at.
--
-- Stored, not recomputed by re-reading payroll_one_time_earnings at payslip
-- time: the earnings rows can be edited or deleted after a run, and a released
-- payslip must keep saying what it said. Same reasoning as the PF EPS/EPF
-- split (migration 295) — the return must agree with the ledger, and two
-- implementations of one number drift.
--
-- Three columns, not one, because the two statutory bases are what the ECR and
-- the ESIC return read, and deriving them back out of a single total is
-- impossible once the rows are gone.

ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS one_time_earnings_paise      bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS one_time_pf_wages_paise      bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS one_time_esi_wages_paise     bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS one_time_taxable_paise       bigint NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.payroll_slips.one_time_earnings_paise IS
    'Total of the one-time and variable earnings paid in this slip''s month '
    '(migration 331). Included in gross_paise and NOT prorated by attendance. '
    'Stored so the payslip''s earnings block reconciles to gross after the '
    'source rows change.';

COMMENT ON COLUMN public.payroll_slips.one_time_pf_wages_paise IS
    'The part of one_time_earnings_paise that entered PF wages — EPF Act '
    '§2(b). Typically arrears of basic or DA and nothing else. Stored because '
    'the ECR reads it and the source rows may be gone by then.';

COMMENT ON COLUMN public.payroll_slips.one_time_esi_wages_paise IS
    'The part of one_time_earnings_paise that entered ESI wages — ESI Act '
    '§2(22), additional remuneration paid at intervals not exceeding two '
    'months. Stored for the same reason as the PF figure.';

COMMENT ON COLUMN public.payroll_slips.one_time_taxable_paise IS
    'The part of one_time_earnings_paise that is salary under IT Act §17(1). '
    'Added to the §192 projection ONCE — not multiplied across the months '
    'still to come, which is what folding a bonus into the monthly rate would '
    'have done.';

ALTER TABLE public.payroll_runs
  ADD COLUMN IF NOT EXISTS total_one_time_paise bigint NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.payroll_runs.total_one_time_paise IS
    'How much of total_gross_paise was one-time or variable earnings rather '
    'than the recurring salary bill (migration 331). The single figure that '
    'answers "why is this month bigger than last month" before anybody opens a '
    'slip. NOT backfilled — runs before this migration had no way to record '
    'such an earning, so zero on them is the truth and not a default.';

-- ═══════════════════════════════════════════════════════════════════════════
-- 4. WHO MAY WRITE IT
-- ═══════════════════════════════════════════════════════════════════════════
-- Firm-scoped, Manager+ to write — the same shape as attendance (326) and for
-- the same reason: this decides what somebody is paid, the frontend reaches
-- ~83 tables directly through PostgREST where rbac() never runs, and RLS is
-- therefore the only control. RESTRICTIVE so the role policies NARROW the firm
-- policy rather than ORing with it.

DO $$
DECLARE t text := 'payroll_one_time_earnings';
BEGIN
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

  EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'firm_' || t, t);
  EXECUTE format(
    'CREATE POLICY %I ON public.%I FOR ALL TO authenticated '
    'USING (firm_id = public.get_my_firm_id()) '
    'WITH CHECK (firm_id = public.get_my_firm_id())', 'firm_' || t, t);

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

  EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);

  IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column'
                                     AND pronamespace = 'public'::regnamespace) THEN
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I', t || '_updated_at', t);
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE UPDATE ON public.%I '
      'FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column()',
      t || '_updated_at', t);
  END IF;
END $$;

COMMIT;
