-- Migration 567: a brought-forward loss records what each filed return used of it (POST-A-073, IT-10's other half).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- `brought_forward_losses` carries one running total, `utilized_amount_paise`, with `remaining_amount_paise` beside it (kept equal to
-- original less utilized by `chk_remaining_consistency`). Nothing wrote either when a return was filed, so next year's computation
-- reloaded the whole loss unless the CA edited it by hand. Writing the total back is not enough, and the way it goes wrong is quiet:
-- the computation screen offers `remaining_amount_paise`, so once a year's return has used a loss, recomputing THAT SAME YEAR (a revised
-- return under section 139(5), or a CA reopening the computation) would offer the loss net of its own earlier use and understate the
-- relief. A wrong number where today there is none.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- Adds `utilisations`, a JSON object keyed by the filing that used the loss:
--
--     { "<itr_filings.id>": { "financial_year": "2025-26", "amount_paise": 4000000, "return_type": "original" } }
--
-- `utilized_amount_paise` stays the single total and `remaining_amount_paise` stays original less utilized; they become a cache of the
-- entries plus whatever was recorded by hand through `utilize_bf_loss` (the baseline, which is never stored: it is utilized less the sum
-- of the entries). `domain/income_tax/loss_utilisation.py` is the one rule that writes all three together, and a computation for a year
-- may use the loss less the uses of OTHER years, which is remaining plus that year's own entries.
--
-- The default is an empty object and the column is NOT NULL, so every existing row reads as "no filing has used it", which is exactly
-- what it was. Two CHECKs hold the column: that it is an object, and that the entries together never exceed `utilized_amount_paise` (the
-- difference is the hand-recorded baseline, and it cannot be negative). The second goes through an IMMUTABLE function that sums the
-- entries, so a direct write to the table (the signed-in role keeps UPDATE on it) cannot leave the entries larger than the total. What no
-- CHECK can hold, that the baseline is exactly what was recorded by hand, stays in the rule and its tests. No policy or grant changes: the
-- column rides the table's existing ones.
--
ALTER TABLE public.brought_forward_losses
    ADD COLUMN IF NOT EXISTS utilisations JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.brought_forward_losses'::regclass
           AND conname = 'brought_forward_losses_utilisations_is_an_object'
    ) THEN
        ALTER TABLE public.brought_forward_losses
            ADD CONSTRAINT brought_forward_losses_utilisations_is_an_object
            CHECK (jsonb_typeof(utilisations) = 'object');
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.brought_forward_loss_entries_total(entries JSONB)
RETURNS BIGINT
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT CASE WHEN jsonb_typeof(entries) = 'object'
                THEN COALESCE((SELECT SUM((e.value ->> 'amount_paise')::bigint) FROM jsonb_each(entries) e), 0)
                ELSE 0 END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.brought_forward_losses'::regclass
           AND conname = 'brought_forward_losses_entries_within_utilized'
    ) THEN
        ALTER TABLE public.brought_forward_losses
            ADD CONSTRAINT brought_forward_losses_entries_within_utilized
            CHECK (utilized_amount_paise >= public.brought_forward_loss_entries_total(utilisations));
    END IF;
END $$;

COMMENT ON COLUMN public.brought_forward_losses.utilisations IS
    'What each filed return used of this loss: {"<itr_filings.id>": {"financial_year": "2025-26", "amount_paise": N, "return_type": "original|revised"}}. '
    'utilized_amount_paise = hand-recorded baseline + the sum of these; remaining = original - utilized. Written together by '
    'domain/income_tax/loss_utilisation.py when a return''s acknowledgement is recorded; a revised return replaces the original''s entry for the same year.';
