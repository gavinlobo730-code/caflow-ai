-- Migration 635: a fixed asset's register carries a version, so a depreciation post that read the row before a whole reversal cannot
-- write over it (ledger POST-A-434).
--
-- WHAT WAS WRONG
-- Migration 587's reversal marker closes the interleavings where a post lands while a reversal is in flight, but the marker is back to
-- NULL once the reversal finishes. A post of the NEXT month that read the row before the reversal claimed it, and writes only after the
-- reversal has claimed, reversed the journal and cleared, finds the row as it read it and wrote the month on top: the register counted
-- the reversed month and the ledger did not. A compare-and-set on the figure or posted-through does not close it, because a reversal
-- followed by a post of the same month returns the row to exactly what was read.
--
-- WHAT THIS DOES
--  * `fixed_assets.register_version` (bigint, default 0) and a BEFORE UPDATE trigger that adds one whenever a column the register is
--    made of changes: the accumulated depreciation, posted-through, the reversal marker, the disposal, the accumulated-depreciation
--    ledger pointer or the soft delete. So every register write (post, reversal claim, restore, clear, correction, disposal,
--    reclassification) increments it, and an edit of a name or a note does not (it would make a post take its journal back for nothing).
--    The trigger sets the figure itself, so no writer can forget to or set it.
--  * The API reads it with the row and makes the post's register write a compare-and-set on it; a miss re-reads and keeps the month
--    when the register now holds it, and takes the journal back otherwise. The API reads the column only where the row carries it, so
--    it runs ahead of this migration.
-- No policy or grant changes: the column follows `fixed_assets`' own grants and policies. Nothing is backfilled (0 for every row).

BEGIN;

ALTER TABLE public.fixed_assets
    ADD COLUMN IF NOT EXISTS register_version bigint NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.fixed_assets.register_version IS
  'Added to by a trigger on every change to the depreciation register columns, so a write can be made conditional on the version it read (POST-A-434, migration 635).';

CREATE OR REPLACE FUNCTION public.fixed_assets_bump_register_version() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF (NEW.accumulated_depreciation_paise, NEW.depreciation_posted_through, NEW.depreciation_reversal_month,
        NEW.is_disposed, NEW.accumulated_account_id, NEW.deleted_at)
       IS DISTINCT FROM
       (OLD.accumulated_depreciation_paise, OLD.depreciation_posted_through, OLD.depreciation_reversal_month,
        OLD.is_disposed, OLD.accumulated_account_id, OLD.deleted_at) THEN
        NEW.register_version := COALESCE(OLD.register_version, 0) + 1;
    ELSE
        NEW.register_version := OLD.register_version;
    END IF;
    RETURN NEW;
END
$fn$;

DROP TRIGGER IF EXISTS trg_fixed_assets_bump_register_version ON public.fixed_assets;
CREATE TRIGGER trg_fixed_assets_bump_register_version
    BEFORE UPDATE ON public.fixed_assets
    FOR EACH ROW EXECUTE FUNCTION public.fixed_assets_bump_register_version();

COMMIT;
