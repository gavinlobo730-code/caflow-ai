# THE PLAN

**The one plan. Everything else in `docs/plan/` is history.**

Written 16 September 2026. Supersedes `2026-09-12-compliance-and-craft.md` (stale
facts) and folds in `2026-09-16-the-redesign-plan-revised.md` (the measurements)
and `2026-09-13-questions-for-the-owner.md` (now answered).

---

## How to use this document

Every item has an **ID**, an **owner**, a **size**, a **status** and a
**DONE WHEN** that is objectively checkable — most of them by running one
command. Neither of us has to take the other's word for whether something is
finished.

**Status values**

| status | means |
|---|---|
| `TODO` | not started |
| `DOING` | in progress |
| `DONE` | its DONE WHEN check passes |
| `BLOCKED` | waiting on something named in the row |

**Owners**

| owner | who |
|---|---|
| 🔧 **C** | Claude. Needs nothing from you. |
| 👤 **O** | Owner. Only you can do it. |
| 🤝 **B** | Both, in a working session. |

**The rule that keeps this honest:** the status table below is updated in the
SAME commit as the work. A plan only ever updated by a planning session is
wrong by the time it is read — that is the lesson `docs/audits/findings-status.json`
exists to record, and it applies here.

---

## Status at a glance

_Last updated: 2026-09-16_

| track | what | owner | size | status |
|---|---|---|---|---|
| **T1** | Repair the safety net | 🔧 C | 4–6d | `DONE` — 7 of 7 |
| **T2** | A demo firm that exists | 🔧 C | 2–3d | `DOING` — T2-0 done |
| **T3** | Design system + 2 reference screens | 🔧 C | 11–13d | `DOING` — T3-a, T3-b, T3-f done; T3-c 4 of 6 (money cell, Dr/Cr, gap callout, period picker) 18 Sep |
| **T4** | Token adoption | 🔧 C | 5–8d | `DOING` — colour 10,146 → 116, type 2,265 → 405 |
| **T5** | Outputs — PDF + Excel | 🔧 C | 16–22d | `TODO` — unblocked 16 Sep |
| **T6** | Navigation + the hub | 🔧 C | 11–17d | `BLOCKED` on T4 |
| **T7** | Analytics & AI | 🔧 C | 3 layers | `BLOCKED` on T3 |
| **T8** | The portals | 🔧 C | 8–12d | `BLOCKED` on T4 |
| **T9** | Backend backlog (8 → 14 items) | 🔧 C | 14–17d | `TODO` — parallel, starts now |
| **D** | Owner decisions | 👤 O | — | 8 of 8 `DONE` |
| **F** | Documents to fetch | 👤 O | — | `TODO` |
| **V** | Pre-demo verification | 🤝 B | 1 session | `BLOCKED` on T8 |

**Honest total: 14–17 weeks** to the CA demo. Core build (through T6) is 10–12;
analytics layers 2–3 and the portals add 4–6.

---

## Decisions taken — locked, do not re-litigate

Answered by the owner on 16 September 2026, except where a row says otherwise.

| # | decision | answer |
|---|---|---|
| D1 | Hub tile set and order | **15 tiles**, below |
| D2 | The 39 screens in no menu | **Give them a home** |
| D3 | Portals in scope? | **In scope** — T8 |
| D4 | Density persistence | **Per device** (localStorage, no migration) |
| D5 | Money display | **2 decimals**, except return-prep screens → whole rupees |
| D6 | Rupee grouping | **Indian everywhere** (12,34,567 — never 1,234,567) |
| D7 | Demo on real or seeded data | **All data is demo today.** Seeded demo firm. |
| D8 | i18n | **Extract strings, translate nothing.** English only. |
| D9 | A PR that carries a migration | **Merge it like any other — no flag, no pause.** 17 Sep. |

**D9 — why this needed asking at all.** Merging to `main` runs
`apply pending migrations — production`, which applies every unapplied migration
to the live Supabase project with no review step in between
(`docs/deploy-migrations.md`). That is deliberate: it closed a gap where
migrations 233-241 sat committed and unapplied for up to six days while the code
that needed them was already live and failing silently behind broad
`try/except`. Nothing in `CLAUDE.md` or in any doc asks for migrations to be held
back — the only rule is the one above it, that CI must pass first, which the job
already enforces. I had been holding migration-carrying work for a confirmation
that was never asked for; D9 removes that. The job fails the push loudly on a bad
migration rather than corrupting data quietly, which is the same bargain
application code has always had here.

**D1 — the tile set:**

> Compliance Calendar · **Insights** · GST · Banking · Accounting · Sales ·
> Purchases · TDS · Payroll · Income Tax · Fixed Assets · Inventory ·
> Year-End · Reports · Documents

Insights is second because T7 makes it a first-class surface. Everything after
Payroll is periodic rather than daily.

