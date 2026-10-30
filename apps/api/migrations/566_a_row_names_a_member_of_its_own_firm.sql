-- Migration 566: a row names a member of its own firm (POST-A-361, the second half of POST-A-304).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 565 made the database refuse a row that names a client of another firm. The same shape is open for the columns
-- that name a MEMBER: `created_by`, `assigned_to`, `reviewed_by`, `user_id` and the rest, every one a foreign key to
-- `users(id)`. A Partner of firm G, a foreign-key check that bypasses row security and a firm policy that asks `firm_id`
-- alone store a row of G that names a member of firm F. Migration 530 closed it for the two tables that decide access
-- (`user_client_assignments`, `user_permissions`) and for nothing else. Nothing is READ across tenants by this (the writer
-- needs the other firm's member id, which nothing serves, and the API names the caller's own id); but a row of one firm that
-- credits or assigns another firm's person is a row that firm's reports and notifications can end up carrying.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- One installer, `public.guard_member_firm(table)`, in the shape of 565's `guard_client_firm`: it finds every single-column
-- foreign key from the table to `users(id)` and gives the table two triggers that name those columns:
--
--   * STATEMENT-level AFTER INSERT over a transition table: one set-based join per column per statement however many rows it
--     carries (a statement upload or a Tally import writes thousands in one statement);
--   * ROW-level BEFORE UPDATE OF the named columns and `firm_id`, only WHEN one of them changes, so an ordinary update
--     (a status flip, a settlement) pays nothing.
--
-- The rule is the one 565 chose: refuse what PROVABLY crosses a tenant. A row with a NULL `firm_id` belongs to no firm and is
-- left alone, a NULL member (`created_by` on a row the system wrote) is left alone, and `users.firm_id` is NOT NULL so a
-- member always names a firm. Existing rows are counted in the apply report (`RAISE WARNING 'migration 566: ...'`, which the
-- runner keeps) and not changed.
--
-- WHAT IT DOES NOT COVER, AND WHY THAT IS NOT QUIET
--   * A column that names a member and has no foreign key to `users` (a bare uuid). The catalog cannot find it. 118 of the 209
--     client-and-firm tables 565 guarded had a `created_by` or similar; the ones with a foreign key are covered here, and the
--     rest are a different question (whether the column should be a foreign key at all).
--   * A PORTAL CONTACT. POST-A-361 named it beside the member. No table has a foreign key to `client_portal_users`; the one
--     column that names a portal contact, `client_portal_sessions.portal_contact_id`, is a bare uuid on a table only the API's
--     privileged client writes. Left open in the ledger with that reason.
--   * A member who changes firm. `users.firm_id` moving later does not re-check rows that already name the member.
--
-- A MAINTENANCE FACT: the update trigger names the columns it watches, so Postgres will not drop or retype one of them while the
-- trigger stands ("trigger row_member_in_firm_upd on table X depends on column Y"). A migration that drops or retypes a member
-- column drops the table's two triggers first and calls `guard_member_firm` after. The failure is loud and its hint says what to do.
--
-- Tables 530 already guards (`user_client_assignments`, `user_permissions`) get this check too: the two rules agree, and a
-- table with two overlapping checks is better than one a later edit to either drops.
--
-- MEASURED AGAINST PRODUCTION BEFORE MERGING: it was not (no read access). The apply report counts the existing rows and the
-- rule was chosen so that it can refuse a write only when it provably names another firm's member.
--
-- SECURITY DEFINER because the check has to SEE the other firm's member, which row security hides from the writer; every
-- function pins its search path (as 360 and 565 do). The two trigger functions take their column names from the trigger's own
-- arguments, which only the installer writes; `guard_member_firm` is a DDL helper and nobody signed in may run it.

BEGIN;

-- 1. The insert check (statement level). TG_ARGV is the list of columns that name a member.
CREATE OR REPLACE FUNCTION public.assert_inserted_rows_name_a_member_of_their_firm()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_col text;
    v_bad text;
