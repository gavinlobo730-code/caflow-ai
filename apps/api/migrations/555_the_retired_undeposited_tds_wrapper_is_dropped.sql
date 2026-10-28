-- Migration 555 — drop public.tds_undeposited_paise (ledger POST-A-275)
--
-- WHY IT WAS KEPT
--   Migration 523 moved the "TDS deducted and not yet deposited" rule into public.tds_deposit_position (the undeposited shortfall in
--   quarters with a challan recorded, and, apart, the tax in quarters with none) and kept public.tds_undeposited_paise as a one-line
--   wrapper over its first figure, because production applies a migration after the tests pass while Render deploys the API on the
--   same push, so either could be live first: the new API against the old schema shows the tile with no figure until the migration
--   applies, and the previous API after it keeps a right answer from the wrapper.
--
-- WHY IT CAN GO
--   The API that calls tds_deposit_position has been live since migration 523 was applied (many deploys ago), and nothing in the
--   repository calls the old name: the hub reads the pair through services/hub_service, the in-memory double's handler for the old
--   name and the tests that held the wrapper equal to the pair's first figure are deleted in this same change.
--
-- WHAT THIS DOES
--   Drops the wrapper. tds_deposit_position, its grants and its comment are untouched, and so is every row. The closing check fails
--   the migration if the new function is missing or the wrapper is still there.
--
-- Reversible: 555_..._rollback.sql recreates the wrapper exactly as 523 defined it, with 523's grants.

DROP FUNCTION IF EXISTS public.tds_undeposited_paise(uuid, uuid[]);

DO $$
BEGIN
    IF to_regprocedure('public.tds_deposit_position(uuid, uuid[])') IS NULL THEN
        RAISE EXCEPTION 'migration 555: public.tds_deposit_position is missing, so nothing answers the hub''s TDS tile';
    END IF;
    IF to_regprocedure('public.tds_undeposited_paise(uuid, uuid[])') IS NOT NULL THEN
        RAISE EXCEPTION 'migration 555: public.tds_undeposited_paise is still there';
    END IF;
END $$;