**Earlier decisions that still stand:** light theme only (no dark mode), fluid
layout with a ~1600px cap, **data tables exempt from that cap**, prose and forms
keep a 65–75 character measure, 16px gutter floor, one PR per module, never
auto-submit to a government portal.

---

# T1 — Repair the safety net

**Owner 🔧 C · 4–6 days · BLOCKED T3, T5, T6 · status `DONE` (16 Sep)**

**Why first.** Track 1 of the old plan was built on 13 September and the
13 September note told you it was "finished and green". It is not. Two of its
four pieces observe nothing, and a redesign PR can merge today with both
required CI checks green and nothing having verified it. Measured:

- **148 of 159 smoke-walk screenshots are byte-identical** — the onboarding
  wizard. Zero product modules have ever rendered under the harness.
- **133 of 159 route pages (84%) can be deleted entirely** with the reachability
  guard reporting zero losses. ✅ **T1-b, 16 Sep: now 77.** The rest share every
  endpoint they call with a second screen, so deleting one orphans nothing —
  that residual is the smoke walk's job, not this guard's.
- **The required backend check reports green without running** on any
  `apps/web`-only PR — which is exactly what a module conversion is.
- **Zero `error.tsx` across 160 routes**, so "if something breaks it is one
  module" is false at runtime.

| ID | item | size | status | DONE WHEN |
|---|---|---|---|---|
| T1-a | Widen `backend-ci.yml` scope to `apps/web/`, or add a third job scoped to the two reachability tests. Make `frontend-ci` a required check. | 2h | `DONE` | A frontend-only PR shows the backend job **ran**, not "reported green without running" |
| T1-b | Attribute reachability to a calling file under `app/` or `components/`, not the `lib/` blob | 1d | `DONE` | `_sources()` counts a URL literal only where a screen can reach it. Endpoints reached falls 907 → **797**; the 110 between were named by nothing but an api-client method with no caller |
| T1-c | Seed the smoke walk's `users` read so `hasFirm` resolves true and screens actually render | 1h | `DONE` | `md5sum apps/web/.smoke/*.jpg \| awk '{print $1}' \| sort -u \| wc -l` ≥ 150 (was **11**, now 154) |
| T1-d | Triage every failure T1-c exposes | 2–3d | `DONE` | `pnpm smoke` exits 0 with all 159 routes rendering their own screen |
| T1-e | Per-route content assertion + fail the run if > 5 screenshots share an md5 | 1d | `DONE` | `pnpm smoke` exits 0 today; with the seeded rows removed — the harness exactly as it stood on 12 September — it exits 1 with **147 of 159** routes reporting, 143 of them "landed on /onboarding". That run exited **0**. |
| T1-f | Add `error.tsx` to every module route | 0.5d | `DONE` | `find apps/web/app -name error.tsx \| wc -l` ≥ 14 (was **0**, now 65) |
| T1-g | Refresh both snapshots at HEAD in a reviewed commit | 0.5h | `DONE` | Unprotected endpoints **0** (was 128); screen snapshot **159 → 160**. The 160th was `/settings/multi-currency`, and it crashed the first time anything visited it — see below. |

**Risk that materialised, twice.** Each fix in this track exposed the next
defect, which is what a safety net is for:

- T1-c seeded the `users` row; **13 screens crashed** the first time anything
  could see them.
- T1-e's landing check found the product's **front door** bouncing to the
  onboarding wizard — `DashboardContent` reads `firms.name` and the stub
  answered null — so the dashboard had never rendered under the harness either.
- T1-g refreshed the screen snapshot from 159 to 160, and the screen nobody had
  ever walked, `/settings/multi-currency`, **threw on mount**: `data` came back
  `[]`, `[] ?? null` is `[]`, and `firmGates?.platform.on` read `.on` off
  undefined. Its error boundary (T1-f) contained it, which is the first time
  that has been observed working.

All three are fixed. `pnpm smoke` walks 160 routes and exits 0.

---

# T2 — A demo firm that exists

**Owner 🔧 C · 2–3 days · parallel with T1 · status `TODO`**

`apps/api/seed/seed_data.py` — 164 lines, a full demo firm, five users, twenty
named clients — has **zero importers**. No demo mode, no reset path. The only
way into the product is a 940-line three-step OTP-gated onboarding wizard.

**"valid PANs and GSTINs" was wrong, and it is measured now.** Checked against
`domain/gst/gstin.checksum_char` on 16 Sep: **17 of the 20 client GSTINs carry
the wrong check digit, and so does the firm's own.** That is not cosmetic —
GST-29 made the check enforced at every door a human types one, `POST
/api/onboarding/firm` refuses a firm GSTIN that fails it, and the GSTR-1 build
refuses the client's own. Seeded as they stand, the demo could not file. The
first 14 characters are fine; only the last needs recomputing, and it must be
COMPUTED rather than typed.