BEGIN
    FOREACH v_col IN ARRAY TG_ARGV LOOP
        -- A column that has since been dropped (DROP COLUMN ... CASCADE takes the row trigger with it and leaves this one) names
        -- nobody: skip it, so a dropped column cannot make every later statement against the table fail. The catalog test fails the table.
        CONTINUE WHEN NOT EXISTS (
            SELECT 1 FROM pg_attribute a WHERE a.attrelid = TG_RELID AND a.attname = v_col AND a.attnum > 0 AND NOT a.attisdropped);
        EXECUTE format(
            'SELECT string_agg(DISTINCT n.%1$I::text, '', '') FROM new_rows n JOIN public.users u ON u.id = n.%1$I '
            'WHERE n.firm_id IS NOT NULL AND u.firm_id <> n.firm_id', v_col)
          INTO v_bad;
        IF v_bad IS NOT NULL THEN
            RAISE EXCEPTION 'a row of % names member(s) % in %, who belong to another firm', TG_TABLE_NAME, v_bad, v_col
                USING ERRCODE = '42501';
        END IF;
    END LOOP;
    RETURN NULL;
END $$;

-- 1b. The same, for a row that changes one of those columns or its firm.
CREATE OR REPLACE FUNCTION public.assert_updated_row_names_a_member_of_its_firm()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_col text;
    v_member uuid;
    v_row jsonb := to_jsonb(NEW);
BEGIN
    IF NEW.firm_id IS NULL THEN
        RETURN NEW;
    END IF;
    FOREACH v_col IN ARRAY TG_ARGV LOOP
        v_member := (v_row ->> v_col)::uuid;
        IF v_member IS NOT NULL AND EXISTS (
            SELECT 1 FROM public.users u WHERE u.id = v_member AND u.firm_id <> NEW.firm_id
        ) THEN
            RAISE EXCEPTION 'a row of % names member % in % who belongs to another firm', TG_TABLE_NAME, v_member, v_col
                USING ERRCODE = '42501';
        END IF;
    END LOOP;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION public.assert_inserted_rows_name_a_member_of_their_firm() IS
    'POST-A-361. Statement-level insert check: every column named in the trigger arguments (a foreign key to users) names a member '
    'of the row''s own firm. Refuses only what provably crosses a tenant. Installed by guard_member_firm. Migration 566.';
COMMENT ON FUNCTION public.assert_updated_row_names_a_member_of_its_firm() IS
    'POST-A-361. Row-level check for an update that changes one of the member columns named in the trigger arguments, or the firm. '
    'Migration 566.';

-- The member columns of a table: its single-column foreign keys to users(id), as the catalog has them now.
CREATE OR REPLACE FUNCTION public.member_columns_of(p_table regclass)
RETURNS text[]
LANGUAGE sql
STABLE
AS $$
    SELECT coalesce(array_agg(a.attname::text ORDER BY a.attname), ARRAY[]::text[])
      FROM pg_constraint k
      JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
     WHERE k.contype = 'f'
       AND k.conrelid = p_table
       AND k.confrelid = 'public.users'::regclass
       AND array_length(k.conkey, 1) = 1
       AND a.atttypid = 'uuid'::regtype
       AND NOT a.attisdropped;
$$;

-- The installer. Idempotent: it drops what it is about to create, and a table with no member column loses any left over.
CREATE OR REPLACE FUNCTION public.guard_member_firm(p_table regclass)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_cols text[];
    v_args text;
    v_when text;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_attribute a
         WHERE a.attrelid = p_table AND a.attname = 'firm_id' AND a.atttypid = 'uuid'::regtype
           AND a.attnum > 0 AND NOT a.attisdropped
    ) THEN
        RAISE EXCEPTION 'guard_member_firm: % has no uuid firm_id', p_table;
    END IF;

    EXECUTE format('DROP TRIGGER IF EXISTS row_member_in_firm_ins ON %s', p_table);
    EXECUTE format('DROP TRIGGER IF EXISTS row_member_in_firm_upd ON %s', p_table);

    v_cols := public.member_columns_of(p_table);
    IF cardinality(v_cols) = 0 THEN
        RETURN;
    END IF;

    SELECT string_agg(quote_literal(c), ', ' ORDER BY c) INTO v_args FROM unnest(v_cols) AS c;
    SELECT 'OLD.firm_id IS DISTINCT FROM NEW.firm_id OR '
           || string_agg(format('OLD.%1$I IS DISTINCT FROM NEW.%1$I', c), ' OR ' ORDER BY c)
      INTO v_when FROM unnest(v_cols) AS c;

    EXECUTE format(
        'CREATE TRIGGER row_member_in_firm_ins AFTER INSERT ON %s REFERENCING NEW TABLE AS new_rows '
        'FOR EACH STATEMENT EXECUTE FUNCTION public.assert_inserted_rows_name_a_member_of_their_firm(%s)', p_table, v_args);
    EXECUTE format(
        'CREATE TRIGGER row_member_in_firm_upd BEFORE UPDATE OF firm_id, %s ON %s FOR EACH ROW WHEN (%s) '
        'EXECUTE FUNCTION public.assert_updated_row_names_a_member_of_its_firm(%s)',
        (SELECT string_agg(format('%I', c), ', ' ORDER BY c) FROM unnest(v_cols) AS c), p_table, v_when, v_args);
