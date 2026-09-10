-- Migration 355: a reconciliation adjustment has to say what it is.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 102 added `adjustments_paise bigint NOT NULL DEFAULT 0` with no
-- companion reason, narration or itemisation column, and
-- domain/banking/reconciliation.tie_out folds it straight into the book
-- balance. So an Executive who cannot find a ₹47,300 difference could type
-- 47300 into "Adjustment (₹)", watch the tie-out go green, press Complete, and
-- the firm would hold a frozen, certified "Bank Reconciliation Statement" PDF
-- with an "Adjustments" line that means nothing. Nobody reading that document —
-- including the partner reviewing it — could tell what the ₹47,300 was.
--
-- The contrast inside this same table is the tell: reopening a completed
-- reconciliation demands a reason of at least ten characters, enforced by a
-- CHECK (migration 253), because an unexplained reversal in the audit trail is
-- barely better than no trail. Forcing a period to tie out is the same kind of
-- act and had none of it.
--
-- Tally's BRS has no plug field at all; Zoho Books makes you match or create a
-- transaction; QuickBooks forces an explicit discrepancy journal that posts to
-- the ledger. None of them lets a number reconcile by assertion.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT
-- ═══════════════════════════════════════════════════════════════════════════
-- It makes the adjustment ACCOUNTABLE: a reason travelling with the figure,
-- who set it and when, and a CHECK that makes the two inseparable in both
-- directions — a non-zero adjustment must be explained, and a reason cannot
-- outlive the figure it explained.
--
-- It does NOT abolish the field, and it does not turn an adjustment into a
-- posted journal, which is the accounting answer. Most of what people plug here
-- is a timing item — a cheque issued and not presented, a deposit not yet
-- credited — and a timing item is not a journal, it belongs on the BOOK side of
-- a two-sided reconciliation statement that this product does not yet produce
-- (BANK-04). Posting those to the ledger would be worse than the plug. What is
-- left after BANK-04 lands is genuinely journal-shaped (bank charges, interest
-- credited), and that is when the field can go.
--
-- Ten characters is the same floor migration 253 puts on a reopen. Migration
-- 354 uses it too, for the same reason: "ok" in an audit trail is barely better
-- than no audit trail.

ALTER TABLE public.bank_reconciliations
    ADD COLUMN IF NOT EXISTS adjustments_reason  text,
    ADD COLUMN IF NOT EXISTS adjustments_set_by  uuid REFERENCES public.users(id),
    ADD COLUMN IF NOT EXISTS adjustments_set_at  timestamptz;

COMMENT ON COLUMN public.bank_reconciliations.adjustments_reason IS
    'What the adjustment IS. Required whenever adjustments_paise is non-zero, and '
    'necessarily NULL when it is zero. Printed on the reconciliation PDF beside the '
    'figure — an unexplained plug on a certified document is the defect this closes.';
COMMENT ON COLUMN public.bank_reconciliations.adjustments_set_by IS
    'public.users.id — the INTERNAL user id, not the Supabase auth id (CLAUDE.md). '
    'Setting a non-zero adjustment needs banking.approve (Manager+).';

DO $$
BEGIN
    -- The figure and its explanation are inseparable, in BOTH directions.
    -- Left to right: a plug nobody can read is the defect. Right to left: a
    -- reason left behind after the figure was zeroed would describe money that
    -- is no longer in the tie-out.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'bank_reconciliations_adjustment_is_explained') THEN
        ALTER TABLE public.bank_reconciliations
            ADD CONSTRAINT bank_reconciliations_adjustment_is_explained
            CHECK (
                (COALESCE(adjustments_paise, 0) = 0 AND adjustments_reason IS NULL)
                OR
                (COALESCE(adjustments_paise, 0) <> 0
                 AND adjustments_reason IS NOT NULL
                 AND length(btrim(adjustments_reason)) >= 10)
            );
    END IF;

    -- Who and when travel with the reason. An explanation with no author is
    -- half a record.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'bank_reconciliations_adjustment_is_attributed') THEN
        ALTER TABLE public.bank_reconciliations
            ADD CONSTRAINT bank_reconciliations_adjustment_is_attributed
            CHECK (adjustments_reason IS NULL OR adjustments_set_at IS NOT NULL);
    END IF;
END $$;
