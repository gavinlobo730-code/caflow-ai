# Overnight run — 24 September 2026

Written at 04:31 IST at the start of an unattended run, from the code rather
than from any status table. Tick each item as it lands, with its evidence.

**Read this before adding to it.** THE-PLAN.md's own markers have been wrong in
both directions this month — PR #568 existed to correct exactly that — so every
state below was established by grep, by reading the file, or by running the
guard, and each row says which.

---

## A correction, made before any work started

The 19 September checkpoint recorded **"hardcoded hex literals 116 → 170, T4-a's
own metric going backwards"**. That is wrong, and it matters because it would
have sent this run hunting a regression that never happened.

The plan's metric command is a coarse grep:

```
grep -rEoh '#[0-9a-fA-F]{6}' apps/web/app apps/web/components | wc -l   # 170
```

The **guard** — `apps/web/scripts/a-colour-and-a-type-size-come-from-the-token-file.test.ts`
— deliberately counts three different populations, and the coarse grep is their
sum plus comments plus an allowlist:

| population | now | budget | what it is |
|---|---|---|---|
| hex in a Tailwind arbitrary class — `border-[#E2E8F0]` | **98** | 98 | always a class; always has a token |
| bare hex outside a class — `style={{}}`, an SVG attr, a prop default | **46** | 46 | same literal, same drift, no token existed to use |
| arbitrary font size — `text-[13px]` | **392** | 405 | |

All eight guard assertions pass on `352dec8c`. Nothing regressed. **Both hex
budgets sit exactly at their ceiling**, so any new colour written today fails
CI — which is the ratchet working, not a problem.

The checkpoint is corrected in the same commit as this file.

---

## The decision that unblocks the bare-hex half

The guard's own note says a bare hex was left uncounted because a chart colour,
an SVG attribute and an inline style "are not classes and have no token to
use". That is the whole defect: `tailwind.config.ts` is a *Tailwind* config, so
its values reach a class and nothing else. Three screens thread colour through
`style={{}}` and prop defaults and had literally nothing to reach for.

**`apps/web/lib/design/tokens.ts` is the answer, and it is `services/pdf_style.py`'s
shape exactly** — one module, values mapped BY ROLE, each carrying the name of
the Tailwind token it came from so a guard can pin the two together. The PDF
pass proved the shape on six documents that had picked four different header
fills; this is the same fix on the browser side of the same palette.

### Decisions taken tonight, defaults recorded rather than waited on

| § | question | decision | why it is not a coin-toss |
|---|---|---|---|
| **G** | the rival indigo, 55 sites | **indigo loses; `brand` navy wins** | `tailwind.config.ts` already names the problem in its own comment — *"there was no single primary, so three were in use at once — brand navy here, indigo #4338CA in banking, blue-700 on the Team screen"* — and declares `brand.DEFAULT` navy. The rival was already identified as the rival. |
| **I** | a band lighter than `ps.bg` | **add `brand.surface: #EFF6FF`** | Not an invented colour: it is the value three screens already use for one role (a tinted fill behind a brand-ish or active icon). Naming a value the product already writes is the token file's own stated method. |
| — | the 4-band health-score ramp | **three bands, not four** | `#EA580C` appears once, at score ≥55. The state vocabulary is deliberately three-valued — is it ready, does it need me, did it go wrong — and a fourth shade nobody can name is what the token file's "a numbered scale is just slate with different names" note refuses. Collapsed **upward** into `attention`, so a middling score reads as needing attention rather than as a failure; the conservative direction. |

Each is recorded in `docs/audits/questions-for-the-owner.md` as a decision
taken, with this reasoning, so it can be reversed in one edit.

### The contrast fix that falls out of it