This is why T1-c is needed at all (nothing to seed → stub everything empty →
land on the wizard) **and** it is on the critical path for the CA demo.

D7 makes this safe: every byte in the platform today is demo data, so I can
wipe and re-seed freely.

| ID | item | size | DONE WHEN |
|---|---|---|---|
| T2-a | Make `seed_data.py` runnable — one command, idempotent, with a reset | 1d | One command creates the firm; running it twice is a no-op |
| T2-0 | Correct the 18 GSTINs, computing each check digit | 1h | `DONE` 16 Sep — `tests/test_the_demo_firm_can_be_created_at_all.py`, 64 tests; 18 fail against the uncorrected data. Three further copies of one of them were found in `mock_data.py` and the document-intelligence specimens, and corrected too. |
| T2-b | Extend to a **full financial year** of transactions across every module — sales, purchases, bank, payroll, GST returns, TDS, fixed assets, inventory | 1–2d | Every one of the 15 tiles has real figures on it; no screen shows an empty state |

**Deliberately included:** at least one client with a locked period, one with a
filed return, one with a statutory gap. A demo where nothing is ever refused
teaches a CA the wrong thing about the product.

**Two facts settled on 16 Sep that decide HOW T2-a is built, recorded so the
build does not re-derive them:**

1. **Creating a firm is four steps, not one insert.** `routers/onboarding.py`
   does `firms` → `users` → `coa_seed_service.seed_firm_coa(firm_id)` →
   `internal_client_service.provision(...)`. The chart of accounts is
   FIRM-level (migration 057: one master chart, `client_id IS NULL`), and
   `STANDARD_COA` is its one authority. A seeder that writes accounts of its
   own would be a second one — so the seeder must either call that service or
   GENERATE its rows from `STANDARD_COA`, never restate them.

2. **Mock mode cannot verify a seeder, and that is by design.**
   `seed_firm_coa` short-circuits to `{"skipped": True, "mock": True}` when
   `SUPABASE_URL` is unset, because mock mode is an in-memory double for the
   test suite rather than a database. So "running it twice is a no-op" is
   checkable only against real Postgres. The practical shape is therefore a
   Python generator that emits SQL from the existing Python authorities and
   applies it with `psql --dsn`, the way `scripts/db/apply_migrations.py`
   already does — verifiable against a local cluster, and runnable against the
   Supabase DSN when the owner chooses.

**⚠️ A seeded user cannot sign in.** `users.auth_user_id` references a Supabase
auth identity, and the seeder must not mint one — that is credential creation.
So either the owner passes the auth id of an account they have already signed
up with, or the rows exist and nobody can log in. Whichever is chosen, the
seeder must SAY which, not leave it to be discovered.

---

# T3 — Design system + two reference screens

**Owner 🔧 C · 11–13 days · BLOCKED on T1 · status `TODO`**

The old plan budgeted one week to "define tokens". **The tokens are already
defined and nothing uses them** — `tailwind.config.ts` has carried brand, gold
and `ps.*` scales all along, and `grep -rl 'bg-brand|text-brand|bg-ps-'` over
`app/` and `components/` returns **zero files**. Against that: **10,828 raw hex
literals across 66 values in 259 files**. About 0.2% of colour decisions go
through the token layer.

So T3 is replace-and-migrate, not define.

| ID | item | size | DONE WHEN |
|---|---|---|---|
| T3-a | ✅ **18 Sep.** Type scale reaches 10px (`text-3xs`) and 11px (`text-2xs`), bare. `darkMode` deleted. Dead gone: 2 colour tokens, 3 box shadows, **17 `:root` variables**, 9 CSS classes. **10,146 → 116 raw hex classes.** Spacing/radius/elevation deliberately NOT invented — see below. | 2.5d | ✅ done |
| T3-b | ✅ **18 Sep.** FIVE built, not eight: `components/ui/field.tsx` (Input, Select, Textarea, Label, **Field** — the aria wiring, since `aria-describedby` appeared ONCE in the tree against 927 `<label>`) and `components/ui/callout.tsx` (Callout + GapList, four tones). **Table and Pagination already exist** as `DataTable` — the 242 raw `<table>` are adoption, not a missing primitive — and **Tooltip is deferred**: 292 sites use native `title=`, and a custom one is a behaviour decision for the reference screens. Both adopted on the screens that argued for them. | 3d | ✅ done |
| T3-c | The 6 product-specific components | 3.5d | 4 of 6 done — below |
| T3-d | Reference screen 1 — **periodic Trial Balance** | 1.5d | Renders full-width; 9 Dr/Cr columns; owner approves |
| T3-e | Reference screen 2 — **Banking Entries** | 1.5d | Density proven; its guard rewritten to name components, not class strings |
| T3-f | ✅ **18 Sep.** `ps.hint` was **2.56:1** — the most-used colour in the product. `label` #64748B→#475569, `hint` #94A3B8→#64748B. Guarded, reading the config. | in T3-a | ✅ every ink token ≥ 4.5:1 on white and on `ps.bg` |

