-- Migration 565: a row names a client of its own firm, and a customer or vendor of its own client (POST-A-304).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- The independent review of migration 528 inserted, as a Partner of firm G, rows whose `firm_id` was G's and whose
-- `client_id` was a client of firm F, into the sixteen tables of that migration. All were accepted. The reasons stack:
-- the Partner branch of the assignment scope short-circuits to TRUE, the firm policy checks `firm_id` alone, and a
-- foreign-key check bypasses row security, so `client_id -> clients(id)` is satisfied by ANY client in the database.
-- The same review, as an assigned Manager, stored a recurring template for their own client that named ANOTHER
-- client's customer. Nothing is READ across tenants by this (the writer needs the other tenant's UUID, which nothing
-- serves), and the API asserts the client first; but the database was willing to store a row whose client belongs to
-- another firm, and a row of firm G naming F's client is a row F's own policies and reports can end up counting.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- Three rules, each a trigger that every table carrying the columns gets from one installer
-- (`public.guard_client_firm(table)`), so the rule lives in six functions and not in two hundred tables:
--
--   1. A row's `client_id` names a client of the row's own `firm_id`.
--   2. A row's `customer_id` (where it is a foreign key to `customers`) names a customer of the row's own `client_id`.
--   3. A row's `vendor_id` (where it is a foreign key to `vendors`) names a vendor of the row's own `client_id`.
--
-- The insert check is STATEMENT-level with a transition table, the shape migration 360 chose for the same reason: a
-- statement upload or a Tally import writes thousands of rows in one statement, and one set-based join per statement
-- costs the same however many rows it carries. The update check is ROW-level, BEFORE UPDATE OF the two columns and
-- only WHEN one of them actually changes, so an ordinary update (a status flip, a settlement) pays nothing.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IT DELIBERATELY DOES NOT REFUSE, AND WHY NONE OF IT IS A HOLE
-- ═══════════════════════════════════════════════════════════════════════════
--   * A row or a client with a NULL `firm_id`. `clients.firm_id` and nine other tables' `firm_id` are nullable. Such a
--     row belongs to no firm, so no firm's policy shows it to anyone, and refusing it would only break a write this
--     migration cannot see in production. The check refuses what it can PROVE crosses a tenant.
--   * A `client_id` that names no client at all. Thirty-six of these tables have no foreign key to `clients` in the
--     migration-built schema; an id that matches nothing cannot belong to another firm. Whether those columns should be
--     real foreign keys is a different question and not this one.
--   * A partitioned table. The installer takes plain tables only: a transition-table trigger on a partitioned parent is not something this
--     migration can try against production before it applies, and a failure there would stop every later migration. None is known; the
--     count in the apply report below is of the tables that were guarded.
--   * Rows that already exist. The triggers fire on writes. This migration COUNTS the existing rows that break the rules
--     and reports the count in the run (the `RAISE WARNING 'migration 565: ...'` below, which the runner keeps), and
--     leaves them: a row found that way is a finding for a person, not something for a migration to delete or to fail on.
--
-- MEASURED AGAINST PRODUCTION BEFORE MERGING: it was not. This session had no read access to the production database,
-- so the counts above are the apply report's job and the rules above were chosen so that none of them can refuse a write
-- unless it provably names another tenant's client, customer or vendor.
--
-- SECURITY DEFINER because the check has to SEE the other firm's client, which row security hides from the writer; every
-- function pins its search path (as 360 does) and none takes an argument, so none can be pointed at a caller's choice.
-- `guard_client_firm` is a DDL helper, not a trigger, and nobody signed in may run it.

BEGIN;

-- 1. A row's client belongs to the row's firm — the insert check (statement level).
CREATE OR REPLACE FUNCTION public.assert_inserted_rows_name_a_client_of_their_firm()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_bad text;
BEGIN
    SELECT string_agg(DISTINCT n.client_id::text, ', ')
      INTO v_bad
      FROM new_rows n
      JOIN public.clients c ON c.id = n.client_id
     WHERE n.firm_id IS NOT NULL
       AND c.firm_id IS NOT NULL
       AND c.firm_id <> n.firm_id;

    IF v_bad IS NOT NULL THEN
        RAISE EXCEPTION 'a row of % names client(s) % that belong to another firm', TG_TABLE_NAME, v_bad
            USING ERRCODE = '42501';
    END IF;
    RETURN NULL;
