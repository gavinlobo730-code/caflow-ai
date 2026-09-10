-- Migration 354: a statement imported over its own totals is marked as such.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS IS FOR
-- ═══════════════════════════════════════════════════════════════════════════
-- Most Indian bank statements print their own totals, and the import sums the
-- parse against them before writing anything (domain/banking/tie_out.py). Until
-- now a disagreement was the end of it: the import was refused and there was no
-- way past. BANK-01 is that wall — and the case it blocks is real, because the
-- bank's own row is not always comparable with the lines beneath it. It can
-- carry a brought-forward figure, or the export can be a filtered view of a
-- period the total covers whole.
--
-- So a CA who has compared the two figures themselves may now import over the
-- mismatch by writing down why. These columns are where that goes.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY IT IS FIVE COLUMNS AND NOT A BOOLEAN
-- ═══════════════════════════════════════════════════════════════════════════
-- BANK-05, in this same subsystem, is the cautionary case: `adjustments_paise`
-- is a plug that any Executive can type, with no reason, no audit row and no
-- narration, and it satisfies the gate that produces a signed reconciliation
-- PDF. Nobody reading that document afterwards can tell what the number was.
--
-- An override that records only THAT it happened is the same defect. What makes
-- this one readable a year later is that the reason sits beside the two figures
-- it excused: the difference between what the lines summed to and what the bank
-- printed, in paise, frozen at the moment of the import. A reason with no figure
-- is an assertion; a figure with no reason is a plug.
--
-- The CHECKs enforce exactly that pairing, and the ten-character minimum
-- mirrors the reconciliation reopen path (migration 253), which is the
-- established shape in this codebase for "a reason, not a keystroke".
--
-- NOT NULLABLE-BY-DEFAULT ANYWHERE ELSE: an ordinary import leaves all five
-- NULL, which is what "nothing was overridden" looks like. There is no default
-- that could be mistaken for a real acknowledgement.

ALTER TABLE public.bank_statements
    ADD COLUMN IF NOT EXISTS totals_mismatch_reason                    text,
    ADD COLUMN IF NOT EXISTS totals_mismatch_debit_difference_paise    bigint,
    ADD COLUMN IF NOT EXISTS totals_mismatch_credit_difference_paise   bigint,
    ADD COLUMN IF NOT EXISTS totals_mismatch_acknowledged_by           uuid REFERENCES public.users(id),
    ADD COLUMN IF NOT EXISTS totals_mismatch_acknowledged_at           timestamptz;

COMMENT ON COLUMN public.bank_statements.totals_mismatch_reason IS
    'Why this statement was imported although its own printed totals row did not '
    'agree with the lines read from it. NULL on an ordinary import.';
COMMENT ON COLUMN public.bank_statements.totals_mismatch_debit_difference_paise IS
    'parsed withdrawals minus the withdrawals the statement printed, in paise, at '
    'the moment of import. The figure the reason beside it excused.';
COMMENT ON COLUMN public.bank_statements.totals_mismatch_credit_difference_paise IS
    'parsed deposits minus the deposits the statement printed, in paise.';
COMMENT ON COLUMN public.bank_statements.totals_mismatch_acknowledged_by IS
    'public.users.id — the INTERNAL user id, not the Supabase auth id (CLAUDE.md).';

DO $$
BEGIN
    -- A reason must be substantive. Ten characters is the same floor migration
    -- 253 puts on reopening a completed reconciliation, and for the same reason:
    -- "ok" in an audit trail is barely better than no audit trail.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'bank_statements_totals_mismatch_reason_substantive') THEN
        ALTER TABLE public.bank_statements
            ADD CONSTRAINT bank_statements_totals_mismatch_reason_substantive
            CHECK (totals_mismatch_reason IS NULL
                   OR length(btrim(totals_mismatch_reason)) >= 10);
    END IF;

    -- The reason and the figures it excused travel together, in both
    -- directions. A reason with no differences cannot be judged; differences
    -- with no reason are a plug.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'bank_statements_totals_mismatch_is_complete') THEN
        ALTER TABLE public.bank_statements
            ADD CONSTRAINT bank_statements_totals_mismatch_is_complete
            CHECK (
                (totals_mismatch_reason IS NULL
                 AND totals_mismatch_debit_difference_paise IS NULL
                 AND totals_mismatch_credit_difference_paise IS NULL
                 AND totals_mismatch_acknowledged_at IS NULL)
                OR
                (totals_mismatch_reason IS NOT NULL
                 AND totals_mismatch_debit_difference_paise IS NOT NULL
                 AND totals_mismatch_credit_difference_paise IS NOT NULL
                 AND totals_mismatch_acknowledged_at IS NOT NULL)
            );
    END IF;

    -- And it has to be a disagreement. An acknowledgement recorded against two
    -- zeroes would be a reason attached to nothing, which is how a box becomes
    -- something people tick out of habit.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'bank_statements_totals_mismatch_is_a_mismatch') THEN
        ALTER TABLE public.bank_statements
            ADD CONSTRAINT bank_statements_totals_mismatch_is_a_mismatch
            CHECK (totals_mismatch_reason IS NULL
                   OR totals_mismatch_debit_difference_paise <> 0
                   OR totals_mismatch_credit_difference_paise <> 0);
    END IF;
END $$;
