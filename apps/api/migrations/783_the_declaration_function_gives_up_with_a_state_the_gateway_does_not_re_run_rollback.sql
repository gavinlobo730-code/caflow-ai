-- Rollback of migration 783: file_it_declaration as migration 548 defined it (its give-up raises 40001 again). The API matches both
-- states, so it is right against either body.

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

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

COMMIT;
