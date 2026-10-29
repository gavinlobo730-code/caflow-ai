-- Migration 563: a signed-in session writes none of the six document headers or their six lines tables (ledger POST-A-335, part 2, step 2).
--
-- ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
-- Migration 541 froze the particulars of an ISSUED invoice, bill or note and 544 sealed the settlement columns of all six headers
-- against a signed-in session. A DRAFT's particulars were the part left: its customer, dates, place of supply, flags and its lines.
-- A member who holds the accounting tier could change them over PostgREST with their own token, skipping every check the API makes
-- before it writes, and a draft is the thing the issue routes then post to the ledger. `authenticated` still holds INSERT, UPDATE,
-- DELETE and TRUNCATE on all twelve (read from production on 29-10-2026):
--
--     client_sales_invoices, client_sales_invoice_lines, purchase_bills, purchase_bill_lines, credit_notes, credit_note_lines,
--     debit_notes, debit_note_lines, purchase_credit_notes, purchase_credit_note_lines, sales_debit_notes, sales_debit_note_lines
--
-- ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
-- Step 1 of POST-A-335 part 2 (the pull request that merged on 29-10-2026, no migration) moved every writer of the twelve tables to the
-- API's privileged client, naming the document, the firm and the client on each statement, and
-- `tests/test_a_write_of_a_table_the_signed_in_role_cannot_write_is_made_on_a_client_that_can.py` holds that over the whole source.
-- This migration then REVOKES INSERT, UPDATE, DELETE and TRUNCATE on the twelve from `authenticated`, `anon` and PUBLIC and checks the
-- EFFECTIVE privilege (table level, column level, through PUBLIC). Reading is untouched, `service_role` is untouched, and the row
-- policies and the particulars triggers (539, 541, 544) stay as the second lock. The four note kinds are numbered and created through
-- `numbered_document_atomic`, which is SECURITY DEFINER and unaffected. `replace_draft_document_lines` (migration 560) is SECURITY
-- INVOKER on purpose, so a signed-in session that calls it by hand loses it with the verbs (its `SELECT ... FOR UPDATE` of the header
-- needs UPDATE); the API calls it with the privileged client, which keeps them. The browser never writes any of the twelve: the
-- document screens save through the API.
--
-- DEPLOY ORDER: step 1 reached production at least an hour before this migration applies (it applies on the first push to main after
-- the merge, about 80 minutes later). For the minutes the OLD API ran against the revoked grants every write above would have failed
-- with a permission error; that window is closed by the order, not by this file.
--
-- Idempotent. Reversible: 563_..._rollback.sql gives `authenticated` back the verbs production held.

DO $$
DECLARE
    tables text[] := ARRAY[
        'client_sales_invoices', 'client_sales_invoice_lines', 'purchase_bills', 'purchase_bill_lines',
        'credit_notes', 'credit_note_lines', 'debit_notes', 'debit_note_lines',
        'purchase_credit_notes', 'purchase_credit_note_lines', 'sales_debit_notes', 'sales_debit_note_lines'
    ];
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;

    FOREACH t IN ARRAY tables LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 563: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 563: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 563: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
