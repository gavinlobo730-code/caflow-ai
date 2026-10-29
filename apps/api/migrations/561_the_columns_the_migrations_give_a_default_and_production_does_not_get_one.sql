-- Migration 561: eleven column defaults the migrations and production disagree about (ledger POST-A-168).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- The schema-drift check compares the presence, the type and the nullability of every column and never the DEFAULT. Run over the
-- production snapshot it finds 39 differing defaults. Twenty-six are harmless: production has a default the migrations lack (twenty-one,
-- all but one on a column the migrations leave optional, the last an empty-string default on a NOT NULL column that a caller written
-- from the migrations always names), or the two spell the same default differently (five: a cast to the enum or to text,
-- `gen_random_uuid()` against `uuid_generate_v4()`). Two more are not rejections but are named in the ledger (POST-A-356): the
-- migrations default `client_timeline_events.actor_type` to 'system' and `form_26as_uploads.status` to 'uploaded', and production
-- leaves both NULL when a caller omits them; defaulting them in production would change what existing inserts store, which is a
-- decision and not a convergence. Eleven are the ones this migration settles:
--
--   NINE are the dangerous direction. The migrations give the column a default and production, where it is NOT NULL, has none, so
--   code written from the migrations (and the test suite, which is built from them) omits the column and the insert is REJECTED in
--   production with a not-null violation while every check here passes. It is the mirror of the failure the nullability check
--   exists for (form_26as_uploads.uploaded_by):
--       brought_forward_losses.original_amount_paise, .remaining_amount_paise          default 0
--       eway_bill_records.dispatch_from, .goods_description, .ship_to                   default ''
--       eway_bill_records.taxable_value_paise                                           default 0
--       itr_filing_versions.json_payload                                                default '{}'
--       tax_deduction_claims.claimed_amount_paise, tax_disallowances.amount_paise       default 0
--   TWO have a different default VALUE: `tally_migration_jobs.is_dry_run` is false in the migrations and true in production, and
--   `form_26as_reconciliations.status` is 'draft' in the migrations and 'pending' in production. The code names both on every insert
--   today, so nothing misbehaves yet, but a job created without naming is_dry_run would write to the books in a test database and
--   preview in production.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- Gives the nine columns the default the migrations always declared (a default on a NOT NULL column only loosens: no existing row and
-- no existing insert changes) and makes the two differing defaults the production values, which are the safe ones (a Tally job is a
-- dry run unless somebody says otherwise). On production the last two statements are no-ops. `tests/test_schema_matches_production_pg.py`
-- asserts both directions from now on, so a default added in a migration and never applied to production fails there.
--
-- Idempotent. The rollback removes the nine defaults and leaves the two others alone: reverting them would make a migration-built
-- database disagree with production again, and on production they are what was there before.

ALTER TABLE public.brought_forward_losses
    ALTER COLUMN original_amount_paise SET DEFAULT 0,
    ALTER COLUMN remaining_amount_paise SET DEFAULT 0;

ALTER TABLE public.eway_bill_records
    ALTER COLUMN dispatch_from SET DEFAULT '',
    ALTER COLUMN goods_description SET DEFAULT '',
    ALTER COLUMN ship_to SET DEFAULT '',
    ALTER COLUMN taxable_value_paise SET DEFAULT 0;

ALTER TABLE public.itr_filing_versions
    ALTER COLUMN json_payload SET DEFAULT '{}'::jsonb;

ALTER TABLE public.tax_deduction_claims
    ALTER COLUMN claimed_amount_paise SET DEFAULT 0;

ALTER TABLE public.tax_disallowances
    ALTER COLUMN amount_paise SET DEFAULT 0;

ALTER TABLE public.tally_migration_jobs
    ALTER COLUMN is_dry_run SET DEFAULT true;

ALTER TABLE public.form_26as_reconciliations
    ALTER COLUMN status SET DEFAULT 'pending';

DO $$
DECLARE
    want text[][] := ARRAY[
        ['brought_forward_losses', 'original_amount_paise'], ['brought_forward_losses', 'remaining_amount_paise'],
        ['eway_bill_records', 'dispatch_from'], ['eway_bill_records', 'goods_description'], ['eway_bill_records', 'ship_to'],
        ['eway_bill_records', 'taxable_value_paise'], ['itr_filing_versions', 'json_payload'],
        ['tax_deduction_claims', 'claimed_amount_paise'], ['tax_disallowances', 'amount_paise'],
        ['tally_migration_jobs', 'is_dry_run'], ['form_26as_reconciliations', 'status']
    ];
    i int;
BEGIN
    FOR i IN 1 .. array_length(want, 1) LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = want[i][1] AND column_name = want[i][2]
               AND column_default IS NOT NULL) THEN
            RAISE EXCEPTION 'migration 561: %.% has no default', want[i][1], want[i][2];
        END IF;
    END LOOP;
END $$;
