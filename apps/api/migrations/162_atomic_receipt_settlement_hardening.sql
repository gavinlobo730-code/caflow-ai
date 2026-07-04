-- 162 — Harden settle_receipt_atomic (R2.12 adversarial-review fix phase).
--
-- An independent adversarial review of migration 160 (2 lenses, each finding
-- re-verified by a separate skeptical agent, several reproduced directly
-- against real Postgres) confirmed three defects inside the function itself
-- (a fourth, the payment_mode CHECK mismatch, was fixed in migration 161).
-- This migration replaces the function (CREATE OR REPLACE, same signature —
-- additive, does not touch 160's own file) with all three fixes:
--
-- 1. No balance/zero-value guard. phase2_journal_service._create_journal
--    (the path every OTHER journal post still goes through) refuses to post
--    an imbalanced or all-zero journal entry (its own comment: "a
--    balanced-but-zero journal is meaningless — never post it"). This
--    function bypassed _create_journal entirely and had no equivalent check
--    of its own — today's only caller (receipt_journal_lines) always builds
--    balanced, non-zero lines, so nothing is currently exploitable, but any
--    future change to that caller, or any future caller built on this same
--    pattern, could silently post a permanently-immutable (journal-
--    immutability trigger, migrations 055/058) broken entry into a firm's
--    real general ledger with zero errors anywhere. Fixed: the same two
--    checks _create_journal performs (debit == credit, total != 0), run
--    BEFORE any insert.
--
-- 2. A second, valid allocation row for the SAME sales_invoice_id in one
--    p_allocations payload always rolled back the whole settlement — the
--    per-row loop's outstanding-balance arithmetic was correct across both
--    rows (no TOCTOU), but the second INSERT INTO receipt_allocations then
--    violated its UNIQUE(receipt_id, sales_invoice_id) constraint (migration
--    050). This contradicted services/receipt_service.py's own pre-
--    validation comment, which states multiple allocation rows for one
--    invoice are meant to be summed and supported. Fails safe (full
--    rollback, confirmed against real Postgres — no book corruption), but
--    is a real availability gap for any caller that emits more than one row
--    per invoice per receipt. Fixed: allocations are now pre-aggregated by
--    sales_invoice_id (summing allocated_paise) before the per-invoice
--    lock+validate+update loop, so duplicate rows for the same invoice are
--    combined instead of colliding.
--
-- 3. The returned jsonb only carried receipt_id/journal_entry_id/allocations
--    (not the full receipt row), so services/receipt_service.py's audit
--    log_event had to reconstruct new_data from the Python-side payload it
--    sent — silently omitting DB-default columns (allocated_paise,
--    updated_at) that the pre-atomicity path's equivalent audit entries
--    always included for the identical logical event. Fixed: the function
--    now returns the full inserted receipts row (via RETURNING * into a
--    record, embedded as the 'receipt' key) alongside the existing keys, so
--    the caller can log the actual DB row instead of reconstructing one.
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
  v_journal_id      uuid;
  v_receipt_id      uuid;
  v_receipt_row     public.receipts;
  v_invoice_id      uuid;
  v_total_paise     bigint;
  v_paid_paise      bigint;
  v_credited_paise  bigint;
  v_allocated_paise bigint;
  v_new_paid        bigint;
  v_new_status      text;
  v_alloc_results   jsonb := '[]'::jsonb;
  v_total_debit     bigint;
  v_total_credit    bigint;
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
  -- re-validate, update, record. Pre-aggregation means a caller sending TWO
  -- allocation rows for the same invoice (summed client-side or not) is
  -- treated identically to one row carrying their sum — matching
  -- services/receipt_service.py's own pre-validation, which already sums
  -- multiple rows per invoice for its outstanding check. The row lock
  -- (FOR UPDATE) serializes concurrent settlements on the SAME invoice: a
  -- second transaction touching the same row blocks here until this one
  -- commits or rolls back, so there is no read-check-write race to retry —
  -- unlike the app-level optimistic CAS loop this function replaces.
  FOR v_invoice_id, v_allocated_paise IN
    SELECT (x->>'sales_invoice_id')::uuid, sum(COALESCE((x->>'allocated_paise')::bigint, 0))
      FROM jsonb_array_elements(p_allocations) AS x
     WHERE COALESCE((x->>'allocated_paise')::bigint, 0) > 0
     GROUP BY (x->>'sales_invoice_id')::uuid
  LOOP
    SELECT total_paise, paid_paise, credited_paise
      INTO v_total_paise, v_paid_paise, v_credited_paise
      FROM public.client_sales_invoices
     WHERE id = v_invoice_id
       AND firm_id = (p_receipt->>'firm_id')::uuid
       AND client_id = (p_receipt->>'client_id')::uuid
     FOR UPDATE;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'settle_receipt_atomic: invoice % is not part of this client''s books', v_invoice_id;
    END IF;

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
