# PracticeSync — Architecture-to-Code Audit (Phase 0)

**Date:** 2026-06-14
**Scope:** Full frozen document set (Docs 1–7 + Amendment v1.1) vs. the existing `caflow-ai` codebase.
**Status:** Audit only — no production code written. Awaiting approval before implementation.

> **Naming note.** The product was renamed **CAflow AI → PracticeSync**. The repository, package names, and DB still say "CAflow AI". Rename is in scope but is cosmetic and must be done without breaking imports, env keys, or migrations.

---

## 0. Executive Summary

The repository is **not** a greenfield. It is a large, substantially-functional practice-management + compliance platform (~45 API routers, ~35 domain/service modules, 72 SQL migrations, 45 test files, a full Next.js dual-rail frontend). A large fraction of the **frozen core (Docs 1–7)** is already Implemented or Partially Implemented, and several table names already match Doc 5 exactly.

The gap concentrates in three places:

1. **Amendment v1.1 (Revenue Operations, Knowledge Base, Firm-as-Internal-Client)** — essentially **unbuilt**, and partially **contradicted** by an existing parallel `fee_*` billing stack.
2. **Platform-grade frozen-core additions** — Signing/UDIN, DPDP consent/rights/retention, Account Aggregator abstraction, versioned Compliance Rule Engine, WhatsApp Business API channel — **Missing or Partial**.
3. **Architectural divergences** from Doc 5 naming/role model that are *functionally equivalent* but not literally conformant (e.g. `tasks` vs `work_items`, 5-role vs 6-role model, `user_client_assignments` vs `firm_users_clients`).

**Recommended posture:** treat Amendment v1.1 as the first work (purely additive, well-specified, testable guardrails, explicitly highlighted by the stakeholder), and treat frozen-core divergences conservatively — document and bridge, do **not** rip-and-replace, because backward compatibility and zero regressions are hard constraints.

---

## 1. Current Implementation Status

Legend: ✅ Implemented · 🟡 Partial · 🟥 Missing · ⚠️ Diverged (works, but not as specified)

