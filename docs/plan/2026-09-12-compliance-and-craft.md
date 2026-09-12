# The plan: compliance and craft

Written 12 September 2026, at the owner's request, after the decision to change
the platform's design.

**The goal, in the owner's words:** a platform the market has not seen — one that
wins on compliance *and* on how it looks, with nothing falling back.

**The correction that shapes everything below.** An earlier note here argued the
outputs matter more than the interface, because the CA's client never sees the
software. That is half right and the wrong half to act on. The CA sees it, and
the CA is the one who decides. Adoption happens in the first ten minutes on
screen; compliance is what keeps them after. So both are on the critical path,
and the interface comes first in *time* even though correctness comes first in
*importance*.

---

## Where the platform actually stands

| | state |
|---|---|
| **Statutory correctness** | strong. 13,255 backend tests, ~70 backlog items left and no criticals. Every rule that matters is guarded by a test that states the RULE rather than an instance |
| **The interface** | never addressed. A sidebar that cannot hold fourteen detailed modules |
| **PDF outputs** | six reportlab services in `apps/api/services/` — invoice, payslip, statement, year-end, bank reconciliation, engagement. Correct, plain, restylable in one place |
| **Excel outputs** | **generated in the BROWSER**, ~10 screens, with a library whose community build cannot style a cell at all. No fonts, no borders, no number formats, no column widths |
| **Foundations** | double-entry kernel, integer paise, tenant isolation, never-auto-submit — all sound, none of it touched by any of this |

That Excel finding is the one that changes a plan rather than a task list.
"Professionally formatted exports" is not a styling pass on what exists; it is
**moving export generation to the server**, which is also where CLAUDE.md says
it belongs.

---

## Five tracks

### Track 0 — Finish correctness *(in flight, ~1 week)*

~70 items, none critical. Do the ones that live in `apps/api`; **park every new
screen** until the design direction is settled, because a screen built now is a
screen thrown away.

Ends when the backlog holds only what is blocked on a registration, a state
notification, or a figure a human has to supply.

### Track 1 — The safety net *(2–3 days, BEFORE any redesign)*

This is the answer to *"if we mess with a module we will not know it."* It does
not exist today and the redesign is blocked on it.

1. **Reachability snapshot.** Freeze which screen reaches which endpoint. After
   every converted module, fail if any endpoint lost its way in. This catches
   the single most dangerous failure — a screen that quietly stops calling the
   engine behind it, which is the exact class the audit kept finding.
2. **Route inventory.** Every route that resolves today still resolves or
   redirects. No CA's bookmark dies.
3. **Playwright smoke walk.** One seeded client, all fourteen modules: does it
   render, does it fetch, does a real number appear, is the console clean.
   Chromium is already installed. **This is the piece that makes the redesign
   safe to attempt.**
4. **Visual baseline.** A screenshot of every module. Not a regression gate —
   these are *supposed* to change — but a review artifact, so every screen can
   be seen side by side before and after.

### Track 2 — The design system *(~1 week, then one reference module)*

Not the redesign. The vocabulary the redesign is written in.

- **Tokens**: colour, type scale, spacing, radius, elevation, density.
- **The things this product specifically repeats**, which a generic system does
  not give you: the money cell (tabular numerals, ₹ alignment, lakh/crore
  grouping), the Dr/Cr pair, the statutory-gap callout, the refusal banner, the
  period picker, and the "what this figure is made of" working panel that half
  the engines already return and no screen renders well.
- **Then ONE module converted end to end.** I would take **Banking Entries** —
  it is the densest screen in the product, and a system that survives it
  survives everything else.

**You review that one module before anything else moves.**

### Track 3 — The outputs *(~1.5–2 weeks, runs in PARALLEL with Track 2)*

Independent of navigation, so it does not wait. Highest commercial value.

- **3a. PDF restyle.** Six services, one shared style module. Typography, a
  masthead the firm's branding drives, proper tables, a signature block.
- **3b. Excel moves to the server.** Rebuild the ~10 browser exports as backend
  exports: real header rows, frozen panes, column widths, ₹ number formats with
  Indian grouping, totals, print areas, and a cover sheet carrying client,
  period and generated-on. **This is the "already professionally edited"
  deliverable** — the hour a CA currently spends reformatting, removed.
- **3c. One export vocabulary**, so every module's output looks like the same
  firm produced it.

### Track 4 — The navigation change *(~2–3 weeks, module by module)*

- The **hub on entry** — the full-screen module grid, each tile carrying live
  signal ("7 lines to pass", "GSTR-3B due in 4 days").
- **Plus a persistent switcher and a ⌘K palette.** This is my one argument with
  the original idea: a CA moves bank line → invoice → GST → TDS in ninety
  seconds, and routing every hop through the hub trades a cramped sidebar for a
  slow one. Hub to *enter*, switcher to *move*.
- One PR per module, smoke test green on each. If something breaks it is one
  module and one diff — never "back to square one".

---

## Where the CA test run goes

**Not at the end.** After Track 2's reference module and Track 3a's first PDF.

At that point a CA can see where the design is going and what the output will
look like, and their reaction shapes Tracks 3b and 4 *while they are being
built* rather than arriving after. Showing them the current design costs
nothing and buys the most valuable input available.

---

## What only the owner can decide

| when | question |
|---|---|
| after Track 2's reference module | does this look right? is the density right? |
| after the first restyled PDF | does this print right, on paper? |
| after the first server-side Excel | is this what you would have formatted by hand? |
| before Track 4 | what order do the modules go in — what does a CA reach for first? |

I can prove nothing broke. Only a CA can say it got better.

---

## Rough time

| track | working time | can overlap |
|---|---|---|
| 0 — correctness | ~1 week | — |
| 1 — safety net | 2–3 days | after 0 |
| 2 — design system + reference module | ~1 week | with 3 |
| 3 — outputs (PDF + Excel to the server) | ~1.5–2 weeks | with 2 and 4 |
| 4 — navigation, module by module | ~2–3 weeks | after 2 is approved |

Five to seven weeks of build time with the overlaps, and the owner's review
checkpoints are on the critical path.

## The one caution

Doing the redesign, the output overhaul and a correctness push at the same time
is how a good idea becomes six unfinished months. The order above exists so
that at every point the platform is shippable: correctness first because it is
what a CA cannot check, the safety net second because it is what makes the rest
reversible, and the visible work last because it is the part that can be judged
by looking.
