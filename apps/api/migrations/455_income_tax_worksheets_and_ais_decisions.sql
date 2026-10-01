-- 455: the house-property and salary worksheets are kept, and a CA's
--      accept or reject on an AIS line is recorded (TDS-INCOME-TAX-14, -15, -10).
--
-- WHY THESE TWO TABLES AND NOT A THIRD PLACE TO TYPE
--   Three findings, one shape: a figure the computation takes as a single typed
--   box (house property, salary, other income) is really the RESULT of a
--   working, and the working was done on paper first. The working is the CA's
--   own work. Keeping it in the browser would be the third path CLAUDE.md
--   already records going wrong three times (ACC-06): a page that stores the
--   user's work in localStorage loses it on another device and shows it to no
--   reviewer. So the worksheets are rows.
--
-- income_tax_worksheets
--   ONE row per (firm, client, financial year, kind) holding the CA's INPUTS —
--   the properties and what was received and paid on each, the employers and
--   what each paid. NOTHING DERIVED IS STORED: the net annual value, the 30%,
--   the interest allowed, the head's income, Schedule S's total — each is a
--   function of the inputs AND of the regime and the year's rates, and the
--   regime is chosen on the computation screen, not here. A stored figure goes
--   wrong the day the regime flips or a Finance Act moves a limit; it is
--   recomputed on every read, the reasoning migration 278 applied to
--   outstanding_paise. `payload_json` is therefore free-shaped JSON validated at
--   the API door (models/income_tax_worksheets), the same shape
--   `tax_audit_checklists.clauses_json` (014) takes for the same reason: the
--   vocabulary is Python's and a CHECK cannot read it.
--
--   `worksheet_kind` IS CHECKed, because unlike the payload it is a closed pair
--   the router dispatches on.
--
-- ais_computation_decisions
--   Whether the CA ACCEPTED or REJECTED the computation's suggestion built from
--   one AIS line — a salary, an interest or a dividend total. It stores the
--   figure the decision was made ON, because a fresh statement can change the
--   line: a decision against a figure that has since moved is shown as made on
--   an earlier figure and asked again, never silently carried onto a number the
--   CA has not seen. (ais_reconciliations, migration 352, carries a CA's
--   working against the BOOKS and is keyed on the record; this is a different
--   fact — whether a figure goes into the COMPUTATION — keyed on the bucket,
--   because a suggestion is a total over several records.)
--
--   `line_key` is CHECKed to the three lines the computation can take. The
--   others — a sale of securities, a property sale, a foreign remittance, rent —
--   are REFUSED a prefill by the service for their own reasons, and a decision
--   recorded against one would be a control that does nothing.
--
-- ISOLATION, IN THE SHAPE 352 ESTABLISHED, PLUS THE ASSIGNMENT SCOPE
--   firm-scoped policy plus RESTRICTIVE role guards at the Executive tier:
--   preparing a working is preparation work, and the same tier writes the AIS
--   and 26AS reconciliations. Delete is Manager.
--
--   AND A RESTRICTIVE <table>_assignment_scope POLICY, which an earlier draft of
--   this header argued away ("every read goes through apps/api ... it would
--   protect a path nothing uses"). That argument was wrong. The tables hold a
--   client's salary, rent and interest, `authenticated` holds full CRUD on them
--   (the GRANT below, and Supabase's default privileges would hand it over
--   anyway), and PostgREST does not ask which tables a screen happens to read:
--   a Manager assigned to client A, with the anon key and their own JWT, could
--   read client B's working papers and an Executive could insert, change or
--   (Manager) delete them. The API path IS assignment-scoped (assert_client_access)
--   and the policy makes the direct path agree with it — on that path RLS is the
--   only control. Migration 084's one-shot loop has never run again (see 370), so
--   a table is firm-wide unless the migration that creates it says otherwise;
--   every client_id table created since 370 says so, and so does this one, in
--   the shape 389 and 407 use: RESTRICTIVE (it can only REMOVE access), FOR ALL
--   (a policy on SELECT alone would leave the writes open) and
--   can_access_client(client_id::text), which lets a Partner through and asks
--   everyone else for an assignment row. Held from the migration text by
--   tests/test_a_client_table_a_migration_creates_is_assignment_scoped.py and
--   from the database by test_income_tax_worksheets_and_ais_decisions_pg.py,
--   which connects as `authenticated` and tries the statements.
--
-- ADDITIVE AND IDEMPOTENT. Two new tables, no existing row touched.

BEGIN;

CREATE TABLE IF NOT EXISTS public.income_tax_worksheets (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         uuid NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id       uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year  text NOT NULL CHECK (financial_year ~ '^[0-9]{4}-[0-9]{2}$'),
  worksheet_kind  text NOT NULL CHECK (worksheet_kind IN ('house_property', 'salary')),
  payload_json    jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_by      uuid REFERENCES public.users(id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),

  -- One worksheet of each kind per client per year. The inputs are replaced,
  -- not versioned: the computation snapshot (tax_computation_snapshots) is the
  -- record of what a computation used, and this is the CA's working paper.
  UNIQUE (firm_id, client_id, financial_year, worksheet_kind)
);

COMMENT ON TABLE public.income_tax_worksheets IS
  'The CA''s INPUTS for the house-property and salary (Schedule S) worksheets, '
  'one row per client, year and kind. Nothing derived is stored: the income, '
  'the deductions and the limits depend on the regime and the year and are '
  'recomputed on every read (domain/income_tax/house_property, schedule_s). '
  'Migration 455.';

CREATE INDEX IF NOT EXISTS idx_income_tax_worksheets_client
  ON public.income_tax_worksheets (firm_id, client_id, financial_year);

CREATE TABLE IF NOT EXISTS public.ais_computation_decisions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id          uuid NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id        uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  -- AIS is published per ASSESSMENT year, and the decision follows the
  -- statement it was made on (352's reasoning).
  assessment_year  text NOT NULL CHECK (assessment_year ~ '^[0-9]{4}-[0-9]{2}$'),
  line_key         text NOT NULL CHECK (line_key IN ('salary', 'interest', 'dividend')),
  decision         text NOT NULL CHECK (decision IN ('accepted', 'rejected')),
  -- The figure the CA was LOOKING AT when they decided. Compared with the
  -- statement's current total to tell a standing decision from a stale one.
  amount_paise     bigint NOT NULL CHECK (amount_paise >= 0),
  decided_by       uuid REFERENCES public.users(id),
  decided_at       timestamptz NOT NULL DEFAULT now(),

  UNIQUE (firm_id, client_id, assessment_year, line_key)
);

COMMENT ON TABLE public.ais_computation_decisions IS
  'Whether a CA accepted or rejected the computation''s suggestion built from '
  'one AIS line (salary, interest or dividend), with the figure it was made '
  'on so a later, different statement is asked again rather than carried. '
  'Distinct from ais_reconciliations (352), which is the working against the '
  'books. Migration 455.';

CREATE INDEX IF NOT EXISTS idx_ais_computation_decisions_client
  ON public.ais_computation_decisions (firm_id, client_id, assessment_year);

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['income_tax_worksheets', 'ais_computation_decisions']
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'firm_' || t, t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR ALL TO authenticated '
      'USING (firm_id = public.get_my_firm_id()) '
      'WITH CHECK (firm_id = public.get_my_firm_id())', 'firm_' || t, t);

    -- The assignment scope. Both halves are named, USING for what a caller may
    -- read, change or delete and WITH CHECK for what they may write: without
    -- the second, an Executive assigned to A could INSERT a row naming B.
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_assignment_scope', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL TO authenticated '
      'USING (public.can_access_client(client_id::text)) '
      'WITH CHECK (public.can_access_client(client_id::text))',
      t || '_assignment_scope', t);

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_insert', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR INSERT '
      'WITH CHECK (public.my_role_at_least(%L))', t || '_role_insert', t, 'Executive');

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_update', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR UPDATE '
      'USING (public.my_role_at_least(%L)) WITH CHECK (public.my_role_at_least(%L))',
      t || '_role_update', t, 'Executive', 'Executive');

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_role_delete', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR DELETE '
      'USING (public.my_role_at_least(%L))', t || '_role_delete', t, 'Manager');

    EXECUTE format(
      'GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
  END LOOP;
END $$;

COMMIT;
