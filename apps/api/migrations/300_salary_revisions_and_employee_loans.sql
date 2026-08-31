-- ============================================================================
-- 300 — effective-dated salary revisions, and loans recovered through payroll
--
-- ─── WHY REVISIONS ──────────────────────────────────────────────────────────
--     An employee's pay lives on payroll_employees as ONE CURRENT VALUE.
--     Raising it in October overwrites what they were on before, and three
--     things are then true:
--
--       * there is no record of what changed, when it took effect, or why. A
--         CA asked to explain a jump in the March payroll has the new figure
--         and nothing else;
--       * a revision cannot be entered in advance. Someone whose raise takes
--         effect on 1 January must be edited ON 1 January, or the December run
--         pays the new rate;
--       * a BACKDATED revision — the ordinary case, since increments are
--         usually agreed months after they take effect — has nowhere to live.
--         Arrears are computed from the difference between what was paid and
--         what should have been, and that requires knowing both.
--
--     Historical payslips are safe: payroll_slips stores each component as
--     paid, so an earlier month's record does not change when the master does.
--     What is missing is the CHANGE itself, which is what this table records.
--
--     A revision holds the whole component set as at its effective date rather
--     than a delta. Deltas compose, and composing them across a backdated
--     revision inserted between two others gives a different answer depending
--     on the order they were entered.
--
-- ─── WHY LOANS ──────────────────────────────────────────────────────────────
--     Recovering an advance through the payslip is ordinary, and there was no
--     way to do it — which meant either an ad-hoc "other deduction" with no
--     running balance, or a payment outside payroll that never reaches the
--     ledger.
--
--     interest_rate_bps is on the row because Rule 3(7)(i) needs it: a loan at
--     less than the State Bank of India's rate is a PERQUISITE, valued at the
--     difference. An employer who lends interest-free and records only the
--     recovery has an unvalued perquisite in every employee's Form 16.
--
-- Additive and idempotent. No backfill: there are no revisions to reconstruct,
-- and inventing an effective date for the pay someone happens to be on today
-- would put a fact in the record that nobody established.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.payroll_salary_revisions (
  id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  employee_id    UUID NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,

  -- The first day the revision applies. A month's payroll uses the latest
  -- revision whose effective_from is on or before that month's start.
  effective_from DATE NOT NULL,

  basic_paise             BIGINT NOT NULL DEFAULT 0,
  hra_percent             NUMERIC(5,2) NOT NULL DEFAULT 0,
  da_percent              NUMERIC(5,2) NOT NULL DEFAULT 0,
  lta_paise               BIGINT NOT NULL DEFAULT 0,
  medical_paise           BIGINT NOT NULL DEFAULT 0,
  special_allowance_paise BIGINT NOT NULL DEFAULT 0,
  other_allowances_paise  BIGINT NOT NULL DEFAULT 0,

  reason         TEXT NOT NULL DEFAULT '',
  created_by     UUID REFERENCES public.users(id),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One revision per employee per effective date. Two would each look complete
-- and the run would use whichever it read first.
CREATE UNIQUE INDEX IF NOT EXISTS payroll_salary_revisions_employee_date_key
  ON public.payroll_salary_revisions (employee_id, effective_from);

CREATE INDEX IF NOT EXISTS payroll_salary_revisions_client_idx
  ON public.payroll_salary_revisions (client_id, effective_from);

COMMENT ON TABLE public.payroll_salary_revisions IS
  'Effective-dated salary history. Each row is the WHOLE component set as at '
  'its effective date, not a delta — deltas compose differently depending on '
  'the order a backdated revision was entered. A payroll month uses the latest '
  'revision effective on or before that month''s first day, and falls back to '
  'payroll_employees where there is none.';


CREATE TABLE IF NOT EXISTS public.payroll_loans (
  id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id                  UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  employee_id              UUID NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,

  principal_paise          BIGINT NOT NULL DEFAULT 0,
  outstanding_paise        BIGINT NOT NULL DEFAULT 0,
  monthly_instalment_paise BIGINT NOT NULL DEFAULT 0,
  -- Rule 3(7)(i): below the SBI rate for the same kind of loan, the shortfall
  -- is a perquisite. Zero here means interest-free, which is the case that
  -- most often goes unvalued.
  interest_rate_bps        INTEGER NOT NULL DEFAULT 0,

  purpose                  TEXT NOT NULL DEFAULT '',
  started_on               DATE,
  closed_on                DATE,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_loans_amounts_nonneg') THEN
    ALTER TABLE public.payroll_loans
      ADD CONSTRAINT payroll_loans_amounts_nonneg
      CHECK (principal_paise >= 0 AND outstanding_paise >= 0
             AND monthly_instalment_paise >= 0);
  END IF;
  -- An outstanding above the principal is arithmetically impossible on a
  -- non-interest-bearing recovery and signals a data error, not a big loan.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_loans_outstanding_le_principal') THEN
    ALTER TABLE public.payroll_loans
      ADD CONSTRAINT payroll_loans_outstanding_le_principal
      CHECK (outstanding_paise <= principal_paise);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS payroll_loans_employee_idx
  ON public.payroll_loans (employee_id) WHERE closed_on IS NULL;

COMMENT ON COLUMN public.payroll_loans.interest_rate_bps IS
  'Basis points a year. Rule 3(7)(i) values a loan below the State Bank of '
  'India''s rate for the same kind of loan as a perquisite, at the difference. '
  'Zero means interest-free — the case that most often goes unvalued.';


-- ─── RLS: firm scope permissive, role gate restrictive (260/261's split) ────
ALTER TABLE public.payroll_salary_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payroll_loans            ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['payroll_salary_revisions','payroll_loans']
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_firm_scope', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR ALL '
      'USING (firm_id = public.get_my_firm_id()) '
      'WITH CHECK (firm_id = public.get_my_firm_id())',
      t || '_firm_scope', t);

    -- payroll:write is Manager and up. Both tables change what an employee is
    -- paid, so they sit at the same tier as editing salary itself.
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
      'USING (public.my_role_at_least(%L))', t || '_role_delete', t, 'Partner');
  END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_salary_revisions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_loans            TO authenticated;
