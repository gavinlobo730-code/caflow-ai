-- Migration 524 — the database asks the banking tier when a client's bank lines, statements and reconciliations are read
-- (POST-A-005, the bank half; found by the per-person grid work of migrations 403, 415 and 485).
--
-- THE HOLE
--
--   The API reserves `banking:read` to Executive and above (`core/permissions.py`: Reviewer is outside it) and every
--   route in `routers/banking.py` asks it through `rbac("banking", "read")`, which resolves the person's own grid
--   entry first (migration 403). Nothing at the database asked it. The six tables below carry a firm policy and,
--   on three of them, an assignment scope (084), and a role tier on the WRITES of two (487, asking `banking:write`:
--   `bank_transactions` and `bank_accounts`) and nothing on a read. So a Partner who unticked Banking for a Manager on the Team screen
--   still left that Manager able to `select` every narration, counterparty name, UPI handle and amount on the
--   client's statements straight over PostgREST with their own sign-in, and a Reviewer assigned to the client did
--   not even need a grid entry: the Reviewer role is outside the route's floor and inside the table's.
--
--   That is the data the DPDP notes call the largest population of third parties in the product: the strangers
--   named in a bank narration (docs/compliance/06-data-protection-dpdp.md section 5e).
--
-- WHAT THIS DOES
--
--   One RESTRICTIVE SELECT policy on each of
--       bank_transactions, bank_statements, bank_transaction_splits,
--       bank_reconciliations, bank_reconciliation_matches, bank_matching_rules
--   asking `my_permission('banking', 'read', 'Executive')`: the function the route's `rbac()` resolves through,
--   at the floor `PERMISSIONS["banking"]["read"]` states, so a per-person yes or no in the access grid is honoured
--   by the database exactly as it is by the route. The policies are RESTRICTIVE, so they AND with the firm
--   isolation and assignment scope already there and can only narrow. Postgres also applies a SELECT policy to
--   the rows an UPDATE or DELETE has to find, so a person who cannot read a bank line cannot change or delete it
--   either (an UPDATE or DELETE that cannot see its row matches nothing). An INSERT is not untouched either: the
--   API inserts with the new row asked back (PostgREST `return=representation`, which is INSERT ... RETURNING),
--   and Postgres checks that row against the SELECT policies too, so a person who may write Banking and may not
--   read it (a Partner can save that grid state, one toggle at a time) is refused at the database on every
--   insert the API makes for them: 42501, which the central speaker words as a server fault. That state is now
--   refused at the DOOR instead, in words: every route of `routers/banking.py` asks `banking:read` first, as a
--   router-level dependency (the payroll finalise tier's rule, POST-A-219), so the policy stays the second lock.
--
--   THE CALL IS WRAPPED IN `(SELECT ...)` AND THAT IS NOT STYLE. `my_permission` is a STABLE plpgsql function
--   that reads `user_permissions`; written bare in a policy, Postgres calls it once per ROW. Measured here on
--   100,000 rows, the same count(*) under the same sign-in took 5.4 s with no tier policy, 61.1 s with the bare
--   call and 6.3 s with the call wrapped (the planner then evaluates it once, as an InitPlan). Migration 485 wrote
--   the bare form on payroll tables, which hold hundreds of rows. A client's bank lines run to about 300 a month on
--   this repository's own figure (`domain/banking/exceptions.py`), so thousands a year and, for a firm, hundreds
--   of thousands over a few years; the bare form costs about 0.55 ms for every row a read scans (61.1 s against
--   6.3 s wrapped on a bare 100,000-row count, about ten times), so the wrapped spelling is the one that cannot make a read of
--   those tables slower as they grow. The guard for this migration asserts the wrapped spelling.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--
--   * `bank_accounts`, the account MASTER (bank name and account number). It is read straight from the browser by
--     the payment-account pickers on receipts, vendor payments and fixed-asset purchases, which are screens a
--     person with sales or accounting access uses without Banking, and the server's own readers of it
--     (`domain/accounting/payment_account`, the post-dated cheque, payroll disbursement and opening-balance paths)
--     run under the caller's sign-in and would see the chosen account as one with no ledger and post the receipt
--     or payment to the default Bank ledger instead (`resolve_payment_account`), which is a wrong posting and not
--     an error. Gating it needs those readers moved behind an access check first.
--     The Team screen's notice keeps naming bank accounts among the tables a block does not reach.
--   * `bank_statement_column_mappings`, which holds a bank's column headings and no client data.
--   * The assignment scope of the three children that carry only a firm policy (`bank_transaction_splits`,
--     `bank_reconciliation_matches`, `bank_matching_rules`): a member of the firm still reaches them whether or
--     not they are assigned to the client. That is a different gap (it is the one 485 closed for the payroll
--     children by scoping through the parent) and it is not claimed closed here.
--   * Documents and the Storage bucket behind them (POST-A-005's other half).
--   * THE TEXT OF A POSTED LINE. These policies hide the six TABLES. A bank line that has been posted also
--     carries its description in the narration of its journal entry (`journal_entries.narration`, "Bank: ..."),
--     which this migration does not touch (`journal_entries` and `journal_lines` stay readable to every assigned
--     staff role straight from the database, and the ledger serves them over the API under `accounting:read`),
--     and the GSTR-3B drill-down serves the description of a posted line on which GST was declared to anyone who
--     holds `gst:read`, which is every staff role. So over the API a person with `gst:read` and without
--     `accounting:read` still reads that one text, by that one route, for lines the practice has already posted.
--     What is newly out of reach is the statement itself: the lines nobody has posted yet, which are the ones
--     carrying a counterparty's name the practice has not even matched to a party.
--   * No function, grant, table, column or row changes. No backfill.
--
-- WHO NOTICES, AND WHAT THE API DID ABOUT IT (same commit)
--
--   Under USE_USER_JWT the API runs as the caller, so this binds the API path too. Two doors outside the
--   banking module read these tables under the caller's own sign-in for people who need not hold `banking:read`,
--   and would now have answered EMPTY, which is worse than a refusal: the client health score (a staff member
--   who reaches it without `banking:read` - the calculate route asks `client:write`, Manager and above, and the
--   score and dimension reads ask `client:read`, every staff role - would have had "no unreconciled bank line"
--   counted as a clean bill, and the six-month hard override missed) and the GST return build (a bank charge on which the CA declared GST would
--   have been left out of the return of a person who holds `gst:compute` and no Banking). Both now read the one
--   fact they need through the service client, after the caller's access to the client is checked (the health
--   read selects only an id and a date; the GST read also selects the line's description, which its drill-down
--   shows: see the caveat above). The accounting dashboard's "Unmatched Bank Txns" tile read the table from the
--   browser and would have shown 0; it now asks the server (`GET /api/banking/unmatched-count`, behind
--   `banking:read`, which asks the person's access on every request), is not asked at all of a person the
--   permission map says is blocked, and shows a dash with the note "Not part of your access" for them (a
--   refusal or any failure is a dash with "Could not be read", never a 0). The hub, the first-run checklist and the
--   books reconciliation already read through the service client.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, and the closing check fails the migration (and so the
-- deploy) if any policy is missing or is not RESTRICTIVE. Reversible:
-- 524_the_database_asks_the_banking_tier_when_a_clients_bank_lines_are_read_rollback.sql drops them again, which
-- RE-OPENS the hole.

DROP POLICY IF EXISTS "bank_transactions_banking_read_tier" ON public.bank_transactions;
CREATE POLICY "bank_transactions_banking_read_tier" ON public.bank_transactions
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING ((SELECT public.my_permission('banking', 'read', 'Executive')));

DROP POLICY IF EXISTS "bank_statements_banking_read_tier" ON public.bank_statements;
CREATE POLICY "bank_statements_banking_read_tier" ON public.bank_statements
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING ((SELECT public.my_permission('banking', 'read', 'Executive')));

DROP POLICY IF EXISTS "bank_transaction_splits_banking_read_tier" ON public.bank_transaction_splits;
CREATE POLICY "bank_transaction_splits_banking_read_tier" ON public.bank_transaction_splits
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING ((SELECT public.my_permission('banking', 'read', 'Executive')));

DROP POLICY IF EXISTS "bank_reconciliations_banking_read_tier" ON public.bank_reconciliations;
CREATE POLICY "bank_reconciliations_banking_read_tier" ON public.bank_reconciliations
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING ((SELECT public.my_permission('banking', 'read', 'Executive')));

DROP POLICY IF EXISTS "bank_reconciliation_matches_banking_read_tier" ON public.bank_reconciliation_matches;
CREATE POLICY "bank_reconciliation_matches_banking_read_tier" ON public.bank_reconciliation_matches
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING ((SELECT public.my_permission('banking', 'read', 'Executive')));

DROP POLICY IF EXISTS "bank_matching_rules_banking_read_tier" ON public.bank_matching_rules;
CREATE POLICY "bank_matching_rules_banking_read_tier" ON public.bank_matching_rules
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING ((SELECT public.my_permission('banking', 'read', 'Executive')));

-- ── the closing check: all 6 policies exist, every one is RESTRICTIVE, and every one is for SELECT ──────────────
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_policies
   WHERE schemaname = 'public'
     AND permissive = 'RESTRICTIVE'
     AND cmd = 'SELECT'
     AND policyname IN (
       'bank_transactions_banking_read_tier', 'bank_statements_banking_read_tier',
       'bank_transaction_splits_banking_read_tier', 'bank_reconciliations_banking_read_tier',
       'bank_reconciliation_matches_banking_read_tier', 'bank_matching_rules_banking_read_tier');
  IF n <> 6 THEN
    RAISE EXCEPTION 'migration 524: expected 6 restrictive select policies, found %', n;
  END IF;
END $$;
