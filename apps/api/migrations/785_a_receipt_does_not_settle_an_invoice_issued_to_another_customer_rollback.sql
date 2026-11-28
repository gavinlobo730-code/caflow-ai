-- Rollback of migration 785: the receipt function's body as migration 782 left it (a receipt is no longer refused another
-- customer's invoice by the database; the API still refuses it).

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

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
  -- migration 781: a receipt in a foreign currency
  v_ccy               text := upper(COALESCE(NULLIF(btrim(p_receipt->>'txn_currency'), ''), 'INR'));
  v_foreign           boolean;
  v_invoice_ccy       text;
  v_txn_total         bigint;
  v_paid_txn          bigint;
  v_allocated_txn     bigint;
  v_new_paid_txn      bigint;
  v_expect_paid       bigint;
  v_expect_paid_txn   bigint;
  v_expect_credited   bigint;
  v_readings_agree    boolean;
  v_fx                jsonb := p_receipt->'fx_adjustment';
  v_fx_delta          bigint := 0;
BEGIN
  v_foreign := v_ccy <> 'INR';

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

  -- 1. Journal header. The three rate columns are what the posting kernel stamps when a rate was chosen (migration 781): for a
  -- rupee receipt the payload carries none of them and the row takes the same values the column defaults gave it.
  INSERT INTO public.journal_entries (
    firm_id, client_id, entry_date, reference_no, narration, entry_type,
    is_posted, status, posted_at, posted_by, created_by, source_type, source_id,
    rate_overridden, rate_selected_by, rate_selected_at
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
    NULLIF(p_journal_entry->>'source_id', '')::uuid,
    COALESCE((p_journal_entry->>'rate_overridden')::boolean, false),
    NULLIF(p_journal_entry->>'rate_selected_by', '')::uuid,
    NULLIF(p_journal_entry->>'rate_selected_at', '')::timestamptz
  )
  RETURNING id INTO v_journal_id;

  -- 2. Journal lines (same transaction -- no orphan header possible)
  -- `line_order` (migration 781): the position each line held in the array, as post_journal_atomic and edit_posted_journal record it
  -- (migration 384). This function never did, so a receipt's lines were shown in the fallback order (debits, then credits); a foreign
  -- receipt used to be posted through post_journal_atomic and would have lost the order it had.
  INSERT INTO public.journal_lines (
    journal_entry_id, account_id, debit_paise, credit_paise, narration,
    txn_currency, base_currency, exchange_rate, txn_debit, txn_credit,
    rate_source, rate_type, rate_date, line_order
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
    NULLIF(l->>'rate_date', '')::date,
    (ord - 1)::integer
  FROM jsonb_array_elements(p_journal_lines) WITH ORDINALITY AS t(l, ord);

  -- 3. Receipt row. The eight currency columns (migration 781) default to what the table's own defaults are, so a rupee receipt,
  -- whose payload names none of them, is stored exactly as it was.
  INSERT INTO public.receipts (
    id, firm_id, client_id, customer_id, receipt_no, receipt_date, amount_paise,
    tds_paise, unallocated_paise, payment_mode, reference_no, notes,
    bank_account_id, gst_rate_bps, place_of_supply, is_interstate,
    journal_entry_id, created_at,
    txn_currency, exchange_rate, txn_amount, rate_source, rate_type, rate_date, rate_selected_by, rate_overridden
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
    COALESCE((p_receipt->>'created_at')::timestamptz, now()),
    v_ccy,
    COALESCE(NULLIF(p_receipt->>'exchange_rate', '')::numeric, 1),
    NULLIF(p_receipt->>'txn_amount', '')::bigint,
    NULLIF(p_receipt->>'rate_source', ''),
    COALESCE(NULLIF(p_receipt->>'rate_type', ''), 'booking'),
    NULLIF(p_receipt->>'rate_date', '')::date,
    NULLIF(p_receipt->>'rate_selected_by', '')::uuid,
    COALESCE((p_receipt->>'rate_overridden')::boolean, false)
  )
  RETURNING * INTO v_receipt_row;

  v_receipt_id := v_receipt_row.id;

  -- 4. Allocations -- pre-aggregate duplicate rows per invoice, then lock,
  -- re-validate, update, record. (See migration 162 for the full rationale on
  -- pre-aggregation and row locking -- unchanged here.)
  --
  -- A FOREIGN receipt (migration 781) settles each invoice in TWO amounts: `allocated_txn`, the foreign money applied, and
  -- `allocated_paise`, the rupees of receivable it relieves at the INVOICE's own booked rate. The second was worked out by the
  -- caller from a read of the invoice taken before this transaction, so each row also says what that read saw
  -- (`expect_paid_paise`, `expect_paid_txn`, `expect_credited_paise`) and the row, once locked, must still say the same: if
  -- another settlement or a credit note landed in between, the rupee figure (and the journal built from it) is stale and the
  -- whole receipt is refused (state RC001) for the caller to prepare again. Nothing is recomputed here, so there
  -- is no second copy of the conversion rule.
  FOR v_invoice_id, v_allocated_paise, v_allocated_txn, v_expect_paid, v_expect_paid_txn, v_expect_credited, v_readings_agree IN
    SELECT (x->>'sales_invoice_id')::uuid,
           sum(COALESCE((x->>'allocated_paise')::bigint, 0)),
           sum(COALESCE(NULLIF(x->>'allocated_txn', '')::bigint, 0)),
           min(NULLIF(x->>'expect_paid_paise', '')::bigint),
           min(NULLIF(x->>'expect_paid_txn', '')::bigint),
           min(NULLIF(x->>'expect_credited_paise', '')::bigint),
           -- several rows for one invoice are one settlement, so they must say ONE thing about what was read of it
           count(DISTINCT COALESCE(x->>'expect_paid_paise', '')) = 1
             AND count(DISTINCT COALESCE(x->>'expect_paid_txn', '')) = 1
             AND count(DISTINCT COALESCE(x->>'expect_credited_paise', '')) = 1
      FROM jsonb_array_elements(p_allocations) AS x
     WHERE COALESCE((x->>'allocated_paise')::bigint, 0) > 0
        OR (v_foreign AND COALESCE(NULLIF(x->>'allocated_txn', '')::bigint, 0) > 0)
     GROUP BY (x->>'sales_invoice_id')::uuid
  LOOP
    SELECT status, total_paise, paid_paise, credited_paise, debit_note_paise,
           upper(COALESCE(NULLIF(btrim(txn_currency), ''), 'INR')), COALESCE(txn_total, 0), COALESCE(paid_txn, 0)
      INTO v_invoice_status, v_total_paise, v_paid_paise, v_credited_paise, v_debit_note_paise,
           v_invoice_ccy, v_txn_total, v_paid_txn
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

    -- A FOREIGN receipt's amounts mean something only against the invoice the caller read, so whether the invoice still reads the
    -- same is asked BEFORE any amount is judged: a receipt that lost a race is told so (RC001, prepare it again), never that its
    -- stale rupee figure "exceeds the outstanding", which is what the amount check below would say of the same receipt.
    IF v_foreign THEN
      IF v_invoice_ccy <> v_ccy THEN
        RAISE EXCEPTION 'settle_receipt_atomic: the receipt is in % and invoice % is billed in %', v_ccy, v_invoice_id, v_invoice_ccy;
      END IF;
      IF v_allocated_txn <= 0 THEN
        RAISE EXCEPTION 'settle_receipt_atomic: the allocation to invoice % names no foreign amount', v_invoice_id;
      END IF;
      -- A foreign allocation that does not say what was read of the invoice cannot be checked at all: that is a caller's defect, said
      -- as one, and never the "changed" refusal a caller answers by preparing the receipt again.
      IF NOT v_readings_agree THEN
        RAISE EXCEPTION 'settle_receipt_atomic: the allocations to invoice % do not agree about what was read of the invoice', v_invoice_id;
      END IF;
      IF v_expect_paid IS NULL OR v_expect_paid_txn IS NULL THEN
        RAISE EXCEPTION 'settle_receipt_atomic: the allocation to invoice % does not say what was read of the invoice (expect_paid_paise, expect_paid_txn)', v_invoice_id;
      END IF;
      IF COALESCE(v_paid_paise, 0) <> v_expect_paid OR v_paid_txn <> v_expect_paid_txn
         OR (v_expect_credited IS NOT NULL AND COALESCE(v_credited_paise, 0) <> v_expect_credited) THEN
        -- RC001, a state of this function's own, and NOT serialization_failure (40001). PostgREST runs every request inside a
        -- transaction that its database library re-runs by itself when the server answers 40001 (read in PostgREST's source by the
        -- review of this change; not tried against the live gateway), and this refusal is permanent for the payload that met it
        -- (the figures have to be worked out again), so a re-run could only loop.
        RAISE EXCEPTION 'settle_receipt_atomic: invoice % changed while this receipt was being prepared', v_invoice_id
          USING ERRCODE = 'RC001';
      END IF;
    END IF;

    -- A RUPEE receipt does not settle an invoice billed in a foreign currency (migration 782). It moved the rupees paid and left the
    -- foreign amount paid at nothing, so the invoice read 'paid' by its rupee total with its whole foreign amount outstanding and no
    -- realised difference recorded. The API refuses it first, in a person's words; this is the second lock.
    IF NOT v_foreign AND v_invoice_ccy <> 'INR' THEN
      RAISE EXCEPTION 'settle_receipt_atomic: the receipt is in INR and invoice % is billed in %', v_invoice_id, v_invoice_ccy;
    END IF;

    IF v_new_paid + COALESCE(v_credited_paise, 0) > v_total_paise THEN
      RAISE EXCEPTION 'settle_receipt_atomic: allocation to invoice % (% paise) exceeds its outstanding',
        v_invoice_id, v_allocated_paise;
    END IF;

    IF v_foreign THEN
      IF v_allocated_txn > v_txn_total - v_paid_txn THEN
        RAISE EXCEPTION 'settle_receipt_atomic: allocation to invoice % (% in %) exceeds its outstanding',
          v_invoice_id, v_allocated_txn, v_ccy;
      END IF;
      v_new_paid_txn := v_paid_txn + v_allocated_txn;
      -- a foreign invoice is paid when its FOREIGN total is settled; the rupees clear exactly because the caller snaps the last
      -- settlement to what is left
      v_new_status := CASE WHEN v_new_paid_txn >= v_txn_total THEN 'paid' ELSE 'partially_paid' END;

      UPDATE public.client_sales_invoices
         SET paid_paise = v_new_paid, paid_txn = v_new_paid_txn, status = v_new_status
       WHERE id = v_invoice_id;

      INSERT INTO public.receipt_allocations (receipt_id, sales_invoice_id, allocated_paise, allocated_txn)
      VALUES (v_receipt_id, v_invoice_id, v_allocated_paise, v_allocated_txn);

      v_alloc_results := v_alloc_results || jsonb_build_object(
        'sales_invoice_id', v_invoice_id,
        'allocated_paise', v_allocated_paise,
        'allocated_txn', v_allocated_txn,
        'new_paid_paise', v_new_paid,
        'new_paid_txn', v_new_paid_txn,
        'new_status', v_new_status
      );
    ELSE
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
    END IF;
  END LOOP;

  -- 5. The realised exchange difference of a foreign receipt (migration 781): the record of it is written with the receipt, the
  -- entry and the settlements, or not at all. It used to be a separate write after them.
  IF v_foreign AND v_fx IS NOT NULL AND jsonb_typeof(v_fx) = 'object' THEN
    v_fx_delta := COALESCE(NULLIF(v_fx->>'base_delta_paise', '')::bigint, 0);
    IF v_fx_delta <> 0 THEN
      INSERT INTO public.fx_adjustments (
        firm_id, client_id, kind, document_type, document_id, currency,
        settlement_rate, base_delta_paise, journal_entry_id, rate_source, created_by
      )
      VALUES (
        (p_receipt->>'firm_id')::uuid, (p_receipt->>'client_id')::uuid, 'realized', 'receipt', v_receipt_id, v_ccy,
        NULLIF(v_fx->>'settlement_rate', '')::numeric, v_fx_delta, v_journal_id,
        NULLIF(v_fx->>'rate_source', ''), NULLIF(v_fx->>'created_by', '')::uuid
      );
    END IF;
  END IF;

  RETURN jsonb_build_object(
    'receipt_id', v_receipt_id,
    'journal_entry_id', v_journal_id,
    'receipt', to_jsonb(v_receipt_row),
    'allocations', v_alloc_results,
    'realized_fx_paise', v_fx_delta
  );
END
$$;

COMMENT ON FUNCTION public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb) IS
    'The body of settle_receipt_atomic (migration 235), reached only through the wrapper of migration 546. Migration 574: the receipt row also stores id, bank_account_id, gst_rate_bps, place_of_supply and is_interstate. Migration 782: a rupee receipt is refused an invoice billed in a foreign currency. Migration 781: a foreign-currency receipt (txn_currency other than INR) settles each invoice in its foreign and rupee amounts under one lock, refuses an invoice that changed since the caller read it, and writes its realised exchange difference in the same transaction.';

-- The privileges are not this migration's to change; it says so by checking them.
DO $$
BEGIN
    IF has_function_privilege('authenticated', 'public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)'::regprocedure, 'EXECUTE')
       OR has_function_privilege('anon', 'public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)'::regprocedure, 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 782: the unguarded receipt body is executable by a signed-in or anonymous user';
    END IF;
    IF NOT (SELECT p.prosecdef FROM pg_proc p WHERE p.oid = 'public.settle_receipt_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)'::regprocedure) THEN
        RAISE EXCEPTION 'migration 782: the receipt body lost SECURITY DEFINER';
    END IF;
END
$$;

COMMIT;
