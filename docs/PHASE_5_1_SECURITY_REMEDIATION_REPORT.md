# Phase 5.1A–5.1C — Security Remediation: Final Report

**Status:** ✅ Merged to `main` (PR #130, merge commit `b9f6394`) and CI-green.
**Scope:** Tenant-isolation remediation from the Phase 5 platform audit. **Code-only — no DB migrations, no schema changes.**
**Date closed:** 2026-06-21.

---

## 1. Root-cause posture (C1)

Backend endpoints obtain their DB handle from `get_supabase()`. The per-user-JWT
cutover (`USE_USER_JWT`) **defaults OFF**, so `get_supabase()` returns the
Supabase **service-role** client, which **bypasses Postgres RLS**
(`core/supabase_client.py`, `core/security_config.py`). Consequence:

> **App-layer firm-scoping is currently the *only* tenant-isolation control on
> the API path.** Any by-id endpoint that locates its row by the path id alone
> (no `firm_id` predicate) can read or mutate another firm's row when the caller
> knows the id.

Every fix below adds the missing app-layer scope. The systemic alternative
(turning on `USE_USER_JWT` so RLS also applies on the backend) is validated as a
Phase 5.2 workstream — see `PHASE_5_2_E2E_UAT_PLAN.md`.

The fix pattern is uniform and reuses the existing authz engine (`core/authz.py`)
— **no second isolation system was introduced**:

- Firm-scope the **guard read**: `.eq("firm_id", current_user.get("firm_id"))` ⇒ a foreign-firm id returns no row ⇒ `404`.
- Firm-scope the **write** (`update`/`delete`) the same way ⇒ defence-in-depth; a foreign row is never mutated even if the guard is bypassed.
- For list/summary surfaces, reuse `filter_by_client` / `assert_client_access` / `effective_client_ids`.

---

## 2. Findings closed

### 5.1A — Release blockers (H1–H4)
| ID | Area | Fix |
|----|------|-----|
| H1 | `workload.get_user_workload` | User lookup scoped `.eq("firm_id", firm_id)` + 404 on foreign user. |
| H2 | Compliance records list/get/summary | `filter_by_client` / `assert_client_access` / `effective_client_ids` applied. |
| H3 | Receipts AR-drift on re-allocation | `update_allocations` firm-scopes the receipt, pre-validates allocations in (firm, client), and reverses prior allocations before re-applying. |
| H4 | Bank settlement | `_settle_doc` / `_settlement_preview` scoped by firm + client. |

### 5.1B — Security closure (F1–F3) + C1 decision
| ID | Area | Fix |
|----|------|-----|
| F1 | Receipt creation | `create_receipt_core` pre-validates each allocation invoice in (firm, client) before insert (422 on foreign); per-invoice select/update scoped. |
| F2 | Compliance firm-summary | `get_firm_summary(allowed_client_ids=...)` filters records + clients by the caller's assigned clients. |
| F3 | Bank-posting settlement | Settlement preview/commit scoped by firm + client (double-compatible `.limit(1)` read, not `.maybe_single()`). |
| C1 | `USE_USER_JWT` posture | Documented; no code change. Cutover seam is correct; gated on live staging E2E (Phase 5.2). |

### 5.1C — Out-of-scope finding closures
| ID | Area | Fix |
|----|------|-----|
| OOS-1 | `purchase_payments` bill status writer | Scoped by firm + client. **Theoretical** — `PurchasePaymentIn` has no `purchase_bill_id` field, so the writer is unreachable via the API; kept as defensive. |
| OOS-2 | Sales-invoice mutations (update/issue/cancel/delete/repost) | Fetch + update firm-scoped. |
| OOS-4 | By-id detail **reads** (invoice, purchase bill, customer, vendor, credit note) | Detail fetch firm-scoped ⇒ foreign id 404s (no cross-firm disclosure). |
| **OOS-5** | By-id **WRITE** endpoints | **customers** (update/deactivate), **vendors** (update/deactivate), **purchase_bills** (update/receive/cancel), **credit_notes** (issue) — guard read + write firm-scoped. |

---

## 3. Final question — do any confirmed practical HIGH tenant-isolation findings remain?

**No.** In the audited core transactional scope (sales invoices, purchase bills,
purchase payments, receipts, customers, vendors, credit notes, compliance
records, workload — both by-id **reads** and **writes**), all confirmed practical
HIGH findings (H1–H4, F1–F3, OOS-1/-2/-4/-5) are closed and covered by negative
cross-firm tests.

### Carried forward (documented, not fixed — per scope-lock discipline)
- **OOS-6 (MEDIUM, read-disclosure):** three secondary reads remain unscoped —
  `purchase_bills.py` create-time vendor lookup, and the customer/vendor
  *outstanding* reads. These can leak existence/balance cross-firm but **cannot
  write**. Recommend closing alongside the OOS-7 sweep.
- **OOS-7 (NEW — UNCONFIRMED, needs RCA):** a platform-wide population of by-id
  writes in **non-core** routers/services (e.g. `year_end*`, `fixed_assets`,
  `invoice_deliveries`, `lifecycle` onboarding/checklists, `collections_service`,
  `knowledge_service`, banking services) shares the same structural pattern. Many
  are already firm-scoped or reached only via a firm-validated parent flow /
  webhook (provider-id keyed); the remainder require **per-endpoint exploitability
  RCA**. This is a candidate hardening sprint for the Phase 5.2 program, **not a
  confirmed release blocker**.

---

## 4. Evidence & verification

- **New OOS-5 tests:** `apps/api/tests/test_oos5_write_scope_5_1c.py` — **16 tests**:
  for every closed write endpoint, a foreign-firm id ⇒ `404` **with the seeded row
  left untouched** (no cross-firm write lands) + a same-firm success (legitimate
  use still works).
- **Security sweep (5.1A→5.1C):** 47 passed (`test_audit_remediation_5_1a` 8,
  `test_security_closure_5_1b` 10, `test_security_closure_5_1c` 2,
  `test_oos2_sales_invoice_scope` 5, `test_read_path_scope_5_1c` 6,
  `test_oos5_write_scope_5_1c` 16).
- **Full backend regression:** **1551 passed / 7 skipped**; the 24 remaining
  failures are the pre-existing environmental set (external-service 503s +
  one stale router-mount introspection test) that are green in CI. **+16 vs. the
  1535 baseline = exactly the new tests. Zero regressions.**
- **CI:** Backend CI green on the PR head (`40a34a0`, run #205) and on the merge
  commit on `main` (`b9f6394`, run #206). Frontend CI path-skipped (backend-only);
  Cloudflare Pages preview succeeded; Supabase Preview skipped (no migrations).
- **Post-merge production verification:** the OOS-5 firm-scoping and the 16-test
  file are confirmed present on `origin/main`; `main` CI is green. Live
  authenticated cross-firm probing against the deployed API is part of the
  Phase 5.2 staging E2E program (cannot be run headlessly here).

---

## 5. Commits

`bedc62f` (5.1A) · `ffdff1e` (5.1B) · `3cd16c3` (OOS-1) · `e6efe7b` (OOS-2) ·
`714dd0c` (read-path/OOS-4) · `40a34a0` (OOS-5) — merged via `b9f6394` (PR #130).
