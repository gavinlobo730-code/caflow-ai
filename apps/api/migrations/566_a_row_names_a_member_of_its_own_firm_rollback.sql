-- Rollback of migration 566: take the member-in-firm triggers and their functions away.
-- Nothing else changes: no data was written by 566, and no column, policy or grant was touched.

BEGIN;

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT g.tgrelid::regclass AS t, g.tgname AS name
          FROM pg_trigger g
         WHERE NOT g.tgisinternal
           AND g.tgname IN ('row_member_in_firm_ins', 'row_member_in_firm_upd')
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %s', r.name, r.t);
    END LOOP;
END $$;

DROP FUNCTION IF EXISTS public.guard_member_firm(regclass);
DROP FUNCTION IF EXISTS public.member_columns_of(regclass);
DROP FUNCTION IF EXISTS public.assert_inserted_rows_name_a_member_of_their_firm();
DROP FUNCTION IF EXISTS public.assert_updated_row_names_a_member_of_its_firm();

COMMIT;
