-- Migration 536: the party-credit tables and the stock ledger are WRITTEN BY THE API ONLY and READ BY THE MEMBERS ASSIGNED
-- TO THE CLIENT, and `demo_filings`, which nothing reads or writes, is reachable by nobody signed in (POST-A-299's fourth
-- tranche, the write side the ledger item named as the urgent part).
--
-- WHAT WAS WRONG
-- Four client tables carried a firm policy and nothing else, so any member of the firm, an unassigned Reviewer included,
-- read and wrote them over PostgREST:
--
--   * party_credit_balances (SELECT, INSERT, UPDATE): `party_credit_service.apply_credit` trusts the stored balance and
--     then raises a document's paid_paise and status with no journal behind it, so a forged balance settled invoices on
--     paper (reproduced on a throwaway database on 21-10-2026: a balance of 100 paise raised to 99,999,999 by an
--     unassigned Reviewer);
--   * party_credit_ledger (SELECT, INSERT): the trail that explains the balance, writable with rows nobody signed in
--     could then remove;
--   * inventory_stock_ledger (SELECT, INSERT, UPDATE, DELETE): the append-only chain every later movement prices from
--     (`_last_ledger_row`), whose deltas closing stock is summed from and which ties to the Inventory control account; the
--     same Reviewer rewrote a row's value_delta_paise to 999,999,999 and deleted the whole ledger;
--   * demo_filings (ALL): a sandbox table from migration 087 that no code reads or writes any more (the browser-side demo
--     that wrote it was deleted, and the shared filing-demo framework writes nothing), holding SELECT, INSERT, UPDATE,
--     DELETE, TRUNCATE, REFERENCES and TRIGGER for every signed-in member.
--
-- WHAT THIS DOES
--   1. party_credit_service and the stock ledger's three writers (domain/inventory_service._insert_and_cache,
--      _set_ledger_journal_entry_id and seed_opening_balances_batch, and services/inventory_location_service.transfer) write
--      with the privileged client behind the routes' own checks (the shape of migrations 519 and 532). THAT SHIPPED IN
--      THE CHANGE BEFORE THIS ONE (PR #865, merged at 11:45 UTC on 22-10-2026), and it has to be live first: this migration
--      merges only after that change has been on Render for at least an hour (the sandbox cannot see which commit Render is
--      serving, so the hour is a delay and the dashboard is the check); the old API against these revoked grants
--      fails soft and wrong (the stock callers swallow the refusal after the item's cached quantity has moved, so an
--      invoice issues with no ledger row and no COGS journal; a bank overpayment's credit grant fails after the
--      transaction is posted).
--   2. INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES and TRIGGER are revoked from `authenticated` (and everything from
--      `anon` and PUBLIC) on the three client tables; SELECT stays, because the API reads them under the caller's own
--      sign-in (USE_USER_JWT, the production default) and row security is then the second lock on those reads. Nothing in
--      apps/web reads them: the browser names them in comments only.
--   3. The two RESTRICTIVE policies every client table carries (the assignment scope and the internal practice's
--      Partner-only guard, in the once-per-query form of migrations 525 to 532) are written for all three, so a member
--      reads the rows of the clients they are assigned to, a Partner reads every row of the firm, and the practice's own
--      rows are a Partner's. With the writes revoked they are the second lock on the write side too.
--   4. demo_filings: every privilege is revoked from `authenticated`, `anon` and PUBLIC. Nothing signed in reads it, so it
--      needs no scope; the service role keeps its grants.
--
-- The migration ends by verifying the EFFECTIVE privileges (has_table_privilege, which counts a grant that arrives through
-- PUBLIC) and that the service role keeps its writes. The tests/fixtures/assignment_scope_exceptions.json entries of the
-- first three leave the shrink-only list in the same commit; demo_filings leaves it by itself, because the catalog lists
-- only tables the signed-in role can reach.
--
-- ROLLBACK gives back exactly what the migrations that created these tables granted (214: SELECT, INSERT, UPDATE on the
-- balances and SELECT, INSERT on the ledger; 188: SELECT, INSERT, UPDATE, DELETE on the stock ledger; 087: ALL on
-- demo_filings) and drops the six policies. Production may hold more than the migrations granted (the platform's default
-- privileges); the revoke does not depend on what it held.

SELECT set_config('lock_timeout', '15s', true);

DROP POLICY IF EXISTS "party_credit_balances_assignment_scope" ON public.party_credit_balances;
CREATE POLICY "party_credit_balances_assignment_scope" ON public.party_credit_balances
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "party_credit_balances_internal_partner_only" ON public.party_credit_balances;
CREATE POLICY "party_credit_balances_internal_partner_only" ON public.party_credit_balances
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

REVOKE ALL ON public.party_credit_balances FROM PUBLIC, anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.party_credit_balances FROM authenticated;
GRANT SELECT ON public.party_credit_balances TO authenticated;

DROP POLICY IF EXISTS "party_credit_ledger_assignment_scope" ON public.party_credit_ledger;
CREATE POLICY "party_credit_ledger_assignment_scope" ON public.party_credit_ledger
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "party_credit_ledger_internal_partner_only" ON public.party_credit_ledger;
CREATE POLICY "party_credit_ledger_internal_partner_only" ON public.party_credit_ledger
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

REVOKE ALL ON public.party_credit_ledger FROM PUBLIC, anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.party_credit_ledger FROM authenticated;
GRANT SELECT ON public.party_credit_ledger TO authenticated;

DROP POLICY IF EXISTS "inventory_stock_ledger_assignment_scope" ON public.inventory_stock_ledger;
CREATE POLICY "inventory_stock_ledger_assignment_scope" ON public.inventory_stock_ledger
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "inventory_stock_ledger_internal_partner_only" ON public.inventory_stock_ledger;
CREATE POLICY "inventory_stock_ledger_internal_partner_only" ON public.inventory_stock_ledger
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

REVOKE ALL ON public.inventory_stock_ledger FROM PUBLIC, anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.inventory_stock_ledger FROM authenticated;
GRANT SELECT ON public.inventory_stock_ledger TO authenticated;

REVOKE ALL ON public.demo_filings FROM PUBLIC, anon, authenticated;

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['party_credit_balances', 'party_credit_ledger', 'inventory_stock_ledger'] LOOP
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
                IF has_table_privilege(r, 'public.' || t, verb) THEN
                    RAISE EXCEPTION 'migration 536: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, 'public.' || t, 'INSERT')
               OR has_any_column_privilege(r, 'public.' || t, 'UPDATE') THEN
                RAISE EXCEPTION 'migration 536: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF has_table_privilege('anon', 'public.' || t, 'SELECT') THEN
            RAISE EXCEPTION 'migration 536: anon still reads %', t;
        END IF;
        IF NOT has_table_privilege('authenticated', 'public.' || t, 'SELECT') THEN
            RAISE EXCEPTION 'migration 536: a signed-in session no longer reads %, and the API reads it as the caller', t;
        END IF;
        FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE'] LOOP
            IF NOT has_table_privilege('service_role', 'public.' || t, verb) THEN
                RAISE EXCEPTION 'migration 536: the API (service_role) cannot % %', verb, t;
            END IF;
        END LOOP;
    END LOOP;

    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege(r, 'public.demo_filings', verb) THEN
                RAISE EXCEPTION 'migration 536: % still holds % on demo_filings', r, verb;
            END IF;
        END LOOP;
        IF has_any_column_privilege(r, 'public.demo_filings', 'SELECT')
           OR has_any_column_privilege(r, 'public.demo_filings', 'INSERT')
           OR has_any_column_privilege(r, 'public.demo_filings', 'UPDATE') THEN
            RAISE EXCEPTION 'migration 536: % still holds a column-level privilege on demo_filings', r;
        END IF;
    END LOOP;
    IF NOT has_table_privilege('service_role', 'public.demo_filings', 'SELECT') THEN
        RAISE EXCEPTION 'migration 536: the service role lost demo_filings';
    END IF;
END $$;
