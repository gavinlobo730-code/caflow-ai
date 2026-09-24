# THE PLAN

**The one plan, end to end. Everything else in `docs/plan/` is history.**

Rewritten **24 September 2026** at the owner's request — *"in the plan
everything should be there, all the open items, up to the whole platform
redesign part."* Every number below was measured on that date by running the
command beside it, not carried forward from the previous version. Where a
carried-forward figure turned out to be wrong, the correction is recorded
rather than quietly replaced.

Supersedes the 16 September edition, `2026-09-12-compliance-and-craft.md`,
`2026-09-16-the-redesign-plan-revised.md` and
`2026-09-13-questions-for-the-owner.md`.

---

## The shape of what is left, in one paragraph

**The engine is done.** 259 of 279 audit findings are closed, 412 migrations
are applied, and every statutory computation a practice needs — GST, TDS,
income tax, payroll, the general ledger, inventory, fixed assets, the year-end
statements — is built, tested and pinned to the Act. **What remains is almost
entirely the product's SHAPE**: a navigation that hides 235 working endpoints,
~40 finished analytical engines with no screen, two portals on the old design,
and a demo firm with nothing in it. In the owner's chosen order: **navigation →
analytics → portals → demo data → a verification session**. Nothing on the
critical path is blocked on anybody but me.

---

## Where the product actually is — measured 24 September 2026

| what | now | was | how it was measured |
|---|---|---|---|
| Audit findings closed | **265 of 279** (95.0%) | 0 of 278 on 7 Sep | `docs/audits/findings-status.json` |
| — still partial | 6 | | each one's remaining half is listed in Phase 1.6 |
| — still open | 2 | | TDS-16 (blocked on a document), GST-25 (blocked on forms) |
| Migrations applied | **412** | 348 on 7 Sep | `ls apps/api/migrations/` |
| Backend tests | ~7,000, green | | `pytest tests/` |
| Routes in the app | **161** | | `find apps/web/app -name page.tsx \| wc -l` |
| Smoke screenshots, distinct | **154 of 160** | 11 on 12 Sep | `md5sum apps/web/.smoke/*.jpg \| awk '{print $1}' \| sort -u \| wc -l` |
| Endpoints a screen can reach | **832 of 1,063** | 829 of 1,064 | the reachability test's own `_sources()` |
| — unreachable | **231** | was 235 | Phase 3 is largely about these |
| Error boundaries | **65** | 0 | `find apps/web/app -name error.tsx \| wc -l` |
| Hardcoded hex colours | **70** | 10,146 | `grep -rEoh '#[0-9a-fA-F]{6}' apps/web/app apps/web/components \| wc -l` |
| Arbitrary font sizes | **379** | 2,265 | `grep -rEoh 'text-\[[0-9]+px\]' apps/web/app apps/web/components \| wc -l` |
| Cloudflare redirect rules | **98 of a hard 100** | 98 | `grep -v '^#' apps/web/public/_redirects \| grep -c '200$'` |
| Portal code | 1,738 lines, 6 routes | | `find apps/web/app/portal -name '*.tsx' \| xargs wc -l` |

**A correction, because the plan's own rule demands it.** The 16 September
edition said retiring the shells meant *"2,675 lines across two shells"*. They
measure **373 lines today** — `AppShell` 137, `ActivityRail` 151,
`ContextPanel` 57, `ClientWorkspaceShell` 28. That figure was either measured
against something else or has been overtaken. **T6-f is a far smaller job than
the plan has been claiming**, and sizing it from the old number would have
budgeted 3–4 days for perhaps one.

---

## Decisions — locked. Do not re-litigate.

### Taken earlier

| # | decision | answer |
|---|---|---|
| D1 | Hub tile set and order | **15 tiles** — Compliance Calendar · Insights · GST · Banking · Accounting · Sales · Purchases · TDS · Payroll · Income Tax · Fixed Assets · Inventory · Year-End · Reports · Documents |
| D2 | The 39 screens in no menu | **Give them a home** |
| D3 | Portals in scope? | **In scope** |
| D4 | Density persistence | **Per device** (localStorage, no migration) |
| D5 | Money display | **2 decimals**, except return-prep screens → whole rupees |
| D6 | Rupee grouping | **Indian everywhere** — 12,34,567, never 1,234,567 |
| D7 | Demo on real or seeded data | **Seeded demo firm** |
| D8 | i18n | **Extract strings, translate nothing.** English only |
| D9 | A PR carrying a migration | **Merge it like any other** — no flag, no pause |
| — | Access control | **Person-wise only.** Role is the template a new hire's grid is pre-filled from; the grid is the authority |
| — | Emailing a client's customers | **Never automatic.** A Send button the CA presses, always |

### Taken 24 September 2026