**T3-c, the six components:**

| component | why it is not generic | today |
|---|---|---|
| **Money cell** | ✅ **18 Sep** — `lib/money/format.ts`. Re-measured: **248 formatters, 26 behaviours**, not 53/11. **139 had no `en-IN` locale at all**, ~150 were null-unsafe, the shared one rendered `undefined` as "₹NaN" and `null` as "₹0.00", and the whole-rupee one ROUNDED — a second CGST §170. Four Intl construction sites became two, both inside the authority | ~~53 / 11~~ **done** |
| **Dr/Cr pair** | ✅ **18 Sep** — `components/ui/drcr.tsx`. The finding was not the duplication: two of the three sites read `p >= 0 ? "Dr" : "Cr"`, so a customer who had **settled every invoice** was emailed a statement reading **"₹0.00 Dr"**, and the same `>= 0` coloured it blue. A nil balance is on neither side; `sideOf` is a tri-state | ~~4 sites~~ **done** |
| **Statutory-gap callout** | ✅ **18 Sep** — `GapList` existed and accepted ONE of the three shapes the backend emits, which is why 48 sites hand-rolled it. Widened, plus `StatutoryNotes` for the gap/caveat pair. The real defect: a GAP wore **11 distinct inks** and a CAVEAT **7**, with **5 used for both** — `RcmDocumentPanel` rendered the two in a *byte-identical* class string | ~~48 sites~~ **18 + 12**, ratcheted |
| **Refusal banner** | `ErrorState`/`AsyncBoundary` already exist and are right | 198 inline sites in 125 files — adoption, not design |
| **Period picker** | ✅ **18 Sep** — `components/ui/period.tsx`, on T3-b's `Select`. **25** selects in 24 files, **14 class strings, 4 focus treatments**. Every option now carries `FY` or `AY`: IT Act §2(9) with §3 makes AY 2026-27 the same period as FY 2025-26, and the filing screen shows both dropdowns together. Month/quarter/range NOT built — no screen asks for one. **Still per-page** | ~~20 sites~~ **done** |
| **Working panel** | "what this figure is made of" — the vehicle for T7 | 7 unrelated panels inside 2,000–4,800-line pages |

**Why two reference screens.** Banking Entries cannot prove the width rule —
it is already full-bleed (`px-6`, no max-width) and has 6 columns against 12 on
the invoice editor. The Trial Balance is 9 Dr/Cr columns inside `max-w-4xl`
(896px), which is exactly where the rule bites.

**What T3-a actually found, and what it deliberately did NOT do.** The plan
budgeted "rewrite the token file" and the file turned out to hold most of the
right answer already; what it lacked was reach and two correct values.

- **Seven greys for four roles.** `ink` is written `#0F172A` (801) and
  `#1E293B` (333) as well as the token's own `#0D1635` (13); `label` is written
  `#64748B` (1,388) *and* `#475569` (894) — and the token held the LIGHTER of
  each pair. `ps.hint` at `#94A3B8` is the single most-used colour in the
  product, 1,567 sites, most of them at 10px or 11px, rendering at **2.56:1**.
- **The dominant hover pair was not the one the file described.** Its comment
  said "104 sites darkening hint→label"; the measured pair is
  `#94A3B8 → #475569` (95 sites), which was hint → *two steps down*. After the
  fix it is hint → label with the target unchanged.
- **Spacing, radius and elevation are NOT in this commit.** `shadow-card`,
  `shadow-card-hover` and `shadow-modal` were declared and used zero times —
  declaring a replacement scale before the reference screens exist just
  re-creates what was deleted. They come with T3-d/T3-e, against a real card.
- **The line-height on the two new type steps is deliberately absent.** Pinning
  one changes the rendering of any of the 1,860 sites nested inside a
  `text-sm`, so the T4 rename would not be a rename. It is a real question and
  it belongs where it can be looked at.
- **Still open, and visible:** ~40 sites on the rival indigo primary
  (`#4338CA`, `#6366F1`, `#3730A3`) that the token file's own comment already
  names. Folding them into `brand` changes what the banking screens look like,
  so it goes with the reference screens.

**⚠️ T3-c's money cell changes visible figures, and the two that shipped on 18
Sep are named.** `/clients/[id]/tax/26as` and `/clients/[id]/tax/computation`
each carried a `paise()` helper at `maximumFractionDigits: 0`, so they ROUNDED.
They now show the paise on any figure the server has not rounded — which is
most of them — because a browser-side round is a second implementation of CGST
§170 and disagrees with it at exactly ₹x.50. More information rather than less,
and a visible change: ₹1,23,457 becomes ₹1,23,456.50.

