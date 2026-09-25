# THE PLAN

**The one plan, end to end. Everything else in `docs/plan/` is history.**

Restructured **25 September 2026** at the owner's request — *"there were many
updates and changes so restructure the phases and draw out a plan so that we
dont miss anything."* Every number below was measured on that date by running
the command beside it. Where a carried-forward figure turned out to be wrong,
the correction is recorded rather than quietly replaced.

Supersedes the 24 September edition and everything before it.

---

## Why this is a RESTRUCTURE and not an edit

The 24 September plan had eight numbered phases in a line. Two things have
happened since that make the line the wrong shape:

1. **Phase 2 is finished, and it finished by being replaced.** What shipped is
   not what Phase 2 specified — the owner looked at the live site, said *"the
   current redesign is actually the same right i dont feel any change for
   real"*, and the workspace was rebuilt around a module grid instead. The
   phase is closed, and its own plan is now history.
2. **The largest remaining class of work has no phase at all.** It is not a
   list of features; it is a SHAPE this codebase keeps finding — an engine
   that is built, tested, mounted and reachable by nobody. `capital_wip` was
   one. The AS 18 related-party note is one. There are more, and a numbered
   phase cannot hold something whose members are still being discovered.

So the phases become **five tracks and one standing lane**. A track is a thing
you could look at and judge; the lane is work that never finishes and must not
block a track.

| old | new |
|---|---|
| Phase 0, 1.1–1.5 | **done** — folded into the history below |
| Phase 1.6 (the partials) | Track 1 §C |
| **Phase 2 (navigation)** | **done** — §"What shipped" below |
| Phase 3a (surface what exists) | **done** |
| Phase 3b, 3c | Track 1 §B |
| Phase 4 (portals) | **Track 2** |
| Phase 5 (demo firm) | **Track 3** |
| Phase 6 (verification) | **Track 4** |
| Phase 7 (registrations) | **Track 5** |
| Row 1.3 tail, dividers, docs | **Standing lane** |
| *(new)* the unwired engines | **Track 1 §A** |
| *(new)* platform: Workers, Render | **Standing lane** |

---

## Where the product actually is — measured 25 September 2026

| what | now | was 24 Sep | how it was measured |
|---|---|---|---|
| Audit findings closed | **266 of 279** | 265 | `docs/audits/findings-status.json` |
| — partial | 6 | 6 | ACC-13, FA-11, IT-11, PAY-27, SALES-23, TDS-22 |
| — open | 2 | 2 | TDS-16, GST-25 — both blocked on a document |
| — not a defect as stated | 5 | 5 | including **PAY-28**, re-read after the redesign |
| Migrations | **416** | 416 | `ls apps/api/migrations/ \| tail -1` — Tracks 1–3 carried none |
| Backend tests | **17,460 pass**, 1,621 skip | 17,263 | `pytest tests/` |
| Real-Postgres suite | **1,571 pass** | not tracked | `HARNESS_PG=… pytest tests/test_migrations_apply.py tests/test_*_pg.py` |
| Frontend guards | **1,655 pass** | 1,644 | `pnpm test` |
| Routes in the app | **166** | 166 | `find apps/web/app -name page.tsx \| wc -l` |
| Endpoints a screen can reach | **856 of 1,069** | 856 | the reachability ratchet |
| Smoke walk | **166 screens, 0 problems** | not tracked | `pnpm smoke:build && pnpm smoke` |
| Error boundaries | **65** | 65 | target ≥14 ✅ |
| **Arbitrary font sizes** | **0** | 0 | **target 0 — D12 is COMPLETE** ✅ |
| **Named palette colours** | **3,712** | *4,043 — but see below* | the guard is the authority |
| Invisible dividers | **0** | 1,009 | `a-divider-you-cannot-see-is-not-a-divider.test.ts` |
| Hardcoded hex (coarse) | 83 | 70 | the guard is the authority, not this grep |
| Cloudflare redirect rules | **98** | 98 | **HARD CAP 100, fails silently** |

