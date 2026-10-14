-- Rollback of migration 497: restores the table-level SELECT that migration 109 gave `authenticated`.
-- THIS RE-OPENS THE HOLE: any staff member who can reach a client can again read the live invite token of a portal contact
-- who has not yet accepted. (Column-level grants left behind are harmless: the
-- table-level grant covers them.)
GRANT SELECT ON public.client_portal_users TO authenticated;
