# Decision Document — Internal (Practice) Client Visibility

**Phase 3.3A · Part F · Decision report only (no implementation in this phase).**

## Question

Should the firm's own internal practice client (`clients.is_internal = true`,
linked by `firms.internal_client_id`) remain **Partner-only**, or be treated like
any normal client visible to assigned staff?

## Current implementation (verified against the live system)

The accounting / reporting / banking **engines are client-agnostic** — they never
branch on `is_internal`. All special handling is in the access/visibility layer,
under four guardrails:

| Guardrail | Where enforced (evidence) |
|---|---|
| **G1 — Partner-only access** | `internal_client_service.assert_can_view_client` / `assert_partner_for_internal_id` (404 to non-Partners); router guard `require_client_access` mounted on accounting/banking/clients/gst/tds in `main.py`; RBAC `practice`+`billing` resources are Partner-only |
| **G2 — excluded from client lists** | `client_repository.find_all/count` (`is_internal=false` default); frontend `lib/data/clients.ts` (`.eq("is_internal", false)`); analytics/search exclusions |
| **G3 — one linked customer** | one customer per practice client (revenue-ops) |
| **G4 — module cap** | `assert_not_internal_for_payroll` (no payroll/HR for the internal client) |
| **RLS (defence-in-depth)** | migration 074 restrictive policies: `get_my_role()='Partner' OR client_id IS DISTINCT FROM my_internal_client_id()` on `clients`, `journal_entries`, sales/GST/TDS tables (binds the anon-key browser; the service-role backend relies on the app-layer checks above) |

## Option A — Keep Partner-only (status quo)

**Pros**
- The firm's own books (partner drawings, profitability, fee realisation) are
  commercially sensitive; restricting to Partners matches real CA-firm practice.
- Already fully built, tested (`test_batch2*`), and enforced at three layers
  (RBAC, app guard, RLS) — zero new work, zero new risk.
- Prevents an Executive/Reviewer assigned to "all clients" from inadvertently
  seeing the firm's internal financials.

**Cons**
- Two visibility rules to reason about (normal vs internal).
- Minor inconsistency: some report client-pickers (financial-statements,
  schedule-iii, cash-flow, GST) query Supabase directly without the
  `is_internal=false` filter and lean on RLS alone (works, but not belt-and-suspenders).

**Security impact:** Strongest posture. The internal client is invisible to
non-Partners by existence (404), by list-exclusion, and by RLS.

## Option B — Treat like a normal client

**Pros**
- One uniform mental model; the literal reading of "the practice behaves like any
  other client." Removes the G1/G2 branches.

**Cons**
- Exposes the firm's own financials to any staff with a broad client assignment.
- Requires removing/relaxing G1, G2, and the migration-074 RLS policies — a
  net **reduction** in security on sensitive data, plus a migration and test rewrite.
- Contradicts how CA firms actually treat their own books.

**Security impact:** Weaker. Internal financials become visible to non-Partners
per normal assignment scope.

## Recommendation — **Option A (keep Partner-only)**

Keep the engine client-agnostic (already true and the right invariant) but retain
the Partner-only **access** overlay. Reword the guiding principle to:

> *"The practice is just another client to the accounting/reporting/banking
> **engines**; it is access-restricted to Partners at the visibility layer."*

This satisfies the spirit of Practice-as-Client (no special accounting logic)
without downgrading the security of the firm's own books. If uniformity is later
desired, Option B remains available as a deliberate, migration-backed change.

**Optional low-risk hardening (not required):** add the `is_internal=false`
filter to the report/GST client-pickers so G2 is belt-and-suspenders rather than
RLS-only. Deferred — out of Phase 3.3A scope.
