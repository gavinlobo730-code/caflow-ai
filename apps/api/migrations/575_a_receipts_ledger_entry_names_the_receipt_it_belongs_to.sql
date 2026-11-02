-- Migration 575: a receipt's ledger entry names the receipt it belongs to (repair of the link migration 574 stops breaking; ACC-22 drill-through).
--
-- ====================================================================================================================================
-- WHAT WAS WRONG
-- ====================================================================================================================================
-- Until migration 574, the database function that records a receipt inserted the receipt WITHOUT the id the API had generated for it,
-- so the receipt got a different id from the one its journal entry carries in `source_id`. The ledger opens a document from
-- `journal_entries.source_type` / `source_id` (`?tab=receipts&doc=<source_id>`), so for a receipt it opened nothing. Read-only on
-- production on 2-11-2026: 101 of 101 entries with source_type 'receipt' named an id that is no receipt; every other source type
-- resolved. `receipts.journal_entry_id` is the one link that was always right (reversal reads it).
--
-- ====================================================================================================================================
-- WHAT THIS DOES
-- ====================================================================================================================================
-- Points each such entry (and a reversal of it, which carries its original's source) at the receipt that owns the entry through
-- `receipts.journal_entry_id`, where that receipt is of the SAME firm and client as the entry (a corrupt link across tenants is never
-- followed). Only the link column changes: no amount, account, date, narration or flag (the row's `updated_at` moves with it, as for any
-- update). A posted entry cannot be edited
-- directly (migration 058 / 266), so the statement runs under the same transaction-local allowance the audited edit path uses
-- (`app.journal_edit`, set and cleared inside this file). THE EDIT LOG IS WRITTEN HERE, BY THE STATEMENT: the row-level trigger
-- (`audit_capture`) records only a write that has a signed-in or carried person, and a migration has neither, so this file inserts one
-- `audit_log` row per repaired entry itself (entity 'journal_entry', action 'update', the old and the new source_id, metadata naming this
-- migration), in the same statement as the repair, so an entry cannot change without its row.
--
-- IT CHANGES A NUMBER A CA READS, FOR THE BETTER. The per-customer breakdown of a control account (`party_ledger_as_at`, migration 419)
-- attributes a receipt entry to its customer through `receipts WHERE id = source_id`. With the dangling ids, every receipt's credit fell
-- into the "unattributed receipt" row, so the customer-wise Trade Receivables breakdown did not net the receipts against the customers
-- who paid them (the account's total was always right). After this file each receipt's credit is attributed to its customer.
-- IT ALSO TOUCHES ENTRIES IN CLOSED PERIODS (a firm-locked or client-finalised year, a period whose return is filed): only the link
-- changes and no figure of any return or statement moves, so the period locks (which judge a document's date and amounts) are not
-- consulted, and the audit rows say so.
--
-- It changes an entry only when ALL of these hold, and counts the rest in the report line the runner keeps:
--   * its source_type is 'receipt' and its stored source_id names NO receipt (a source_id that names a real receipt is never moved);
--   * exactly one receipt of the entry's own firm and client is tied to it through journal_entry_id (or to the entry it reverses): an
--     entry tied to two receipts, to a receipt of another firm or client, or to none, is left alone, because which receipt it belongs
--     to would be a guess.
-- It is idempotent: a second run finds nothing to change.
--
-- The rollback (575_..._rollback.sql) is a no-op that says so: the previous ids were ids no row carries, so there is nothing to put back.
--
-- Nothing here transmits anything to a portal.

BEGIN;

DO $$
DECLARE
    v_fixed int;
    v_left int;
BEGIN
    PERFORM set_config('app.journal_edit', 'on', true);

    WITH owner AS (
        -- the receipt each receipt-sourced entry belongs to, only where there is exactly one
        SELECT j.id AS entry_id, j.firm_id, j.source_id AS old_source_id, min(r.id::text)::uuid AS receipt_id
          FROM public.journal_entries j
          JOIN public.receipts r ON r.journal_entry_id IN (j.id, j.reversal_of)
                               AND r.firm_id = j.firm_id AND r.client_id = j.client_id
         WHERE j.source_type = 'receipt'
         GROUP BY j.id, j.firm_id, j.source_id
        HAVING count(DISTINCT r.id) = 1
    ), fix AS (
        UPDATE public.journal_entries j
           SET source_id = o.receipt_id
          FROM owner o
         WHERE j.id = o.entry_id
           AND j.source_id IS DISTINCT FROM o.receipt_id
           AND NOT EXISTS (SELECT 1 FROM public.receipts x WHERE x.id = j.source_id)
        RETURNING j.id AS entry_id, o.firm_id, o.old_source_id, o.receipt_id
    ), logged AS (
        INSERT INTO public.audit_log (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
        SELECT f.firm_id, NULL, NULL, 'journal_entry', f.entry_id::text, 'update',
               jsonb_build_object('source_id', f.old_source_id), jsonb_build_object('source_id', f.receipt_id),
               jsonb_build_object('source', 'migration 575',
                                  'reason', 'the receipt was stored under another id than the one its ledger entry carried (migration 574)')
          FROM fix f
        RETURNING 1
    )
    SELECT count(*) INTO v_fixed FROM fix;

    PERFORM set_config('app.journal_edit', '', true);

    SELECT count(*) INTO v_left
      FROM public.journal_entries j
     WHERE j.source_type = 'receipt'
       AND NOT EXISTS (SELECT 1 FROM public.receipts x WHERE x.id = j.source_id);

    RAISE WARNING 'migration 575: % receipt ledger entr(ies) now name their receipt; % receipt entr(ies) still name no receipt (tied to no receipt, to more than one, or to one of another firm or client: left as they are)',
        v_fixed, v_left;
END $$;

COMMIT;