`app/workflows/page.tsx:296` colours an inactive template's icon **`#94A3B8`**
— the exact value the token file records moving `ps.hint` **off** at
**2.56:1 on white**, below WCAG 1.4.3 and below 1.4.11's 3:1 for a non-text
component. Same shape as the two contrast defects T5a-2 turned up in the PDFs:
found by doing the consistency sweep, real on its own.

---

## Batch 1 — the browser has a palette it can read outside a class ✅ **LANDED**

- [x] **1.1** ✅ `lib/design/tokens.ts`, 28 values by role. `scripts/one-palette-and-the-browser-reads-it.test.ts` pins it to the config **both ways** — every value equals the config's at its named path, and every export must declare a path, so a value invented here fails. Two negative controls fire on exactly their own defect: changing `READY` to green-600 fails only assertion 1, adding an undeclared export fails only 2 and 3.
- [x] **1.2** ✅ `brand.surface: #EFF6FF`, with the reason and the `ps.hover` trap written beside it. No other token moved — assertion 6 of the older guard still passes.
- [x] **1.3** ✅ 29 → 0.
- [x] **1.4** ✅ 9 → 0.
- [x] **1.5** ✅ 8 → 0, and the inactive-template icon moves off `#94A3B8` (2.56:1) onto `ps.hint` `#64748B` (4.76:1 on white).
- [x] **1.6** ✅ bare-hex budget **46 → 0**, arbitrary font size **405 → 392**. `lib/design/tokens.ts` is allowlisted — hex is its data, the colour picker's exemption. The vacuity floor MOVED rather than being deleted: `total >= 1` becomes self-contradictory at a budget of 0 (the assertion the ratchet exists to reach would fail on reaching it), and the property it protected — that the probe still matches and still reads bodies — is already proved by the allowlist test, which asserts each exempt file still holds a literal.

## Batch 2 — the 98 hex classes ✅ **LANDED**

Worst first, and they are concentrated: `components/ui/data-table.tsx` (18),
`app/clients/[id]/sales` (12), `app/clients/[id]/compliance` (8),
`app/clients` (8), `components/portal/TaxDeclarationTab.tsx` (8) — 54 of 98 in
five files.

- [x] **2.1** ✅ `data-table.tsx`, 18 → 0. Every one was the SELECTION affordance — the bar, the selected-row fill, the checkbox accent, the bulk-action links — so every screen using `DataTable` inherited the rival indigo.
- [x] **2.2–2.5** ✅ the four screens, 36 → 0. Three carry the same bulk-action bar; `components/portal/TaxDeclarationTab.tsx` held the OTHER two rivals the config names, blue-700 as a primary and its own emerald for "ready".
- [x] **2.6** ✅ class budget **98 → 44**.
      *Verified by rendering:* the built stylesheet is grepped for the emitted utilities, so `bg-brand-surface` and `bg-ps-hover` are proved to reach CSS rather than assumed — a Tailwind class naming a token the config does not declare is simply absent, and the element renders unstyled.

## Batch 3 — T6-a, redirect headroom ⏸ **BLOCKED on an observation, not a decision**

98 of Cloudflare's hard cap of 100. THE-PLAN says do this before anything else
in T6, and it is independent of T4.