⚠️ **THE NAMED-PALETTE FIGURE IS NOT COMPARABLE WITH THE ONE ABOVE IT, AND
THAT IS THE POINT.** The guard's family list was **eleven of Tailwind's
twenty-two**, so purple (69), indigo (59), violet (56), cyan (16), sky (14)
and pink (2) — **216 sites** — had never been counted by anything, and the
count could not have gone up when somebody wrote a purple chip. Indigo is the
one that stings: the token file names it as the *fourth primary* and G0
converted 92 sites of it on that argument, with 59 more sitting in a family
the ratchet could not see. Found by converting a compliance screen whose three
navigation cards were tinted green, blue and **purple** — two counted, one
not. The list is Tailwind's own now; 3,712 is the first honest number.

**Two numbers moved that are worth naming.** Arbitrary font sizes went 379 → 0,
which closes D12 outright. Endpoint reachability went 829 → 856 without a
reachability push, because every screen built since carries its own endpoints.

---

## What shipped on 25 September — the navigation redesign

Recorded here because it replaced Phase 2 rather than completing it.

**The diagnosis.** `/clients/{id}` was not a page — a spinner and a
`router.replace` to `/overview/`, so there was no front door. The tile grid
already existed with live figures and sat at **line 133** of the overview page,
below the fold. And the 272px, 21-item `ClientSections` list — not the 64px
rail — was what made the workspace feel like a file cabinet. Phase 2.6 had
turned that list from navy to white, which is invisible to a person using the
product. That is why the owner felt no change.

