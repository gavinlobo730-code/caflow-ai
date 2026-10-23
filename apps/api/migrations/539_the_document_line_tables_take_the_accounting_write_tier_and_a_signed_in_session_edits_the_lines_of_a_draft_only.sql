-- Migration 539 — the document line tables take the accounting write tier, and a signed-in session edits the lines of a draft
-- document; on any other document it may only correct a unit of measure or clear a catalogue link (POST-A-328).
--
-- WHAT WAS WRONG
--   Eight line tables carry the parent's READ scope (a policy asking the parent's firm and, through the parent, the client) and
--   nothing more: no role tier and no rule about the document's state. `authenticated` holds INSERT, UPDATE and DELETE on all of
--   them and no trigger exists on any (production read on 23-10-2026: one permissive policy each, no user trigger). So a Reviewer
--   assigned to a client, or an Executive, could change the quantity, rate, HSN or tax of a line of an ISSUED invoice, bill or
--   note over PostgREST, without touching the header or the journal: the document's PDF, and any return built from its lines,
--   moved while the ledger did not. The API is right and the database was silent: the routes that write a line ask
--   `accounting:write` (a Manager's; the billing run asks `billing:write`, a Partner's, and its header insert already needs
--   `accounting:write` since 487), a note's PATCH is draft-only (422 after issue), an invoice or bill PATCH replaces its lines
--   only while draft, and the one post-issue line edit is a `unit` correction. The parents have had their tier since migration
--   487; the lines were never named in it.
--
-- WHAT THIS DOES (one transaction)
--   * Per-command RESTRICTIVE policies on all eight line tables, `(SELECT public.my_permission('accounting', 'write', 'Manager'))`
--     for INSERT, UPDATE and DELETE (the pair every route that writes a line asks; asked once per query, the form of 525), so a
--     per-person grant or denial in the access grid counts here as it does on the header. The recurring-template lines are in the
--     tier too: their routes ask the same pair. Every CREATE POLICY is written out with its name as a literal, on purpose: the
--     production-drift guard (tests/test_guards_match_production_pg.py) finds a policy a migration adds by that text, and a name
--     built inside format() is invisible to it.
--   * One trigger function, `public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document()`
--     (63 characters or fewer, so the name Postgres stores is the name written), on the six line tables of documents that HAVE a
--     draft (client_sales_invoice_lines, purchase_bill_lines, credit_note_lines, debit_note_lines, purchase_credit_note_lines,
--     sales_debit_note_lines): a signed-in session (`current_setting('role')` is `authenticated` or `anon`, the test of
--     migration 498) may insert, update or delete a line only while its document's status is `draft`. Two exceptions, both
--     UPDATEs that change nothing else (the whole row is compared with the columns named and `updated_at` taken out, so a line
--     cannot be moved to another document under cover of either):
--       1. the correction the API itself allows on any invoice or bill that is not cancelled: a change to `unit`;
--       2. clearing `service_catalogue_id` or `purchase_order_line_id` (each stays or becomes NULL) on a line of a CANCELLED
--          document. This is what the foreign key's ON DELETE SET NULL does when a product or service preset is deleted, which
--          the product allows when every document carrying it is a draft or cancelled (routers/service_catalogue.py): the FK
--          action is an UPDATE of the line made under the deleting person's role setting, so without this exception that delete
--          failed for everybody, a Partner included. The same delete of a preset used on an issued document is refused here (it
--          was already refused by the route). The function does not ask whether the UPDATE IS that foreign-key action, so a
--          member with the tier can also clear either link directly on a cancelled document's line: that cuts a reference to a
--          catalogue item or an order line and changes no amount, and the purchase cycle already leaves cancelled bills out of
--          what an order has billed. Only the catalogue link can reach a signed-in session as a foreign-key action today (order
--          lines are deleted on the privileged client).
--     The privileged client, the database owner and the firm purge (replica mode) are not judged. A document that cannot be
--     found is not judged either: when a document's own delete cascades to its lines the document row is already gone when the
--     line is reached (the cascade runs under the deleting person's role setting, so it is the missing parent, and not the role,
--     that lets it through). The parent's status is read FOR SHARE, so a line write that races the issuing of its document waits
--     for the issue to commit and is then judged on the new status. The function reads the parent as its owner, so row security
--     cannot hide the status, and EXECUTE on it is revoked from the signed-in roles (a trigger function needs none).
--   * The policies and the triggers are created inside ONE DO block, every statement written out literally. CREATE POLICY and
--     DROP POLICY take ACCESS EXCLUSIVE on the table and CREATE TRIGGER takes SHARE ROW EXCLUSIVE, all held to the end of the
--     transaction, and the runner sends one top-level statement per round trip: a review ran this migration with that shape through
--     a proxy adding a quarter of a second to each round trip (an assumed figure, not measured from the runner) and the
--     invoice-lines table was locked for about 15 seconds, longer than the 8 seconds a signed-in request may run in production,
--     and a reader holding a lock on a later table made the apply fail on its 15 second lock timeout. Inside one block the same
--     DDL took about 3 seconds end to end and no reader waited more than half a second.
--   * A DO block fails the migration unless the 24 policies and 6 triggers exist and no signed-in role can execute the function.
--
-- WHAT IT CHECKED BEFORE ADDING THE RULE, BECAUSE IT COULD HAVE BROKEN A ROUTE
--   Every writer of the eight tables (the table-use scanner, then a read of each) is a route that asks `accounting:write`
--   (the billing run: `billing:write`, behind the same header insert), or a service reached from one, and each creates its
--   document as a DRAFT before inserting its lines (the invoice, the bill, and the four notes, whose lines are inserted by
--   `numbered_document_atomic` in the same transaction as the header). The compensating deletes (`billing_service`,
--   `recurring_invoice_service`, `recurring_purchase_bill_service`) remove the lines of a draft just made; the
--   `late_interest_service` one runs on the privileged client. The edits of a line of a non-draft document are the `unit`
--   update and the SET NULL of exception 2 above; every other foreign key that touches these tables is a CASCADE from the
--   document (judged only if the document still exists) or a SET NULL on `expense_account_id` or `service_catalogue_id` of a
--   template line (migration 379; no state rule there). The purchase order's re-pricing deletes order lines on the
--   privileged client.
--
-- THE COST OF THE RULE
--   Reading the status FOR SHARE waits for any open transaction that has updated the document's header (nothing in the code holds
--   one longer than a statement), and it makes one race possible that did not exist: an UPDATE or DELETE of a line locks the LINE
--   row before this trigger runs, while a DELETE of the header locks the header and then reaches its lines through the cascade,
--   so deleting a draft while one of its lines is being edited can deadlock (40P01). One of the two requests fails after about a
--   second and a retry works; nothing is corrupted. A review reproduced it with a loop of one deleter and four editors on one
--   document, not with anything an ordinary session does. The status read cannot be a weaker lock: only a lock that conflicts
--   with the issuing UPDATE closes the race with issuing.
--
-- WHAT IT DOES NOT DO, ON PURPOSE
--   * The recurring-template PARENTS (recurring_invoice_templates, recurring_purchase_bill_templates, recurring_journal_templates)
--     carry no tier in 487 to 489; that and the other firm-level masters are POST-A-329. A template has no draft state, so its
--     lines get the tier and no state rule.
--   * The HEADERS of the six documents carry no state rule. A member with the tier can still delete an issued document with its
--     lines, alter its frozen columns, or insert one already issued (POST-A-330), and can move an issued document back to `draft`
--     (the status and settlement columns are written by about a dozen legitimate paths under the caller's role, POST-A-331), after
--     which its lines are editable again. A review reproduced the move back as an assigned Manager and as an assigned Executive on
--     a partly paid invoice. This migration is therefore a floor under the lines, not a seal.
--   * The API replaces the lines of a draft invoice or bill as a delete and then an insert, two requests. If another member issues
--     the document between them, the insert is now refused and the issued document is left without lines; before this migration
--     the insert would have succeeded. The window is tens of milliseconds and the fix is to make the replacement one write
--     (POST-A-332).
--   * The signed-in roles keep the platform's TRUNCATE, TRIGGER, REFERENCES and MAINTAIN privileges on the eight tables (read in
--     production on 23-10-2026). PostgREST issues none of them, so this migration does not touch them.
--   * Nothing is rewritten; no row changes. Existing issued documents keep their lines as they are.
--
-- DEPLOY ORDER
--   No writer moves and no grant changes, so there is no ordering with the API deploy.

