-- Migration 137: make is_fy_locked callable by the service-role backend.
--
-- The previous body filtered `... WHERE id = p_firm_id AND id = public.get_my_firm_id()`.
-- The backend posts as the service-role (no end-user JWT), so get_my_firm_id() is
-- NULL there → the row never matched → the function returned NULL for EVERY backend
-- call. Two consequences:
--   * FY locking was never actually enforced from the backend (NULL → not True), and
--   * after the validator was made fail-closed, NULL was treated as "indeterminate"
--     and BLOCKED every posting (incl. automatic opening-balance posting), surfacing
--     as "Unable to save customer. Please try again."
--
-- The function is SECURITY DEFINER and the caller already passes the authenticated
-- user's own firm_id, so scoping by p_firm_id alone is correct. coalesce(...,false)
-- guarantees a definitive boolean (false = open, true = locked) for any firm/date.
CREATE OR REPLACE FUNCTION public.is_fy_locked(p_firm_id uuid, p_date date)
RETURNS boolean
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $function$
  SELECT coalesce((
    SELECT
      CASE
        WHEN EXTRACT(MONTH FROM p_date) >= 4 THEN
          (EXTRACT(YEAR FROM p_date)::text || '-' ||
           RIGHT((EXTRACT(YEAR FROM p_date) + 1)::text, 2)) = ANY(locked_financial_years)
        ELSE
          ((EXTRACT(YEAR FROM p_date) - 1)::text || '-' ||
           RIGHT(EXTRACT(YEAR FROM p_date)::text, 2)) = ANY(locked_financial_years)
      END
    FROM public.firms
    WHERE id = p_firm_id
  ), false);
$function$;
