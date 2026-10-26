-- Rollback of migration 552: the column and its check are dropped, and every recorded row is lost with them (the blocks, their rates and
-- their opening values are untouched). Roll back the code that writes `itr_schedule_row` FIRST: a write that names a column that is gone
-- is refused. The schedule assembly then lists every block as "no row recorded".

ALTER TABLE public.income_tax_asset_blocks
    DROP CONSTRAINT IF EXISTS income_tax_asset_blocks_itr_schedule_row_shape;
ALTER TABLE public.income_tax_asset_blocks
    DROP COLUMN IF EXISTS itr_schedule_row;