**What replaced it** (#613, #614):

- `/clients/{id}` is the **front door**: every module as a card. Zero redirect
  rules — that route already existed to serve the redirect it replaced.
- The **module name in the header is the switcher**, opening the same grid over
  the content. One object, two jobs.
- The **firm rail is gone inside a client**. `AppShell` returns `ClientShell`
  (one 48px bar) or `NavShell` (rail + panel) and **never neither** — the three
  things 2.6 exists for (sign-out, Settings, ⌘K) moved into `UtilityCluster`,
  which both shells render.
- **The grid carries no figures** — see D25.

---

## Decisions — locked. Do not re-litigate.

### Taken earlier

| # | decision | answer |
|---|---|---|
| D1 | Hub tile set and order | **15 tiles**, D1's order |
| D2 | The screens in no menu | **Give them a home** |
| D3 | Portals in scope? | **In scope** |
| D4 | Density persistence | **Per device** |
| D5 | Money display | **2 decimals**, whole rupees on return-prep screens |
| D6 | Rupee grouping | **Indian everywhere** — 12,34,567 |
| D7 | Demo on real or seeded data | **Seeded demo firm** |
| D8 | i18n | **Extract strings, translate nothing** |
| D9 | A PR carrying a migration | **Merge it like any other** |
| — | Access control | **Person-wise.** Role is the template; the grid is the authority |
| — | Emailing a client's customers | **Never automatic.** A Send button, always |

### Taken 24 September

D10–D22 stand unchanged. In brief: **D10** the redirect rules are load-bearing
(98 of 100, no new route under `/clients/[id]`); **D11** width by content type;
**D12** convert every hand-written text size — **now complete**; **D13** keep
`Rs.` on PDFs; **D14** tell the CA on the row AND in the confirmation;
**D15** navigation → analytics → portals → demo firm; **D16** no fixed date;
**D17** stay prepare-only; **D18** the six documents are tracked, not blocking;
**D19** a trusted bank rule flags a TDS decision, never decides it; **D20**
credit limits warn by default; **D21** delete a dead endpoint that duplicates a
live one; **D22** a per-client worklist for four of the five tiles.

### Taken 25 September

| # | question | decision | the reasoning |
|---|---|---|---|
| **D23** | Does the firm rail stay inside a client workspace? | **Remove it completely** | Owner: *"when inside a client they should see only the client stuff and we will give the exit the client workspace button and that helps in the per person access as well right."* This REVERSES 2.6's "the rail is constant". What 2.6 actually fixed was the ABSENCE of sign-out, Settings and ⌘K, not the presence of the rail — so those three moved into `UtilityCluster`, which both shells render, and a guard asserts reachability from each. The owner's second clause is the stronger argument: a client-scoped shell is what lets migration 403's per-person grid decide what a person sees |
| **D24** | Where does a client workspace open? | **`/clients/{id}` is a real page showing the module grid** | It was a redirect to Overview, so there was no front door. Costs **zero** of D10's budget because the route already existed. Overview is unchanged and one click away |
| **D25** | Does the grid carry live figures per module? | **No. Plain names.** | Built with figures, removed the same day on the owner's report: *"for 10 seconds there are no numbers then suddenly the numbers come… the plain name is fine it looks good."* The defect was not the delay — it was that the grid derived its own SHAPE from the payload, so after ten seconds of Render cold start it re-sorted, re-banded and re-flowed every card. **Progressive loading must not move what is already on screen.** Figures may return one day in a fixed-height slot inside a card that never re-orders. The same figures are on Overview, one click away |
| **D26** | The 100-rule redirect cap — live with it, or leave Cloudflare Pages? | **OPEN — owner's call.** My recommendation: migrate Pages → Workers | Researched 25-09 against Cloudflare's own docs. The `_redirects` cap is **identical** on both products (100 dynamic), so the migration does not raise it — but on Workers you need no `_redirects` at all: ~15 lines in a `fetch` handler do the rewrite in code and the cap disappears, along with `generate-redirects.js` and D10 as a constraint. **No new subscription**: Workers Free is 100,000 requests/day, static-asset requests are free and unlimited on both plans, and the Worker would run only on `/clients/*` page loads. Cost is a day, most of it verifying every route shape on a preview URL before the domain moves. **I cannot do the cutover** — it is the owner's Cloudflare account and it changes how the live site is served |

---

## Track 1 — Nothing a CA opens is a stub · 🔧 C

**The theme.** Every remaining defect class has one shape: the computation is
right and something between it and the CA is missing. Ordered by what a CA
would notice first.

### §A — the unwired engines (NEW, and the largest of the three)

A built, tested, mounted engine that no screen reaches. This codebase has found
it repeatedly — `capital_wip`, the FX revaluation, the §115BAC(6) election,
`invoice_templates`, `POST /api/itr/snapshots/{id}/review`. Each was invisible
until somebody read the callers.

| ID | item | state | DONE WHEN |
|---|---|---|---|
| 1A-1 | **Related parties / AS 18** | **done 25 Sep** ✅ | `GET /related-party-report` had zero callers and dropped a Karta, a Proprietor and a Beneficiary from a statutory note in silence. `domain/related_party/disclosure.py` + `services/related_party_service.py` + a client tab that lists roles, picks an entity and renders the note with its gaps. Transactions matched on PAN against the customer and vendor masters. 30 tests green |
| 1A-2 | **Sweep for the rest of the class** | **done 25 Sep** ✅ | `tests/test_a_computed_answer_nobody_can_open_is_named.py`. A guard, not a list: every GET whose response is a computed REPORT has a caller or a named exemption. **12 named with reasons, frozen as an EQUALITY** rather than a budget, so a fix that leaves its entry behind fails as loudly as a regression. Three left the list the same day and for different reasons — one wired, one wired, one DELETED as a byte-identical duplicate |
| 1A-3 | Re-read **PAY-28** | **done 25 Sep** ✅ | Re-read against the code; `not_a_defect_as_stated` |

### §B — analytics with no screen (was Phase 3b / 3c)

| ID | item | state |
|---|---|---|
| 3b-1 | Ledger anomaly detection | **done 25 Sep** ✅ — and **NOT over `account_period_balances`**, reversing the plan. That table is a cache with a healing auditor, and a check looking for things wrong with the ledger must not read something that can itself be wrong; it reads the posted entries the runner already fetched. A tenth check in the existing Verify Books engine rather than a parallel feature. Three kinds, all `warning`, each with the innocent reading beside the guilty one. ⚠️ Two of my own defects here, both caught by a negative control: the dormant check as first written **could never fire** (the closing balance IS the sum of the months), and the median's justification was wrong — a probe swapping `_median` for a mean passed every test |
| 3b-4 | Firm-wide capacity risk | **done 25 Sep** ✅ `domain/practice/capacity_risk.py` + `GET /api/workload/capacity-risk`, 13 weeks ahead. It refuses two numbers it would be easy to invent: hours are reported only where a workflow step recorded one, and load is measured against the practice's **own median week**, never `max_concurrent_tasks`, which is a limit on what may be OPEN |
| 3b-5 | Surface `workload-insights` | **done 25 Sep** ✅ — by rendering the **unassigned backlog only**. `overload` and `idle` restate what `/team/workload`'s own member grouping already says from the same tasks, and two authorities on who is overloaded disagree the first time either threshold moves |
| 3c-3 | **Fee concentration** — if the largest client leaves, what happens | **done 25 Sep** ✅ `domain/practice/concentration.py` + `GET /api/analytics/concentration`, rendered on `/practice/profitability`. The ICAI fee-dependence threat is NAMED and no threshold is drawn: icai.org is refused at this environment's proxy, and a percentage from memory on an independence question hands a firm a clean bill of health nobody issued |
| 3c-1, 3c-2, 3c-4, and the tax half of 3c-5 | Effective tax rate trend · ITC leakage trend · GST/TDS/payroll trends · cross-client tax benchmarking | **blocked — STUCK.md §1.** Not a judgement call: each figure is derived from a client's whole ledger for a period, so computing it for every client to compare one against them is a read proportional to transaction volume × client count. Needs a `client_period_metrics` table on the `account_period_balances` shape, maintained by the nightly sweep. **Which columns it holds is the owner's**, because a column added later cannot be back-filled for a period whose books are locked |

### §C — the six partials (was Phase 1.6)

| finding | what remains | blocked? |
|---|---|---|
| PAY-27 | three more payroll report shapes, if wanted | no |
| IT-11 | **Form 3CD** — a clause workspace, needs a migration | document #4 |
| SALES-23 | whether the nightly sweep may EMAIL a client's customers | **owner (A)** |
| ACC-13 | **cost centres** — a dimension on `journal_lines` | **owner (C)** |
| TDS-22 | two numbers for the §194I(a)/§194J(a) limbs | document #4 |
| FA-11 | shift working (NESD markings); revaluation and component accounting unstarted | document #9 |
| TDS-16 *(open)* | the FVU/RPU file writer | document #3 |
| GST-25 *(open)* | composition, TCS on GSTR-8, GSTR-9C | document #5 |

---

## Track 2 — The portals · 🔧 C · 8–12 days

Six routes, ~1,738 lines under `apps/web/app/portal/`, rendered outside the
staff shell and importing almost none of the shared primitives.

**This is the only surface the CA's own client and employees ever see.** If it
keeps today's look, the product visibly has two designs and the outside world
sees the old one.

| ID | item | DONE WHEN |
|---|---|---|
| 2.1 | Client portal on the design system | **done 25 Sep** ✅ `PortalShell` + the shared primitives; the local `Panel`/`Table`/`Empty` were those written twice in raw grey and are gone |
| 2.2 | Employee portal on the design system | **done 25 Sep** ✅ Same shell — and it had **no sign-out at all**, so an employee reading a payslip on a shared phone could not end the session |
| 2.3 | `apps/marketing` brand parity | **done 24 Sep** ✅ |
| 2.4 | The portal dashboard drops 3 of 7 sections the API serves | **done 25 Sep** ✅ All seven render. The three were BUILDABLE — migration 109's RLS already grants the contact the tables — so Documents, Document Requests and Messages are real now, served (not read over PostgREST, because the DOWNLOAD cannot work there: migration 005's storage policies key on `get_my_firm_id()`, which a portal contact has no row for). `_DASHBOARD_SECTIONS` grew a `note` per section and the browser keeps no list |
| — | Guard | `scripts/the-portal-wears-the-product.test.ts`: every page wears the shell, no raw palette colour, no browser-side section vocabulary |

