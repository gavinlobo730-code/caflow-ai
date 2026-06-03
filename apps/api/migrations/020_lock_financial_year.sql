-- Migration 020: Financial year locking for accounting
-- Locked years prevent any journal entry modifications for that FY
-- Only Partners can lock/unlock years

ALTER TABLE public.firms
  ADD COLUMN IF NOT EXISTS locked_financial_years TEXT[] NOT NULL DEFAULT '{}';

-- Helper function: check if a date falls in a locked FY
-- Indian FY format: '2024-25', '2025-26', etc.
CREATE OR REPLACE FUNCTION public.is_fy_locked(p_firm_id uuid, p_date date)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT
    CASE
      WHEN EXTRACT(MONTH FROM p_date) >= 4 THEN
        -- April onwards: FY is current_year - (current_year+1)
        (EXTRACT(YEAR FROM p_date)::text || '-' ||
         RIGHT((EXTRACT(YEAR FROM p_date) + 1)::text, 2))
        = ANY(locked_financial_years)
      ELSE
        -- Jan-March: FY is (current_year-1) - current_year
        ((EXTRACT(YEAR FROM p_date) - 1)::text || '-' ||
         RIGHT(EXTRACT(YEAR FROM p_date)::text, 2))
        = ANY(locked_financial_years)
    END
  FROM public.firms
  WHERE id = p_firm_id;
$$;

GRANT EXECUTE ON FUNCTION public.is_fy_locked(uuid, date) TO authenticated;
