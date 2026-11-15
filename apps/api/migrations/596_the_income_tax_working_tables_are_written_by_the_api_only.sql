-- Migration 596: the income-tax working tables are written by the API only (ledger POST-A-008, the income-tax tranche, part 2 of 2).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Eleven income-tax tables are granted to the signed-in role behind policies that ask the firm and the client assignment and no role tier:
-- `ais_uploads`, `ais_records` and `ais_reconciliations` (the Annual Information Statement and the line-by-line working a s.143(1)(a)
-- adjustment is answered from), `ais_computation_decisions`, `form_26as_records`, `income_tax_asset_blocks` (the s.32 blocks),
-- `income_tax_worksheets`, `itr_filing_versions` (each version of a return's JSON), `tax_deduction_claims` (the Chapter VI-A claims), and
-- `it_deductions` and `tax_notices`, which nothing in the API or the browser reads or writes. Production granted `authenticated` INSERT, UPDATE,
-- DELETE and TRUNCATE on all eleven and `anon` TRUNCATE (read on 15-11-2026). The browser writes none of them, so a hand-made PostgREST request
-- from a signed-in session was the only user of the grant, and a Reviewer assigned to a client, who writes nothing through the API, could
-- rewrite the client's AIS working or add a deduction claim. Found through POST-A-008's list of the tables a signed-in session reaches outside
-- the access matrix.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (part 1, held over the source by
-- `tests/test_the_income_tax_working_tables_are_written_with_the_privileged_client.py`). This migration then REVOKES INSERT, UPDATE, DELETE and
-- TRUNCATE on the eleven tables from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column level, through
-- PUBLIC) and that `service_role` kept its writes. Reading and the row policies are untouched, so a member still reads the rows of the clients
-- they are assigned to. The shape is migration 593's.
--
-- DEPLOY ORDER: part 1 reached production first and this ships at least an hour after it, because an API instance still serving when the grant
-- goes, writing with the caller's own sign-in, would answer "permission denied" to a CA saving an AIS working or a deduction claim.
--
-- Idempotent. Reversible: 596_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['ais_uploads', 'ais_records', 'ais_reconciliations', 'ais_computation_decisions', 'form_26as_records', 'income_tax_asset_blocks', 'income_tax_worksheets', 'itr_filing_versions', 'tax_deduction_claims', 'it_deductions', 'tax_notices'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 596: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 596: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 596: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
