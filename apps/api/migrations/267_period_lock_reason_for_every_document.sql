-- Migration 267: the period lock is about a PERIOD, not about journals.
--
-- Migration 266 introduced journal_period_lock_reason: given a firm, a client
-- and a date, return NULL if that date may still be changed, or a sentence
-- saying why not — the financial year is locked, or a return covering the date
-- has been filed.
--
-- Nothing about that reasoning is specific to journals. A sales invoice dated
-- inside a filed GSTR-1 period is the same problem as a journal entry dated
-- there: the return at the portal says one thing and the books would say
-- another, with nothing recording why. Sales invoices and purchase bills check
-- only the financial-year half today (period_validation_service), so a document
-- can still be created or changed inside a period whose return has been filed.
--
-- Rather than write that rule a second time in Python, this renames the
-- function to what it actually is and leaves the old name as a delegate.
--
-- WHY A DELEGATE RATHER THAN A RENAME-AND-UPDATE-CALLERS
--     journal_period_lock_reason is called from inside edit_posted_journal
--     (migration 266) and from manual_journal_service. Both are load-bearing on
--     the ledger, both are covered by the real-Postgres suite, and neither has
--     any reason to change. Keeping the old name working means this migration
--     cannot break them: the tests that pin 266's behaviour go on testing the
--     same behaviour through the same name.

-- ═══════════════════════════════════════════════════════════════════════════
-- The general form.
-- ═══════════════════════════════════════════════════════════════════════════
-- Body identical to 266's, deliberately: this IS that function, renamed. Any
-- future change to what "closed" means belongs here and reaches every document
-- at once, which is the whole point of there being one of it.
--
-- Indian financial year runs 1 April to 31 March (Income Tax Act §3), which is
-- why the lock is keyed on a "YYYY-YY" label rather than a calendar year.
CREATE OR REPLACE FUNCTION public.period_lock_reason(
    p_firm   uuid,
    p_client uuid,
    p_date   date
) RETURNS TEXT LANGUAGE plpgsql STABLE
SET search_path = public, pg_catalog AS $$
DECLARE
    v_fy_start  int;
    v_fy_label  text;
    v_locked    text[];
    v_filing    record;
BEGIN
    IF p_date IS NULL THEN
        RETURN NULL;
    END IF;

    v_fy_start := CASE WHEN EXTRACT(MONTH FROM p_date) >= 4
                       THEN EXTRACT(YEAR FROM p_date)::int
                       ELSE EXTRACT(YEAR FROM p_date)::int - 1 END;
    v_fy_label := v_fy_start::text || '-' || lpad(((v_fy_start + 1) % 100)::text, 2, '0');

    SELECT locked_financial_years INTO v_locked FROM public.firms WHERE id = p_firm;
    IF v_locked IS NOT NULL AND v_fy_label = ANY (v_locked) THEN
        RETURN 'Financial year ' || v_fy_label || ' is locked. Unlock it, or post a reversal in an open year.';
    END IF;

    -- A filed return freezes the period it covers. The document at the portal
    -- cannot be recalled, so the books behind it must stop moving too —
    -- otherwise the return and the ledger disagree with nothing recording why.
    SELECT filing_type, filed_date INTO v_filing
      FROM public.filings
     WHERE client_id = p_client
       AND deleted_at IS NULL
       AND filed_date IS NOT NULL
       AND p_date BETWEEN period_start AND period_end
     ORDER BY filed_date
     LIMIT 1;
    IF FOUND THEN
        RETURN v_filing.filing_type || ' covering this date was filed on '
               || to_char(v_filing.filed_date, 'DD Mon YYYY')
               || '. Correct it with a reversal and an amendment in the next return.';
    END IF;

    RETURN NULL;
END;
$$;


-- ═══════════════════════════════════════════════════════════════════════════
-- The journal-shaped name, kept working.
-- ═══════════════════════════════════════════════════════════════════════════
-- edit_posted_journal calls this from inside a transaction that rewrites posted
-- ledger rows. It keeps calling exactly what it called before; only where the
-- answer is computed has moved.
CREATE OR REPLACE FUNCTION public.journal_period_lock_reason(
    p_firm   uuid,
    p_client uuid,
    p_date   date
) RETURNS TEXT LANGUAGE sql STABLE
SET search_path = public, pg_catalog AS $$
    SELECT public.period_lock_reason(p_firm, p_client, p_date);
$$;


GRANT EXECUTE ON FUNCTION public.period_lock_reason(uuid, uuid, date)
    TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.journal_period_lock_reason(uuid, uuid, date)
    TO authenticated, service_role;

COMMENT ON FUNCTION public.period_lock_reason(uuid, uuid, date) IS
    'NULL when this date may still be changed; otherwise the reason it may not '
    '(financial year locked, or a return covering it filed). One rule for every '
    'document type — journals, sales invoices, purchase bills.';
