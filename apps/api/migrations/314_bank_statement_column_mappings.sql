-- 314: remember where an unrecognised bank keeps its columns.
--
-- WHY
--   domain/banking/normalizer._ADAPTERS knows six statement layouts: HDFC, SBI,
--   ICICI, Axis and two generic ones. Every other bank — Kotak, IDFC First,
--   PNB, Canara, Union, and every co-operative bank in the country — reached
--   'Unsupported bank statement format' and stopped. There was no way past it,
--   so a client banking anywhere unusual could not get a statement into the
--   product at all. That is the single most user-visible gap left in the bank
--   module (docs/audits/2026-08-02-bank-module-quickbooks-gap-audit.md, 3.2).
--
-- WHY A SAVED MAPPING AND NOT MORE ADAPTERS
--   An adapter is a guess about a layout nobody here has seen, and the audit
--   asks for eight of them. Guessing eight column orders from memory is how a
--   Canara adapter ships reading the balance column as a credit — silently
--   wrong numbers, which is the exact failure _validate_adapter exists to
--   prevent. A mapping is not a guess: the person holding the file says where
--   the columns are, once, and we keep the answer. It also generalises to
--   banks nobody thought of.
--
-- WHY THE FINGERPRINT IS PART OF THE KEY
--   A mapping is reused only for a file whose header row still matches. When a
--   bank changes its export — a column inserted, one renamed — the fingerprint
--   changes, the stale mapping stops being applied, and the CA is asked once
--   more. Keying on the account alone would silently read the new layout at the
--   old positions, which is the corruption this whole feature is trying not to
--   cause.
--
-- The mapping mirrors an _ADAPTERS entry exactly: column name -> 0-based index,
-- with either debit+credit or amount+drcr. Validated in
-- normalizer.validate_mapping before it is ever stored or used; the CHECK here
-- is the backstop for the direct-PostgREST path, not the primary guard.

BEGIN;

CREATE TABLE IF NOT EXISTS public.bank_statement_column_mappings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID NOT NULL REFERENCES public.firms(id)         ON DELETE CASCADE,
    client_id           UUID NOT NULL REFERENCES public.clients(id)       ON DELETE CASCADE,
    bank_account_id     UUID NOT NULL REFERENCES public.bank_accounts(id) ON DELETE CASCADE,
    -- sha256 of the normalised header row, truncated. Not a secret; a key.
    header_fingerprint  TEXT NOT NULL CHECK (btrim(header_fingerprint) <> ''),
    -- The labels the CA actually saw when they mapped it. Kept for display, so
    -- a saved mapping can be shown as "Date -> Txn Date" rather than "0 -> 0",
    -- and so a stale one can be recognised by a human.
    header_labels       JSONB NOT NULL,
    mapping             JSONB NOT NULL,
    created_by          UUID REFERENCES public.users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- The date and description are what make a row a transaction; without both
    -- there is nothing to import. The amount side is checked in the
    -- application, where the either/or between debit+credit and amount+drcr can
    -- be expressed with a message a CA can act on.
    CONSTRAINT bank_statement_column_mappings_has_date_desc CHECK (
        mapping ? 'date' AND mapping ? 'desc'
        AND jsonb_typeof(mapping->'date') = 'number'
        AND jsonb_typeof(mapping->'desc') = 'number'
    )
);

-- One mapping per (account, layout). ON CONFLICT targets this, so re-mapping a
-- layout updates in place rather than accumulating rival answers.
CREATE UNIQUE INDEX IF NOT EXISTS uq_bank_stmt_col_map_account_fingerprint
    ON public.bank_statement_column_mappings (bank_account_id, header_fingerprint);

CREATE INDEX IF NOT EXISTS idx_bank_stmt_col_map_firm_client
    ON public.bank_statement_column_mappings (firm_id, client_id);

COMMENT ON TABLE public.bank_statement_column_mappings IS
    'Where an unrecognised bank keeps its statement columns, as told to us once '
    'by the CA who had the file. Keyed by (bank_account_id, header_fingerprint) '
    'so a changed export layout is re-asked rather than silently misread. '
    'Migration 314.';

ALTER TABLE public.bank_statement_column_mappings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_bank_statement_column_mappings"
    ON public.bank_statement_column_mappings;
CREATE POLICY "firm_bank_statement_column_mappings"
    ON public.bank_statement_column_mappings
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());

-- Role-aware write guards, the shape migrations 260/261/304/305/310 established.
-- RESTRICTIVE so they narrow rather than widen. EXECUTIVE tier, matching
-- core/permissions banking.write: mapping a statement's columns is ordinary
-- bookkeeping done by whoever imports the statement, not a professional
-- position — and gating it above the person doing the import would leave them
-- unable to finish the job they are already permitted to start.
DO $$
DECLARE t text := 'bank_statement_column_mappings';
BEGIN
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
    'USING (public.my_role_at_least(%L))', t || '_role_delete', t, 'Executive');
END $$;

-- With USE_USER_JWT on, a request runs as `authenticated` and RLS is what
-- confines it — but RLS only narrows a privilege that exists. Without this the
-- policies above are enforcing on a role that cannot reach the table at all,
-- and every read and write fails for a reason that looks nothing like a
-- permission problem. Migration 310 does the same for dtaa_treaty_rates.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.bank_statement_column_mappings TO authenticated;

COMMIT;
