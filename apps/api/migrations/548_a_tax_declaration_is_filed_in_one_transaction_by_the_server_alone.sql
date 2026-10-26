-- Migration 548 — a tax declaration is filed in one transaction, by the server alone (POST-A-340).
--
-- WHAT IS WRONG TODAY
--   An employee's Form 12BB declaration (payroll_it_declarations, with its Chapter VI-A lines in payroll_it_declaration_items) is
--   filed by two doors, and each writes it as several separate requests:
--     * PUT /api/portal/employee/tax-declaration (POST-A-010) updates or inserts the header, inserts the new lines, removes the old
--       ones, reads the result back and, on a failure, puts back what it replaced;
--     * PUT /api/payroll/declarations (the staff door) upserts the header, deletes the lines and inserts the new ones, with no
--       put-back at all.
--   That is sound for one filing at a time and for a CA verifying in between. It is not sound for two filings by one employee at the
--   same instant (a second tab, or the browser's retry after a network failure the server had already served): the header of one
--   filing can end up beside the lines of the other. The employee door's put-back is the best a client of the database can do
--   without a transaction, and it is more code than the thing it protects.
--
-- WHAT IT DOES
--   public.file_it_declaration(p_declaration jsonb, p_items jsonb, p_refuse_verified boolean) RETURNS uuid, SECURITY INVOKER, executable
--   by the service role alone (the two doors call it with the API's privileged client, after their own role, client and validation
--   checks), in ONE transaction:
--     1. names its scope or refuses: firm, client, employee and year are required, and the employee must be that firm's and that
--        client's (42501 otherwise), so a privileged call that names an employee of another firm writes nothing;
--     2. locks the (employee, year) row FOR UPDATE, or creates it (INSERT ... ON CONFLICT DO NOTHING, then the lock), so two
--        filings of the same declaration run one after the other and the second sees the first's result;
--     3. refuses a VERIFIED declaration when `p_refuse_verified` (the employee's door: the CA has finished checking, the figures are
--        no longer the employee's to change), with the message `declaration_verified:` the API answers 409; the staff door passes
--        false and replaces a verified declaration as it always has, resetting what was checked;
--     4. replaces the header's declared figures and RESETS every verified column, status, `submitted_at` and `updated_at`;
--     5. replaces the lines wholesale (delete, then insert the ones given) and returns the declaration's id.
--   Any failure (a CHECK, a foreign key, a malformed line) rolls the whole call back: the header and the lines are exactly what they
--   were. The verified-columns guards (migrations 296/297) still see every statement and do not fire for the service role, as before.
--
-- WHY IT SHIPS ALONE AND FIRST
--   The schema guard flips /health to 503 for a function the code names and the database lacks, so the code that calls it (the next
--   change, which deletes the employee door's read-back and put-back) ships after this is applied. Nothing calls it yet.
--
-- WHAT IT DOES NOT DO
--   It does not validate the declaration (landlord's PAN, sections, regime: `domain/payroll/declarations.validate` does, in the API,
--   before the call), it does not decide who may file (the routes do), and it does not write the audit log (the routes do).
--
-- Reversible: 548_..._rollback.sql drops the function. Roll back the code that calls it first.


CREATE OR REPLACE FUNCTION public.file_it_declaration(p_declaration jsonb, p_items jsonb, p_refuse_verified boolean DEFAULT false)
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $fn$
DECLARE
    v_firm      uuid := nullif(p_declaration->>'firm_id', '')::uuid;
    v_client    uuid := nullif(p_declaration->>'client_id', '')::uuid;
    v_employee  uuid := nullif(p_declaration->>'employee_id', '')::uuid;
    v_fy        text := nullif(p_declaration->>'fy', '');
    v_id        uuid;
    v_verified  boolean;
    v_now       timestamptz := now();
    v_tries     int := 0;
BEGIN
    IF v_firm IS NULL OR v_client IS NULL OR v_employee IS NULL OR v_fy IS NULL THEN
        RAISE EXCEPTION 'file_it_declaration: a declaration names its firm, client, employee and year' USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(coalesce(p_items, '[]'::jsonb)) <> 'array' THEN
        RAISE EXCEPTION 'file_it_declaration: the lines must be a JSON array' USING ERRCODE = '22023';
    END IF;
    -- A privileged call names a scope it proved; the employee must be that firm's and that client's.
    IF NOT EXISTS (SELECT 1 FROM public.payroll_employees e WHERE e.id = v_employee AND e.firm_id = v_firm AND e.client_id = v_client) THEN
        RAISE EXCEPTION 'file_it_declaration: employee % is not an employee of client % of firm %', v_employee, v_client, v_firm
            USING ERRCODE = '42501';
    END IF;

    LOOP
        v_tries := v_tries + 1;
        -- The row for this employee and year, locked so a second filing waits for this one and then sees its result.
        SELECT d.id, d.proofs_verified INTO v_id, v_verified
          FROM public.payroll_it_declarations d
         WHERE d.employee_id = v_employee AND d.fy = v_fy AND d.firm_id = v_firm
         FOR UPDATE;
        EXIT WHEN v_id IS NOT NULL;
        -- None yet: create it. A filing from another window that got here first makes this insert do nothing, and the loop
        -- reads (and locks) its row on the next pass.
        INSERT INTO public.payroll_it_declarations (
            firm_id, client_id, employee_id, fy, regime, status,
            rent_paid_declared_paise, rent_paid_verified_paise, landlord_name, landlord_address, landlord_pan, rent_is_metro,
            lta_declared_paise, lta_verified_paise, home_loan_interest_declared_paise, home_loan_interest_verified_paise,
            lender_name, lender_pan, other_income_declared_paise, house_property_loss_declared_paise,
            proofs_verified, verified_at, verified_by, submitted_at, updated_at)
        VALUES (
            v_firm, v_client, v_employee, v_fy,
            coalesce(p_declaration->>'regime', 'new'), 'submitted',
            coalesce((p_declaration->>'rent_paid_declared_paise')::bigint, 0), 0,
            coalesce(p_declaration->>'landlord_name', ''), coalesce(p_declaration->>'landlord_address', ''),
            coalesce(p_declaration->>'landlord_pan', ''), coalesce((p_declaration->>'rent_is_metro')::boolean, false),
            coalesce((p_declaration->>'lta_declared_paise')::bigint, 0), 0,
            coalesce((p_declaration->>'home_loan_interest_declared_paise')::bigint, 0), 0,
            coalesce(p_declaration->>'lender_name', ''), coalesce(p_declaration->>'lender_pan', ''),
            coalesce((p_declaration->>'other_income_declared_paise')::bigint, 0),
            coalesce((p_declaration->>'house_property_loss_declared_paise')::bigint, 0),
            false, NULL, NULL, v_now, v_now)
        ON CONFLICT (employee_id, fy) DO NOTHING
        RETURNING id INTO v_id;
        IF v_id IS NOT NULL THEN
            v_verified := false;
            EXIT;
        END IF;
        IF v_tries >= 3 THEN
            RAISE EXCEPTION 'file_it_declaration: could not take the declaration for employee % and year %', v_employee, v_fy
                USING ERRCODE = '40001';
        END IF;
    END LOOP;

    IF v_verified AND p_refuse_verified THEN
        RAISE EXCEPTION 'declaration_verified: the declaration for % is verified and is not the employee''s to change', v_fy
            USING ERRCODE = 'P0001';
    END IF;

    -- The header: declared figures replaced, every verified column reset (the figures claimed are no longer the ones that were
    -- checked, and carrying the old verdict forward would let a raised claim inherit the proof for a smaller one).
    UPDATE public.payroll_it_declarations d SET
        regime                             = coalesce(p_declaration->>'regime', 'new'),
        status                             = 'submitted',
        rent_paid_declared_paise           = coalesce((p_declaration->>'rent_paid_declared_paise')::bigint, 0),
        rent_paid_verified_paise           = 0,
        landlord_name                      = coalesce(p_declaration->>'landlord_name', ''),
        landlord_address                   = coalesce(p_declaration->>'landlord_address', ''),
        landlord_pan                       = coalesce(p_declaration->>'landlord_pan', ''),
        rent_is_metro                      = coalesce((p_declaration->>'rent_is_metro')::boolean, false),
        lta_declared_paise                 = coalesce((p_declaration->>'lta_declared_paise')::bigint, 0),
        lta_verified_paise                 = 0,
        home_loan_interest_declared_paise  = coalesce((p_declaration->>'home_loan_interest_declared_paise')::bigint, 0),
        home_loan_interest_verified_paise  = 0,
        lender_name                        = coalesce(p_declaration->>'lender_name', ''),
        lender_pan                         = coalesce(p_declaration->>'lender_pan', ''),
        other_income_declared_paise        = coalesce((p_declaration->>'other_income_declared_paise')::bigint, 0),
        house_property_loss_declared_paise = coalesce((p_declaration->>'house_property_loss_declared_paise')::bigint, 0),
        proofs_verified                    = false,
        verified_at                        = NULL,
        verified_by                        = NULL,
        submitted_at                       = v_now,
        updated_at                         = v_now
     WHERE d.id = v_id AND d.firm_id = v_firm;

    -- The lines: replaced wholesale. A declaration states the whole year's intent, and merging would leave a withdrawn
    -- investment in place.
    DELETE FROM public.payroll_it_declaration_items i WHERE i.declaration_id = v_id AND i.firm_id = v_firm;
    INSERT INTO public.payroll_it_declaration_items
        (firm_id, declaration_id, section, label, amount_declared_paise, amount_verified_paise, status, proof_reference, proof_attachments)
    SELECT v_firm, v_id, x->>'section', coalesce(x->>'label', ''), coalesce((x->>'amount_declared_paise')::bigint, 0), 0, 'declared',
           coalesce(x->>'proof_reference', ''), coalesce(x->'proof_attachments', '[]'::jsonb)
      FROM jsonb_array_elements(coalesce(p_items, '[]'::jsonb)) AS x;

    RETURN v_id;
END;
$fn$;

REVOKE ALL ON FUNCTION public.file_it_declaration(jsonb, jsonb, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.file_it_declaration(jsonb, jsonb, boolean) TO service_role;

-- ── the closing check ───────────────────────────────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    v_def boolean;
BEGIN
    SELECT p.prosecdef INTO v_def FROM pg_proc p WHERE p.oid = 'public.file_it_declaration(jsonb, jsonb, boolean)'::regprocedure;
    IF v_def THEN
        RAISE EXCEPTION 'migration 548: file_it_declaration must be SECURITY INVOKER';
    END IF;
    IF has_function_privilege('anon', 'public.file_it_declaration(jsonb, jsonb, boolean)', 'EXECUTE')
       OR has_function_privilege('authenticated', 'public.file_it_declaration(jsonb, jsonb, boolean)', 'EXECUTE')
       OR NOT has_function_privilege('service_role', 'public.file_it_declaration(jsonb, jsonb, boolean)', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 548: file_it_declaration must be executable by the service role alone';
    END IF;
END
$$;
