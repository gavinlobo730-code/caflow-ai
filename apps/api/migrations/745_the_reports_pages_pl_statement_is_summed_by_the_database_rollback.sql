-- Rollback of migration 745: drops public.report_party_totals. The API falls back to its Python twin
-- (domain/reporting/party_totals.py) when the function is absent, so the screen keeps working.
DROP FUNCTION IF EXISTS public.report_party_totals(uuid, uuid[], date, date);