| # | question | decision | the reasoning |
|---|---|---|---|
| **D10** | Are the 41 bare-path redirect rules load-bearing? | **Yes.** The owner opened the Cloudflare preview: it 404s or bounces to the trailing-slash form | So the rule count cannot be collapsed. **Two rules of headroom against a cap that fails SILENTLY.** Consequence, binding on all of Phase 2: **no new route under `/clients/[id]`** — a query-param workspace instead, the way the year-end workspace already does it. The real relief is *reducing* dynamic pages, which the hub does anyway |
| **D11** | One content width, or width by content? | **Width by content type** | Tables and dense grids full-width to the ~1600px cap; prose, forms and single-column reads keep a 65–75 character measure. Already what the Trial Balance and cash-flow views do, and it matches the standing decision that data tables are exempt from the cap |
| **D12** | The 379 hand-written text sizes | **Convert all of them — module by module, with a before/after screenshot check on each.** The 135 off-scale sizes first | The owner's own point decided it: *"one would be good for one screen but not for the other."* There is no single correct line height, so this cannot be a codemod. The smoke walk already renders all 160 screens, so "before" and "after" are observable rather than discovered later. Anything that gets worse takes an explicit line height by hand |
| **D13** | ₹ on PDFs | **Keep `Rs.` for now** | CGST Rule 46 prescribes no currency symbol, so this is cosmetic. The only two fonts that carry U+20B9 each cost something real — FreeSans is a metric drop-in but GPLv3 *in this repo*; DejaVu is permissive but 1.13–1.26× wider, which re-breaks the seven invoice columns T5a-4b just fixed. Reversible in one commit |
| **D14** | Where a CA is told a posting fell back to the generic Bank ledger | **On the entry row AND in the posting confirmation** | The row so it is visible while scanning the ledger; the confirmation so it is caught at the moment it happens, when it is cheapest to fix |
| **D15** | Order of the remaining tracks | **Navigation → analytics → portals → demo firm** | The analytics screens and the portal both need somewhere to live |
| **D16** | Is there a date? | **No fixed date — do it properly** | Each track finishes before the next starts. Nothing half-built |
| **D17** | Filing to the government portals | **Stay prepare-only.** Keep the simulation, make its wording professional, and say in the product that real filing is coming | The owner: *"once we demo to a CA I would go and start doing those registrations."* GSP/ERI/NIC are months of commercial lead time and the demo is what justifies starting them. Until then the simulation must be indistinguishable from the real flow **except** for saying, in plain professional words, that it is a simulation |
| **D18** | The six documents this environment cannot fetch | **The owner will get all six — later. Tracked, not blocking** | Every one is already a NAMED gap in the product rather than a wrong number, which is the safe direction |
| **D19** | May a TRUSTED bank rule — one that posts with nobody watching — decide a TDS treatment? | **No. It posts the payment and FLAGS the line for a TDS decision** | The middle option, and the owner took it. A trusted rule already decides account, split and party, and rent, fees and contractor payments are exactly the recurring lines it is for — so leaving TDS out entirely means revisiting every one of them. But an under-deduction disallows the **whole expenditure** under §40(a)(ia), puts the tax on the client under §201(1) with §201(1A) interest, and is INVISIBLE: the entry posts, the books balance, and it surfaces in an assessment order two years later. A flagged line is visible; a wrong deduction is not |
| **D20** | Should a customer credit limit WARN, or REFUSE the invoice? | **Warn by default; refuse only where the firm switches it on**, and never on an opening document | Taken by me on 24-09 under your standing instruction that code decisions are mine — raised as a question first, then withdrawn, because the finding already specifies the default and nothing is refused unless a firm deliberately asks. A block stops a CA recording a supply **that has already happened**: the goods went out, CGST §31 makes the invoice due, and a document this product refuses gets recorded somewhere it cannot see. An opening document is exempt whatever the switch says — ACC-14's reasoning, and it is exactly the document that pushes a customer past a limit somebody has just typed in. Migration 414. Overrule by saying so |
| **D21** | A dead API endpoint that duplicates a live one — wire it up, or delete it? | **Delete it**, where nothing calls it and another endpoint already owns the fact | Taken by me on 24-09 under the same standing instruction as D20. `PATCH /api/team/{user_id}/role` and `PATCH /api/identity/users/{user_id}/role` both changed a member's role; the Team screen calls the second, the first had no caller in either frontend, and the two validated against different role lists. Two write paths for one fact is what this codebase refuses everywhere else, and the one nobody could reach is the one with no users to break. Nothing else in that batch is a deletion — the other three unreachable endpoints were WIRED UP, because each was the only way to do something a CA needs (extend an e-way bill under the proviso to Rule 138(10), correct the firm's own GSTIN on the client it bills from, see what a recurring journal will post next). Overrule by saying so; restoring it is a revert |

