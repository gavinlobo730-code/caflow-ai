-- Migration 251: restore immutability of POSTED journal LINES, and give a
-- ledger-repair migration a supported way to keep the reporting passbook honest.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- Posted journal ENTRIES are protected: trg_journal_immutability (BEFORE
-- UPDATE) and trg_journal_immutability_delete (BEFORE DELETE) are on
-- journal_entries in production, and migration 213 narrowed the UPDATE carve-out
-- to a single is_reversed FALSE->TRUE flip that changes no amount, account or
-- date.
--
-- Posted journal LINES were NOT protected at all. Migration 055
-- (055_v131_hardening.sql) was written to add
-- prevent_posted_journal_line_modification() plus a BEFORE UPDATE OR DELETE
-- trigger on journal_lines — but that file was never applied to this database.
-- The migration ledger records a *different* file under the number 055
-- ("055_journal_reversal_of_column"), so the number was consumed and the
-- hardening silently never ran. Verified against the live catalog: the function
-- does not exist, and journal_lines carries only two triggers, both INSERT-only
-- (trg_apb_on_line_insert, trg_archived_account_check).
--
-- Consequences, all live until this migration:
--
--   1. Any statement could rewrite or delete a line of a posted entry with no
--      error. That is how migration 248 was able to reduce a Trade Receivables
--      debit and DELETE the contra Round Off line on entries that were already
--      posted — no trigger stood in its way, and none of the usual
--      "create a reversal instead" protection applied.
--
--   2. Nothing enforced that a posted entry still BALANCES afterwards. Deleting
--      one leg of a two-leg entry leaves Dr <> Cr in the permanent ledger.
--
--   3. Migration 228's stated invariant was false. Its header reasons: "A posted
--      journal entry is IMMUTABLE (migrations 055 / 058 block any UPDATE or
--      DELETE of a posted entry or its lines) ... So a bucket's value can only
--      ever change when an entry BECOMES posted — never afterwards." The
--      account_period_balances triggers are additive-only BECAUSE of that
--      premise. With 055 missing, the premise did not hold, and the passbook
--      drifted exactly as migration 249 had to repair by hand.
--
-- So this is one root cause, not three symptoms. Restoring the line trigger
-- closes it.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THIS IS SAFE TO TURN ON NOW
-- ═══════════════════════════════════════════════════════════════════════════
-- No application code path updates or deletes a journal line. Every reference
-- in apps/api reads or inserts; there is no .update()/.delete() against
-- journal_lines anywhere, and no SQL function does it either. The only
-- statements in the repository that ever mutated a posted line are migration
-- 248's two repair statements. Turning the guard on therefore breaks nothing
-- that exists — it only forecloses the class of accident that already cost us
-- one wrong Profit & Loss.
--
-- journal_lines_journal_entry_id_fkey has NO ON DELETE CASCADE, so deleting an
-- entry never implicitly deletes lines; a draft's lines are removed explicitly
-- (and stay allowed, because the parent is not posted).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- A BUG IN 055 THAT IS NOT REPRODUCED HERE
-- ═══════════════════════════════════════════════════════════════════════════
-- 055's function ends with `RETURN NEW;` on every path. In a BEFORE DELETE row
-- trigger NEW is NULL, and returning NULL SILENTLY CANCELS the delete. Had 055
-- ever been applied, deleting a DRAFT entry's lines would have quietly done
-- nothing — no error, no row removed. The function below returns OLD for DELETE
-- and NEW for UPDATE, so a permitted delete actually happens.

BEGIN;

-- ── 1. The guard ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.prevent_posted_journal_line_modification()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_is_posted BOOLEAN;
BEGIN
    SELECT is_posted INTO v_is_posted
      FROM public.journal_entries
     WHERE id = OLD.journal_entry_id;

    -- v_is_posted IS NULL means the parent is gone (an orphan line). Deleting
    -- such a row is cleanup, not a ledger edit, so it is allowed. `IS TRUE`
    -- rather than `= TRUE` keeps that explicit instead of relying on NULL
    -- comparison semantics.
    IF v_is_posted IS TRUE THEN
        RAISE EXCEPTION
            'Cannot modify or delete lines of a posted journal entry '
            '(journal_entry_id: %). Create a reversal entry instead.',
            OLD.journal_entry_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;

    -- BEFORE DELETE must return OLD; returning NEW (NULL) would cancel the
    -- delete silently. See the note above about migration 055.
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_posted_journal_line_update ON public.journal_lines;
CREATE TRIGGER trg_prevent_posted_journal_line_update
    BEFORE UPDATE OR DELETE ON public.journal_lines
    FOR EACH ROW
    EXECUTE FUNCTION public.prevent_posted_journal_line_modification();

