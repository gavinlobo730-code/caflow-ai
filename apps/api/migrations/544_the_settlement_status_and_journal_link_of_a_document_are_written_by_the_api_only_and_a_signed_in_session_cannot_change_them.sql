-- Migration 544 — the settlement, status and journal link of an invoice, bill or note are written by the API only, and a signed-in
-- session cannot change them (POST-A-331, step 2).
--
-- WHAT WAS WRONG
--   Migration 541 froze the particulars of an ISSUED document (who, what, how much, which day) and left the columns that say what
--   has been settled against a document, what state it is in and which journal entry it posted writable by a member who holds the
--   tier, because about a dozen API paths wrote them AS THE CALLER and a rule that asks who is writing could not tell the API's
--   settlement from a member's direct PostgREST call. So, over PostgREST and while the API refuses all of it, a member could mark
--   an invoice paid or set its paid amount to anything, cancel an invoice or re-issue a cancelled one, issue a draft with whatever
--   particulars it was given and none of the API's issue checks, move a bill's credit-note or debit-note totals, and point a document
--   at another journal entry. The paid amount is what the ageing, the statements, the collections queue and the bank match queue
--   read, so the books were not changed by it but every screen that reads the document was.
--
-- THE ORDER THIS WAS DONE IN
--   The change before this one (POST-A-331 step 1, no migration) moved every one of those writers to the API's privileged client
--   (`services/document_header_writer.update_header`), which names the document, its firm and its client on the statement and
--   writes the audit row the capture trigger of migration 111 skips for a write with no `auth.uid()`. This migration merges only
--   after that change has been on Render for at least an hour, because the old API against this trigger fails soft and wrong: a
--   receipt's settlement is refused with 42501, which the callers do not treat as a version conflict.
--
-- WHAT THIS DOES (one transaction)
--   One trigger function, `public.refuse_a_signed_in_change_of_a_documents_settlement()`, on the six header tables
--   (client_sales_invoices, purchase_bills, credit_notes, debit_notes, purchase_credit_notes, sales_debit_notes), BEFORE INSERT OR
--   UPDATE OF the table's own settlement columns, FOR EACH ROW:
--     * client_sales_invoices: status, journal_entry_id, issued_at, paid_paise, paid_txn, credited_paise, debit_note_paise;
--     * purchase_bills: status, journal_entry_id, received_at, cancelled_at, paid_paise, paid_txn, debited_paise, credit_note_paise;
--     * the four note tables: status, journal_entry_id, applied_paise.
--   An UPDATE that CHANGES one of them is refused (a statement that names a column and sends the value the row holds is not a
--   change, and one that names none never runs the trigger); an INSERT carrying any of them other than at its column default (zero,
--   or NULL) is refused as well, `status` excepted because migration 541 already judges it (a draft, or an opening document in the
--   one status the API gives it). Both are refused with 42501 in words, and nothing is saved.
--   WHO IS JUDGED, AND WHY AN UPDATE AND AN INSERT ARE NOT JUDGED BY THE SAME TEST. The function is SECURITY INVOKER.
--     * An UPDATE is judged by `current_user`, not by the `role` setting migrations 498 to 543 test: a signed-in session is
--       `authenticated` (or `anon`) when PostgREST runs the statement, so a direct PATCH is judged; the privileged client
--       (`service_role`), the database owner and the firm purge (triggers off, replica mode) are not. The difference matters for
--       exactly one database function, `settle_receipt_atomic`, which the API's plain rupee receipt calls and which writes an
--       invoice's paid amount and status inside the database. It is SECURITY DEFINER (migration 217) and runs as its owner, so
--       `current_user` inside it is the owner and the settlement passes; the `role` setting inside it stays the caller's, which is
--       why the earlier triggers could not be used here without refusing every ordinary receipt.
--     * An INSERT is judged by the `role` setting, the test of 541. The review of this migration found that a `current_user` test
--       lets a member create a note already carrying a paid amount or a journal link through `numbered_document_atomic`, the
--       SECURITY DEFINER function that inserts the four note tables from whatever header it is handed (its wrapper asks who is
--       calling and lets a Manager through). No function that is legitimately called by a signed-in session inserts a document
--       with a settlement on it (the API creates drafts at the defaults and opening documents with none, and every issued insert is
--       the privileged client's), so nothing needs the owner's pass on an INSERT.
--   An UPDATE made by a foreign-key action (ON DELETE SET NULL of the journal link, the billing schedule or the recurring template)
--   runs as the owner of the table it updates, so `current_user` is the owner and it passes without a rule of its own. There is
--   deliberately NO exemption for a write made from inside another trigger (`pg_trigger_depth()`, which 541 uses because it
--   judges the role setting): an invoker trigger on another table that wrote a settlement as the signed-in caller would be judged
--   and refused. The schema has no such trigger, and the exemption would have been a bypass waiting for one.
--   Because the function is INVOKER, it must stay INVOKER: made SECURITY DEFINER it would see its owner on every call and pass every
--   statement. The closing check below reads that. The function also refuses, loudly, to run when a name it was given is not a
--   column of the row (a column renamed after this migration would otherwise stop being judged without a sound, while the
--   `UPDATE OF` list, which is stored by column number, kept firing). EXECUTE on it is revoked from the signed-in roles (a trigger function is checked
--   for EXECUTE when the trigger is created, not when it fires), and the closing check compares each trigger's table, event,
--   function, enabled state, tgtype, arguments and column list with what is written here.
--   The six triggers are created inside ONE DO block that first locks the six tables in SHARE ROW EXCLUSIVE mode with NOWAIT,
--   retried every half second for fifteen seconds and then failing in its own words (the shape of 541 and 543); CREATE OR REPLACE
--   TRIGGER takes that lock whether or not the trigger exists, and nothing is dropped, because DROP TRIGGER of an existing trigger
--   takes ACCESS EXCLUSIVE.
--
-- WHAT IT DOES NOT DO, ON PURPOSE
--   * `settle_receipt_atomic` and `post_journal_atomic` still run as their owner and still take whatever they are handed from a
--     signed-in caller: the API's receipt passes through the first, and a member holding the tier can still call it over PostgREST
--     with an invoice id of the firm. Moving the ledger's two functions behind the privileged client, with the actor carried across
--     (the capture trigger skips a write with no `auth.uid()`), is POST-A-317.
--   * A DRAFT's particulars and flags stay editable over PostgREST (migration 541 leaves an UPDATE of a draft to the API), and the
--     API's issue posts from the stored row. So a member can still edit a draft's totals, tax or flags (`is_opening` is the sharpest:
--     an invoice flagged as carried over is left out of GSTR-1 and GSTR-3B) and then issue it with the permission they have. What is
--     closed here is the issue itself, the settlement and the journal link; the particulars of a draft are POST-A-335.
--   * The rows a settlement is derived from (receipts and their allocations, vendor payments and theirs) are written by the
--     caller's own client and stay writable by a member who holds the tier: POST-A-336.
--   * The collections flags (`is_overdue`, `days_overdue`, `aging_bucket`, the reminder counters), the follow-up stamps and
--     `landed_cost_basis` stay writable under migration 541: they are soft columns and no settlement.
--   * A TRUNCATE is not seen by a row trigger; PostgREST has no verb for it.
--   * Nothing is rewritten: existing documents keep their rows as they are.
--
-- Idempotent (CREATE OR REPLACE for the function and for each trigger). Reversible: 544_..._rollback.sql drops the six triggers and
-- the function.

SELECT set_config('lock_timeout', '15s', true);

CREATE OR REPLACE FUNCTION public.refuse_a_signed_in_change_of_a_documents_settlement()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_cols  text[] := string_to_array(COALESCE(TG_ARGV[0], ''), ',');
  v_label text := COALESCE(TG_ARGV[1], 'document');
  v_old   jsonb;
  v_new   jsonb;
  v_bad   text[];
BEGIN
  -- WHO IS WRITING. For an UPDATE, `current_user` is the role the statement runs as: `authenticated` or `anon` for a PostgREST
  -- caller, and the function's owner inside a SECURITY DEFINER function such as settle_receipt_atomic or inside a foreign-key
  -- action. (`current_setting('role')` stays the caller's inside a definer function, which is the test of 498 to 543 and not
  -- this one.) For an INSERT it is the `role` setting, so that a definer function which inserts a document, numbered_document_atomic,
  -- does not give a signed-in caller the owner's pass.
  IF TG_OP = 'INSERT' THEN
    IF COALESCE(current_setting('role', true), 'none') NOT IN ('authenticated', 'anon') THEN
      RETURN NEW;
    END IF;
  ELSIF current_user NOT IN ('authenticated', 'anon') THEN
    RETURN NEW;
  END IF;

  v_new := to_jsonb(NEW);

  -- a name this trigger was given that is not a column of the row (a column renamed after this migration) would read as NULL on both
  -- sides of an UPDATE and as the default on an INSERT, and so stop being judged without a sound: fail closed instead
  SELECT array_agg(c ORDER BY c) INTO v_bad FROM unnest(v_cols) AS c WHERE NOT (v_new ? c);
  IF v_bad IS NOT NULL THEN
    RAISE EXCEPTION 'The settlement trigger on % names % which is not a column of the row (renamed?). Nothing was saved until the trigger is rebuilt.',
      TG_TABLE_NAME, array_to_string(v_bad, ', ') USING ERRCODE = '42703';
  END IF;

  IF TG_OP = 'INSERT' THEN
    -- born with a settlement is the same forgery as changing it afterwards: the API's issue would carry it into the books. `status`
    -- is migration 541's to judge (a draft, or an opening document).
    SELECT array_agg(c ORDER BY c) INTO v_bad
      FROM unnest(v_cols) AS c
     WHERE c <> 'status'
       AND (v_new -> c) NOT IN ('null'::jsonb, '0'::jsonb);
    IF v_bad IS NOT NULL THEN
      RAISE EXCEPTION 'A % cannot be created from a signed-in session already carrying % : what has been settled against a document and its journal link are written by the API. Nothing was saved.',
        v_label, array_to_string(v_bad, ', ') USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
  END IF;

  v_old := to_jsonb(OLD);
  SELECT array_agg(c ORDER BY c) INTO v_bad
    FROM unnest(v_cols) AS c
   WHERE (v_new -> c) IS DISTINCT FROM (v_old -> c);
  IF v_bad IS NOT NULL THEN
    RAISE EXCEPTION 'The % cannot have its % changed from a signed-in session: what has been settled against a document, its status and its journal link are written by the API when the document is issued, paid, credited, applied or cancelled. Nothing was saved.',
      v_label, array_to_string(v_bad, ', ') USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.refuse_a_signed_in_change_of_a_documents_settlement() FROM PUBLIC, anon, authenticated;

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
        RAISE EXCEPTION 'migration 544: could not lock the six document header tables in 15 seconds (a write or a maintenance job holds one); run it again';
      END IF;
      PERFORM pg_sleep(0.5);
    END;
  END LOOP;

  CREATE OR REPLACE TRIGGER a_documents_settlement_is_written_by_the_api_only
    BEFORE INSERT OR UPDATE OF status, journal_entry_id, issued_at, paid_paise, paid_txn, credited_paise, debit_note_paise ON public.client_sales_invoices
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_change_of_a_documents_settlement('status,journal_entry_id,issued_at,paid_paise,paid_txn,credited_paise,debit_note_paise', 'invoice');

  CREATE OR REPLACE TRIGGER a_documents_settlement_is_written_by_the_api_only
    BEFORE INSERT OR UPDATE OF status, journal_entry_id, received_at, cancelled_at, paid_paise, paid_txn, debited_paise, credit_note_paise ON public.purchase_bills
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_change_of_a_documents_settlement('status,journal_entry_id,received_at,cancelled_at,paid_paise,paid_txn,debited_paise,credit_note_paise', 'bill');

  CREATE OR REPLACE TRIGGER a_documents_settlement_is_written_by_the_api_only
    BEFORE INSERT OR UPDATE OF status, journal_entry_id, applied_paise ON public.credit_notes
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_change_of_a_documents_settlement('status,journal_entry_id,applied_paise', 'credit note');

  CREATE OR REPLACE TRIGGER a_documents_settlement_is_written_by_the_api_only
    BEFORE INSERT OR UPDATE OF status, journal_entry_id, applied_paise ON public.debit_notes
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_change_of_a_documents_settlement('status,journal_entry_id,applied_paise', 'debit note');

  CREATE OR REPLACE TRIGGER a_documents_settlement_is_written_by_the_api_only
    BEFORE INSERT OR UPDATE OF status, journal_entry_id, applied_paise ON public.purchase_credit_notes
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_change_of_a_documents_settlement('status,journal_entry_id,applied_paise', 'purchase credit note');

  CREATE OR REPLACE TRIGGER a_documents_settlement_is_written_by_the_api_only
    BEFORE INSERT OR UPDATE OF status, journal_entry_id, applied_paise ON public.sales_debit_notes
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_change_of_a_documents_settlement('status,journal_entry_id,applied_paise', 'sales debit note');
END $apply$;

DO $$
DECLARE
  v record;
BEGIN
  -- each trigger is the one written: its table, ROW + BEFORE + INSERT + UPDATE (tgtype 23), enabled, its function, its two arguments
  -- and exactly the UPDATE OF column list
  FOR v IN SELECT * FROM (VALUES
      ('client_sales_invoices', 'status,journal_entry_id,issued_at,paid_paise,paid_txn,credited_paise,debit_note_paise', 'invoice'),
      ('purchase_bills', 'status,journal_entry_id,received_at,cancelled_at,paid_paise,paid_txn,debited_paise,credit_note_paise', 'bill'),
      ('credit_notes', 'status,journal_entry_id,applied_paise', 'credit note'),
      ('debit_notes', 'status,journal_entry_id,applied_paise', 'debit note'),
      ('purchase_credit_notes', 'status,journal_entry_id,applied_paise', 'purchase credit note'),
      ('sales_debit_notes', 'status,journal_entry_id,applied_paise', 'sales debit note')
    ) AS x(tbl, cols, label)
  LOOP
    IF NOT EXISTS (
         SELECT 1 FROM pg_trigger t
          WHERE t.tgname = 'a_documents_settlement_is_written_by_the_api_only'
            AND t.tgrelid = ('public.' || v.tbl)::regclass
            AND t.tgfoid = 'public.refuse_a_signed_in_change_of_a_documents_settlement()'::regprocedure
            AND NOT t.tgisinternal AND t.tgenabled = 'O'
            AND t.tgtype = 23                                  -- ROW, BEFORE, INSERT, UPDATE
            AND t.tgargs = convert_to(v.cols, 'UTF8') || '\x00'::bytea || convert_to(v.label, 'UTF8') || '\x00'::bytea
            AND (SELECT array_agg(a.attname::text COLLATE "C" ORDER BY a.attname::text COLLATE "C")
                   FROM unnest(t.tgattr) AS k(num) JOIN pg_attribute a ON a.attrelid = t.tgrelid AND a.attnum = k.num)
                = (SELECT array_agg(c COLLATE "C" ORDER BY c COLLATE "C") FROM unnest(string_to_array(v.cols, ',')) AS c)) THEN
      RAISE EXCEPTION 'migration 544: the settlement trigger on public.% is missing, disabled or is not the one written', v.tbl;
    END IF;
  END LOOP;

  -- the function must stay SECURITY INVOKER (a definer would see its owner on every call and pass every statement), pin its search
  -- path, and be closed to the signed-in roles
  IF EXISTS (SELECT 1 FROM pg_proc p WHERE p.oid = 'public.refuse_a_signed_in_change_of_a_documents_settlement()'::regprocedure AND p.prosecdef) THEN
    RAISE EXCEPTION 'migration 544: the settlement trigger function is SECURITY DEFINER; it must be SECURITY INVOKER or it judges its owner';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_proc p WHERE p.oid = 'public.refuse_a_signed_in_change_of_a_documents_settlement()'::regprocedure
                    AND p.proconfig @> ARRAY['search_path=public, pg_temp']) THEN
    RAISE EXCEPTION 'migration 544: the settlement trigger function does not pin its search path';
  END IF;
  IF has_function_privilege('authenticated', 'public.refuse_a_signed_in_change_of_a_documents_settlement()', 'EXECUTE')
     OR has_function_privilege('anon', 'public.refuse_a_signed_in_change_of_a_documents_settlement()', 'EXECUTE') THEN
    RAISE EXCEPTION 'migration 544: a signed-in role can execute the settlement trigger function';
  END IF;
END $$;