| Area | Status | Evidence / Notes |
|---|---|---|
| **Accounting** | ✅ | `chart_of_accounts`, `journal_entries`/`journal_lines` (paise, immutable via trigger — `058_*`), ledger, trial balance, P&L, balance sheet, period lock (`020_*`, `period_validation_service.py`). Names match Doc 5. |
| **GST** | ✅ / 🟡 IMS | Classifier (CGST §2(6)), GSTR-1 builder, GSTR-3B computer (Rule 36(4)), GSTR-9, 2A/2B upload + reconciliation (`036_*`, `domain/gst/*`). **IMS accept/reject/pending (`gst_ims_actions`) not present** → IMS-aware recon is 🟡. |
| **TDS** | ✅ | 24Q/26Q/27Q, deductions, challans, certificates (16/16A), §194 sections, 26AS reconciliation (`037_*`, `domain/tds/*`). |
| **Client Management** | ✅ | `clients`, lifecycle lead→prospect→onboarding→active→renewal→dormant→exit (`042_*`, `059_*`, `lifecycle.py`), onboarding checklists. |
| **Timeline** | 🟡 | `client_timeline_events` + `timeline_service.py` match Doc 5 well (category/severity/actor/amount_paise/visibility). **Append-only enforced in practice, not by DB trigger** → 🟡 vs Doc 5 §27.2. |
| **AI Memory** | ✅ | `memory_pipeline.py`, `client_profiles`, `client_profile_history`, `firm_profiles`, `pattern_anomalies`, memory triggers (`070_*`). Runs as job #11 of the daily scheduler sweep (`jobs/memory_job.py`, invoked from `run_daily_jobs`) — it was a self-scheduling thread until task #158. |
| **Health Engine** | ✅ | 7 dimensions w/ exact weights, composite, hard overrides, daily history, alerts, dashboard (`046_health_engine_foundation.sql`, `routers/health.py`). Strong match to Doc 1 §11.2 / Doc 5 §16. |
| **Work Management** | ⚠️ | Implemented as `tasks` + templates + dependencies + recurring + workflow builder + automation + escalation. **Not** the Doc 5 `work_items`/`pipeline_*`/`work_item_*` model ("one deliverable for one client in one period"). Functionally rich but diverged. |
| **Portal** | ✅ / 🟡 | `document_requests`, `portal_messages` (has `channel`), approvals, dues, employee portal. Separate client-portal surface exists. WhatsApp = 🟡 (page + channel field; **no WhatsApp Business API integration / `messaging_threads`**). |
| **Documents** | ✅ / 🟡 | Upload, extraction, Document Intelligence v1 (invoice) + v2 (notices), risks (`023/024/*`). **Tier-1/Tier-2 tiering + SHA-256 dedupe + generated-doc staleness** partially present → 🟡. |
| **Payroll** | ✅ | Employees, salary structures, runs, slips, PF 12% / ESI / PT / TDS §192, statutory summary, payslip PDF (`027_*`, `054_*`). |
| **Revenue Operations (Amd v1.1)** | 🟥 / ⚠️ | A **parallel** `fee_engagements`/`fee_invoices`/`fee_receipts` stack exists (`014_*`) with invoice gen, PDF, overdue lifecycle, portal dues. **None** of the Amendment model exists: no `billing_schedules`, no AR-aging buckets, no `client_firm_customer_links`, no firm-as-internal-client reuse. The existing stack is the "second accounting platform" the Amendment forbids. |
| **Knowledge Base (Amd v1.1)** | 🟥 | No `knowledge_articles`, `knowledge_article_versions`, `client_instructions`. No UI. |
| **Internal-Client Architecture (Amd v1.1)** | 🟥 | No `clients.is_internal`, no `firms.internal_client_id`, no Practice workspace, no guardrails G1–G4. |
| **Reporting** | ✅ | Financial statements, analytics, profitability, scheduled/shared reports, cash-flow, executive dashboard. |
| **Security (authz)** | ⚠️ | RBAC matrix solid (`core/permissions.py`). **Role model diverges**: code = Partner/Manager/Executive/Reviewer/Client (5); spec = owner/partner/manager/staff/viewer/client (6). **No `owner` role** — `Partner` is the de-facto top role. |
| **RLS** | ✅ / 🟡 | `get_my_firm_id()` firm-isolation on all tenant tables (`005_*`, `071_*`). **Client-assignment-gated RLS on financial tables (Doc 5 §27.1 second pattern) is inconsistent** — most policies are firm-only; staff↔client scoping is enforced mostly at the API → 🟡. |
| **Audit Trails** | ✅ | Immutable `audit_log` (`audit_service.py`), legacy `activity_logs`, task timeline events. |
| **Signing / UDIN** | 🟡 | `dsc_records` + DSC-tracker page exist. **No `signatures`/`signing_batches`/`udin_records`, no eSign, no batch signing service** (Doc 5 §21). |
| **Compliance Rule Engine (versioned)** | 🟡 | `compliance_engine.py` computes obligations + due dates. **Not the versioned, dated `compliance_rulesets`/`compliance_rules`/`client_obligations`** model (Doc 5 §26). |
| **DPDP (consent/rights/retention/breach)** | 🟥 | No `consents`, `data_rights_requests`, `retention_policies`, `breach_log`. Aadhaar present in payroll — **masking not verified**. |
| **Account Aggregator** | 🟡 | `bank_transactions` exists; **`ingest_source` abstraction + `aa_consents`/`aa_data_fetches` not present**. |
| **Tally import** | ✅ | `tally-migration` jobs, parse/preview/import/rollback (`domain/tally/migration_service.py`). |
| **Relationship Intelligence** | ✅ | `entities`, relationships, cross-client matches, §185 report, loans, properties (`047_*`, `relationships.py`). |
| **Tax / ITR / XBRL / e-invoice** | ✅ / 🟡 | ITR engine (regimes, §40/43 disallowances, §80 deductions, b/f losses), 26AS recon, e-invoice/e-way records, XBRL packages. Live rails = prepare-only (correct per Doc 7). |

