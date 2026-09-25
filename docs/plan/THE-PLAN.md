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
| Audit findings closed | **265 of 279** | 265 | `docs/audits/findings-status.json` |
| — partial | 6 | 6 | ACC-13, FA-11, IT-11, PAY-27, SALES-23, TDS-22 |
| — open | 2 | 2 | TDS-16, GST-25 — both blocked on a document |
| — deferred to the redesign | 1 | 1 | **PAY-28 — the redesign is now done, so this needs re-reading** |
| Migrations | **416** | 412 | `ls apps/api/migrations/ \| tail -1` |
| Backend tests | **17,263 pass**, 1,623 skip | ~17,200 | `pytest tests/` |
| Frontend guards | **1,644 pass** | 1,638 | `pnpm test` |
| Routes in the app | **166** | 161 | `find apps/web/app -name page.tsx \| wc -l` |
| Endpoints a screen can reach | **856 of 1,069** | 829 of 1,064 | the reachability ratchet |
| Distinct smoke screenshots | **163** | 154 | target ≥150 ✅ |
| Error boundaries | **65** | 65 | target ≥14 ✅ |
| **Arbitrary font sizes** | **0** | 379 | **target 0 — D12 is COMPLETE** ✅ |
| Hardcoded hex (coarse) | 70 | 70 | the guard is the authority, not this grep |
| Cloudflare redirect rules | **98** | 98 | **HARD CAP 100, fails silently** |

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
| 1A-1 | **Related parties / AS 18** | **in flight** | `GET /related-party-report` had zero callers and dropped a Karta, a Proprietor and a Beneficiary from a statutory note in silence. `domain/related_party/disclosure.py` + `services/related_party_service.py` + a client tab that lists roles, picks an entity and renders the note with its gaps. Transactions matched on PAN against the customer and vendor masters. 30 tests green |
| 1A-2 | **Sweep for the rest of the class** | not started | A guard, not a list: every FastAPI route whose response is a computed REPORT must have a caller, or an exemption naming why. The reachability ratchet counts endpoints; this counts *outputs nobody can see* |
| 1A-3 | Re-read **PAY-28** | not started | Marked `deferred_to_the_redesign`. The redesign is done, so it is either closed or it is real |

### §B — analytics with no screen (was Phase 3b / 3c)

| ID | item | state |
|---|---|---|
| 3b-1 | Ledger anomaly detection over `account_period_balances` | not started |
| 3b-4 | Firm-wide capacity risk | not started — premise measured: `/api/workload/capacity` is fully reached and `workload-insights` describes the current state, so this is a genuine build |
| 3b-5 | Surface `workload-insights` | not started — small; drops `/api/intelligence` unreached from 3 → 2 |
| 3c-1..5 | Effective tax rate trend · ITC leakage trend · concentration · GST/TDS/payroll trends · **cross-client benchmarking** | not started. 3c-5 is the one nobody else in this market can copy |

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
| 2.1 | Client portal on the design system | uses the shared primitives |
| 2.2 | Employee portal on the design system | same |
| 2.3 | `apps/marketing` brand parity | **done 24 Sep** ✅ |
| 2.4 | The portal dashboard drops 3 of 7 sections the API serves | all render, or are excluded and say why |

---

## Track 3 — The demo firm · 🔧 C · 2–3 days

Seeded (D7). Nothing to show today: 7 clients, 2 bank accounts, most tables
empty. The demo is what Track 4 judges and what justifies Track 5.

---

## Track 4 — Verification, with you · 🤝 · one session

### My gates — I do not book the session until all five pass

1. Every track above closed or explicitly deferred by you
2. Backend and frontend suites green, smoke walk renders every route
3. No screen renders a figure the server did not compute
4. The filing simulation says plainly what it is (D17)
5. The demo firm has a full year of believable data

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
| Named-palette judgement pass | ongoing, one module per PR. Next by count: `clients/[id]/accounting` 99, `memory` 96, `health/[client_id]` 84, `payroll/reports` 79 |
| 95 `border-gray-50` card dividers (1.05:1) | not started. Not a WCAG fix — `ps.border` is 1.23:1 |
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