-- ── 2. Supported repair tools for the passbook ──────────────────────────────
--
-- With the guard on, the ONLY way to legitimately change a posted ledger is a
-- migration that deliberately disables it — a rare, reviewable act. Such a
-- migration must also repair account_period_balances, because the maintenance
-- triggers are additive-only and will not notice.
--
-- Migration 249 had to hand-roll ~100 lines of delete-then-insert to do that
-- once. These functions make it two calls, so the next repair has no excuse to
-- skip it. They mirror services/balance_cache_service.recompute_client and
-- domain/reporting/balance_cache.build_buckets exactly: for every posted,
-- non-deleted line, fold debit/credit into the (account, month-of-entry_date)
-- bucket, delete-then-insert so a bucket that should no longer exist cannot
-- linger.

CREATE OR REPLACE FUNCTION public.apb_rebuild_client(p_firm uuid, p_client uuid)
RETURNS void
LANGUAGE sql
SET search_path = public, pg_catalog
AS $$
    DELETE FROM public.account_period_balances
     WHERE firm_id = p_firm AND client_id = p_client;

    INSERT INTO public.account_period_balances
        (firm_id, client_id, account_id, period_month, debit_paise, credit_paise, updated_at)
    SELECT je.firm_id, je.client_id, jl.account_id,
           date_trunc('month', je.entry_date)::date,
           sum(COALESCE(jl.debit_paise, 0))::bigint,
           sum(COALESCE(jl.credit_paise, 0))::bigint,
           now()
      FROM public.journal_lines jl
      JOIN public.journal_entries je ON je.id = jl.journal_entry_id
     WHERE je.firm_id = p_firm AND je.client_id = p_client
       AND je.is_posted = true AND je.deleted_at IS NULL
     GROUP BY je.firm_id, je.client_id, jl.account_id, date_trunc('month', je.entry_date);
$$;

-- Every (firm, client) whose cached totals disagree with the posted ledger.
-- A client with NO buckets at all has simply never been backfilled — a
-- legitimate state (the passbook falls back to full replay), not drift.
CREATE OR REPLACE FUNCTION public.apb_drifted_clients()
RETURNS TABLE (firm_id uuid, client_id uuid)
LANGUAGE sql STABLE
SET search_path = public, pg_catalog
AS $$
    WITH cache AS (
        SELECT b.firm_id, b.client_id, b.account_id,
               sum(b.debit_paise) AS c_dr, sum(b.credit_paise) AS c_cr
          FROM public.account_period_balances b
         GROUP BY 1, 2, 3
    ),
    ledger AS (
        SELECT je.firm_id, je.client_id, jl.account_id,
               sum(jl.debit_paise) AS l_dr, sum(jl.credit_paise) AS l_cr
          FROM public.journal_lines jl
          JOIN public.journal_entries je ON je.id = jl.journal_entry_id
         WHERE je.is_posted = true AND je.deleted_at IS NULL
         GROUP BY 1, 2, 3
    )
    SELECT DISTINCT
           COALESCE(cache.firm_id,   ledger.firm_id),
           COALESCE(cache.client_id, ledger.client_id)
      FROM cache
      FULL OUTER JOIN ledger
        ON  cache.firm_id    = ledger.firm_id
        AND cache.client_id  = ledger.client_id
        AND cache.account_id = ledger.account_id
     WHERE (COALESCE(c_dr, 0) - COALESCE(c_cr, 0))
        <> (COALESCE(l_dr, 0) - COALESCE(l_cr, 0))
       AND EXISTS (
           SELECT 1 FROM public.account_period_balances b
            WHERE b.firm_id   = COALESCE(cache.firm_id,   ledger.firm_id)
              AND b.client_id = COALESCE(cache.client_id, ledger.client_id)
       );
