-- Migration 527 — the children of a client's bank lines take the client's assignment scope and the internal practice's
-- Partner-only guard (POST-A-005, the third item of its STILL OPEN list; found by the review of migration 524).
--
-- THE HOLE
--
--   `bank_transactions`, `bank_statements` and `bank_reconciliations` carry a RESTRICTIVE assignment scope (migration 084:
--   a Partner sees every client, anyone else the clients they are assigned to) and a RESTRICTIVE internal-practice guard
--   (074: the firm's own practice is a client whose rows only a Partner sees). Three of their children did not, and still
--   do not:
--
--       bank_transaction_splits           firm policy (and, since 524, the banking read tier); has a client_id
--       bank_matching_rules               firm policy (and, since 524, the banking read tier); has a client_id
--       bank_reconciliation_matches       firm policy (and, since 524, the banking read tier); no client_id: keyed on the line
--
--   so a member of the firm assigned to NO client at all, or to a different one, could `select`, `update` or `delete`
--   the splits of any client's bank lines (the account each part was coded to, the amount and the narration), every
--   client's matching rules (a description pattern, an amount range and the account it suggests) and every match
--   between a bank line and a journal line, straight over PostgREST with their own sign-in, and could insert a split
--   or a rule into a client they are not assigned to. A Manager the API refuses at `assert_client_access` for a
--   client reaches the same rows by not asking the API. The browser does not read these tables; PostgREST does not
--   care what the browser reads, and the API itself reads them under the caller's sign-in when USE_USER_JWT is on
--   (the production default). The 14-10-2026 decision to leave the tables with no per-client rule (POST-B-016) deferred
--   the question to the extension of the role-by-table matrix (POST-A-008); this is its settlement for the bank's
--   children, and `tests/test_every_client_table_is_assignment_scoped_or_says_why_pg.py` is the rule for the rest.
--
-- WHAT THIS DOES
--
--   1. On `bank_transaction_splits` and `bank_matching_rules` (each has a NOT NULL `client_id`): the two RESTRICTIVE
--      FOR ALL policies the parents carry, written the way migrations 525 and 526 write them so they are asked once per
--      query and not once per row:
--
--          <table>_assignment_scope       COALESCE(client_id::text IS NULL OR (SELECT get_my_role()) = 'Partner'
--                                                  OR client_id::text IN (SELECT my_assigned_client_ids()), false)
--          <table>_internal_partner_only  (SELECT get_my_role()) = 'Partner'
--                                         OR client_id::text IS DISTINCT FROM (SELECT my_internal_client_id())::text
--
--      in the USING and in the WITH CHECK, so a person cannot insert a row for a client they cannot see, nor move one.
--   2. On `bank_reconciliation_matches`, which has no client, and on `bank_transaction_splits` too: one RESTRICTIVE FOR ALL
--      policy, `<table>_parent_visible`, asking that the bank line the row belongs to is one the caller can see (an
--      EXISTS over `bank_transactions`, whose own policies - the firm, the assignment scope, the internal-practice guard
--      and, since 524, the banking tier - apply to the caller inside it). A match is therefore exactly as visible as its
--      line, for a read, an update, a delete and, in the WITH CHECK, an insert. A split carries a client of its own, but
--      nothing ties that client to its line's, so without this a person assigned to client A could write a split with
--      client A's id onto client B's bank line. The parent is read by its primary key; each policy adds one index lookup
--      per row.
--
--   They narrow the firm policy already there and cannot widen anything. Nothing a Partner can do changes, and nothing
--   an assigned Manager or Executive does changes: the API's own routes (`routers/banking.py`) assert the client first.
--
--   Every CREATE POLICY below is written out with its name as a literal, on purpose: `test_guards_match_production_pg`
--   excuses a restrictive policy that production does not hold yet only when a migration after its snapshot names it in
--   plain text, and a name built by `format()` from a loop is invisible to it (the first draft of this file did that and
--   would have turned the required real-Postgres check red).
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--
--   * `bank_statement_column_mappings`, which has a client_id and a firm policy and is NOT scoped on purpose: the
--     firm-wide second look of `find_mapping` (BANK-26) reuses a layout drawn for one account on another account of the
--     practice, for a co-operative bank that no adapter knows, and a scope on reads would end that for everyone but a
--     Partner. The table holds column headings and positions, not a client's figures. Its writes carry a role tier
--     (Executive and above). It is listed as an `own` entry in `tests/fixtures/assignment_scope_exceptions.json`. What
--     is wrong in the neighbourhood is that `save_mapping` updates a layout of ANOTHER account when the firm-wide look
--     finds one, instead of recording one for this account (POST-A-300).
--   * The other client tables that carry a firm policy and no per-client rule; they are listed, with the reason each is
--     not done yet, in `tests/fixtures/assignment_scope_exceptions.json`, which `test_every_client_table_is_assignment_
--     scoped_or_says_why_pg` holds shrink-only (a table that gains a scope must leave the list, and a new one cannot join).
--   * `bank_accounts`, the account master (524's header says why: pickers and posting readers need it without Banking).
--   * The SECURITY INVOKER database functions `bank_register` (353) and `bank_reconciling_items` (356) read the parents
--     (`bank_accounts`, `bank_transactions`, `bank_statements`, `bank_reconciliations`, the journal) and none of the three
--     tables changed here, so their results do not change.
--
-- Idempotent (DROP POLICY IF EXISTS before each CREATE). Reversible: 527_..._rollback.sql drops the six policies, which
-- restores the firm-only behaviour and nothing else.
--
-- LOCKS. DROP POLICY and CREATE POLICY take an ACCESS EXCLUSIVE lock on their table until the migration commits (it is one
-- transaction); the three tables are small. A lock_timeout of 15 seconds for this transaction (as 525 and 526 set) makes a
-- long-running transaction that holds one of them fail the migration, to be re-run, instead of queueing every later request
-- on the table behind it.

SELECT set_config('lock_timeout', '15s', true);

-- ── bank_transaction_splits: the client, the internal practice, and the line it hangs from ───────────────────────────
DROP POLICY IF EXISTS "bank_transaction_splits_assignment_scope" ON public.bank_transaction_splits;
CREATE POLICY "bank_transaction_splits_assignment_scope" ON public.bank_transaction_splits
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "bank_transaction_splits_internal_partner_only" ON public.bank_transaction_splits;
CREATE POLICY "bank_transaction_splits_internal_partner_only" ON public.bank_transaction_splits
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

DROP POLICY IF EXISTS "bank_transaction_splits_parent_visible" ON public.bank_transaction_splits;
CREATE POLICY "bank_transaction_splits_parent_visible" ON public.bank_transaction_splits
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.bank_transactions bt WHERE bt.id = bank_transaction_splits.bank_transaction_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.bank_transactions bt WHERE bt.id = bank_transaction_splits.bank_transaction_id));

-- ── bank_matching_rules: the client and the internal practice ────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "bank_matching_rules_assignment_scope" ON public.bank_matching_rules;
CREATE POLICY "bank_matching_rules_assignment_scope" ON public.bank_matching_rules
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "bank_matching_rules_internal_partner_only" ON public.bank_matching_rules;
CREATE POLICY "bank_matching_rules_internal_partner_only" ON public.bank_matching_rules
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- ── bank_reconciliation_matches: no client of its own, so it follows the line ────────────────────────────────────────
DROP POLICY IF EXISTS "bank_reconciliation_matches_parent_visible" ON public.bank_reconciliation_matches;
CREATE POLICY "bank_reconciliation_matches_parent_visible" ON public.bank_reconciliation_matches
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.bank_transactions bt WHERE bt.id = bank_reconciliation_matches.bank_transaction_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.bank_transactions bt WHERE bt.id = bank_reconciliation_matches.bank_transaction_id));
