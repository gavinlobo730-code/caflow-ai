-- Migration 587: a month of depreciation that is being reversed cannot be posted over (ledger POST-A-349).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- `reverse_depreciation` writes the register first (a compare-and-set that rolls the asset back a month) and reverses the month's
-- journal second. A second request that posts the SAME month of the SAME asset in that window read a register that no longer had the
-- month, found the journal still live, was handed it by the posting kernel's duplicate check without a new entry, wrote the register up
-- again, and was then reversed by the first request: the register said the month was posted and the ledger said it was reversed. A
-- request posting the NEXT month in the same window could likewise write the register over the reversal's roll-back. A half-done
-- reversal and a half-done post leave the same state (register behind, journal live), and the retry that adopts a live journal is
-- deliberate for the second, so the post could not tell them apart on the state alone.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
--  * `fixed_assets.depreciation_reversal_month` ('YYYY-MM') and `fixed_assets.depreciation_reversal_claimed_at`: written by the
--    reversal in the SAME compare-and-set as its claim, cleared when the month's journal is reversed or the claim is put back. Both or
--    neither (a CHECK), and the month is a month (a CHECK). NULL is the ordinary state; nothing is backfilled, because the code before
--    this migration never writes a marker (it writes one only when the row it read carries the column).
--  * The API reads them: a post of the asset refuses while a FRESH marker is on it (a lease: a marker older than the lease is a
--    reversal that died, and the post adopts as it always has), and the post's own register write is a compare-and-set on the marker
--    still being what it read, so a reversal that claims the row after the post read it makes the post take its journal back and say so.
--  * Not caught: a post that read the row before a reversal claimed it and writes only after that reversal has wholly finished (the
--    marker is back to NULL by then, so the row reads as it did). That needs a version on every register write; ledger POST-A-434.
--
-- No function, policy or grant changes: the columns follow `fixed_assets`' own table grants and policies.

BEGIN;

ALTER TABLE public.fixed_assets
    ADD COLUMN IF NOT EXISTS depreciation_reversal_month text,
    ADD COLUMN IF NOT EXISTS depreciation_reversal_claimed_at timestamptz;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fixed_assets_reversal_marker_is_whole') THEN
        ALTER TABLE public.fixed_assets ADD CONSTRAINT fixed_assets_reversal_marker_is_whole
            CHECK ((depreciation_reversal_month IS NULL) = (depreciation_reversal_claimed_at IS NULL));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fixed_assets_reversal_marker_is_a_month') THEN
        ALTER TABLE public.fixed_assets ADD CONSTRAINT fixed_assets_reversal_marker_is_a_month
            CHECK (depreciation_reversal_month IS NULL OR depreciation_reversal_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

COMMENT ON COLUMN public.fixed_assets.depreciation_reversal_month IS
  'The month a depreciation reversal has claimed and not yet finished (POST-A-349, migration 587). NULL = no reversal in flight.';
COMMENT ON COLUMN public.fixed_assets.depreciation_reversal_claimed_at IS
  'When that reversal claimed the row: a post refuses the asset while the claim is younger than the lease (POST-A-349).';

COMMIT;
