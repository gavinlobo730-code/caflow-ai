-- Migration 522: TDS deducted and not yet deposited, read from the challan register (found by driving the seeded firm in a browser).
--
-- WHY. The hub's TDS tile ("Deducted and not yet deposited") summed tds_deductions.tds_paise WHERE challan_no IS NULL. A deduction a
-- purchase bill writes never carries challan_no, and neither does challan_date nor a status other than 'deducted': POST /challans
-- records the challan and never touches the deductions it paid. So the tile counted EVERY bill-derived deduction as undeposited,
-- whatever had been paid in: on the seeded demo firm, every deduction of the year deposited by a recorded challan, the dashboard said
-- Rs 1,94,614.98 and a client's overview said Rs 63,647.88. A number a CA acts on, and wrong in the direction that sends them to
-- chase a deposit they made. (A hand-keyed deduction can carry a typed challan number: that is a note, not a record of a deposit,
-- and the statement and the deposit worksheet ignore it; this function does too. The challan register is the one record.)
--
-- WHAT THIS IS. The register's answer, computed where the rows are (CLAUDE.md's reporting rule: what crosses the wire is
-- proportional to the answer, not the ledger). A challan pays deductions of its own financial year and quarter under its own
-- section, first in first out (domain/tds/challan_mapping), so the tax of a (client, financial year, quarter, section) group that is
-- left over after the group's challans is exactly
--
--     greatest(0, sum(deductions' tax) - sum(challans' tax))
--
-- whatever order the fill takes: a challan can only pay a deduction of its own group and every rupee of it that is not needed is
-- surplus, never carried to another group. The function sums that shortfall. It does not name a deduction, a challan or a date.
--
--   * a deduction's tax is its tds_paise + surcharge_paise + cess_paise; a challan's is its tds_paise + surcharge_paise (a cess
--     paid on a challan sits inside tds_paise: the form has no cess head), which is what deposit_due.mapping_from_register matches.
--     (The quarterly statement matches a challan's tds_paise alone against a deduction's tds_paise alone: the two agree for every
--     resident section, which has no surcharge and no cess, and differ for a section 195 payment by exactly those.)
--     Each row counts at least nil, as challan_mapping.assign counts it (a negative row neither pays nor owes);
--   * salary (section 192) is deposited from payroll and neither side of this register carries it, so rows under its three
--     spellings ('192', 'SEC192', 'S192', spaces ignored) are left out of both sides, as deposit_due does;
--   * the group's section is the section as typed, trimmed of ASCII whitespace, upper-cased, with a trailing bracketed limb dropped
--     ("194J(B)" -> "194J"; a deduction with no section is "(NO SECTION)", a challan with none is ''). For every section the
--     registry holds that is domain/tds/section_rates.parent_of, which is what the statement and the worksheet group by (the pg test
--     runs every registry key, in both years, through both, and goes red the day a key is added whose parent is not its
--     bracket-stripped text: that is when this needs a lookup and not a pattern). For a section the registry does NOT hold the
--     statement groups by the text itself and this function by the bracket-stripped text, so a deduction under "194Z(A)" is paid
--     by a challan typed "194Z" here and is not on the statement; the registry is the only source of what a section is, and a
--     challan's section is free text. The Python twin (domain/tds/undeposited) is written to this spelling, not to the registry's;
--   * a deduction is placed in the financial year and quarter its transaction_date falls in (Rule 31A's quarters), and meets the
--     challans RECORDED for that financial_year and quarter, exactly as the worksheet reads them;
--   * p_client_ids NULL is every client of the firm (a Partner); an array is the clients a caller is assigned to; an EMPTY array is no
--     client and answers 0. The all-clients case is resolved to the firm's own client ids first so that BOTH cases ask the same
--     indexed question (client_id = ANY(array)), and not an OR that sends the planner to a scan of the whole table.
--
-- SECURITY INVOKER: it only reads, and both tables carry row security for a signed-in caller (the hub reads as the service role and
-- scopes by the arguments, as it does for every other tile). Rollback drops the function; the tile then has nothing to ask and shows
-- no figure rather than a wrong one.

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

REVOKE EXECUTE ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) FROM anon;
GRANT EXECUTE ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) TO authenticated, service_role;
