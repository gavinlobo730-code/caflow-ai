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
| Arbitrary font sizes | **0** | 2,265 | `grep -rEoh 'text-\[[0-9]+(\.[0-9]+)?px\]' apps/web/app apps/web/components apps/web/lib \| wc -l` — **the guard's budget is 0, which is a ban** |
| Named-colour utilities | **4,373** | 5,541 and 5,840 earlier on 24 Sep; 5,993 before that | `for c in amber red green emerald blue gray slate rose yellow orange teal; do grep -rEoh "\b(text\|bg\|border\|ring\|fill\|stroke\|divide\|from\|to\|via)-$c-[0-9]{2,3}\b" apps/web/{app,components,lib}; done \| wc -l` |
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
| **D10** | Are the 41 bare-path redirect rules load-bearing? | **Yes.** The owner opened the Cloudflare preview: it 404s or bounces to the trailing-slash form | So the rule count cannot be collapsed. **Two rules of headroom against a cap that fails SILENTLY.** Consequence, binding on all of Phase 2: **no new route under `/clients/[id]`** — a query-param workspace instead, the way the year-end workspace already does it. The real relief is *reducing* dynamic pages, which the hub does anyway. ✅ **Written into `generate-redirects.js`'s own module doc and asserted, 24-09** (2.1). One clarification on re-measuring: there are **43** bare-path rules, and **41 of them are under `/clients/`** — so the number in the question is right about the subset the consequence actually binds on, which is the useful way round. The other two are `/health/:id` and `/relationships/:entity_id` |
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
| **D22** | G3 — the five hub tiles with no firm-level screen: build five roll-ups, or send them to the client picker? | **A per-client WORKLIST for four of the five**, at `/accounting/banking`, `/accounting/purchases`, `/accounting/fixed-assets` and `/accounting/year-end`. Inventory keeps none and says why | Taken by me on 24-09 under the standing instruction that code decisions are mine, in the shape the recommendation already named ("a firm-level roll-up is a STATIC route"). ⚠️ **The tombstones are what decides the shape, and reading them changed the answer.** `MovedToClientWorkspace` records a deliberate earlier decision — *"firm-level accounting screens have been retired; accounting flows exclusively through the client workspace"* — so rebuilding a firm-level Fixed Assets REGISTER is the duplicate those pages exist to prevent. What a bureau actually asks on the 3rd is **which of my clients needs work in this module**, which is a QUEUE, not a register: one row per client with the tile's own figure, every row opening that client's own section. `/accounting/fixed-assets` REPLACES its tombstone, whose message was already "choose a client" — this is that sentence with the clients that need choosing listed. **Inventory is refused and named**: its tile already carries `no_firm_signal_because` (on-hand stock is one client's ledger), so a worklist there would be a list of names with a dash beside each, which is `/clients` with extra steps. Cost: **zero** of D10's dynamic redirect rules — re-measured at 98 after the change. Overrule by saying so; it is four pages, one component and one read-only SQL function |

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
| **1.1** ✅ | **LANDED 24-09. The type scale (D12) — 380 arbitrary font sizes → 0, module by module, each with a before/after smoke walk.** 1.1a the auth and onboarding family (103 in six files, its own 32/26/22/18/16/14/13/12 ladder with three steps between Tailwind's); 1.1b the SHELL (13 × `text-[12.5px]`, a half pixel, showing on 90 of the 160 routes); 1.1c PAYROLL (90 in five files, and only ONE route moved because 71 are inside drawers and modals the walk never opens); 1.1d the TAIL (187 in 54 files, 149 routes moved). The 29 × `text-[9px]` round to `text-3xs` rather than gaining a token — T3-a's recorded decision that naming 9px would bless it. **Nothing needed a hand-set `leading-*`**, which is what D12 reserved for a size that got worse | 2–3d | `grep -rEoh 'text-\[[0-9]+(\.[0-9]+)?px\]' apps/web/app apps/web/components apps/web/lib \| wc -l` = **0** (the DECIMAL and `lib/` matter — the old spelling of this metric missed 13 half-pixel sizes), and the guard's budget is **0**, which is a ban rather than a number to raise |
| **1.2** ✅ | **LANDED 24-09.** **Width by content type (D11).** **59 pages rendered a table inside a centred container at NINE widths** — 576px to 1400px, `max-w-5xl` and `max-w-7xl` both common — and nobody chose that spread. One token, `max-w-ps-data` (1600px), on 58 of them; `portal/employee` is named as the one exception with its reason. **The reading half of D11 needed no work and the guard says why**: of 102 pages that centre a container, exactly one ran wide without holding data, and that one renders its rows through a custom component. Verified by a 160-route smoke walk before and after — 23 routes moved at 1440×900, each read, one page fixed | 1d | A guard fails a table page that picks its own width; the exemption list only shrinks |
| **1.3** | **The named-colour judgement pass (T4-b).** **5,840** utilities like `text-amber-600` (was 5,993). Status colours resolve to the semantic tokens; decorative ones stay. **Two slices have landed, each one where the judgement is not a judgement.** **1.3a (24-09)**: an element carrying `role="alert"` has ANSWERED the status question out loud, so 59 raw reds across 29 files resolve, and the money-direction tokens leave the five status sites they had been reached for as "a red and a green". **1.3b (24-09) — the surface follows the ink**: **181 class-lists carried `text-state-*` beside a raw Tailwind surface**, because the hex sweep tokenised the INK and left the SURFACE where it was, so `Filed` came out on two different greens across the product and `Overdue` wore three reds. The ink has already declared the state, so the surface is determined. Three things fell out of it: **eleven money-direction tokens painting a status inside `components/banking/`** — the very carve-out that made 1.3a's location rule safe is what hid them; **`state.attention-border` used as a chip FILL at 4.03:1**, under WCAG 1.4.3, including on a Team screen ROLE chip that is a category and had no business wearing a state token; and **the hover step two of the three states never had** — `ready-hover` existed alone, so `problem-hover` and `attention-hover` joined it at the `-100` values the product was already reaching for. **What is left of T4-b is now measured rather than estimated, and its biggest piece is an OWNER DECISION, not work**: the product has THREE primary colours — `bg-blue-600` (303) and `bg-blue-700` (244) against the brand navy's 200 and indigo's 92 — so Tailwind blue is the de-facto primary 547 to 200, and `tailwind.config.ts`'s own comment claiming it "closes all three" is not true of the codebase. Whichever way it goes, hundreds of buttons change colour or the brand loses, so it is question **G0** in `questions-for-the-owner.md` with a rendered three-way comparison. **AND T4-b's REMAINING 5,840 IS NOT 5,840 JUDGEMENTS — it is TWO DECISIONS AND A CODEMOD, measured 24-09.** Inside the 67 maps that ALREADY speak the state vocabulary — where the author had already decided this is a status — **191 raw colours survive**, and they sort almost perfectly: **green+emerald 66** (`filed`, `paid`, `completed`, `approved`) which IS `state.ready` and is determined today; **blue 51** (`in_progress`, `received`, `prepared`, `running`) for which **no token exists**; and **orange+yellow 27**, a RANKED ladder (`critical/high/medium/low`, `Healthy/Good/Needs Attention/At Risk/Critical`) where the set has three UNRANKED severities. The blue row is the finding: a CA screen asks a fifth question the vocabulary cannot say — *somebody is on it* — which is why blue is the largest colour in the codebase at 2,101 utilities and why it collides with G0. Both are question **G1**. **The 66 determined greens are deliberately NOT converted yet**: they are ~40 minutes, and doing them now means touching the same 67 maps twice, once for the greens and again when the tokens land. One pass after the decision beats two. **The smaller observation that started this**: 28 status words wear more than one spelling — `filed` appears in PURPLE once, `generated` is split 2-2 between blue and green, `cancelled` is red in four files and grey in two (it is `done`, not `problem` — a cancelled document is settled, not failed). It stops where a word needs a token that does not exist (`in_progress`, `issued`, `running` are none of the four states). **1.3c (24-09) — G1 ANSWERED, and the ladder was collapsing its own middle.** The owner's answer was *"you decide"*, so both tokens landed at values already on screen: **`state.working`** (#1D4ED8, the `blue-700` every screen was reaching for when none of the four states fitted) and a five-step **`sev` ladder** (`ok / low / medium / high / critical`), whose `ok` and `critical` deliberately hold the SAME hex as `state.ready` and `state.problem` because a second pair of near-identical greens and reds is what this file exists to stop. **186 class-lists across 56 files** converted; **44 change hue** and the rest are the same colour at the token's own shade. Two live defects fell out, neither in the measurement: **a ladder that borrows two steps from the state set collapses its middle** — `app/risks` painted `critical` and `high` both `state-problem`, `app/work` and `app/tasks/templates` painted `high` and `medium` both `state-attention`, so two RANKED steps rendered identically, invisible in review because the shared values make the mixture look right; and **a cancelled payment was a red pill with grey type** (`bg-state-problem-surface text-state-done`), called a failure by 1.3b and settled by 1.3c, with both halves tokenised so every rule written so far read it as clean. Also **two payroll screens disagreed about `finalized`** while one of them carried its own note saying *"Still to disburse"*. **The vocabulary is still short of two words and they are recorded rather than invented**: *waiting on somebody outside the firm* (`waiting_client`, 5 sites, all purple) and *queued, nobody on it yet* (`app/workflows`' `pending`). Both left exactly as they were. Named-colour utilities **5,840 → 5,541**. **1.3d (24-09) — G0 ANSWERED "Navy", and there were FIVE primaries, not three.** 1,193 utilities across 162 files: the fill of a primary control and its hover, the focus ring, the focus border, the soft halo, and the borders that dress a converted fill. **The count in the question was of what somebody had already measured; writing the GUARD is what found the other two** — the HSN library screen's buttons and focus rings were VIOLET and the treaty-rates screen's were SKY, neither colour in any palette and neither screen in any count. That is the argument for asserting a rule rather than converting a list. **The focus ring is an accessibility fix rather than a brand change**: `focus:ring-brand` is 15.05:1 on white where `ring-blue-500` was 3.68:1, barely clearing WCAG 1.4.11's 3:1, and `components/ui/field.tsx` had already written that rule in its own docstring (*"the fourth primary in a product that already had three"*) where it was true of one component and nothing else. **One thing is measurably worse and is recorded, not papered over**: the hover step, `brand` → `brand-dark` at 1.18:1 against `blue-600` → `blue-700`'s 1.30:1 — about 6.7 L* units, above the just-noticeable threshold, and it uses the pair the 22 existing brand buttons already wrote rather than inventing a third navy. Links (`text-blue-*`), the `-50`/`-100` tint panels and the opacity-modified column shades are deliberately out: a link in #182350 reads as body text, and a tint is a different role. `tailwind.config.ts`'s own "What follows closes all three" — false for months, since the token landed and the sites never moved — is corrected in place. Named-colour utilities **5,541 → 4,376**; blue alone 2,101 → 858. **1.3e (24-09) — the first MODULE pass, and it reversed two of 1.3d's own decisions before it caught itself.** `app/income-tax` converted by ROLE (202 sites, 8 files), `StatCard` with it, and `text-red-500` swept app-wide (101 sites, 66 files) because it is ONE role — problem — wearing a value that fails WCAG 1.4.3 at 3.76:1 on the glyph that is the only mark of a mandatory field. **Three defects fell out that are not colour at all.** `StatCard.gradient` was declared on the props interface, marked `@deprecated`, and **never destructured** — so the four `gradient="bg-gradient-to-br from-…"` values the income-tax page passed were type-checked, accepted and dropped, and all four tiles rendered the default (the `InvoiceLineIn.is_service` shape, migration 411); it is DELETED rather than implemented, because four tiles in four hues is the multi-accent pattern the palette exists to stop. A `bg-green-600` **primary** "Confirm Filing" button in a product whose 360 other primaries are `bg-brand`. And a regime-recommendation banner that painted the new-regime answer GREEN and the old-regime answer BLUE for one sentence with one shape, so the colour encoded which BRANCH rather than anything a CA needs. ⚠️ **AND THE SWEEP ITSELF BROKE TWO RECORDED DECISIONS, which is the durable lesson**: four inline links became brand navy although 1.3d left `text-blue-*` links alone for a stated reason (a navy link sits beside `ps.ink` #0D1635 and reads as body text; the app-wide convention is still `text-blue-600` at 64 sites), and the AIS badge's `explained` branch became a brand chip although a status in the brand is the one thing `tailwind.config` forbids. All six reverted, which is why the count is 4,043 and not 4,037. `explained` is the vocabulary's **third missing word** — settled by a human explanation, distinct from `ready` ("Agreed", the figures match) and from `done`, whose surface and ink are within a shade of the pair "Not reviewed" uses — and is left raw exactly as 1.3c left `waiting_client` and `queued`. Named-colour utilities **4,376 → 4,043**. The rest of T4-b is still a judgement per site | 2–3d | `amber`/`red`/`green` on a STATUS element resolve to `state.*`, asserted by a guard. **Eight rules are asserted today**: no money token on an alert; no money token outside the module where money has a direction; no raw status colour inside an alert; a surface beside a state ink comes from that state (now including `working` and every `sev` step); a money token carries no surface of its own; a state's or ladder's `-border` token is a border; a tokenised surface and a tokenised ink name the same state; a map paints with the severity ladder or the state set, never both; a primary action and a focus ring come from the brand (with an allowlist whose entries must still hold one) |
| **1.4** ✅ | **LANDED 24-09.** **The generic-Bank-ledger disclosure (D14).** `PaymentAccount.is_fallback` and `.reason` are computed and reach no caller. Surface on the entry row and in the posting confirmation. This is a refactor through eight journal-line builders | 1d | Posting a payment with no resolvable bank account shows the sentence in both places; a test asserts both |
| **1.5** ✅ | **LANDED 24-09.** **The filing-simulation wording (D17).** Every demo flow already carries an honest `SIM-NOT-FILED` reference and a "what changes when this is real" sentence. Rewrite those to read as a professional product statement — *"Preview only. PracticeSync does not transmit to the portal. Direct filing is in development"* — consistent across all flows, and visible on the screen rather than only in the response | 0.5d | One wording, one place it is defined, rendered by every flow; a guard asserts no flow renders its own |
| **1.7** | **The fee-engagement tier, and a state machine with no caller (question G2).** The backlog item read *"created over PostgREST, so `rbac()` and the state machine never run"*; re-reading the code found something sharper under each half. **`billing:write` is Partner-only** (*"exposes fee economics"*) and **`engagement:write` is Manager+**; migration 260 put the RLS on `fee_engagements` at Partner citing billing, and `POST /api/engagements` guards the same table with `engagement`. One row, two answers, a whole tier apart — so a Manager can create a fee-bearing row through the API (service-role key bypasses RLS) and is refused on the billing screen. And **`lib/api/index.ts` has no `engagements` namespace at all**: the whole seven-endpoint router is unreachable, so `POST /{id}/transition` — which validates `ENGAGEMENT_TRANSITIONS` and writes `audit_log` and the timeline — has never been called. An engagement is created `Active` and can never change, though the screen's own type offers `"Paused"`. **ANSWERED and mostly DONE 24-09**: the owner's reply — *"I thought we were going to change the control from position to per individual right?"* — reframes it rather than picking a tier, and is right: the grid is the control and the tier is the template it falls back to. Three things followed. **The two authorities now name `billing`** (the row carries the fee; migration 260 read it that way), and **that removes nothing anybody can do today** — `apps/web` mentioned `/api/engagements` NOWHERE, and the screen's own PostgREST insert was already refused for a Manager by that RLS, so no journey existed in which a Manager created one. **The screen goes through the API** and six of the seven endpoints have a caller. **And a status the database cannot hold is gone**: the screen's type said `"Active" | "Paused"` and migration 108's CHECK allows seven, none of them Paused — building Pause would have written a row Postgres rejects. ✅ **And the step that makes the grid real landed as migration 415**, on the owner's approval: `public.my_permission(resource, action, minimum_role)` is the SQL twin of `resolve_permission` and migration 260's nine policies ask it. No table's minimum ROLE moved, so against an empty `user_permissions` (403 wrote no backfill) it reproduces today's behaviour exactly. **The guard caught a lockout before it shipped**: the first draft asked `billing:delete`, a pair PERMISSIONS does not define, which `resolve_permission` treats as inert and `can` refuses — every fee invoice and fee engagement would have become permanently undeletable, for a Partner too. And the real database settled a second thing: a grant is a MODULE, not a SCOPE, because migration 084's `assignment_scope` is an orthogonal policy. ⚠️ One of the new tests was VACUOUS on its first run — a RESTRICTIVE `USING` clause FILTERS rows, so a refused UPDATE is `UPDATE 0` and psql exits 0; it measures the row now | done | A per-person grant reaches the database, proved against real Postgres |
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

**Re-measured 24-09-2026, because this file's own lesson is that an inventory
goes stale as fast as an audit's.** **161 routes is exact.** The other two
numbers need reading carefully, and the difference between them is what Phase 2
is actually for:

- **Six screens have no link ANYWHERE in the product**, not 39 — and
  `apps/web/scripts/every-screen-has-a-way-in.test.ts` already asserts it, with
  a recorded reason per entry and a staleness test that deletes an exemption
  once the screen gets a real link. So **2.5's guard is built and green**; what
  is left of 2.5 is placement, not reachability.
- **"In no menu" is the softer and more useful number, and it depends on what
  counts as a menu.** Against the shell, its panels and the client workspace nav
  — the things a CA would call navigation — **63** routes are absent. Against
  those plus each module's landing-page card grid, far fewer. The 39 sits
  between the two, which is why it cannot be reproduced exactly: nobody wrote
  down which definition it used.

**Settled by 2.5, 24-09:** the useful number turned out to be neither. Only **two**
named screens were absent from BOTH a panel and a landing page, and 46 of the 48
absent from the browse navigation were on their own module's landing page — so
almost nothing was an orphan. What was actually wrong is that the two surfaces
listed **disjoint** sets, which no count of "screens in no menu" can express. See
row 2.5.

That ambiguity is itself an argument for the hub. **Once 2.2 exists, "is this
screen in the hub" is a crisp test** and 2.5's guard tightens from *something
links to it* to *the hub reaches it* — which is the assertion the DONE WHEN
column has always asked for and that no shape of the current navigation can
support.

**The constraint D10 puts on all of it.** Cloudflare Pages silently ignores
`_redirects` rules past position 100. There are 98. The owner checked the
preview and the bare-path rules are load-bearing, so they cannot be collapsed.
**Two rules of headroom.** Every item below is designed around it: the hub adds
no dynamic routes, and anything new under `/clients/[id]` is a query parameter,
not a path. This is not a preference — it 404'd the entire client workspace
once already, with no build error and no log.

| ID | item | size | DONE WHEN |
|---|---|---|---|
| **2.1** ✅ | **LANDED 24-09. Re-pin the redirect budget and write D10 into the generator's own comment**, so the next person does not re-derive it. The budget was pinned at **≤ 99** against a real count of **98** — one above the truth, which is the same mistake as the old `≤ 90` one rule smaller: it silently admits the next page added, and that page lands the file ON the cap with no spare. It is an **equality at 98** now, a ratchet like every other count in this repo, and the failure message names D10 rather than inviting a bump. Three things the old guard could not see are asserted: the count is of **DYNAMIC** rules (Cloudflare's 100 cap is on those specifically — "lines ending in 200" coincides today only because the generator emits nothing static, which is now its own test rather than a comment); the budget's **SHAPE** (43 bare + 43 bare-RSC + 12 splats, and 41 of the 43 under `/clients/`), so a route being added and a shape changing are told apart; and the **arithmetic**, on a synthetic tree — a page under an existing splat group costs 2 rules and a page opening a new group costs 3, which is what makes 98 the last safe number rather than a preference | 0.5d | `generate-redirects.test.ts` pins the count at 98, names why the 43 cannot be collapsed, and fires on one added page — verified by adding one and watching it report 100 |
| **2.2** ✅ | **The hub — firm level and client level.** The 15 tiles of D1, each with live signal rather than a label. **The AUTHORITY landed 24-09** (`domain/hub/tiles.py` + 36 tests): what each tile ASKS, in what unit, and which tiles honestly have none. **The signal is what needs DOING, not what exists** — a tile reading "1,284 invoices" is unactionable, so every figure is outstanding work, which also fixes the direction (**lower is better on all fifteen**, so a CA never has to remember which way one reads) and a guard rejects a question that reads as a total. **Two tiles have no signal and say so**: `insights` and `reports` are destinations, not queues, and `describe()` FORCES their figure to None so a service cannot put a number on one by mistake — a nil meaning *nothing to do* and a nil meaning *nobody can tell* are different facts, and the payload keeps three states apart (0 / null-and-flagged / null-and-not, the third being a failed fetch), asserted as three distinct dicts. ⛔ **The href guard found the thing that changes the design**: it opens each destination against the real route tree rather than trusting the path, four were wrong, and chasing them found **five modules with no firm-level screen at all** — Banking, Purchases, Inventory, Year-End, and **Fixed Assets, whose `/accounting/fixed-assets` is a `MovedToClientWorkspace` TOMBSTONE**, which is worse than a 404 because it renders. That was **question G3**, and **D22 answers it — LANDED 24-09 as 2.7b**: four of the five got a per-client WORKLIST (one row per client with the tile's own figure, opening that client's own section), which is a QUEUE rather than a rebuilt register and so keeps the tombstones' own retirement decision intact. `/accounting/fixed-assets` replaces its tombstone. Inventory keeps none and `worklist.NO_WORKLIST_BECAUSE` says why. Cost: **zero** of D10's dynamic rules, re-measured at 98. | 3–4d | Every tile shows a real figure or a real count; none is a stub. Four negative controls on the authority, each firing on one test |
| **2.2b** ✅ | **LANDED 24-09. The hub SCREEN, firm level and client level** — `components/hub/Hub.tsx`, one component at both scopes, plus `GET /api/hub`, which lands WITH it because `test_every_mounted_endpoint_has_a_way_in` refuses a mounted route no screen calls (budget 0, and raising it would ship the shape the ratchet exists to prevent). **ONE REQUEST, not fifteen** — fifteen fetches would be fifteen Singapore-to-Mumbai round trips for fifteen numbers. **COMPOSED WITH `/` RATHER THAN REPLACING IT, and that is a change from what this row used to say**: reading `DashboardContent` properly, its three panels — Upcoming Deadlines, Recent Clients, Pending Tasks — are each a TILE'S OWN DESTINATION shown in detail, which is a reasonable thing to have under the grid rather than a thing to delete. The tiles go on top, nothing is lost, and the smoke-walk diff is additive. ⚠️ **Still owed and deliberately not in this change**: those three panels read four tables straight over PostgREST, unpaged. That is its own argument and its own guard. **THREE RENDERINGS, told apart by the SERVER and not by the value** — `0` with `answerable` is the finished state (drawn calm, in `state.ready`, because lower is better on every tile); `null` with `answerable: false` renders the reason instead of a number; `null` with `answerable: true` says this one tile could not be read while the other fourteen stand. `scripts/the-hub-renders-three-states.test.ts` forbids the one-character mistake (`signal ?? 0`) that turns *nobody can tell* into *nothing to do*, and forbids a tile with no `href` at this scope rendering as a link — G3's five at firm level, one of which is a tombstone that renders | 2–3d | Both hubs render from one request; no tile is a stub; six browser rules, two negative controls |
| **2.3** ✅ | **LANDED 24-09. The persistent client switcher.** The client's name in `ClientHeader` is the control: a searchable picker (the existing `Combobox`, `chrome="plain"`, so keyboard, a11y and search come free) listing the firm's clients, landing on **the same section of the new client**. **Where it lands is the whole rule and it lives in `lib/workspace/clientPath.switchClientPath`**: exactly ONE segment travels. Carrying the whole path would send `/clients/A/sales/invoices/<id>/edit` to `/clients/B/sales/invoices/<id>/edit` — B's workspace pointing at A's invoice, which is a 404 at best and one client's document under another client's name at worst. That is safe **by construction rather than by a list**: all 21 first segments under `/clients/:id/` have their own landing page (measured; 0 without), so no second vocabulary beside `CLIENT_SECTIONS` is needed — and a guard runs the real function over the real route tree, asserting every destination exists and that no switch ever carries the old client's id through. **The list comes from `GET /api/clients`, not PostgREST**, which is a permission decision: that endpoint is `rbac("client","read")` + `effective_client_ids`, so an Executive sees their assigned book; the browser's own SELECT policy is firm-scoped with no assignment test and would have named every client in the firm. It **degrades to the name** — the header already resolves the client for its heading, and that is the picker's placeholder, so a slow or failed list leaves the name on screen instead of blanking the header. ⚠️ **Typing `api.clients.list()` found two live defects in existing screens** — see the row below | 1–2d | Move client → client without returning to a list; four guards, two negative controls |
| **2.3b** ⚠️ | **Two screens believed the wrong shape of one endpoint, and the CAST is what hid it.** `api.clients.list()` was declared `request("/api/clients")` — return type `{}` — so all **six** callers cast it, and they held **two different beliefs**: four said `ApiResp<{clients: …}>` (right) and two said the payload was a bare ARRAY (wrong). The endpoint answers `{clients, total}`. So **`/settings/multi-currency` handed an OBJECT to `arrayOrEmpty`, got `[]` back exactly as that helper should, and listed no clients at all — for every firm, permanently**, on the screen ACC-19 had just built to switch multi-currency on per client; and **`/payroll/people` put the whole envelope into a `Client[]` state**, so the next `clients.find(...)` threw *"clients.find is not a function"*. Both screens FOLLOWED CLAUDE.md's payload rule — they applied it to the wrong FIELD, which is the thing a type can check and a convention cannot. Typing the namespace found both in one `tsc` run, and removing the casts found a **third** latent error the compiler had been asserted past: `ClientSummary.entity_type` is nullable and a local interface said it was not. The new guard is **per namespace, deliberately not a blanket rule** — 131 casts over `api.*` exist and most sit over namespaces still untyped, where the cast is the only shape information there is; banning all 131 produces a budget somebody raises until it means nothing. The ratchet is: type a namespace, add it to the list, its casts have to go. ⚠️ **The guard found a sixth caller a `grep` had missed**, which is G0's lesson again — a list holds what somebody counted, a rule holds what nobody has looked at yet | — | `a-typed-api-call-is-not-cast.test.ts`; the 131 remaining casts are recorded, not swept |
| **2.2c** ✅ | **LANDED 24-09. Calling the hub for real found three dead reads, and only one of them was the hub's.** 2.2b's two guards read `hub_service`'s AST and checked its columns against the live schema; NOTHING called `hub()`. Writing that test found `core.db_paging.fetch_all` handed something it cannot call at two sites — it CALLS `make_query` once per page, because a builder is stateful. `_sum_paise` passed THREE positional arguments, so **Sales, Purchases and TDS rendered "—"** from the day the hub shipped; `services/reorder_service._catalogue` passed the BUILDER, so **the reorder report has never run against a database** — INV-03's panel has always shown "Couldn't load the reorder report". **They hid for DIFFERENT reasons, which is what makes it a class**: one behind a router's broad `except`, one behind `_safely`'s deliberate per-tile one — and the mock suite could not reach the reorder path at all, because that router's `_USE_MOCK` branch passes `db=None` and short-circuits BEFORE the fetch. The third defect was the hub's own and is 2.2b's three-state contract turned on itself: `Tile.no_firm_signal_because` promised the CLIENT hub answers Inventory and `_signals` computed it at no scope, so a tile **nobody had asked for** was indistinguishable from one asked and failed. ⚠️ The inventory figure is the one read on the hub that is neither a count nor a summed column, and its cost is written down: catalogue-proportional, with a ledger-proportional FALLBACK if migration 363's aggregate raises — bounded to one client and removed by a `reorder_count_as_at` function, which is a migration and so is named rather than taken as a side effect of a hub. **`MAX_UNREADABLE` 459 → 463**: two of the four arrived with 2.2b unbudgeted, so that check was already red. **THE BLAST RADIUS WAS MEASURED, NOT ASSUMED**: all 59 services exposing a `db`-taking public function were CALLED against the shared `FakeDB`, and every one of them runs — `reorder_service` was the only live instance, and the four apparent failures were the probe passing a `str` where the signature wants a `date`. A negative result, and the reason the guard is the deliverable rather than a sweep | — | `test_fetch_all_is_given_something_it_can_call.py` states the rule on the ARGUMENTS at all 104 call sites; `test_the_hub_actually_answers.py` and `test_the_reorder_report_runs_against_a_database.py` are the two that CALL rather than read — a service whose job is to fetch needs a test that fetches |
| **2.2d** ✅ | **The payload guard covers the array half, and the object half is the one that crashed.** `a-payload-field-is-not-a-list-until-it-is-checked.test.ts` matches `useState<…>([])` and says in its own comment that an object-typed `useState<X | null>(null)` *"is a separate shape whose guard is `objectOrNull` at the read"* — and no guard for that shape exists. **Both components CLAUDE.md names as having crashed the 24-09 smoke walk are that shape**: `ExpiringEwayBills` held a `report` object and read `report.bills.length`; `FxRatesPanel` held one and read `types.find`. Measured 24-09: **66 object-state variables are set from a payload and then read with a nested `.map`/`.length`/`.filter` with no `objectOrNull` at the setter** — and the first sweep said 62, which its OWN negative control falsified: it matched `x.field.map` and not `x?.field.map`, and the optional-chained form is the dangerous one, since `?.` guards `x` and says nothing about `field`. ⚠️ **`objectOrNull` is NECESSARY AND NOT SUFFICIENT** and that is the part to read before sweeping: it answers whether `data` is the right KIND of thing, so `{}` passes straight through and `report.groups.map` still throws — a nested list needs `arrayOrEmpty` at the READ as well. And `report.items_considered === 0` is not a guard either, since `undefined === 0` is false. **One is fixed** — `ReorderPanel`, because 2.2c's `fetch_all` repair made its success path reachable for the first time ever, so a latent crash became a live one in the same commit. **LANDED 24-09. 66 → 0.** The guard is `an-object-payload-is-not-its-fields-until-it-is-checked.test.ts`, a FROZEN LIST rather than a budget and asserted as an equality in BOTH directions — which is what drove it to zero rather than to "mostly", since every fix failed until its own line came out. `objectWithLists` carries the two halves together. Three files needed hands because several components in one file share a state name (`data`, `result`) and a sweep keyed on (file, state) pools fields across them — **tsc caught every one**, which is the argument for typing a payload rather than casting it. The list is empty now, so the guard is simply the rule | — | 66 → 0; a new offender still fails the guard against an empty list (negative control run) |
| **2.4** ✅ | **LANDED 24-09. ⌘K finds SCREENS, and the names are the deliverable.** `lib/navigation/screens.ts` names 136 of the 161 routes and accounts for the other 25 with a reason each. **The route is the worst possible name** — `/accounting/msme-tracker` is the §43B(h) screen and nobody types "tracker" — so `synonyms` is where the statutory vocabulary lives, and it is the half that makes the palette worth opening: a CA types `43bh`, `gstr1`, `24Q`, `44AB`, `12BB`, `rule 46(b)`, `AS-3`, and almost none of that appears in a path. ⚠️ **THE PREFIX DECISION IS REVERSED and the reason is COST, not priority**: this row used to say entity search moves behind a prefix, and the commonest ⌘K use here is typing a CLIENT's name — `@sharma` makes the common case worse to tidy the rare one. Screens are LOCAL (they render on the first keystroke) and entities need the SERVER (which is where client-assignment scoping is enforced, M2), so both run, screens first, and `>` restricts to screens. Nothing removed, nothing slower. **A client screen needs a client** and that is a third state, not an absence: 32 live under `/clients/:id/` and are offered only inside a workspace, because offering them at firm level means inventing a pick-a-client flow, which is a feature and not a palette. **The two TOMBSTONES are deliberately unnamed** — typing "fixed assets" and landing on "this moved" reads as a working destination, 2.2b's argument about hub tiles (G3) | — | `every-screen-has-a-name.test.ts` runs BOTH directions: a route on disk in neither list fails, and a named route absent from disk fails too (2.2b found four typed paths that did not resolve). Four negative controls |
| **2.5** ✅ | **LANDED 24-09. Every module's sidebar lists the whole module.** ⚠️ **THE FINDING WAS NOT WHAT THIS ROW SAID, and the re-measure above already half-said so.** No named screen is an orphan: 46 of the 48 absent from the browse navigation were on their own module's landing page, and "39 orphans" remains unreproducible. The real defect is that a module has **TWO** navigation surfaces — the 220px panel the shell renders on every page of the module, and the module's landing page — and they listed **DISJOINT** sets for every module that had both. `/accounting`: 10 on the landing page, 4 in the panel, **not one in both**. `/settings`: 8 against 1, also disjoint. `/gst`, `/income-tax`, `/tds` and `/reports`: 11 sub-screens on landing pages, the panel offering the module ROOT and nothing else. So which half of their own module a CA could see depended on which surface they navigated by — and standing ON one of those screens the landing page is not in front of them and the panel is, so from `/income-tax/capital-gains` there was no way to `/income-tax/tax-audit` but the browser's Back button. **The panel is the surface present on every page, so the panel is the one that has to be complete**; a landing page may still feature whatever it likes. 36 entries added across five panels, each with its icon and, where a FastAPI permission governs the page, a `requires` pair **read off the endpoint's own `rbac(...)`** rather than guessed. Accounting (22 entries) and Settings (13) are GROUPED, and the eleven filing screens render under their hub only inside it — a flat list at 220px is a wall. **Two screens were in NEITHER surface**: `/team/workload`, and `/onboarding/checklist` — the client-onboarding tracker, which shared a path prefix with the firm SIGNUP wizard and so matched both `AppShell`'s no-shell list AND `isPublicPath`, rendering with no navigation at all and handed to signed-out visitors instead of the login page. Both lists are EXACT on `/onboarding` now. `getActiveWorkspaceForPathname` MOVED to `lib/workspace/routeOwnership.ts` (no imports, so a `node --test` guard can load it) because the guard has to ask which panel OWNS a route — `/payroll/attendance` was in TeamPanel and missing from the panel that owns `/payroll`, so the question is not "any panel" | 1d | `scripts/a-module-shows-all-of-itself.test.ts`: every named firm screen is in its OWNING panel, a frozen `NO_BROWSE_SURFACE` of 3 with an argument each and a staleness test both ways, the workspace→panel map READ OFF `ContextPanel.tsx` rather than copied, and a named negative control on the two that had nothing. Verified by breaking two entries and watching it report both |
| **2.6** ✅ | **LANDED 24-09. One shell, and the rail is CONSTANT.** Two shells shared nothing: `AppShell` rendered `ActivityRail` (52px navy) beside `ContextPanel` (220px white) and HID BOTH inside the client workspace, where `ClientWorkspaceShell` rendered `ClientContextPanel` — 200px navy, its own collapse, storage key, mobile drawer, close-on-navigate effect and reading of the URL. 2.8 existed because the two hamburgers rendered on top of one another. ⚠️ **AND THREE THINGS DID NOT EXIST INSIDE A CLIENT, which is where a CA spends the day**: `signOut` appears in exactly ONE navigation surface in this product and so does the only `href="/settings"` outside the settings screens — the rail. So a CA inside a client could not sign out or reach Settings without leaving the client, and ⌘K worked with nothing on screen saying so. Measured by grepping both, not inferred. `components/shell/NavShell.tsx` owns the desktop layout, one collapse and one storage key, one mobile trigger/backdrop/drawer/close-on-navigate and the main scroll area; callers own only CONTENT. `ClientWorkspaceShell` is the client HEADER now, because a header is content and a rail is chrome. ⚠️ **Two things the first draft got wrong and both are recorded**: `childOwnsScroll` (the old shell branched `h-screen overflow-hidden` inside a client so `ClientHeader` stays put — collapsing it gave two nested scrollers and 48px of dead space), and the collapse control lives on the RAIL, because a control inside the thing it hides has to be drawn twice, which is what `ClientContextPanel` did. **The rail is 64px and was 52**: the smoke shots show "Relationships" rendering as `elationship` and "Engagements" as `ngagement` on every firm screen. 64px fits ten of twelve; the last two carry a `railLabel` — the SAME WORD with a U+200B in it, so the browser breaks it where a person would rather than showing an abbreviation, since the width that fits them whole is ~84px and that is not an icon rail | 0.5d | `one-mobile-menu-button.test.ts` RESTATED, not deleted: its old rule ("nothing in AppShell's chrome renders inside the client workspace") is deliberately reversed by this change, so its three assertions failed on correct code — a spelling of the rule in one named file. It now states the rule that survives any restructuring: **exactly ONE mobile trigger and ONE drawer in the product**, counting `md:hidden fixed` rather than `<Menu>`, plus that the two retired components are GONE from disk. Six tests; a second trigger added to `ClientHeader` fails two of them. All three `window.location` static-export workarounds survive. **Verified visually**: 1633 frontend tests, tsc and lint clean, and a Chromium walk of all 43 client routes — 0 crashes, 42 distinct bodies, the only flagged route being the documented `/clients/:id` → `/overview` redirect |
| **2.7a** ✅ | **LANDED 24-09. PAY-28 / item 2.9 — payroll is ONE place, and it is the thirteenth workspace.** Its six screens sat across THREE top-level areas: `/payroll` and `/payroll/statutory` under Accounting, `/payroll/attendance` under TEAM, and three in no panel at all until 2.5 — which then left attendance in BOTH, two clicks apart under two module headings, lighting a different rail icon depending on which the CA used. `docs/architecture/10-payroll.md` specifies the fix as the 13th workspace and that is what this is. **Setup is a POINTER, not a seventh screen**: the doc's `/payroll/setup` is state coverage, which is already built at `/settings/statutory-values` (PAY-28's own verification says so), and a second screen for one fact is the `/accounting/retainer` mistake. ⚠️ **The new guard found a real defect on its first run**: `/deadlines` is in `STAFF_HIDDEN_HREFS` and `HomePanel` had NO role filter, so an Executive, a Reviewer and a Client were offered from Home a workspace the rail deliberately hides. ⚠️ **And the EXISTING guard was vacuous for four screens** — a negative control on `/payroll/people` PASSED, because `a-module-shows-all-of-itself` did not strip comments and every panel that gives a screen up writes a comment naming it. ⚠️ **The thirteenth tile fell off the rail**: at the old 56px pitch the column is 938px against a 900px viewport and the nav scrolls with the scrollbar hidden, so Engagements was there and nothing said so — 2.6's "elationship" defect in the other axis. `gap-1` and a 32px hit area buy back 76px | 0.5d | `scripts/a-screen-has-one-home.test.ts`: no named firm screen is in more than one panel, with a frozen `LISTED_TWICE` of 4 (each argued) and a staleness test both ways. Re-adding attendance to TeamPanel fails two of four AND leaves the old guard green, which is the argument for the new one |
| **2.7b** ✅ | **LANDED 24-09. D22 / G3 — the four tiles with no firm-level destination get a per-client WORKLIST.** `domain/hub/worklist.py` is the authority, `public.hub_client_worklist` (migration 416) the GROUP BY, `services/hub_worklist_service` the fetch with its mock-mode twin, `components/hub/ModuleWorklist` the one screen behind four thin pages. **The answer is one row per CLIENT**, so the reporting rule puts the aggregation in the database — PostgREST has no GROUP BY and the two Python shapes are N round trips or a ledger-proportional read, which is what the rule forbids. **Three places compute "what is outstanding on this tile" and a test holds all three to one vocabulary** (`hub_service._signals`, the twin's `_POPULATION`, and the migration's own SQL text). ⚠️ **The parity test reads the rows BACK out of Postgres rather than restating them**, because `bank_transactions.entry_state` is trigger-maintained (322) and `purchase_bills.outstanding_paise` is GENERATED (278) — the first draft seeded `entry_state` directly, the trigger recomputed it, and the two halves disagreed. Two fixtures can agree with each other while both disagree with the database. ⚠️ **The unreadable-column budget was recovered, not raised**: the generic `.select()` cost 2 against `test_backend_columns_exist_pg`, so the projections are written out per tile — four near-identical lines, the `domain/tally/party_identifiers` trade | 1d | 26 mock tests + 14 real-Postgres parity tests. Four negative controls, each firing on exactly the tests it should: a fifth entry state in the SQL, a branch losing its firm filter, a branch losing the client scope, and the `> 0` filter dropped. Redirect rules re-measured at **98**, unchanged |
| **2.7c** ✅ | **THE STRUCTURAL HALF OF 2.7 IS DONE, AND THAT IS A MEASUREMENT RATHER THAN A CLAIM.** 2.7's DONE WHEN talks about guards breaking on a MOVE, so it is about screens being in the wrong place — and after 2.7a and 2.7b every check that can express "in the wrong place" passes: every named firm screen is in its OWNING panel, no screen is in two, every screen has a way in, every hub tile lands on a real page, every client sub-screen is linked from its section page, ⌘K names 140 of 164 routes and accounts for the rest, and the per-module endpoint-reachability ratchet holds. Measured too: **`pageOnly` is 0 for every module** — every screen a landing page links is also in its panel, which is 2.5's disjointness gone in the direction that mattered. Four landing pages (`/practice`, `/team`, `/health`, `/relationships`) link to none of their own sub-screens and are LEFT ALONE: they are 259–1,021-line working dashboards with the complete panel beside them, which is the shape 2.5 settled. ⚠️ **AND THE REMAINING PER-MODULE WORK IS 1.3's TAIL, NOT A THIRD 2.7 ITEM — a correction to this row's own first draft.** It read "what is left under 2.7 is the DESIGN conversion", which conflates two phases: the **4,373 named Tailwind palette colours** (`app` 3,581 · `components` 780 · `lib` 12; worst-first `app/clients` 1,045, `app/relationships` 285, `app/income-tax` 202, `app/health` 188, `app/accounting` 180) are T4-b's remainder and belong to **row 1.3**, which says in its own words that "the rest of T4-b is still a judgement per site". Filing it here would give one body of work two homes, which is the mistake this file records everywhere else. **2.7 is closed.** ⚠️ **AND 4,373 IS A CEILING, NOT A BACKLOG** — read that before scheduling it as one. 1.3d's own record puts three categories deliberately OUT of the conversion: links (`text-blue-*`, because a link in #182350 reads as body text), the `-50`/`-100` tint panels, and the opacity-modified column shades; chart series and illustrations are out for the same reason the hex guard exempts them. A sample of `app/income-tax`'s 202 is roughly half exactly those — `bg-blue-50 border-blue-200` info boxes and `bg-green-50` chips — so a blind module sweep would REVERSE recorded decisions rather than continue them. It is a judgement per site, which is what 1.3 has said all along; the ratchet stops the number growing while that judgement is made. The first pass on income-tax already has a real finding in it: a `bg-green-600` primary-action button in a module whose primary is the brand navy | 1d | **The ratchet landed first**, which is the part that was missing: the named-palette count was a number in the metrics table above and NOTHING enforced it, so it could grow on any commit. `a-colour-and-a-type-size-come-from-the-token-file.test.ts` now pins it at 4,373 and may only come down, counting **the same list this file's metric greps** — CLAUDE.md's own lesson about a metric and its guard counting the same population. Then one module per PR, lowering the budget in the same commit |
| **2.8** ✅ | **LANDED 24-09. The two stacked mobile hamburgers.** `AppShell`'s desktop branch already hid `ActivityRail` + `ContextPanel` inside the client workspace, with a comment calling the failure to do so the "two sidebars" bug — and the MOBILE half was never gated. So at `/clients/:id` on a phone both triggers rendered: AppShell's `fixed top-3 left-3 z-40` white `p-2` button under ClientContextPanel's `fixed top-2.5 left-2.5 z-50` navy `w-8 h-8` one. Different size, different colour, **2px apart**, so the white one showed as a rim along two edges of the navy — and tapping that rim opened the FIRM drawer on top of the client workspace. Gating it loses nothing: the client drawer's own header already carries the `/clients` back link, which is the same way out the desktop panel gives, and `ClientHeader` reserves the space with `pl-12 md:px-4`, sized for one button. **The guard states the rule the file had already made for desktop, for every viewport** — *nothing in AppShell's chrome renders inside the client workspace* — rather than "the hamburger is gated", because the next thing added to this shell (a bottom bar, a floating action button) collides identically and would pass a guard that only knew about `<Menu>`. It matches parentheses from the gate's opener rather than using a regex, since the body is JSX with its own brackets | 0.5d | One drawer, reachable. Three negative controls, each firing on exactly one test: ungating the mobile block (the original defect, 3 ungated `md:hidden`), the client drawer losing its way out, and the header no longer reserving the space |
| **2.9** ✅ | **PAY-28** — payroll's three top-level areas. **LANDED 24-09 as 2.7a** | — | Payroll is one place, and `a-screen-has-one-home.test.ts` holds it as a rule rather than as an assertion about payroll |

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
| 3a-2 ✅ | Client profitability and realization | **DONE 25-09.** `/practice/profitability` reaches both. **It sits under Practice, not Health**: the hub's `insights` tile points at `/health`, whose own panel is headed *Client health monitor* — how the CLIENT is doing — while revenue less cost per client is how the PRACTICE is doing, which is what `/practice/revenue`, `/billing`, `/collections` and `/ar` already are. Repointing the tile needs a real Insights page holding health, risk AND profitability together, which is 3a-1. **Not `PartnerGuard`**, although `/practice/revenue` is: both endpoints narrow their per-client rows — and, on profitability, their TOTALS — to the caller's assigned book, with a test pinning both directions, so a Partner-only screen would make that narrowing dead code and hide a Manager's own book from them. ⚠️ **SURFACING THEM FOUND TWO LIVE DEFECTS, WHICH IS THE ARGUMENT FOR DOING 3a AT ALL.** (1) `_period_range`'s quarter label was the CALENDAR quarter — Jan-Mar came back "Q1 2026" where a CA reads Q1 as April-June and calls that window Q4 of FY 2025-26 — and it was wrong in **all four** quarters, not just across the year boundary, on five endpoints. The BUCKET was always the Indian one, so only a string moved; the label now comes from `core.ist_clock.fy_quarters`. (2) `revenue_vs_effort`'s two loops bound their row's client to `client_id`, the PARAMETER's own name, so the filter at the foot read the LAST key of the dict — truthy for every caller — and the realization report **has never once returned more than one client**, chosen by dict iteration order. Its own comment said the parameter "never filters anything", the opposite of what it did, which is how it survived. Both pinned, both with a negative control. | 
| 3a-3 ✅ | Statement analysis | **DONE 25-09.** `StatementAnalysisPanel` on the client accounting **Reports** tab, where the client and the financial year are already chosen — which is why a firm-level version would need a picker nobody wants. It renders the RATIOS from the payload's own numbers rather than parsing them out of the prose, so nothing on the panel is a figure the model chose, and it shows `ai_generated` rather than hiding it: when Groq is unreachable the service falls back to a deterministic sentence, which is a different kind of statement and the reader is entitled to know which they have. It does not load on mount — an LLM round trip on a tab opened to export a spreadsheet waits to be asked. ⚠️ **AND LOOKING AT IT EXPOSED A HOLE IN THE SMOKE WALK: it photographs ONE TAB PER ROUTE.** A tabbed screen keeps its tab in `?tab=` and the route list carries no query, so the twelve-tab accounting page has only ever been seen on `dashboard` — eleven panels, and the same on GST, sales and payroll, have never appeared in a shot, which is exactly where a panel can render a header over nothing unnoticed. `--at <path>` walks a given path verbatim, query included, as a SPOT CHECK; walking every tab means reading each page's own `TABS` const and is its own change. Its first run found a second bug in the walk itself — the trailing slash the static export needs was appended AFTER the query, so `?tab=reports` arrived as `reports/`, fell back to the default, and the run photographed Dashboard while reporting Reports. | 
| 3a-4 | Health — render the **computed** 7-dimension score | 8 unreached health endpoints reached; screens stop rebuilding scores from raw rows |
| 3a-5 | Compliance risk and predicted misses | `/api/intelligence/*` reached |
| 3a-6 | `ai_insights` — wire the **writer** | Today a screen reads a table nothing reachable populates |
| 3a-7 | Give the copilot the client's own data | The 8 unreached copilot endpoints reached; the static prompt replaced by one that loads the client context |

**Target: the 231 unreachable endpoints fall below 120.**

**One of them is now measured and NAMED, because it is the shape the rest of
that 231 will turn out to be** (24-09). `POST /api/banking/transactions/{id}/post`
and its `/posting-preview` twin had lost their browser caller, and the obvious
reading — a dead endpoint duplicating the live `/pass` door, so D21 says delete
it — **is wrong, and the docstrings are why anybody would read it that way.**

`PassEntryIn` carries `gst_rate_bps` and `is_interstate` and **no account
fields at all**. `PostBankTxnIn` carries `bank_account_id`, `account_id` and
`to_bank_account_id`. So `/pass` applies the draft the machine wrote and
`/post` applies a coding the CA chose, and those are two different acts. Both
reach the same `bank_posting_service.post` kernel, which is what made them look
like one door.

**The consequence is a product gap, not dead code: a CA cannot code a bank line
themselves from any screen.** `/entries/redraft` re-runs the machine's
proposal, `/pass` accepts or rejects it, and nothing takes an account the
person picked. `/post` is the endpoint that closes that and it has no screen —
so under D21 this is the WIRE IT UP branch, like the e-way extension and the
firm's own GSTIN, and it belongs here in Phase 3 rather than in a cleanup.
Deleting the browser wrapper would have made the gap invisible.

Two docstrings said `/pass` applies "the draft **or the CA's own coding**",
which its signature cannot express; both are corrected in the same commit.

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
