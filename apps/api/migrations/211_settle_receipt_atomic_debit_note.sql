-- 211 — settle_receipt_atomic must know about sales debit notes.
--
-- Migration 210 added client_sales_invoices.debit_note_paise (CGST Act
-- §34(3): a sales debit note increases what a customer owes). The Python
-- ceiling checks in services/receipt_service.py were updated to fold it in,
-- but production receipts never actually run that Python path — per R2.12,
-- the real Supabase client always exposes .rpc, so every real receipt
-- settles through settle_receipt_atomic (migration 160, hardened by 162)
-- instead. Left unpatched, that function's own outstanding ceiling
-- (`v_new_paid + v_credited_paise > v_total_paise`) would reject a payment
-- for the TRUE outstanding on a debit-noted invoice — exactly the amount the
-- frontend now correctly displays and offers to collect — and would mark an
-- invoice "paid" before the debit note's addition was actually settled.
--
-- CREATE OR REPLACE, same signature — additive, does not touch 160/162's own
-- files. Only change: the invoice SELECT now also reads debit_note_paise,
-- folded into the working ceiling once so every downstream comparison
-- (the exceeds-outstanding check and the paid/partially_paid threshold)
-- picks it up automatically.
CREATE OR REPLACE FUNCTION settle_receipt_atomic(
  p_receipt jsonb,
  p_journal_entry jsonb,
  p_journal_lines jsonb,
  p_allocations jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_journal_id        uuid;
  v_receipt_id        uuid;
  v_receipt_row       public.receipts;
  v_invoice_id        uuid;
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
  -- ── 0. Balance/non-zero guard (mirrors phase2_journal_service._create_journal) ──
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

  -- ── 1. Journal header ────────────────────────────────────────────────────
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

  -- ── 2. Journal lines (same transaction — no orphan header possible) ─────
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

  -- ── 3. Receipt row ───────────────────────────────────────────────────────
  INSERT INTO public.receipts (
    firm_id, client_id, customer_id, receipt_no, receipt_date, amount_paise,
    tds_paise, unallocated_paise, payment_mode, reference_no, notes,
    journal_entry_id, created_at
  )
  VALUES (
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
    v_journal_id,
    COALESCE((p_receipt->>'created_at')::timestamptz, now())
  )
  RETURNING * INTO v_receipt_row;

  v_receipt_id := v_receipt_row.id;

  -- ── 4. Allocations — pre-aggregate duplicate rows per invoice, then lock,
  -- re-validate, update, record. (See migration 162 for the full rationale on
  -- pre-aggregation and row locking — unchanged here.)
  FOR v_invoice_id, v_allocated_paise IN
    SELECT (x->>'sales_invoice_id')::uuid, sum(COALESCE((x->>'allocated_paise')::bigint, 0))
      FROM jsonb_array_elements(p_allocations) AS x
     WHERE COALESCE((x->>'allocated_paise')::bigint, 0) > 0
     GROUP BY (x->>'sales_invoice_id')::uuid
  LOOP
    SELECT total_paise, paid_paise, credited_paise, debit_note_paise
      INTO v_total_paise, v_paid_paise, v_credited_paise, v_debit_note_paise
      FROM public.client_sales_invoices
     WHERE id = v_invoice_id
       AND firm_id = (p_receipt->>'firm_id')::uuid
       AND client_id = (p_receipt->>'client_id')::uuid
     FOR UPDATE;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'settle_receipt_atomic: invoice % is not part of this client''s books', v_invoice_id;
    END IF;

    -- A sales debit note (CGST Act §34(3)) increases what's collectible.
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

GRANT EXECUTE ON FUNCTION settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb) TO authenticated, service_role;
