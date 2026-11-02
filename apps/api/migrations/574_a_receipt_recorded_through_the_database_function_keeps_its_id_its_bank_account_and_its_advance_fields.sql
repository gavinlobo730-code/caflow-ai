-- Migration 574: a receipt recorded through the database function keeps the id its journal entry names, the bank account it was paid
-- into and the GSTR-1 Table 11A fields the CA supplied (POST-A-369 review of migration 572, found on the way; ledger drill-through ACC-22).
--
-- ====================================================================================================================================
-- WHAT WAS WRONG
-- ====================================================================================================================================
-- Every receipt the product records in production goes through `settle_receipt_atomic` (the real client always has `.rpc`), which calls
-- `settle_receipt_atomic__unguarded`, whose body is migration 235's, renamed by 486 and never rewritten. Its INSERT INTO public.receipts
-- names a fixed column list, and that list was written before the API sent `bank_account_id` (SALES-08, migration 342), the three
-- Table 11A columns `gst_rate_bps`, `place_of_supply` and `is_interstate` (migration 286, SALES-15) and a pre-generated `id`.
-- `create_receipt_core` sends all five in the receipt payload; the function dropped them, with no error:
--   * the stored receipt had NO bank account, so the Receipts tab said the receipt was posted to the general Bank ledger when its journal
--     had in fact debited the bank the CA chose;
--   * an advance receipt for a client whose advances bear tax kept no rate or place of supply, so GSTR-1 Table 11A listed it as a gap
--     although the CA had typed both, and the create response and its audit event said null for all of them;
--   * the receipt got a database-generated id while its journal entry carried the pre-generated one in `source_id`, so the ledger's
--     "open the document" (`?tab=receipts&doc=<source_id>`) opened nothing: on production, 101 of 101 receipt entries named an id that is
--     no receipt (read-only, 2-11-2026). Every other document type resolves (5,650 invoices, 769 bills, 31 purchase payments, the
--     notes, bank transactions, assets and payroll runs: no dangling id).
-- The test double the suite uses (`tests/e2e_harness.py`) stores the whole payload, which is why no mock test could see it.
--
-- ====================================================================================================================================
-- WHAT THIS DOES
-- ====================================================================================================================================
-- Re-defines `public.settle_receipt_atomic__unguarded` with migration 235's body UNCHANGED except for the INSERT into receipts, which now
-- also stores `id` (the payload's, or a generated one when the caller sent none), `bank_account_id`, `gst_rate_bps`, `place_of_supply`
-- and `is_interstate` (each NULL when absent or blank, the state the advances report already names).
-- The body below was checked against production's before this file was written: the old text, comments folded to ASCII as the platform
-- stores them, installs to the SAME md5 as production's function (45807d07a4e02711c88dafe36fabe40f, 6,462 characters), and this
-- file's text differs from it in exactly the six lines of the INSERT. CREATE OR REPLACE keeps the owner, the SECURITY DEFINER attribute
-- (restated here), the search path (restated) and the privileges (owner and service_role only, not touched); the privileged wrapper
-- `settle_receipt_atomic` (migration 546) is not touched.
-- Existing receipts are not changed by this file (migration 575 repairs the ledger entries' link; the bank account and the advance fields
-- of the 101 existing receipts are unrecoverable from the database: nothing stored them, and production holds no client whose advances
-- bear tax and no receipt with a bank account chosen).
-- Rollback: 574_..._rollback.sql restores the previous text.
--
-- Nothing here transmits anything to a portal.

BEGIN;

CREATE OR REPLACE FUNCTION public.settle_receipt_atomic__unguarded(
  p_receipt jsonb,
  p_journal_entry jsonb,
  p_journal_lines jsonb,
  p_allocations jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_journal_id        uuid;
  v_receipt_id        uuid;
  v_receipt_row       public.receipts;
  v_invoice_id        uuid;
  v_invoice_status     text;
  v_total_paise       bigint;
  v_paid_paise        bigint;
  v_credited_paise    bigint;
  v_debit_note_paise  bigint;
  v_allocated_paise   bigint;
  v_new_paid          bigint;
  v_new_status        text;
  v_alloc_results     jsonb := '[]'::jsonb;
  v_total_debit       bigint;
  v_total_credit      bigint;
BEGIN
  -- 0. Balance/non-zero guard (mirrors phase2_journal_service._create_journal)
  SELECT COALESCE(sum(COALESCE((l->>'debit_paise')::bigint, 0)), 0),
         COALESCE(sum(COALESCE((l->>'credit_paise')::bigint, 0)), 0)
    INTO v_total_debit, v_total_credit
    FROM jsonb_array_elements(p_journal_lines) AS l;

  IF v_total_debit <> v_total_credit THEN
    RAISE EXCEPTION 'settle_receipt_atomic: journal imbalance debit=% credit=% for ref=%',
      v_total_debit, v_total_credit, p_journal_entry->>'reference_no';
  END IF;
  IF v_total_debit = 0 THEN
    RAISE EXCEPTION 'settle_receipt_atomic: refusing to post a zero-value journal entry for ref=%',
      p_journal_entry->>'reference_no';
  END IF;

  -- 1. Journal header
  INSERT INTO public.journal_entries (
    firm_id, client_id, entry_date, reference_no, narration, entry_type,
    is_posted, status, posted_at, posted_by, created_by, source_type, source_id
  )
  VALUES (
    (p_journal_entry->>'firm_id')::uuid,
    (p_journal_entry->>'client_id')::uuid,
    (p_journal_entry->>'entry_date')::date,
    p_journal_entry->>'reference_no',
    p_journal_entry->>'narration',
    p_journal_entry->>'entry_type',
    COALESCE((p_journal_entry->>'is_posted')::boolean, true),
    COALESCE(p_journal_entry->>'status', 'posted'),
    NULLIF(p_journal_entry->>'posted_at', '')::timestamptz,
    NULLIF(p_journal_entry->>'posted_by', '')::uuid,
    NULLIF(p_journal_entry->>'created_by', '')::uuid,
    p_journal_entry->>'source_type',
    NULLIF(p_journal_entry->>'source_id', '')::uuid
  )
  RETURNING id INTO v_journal_id;

  -- 2. Journal lines (same transaction -- no orphan header possible)
  INSERT INTO public.journal_lines (
    journal_entry_id, account_id, debit_paise, credit_paise, narration,
    txn_currency, base_currency, exchange_rate, txn_debit, txn_credit,
    rate_source, rate_type, rate_date
  )
  SELECT
    v_journal_id,
    (l->>'account_id')::uuid,
    COALESCE((l->>'debit_paise')::bigint, 0),
    COALESCE((l->>'credit_paise')::bigint, 0),
    l->>'narration',
    COALESCE(NULLIF(l->>'txn_currency', ''), 'INR'),
    COALESCE(NULLIF(l->>'base_currency', ''), 'INR'),
    COALESCE((l->>'exchange_rate')::numeric, 1),
    NULLIF(l->>'txn_debit', '')::bigint,
    NULLIF(l->>'txn_credit', '')::bigint,
    l->>'rate_source',
    COALESCE(NULLIF(l->>'rate_type', ''), 'booking'),
    NULLIF(l->>'rate_date', '')::date
  FROM jsonb_array_elements(p_journal_lines) AS l;

  -- 3. Receipt row
  INSERT INTO public.receipts (
    id, firm_id, client_id, customer_id, receipt_no, receipt_date, amount_paise,
    tds_paise, unallocated_paise, payment_mode, reference_no, notes,
    bank_account_id, gst_rate_bps, place_of_supply, is_interstate,
    journal_entry_id, created_at
  )
  VALUES (
    COALESCE(NULLIF(p_receipt->>'id', '')::uuid, gen_random_uuid()),
    (p_receipt->>'firm_id')::uuid,
    (p_receipt->>'client_id')::uuid,
    (p_receipt->>'customer_id')::uuid,
    p_receipt->>'receipt_no',
    (p_receipt->>'receipt_date')::date,
    COALESCE((p_receipt->>'amount_paise')::bigint, 0),
    COALESCE((p_receipt->>'tds_paise')::bigint, 0),
    COALESCE((p_receipt->>'unallocated_paise')::bigint, 0),
    COALESCE(NULLIF(p_receipt->>'payment_mode', ''), 'bank'),
    p_receipt->>'reference_no',
    p_receipt->>'notes',
    NULLIF(p_receipt->>'bank_account_id', '')::uuid,
    NULLIF(p_receipt->>'gst_rate_bps', '')::integer,
    NULLIF(p_receipt->>'place_of_supply', ''),
    NULLIF(p_receipt->>'is_interstate', '')::boolean,
    v_journal_id,
    COALESCE((p_receipt->>'created_at')::timestamptz, now())
  )
  RETURNING * INTO v_receipt_row;

  v_receipt_id := v_receipt_row.id;

  -- 4. Allocations -- pre-aggregate duplicate rows per invoice, then lock,
  -- re-validate, update, record. (See migration 162 for the full rationale on
  -- pre-aggregation and row locking -- unchanged here.)
  FOR v_invoice_id, v_allocated_paise IN
    SELECT (x->>'sales_invoice_id')::uuid, sum(COALESCE((x->>'allocated_paise')::bigint, 0))
      FROM jsonb_array_elements(p_allocations) AS x
     WHERE COALESCE((x->>'allocated_paise')::bigint, 0) > 0
     GROUP BY (x->>'sales_invoice_id')::uuid
  LOOP
    SELECT status, total_paise, paid_paise, credited_paise, debit_note_paise
      INTO v_invoice_status, v_total_paise, v_paid_paise, v_credited_paise, v_debit_note_paise
      FROM public.client_sales_invoices
     WHERE id = v_invoice_id
       AND firm_id = (p_receipt->>'firm_id')::uuid
       AND client_id = (p_receipt->>'client_id')::uuid
     FOR UPDATE;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'settle_receipt_atomic: invoice % is not part of this client''s books', v_invoice_id;
    END IF;

    -- task #227: a draft invoice was never issued (no AR journal exists to
    -- settle) and a cancelled one is terminal -- neither can be settled.
    IF v_invoice_status IN ('draft', 'cancelled') THEN
      RAISE EXCEPTION 'settle_receipt_atomic: invoice % is % and cannot receive a payment',
        v_invoice_id, v_invoice_status;
    END IF;

    -- A sales debit note (CGST Act sec 34(3)) increases what's collectible.
    v_total_paise := v_total_paise + COALESCE(v_debit_note_paise, 0);

    v_new_paid := COALESCE(v_paid_paise, 0) + v_allocated_paise;
    IF v_new_paid + COALESCE(v_credited_paise, 0) > v_total_paise THEN
      RAISE EXCEPTION 'settle_receipt_atomic: allocation to invoice % (% paise) exceeds its outstanding',
        v_invoice_id, v_allocated_paise;
    END IF;
    v_new_status := CASE WHEN v_new_paid + COALESCE(v_credited_paise, 0) >= v_total_paise
                          THEN 'paid' ELSE 'partially_paid' END;

    UPDATE public.client_sales_invoices
       SET paid_paise = v_new_paid, status = v_new_status
     WHERE id = v_invoice_id;

    INSERT INTO public.receipt_allocations (receipt_id, sales_invoice_id, allocated_paise)
    VALUES (v_receipt_id, v_invoice_id, v_allocated_paise);

    v_alloc_results := v_alloc_results || jsonb_build_object(
      'sales_invoice_id', v_invoice_id,
      'allocated_paise', v_allocated_paise,
      'new_paid_paise', v_new_paid,
      'new_status', v_new_status
    );
  END LOOP;

  RETURN jsonb_build_object(
    'receipt_id', v_receipt_id,
    'journal_entry_id', v_journal_id,
    'receipt', to_jsonb(v_receipt_row),
    'allocations', v_alloc_results
  );
END
$$;

COMMENT ON FUNCTION public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb) IS
    'The body of settle_receipt_atomic (migration 235), reached only through the wrapper of migration 546. Migration 574: the receipt row now also stores id, bank_account_id, gst_rate_bps, place_of_supply and is_interstate from the payload.';

COMMIT;
