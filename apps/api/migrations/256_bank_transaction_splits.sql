-- Migration 256: split one bank line across several GL accounts (Tier 1.2).
--
-- WHY THIS EXISTS
-- One debit on a statement is often several things. A ₹47,200 payment to a
-- landlord might be ₹40,000 of rent, ₹5,000 of maintenance and ₹2,200 of
-- parking. Until now the posting engine could only ever produce a TWO-line
-- entry — one bank leg, one counter leg — so the only way to record that was to
-- code the whole amount to one account and correct it later with a manual
-- journal.
--
-- ── THE INVARIANT, AND WHY IT NEEDS AN RPC ──────────────────────────────────
-- The splits must sum EXACTLY to the transaction amount. A journal that does
-- not account for every paise the bank moved either fails to balance or buries
-- the difference in whichever account happened to be last.
--
-- That is a constraint ACROSS ROWS, so a CHECK cannot express it. The obvious
-- alternative — a deferred constraint trigger — does not work here either: the
-- service reaches this table through PostgREST, where each statement commits on
-- its own, so a delete-then-insert would trip the trigger at the first commit
-- with the new rows not yet written.
--
-- Hence replace_bank_transaction_splits(): delete, insert and verify inside ONE
-- function invocation, which is one transaction. Either the whole split set
-- lands and ties, or nothing changes. This mirrors post_journal_atomic, which
-- exists for the same reason.
--
-- ── WHAT IS DELIBERATELY REFUSED ────────────────────────────────────────────
--   * a non-positive split      Direction comes from the bank line, not the
--                               split. A negative leg would let the total look
--                               right while describing a movement the bank
--                               never made.
--   * fewer than two splits     One "split" is an ordinary posting.
--   * editing after posting     The journal built from these splits is already
--                               on the books and is immutable (migration 251).
--                               Editing the splits underneath it would leave
--                               the ledger and its explanation disagreeing.

BEGIN;