---

## Track 3 — The demo firm · 🔧 C · **done 25 Sep** ✅

Seeded (D7). The live book was 7 clients and 2 bank accounts with most tables
empty, so every screen rendered its empty state and nothing could be judged.

**Sharma & Associates**, Mumbai, FY 2025-26 — 8 clients, 31 customers, 30
vendors, **315 sales invoices** (285 issued, 227 settled, 33 of them in part,
88 still open), **200 purchase bills** (181 received) and 139 vendor payments,
**9 bank accounts** with **276 statement lines**, **21 fixed assets**, **12
employees** across **24 payroll runs**, 42 inter-state supplies, 9
reverse-charge bills, 16 unregistered parties. One full run is **1,528 API
calls**.

| | |
|---|---|
| `domain/demo/fixture.py` | the practice as DATA — no handle, no call, deterministic on one fixed seed, and nothing in it reads the clock (a demo pinned to "now" is a different set of books every month, and a LOCKED PERIOD cannot be demonstrated at all if every date is recent) |
| `scripts/seed_demo_firm.py` | writes it **through the API, never the database** — every posting here goes through the one kernel, and a seeder writing rows directly would produce books this product's own Verify Books would refuse. **A DRY RUN until `--confirm`**, and it refuses a firm that already has clients |
| `tests/test_the_seeder_actually_seeds.py` | RUNS `seed()` through the real routers. A seeder whose job is to WRITE needs a test that WRITES — the first real run died on the first invoice, because `service_catalogue_id` has been required since migration 206 and no amount of reading the fixture could have said so |
| `tests/test_every_body_..._its_door_accepts.py` | runs the same `seed()` against **the app's own route table** and validates each body against the model FastAPI resolved for that path. No hand-written map, so a door added tomorrow is covered the day it is written |

