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

## Batch 4 — T5b, the exports that bypass `rbac()` ✅ **LANDED**

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

- [x] **4.4** ✅ **LANDED.** `shareToPortal` was an access-control gap rather than a
      tidy-up: `app/clients/[id]/accounting/page.tsx` built the P&L, Balance Sheet or
      Trial Balance, uploaded the workbook to Supabase Storage **from the browser**,
      and inserted into `shared_reports` over PostgREST — so `rbac()` ran on neither
      half, `core.authz`'s assignment scope ran on neither either, and what it
      publishes is a client's financial statements to that client's own portal.

      `POST /api/accounting/shared-reports` is the one door, under
      `rbac("accounting", "write")` with `can_access_client` beside it;
      `domain/reporting/shared_report.py` decides what may be shared and what the
      table calls it, so the browser names no report type at all. A failed insert
      now REMOVES the uploaded file, and a cleanup that itself fails goes to
      `capture_soft_failure` rather than `pass`.

      **The acceptance criterion above was half wrong and is corrected here.** It
      said "builds the workbook server-side (openpyxl)". The workbook stays in the
      browser and that is not the frontend holding business logic: `lib/export/xlsx.ts`
      FORMATS figures `/api/accounting/{profit-loss,balance-sheet,trial-balance}`
      already computed, and 4.2/4.3 above record that placement as right. Rebuilding
      it in openpyxl would be a SECOND renderer of the same three statements, with
      the export and the shared copy free to disagree. What had to move was the two
      privileged WRITES, which is the clause of the criterion that mattered.

      ⚠️ **A claim I made while scoping this was false and is corrected.** I wrote
      that `apps/api` had never uploaded to storage, so there was no precedent.
      `routers/branding.py:174` has uploaded a firm logo to Supabase Storage under
      `rbac("branding", "write")` since it was written — service client, explicit
      content type, mock branch first — and the new router copies that shape. The
      error came from grepping only `services/*.py`; it overstated the cost of this
      item, and it is the kind of "no precedent" claim that talks a reader out of
      the right fix.

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

      Must-fix class now **9 → 5** (the Schedule III client picker went too, in the
      same batch as the payroll ones), and every one of the five left was opened and
      checked rather than counted: `lib/data/gst.ts`'s remaining reads are keyed on a
      client AND a period, `lib/data/tds.ts` is a client's returns by financial year,
      the two client screens are client-scoped, and `app/clients/page.tsx`'s hit is an
      `.insert`, not a read at all. The other 65 stay a recorded finding: most are bounded in practice, a
      screen that truncates is at least a screen somebody is looking at, and a
      budget over 65 files is the shape that gets raised until it means nothing.

## Batch 6 — a clock frozen at deploy, and two identifiers the browser checked its own way ✅ **LANDED**

Nothing on the plan named any of these. All three were found by sweeping for a
RULE — "where is a date bound", "where is this identifier tested" — rather than
for a symptom, which is the argument for doing these passes by hand.

- [x] **6.1** ✅ **A date bound at import is the deploy date.** Seven modules
      opened `today = ist_today()`, evaluated once, and four functions read it
      at call time. The live one WRITES: `ai_insight_service` computed
      `days_left = (due - today).days` behind a `0 <= days_left <= 7` gate and
      persisted an insight stating that figure — so it failed in BOTH
      directions, dropping a deadline genuinely three days out and raising one
      a fortnight out. `mock_data.py` carried the other half, `date.today()` on
      a Singapore box. Fixed as the NAME (`_FIXTURES_BUILT_ON`, `_SEEDED_ON`)
      plus four call-time reads, because four of the seven legitimately want
      their import-time day. `test_a_date_bound_at_import_says_so.py` states
      two rules and PROVES the two exemptions rather than allowlisting them.
      One older guard asserted the literal `today = ist_today()` and failed on
      a rename that made the module more correct — fifth time that pattern has
      been corrected here.

