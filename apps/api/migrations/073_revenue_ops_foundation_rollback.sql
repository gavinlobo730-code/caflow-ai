-- PracticeSync AI — Migration 073 ROLLBACK (Revenue Operations & KB Foundation)
-- Forward-only rollback: drops ONLY the objects created by 073, restoring the
-- pre-073 schema exactly. Safe/idempotent. Drops dependent objects (policies via
-- table drops) before the functions they reference.
--
-- NOTE: this removes Batch 1 structures only. No existing table, column, route,
-- or workflow is affected. Run against a database where 073 was applied.

-- 8 / 9. View + provisioning + role helper (drop view & functions; tables below
-- carry the policies that reference get_my_role()/get_my_firm_id()).
DROP VIEW IF EXISTS clients_external;
DROP FUNCTION IF EXISTS provision_internal_client(UUID, TEXT, TEXT, TEXT, TEXT);

-- 2–4. New tables (dropping a table removes its RLS policies, indexes, FKs).
DROP TABLE IF EXISTS client_instructions;
DROP TABLE IF EXISTS knowledge_article_versions;
DROP TABLE IF EXISTS knowledge_articles;
DROP TABLE IF EXISTS client_firm_customer_links;
DROP TABLE IF EXISTS billing_schedules;

-- 5. Role helper (dropped after the policies that used it are gone).
DROP FUNCTION IF EXISTS get_my_role();

-- 1. Column additions + FK on existing tables.
ALTER TABLE firms        DROP CONSTRAINT IF EXISTS firms_internal_client_id_fkey;
ALTER TABLE time_entries DROP COLUMN IF EXISTS billable_rate_paise;
ALTER TABLE users        DROP COLUMN IF EXISTS cost_rate_paise;
ALTER TABLE firms        DROP COLUMN IF EXISTS internal_client_id;
ALTER TABLE clients      DROP COLUMN IF EXISTS is_internal;
