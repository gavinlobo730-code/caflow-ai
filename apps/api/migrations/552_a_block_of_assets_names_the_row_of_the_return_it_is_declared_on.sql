-- Migration 552: a §32 block names the row of the return it is declared on (POST-A-070).
--
-- WHY A BLOCK NEEDS ONE MORE FACT
--
-- Depreciation under §32 is charged on a BLOCK, and a block is "assets of the same NATURE carrying the same RATE" (§2(11)). Migration
-- 357 stored the rate and a name the CA chose ("Plant & Machinery 15%") and nothing that says which nature the block is, because the
-- engine needs only the rate to compute the allowance. The RETURN needs the nature too: Schedule DPM and Schedule DOA are a fixed set of
-- rows, each one a nature at a rate (plant and machinery at 15, 30, 40 or 45 per cent; building at 5, 10 or 40; furniture and fittings;
-- intangible assets; ships; land), and a block cannot be placed on the return without being told which row it is. The name is free
-- text and a guess from it is a guess; the rate alone does not decide it (40 per cent is a row under plant and machinery AND one
-- under building).
--
-- WHAT IS STORED
--
-- `itr_schedule_row` holds the Department's own key for the row: `PlantMachinery.Rate15`, `Building.Rate10`, `FurnitureFittings.Rate10`,
-- `Land`. The vocabulary is read from the committed ITR schemas by `domain/income_tax/itr_depreciation_rows.py`, not typed in SQL: a
-- list of the form's rows here would be a second copy that a year's new form leaves behind, and the check on the column is therefore
-- the SHAPE of a key and not its membership. The API refuses a key that is not a row of the form and a row whose rate disagrees with the
-- block's, and the schedule assembly (`domain/income_tax/books_schedules.py`) puts a block with no row, or a bad one, aside by name.
--
-- NULLABLE, NO DEFAULT, NO BACKFILL
--
-- NULL means nobody has said which nature the block is. It is not defaulted from the name or the rate, because a block placed on the
-- wrong row prints a depreciation figure against a nature it does not belong to, on a return the CA signs; the assembly reports the
-- block as "no row recorded" and leaves it off the schedule, with its figures, and the tie-out names the difference.
--
-- Nothing else changes: the block's rate, opening written-down value and the allowance are exactly what they were, no policy
-- is touched, and no existing reader selects this column (the §32 service reads the row whole and takes the key with `.get`).

ALTER TABLE public.income_tax_asset_blocks
    ADD COLUMN IF NOT EXISTS itr_schedule_row text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.income_tax_asset_blocks'::regclass
           AND conname = 'income_tax_asset_blocks_itr_schedule_row_shape'
    ) THEN
        ALTER TABLE public.income_tax_asset_blocks
            ADD CONSTRAINT income_tax_asset_blocks_itr_schedule_row_shape
            CHECK (itr_schedule_row IS NULL OR itr_schedule_row ~ '^[A-Za-z]+(\.Rate[0-9]{1,3})?$');
    END IF;
END $$;

COMMENT ON COLUMN public.income_tax_asset_blocks.itr_schedule_row IS
    'The row of Schedule DPM or DOA this block is declared on: the Department''s own key (PlantMachinery.Rate15, Building.Rate10, '
    'Land), read from the committed ITR schemas by domain/income_tax/itr_depreciation_rows.py. A CA determination of the block''s '
    'NATURE (§2(11)); NULL = nobody has said, and the schedule assembly leaves the block off the return and names it.';
