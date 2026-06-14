# Batch 2.1 Hardening Report — G1 by-id access guard

**Amendment v1.1 (Phase 10B) · Batch 2.1 (hardening) · Branch:** `claude/compassionate-darwin-nffpnb`
**Date:** 2026-06-14

## Objective

Close the G1 *direct-access-by-id* surface identified in the G2 assessment: because
the backend uses the Supabase SERVICE_ROLE key (RLS bypassed), a non-Partner who
supplies the internal practice client's id to a client-scoped **read** endpoint
could read its data. (G2 — accidental inclusion in populations/feeds — was already
comprehensively covered in Batch 2.)

## What was implemented

1. **Shared guard** `require_client_access` (`services/internal_client_service.py`):
   reads `client_id` from the request **path or query**; if it targets the firm's
   internal client and the caller is not a Partner → **404** (existence not
   disclosed). No-op when no `client_id` is present (firm-level endpoints).

2. **Applied at registration** in `main.py` via
   `include_router(..., dependencies=[require_client_access])` — verified to be the
   only reliable mechanism (mutating `router.dependencies` post-decoration does
   **not** apply). This makes it impossible for any existing or future endpoint in
   a guarded router to skip the check.

3. **Migration 074 extended** (defence-in-depth) to add restrictive policies on the
   client-scoped read tables: `client_timeline_events`, `documents`,
   `document_extractions`, `document_requests`, `ai_insights`, `government_notices`,
   `it_notices`, `tax_notices` (each applied only if it exists and has `client_id`).

### Routers guarded (client-scoped)

clients, documents, accounting, compliance_records, risks, ai_insights, ai_copilot,
tds, invoices, customers, vendors, sales_invoices, receipts, credit_notes,
purchase_bills, purchase_payments, gst_workspace, tds_workspace, mca_workspace,
document_intelligence_v2, payroll, fixed_assets, banking, timeline, year_end,
year_end_exports, relationships, health, ai_copilot_v2, memory_intelligence.

### Deliberately NOT guarded (with rationale)

- **portal** — separate auth audience (client portal users have no firm JWT);
  guarding with `get_current_user` would break it. The internal client has no
  portal users.
- **Firm-level routers** (team, workload, analytics, notifications, reminders,
  automation, workflow, tasks, lifecycle, etc.) — no `client_id` read surface; the
  guard would be a pure no-op, so not added to avoid touching unrelated auth.

## Remaining uncovered endpoints (residual surfaces)

| Surface | Why not covered by the path/query guard | Residual risk | Compensating controls |
|---|---|---|---|
| **Body-based compute** (`gst` classify/compute, `income_tax` compute, `itr_workspace`, `einvoice`/`eway_bill` create) | `client_id` arrives in the request **body**, not path/query | **Low** — these are compute/write actions (RBAC Executive+), not stored-data reads; would require a non-Partner to deliberately POST the internal id | RBAC gate; RLS restrictive policies (074) on the underlying tables for any direct DB access |
| **Year-end sub-routers** (checklist, adjustments, statements, notes, reviews, mappings) | scoped by `engagement_id`, not `client_id` | **Low** — requires `year_end` RBAC + a specific engagement id; internal-client year-end is Partner-driven | `year_end_engagements` is in the 074 restrictive list; main `year_end` + `exports` routers (which take `client_id`) are guarded |

Both residuals are **deliberately out of scope** per the instruction ("do not expand
scope beyond closing the identified by-id access surface", which was path/query
`client_id` **read** endpoints). They are documented here for a future hardening
pass if desired; neither is a population/feed leak.

## Test results

- **`test_batch2_1_client_access_guard.py` (5):** staff blocked from internal via
  query and via path (404); external access OK; Partner allowed; firm-level
  endpoints unaffected; app imports cleanly. PASS.
- **Batch 2 unit (6) + RLS harness (1):** PASS.
- **Full regression:** **983 passed**; the **same 23 pre-existing Supabase-503
  environmental failures** — no regression. The guard is a no-op in mock mode
  (no internal client), so existing client-scoped endpoint tests are unaffected.

## Final coverage status

| Guardrail | Status |
|---|---|
| **G2** (population/feed exclusion) | ✅ Comprehensive (Batch 2 + assessment) |
| **G1** by-id **read** access (path/query `client_id`) | ✅ Closed at API layer (all client-scoped routers) + RLS defence-in-depth |
| **G1** body-compute & engagement-id year-end | 🟡 Low-risk residual, documented, RBAC + RLS-covered, out of declared scope |
| **G1** internal client row / workspace | ✅ (Batch 2) |
| **G3 / G4** | ✅ (Batch 2: unique link constraint; payroll cap) |

**Residual risk: LOW.** The identified by-id read surface is closed. Remaining
residuals are RBAC-gated, RLS-covered, and non-aggregating.

**Status: Batch 2.1 complete and passing → proceeding to Batch 3 planning.**
