-- Migration 136: protect firms.locked_financial_years from direct modification.
--
-- Year locks were writable by any authenticated firm user (RLS firms_own = FOR ALL),
-- so the "Partner-only" control was bypassable from the browser. This trigger makes
-- the service-role backend the ONLY writer of the lock array; all year lock/unlock
-- must go through the Partner-gated, audited POST /api/accounting/year-lock endpoint.
--
-- Other firm columns remain editable by authenticated users (the trigger only fires
-- when locked_financial_years actually changes). Migrations / admin SQL (postgres,
-- supabase_admin) are allowed so the column can still be maintained operationally.

CREATE OR REPLACE FUNCTION public.guard_locked_financial_years()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  jwt_role text;
BEGIN
  IF NEW.locked_financial_years IS DISTINCT FROM OLD.locked_financial_years THEN
    BEGIN
      jwt_role := auth.role();
    EXCEPTION WHEN OTHERS THEN
      jwt_role := NULL;
    END;
    IF coalesce(jwt_role, '') <> 'service_role'
       AND current_user NOT IN ('service_role', 'postgres', 'supabase_admin', 'supabase_auth_admin') THEN
      RAISE EXCEPTION
        'locked_financial_years can only be changed via the year-lock API (Partner-only).';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_locked_fy ON public.firms;
CREATE TRIGGER trg_guard_locked_fy
  BEFORE UPDATE ON public.firms
  FOR EACH ROW
  EXECUTE FUNCTION public.guard_locked_financial_years();