END $$;

-- 1b. The same, for a row that changes its client or its firm.
CREATE OR REPLACE FUNCTION public.assert_updated_row_names_a_client_of_its_firm()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
BEGIN
    IF NEW.client_id IS NOT NULL AND NEW.firm_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.clients c
         WHERE c.id = NEW.client_id AND c.firm_id IS NOT NULL AND c.firm_id <> NEW.firm_id
    ) THEN
        RAISE EXCEPTION 'a row of % names client % that belongs to another firm', TG_TABLE_NAME, NEW.client_id
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END $$;

-- 2. A row's customer belongs to the row's client.
CREATE OR REPLACE FUNCTION public.assert_inserted_rows_name_a_customer_of_their_client()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_bad text;
BEGIN
    SELECT string_agg(DISTINCT n.customer_id::text, ', ')
      INTO v_bad
      FROM new_rows n
      JOIN public.customers p ON p.id = n.customer_id
     WHERE n.client_id IS NOT NULL
       AND p.client_id <> n.client_id;

    IF v_bad IS NOT NULL THEN
        RAISE EXCEPTION 'a row of % names customer(s) % that belong to another client', TG_TABLE_NAME, v_bad
            USING ERRCODE = '42501';
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION public.assert_updated_row_names_a_customer_of_its_client()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
BEGIN
    IF NEW.client_id IS NOT NULL AND NEW.customer_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.customers p WHERE p.id = NEW.customer_id AND p.client_id <> NEW.client_id
    ) THEN
        RAISE EXCEPTION 'a row of % names customer % that belongs to another client', TG_TABLE_NAME, NEW.customer_id
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END $$;

-- 3. A row's vendor belongs to the row's client.
CREATE OR REPLACE FUNCTION public.assert_inserted_rows_name_a_vendor_of_their_client()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_bad text;
BEGIN
    SELECT string_agg(DISTINCT n.vendor_id::text, ', ')
      INTO v_bad
      FROM new_rows n
      JOIN public.vendors p ON p.id = n.vendor_id
     WHERE n.client_id IS NOT NULL
       AND p.client_id <> n.client_id;

    IF v_bad IS NOT NULL THEN
        RAISE EXCEPTION 'a row of % names vendor(s) % that belong to another client', TG_TABLE_NAME, v_bad
            USING ERRCODE = '42501';
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION public.assert_updated_row_names_a_vendor_of_its_client()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
BEGIN
    IF NEW.client_id IS NOT NULL AND NEW.vendor_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.vendors p WHERE p.id = NEW.vendor_id AND p.client_id <> NEW.client_id
    ) THEN
        RAISE EXCEPTION 'a row of % names vendor % that belongs to another client', TG_TABLE_NAME, NEW.vendor_id
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION public.assert_inserted_rows_name_a_client_of_their_firm() IS
    'POST-A-304. Statement-level insert check: every row names a client of its own firm. Refuses only what provably crosses a tenant '
    '(both firms known and different). Installed on a table by guard_client_firm. Migration 565.';
COMMENT ON FUNCTION public.assert_updated_row_names_a_client_of_its_firm() IS
    'POST-A-304. Row-level check for an update that changes client_id or firm_id. Migration 565.';

