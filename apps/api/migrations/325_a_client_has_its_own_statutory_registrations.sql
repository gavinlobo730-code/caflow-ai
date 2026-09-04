-- Migration 325: the establishment identifiers a client's statutory returns
-- carry, and which this platform held nowhere.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING
-- ═══════════════════════════════════════════════════════════════════════════
-- Three statutory outputs are finished, correct, and cannot be filed:
--
--   * domain/payroll/ecr.py       builds the EPFO ECR from the posted payslips
--   * domain/payroll/esic.py      builds the ESIC monthly contribution return
--   * domain/payroll/form24q.py   builds Form 24Q's Annexure I from payroll
--
-- Each of them is a return BY AN ESTABLISHMENT, and the establishment is
-- identified by a registration number this database did not have a column for.
-- A grep across the whole repo found exactly two `tan` columns — customers.tan
-- and form_26as_records.deductor_tan — and neither is the client's own TAN as
-- an employer. No EPF establishment code, no ESIC employer code, no
-- professional-tax registration, no LIN, anywhere.
--
-- The visible consequence is routers/tds.py: Compute24QRequest takes `tan`,
-- `deductor_name`, `deductor_pan` and `deductor_address` in the REQUEST BODY,
-- because there was nowhere to read them from. A CA who has just produced a
-- quarter's deductee rows from the books then retypes the deductor block by
-- hand, every quarter, for every client. A TAN keyed one character wrong files
-- the quarter against somebody else's account.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY TWO TABLES AND NOT ONE
-- ═══════════════════════════════════════════════════════════════════════════
-- Four of the five identifiers belong to the ENTITY: one TAN, one EPF
-- establishment code, one ESIC employer code, one LIN.
--
-- Professional tax does not. It is a STATE levy under Article 276(2), each
-- state registers employers itself, and an employer with staff in Maharashtra
-- and Karnataka holds two separate registrations that renew and change
-- independently. Putting it in the same row would mean either one PT column
-- that silently holds whichever state was entered last, or a row per state in
-- which the other four columns are NULL on every row but one — a table whose
-- meaning depends on which columns happen to be filled.
--
-- So: one row per client for the entity, one row per (client, state) for PT.
-- Every column on both tables applies to every row of it.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- ONLY TAN IS FORMAT-CHECKED, AND THAT IS DELIBERATE
-- ═══════════════════════════════════════════════════════════════════════════
-- TAN is four letters, five digits, one letter (`^[A-Z]{4}[0-9]{5}[A-Z]$`) —
-- the same well-settled shape as the PAN check clients.pan has carried since
-- migration 001, and the format TRACES itself rejects on.
--
-- The other four are stored as text with no pattern. The EPF establishment
-- code, the ESIC 17-digit employer code, the state PT registration numbers and
-- the Shram Suvidha LIN each have published conventions that vary by region,
-- by vintage, and by which office issued them. A CHECK written from memory
-- would not catch a typo — it would REFUSE A VALID REGISTRATION, and the CA
-- would have no way past it. That is the wrong direction of error for a field
-- whose whole purpose is to record a fact somebody read off a certificate.
--
-- The same reasoning the codebase already applies to the MSMED classification,
-- the DTAA treaty rates and the state PT slabs: where the truth has to come
-- from a human, take what they give you and do not invent a rule that argues
-- with it. What IS enforced is that a stored value is non-blank — an empty
-- string recorded as an identifier is the silent-default failure this whole
-- table exists to end.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- ABSENT IS NOT BLANK
-- ═══════════════════════════════════════════════════════════════════════════
-- Every identifier column is NULLABLE with no default, and the API reports a
-- missing one as a named gap on the output that needs it rather than emitting
-- the file with an empty field. A 24Q with a blank TAN is not a return with a
-- small omission; it is a return filed against no account.
--
-- Idempotent, safe to re-run. Two new tables and nothing altered.

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════════
-- 1. The entity's own registrations
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.client_statutory_identity (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id    uuid NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id  uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  -- Tax Deduction and Collection Account Number. IT Act s.203A; quoted on
  -- every TDS return, challan and certificate. Four letters, five digits, one
  -- letter.
  tan text CHECK (tan IS NULL OR tan ~ '^[A-Z]{4}[0-9]{5}[A-Z]$'),

  -- The EPFO establishment code the ECR is uploaded under, at
  -- unifiedportal-emp.epfindia.gov.in. Regional and not pattern-checked here.
  epf_establishment_code text CHECK (epf_establishment_code IS NULL
                                     OR length(btrim(epf_establishment_code)) > 0),

  -- The ESIC employer code the monthly contribution return is filed under.
  esic_employer_code text CHECK (esic_employer_code IS NULL
                                 OR length(btrim(esic_employer_code)) > 0),

  -- Labour Identification Number — the single id across the Shram Suvidha
  -- portal's labour returns.
  lin text CHECK (lin IS NULL OR length(btrim(lin)) > 0),

  note        text,
  updated_by  uuid REFERENCES public.users(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),

  UNIQUE (firm_id, client_id)
);

