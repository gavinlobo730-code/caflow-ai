-- Migration 682: correcting or deleting a posted manual journal is the server's call alone (follow-up to POST-A-456, migration 681).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Migration 681 let a firm have a Partner approve every manual journal, and the API holds a correction and a delete of an entry on the books
-- to that rule (`services/journal_approval_rule.assert_may_change_posted`). The two database functions that do the work,
-- `public.edit_posted_journal` (rewrites a manual entry's lines) and `public.discard_posted_journal` (soft-deletes one), are the guarded
-- wrappers of migration 486, and 486 granted EXECUTE on both to `authenticated`. The wrappers ask whether the caller may write the books for
-- that client (`accounting` `write`, a Manager), not the firm's switch, which lives in the API. So with the switch on, a Manager the API
-- refuses could rewrite or delete an entry a Partner had approved with a hand-made PostgREST call to either function.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- Revokes EXECUTE on both wrappers from PUBLIC, anon and authenticated, so only the service role (the API's privileged client) runs them.
-- The API already calls both through `db_provider.service_db_or_none` (`routers/accounting.py` `_prod_db`, which `update_journal_entry`
-- hands to `manual_journal_service.update` and `discard_journal_entry` calls itself), after the route has asked the posting rule; nothing in
-- the browser calls either. With no signed-in caller the wrappers' `assert_caller_acts_for` and `assert_caller_is_actor` do not ask who is
-- calling, which is the shape migration 546 gave `post_journal_atomic`. The functions' bodies are untouched.
--
-- DEPLOY ORDER: the API that calls them as the service role is already live, so this is safe to apply at any time. Idempotent. Reversible:
-- the rollback grants EXECUTE back to `authenticated` as 486 did.

REVOKE ALL ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean) TO service_role;

DO $check$
DECLARE
    f regprocedure;
BEGIN
    FOREACH f IN ARRAY ARRAY['public.edit_posted_journal(uuid, uuid, uuid, jsonb, text, text, date, uuid)'::regprocedure,
                             'public.discard_posted_journal(uuid, uuid, uuid, uuid, boolean)'::regprocedure] LOOP
        IF has_function_privilege('authenticated', f, 'EXECUTE') OR has_function_privilege('anon', f, 'EXECUTE') THEN
            RAISE EXCEPTION 'migration 682: a signed-in or anonymous caller can still execute %', f;
        END IF;
        IF NOT has_function_privilege('service_role', f, 'EXECUTE') THEN
            RAISE EXCEPTION 'migration 682: the service role cannot execute %', f;
        END IF;
    END LOOP;
END
$check$;
