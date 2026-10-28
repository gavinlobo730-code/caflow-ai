-- Migration 558: a signed-in session writes none of the seven tables a document's settlement is derived from (ledger POST-A-336).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 544 seals the six document headers' settlement columns (paid, credited, debited and their status) against a signed-in
-- session. The figure those columns hold is DERIVED from other rows, and a decision made on a bill's payment does not read the
-- header: `services/msme_43bh_service` decides whether a bill was paid within fifteen days from `purchase_payments` and
-- `purchase_payment_allocations`. The receipt, the vendor payment and the three note-allocation tables were written by the API
-- with the CALLER'S OWN session, and `authenticated` still holds INSERT, UPDATE and DELETE on all seven (read from production on
-- 28-10-2026):
--
--     receipts, receipt_allocations, purchase_payments, purchase_payment_allocations,
--     debit_note_allocations, sales_debit_note_allocations, purchase_credit_note_allocations
--
-- (`credit_note_allocations` was closed by migration 513.) A Manager who holds the accounting tier could therefore insert a
-- payment dated inside the fifteen days and an allocation for a vendor bill over PostgREST and change the section 43B(h)
-- disallowance although the bill's own header cannot be touched, or move a receipt's allocation from one invoice to another
-- without the invoice's paid figure moving.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- The API writes all seven with the privileged client, after its own checks, naming the firm and the client on every statement
-- (the change that ships with this migration; `tests/test_a_write_of_a_table_the_signed_in_role_cannot_write_is_made_on_a_client_that_can.py`
-- holds it over the whole source). This migration then REVOKES INSERT, UPDATE, DELETE and TRUNCATE on the seven from `authenticated`,
-- `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column level, through PUBLIC). Reading is untouched, `service_role`
-- is untouched, and the row policies stay as the second lock. The browser never writes any of them: `AllocateReceiptModal` and
-- `AllocatePaymentModal` only read the allocations and save through `PUT /api/receipts/{id}/allocations` and its vendor twin.
--
-- NOT DONE HERE: the six document headers and their lines (POST-A-335 part 2) stay writable by a member who holds the tier; that
-- needs the invoice, bill and note routes moved first and is its own change.
--
-- DEPLOY ORDER: the new API works either side of this migration (a privileged write is a superset of the caller's). For the minutes
-- the OLD API still runs against the revoked grants, recording a receipt or a vendor payment, re-allocating one, reversing one and
-- issuing a debit note, sales debit note or purchase credit note against a bill or invoice fail with a permission error. The
-- settlement of a receipt is made inside `settle_receipt_atomic`, which is SECURITY DEFINER and unaffected. Nothing is half-written:
-- each of those is rolled back by its caller.
--
-- Idempotent. Reversible: 558_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    tables text[] := ARRAY[
        'receipts', 'receipt_allocations', 'purchase_payments', 'purchase_payment_allocations',
        'debit_note_allocations', 'sales_debit_note_allocations', 'purchase_credit_note_allocations'
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
                    RAISE EXCEPTION 'migration 558: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 558: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE') THEN
            RAISE EXCEPTION 'migration 558: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
