-- Rollback for 409. Drops the three columns and their four constraints.
-- Nothing else reads them and no figure was derived from them, so this is a
-- clean reversal — but it DISCARDS any alternate unit, factor or reorder level
-- a CA has recorded, which is data nothing else holds.

ALTER TABLE public.service_catalogue
    DROP CONSTRAINT IF EXISTS service_catalogue_units_per_alternate_positive,
    DROP CONSTRAINT IF EXISTS service_catalogue_alternate_unit_pairs,
    DROP CONSTRAINT IF EXISTS service_catalogue_alternate_unit_differs,
    DROP CONSTRAINT IF EXISTS service_catalogue_reorder_level_nonneg;

ALTER TABLE public.service_catalogue
    DROP COLUMN IF EXISTS alternate_unit,
    DROP COLUMN IF EXISTS units_per_alternate,
    DROP COLUMN IF EXISTS reorder_level_units;