END $$;

COMMENT ON FUNCTION public.member_columns_of(regclass) IS
    'POST-A-361. The columns of a table that are single-column foreign keys to users(id). Migration 566.';
COMMENT ON FUNCTION public.guard_member_firm(regclass) IS
    'POST-A-361. Installs the member-belongs-to-firm triggers on a table with a uuid firm_id and at least one foreign key to users. '
    'DDL: not for a signed-in role. Migration 566.';

REVOKE ALL ON FUNCTION public.guard_member_firm(regclass) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.guard_member_firm(regclass) FROM anon;
REVOKE ALL ON FUNCTION public.guard_member_firm(regclass) FROM authenticated;

-- Every plain table that has a uuid firm_id and a foreign key to users, as it stands.
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT c.oid::regclass AS t
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind = 'r'
           AND EXISTS (SELECT 1 FROM pg_attribute a
                        WHERE a.attrelid = c.oid AND a.attname = 'firm_id' AND a.atttypid = 'uuid'::regtype
                          AND a.attnum > 0 AND NOT a.attisdropped)
           AND cardinality(public.member_columns_of(c.oid::regclass)) > 0
         ORDER BY c.relname
    LOOP
        PERFORM public.guard_member_firm(r.t);
    END LOOP;
END $$;

-- The closing check, and the report of what already breaks the rule.
DO $$
DECLARE
    r record;
    v_col text;
    v_missing text;
    v_n bigint;
    v_rows bigint := 0;
    v_tables int := 0;
    v_columns int := 0;
    v_guarded int := 0;
BEGIN
    SELECT string_agg(c.relname, ', ' ORDER BY c.relname)
      INTO v_missing
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind = 'r'
       AND EXISTS (SELECT 1 FROM pg_attribute a
                    WHERE a.attrelid = c.oid AND a.attname = 'firm_id' AND a.atttypid = 'uuid'::regtype
                      AND a.attnum > 0 AND NOT a.attisdropped)
       AND cardinality(public.member_columns_of(c.oid::regclass)) > 0
       AND (SELECT count(*) FROM pg_trigger g
             WHERE g.tgrelid = c.oid AND NOT g.tgisinternal
               AND g.tgname IN ('row_member_in_firm_ins', 'row_member_in_firm_upd')) <> 2;
    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'migration 566: these tables still lack the member-in-firm triggers: %', v_missing;
    END IF;

    FOR r IN
        SELECT c.oid::regclass AS t
          FROM pg_class c
          JOIN pg_trigger g ON g.tgrelid = c.oid AND NOT g.tgisinternal AND g.tgname = 'row_member_in_firm_ins'
         ORDER BY c.relname
    LOOP
        v_guarded := v_guarded + 1;
        v_n := 0;
        FOREACH v_col IN ARRAY public.member_columns_of(r.t) LOOP
            v_columns := v_columns + 1;
            EXECUTE format(
                'SELECT count(*) FROM %s t JOIN public.users u ON u.id = t.%I '
                'WHERE t.firm_id IS NOT NULL AND u.firm_id <> t.firm_id', r.t, v_col) INTO v_n;
            IF v_n > 0 THEN
                v_rows := v_rows + v_n;
                v_tables := v_tables + 1;
            END IF;
        END LOOP;
    END LOOP;

    -- The runner keeps a WARNING that starts 'migration NNN:'. Rows found here are left as they are.
    RAISE WARNING 'migration 566: % tables (% member columns) now check that a row names a member of its own firm; % existing row(s) in % table column(s) already name a member of another firm; they are not changed or removed, and the check applies to every row written from now on',
        v_guarded, v_columns, v_rows, v_tables;
END $$;

COMMIT;