The remaining screens move with T4's adoption pass, one at a time, because 103
of the sites that divide by 100 are CSV cells and `<input value>` strings that
must NOT carry a ₹ or a comma — the one rule a naive sweep would get wrong.

---

# T4 — Token adoption

**Owner 🔧 C · 5–8 days · BLOCKED on T3 · status `TODO`**

**The work no track in the old plan owned.** Track 2 was scoped as "the
vocabulary, not the redesign"; Track 4 as navigation. Neither budgeted 10,828
replacement sites, and the work does not vanish.

| ID | item | size | DONE WHEN |
|---|---|---|---|
| T4-a | Codemod the 66 hex values | 2d | Zero `#RRGGBB` literals in `app/` and `components/` |
| T4-b | Judgement pass over 8,234 Tailwind named-colour utilities | 3–4d | `amber`/`red` resolve to semantic status tokens, not raw colours |
| T4-c | Type-size codemod over 13 arbitrary px values (2,171 uses) | 1d | Every size on the scale |
| T4-d | Width sweep over the 95 pages that centre their own container | 1d | Tables full-width; prose keeps its measure |

**Must land before the second module in T6**, or module two re-litigates
module one.

**⚠️ No blanket codemod on the named colours.** `text-amber-600` on a statutory
gap and on a decorative icon are the same string with different meanings.

---

# T5 — Outputs: PDF and Excel

**Owner 🔧 C · 16–22 days · BLOCKED on T1 · parallel with T3/T4 · status `TODO`**

## T5a — PDF (6–9 days)

Six services produce **nine documents**, and one of the six is `xhtml2pdf`, not
reportlab — so "one shared style module over six services" cannot span it
as written.

| ID | item | DONE WHEN |
|---|---|---|
| T5a-1 | Write the shared style module. **Name it with "pdf" in it** so `test_no_pdf_renders_the_rupee_sign.py`'s glob catches it. | Exists with tests |
| T5a-2 | Convert the five reportlab services (~1,240 lines of render body) | 32 test modules still pass; 8 use pdfplumber so each failure is **read**, not re-baselined |
| T5a-3 | **Merge SALES-13 in** — `invoice_templates` read on day one, not retrofitted | A configured branding value appears in the output, asserted by a test |
| T5a-4 | Page numbers on all nine (**currently zero**) + `repeatRows` on the 18 tables lacking it | A 40-line invoice keeps its headers on page 2 |
| T5a-5 | Embed a Unicode font so ₹ prints instead of "Rs." | Invert `test_no_pdf_renders_the_rupee_sign.py` — rewrite it, do not delete it |
| T5a-6 | **Indian rupee grouping (D6)** — one formatter replacing three | Invoice prints 12,34,567 |
| T5a-7 | **IST on the year-end pack** — `datetime.now()` at two sites, no TZ set | A pack generated 01:00 IST on 1 April is dated 1 April, not 31 March |
| T5a-8 | The year-end pack says **"PracticeSync AI"** where the firm's name belongs | The practice's name is on the document a CA signs |

**T5a-6 and T5a-7 are live correctness bugs, not styling.** They can ship
before the rest of T5a.

**⚠️ Do NOT put firm branding on the sales invoice, payslip or statement.**
Three separately-fixed bugs are pinned by tests and written into the code as
refusals — those documents belong to the *client*, not the practice.

## T5b — Excel (10–13 days)

| ID | item | DONE WHEN |
|---|---|---|
| T5b-1 | One shared workbook module in `apps/api` — header style, Indian number format, column widths, freeze panes, cover sheet, totals, print area | Exists with tests. **Copy `services/time_export_service.py`** — openpyxl is already deployed and working |
| T5b-2 | **Money becomes a NUMBER, not text** | `=SUM(B:B)` on an exported trial balance returns the total, not **0** |
| T5b-3 | 11 export actions become FastAPI endpoints | Each has a `reachable_endpoints.json` entry |
| T5b-4 | `shareToPortal` — decide whether the server uploads | Today it writes to storage from the browser so `rbac()` never runs |
| T5b-5 | CSV: 43 of 64 controls share two helpers | One change reaches 43 |

**⚠️ Do not remove `xlsx` from `package.json`** — it is the .xlsx import parser
on 17 screens. Only the write side moves.

**The real defect the old plan missed:** every money cell in every browser
export is a **text** cell, and SheetJS suppresses Excel's warning triangle. A
CA who types `=SUM()` on your trial balance gets 0 with nothing explaining why.
That is a correctness defect on an output that leaves the building.

---

# T6 — Navigation and the hub

**Owner 🔧 C · 11–17 days · BLOCKED on T4 · status `TODO`**

