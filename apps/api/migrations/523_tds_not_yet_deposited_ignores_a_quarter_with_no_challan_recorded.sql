-- Migration 523: tax deducted in a quarter for which NO challan is recorded is "not recorded", and is not "deducted and not yet deposited".
--
-- WHY. Migration 522 made the hub's TDS tile the challan register's answer: per (client, financial year, quarter, section), the
-- deductions' tax left over after the group's challans. It counted EVERY quarter, including a quarter for which the register holds no
-- challan at all. For a pilot firm that keeps its deposits in Tally (the importer writes customer and vendor masters only, so its
-- challans are not in this product) that is the whole of the tax its purchase bills withheld, shown on the dashboard as "Deducted and
-- not yet deposited": a statement this product cannot make. It knows what was withheld and holds no challan to say whether it was
-- paid over. An unknown is never shown as a value. Form 3CD clause 34 had exactly this defect and was corrected (it reports such a quarter as "not
-- recorded", apart); the dashboard was built the same week and carried it.
--
-- WHAT THIS DOES. One function, public.tds_deposit_position, returns the two figures a screen needs from one scan of the rows:
--
--     undeposited_paise    the shortfall of 522 (greatest(0, deducted - paid) per group, summed), counted ONLY in a (client,
--                          financial year, quarter) for which the register holds at least one non-salary challan; and
--     not_recorded_paise   the tax deducted in a (client, financial year, quarter) for which it holds none.
--
-- A quarter is "recorded" when ANY non-salary challan row exists for that client, financial year and quarter, whatever its section or
-- amount: the person who keeps the register for a quarter records every deposit of it, so a section with no challan in a quarter that
-- has others is a real shortfall, and a quarter with none is a quarter nobody has recorded (the rule Form 3CD clause 34 uses). A salary
-- (section 192) challan does not make a quarter recorded: payroll deposits salary tax and neither side of this register carries it.
-- Everything else is exactly migration 522: the same tax on each side, the same section grouping, the same salary exclusion, the same
-- scope arguments (NULL is every client of the firm, an array is those clients, an EMPTY array is none).
--
-- tds_undeposited_paise (522) stays, as a one-line wrapper over the new function. Production applies this migration after the tests
-- pass, while Render deploys the API on the push, so EITHER can be live first. With the new API first there is no function for the
-- tile to ask, and it shows no figure (it says it could not be read), never a wrong one; with the previous API still live after the
-- migration, the wrapper keeps giving it a right answer (the shortfall of recorded quarters). Nothing in this repository calls the
-- wrapper once the new API is live; dropping it is a later migration.
--
-- SECURITY INVOKER, read-only, as 522: both tables carry row security for a signed-in caller, the hub reads as the service role and
-- scopes by the arguments. Rollback restores 522's function and drops the new one.

CREATE OR REPLACE FUNCTION public.tds_deposit_position(p_firm_id uuid, p_client_ids uuid[] DEFAULT NULL)
RETURNS TABLE (undeposited_paise bigint, not_recorded_paise bigint)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    WITH scope AS (
        SELECT coalesce(p_client_ids, (SELECT array_agg(c.id) FROM public.clients c WHERE c.firm_id = p_firm_id)) AS client_ids
    ),
    deducted AS (
        SELECT d.client_id,
               CASE WHEN extract(month FROM d.transaction_date) >= 4
                    THEN extract(year FROM d.transaction_date)::int
                    ELSE extract(year FROM d.transaction_date)::int - 1 END AS fy_start,
               CASE WHEN extract(month FROM d.transaction_date) BETWEEN 4 AND 6 THEN 'Q1'
                    WHEN extract(month FROM d.transaction_date) BETWEEN 7 AND 9 THEN 'Q2'
                    WHEN extract(month FROM d.transaction_date) BETWEEN 10 AND 12 THEN 'Q3'
                    ELSE 'Q4' END AS quarter,
               regexp_replace(
                   upper(coalesce(nullif(regexp_replace(coalesce(d.section, ''), '^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$', '', 'g'), ''),
                                  '(no section)')),
                   '([^(])\(.*\)$', '\1') AS section_parent,
               sum(greatest(coalesce(d.tds_paise, 0) + coalesce(d.surcharge_paise, 0) + coalesce(d.cess_paise, 0), 0)) AS tax_paise
        FROM public.tds_deductions d, scope
        WHERE d.firm_id = p_firm_id
          AND d.client_id = ANY (scope.client_ids)
          AND upper(replace(coalesce(d.section, ''), ' ', '')) NOT IN ('192', 'SEC192', 'S192')
        GROUP BY 1, 2, 3, 4
    ),
    paid AS (
        SELECT c.client_id, c.financial_year, c.quarter,
               regexp_replace(upper(regexp_replace(coalesce(c.section, ''), '^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$', '', 'g')),
                              '([^(])\(.*\)$', '\1') AS section_parent,
               sum(greatest(coalesce(c.tds_paise, 0) + coalesce(c.surcharge_paise, 0), 0)) AS paid_paise
        FROM public.tds_challans c, scope
        WHERE c.firm_id = p_firm_id
          AND c.client_id = ANY (scope.client_ids)
          AND upper(replace(coalesce(c.section, ''), ' ', '')) NOT IN ('192', 'SEC192', 'S192')
        GROUP BY 1, 2, 3, 4
    ),
    recorded AS (
        SELECT DISTINCT p.client_id, p.financial_year, p.quarter FROM paid p
    )
    SELECT coalesce(sum(greatest(d.tax_paise - coalesce(p.paid_paise, 0), 0)) FILTER (WHERE r.client_id IS NOT NULL), 0)::bigint,
           coalesce(sum(d.tax_paise) FILTER (WHERE r.client_id IS NULL), 0)::bigint
    FROM deducted d
    LEFT JOIN recorded r
      ON r.client_id = d.client_id
     AND r.financial_year = d.fy_start::text || '-' || lpad(((d.fy_start + 1) % 100)::text, 2, '0')
     AND r.quarter = d.quarter
    LEFT JOIN paid p
      ON p.client_id = d.client_id
     AND p.financial_year = d.fy_start::text || '-' || lpad(((d.fy_start + 1) % 100)::text, 2, '0')
     AND p.quarter = d.quarter
     AND p.section_parent = d.section_parent;
$$;

COMMENT ON FUNCTION public.tds_deposit_position(uuid, uuid[]) IS
    'TDS deposit position from the challan register, in paise: undeposited_paise is the shortfall (greatest(0, deducted - paid) per client, financial year, quarter and section, summed) counted only in a quarter for which at least one non-salary challan is recorded; not_recorded_paise is the tax deducted in a quarter for which none is, which the books cannot say was deposited or not. A section is grouped as typed with a trailing bracketed limb dropped. Salary (192) is not in this register. p_client_ids NULL is every client of the firm. Migration 523. SECURITY INVOKER, read-only.';

REVOKE EXECUTE ON FUNCTION public.tds_deposit_position(uuid, uuid[]) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.tds_deposit_position(uuid, uuid[]) FROM anon;
GRANT EXECUTE ON FUNCTION public.tds_deposit_position(uuid, uuid[]) TO authenticated, service_role;

CREATE OR REPLACE FUNCTION public.tds_undeposited_paise(p_firm_id uuid, p_client_ids uuid[] DEFAULT NULL)
RETURNS bigint
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    SELECT p.undeposited_paise FROM public.tds_deposit_position(p_firm_id, p_client_ids) p;
$$;

COMMENT ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) IS
    'The undeposited_paise of public.tds_deposit_position, kept for the API that was live when migration 523 was applied. Migration 523 changed it to count only quarters for which a challan is recorded. SECURITY INVOKER, read-only.';

REVOKE EXECUTE ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) FROM anon;
GRANT EXECUTE ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) TO authenticated, service_role;