-- The installer. One place says which triggers a table gets, so a table created later asks for them with one call, and a
-- guard (tests/test_a_client_firm_table_a_migration_creates_carries_the_check.py) fails a migration that creates such a
-- table without calling it. It is idempotent: it drops what it is about to create.
CREATE OR REPLACE FUNCTION public.guard_client_firm(p_table regclass)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_ok boolean;
BEGIN
    SELECT count(*) = 2
      INTO v_ok
      FROM pg_attribute a
     WHERE a.attrelid = p_table
       AND a.attname IN ('client_id', 'firm_id')
       AND a.atttypid = 'uuid'::regtype
       AND a.attnum > 0
       AND NOT a.attisdropped;
    IF NOT v_ok THEN
        RAISE EXCEPTION 'guard_client_firm: % has no uuid client_id and firm_id', p_table;
    END IF;

    EXECUTE format('DROP TRIGGER IF EXISTS row_client_in_firm_ins ON %s', p_table);
    EXECUTE format(
        'CREATE TRIGGER row_client_in_firm_ins AFTER INSERT ON %s REFERENCING NEW TABLE AS new_rows '
        'FOR EACH STATEMENT EXECUTE FUNCTION public.assert_inserted_rows_name_a_client_of_their_firm()', p_table);
    EXECUTE format('DROP TRIGGER IF EXISTS row_client_in_firm_upd ON %s', p_table);
    EXECUTE format(
        'CREATE TRIGGER row_client_in_firm_upd BEFORE UPDATE OF client_id, firm_id ON %s FOR EACH ROW '
        'WHEN (OLD.client_id IS DISTINCT FROM NEW.client_id OR OLD.firm_id IS DISTINCT FROM NEW.firm_id) '
        'EXECUTE FUNCTION public.assert_updated_row_names_a_client_of_its_firm()', p_table);

    -- A customer column that is a foreign key to customers.
    IF EXISTS (
        SELECT 1 FROM pg_constraint k
         WHERE k.contype = 'f' AND k.conrelid = p_table AND k.confrelid = 'public.customers'::regclass
           AND k.conkey = ARRAY[(SELECT a.attnum FROM pg_attribute a
                                  WHERE a.attrelid = p_table AND a.attname = 'customer_id' AND NOT a.attisdropped)]
    ) THEN
        EXECUTE format('DROP TRIGGER IF EXISTS row_customer_in_client_ins ON %s', p_table);
        EXECUTE format(
            'CREATE TRIGGER row_customer_in_client_ins AFTER INSERT ON %s REFERENCING NEW TABLE AS new_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION public.assert_inserted_rows_name_a_customer_of_their_client()', p_table);
        EXECUTE format('DROP TRIGGER IF EXISTS row_customer_in_client_upd ON %s', p_table);
        EXECUTE format(
            'CREATE TRIGGER row_customer_in_client_upd BEFORE UPDATE OF client_id, customer_id ON %s FOR EACH ROW '
            'WHEN (OLD.client_id IS DISTINCT FROM NEW.client_id OR OLD.customer_id IS DISTINCT FROM NEW.customer_id) '
            'EXECUTE FUNCTION public.assert_updated_row_names_a_customer_of_its_client()', p_table);
    END IF;

    -- A vendor column that is a foreign key to vendors.
    IF EXISTS (
        SELECT 1 FROM pg_constraint k
         WHERE k.contype = 'f' AND k.conrelid = p_table AND k.confrelid = 'public.vendors'::regclass
           AND k.conkey = ARRAY[(SELECT a.attnum FROM pg_attribute a
                                  WHERE a.attrelid = p_table AND a.attname = 'vendor_id' AND NOT a.attisdropped)]
    ) THEN
        EXECUTE format('DROP TRIGGER IF EXISTS row_vendor_in_client_ins ON %s', p_table);
        EXECUTE format(
            'CREATE TRIGGER row_vendor_in_client_ins AFTER INSERT ON %s REFERENCING NEW TABLE AS new_rows '
            'FOR EACH STATEMENT EXECUTE FUNCTION public.assert_inserted_rows_name_a_vendor_of_their_client()', p_table);
        EXECUTE format('DROP TRIGGER IF EXISTS row_vendor_in_client_upd ON %s', p_table);
        EXECUTE format(
            'CREATE TRIGGER row_vendor_in_client_upd BEFORE UPDATE OF client_id, vendor_id ON %s FOR EACH ROW '
            'WHEN (OLD.client_id IS DISTINCT FROM NEW.client_id OR OLD.vendor_id IS DISTINCT FROM NEW.vendor_id) '
            'EXECUTE FUNCTION public.assert_updated_row_names_a_vendor_of_its_client()', p_table);
    END IF;
END $$;

COMMENT ON FUNCTION public.guard_client_firm(regclass) IS
    'POST-A-304. Installs the client-belongs-to-firm triggers (and the customer and vendor ones where the table has those foreign '
    'keys) on a table with a uuid client_id and firm_id. DDL: not for a signed-in role. Migration 565.';

-- Nobody signed in runs any of these directly. The trigger functions cannot be called as functions at all; the installer can.
REVOKE ALL ON FUNCTION public.guard_client_firm(regclass) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.guard_client_firm(regclass) FROM anon;
REVOKE ALL ON FUNCTION public.guard_client_firm(regclass) FROM authenticated;

