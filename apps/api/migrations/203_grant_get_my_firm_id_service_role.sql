-- get_my_firm_id() was only granted EXECUTE to postgres/authenticated,
-- never service_role — the role the backend actually uses for every
-- request. Most RLS policies that call it are moot for service_role
-- (which bypasses table RLS entirely), but Supabase Storage evaluates its
-- own storage.objects policies independently of that bypass, so a
-- service_role-backed Storage upload against a policy referencing
-- get_my_firm_id() fails outright with "permission denied for function
-- get_my_firm_id" — confirmed live: this silently broke the purchase-bill
-- invoice attachment upload (routers/document_intelligence_v1.py) added
-- earlier in this batch of work. Same class of bug as migrations 192-194
-- (grant_missing_*_privileges) — a recurring gap in this project between
-- "function exists" and "every role that ends up calling it can".
--
-- is_fy_locked() has the identical gap (same missing service_role grant,
-- same shape of function) — granting it here too since it's used by
-- services/period_validation_service.py, a genuinely live code path, to
-- close the same landmine before it also gets hit.
GRANT EXECUTE ON FUNCTION public.get_my_firm_id() TO service_role;
GRANT EXECUTE ON FUNCTION public.is_fy_locked(uuid, date) TO service_role;
