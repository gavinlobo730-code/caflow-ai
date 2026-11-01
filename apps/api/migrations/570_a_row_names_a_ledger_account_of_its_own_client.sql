-- Migration 570: a row names a ledger account of its own client, or a firm-level account of its own firm (POST-A-353, the account family).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- A ledger LINE that names another client's account has been refused since migration 360 (it surfaces as a 500 "nothing was written"),
-- but the twenty-odd places that STORE a link to an account for later were never asked: a bank account's ledger account, a matching
-- rule's suggested account, a budget, a bill of entry's two accounts, a fixed asset's accumulated-depreciation account, a purchase
-- bill's landed cost, an order line's expense account, a bank line's account and draft account, a split, a recurring template's
-- lines, and an account's own parent. Each is a foreign key to chart_of_accounts(id), and a foreign-key check bypasses row security,
-- so each is satisfied by ANY account in the database. Four more links have NO foreign key at all, so no key even asks that the account
-- exists: a year-end adjustment's debit and credit accounts, a year-end mapping's account, and a purchase bill line's expense account.
-- The API asks whose the account is at only some of those doors. A row that holds another client's account is not a leak (nothing
-- serves another tenant's account id, so the writer needs a UUID they cannot get), but it is a stored link into another client's books
-- that fails later, at the moment the document posts.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- One rule, installed by one function (`public.guard_ledger_account`) on every foreign key to chart_of_accounts of a table that carries
-- its own uuid firm_id and client_id, on the two recurring-template line tables and the purchase bill lines through their parent, on the
-- year-end adjustment's two unkeyed columns, and, judged by the FIRM alone because a year-end mapping belongs to the firm and not to a
-- client, on the year-end mapping's account:
--
--   A row's account belongs to the row's own FIRM and is either that CLIENT's account or a firm-level one (client_id IS NULL), the same
--   rule migration 360 applies to a journal line.
--
-- The insert check is STATEMENT-level with a transition table (one set-based join per statement however many rows it carries, the shape
-- 360 and 565 chose); the update check is ROW-level, BEFORE UPDATE OF the column and the keys it is judged against, and only WHEN one of
-- them actually changes, so an ordinary update pays nothing and a row that already breaks the rule is not blocked from an unrelated edit.
--
-- WHAT IT DELIBERATELY DOES NOT REFUSE
--   * A row whose firm or client is NULL, and an account whose firm or client is NULL: the check refuses what it can PROVE crosses a
--     tenant (both sides known and different), as 565 does. A firm-level account (client_id NULL) is allowed on any of that firm's rows.
--   * What changes on the ACCOUNT's side. Only the row is judged: a Partner who moves an account to another client does not re-judge the
--     rows that already point at it, a firm-level row (no client) naming a client-level account is accepted (it matters for an account's
--     own parent only), and changing a template's own client does not re-judge its lines. Each is a limit, written in the design record.
--   * Rows that already exist. They are COUNTED and reported (the `RAISE WARNING 'migration 570: ...'` below, which the runner keeps) and
--     left: a row found that way is a finding for a person. A read-only count on production on 1-11-2026 found none in the nine columns
--     whose tables carry a client of their own that were counted.
--   * `journal_lines` (migration 360 already asks), and `account_period_balances` and `ledger_balances`, which only the database's own
--     triggers write, from lines 360 has already checked.
--
-- SECURITY DEFINER because the check has to SEE the other client's account, which row security hides from the writer; the two trigger
-- functions pin their search path. The installer is invoker-run DDL: nobody signed in may run it. A refusal is P0001, a business rule
-- written for a person (core/exceptions surfaces its message as it is); 42501 would be worded as a fault on our side.

BEGIN;

-- 1. The insert check. Trigger arguments, fixed at install: [0] the column that names the account; [1] and [2] for a table judged through a
--    parent, the parent table and the column that names it ('' for none); [3] what the row is judged by, 'client' (its firm and its
--    client) or 'firm' (its firm alone).
CREATE OR REPLACE FUNCTION public.assert_inserted_rows_name_a_ledger_account_of_their_client()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_col text := TG_ARGV[0];
    v_parent text := NULLIF(TG_ARGV[1], '');
    v_fk text := NULLIF(TG_ARGV[2], '');
    v_by_client boolean := TG_ARGV[3] = 'client';
    v_bad text;
