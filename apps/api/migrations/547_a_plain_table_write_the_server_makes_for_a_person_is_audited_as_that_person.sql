-- Migration 547 — an ordinary table write the server makes for a person is audited as that person (POST-A-339, ahead of the change).
--
-- WHAT IS WRONG TODAY
--   The row-level edit log is written by triggers (`audit_capture`, migration 111, redacted by 336, with the carried actor of 545) that
--   record a write only when someone is signed in: `auth.uid()` for the browser's and the API's request-scoped writes, or, since 545,
--   the actor a ledger function carries. Production holds 492 bank-line creates and 789 bank-line updates written by that trigger in
--   the last 120 days against 58 written by the application, 22 + 22 client-document creates and deletes against none, and the
--   trigger's own comment says why: "service-role backend writes have a NULL auth.uid() and are audited in-app by log_event".
--   POST-A-339 takes the signed-in role's grants on the payroll, bank and document tables away, which means the API stops writing
--   them as the signed-in person and writes them with its privileged client. Without this migration every one of those writes would
--   leave the edit log: no row, no person, no before and after, and nothing to say so.
--
-- WHAT IT DOES
--   * `public.carried_audit_actor()` (migration 545's reader, the one place both trigger functions ask) gains one more place to look.
--     When no actor is carried in the transaction-local setting `app.audit_actor`, and the request is the SERVER'S own (the database
--     role the request runs as is `service_role`, which only the holder of the service key can be, and a signed-in session cannot become),
--     it reads the person from the request header `x-acting-auth-user`, which PostgREST exposes to the database as
--     `current_setting('request.headers')`. The API sets that header, on the statements it makes for a person, to the AUTH id its
--     authentication dependency verified for the request (`core/request_actor.py`; the token is not decoded a second time). A value
--     that is not a uuid, or names nobody, is no actor; a request that is not the server's own ignores the header altogether, so
--     a signed-in person can neither be replaced nor impersonated by sending it.
--   * `public.audit_actor_probe()` (read-only, SECURITY INVOKER, executable by the service role alone) says what the database saw of
--     the request that called it: the role it runs as and the value of the `x-acting-auth-user` header. The API calls it once, with
--     a label of its own, and `/health` reports whether the label arrived (`audit_actor`: carried / not_seen), so the claim that the
--     hosted API passes the header through to the database is a thing the deployment can SAY about itself and not a thing assumed.
--   * Nothing else changes. `audit_capture` and `audit_capture_journal_line` already read this function when `auth.uid()` is NULL and
--     already mark a row written for a carried person (`metadata.actor_source = 'carried'`), so the bank, document and payroll
--     tables' triggers, and every other trigger that calls it, start recording the person with no change of their own.
--
-- WHY IT SHIPS ALONE AND FIRST
--   Nothing sends the header yet, so this changes nothing the moment it applies: a request without it behaves as before. The Python
--   that sends it ships after this is applied (a write made before then would carry the header to a reader that ignores it, and be
--   unaudited as it is today), and the revokes that force every write onto the privileged client come after that.
--
-- WHAT IT DOES NOT DO
--   It does not check that the person belongs to the row's firm: the reader cannot see the row, and the header is set only by the
--   server, from the person its own authentication verified, for a request whose routes already keep that person inside their firm.
--   It does not touch a write the server makes for nobody (a job): no header, no actor, no row, as today.
--
-- Derived from migration 545, the last to define public.carried_audit_actor (found by number); the test asserts the new body is
-- 545's plus exactly the added lines. Reversible: 547_..._rollback.sql restores 545's definition.


CREATE OR REPLACE FUNCTION public.carried_audit_actor()
RETURNS uuid
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
DECLARE
    v_setting text := nullif(current_setting('app.audit_actor', true), '');
    v_header  text;
    v_actor   uuid;
BEGIN
    IF v_setting IS NULL THEN
        -- MIGRATION 547: the server's own request names the person in a header (see the migration's header). Only a request that
        -- runs as service_role is believed: the role is set by PostgREST from the verified key, never by the caller.
        IF current_setting('role', true) = 'service_role' THEN
            BEGIN
                v_header := nullif(current_setting('request.headers', true)::json ->> 'x-acting-auth-user', '');
            EXCEPTION WHEN others THEN
                v_header := NULL;
            END;
            IF v_header IS NOT NULL THEN
                BEGIN
                    v_actor := v_header::uuid;
                EXCEPTION WHEN others THEN
                    RETURN NULL;
                END;
                -- a label that names nobody is no actor
                IF NOT EXISTS (SELECT 1 FROM public.users u WHERE u.auth_user_id = v_actor) THEN
                    RETURN NULL;
                END IF;
                RETURN v_actor;
            END IF;
        END IF;
    END IF;
    IF v_setting IS NULL THEN
        RETURN NULL;
    END IF;
    BEGIN
        RETURN v_setting::uuid;
    EXCEPTION WHEN others THEN
        RETURN NULL;
    END;
END;
$fn$;

REVOKE ALL ON FUNCTION public.carried_audit_actor() FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.audit_actor_probe()
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
SET search_path = pg_catalog
AS $fn$
DECLARE
    v_header text;
BEGIN
    BEGIN
        v_header := nullif(current_setting('request.headers', true)::json ->> 'x-acting-auth-user', '');
    EXCEPTION WHEN others THEN
        v_header := NULL;
    END;
    RETURN jsonb_build_object('role', current_setting('role', true), 'header', v_header);
END;
$fn$;

REVOKE ALL ON FUNCTION public.audit_actor_probe() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.audit_actor_probe() TO service_role;

-- ── the closing check: what the migration claims is true of the database it ran on ──────────────────────────────────────────
DO $$
DECLARE
    v_src  text;
    v_def  boolean;
BEGIN
    SELECT p.prosrc, p.prosecdef INTO v_src, v_def FROM pg_proc p WHERE p.oid = 'public.carried_audit_actor()'::regprocedure;
    IF v_def THEN
        RAISE EXCEPTION 'migration 547: carried_audit_actor must be SECURITY INVOKER';
    END IF;
    IF v_src NOT LIKE '%x-acting-auth-user%' OR v_src NOT LIKE '%app.audit_actor%' OR v_src NOT LIKE '%service_role%' THEN
        RAISE EXCEPTION 'migration 547: carried_audit_actor does not read both the setting and the server header';
    END IF;
    IF has_function_privilege('anon', 'public.carried_audit_actor()', 'EXECUTE')
       OR has_function_privilege('authenticated', 'public.carried_audit_actor()', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 547: carried_audit_actor must not be executable by a signed-in role';
    END IF;
    IF has_function_privilege('anon', 'public.audit_actor_probe()', 'EXECUTE')
       OR has_function_privilege('authenticated', 'public.audit_actor_probe()', 'EXECUTE')
       OR NOT has_function_privilege('service_role', 'public.audit_actor_probe()', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 547: audit_actor_probe must be executable by the service role alone';
    END IF;
END
$$;
