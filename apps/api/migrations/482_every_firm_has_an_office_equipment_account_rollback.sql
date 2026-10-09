-- Rollback for 482.
--
-- Removes the firm-level `Office Equipment` (Asset / Fixed Asset) ledgers at
-- code 1508 or later that nothing refers to, and leaves every other one alone.
--
-- "Nothing refers to" is asked of EVERY foreign key that points at
-- chart_of_accounts, found in pg_constraint rather than listed here, and not
-- only of journal_lines: a journal line is the one that matters (migration 251
-- makes a posted entry immutable, so a ledger carrying a line cannot go), but
-- several other tables reference the chart with ON DELETE CASCADE (the period
-- balance buckets, budgets, recurring journal lines) or ON DELETE SET NULL
-- (bank drafts, recurring bill and purchase order lines), and a blind DELETE
-- would silently remove or blank those rows. A ledger anything points at stays.
--
-- It cannot tell a row this migration inserted from one STANDARD_COA seeded for
-- a firm onboarded after the change (both are active, code 1508+, named
-- exactly 'Office Equipment', no system key), and does not try: rolling back is
-- reverting the standard chart's row as well, and an unreferenced ledger of
-- that name is the same account either way. Never a candidate: the migration-011
-- chart's own ledger (code 1501), a client-level account, and one a CA has
-- deactivated (neither 482 nor STANDARD_COA inserts an inactive account, so an
-- inactive one is the CA's own).
--
-- After this, `POST /api/fixed-assets` with category "Office Equipment" answers
-- 500 again on every firm whose ledger was removed.

BEGIN;

DO $$
DECLARE
  acct       RECORD;
  fk         RECORD;
  referenced BOOLEAN;
BEGIN
  FOR acct IN
    SELECT c.id
    FROM public.chart_of_accounts c
    WHERE c.client_id IS NULL
      AND c.account_name = 'Office Equipment'
      AND c.account_type = 'Asset'
      AND c.account_subtype = 'Fixed Asset'
      AND c.system_account_key IS NULL
      AND c.is_active IS TRUE
      -- a CASE, not `code ~ digits AND code::bigint`: AND does not promise to
      -- stop at the first false, and a code such as 'FA12' must not raise.
      AND (CASE WHEN c.account_code ~ '^[0-9]{1,9}$'
                THEN c.account_code::bigint END) >= 1508
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

COMMIT;