SELECT set_config('lock_timeout', '15s', true);

-- ── 1. a signed-in session edits the lines of a draft document and, on any other, only the two things above ────
CREATE OR REPLACE FUNCTION public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_role     text := COALESCE(current_setting('role', true), 'none');
  v_parent   text := TG_ARGV[0];
  v_fk       text := TG_ARGV[1];
  v_unit_ok  boolean := COALESCE(TG_ARGV[2], '') = 'unit';
  v_label    text := COALESCE(TG_ARGV[3], 'document');
  v_ids      uuid[] := ARRAY[]::uuid[];
  v_id       uuid;
  v_status   text;
BEGIN
  -- The test of migration 498: PostgREST sets the role setting for a caller, and inside a SECURITY DEFINER function it stays the
  -- caller's. The privileged client, the database owner and the firm purge (which runs with replica triggers off) pass untouched.
  IF v_role NOT IN ('authenticated', 'anon') THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;

  -- The documents this write touches (two when a line is moved), sorted so the document a refusal names is the same every time.
  SELECT COALESCE(array_agg(DISTINCT x ORDER BY x), ARRAY[]::uuid[]) INTO v_ids
    FROM unnest(ARRAY[
           CASE WHEN TG_OP <> 'INSERT' THEN (to_jsonb(OLD) ->> v_fk)::uuid END,
           CASE WHEN TG_OP <> 'DELETE' THEN (to_jsonb(NEW) ->> v_fk)::uuid END]) AS u(x)
   WHERE x IS NOT NULL;

  -- Exception 1, the one edit the API allows on a document that is not a draft: the unit of measure of a line, on any document
  -- that is not cancelled (it never touches a rate, a quantity, an amount or a tax). Nothing else on the row may change, and
  -- that includes the column that names the document: the whole row is compared with `unit` and `updated_at` taken out, so a
  -- line cannot be moved to another document under cover of a unit correction.
  IF TG_OP = 'UPDATE' AND v_unit_ok
     AND (to_jsonb(NEW) - 'unit' - 'updated_at') = (to_jsonb(OLD) - 'unit' - 'updated_at') THEN
    EXECUTE format('SELECT status FROM public.%I WHERE id = $1 FOR SHARE', v_parent) INTO v_status USING v_ids[1];
    IF v_status IS DISTINCT FROM 'cancelled' THEN
      RETURN NEW;
    END IF;
  END IF;

  -- Exception 2, the foreign-key action of deleting a catalogue item or a purchase order line: ON DELETE SET NULL updates the
  -- line under the deleting person's role setting. Allowed for exactly that shape of change (each of the two links stays or
  -- becomes NULL, nothing else on the row changes) and only on a line of a cancelled document, which is the case a preset's
  -- delete route allows; on any other document the delete is refused. The test is the shape of the change and not its cause,
  -- so a direct clearing of either link on a cancelled document's line passes too (see the header).
  IF TG_OP = 'UPDATE'
     AND (to_jsonb(NEW) - 'service_catalogue_id' - 'purchase_order_line_id' - 'updated_at')
       = (to_jsonb(OLD) - 'service_catalogue_id' - 'purchase_order_line_id' - 'updated_at')
     AND ((to_jsonb(NEW) ->> 'service_catalogue_id') IS NULL
          OR (to_jsonb(NEW) ->> 'service_catalogue_id') IS NOT DISTINCT FROM (to_jsonb(OLD) ->> 'service_catalogue_id'))
     AND ((to_jsonb(NEW) ->> 'purchase_order_line_id') IS NULL
          OR (to_jsonb(NEW) ->> 'purchase_order_line_id') IS NOT DISTINCT FROM (to_jsonb(OLD) ->> 'purchase_order_line_id')) THEN
    EXECUTE format('SELECT status FROM public.%I WHERE id = $1 FOR SHARE', v_parent) INTO v_status USING v_ids[1];
    IF v_status = 'cancelled' THEN
      RETURN NEW;
    END IF;
  END IF;

  FOREACH v_id IN ARRAY v_ids LOOP
    EXECUTE format('SELECT status FROM public.%I WHERE id = $1 FOR SHARE', v_parent) INTO v_status USING v_id;
    -- a document that cannot be found is being deleted (the cascade of its own delete), or never existed (the foreign key says so)
    IF v_status IS NOT NULL AND v_status <> 'draft' THEN
      RAISE EXCEPTION 'The lines of the % that is % cannot be changed from a signed-in session. %', v_label, v_status,
        CASE WHEN v_status = 'cancelled' THEN 'A cancelled document keeps its lines as they were.'
             ELSE 'Only a draft can be edited; correct an issued document with a credit or debit note.' END
        USING ERRCODE = '42501';
    END IF;
  END LOOP;

  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

