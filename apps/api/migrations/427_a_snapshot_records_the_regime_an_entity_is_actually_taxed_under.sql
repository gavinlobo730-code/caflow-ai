-- 427: a computation snapshot records the regime an entity is actually taxed
--      under, not only the two answers to s.115BAC.
--
-- WHY
--   tax_computation_snapshots_regime_check is CHECK (regime IN ('new','old'))
--   -- declared by migration 319 from what production enforced, and the column
--   is NOT NULL since 292. 'new' and 'old' are the two answers to IT Act
--   s.115BAC, which is an INDIVIDUAL / HUF election. Nobody else has it:
--
--     * a domestic company is taxed at the normal rate, or under s.115BAA or
--       s.115BAB -- domain/income_tax/itr_engine.py sets result.regime to
--       req.company_regime for exactly that reason;
--     * a firm or an LLP has no regime choice at all, and the engine returns
--       an empty regime, which the computation screen fills with the assessee
--       kind ('firm' / 'llp') so the label is at least true.
--
--   So EVERY company, firm and LLP snapshot violated the CHECK. The router
--   turned the 23514 into a 500 carrying the constraint name, the screen
--   awaited the POST and never read it, and the CA saw their computation
--   reading as saved while GET /api/itr/snapshots stayed empty -- which also
--   left the ITR filing with no snapshot to pin (IT-30's review gate reads
--   exactly that pin).
--
-- WHAT THIS DOES
--   Widens the CHECK to the seven values the computation screen's own
--   regimeLabel() already renders: new, old, normal, 115BAA, 115BAB, firm,
--   llp. routers/itr_workspace.SnapshotRequest.regime is a Literal of the
--   same seven, pinned to this file by
--   tests/test_a_snapshot_records_the_regime_an_entity_is_taxed_under.py, so
--   a bad value is a 422 naming the field before it ever reaches here.
--
--   DELIBERATELY NOT the alternative of recording a company as 'old'. That
--   stamps a s.115BAC election on an assessee who cannot make one, and the
--   snapshot is the record a reviewer signs off (IT-30). A label with no
--   statute behind it is the defect the screen's regimeLabel() was written to
--   stop showing.
--
--   Widening cannot fail against stored data: every existing row satisfies
--   the narrower CHECK, which is a subset of this one. NOT VALID + VALIDATE is
--   used anyway, matching migrations 315 and 424, because this runs unattended
--   on merge and a pattern that is correct whether or not the table holds data
--   is worth more than one that only happens to be correct today.
--
--   The production guard fixture (tests/fixtures/production_guards_*.json)
--   still records the two-value CHECK. test_guards_match_production_pg excuses
--   it while this migration is in flight, because it ADDs the constraint by
--   name; the next fixture refresh absorbs it.

BEGIN;

ALTER TABLE public.tax_computation_snapshots
    DROP CONSTRAINT IF EXISTS tax_computation_snapshots_regime_check;

ALTER TABLE public.tax_computation_snapshots
    ADD CONSTRAINT tax_computation_snapshots_regime_check
    CHECK (regime IN ('new', 'old', 'normal', '115BAA', '115BAB', 'firm', 'llp'))
    NOT VALID;

ALTER TABLE public.tax_computation_snapshots
    VALIDATE CONSTRAINT tax_computation_snapshots_regime_check;

COMMENT ON COLUMN public.tax_computation_snapshots.regime IS
    'How the assessee is taxed for this computation: new | old (IT Act s.115BAC, '
    'individual/HUF only); normal | 115BAA | 115BAB (a domestic company); '
    'firm | llp (no regime choice). Migration 427 widened the CHECK from new/old.';

COMMIT;