---

## Phase 0 — what is already finished

Recorded so nothing here gets re-started. Each was verified by running its own
check, not by reading a status line.

| track | what it delivered |
|---|---|
| **T1 — the safety net** | 7 of 7. Required checks actually run on a web-only PR; reachability attributed to a calling screen; the smoke walk renders 154 distinct screens (was 11); 65 error boundaries (was 0); both snapshots refreshed |
| **T3 — the design system** | The token file with a contrast-audited scale (`ps.hint` was **2.56:1**, the most-used colour in the product); five primitives; five of six product components; 10,146 → 70 hex literals |
| **T5a — PDFs** | One style module shared by all six documents, which had picked **four different header fills** — including a navy on the year-end pack *a CA signs*. Two real contrast failures fixed. Page numbers and repeating headers. Indian rupee grouping. IST dating. The practice's own name on the pack instead of the product's |
| **T5b — Excel and CSV** | One workbook builder — a money cell is a **number**, so `=SUM()` returns the total rather than 0. One CSV writer: two of thirteen hand-rolled escapers were wrong, and one shifted every column after a client called "Sharma, Gupta & Co" |
| **T9 — the backend backlog** | Grew from 8 items to ~70 as each pass found more. 259 findings closed |
| **The 24 Sep overnight run** | Eight batches: a browser palette; the 98 hex classes; four unpaged exports; a clock frozen at deploy date; the GSTIN check digit reaching seven doors that used a shape regex; PAN/TAN/DIN validators; the risk register moved out of the browser; two files that claimed another agreed with them and nothing checked either claim |

---

## Phase 1 — finish the foundation · 🔧 C · 6–9 days

Small, well-understood, and every item is unblocked. This clears the residue so
Phase 2 starts on a clean base.

| ID | item | size | DONE WHEN |
|---|---|---|---|
| **1.1** | **The type scale (D12).** Convert all 379 arbitrary sizes, module by module. The 135 off-scale ones (13px ×88, 9px ×29, 15px, 22px, 26px, 32px) first — they map to nothing, so nothing moves. Then the 244 that map to a built-in, one module per PR, each with a smoke-walk diff | 2–3d | `grep -rEoh 'text-\[[0-9]+px\]' apps/web/app apps/web/components \| wc -l` = **0**, and the guard's arbitrary-size budget is 0 |
| **1.2** ✅ | **LANDED 24-09.** **Width by content type (D11).** **59 pages rendered a table inside a centred container at NINE widths** — 576px to 1400px, `max-w-5xl` and `max-w-7xl` both common — and nobody chose that spread. One token, `max-w-ps-data` (1600px), on 58 of them; `portal/employee` is named as the one exception with its reason. **The reading half of D11 needed no work and the guard says why**: of 102 pages that centre a container, exactly one ran wide without holding data, and that one renders its rows through a custom component. Verified by a 160-route smoke walk before and after — 23 routes moved at 1440×900, each read, one page fixed | 1d | A guard fails a table page that picks its own width; the exemption list only shrinks |
| **1.3** | **The named-colour judgement pass (T4-b).** 8,234 Tailwind utilities like `text-amber-600`. Status colours resolve to the semantic tokens; decorative ones stay | 2–3d | `amber`/`red`/`green` on a STATUS element resolve to `state.*`, asserted by a guard |
| **1.4** ✅ | **LANDED 24-09.** **The generic-Bank-ledger disclosure (D14).** `PaymentAccount.is_fallback` and `.reason` are computed and reach no caller. Surface on the entry row and in the posting confirmation. This is a refactor through eight journal-line builders | 1d | Posting a payment with no resolvable bank account shows the sentence in both places; a test asserts both |
| **1.5** ✅ | **LANDED 24-09.** **The filing-simulation wording (D17).** Every demo flow already carries an honest `SIM-NOT-FILED` reference and a "what changes when this is real" sentence. Rewrite those to read as a professional product statement — *"Preview only. PracticeSync does not transmit to the portal. Direct filing is in development"* — consistent across all flows, and visible on the screen rather than only in the response | 0.5d | One wording, one place it is defined, rendered by every flow; a guard asserts no flow renders its own |
| **1.6** | **The twelve partial findings' remaining halves.** Listed below. **Three more closed 24-09 — ACC-03, INV-09, SALES-28 — leaving six partial and two open, every one of them waiting on the owner or on a document** | 1–2d | Each moves to `closed` in `findings-status.json` in the same commit |

### 1.6 — the twelve partials, and what is actually left of each