COMMENT ON TABLE public.client_statutory_identity IS
    'The registration numbers a client files its own statutory returns under, '
    'as an employer and a deductor: TAN, EPF establishment code, ESIC employer '
    'code, LIN. One row per client. Professional tax is NOT here — it is a '
    'state levy and lives in client_pt_registrations, one row per state. '
    'Every column is nullable with no default: a missing identifier is '
    'reported as a gap on the return that needs it, never emitted blank. '
    'Migration 325.';

COMMENT ON COLUMN public.client_statutory_identity.tan IS
    'The client''s own Tax Deduction and Collection Account Number (IT Act '
    's.203A) as an employer deducting under s.192. NOT customers.tan, which is '
    'a customer''s TAN, and NOT form_26as_records.deductor_tan, which is '
    'somebody else deducting FROM this client. Form 24Q is filed against this '
    'number; a wrong one files the quarter against another account.';

ALTER TABLE public.client_statutory_identity ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_statutory_identity" ON public.client_statutory_identity;
CREATE POLICY "firm_statutory_identity" ON public.client_statutory_identity
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());

-- ═══════════════════════════════════════════════════════════════════════════
-- 2. Professional tax, one registration per state
-- ═══════════════════════════════════════════════════════════════════════════
--
-- PTRC and PTEC are two different registrations and an employer usually holds
-- both, so they are two columns rather than one "PT number":
--
--   PTRC  Registration Certificate — the employer's authority to DEDUCT
--         professional tax from employees and deposit it. This is the one the
--         payroll run needs.
--   PTEC  Enrolment Certificate — the entity's OWN professional tax, payable
--         on itself, not deducted from anyone.
--
-- Recording one in the other's column means either paying the entity's own
-- levy against the employees' deductions or the reverse, in a state
-- department's ledger, which is unpleasant to unwind.

CREATE TABLE IF NOT EXISTS public.client_pt_registrations (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id    uuid NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id  uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  -- The two-letter code payroll_employees.pt_state carries and
  -- domain/payroll/professional_tax.py classifies — "MH", "KA", "TN".
  state text NOT NULL CHECK (state ~ '^[A-Z]{2}$'),

  ptrc_number text CHECK (ptrc_number IS NULL OR length(btrim(ptrc_number)) > 0),
  ptec_number text CHECK (ptec_number IS NULL OR length(btrim(ptec_number)) > 0),

  note        text,
  updated_by  uuid REFERENCES public.users(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),

  UNIQUE (firm_id, client_id, state)
);

COMMENT ON TABLE public.client_pt_registrations IS
    'One professional-tax registration per (client, state). PT is a state levy '
    'under Article 276(2) and an employer with staff in two states holds two '
    'independent registrations, so this is not a column on '
    'client_statutory_identity. ptrc_number is the employer''s authority to '
    'DEDUCT from employees; ptec_number is the entity''s own enrolment. A '
    'payroll run reports a state whose employees are marked pt_applicable and '
    'for which no PTRC is recorded. Migration 325.';

ALTER TABLE public.client_pt_registrations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_pt_registrations" ON public.client_pt_registrations;
CREATE POLICY "firm_pt_registrations" ON public.client_pt_registrations
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());

-- ═══════════════════════════════════════════════════════════════════════════
-- 3. Role-aware write guards
-- ═══════════════════════════════════════════════════════════════════════════
-- The shape migrations 260/261/304/305 established: RESTRICTIVE, so they
-- NARROW the firm policy above rather than granting alongside it. A permissive
-- policy here would be a second way in.
--
-- Manager tier, matching the payroll:write the endpoints require. These
-- numbers appear on filed returns — an Executive keying a TAN that then goes
-- onto a quarter's 24Q is a change somebody senior should be making.

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['client_statutory_identity', 'client_pt_registrations'] LOOP
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
  END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_statutory_identity TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_pt_registrations   TO authenticated;

-- ═══════════════════════════════════════════════════════════════════════════
-- 4. updated_at, the house trigger
-- ═══════════════════════════════════════════════════════════════════════════

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column'
                                     AND pronamespace = 'public'::regnamespace) THEN
    DROP TRIGGER IF EXISTS client_statutory_identity_updated_at ON public.client_statutory_identity;
    CREATE TRIGGER client_statutory_identity_updated_at
      BEFORE UPDATE ON public.client_statutory_identity
      FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

    DROP TRIGGER IF EXISTS client_pt_registrations_updated_at ON public.client_pt_registrations;
    CREATE TRIGGER client_pt_registrations_updated_at
      BEFORE UPDATE ON public.client_pt_registrations
      FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
  END IF;
END $$;

COMMIT;