- [x] **6.2** ✅ **Eight GSTIN shape regexes in `apps/web` against one caller of
      the check-digit authority.** The worst is `app/risks/page.tsx`, whose
      GSTIN Mismatch section exists for no other purpose — so the one page a CA
      opens to be told a GSTIN is wrong reported clean on every transposition.
      Seven doors moved onto `lib/gst/gstin.gstinProblem`; the eighth
      (`lib/invoices/compliance.ts`) is Rule 48(4)'s shape-only limb, pinned by
      `shared/irn-parity-vectors.json`, and now says so in the code. Five
      specimen GSTINs a CA READS had check digits this product refuses —
      third time this repository has found that.

- [x] **6.3** ✅ **Seven PAN validators tested the raw field.**
      `core/validators.validate_pan` opens `value.strip().upper()`; the browser
      copies did not, so they refused what the server accepts. Visible on
      Settings and onboarding, where the shared `Field` does not uppercase:
      typing `aabcu9603r` was refused. `lib/identifiers/pan.ts` mirrors the
      server EXACTLY, edge included — `validate_pan` returns None for `""`
      before normalising, so a string of spaces is a format error, an asymmetry
      recorded rather than tidied. Rule 114's holder-type code is refused on
      BOTH sides together, because the full set could not be confirmed here and
      an incomplete one blocks a real client record.

- [x] **6.4** ✅ **TAN and DIN, one copy each, same defect.** `tan.ts` and
      `din.ts`, one rule per file. Two asymmetries pinned: a TAN's shape is a
      PAN's reversed, and a BLANK DIN is an error where a blank PAN is not —
      the server's own rule, since a director without a DIN is not a director.

      **The guard does not compare two descriptions of the rule.** The whole
      finding is that the two implementations NORMALISE differently, so it runs
      the TypeScript through node and the Python in-process over the same
      inputs. Thirteen negative controls across the four items, each firing on
      the assertion it names; two guard bugs were caught by their own controls
      — a door test satisfied by the comment that explained it, and a scan that
      failed on its own explanation before comments were stripped.


## Batch 7 — the risk register was derived in the browser ✅ **LANDED** (#576)

- [x] **7.1** ✅ `app/risks/page.tsx` was 856 lines that made six PostgREST
      reads of their own and derived NINE kinds of statutory risk in the
      browser, citing CGST §47, IT §200A, §201(1A), §234B/C, §139A and §194A.
      `rbac()` ran on none of the six and neither did the assignment scope. The
      advance-tax dates were four hardcoded strings against
      `compliance_engine.advance_tax_due_dates`. And the FD row advised "TDS
      applicable u/s 194A if interest > ₹40,000", a figure NOTHING here can
      establish — §194A(3)(i) has three limbs and `section_rates` holds one,
      which its own docstring names as the general one.
      `domain/risk/register.py` decides, `services/risk_register_service.py`
      fetches and pages, `GET /api/risks/register` serves. The browser holds no
      per-kind knowledge: the server sends a `particulars` map in display order
      and one renderer replaces nine hand-written tables. 858 → 420 lines.
      ⚠️ **The first draft misread 1000000 paise as ₹1,00,000** — it is ₹10,000
      — and would have quoted the general limb as the bank one. Third miscount
      of an Indian figure in this run; recorded in the module.

## Batch 8 — two files claimed another agreed with them ✅ **LANDED** (#577)

- [x] **8.1** ✅ **`private_limited` was a Companies Act company on the server
      and not in the browser.** The two SETS were identical; the two
      NORMALISATIONS were not — Python folds `[\s_]+`, the browser folded
      `\s+` — so the compliance calendar generated AOC-4, MGT-7 and ADT-1 for
      a client whose MCA workspace the product then refused to show, and Year
      End declined to call their statements Schedule III. The underscore is not
      hypothetical: `normalise_entity_type`'s docstring records that the
      income-tax page renders entity types with `.replace(/_/g, " ")` and that
      *the bug it replaced was a title-case value tested against an underscored
      constant*. The same defect had never been swept out of `apps/web`.
      `shared/entity-type-vectors.json` runs both implementations over the same
      28 strings.