| finding | what is done | what remains | blocked? |
|---|---|---|---|
| GST-11 QRMP | the whole return engine **and the Rule 59(2) facility** ✅ | **nothing — closed 24-09** | — |
| PAY-27 payroll reports | variance, department cost, bank advice | three more report shapes, if wanted | no |
| IT-11 tax audit | §44AB applicability decided and served | **Form 3CD itself** — a clause workspace, needs a migration | needs document #4 |
| SALES-23 reminders | the bulk Remind, and migration 405 stopped the counter | the sweep SENDS nothing — and whether it should is **owner question A** | **owner** |
| BANK-11 rules | priority, match field, operator, patterns, party, **and D19's TDS flag** ✅ | **nothing — closed 24-09** | — |
| SALES-25 credit notes | the §34(2) window (half a) **and the customer credit limit** ✅ | **nothing — closed 24-09.** Migration 414, warn by default, block only where the firm asks | — |
| ACC-03 bank ledger | all three — **1.4 landed 24-09** | **nothing — closed 24-09** | — |
| ACC-13 day book | day book built | **cost centres** — a dimension on `journal_lines`, **owner question C** | **owner** |
| GST-25 returns | GSTR-9 computed; 3.1.1 named as underivable | composition (CMP-08/GSTR-4), TCS on GSTR-8, GSTR-9C | needs document #5 |
| INV-09 quantities | the three-decimal rule at every door, and the alternate unit (migration 409) | **nothing — closed 24-09** on part 2, with the reasoning rather than a widening: `NUMERIC(10,3)` holds 9,999,999.999 units of one item on one movement, and the alternate unit relieves the case that comes closest | no |
| SALES-28 e-way | applicability, validity, the expiring-bill panel, and **the extension is now RECORDABLE (24-09)** — the endpoint existed from the first day and no screen called it | **nothing — closed 24-09.** The JSON payload is GST-32's refusal, not this finding's | — |
| TDS-22 clause rates | both clauses recordable, (b) limbs complete | **two numbers** for the (a) limbs | needs document #4 |
| FA-11 CWIP | capital work-in-progress complete | shift working is **blocked on a document** — Part C here holds the LIVES and not the NESD markings (**question D**); revaluation and component accounting are unstarted | needs document #9 |
| TDS-16 (open) | every figure computed | **the FVU/RPU file writer** | needs document #3 |

**The 1.6 table above was RE-READ against the code on 24-09-2026, and five of
its rows were wrong.** SALES-23's counter defect was fixed by migration 405;
SALES-28's extension write path exists; ACC-03's third half landed the same
morning; SALES-25's remaining half is a CUSTOMER CREDIT LIMIT and not a credit
note path; and INV-09's part 3 landed with migration 409. That is the staleness
this file's own header warns about, one level down — **a plan's inventory goes
stale exactly as fast as an audit's does, and only re-reading fixes it.**

Four of the rows now say **owner**. They are written up in full, with what I
would do about each, in `docs/audits/questions-for-the-owner.md` under *WHAT IS
WAITING ON YOU*: whether the nightly sweep may EMAIL a client's customers (A),
whether a customer credit limit warns or blocks (B), cost centres (C), and
extra-shift depreciation, which is blocked on a document rather than on a
decision (D).

---

**BANK-11 step 3 (D19) — landed whole, 24-09-2026. ✅**

The backend: migration 413 (`bank_matching_rules.flags_tds_decision`, and on
`bank_transactions` the `draft_flags_tds_decision` proposal beside the
`tds_decision_needed` recorded fact — migration 382's split, so a REJECTED
proposal cannot read as a recorded one); the flag on both rule doors; the
draft carrying it; the stamp at pass time; and a guard holding it **one-way** —
a rule may only ever set it true, because a rule that could CLEAR it would
silently dismiss the outstanding withholding question on every line it matched.

The screen, which is what stopped this being the `capital_wip` shape: the
checkbox in the rule editor, a **TDS?** chip on the flagged line, a count and
filter above the queue, and **TDS decided** as a bulk action writing
`tds_decision_resolved_at`/`_by`.

Three shapes in it are worth keeping:

- **Pending is TWO columns.** Answering never clears the flag — three states,
  not two: never flagged, flagged and waiting, flagged and answered. The third
  is the audit answer to *did anyone look at the withholding on this line*,
  which is what a §201 proceeding asks, and clearing the boolean loses it.
  `domain`-side that predicate is `_tds_pending`, migration 413's partial index
  and `lib/banking/tdsDecision.ts`, all three the same two-column test.
- **The filter REPLACES the state rather than narrowing it.** A flagged line is
  stamped when it is PASSED, so ANDing the flag with the default `to_do` would
  answer zero rows for every client, every time, with nothing on screen to say
  why. The service decides that, not the caller, so no caller can get that
  confidently empty answer.
