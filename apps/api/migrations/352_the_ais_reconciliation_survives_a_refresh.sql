-- ============================================================================
-- 352 — the AIS reconciliation is kept (IT-18)
--
-- WHAT WAS WRONG
--     apps/web/app/income-tax/ais/page.tsx is 776 lines with a JSON parser, a
--     transaction table and a books-comparison grid, and a grep of it for
--     `api.` / `apiFetch` / `supabase.from` / `fetch(` / `localStorage`
--     returned NOTHING. The whole reconciliation lived in React useState and
--     was gone on refresh.
--
--     Backend-side there was no AIS table, no AIS endpoint and no TIS
--     anything. So the one statement the Income-tax Department publishes about
--     what OTHERS reported paying the client — IT Act §285BB, the thing a CA
--     must review before filing an ITR because it is what a §143(1)(a)
--     adjustment and a §143(3) scrutiny are raised from — could be looked at
--     once and never recorded.
--
--     26AS has had exactly this shape since migration 156: an upload row,
--     parsed records, and a persisted reconciliation. This gives AIS the same
--     one.
--
-- WHY THREE TABLES AND NOT ONE
--     An upload is a FILE somebody produced on the portal on a date. A record
--     is one line of it. A reconciliation is a CA's WORKING against the books,
--     and it outlives any particular upload — a fresh AIS is published while
--     the reconciliation is half done, and the earlier working must not
--     vanish with the file it started from.
--
-- WHAT IS DELIBERATELY NOT HERE: A BOOKS FIGURE THIS MIGRATION CAN DERIVE
--     `books_amount_paise` is entered by the CA, and it is nullable, and NULL
--     means "nobody has looked" rather than nil. AIS categories do not map
--     onto ledger accounts by rule: "Interest from savings bank" could be one
--     account or six, and "Sale of securities" is a capital-gains computation
--     rather than a balance. Deriving it would be the same fabrication the
--     previous commit removed from detect_document_risks, which invented the
--     book income as 85% of the AIS income and reported the difference.
--
--     status is therefore also nullable-by-default 'not_reviewed', not
--     'matched'. A row nobody has looked at must never read as agreed.
--
-- IDEMPOTENT. Three new tables and nothing altered.
-- ============================================================================

BEGIN;

