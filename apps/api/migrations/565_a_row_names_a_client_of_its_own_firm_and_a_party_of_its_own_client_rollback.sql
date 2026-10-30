-- Rollback of migration 565: take the client-in-firm, customer-in-client and vendor-in-client triggers and their functions away.
-- Nothing else changes: no data was written by 565, and no column, policy or grant was touched.

BEGIN;

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT g.tgrelid::regclass AS t, g.tgname AS name
          FROM pg_trigger g
         WHERE NOT g.tgisinternal
           AND g.tgname IN ('row_client_in_firm_ins', 'row_client_in_firm_upd',
                            'row_customer_in_client_ins', 'row_customer_in_client_upd',
                            'row_vendor_in_client_ins', 'row_vendor_in_client_upd')
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %s', r.name, r.t);
    END LOOP;
END $$;

DROP FUNCTION IF EXISTS public.guard_client_firm(regclass);
DROP FUNCTION IF EXISTS public.assert_inserted_rows_name_a_client_of_their_firm();
DROP FUNCTION IF EXISTS public.assert_updated_row_names_a_client_of_its_firm();
DROP FUNCTION IF EXISTS public.assert_inserted_rows_name_a_customer_of_their_client();
DROP FUNCTION IF EXISTS public.assert_updated_row_names_a_customer_of_its_client();
DROP FUNCTION IF EXISTS public.assert_inserted_rows_name_a_vendor_of_their_client();
DROP FUNCTION IF EXISTS public.assert_updated_row_names_a_vendor_of_its_client();

COMMIT;
