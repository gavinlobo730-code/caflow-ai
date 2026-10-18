-- Migration 512: a signed-in session reads four AI tables no more, and the client activity feed is append-only.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- PART 1 — THE FOUR AI TABLES NOBODY SIGNED IN READS (ledger POST-A-260, found while closing POST-A-258)
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 505 took the WRITE verbs away from `authenticated` on the seven `ai_*` conversation-and-copilot tables and 510 made
-- a conversation readable by its owner alone. Five tables were left whose READ policy nobody had read: `ai_context_windows`,
-- `ai_summaries`, `ai_recommendations`, `ai_feedback` and `ai_actions`. Read from production on 18-10-2026, each carries one
-- permissive firm-isolation policy `FOR ALL TO public USING (firm_id = get_my_firm_id())` and nothing else, except
-- `ai_recommendations`, which also carries a RESTRICTIVE assignment-scope policy (`can_access_client(client_id)`), so a member
-- reads only the recommendations of the clients they are assigned to. `authenticated` held SELECT on all five.
--
-- WHAT THAT EXPOSED, AND WHY IT IS NOT THE SAME FOR EACH
--   * `ai_summaries` caches the executive dashboard and the compliance summary for an hour, keyed by the scope of the person
--     who asked: a Partner's (firm-wide) answer is stored with no scope and a scoped member's with a digest of their client
--     set. A member reading the table over PostgREST with their own sign-in read the Partner's row, which names every client
--     (`churn_signals`) and carries the practice's own revenue figure, a figure the product withholds from everyone but a
--     Partner everywhere else (guardrail G1). The cache key keeps the API from SERVING one scope's answer to another; it never
--     applied to a direct read of the table. A digest cannot be judged in a row policy (that would be a second copy of the
--     scope rule in SQL), so the table cannot be narrowed by a policy. It can be closed: nothing in `apps/web` reads it, and
--     the one reader is `AICopilotRepository.get_summary`, which now reads with the privileged client and still names the firm
--     (the same change, as migration 499 and 505 did for the writes).
--   * `ai_context_windows` is the data injected into a conversation, which is the conversation's content in another shape, and
--     nothing reads or writes it. `ai_feedback` holds a member's rating and free-text note on a reply, and nothing reads it.
--     `ai_actions` has had no writer since 1 October 2026 and nothing reads it. None of the three has a reader to protect, so
--     none gets a policy: the privilege goes.
--   * `ai_recommendations` is DELIBERATELY LEFT READABLE. The API reads it with the caller's own session and the restrictive
--     assignment-scope policy is what narrows it to the caller's clients; a recommendation with no client is firm-level on
--     purpose. Its writes went in 505.
--
-- WHAT THIS DOES
--   REVOKE ALL (SELECT, REFERENCES and TRIGGER, which 505 left, as well as the verbs it took) on the four from `authenticated`,
--   `anon` and PUBLIC. `service_role` is untouched, so the API and the scheduler are unaffected, and the row-security
--   policies stay as the second lock. The closing check asks the EFFECTIVE privilege, so one reaching a role through PUBLIC, a
--   membership or a column grant is seen.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- PART 2 — THE ACTIVITY FEED IS APPEND-ONLY IN THE DATABASE, NOT BY CONVENTION (ledger POST-A-016)
-- ═══════════════════════════════════════════════════════════════════════════
-- `client_timeline_events` was created as "the append-only" client activity record (migration 045). Nothing in the database
-- refused a change to it: migration 494 (14-10-2026) took the table-level UPDATE grant from `authenticated` and gave back
-- `is_pinned` alone, but `service_role` can still rewrite or delete any event and so can anyone holding the owner's
-- connection. The audit log is a separate append-only table; this is the feed a client's activity page reads, and the
-- principle that every action is a timeline event is only as good as the events staying as they were written.
--
-- WHAT THIS DOES
--   A BEFORE UPDATE OR DELETE row trigger, `client_timeline_events_append_only`:
--     * DELETE is refused;
--     * an UPDATE may change `is_pinned` (the pin button), `updated_at`, and a one-way SOFT DELETE: `deleted_at` (and
--       `deleted_by`) going from NULL to a value. Nothing else may change, and a hidden event cannot be un-hidden or re-dated.
--       The comparison is on the whole row as JSON with those four columns removed, so a column added to the table later is
--       protected without anyone remembering to add it here;
--     * the TABLE'S OWNER, the role migrations run as, may do anything: a back-fill such as migration 437's
--       (`financial_year`) is a maintenance migration, runs as the owner, and is not blocked. `service_role` and
--       `authenticated` are not members of the owner role. The function runs as its INVOKER on purpose: a SECURITY DEFINER
--       function would see the owner as `current_user` and let every caller through.
--   `platform_purge_firm` (the operator's erase-a-firm function) sets `session_replication_role = replica` before it deletes,
--   which skips ordinary triggers, so removing a whole firm still works and nothing else gets that road.
--   TRUNCATE is revoked from `authenticated`, `anon` and PUBLIC (a default privilege of the hosting platform that PostgREST
--   does not expose; revoked so none of the destructive verbs is left).
--
-- NOT DONE HERE
--   The browser still INSERTS events and names the actor itself (`lib/services/timeline.ts`); moving that behind a server door
--   is the ledger line POST-A-228.
--
-- Idempotent. Reversible: 512_..._rollback.sql restores the four tables' privileges as 505 left them and drops the trigger.

DO $$
DECLARE
    tables text[] := ARRAY['ai_context_windows', 'ai_summaries', 'ai_feedback', 'ai_actions'];
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;

    FOREACH t IN ARRAY tables LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 512: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'SELECT')
               OR has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 512: % still holds a column-level privilege on %', r, t;
            END IF;
        END LOOP;
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.client_timeline_events_append_only()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_owner oid;
    v_old jsonb;
    v_new jsonb;
    -- The columns an UPDATE may change. Everything else on the row must be exactly as it was.
    v_free text[] := ARRAY['is_pinned', 'updated_at', 'deleted_at', 'deleted_by'];
