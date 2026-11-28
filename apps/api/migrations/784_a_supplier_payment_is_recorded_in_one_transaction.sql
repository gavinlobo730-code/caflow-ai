-- Migration 784: a supplier payment is recorded in one transaction (POST-A-575, the database half).
--
-- WHAT IS WRONG TODAY
--   A customer receipt posts its entry, its row and every invoice it settles in ONE database transaction (settle_receipt_atomic,
--   migrations 160 to 782). A payment to a supplier does not, in any of its four shapes (one bill or several, rupees or a foreign
--   currency). The API reserves the bill or posts the entry first, then inserts the payment, then moves each bill with a
--   compare-and-set it retries, then writes the allocations and the record of the realised exchange difference, as separate
--   statements, and on a failure runs a compensation that reverses the entry, deletes the payment and gives the reservation back.
--   Under a real race between two payments for the same bills an earlier bill's paid amount is not rolled back when a later one
--   fails (the compensation logs the bill ids for a person to put right), and a compensation that itself fails leaves an entry in
--   the ledger with no payment behind it.
--
-- WHAT THIS DOES
--   It adds the function the API will call for all four shapes, on the receipt function's own shape (migration 781's body is the
--   model, read line by line, and nothing of it is changed):
--     settle_payment_atomic__unguarded(p_payment, p_journal_entry, p_journal_lines, p_allocations) writes, together or not at all,
--       * the entry and its lines (balanced, not nil, each line in the position it held in the array);
--       * the payment row, built from the payload's OWN keys, so a column the caller sends is stored or the call fails: nothing is
--         dropped in silence, which is how a receipt once lost its bank account (migration 574 records that);
--       * each bill it settles, under a row lock (FOR NO KEY UPDATE, taken in one order, by id: the payment row may itself name
--         the bill, and the stronger lock would deadlock two payments that do): the bill is this client's, was raised by the
--         payment's own supplier, is not a draft and not cancelled, has that much left, and its paid amount and status move;
--       * the allocation rows, for a payment across several bills. A payment that names its bill on its own row (the older shape,
--         which the reversal reads to know how to roll the bill back) settles that bill alone, for the payment's whole amount,
--         and writes no allocation row, exactly as it does today;
--       * for a payment in a foreign currency, the bill's foreign paid amount beside its rupee one, the bill 'paid' when its
--         foreign total is settled, and the record of the realised exchange difference. Each allocation says what the caller
--         read of the bill (expect_paid_paise, expect_paid_txn, and expect_debited_paise where sent), and the bill, once locked,
--         must still say the same or the WHOLE payment is refused with this function's own state VP001 for the caller to prepare
--         again. That is asked before any amount is judged. Never 40001: the gateway re-runs that state by itself and this
--         refusal is permanent for the payload that met it.
--     settle_payment_atomic(...) is the guarded door, the receipt wrapper's checks word for word (migration 546): the payment and
--       its journal name one firm and one client, a signed-in caller is asked who they are, the server's own call must name a
--       client of its firm, the posting person travels to the audit trigger, and the entry's date and the payment's date are each
--       asked of the closure (the firm's locked year, this client's finalised year-end).
--   Nothing is converted here: the rupee figures of a foreign payment are the caller's, checked by the compare under the lock, so
--   there is no second copy of the conversion rule in SQL. What the function CAN check of the caller's arithmetic it does: a
--   rupee payment's unallocated figure is its amount less what was allocated, no allocation relieves a negative amount, a payment
--   is not recorded as already reversed, and a foreign payment that names its bill relieves it of the cash paid plus the
--   realised difference (the figure the reversal later works out).
--
-- TWO REFUSALS THE API DOES NOT MAKE TODAY, AND WHY THEY ARE HERE
--   * A payment to one supplier cannot settle a bill raised by another. The single-bill route has always asked this; the route
--     for several bills never did, so one supplier's payment could mark another supplier's bill paid and both statements were
--     wrong (POST-A-580).
--   * A payment in rupees cannot settle a bill billed in a foreign currency. It would move the bill's rupee paid amount and not
--     its foreign one, so the bill never reaches 'paid' by its foreign total (the receipt function refuses the same since
--     migration 782).
--
-- NOTHING CALLS IT YET, and that is the order of the rollout: the function ships alone, in a pull request of its own, and the
--   service change that moves the four paths onto it follows once this is on production. Executable by the service role only.
--
-- Reversible: 784_..._rollback.sql drops both functions. Roll it back only with a service that does not call them.

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

