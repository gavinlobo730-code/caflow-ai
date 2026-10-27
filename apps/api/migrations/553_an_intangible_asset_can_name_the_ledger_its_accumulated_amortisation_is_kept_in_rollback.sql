-- Rollback of migration 553.
--
-- IT REFUSES, RATHER THAN LOSING WHAT THE LATER STAGES RECORD. Once an asset points at the new ledger (stage 3), dropping the column
-- would silently send its next month's depreciation and its disposal back to the shared Accumulated Depreciation ledger while its
-- history sits in the new one: the books would stay balanced and each ledger would be wrong by the asset's whole accumulated figure,
-- which is the defect this change exists to remove. So this raises, and changes nothing, while ANY asset points at a ledger or any
-- journal line is posted to an Accumulated Amortisation ledger at a code this migration could have seeded (1591 to 1599). Undo the reclassification on the
-- fixed-assets screen first (stage 3), then roll back; or roll the code FORWARD, not back: older code ignores the column.
--
-- When nothing refers to it, it removes the firm-level 'Accumulated Amortisation' ledgers (Asset, code 1591 to 1599, no system key,
-- active, nothing pointing at them) and drops the index and the column. "Nothing refers to" is asked of EVERY foreign key that
-- points at chart_of_accounts, found in pg_constraint rather than listed here (migration 482's rollback explains why): a ledger
-- anything points at stays. It cannot tell a ledger this migration seeded from one STANDARD_COA seeded for a firm onboarded after
-- the change (both are active, named exactly 'Accumulated Amortisation', code 1591 to 1599, no system key), and does not try: an
-- unreferenced ledger of that name is the same account either way, and rolling back is reverting the standard chart's row as well.
-- Never a candidate: an inactive account, a client-level account, or one a CA created under another name or at another code.

DO $$
DECLARE
  acct       RECORD;
  fk         RECORD;
  referenced BOOLEAN;
  pointed    BIGINT := 0;
  posted     BIGINT := 0;
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'fixed_assets' AND column_name = 'accumulated_account_id') THEN
    EXECUTE 'SELECT count(*) FROM public.fixed_assets WHERE accumulated_account_id IS NOT NULL' INTO pointed;
  END IF;

  SELECT count(*) INTO posted
  FROM public.journal_lines jl
  JOIN public.chart_of_accounts c ON c.id = jl.account_id
  WHERE c.client_id IS NULL
    AND c.account_type = 'Asset'
    AND c.account_name = 'Accumulated Amortisation'
    AND c.system_account_key IS NULL
    AND (CASE WHEN c.account_code ~ '^[0-9]{1,9}$' THEN c.account_code::bigint END) BETWEEN 1591 AND 1599;

  IF pointed > 0 OR posted > 0 THEN
    RAISE EXCEPTION 'migration 553 rollback REFUSED: % asset(s) point at a ledger and % journal line(s) are posted to an Accumulated Amortisation ledger. Undo the reclassification first, or roll the code forward instead of back.', pointed, posted;
  END IF;

  FOR acct IN
    SELECT c.id
    FROM public.chart_of_accounts c
    WHERE c.client_id IS NULL
      AND c.account_name = 'Accumulated Amortisation'
      AND c.account_type = 'Asset'
      AND c.system_account_key IS NULL
      AND c.is_active IS TRUE
      -- a CASE, not `code ~ digits AND code::bigint`: AND does not promise to stop at the first false, and a code such as 'FA12'
      -- must not raise.
      AND (CASE WHEN c.account_code ~ '^[0-9]{1,9}$' THEN c.account_code::bigint END) BETWEEN 1591 AND 1599
  LOOP
    referenced := FALSE;
    FOR fk IN
      SELECT con.conrelid::regclass::text AS tbl, att.attname AS col
      FROM pg_constraint con
      JOIN pg_attribute att
        ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey)
      WHERE con.contype = 'f'
        AND con.confrelid = 'public.chart_of_accounts'::regclass
    LOOP
      EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s WHERE %I = $1)', fk.tbl, fk.col)
        INTO referenced USING acct.id;
      EXIT WHEN referenced;
    END LOOP;

    IF NOT referenced THEN
      DELETE FROM public.chart_of_accounts WHERE id = acct.id;
    END IF;
  END LOOP;
END $$;

DROP INDEX IF EXISTS public.fixed_assets_accumulated_account_idx;

ALTER TABLE public.fixed_assets
    DROP COLUMN IF EXISTS accumulated_account_id;

NOTIFY pgrst, 'reload schema';