-- Every table that has both columns, as it stands.
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT c.oid::regclass AS t
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind = 'r'
           AND (SELECT count(*) FROM pg_attribute a
                 WHERE a.attrelid = c.oid AND a.attname IN ('client_id', 'firm_id')
                   AND a.atttypid = 'uuid'::regtype AND a.attnum > 0 AND NOT a.attisdropped) = 2
         ORDER BY c.relname
    LOOP
        PERFORM public.guard_client_firm(r.t);
    END LOOP;
END $$;

-- The closing check: no eligible table is left without its two client triggers (a loop that skipped one would otherwise
-- look like success), and the report of what already breaks the rules.
DO $$
DECLARE
    r record;
    v_missing text;
    v_n bigint;
    v_client_rows bigint := 0;
    v_client_tables int := 0;
    v_party_rows bigint := 0;
    v_party_tables int := 0;
    v_guarded int := 0;
BEGIN
    SELECT string_agg(c.relname, ', ' ORDER BY c.relname)
      INTO v_missing
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind = 'r'
       AND (SELECT count(*) FROM pg_attribute a
             WHERE a.attrelid = c.oid AND a.attname IN ('client_id', 'firm_id')
               AND a.atttypid = 'uuid'::regtype AND a.attnum > 0 AND NOT a.attisdropped) = 2
       AND (SELECT count(*) FROM pg_trigger g
             WHERE g.tgrelid = c.oid AND NOT g.tgisinternal
               AND g.tgname IN ('row_client_in_firm_ins', 'row_client_in_firm_upd')) <> 2;
    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'migration 565: these tables still lack the client-in-firm triggers: %', v_missing;
    END IF;

    FOR r IN
        SELECT c.oid::regclass AS t
          FROM pg_class c
          JOIN pg_trigger g ON g.tgrelid = c.oid AND NOT g.tgisinternal AND g.tgname = 'row_client_in_firm_ins'
         ORDER BY c.relname
    LOOP
        v_guarded := v_guarded + 1;
        EXECUTE format(
            'SELECT count(*) FROM %s t JOIN public.clients c ON c.id = t.client_id '
            'WHERE t.firm_id IS NOT NULL AND c.firm_id IS NOT NULL AND c.firm_id <> t.firm_id', r.t) INTO v_n;
        IF v_n > 0 THEN
            v_client_rows := v_client_rows + v_n;
            v_client_tables := v_client_tables + 1;
        END IF;
    END LOOP;

    FOR r IN
        SELECT c.oid::regclass AS t
          FROM pg_class c
          JOIN pg_trigger g ON g.tgrelid = c.oid AND NOT g.tgisinternal AND g.tgname = 'row_customer_in_client_ins'
    LOOP
        EXECUTE format(
            'SELECT count(*) FROM %s t JOIN public.customers p ON p.id = t.customer_id '
            'WHERE t.client_id IS NOT NULL AND p.client_id <> t.client_id', r.t) INTO v_n;
        IF v_n > 0 THEN
            v_party_rows := v_party_rows + v_n;
            v_party_tables := v_party_tables + 1;
        END IF;
    END LOOP;

    FOR r IN
        SELECT c.oid::regclass AS t
          FROM pg_class c
          JOIN pg_trigger g ON g.tgrelid = c.oid AND NOT g.tgisinternal AND g.tgname = 'row_vendor_in_client_ins'
    LOOP
        EXECUTE format(
            'SELECT count(*) FROM %s t JOIN public.vendors p ON p.id = t.vendor_id '
            'WHERE t.client_id IS NOT NULL AND p.client_id <> t.client_id', r.t) INTO v_n;
        IF v_n > 0 THEN
            v_party_rows := v_party_rows + v_n;
            v_party_tables := v_party_tables + 1;
        END IF;
    END LOOP;

    -- The runner keeps a WARNING that starts 'migration NNN:'. Rows found here are left as they are.
    RAISE WARNING 'migration 565: % tables now check that a row names a client of its own firm; % existing row(s) in % table(s) already name a client of another firm, and % existing row(s) in % table(s) name a customer or vendor of another client; they are not changed or removed, and the check applies to every row written from now on',
        v_guarded, v_client_rows, v_client_tables, v_party_rows, v_party_tables;
END $$;

COMMIT;