- [!] **3.1** ⏸ **NOT DONE, and the plan's own target is stale.** Investigated and
      deliberately left alone. What was found:

      **The ≤90 target was already tried and abandoned, on the record.**
      `scripts/generate-redirects.test.ts:58` says so: *"The budget was previously
      pinned at 90 for headroom, but by the time the … count was OVER the real cap,
      meaning some pages were silently 404ing in production."* The cap IS enforced
      today, at 99, with one rule of headroom deliberately left.

      **98 rules = 12 splats + 86 enumerated, and 82 of the 86 are one group.**
      `/clients/:id` has 41 dynamic pages × 2 shapes — the bare path and the bare
      `.txt` RSC payload — which are the two the generator's own doc says a
      wildcard cannot express, because each needs a transform (append `/`, insert
      `/index`) rather than a straight copy.

      **The one idea that would collapse them needs a fact I cannot establish
      here.** If Cloudflare Pages resolves `/clients/x/bank` to
      `clients/_placeholder/bank/index.html` by ordinary directory-index lookup,
      then the 41 bare-path rules are unnecessary and the count drops to ~57. The
      generator's author says the transform is needed; whether that is Cloudflare's
      asset resolution or Next's `trailingSlash` redirect is not written down.
      Settling it means requesting a path against a deployed preview, and **egress
      is refused at this environment's proxy** — the same class of blocker as the
      NSDL file layout, not a design question a default can settle.

      **I did NOT verify the `.txt` half was dead weight — I checked, and it is
      not.** The static export emits 163 RSC `.txt` payloads, so shapes 3 and 4 are
      real. That was the cheap hypothesis and it was wrong; recorded because the
      next person will have it too.

      **Why not guess:** the comment this generator carries exists because of a
      production incident in which *"the whole client workspace 404s"*. A wrong
      splat reproduces it, and it would not fail CI — rules past position 100 are
      ignored **silently**. Added to the owner questions as a one-request
      observation, since a Cloudflare preview already deploys on every PR.

## Batch 4 — T5b, the exports that bypass `rbac()` ⏸ **partly; 4.4 scoped, not built**

Default taken on T5b-3's open scope question: **convert the `rbac()`-bypassing
exports first**. That is the security half and cannot be the wrong call,
whichever way the full-scope question is eventually answered.

- [x] **4.1** ✅ Enumerated. **Six** writers, not seven — `components/CsvImportModal.tsx`
      is a blank TEMPLATE download and exports no data at all, so counting it
      overstates the surface.

- [x] **4.2 + 4.3** ✅ **ALREADY DONE — two more stale plan rows.**
      `apps/web/lib/export/xlsx.ts` exists with `buildWorkbook`, `moneyCell` and
      `INR_FORMAT`, and `scripts/a-money-cell-in-a-spreadsheet-is-a-number.test.ts`
      passes all five of its assertions: no export may call `json_to_sheet`
      directly (the door), the helper must actually emit a numeric cell (the
      behaviour), the header freezes, columns are not clipped, and `moneyCell` is
      exact for the figures this product holds. `=SUM(B:B)` already returns the
      total.

      The plan says the module belongs in `apps/api` and it is in `apps/web`. That
      placement is **right where it is** for the five exports whose data already
      comes from an API: the browser is only formatting what the server computed,
      which is not business logic. It is wrong only for a write path, which is 4.4.

