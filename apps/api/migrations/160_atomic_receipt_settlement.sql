-- 160 — Atomic receipt→AR→journal settlement (R2.12, follow-up from R1.6/F7).
--
-- Problem
-- -------
-- R1.6 made receipt creation journal-first (post the GL journal, then insert
-- the receipt row, then settle each allocated invoice's paid_paise/status via
-- an app-level optimistic compare-and-set retry loop), so a failure partway
-- through is COMPENSATED (journal reversed, receipt deleted) rather than left
-- as a phantom entry. That closed the worst harm, but two residual gaps
-- remained (documented in services/receipt_service.py):
--   * if a receipt allocates to MULTIPLE invoices and an EARLIER invoice's
--     CAS already committed before a LATER one fails, that earlier invoice's
--     paid_paise/status is not rolled back — reverting a concurrent CAS write
--     safely needs its own transaction, which the app-level compensation
--     path doesn't have;
--   * R2.9 found the journal-first ordering can, via post_journal_atomic's
--     idempotency fast-path, observe and reference ANOTHER request's
--     already-committed journal on a numbering collision — the compensation
--     path had to grow an ownership check before it could safely reverse
--     anything.
--
-- Fix
-- ---
-- settle_receipt_atomic wraps the journal insert, the journal lines, the
-- receipt insert, and every allocated invoice's row-locked update in ONE
-- database transaction — a plpgsql function body is a single transaction, so
-- ANY failure (a bad account id, a receipt_no collision, a concurrent
-- over-allocation) rolls EVERYTHING back together. No partial state can ever
-- be observed, and no app-level compensation is needed for this path — there
-- is nothing to compensate, because nothing partial was ever committed. Each
-- allocated invoice row is locked with SELECT ... FOR UPDATE before its
-- outstanding is re-validated and updated, which serializes concurrent
-- settlements on the SAME invoice without an optimistic-retry loop — the row
-- lock IS the concurrency control.
--
-- Scope: this function does NOT attempt post_journal_atomic's idempotent-
-- retry-returns-existing-id behaviour. A retried/duplicate call (same
-- reference_no/entry_date, or a receipt_no collision from migration 159's
-- constraint) raises a unique_violation, which rolls back this ENTIRE
-- transaction and propagates to the caller — services/receipt_service.py
-- treats that as "please retry with a fresh sequence number" (mirroring
-- R2.9's existing 409 handling), rather than risk silently attributing a
-- different request's money movement to the caller (the exact class of bug
-- R2.9's adversarial review found in the journal-idempotency fast-path).
--
-- Used by services/receipt_service.py's create_receipt_core (the plain-INR
-- path only). create_foreign_receipt (multi-currency, FX gain/loss,
-- per-invoice rate resolution) stays on the existing journal-first +
-- compensate pattern — deliberately out of scope here, a smaller and
-- less-common surface where the existing (R2.9-hardened) compensation path
-- remains adequate; folding FX rate resolution and fx_adjustments into this
-- same atomic function is left as a follow-up if that path's residual risk
-- is later judged to warrant it.

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
  v_alloc           jsonb;
  v_invoice_id      uuid;
  v_total_paise     bigint;
  v_paid_paise      bigint;
  v_credited_paise  bigint;
  v_allocated_paise bigint;
  v_new_paid        bigint;
  v_new_status      text;
  v_alloc_results   jsonb := '[]'::jsonb;
BEGIN
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
  RETURNING id INTO v_receipt_id;

  -- ── 4. Allocations — lock each invoice, re-validate, update, record ─────
  -- The row lock (FOR UPDATE) serializes concurrent settlements on the SAME
  -- invoice: a second transaction touching the same row blocks here until
  -- this one commits or rolls back, so there is no read-check-write race to
  -- retry — unlike the app-level optimistic CAS loop this function replaces.
  FOR v_alloc IN SELECT * FROM jsonb_array_elements(p_allocations)
  LOOP
    v_allocated_paise := COALESCE((v_alloc->>'allocated_paise')::bigint, 0);
    IF v_allocated_paise <= 0 THEN
      CONTINUE;
    END IF;
    v_invoice_id := (v_alloc->>'sales_invoice_id')::uuid;

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
    'allocations', v_alloc_results
  );
END
$$;

GRANT EXECUTE ON FUNCTION settle_receipt_atomic(jsonb, jsonb, jsonb, jsonb) TO authenticated, service_role;