-- ═══════════════════════════════════════════════════════════════════════════
-- 1. The file
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.ais_uploads (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id            uuid NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id          uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  -- The ASSESSMENT year, not the financial year. AIS is published per AY and
  -- labelled that way on the portal, and storing the FY here would have a CA
  -- reconciling the wrong statement against the wrong return.
  assessment_year    text NOT NULL CHECK (assessment_year ~ '^[0-9]{4}-[0-9]{2}$'),

  -- What the taxpayer block of the file itself said, kept as filed. A PAN that
  -- does not match the client's is the first thing to check and cannot be
  -- checked if it is not stored.
  pan                text CHECK (pan IS NULL OR pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
  taxpayer_name      text,

  file_name          text,
  -- SHA-256 of the bytes uploaded. A re-upload of the SAME file is the
  -- ordinary case (a CA re-downloads to check) and must be recognised rather
  -- than duplicated; a DIFFERENT file for the same year is a fresh statement
  -- and gets its own row.
  file_hash          text,
  record_count       integer NOT NULL DEFAULT 0,
  total_amount_paise bigint  NOT NULL DEFAULT 0,
  total_tds_paise    bigint  NOT NULL DEFAULT 0,

  -- Sentences the parser composed about what it could not read. A file that
  -- parsed with problems is not a file that parsed.
  problems           jsonb   NOT NULL DEFAULT '[]'::jsonb,

  uploaded_by        uuid REFERENCES public.users(id),
  created_at         timestamptz NOT NULL DEFAULT now(),

  UNIQUE (firm_id, client_id, assessment_year, file_hash)
);

COMMENT ON TABLE public.ais_uploads IS
  'One Annual Information Statement JSON as downloaded from the income-tax '
  'portal (IT Act s.285BB). The UNIQUE on file_hash makes a re-upload of the '
  'same bytes idempotent while a genuinely new statement for the same '
  'assessment year gets its own row. Migration 352.';

CREATE INDEX IF NOT EXISTS idx_ais_uploads_firm_client
  ON public.ais_uploads (firm_id, client_id, assessment_year);

-- ═══════════════════════════════════════════════════════════════════════════
-- 2. Its lines
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.ais_records (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id             uuid NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id           uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  upload_id           uuid NOT NULL REFERENCES public.ais_uploads(id) ON DELETE CASCADE,
  assessment_year     text NOT NULL,

  -- The information category as the file words it, kept VERBATIM alongside the
  -- bucket the product sorts it into. The portal's own wording is what a CA
  -- searches the statement for, and a bucket is a lossy reading of it.
  information_source  text,
  information_label   text,
  transaction_type    text NOT NULL DEFAULT 'Other',

  payer               text,
  amount_paise        bigint NOT NULL DEFAULT 0,
  tds_deducted_paise  bigint NOT NULL DEFAULT 0,

  -- 'json' where the parser read it, 'manual' where a CA added a line the file
  -- did not carry. The two are not the same evidence and the screen says so.
  source              text NOT NULL DEFAULT 'json'
                      CHECK (source IN ('json', 'manual')),

  created_at          timestamptz NOT NULL DEFAULT now()
);

COMMENT ON COLUMN public.ais_records.transaction_type IS
  'The bucket the product sorts the line into — Salary, Interest, Dividend, '
  'Stock Sale, Property Sale, Foreign Remittance, Rent Received, Other. A '
  'reading of information_label, which is kept verbatim beside it because the '
  'portal wording is what a CA searches the statement for.';

CREATE INDEX IF NOT EXISTS idx_ais_records_upload
  ON public.ais_records (upload_id);
CREATE INDEX IF NOT EXISTS idx_ais_records_firm_client
  ON public.ais_records (firm_id, client_id, assessment_year);

-- ═══════════════════════════════════════════════════════════════════════════
-- 3. The CA's working against the books
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.ais_reconciliations (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id            uuid NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id          uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  record_id          uuid NOT NULL REFERENCES public.ais_records(id) ON DELETE CASCADE,
  assessment_year    text NOT NULL,

  -- NULLABLE, AND NULL MEANS NOBODY HAS LOOKED. Not nil. AIS categories do not
  -- map onto ledger accounts by rule, so this is a figure a CA supplies; a
  -- default of 0 would report every unreviewed line as income the books do not
  -- carry, which is a §143(1)(a) adjustment waiting to happen.
  books_amount_paise bigint,

  status             text NOT NULL DEFAULT 'not_reviewed'
                     CHECK (status IN ('not_reviewed', 'matched',
                                       'amount_mismatch', 'not_in_books',
                                       'explained')),
  -- Why a difference is acceptable. 'explained' without one is a conclusion
  -- with no working, so the service refuses it.
  note               text,

  reviewed_by        uuid REFERENCES public.users(id),
  reviewed_at        timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),

  -- One working per AIS line.
  UNIQUE (record_id)
);

COMMENT ON TABLE public.ais_reconciliations IS
  'A CA''s working for one AIS line against the books. Separate from '
  'ais_records because it outlives the upload: a fresh AIS is published while '
  'the reconciliation is half done, and the earlier working must not vanish '
  'with the file it started from. Migration 352.';

CREATE INDEX IF NOT EXISTS idx_ais_recons_firm_client
  ON public.ais_reconciliations (firm_id, client_id, assessment_year);

-- ═══════════════════════════════════════════════════════════════════════════
-- 4. Isolation, and the role-aware write guards
-- ═══════════════════════════════════════════════════════════════════════════
-- The shape migrations 260/261/304/305 established. RESTRICTIVE so they narrow
-- rather than widen — a permissive policy here would GRANT.
--
-- Executive tier, not Manager: recording what a statement says and comparing it
-- to the books is preparation work, and the same tier already writes the 26AS
-- reconciliation. Nothing here posts to the ledger or files anything.

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['ais_uploads', 'ais_records', 'ais_reconciliations']
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'firm_' || t, t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR ALL TO authenticated '
      'USING (firm_id = public.get_my_firm_id()) '
      'WITH CHECK (firm_id = public.get_my_firm_id())', 'firm_' || t, t);

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
