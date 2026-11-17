-- Migration 641: a payroll opening position per employee, for a client that comes onto the product part-way through a financial
-- year (POST-A-082).
--
-- WHAT WAS WRONG
--
-- Everything the §192 withholding, the ESI coverage rule and the year's totals know about "what was already paid this year" is
-- read from RELEASED payroll runs this product produced (`_tds_already_deducted_this_fy`, `_members_contributing_earlier_this_period`).
-- A CA firm wins clients all year, so a client that starts in October has months of salary, tax withheld, PF, ESI and professional
-- tax behind it that this product never saw. The run then spreads the whole year's tax over twelve months instead of the six
-- that remain, the s.192(3) true-up has nothing to correct, and ESI coverage for the contribution period cannot be established.
--
-- WHAT THIS DOES
--
-- One row per (client, employee, financial year): the month the client's payroll starts on this product and what the employee had
-- already been paid, had tax withheld on, and had deducted and remitted for PF, ESI and PT in the months BEFORE it. It is a
-- record a CA enters, not a back-dated run: nothing is posted to the ledger, no slip exists, nothing is remitted from here.
-- The engine reads it beside the released runs and only for a run month on or after `first_month_here`.
--
-- WHAT IT DOES NOT CARRY, and the screen says so: no previous-EMPLOYER salary or tax (s.192(2), Form 12B: POST-A-084, a
-- different fact with its own proof and its own reading, a separate table when it is built), no lifetime exemptions
-- (gratuity and leave encashment used), no PF or ESI wage base, and no figure for any month this product ran.
--
-- WHO MAY TOUCH IT: the API alone. No privilege is granted to `authenticated` (the browser reaches no payroll table, migrations
-- 549 and after); the row policies are kept as the second lock, with the assignment scope every client table carries.

CREATE TABLE IF NOT EXISTS public.payroll_opening_positions (
  id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                 UUID        NOT NULL REFERENCES public.firms(id)             ON DELETE CASCADE,
  client_id               UUID        NOT NULL REFERENCES public.clients(id)           ON DELETE CASCADE,
  employee_id             UUID        NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,
  financial_year          TEXT        NOT NULL,
  first_month_here        DATE        NOT NULL,
  months_paid             SMALLINT    NOT NULL,
  gross_paise             BIGINT      NOT NULL,
  tds_paise               BIGINT      NOT NULL,
  pf_employee_paise       BIGINT      NOT NULL,
  pf_employer_paise       BIGINT      NOT NULL,
  esi_employee_paise      BIGINT      NOT NULL,
  esi_employer_paise      BIGINT      NOT NULL,
  pt_paise                BIGINT      NOT NULL,
  -- NULL is "not known", which is not "no": an unknown is never read as a fact. TRUE says the employee contributed to ESI in an
  -- earlier month of the contribution period that `first_month_here` falls in.
  esi_contributed_earlier_in_period BOOLEAN,
  source_note             TEXT,
  entered_by              UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT payroll_opening_positions_one_per_year UNIQUE (firm_id, client_id, employee_id, financial_year),
  CONSTRAINT payroll_opening_positions_fy_label CHECK (financial_year ~ '^[0-9]{4}-[0-9]{2}$'),
  CONSTRAINT payroll_opening_positions_a_month CHECK (date_trunc('month', first_month_here)::date = first_month_here),
  CONSTRAINT payroll_opening_positions_months CHECK (months_paid BETWEEN 0 AND 11),
  CONSTRAINT payroll_opening_positions_amounts CHECK (
    gross_paise >= 0 AND tds_paise >= 0 AND pf_employee_paise >= 0 AND pf_employer_paise >= 0
    AND esi_employee_paise >= 0 AND esi_employer_paise >= 0 AND pt_paise >= 0),
  CONSTRAINT payroll_opening_positions_months_and_gross CHECK ((months_paid = 0) = (gross_paise = 0)),
  CONSTRAINT payroll_opening_positions_note CHECK (char_length(coalesce(source_note, '')) <= 500)
);

COMMENT ON TABLE public.payroll_opening_positions IS
  'POST-A-082, migration 641. What an employee had been paid and had deducted in the financial year BEFORE the client''s payroll started '
  'on this product: a record a CA enters, never a run. Read by the §192 withholding, the s.192(3) true-up and the ESI coverage rule for '
  'run months on or after first_month_here. Carries no previous-employer figure (POST-A-084) and posts nothing.';

CREATE INDEX IF NOT EXISTS idx_payroll_opening_positions_client_year
  ON public.payroll_opening_positions (firm_id, client_id, financial_year);

ALTER TABLE public.payroll_opening_positions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "payroll_opening_positions_firm_isolation" ON public.payroll_opening_positions;
CREATE POLICY "payroll_opening_positions_firm_isolation" ON public.payroll_opening_positions
  FOR ALL TO authenticated
  USING (firm_id = (SELECT public.get_my_firm_id()))
  WITH CHECK (firm_id = (SELECT public.get_my_firm_id()));

DROP POLICY IF EXISTS "payroll_opening_positions_assignment_scope" ON public.payroll_opening_positions;
CREATE POLICY "payroll_opening_positions_assignment_scope" ON public.payroll_opening_positions
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "payroll_opening_positions_internal_partner_only" ON public.payroll_opening_positions;
CREATE POLICY "payroll_opening_positions_internal_partner_only" ON public.payroll_opening_positions
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

REVOKE ALL ON public.payroll_opening_positions FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_opening_positions TO service_role;

DO $$
BEGIN
    PERFORM public.guard_client_firm('public.payroll_opening_positions');
    PERFORM public.guard_member_firm('public.payroll_opening_positions');
END $$;