- [x] **8.2** ✅ **T8-c, the marketing brand parity test.** Nine of ten colours
      agreed to the character; `brand.hover: #0F1A3D` existed there and nowhere
      in the product, for a role `apps/web` expresses as `brand-dark` at
      fifteen sites. Three dead `boxShadow` tokens went too — the same three
      T3-a deleted, and `grep -r "shadow-card"` over `apps/marketing` was
      empty.

---

## ⚠️ T4-c IS NOT A MECHANICAL CODEMOD, AND THE PLAN ROW READS AS THOUGH IT IS

Measured before starting it, and NOT started. THE-PLAN gives T4-c one day to
"codemod over 13 arbitrary px values" toward a target of ~130. The tree owes
**379** today, in ten distinct sizes:

| size | count | Tailwind built-in |
|---|---|---|
| `text-[12px]` | 189 | `text-xs` — **same size** |
| `text-[13px]` | 88 | none |
| `text-[14px]` | 40 | `text-sm` — **same size** |
| `text-[9px]` | 29 | none (`3xs` is 10px) |
| `text-[18px]` | 8 | `text-lg` — **same size** |
| `text-[16px]` | 7 | `text-base` — **same size** |
| `text-[22px]`, `[26px]`, `[15px]`, `[32px]` | 18 | none |

So 244 of the 379 look like a find-and-replace and **are not**, because a
Tailwind size token carries a LINE HEIGHT and an arbitrary value does not:

```
xs   ["0.75rem",  {"lineHeight":"1rem"}]
sm   ["0.875rem", {"lineHeight":"1.25rem"}]
base ["1rem",     {"lineHeight":"1.5rem"}]
lg   ["1.125rem", {"lineHeight":"1.75rem"}]
```

Only **7 of the 167** `class="…text-[12px]…"` sites also set a `leading-`, so
converting would silently give 160 elements a 16px line height they do not have
today. The config's own custom steps (`3xs`, `2xs`) are declared as bare
strings precisely to avoid that — which means the honest conversion is to add
size-only steps, and **adding a size-only `xs` would override Tailwind's own
`text-xs` and change the line height of every element already using it**, in
the other direction.

**That is a typographic decision across the product, not a codemod**, and it is
the one thing on this list that cannot be verified without looking at the
result. Left for the owner with the measurement above; the remaining 135 are
genuinely off-scale and need scale steps chosen anyway.


## A THIRD METRIC COUNTING A DIFFERENT POPULATION FROM ITS GUARD

This run opened by correcting one of these and has now found two more. The
lesson is already in CLAUDE.md; what is new is that it keeps happening to
metrics written as `grep … | wc -l` beside a guard that checks the property.

| metric | what it counts | what the guard checks |
|---|---|---|
| hex literals (corrected at the top of this file) | every `#RRGGBB` in `app/` + `components/`, comments included | three populations, comments stripped, with an allowlist |
| **T5b "browser-side Excel writers: 7 → 0"** | `XLSX.write` call sites | that there is ONE writer and a money cell is a NUMBER. **Six of the seven already go through `buildWorkbook`; the seventh builds an empty import TEMPLATE with no money in it and is allowlisted with that reason.** The property is held and guarded; the count is a spelling of it |
| **T4-c "codemod 13 arbitrary px values"** | `text-[Npx]` occurrences | nothing — and the conversion is a LINE-HEIGHT change, see above |

None of the three was a regression. All three would have sent somebody hunting
one.


---

## Four probes that came back CLEAN, recorded so nobody re-derives them

