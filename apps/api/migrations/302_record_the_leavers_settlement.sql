-- ============================================================================
-- 302 — a leaver's settlement becomes a recorded, posted, taxed event
--
-- WHAT WAS WRONG
--     POST /employees/{id}/settlement composed salary to date, gratuity, leave
--     encashment, bonus, notice pay and recoveries, with the taxable and exempt
--     split per component — and NOTHING CONSUMED IT. It did not post to the
--     general ledger, did not withhold, did not become a payslip, and did not
--     reach §17(1) for the year. A CA had to read the figures off a screen and
--     re-enter the taxable part by hand before Q4.
--
--     The 1 September walk-through named this the largest remaining gap in the
--     module, and a wiring job rather than a statutory one. This is the wiring.
--
-- WHY A TABLE OF ITS OWN RATHER THAN A PAYSLIP
--     A settlement is not a payslip with a different date on it. Its components
--     have exempt portions (§10(10) on gratuity, §10(10AA) on leave) and sit on
--     DIFFERENT LINES of the salary head — leave encashment is §17(1)(va),
--     gratuity is §17(3) — and payroll_slips has no column for either fact.
--     Forcing them into a slip would either lose the exemption or misreport the
--     head, and both are wrong on a Form 16.
--
--     So the settlement is its own record, and the Annexure II builder reads it
--     alongside the year's slips. TDS, which behaves identically to any other
--     month's, is stored on the header so 24Q picks it up without a special
--     case.
--
-- WHY COMPONENTS ARE ROWS
--     A CA asked to justify the figure needs to see which statute produced
--     which part. Summing before storage loses exactly that, and the exempt
--     split with it.
--
-- ONE SETTLEMENT PER DEPARTURE
--     Unique on (employee_id, leaving_date) rather than on employee_id alone:
--     an employee rehired and settled again is unusual but real, and the risk
--     worth closing is SETTLING THE SAME DEPARTURE TWICE — which would double
--     the gratuity, double the GL posting and double the §17(1) figure, each
--     of them looking correct on its own.
--
-- Additive. No backfill: no settlement has ever been recorded, and inventing
-- one for an employee already marked resigned would put money in the ledger
-- that nobody paid.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.payroll_settlements (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id          UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id        UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  employee_id      UUID NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,

  fy               TEXT NOT NULL,          -- the FY the payment falls in (§15: receipt)
  leaving_date     DATE NOT NULL,

  -- Totals, all derived from the components below and stored so the ledger,
  -- the annexure and 24Q read one agreed figure rather than three recomputations.
  gross_paise      BIGINT NOT NULL DEFAULT 0,
  exempt_paise     BIGINT NOT NULL DEFAULT 0,
  taxable_paise    BIGINT NOT NULL DEFAULT 0,   -- what reaches §17(1)/§17(3)
  deductions_paise BIGINT NOT NULL DEFAULT 0,   -- notice pay, loans, other
  tds_paise        BIGINT NOT NULL DEFAULT 0,
  net_paid_paise   BIGINT NOT NULL DEFAULT 0,

  journal_entry_id UUID REFERENCES public.journal_entries(id),
  created_by       UUID REFERENCES public.users(id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_settlements_amounts_nonneg') THEN
    ALTER TABLE public.payroll_settlements
      ADD CONSTRAINT payroll_settlements_amounts_nonneg
      CHECK (gross_paise >= 0 AND exempt_paise >= 0 AND taxable_paise >= 0
             AND deductions_paise >= 0 AND tds_paise >= 0);
  END IF;
  -- The exempt part can never exceed the gross it is exempt FROM. A breach
  -- means a component was mis-composed, and it would understate §17(1).
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_settlements_exempt_le_gross') THEN
    ALTER TABLE public.payroll_settlements
      ADD CONSTRAINT payroll_settlements_exempt_le_gross
      CHECK (exempt_paise <= gross_paise);
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS payroll_settlements_employee_leaving_key
  ON public.payroll_settlements (employee_id, leaving_date);

CREATE INDEX IF NOT EXISTS payroll_settlements_client_fy_idx
  ON public.payroll_settlements (client_id, fy);

COMMENT ON COLUMN public.payroll_settlements.taxable_paise IS
  'What reaches the salary head for the year. Recoveries do NOT reduce it — '
  'taking notice pay back does not un-earn the salary — so it is the sum of '
  'the components net of their §10 exemptions and nothing else.';


CREATE TABLE IF NOT EXISTS public.payroll_settlement_components (
  id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  settlement_id  UUID NOT NULL REFERENCES public.payroll_settlements(id) ON DELETE CASCADE,

  -- 'earning' reaches the salary head; 'deduction' reduces only what is paid.
  kind           TEXT NOT NULL DEFAULT 'earning',
  label          TEXT NOT NULL,
  gross_paise    BIGINT NOT NULL DEFAULT 0,
  exempt_paise   BIGINT NOT NULL DEFAULT 0,
  -- 24Q Annexure II splits gross salary across these three lines, so a
  -- component has to carry which one it belongs on. Leave encashment is
  -- §17(1)(va) by statute; gratuity is §17(3) as a termination payment.
  tax_head       TEXT NOT NULL DEFAULT '17(1)',
  -- The §10 clause exempting part of it, for the annexure's breakup.
  exempt_section TEXT NOT NULL DEFAULT '',
  statute        TEXT NOT NULL DEFAULT '',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_settlement_components_kind_check') THEN
    ALTER TABLE public.payroll_settlement_components
      ADD CONSTRAINT payroll_settlement_components_kind_check
      CHECK (kind IN ('earning','deduction'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_settlement_components_head_check') THEN
    ALTER TABLE public.payroll_settlement_components
      ADD CONSTRAINT payroll_settlement_components_head_check
      CHECK (tax_head IN ('17(1)','17(2)','17(3)'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_settlement_components_exempt_le_gross') THEN
    ALTER TABLE public.payroll_settlement_components
      ADD CONSTRAINT payroll_settlement_components_exempt_le_gross
      CHECK (exempt_paise <= gross_paise AND exempt_paise >= 0 AND gross_paise >= 0);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS payroll_settlement_components_settlement_idx
  ON public.payroll_settlement_components (settlement_id);


-- ─── RLS: firm scope permissive, role gate restrictive (260/261's split) ────
ALTER TABLE public.payroll_settlements            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payroll_settlement_components  ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['payroll_settlements','payroll_settlement_components']
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_firm_scope', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR ALL '
      'USING (firm_id = public.get_my_firm_id()) '
      'WITH CHECK (firm_id = public.get_my_firm_id())',
      t || '_firm_scope', t);

    -- Recording a settlement releases money and ends an employment. Same tier
    -- as finalising a payroll run rather than as editing a salary: Partner.
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT '
      'WITH CHECK (public.my_role_at_least(%L))', t || '_role_insert', t, 'Partner');

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE '
      'USING (public.my_role_at_least(%L)) WITH CHECK (public.my_role_at_least(%L))',
      t || '_role_update', t, 'Partner', 'Partner');

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE '
      'USING (public.my_role_at_least(%L))', t || '_role_delete', t, 'Partner');
  END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_settlements           TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_settlement_components TO authenticated;