CREATE TABLE IF NOT EXISTS public.bank_transaction_splits (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID        NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
    client_id           UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    bank_transaction_id UUID        NOT NULL
        REFERENCES public.bank_transactions(id) ON DELETE CASCADE,
    account_id          UUID        NOT NULL REFERENCES public.chart_of_accounts(id),
    -- Always positive. See the note above about direction.
    amount_paise        BIGINT      NOT NULL CHECK (amount_paise > 0),
    narration           TEXT,
    sequence_no         INTEGER     NOT NULL DEFAULT 0,
    created_by          UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bank_transaction_splits_txn
    ON public.bank_transaction_splits (bank_transaction_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_bank_transaction_splits_account
    ON public.bank_transaction_splits (firm_id, account_id);

ALTER TABLE public.bank_transaction_splits ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bank_transaction_splits_isolation ON public.bank_transaction_splits;
CREATE POLICY bank_transaction_splits_isolation ON public.bank_transaction_splits
    FOR ALL TO authenticated
    USING (firm_id = public.get_my_firm_id())
    WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.bank_transaction_splits TO authenticated;
GRANT ALL                            ON public.bank_transaction_splits TO service_role;

COMMENT ON TABLE public.bank_transaction_splits IS
    'Tier 1.2 — one bank line allocated across several GL accounts. Splits must '
    'sum exactly to the transaction amount; enforced by '
    'replace_bank_transaction_splits(), which is the only supported way to write '
    'this table.';

-- ── The atomic replace ──────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.replace_bank_transaction_splits(
    p_firm_id  UUID,
    p_txn_id   UUID,
    p_splits   JSONB,           -- [{account_id, amount_paise, narration}, ...]
    p_actor_id UUID DEFAULT NULL
)
RETURNS SETOF public.bank_transaction_splits
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_txn      public.bank_transactions%ROWTYPE;
    v_amount   BIGINT;
    v_total    BIGINT;
    v_count    INTEGER;
    v_bad      INTEGER;
BEGIN
    SELECT * INTO v_txn
      FROM public.bank_transactions
     WHERE id = p_txn_id AND firm_id = p_firm_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Bank transaction not found for this firm.'
            USING ERRCODE = 'no_data_found';
    END IF;

    -- The journal built from these splits is already posted and immutable
    -- (migration 251). Changing the splits under it would leave the ledger and
    -- its explanation disagreeing, with no trace of which is right.
    IF v_txn.posted_journal_id IS NOT NULL THEN
        RAISE EXCEPTION
            'This transaction already has a journal. Reverse it before changing '
            'how the amount is split.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    v_amount := GREATEST(COALESCE(v_txn.debit_paise, 0), COALESCE(v_txn.credit_paise, 0));
    IF v_amount <= 0 THEN
        RAISE EXCEPTION 'The transaction has no amount to split.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    DELETE FROM public.bank_transaction_splits WHERE bank_transaction_id = p_txn_id;

    -- Clearing the splits entirely is legitimate: it returns the transaction to
    -- an ordinary single-account posting.
    IF p_splits IS NULL OR jsonb_array_length(p_splits) = 0 THEN
        RETURN;
    END IF;

    SELECT count(*), coalesce(sum((e->>'amount_paise')::bigint), 0),
           count(*) FILTER (WHERE (e->>'amount_paise')::bigint <= 0)
      INTO v_count, v_total, v_bad
      FROM jsonb_array_elements(p_splits) e;

    IF v_bad > 0 THEN
        RAISE EXCEPTION
            'Every split must be a positive amount — they all move in the same '
            'direction as the bank line.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF v_count < 2 THEN
        RAISE EXCEPTION
            'A split needs at least two lines — for a single account, post it the '
            'ordinary way.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF v_total <> v_amount THEN
        RAISE EXCEPTION
            'The splits come to % paise but the transaction is % paise. Every '
            'paise the bank moved has to be accounted for.', v_total, v_amount
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    RETURN QUERY
    INSERT INTO public.bank_transaction_splits
        (firm_id, client_id, bank_transaction_id, account_id, amount_paise,
         narration, sequence_no, created_by)
    SELECT p_firm_id, v_txn.client_id, p_txn_id,
           (e->>'account_id')::uuid,
           (e->>'amount_paise')::bigint,
           nullif(btrim(coalesce(e->>'narration', '')), ''),
           (ord - 1)::int,
           p_actor_id
      FROM jsonb_array_elements(p_splits) WITH ORDINALITY AS t(e, ord)
    RETURNING *;
END;
$$;

-- SECURITY DEFINER, so it must not be callable by anyone who could pass another
-- firm's id. The service holds the service_role key; `authenticated` reaches
-- the table through RLS for reads and never calls this directly.
REVOKE ALL ON FUNCTION public.replace_bank_transaction_splits(UUID, UUID, JSONB, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.replace_bank_transaction_splits(UUID, UUID, JSONB, UUID)
    TO service_role;

-- ── Post-conditions ─────────────────────────────────────────────────────────
DO $verify$
BEGIN
    IF to_regclass('public.bank_transaction_splits') IS NULL THEN
        RAISE EXCEPTION 'Migration 256 failed: bank_transaction_splits was not created.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_proc
                    WHERE proname = 'replace_bank_transaction_splits') THEN
        RAISE EXCEPTION 'Migration 256 failed: the atomic replace function is missing.';
    END IF;

    -- Isolation on BOTH read and write. A policy without WITH CHECK would still
    -- constrain INSERT (Postgres reuses USING), but stating it explicitly is
    -- what the rest of this schema does and what 252's parity check expects.
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
         WHERE schemaname = 'public' AND tablename = 'bank_transaction_splits'
           AND qual IS NOT NULL AND with_check IS NOT NULL
    ) THEN
        RAISE EXCEPTION
            'Migration 256 failed: bank_transaction_splits needs an RLS policy '
            'with both USING and WITH CHECK.';
    END IF;

    -- `authenticated` must not be able to invoke a SECURITY DEFINER function
    -- that takes a firm_id as an argument.
    IF has_function_privilege('authenticated',
            'public.replace_bank_transaction_splits(uuid, uuid, jsonb, uuid)', 'EXECUTE') THEN
        RAISE EXCEPTION
            'Migration 256 failed: authenticated can execute the SECURITY DEFINER '
            'split replace function.';
    END IF;
END
$verify$;

COMMIT;
