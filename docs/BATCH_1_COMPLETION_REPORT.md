# Batch 1 Completion Report — Revenue Operations & Knowledge Base Foundation

**Amendment v1.1 (Phase 10B) · Batch 1 of 7 · Schema + Security foundation only**
**Date:** 2026-06-14 · **Branch:** `claude/compassionate-darwin-nffpnb`
**Migration:** `apps/api/migrations/073_revenue_ops_foundation.sql` (+ `_rollback.sql`)

Batch 1 introduced **no** business logic, services, APIs, UI, or workflows — only
migrations, constraints, indexes, foreign keys, RLS, views, a role helper, and an
idempotent provisioning **function** (a foundation invoked in Batch 2).

---

## 1. New tables created (5)

| Table | Purpose | RLS |
|---|---|---|
| `billing_schedules` | Recurring/one-time billing arrangement per engagement (Amd §4.2) | **Partner-only** |
| `client_firm_customer_links` | G3: map a practice client → one customer in the internal client's books (Amd §4.3) | **Partner-only** |
| `knowledge_articles` | Versioned firm/department/client SOPs (Amd §4.4) | Firm-scoped |
| `knowledge_article_versions` | Version snapshots of articles | Firm-scoped |
| `client_instructions` | Pinned client standing instructions | Firm-scoped |

## 2. New columns added (4) — all nullable/defaulted (backward-compatible)

| Table | Column | Type | Default |
|---|---|---|---|
| `clients` | `is_internal` | `boolean` | `false` (NOT NULL) |
| `firms` | `internal_client_id` | `uuid` | NULL (FK → clients) |
| `users` | `cost_rate_paise` | `bigint` | NULL |
| `time_entries` | `billable_rate_paise` | `bigint` | NULL |

## 3. New indexes (9)

`idx_billing_schedules_firm_next_run` (partial `WHERE is_active`),
`idx_billing_schedules_firm_client`, `idx_cfcl_firm_customer`,
`UNIQUE(firm_id, client_id)` on `client_firm_customer_links`,
`idx_knowledge_articles_firm_scope`, `idx_knowledge_articles_firm_client`,
`idx_knowledge_articles_title_fts` (GIN), `idx_knowledge_articles_tags` (GIN),
`idx_kav_firm`, `idx_kav_content_fts` (GIN), `UNIQUE(article_id, version)`,
`idx_client_instructions_firm_client`.

## 4. New RLS policies (5)

- `billing_schedules_partner_only`, `client_firm_customer_links_partner_only` —
  `USING/WITH CHECK (firm_id = get_my_firm_id() AND get_my_role() = 'Partner')`
  (Partner = Owner-equivalent per approved role mapping; Guardrail G1 foundation).
- `knowledge_articles_own_firm`, `knowledge_article_versions_own_firm`,
  `client_instructions_own_firm` — firm isolation (client-assignment gating for
  client-scoped KB layered in Batch 6).

## 5. New views (1)

- `clients_external` (`security_invoker = true`) = `SELECT * FROM clients WHERE is_internal = false`.
  Guardrail **G2** single-source predicate for client counts, lists, Health triage,
  lifecycle dashboards, and client-facing Deadlines.

## 6. New functions (2)

- `get_my_role()` — SECURITY DEFINER STABLE; reads `users.role` for the JWT user.
- `provision_internal_client(firm_id, legal_name, entity_type, pan, gstin)` —
  SECURITY DEFINER, **idempotent**; creates the `is_internal=true` client and links
  `firms.internal_client_id`. Created as a foundation; **invoked in Batch 2** (not run now).

## 7. New foreign key (1)

- `firms_internal_client_id_fkey`: `firms.internal_client_id → clients(id) ON DELETE SET NULL`.

---

## 8. Migration risks (and mitigations)

| Risk | Severity | Mitigation / status |
|---|---|---|
| `ADD COLUMN is_internal NOT NULL DEFAULT false` rewrite on large `clients` | Low | PG11+ applies constant defaults without a table rewrite; verified fast + existing rows default `false`. |
| New tables/policies break existing queries | Low | Purely additive; no existing table/column/policy altered. Full suite: 971 passed, no new failures. |
| Partner-only RLS too strict / locks out backend | Low | Backend uses the service-role key which bypasses RLS (documented in `SECURITY.md`). |
| `service_id` has no FK (no `service_catalogue` table) | Low (tech debt) | Nullable, documented in `REVENUE_OPS_BRIDGE.md`; FK added if/when `service_catalogue` lands. |
| `billable_rate_paise` duplicates legacy `hourly_rate_paise` | Low (tech debt) | Coexist; bridge documented. No data migration. |
| Migration numbering collision | None | `073_*` is the next free number after `072`. |

## 9. Test results

Verified against a real PostgreSQL 16 instance via
`apps/api/tests/test_batch1_foundation_migration.py` (+ harness
`apps/api/tests/sql/batch1_foundation_verify.sql`):

- **Forward migration** applies cleanly; **applied twice** → fully idempotent (all
  objects `IF NOT EXISTS`/`OR REPLACE`/guarded).
- **Structural** assertions: columns/types/defaults, 5 tables, FK, UNIQUE, indexes,
  RLS enabled, policies present, view, functions — **PASS**.
- **Default-preservation**: legacy-style insert defaults `is_internal=false` — **PASS**.
- **clients_external** excludes internal, includes external — **PASS** (superuser and under firm RLS).
- **RLS partner-only**: staff blocked from `billing_schedules` read **and** write
  (WITH CHECK denial); partner allowed — **PASS**.
- **RLS firm isolation** on Knowledge Base (firm A cannot see firm B; staff can read
  firm KB) — **PASS**.
- **G2 under RLS**: firm sees 2 raw clients, 1 via `clients_external` — **PASS**.
- **Provisioning idempotency**: two calls return the same id; link set; exactly one
  internal client — **PASS**.
- **Rollback**: drops only new objects; columns/tables/view/functions gone;
  existing rows intact — **PASS**.
- **Regression**: full backend suite **971 passed**; the **23 failures are
  pre-existing Supabase-unavailable (HTTP 503) DB tests** in this container,
  identical before and after Batch 1 — **no regression**.

## 10. Discovered blockers / inputs for Batch 2

1. **Internal-client provisioning needs business inputs.** `clients.pan` is
   `NOT NULL` + regex-validated. `firms.pan` exists but is **nullable and
   unvalidated**, and `firms` has **no `entity_type`**. Batch 2 must source a valid
   PAN and an entity type (from firm settings/UI), and handle firms lacking a PAN
   (cannot provision until provided). This is the reason provisioning is deferred
   from Batch 1 to Batch 2.
2. **G4 (module cap) enforcement is not in Batch 1.** Blocking payroll/HR for the
   internal client is a Batch 2 service/API concern.
3. **G2 wiring.** `clients_external` exists, but switching every client-population
   query/endpoint to use it is Batch 2 work.
4. **Role mapping confirmed.** Partner = Owner-equivalent is implemented in
   `get_my_role()`-based policies; no `owner` DB role introduced (per decision).

**Status: Batch 1 complete and passing. Awaiting report review before Batch 2.**
