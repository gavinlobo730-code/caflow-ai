# Demo (Simulated) Filing Mode

A realistic, end-to-end **filing workflow simulation** for demos and the first
CA-firm trial — *before* any real government integrations exist.

> **This is NOT real filing.** Nothing is ever submitted to any government
> portal. Every screen carries a DEMO MODE banner and every reference is a
> visibly-fake `DEMO-`/`SIM-` value.

## Why it's safe (no false "filed" confidence)

The hard rule: **a user must never believe a real filing occurred.** Enforced by:

1. **Separate storage.** Simulated filings live in their own `demo_filings`
   table and **never** touch `compliance_calendar.filing_status`. A real
   deadline still reads `pending` / `overdue` after a simulation — the demo
   result is shown as a separate, clearly-labelled overlay.
2. **Distinct status label.** The UI shows **"Demo Filed"** / "Simulated Filing
   Complete" — never the bare word **"Filed"** for a simulated workflow.
3. **Fake references only.** `DEMO-ARN-…`, `DEMO-SRN-…`, `SIM-GST-…` — the
   `isDemoReference()` guard refuses to persist anything else, and the demo
   prefix means they can never collide with a real government reference.
4. **Required banner.** Every step shows: *"DEMO MODE — No data is being
   submitted to any government portal. This is a workflow simulation only."*

## Workflow

`Prepare Return → Validate Return → Simulate Filing → Processing animation →
Generate Demo ARN/SRN → Update status → Update dashboard → Update calendar`

Entry point: **Deadlines** (the cross-client compliance calendar) → the
**Simulate Filing** action on any simulatable row → `DemoFilingModal`.

## Where simulation applies (and where it doesn't)

| Area | Simulated? | Demo reference | Notes |
|------|-----------|----------------|-------|
| **GST** (GSTR-1/3B/9) | ✅ | `SIM-GST-XXXXXXXX` | |
| **TDS** (24Q/26Q, TCS) | ✅ | `DEMO-ARN-XXXXXXXX` | ARN = Acknowledgement Reference Number |
| **Income Tax** (ITR) | ✅ | `DEMO-ARN-XXXXXXXX` | |
| **MCA** (AOC-4/MGT-7) | ✅ | `DEMO-SRN-XXXXXXXX` | SRN = Service Request Number |
| **Advance Tax** | ❌ | — | A payment, not a return — no filing/ARN |
| **E-Invoice / IRN** | ❌ (deferred) | — | Real-time per-invoice IRN/ACK model, different surface — simulate later if needed |
| **XBRL** | ❌ | — | A document-generation step, not a portal submission with an ARN |

Naming used everywhere: **"Simulate Filing"**, **"Demo Filing"** — never
"File Return" / "Submit Return" without demo labelling.

## Integration points

- **Deadlines** (`app/deadlines/page.tsx`): per-row "Simulate Filing" button, a
  "Demo Filed" status overlay + demo reference, and a "Demo Filed" stat.
- **Dashboard** (`app/DashboardContent.tsx`): a "Demo Filed" indicator in the
  stats strip, shown only once simulations exist, clearly labelled DEMO.
- **Calendar**: the `/deadlines` compliance calendar is the DB-backed surface
  that carries filing status; the generic `/calendar` statutory-date grid has no
  per-record status and is intentionally left unchanged.

## Files

- `apps/web/lib/filing/demoFiling.ts` — pure helpers: reference generation,
  type→scheme mapping, eligibility, validation, status labels (+ `demoFiling.test.ts`).
- `apps/web/lib/data/demoFilings.ts` — read/write `demo_filings` (Supabase).
- `apps/web/components/DemoModeBanner.tsx` — the required banner.
- `apps/web/components/DemoFilingModal.tsx` — the Prepare→Validate→Simulate→Done flow.
- `apps/api/migrations/087_demo_filings.sql` (+ rollback) — `demo_filings` table, firm-scoped RLS.

## Tests

```bash
cd apps/web
node --experimental-strip-types --test lib/filing/demoFiling.test.ts
```

Covers per-type reference schemes, the "never a realistic government reference"
invariant, simulatability (advance tax excluded), the "Demo Filed" (never
"Filed") label, and validation rules.

## Deploying

Migration **087** must be applied to Supabase for the feature to persist demo
filings. It is additive, idempotent, and reversible (validated on a throwaway
Postgres). No backend (Render) change is required — the flow writes via the
Supabase client under firm-scoped RLS.
