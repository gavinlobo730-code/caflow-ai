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

### What each flow teaches beyond the ceremony

The walk-throughs exist so a CA recognises the sequence, so the steps that are
easy to skip are IN them:

| Flow | The step the walk-through exists to put in front of a CA |
|---|---|
| `gstr1` | The sequence lock both ways — Rule 59(6) and §39(10) — and that **GSTR-1A**, not the later-period amendment tables, is the only correction that still reaches this period's GSTR-3B now that its outward tables are locked. |
| `gstr3b` | **IMS**, between Table 3.1 and Table 4, because that is where Table 4(A) comes from: Accept / Reject / Pending, no action **deemed accepted**, draft GSTR-2B cut on the 14th but the operative deadline being the filing of the return — with a **recompute** in between. Then Table 6.1, the set-off, which is the screen the CA actually decides on. |
| `gstr9` | That the annual return is **up to two forms** — GSTR-9C above ₹5 crore, self-certified, filed with it, and the §47(2) late fee attaching to the complete package — and that filing early **shuts the correction window** early. |
| `itr` | **Why no return file comes out.** The Department's schemas are held and every field path verified; what is missing is the `SW########` provider id and the non-computed half of a return. Read out of `domain/income_tax/itr_json.py`, not restated. |
| `tds` | That a TDS statement is **not filed on TRACES** — CSI, FVU, `.fvu` upload under the deductor's TAN — and, from FY 2026-27, that the form is **138 / 140** under the Income-tax Act 2025 while the stored key stays 24Q / 26Q. |
| `pf` | The ECR is a **file**, with four validations that reject it whole, filed in **wage-month order** since the 2025 revamp — one skipped month blocks every month after it, and a nil month still needs a nil return. |
| `esi` | Coverage runs on **contribution periods**, and an employee who crosses ₹21,000 mid-period stays covered to the end of it. |
| `mca` | The **dual signature** — a director's DIN-linked DSC, then the practising professional's own — and that an SRN in Pending Payment is **not a filed form**. |

Every flow also carries a **"what changes when this is real"** note: the
registration that gates real transmission (a GSP, an ERI's `SW########`, an
EPFO establishment login, MCA21 credentials) and what the CA will do
differently the day it arrives. `common.envelope()` will not build without one,
so no walk-through can show a capability and stay silent about its gate. Three
of the eight say honestly that **no registration is waiting** — TDS, PF and ESI
have no API to be granted access to.

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

On the five module screens where the return actually lives — each gated on
`fetchFilingDemoCapabilities()`:

| Screen | Flows |
|---|---|
| `app/clients/[id]/compliance/gst/page.tsx` | `gstr1`, `gstr3b`, `gstr9` |
| `app/clients/[id]/compliance/mca/page.tsx` | `mca` |
| `app/clients/[id]/payroll/page.tsx` | `pf`, `esi` |
| `app/clients/[id]/tax/filing/page.tsx` | `itr` |
| `app/tds/returns/page.tsx` | `tds` |

**Not from `/deadlines`.** A deadline row is a calendar obligation, not a saved
return, so there is nothing for a flow to walk through; the CA opens the client
and demos it where the figures are.

**Five screens hold the same returns and do NOT offer it yet** — a gap, not a
rule, and each is a small wiring change (probe capabilities, pass the record
id) rather than anything new:

| Screen | Flow it should offer | The id it already has |
|---|---|---|
| `app/gst/gstr1/page.tsx` | `gstr1` | `getGSTR1Return(clientId, period).id` |
| `app/gst/gstr3b/page.tsx` | `gstr3b` | `getGSTR3BReturn(clientId, period).id` |
| `app/clients/[id]/compliance/tds/page.tsx` | `tds` | the `tds_returns` row's `id` |
| `app/mca/page.tsx` | `mca` | the `mca_filings` row's `id` |
| `app/payroll/page.tsx` | `pf`, `esi` | `run.id` |

The two `app/gst/*` workspaces are arguably the PRIMARY screens for those
returns — compute, CA Approve, Download JSON, Mark as Filed all live there —
so the demo being absent from them is the largest of the five gaps. Whichever
is wired, the rule holds: probe `fetchFilingDemoCapabilities()` first, gate the
control on the flow appearing in `flows`, and gate it on the same status the
flow does (`ca_approved` for the GST and TDS returns, `finalized`/`paid` for a
payroll run).

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
- **The transmit stage says nothing is being sent, inside its own frame.** It is
  the stage that most resembles a real upload — ticks appearing one by one — and
  the one most likely to be screenshotted mid-play.
- **The success panel disowns its own heading.** `✓ Filing successful` is what
  makes the walk-through recognisable and it is the most dangerous string in the
  product, so it keeps its DEMO badge and now cannot render without the line
  under it: *that is what the portal would say; this is PracticeSync, nothing was
  sent.* The component renders it, so no flow can leave it out.
- **A credential is SHOWN and never TAKEN.** The OTP stage stays — the step is
  real, and it is how nearly every Indian return is signed — but it has **no
  input**, and the component holds no OTP state. CLAUDE.md: an EVC OTP field in
  this app is a credential-capture surface whatever it is labelled, and a demo
  that trains the habit is how the habit arrives. It is also the more faithful
  rendering: the code is typed on gst.gov.in or incometax.gov.in, never in the
  software that prepared the return, so a field here taught the step in the
  wrong PLACE. This is the ONE point where the walk-through is deliberately less
  imitative than the portal.
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

# the framework's five rules, and every flow's own statutory specifics
cd apps/api && pytest tests/test_filing_demo_framework.py tests/test_filing_demo_*.py -v

# one implementation, the kill switch reaches it, and the wizard takes no
# credential
cd apps/web && node --experimental-strip-types \
  --test scripts/one-filing-demo-and-the-kill-switch-reaches-it.test.ts
```

`tests/test_filing_demo_framework.py` holds five rules for every flow at once,
including the ones written later. Three are shapes — writes nothing, honest
envelope, labelled realism — and two are refusals, which are the ones that
erode when a walk-through is made to look more like the real thing: a
credential is shown and never taken, and every flow says what changes when it
is real (`envelope()` will not build without it).

**The write scan walks every `*.py` in `services/filing_demo/`, deliberately.**
If an unrelated module is dropped into that directory it will fail the scan —
which is the scan working, not a false positive. Put it somewhere else.