BEGIN
    IF v_parent IS NULL THEN
        EXECUTE format(
            'SELECT string_agg(DISTINCT j.%1$I::text, '', '') FROM new_rows j '
            'JOIN public.chart_of_accounts a ON a.id = j.%1$I '
            'WHERE (j.firm_id IS NOT NULL AND a.firm_id IS NOT NULL AND a.firm_id <> j.firm_id)%2$s',
            v_col,
            CASE WHEN v_by_client THEN ' OR (j.client_id IS NOT NULL AND a.client_id IS NOT NULL AND a.client_id <> j.client_id)' ELSE '' END)
          INTO v_bad;
    ELSE
        EXECUTE format(
            'SELECT string_agg(DISTINCT n.%1$I::text, '', '') FROM new_rows n '
            'JOIN public.%2$I j ON j.id = n.%3$I '
            'JOIN public.chart_of_accounts a ON a.id = n.%1$I '
            'WHERE (j.firm_id IS NOT NULL AND a.firm_id IS NOT NULL AND a.firm_id <> j.firm_id)%4$s',
            v_col, v_parent, v_fk,
            CASE WHEN v_by_client THEN ' OR (j.client_id IS NOT NULL AND a.client_id IS NOT NULL AND a.client_id <> j.client_id)' ELSE '' END)
          INTO v_bad;
    END IF;

    IF v_bad IS NOT NULL THEN
        RAISE EXCEPTION 'That ledger account belongs to another client or firm, so it cannot be used on this record (% in %: %).',
            v_col, TG_TABLE_NAME, v_bad;
    END IF;
    RETURN NULL;
END $$;

-- 2. The update check, for a row that changes the account or what it is judged against.
CREATE OR REPLACE FUNCTION public.assert_updated_row_names_a_ledger_account_of_its_client()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_col text := TG_ARGV[0];
    v_parent text := NULLIF(TG_ARGV[1], '');
    v_fk text := NULLIF(TG_ARGV[2], '');
    v_by_client boolean := TG_ARGV[3] = 'client';
    v_row jsonb := to_jsonb(NEW);
    v_account uuid := NULLIF(v_row ->> v_col, '')::uuid;
    v_firm uuid;
    v_client uuid;
    v_afirm uuid;
    v_aclient uuid;
BEGIN
    IF v_account IS NULL THEN
        RETURN NEW;
    END IF;
    IF v_parent IS NULL THEN
        v_firm := NULLIF(v_row ->> 'firm_id', '')::uuid;
        v_client := CASE WHEN v_by_client THEN NULLIF(v_row ->> 'client_id', '')::uuid END;
    ELSE
        EXECUTE format('SELECT firm_id, %s FROM public.%I WHERE id = $1',
                       CASE WHEN v_by_client THEN 'client_id' ELSE 'NULL::uuid' END, v_parent)
           INTO v_firm, v_client
          USING NULLIF(v_row ->> v_fk, '')::uuid;
    END IF;
    SELECT a.firm_id, a.client_id INTO v_afirm, v_aclient FROM public.chart_of_accounts a WHERE a.id = v_account;
    IF (v_firm IS NOT NULL AND v_afirm IS NOT NULL AND v_afirm <> v_firm)
       OR (v_client IS NOT NULL AND v_aclient IS NOT NULL AND v_aclient <> v_client) THEN
        RAISE EXCEPTION 'That ledger account belongs to another client or firm, so it cannot be used on this record (% in %: %).',
            v_col, TG_TABLE_NAME, v_account;
    END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION public.assert_inserted_rows_name_a_ledger_account_of_their_client() IS
    'POST-A-353. Statement-level insert check: every row names a ledger account of its own client or a firm-level account of its own firm '
    '(its own columns, its parent''s for a line table, or its firm alone for a firm-wide table). Refuses only what provably crosses a tenant. '
    'Installed by guard_ledger_account. Migration 570.';
COMMENT ON FUNCTION public.assert_updated_row_names_a_ledger_account_of_its_client() IS
    'POST-A-353. Row-level check for an update that changes the account column or the client or firm it is judged against. Migration 570.';

