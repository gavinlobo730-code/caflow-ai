# PracticeSync Amendment v1.1 — Deployment Readiness Audit

**Date:** 2026-06-14 · **Scope:** Batches 1–7 · **Branch:** `claude/compassionate-darwin-nffpnb`
**Method:** manual verification (not trusting passing tests) + real-Postgres checks. Issues found were fixed, re-tested, re-audited.

---

## 1. Executive summary

Amendment v1.1 (Firm-as-Internal-Client, Revenue Operations, Collections/AR, billable/cost capture, Knowledge Base, and the Practice/Knowledge frontend) is **functionally complete and internally consistent**. Migrations `073`–`080` are ordered, idempotent, and rollback-safe; the API contract between the new frontend and backend is consistent; guardrails G1–G4 hold at the backend (RBAC + RLS dual-layer).

The audit found **two real issues**, both **now fixed and re-verified**:
1. **G2 frontend pollution** — the firm's internal client appeared (to Partners) in the Clients list, dashboard count, and global search, because those surfaces query Supabase directly (bypassing the backend's `clients_external` exclusion). **Fixed.**
2. **Duplicate internal client risk** — no DB constraint prevented concurrent provisioning from creating two internal clients per firm. **Fixed** (migration `080` partial unique index + `provision()` race handling; verified against Postgres).

No **critical** (deployment-blocking, data-loss, or unauthorized-access) issues remain.

**Classification: (2) Production Ready with Minor Fixes** — deploy after applying migrations `073`–`080` to Supabase and running provisioning/CoA backfill; the remaining items are documented medium technical debt (none critical).

---

## 2. Critical findings — must-fix before deployment

**None remaining.** (The two real issues below were High and are fixed.)

---

## 3. High priority findings — FIXED

### H1 · G2 frontend pollution (internal client visible to Partners in lists/search) — FIXED
- **Evidence:** ~30 frontend call sites query `supabase.from("clients")` directly; RLS (`074` restrictive `clients_internal_partner_only`) hides the internal client from non-partners but **shows it to Partners**. The backend `/api/clients` excludes it, but the frontend bypasses the backend.
- **Impact:** Partners would see the internal client in the **Clients list**, the **dashboard "total clients" count**, and **global search** ("client 101" pollution — exactly the G2 risk). Not a leak to unauthorized roles (RLS correctly hides it from staff); a Partner-visible correctness issue.
- **Fix (applied):** added `.eq("is_internal", false)` to the three population surfaces — `lib/data/clients.ts::getClients()` (Clients list + most dropdowns), `app/DashboardContent.tsx` (count + recent list), `app/search/page.tsx`. Backward-compatible (all rows are `is_internal=false` until an internal client exists).

### H2 · Duplicate internal client under concurrency — FIXED
- **Evidence:** `internal_client_service.provision()` and the SQL `provision_internal_client()` do check-then-insert with **no DB uniqueness**; two concurrent calls (double-click "Set up Practice", or a create_firm race) could insert two `is_internal=true` clients per firm.
- **Fix (applied):** migration **`080`** adds `CREATE UNIQUE INDEX … ON clients(firm_id) WHERE is_internal` (verified on Postgres: a second internal client is rejected). `provision()` now **catches the unique violation and returns the winning row** (idempotent, no duplicate, no error surfaced).

---

## 4. Medium priority findings — technical debt (non-blocking)

| # | Finding | Impact | Recommendation |
|---|---|---|---|
| M1 | Client-picker **dropdowns** in ~10 pages (gst/gstr1, gstr3b, payroll, payroll/statutory, accounting/loans, invoices, receivables, fixed-assets, suppliers, schedule-iii, bank-reconciliation, auto-journals, scheduled-reports, whatsapp) still query `clients` directly without `is_internal=false`. | Partner-only cosmetic: the internal client could appear in a client picker (it has no GST/payroll work). Not a leak (RLS hides from staff). | Switch these to `getClients()` or add `.eq("is_internal", false)` in a follow-up sweep. |
| M2 | AR Dashboard has buckets/totals but **no per-invoice drill-down + record-receipt (incl. `tds_paise`) form**; `api.salesInvoices`/`api.receipts` namespaces are wired but unused in the UI. | Collections done via API but not fully UI-driven. | Add the per-invoice receipt form (Batch 7 follow-up). |
| M3 | **Frontend role drift** — FE roles `Partner/Manager/Article/Staff` vs backend 6. Executive/Reviewer assignment-gating relies on backend enforcement (FE shows write controls; API authorises/403s). | No security gap (backend authoritative); UX could show a control that 403s. | Align FE to the 6-role model + surface 403s gracefully. |
| M4 | Pre-existing FE business-logic violations (`lib/services/health-*`, `relationship-intelligence`, `lib/repositories/*`, large inline-CRUD pages). | Architecture-rule drift (pre-Amendment). Batch 7 added none. | Separate cleanup pass. |
| M5 | `075` does `ENABLE ROW LEVEL SECURITY` + adds a permissive `client_sales_invoices_own_firm` policy; if a same-purpose policy already exists it is additive (OR, same firm predicate). | Harmless (no access widening beyond firm). | None required; documented. |
| M6 | App-wide Next warnings (`themeColor` metadata, `no-img-element`) inherited by all routes. | Cosmetic; pre-existing. | Move `themeColor` to a viewport export. |