CREATE OR REPLACE FUNCTION public.settle_payment_atomic__unguarded(
  p_payment jsonb,
  p_journal_entry jsonb,
  p_journal_lines jsonb,
  p_allocations jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_firm              uuid := NULLIF(p_payment->>'firm_id', '')::uuid;
  v_client            uuid := NULLIF(p_payment->>'client_id', '')::uuid;
  v_vendor            uuid := NULLIF(p_payment->>'vendor_id', '')::uuid;
  v_payment_id        uuid := NULLIF(p_payment->>'id', '')::uuid;
  v_single_bill       uuid := NULLIF(p_payment->>'purchase_bill_id', '')::uuid;
  v_ccy               text := upper(COALESCE(NULLIF(btrim(p_payment->>'txn_currency'), ''), 'INR'));
  v_foreign           boolean;
  v_journal_id        uuid;
  v_row               jsonb;
  v_keys              text;
  v_payment_row       public.purchase_payments;
  v_total_debit       bigint;
  v_total_credit      bigint;
  v_bill_id           uuid;
  v_bills             integer := 0;
  v_total_allocated   bigint := 0;
  v_allocated_paise   bigint;
  v_allocated_txn     bigint;
  v_expect_paid       bigint;
  v_expect_paid_txn   bigint;
  v_expect_debited    bigint;
  v_readings_agree    boolean;
  v_bill              record;
  v_new_paid          bigint;
  v_new_paid_txn      bigint;
  v_new_status        text;
  v_alloc_results     jsonb := '[]'::jsonb;
  v_fx                jsonb := p_payment->'fx_adjustment';
  v_fx_delta          bigint := 0;
BEGIN
  v_foreign := v_ccy <> 'INR';

  -- The payment's id is the caller's, chosen before the call, because the entry names the payment it belongs to (source_id) and the
  -- reversal finds the entry by it. An entry that names another document is a caller's defect and is said as one.
  IF v_payment_id IS NULL THEN
    RAISE EXCEPTION 'settle_payment_atomic: the payment carries no id';
  END IF;
  IF NULLIF(p_journal_entry->>'source_id', '')::uuid IS DISTINCT FROM v_payment_id THEN
    RAISE EXCEPTION 'settle_payment_atomic: the entry does not name this payment as its source';
  END IF;

  -- A payment is recorded live: the reversal is its own act, with its own entry.
  IF COALESCE((p_payment->>'is_reversed')::boolean, false) THEN
    RAISE EXCEPTION 'settle_payment_atomic: a payment is not recorded as already reversed';
  END IF;
  -- The realised exchange difference of a foreign payment, read here because the older shape's settlement is checked against it.
  IF v_foreign AND v_fx IS NOT NULL AND jsonb_typeof(v_fx) = 'object' THEN
    v_fx_delta := COALESCE(NULLIF(v_fx->>'base_delta_paise', '')::bigint, 0);
  END IF;

  -- 0. Balance/non-zero guard (mirrors phase2_journal_service._create_journal)
  SELECT COALESCE(sum(COALESCE((l->>'debit_paise')::bigint, 0)), 0),
         COALESCE(sum(COALESCE((l->>'credit_paise')::bigint, 0)), 0)
    INTO v_total_debit, v_total_credit
    FROM jsonb_array_elements(p_journal_lines) AS l;

  IF v_total_debit <> v_total_credit THEN
    RAISE EXCEPTION 'settle_payment_atomic: journal imbalance debit=% credit=% for ref=%',
      v_total_debit, v_total_credit, p_journal_entry->>'reference_no';
  END IF;
  IF v_total_debit = 0 THEN
    RAISE EXCEPTION 'settle_payment_atomic: refusing to post a zero-value journal entry for ref=%',
      p_journal_entry->>'reference_no';
  END IF;

  -- 1. Journal header: the columns the receipt function writes (migration 781), which are the ones the posting kernel stamps.
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
    v_payment_id,
    COALESCE((p_journal_entry->>'rate_overridden')::boolean, false),
    NULLIF(p_journal_entry->>'rate_selected_by', '')::uuid,
    NULLIF(p_journal_entry->>'rate_selected_at', '')::timestamptz
  )
  RETURNING id INTO v_journal_id;

  -- 2. Journal lines, each in the position it held in the array (journal_lines.line_order, migration 384).
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

  -- 3. The payment row, from the payload's OWN keys (the posting function's way, migration 384): a column the caller names is stored,
  -- a column it leaves out takes the table's default, and a key that is no column fails the whole call. `fx_adjustment` is the one
  -- key that is not the row's (it is the exchange record written at step 5), and the entry's id is this function's to set.
  v_row := (p_payment - 'fx_adjustment') || jsonb_build_object('journal_entry_id', v_journal_id);
  SELECT string_agg(quote_ident(k), ', ' ORDER BY k) INTO v_keys FROM jsonb_object_keys(v_row) AS k;
  EXECUTE format(
    'INSERT INTO public.purchase_payments (%1$s) '
    'SELECT %1$s FROM jsonb_populate_record(NULL::public.purchase_payments, $1) '
    'RETURNING *', v_keys
  ) INTO v_payment_row USING v_row;

  -- 4. The bills. Rows for one bill are one settlement and are added up first; the bills are locked in one order (by id), so two
  -- payments for the same bills wait for each other and cannot each hold what the other wants.
  FOR v_bill_id, v_allocated_paise, v_allocated_txn, v_expect_paid, v_expect_paid_txn, v_expect_debited, v_readings_agree IN
    SELECT (x->>'purchase_bill_id')::uuid,
           sum(COALESCE((x->>'allocated_paise')::bigint, 0)),
           sum(COALESCE(NULLIF(x->>'allocated_txn', '')::bigint, 0)),
           min(NULLIF(x->>'expect_paid_paise', '')::bigint),
           min(NULLIF(x->>'expect_paid_txn', '')::bigint),
           min(NULLIF(x->>'expect_debited_paise', '')::bigint),
           -- several rows for one bill must say ONE thing about what was read of it
           count(DISTINCT COALESCE(x->>'expect_paid_paise', '')) = 1
             AND count(DISTINCT COALESCE(x->>'expect_paid_txn', '')) = 1
             AND count(DISTINCT COALESCE(x->>'expect_debited_paise', '')) = 1
      FROM jsonb_array_elements(COALESCE(p_allocations, '[]'::jsonb)) AS x
     WHERE COALESCE((x->>'allocated_paise')::bigint, 0) > 0
        OR (v_foreign AND COALESCE(NULLIF(x->>'allocated_txn', '')::bigint, 0) > 0)
     GROUP BY (x->>'purchase_bill_id')::uuid
     ORDER BY 1
  LOOP
    v_bills := v_bills + 1;
    v_total_allocated := v_total_allocated + v_allocated_paise;

    SELECT b.status, b.vendor_id,
           COALESCE(b.net_payable_paise, 0) AS net_payable, COALESCE(b.paid_paise, 0) AS paid,
           COALESCE(b.debited_paise, 0) AS debited, COALESCE(b.credit_note_paise, 0) AS credit_note,
           upper(COALESCE(NULLIF(btrim(b.txn_currency), ''), 'INR')) AS ccy,
           COALESCE(b.txn_net_payable, 0) AS txn_net_payable, COALESCE(b.paid_txn, 0) AS paid_txn
      INTO v_bill
      FROM public.purchase_bills b
     WHERE b.id = v_bill_id
       AND b.firm_id = v_firm
       AND b.client_id = v_client
     -- FOR NO KEY UPDATE, and not FOR UPDATE. The payment row inserted at step 3 may name this bill (purchase_bill_id), and its
     -- foreign-key check holds FOR KEY SHARE on the bill until the transaction ends. FOR UPDATE conflicts with that: two payments
     -- that name the same bill would each hold the key share and each wait for the other's to go, and one would be killed as a
     -- deadlock (the window migration 572 closed on the receipt side). NO KEY UPDATE is what the UPDATE below takes anyway (it
     -- changes no key column); it lets a key share stand and still makes the second payment wait for the first.
     FOR NO KEY UPDATE;

    IF NOT FOUND THEN
      RAISE EXCEPTION 'settle_payment_atomic: bill % is not part of this client''s books', v_bill_id;
    END IF;

    -- A payment that names its bill on its own row settles that bill and no other (the reversal rolls that one bill back).
    IF v_single_bill IS NOT NULL AND v_bill_id <> v_single_bill THEN
      RAISE EXCEPTION 'settle_payment_atomic: the payment names bill % and its settlement names bill %', v_single_bill, v_bill_id;
    END IF;

    -- One supplier's payment does not settle another supplier's bill (POST-A-580): both statements would be wrong.
    IF v_bill.vendor_id IS DISTINCT FROM v_vendor THEN
      RAISE EXCEPTION 'settle_payment_atomic: bill % was raised by another supplier', v_bill_id;
    END IF;

    -- A draft bill was never received (no payable was posted) and a cancelled one is terminal: neither can be paid.
    IF v_bill.status IN ('draft', 'cancelled') THEN
      RAISE EXCEPTION 'settle_payment_atomic: bill % is % and cannot be paid', v_bill_id, v_bill.status;
    END IF;

    -- A settlement never takes rupees back from a bill. (A foreign row is admitted by its foreign amount alone, so its rupees are
    -- asked here: a bill whose debit notes exceed what was left would otherwise be "relieved" of a negative figure.)
    IF v_allocated_paise < 0 THEN
      RAISE EXCEPTION 'settle_payment_atomic: the allocation to bill % relieves a negative amount', v_bill_id;
    END IF;

    v_new_paid := v_bill.paid + v_allocated_paise;

    IF v_foreign THEN
      -- A FOREIGN payment's amounts mean something only against the bill the caller read, so whether the bill still reads the
      -- same is asked BEFORE any amount is judged: a payment that lost a race is told so (VP001, prepare it again), never that
      -- its stale rupee figure "exceeds the outstanding".
      IF v_bill.ccy <> v_ccy THEN
        RAISE EXCEPTION 'settle_payment_atomic: the payment is in % and bill % is billed in %', v_ccy, v_bill_id, v_bill.ccy;
      END IF;
      IF v_allocated_txn <= 0 THEN
        RAISE EXCEPTION 'settle_payment_atomic: the allocation to bill % names no foreign amount', v_bill_id;
      END IF;
      IF NOT v_readings_agree THEN
        RAISE EXCEPTION 'settle_payment_atomic: the allocations to bill % do not agree about what was read of the bill', v_bill_id;
      END IF;
      IF v_expect_paid IS NULL OR v_expect_paid_txn IS NULL THEN
        RAISE EXCEPTION 'settle_payment_atomic: the allocation to bill % does not say what was read of the bill (expect_paid_paise, expect_paid_txn)', v_bill_id;
      END IF;
      IF v_bill.paid <> v_expect_paid OR v_bill.paid_txn <> v_expect_paid_txn
         OR (v_expect_debited IS NOT NULL AND v_bill.debited <> v_expect_debited) THEN
        -- VP001, a state of this function's own, and NOT serialization_failure (40001), which the gateway re-runs by itself: this
        -- refusal is permanent for the payload that met it (the figures have to be worked out again), so a re-run could only loop.
        RAISE EXCEPTION 'settle_payment_atomic: bill % changed while this payment was being prepared', v_bill_id
          USING ERRCODE = 'VP001';
      END IF;
    ELSIF v_bill.ccy <> 'INR' THEN
      -- A rupee payment would move the bill's rupee paid amount and not its foreign one (the receipt function's rule, migration 782).
      RAISE EXCEPTION 'settle_payment_atomic: the payment is in rupees and bill % is billed in %', v_bill_id, v_bill.ccy;
    END IF;

    -- What is payable: the bill's net payable, raised by a purchase credit note (the increase document, migration 210) and
    -- already reduced by what was paid and by debit notes.
    IF v_new_paid + v_bill.debited > v_bill.net_payable + v_bill.credit_note THEN
      RAISE EXCEPTION 'settle_payment_atomic: allocation to bill % (% paise) exceeds its outstanding', v_bill_id, v_allocated_paise;
    END IF;

    IF v_foreign THEN
      IF v_allocated_txn > v_bill.txn_net_payable - v_bill.paid_txn THEN
        RAISE EXCEPTION 'settle_payment_atomic: allocation to bill % (% in %) exceeds its outstanding', v_bill_id, v_allocated_txn, v_ccy;
      END IF;
      -- the older shape's reversal gives the bill back the payment's whole foreign amount, so that is what it must have taken
      IF v_single_bill IS NOT NULL AND v_allocated_txn IS DISTINCT FROM NULLIF(p_payment->>'txn_amount', '')::bigint THEN
        RAISE EXCEPTION 'settle_payment_atomic: a payment that names its bill settles it for the payment''s whole foreign amount';
      END IF;
      -- and the rupees it relieves are the cash that left plus the realised difference, which is the figure the reversal works
      -- out from the payment's row and the exchange record when it gives the bill its money back
      IF v_single_bill IS NOT NULL
         AND v_allocated_paise IS DISTINCT FROM COALESCE((p_payment->>'amount_paise')::bigint, 0) + v_fx_delta THEN
        RAISE EXCEPTION 'settle_payment_atomic: a payment that names its bill relieves it of the cash paid plus the exchange difference';
      END IF;
      v_new_paid_txn := v_bill.paid_txn + v_allocated_txn;
      -- a foreign bill is paid when its FOREIGN total is settled; the rupees clear exactly because the caller snaps the last
      -- settlement to what is left
      v_new_status := CASE WHEN v_new_paid_txn >= v_bill.txn_net_payable THEN 'paid' ELSE 'partially_paid' END;

      UPDATE public.purchase_bills
         SET paid_paise = v_new_paid, paid_txn = v_new_paid_txn, status = v_new_status, updated_at = now()
       WHERE id = v_bill_id;

      IF v_single_bill IS NULL THEN
        INSERT INTO public.purchase_payment_allocations (purchase_payment_id, purchase_bill_id, allocated_paise, allocated_txn)
        VALUES (v_payment_row.id, v_bill_id, v_allocated_paise, v_allocated_txn);
      END IF;

      v_alloc_results := v_alloc_results || jsonb_build_object(
        'purchase_bill_id', v_bill_id,
        'allocated_paise', v_allocated_paise,
        'allocated_txn', v_allocated_txn,
        'new_paid_paise', v_new_paid,
        'new_paid_txn', v_new_paid_txn,
        'new_status', v_new_status
      );
    ELSE
      -- the older shape's reversal gives the bill back the payment's whole amount, so that is what it must have taken
      IF v_single_bill IS NOT NULL AND v_allocated_paise IS DISTINCT FROM COALESCE((p_payment->>'amount_paise')::bigint, 0) THEN
        RAISE EXCEPTION 'settle_payment_atomic: a payment that names its bill settles it for the payment''s whole amount';
      END IF;
      v_new_status := CASE WHEN v_new_paid + v_bill.debited >= v_bill.net_payable + v_bill.credit_note
                            THEN 'paid' ELSE 'partially_paid' END;

      UPDATE public.purchase_bills
         SET paid_paise = v_new_paid, status = v_new_status, updated_at = now()
       WHERE id = v_bill_id;

      IF v_single_bill IS NULL THEN
        INSERT INTO public.purchase_payment_allocations (purchase_payment_id, purchase_bill_id, allocated_paise)
        VALUES (v_payment_row.id, v_bill_id, v_allocated_paise);
      END IF;

      v_alloc_results := v_alloc_results || jsonb_build_object(
        'purchase_bill_id', v_bill_id,
        'allocated_paise', v_allocated_paise,
        'new_paid_paise', v_new_paid,
        'new_status', v_new_status
      );
    END IF;
  END LOOP;

  -- A payment that names its bill and settled nothing has claimed a bill it did not pay.
  IF v_single_bill IS NOT NULL AND v_bills <> 1 THEN
    RAISE EXCEPTION 'settle_payment_atomic: the payment names bill % and settles nothing against it', v_single_bill;
  END IF;

  -- What a RUPEE payment says is left of it (the advance: the AP ageing and a later re-allocation read it) is its amount less
  -- what this call gave to bills. A foreign payment's is carried at the payment's own rate and is the caller's figure.
  IF NOT v_foreign AND v_payment_row.unallocated_paise IS DISTINCT FROM v_payment_row.amount_paise - v_total_allocated THEN
    RAISE EXCEPTION 'settle_payment_atomic: the payment says % paise are left of it and % are (amount % less % allocated)',
      v_payment_row.unallocated_paise, v_payment_row.amount_paise - v_total_allocated, v_payment_row.amount_paise, v_total_allocated;
  END IF;

  -- 5. The realised exchange difference of a foreign payment: its record is written with the payment, the entry and the
  -- settlements, or not at all.
  IF v_foreign AND v_fx IS NOT NULL AND jsonb_typeof(v_fx) = 'object' THEN
    IF v_fx_delta <> 0 THEN
      INSERT INTO public.fx_adjustments (
        firm_id, client_id, kind, document_type, document_id, currency,
        settlement_rate, base_delta_paise, journal_entry_id, rate_source, created_by
      )
      VALUES (
        v_firm, v_client, 'realized', 'purchase_payment', v_payment_row.id, v_ccy,
        NULLIF(v_fx->>'settlement_rate', '')::numeric, v_fx_delta, v_journal_id,
        NULLIF(v_fx->>'rate_source', ''), NULLIF(v_fx->>'created_by', '')::uuid
      );
    END IF;
  END IF;

  RETURN jsonb_build_object(
    'payment_id', v_payment_row.id,
    'journal_entry_id', v_journal_id,
    'payment', to_jsonb(v_payment_row),
    'allocations', v_alloc_results,
    'realized_fx_paise', v_fx_delta
  );