---

## 2. Document Compliance Matrix (selected, high-signal)

| Document Requirement | Code Location | Status |
|---|---|---|
| FR-C-05 double-entry, balanced journals server-side | `domain/accounting_service.py`, `phase2_journal_service.py`; trigger `058_*` | Complete |
| Principle 2 — paise never float | `*_paise` columns across all money migrations; models validate | Complete |
| Principle 3 — journals immutable | `058_journal_immutability_and_validations.sql` | Complete |
| Principle 4 — every action a Timeline event | `services/timeline_service.py`, `client_timeline_events` | Partial (no DB append-only trigger) |
| FR-C-07 GSTR-1/3B/9 + 2B IMS-aware | `domain/gst/*`, `036_*` | Partial (IMS accept/reject/pending missing) |
| FR-C-08 TDS full | `domain/tds/*`, `037_*` | Complete |
| FR-AI-04 Health 7-dimension model | `routers/health.py`, `046_health_engine_foundation.sql` | Complete |
| FR-F-10 Work item = 1 deliverable/client/period | `tasks` model | Diverged |
| FR-F-09 / TRD §5.6 versioned rule engine | `compliance_engine.py` | Partial |
| TRD §5.5 Signing service (eSign + DSC batch) | `dsc_records` only | Partial |
| TRD §10.2 DPDP consent/rights/retention | — | Missing |
| TRD §10.1 six roles incl. Owner | `core/permissions.py` (5 roles) | Diverged |
| Doc 5 §27.1 assignment-gated RLS on financial tables | `005_*`, `071_*` (firm-only mostly) | Partial |
| **Amd FR-FIC-01..05 Firm-as-Internal-Client** | — | Missing |
| **Amd FR-REV-01..08 Revenue Operations** | `fee_*` (parallel, non-conformant) | Missing / Diverged |
| **Amd FR-KB-01..04 Knowledge Base** | — | Missing |
| **Amd schema: `billing_schedules`, `client_firm_customer_links`, KB tables, `is_internal`, `internal_client_id`, `cost_rate_paise`** | — | Missing |
| **Amd `time_logs.is_billable` / `billable_rate_paise`** | `time_entries.is_billable` ✅, `hourly_rate_paise` (name differs) | Partial |
| **Amd G1 partner-only RLS on internal client** | — | Missing |
| **Amd G2 `clients_external` exclusion predicate** | — | Missing |

---

## 3. Dependency Analysis & Implementation Order

**Blocking dependencies for Amendment v1.1 (the priority work):**

```
clients.is_internal ─┐
firms.internal_client_id ─┼─► (B1) Firm-as-Internal-Client provisioning + clients_external view
                          │        │
                          │        ├─► (B2) Guardrails G1 (partner-only RLS) + G2 (exclusion in counts/Health/lists/Deadlines)
                          │        │
client_firm_customer_links ─────► (B3) Billing reuse: sales_invoices owned by internal client
billing_schedules ──────────────► (B4) Recurring invoice generation (CA-confirm gate) + AR aging + reminders
                                   │
time_entries.is_billable (exists) ► (B5) Billable flag surfacing + cost_rate_paise (realization data capture)
knowledge_articles/versions ─────► (B6) Knowledge Base + client_instructions (independent, low-dep)
```

**Recommended batch order (smallest risk first):**
1. **B0** — Product rename CAflow→PracticeSync (cosmetic, reversible) *(optional / can defer)*.
2. **B1** — Additive schema: `is_internal`, `internal_client_id`, `cost_rate_paise`, billable columns reconciliation; `clients_external` view. (Pure migration, defaulted, backward-compatible.)
3. **B2** — Guardrails G1/G2 enforcement (RLS + API + every client-population query) + Practice workspace entry.
4. **B3** — `client_firm_customer_links` + internal-client customer provisioning (G3, no duplicate entity).
5. **B4** — `billing_schedules` + Billing Orchestration service (reuse Sales/GST) + AR aging view + collections/reminders.
6. **B5** — Billable/realization data capture (cost_rate, unbilled view).
7. **B6** — Knowledge Base (`knowledge_articles`, `knowledge_article_versions`, `client_instructions`) + search + Timeline link + client-workspace surfacing.

