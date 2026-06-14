-- PracticeSync AI — Migration 080: enforce one internal client per firm (Audit fix)
-- Amendment v1.1. Additive, idempotent. Closes the concurrency gap where two
-- simultaneous provisioning calls could create duplicate is_internal=true clients
-- (provision() check-then-insert is not atomic on its own).
--
-- A partial UNIQUE index guarantees at most one internal practice client per firm
-- at the database level. Apply alongside 073–079 BEFORE provisioning runs.

CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_one_internal_per_firm
  ON clients(firm_id) WHERE is_internal;