**Three modules were still empty and are not now.** Every receipt, vendor
payment, asset purchase and salary disbursement names the client's own bank
account, so the money lands in that client's ledger rather than
`resolve_payment_account`'s generic `%Bank%` fallback — a real disclosure that
a demo carrying it on every posting would teach the CA to ignore. The register
holds a **Land** row nothing depreciates, a motor car whose §17(5)-blocked tax
is capitalised, and assets acquired in earlier years so the movement note opens
with a gross block. The payroll year is left in **all three states** — ten
months paid, one finalised, one still a draft — because a book of twelve
drafts has posted no journal and paid nobody.

**What the bank statement deliberately does NOT carry** is a line for a receipt
the ledger already holds. Passing a statement line CREATES a voucher, so such a
line invites the CA to record the same rupees twice on the very screen the demo
is meant to sell. What is on it is the operating outflows nobody has coded —
rent, power, courier, and the bank's own charges, which carry GST and are
BANK-24's whole point — plus credits against invoices nobody paid, which is
what gives the match queue a real candidate to offer.

**AND EVERY DOCUMENT WAS A DRAFT, WHICH IS THE ONE THAT MATTERED MOST.**
`POST /api/sales-invoices/` and `POST /api/purchase-bills/` both insert with
`status: "draft"`; the journal is posted by the SEPARATE transition,
`/{id}/issue` and `/{id}/receive`. So the demo had 315 invoices and 200 bills
that posted no journal, raised no receivable or payable, moved no stock and
**reached no return** — a GSTR-1 and a GSTR-3B structurally empty on a book of
515 documents, with every count looking right. 285 invoices are issued now and
181 bills received; **the last month is left in draft on purpose**, because a
practice partway through the month after the year end has exactly that, and a
book where everything is posted cannot show the issue and receive buttons.

**Inventory opens with stock.** Each goods item carries an opening quantity and
its COST — not its price, AS-2 paragraph 6 — so the first sale of the year
relieves real stock instead of driving the position negative on document one,
and the item group and reorder level make the reorder report and the item
grouping non-empty. Two items deliberately have **no** reorder level, because
zero is a real answer ("tell me when it runs out") and reading an absence as
zero records a decision nobody made.

**Two fields were being silently dropped**, and only the route-table guard
could see it: `hra_paise` and `date_of_joining` on a payroll employee, where
`EmployeeIn` declares `hra_percent` and `joining_date` — so every seeded
employee had no joining date and no house rent allowance in their §192 working
— and `msme_status` on a vendor, which is not a field of `VendorIn` at all and
is recorded through the Schedule III ageing screen's own door.

