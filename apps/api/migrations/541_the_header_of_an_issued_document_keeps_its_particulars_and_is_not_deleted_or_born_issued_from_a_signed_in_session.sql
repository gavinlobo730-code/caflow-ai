-- Migration 541 — the header of an issued invoice, bill or note keeps its particulars, and a signed-in session cannot delete one or
-- INSERT one already issued (POST-A-330).
--
-- WHAT WAS WRONG
--   Migration 539 put the accounting tier and a draft-only rule on the LINES of a document. The HEADERS of the six documents
--   (client_sales_invoices, purchase_bills, credit_notes, debit_notes, purchase_credit_notes, sales_debit_notes) carry a role tier
--   since 487 and nothing that asks what state the row is in. So a member who holds the tier could, over PostgREST and while the
--   API refuses every one of these. The reach differs by command: INSERT and DELETE of any of the six need `accounting:write`
--   (a Manager), and so does UPDATE of the four notes, while UPDATE of an invoice also opens to an Executive through
--   `banking:write` or `invoice:write` and UPDATE of a bill through `banking:write`, so the change and the soft delete of an issued
--   invoice or bill, and the move back to a draft, are an Executive's as well:
--     * change an issued document's amounts, tax, party, number, dates or supply fields (the PDF, the return built from it and the
--       ledger then disagree);
--     * delete an issued document with its lines (a Manager reproduced it on 23-10-2026);
--     * insert a document already issued, which for the four note tables went round the draft the numbering function creates;
--     * soft-delete an issued document (`deleted_at`), which hides it from every report;
--     * move an issued document back to `draft`, which opens its lines again and so undoes migration 539.
--   The API's own rule is that an issued invoice or bill changes only soft fields (`_SOFT_UPDATE_FIELDS`, `_SOFT_BILL_UPDATE_FIELDS`),
--   a note only `notes` (and `document_url` on the two purchase-side notes), that only a draft is deleted, that every document is
--   created as a draft except an opening document, and that the one move to `draft` is a received bill whose journal failed.
--
-- WHAT THIS DOES (one transaction)
--   One trigger function, `public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft(allowed, opening, label)`,
--   on the six header tables, BEFORE INSERT OR UPDATE OR DELETE, judging only a signed-in session (`current_setting('role')`
--   `authenticated` or `anon`, the test of migrations 498 and 539):
--     * INSERT: the document must be a draft. The exception is an opening document (`is_opening`), which the API creates as
--       `issued` (an invoice) or `received` (a bill) with no tax; the four note tables have none. The exception is held to that
--       shape (the trigger's second argument names the status): that status, no tax, TDS, ineligible credit, discount, round-off,
--       payment or application on it and no journal entry, which is what `opening_documents.row_for` writes, so it cannot be used
--       to create an issued, paid or cancelled document with tax on it. Its `total_paise` (and a bill's `net_payable_paise`) is the
--       balance carried over, which is the member's to state, as it is through the API.
--     * DELETE: only a draft. A delete made by a foreign-key action (the delete of a customer, vendor, client or firm cascading to
--       its documents) runs one trigger level deeper than a statement and is not judged: the API's own dependency guards decide
--       those, and the firm purge runs with triggers off.
--     * UPDATE of a document that is a draft: not judged (the API decides what a draft may change, and issuing is an update of a
--       draft). UPDATE of a document that is NOT a draft: only the columns listed for its table may change, and a change of any
--       other column is refused in words. The lists are the union of what the legitimate writers change, read from the code and
--       from the first review of this change: soft fields (references, notes, due date, credit days, the shipping-bill three on an
--       invoice, the attached document and the Form 15CA/15CB references on a bill), the settlement and status columns the receipt,
--       payment, bank, party-credit and note-application paths write (`paid_paise`, `paid_txn`, `status`, `credited_paise`,
--       `debit_note_paise`, `debited_paise`, `credit_note_paise`, `cancelled_at`, `journal_entry_id`; the two generated outstanding
--       columns are derived from them and are ignored), the collections metadata (`is_overdue`, `days_overdue`, `aging_bucket`, the reminder counters) and
--       `landed_cost_basis`. `status` and the settlement columns stay writable here because about a dozen paths change them under the
--       caller's role (POST-A-331); everything that says WHAT was supplied, to WHOM, for HOW MUCH and ON WHICH DAY, the number,
--       the currency and the tax is frozen. `deleted_at` may change only on an opening document with nothing paid against it (the API's only soft delete, and its own 409).
--     * The journal link of a document that is not a draft cannot be changed once it is made (a link may be set where there is
--       none: the receive, the repost and the issue do exactly that); the way back to a draft below stands on it. The link is
--       permanent from a signed-in session even when it is wrong, and that includes a link to an entry of another firm (a foreign
--       key admits one): correcting it is the privileged client's, which the API uses for a repost.
--     * A move of a non-draft document back to `draft` is refused, except the one the API makes: a received bill that is not an
--       opening bill, was received in the last ten minutes (`received_at` is set by the receive, and the rollback runs in the same
--       request), has no journal link yet and nothing paid, debited or credited against it, whose `received_at` is cleared in the
--       same statement and nothing else changes (the rollback of a receive whose journal failed). The ten minutes are what stops
--       a bill that has sat received for days from being walked back to a draft: the paid, debited and credited columns are ones
--       this trigger leaves writable, so a member could zero them first, and a bill that was received long ago and never got its
--       journal link is a bill to be posted, not a draft.
--     * An UPDATE made by a foreign-key action (ON DELETE SET NULL of the journal link, the billing schedule or the recurring
--       template) runs one level deeper and is not judged.
--   The privileged client, the database owner and the firm purge (replica mode) are not judged. The function reads nothing else
--   and takes no lock (it reads only OLD and NEW), EXECUTE on it is revoked from the signed-in roles, and a closing DO block
--   compares each trigger's table, event, function and arguments with what is written here.
--   The six triggers are created inside ONE DO block, every statement written out literally. CREATE OR REPLACE TRIGGER (Postgres 14
--   and later) takes SHARE ROW EXCLUSIVE on the table (writes wait, reads do not) whether or not the trigger exists, until the
--   migration commits; measured on 16 on 23-10-2026. The triggers are not dropped first, because DROP TRIGGER of a trigger that
--   exists takes ACCESS EXCLUSIVE, which on a re-apply would queue behind every reader and could deadlock a transaction that
--   reads and then writes (the review of this change reproduced both). The runner sends a top-level statement per round trip,
--   which is why the block is one statement (the review of migration 539 measured what a round trip costs while a lock is held).
--
-- WHAT IT DOES NOT DO, ON PURPOSE
--   * `status`, `paid_paise`, `paid_txn`, `credited_paise`, `debit_note_paise`, `debited_paise`, `credit_note_paise`,
--     `cancelled_at` and `journal_entry_id` (where it is NULL) stay writable by a member who holds the tier, so such a member can
--     still mark an invoice paid, cancel it or re-issue a cancelled one over PostgREST, and an UPDATE of a DRAFT is not judged, so a
--     document can still be ISSUED over PostgREST in two statements (edit the draft, then set its status), carrying whatever
--     particulars the draft was given and none of the API's issue checks. Closing those needs the writers moved to the privileged
--     client first (POST-A-331); what is closed here is the INSERT of an issued document, the change of an issued one, its delete
--     and its move back to a draft.
--   * A cancelled document is not frozen by status: a cancelled invoice's soft fields stay editable as they are in the API.
--   * A TRUNCATE is not seen by a row trigger. PostgREST has no verb for it, so it is not reachable over the API; the signed-in
--     role's TRUNCATE privilege on public tables is the platform default and is not what this closes.
--   * Nothing is rewritten: existing documents keep their rows as they are.
--
-- Idempotent (CREATE OR REPLACE for the function and for each trigger). Reversible: 541_..._rollback.sql drops the six triggers
-- and the function.
--
-- LOCKS. The block takes its table locks WITHOUT QUEUEING: it asks for all six tables at once in SHARE ROW EXCLUSIVE mode with
-- NOWAIT and, when any of them is busy (a write in flight), gives up that attempt, holding nothing, waits half a second and asks
-- again, for up to fifteen seconds. A plain lock request would sit in the queue and every later write to that table would queue
-- behind it, and six of them taken one after another would hold the earlier tables while waiting for the later. After fifteen
-- seconds the migration fails (a transaction that long on one of these tables), to be re-run. A lock_timeout of 15 seconds, as
-- migrations 536 to 540 set, backs any other statement of the file that could wait.

SELECT set_config('lock_timeout', '15s', true);

CREATE OR REPLACE FUNCTION public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_role     text := COALESCE(current_setting('role', true), 'none');
  v_allowed  text[] := string_to_array(COALESCE(TG_ARGV[0], ''), ',');
  v_opening  boolean := COALESCE(TG_ARGV[1], '') LIKE 'opening:%';
  v_open_st  text := split_part(COALESCE(TG_ARGV[1], ''), ':', 2);
  v_label    text := COALESCE(TG_ARGV[2], 'document');
  v_old_open boolean;
  v_changed  text[];
  v_frozen   text[];
  v_loaded   text[];
  v_old      jsonb;
  v_new      jsonb;
BEGIN
  -- The test of 498 and 539: PostgREST sets the role setting for a caller, and inside a SECURITY DEFINER function it stays the
  -- caller's. The privileged client, the database owner and the firm purge (replica triggers off) pass untouched.
  IF v_role NOT IN ('authenticated', 'anon') THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;

  IF TG_OP = 'INSERT' THEN
    IF NEW.status IS DISTINCT FROM 'draft' THEN
      v_new := to_jsonb(NEW);                           -- read once, and only on the path that needs it
      IF NOT (v_opening AND COALESCE((v_new ->> 'is_opening')::boolean, false)) THEN
        RAISE EXCEPTION 'A % can only be created as a draft from a signed-in session (this one is %). Nothing was saved.',
          v_label, COALESCE(NEW.status, 'without a status') USING ERRCODE = '42501';
      END IF;
      -- an opening document is a balance carried over from the old books: the status the API gives it, no tax, nothing paid or
      -- applied and no journal (the API's opening_documents.row_for writes exactly that), so the exemption cannot be used to
      -- create an issued, paid or cancelled document with tax on it
      IF NEW.status IS DISTINCT FROM v_open_st THEN
        RAISE EXCEPTION 'An opening % can only be created as %, from a signed-in session (this one is %). Nothing was saved.',
          v_label, v_open_st, COALESCE(NEW.status, 'without a status') USING ERRCODE = '42501';
      END IF;
      SELECT array_agg(n.key ORDER BY n.key) INTO v_loaded
        FROM jsonb_each_text(v_new) AS n
       WHERE n.key IN ('taxable_amount_paise', 'cgst_paise', 'sgst_paise', 'igst_paise', 'total_gst_paise', 'cess_paise',
                       'tds_paise', 'tds_rate_bps', 'tds_surcharge_paise', 'tds_cess_paise', 'tds_advance_adjusted_paise',
                       'ineligible_itc_igst_paise', 'ineligible_itc_cgst_paise', 'ineligible_itc_sgst_paise',
                       'ineligible_itc_cess_paise', 'discount_paise', 'discount_percent_bps', 'round_off_paise',
                       'paid_paise', 'paid_txn', 'credited_paise', 'debit_note_paise', 'debited_paise', 'credit_note_paise')
         AND COALESCE(n.value::numeric, 0) <> 0;
      IF v_loaded IS NOT NULL OR (v_new ->> 'journal_entry_id') IS NOT NULL THEN
        RAISE EXCEPTION 'An opening % carries no tax, no payment and no journal entry, from a signed-in session (% set). Nothing was saved.',
          v_label, array_to_string(COALESCE(v_loaded, ARRAY['journal_entry_id']), ', ') USING ERRCODE = '42501';
      END IF;
    END IF;
    RETURN NEW;
  END IF;

  IF TG_OP = 'DELETE' THEN
    -- a foreign-key cascade (the delete of the customer, vendor, client or firm) reaches here one trigger level deeper than a statement
    IF OLD.status IS DISTINCT FROM 'draft' AND pg_trigger_depth() <= 1 THEN
      RAISE EXCEPTION 'The % that is % cannot be deleted from a signed-in session. Only a draft can be deleted; correct an issued document with a credit or debit note.',
        v_label, COALESCE(OLD.status, 'without a status') USING ERRCODE = '42501';
    END IF;
    RETURN OLD;
  END IF;

  -- UPDATE. A draft is the API's to judge, and a foreign-key action (ON DELETE SET NULL of a link) runs one level deeper.
  IF OLD.status = 'draft' OR pg_trigger_depth() > 1 THEN
    RETURN NEW;
  END IF;

  -- read once, and only for a document that is not a draft: a draft's update is not judged and costs nothing here
  v_old := to_jsonb(OLD);
  v_new := to_jsonb(NEW);

  -- the two generated outstanding columns are recomputed AFTER a BEFORE trigger, so NEW does not carry their new value: they are
  -- derived from the paid columns and are never what a person changed
  SELECT array_agg(n.key ORDER BY n.key) INTO v_changed
    FROM jsonb_each(v_new) AS n
   WHERE n.value IS DISTINCT FROM (v_old -> n.key)
     AND n.key NOT IN ('outstanding_paise', 'txn_outstanding');
  IF v_changed IS NULL THEN
    RETURN NEW;                                       -- nothing changed
  END IF;

  -- the journal link, once made, is not a signed-in member's to move or clear (the writers only ever link a document that has none:
  -- the receive, the repost and the issue), and it is what the way back to a draft below stands on
  IF 'journal_entry_id' = ANY (v_changed) AND (v_old ->> 'journal_entry_id') IS NOT NULL THEN
    RAISE EXCEPTION 'The % that is % keeps the journal entry it was posted with: the link cannot be changed from a signed-in session.',
      v_label, COALESCE(OLD.status, 'without a status') USING ERRCODE = '42501';
  END IF;

  -- back to a draft: only the received bill whose journal failed, the one move of that kind the API makes: a bill the API received
  -- in this request (received_at set within the last ten minutes, an opening bill has none), with no journal link yet, nothing
  -- paid, debited or credited against it, and nothing changed but the status and received_at
  IF NEW.status IS NOT DISTINCT FROM 'draft' THEN
    IF TG_TABLE_NAME = 'purchase_bills' AND OLD.status = 'received'
       AND (v_old ->> 'journal_entry_id') IS NULL
       AND NOT COALESCE((v_old ->> 'is_opening')::boolean, false)
       AND (v_old ->> 'received_at') IS NOT NULL
       AND (v_old ->> 'received_at')::timestamptz > now() - interval '10 minutes'
       AND (v_new ->> 'received_at') IS NULL
       AND COALESCE((v_old ->> 'paid_paise')::numeric, 0) = 0
       AND COALESCE((v_old ->> 'debited_paise')::numeric, 0) = 0
       AND COALESCE((v_old ->> 'credit_note_paise')::numeric, 0) = 0
       AND v_changed <@ ARRAY['status', 'received_at', 'updated_at'] THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'The % that is % cannot be moved back to a draft from a signed-in session.',
      v_label, COALESCE(OLD.status, 'without a status') USING ERRCODE = '42501';
  END IF;

  -- the soft delete is the opening document's alone, and only while nothing has been paid against it (the API's own 409)
  v_old_open := v_opening AND COALESCE((v_old ->> 'is_opening')::boolean, false)
                AND COALESCE((v_old ->> 'paid_paise')::numeric, 0) = 0;
  SELECT array_agg(c ORDER BY c) INTO v_frozen
    FROM unnest(v_changed) AS c
   WHERE NOT (c = ANY (v_allowed))
     AND NOT (c = 'deleted_at' AND v_old_open);
  IF v_frozen IS NOT NULL THEN
    RAISE EXCEPTION 'The % that is % cannot be changed from a signed-in session: % can no longer be edited. Correct an issued document with a credit or debit note.',
      v_label, COALESCE(OLD.status, 'without a status'), array_to_string(v_frozen[1:6], ', ') USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft() FROM PUBLIC, anon, authenticated;

DO $apply$
DECLARE
  v_try integer := 0;
BEGIN
  -- Ask for all six tables at once without queueing (NOWAIT), and when one is busy give the attempt up, holding nothing, and ask
  -- again half a second later: a plain request would sit in the lock queue and every later write to the table would wait behind it.
  -- SHARE ROW EXCLUSIVE is what CREATE OR REPLACE TRIGGER takes, so nothing below asks for a stronger lock than the one held.
  LOOP
    BEGIN
      LOCK TABLE public.client_sales_invoices, public.purchase_bills, public.credit_notes, public.debit_notes, public.purchase_credit_notes, public.sales_debit_notes IN SHARE ROW EXCLUSIVE MODE NOWAIT;
      EXIT;
    EXCEPTION WHEN lock_not_available THEN
      v_try := v_try + 1;
      IF v_try >= 30 THEN
        RAISE EXCEPTION 'migration 541: could not lock the six document header tables in 15 seconds (a transaction is writing one); run it again';
      END IF;
      PERFORM pg_sleep(0.5);
    END;
  END LOOP;

  CREATE OR REPLACE TRIGGER a_document_that_is_not_a_draft_keeps_its_particulars
    BEFORE INSERT OR UPDATE OR DELETE ON public.client_sales_invoices
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft('reference_no,notes,due_date,credit_days,shipping_bill_no,shipping_bill_date,port_code,updated_at,status,journal_entry_id,paid_paise,paid_txn,credited_paise,debit_note_paise,last_reminded_at,reminder_count,is_overdue,days_overdue,aging_bucket,last_internal_followup_at,internal_followup_count', 'opening:issued', 'invoice');

  CREATE OR REPLACE TRIGGER a_document_that_is_not_a_draft_keeps_its_particulars
    BEFORE INSERT OR UPDATE OR DELETE ON public.purchase_bills
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft('notes,due_date,credit_days,our_reference,document_url,form_15ca_ack_no,form_15ca_filed_on,form_15cb_udin,updated_at,status,cancelled_at,journal_entry_id,paid_paise,paid_txn,debited_paise,credit_note_paise,landed_cost_basis', 'opening:received', 'bill');

  CREATE OR REPLACE TRIGGER a_document_that_is_not_a_draft_keeps_its_particulars
    BEFORE INSERT OR UPDATE OR DELETE ON public.credit_notes
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft('notes,updated_at', 'none', 'credit note');

  CREATE OR REPLACE TRIGGER a_document_that_is_not_a_draft_keeps_its_particulars
    BEFORE INSERT OR UPDATE OR DELETE ON public.debit_notes
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft('notes,document_url', 'none', 'debit note');

  CREATE OR REPLACE TRIGGER a_document_that_is_not_a_draft_keeps_its_particulars
    BEFORE INSERT OR UPDATE OR DELETE ON public.purchase_credit_notes
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft('notes,document_url', 'none', 'purchase credit note');

  CREATE OR REPLACE TRIGGER a_document_that_is_not_a_draft_keeps_its_particulars
    BEFORE INSERT OR UPDATE OR DELETE ON public.sales_debit_notes
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft('notes,updated_at', 'none', 'sales debit note');
END $apply$;

DO $$
DECLARE
  v record;
BEGIN
  -- each trigger is the one written: its table, ROW + BEFORE + INSERT + UPDATE + DELETE, its function and its three arguments
  FOR v IN SELECT * FROM (VALUES
      ('client_sales_invoices', 'reference_no,notes,due_date,credit_days,shipping_bill_no,shipping_bill_date,port_code,updated_at,status,journal_entry_id,paid_paise,paid_txn,credited_paise,debit_note_paise,last_reminded_at,reminder_count,is_overdue,days_overdue,aging_bucket,last_internal_followup_at,internal_followup_count', 'opening:issued', 'invoice'),
      ('purchase_bills', 'notes,due_date,credit_days,our_reference,document_url,form_15ca_ack_no,form_15ca_filed_on,form_15cb_udin,updated_at,status,cancelled_at,journal_entry_id,paid_paise,paid_txn,debited_paise,credit_note_paise,landed_cost_basis', 'opening:received', 'bill'),
      ('credit_notes', 'notes,updated_at', 'none', 'credit note'),
      ('debit_notes', 'notes,document_url', 'none', 'debit note'),
      ('purchase_credit_notes', 'notes,document_url', 'none', 'purchase credit note'),
      ('sales_debit_notes', 'notes,updated_at', 'none', 'sales debit note')
    ) AS x(tbl, allowed, opening, label)
  LOOP
    IF NOT EXISTS (
         SELECT 1 FROM pg_trigger t
          WHERE t.tgname = 'a_document_that_is_not_a_draft_keeps_its_particulars'
            AND t.tgrelid = ('public.' || v.tbl)::regclass
            AND t.tgfoid = 'public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft()'::regprocedure
            AND NOT t.tgisinternal AND t.tgenabled = 'O'
            AND t.tgtype = 31                                  -- ROW, BEFORE, INSERT, DELETE, UPDATE
            AND t.tgattr::text = ''                            -- not UPDATE OF a column list
            AND t.tgargs = convert_to(v.allowed, 'UTF8') || '\x00'::bytea || convert_to(v.opening, 'UTF8') || '\x00'::bytea
                           || convert_to(v.label, 'UTF8') || '\x00'::bytea) THEN
      RAISE EXCEPTION 'migration 541: the header trigger on public.% is missing, disabled or is not the one written', v.tbl;
    END IF;
  END LOOP;
  IF has_function_privilege('authenticated', 'public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft()', 'EXECUTE')
     OR has_function_privilege('anon', 'public.refuse_a_signed_in_edit_of_a_document_that_is_not_a_draft()', 'EXECUTE') THEN
    RAISE EXCEPTION 'migration 541: a signed-in role can execute the header trigger function';
  END IF;
END $$;