| ID | item | size | DONE WHEN |
|---|---|---|---|
| T6-a | Reclaim redirect headroom **before anything else** | 0.5d | `grep -v '^#' apps/web/public/_redirects \| grep -c '200$'` ≤ 90 (is **98**) |
| T6-b | Build the hub — firm level and client level | 3–4d | The 15 tiles of D1, each with live signal |
| T6-c | Persistent client switcher | 1–2d | Move client→client without returning to the hub |
| T6-d | Re-point ⌘K at navigation | 1d | Already bound globally; today it opens an entity search |
| T6-e | **Give the 39 orphan screens a home (D2)** | 1–2d | Every route reachable from the hub or a tile's sub-list |
| T6-f | Retire `ActivityRail` + `ContextPanel` + the client sidebar | 3–4d | 2,675 lines across two shells that share nothing. All three `window.location` static-export workarounds survive |
| T6-g | Per-module conversion, one PR each | 5–8d | Smoke walk green per module; guard edits budgeted at 0.5–1d per module |
| T6-h | Fix the two stacked mobile hamburgers | 0.5d | One drawer, reachable |
| T6-i | Close PAY-28 (`deferred_to_the_redesign`) | in T6-g | Payroll's three top-level areas resolved |

**⚠️ T6-a is a silent cliff.** Cloudflare ignores `_redirects` rules past
position 100 — no build error, no test, no log. It 404'd the entire client
workspace once already. Each new page under a dynamic segment costs 2 rules.
**Prefer a query-param workspace over new routes**, the way the year-end
workspace already does.

---

# T7 — Analytics and AI

**Owner 🔧 C · three layers · BLOCKED on T3 · status `TODO`**

**The finding.** You already own more analysis than the product shows, and the
AI a CA can see is the weakest AI you have.

- `/ai-assistant` → `POST /api/assistant` is a **pure Groq passthrough over a
  static prompt that loads no client data at all.** Its own code comment says
  so. That is a generic tax chatbot.
- `GET /api/accounting/statement-analysis` — an LLM narrating ratios computed
  from the reporting engine's own paise, with a deterministic fallback — has
  **0 screen callers**. The best AI feature here is unreachable.
- `GET /api/analytics/profitability` — **client profitability, already built**,
  revenue minus cost in integer paise, by client/engagement/team — **0 screen
  callers**.
- The modules named "intelligence" and "memory" analyse **tasks, not money**.
  `cash_flow_risk_months` is literally the two months with the most tasks:
  `# Cash flow risk: months with highest task load typically correlate with pressure`
- **~40 finished analytical endpoints have no screen** — all of
  `/api/analytics`, `/api/intelligence`, `/api/risks`, 8 of 13 health, 8 of 17
  copilot, 6 of 6 ai-insights.

## The rule, adopted now

> **The LLM narrates figures the product computed. It never computes them.**

Already the pattern in `statement-analysis`: deterministic ratios → LLM
narration → deterministic fallback. A CA who catches the AI inventing a number
stops trusting the software entirely. This becomes a guard test.

## T7-L1 — Surface what exists · rides along with T6 · 8–12d standalone

No new engines. Screens for what is already computed and tested.

| ID | item | DONE WHEN |
|---|---|---|
| T7-L1-a | The **Insights** tile (D1) — health, risk, profitability, trends in one place | The tile is not a stub |
| T7-L1-b | Client profitability + realization | `/api/analytics/profitability` and `/revenue-vs-effort` have screen callers |
| T7-L1-c | Statement analysis | `/api/accounting/statement-analysis` has a screen caller |
| T7-L1-d | Health: render the **computed** 7-dimension score | 8 unreached health endpoints reached; screens stop rebuilding scores from raw rows |
| T7-L1-e | Compliance risk + predicted misses | `/api/intelligence/*` reached |
| T7-L1-f | Risk dashboard — delete the browser-side rival model | `/api/risks/*` reached; `app/risks/page.tsx` stops rebuilding its own |
| T7-L1-g | `ai_insights` — wire the **writer** | Today a screen reads a table nothing reachable populates |

**DONE WHEN (whole layer):** zero analytical endpoints unreached by a screen,
asserted by T1-b's repaired guard.

## T7-L2 — Repoint the intelligence at the ledger · 6–10d

The engines exist; they read the wrong table.

| ID | item | DONE WHEN |
|---|---|---|
| T7-L2-a | Anomaly detection over `account_period_balances` — round numbers, period-end spikes, unusual account pairings, duplicate payments | "Anomaly" means a ledger anomaly, not task-volume sigma |
| T7-L2-b | **Real cash-flow forecasting** from invoice/bill due dates, ageing and bank history | A forward-looking engine exists. There is **none** today — the only "forecast" is 353 lines of browser arithmetic with a user-typed opening balance |
| T7-L2-c | Rewrite or retire `cash_flow_risk_months` and `seasonal_revenue_peak` | No financial-sounding figure is derived from task counts |
| T7-L2-d | Firm-wide capacity risk — deadline concentration vs team capacity | *Which March are you about to fail?* |

