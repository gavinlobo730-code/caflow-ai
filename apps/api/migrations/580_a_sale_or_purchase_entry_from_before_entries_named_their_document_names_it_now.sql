-- Migration 580: the sale and purchase ledger entries written before entries named their document name it now (POST-A-372, ACC-22).
--
-- ====================================================================================================================================
-- WHAT WAS WRONG
-- ====================================================================================================================================
-- Every posting path stamps `journal_entries.source_type` / `source_id` with the document an entry came from, and has done since
-- ACC-22. Entries written BEFORE the stamp existed carry neither. Read-only on production on 2-11-2026 and again on 4-11-2026:
-- 5,658 live entries of type Sales and 759 of type Purchase have no source_type and no source_id, and each is named by exactly one
-- sales invoice (`client_sales_invoices.journal_entry_id`) or purchase bill (`purchase_bills.journal_entry_id`) of the same firm and
-- client. `party_ledger_as_at` (migration 419) finds a customer or a vendor only through `source_id`, so for the client with the most
-- receipts the customer-wise breakdown of Trade Receivables showed Rs 19,91,50,407.00 of debits (every invoice) in the unattributed
-- row and only credits against customers: every customer read as owed nothing and over-paid, while the account's own total was right.
-- The ledger's "open the document" link fails on the same entries. A freshly seeded firm is not affected, because it posts with the
-- stamp.
--
-- ====================================================================================================================================
-- WHAT THIS DOES (three steps, in this order, and nothing else)
-- ====================================================================================================================================
--   1. A live Sales entry with no source is stamped `sales_invoice` + the invoice's id, and a live Purchase entry with no source is
--      stamped `purchase_bill` + the bill's id, ONLY WHEN exactly one document of the entry's own firm and client names it through
--      `journal_entry_id`, the entry's type matches the document's kind, and no other live entry of that type (a reversal is not
--      another entry of its original's type) already carries the document. A document legitimately has a second entry of ANOTHER type,
--      its cost-of-goods journal, so the test is on the type. A document of another firm or client that also names the entry is
--      ignored and never followed: it neither stamps the entry nor stops the one document of its own that does.
--   2. The vendor-payment entry that names its kind but not which payment (`source_type` 'purchase_payment', `source_id` null) gets
--      the payment that names it through `purchase_payments.journal_entry_id`, on the same terms. Only `source_id` changes.
--   3. Each live reversal that carries no source takes its ORIGINAL's source, which is the rule the posting kernel applies when it
--      writes a reversal (`phase2_journal_service`, task #102). It runs after steps 1 and 2 so that the reversal of an entry stamped by
--      them follows it, and repeats so that a reversal of a reversal does too.
--
-- It changes the two source columns and nothing else (no amount, account, date, narration, reference, flag or line; the row's
-- `updated_at` moves with the update, as for any update). A posted entry cannot be edited directly (migrations 058 and 266), so the
-- statements run under the same transaction-local allowance the audited edit path uses (`app.journal_edit`, set and cleared inside
-- this file, so it cannot outlive it). THE EDIT LOG IS WRITTEN HERE, BY THE STATEMENT: the row trigger (`audit_capture`) records a write
-- only when it has a signed-in or carried person, and a migration has neither, so each statement inserts one `audit_log` row per
-- entry it stamps (entity 'journal_entry', action 'update', the old and the new source, metadata naming this migration and the
-- step), in the same statement as the stamp, so an entry cannot change without its row. The rollback reads exactly those rows.
--
-- IT CHANGES A NUMBER A CA READS, FOR THE BETTER: the customer-wise and vendor-wise breakdowns of Trade Receivables and Trade
-- Payables attribute these entries to their party, and the ledger opens their document.
-- IT ALSO TOUCHES ENTRIES IN CLOSED PERIODS (a firm-locked or client-finalised year, a period whose return is filed): only the link
-- changes, no figure of any return or statement moves, and no period lock judges a link, so none is consulted.
--
-- Entries it leaves alone, and counts in the report line the runner keeps: an entry named by no document of its own firm and client, or
-- by more than one of them, or whose one document is already carried by another live entry of its type (which of the two is the
-- document's would be a guess); a reversal whose original has no source, or whose own kind differs from its original's; and every other
-- entry type with no document (manual journals, opening entries). Step 3 is wider than steps 1 and 2 on purpose: it follows the
-- posting kernel's rule for ANY stamped original, whatever its kind. On production on 4-11-2026 it reaches exactly five reversals
-- (four Purchase, one Sales), read before this file was written, because no other unstamped reversal has a stamped original.
-- It is idempotent: a second run finds nothing to change.
--
-- The rollback (580_..._rollback.sql) puts back exactly the entries this file's audit rows name, and only while they still carry
-- what this file gave them.
--
-- Nothing here transmits anything to a portal.

BEGIN;

DO $$
DECLARE
    v_sales int := 0;
    v_purchases int := 0;
    v_payments int := 0;
    v_reversals int := 0;
    v_pass int;
    v_sales_left int;
    v_purchases_left int;
    v_payments_left int;
BEGIN
    PERFORM set_config('app.journal_edit', 'on', true);

    -- ------------------------------------------------------------------------------------------------------------------------
    -- Step 1: a Sales entry the invoice names, a Purchase entry the bill names.
    -- ------------------------------------------------------------------------------------------------------------------------
    WITH owner AS (
        SELECT j.id AS entry_id, j.firm_id, 'sales_invoice'::text AS kind, min(d.id::text)::uuid AS doc_id
          FROM public.journal_entries j
          JOIN public.client_sales_invoices d
            ON d.journal_entry_id = j.id AND d.firm_id = j.firm_id AND d.client_id = j.client_id
         WHERE j.deleted_at IS NULL AND j.entry_type = 'Sales' AND j.source_type IS NULL AND j.source_id IS NULL
         GROUP BY j.id, j.firm_id
        HAVING count(DISTINCT d.id) = 1
        UNION ALL
        SELECT j.id, j.firm_id, 'purchase_bill'::text, min(d.id::text)::uuid
          FROM public.journal_entries j
          JOIN public.purchase_bills d
            ON d.journal_entry_id = j.id AND d.firm_id = j.firm_id AND d.client_id = j.client_id
         WHERE j.deleted_at IS NULL AND j.entry_type = 'Purchase' AND j.source_type IS NULL AND j.source_id IS NULL
         GROUP BY j.id, j.firm_id
        HAVING count(DISTINCT d.id) = 1
    ), fix AS (
        UPDATE public.journal_entries j
           SET source_type = o.kind, source_id = o.doc_id
          FROM owner o
         WHERE j.id = o.entry_id
           AND j.source_type IS NULL AND j.source_id IS NULL
           AND NOT EXISTS (SELECT 1
                             FROM public.journal_entries x
                            WHERE x.id <> j.id AND x.firm_id = j.firm_id AND x.client_id = j.client_id
                              AND x.deleted_at IS NULL AND x.reversal_of IS NULL AND x.entry_type = j.entry_type
                              AND x.source_type = o.kind AND x.source_id = o.doc_id)
        RETURNING j.id AS entry_id, j.firm_id, o.kind, o.doc_id
    ), logged AS (
        INSERT INTO public.audit_log (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
        SELECT f.firm_id, NULL, NULL, 'journal_entry', f.entry_id::text, 'update',
               jsonb_build_object('source_type', NULL::text, 'source_id', NULL::uuid),
               jsonb_build_object('source_type', f.kind, 'source_id', f.doc_id),
               jsonb_build_object('source', 'migration 580', 'step', 'document',
                                  'reason', 'the entry was written before entries named their document; the one ' ||
                                            CASE f.kind WHEN 'sales_invoice' THEN 'invoice' ELSE 'bill' END ||
                                            ' that names it through journal_entry_id is now its source')
          FROM fix f
        RETURNING 1
    )
    SELECT count(*) FILTER (WHERE kind = 'sales_invoice'), count(*) FILTER (WHERE kind = 'purchase_bill')
      INTO v_sales, v_purchases
      FROM fix;

    -- ------------------------------------------------------------------------------------------------------------------------
    -- Step 2: the vendor-payment entry that names its kind and not which payment.
    -- ------------------------------------------------------------------------------------------------------------------------
    WITH owner AS (
        SELECT j.id AS entry_id, j.firm_id, min(p.id::text)::uuid AS payment_id
          FROM public.journal_entries j
          JOIN public.purchase_payments p
            ON p.journal_entry_id = j.id AND p.firm_id = j.firm_id AND p.client_id = j.client_id
         WHERE j.deleted_at IS NULL AND j.entry_type = 'Payment' AND j.source_type = 'purchase_payment' AND j.source_id IS NULL
         GROUP BY j.id, j.firm_id
        HAVING count(DISTINCT p.id) = 1
    ), fix AS (
        UPDATE public.journal_entries j
           SET source_id = o.payment_id
          FROM owner o
         WHERE j.id = o.entry_id
           AND j.source_type = 'purchase_payment' AND j.source_id IS NULL
           AND NOT EXISTS (SELECT 1
                             FROM public.journal_entries x
                            WHERE x.id <> j.id AND x.firm_id = j.firm_id AND x.client_id = j.client_id
                              AND x.deleted_at IS NULL AND x.reversal_of IS NULL AND x.entry_type = j.entry_type
                              AND x.source_type = 'purchase_payment' AND x.source_id = o.payment_id)
        RETURNING j.id AS entry_id, j.firm_id, o.payment_id
    ), logged AS (
        INSERT INTO public.audit_log (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
        SELECT f.firm_id, NULL, NULL, 'journal_entry', f.entry_id::text, 'update',
               jsonb_build_object('source_type', 'purchase_payment'::text, 'source_id', NULL::uuid),
               jsonb_build_object('source_type', 'purchase_payment'::text, 'source_id', f.payment_id),
               jsonb_build_object('source', 'migration 580', 'step', 'payment',
                                  'reason', 'the entry named its kind and not which payment; the one payment that names it through ' ||
                                            'journal_entry_id is now its source')
          FROM fix f
        RETURNING 1
    )
    SELECT count(*) INTO v_payments FROM fix;

    -- ------------------------------------------------------------------------------------------------------------------------
    -- Step 3: a live reversal with no source takes its original's. Repeats until a pass finds none, so a reversal of a reversal
    -- follows the one it reverses; each pass strictly shrinks the set it reads (a stamped row is never selected again), so it ends.
    -- ------------------------------------------------------------------------------------------------------------------------
    LOOP
        WITH target AS (
            SELECT r.id AS entry_id, r.firm_id, r.source_type AS old_type, o.source_type AS new_type, o.source_id AS new_id
              FROM public.journal_entries r
              JOIN public.journal_entries o
                ON o.id = r.reversal_of AND o.firm_id = r.firm_id AND o.client_id = r.client_id
             WHERE r.deleted_at IS NULL AND r.source_id IS NULL
               AND o.source_type IS NOT NULL AND o.source_id IS NOT NULL
               AND (r.source_type IS NULL OR r.source_type = o.source_type)
        ), fix AS (
            UPDATE public.journal_entries j
               SET source_type = t.new_type, source_id = t.new_id
              FROM target t
             WHERE j.id = t.entry_id AND j.source_id IS NULL
            RETURNING j.id AS entry_id, t.firm_id, t.old_type, t.new_type, t.new_id
        ), logged AS (
            INSERT INTO public.audit_log (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
            SELECT f.firm_id, NULL, NULL, 'journal_entry', f.entry_id::text, 'update',
                   jsonb_build_object('source_type', f.old_type, 'source_id', NULL::uuid),
                   jsonb_build_object('source_type', f.new_type, 'source_id', f.new_id),
                   jsonb_build_object('source', 'migration 580', 'step', 'reversal',
                                      'reason', 'a reversal carries its original''s source, as the posting kernel writes it')
              FROM fix f
            RETURNING 1
        )
        SELECT count(*) INTO v_pass FROM fix;
        EXIT WHEN v_pass = 0;
        v_reversals := v_reversals + v_pass;
    END LOOP;

    PERFORM set_config('app.journal_edit', '', true);

    SELECT count(*) INTO v_sales_left
      FROM public.journal_entries j
     WHERE j.deleted_at IS NULL AND j.entry_type = 'Sales' AND j.source_type IS NULL AND j.source_id IS NULL;
    SELECT count(*) INTO v_purchases_left
      FROM public.journal_entries j
     WHERE j.deleted_at IS NULL AND j.entry_type = 'Purchase' AND j.source_type IS NULL AND j.source_id IS NULL;
    SELECT count(*) INTO v_payments_left
      FROM public.journal_entries j
     WHERE j.deleted_at IS NULL AND j.source_type = 'purchase_payment' AND j.source_id IS NULL;

    RAISE WARNING 'migration 580: % sale, % purchase and % vendor-payment ledger entr(ies) now name their document and % reversal(s) now carry their original''s source; % sale, % purchase and % vendor-payment entr(ies) still name none (named by no document, by more than one, by a document of another firm or client, or already carried by another entry of their type: left as they are)',
        v_sales, v_purchases, v_payments, v_reversals, v_sales_left, v_purchases_left, v_payments_left;
END $$;

COMMIT;
