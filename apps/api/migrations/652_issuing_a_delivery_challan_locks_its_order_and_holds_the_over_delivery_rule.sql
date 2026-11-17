-- Migration 652: issuing a delivery challan locks the order it names and holds the over-delivery rule (ledger POST-A-421, part b).
--
-- WHAT WAS WRONG. `sales_cycle_service.issue_challan` asked, in the API, that a delivery is not more than its order has undelivered
-- (`order_cycle.over_delivery`) and then wrote the status with a compare-and-set on the CHALLAN's row. Two different drafts of the whole
-- order, issued in the same instant, each read the order as undelivered and each won its own compare-and-set: the order was delivered
-- twice. A compare-and-set on one row protects that row, not the quantity the order's lines hold.
--
-- WHAT THIS DOES. `issue_delivery_challan_atomic(firm, client, challan, issued_at)` takes the challan's lock FOR UPDATE and then the lock of
-- the order it names (always in that order, so two issues on one order queue and do not deadlock; a cancel and a lot lock the challan
-- alone), refuses unless the challan is a draft, asks the order rule of every order line its lines name (the lines that name one order
-- line added together), and only then writes `status = 'issued'` and the moment of issue, in the same transaction. The rule is
-- `order_cycle.over_delivery`: a positive quantity, and no more than the line's ordered quantity less what the ISSUED challans of that
-- order already deliver (a draft, a cancelled challan and one marked received back deliver nothing:
-- `STATUSES_THAT_DELIVER_AGAINST_AN_ORDER`). The SQL is its copy, run beside it by
-- `tests/test_652_issue_delivery_challan_parity_pg.py`; the API keeps asking first, in its own sentences, and reads this function's
-- words (`order_over_delivered`, `order_line_not_of_order`, `challan_not_draft`) only for the race it could not see.
-- It checks nothing else: Rule 55(1)'s particulars, the date and the header's arithmetic stay with the API, which asks them before.
--
-- SECURITY INVOKER (the privileged client's own privileges judge every row), EXECUTE to service_role alone.
-- DEPLOY ORDER: safe either way. Until the migration is live the API issues with the compare-and-set it had (it reads the missing function
-- and says so in its log); that fallback is deleted once 652 has been in production.
-- Idempotent. Reversible: 652_..._rollback.sql drops the function.

BEGIN;

CREATE OR REPLACE FUNCTION public.issue_delivery_challan_atomic(p_firm_id uuid, p_client_id uuid, p_challan_id uuid, p_issued_at timestamptz)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_catalog
AS $$
DECLARE
    v_status   text;
    v_order_id uuid;
    v_bad      record;
    v_row      jsonb;
BEGIN
    SELECT status, order_id INTO v_status, v_order_id FROM public.delivery_challans
     WHERE id = p_challan_id AND firm_id = p_firm_id AND client_id = p_client_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'challan_not_found' USING ERRCODE = 'P0002';
    END IF;
    IF v_status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'challan_not_draft' USING ERRCODE = 'P0001', DETAIL = format('status is %s', coalesce(v_status, 'null'));
    END IF;

    IF v_order_id IS NOT NULL THEN
        -- The order's lock, taken after the challan's: a second issue on this order waits here for the first to commit and then reads what it delivered.
        PERFORM 1 FROM public.sales_orders WHERE id = v_order_id AND firm_id = p_firm_id AND client_id = p_client_id FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'order_line_not_of_order' USING ERRCODE = 'P0001', DETAIL = 'the challan names an order that is not this client''s';
        END IF;
    END IF;

    -- A line that names an order line while the challan names no order, or one of another order, or a quantity that is not positive.
    SELECT l.description, l.quantity INTO v_bad
      FROM public.delivery_challan_lines l
     WHERE l.challan_id = p_challan_id AND l.order_line_id IS NOT NULL
       AND (v_order_id IS NULL
            OR NOT EXISTS (SELECT 1 FROM public.sales_order_lines ol WHERE ol.id = l.order_line_id AND ol.order_id = v_order_id))
     LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'order_line_not_of_order' USING ERRCODE = 'P0001', DETAIL = format('%s names an order line that is not on this challan''s order', v_bad.description);
    END IF;

    -- order_cycle.over_delivery, per order line: the quantities this challan puts on the line ADDED TOGETHER (two lines of 6 against an order
    -- line of 10 deliver 12, though each fits alone), against what is left of it after the ISSUED challans; a line that is not positive is
    -- refused on its own.
    SELECT ol.description, ol.quantity AS ordered, sum(l.quantity) AS mine,
           coalesce((SELECT sum(d.quantity) FROM public.delivery_challan_lines d
                       JOIN public.delivery_challans dc ON dc.id = d.challan_id
                      WHERE d.order_line_id = ol.id AND dc.status = 'issued' AND dc.id <> p_challan_id), 0) AS delivered,
           bool_or(l.quantity <= 0) AS non_positive
      INTO v_bad
      FROM public.delivery_challan_lines l
      JOIN public.sales_order_lines ol ON ol.id = l.order_line_id
     WHERE l.challan_id = p_challan_id
     GROUP BY ol.id, ol.description, ol.quantity
    HAVING bool_or(l.quantity <= 0)
        OR sum(l.quantity) > greatest(0, ol.quantity - coalesce((SELECT sum(d.quantity) FROM public.delivery_challan_lines d
                                                                   JOIN public.delivery_challans dc ON dc.id = d.challan_id
                                                                  WHERE d.order_line_id = ol.id AND dc.status = 'issued' AND dc.id <> p_challan_id), 0))
     ORDER BY ol.id
     LIMIT 1;
    IF FOUND THEN
        IF v_bad.non_positive THEN
            RAISE EXCEPTION 'order_over_delivered' USING ERRCODE = 'P0001', DETAIL = format('%s: a delivery must be of a positive quantity', v_bad.description);
        END IF;
        RAISE EXCEPTION 'order_over_delivered' USING ERRCODE = 'P0001',
            DETAIL = format('%s: %s is more than the %s still undelivered on this order line (%s ordered, %s already delivered)',
                            v_bad.description, v_bad.mine, greatest(0, v_bad.ordered - v_bad.delivered), v_bad.ordered, v_bad.delivered);
    END IF;

    UPDATE public.delivery_challans
       SET status = 'issued', issued_at = p_issued_at, updated_at = p_issued_at
     WHERE id = p_challan_id AND firm_id = p_firm_id AND client_id = p_client_id AND status = 'draft'
    RETURNING to_jsonb(delivery_challans) INTO v_row;
    RETURN v_row;
END
$$;

REVOKE ALL ON FUNCTION public.issue_delivery_challan_atomic(uuid, uuid, uuid, timestamptz) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.issue_delivery_challan_atomic(uuid, uuid, uuid, timestamptz) TO service_role;

COMMIT;