-- 3. The installer. Idempotent: it drops what it is about to create. A table judged through a parent (it has no client of its own) names
--    the parent and the column that points at it; a table that belongs to the firm and not to a client says p_firm_only. The column must
--    be a uuid; if it has a foreign key, the key must be to chart_of_accounts (four links have none, and are the reason this does not
--    require one).
CREATE OR REPLACE FUNCTION public.guard_ledger_account(p_table regclass, p_column text,
                                                        p_parent regclass DEFAULT NULL, p_parent_fk text DEFAULT NULL,
                                                        p_firm_only boolean DEFAULT false)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_judged regclass := COALESCE(p_parent, p_table);
    v_ins text := 'row_ledger_account_' || p_column || '_ins';
    v_upd text := 'row_ledger_account_' || p_column || '_upd';
    v_keys text;
    v_when text;
    v_args text;
    v_need int := CASE WHEN p_firm_only THEN 1 ELSE 2 END;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = p_table AND a.attname = p_column
                      AND a.atttypid = 'uuid'::regtype AND NOT a.attisdropped) THEN
        RAISE EXCEPTION 'guard_ledger_account: %.% is not a uuid column', p_table, p_column;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint k
                WHERE k.contype = 'f' AND k.conrelid = p_table
                  AND k.conkey = ARRAY[(SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = p_table AND a.attname = p_column)]
                  AND k.confrelid <> 'public.chart_of_accounts'::regclass) THEN
        RAISE EXCEPTION 'guard_ledger_account: %.% is a foreign key to something other than chart_of_accounts', p_table, p_column;
    END IF;
    IF (SELECT count(*) FROM pg_attribute a
         WHERE a.attrelid = v_judged AND a.attname = ANY (CASE WHEN p_firm_only THEN ARRAY['firm_id'] ELSE ARRAY['client_id', 'firm_id'] END)
           AND a.atttypid = 'uuid'::regtype AND a.attnum > 0 AND NOT a.attisdropped) <> v_need THEN
        RAISE EXCEPTION 'guard_ledger_account: % has not the uuid columns % to judge % by', v_judged,
            CASE WHEN p_firm_only THEN 'firm_id' ELSE 'client_id and firm_id' END, p_column;
    END IF;
    IF p_parent IS NOT NULL AND (p_parent_fk IS NULL OR NOT EXISTS (
        SELECT 1 FROM pg_attribute a WHERE a.attrelid = p_table AND a.attname = p_parent_fk
           AND a.atttypid = 'uuid'::regtype AND NOT a.attisdropped)) THEN
        RAISE EXCEPTION 'guard_ledger_account: % has no uuid column % naming its parent %', p_table, p_parent_fk, p_parent;
    END IF;

    v_args := format('%L, %L, %L, %L', p_column, COALESCE((SELECT relname FROM pg_class WHERE oid = p_parent), ''),
                     COALESCE(p_parent_fk, ''), CASE WHEN p_firm_only THEN 'firm' ELSE 'client' END);
    IF p_parent IS NULL THEN
        v_keys := CASE WHEN p_firm_only THEN format('%I, firm_id', p_column) ELSE format('%I, client_id, firm_id', p_column) END;
        v_when := format('OLD.%1$I IS DISTINCT FROM NEW.%1$I OR OLD.firm_id IS DISTINCT FROM NEW.firm_id', p_column)
                  || CASE WHEN p_firm_only THEN '' ELSE ' OR OLD.client_id IS DISTINCT FROM NEW.client_id' END;
    ELSE
        v_keys := format('%I, %I', p_column, p_parent_fk);
        v_when := format('OLD.%1$I IS DISTINCT FROM NEW.%1$I OR OLD.%2$I IS DISTINCT FROM NEW.%2$I', p_column, p_parent_fk);
    END IF;

    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %s', v_ins, p_table);
    EXECUTE format(
        'CREATE TRIGGER %I AFTER INSERT ON %s REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT '
        'EXECUTE FUNCTION public.assert_inserted_rows_name_a_ledger_account_of_their_client(%s)', v_ins, p_table, v_args);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %s', v_upd, p_table);
    EXECUTE format(
        'CREATE TRIGGER %I BEFORE UPDATE OF %s ON %s FOR EACH ROW WHEN (%s) '
        'EXECUTE FUNCTION public.assert_updated_row_names_a_ledger_account_of_its_client(%s)', v_upd, v_keys, p_table, v_when, v_args);
END $$;

COMMENT ON FUNCTION public.guard_ledger_account(regclass, text, regclass, text, boolean) IS
    'POST-A-353. Installs the account-belongs-to-the-row''s-client check on one uuid column that names a ledger account. DDL: not for a signed-in role. Migration 570.';

