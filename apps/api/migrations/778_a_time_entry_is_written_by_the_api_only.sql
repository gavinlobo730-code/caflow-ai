-- Migration 778: a time entry is written by the API only (ledger POST-A-546).
--
-- WHAT WAS WRONG
--   `time_entries.billed_invoice_id` says which invoice bills an hour, and the two rate columns price it. The server sets the
--   mark in a claim that takes only entries still unbilled, resolves the rate when the work is recorded, and refuses to re-price
--   or remove time an invoice has been raised from. The DATABASE asked none of that: `authenticated` held INSERT, UPDATE and
--   DELETE on the table behind a row rule that asks the firm and nothing narrower, so a hand-made request to the database's own
--   API by any member of staff could mark any entry of the firm billed (it leaves the unbilled list for good), clear the mark
--   (it can be billed twice), re-price it, or remove an entry an invoice bills.
--
-- WHAT THIS DOES
--   REVOKES INSERT, UPDATE, DELETE and TRUNCATE on `time_entries` from `authenticated`, `anon` and PUBLIC, checks the EFFECTIVE
--   privilege (table level, column level, through PUBLIC), and that `service_role` kept its writes. READING is untouched: the
--   Time screens' reads still run as the caller, behind the same row rule.
--
--   The ledger line asked for a rule on three columns (a trigger, or a column-level revoke). The whole write is taken instead:
--   nothing in the browser writes this table, so a narrower rule would have left every other column writable by hand (the
--   client, the duration, the day) and would not have covered removing a billed entry at all; and the role-by-table matrix
--   observes a table's privilege, not a column's.
--
-- DEPLOY ORDER: the API has created, changed and removed a time entry with its own client since the change merged as 40b2234d on
--   22-11-2026 (each of the three refuses to run without the firm; held over the whole server tree by
--   `tests/test_the_register_and_a_time_entry_are_reached_through_the_servers_own_client.py`). This migration follows that deploy.
--   An API still on the earlier code would be refused every timer and every time entry with a permission error until it restarts;
--   nothing is half-written.
--
-- No row changes. Reversible: 778_a_time_entry_is_written_by_the_api_only_rollback.sql.

DO $$
DECLARE
    r text;
    verb text;
BEGIN
    IF to_regclass('public.time_entries') IS NULL THEN
        RETURN;
    END IF;
    REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.time_entries FROM PUBLIC, authenticated, anon;

    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
            IF has_table_privilege(r, 'public.time_entries', verb) THEN
                RAISE EXCEPTION 'migration 778: % still holds % on time_entries', r, verb;
            END IF;
        END LOOP;
        IF has_any_column_privilege(r, 'public.time_entries', 'INSERT')
           OR has_any_column_privilege(r, 'public.time_entries', 'UPDATE') THEN
            RAISE EXCEPTION 'migration 778: % still holds a column-level write privilege on time_entries', r;
        END IF;
    END LOOP;
    IF NOT has_table_privilege('service_role', 'public.time_entries', 'INSERT')
       OR NOT has_table_privilege('service_role', 'public.time_entries', 'UPDATE')
       OR NOT has_table_privilege('service_role', 'public.time_entries', 'DELETE') THEN
        RAISE EXCEPTION 'migration 778: service_role lost its write on time_entries';
    END IF;
    IF NOT has_table_privilege('authenticated', 'public.time_entries', 'SELECT') THEN
        RAISE EXCEPTION 'migration 778: authenticated lost its read of time_entries, which the Time screens make as the caller';
    END IF;
END $$;
