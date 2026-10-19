-- Rollback of migration 523: restores migration 522's tds_undeposited_paise (every quarter counted, recorded or not) and drops
-- public.tds_deposit_position. For fidelity with the previous schema, not for use: it brings back the dashboard's statement that a
-- quarter with no challan recorded is wholly undeposited.

CREATE OR REPLACE FUNCTION public.tds_undeposited_paise(p_firm_id uuid, p_client_ids uuid[] DEFAULT NULL)
RETURNS bigint
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
    )
    SELECT coalesce(sum(greatest(d.tax_paise - coalesce(p.paid_paise, 0), 0)), 0)::bigint
    FROM deducted d
    LEFT JOIN paid p
      ON p.client_id = d.client_id
     AND p.financial_year = d.fy_start::text || '-' || lpad(((d.fy_start + 1) % 100)::text, 2, '0')
     AND p.quarter = d.quarter
     AND p.section_parent = d.section_parent;
$$;

COMMENT ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) IS
    'TDS deducted and not yet deposited, in paise, from the challan register: per (client, financial year, quarter, section), the deductions'' tax left over after the quarter''s challans (greatest(0, deducted - paid)), summed. A section is grouped as typed with a trailing bracketed limb dropped. Salary (192) is not in this register. p_client_ids NULL is every client of the firm. Migration 522. SECURITY INVOKER, read-only.';

DROP FUNCTION IF EXISTS public.tds_deposit_position(uuid, uuid[]);
