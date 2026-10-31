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
--     { "<itr_filings.id>": { "financial_year": "2025-26", "amount_paise": 4000000 } }
--
-- `utilized_amount_paise` stays the single total and `remaining_amount_paise` stays original less utilized; they become a cache of the
-- entries plus whatever was recorded by hand through `utilize_bf_loss` (the baseline, which is never stored: it is utilized less the sum
-- of the entries). `domain/income_tax/loss_utilisation.py` is the one rule that writes all three together, and a computation for a year
-- may use the loss less the uses of OTHER years, which is remaining plus that year's own entries.
--
-- The default is an empty object and the column is NOT NULL, so every existing row reads as "no filing has used it", which is exactly
-- what it was. The CHECK keeps the column an object; the arithmetic between the entries and the totals is not expressible as a CHECK
-- (it would need a subquery over the object) and is held by the rule and its tests. No policy or grant changes: the column rides the
-- table's existing ones.
--
-- Idempotent. Nothing is read or rewritten; the rollback drops the column and with it the per-filing record, leaving the two totals as
-- the filings left them.

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

COMMENT ON COLUMN public.brought_forward_losses.utilisations IS
    'What each filed return used of this loss: {"<itr_filings.id>": {"financial_year": "2025-26", "amount_paise": N}}. '
    'utilized_amount_paise = hand-recorded baseline + the sum of these; remaining = original - utilized. Written together by '
    'domain/income_tax/loss_utilisation.py when a return''s acknowledgement is recorded; a revised return replaces the original''s entry for the same year.';
