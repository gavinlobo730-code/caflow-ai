-- ============================================================================
-- 296 — the employee's §192 declaration, and the proofs behind it
--
-- WHY
--     Every employee is withheld on the new regime with nothing but the
--     §16(ia) standard deduction, because there is nowhere for anyone to
--     declare anything. That is the right DEFAULT and the wrong ANSWER. CBDT
--     Circular 04/2023 of 05-04-2023 requires the employer to "seek information
--     from each of its employees ... regarding their intended tax regime", and
--     Rule 26C prescribes Form 12BB for the four claims an employee makes
--     against salary: HRA under §10(13A), leave travel under §10(5), interest
--     on borrowed capital under §24(b), and Chapter VI-A.
--
--     Without these tables an old-regime employee with a home loan is
--     over-withheld all year, and Annexure II — the input TRACES generates
--     Form 16 Part B from — reports four blanks a CA fills in by hand in May.
--
-- THE INTIMATION IS NOT THE ELECTION
--     `regime` here governs WITHHOLDING and nothing else. Circular 04/2023 is
--     express that intimating a regime to the employer "would not amount to
--     exercising option in terms of sub-section (6) of section 115BAC and the
--     person shall be required to do so separately". An employee with business
--     income who tells payroll "old regime" and never files Form 10-IEA is
--     withheld on one basis and assessed on the other. The §115BAC(6) election
--     lives in domain/income_tax/regime_election.py and is deliberately not
--     stored here — one column that meant both would guarantee the confusion.
--
-- WHY DECLARED AND VERIFIED ARE SEPARATE COLUMNS RATHER THAN ONE
--     Practice runs in two halves. For most of the year the employee has
--     declared an intention and produced nothing; from around January the
--     employer collects proofs and withholds on what was substantiated.
--     §192(1) makes the EMPLOYER answerable for a correct deduction, so a
--     declaration that never grew a proof has to stop reducing tax before the
--     year ends — otherwise the shortfall surfaces in Q4 with no salary left
--     to recover it from. A single column would have to be overwritten at
--     verification, losing what was claimed, which is the one thing an
--     assessing officer asks to see.
--
-- The unique index is the point of the header table: one declaration per
-- employee per financial year. Two would each look complete and payroll would
-- withhold on whichever it read first.
--
-- Additive and idempotent. No backfill — there are no declarations to migrate,
-- and inventing "new regime, nothing claimed" rows would be indistinguishable
-- from employees who actually said so.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.payroll_it_declarations (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id       UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id     UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  employee_id   UUID NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,
  fy            TEXT NOT NULL,                      -- "2025-26"
  regime        TEXT NOT NULL DEFAULT 'new',
  status        TEXT NOT NULL DEFAULT 'draft',

  -- Form 12BB, Rule 26C — HRA under §10(13A)
  rent_paid_declared_paise            BIGINT NOT NULL DEFAULT 0,
  rent_paid_verified_paise            BIGINT NOT NULL DEFAULT 0,
  landlord_name                       TEXT NOT NULL DEFAULT '',
  landlord_address                    TEXT NOT NULL DEFAULT '',
  landlord_pan                        TEXT NOT NULL DEFAULT '',
  rent_is_metro                       BOOLEAN NOT NULL DEFAULT false,

  -- Form 12BB — leave travel concession under §10(5)
  lta_declared_paise                  BIGINT NOT NULL DEFAULT 0,
  lta_verified_paise                  BIGINT NOT NULL DEFAULT 0,

  -- Form 12BB — interest on borrowed capital under §24(b)
  home_loan_interest_declared_paise   BIGINT NOT NULL DEFAULT 0,
  home_loan_interest_verified_paise   BIGINT NOT NULL DEFAULT 0,
  lender_name                         TEXT NOT NULL DEFAULT '',
  lender_pan                          TEXT NOT NULL DEFAULT '',

  -- §192(2B) — other income the employee reports so the employer withholds on
  -- it. Stored as declared only: the proviso lets it increase the withholding,
  -- never reduce it, so there is nothing for a proof to unlock.
  other_income_declared_paise         BIGINT NOT NULL DEFAULT 0,
  -- A house property loss, held as a POSITIVE number. It is the proviso's one
  -- exception — the only declared figure that may reduce the withholding — and
  -- §115BAC(2)(i) bars even that under the new regime.
  house_property_loss_declared_paise  BIGINT NOT NULL DEFAULT 0,

  proofs_verified     BOOLEAN NOT NULL DEFAULT false,
  submitted_at        TIMESTAMPTZ,
  verified_at         TIMESTAMPTZ,
  verified_by         UUID REFERENCES public.users(id),
  rejected_reason     TEXT NOT NULL DEFAULT '',

  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_it_declarations_regime_check') THEN
    ALTER TABLE public.payroll_it_declarations
      ADD CONSTRAINT payroll_it_declarations_regime_check
      CHECK (regime IN ('new','old'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_it_declarations_status_check') THEN
    ALTER TABLE public.payroll_it_declarations
      ADD CONSTRAINT payroll_it_declarations_status_check
      CHECK (status IN ('draft','submitted','verified'));
  END IF;
END $$;

-- One declaration per employee per year. See the header note.
CREATE UNIQUE INDEX IF NOT EXISTS payroll_it_declarations_employee_fy_key
  ON public.payroll_it_declarations (employee_id, fy);

CREATE INDEX IF NOT EXISTS payroll_it_declarations_client_fy_idx
  ON public.payroll_it_declarations (client_id, fy);

COMMENT ON COLUMN public.payroll_it_declarations.regime IS
  'The employee''s regime intimation to the EMPLOYER under CBDT Circular '
  '04/2023 — it governs withholding only. It is NOT the §115BAC(6) election, '
  'which is made in Form 10-IEA or the return itself; see '
  'domain/income_tax/regime_election.py. Defaults to ''new'' because '
  '§115BAC(1A) is the default regime and a missing intimation means exactly '
  'that.';

COMMENT ON COLUMN public.payroll_it_declarations.house_property_loss_declared_paise IS
  'A POSITIVE number holding a loss. §192(2B)''s proviso makes this the only '
  'declared figure that may reduce the tax deductible; §115BAC(2)(i) bars the '
  'set-off against salary under the new regime.';


-- ── The Chapter VI-A lines ───────────────────────────────────────────────────
-- A row per investment rather than a column per section: 80C alone runs to
-- twenty-odd clauses, the CA verifies proof by proof rather than section by
-- section, and a rejected line has to stay visible next to the accepted ones.
CREATE TABLE IF NOT EXISTS public.payroll_it_declaration_items (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id         UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  declaration_id  UUID NOT NULL REFERENCES public.payroll_it_declarations(id) ON DELETE CASCADE,
  section         TEXT NOT NULL,
  label           TEXT NOT NULL DEFAULT '',
  amount_declared_paise  BIGINT NOT NULL DEFAULT 0,
  amount_verified_paise  BIGINT NOT NULL DEFAULT 0,
  status          TEXT NOT NULL DEFAULT 'declared',
  proof_reference TEXT NOT NULL DEFAULT '',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_it_declaration_items_status_check') THEN
    ALTER TABLE public.payroll_it_declaration_items
      ADD CONSTRAINT payroll_it_declaration_items_status_check
      CHECK (status IN ('declared','verified','rejected'));
  END IF;
  -- A proof may support LESS than was claimed, never more. Enforced here as
  -- well as in domain/payroll/declarations.py because the frontend writes
  -- these tables directly through PostgREST (CLAUDE.md, "the frontend's second
  -- data path") where no rbac() or service-layer validation runs at all.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_it_declaration_items_verified_le_declared') THEN
    ALTER TABLE public.payroll_it_declaration_items
      ADD CONSTRAINT payroll_it_declaration_items_verified_le_declared
      CHECK (amount_verified_paise <= amount_declared_paise);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_it_declaration_items_amounts_nonneg') THEN
    ALTER TABLE public.payroll_it_declaration_items
      ADD CONSTRAINT payroll_it_declaration_items_amounts_nonneg
      CHECK (amount_declared_paise >= 0 AND amount_verified_paise >= 0);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS payroll_it_declaration_items_declaration_idx
  ON public.payroll_it_declaration_items (declaration_id);


-- ── RLS ──────────────────────────────────────────────────────────────────────
-- Firm scoping is PERMISSIVE (it grants), the role gate is RESTRICTIVE (it
-- checks) — the split migrations 260/261 established. A declaration carries an
-- employee's PAN-adjacent financial detail, so it is firm-scoped like every
-- other payroll table and never client-portal readable.
ALTER TABLE public.payroll_it_declarations      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payroll_it_declaration_items ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['payroll_it_declarations','payroll_it_declaration_items']
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_firm_scope', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR ALL '
      'USING (firm_id = public.get_my_firm_id()) '
      'WITH CHECK (firm_id = public.get_my_firm_id())',
      t || '_firm_scope', t);

    -- payroll:write is Manager and above (core/permissions.py), and these
    -- tables are written from the browser as well as the API, so the tier has
    -- to be stated here too.
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT '
      'WITH CHECK (public.my_role_at_least(%L))',
      t || '_role_insert', t, 'Manager');

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE '
      'USING (public.my_role_at_least(%L)) WITH CHECK (public.my_role_at_least(%L))',
      t || '_role_update', t, 'Manager', 'Manager');

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE '
      'USING (public.my_role_at_least(%L))',
      t || '_role_delete', t, 'Partner');
  END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_it_declarations      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_it_declaration_items TO authenticated;