END
$$;

COMMENT ON FUNCTION public.settle_payment_atomic__unguarded(jsonb, jsonb, jsonb, jsonb) IS
    'The body of settle_payment_atomic (migration 784), reached only through the wrapper: a supplier payment''s entry, row, bill settlements, allocation rows and realised exchange difference in one transaction.';


-- ── the guarded door: the receipt wrapper's checks (migration 546), for a payment ──
CREATE OR REPLACE FUNCTION public.settle_payment_atomic(p_payment jsonb, p_journal_entry jsonb, p_journal_lines jsonb, p_allocations jsonb)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_reason text;
    v_date   text;
    v_day    date;
BEGIN
    -- The payment and its journal must name the same firm and client, for everyone: the function takes each from
    -- its own payload, so a mismatch is a payment for one client posted against another's books.
    IF NULLIF(p_payment->>'firm_id', '')::uuid   IS DISTINCT FROM NULLIF(p_journal_entry->>'firm_id', '')::uuid
       OR NULLIF(p_payment->>'client_id', '')::uuid IS DISTINCT FROM NULLIF(p_journal_entry->>'client_id', '')::uuid THEN
        RAISE EXCEPTION 'settle_payment_atomic: the payment and its journal name different firms or clients'
            USING ERRCODE = '42501';
    END IF;
    -- accounting:write is Manager; a bank match settles payments as an Executive (banking:write). No signed-in caller holds
    -- EXECUTE (below); a grant restored by hand would meet these checks.
    PERFORM public.assert_caller_acts_for('settle_payment_atomic',
        NULLIF(p_journal_entry->>'firm_id', '')::uuid, NULLIF(p_journal_entry->>'client_id', '')::uuid,
        '[["accounting","write","Manager"],["banking","write","Executive"]]'::jsonb);

    -- THE SERVER'S OWN CALL NAMES A CLIENT OF ITS FIRM (migration 546's rule): with no auth.uid() the check above returned
    -- without asking anything. A NULL firm or client names no such client.
    IF auth.uid() IS NULL AND NOT EXISTS (
            SELECT 1 FROM public.clients c WHERE c.id = NULLIF(p_journal_entry->>'client_id', '')::uuid AND c.firm_id = NULLIF(p_journal_entry->>'firm_id', '')::uuid) THEN
        RAISE EXCEPTION 'settle_payment_atomic: client % is not a client of firm %', NULLIF(p_journal_entry->>'client_id', '')::uuid, NULLIF(p_journal_entry->>'firm_id', '')::uuid USING ERRCODE = '42501';
    END IF;
    -- The payment, the bill settlement and the journal are audited as the poster (migration 545).
    PERFORM public.carry_audit_actor(p_journal_entry->>'audit_actor', p_journal_entry->>'created_by', NULLIF(p_journal_entry->>'firm_id', '')::uuid);
    -- THE CLOSURE (migration 533's rule): the journal's date and the payment's own date, each against the firm's locked year and
    -- this client's finalised year-end. A date that is missing or cannot be read is a refusal.
    FOREACH v_date IN ARRAY ARRAY[p_journal_entry->>'entry_date', p_payment->>'payment_date'] LOOP
        BEGIN
            IF v_date IS NULL OR v_date = '' THEN
                RAISE invalid_datetime_format;
            END IF;
            v_day := v_date::date;
            IF v_day = 'infinity'::date OR v_day = '-infinity'::date THEN
                RAISE invalid_datetime_format;
            END IF;
            v_reason := public.period_closure_reason(
                NULLIF(p_journal_entry->>'firm_id', '')::uuid, NULLIF(p_journal_entry->>'client_id', '')::uuid, v_day);
        EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow OR invalid_text_representation THEN
            RAISE EXCEPTION 'settle_payment_atomic: ''%'' is not a posting date. Use YYYY-MM-DD: a date this cannot read is a date the year-end lock cannot be checked against.', v_date
                USING ERRCODE = '22007';
        END;
        IF v_reason IS NOT NULL THEN
            RAISE EXCEPTION '%', v_reason;
        END IF;
    END LOOP;
    RETURN public.settle_payment_atomic__unguarded(p_payment, p_journal_entry - 'audit_actor', p_journal_lines, p_allocations);
END;
$fn$;

COMMENT ON FUNCTION public.settle_payment_atomic(jsonb, jsonb, jsonb, jsonb) IS
    'Records a supplier payment in one transaction (migration 784): asks who is calling, that the client is the firm''s, and that neither date falls in a closed year, then runs settle_payment_atomic__unguarded. The server''s alone.';

-- ── who may call them: the server, and nobody signed in ──
REVOKE ALL ON FUNCTION public.settle_payment_atomic(jsonb, jsonb, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.settle_payment_atomic__unguarded(jsonb, jsonb, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.settle_payment_atomic(jsonb, jsonb, jsonb, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.settle_payment_atomic__unguarded(jsonb, jsonb, jsonb, jsonb) TO service_role;

DO $$
DECLARE
    v_fn regprocedure;
BEGIN
    FOREACH v_fn IN ARRAY ARRAY['public.settle_payment_atomic(jsonb, jsonb, jsonb, jsonb)'::regprocedure,
                                'public.settle_payment_atomic__unguarded(jsonb, jsonb, jsonb, jsonb)'::regprocedure] LOOP
        IF has_function_privilege('authenticated', v_fn, 'EXECUTE') OR has_function_privilege('anon', v_fn, 'EXECUTE') THEN
            RAISE EXCEPTION 'migration 784: % is executable by a signed-in or anonymous user', v_fn; END IF;
        IF NOT has_function_privilege('service_role', v_fn, 'EXECUTE') THEN
            RAISE EXCEPTION 'migration 784: % is not executable by the service role', v_fn; END IF;
        IF NOT (SELECT p.prosecdef FROM pg_proc p WHERE p.oid = v_fn) THEN
            RAISE EXCEPTION 'migration 784: % is not SECURITY DEFINER', v_fn; END IF;
    END LOOP;
END
$$;

COMMIT;