$$;

-- Rebuild every drifted client. Returns how many were rebuilt, so a caller can
-- log it. Idempotent: a second run finds nothing and rebuilds nothing.
CREATE OR REPLACE FUNCTION public.apb_rebuild_drifted()
RETURNS integer
LANGUAGE plpgsql
SET search_path = public, pg_catalog
AS $$
DECLARE r RECORD; n integer := 0;
BEGIN
    FOR r IN SELECT * FROM public.apb_drifted_clients() LOOP
        PERFORM public.apb_rebuild_client(r.firm_id, r.client_id);
        n := n + 1;
    END LOOP;
    RETURN n;
END;
$$;

-- The line a ledger-repair migration should end with. Raises rather than
-- returning a flag, so a migration cannot commit over the top of drift.
CREATE OR REPLACE FUNCTION public.apb_assert_no_drift()
RETURNS void
LANGUAGE plpgsql
SET search_path = public, pg_catalog
AS $$
DECLARE n integer;
BEGIN
    SELECT count(*) INTO n FROM public.apb_drifted_clients();
    IF n > 0 THEN
        RAISE EXCEPTION
            'account_period_balances disagrees with the posted ledger for % '
            'client(s). Call apb_rebuild_drifted() after changing posted '
            'journal data.', n;
    END IF;
END;
$$;

-- These are maintenance tools, not application surface. Only the service role
-- (and the migration runner) may call them; `authenticated` must not be able to
-- rewrite the reporting cache.
REVOKE ALL ON FUNCTION public.apb_rebuild_client(uuid, uuid)  FROM PUBLIC;
REVOKE ALL ON FUNCTION public.apb_drifted_clients()           FROM PUBLIC;
REVOKE ALL ON FUNCTION public.apb_rebuild_drifted()           FROM PUBLIC;
REVOKE ALL ON FUNCTION public.apb_assert_no_drift()           FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.apb_rebuild_client(uuid, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.apb_drifted_clients()          TO service_role;
GRANT EXECUTE ON FUNCTION public.apb_rebuild_drifted()          TO service_role;
GRANT EXECUTE ON FUNCTION public.apb_assert_no_drift()          TO service_role;

-- ── 3. Heal anything that drifted while the guard was missing ───────────────
-- 249 repaired the drift that migration 248 caused. This catches anything else
-- the open window allowed, and is a no-op when the cache is already exact
-- (as it is in production at the time of writing — verified, zero drifted
-- buckets).
DO $heal$
DECLARE n integer;
BEGIN
    n := public.apb_rebuild_drifted();
    IF n > 0 THEN
        RAISE NOTICE 'Migration 251: rebuilt the passbook for % client(s).', n;
    END IF;
END
$heal$;

-- ── Post-conditions ─────────────────────────────────────────────────────────
DO $verify$
DECLARE v_trigger int; v_entry_triggers int;
BEGIN
    SELECT count(*) INTO v_trigger
      FROM pg_trigger t
      JOIN pg_class c ON c.oid = t.tgrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relname = 'journal_lines'
       AND NOT t.tgisinternal
       AND t.tgname = 'trg_prevent_posted_journal_line_update';
    IF v_trigger <> 1 THEN
        RAISE EXCEPTION 'Migration 251 failed: the journal_lines immutability trigger is not present.';
    END IF;

    -- The entry-level guards this depends on must still be there; without them
    -- a posted entry could be deleted and its lines orphaned.
    SELECT count(*) INTO v_entry_triggers
      FROM pg_trigger t
      JOIN pg_class c ON c.oid = t.tgrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relname = 'journal_entries'
       AND NOT t.tgisinternal
       AND t.tgname IN ('trg_journal_immutability', 'trg_journal_immutability_delete');
    IF v_entry_triggers <> 2 THEN
        RAISE EXCEPTION
            'Migration 251 failed: journal_entries is missing an immutability '
            'trigger (found % of 2).', v_entry_triggers;
    END IF;

    PERFORM public.apb_assert_no_drift();
END
$verify$;

COMMIT;