Frozen-core gap remediation (Signing/UDIN, DPDP, AA, versioned rule engine, IMS, WhatsApp) is **sequenced after** Amendment v1.1 unless you direct otherwise.

---

## 4. Risk Analysis

| Risk class | Specific risk | Severity | Mitigation |
|---|---|---|---|
| **Security / G1** | Firm financials leak to staff | High | RLS first (`role IN ('owner','partner')` — see role-model decision), then API role checks, then UI. Negative RLS tests **before** go-live. |
| **Data integrity / G2** | Internal client pollutes client counts / Health / lists ("client 101") | High | Single `clients_external` predicate/view feeding **every** population surface; Health computation skips `is_internal`. Regression tests on counts. |
| **Backward compat** | Existing `fee_*` billing already in use (router/PDF/portal dues) | High | Do **not** delete. Bridge or co-exist (see decision). Forward-only additive migrations only. |
| **Migration** | 72 existing migrations; numbering collisions (two `045_*`, two `046_*` already exist) | Medium | New migrations start at `073_`; idempotent guards; no destructive DDL. |
| **RLS** | Assignment-gated RLS inconsistent on financial tables | Medium | Audit + backfill assignment predicate where Doc 5 §27.1 requires; verify portal audience cannot reach firm tables. |
| **Performance** | AR aging / revenue dashboards at 100-client scale | Medium | Indexed views `(firm_id, next_run_date) where is_active`, `(firm_id, client_id)`; cursor pagination. |
| **Scope drift** | Revenue *Intelligence* / ERP creep | Medium | Hold FR-RI in Phase 13+; G4 blocks payroll/HR for internal client. |
| **Doc/state drift** | `security_audit_phase13b.md` references `supabase/migrations/011` but real migrations live in `apps/api/migrations` w/ different numbers | Low | Correct/annotate during rename batch. |

---

## 5. Finalized Roadmap — Amendment v1.1 (Phase 10B)

**Approved decisions (2026-06-14):**
- **Billing:** Amendment model; **bridge** `fee_*`. Keep `fee_*` readable as a legacy compatibility layer; **no historical data migration** this phase; route all NEW Revenue Operations through `sales_*` owned by the internal client. Build an adapter so existing screens/reports keep working. Document all bridge points + tech debt.
- **Roles:** Map onto existing 5 roles. **Partner = Owner-equivalent.** G1 = Partner-only access to Practice workspace, internal-client records, firm revenue, collections/AR, GST/TDS on firm fees. No new auth roles, no user migration.
- **Scope:** Amendment v1.1 only. No IMS / versioned rule engine / Signing-UDIN / DPDP / AA / WhatsApp / naming reconciliation / broad refactors. Frozen-core gaps found mid-flight are tracked separately unless they block delivery.
- **Rename:** PracticeSync rename first (user-facing only; internal package/env keys unchanged).

Every batch ships with: unit + integration + **RLS negative** + permission + migration + regression tests, and a forward-only rollback that drops only the new objects. Batches execute strictly in order; the next does not start until the current passes.

### Batch 0 — Rename CAflow → PracticeSync (cosmetic)
- **Files:** `apps/web` UI strings/title/logo text, `README.md`, `CLAUDE.md` product name, `docs/*`. **Unchanged:** package names, env var keys (`GROQ_API_KEY` etc.), import paths, DB identifiers.
- **DB/API:** none functional (FastAPI app title only).
- **Tests:** frontend build smoke; grep guard that no env/import keys changed.
- **Rollback:** revert strings.