**Each client exists for a different screen**, and the fixture says which:
the ordinary monthly GST client for volume; QRMP; a proprietor for §44AD; a
GTA for reverse charge; payroll spanning the ESI and Bonus Act ceilings; a
partnership for §194T; an individual with no GSTIN; construction for CWIP.
Some vendors are deliberately **unclassified** under MSMED, because §43B(h)
names that gap rather than assuming Others and a fixture where everything is
classified cannot show it.

---

## Track 4 — Verification, with you · 🤝 · one session

### My gates — I do not book the session until all five pass

| # | gate | state on 25 Sep |
|---|---|---|
| 1 | Every track above closed or explicitly deferred by you | **Tracks 1–3 closed.** What is left inside Track 1 is §B's tax benchmarking (blocked, STUCK.md §1) and §C's partials — four on a document, two on you |
| 2 | Backend and frontend suites green, smoke walk renders every route | **suites green, SMOKE WALK RED.** 17,494 backend · 1,566 real-Postgres · frontend lint/typecheck/test/build green. The walk renders all 166 screens with 0 per-screen problems and then **fails its own duplicate-body check**: six `/clients/_placeholder/…` screens (overview, sales, purchases, inventory, relationships, the journal editor) render the workspace shell and nothing else, because the walk feeds every `:id` the literal `_placeholder` and no client resolves. `MAX_ROUTES_PER_DIGEST` is 5 and the script's own comment says a sixth *should* trip it — *"six screens showing a CA nothing but navigation is the finding, not the false alarm"* — so the threshold is NOT being raised. The comment also says a seeded demo firm fixes it, and **that is not true**: the walk uses `_placeholder`, which resolves to nothing whatever is seeded. See STUCK.md §3 — it is one design decision |
| 3 | No screen renders a figure the server did not compute | **MEASURED 25 Sep, and it is not clean.** The guards that hold it (`a-computed-figure-reaches-the-screen`, `tds-is-computed-by-the-engine-not-the-browser`, `section-32-is-computed-on-the-server`, the browser-logic scans) all pass. But `apps/web` carries **264 sites of arithmetic on a `*_paise` value** outside tests. Most are presentation — summing a column, `a − b` for an outstanding figure — and the sharp end is **43 MULTIPLY or DIVIDE sites** once the paise→rupee `/100` conversions are excluded. Nine of those are the deliberately parity-pinned keystroke mirrors (`lib/money/gstLine.ts`, `lib/invoices/gst.ts`, `lib/money/decimalMath.ts`), which leaves **28 files to read**: `accounting/loans`, `trial-balance-import`, `billing`, `compliance/tds`, `fixed-assets`, `inventory`, `sales`, `tax/computation`, the year-end statements, the employee portal, `tds`, `time`, four purchase editors/modals, `drcr.tsx`, and eight `lib/` modules. A multiplication or a division is a RATE or a PROPORTION, which is the kind of figure a server owes; a sum is not. Triaging 28 files, and building an endpoint wherever one is owed, is a tranche of its own — not a loose end, and not something to claim either way from a grep |
| 4 | The filing simulation says plainly what it is (D17) | **passing** — one posture, one wording, pinned from the Python side |
| 5 | The demo firm has a full year of believable data | **passing** — Track 3, now including banking, fixed assets and payroll. It has not yet been SEEDED anywhere: `scripts/seed_demo_firm.py` is a dry run until `--confirm`, the target firm is yours to choose, and the deployment is not reachable from this container (the egress proxy answers 403 to CONNECT) |

---

## Track 5 — After the demo: the commercial track · 👤 O

GSP, ERI, NIC production credentials, and the Third Party Software Utility
registration. Months of lead time; the demo is what justifies starting them.
`docs/compliance/07-getting-permission-to-file.md` is the playbook.

---

## The standing lane — never blocks a track

