-- Rollback of migration 570: take the ledger-account checks away. The functions go with the triggers; nothing else read them.
BEGIN;

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT g.tgrelid::regclass AS t, g.tgname AS name
          FROM pg_trigger g
         WHERE NOT g.tgisinternal AND g.tgname LIKE 'row\_ledger\_account\_%'
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %s', r.name, r.t);
    END LOOP;
END $$;

DROP FUNCTION IF EXISTS public.guard_ledger_account(regclass, text, regclass, text, boolean);
DROP FUNCTION IF EXISTS public.assert_inserted_rows_name_a_ledger_account_of_their_client();
DROP FUNCTION IF EXISTS public.assert_updated_row_names_a_ledger_account_of_its_client();

COMMIT;