- [ ] **4.4** ⚠️ **`shareToPortal` is the real remaining item, and it is an access-control
      gap rather than a tidy-up.** `app/clients/[id]/accounting/page.tsx:3523`
      builds the P&L, Balance Sheet or Trial Balance, uploads the workbook to
      Supabase storage **from the browser**, and inserts into `shared_reports` over
      PostgREST — so `rbac()` never runs on either half, and what it publishes is a
      client's financial statements to that client's own portal. The only control
      is RLS.

      *Accept:* one endpoint under `rbac()` that builds the workbook server-side
      (openpyxl, `services/time_export_service.py`'s shape), uploads, and inserts —
      with the browser holding neither the storage write nor the table insert.

## Batch 5 — the backlog residue and the unpaged reads ✅ **LANDED**

- [x] **5.1** ✅ All 14 accounted for, and **none is a quick win hiding in the list**.
      The two marked `open` are the document-blocked pair the checkpoint named —
      **TDS-16** (FVU/RPU needs the NSDL layout) and **GST-25** (composition,
      e-commerce TCS and GSTR-9C: the forms' own layouts, plus a product decision
      about scope). Of the twelve `partial`, each is either done-in-substance with
      a named residue (PAY-27's bank advice and month-on-month are built; SALES-28's
      IRN scope, IRP validations and e-way validity are built and the JSON payload
      is *deliberately* refused by GST-32; GST-11's QRMP is built; INV-09's
      alternate unit landed in migration 409; BANK-11 steps 1–2 landed in migration
      380) or blocked on exactly the two things this run may not settle: a document
      (**TDS-22** needs the Finance Act read for §194I(a)/§194J(a)'s 2%) or an owner
      decision (**ACC-03**'s `is_fallback`/`reason` reach no caller, and *where* a
      CA is told is a product call; **BANK-11** step 3 widens what a TRUSTED rule
      may post unattended).

- [x] **5.2** ✅ Measured rather than assumed: **74** files touch PostgREST without
      `selectAll`, and **9** of those also build a downloadable file — the class
      where truncation is silent AND leaves the building. Three were genuinely
      unbounded and are fixed; the rest are bounded by one client or one period.

      | file | what was unbounded |
      |---|---|
      | `app/payroll/reports/page.tsx` | `payroll_runs` firm-wide — a row per client per month, so a fifty-client practice crosses 1000 inside two years |
      | `app/payroll/attendance/page.tsx` | the employee roster the attendance CSV maps over (the attendance read itself is month-bounded and was fine) |
      | `app/payroll/statutory/page.tsx` | the client picker |

      Must-fix class now **9 → 6**, and the six left are single-row or client-scoped
      reads. The other 65 stay a recorded finding: most are bounded in practice, a
      screen that truncates is at least a screen somebody is looking at, and a
      budget over 65 files is the shape that gets raised until it means nothing.

---

## Blocked — do not start

| what | why |
|---|---|
| the TDS FVU/RPU writer | needs the NSDL file layout; egress is refused here |
| the GSTR-9 filing demo | needs the GST offline utility's own screens |
| the annual ITR schema refresh | the ITD publishes them per form per AY; they cannot be inferred |
| professional tax slabs (18 states), LWF amounts | per-state notifications |
| Form 3CD, the bank salary file format | same |
| anything needing spend, a licence purchase, or a registration | GSP, ERI, NIC, Account Aggregator FIU |

A design preference is **not** on this list. Take the defensible default,
record it above, move on.

---

## Found while working — defects no plan row and no finding covered

Each was turned up by reading code for something else, which is the argument for
doing these sweeps by hand rather than by grep.

| what | where | why it matters |
|---|---|---|
| **A UTC date compared with an Indian one**, three sites | `recurring_task_service._is_already_generated_today`, `customer_statement_service.ar_aging`, `vendor_statement_service.ap_aging` | between 18:30 and 24:00 UTC the two are different days. The first regenerated a recurring compliance task that had just been generated; the other two dated an ageing report yesterday and shifted every bucket |
| **A button that has never once worked** | `shareToPortal("trial")` | wrote `report_type: "trial"` against a CHECK that has never contained it, and the workbook uploads BEFORE the insert, so every press orphaned a file in storage |
| **A roster read that truncates an export** | `app/payroll/{reports,attendance,statutory}` | `payroll_runs` firm-wide is a row per client per month; a fifty-client practice crosses PostgREST's 1000 cap inside two years |
| **A dead reader that would have truncated a reconciliation** | `lib/data/gst.fetchGSTR2ARecords` | unpaged `gstr2a_records` for a period, zero callers. Deleted rather than paged |
| **An inactive icon at 2.56:1** | `app/workflows/page.tsx` | the exact value the token file records moving `ps.hint` OFF |

## Two lessons recorded in CLAUDE.md

1. **A stored instant and `ist_today()` are not comparable until one of them
   moves.** The earlier naive-clock sweep missed all three sites above because
   it searched for `date.today()` and these write
   `datetime.now(timezone.utc).date()` — the same defect in a different
   spelling, which is this repository's most-repeated lesson.
2. **A metric and the guard that enforces it must count the same population**,
   or the metric reports a regression the guard cannot see and nobody can find.