REVOKE ALL ON FUNCTION public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document() FROM PUBLIC, anon, authenticated;

-- ── 2. the accounting write tier on all eight line tables, and the trigger on six, in one block (the locks are held to commit) ──
DO $apply$
BEGIN
  DROP POLICY IF EXISTS client_sales_invoice_lines_write_tier_insert ON public.client_sales_invoice_lines;
  CREATE POLICY client_sales_invoice_lines_write_tier_insert ON public.client_sales_invoice_lines AS RESTRICTIVE FOR INSERT TO authenticated
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS client_sales_invoice_lines_write_tier_update ON public.client_sales_invoice_lines;
  CREATE POLICY client_sales_invoice_lines_write_tier_update ON public.client_sales_invoice_lines AS RESTRICTIVE FOR UPDATE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')))
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS client_sales_invoice_lines_write_tier_delete ON public.client_sales_invoice_lines;
  CREATE POLICY client_sales_invoice_lines_write_tier_delete ON public.client_sales_invoice_lines AS RESTRICTIVE FOR DELETE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')));

  DROP POLICY IF EXISTS purchase_bill_lines_write_tier_insert ON public.purchase_bill_lines;
  CREATE POLICY purchase_bill_lines_write_tier_insert ON public.purchase_bill_lines AS RESTRICTIVE FOR INSERT TO authenticated
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS purchase_bill_lines_write_tier_update ON public.purchase_bill_lines;
  CREATE POLICY purchase_bill_lines_write_tier_update ON public.purchase_bill_lines AS RESTRICTIVE FOR UPDATE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')))
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS purchase_bill_lines_write_tier_delete ON public.purchase_bill_lines;
  CREATE POLICY purchase_bill_lines_write_tier_delete ON public.purchase_bill_lines AS RESTRICTIVE FOR DELETE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')));

  DROP POLICY IF EXISTS credit_note_lines_write_tier_insert ON public.credit_note_lines;
  CREATE POLICY credit_note_lines_write_tier_insert ON public.credit_note_lines AS RESTRICTIVE FOR INSERT TO authenticated
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS credit_note_lines_write_tier_update ON public.credit_note_lines;
  CREATE POLICY credit_note_lines_write_tier_update ON public.credit_note_lines AS RESTRICTIVE FOR UPDATE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')))
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS credit_note_lines_write_tier_delete ON public.credit_note_lines;
  CREATE POLICY credit_note_lines_write_tier_delete ON public.credit_note_lines AS RESTRICTIVE FOR DELETE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')));

  DROP POLICY IF EXISTS debit_note_lines_write_tier_insert ON public.debit_note_lines;
  CREATE POLICY debit_note_lines_write_tier_insert ON public.debit_note_lines AS RESTRICTIVE FOR INSERT TO authenticated
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS debit_note_lines_write_tier_update ON public.debit_note_lines;
  CREATE POLICY debit_note_lines_write_tier_update ON public.debit_note_lines AS RESTRICTIVE FOR UPDATE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')))
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS debit_note_lines_write_tier_delete ON public.debit_note_lines;
  CREATE POLICY debit_note_lines_write_tier_delete ON public.debit_note_lines AS RESTRICTIVE FOR DELETE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')));

  DROP POLICY IF EXISTS purchase_credit_note_lines_write_tier_insert ON public.purchase_credit_note_lines;
  CREATE POLICY purchase_credit_note_lines_write_tier_insert ON public.purchase_credit_note_lines AS RESTRICTIVE FOR INSERT TO authenticated
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS purchase_credit_note_lines_write_tier_update ON public.purchase_credit_note_lines;
  CREATE POLICY purchase_credit_note_lines_write_tier_update ON public.purchase_credit_note_lines AS RESTRICTIVE FOR UPDATE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')))
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS purchase_credit_note_lines_write_tier_delete ON public.purchase_credit_note_lines;
  CREATE POLICY purchase_credit_note_lines_write_tier_delete ON public.purchase_credit_note_lines AS RESTRICTIVE FOR DELETE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')));

  DROP POLICY IF EXISTS sales_debit_note_lines_write_tier_insert ON public.sales_debit_note_lines;
  CREATE POLICY sales_debit_note_lines_write_tier_insert ON public.sales_debit_note_lines AS RESTRICTIVE FOR INSERT TO authenticated
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS sales_debit_note_lines_write_tier_update ON public.sales_debit_note_lines;
  CREATE POLICY sales_debit_note_lines_write_tier_update ON public.sales_debit_note_lines AS RESTRICTIVE FOR UPDATE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')))
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS sales_debit_note_lines_write_tier_delete ON public.sales_debit_note_lines;
  CREATE POLICY sales_debit_note_lines_write_tier_delete ON public.sales_debit_note_lines AS RESTRICTIVE FOR DELETE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')));

  DROP POLICY IF EXISTS recurring_invoice_template_lines_write_tier_insert ON public.recurring_invoice_template_lines;
  CREATE POLICY recurring_invoice_template_lines_write_tier_insert ON public.recurring_invoice_template_lines AS RESTRICTIVE FOR INSERT TO authenticated
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS recurring_invoice_template_lines_write_tier_update ON public.recurring_invoice_template_lines;
  CREATE POLICY recurring_invoice_template_lines_write_tier_update ON public.recurring_invoice_template_lines AS RESTRICTIVE FOR UPDATE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')))
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS recurring_invoice_template_lines_write_tier_delete ON public.recurring_invoice_template_lines;
  CREATE POLICY recurring_invoice_template_lines_write_tier_delete ON public.recurring_invoice_template_lines AS RESTRICTIVE FOR DELETE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')));

  DROP POLICY IF EXISTS recurring_purchase_bill_template_lines_write_tier_insert ON public.recurring_purchase_bill_template_lines;
  CREATE POLICY recurring_purchase_bill_template_lines_write_tier_insert ON public.recurring_purchase_bill_template_lines AS RESTRICTIVE FOR INSERT TO authenticated
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS recurring_purchase_bill_template_lines_write_tier_update ON public.recurring_purchase_bill_template_lines;
  CREATE POLICY recurring_purchase_bill_template_lines_write_tier_update ON public.recurring_purchase_bill_template_lines AS RESTRICTIVE FOR UPDATE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')))
    WITH CHECK ((SELECT public.my_permission('accounting', 'write', 'Manager')));
  DROP POLICY IF EXISTS recurring_purchase_bill_template_lines_write_tier_delete ON public.recurring_purchase_bill_template_lines;
  CREATE POLICY recurring_purchase_bill_template_lines_write_tier_delete ON public.recurring_purchase_bill_template_lines AS RESTRICTIVE FOR DELETE TO authenticated
    USING ((SELECT public.my_permission('accounting', 'write', 'Manager')));

  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_lines ON public.client_sales_invoice_lines;
  CREATE TRIGGER a_document_that_is_not_a_draft_keeps_its_lines
    BEFORE INSERT OR UPDATE OR DELETE ON public.client_sales_invoice_lines
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document('client_sales_invoices', 'sales_invoice_id', 'unit', 'invoice');

  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_lines ON public.purchase_bill_lines;
  CREATE TRIGGER a_document_that_is_not_a_draft_keeps_its_lines
    BEFORE INSERT OR UPDATE OR DELETE ON public.purchase_bill_lines
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document('purchase_bills', 'bill_id', 'unit', 'bill');

  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_lines ON public.credit_note_lines;
  CREATE TRIGGER a_document_that_is_not_a_draft_keeps_its_lines
    BEFORE INSERT OR UPDATE OR DELETE ON public.credit_note_lines
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document('credit_notes', 'credit_note_id', 'none', 'credit note');

  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_lines ON public.debit_note_lines;
  CREATE TRIGGER a_document_that_is_not_a_draft_keeps_its_lines
    BEFORE INSERT OR UPDATE OR DELETE ON public.debit_note_lines
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document('debit_notes', 'debit_note_id', 'none', 'debit note');

  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_lines ON public.purchase_credit_note_lines;
  CREATE TRIGGER a_document_that_is_not_a_draft_keeps_its_lines
    BEFORE INSERT OR UPDATE OR DELETE ON public.purchase_credit_note_lines
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document('purchase_credit_notes', 'credit_note_id', 'none', 'purchase credit note');

  DROP TRIGGER IF EXISTS a_document_that_is_not_a_draft_keeps_its_lines ON public.sales_debit_note_lines;
  CREATE TRIGGER a_document_that_is_not_a_draft_keeps_its_lines
    BEFORE INSERT OR UPDATE OR DELETE ON public.sales_debit_note_lines
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document('sales_debit_notes', 'debit_note_id', 'none', 'sales debit note');
END $apply$;

