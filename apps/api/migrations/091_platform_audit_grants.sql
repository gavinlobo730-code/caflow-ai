-- 091_platform_audit_grants.sql
-- platform_audit was created without DML grants for service_role (it only had
-- REFERENCES/TRIGGER/TRUNCATE), so the backend's audit insert during a firm
-- purge failed with permission-denied — the purge itself succeeded (SECURITY
-- DEFINER runs as the owner) but the endpoint then 500'd on the audit write.
-- Grant DML to service_role (which also bypasses the table's RLS). anon /
-- authenticated remain without access.

grant select, insert, update, delete on platform_audit to service_role;

-- Rollback: revoke select, insert, update, delete on platform_audit from service_role;
