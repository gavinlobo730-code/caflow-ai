# Demo (simulated) filing

A portal-faithful **walk-through** of each statutory filing, so the flow can be
shown and rehearsed before any real government integration exists.

> **Nothing is ever filed.** No demo path transmits anything, writes any return,
> or records any filing. Every stage carries a DEMO banner, every reference is
> either the honest `SIM-NOT-FILED` or a realistic-looking one wearing a
> **SPECIMEN** badge at the point of display.

## There is one implementation

**`apps/api/services/filing_demo/`** builds each flow as a list of stages in a
small fixed vocabulary — summary, table, warning, declaration, signature, otp,
transmit, result — in the real portal's order for that filing.
**`apps/web/components/FilingDemoWizard.tsx`** renders whatever it is given. A
new statutory flow is a new server-side definition and zero new UI.

One flow per statutory filing, served by `POST /api/filing-demo/{flow}/preview`,
listed by `GET /api/filing-demo/capabilities`.

### Why one, emphatically

Two demos of one filing drift, and each needs its own safety argument. This has
already happened twice and been undone twice:

1. **A bespoke GSTR-3B simulation** at `POST /gst-workspace/gstr3b/{id}/simulate-filing`
   — the first built. Deleted when the shared framework replaced it, rather than
   left beside it.
2. **A browser-side simulation** — `components/DemoFilingModal` +
   `lib/filing/demoFiling` + `lib/data/demoFilings`, reachable from
   `/deadlines`. Deleted 2026-09-05, and it is worth saying exactly what was
   wrong with it, because it looked fine:

   - it generated the demo reference and ran the validation **in the browser**;
   - it wrote the result **straight to `demo_filings` over PostgREST**, so
     `rbac()` never ran and only RLS applied;
   - **it never called the server at all** — so it never asked
     `/api/filing-demo/capabilities`, and **`ENABLE_FILING_SIMULATION` did not
     reach it.** That flag is the kill switch. Setting it to `false` on a
     deployment that records real filings left this button still simulating
     filings and still persisting references.

   `apps/web/scripts/one-filing-demo-and-the-kill-switch-reaches-it.test.ts`
   is what stops it coming back: inverted assertions whose subject is code that
   must never exist again, plus its own negative control.

## Where a CA reaches it

On the five module screens where the return actually lives — GST, TDS, MCA,
payroll and tax filing — each gated on `fetchFilingDemoCapabilities()`.

**Not from `/deadlines`.** A deadline row is a calendar obligation, not a saved
return, so there is nothing for a flow to walk through; the CA opens the client
and demos it where the figures are.

## The kill switch

`ENABLE_FILING_SIMULATION` defaults **on** — an owner decision of 2026-08-29,
because demo filing is a core product capability and this deployment records no
real filings.

**Set it to `false` on any deployment that records real filings.** It gates the
capabilities probe and every preview endpoint, so every screen stops offering
the control rather than offering one that errors.

## What makes it safe

- **It cannot file.** There is no portal client behind it. The safety argument
  is the absence of the capability, not a check that could be bypassed.
- **Honest references.** `SIM-NOT-FILED`, or a realistic-looking one that always
  renders with its SPECIMEN badge and note. `FilingDemoWizard` has no code path
  that omits them.
- **The banner never scrolls away.**
- **No dead controls.** A capability the server does not have is not offered;
  a probe that fails is treated as absent.

## When real filing is built

It is a **new endpoint**, and the simulation is **deleted** — never repointed at
a live portal. Everything that makes the demo safe is the fact that it cannot
file. See CLAUDE.md, "Filing to the government portals through the software".

## Leftovers

`demo_filings` (migration 087) has **no reader and no writer** since the browser
path was deleted, and **zero rows in production**. The table is left in place
rather than dropped: dropping it is a destructive production migration for no
functional gain, and nothing reads it, so it cannot mislead. If a deadline-level
demo is ever wanted, the storage is already there — but it would go through the
server like everything else.

## Tests

```bash
# the shared framework never files, and the flag really is a kill switch
cd apps/api && pytest tests/test_filing_simulation_never_files.py -v

# one implementation, and the kill switch reaches it
cd apps/web && node --experimental-strip-types \
  --test scripts/one-filing-demo-and-the-kill-switch-reaches-it.test.ts
```
