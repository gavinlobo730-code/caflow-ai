-- Migration 550: a signed-in session reads and writes none of the bank tables and runs neither bank report, nor reads the foreign bank
-- balances (POST-A-339, the bank group).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- POST-A-010 (25-10-2026) moved every read and write of the bank tables out of the browser: the four account pickers ask
-- `GET /api/banking/accounts`, statements, lines, splits, matches, rules and reconciliations are asked of the API, and
-- `tests/test_a_sensitive_table_is_not_read_from_the_browser.py` holds that the browser names none of them. What that did not do
-- was take the grants away. `authenticated` still held SELECT, INSERT, UPDATE and DELETE on all eight tables (and the platform's
-- TRUNCATE sat on `authenticated` and `anon`), so a person with their own sign-in could still call PostgREST by hand and read, or
-- write, exactly what the row policies let them: the account numbers, the narrations (which name counterparties who are strangers
-- to the engagement), the matches that settle invoices, the rules that post lines to the ledger on their own. The row policies are
-- good (migrations 093, 261, 370, 527 and 530 are the work of making them so) and they were all that stood between a hand-made
-- call and the data, when nothing legitimate needs the call to work at all.
--
-- Two bank REPORTS were open the same way. `bank_register` and `bank_reconciling_items` are `SECURITY INVOKER` functions that read
-- the bank tables as whoever calls them, and both were executable by PUBLIC, `anon` and `authenticated`. While the tables were
-- granted that was harmless (the invoker's own row security applied). Once the tables are not granted, a signed-in call to either
-- would be refused by the privilege anyway; the EXECUTE is taken away as well, so that the closed door is the one the next reader
-- sees, and so that a later migration that grants a table again does not silently reopen a report that returns whole registers.
--
-- A THIRD READER was open the same way, and an independent read of this change found it: `fx_foreign_bank_balances(p_firm,
-- p_client)` (migration 281) is `SECURITY DEFINER`, so it reads `bank_accounts` as its owner whatever the caller holds, and it
-- returns every foreign-currency account of a client with its bank name, ACCOUNT NUMBER, currency and balances. Its only gate is
-- the caller's firm and the client's assignment; it never asked the banking tier, so a Partner's block on `banking` (which the
-- database applies to the bank tables) did not reach it, and it stayed executable by `authenticated` when the tables were not.
-- Its only caller is `FxReportingService._foreign_bank_balances`, which now calls it through the privileged client (and falls
-- back to its own privileged Python reconciliation, correct and slower, if the call is refused, so the minutes between this
-- migration and the deploy that carries that change cost speed and not an answer).
--
-- The API was moved first (POST-A-339 step 1, merged and running before this migration, `/health` reading `audit_actor: carried`):
-- every query it makes on these tables is made with its privileged client, naming the firm and the client the caller's role would
-- have been limited to, and both reports are called through the privileged client too. The old API against revoked grants fails
-- soft and wrong (an empty list, a lookup that says not found, a posting skipped), which is why that change shipped and ran first.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- REVOKE SELECT, INSERT, UPDATE, DELETE and TRUNCATE from PUBLIC, `authenticated` and `anon` on the eight bank tables:
--
--   accounts                    bank_accounts
--   statements and their lines  bank_statements, bank_transactions, bank_transaction_splits
--   matching                    bank_reconciliation_matches, bank_matching_rules
--   reconciliation              bank_reconciliations
--   the importer's memory       bank_statement_column_mappings
--
-- and REVOKE EXECUTE on `bank_register`, `bank_reconciling_items` and `fx_foreign_bank_balances` from PUBLIC, `anon` and
-- `authenticated`, granting it to the service role explicitly (production's ACL for `bank_reconciling_items` held no explicit
-- service-role entry: it reached the role through PUBLIC, which the revoke would otherwise have taken). The platform's REFERENCES and TRIGGER privileges are not
-- privileges on rows and are left alone, as migrations 499 and 549 left them.
--
-- `service_role` keeps every privilege it had on the tables, and the migration REFUSES (rolls back) if the service role would be
-- left without one. THE ROW POLICIES STAY as the SECOND LOCK, the way 499 and 549 left theirs: a later migration that grants a list
-- of tables again (041 and 055 did) would undo a revoke and would not undo a policy. `tests/fixtures/rls_expected_second_lock.json`
-- holds what the policies decide, and a real-Postgres test gives the privilege back in a copy of the database and asks every
-- actor again.
--
-- WHAT A SIGNED-IN SESSION NOW SEES
--   Any read or write of one of these tables, or a call to either report, is "permission denied" (SQLSTATE 42501) instead of a
--   row-security answer. A foreign-key cascade is not a privilege check, so deleting a client still cascades as it did. The
--   SECURITY DEFINER functions that touch the bank tables as their owner are unaffected: `replace_bank_transaction_splits`,
--   `pair_bank_transfer` and `unpair_bank_transfer` are executable by the service role alone already,
--   `hub_client_worklist__unguarded` is not executable by a signed-in user, `bank_transaction_sync_has_splits` is a trigger
--   function, and `hub_client_worklist('banking')` stays callable because it returns per-client COUNTS and no bank record.
--
-- PRODUCTION, read from its catalogue on 26-10-2026: `authenticated` held SELECT, INSERT, UPDATE and DELETE (and the platform's
-- REFERENCES, TRIGGER and TRUNCATE) on all eight, `anon` held REFERENCES, TRIGGER and TRUNCATE; row security was on for all eight;
-- no policy of another table, and no view, refers to them (pg_policies and pg_depend), and the only functions that read them are
-- the ones named above.