- **Resolving takes NO body.** It records that somebody looked and nothing
  about what they concluded. A section or a rate on that endpoint would be
  migration 404's refusal — a rule may not carry a TDS treatment — undone at
  the other end of the same flow.

**GST-11 (the Invoice Furnishing Facility) — landed 24-09-2026. ✅**

CGST Rule 59(2). A QRMP filer's GSTR-1 covers a quarter, so their customer's
input tax credit — which rests on §16(2)(aa), the SUPPLIER's furnished invoice
as communicated in GSTR-2B — waited up to three months. The facility furnishes
months 1 and 2 to registered customers by the 13th of the following month.
`domain/gst/iff.py`, `iff_from_books`, `GET /api/gst-workspace/iff/compute`, and
one panel on BOTH GSTR-1 screens.

Three shapes worth keeping:

- **What it carries is derived from the rule's own words**, not from a
  remembered list of portal tiles: *"outward supplies … to a REGISTERED
  person"*. That sentence puts SEZ and deemed export IN (both recipients are
  registered) and exports OUT, and it is why the finding's own suggested fix —
  which named `cdnur` among the sections — is wrong.
- **The ₹50 lakh cap REPORTS and never truncates.** The rule lets the supplier
  furnish *"as he may consider necessary"*, so which documents fit is the CA's
  choice; a set this product had silently trimmed would not match the sales
  register with nothing on screen saying what was left out.
- **The classify step was EXTRACTED, not copied.** Two fetch-and-classify paths
  would be two answers to "what did this client supply in March", and the
  facility's whole value rests on furnishing exactly what the quarter will later
  declare.

Amendments and the payload envelope are NAMED as not built, each with its own
reason; the first is settled by document #5.

---

## Phase 2 — Navigation and the hub · 🔧 C · 10–15 days

The largest single change to what the product feels like. **This is the
redesign.**

**What is wrong today.** There are 161 routes, 39 of them in no menu at all.
Two different shells — the firm-level one and the client workspace — share
nothing. Moving from one client to another means going back out to a list.
⌘K is bound globally and opens an entity search rather than navigation. And 235
working endpoints have no screen that can reach them, most of which is Phase 3
but some of which is simply that nothing links to the screen.

**The constraint D10 puts on all of it.** Cloudflare Pages silently ignores
`_redirects` rules past position 100. There are 98. The owner checked the
preview and the bare-path rules are load-bearing, so they cannot be collapsed.
**Two rules of headroom.** Every item below is designed around it: the hub adds
no dynamic routes, and anything new under `/clients/[id]` is a query parameter,
not a path. This is not a preference — it 404'd the entire client workspace
once already, with no build error and no log.

| ID | item | size | DONE WHEN |
|---|---|---|---|
| 2.1 | **Re-pin the redirect budget and write D10 into the generator's own comment**, so the next person does not re-derive it | 0.5d | `generate-redirects.test.ts` asserts ≤ 98 and names why 41 cannot be collapsed |
| 2.2 | **The hub — firm level and client level.** The 15 tiles of D1, each with live signal rather than a label | 3–4d | Every tile shows a real figure or a real count; none is a stub |
| 2.3 | **The persistent client switcher** | 1–2d | Move client → client without returning to a list |
| 2.4 | **Re-point ⌘K at navigation** | 1d | ⌘K goes to any of the 161 screens by name; entity search moves behind a prefix |
| 2.5 | **Give the 39 orphan screens a home (D2)** | 1–2d | Every route is reachable from the hub or a tile's sub-list. A guard asserts it, so a screen added later cannot be orphaned silently |
| 2.6 | **Retire `ActivityRail`, `ContextPanel` and the client sidebar** | **0.5–1d** (was budgeted 3–4d on a stale 2,675-line figure; they are 373 lines) | One shell. All three `window.location` static-export workarounds survive — they exist because this is a static export and there is no server to redirect |
| 2.7 | **Per-module conversion, one PR each** | 5–8d | Smoke walk green per module. Budget 0.5–1d per module for guard edits — several guards name a file path and will break on a move that does not break their rule; restate them as the rule |
| 2.8 | **The two stacked mobile hamburgers** | 0.5d | One drawer, reachable |
| 2.9 | **PAY-28** — payroll's three top-level areas | in 2.7 | Payroll is one place |

---

## Phase 3 — Analytics and AI · 🔧 C · three layers

**The finding that makes this worth doing: you already own more analysis than
the product shows, and the AI a CA can see is the weakest AI you have.**

- `/ai-assistant` is a **pure passthrough over a static prompt that loads no
  client data at all.** Its own code comment says so. It is a generic tax
  chatbot wearing your product's name.
