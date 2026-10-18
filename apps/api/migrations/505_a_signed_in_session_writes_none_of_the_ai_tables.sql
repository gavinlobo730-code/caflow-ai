-- Migration 505: a signed-in session writes none of the AI tables.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ledger POST-A-250, found by the independent review of POST-A-047)
-- ═══════════════════════════════════════════════════════════════════════════
-- `ai_conversations`, `ai_messages`, `ai_summaries`, `ai_recommendations` and `ai_feedback` (and `ai_actions`, which has had
-- no writer since 1 October 2026, and `ai_context_windows`, which nothing reads or writes) were granted INSERT, UPDATE and
-- DELETE to `authenticated` by migration 095, and `ai_recommendations` again by 287, with a firm-isolation row policy as the
-- only control. No file in `apps/web` reads or writes any of them (the copilot page goes through the API), so nothing needs
-- the privilege. What it allowed:
--
--   * any signed-in member of a firm, whatever the role, could write another member's conversation, or plant an
--     `assistant`-role message in it;
--   * `AICopilotService._build_messages` replays the last eight stored turns of a conversation into the next prompt as if
--     the model had said them, so a planted turn is an instruction the next answer follows, in the voice of the model.
--     That is the way into the model that migration-level control exists to close, and the API's own check does not
--     reach it because the write never touches the API;
--   * the summaries the executive dashboard shows (cached an hour in `ai_summaries`) could be rewritten the same way.
--
-- This is the shape of migration 499: the repository's writes were made with the caller's own session because
-- `db_provider.request_db` is that session under `USE_USER_JWT`, which is the production default. The same commit moves
-- every write in `repositories/ai_copilot_repository.py` onto the privileged client (`db_provider.service_db`), names the
-- firm on every one of them, and looks a conversation up by its OWNER as well as its firm and id, which is why the grant can
-- go now and could not before.
--
-- PRODUCTION, read from its catalogue on 17-10-2026: `authenticated` holds INSERT, UPDATE and DELETE on the five, and
-- TRUNCATE (a default privilege of the hosting platform, not a migration's grant; `anon` holds it too). PostgREST does not
-- expose TRUNCATE, so it was not reachable from a browser; it is revoked anyway so none of the four write verbs is left.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- REVOKE INSERT, UPDATE, DELETE and TRUNCATE from `authenticated`, `anon` and PUBLIC on the seven tables below (PUBLIC is
-- named so that a privilege reaching a signed-in role through it cannot survive; none is known to exist). Reading is
-- untouched, `service_role` is untouched (so the API and the scheduler are unaffected), and the row-security policies stay
-- as the second lock: a later migration that grants a list of tables again (095 did) would undo a revoke and would not undo a
-- policy.
--
-- WHAT A SIGNED-IN SESSION NOW SEES
--   A write to one of the seven is a "permission denied for table" error (SQLSTATE 42501) instead of a row-security refusal or
--   a success. A read is as before. `increment_message_count` (migration 156, wrapped by 486) is a function the API now calls
--   with the privileged client; a signed-in caller can still execute it and 486's check still asks whose conversation it is.
--
-- NOT DONE HERE: `ai_insights` and `ai_memory_triggers` carry the same migration-095 grants but are written by repositories
-- that take the caller's session (the insight status route, the memory pipeline's route), so revoking them first would break
-- those routes: they are the ledger line POST-A-257. The `workflow_*` tables are the ledger line POST-A-248.

DO $$
DECLARE
    tables text[] := ARRAY[
        'ai_conversations', 'ai_messages', 'ai_summaries', 'ai_recommendations', 'ai_feedback', 'ai_actions',
        'ai_context_windows'
    ];
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;

    -- The check asks the EFFECTIVE privilege (has_table_privilege and has_any_column_privilege), which sees a privilege that
    -- reaches the role through PUBLIC, through membership of another role or at column level, none of which a look at
    -- information_schema.role_table_grants for the two role names would.
    FOREACH t IN ARRAY tables LOOP
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 505: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 505: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
    END LOOP;
END $$;