---

## 5. Migration readiness assessment (073–080)

| Mig | Purpose | Ordering deps | Idempotent | Rollback | Real-Supabase risk |
|---|---|---|---|---|---|
| 073 | Schema foundation (cols, KB tables, billing_schedules, links, view, provision fn, firm RLS) | needs 005 `get_my_firm_id` | ✓ (IF NOT EXISTS / OR REPLACE / guarded FK) | ✓ | Low — `is_internal NOT NULL DEFAULT false` is a constant default (no rewrite) |
| 074 | Internal-client RLS guardrails (G1) | needs 073 `get_my_role` | ✓ (DO-loop existence/column checks) | ✓ | Low — skips non-existent tables; `IS DISTINCT FROM` handles NULL |
| 075 | Billing traceability + idempotency index + `client_sales_invoices` G1 RLS | needs 073/074 helpers, `billing_schedules` | ✓ | ✓ | Low — status CHECK already allows `partially_paid`; permissive policy additive |
| 076 | invoice→journal link (atomic issue / recovery) | needs `client_sales_invoices`, `journal_entries` | ✓ | ✓ | Low |
| 077 | Collections/AR cols + `receipts.tds_paise` | needs `client_sales_invoices`, `receipts` | ✓ | ✓ | Low |
| 078 | Billed linkage; **`is_billed` GENERATED** | needs `client_sales_invoices`, `time_entries` | ✓ | ✓ | Low — GENERATED needs PG12+ (Supabase ≥15) |
| 079 | KB assignment-gated RLS + `get_my_user_id` | needs 073 KB tables, 073/074 helpers, 022 `user_client_assignments` | ✓ | ✓ | Low — RLS subquery needs authenticated grant on `user_client_assignments` (present, migration 041) |
| 080 | One-internal-client-per-firm unique index (audit fix) | needs `clients.is_internal` (073) | ✓ | ✓ | Low — apply **before** provisioning; would fail only if duplicates already exist (none pre-provision) |

All eight verified via self-contained Postgres harnesses (forward + idempotent re-apply + rollback). **Apply in numeric order 073 → 080.**

---

## 6. Supabase deployment readiness

**Safe to apply 073–080**, with this sequence (in an MCP-enabled session; recommend a Supabase **branch** first, then merge):
1. Apply `073`→`080` in order (forward-only, additive, idempotent).
2. Run `get_advisors` (security + performance) after apply; expect no new missing-RLS findings (new tables have policies).
3. **Provision + backfill:** internal-client provisioning + firm CoA seeding are idempotent and run via `create_firm` onboarding and `POST /api/practice/provision`; trigger once per existing firm post-deploy (CoA seed via `seed_firm_coa`). `080` must be applied **before** mass provisioning.
4. The backend uses the **service-role key (RLS bypassed)** — the API/repository layer is the effective control; RLS is defense-in-depth. This is by design and consistently enforced.

**Not yet applied to the live project** (the MCP approval gate was blocking earlier) — this is the one remaining deployment action, not a code defect.

---

## 7. Verification results (post-fix)

- **Backend:** `pytest` → **1025 passed**; 23 failures are the long-standing Supabase-unavailable (HTTP 503) DB tests in this container — unchanged, environmental, not Amendment-related.
- **Frontend:** `pnpm build` → **Compiled successfully** (full strict type-check; all 10 new routes build).
- **Permissions:** `lib/auth/permissions.test.ts` → **6/6 pass** (Practice partner-only/absent for others; Knowledge all-staff; legacy billing unchanged; existing gating intact).
- **Migration 080:** Postgres check → duplicate internal client rejected; external client allowed.
- **API contract:** every Batch-7 `api.*` call cross-checked against its backend route + `{success,data,error}` shape — consistent (response fields used by the UI exist in the backend responses).

---

## 8. Final recommendation

**Fix-first items are done.** No critical issues remain.

**Recommendation: deploy after the migration step** —
1. Apply migrations `073`–`080` to Supabase (branch → verify → merge) in a fresh MCP-enabled session.
2. Run `get_advisors`; provision internal clients + seed firm CoA (idempotent).
3. Schedule the medium debt (M1 dropdown sweep, M2 AR receipt UI, M3 role alignment) as a follow-up — none block release.

**Classification: (2) Production Ready with Minor Fixes.**
