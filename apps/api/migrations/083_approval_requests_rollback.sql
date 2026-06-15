-- Rollback for 083_approval_requests.sql
DROP POLICY IF EXISTS "approval_requests_read" ON public.approval_requests;
DROP TABLE IF EXISTS public.approval_requests;