BEGIN
    -- The table's owner (and a superuser) maintains the table: a back-fill is a migration, and migrations run as the owner.
    -- NOT SECURITY DEFINER, so `current_user` here is the caller and not the owner.
    SELECT relowner INTO v_owner FROM pg_class WHERE oid = TG_RELID;
    IF pg_has_role(current_user, v_owner, 'USAGE') THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'client_timeline_events is append-only: an event is never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;

    v_old := to_jsonb(OLD) - v_free;
    v_new := to_jsonb(NEW) - v_free;
    IF v_old IS DISTINCT FROM v_new THEN
        RAISE EXCEPTION 'client_timeline_events is append-only: what an event says cannot be changed'
            USING ERRCODE = 'restrict_violation';
    END IF;

    -- A hidden event stays hidden, and when it was hidden is not rewritten.
    IF OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS DISTINCT FROM OLD.deleted_at THEN
        RAISE EXCEPTION 'client_timeline_events is append-only: a hidden event cannot be restored or re-dated'
            USING ERRCODE = 'restrict_violation';
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.client_timeline_events_append_only() IS
    'POST-A-016, migration 512. Refuses a DELETE and any UPDATE other than is_pinned, updated_at and a one-way soft delete, for '
    'every role but the table''s owner. Runs as its invoker on purpose.';

DROP TRIGGER IF EXISTS client_timeline_events_append_only ON public.client_timeline_events;
CREATE TRIGGER client_timeline_events_append_only
    BEFORE UPDATE OR DELETE ON public.client_timeline_events
    FOR EACH ROW EXECUTE FUNCTION public.client_timeline_events_append_only();

REVOKE TRUNCATE ON public.client_timeline_events FROM PUBLIC, authenticated, anon;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                    WHERE tgrelid = 'public.client_timeline_events'::regclass
                      AND tgname = 'client_timeline_events_append_only' AND tgenabled = 'O') THEN
        RAISE EXCEPTION 'migration 512: the append-only trigger is missing or disabled on client_timeline_events';
    END IF;
    IF has_table_privilege('authenticated', 'public.client_timeline_events', 'TRUNCATE')
       OR has_table_privilege('anon', 'public.client_timeline_events', 'TRUNCATE') THEN
        RAISE EXCEPTION 'migration 512: a signed-in role still holds TRUNCATE on client_timeline_events';
    END IF;
END $$;
