-- Rollback of migration 550: gives `authenticated` back the privileges the earlier migrations granted on the bank tables, and
-- gives PUBLIC, `anon` and `authenticated` back EXECUTE on the two bank reports.
-- THIS RE-OPENS THE HOLE: a person with their own sign-in can read and write, over PostgREST and not through the API, whatever the
-- row policies let them of the bank accounts, statements, lines, splits, matches, rules and reconciliations of their clients, and
-- run both reports. Roll back the code that depends on the revoke first (there is none: the API runs as the server on these tables
-- since POST-A-339 step 1).
-- It restores exactly what a database built from the migrations held before 550: SELECT, INSERT, UPDATE and DELETE on the eight
-- tables for `authenticated`, and EXECUTE on the two reports for PUBLIC (which is how a function created without a REVOKE reaches
-- `anon` and `authenticated`), with the service role's explicit entry kept. It does NOT restore the TRUNCATE privilege that 550
-- also revoked, because no migration ever granted it (it came from the hosting platform's defaults) and a signed-in role has no
-- use for it.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'bank_accounts', 'bank_statements', 'bank_transactions', 'bank_transaction_splits',
        'bank_reconciliation_matches', 'bank_matching_rules', 'bank_reconciliations', 'bank_statement_column_mappings'
    ] LOOP
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
    END LOOP;
    GRANT EXECUTE ON FUNCTION public.bank_register(uuid, uuid, date, date, text, text, text, boolean, integer, integer)
        TO PUBLIC, anon, authenticated;
    GRANT EXECUTE ON FUNCTION public.bank_reconciling_items(uuid, uuid, uuid, uuid, date, bigint, integer)
        TO PUBLIC, anon, authenticated;
    -- migration 281's grant: signed-in users and the service role, never PUBLIC or anon
    GRANT EXECUTE ON FUNCTION public.fx_foreign_bank_balances(uuid, uuid) TO authenticated, service_role;
END $$;
