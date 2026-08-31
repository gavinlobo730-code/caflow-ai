-- ============================================================================
-- 299 — §17(2) perquisites, valued under Rule 3
--
-- WHY A TABLE OF VALUES RATHER THAN OF INPUTS
--     Rule 3's inputs are heterogeneous and numerous — a city's population for
--     accommodation, an engine's displacement for a car, the State Bank of
--     India's rate on the first day of the year for a loan, the number of meals
--     — and several of them are not payroll data at all. Storing them all would
--     be a schema for Rule 3 rather than for a payroll.
--
--     What every consumer needs is the VALUE and the rule it came from: the
--     annexure needs one §17(2) figure per employee, and a CA reviewing it needs
--     to see which rule produced each part and on what basis. So the row holds
--     the value, the rule, and the note explaining the working — the same
--     reasoning as migration 295, which stores the PF split rather than
--     recomputing it, because a return that disagrees with the ledger is worse
--     than no return.
--
--     The valuation itself stays in domain/payroll/perquisites.py and is
--     re-runnable at any time; this records what was decided for the year.
--
-- ONE ROW PER PERQUISITE, NOT ONE PER EMPLOYEE
--     An employee may have a flat and a car and a loan, each under a different
--     sub-rule. Summing them before storage would lose which rule produced
--     what, which is the first thing anyone asks when the figure is questioned.
--
-- Additive and idempotent. No backfill — nothing was valued before this, and
-- inventing perquisites for closed years would put figures in Form 16s that
-- nobody computed.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.payroll_perquisites (
  id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id      UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id    UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  employee_id  UUID NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,
  fy           TEXT NOT NULL,                 -- "2025-26"
  label        TEXT NOT NULL,                 -- "Accommodation", "Motor car", ...
  rule         TEXT NOT NULL DEFAULT '',      -- "Rule 3(1)", "Rule 3(2)", ...
  value_paise  BIGINT NOT NULL DEFAULT 0,
  note         TEXT NOT NULL DEFAULT '',      -- the working, in words
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_perquisites_value_nonneg') THEN
    ALTER TABLE public.payroll_perquisites
      ADD CONSTRAINT payroll_perquisites_value_nonneg CHECK (value_paise >= 0);
  END IF;
END $$;

-- One line per employee per rule per year. A second "Motor car" row for the
-- same year would double-count into Annexure II, and both rows would look
-- correct on their own.
CREATE UNIQUE INDEX IF NOT EXISTS payroll_perquisites_employee_fy_label_key
  ON public.payroll_perquisites (employee_id, fy, label);

CREATE INDEX IF NOT EXISTS payroll_perquisites_client_fy_idx
  ON public.payroll_perquisites (client_id, fy);

COMMENT ON TABLE public.payroll_perquisites IS
  'IT Act §17(2) perquisites valued under Rule 3. Holds the VALUE and the rule '
  'that produced it, not Rule 3''s inputs — see the migration header. Read by '
  'the 24Q Annexure II builder, which TRACES turns into Form 16 Part B.';

ALTER TABLE public.payroll_perquisites ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "payroll_perquisites_firm_scope" ON public.payroll_perquisites;
CREATE POLICY "payroll_perquisites_firm_scope" ON public.payroll_perquisites
  FOR ALL
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- payroll:write is Manager and above (core/permissions.py). A perquisite value
-- changes an employee's taxable salary, so it is the same tier that edits pay.
DROP POLICY IF EXISTS "payroll_perquisites_role_insert" ON public.payroll_perquisites;
CREATE POLICY "payroll_perquisites_role_insert" ON public.payroll_perquisites
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.my_role_at_least('Manager'));

DROP POLICY IF EXISTS "payroll_perquisites_role_update" ON public.payroll_perquisites;
CREATE POLICY "payroll_perquisites_role_update" ON public.payroll_perquisites
  AS RESTRICTIVE FOR UPDATE
  USING (public.my_role_at_least('Manager'))
  WITH CHECK (public.my_role_at_least('Manager'));

DROP POLICY IF EXISTS "payroll_perquisites_role_delete" ON public.payroll_perquisites;
CREATE POLICY "payroll_perquisites_role_delete" ON public.payroll_perquisites
  AS RESTRICTIVE FOR DELETE
  USING (public.my_role_at_least('Partner'));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_perquisites TO authenticated;
