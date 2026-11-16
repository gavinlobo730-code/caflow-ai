-- Migration 650: what the issued invoices bill against a sales-order line is held by the database (ledger POST-A-440).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Migration 589 gave an invoice line `sales_order_line_id`, and the API refuses an invoice whose lines bill more of an order line than
-- is left (`sales_cycle_service.check_invoice_lines_against_orders`, with `domain/sales/order_cycle.over_billing` as the rule), on save
-- and again at issue. Each check READS what the other invoices bill and the write comes after, in another request; two issues made at
-- the same moment can each read the other as a draft (the issue check counts a draft, so two drafts saved together are refused, but two
-- drafts ISSUED together each see the other unissued at the moment of the read, and both pass). Ten ordered could be billed as twelve.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
--  * `order_lines_billed_beyond_what_was_ordered(ids)`: takes each named order line's row lock (FOR NO KEY UPDATE, in id order, so two
--    invoices naming the same lines queue rather than deadlock, and a foreign-key check from a new invoice line, which takes KEY SHARE,
--    is not blocked by it), and THEN, in a separate statement (under READ COMMITTED a new statement takes a new snapshot, so it sees an
--    issue that committed while this one waited), sums what the BILLING invoices' lines carry against each line. A billing invoice is one
--    that is not deleted, not a draft and not cancelled: `sales_cycle_service.billed_by_line(with_drafts=False)`, with a NULL status
--    read as the empty string the Python reads it as. It refuses, with SQLSTATE 23514 and one sentence that names the line and the
--    figures, a line whose billed total is more than its ordered quantity, or a linked billing line of a quantity that is not positive
--    (`over_billing`'s two refusals). The rule is `order_cycle.over_billing`; this is its SQL copy, and
--    `tests/test_650_order_line_billing_parity_pg.py` runs the same scenarios through both.
--  * three triggers that call it, each only when billing can grow:
--      - on `client_sales_invoices`, AFTER UPDATE OF status, deleted_at, per row, WHEN the invoice moves from not billing to billing (the
--        issue: `issue_sales_invoice_atomic`, migration 577, writes `status = 'issued'` inside its own transaction, so a refusal undoes
--        its journal entry too);
--      - on `client_sales_invoice_lines`, AFTER INSERT and AFTER UPDATE, per statement over the transition rows (an INSERT and an UPDATE
--        need a trigger each: a trigger with transition tables takes one event), for lines that name an order line and sit on a billing
--        invoice (a draft's lines are the API's to judge: a draft bills nothing);
--      - on `sales_order_lines`, AFTER UPDATE OF quantity, per row, WHEN the quantity goes down (the order's lines are replaced, not
--        updated, by the API, and one an invoice names cannot be deleted under migration 589's ON DELETE RESTRICT; this is the one
--        remaining way the ordered side could fall under what is billed).
--
-- WHAT IT DOES NOT DO: it holds what ISSUED invoices bill. Two drafts saved at one moment can still each claim the same quantity (the
-- API counts drafts on save and at issue, so the second to be issued is refused by the API or, in the race, by this). It does not
-- re-judge an invoice already issued: an over-billed line written before this migration stays as it is until something on it changes.
-- It assumes READ COMMITTED, the isolation every client of this database uses (PostgREST and the scripts); under REPEATABLE READ the
-- sum would be read on the transaction's first snapshot.
--
-- All functions are SECURITY DEFINER with a fixed search_path (the sum must see every billing line whoever writes, as migration 589's
-- trigger does) and EXECUTE is revoked from PUBLIC, anon and authenticated; the one that takes an argument is not callable by them.
--
-- DEPLOY ORDER: safe either way. The API asks the same question first, in words; the code that words this refusal ships with it and
-- reads it only when the database raises it.
--
-- Idempotent. Reversible: 650_..._rollback.sql drops the three triggers and the functions.

BEGIN;

CREATE OR REPLACE FUNCTION public.order_lines_billed_beyond_what_was_ordered(p_order_line_ids uuid[])
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    v_ids uuid[];
    v_bad record;
BEGIN
    SELECT array_agg(DISTINCT x ORDER BY x) INTO v_ids FROM unnest(p_order_line_ids) AS x WHERE x IS NOT NULL;
    IF v_ids IS NULL THEN
        RETURN;
    END IF;

    -- The lock first, in id order. A second issue naming these lines waits here until the first commits or rolls back.
    PERFORM 1 FROM public.sales_order_lines WHERE id = ANY (v_ids) ORDER BY id FOR NO KEY UPDATE;

    -- Then what the billing invoices bill, in a statement of its own (a new snapshot, which sees an issue committed while this waited).
    SELECT ol.id, ol.description, ol.quantity AS ordered,
           coalesce(sum(il.quantity), 0) AS billed,
           bool_or(il.quantity <= 0) AS non_positive
      INTO v_bad
      FROM public.sales_order_lines AS ol
      JOIN public.client_sales_invoice_lines AS il ON il.sales_order_line_id = ol.id
      JOIN public.client_sales_invoices AS inv ON inv.id = il.sales_invoice_id
     WHERE ol.id = ANY (v_ids)
       AND inv.deleted_at IS NULL
       AND coalesce(inv.status, '') NOT IN ('draft', 'cancelled')
     GROUP BY ol.id, ol.description, ol.quantity
    HAVING coalesce(sum(il.quantity), 0) > coalesce(ol.quantity, 0) OR bool_or(il.quantity <= 0)
     ORDER BY ol.id
     LIMIT 1;

    IF FOUND THEN
        IF v_bad.non_positive THEN
            RAISE EXCEPTION 'An invoice line billing the order line "%" is not of a positive quantity.', coalesce(v_bad.description, '')
                USING ERRCODE = '23514', DETAIL = 'order_line_over_billed';
        END IF;
        RAISE EXCEPTION 'The issued invoices would bill % of the order line "%", which was ordered as %: more than its sales order line has unbilled.',
            round(v_bad.billed, 3), coalesce(v_bad.description, ''), round(coalesce(v_bad.ordered, 0), 3)
            USING ERRCODE = '23514', DETAIL = 'order_line_over_billed';
    END IF;
END
$fn$;

-- ── the issue: an invoice that starts to bill ───────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.invoice_that_starts_to_bill_is_within_its_orders()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
BEGIN
    PERFORM public.order_lines_billed_beyond_what_was_ordered(
        ARRAY(SELECT il.sales_order_line_id FROM public.client_sales_invoice_lines AS il
               WHERE il.sales_invoice_id = NEW.id AND il.sales_order_line_id IS NOT NULL));
    RETURN NULL;
END
$fn$;

DROP TRIGGER IF EXISTS trg_invoice_that_starts_to_bill_is_within_its_orders ON public.client_sales_invoices;
CREATE TRIGGER trg_invoice_that_starts_to_bill_is_within_its_orders
    AFTER UPDATE OF status, deleted_at ON public.client_sales_invoices
    FOR EACH ROW
    WHEN (NEW.deleted_at IS NULL AND coalesce(NEW.status, '') NOT IN ('draft', 'cancelled')
          AND NOT (OLD.deleted_at IS NULL AND coalesce(OLD.status, '') NOT IN ('draft', 'cancelled')))
    EXECUTE FUNCTION public.invoice_that_starts_to_bill_is_within_its_orders();

-- ── a line written onto an invoice that already bills ───────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.invoice_lines_that_bill_are_within_their_orders()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
BEGIN
    PERFORM public.order_lines_billed_beyond_what_was_ordered(
        ARRAY(SELECT n.sales_order_line_id
                FROM new_lines AS n
                JOIN public.client_sales_invoices AS inv ON inv.id = n.sales_invoice_id
               WHERE n.sales_order_line_id IS NOT NULL
                 AND inv.deleted_at IS NULL
                 AND coalesce(inv.status, '') NOT IN ('draft', 'cancelled')));
    RETURN NULL;
END
$fn$;

DROP TRIGGER IF EXISTS trg_invoice_lines_inserted_bill_within_their_orders ON public.client_sales_invoice_lines;
CREATE TRIGGER trg_invoice_lines_inserted_bill_within_their_orders
    AFTER INSERT ON public.client_sales_invoice_lines
    REFERENCING NEW TABLE AS new_lines
    FOR EACH STATEMENT EXECUTE FUNCTION public.invoice_lines_that_bill_are_within_their_orders();

DROP TRIGGER IF EXISTS trg_invoice_lines_updated_bill_within_their_orders ON public.client_sales_invoice_lines;
CREATE TRIGGER trg_invoice_lines_updated_bill_within_their_orders
    AFTER UPDATE ON public.client_sales_invoice_lines
    REFERENCING NEW TABLE AS new_lines
    FOR EACH STATEMENT EXECUTE FUNCTION public.invoice_lines_that_bill_are_within_their_orders();

-- ── an order line whose quantity goes down ──────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.order_line_reduced_stays_above_what_is_billed()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $fn$
BEGIN
    PERFORM public.order_lines_billed_beyond_what_was_ordered(ARRAY[NEW.id]);
    RETURN NULL;
END
$fn$;

DROP TRIGGER IF EXISTS trg_order_line_reduced_stays_above_what_is_billed ON public.sales_order_lines;
CREATE TRIGGER trg_order_line_reduced_stays_above_what_is_billed
    AFTER UPDATE OF quantity ON public.sales_order_lines
    FOR EACH ROW
    WHEN (NEW.quantity IS DISTINCT FROM OLD.quantity AND (NEW.quantity IS NULL OR NEW.quantity < OLD.quantity))
    EXECUTE FUNCTION public.order_line_reduced_stays_above_what_is_billed();

REVOKE ALL ON FUNCTION public.order_lines_billed_beyond_what_was_ordered(uuid[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.invoice_that_starts_to_bill_is_within_its_orders() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.invoice_lines_that_bill_are_within_their_orders() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.order_line_reduced_stays_above_what_is_billed() FROM PUBLIC, anon, authenticated;

COMMIT;