DO $$
DECLARE
    tables text[] := ARRAY[
        'bank_accounts', 'bank_statements', 'bank_transactions', 'bank_transaction_splits',
        'bank_reconciliation_matches', 'bank_matching_rules', 'bank_reconciliations', 'bank_statement_column_mappings'
    ];
    fns regprocedure[] := ARRAY[
        'public.bank_register(uuid, uuid, date, date, text, text, text, boolean, integer, integer)'::regprocedure,
        'public.bank_reconciling_items(uuid, uuid, uuid, uuid, date, bigint, integer)'::regprocedure,
        'public.fx_foreign_bank_balances(uuid, uuid)'::regprocedure
    ];
    t text;
    r text;
    verb text;
    fn regprocedure;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;
    FOREACH fn IN ARRAY fns LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated', fn);
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', fn);
    END LOOP;

    -- The check asks the EFFECTIVE privilege (has_table_privilege, has_any_column_privilege and has_function_privilege), which
    -- sees a privilege that reaches the role through PUBLIC, through membership of another role or at column level, none of which
    -- a look at information_schema.role_table_grants for the two role names would.
    FOREACH t IN ARRAY tables LOOP
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 550: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'SELECT')
               OR has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 550: % still holds a column-level privilege on %', r, t;
            END IF;
        END LOOP;
        -- The API is unaffected: the service role keeps what it had.
        FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
            IF NOT has_table_privilege('service_role', format('public.%I', t), verb) THEN
                RAISE EXCEPTION 'migration 550: service_role no longer holds % on %', verb, t;
            END IF;
        END LOOP;
    END LOOP;
    FOREACH fn IN ARRAY fns LOOP
        IF has_function_privilege('authenticated', fn, 'EXECUTE') OR has_function_privilege('anon', fn, 'EXECUTE') THEN
            RAISE EXCEPTION 'migration 550: % is still executable by a signed-in user', fn;
        END IF;
        IF NOT has_function_privilege('service_role', fn, 'EXECUTE') THEN
            RAISE EXCEPTION 'migration 550: % is not executable by the service role', fn;
        END IF;
    END LOOP;
END $$;