Each of these looked like a defect class worth sweeping, was measured, and was
not one. A negative result nobody wrote down is a negative result somebody will
pay for again.

| probe | what was measured | why it is not a defect |
|---|---|---|
| **A read filtered on `client_id` without `firm_id`** | 11 statements, on tables that DO carry `firm_id` | `clients.id` is a globally unique UUID and `can_access_client` checks `_client_belongs_to_firm` before any of them run (the F1 fix), so a client id from another firm never reaches them. Defence-in-depth loss, not a cross-tenant read. Not "fixed" opportunistically: 11 untested query changes for no behaviour change is the wrong trade. |
| **A write whose `{success:false}` nobody checks** | 9 unchecked write calls across `app/` and `components/` | `request()` throws only on `!res.ok`, so a **200 with `success:false`** does pass through — the failure mode CLAUDE.md records for the GST workspace. But of the six routers those nine reach, only `payroll` answers 200+false at all, on `finalize_run` and `disburse_run`, and **both of those callers check** (`page.tsx:1066`, `DisburseModal.tsx:66`). A guard was considered and rejected: it would have to map a browser call to a Python endpoint across two languages, and a fragile guard is worse than the finding. |
| **Western grouping in the BROWSER** | 60 `toLocaleString`, 47 `toLocaleDateString` | 57 and 45 respectively already name `en-IN`. The three exceptions format a MONTH NAME, and the one date exception is `en-CA` with `timeZone: "Asia/Kolkata"` — the idiomatic ISO-date trick, deliberate and correct. |
| **Health scores rebuilt from raw rows** (T7-L1-d's premise) | `app/health/page.tsx`, `/at-risk`, `/critical` | All three READ the stored `health_scores` table; none recomputes. The plan row's premise is stale for these three |
| **`lib/purchases/billEditor.ts`**, 403 lines citing §17(5) thirty-four times | the heuristic, the clause list, the GST maths | Honestly built: the keyword heuristic disclaims itself in its own comment ("NOT a legal determination … never blocks the save"), the decision is the CA's `itc_eligible` boolean, and the money delegates to `dnLineGst`, which mirrors the backend. The clause list is free text by migration 240 and has one reader |
| **`lib/sales/receiptAllocation.ts`** | the allocation caps | Its docstring states the rule it follows — "Nothing here decides anything the server does not re-decide" — and it prefers the SERVER's `unallocated_paise` over any subtraction. A drift shows as a refused save, not a wrong number |
| **A day book** (ACC-13's first limb) | `app/clients/[id]/accounting` | Already built, as `mode === "day_book"` on the journal tab — "Day Book — every posting in this period". The finding's own wording ("no day book") is stale |
| **The marketing site overclaiming** | every `file` / `auto-submit` / `GSTR-*` string in `apps/marketing` | It is honest, explicitly: *"You upload and sign on the government portal"*, *"PracticeSync prepares the return; a CA files it on the portal. The software never transmits anything"*, and a section headed *"Never auto-submit — the principle at the heart of the platform."* |

---

## Two measurements of mine that were wrong, and the same mistake both times

Recorded because the mistake is the one CLAUDE.md now states as a rule — *a
metric and the guard that enforces it must count the same population* — and I
made it twice in one run, in both directions.

**"68 guards have no vacuity floor."** Counted over all 121 `apps/web/scripts`
guards. A vacuity floor is only meaningful for a guard whose assertion is a
BUDGET: `found.length <= N` passes when the probe stops matching, while
`assert.match(src, /…/)` fails. Re-counted over that population there are **six**
budget-shaped web guards, and **all six are sound**: three carry an explicit
floor; `a-colour-and-a-type-size-come-from-the-token-file` moved its floor onto
the allowlist test, with the reason written down, when its own budget reached 0
and `total >= 1` became self-contradictory; `a-rupee-figure-is-formatted-in-one-place`
carries two (`FILES.length > 400` and `moneyFormatters().length > 50`); and
`OVERRIDE_REASON_MIN` is a product constant, not a budget. **No work item. The
68 was the wrong denominator, not a backlog.**

**"`apps/api` has never uploaded to storage."** Grepped `services/*.py` only.
`routers/branding.py:174` does, under `rbac()`. Corrected in 4.4 above.

Both errors ran the same way: a population chosen for convenience, then a
conclusion drawn as though it were the population the claim was about.

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
| **Publishing a client's statements ran no permission check** | `shareToPortal` | both privileged writes were the browser's — a Supabase Storage upload and a `shared_reports` INSERT over PostgREST — so `rbac()` ran on neither and `core.authz`'s assignment scope on neither either. An Executive who cannot see a client could publish that client's balance sheet to that client's own portal |
| **85 rupee figures grouped the Western way, ten of them inverting a negative** | 47 backend modules | `f"{n:,}"` gives 1,23,456.78 as 123,456.78, and the browser has used `en-IN` the whole time — so a figure was grouped one way in a column and the other way in the sentence beside it. Ten sites also carried the sign bug `domain/reporting/pdf_money`'s own docstring documents: -1 paise printed "-1.99" |
| **The AI copilot is told the UTC day** | `ai_copilot_service`, 5 sites | between 00:00 and 05:30 IST that is YESTERDAY, and it is the line the model reasons from when a CA asks what is due. Third instance of the same clock class this run |
| **Two grouping implementations with nothing pinning them** | `domain/money_text` vs `lib/money/format` | the shape this repo pins for GSTIN, UQC, invoice numbers, GST line tax, the e-way threshold and IRN scope. Grouping was the one that had two implementations and no vectors, which is how it came to be wrong on one side for as long as it was |
| **A dead reader that would have truncated a reconciliation** | `lib/data/gst.fetchGSTR2ARecords` | unpaged `gstr2a_records` for a period, zero callers. Deleted rather than paged |
| **A date bound at import, read at call time** | `ai_insight_service` ×2, `automation_engine`, `risk_engine` | a long-lived uvicorn process makes it the DEPLOY date. The insight writer's `0 <= days_left <= 7` gate dropped a deadline three days out and raised one a fortnight out, and PERSISTED the wrong figure |
| **The screen that finds wrong GSTINs could not see the commonest one** | `app/risks/page.tsx`, +6 more | eight shape regexes against one caller of the check-digit authority. A transposition inside the PAN is what a person typing fifteen characters produces |
| **Five specimen GSTINs a CA reads are refused by this product's own validator** | two placeholders, an invoice-terms example, a supplier placeholder, a client-form error message | a placeholder is a GSTIN the screen teaches. Third instance |
| **Seven PAN validators tested the raw field** | Settings, onboarding, client form, two bulk imports, MCA, CSV mapper | `validate_pan` strips and uppercases first, so the browser refused what the server accepts — and the firm's own PAN field does not uppercase what is typed |
| **An inactive icon at 2.56:1** | `app/workflows/page.tsx` | the exact value the token file records moving `ps.hint` OFF |

## Phase 2 — 2.4, 2.5 and 2.6 ✅ **LANDED** (#602, #603, #604)

Three things in this tranche were found by LOOKING at the product rather than
by reading it, and none of them could have been found by a test.

**2.5's premise was wrong and the real defect was bigger.** THE-PLAN's "39
orphan screens" is unreproducible under any definition, and so is the 63 the
24-09 re-measure offered. Only **two** named screens were absent from both the
sidebar and their module's landing page. What is actually wrong is that every
module has **two** navigation surfaces and they listed **disjoint** sets:
`/accounting` 10 against 4 with no overlap, `/settings` 8 against 1, the four
filing modules 11 on landing pages against a panel offering the module root.
No count of "screens in no menu" can express that.

**A grep for `signOut` settled 2.6's shape.** It appears in exactly one
navigation surface in this product, and so does the only `href="/settings"`
outside the settings screens — the rail, which was hidden inside the client
workspace. A CA in a client could not sign out or reach Settings.

**And the screenshots caught what no assertion would.** At 52px the rail was
cutting "Relationships" to `elationship` and "Engagements" to `ngagement` on
every firm screen.

| what | where | why it matters |
|---|---|---|
| **`/onboarding/checklist` had no navigation and was PUBLIC** | `AppShell`, `lib/auth/public-paths.ts` | the client-onboarding tracker shares a path prefix with the firm SIGNUP wizard, so it matched both the no-shell list and `isPublicPath`: no rail, no panel, no ⌘K, and handed to signed-out visitors instead of the login page. Its API call still needs a token, so nothing leaked — it rendered empty at a URL that should have bounced. Both lists are EXACT on `/onboarding` now |
| **`/accounting/schedule-iii` was named for the wrong screen** | `lib/navigation/screens.ts` | the ⌘K inventory called it "Schedule III captions"; it renders the STATEMENTS, and the caption mapping is `/accounting/schedule-iii-mapping`. So "balance sheet" found nothing and "captions" landed on the statements — wrong in exactly the way that list exists to prevent |
| **The smoke walk has never seen the client workspace** | `scripts/smoke-walk.mjs` | `isClientWorkspacePath` requires a real UUID, and the walk's server serves `out/` as plain files, so a uuid path 404s and it could only ask for `/clients/_placeholder/…`. Every client screenshot it has ever taken wore the FIRM chrome — the half its own header says it exists for. `--real-client` mirrors Cloudflare's rewrite, and the first run of it walked 43 client routes with 0 crashes and 42 distinct bodies |
| **`WorkspaceRail` labels were clipped mid-word** | `components/shell/WorkspaceRail.tsx` | two of twelve, on every firm screen. Widening to 64px fixed ten and left the other two ellipsised; the width that fits them whole is ~84px. They carry the same word with a U+200B in it instead |

**A guard was deliberately reversed, and restated rather than deleted.**
`one-mobile-menu-button.test.ts` asserted "nothing in AppShell's chrome renders
inside the client workspace" — a SPELLING of its rule, in one named file, which
2.6 reverses on purpose. It now states the rule that survives any
restructuring: exactly one mobile trigger and one drawer in the product,
counted on `md:hidden fixed` rather than on `<Menu>`. That is this run's fourth
instance of the same lesson.

## Two lessons recorded in CLAUDE.md

1. **A stored instant and `ist_today()` are not comparable until one of them
   moves.** The earlier naive-clock sweep missed all three sites above because
   it searched for `date.today()` and these write
   `datetime.now(timezone.utc).date()` — the same defect in a different
   spelling, which is this repository's most-repeated lesson.
2. **A metric and the guard that enforces it must count the same population**,
   or the metric reports a regression the guard cannot see and nobody can find.

---

# Phase 2 — 2.7a and 2.7b ✅ LANDED (#605, #606)

## 2.7a — payroll is one place, and it is the thirteenth workspace

PAY-28, which the plan had folded into 2.7 as item 2.9. Payroll's six screens
sat across **three** top-level areas: `/payroll` and `/payroll/statutory` under
Accounting, `/payroll/attendance` under **Team**, and `/payroll/people`,
`/payroll/declarations` and `/payroll/reports` in no panel at all until 2.5 —
which then left attendance in **both**, two clicks apart under two module
headings, lighting a different rail icon depending on which one the CA had
used. A bureau running payroll for a dozen clients — a service a practice
*sells*, priced per employee per month — had no home for it.
`docs/architecture/10-payroll.md` specifies the fix and specifies it as the
13th top-level workspace.

**Setup is a pointer, not a seventh screen.** The doc's `/payroll/setup` is
state coverage, and that is already built at `/settings/statutory-values` —
PAY-28's own verification pass established it. A second screen for one fact is
the `/accounting/retainer` mistake.

## 2.7b — D22 answers G3: the firm hub's dead tiles land on a worklist

Five of D1's fifteen tiles had no firm-level destination and two of the five
landed on a `MovedToClientWorkspace` **tombstone** — a page whose whole content
is "this moved", which is worse than a 404 because it renders.

**Reading the tombstone changed the answer.** It records a deliberate earlier
decision: *"firm-level accounting screens have been retired; accounting flows
exclusively through the client workspace."* So the answer is not five rebuilt
firm-level registers — that is the duplicate those pages exist to prevent. It
is the question a bureau actually asks on the 3rd: **which of my clients needs
work in this module.** A queue, not a register, with every row opening that
client's own section. `/accounting/fixed-assets` replaces its tombstone, whose
message was already "choose a client".

## The defects and near-misses this tranche turned up

| what | where | why it matters |
|---|---|---|
| **`HomePanel` had no role filter at all** | `components/panels/HomePanel.tsx` | `/deadlines` is in `STAFF_HIDDEN_HREFS` and the `deadlines` and `work` **workspaces** are both hidden from delivery staff — so the rail hid them from an Executive, a Reviewer and a Client while Home offered both to everyone. Found by the new one-home guard on its first run, not by looking for it |
| **`a-module-shows-all-of-itself` was vacuous for four screens** | `apps/web/scripts/` | it did not strip comments, and every panel that gives a screen up writes a comment naming it. A negative control that removed `/payroll/people` from `PayrollPanel` **passed**. Third instance of the same hazard in one day; the fourth was the Python tombstone check, which failed a page whose docstring explained what it replaced |
| **The thirteenth rail tile fell off the bottom** | `components/shell/WorkspaceRail.tsx` | at the old 56px pitch the column is 13×56 + 56 + 24 + 130 = 938px against a 900px viewport, and the nav scrolls with the scrollbar hidden — so Engagements was there and nothing on screen said so. 2.6's "elationship" defect in the other axis, caught by the same means: looking at the shot |
| **The worklist panel rendered a header over nothing** | `components/panels/PayrollPanel.tsx` | every entry carries a `requires` pair and `can()` fails closed while the permission map is in flight, so unlike every other panel — which has ungated entries and degrades to a partial list — this one degraded to a blank column. It waits for `resolved`, the same rule the rail applies to the tile that opens it |
| **A fourth render state with no rendering** | `components/hub/ModuleWorklist.tsx` | `success` with an unreadable payload leaves `loading` false, `error` null and `data` null, and the first draft drew the heading over nothing. The first smoke shot of the screen caught it |
| **The parity fixture disagreed with the database and both halves were "right"** | `tests/test_hub_client_worklist_parity_pg.py` | `bank_transactions.entry_state` is trigger-maintained (322) and `purchase_bills.outstanding_paise` is GENERATED (278). Seeding `entry_state` directly let the trigger recompute it, so the SQL saw one thing and the twin saw the fixture's claim. The twin is now fed rows **read back out of Postgres**: two fixtures can agree with each other while both disagree with the database |
| **`scripts/screens.snapshot.json` is a THIRD route inventory** | `apps/web/scripts/` | `knownRoutes.generated.ts` regenerates on `next build` and is guarded; the smoke walk reads its own snapshot, which nothing regenerates automatically. Three new pages existed, built and passed every test while the walk silently never visited them. Refreshed by hand here; worth a guard |

## One thing recovered rather than exempted

`test_backend_columns_exist_pg` counts a `.select()` reached through a name as
**unreadable** — its budget went 463 → 465 on the generic per-tile projection,
and the failure message invites raising it. The coverage was recoverable, so
the projections are written out per tile instead: four near-identical lines,
the same trade `domain/tally/party_identifiers` records. Of all the reads to
leave unchecked, four feeding a queue a CA works from is a poor choice.