-- ── 3. check it ────────────────────────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
  n_pol integer;
  n_trg integer;
BEGIN
  SELECT count(*) INTO n_pol FROM pg_policy p JOIN pg_class k ON k.oid = p.polrelid
   WHERE k.relnamespace = 'public'::regnamespace AND p.polname LIKE '%\_write\_tier\_%'
     AND k.relname IN ('client_sales_invoice_lines', 'purchase_bill_lines', 'credit_note_lines', 'debit_note_lines', 'purchase_credit_note_lines', 'sales_debit_note_lines', 'recurring_invoice_template_lines', 'recurring_purchase_bill_template_lines')
     AND NOT p.polpermissive;
  IF n_pol <> 24 THEN
    RAISE EXCEPTION 'migration 539: expected 24 write-tier policies on the line tables, found %', n_pol;
  END IF;
  SELECT count(*) INTO n_trg FROM pg_trigger WHERE tgname = 'a_document_that_is_not_a_draft_keeps_its_lines' AND NOT tgisinternal AND tgenabled = 'O';
  IF n_trg <> 6 THEN
    RAISE EXCEPTION 'migration 539: expected 6 draft-only triggers, found %', n_trg;
  END IF;
  IF has_function_privilege('authenticated', 'public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document()', 'EXECUTE')
     OR has_function_privilege('anon', 'public.refuse_a_signed_in_edit_of_lines_of_a_non_draft_document()', 'EXECUTE') THEN
    RAISE EXCEPTION 'migration 539: a signed-in role can execute the draft-only trigger function';
  END IF;
END $$;
