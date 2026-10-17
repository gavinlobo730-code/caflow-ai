-- Rollback of migration 500: gives `authenticated` back what migration 014 granted on the Form 3CD checklist table.
-- It does NOT restore the platform-default TRUNCATE, REFERENCES and TRIGGER privileges for `authenticated`, nor anything
-- for `anon`: no migration ever granted them and a signed-in role has no use for them.
-- THIS RE-OPENS THE HOLE: a Partner, or a member assigned to a client, can again read and write that client's checklist,
-- its status and clauses included, directly over the database, whatever the route says.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.tax_audit_checklists TO authenticated;