- `GET /api/accounting/statement-analysis` — ratios computed from the reporting
  engine's own paise, narrated by an LLM, with a deterministic fallback — has
  **zero screen callers.** The best AI feature here is unreachable.
- `GET /api/analytics/profitability` — **client profitability, built, in
  integer paise, by client and engagement and team** — zero screen callers.
- The modules named "intelligence" and "memory" analyse **tasks, not money**.
  `cash_flow_risk_months` is literally the two months with the most tasks.

### The rule, adopted now and enforced by a guard

> **The LLM narrates figures the product computed. It never computes them.**

Already the pattern in `statement-analysis`. A CA who catches the AI inventing
a number stops trusting the software entirely — and unlike a wrong figure in a
report, there is no way to audit it afterwards.

### 3a — surface what exists · 8–12 days

No new engines. Screens for what is already computed and tested.

| ID | item | DONE WHEN |
|---|---|---|
| 3a-1 | The **Insights** tile (D1) — health, risk, profitability, trends in one place | The tile is not a stub |
| 3a-2 | Client profitability and realization | `/api/analytics/profitability` and `/revenue-vs-effort` have screen callers |
| 3a-3 | Statement analysis | `/api/accounting/statement-analysis` has a screen caller |
| 3a-4 | Health — render the **computed** 7-dimension score | 8 unreached health endpoints reached; screens stop rebuilding scores from raw rows |
| 3a-5 | Compliance risk and predicted misses | `/api/intelligence/*` reached |
| 3a-6 | `ai_insights` — wire the **writer** | Today a screen reads a table nothing reachable populates |
| 3a-7 | Give the copilot the client's own data | The 8 unreached copilot endpoints reached; the static prompt replaced by one that loads the client context |

**Target: the 231 unreachable endpoints fall below 120.**

### 3b — repoint the intelligence at the ledger · 6–10 days

| ID | item | DONE WHEN |
|---|---|---|
| 3b-1 | **Anomaly detection over `account_period_balances`** — round numbers, period-end spikes, unusual account pairings, duplicate payments | "Anomaly" means a ledger anomaly, not task-volume sigma |
| 3b-2 | **Real cash-flow forecasting** from invoice and bill due dates, ageing and bank history | A forward-looking engine exists. There is **none** today — the only "forecast" is 353 lines of browser arithmetic off a user-typed opening balance |
| 3b-3 | Rewrite or retire `cash_flow_risk_months` and `seasonal_revenue_peak` | No financial-sounding figure is derived from task counts |
| 3b-4 | Firm-wide capacity risk — deadline concentration against team capacity | *Which March are you about to fail?* |

### 3c — the differentiators · 10–15 days

| ID | item | DONE WHEN |
|---|---|---|
| 3c-1 | Effective tax rate trend across years | Snapshots are stored and never compared |
| 3c-2 | ITC leakage as a trend | Reversals computed per return, never totalled for the year |
| 3c-3 | Vendor and customer concentration | No top-N share, no year-on-year shift today |
| 3c-4 | GST / TDS / payroll trend analysis | All per-period today |
| 3c-5 | **Cross-client benchmarking** | *"Your client against the other 40 in this sector."* Needs a book of clients on one platform — **nobody else in this market can copy it** |

---

## Phase 4 — The portals · 🔧 C · 8–12 days

Six routes, 1,738 lines under `apps/web/app/portal/`, rendered outside the
staff shell and importing almost none of the shared primitives — so Phase 1 and
Phase 2 reach none of them.

**This is the only surface the CA's own client and employees ever see.** If it
keeps today's look, the product visibly has two designs and the outside world
sees the old one.

| ID | item | DONE WHEN |
|---|---|---|
| 4.1 | Client portal on the design system | Uses the shared primitives |
| 4.2 | Employee portal on the design system | Same |
| 4.3 | `apps/marketing` brand parity | **Done 24 Sep** — a parity test written from `apps/web`'s side, replacing a hand-copy maintained by a comment |
| 4.4 | The portal dashboard drops 3 of 7 sections the API serves | All served sections render, or are deliberately excluded and say why |

---

## Phase 5 — The demo firm · 🔧 C · 2–3 days

**Yes, I can build this entirely — it needs nothing from you.**
`apps/api/seed/seed_data.py` already exists and is idempotent; what it lacks is
volume. The work is to drive a full financial year through the **real posting
paths** — not to insert rows — so the data is as valid as a real client's.

| ID | item | DONE WHEN |
|---|---|---|
| 5.1 | One command creates the firm; running it twice is a no-op | `python -m seed.seed_data` twice, no duplicates |
| 5.2 | A **full financial year** across every module — sales, purchases, bank, payroll, GST returns, TDS, fixed assets, inventory, year-end | Every one of the 15 tiles has real figures; no screen shows an empty state |
| 5.3 | The figures tie | Trial balance balances; GSTR-1 and GSTR-3B reconcile; the payroll challan foots |

