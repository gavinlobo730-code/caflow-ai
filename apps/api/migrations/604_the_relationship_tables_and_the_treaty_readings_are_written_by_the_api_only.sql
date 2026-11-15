-- Migration 604: the relationship tables and the treaty readings are written by the API only, and three tables nothing writes take no
-- signed-in write (ledger POST-A-008, the relationships tranche, part 2 of 2).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Seven tables are granted to the signed-in role behind policies that ask the firm (and the client assignment where a row names a client) and no
-- role tier. Four the API writes: `entity_roles` (a person or entity as a client's director, partner or shareholder, with the share held),
-- `properties` (a client's house property, whose cost and rent feed the house-property working), `related_party_loans` (a loan to or from a
-- related party, which the Section 185 and 186 flags read) and `dtaa_treaty_rates` (the firm's own reading of a treaty's rate for a country and
-- a nature of income, which a payment to a non-resident is withheld on). Three nothing writes at all: `entity_client_links`,
-- `auto_journal_suggestions` and `engagement_letters` (the engagement letter the product sends is a row of `engagements`; this table has no
-- reader or writer in the code). Production granted `authenticated` INSERT, UPDATE, DELETE and TRUNCATE on all seven and `anon` TRUNCATE (read
-- on 15-11-2026). The browser writes none of them, and no database function does, so a hand-made PostgREST request from a signed-in session was
-- the only user of the grant, and a Reviewer could add a director to a client or change the rate a non-resident is withheld at. Found through
-- POST-A-008's list of the tables a signed-in session reaches outside the access matrix.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers of the first four moved onto the privileged client first (part 1, held over the source by
-- `tests/test_the_relationship_and_treaty_tables_are_written_with_the_privileged_client.py`). This migration then REVOKES INSERT, UPDATE,
-- DELETE and TRUNCATE on the seven from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column level,
-- through PUBLIC) and that `service_role` kept its writes. Reading and the row policies are untouched. The shape is migration 593's.
--
-- DEPLOY ORDER: part 1 reached production first and this ships at least an hour after it, because an API instance still serving when the grant
-- goes, writing with the caller's own sign-in, would answer "permission denied" to a CA recording a director or a treaty rate.
--
-- Idempotent. Reversible: 604_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['entity_roles', 'properties', 'related_party_loans', 'dtaa_treaty_rates', 'entity_client_links',
                             'auto_journal_suggestions', 'engagement_letters'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 604: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 604: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 604: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
