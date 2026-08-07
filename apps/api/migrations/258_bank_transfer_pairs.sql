-- Migration 258: pair the two halves of one transfer (Tier 1.5).
--
-- WHY THIS EXISTS
-- Move ₹5,00,000 between two of the client's own accounts and it lands on TWO
-- statements: a debit on one, a credit on the other. One real movement, seen
-- twice. Coded independently, that becomes two journals and ₹10,00,000 of
-- apparent activity — the easiest way to silently overstate a P&L from a bank
-- feed.
--
-- ── THE HALF THAT IS NOT DETECTION ──────────────────────────────────────────
-- posting_map.build_transfer_lines already writes the COMPLETE double entry for
-- a transfer (Dr destination, Cr source). So finding the pair is not enough:
-- if both bank lines then post, the cash is double-counted anyway — the exact
-- bug this feature exists to prevent, just arrived at more tidily.
--
-- Hence transfer_is_primary. Exactly one side of a pair carries the journal —
-- the OUTFLOW, because a transfer is naturally described from the account the
-- money left. The counterpart is marked, shown as part of the transfer, and
-- never produces a journal of its own.
--
-- ── WHY NOT REUSE matched_entity_type/matched_entity_id ─────────────────────
-- That pair means "this bank line settles this business document", and its
-- CHECK vocabulary (migration 096) is a closed list of document types. A
-- transfer counterpart is not a document and does not settle anything;
-- overloading those columns would make every settlement code path have to ask
-- "…unless it is actually a transfer", which is how the settlement logic starts
-- being wrong in ways nobody notices.
--
-- ── WHY AN RPC RATHER THAN TWO UPDATES ──────────────────────────────────────
-- A pair is mutual: each row points at the other, and exactly one is primary.
-- Written as two statements through PostgREST — which commits each separately —
-- a failure between them leaves ONE side pointing at a partner that does not
-- point back, and that half-paired line would then post its own journal.
-- pair_bank_transfer() writes both sides in one transaction, or neither.

BEGIN;

ALTER TABLE public.bank_transactions
  ADD COLUMN IF NOT EXISTS transfer_pair_id    UUID,
  ADD COLUMN IF NOT EXISTS transfer_is_primary BOOLEAN,
  ADD COLUMN IF NOT EXISTS transfer_paired_at  TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS transfer_paired_by  UUID;

-- Both or neither. A pair id with no primary flag cannot say which side posts,
-- and a primary flag with no pair id points at nothing.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.bank_transactions'::regclass
      AND conname  = 'bank_transactions_transfer_pair_check'
  ) THEN
    ALTER TABLE public.bank_transactions
      ADD CONSTRAINT bank_transactions_transfer_pair_check
      CHECK ((transfer_pair_id IS NULL     AND transfer_is_primary IS NULL)
          OR (transfer_pair_id IS NOT NULL AND transfer_is_primary IS NOT NULL));
  END IF;
END $$;

