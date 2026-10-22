-- Migration 532 — a client's year locks are visible to the members who post into that client, and written by the API alone
-- (POST-A-314, high; also the third tranche of POST-A-299: `client_year_locks` was the one table on the shrink-only list whose
-- trouble was a dead policy and not a missing one).
--
-- THE HOLE
--
--   Migration 289 wrote the only policy of `client_year_locks` as
--
--       USING / WITH CHECK (firm_id = (auth.jwt() ->> 'firm_id')::uuid)
--
--   the shape migration 154 found on the tables of 059, 067 and 071 and fixed: this project issues no `firm_id` claim, so the
--   predicate is NULL for everyone, a Partner included. Row security therefore refuses every signed-in session every row of
--   this table, in both directions. With USE_USER_JWT on (the production default) that has two consequences, and the second is
--   the serious one:
--
--   1. FINALISING A YEAR-END FAILS HALF WAY. `routers/year_end.py` and `routers/year_end_reviews.py` write the engagement as
--      `locked` and then call `year_lock_service.set_client_lock` with the caller's own sign-in; the insert of the lock row is
--      refused by row security after the engagement row was written, so the engagement reads "locked" and the client's year
--      stays open. (The docstring of `set_client_lock` records the same shape of failure from a wrong actor id, and says it was
--      latent because production holds no year-end engagements yet. It still holds none, so nothing was harmed.)
--
--   2. A FINALISED YEAR READS AS OPEN TO EVERY CHECK MADE UNDER A SIGN-IN. `public.period_closure_reason` and
--      `public.period_lock_reason` (migrations 361 and 267) are SECURITY INVOKER and read `client_year_locks` directly, so a call
--      made under a signed-in session sees no lock row and answers NULL for a year the administrator sees as closed. The posting
--      kernel's gate (`services/phase2_journal_service._create_journal` -> `period_lock_service.closure_reason(db, ...)`, with
--      the request's own client) and the pre-checks of invoices, bills, credit and debit notes, receipts, fixed assets,
--      inventory, the manual journal and the imports (`period_lock_service.assert_open`) all ask it that way. `post_journal_atomic`
--      does not ask the question again. The ledger line for this item first said the kernel "is not fooled" because it is a
--      definer function; that was wrong, the check is made before it, in Python, as the caller. So for every path that asks, the
--      year lock of a client was not enforced against a signed-in session at all, and the first year-end any firm finalised would
--      have been finalised in name only. Reproduced on a throwaway database on 21-10-2026: the administrator reads one lock row
--      and the reason; a signed-in Partner reads 0 rows and NULL.
--
--   3. NOT FIXED HERE, AND SAID SO (POST-A-316): two doors never ask the question at all, whatever this migration does.
--      `post_journal_atomic` and `settle_receipt_atomic` are SECURITY DEFINER functions a signed-in person may call with their
--      own token, and neither reads `client_year_locks`; the API's plain rupee customer receipt posts through
--      `settle_receipt_atomic` and not through the kernel. The independent review of this migration built each on a throwaway
--      database and posted into a finalised year as an assigned Executive, Manager and Reviewer, and as a Partner. The durable
--      fix belongs in the database (a closure check after the caller check in both functions, which as definers read the table as
--      their owner) and is its own change on the hottest write path in the product.
--
-- WHAT THIS DOES
--
--   READS. The dead policy is replaced by the canonical firm policy (`firm_id = (SELECT get_my_firm_id())`, FOR ALL, as the other tables have it) and the two
--   RESTRICTIVE FOR ALL policies every client table carries since migrations 084 and 074, in the once-per-query form of 525 to
--   531: `client_year_locks_assignment_scope` (a Partner, or the client is one of the caller's assigned clients) and
--   `client_year_locks_internal_partner_only` (a Partner, or the client is not the firm's internal practice). So a Partner reads
--   every lock of the firm, a Manager or an Executive assigned to a client reads that client's locks and nobody else's, and the
--   two invoker functions above answer for the clients the caller can post for, which is every client they can reach through the
--   API. Not done here, deliberately: making the two functions SECURITY DEFINER. A definer function with arguments that a
--   signed-in user can execute must ask who is calling (migration 486) or it answers about any firm and client for anyone, and the
--   kernel calls these functions on every posting; fixing the table's visibility is the smaller and the safer change, and it is
--   the one every other table the invoker functions read (`firms`, `filings`) already has.
--
--   WRITES. The lock row is written by the API and by nobody signed in, as migrations 499, 515 and 519 did for the payroll
--   tables the browser never writes: `year_lock_service.set_client_lock` now reads and writes the table with the privileged
--   client, behind the routes' own checks (a Partner finalises and a Partner reopens: `routers/year_end._assert_transition_allowed`
--   and `routers/year_end_reviews.final_approve` / `reopen`, each after the engagement's own scope check), and this migration
--   REVOKEs INSERT, UPDATE, DELETE and TRUNCATE from the signed-in roles. Nothing else writes the table (nothing in
--   `apps/web` reads or writes it; the one mention is a comment). The reason for taking the grant away and not only for adding a
--   role tier is the audit trail: a lock deleted over the database by anyone who could do so leaves no `client_year_lock` row in
--   `audit_log`, and the unlock needs a reason that the API demands and the database cannot. As the SECOND lock, three
--   RESTRICTIVE write policies (`client_year_locks_role_insert|update|delete`) ask for a Partner, so that a later GRANT, or a
--   default privilege nobody noticed, does not let an assigned Executive lock or unlock a year; a test grants the writes in a
--   throwaway database to show it.
--
--   The scope's `client_id IS NULL OR` branch can never be true here (the client is NOT NULL); it is written anyway, because every
--   scope since 527 is written in that one shape and the rollback of migration 526 recognises only that shape.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--
--   * `public.is_client_fy_locked`, which nothing calls and which migration 486 took from the signed-in role.
--   * The ORDER of the year-end routes: the engagement row is still written as `locked` before the lock row, so a failure of the
--     second (a database outage between the two statements) still leaves an engagement that reads locked and a year that is
--     open. It is no longer the ordinary outcome of finalising; making the pair atomic is a separate piece of work (see the
--     ledger).
--   * The two doors above (POST-A-316), and the fact that `post_journal_atomic`, unlike `settle_receipt_atomic`, is not wrapped by
--     the accounting:write role-pair check of migration 486, so a Reviewer can call it (the same ledger item).
--   * The seven other client tables on the shrink-only list (POST-A-299).
--
-- Idempotent (DROP POLICY IF EXISTS before each CREATE; the REVOKEs and the GRANT can be repeated). Reversible:
-- 532_..._rollback.sql restores the policy migration 289 wrote and the write grants it gave, and drops the policies created
-- here. (anon's and PUBLIC's access to the table is not given back: neither could read a row.)
--
-- LOCKS. The statements take an ACCESS EXCLUSIVE lock on the table until the migration commits; the table has no rows in
-- production (no year-end has been finalised), and a lock_timeout of 15 seconds makes a long transaction holding it fail the
-- migration, to be re-run, instead of queueing every later request behind it.
--
-- Every CREATE POLICY below is written out with its name as a literal, on purpose: `test_guards_match_production_pg` excuses a
-- restrictive policy that production does not hold yet only when a migration after its snapshot names it in plain text.

SELECT set_config('lock_timeout', '15s', true);

-- ── READS ─────────────────────────────────────────────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "client_year_locks_firm_isolation" ON public.client_year_locks;
CREATE POLICY "client_year_locks_firm_isolation" ON public.client_year_locks
  FOR ALL TO authenticated
  USING (firm_id = (SELECT public.get_my_firm_id()))
  WITH CHECK (firm_id = (SELECT public.get_my_firm_id()));

DROP POLICY IF EXISTS "client_year_locks_assignment_scope" ON public.client_year_locks;
CREATE POLICY "client_year_locks_assignment_scope" ON public.client_year_locks
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "client_year_locks_internal_partner_only" ON public.client_year_locks;
CREATE POLICY "client_year_locks_internal_partner_only" ON public.client_year_locks
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- ── WRITES: the second lock, a Partner's act ──────────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "client_year_locks_role_insert" ON public.client_year_locks;
CREATE POLICY "client_year_locks_role_insert" ON public.client_year_locks
  AS RESTRICTIVE FOR INSERT
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text);

DROP POLICY IF EXISTS "client_year_locks_role_update" ON public.client_year_locks;
CREATE POLICY "client_year_locks_role_update" ON public.client_year_locks
  AS RESTRICTIVE FOR UPDATE
  USING ((SELECT public.get_my_role()) = 'Partner'::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text);

DROP POLICY IF EXISTS "client_year_locks_role_delete" ON public.client_year_locks;
CREATE POLICY "client_year_locks_role_delete" ON public.client_year_locks
  AS RESTRICTIVE FOR DELETE
  USING ((SELECT public.get_my_role()) = 'Partner'::text);

-- ── WRITES: the first lock, which is the API's alone ──────────────────────────────────────────────────────────
REVOKE ALL ON public.client_year_locks FROM PUBLIC, anon;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.client_year_locks FROM authenticated;
GRANT SELECT ON public.client_year_locks TO authenticated;

DO $$
DECLARE
    r text;
    verb text;
BEGIN
    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege(r, 'public.client_year_locks', verb) THEN
                RAISE EXCEPTION 'migration 532: % still holds % on client_year_locks', r, verb;
            END IF;
        END LOOP;
        IF has_any_column_privilege(r, 'public.client_year_locks', 'INSERT')
           OR has_any_column_privilege(r, 'public.client_year_locks', 'UPDATE') THEN
            RAISE EXCEPTION 'migration 532: % still holds a column-level write privilege on client_year_locks', r;
        END IF;
    END LOOP;
    IF has_table_privilege('anon', 'public.client_year_locks', 'SELECT') THEN
        RAISE EXCEPTION 'migration 532: anon still reads client_year_locks';
    END IF;
    IF NOT has_table_privilege('authenticated', 'public.client_year_locks', 'SELECT') THEN
        RAISE EXCEPTION 'migration 532: a signed-in session no longer reads client_year_locks, and the period checks read it as the caller';
    END IF;
    IF NOT has_table_privilege('service_role', 'public.client_year_locks', 'INSERT') THEN
        RAISE EXCEPTION 'migration 532: the API (service_role) cannot write client_year_locks';
    END IF;
END $$;

-- ── What the apply log should say about the old half-way failure ────────────────────────────────────────────────
-- Before this migration a finalise could leave an engagement that reads locked with no lock row (the insert was refused after
-- the status was written). Production holds no year-end engagement, so the expected count is 0; the apply log states it
-- rather than leaving the premise unchecked. Nothing is changed here: the recovery is a reopen with a reason and a second final
-- approval (POST-A-315).
DO $$
DECLARE
    n bigint;
BEGIN
    IF to_regclass('public.year_end_engagements') IS NOT NULL THEN
        SELECT count(*) INTO n
          FROM public.year_end_engagements e
         WHERE e.status = 'locked'
           AND NOT EXISTS (SELECT 1 FROM public.client_year_locks l
                            WHERE l.firm_id = e.firm_id AND l.client_id = e.client_id AND l.financial_year = e.financial_year);
        RAISE WARNING 'migration 532: % year-end engagement(s) read locked with no lock row for their client and year (a finalise that failed half way); expected 0', n;
    END IF;
END $$;