REVOKE ALL ON FUNCTION public.guard_ledger_account(regclass, text, regclass, text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.guard_ledger_account(regclass, text, regclass, text, boolean) FROM anon;
REVOKE ALL ON FUNCTION public.guard_ledger_account(regclass, text, regclass, text, boolean) FROM authenticated;

-- 4. Install it. Every foreign key to chart_of_accounts of a plain table with its own uuid firm_id and client_id, except the three the
--    header explains; then the two line tables that are judged through their template.
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT k.conrelid::regclass AS t, a.attname::text AS col
          FROM pg_constraint k
          JOIN pg_class c ON c.oid = k.conrelid AND c.relkind = 'r'
          JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
          JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
         WHERE k.contype = 'f' AND k.confrelid = 'public.chart_of_accounts'::regclass
           AND array_length(k.conkey, 1) = 1
           AND c.relname NOT IN ('journal_lines', 'account_period_balances', 'ledger_balances')
           AND (SELECT count(*) FROM pg_attribute x
                 WHERE x.attrelid = c.oid AND x.attname IN ('client_id', 'firm_id')
                   AND x.atttypid = 'uuid'::regtype AND x.attnum > 0 AND NOT x.attisdropped) = 2
         ORDER BY c.relname, a.attname
    LOOP
        PERFORM public.guard_ledger_account(r.t, r.col);
    END LOOP;

    PERFORM public.guard_ledger_account('public.recurring_journal_template_lines', 'account_id',
                                        'public.recurring_journal_templates', 'template_id');
    PERFORM public.guard_ledger_account('public.recurring_purchase_bill_template_lines', 'expense_account_id',
                                        'public.recurring_purchase_bill_templates', 'template_id');

    -- The four links that have no foreign key at all (nothing even asks that the account exists), found by listing every uuid column
    -- named for an account that is not a key to anything. The tables are named, not discovered: each is judged by something different.
    PERFORM public.guard_ledger_account('public.year_end_adjustments', 'debit_account_id');
    PERFORM public.guard_ledger_account('public.year_end_adjustments', 'credit_account_id');
    PERFORM public.guard_ledger_account('public.purchase_bill_lines', 'expense_account_id', 'public.purchase_bills', 'bill_id');
    -- A year-end mapping belongs to the firm and not to a client (one row per account), so the firm alone is what it is judged by.
    PERFORM public.guard_ledger_account('public.account_group_mappings', 'account_id', NULL, NULL, true);
END $$;

-- 5. The closing check: no eligible column is left without its two triggers (a loop that skipped one would otherwise look like
--    success), and the report of what already breaks the rule. Existing rows are counted and left as they are.
DO $$
DECLARE
    r record;
    v_missing text := '';
    v_n bigint;
    v_rows bigint := 0;
    v_cols int := 0;
    v_guarded int := 0;
BEGIN
    FOR r IN
        SELECT g.tgrelid::regclass AS t, g.tgname AS name
          FROM pg_trigger g
         WHERE NOT g.tgisinternal AND g.tgname LIKE 'row\_ledger\_account\_%\_ins'
         ORDER BY g.tgrelid::regclass::text, g.tgname
    LOOP
        v_guarded := v_guarded + 1;
        IF NOT EXISTS (SELECT 1 FROM pg_trigger u WHERE u.tgrelid = r.t AND NOT u.tgisinternal
                        AND u.tgname = regexp_replace(r.name, '_ins$', '_upd')) THEN
            v_missing := v_missing || r.t::text || ' (' || r.name || '), ';
        END IF;
    END LOOP;
    IF v_missing <> '' THEN
        RAISE EXCEPTION 'migration 570: these columns have an insert check and no update check: %', v_missing;
    END IF;

    FOR r IN
        SELECT k.conrelid::regclass AS t, a.attname::text AS col
          FROM pg_constraint k
          JOIN pg_class c ON c.oid = k.conrelid AND c.relkind = 'r'
          JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
          JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
         WHERE k.contype = 'f' AND k.confrelid = 'public.chart_of_accounts'::regclass
           AND array_length(k.conkey, 1) = 1
           AND c.relname NOT IN ('journal_lines', 'account_period_balances', 'ledger_balances',
                                 'recurring_journal_template_lines', 'recurring_purchase_bill_template_lines')
           AND (SELECT count(*) FROM pg_attribute x
                 WHERE x.attrelid = c.oid AND x.attname IN ('client_id', 'firm_id')
                   AND x.atttypid = 'uuid'::regtype AND x.attnum > 0 AND NOT x.attisdropped) = 2
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_trigger g WHERE g.tgrelid = r.t AND NOT g.tgisinternal
                        AND g.tgname = 'row_ledger_account_' || r.col || '_ins') THEN
            RAISE EXCEPTION 'migration 570: %.% still has no account check', r.t, r.col;
        END IF;
        EXECUTE format(
            'SELECT count(*) FROM %s t JOIN public.chart_of_accounts a ON a.id = t.%I '
            'WHERE (t.firm_id IS NOT NULL AND a.firm_id IS NOT NULL AND a.firm_id <> t.firm_id) '
            '   OR (t.client_id IS NOT NULL AND a.client_id IS NOT NULL AND a.client_id <> t.client_id)', r.t, r.col) INTO v_n;
        IF v_n > 0 THEN
            v_rows := v_rows + v_n;
            v_cols := v_cols + 1;
        END IF;
    END LOOP;

    EXECUTE 'SELECT count(*) FROM public.recurring_journal_template_lines t '
            'JOIN public.recurring_journal_templates p ON p.id = t.template_id '
            'JOIN public.chart_of_accounts a ON a.id = t.account_id '
            'WHERE (p.firm_id IS NOT NULL AND a.firm_id IS NOT NULL AND a.firm_id <> p.firm_id) '
            '   OR (p.client_id IS NOT NULL AND a.client_id IS NOT NULL AND a.client_id <> p.client_id)' INTO v_n;
    IF v_n > 0 THEN v_rows := v_rows + v_n; v_cols := v_cols + 1; END IF;
    EXECUTE 'SELECT count(*) FROM public.recurring_purchase_bill_template_lines t '
            'JOIN public.recurring_purchase_bill_templates p ON p.id = t.template_id '
            'JOIN public.chart_of_accounts a ON a.id = t.expense_account_id '
            'WHERE (p.firm_id IS NOT NULL AND a.firm_id IS NOT NULL AND a.firm_id <> p.firm_id) '
            '   OR (p.client_id IS NOT NULL AND a.client_id IS NOT NULL AND a.client_id <> p.client_id)' INTO v_n;
    IF v_n > 0 THEN v_rows := v_rows + v_n; v_cols := v_cols + 1; END IF;

    -- The four links with no foreign key. A row that names an account that does not exist is not a row that crosses a tenant and is not counted.
    FOR r IN
        SELECT * FROM (VALUES
            ('year_end_adjustments', 'debit_account_id'),
            ('year_end_adjustments', 'credit_account_id')) AS x(t, col)
    LOOP
        EXECUTE format(
            'SELECT count(*) FROM public.%I t JOIN public.chart_of_accounts a ON a.id = t.%I '
            'WHERE (t.firm_id IS NOT NULL AND a.firm_id IS NOT NULL AND a.firm_id <> t.firm_id) '
            '   OR (t.client_id IS NOT NULL AND a.client_id IS NOT NULL AND a.client_id <> t.client_id)', r.t, r.col) INTO v_n;
        IF v_n > 0 THEN v_rows := v_rows + v_n; v_cols := v_cols + 1; END IF;
    END LOOP;
    EXECUTE 'SELECT count(*) FROM public.purchase_bill_lines t '
            'JOIN public.purchase_bills p ON p.id = t.bill_id '
            'JOIN public.chart_of_accounts a ON a.id = t.expense_account_id '
            'WHERE (p.firm_id IS NOT NULL AND a.firm_id IS NOT NULL AND a.firm_id <> p.firm_id) '
            '   OR (p.client_id IS NOT NULL AND a.client_id IS NOT NULL AND a.client_id <> p.client_id)' INTO v_n;
    IF v_n > 0 THEN v_rows := v_rows + v_n; v_cols := v_cols + 1; END IF;
    EXECUTE 'SELECT count(*) FROM public.account_group_mappings t '
            'JOIN public.chart_of_accounts a ON a.id = t.account_id '
            'WHERE t.firm_id IS NOT NULL AND a.firm_id IS NOT NULL AND a.firm_id <> t.firm_id' INTO v_n;
    IF v_n > 0 THEN v_rows := v_rows + v_n; v_cols := v_cols + 1; END IF;

    -- The runner keeps a WARNING that starts 'migration NNN:'. Rows found here are left as they are.
    RAISE WARNING 'migration 570: % ledger-account columns now check that a row names an account of its own client or a firm-level account of its own firm; % existing row(s) in % column(s) already name another client''s or firm''s account; they are not changed or removed, and the check applies to every row written from now on',
        v_guarded, v_rows, v_cols;
END $$;

COMMIT;