### Batch 1 — Additive schema foundation (migration `073_*`, forward-only)
- **DB:** `clients.is_internal bool not null default false`; `firms.internal_client_id uuid null → clients(id)`; `users.cost_rate_paise bigint null` (maps spec `firm_users.cost_rate_paise`); `time_entries.billable_rate_paise bigint null` (alongside existing `is_billable`, `hourly_rate_paise` — bridge documented). New tables: `billing_schedules`, `client_firm_customer_links`, `knowledge_articles`, `knowledge_article_versions`, `client_instructions`. View: `clients_external` (= `is_internal = false`). RLS enabled on all new tables (firm isolation; partner-only on billing/links).
- **Tests:** migration applies + idempotent; existing rows default `is_internal=false`; no existing query regresses.
- **Rollback:** `073_down` drops new tables/columns/view.

### Batch 2 — Firm-as-Internal-Client provisioning + Guardrails G1–G4
- **API/Service:** provision one internal client per firm (`is_internal=true`, set `firms.internal_client_id`); cap modules to accounting+GST+TDS+documents+reports+billing (G4 blocks payroll/HR). Route every client-population surface (count, Clients list, Health computation/triage, lifecycle dashboards, client-facing Deadlines) through `clients_external` (G2). Partner-only enforcement in RLS + API for internal-client + firm-financial reads (G1).
- **UI:** none yet (B7).
- **Tests:** **RLS negative** — staff/manager/executive/reviewer cannot read internal-client financial rows; **regression** — client counts/Health/lists exclude internal client; G4 — payroll provisioning blocked for internal client.

### Batch 3 — Revenue Operations: recurring billing via Sales reuse
- **API/Service:** `client_firm_customer_links` (G3, one customer per practice client in internal-client books); Billing Orchestration (`billing.previewRun`, `billing.generateInvoice` idempotent) materialising `billing_schedules` → draft `sales_invoices` (GST applied via existing engine) behind **CA-confirm gate**; receipts reuse `receipts`/`sales_receipts`; credit notes reuse existing mechanism. Timeline events on the internal client throughout.
- **Tests:** invoice generation idempotency; GST applied correctly (paise); CA-confirm gate precedes despatch; appears in firm revenue AND client billing tab via the link (no duplicate entity).

### Batch 4 — Collections, AR aging, GST/TDS on firm fees
- **API/Service:** invoice status lifecycle from receipts (raised→sent→part-paid→paid→overdue); `ar.aging` (0–30/31–60/61–90/>90) view; `collections.sendReminder` via existing notification/portal channels (+Timeline); record TDS deducted by clients on firm fees as a receivable; firm-level Collections/AR aggregate (Partner-only).
- **Tests:** aging bucket arithmetic; reminder writes Timeline; AR aggregate excludes nothing/leaks nothing; partner-only visibility.

### Batch 5 — Billable flags + staff cost rates (data capture only)
- **API/Service:** surface `is_billable` + `billable_rate_paise`; `users.cost_rate_paise` capture; "unbilled work" view per client/work-item. (Revenue *Intelligence* / realization explicitly deferred — data capture only.)
- **Tests:** unbilled view correctness; cost-rate partner-only.

### Batch 6 — Knowledge Base + client instructions
- **API/Service:** versioned articles (firm/department/client scope) with `knowledge_article_versions` snapshots; `client_instructions` pinned per client; full-text search; Timeline links. Client-scoped rows honour client assignment (staff see only assigned-client instructions).
- **Tests:** version history integrity; search; RLS — staff see only assigned-client instructions.

### Batch 7 — Frontend (Partner-only Practice workspace + Revenue/KB UI)
- **UI:** distinct **Practice** entry on Rail 1 (Partner-only, does not render for others); reuse client workspace shell. Firm Collections/AR dashboard (aging, overdue, one-click reminder); per-client Billing tab; KB section (firm/department articles + version history); client-instruction cards pinned atop client Overview. Money in Indian format from paise. Firm-financial surfaces **absent** (not merely hidden) for non-partners.
- **Tests:** Practice entry hidden for non-partners; no client-count/Health surface shows the internal entity; money formatting.

### Cross-cutting deliverable
- `docs/REVENUE_OPS_BRIDGE.md` — every `fee_*` ↔ `sales_*` bridge point and the technical debt the legacy compatibility layer carries, per the billing decision.
</content>
</invoke>