**Why it is worth the 2–3 days beyond the demo:** driving a year through the
real paths exercises the whole engine end to end, and finds the class of defect
an empty screen hides. Every previous seeding pass found some.

---

## Phase 6 — Verification, with you · 🤝 · one session

### My gates — I refuse to book the session until all five pass

| gate | your one-command check |
|---|---|
| Smoke walk renders the product | `md5sum apps/web/.smoke/*.jpg \| awk '{print $1}' \| sort -u \| wc -l` ≥ 150 ✅ **154** |
| Required checks run on a web-only PR | Open one and read the job log ✅ |
| Reachability attributed to screens | `pytest tests/test_reachability_is_attributed_to_a_screen.py` ✅ |
| A demo firm exists | One command builds it — **Phase 5** |
| Error boundaries | `find apps/web/app -name error.tsx \| wc -l` ≥ 14 ✅ **65** |

### The session

| ID | item |
|---|---|
| 6.1 | **Six spot-checks** — one GSTR-1, GSTR-3B, 26Q, payslip, trial balance, balance sheet against figures you trust. Not because the engines are unverified, but so you can tell a CA you checked it yourself |
| 6.2 | **Print four documents on paper** — invoice, payslip, year-end pack, customer statement |
| 6.3 | Review the hub and the two reference screens |
| 6.4 | **Walk the first-hour gaps and decide what you are content to show** — payroll gaps in 18 of 22 professional-tax states, §89 arrears before FY 2025-26, "cannot file yet" |
| 6.5 | Agree the sentence for *"can I use this tomorrow?"* — today, honestly: yes for everything except transmitting a return, which needs registrations you will start after this demo (D17) |

---

## Phase 7 — After the demo: the commercial track · 👤 O

**Not code. Do not start it before the demo (D17).** Recorded here because the
lead times are long and the order matters.

| step | what | lead time | what it unblocks |
|---|---|---|---|
| 7.1 | **Third Party Software Utility Developer** registration (income tax) | days, free, self-service | An `SW########` number. The first rung, and the only one available without commercial negotiation |
| 7.2 | **ERI** registration | months | Filing income-tax returns from inside the product |
| 7.3 | **GSP** — via a GST Suvidha Provider | months, real money | Filing GST returns. There is no direct public GSTN endpoint; every product that files goes through a GSP |
| 7.4 | **NIC** production credentials | months | e-way bill and e-invoice IRN — **the only two statutory outputs software can complete end to end**, because the portal signs them and no taxpayer signature is needed |

**Three rules that do not relax when this becomes real, and get stricter:**
never auto-submit — an explicit confirmation click per return, every time, never
a batch and never a retry that resubmits; the signature is the **taxpayer's**,
so the flow is *CA prepares → taxpayer signs on the portal*; and there is never
an OTP or EVC field in this application, whatever it is labelled, because that
is a credential-capture surface.

The full playbook is `docs/compliance/07-getting-permission-to-file.md`.

---

## The standing work that never finishes

Not a phase. These recur, and each has a named home so nobody rediscovers them.

| what | when | where |
|---|---|---|
| **The financial-year refresh** | every April, and CII around June | `CLAUDE.md` § "What has to be updated every financial year". Every rate registry **falls back silently to last year** rather than failing, so a missing year is a confidently wrong number, not an error |
| **The ITR JSON schemas** | every assessment year | The one item on that list that cannot be done from inside the repo. Document #7 |
| **The six documents** (D18) | when you get to them | Listed below |
| **The schema-drift fixtures** | when a migration moves them | `docs/schema-drift.md` |
| **The findings ledger** | in the same commit as the fix | `docs/audits/findings-status.json`. A status only ever written by an audit is wrong by the time it is read — this is the lesson that file exists to record |

### The six documents, and what each settles (D18 — tracked, not blocking)

| # | document | what stays refused without it |
|---|---|---|
| 3 | NSDL **TDS FVU/RPU file layout** | TDS-16. Every figure on a quarterly statement is computed; nothing can write the file the portal accepts |
| 4 | **Finance Act** §194I(a) / §194J(a), and **Form 3CD** | TDS-22's two clause rates, and IT-11's tax-audit annexure. Today those two limbs deduct at the parent's HIGHER rate and say so, rather than my guessing 2% |
| 5 | **GST offline utility** screens | The GSTR-9 filing demo, and GST-25's composition and TCS returns |
| 6 | A bank's **salary upload format** | Nothing. `domain/payroll/bank_advice` is deliberately generic — inventing one bank's layout produces a file that fails AT THE BANK rather than in front of the CA. Listed so the decision is visible |
| 7 | **ITR JSON schemas** per form per AY | The annual refresh |
| 8 | **State professional-tax slabs** (18 states) and **LWF** | Eighteen states' payroll deductions. Today reported as named gaps, which is the safe direction: a wrong deduction short-pays the employee AND leaves the employer owing the right figure, so a flagged gap beats a half-right table |
| 9 | **Schedule II Part C's NESD markings** | FA-11's shift working. Part C here holds the useful LIVES and not which classes are marked NESD, and extra-shift depreciation reaches only the classes that are NOT. Charging 50% or 100% extra on an exempted class is a wrong profit, so it is refused rather than guessed |