## T7-L3 — The differentiators · 10–15d

None of this exists.

| ID | item | why it matters |
|---|---|---|
| T7-L3-a | Effective tax rate trend across years | Snapshots are stored and never compared |
| T7-L3-b | ITC leakage as a trend | Reversals computed per return, never totalled for the year |
| T7-L3-c | Vendor and customer concentration | No top-N share, no year-on-year shift |
| T7-L3-d | GST/TDS/payroll trend analysis | All per-period today |
| T7-L3-e | **Cross-client benchmarking** | *"Your client vs the other 40 in this sector."* Needs a book of clients on one platform — **nobody else can copy this** |

---

# T8 — The portals

**Owner 🔧 C · 8–12 days · BLOCKED on T4 · status `TODO`** — in scope per D3

Six routes, 1,713 lines under `apps/web/app/portal/`, rendered outside the
staff shell. They import almost none of the shared primitives, so T3 and T6
reach none of them.

**This is the only surface the CA's own client and employees see.** If it keeps
today's look, the product visibly has two designs and the outside world sees
the old one.

| ID | item | DONE WHEN |
|---|---|---|
| T8-a | Client portal on the design system | Uses T3 primitives |
| T8-b | Employee portal on the design system | Same |
| T8-c | `apps/marketing` brand parity | A **parity test written from `apps/web`'s side** — today it is a hand-copy maintained by a comment, the exact drift shape CLAUDE.md warns about three times |
| T8-d | The portal dashboard drops 3 of 7 sections the API serves | All served sections render or are deliberately excluded |

---

# T9 — Backend backlog

**Owner 🔧 C · 14–17 days · parallel, starts now · status `TODO`**

**Exactly 8 of the 35 remaining findings can run alongside the redesign.** The
other 27 either need a screen (17) or are blocked on a document (10).

`PAY-21` · `BANK-10` · `GST-19` · `INV-09` · `IT-09` · `PUR-07` · `SALES-13` ·
`SALES-15`

Two worth splitting rather than treating whole:

- **ACC-22** — land the backend half now (carry `source_type`/`source_id`
  through the reporting model and `account_ledger_page`) so T6's redesigned
  ledger table has something to click. Do not build the click twice.
- **IT-20** — its statutory branch is blocked; its surfacing branch is one hour
  during any screen pass.

**⚠️ Expect this to grow.** The 16 September re-read found 16% of "closed"
findings not closed. The 106 verified on earlier dates have not been re-read.
Budget 35–45, not 35.

---

# D / F / V — the owner's tracks

## D — Decisions · 8 of 8 `DONE` ✅

## F — Documents to fetch · 👤 O · `TODO`

Each needs a person to read a document. None can be derived, and writing any
from memory puts a wrong number in somebody's pay or return.

| ID | what | unblocks |
|---|---|---|
| F-1 | **§194I(a) and §194J(a) rates** off the Finance Act | **Two numbers close TDS-22 entirely.** Both limbs exist and withhold at the higher rate today |
| F-2 | §47 GST late-fee rates | `LATE_FEE_RATES` is deliberately empty |
| F-3 | §50(3) notified rate — 18% or 24% | A third of the charge separates the readings |
| F-4 | PT slabs for any state your testers are in | 4 of 22 states modelled |
| F-5 | §288A/§288B — nearest ₹10 or ₹1 on the ITR payload | Found 16 Sep; not modelled |

## V — Pre-demo verification · 🤝 B · `BLOCKED` on T8

### My gates — refuse to start the session until all five pass

| ID | gate | your one-command check |
|---|---|---|
| V-1 | Smoke walk renders the product | `md5sum apps/web/.smoke/*.jpg \| awk '{print $1}' \| sort -u \| wc -l` ≥ 150 |
| V-2 | Required checks actually run on a web-only PR | Open one and read the job log |
| V-3 | Reachability attributed to screens | `pytest tests/test_reachability_is_attributed_to_a_screen.py` passes |
| V-4 | A demo firm exists | One command builds it |
| V-5 | Error boundaries | `find apps/web/app -name error.tsx \| wc -l` ≥ 14 |

### The session itself

| ID | item |
|---|---|
| V-6 | **Six spot-checks** — one GSTR-1, GSTR-3B, 26Q, payslip, trial balance, balance sheet against figures you trust. Not because the engines are unverified, but so you can tell a CA you checked it yourself |
| V-7 | **Print four documents on paper** — invoice, payslip, year-end pack, statement |
| V-8 | Review the two reference screens and the hub |
| V-9 | **Walk the first-hour gaps and decide what you are content to show** — payroll gaps in 18 of 22 PT states, §89 arrears before FY 2025-26, "cannot file" |
| V-10 | Agree the sentence for *"can I use this tomorrow?"* — honestly no, because filing needs GSP and ERI registrations |