-- A line cannot be its own counterpart.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.bank_transactions'::regclass
      AND conname  = 'bank_transactions_transfer_not_self_check'
  ) THEN
    ALTER TABLE public.bank_transactions
      ADD CONSTRAINT bank_transactions_transfer_not_self_check
      CHECK (transfer_pair_id IS NULL OR transfer_pair_id <> id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bank_txns_transfer_pair
    ON public.bank_transactions (transfer_pair_id)
    WHERE transfer_pair_id IS NOT NULL;

COMMENT ON COLUMN public.bank_transactions.transfer_pair_id IS
    'Tier 1.5 — the OTHER bank line of the same movement between the client''s '
    'own accounts. Mutual: each row points at the other. Written only by '
    'pair_bank_transfer().';
COMMENT ON COLUMN public.bank_transactions.transfer_is_primary IS
    'true on the side that carries the journal (the outflow). The counterpart '
    'never produces a journal — build_transfer_lines already writes BOTH legs, '
    'so posting both sides would double-count the cash.';

-- ── Pair, atomically ────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.pair_bank_transfer(
    p_firm_id     UUID,
    p_primary_id  UUID,      -- the outflow (debit) side
    p_counter_id  UUID,      -- the inflow (credit) side
    p_actor_id    UUID DEFAULT NULL
)
RETURNS SETOF public.bank_transactions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE
    a public.bank_transactions%ROWTYPE;
    b public.bank_transactions%ROWTYPE;
    a_acct UUID; b_acct UUID;
BEGIN
    IF p_primary_id = p_counter_id THEN
        RAISE EXCEPTION 'A transaction cannot be its own transfer counterpart.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    SELECT * INTO a FROM public.bank_transactions
     WHERE id = p_primary_id AND firm_id = p_firm_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Bank transaction not found for this firm.'
            USING ERRCODE = 'no_data_found';
    END IF;
    SELECT * INTO b FROM public.bank_transactions
     WHERE id = p_counter_id AND firm_id = p_firm_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Bank transaction not found for this firm.'
            USING ERRCODE = 'no_data_found';
    END IF;

    IF a.client_id <> b.client_id THEN
        RAISE EXCEPTION 'Both sides of a transfer must belong to the same client.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF a.posted_journal_id IS NOT NULL OR b.posted_journal_id IS NOT NULL THEN
        RAISE EXCEPTION
            'One of these transactions already has a journal. Reverse it before '
            'pairing them as a transfer.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    IF a.transfer_pair_id IS NOT NULL OR b.transfer_pair_id IS NOT NULL THEN
        RAISE EXCEPTION 'One of these transactions is already paired as a transfer.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- Direction: exactly one out, one in. Two debits are not a transfer however
    -- well they match.
    IF NOT (COALESCE(a.debit_paise,0) > 0 AND COALESCE(b.credit_paise,0) > 0) THEN
        RAISE EXCEPTION
            'A transfer pairs one payment out with one receipt in. The primary '
            'side must be the outflow.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- Exact paise. A transfer that arrives short is a transfer PLUS a bank
    -- charge — two facts, and pairing them as one would bury the charge.
    IF COALESCE(a.debit_paise,0) <> COALESCE(b.credit_paise,0) THEN
        RAISE EXCEPTION
            'The two sides differ (% paise out, % paise in). A transfer that '
            'arrives short is a transfer plus a charge — record them separately.',
            a.debit_paise, b.credit_paise
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- Different accounts, resolved through each line's statement.
    SELECT bank_account_id INTO a_acct FROM public.bank_statements WHERE id = a.statement_id;
    SELECT bank_account_id INTO b_acct FROM public.bank_statements WHERE id = b.statement_id;
    IF a_acct IS NULL OR b_acct IS NULL OR a_acct = b_acct THEN
        RAISE EXCEPTION
            'A transfer moves money between two DIFFERENT accounts of this client.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    UPDATE public.bank_transactions
       SET transfer_pair_id = p_counter_id, transfer_is_primary = true,
           category = 'Transfer', transfer_paired_at = now(),
           transfer_paired_by = p_actor_id, updated_at = now()
     WHERE id = p_primary_id;

    UPDATE public.bank_transactions
       SET transfer_pair_id = p_primary_id, transfer_is_primary = false,
           category = 'Transfer', transfer_paired_at = now(),
           transfer_paired_by = p_actor_id, updated_at = now()
     WHERE id = p_counter_id;

    RETURN QUERY SELECT * FROM public.bank_transactions
                  WHERE id IN (p_primary_id, p_counter_id);
END;
$$;

-- ── Unpair, atomically ──────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.unpair_bank_transfer(
    p_firm_id UUID,
    p_txn_id  UUID
)
RETURNS SETOF public.bank_transactions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE t public.bank_transactions%ROWTYPE; other UUID;
BEGIN
    SELECT * INTO t FROM public.bank_transactions
     WHERE id = p_txn_id AND firm_id = p_firm_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Bank transaction not found for this firm.'
            USING ERRCODE = 'no_data_found';
    END IF;
    IF t.transfer_pair_id IS NULL THEN
        RETURN;                                   -- already unpaired; idempotent
    END IF;
    IF t.posted_journal_id IS NOT NULL THEN
        RAISE EXCEPTION
            'This transfer already has a journal. Reverse it before unpairing.'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    other := t.transfer_pair_id;

    -- The category is left alone: 'Transfer' may well still be the right answer,
    -- and silently reverting it would undo a judgement the CA may have made
    -- independently of the pairing.
    UPDATE public.bank_transactions
       SET transfer_pair_id = NULL, transfer_is_primary = NULL,
           transfer_paired_at = NULL, transfer_paired_by = NULL, updated_at = now()
     WHERE id IN (p_txn_id, other) AND firm_id = p_firm_id;

    RETURN QUERY SELECT * FROM public.bank_transactions
                  WHERE id IN (p_txn_id, other);
END;
$$;

REVOKE ALL ON FUNCTION public.pair_bank_transfer(UUID, UUID, UUID, UUID)   FROM PUBLIC;
REVOKE ALL ON FUNCTION public.unpair_bank_transfer(UUID, UUID)             FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.pair_bank_transfer(UUID, UUID, UUID, UUID)   TO service_role;
GRANT EXECUTE ON FUNCTION public.unpair_bank_transfer(UUID, UUID)             TO service_role;

-- ── Post-conditions ─────────────────────────────────────────────────────────
DO $verify$
DECLARE missing text[] := ARRAY[]::text[]; c text;
BEGIN
    FOREACH c IN ARRAY ARRAY['transfer_pair_id','transfer_is_primary',
                             'transfer_paired_at','transfer_paired_by'] LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='bank_transactions'
                          AND column_name=c) THEN
            missing := missing || c;
        END IF;
    END LOOP;
    IF array_length(missing, 1) > 0 THEN
        RAISE EXCEPTION 'Migration 258 failed: missing %', array_to_string(missing, ', ');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'pair_bank_transfer')
       OR NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'unpair_bank_transfer') THEN
        RAISE EXCEPTION 'Migration 258 failed: a transfer pairing function is missing.';
    END IF;

    -- SECURITY DEFINER functions taking a firm_id must not be callable by
    -- `authenticated` — it could pass any firm's id.
    IF has_function_privilege('authenticated',
            'public.pair_bank_transfer(uuid, uuid, uuid, uuid)', 'EXECUTE')
       OR has_function_privilege('authenticated',
            'public.unpair_bank_transfer(uuid, uuid)', 'EXECUTE') THEN
        RAISE EXCEPTION
            'Migration 258 failed: authenticated can execute a SECURITY DEFINER '
            'transfer function.';
    END IF;

    -- No existing row may already be half-paired.
    IF EXISTS (SELECT 1 FROM public.bank_transactions
                WHERE (transfer_pair_id IS NULL) <> (transfer_is_primary IS NULL)) THEN
        RAISE EXCEPTION 'Migration 258 failed: a row is half-paired.';
    END IF;
END
$verify$;

COMMIT;