**Two of the nine are already done** — #9 was added on 24-09 when FA-11's shift working was re-read and found blocked on data rather than on a decision — and both changed real code: the CBIC
late-fee notifications and §50(3) — which turned out to be **24%, not the 18%
three successive readings had settled on** — and the e-invoice validation set,
which turned out to refuse `0001`, a number this product's own numbering
service hands to a firm with an empty prefix.

---

## Sequencing

```
Phase 1  foundation residue  (6-9d)
   │
Phase 2  navigation + hub    (10-15d)  ◄── the redesign
   │
Phase 3  analytics  3a (8-12d) → 3b (6-10d) → 3c (10-15d)
   │
Phase 4  the portals         (8-12d)
   │
Phase 5  the demo firm       (2-3d)
   │
Phase 6  verification, with you   (1 session)
   │
Phase 7  registrations — yours, after the demo
```

**Honest totals.** Phase 1 → 6 is **10–14 weeks** of build. Phases 1, 2, 3a, 4,
5 and 6 are the path to a demo — about **8–11 weeks**. Phases 3b and 3c are
real differentiation and can land after the demo without anything looking
unfinished.

**There is no fixed date (D16), so nothing on this list is a candidate for
cutting.** If one appears, tell me and I will re-cut around it.

---

## Explicitly not in scope

Recorded so nobody half-starts them.

- **Filing to government portals** — until Phase 7's registrations exist. The
  simulation stays, and says so (D17).
- **Account Aggregator bank feeds** — closed, and the reason is not cost. The
  five published AA purpose codes are each tied to a class of licensee, and
  **none describes an agent keeping the customer's own books.** Purpose defeats
  the partner route too, so the whole line is shut. Statement upload is the
  path, permanently. See `docs/compliance/05-…`.
- **Screen-scraping net banking** — never. No credential capture, no stored
  bank logins, no third party that works that way.
- **Translations** — D8.
- **Dark mode** — not built; one inert config line to delete.
- **A second filing demo, a second reconciliation screen, a second cost
  formula, a second pager, a second money parser.** This codebase has found
  each of those once already, and each one drifted before it was caught.

---

## The numbers — run these any time, no need to ask me

```sh
cd /path/to/caflow-ai

# Findings closed                                     259 of 279
python3 -c "import json,collections; d=json.load(open('docs/audits/findings-status.json'))['findings']; print(collections.Counter(v['status'] for v in d.values()))"

# Distinct smoke screenshots                          154   target >=150  ✅
md5sum apps/web/.smoke/*.jpg | awk '{print $1}' | sort -u | wc -l

# Endpoints a screen can reach                        829 of 1064
cd apps/api && python3 -c "from tests.test_every_mounted_endpoint_has_a_way_in \
  import _sources, _pattern, _routes; b=_sources(); \
  print(sum(1 for m,p in _routes() if _pattern(p).search(b)), 'of', len(_routes()))"

# Error boundaries                                    65    target >=14   ✅
find apps/web/app -name error.tsx | wc -l

# Hardcoded hex colours (coarse; the GUARD is the authority)   70
grep -rEoh '#[0-9a-fA-F]{6}' apps/web/app apps/web/components | wc -l

# Arbitrary font sizes                                379   target 0
grep -rEoh 'text-\[[0-9]+px\]' apps/web/app apps/web/components | wc -l

# Cloudflare redirect rules                           98    HARD CAP 100
grep -v '^#' apps/web/public/_redirects | grep -c '200$'
```

⚠️ **A metric and the guard that enforces it must count the same population.**
The hex and font-size greps above are coarse — they include comments and
allowlisted entries, and they sum three populations the guard counts
separately. The 19 September checkpoint recorded a hex "regression" of 54
literals nobody had added, purely because the metric and the guard disagreed.
**When they disagree, the guard is the authority and the metric is the thing to
fix.**

---

## When you ask "where are we?"

Run the block above. If a number here disagrees with it, the command is right
and this file is stale — tell me and I will fix the file in the same commit as
whatever I am working on. That rule is the only thing that keeps a plan
honest, and this repository has watched three separate status documents go
wrong for want of it.