---

## Sequencing

```
now ──┬── T1  safety net (4-6d) ──┬── T3 design system (11-13d) ── T4 tokens (5-8d) ──┬── T6 nav (11-17d) ──┬── T8 portals (8-12d) ── V session ── CA DEMO
      │                           │                                                   │                     │
      ├── T2  demo firm (2-3d) ───┘                                                   ├── T7-L1 (rides T6)  ├── T7-L2 (6-10d)
      │                                                                                │                     │
      ├── T5  outputs (16-22d) ───────────────────────────────────────────────────────┘                     └── T7-L3 (10-15d)
      │
      └── T9  backend backlog (14-17d, continuous)
```

**Critical path:** T1 → T3 → T4 → T6 → T8 → V ≈ **10–12 weeks**.
T7-L2 and T7-L3 add 4–6 more and can land after the demo.

---

## Explicitly not in scope

Recorded so nobody half-starts them.

- **Filing to government portals.** Needs GSP and ERI registrations — months of
  commercial work. See `docs/compliance/07-getting-permission-to-file.md`.
- **Account Aggregator bank feeds.** Closed: no purpose code fits an agent
  keeping the customer's books.
- **Translations.** D8 — extract strings, translate nothing.
- **Dark mode.** Not built, and one inert config line to delete.
- **A second filing demo, a second reconciliation screen, a second cost
  formula.** This codebase has found each of those once already.

---

## The numbers, today — run these any time

Copy-paste. Every one is a real baseline taken 16 September 2026, so progress
is visible without asking me.

```sh
cd /path/to/caflow-ai

# T1-c/V-1  distinct smoke screenshots            now 11      target >=150
md5sum apps/web/.smoke/*.jpg | awk '{print $1}' | sort -u | wc -l

# T1-b/V-3  endpoints a screen can actually reach    now 797    was 907
cd apps/api && python3 -c "from tests.test_every_mounted_endpoint_has_a_way_in \
  import _sources, _pattern, _routes; b = _sources(); \
  print(sum(1 for m, p in _routes() if _pattern(p).search(b)))"

# T1-f/V-5  error boundaries                      now 0       target >=14
find apps/web/app -name error.tsx | wc -l

# T6-a      Cloudflare redirect rules             now 98      target <=90  (cap 100)
grep -v '^#' apps/web/public/_redirects | grep -c '200$'

# T3-a/T4-a hardcoded hex colours                 now    116  target 0  (was 10,146)

# T4-a  arbitrary font sizes                       now    405  target ~130 (was 2,265)
grep -rEoh 'text-\[[0-9]+px\]' apps/web/app apps/web/components apps/web/lib | wc -l
grep -rEoh '#[0-9a-fA-F]{6}' apps/web/app apps/web/components | wc -l

# T5b       browser-side Excel writers            now 7       target 0
grep -rl 'XLSX.write' apps/web/app apps/web/components | wc -l

# T9        backlog: open + partial               now 49      target <=10 (rest blocked)
python3 -c "import json,collections; d=json.load(open('docs/audits/findings-status.json')); \
c=collections.Counter(v['status'] for v in d['findings'].values()); print(c['open']+c['partial'])"
```

| check | 16 Sep 2026 | target | track |
|---|---|---|---|
| distinct smoke screenshots | ~~11~~ **154** of 160 | ≥ 150 | ✅ T1-c |
| distinct rendered bodies | ~~11~~ **150** of 154 that stay put | largest group ≤ 5 | ✅ T1-e |
| routes landing on someone else's screen | ~~143~~ **0** unpinned | 0 | ✅ T1-e |
| error boundaries | ~~0~~ **65** | ≥ 14 | ✅ T1-f |
| endpoints reached by an uncalled api-client method | ~~110~~ **0** of 797 | 0 | ✅ T1-b |
| screens deletable in silence | ~~133~~ **77** of 159 | see note | T1-b done, rest → T1-e |
| redirect rules used | **98** of 100 | ≤ 90 | T6-a |
| hardcoded hex colours | ~~10,850~~ **116** | 0 | ✅ T3-a / T4-a |
| money formatters | ~~53~~ **257** (re-measured) | 1 | T3-c done · adoption is T4 |
| browser Excel writers | **7** | 0 | T5b |
| analytical endpoints with no screen | **~40** | 0 | T7-L1 |
| backlog open + partial | ~~35~~ **49** | ≤ 10 | T9 |

---

## When you ask "where are we?"

Read the status table at the top. If an item says `DONE`, run its DONE WHEN
check — you should never have to take my word for it. If the table and the code
disagree, **the code wins and the table gets fixed.**