| item | state |
|---|---|
| **Platform: Pages → Workers** (D26) | waiting on the owner. Removes the silent 100-rule cap |
| **Platform: Render free → paid** (~$7/mo) | waiting on the owner. The free tier sleeps; the ten-second cold start is what killed D25's figures, and it will be the first thing a CA notices in a demo |
| Three navigation cards tinted by state | **done 25 Sep** ✅ `/clients/{id}/compliance` painted GST green, TDS blue and MCA purple. Decoration — but in a product whose colour vocabulary IS state, it said the GST workspace was `ready` and the TDS one `working`. All three wear the navigation surface now, and the `color` field is gone rather than made uniform |
| Named-palette judgement pass | ongoing, one module per PR. **25 Sep: purchases 154→15, sales 100→11, compliance 145→39** — every one mapped by ROLE, and the residues NAMED in the code rather than flattened (a `text-blue-600` link, because 1.3d left those alone at 64 sites; a derived cost column the state set has no word for; a suggestion chip whose base is blue-50, for which mapping to `working-surface` would make it the same colour as its own hover; a `cancelled` badge that is neither `problem` nor `done`). **Next by count**: `components` 97, `memory` 96, `clients/[id]/accounting` 93, `clients/[id]/tax` 90 |
| ~~1,009 invisible dividers~~ | **done 25 Sep** ✅ Not the 95 this row claimed: 136 in the Tailwind families and **873 more written in the product's OWN surface tokens** (`border-ps-muted`, `divide-ps-bg`), which T3-a's pure hex→token rename had faithfully preserved. The guard states a CONTRAST against `ps.border`, read out of the token file, in both vocabularies — its first version knew one and was silently wrong about the other, over the larger population |
| The six documents (D18) | 2 of 8 fetched. Each is NAMED as a gap in the product, which is the safe direction |
| Findings status hygiene | `findings-status.json` is amended in the commit that closes a finding. The only rule that keeps it honest |

---

## Waiting on you — nothing else is

| | question | my recommendation |
|---|---|---|
| **A** | May the nightly sweep EMAIL a client's customers? | No — a Send button the CA presses |
| **C** | Cost centres on `journal_lines`? | Build it; it is a real dimension a practice asks for |
| **D26** | Pages → Workers? | Yes, before the next navigation work |
| — | Render paid tier before the demo? | Yes — the cold start is the first thing a CA sees |
| — | Documents #3–#9 | Whenever convenient; nothing is blocked *wrongly*, only *incompletely* |

---

## The numbers — run these any time

```sh
cd /path/to/caflow-ai

python3 -c "import json,collections; d=json.load(open('docs/audits/findings-status.json'))['findings']; print(collections.Counter(v['status'] for v in d.values()))"
ls apps/api/migrations/*.sql | sed 's/.*\///' | cut -d_ -f1 | sort -n | tail -1   # highest migration
find apps/web/app -name page.tsx | wc -l                                          # routes
md5sum apps/web/.smoke/*.jpg | awk '{print $1}' | sort -u | wc -l                  # distinct shots
find apps/web/app -name error.tsx | wc -l                                          # error boundaries
grep -rEoh 'text-\[[0-9]+px\]' apps/web/app apps/web/components | wc -l            # arbitrary font sizes
grep -v '^#' apps/web/public/_redirects | grep -c '200$'                           # HARD CAP 100

cd apps/api && python3 -c "from tests.test_every_mounted_endpoint_has_a_way_in \
  import _sources, _pattern, _routes; b=_sources(); \
  print(sum(1 for m,p in _routes() if _pattern(p).search(b)), 'of', len(_routes()))"
```

⚠️ **A metric and the guard that enforces it must count the same population.**
The hex grep above is coarse. When the two disagree, **the guard is the
authority and the metric is the thing to fix.**

---

## Explicitly not in scope

Real filing to any government portal (D17) · Account Aggregator bank feeds
(route 3 chosen, closed) · translating anything (D8) · a second filing demo ·
any screen that computes a statutory figure in the browser.

---

## When you ask "where are we?"

Run the block above. If a number here disagrees with it, **the command is right
and this file is stale** — tell me and I will fix the file in the same commit
as whatever I am working on. That rule is the only thing that keeps a plan
honest, and this repository has watched three separate status documents go
wrong for want of it.
