PracticeSync — AI-powered practice management platform for Indian Chartered Accountants.
Replaces Tally + ClearTax + Winman + WhatsApp with one unified AI-first platform.

Naming: the product is **PracticeSync**. The repo, the Supabase project, log prefixes
(`caflow.*`), some seed data and a few mock URLs still say `caflow` / `CAflow AI`. That
is known cosmetic legacy — do not "tidy" it opportunistically. It appears in import
paths, env keys and migration history, and a careless rename breaks all three.

## Repo layout

Three apps, not two:

- `apps/api` — FastAPI (Python 3.11). **All** business logic lives here.
- `apps/web` — Next.js 14, the product. Static export (`output: "export"` in
  `next.config.mjs`), deployed to Cloudflare Pages.
- `apps/marketing` — separate Next.js marketing site, its own Cloudflare Pages project.

## Tech stack

- Frontend: Next.js 14, TypeScript, Tailwind CSS, shadcn/ui primitives in
  `apps/web/components/ui/` (vendored source — there is no `components.json`, so the
  shadcn CLI will not work; add primitives by hand).
- Backend: FastAPI (Python 3.11)
- Database: Supabase (Postgres), project region ap-south-1 (Mumbai)
- Package manager: pnpm for frontend, pip for backend

### AI providers — every key is backend-only

`apps/web` builds as a static export, so it has no server and can read nothing but
`NEXT_PUBLIC_*` values, which are inlined into the browser bundle. An AI key in the
frontend environment is at best ignored and at worst published. All AI calls happen in
`apps/api`, with keys in `apps/api/.env` ONLY.

- **Groq** — chat/text features and PDF (text-only) invoice extraction. Needs
  `GROQ_API_KEY`. Default model `llama-3.3-70b-versatile`, overridable via
  `GROQ_TEXT_MODEL`.
- **Gemini** — image-based invoice extraction only (photographed/scanned bills, in
  `routers/document_intelligence_v1.py`). Needs `GEMINI_API_KEY`. Default model
  `gemini-3.5-flash`, overridable via `GEMINI_VISION_MODEL`.

Why two providers: Groq's vision models returned a live 404 `model_not_found` on this
account; Gemini's free tier is multimodal-native and already provisioned. The PDF/text
path stayed on Groq and works fine. Treat the model names above as current defaults,
not as contracts — `gemini-2.5-flash` was retired by Google ahead of its announced
shutdown, and the code reads the env var precisely so the next retirement is a config
change. The code is the authority; keep this file in step with it.

## Money and the general ledger

- **Every rupee calculation uses integer paise arithmetic, never floating point.**
  Monetary columns are `*_paise BIGINT`. ₹1 = 100 paise.
- **One posting kernel, no alternative paths.** Every accounting event that touches the
  GL is written by `services/phase2_journal_service._create_journal`. It asserts
  double-entry balance and dedupes on `(client_id, reference_no, entry_date)` before
  inserting. Sales, purchases, receipts, payments, credit/debit notes, banking, payroll,
  fixed assets, opening balances, manual journals and reversals all route through it. Do
  not add a second write path.
- The live GL is `journal_entries` + `journal_lines` only. A posted entry can never be
  hard-DELETEd or rewritten in place (DB triggers), and a correction to a real
  transaction is an append-only reversal. But immutability is not absolute, and the
  code is the authority on where the line falls: a **manual** entry may be edited
  (migration 266) or soft-deleted (275, 276) while its period is open, judged by
  `journal_period_lock_reason` — the CA locks the year, or a return covering the date is
  filed. Migration 276 also lets a reversed entry and its reversal go together, since a
  pair strands nothing and nets to zero. This tracks Indian law rather than exceeding it:
  the proviso to Rule 3(1) of the Companies (Accounts) Rules 2014 requires an **edit
  log**, which presumes entries can change, and TallyPrime's Edit Log — mandatory and
  non-disableable — still lets a voucher be deleted. The log is what is immutable, not
  the entry. Every deletion writes the whole entry, its lines and their account names to
  `audit_log` in the same transaction, unswallowed.
- `created_by` / `posted_by` FK to `public.users.id` (the internal user id), **not** the
  Supabase auth id.
- Money crosses the API as raw integer `*_paise`. The frontend formats to ₹. Rupee
  conversion happens only at the statutory payload boundary — see
  `domain/gst/money.py`: 2-decimal rupees for GSTR-1, whole rupees for GSTR-3B
  (CGST Act §170, half rounded up).

## Indian tax domain rules — never violate these

- GSTIN format: 2-digit state code + PAN (10 chars) + 1 digit entity number + Z + 1 check digit
- PAN format: AAAAA9999A (5 uppercase letters + 4 digits + 1 uppercase letter)
- Financial year: April 1 to March 31
- GSTR-1 due date: 11th of the following month
- GSTR-3B due date: 20th of the following month
- GSTR-9 (annual): 31st December
- TDS return (24Q salary / 26Q residents / 27Q non-residents — Rule 31A(2) sets one due date per quarter regardless of form): Q1 31 Jul, Q2 31 Oct, Q3 31 Jan, Q4 31 May. Q4 is the exception — it is NOT the end of the month following quarter end (that would be 30 Apr). services/compliance_engine.py::tds_return_due_date is the authority; keep any prose in step with it.
- Advance tax due dates: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
- ITR (IT Act §139): 31 July, or 31 October where audit applies
- MCA/ROC offsets from the AGM date: ADT-1 +15d (§139), AOC-4 +30d (§137), MGT-7 +60d (§92)
- **GSTR-3B Table 4** follows Notification 14/2022-Central Tax with Circular
  170/02/2022-GST, live on the portal from 01-09-2022: 4(A) is **gross** (it is
  auto-populated from GSTR-2B, so netting blocked credit out of it breaks the
  tie-up), 4(B)(1) takes reversals "absolute in nature and not reclaimable"
  (Rules 38/42/43 and §17(5)), 4(B)(2) takes the reclaimable ones (Rule 37/37A,
  §16(2)(b)/(c)), and 4(C) = 4(A) − 4(B). §17(5) goes in 4(B) and is **not**
  repeated in 4(D). Table 6 sets off 4(C), never 4(A) — §49(4) allows payment
  only from credit available in the credit ledger, and credit reversed in the
  same return is not. `domain/gst/gstr3b_computer.py` carries the circular's
  wording and is the authority; the pre-2022 layout looks plausible and gets the
  tax right, which is why it survived so long.
- **Correction window** (CGST §37(3), §39(9), §16(4)): 30 November following the FY, **or
  the date GSTR-9 was furnished, whichever is EARLIER**. Filing the annual return early
  shuts the window early. `compliance_engine.correction_window_closes()` is the function
  to use — `november_30_cutoff()` is only the statutory outer limit and will tell a CA a
  correction is available when it is not.
- **§192 withholding rests on THREE separate things, and conflating any two gets
  it wrong.** (1) The employee's regime INTIMATION to the employer — CBDT
  Circular 04/2023 — governs withholding only, and the same circular says
  expressly that it "would not amount to exercising option in terms of
  sub-section (6) of section 115BAC". (2) The §115BAC(6) ELECTION governs the
  return: Form 10-IEA where there is business income, the return itself where
  there is not (`domain/income_tax/regime_election.py`). (3) The Rule 26C
  FORM 12BB statement is the evidence, and prescribes exactly four claims —
  §10(13A), §10(5), §24(b) and Chapter VI-A. `domain/payroll/declarations.py`
  keeps them apart; nothing sets one from another.
- **Under the new regime §115BAC(2) allows §16(ia) and nothing else from
  section 16** — professional tax under §16(iii) is NOT deductible, nor is
  §10(13A) HRA, §10(5) LTA, or any Chapter VI-A head except §80CCD(2) (and
  §80CCH(2)/§80JJAA, neither a salary declaration). Since payroll withholds on
  the new regime by default, a deduction applied unconditionally is applied to
  everyone it is not available to.
- **The two Schedule III ageing schedules are NOT the same shape.** MCA
  Notification G.S.R. 207(E) of 24-03-2021 added both to the notes to the
  balance sheet. Trade RECEIVABLES age in five columns from six months (`<6m |
  6m–1y | 1–2y | 2–3y | >3y`), rows (i)–(iv) splitting undisputed/disputed ×
  considered good/doubtful. Trade PAYABLES age in FOUR columns from one year
  (`<1y | 1–2y | 2–3y | >3y`), rows (i) MSME, (ii) Others, (iii) Disputed
  dues–MSME, (iv) Disputed dues–Others. Both age from the DUE DATE of payment,
  or from the transaction date where none is specified. Giving the payables
  table the receivables' columns is the easy mistake and it is a wrong
  disclosure. Only MICRO and SMALL are row (i) — MSMED §22 and §2(n) both stop
  at small, so a MEDIUM enterprise is registered under MSMED and still belongs
  in Others. These are the **Division I** (AS) tables; Division II (Ind AS)
  splits the doubtful receivables row into "significant increase in credit risk"
  and "credit impaired". `domain/reporting/ageing.py` and
  `public.schedule_iii_ageing` (migration 303) are the authority and are pinned
  to each other by a parity test.
- Never auto-submit anything to any government portal — always require explicit CA confirmation click

`services/compliance_engine.py` is the single source for every due date above. If prose
and that module disagree, the module wins and the prose gets fixed.

## What has to be updated every financial year

Indian tax rates, limits and forms change annually. This is the complete list of
what goes stale, where it lives, and how to tell. **It is deliberately short:
only things that actually change by statute or notification are here.** If
something is not on this list, it does not need an annual edit.

### The trap that makes this list necessary

Every rate lookup falls back rather than failing:

```python
def rates_for(fy):
    if fy in RATES_BY_FY:
        return RATES_BY_FY[fy]
    return RATES_BY_FY[LATEST_VERIFIED_FY]   # <- silently LAST year's rates
```

`entity_rates`, `presumptive`, `minimum_tax`, `section_rates` and `cii_for` all
do the same. So a missing year is **not an error — it is a confidently wrong
number**, computed at last year's rates and presented with no warning. That is
the whole reason this has to be a checklist someone works through, rather than
something that surfaces on its own.

There is one live instance right now. `CII_BY_FY` stops at 2025-26, so on any
date in FY 2026-27 `cii_for("2026-27")` returns 380 — the 2025-26 index. Post
Budget 2024 indexation survives only as the grandfathered option on immovable
property, so the blast radius is small, but the number is wrong, not absent.

### 1. The FY-versioned rate registries

Same shape in each: a `*_BY_FY` dict, and a `LATEST_VERIFIED_FY` naming the last
year a human checked against the Finance Act. **Add the new year's entry, then
move `LATEST_VERIFIED_FY` — moving it without adding the entry silently promotes
a guess to a verified figure.**

| File | Holds | Changes with |
|---|---|---|
| `domain/income_tax/statutory_rates.py` | slabs (both regimes), §87A rebate, surcharge brackets and marginal relief, cess | Finance Act |
| `domain/income_tax/entity_rates.py` | firm / LLP / domestic and foreign company rates | Finance Act |
| `domain/income_tax/presumptive.py` | §44AD, §44ADA, §44AE turnover limits and deemed rates | Finance Act |
| `domain/income_tax/minimum_tax.py` | MAT §115JB, AMT §115JC rates and thresholds | Finance Act |
| `domain/tds/section_rates.py` | TDS rates AND per-section thresholds (`LATEST_VERIFIED_TDS_FY`) | Finance Act, and mid-year CBDT notifications |
| `domain/income_tax/capital_gains_engine.py` | `CII_BY_FY` + `LATEST_CII_FY` | one CBDT notification, usually around June |

CII is the odd one out: it is notified *partway through* the year it applies to,
so at 1 April the entry legitimately does not exist yet. Check again mid-year.

Print current coverage before deciding anything:

```
cd apps/api && python3 -c "
from domain.income_tax import statutory_rates as s, entity_rates as e, presumptive as p, minimum_tax as m, capital_gains_engine as c
from domain.tds import section_rates as t
for n, d in [('slabs',s.RATES_BY_FY),('entity',e.RATES_BY_FY),('presumptive',p.LIMITS_BY_FY),
             ('minimum tax',m.RATES_BY_FY),('TDS',t.TDS_RATES_BY_FY),('CII',c.CII_BY_FY)]:
    print(f'{n:12} latest {max(d)}')"
```

### 2. The ITR JSON schemas — these must be downloaded by hand

`domain/income_tax/schemas/`, wired up in `itr_schema.py`'s `SCHEMA_FILES`.

The Income Tax Department publishes a new JSON schema per form per assessment
year, at **incometax.gov.in → Downloads → Income Tax Returns**, and the filename
carries a version that changes *within* a year too (the set on disk today spans
V0.1 to V1.2). They cannot be generated or inferred — somebody downloads them.

**So yes, this is an annual hand-off, and it is the only item on this list that
cannot be done from inside the repo.** Replace the seven files, update
`SCHEMA_FILES` to the new names, and re-run the field-path tests — the paths move
between versions, and `itr_json.py` writes against them. A path that silently
resolves to the wrong node is the failure mode here: an earlier version of this
work picked `TaxPayableOnDeemedTI` (the §115JB/§115JC MAT branch) instead of
`TaxPayableOnTI` on ITR-5 and ITR-6, which validated perfectly and reported the
wrong tax.

### 3. Payroll statutory limits — PF and ESI are versioned; PT is not yet

`domain/payroll/statutory.py` now holds the EPF and ESI figures in the same
`*_BY_FY` + `LATEST_VERIFIED_FY` shape as everything else: the ₹15,000 EPF
ceiling and 12% rate, the EPS 8.33% / ₹1,250 diversion, EDLI and admin charges,
and the ₹21,000 ESI ceiling with its 0.75% / 3.25% rates.

They change by EPFO / ESIC notification rather than on an annual cycle, so they
do not belong in the April sweep — but they are now printable, so add them to
any coverage check you run:

```
cd apps/api && python3 -c "
from domain.payroll.statutory import RATES_BY_FY, LATEST_VERIFIED_FY
print('payroll     latest', max(RATES_BY_FY), '| verified', LATEST_VERIFIED_FY)"
```

**Partly a gap: professional tax and the Labour Welfare Fund.** PT slabs are
still bare literals in `routers/payroll.py`, covering **Maharashtra, Tamil Nadu,
Karnataka and West Bengal** — four of the twenty-two states that levy it. LWF
has no amounts at all.

What is no longer a gap is the SILENCE. `domain/payroll/professional_tax.py` and
`domain/payroll/lwf.py` carry which states levy each, so an unmodelled state now
reports itself: creating a payroll run returns `statutory_gaps` naming every
employee whose state levies a deduction the run did not compute. A zero for
Delhi and a zero for Gujarat used to be the same number meaning opposite things.

The amounts are deliberately not written from memory — twenty states' slabs and
sixteen states' LWF figures, each moving by its own notification, would be
thirty-six confidently wrong deductions in people's pay, and a wrong deduction
is worse than a flagged gap: the employee is short-paid and the employer still
owes the right figure. **Adding a state is a human step**, like the ITR schemas:
read the current state notification, add the table, move the code out of the
unmodelled set.

### 3b. The other statutory data a human has to supply

Not annual — each moves on its own cycle — but all of it shares one shape: the
code REFUSES rather than guessing, and the refusal comes back as a named gap in
the response. Adding any of them is a human step, like the ITR schemas.

| what | where it is refused | why it cannot be derived |
|---|---|---|
| minimum wage for §12 of the Bonus Act | `domain/payroll/bonus.py` | per state, per scheduled employment, per skill grade, revised twice yearly. §12 computes on ₹7,000 **or the minimum wage, whichever is HIGHER** — treating ₹7,000 as the ceiling underpays by half in most states |
| SBI's rate for Rule 3(7)(i) | `domain/payroll/perquisites.py` | published by the bank on the first day of the previous year |
| ESIC reason codes | `domain/payroll/esic.py` | ESIC's own list |
| an earlier year's total income for §89 | `domain/payroll/arrears.py` | comes off the employee's return; the employer never held it |
| prior gratuity / leave exemption used | `gratuity.py`, `leave_encashment.py` | §10(10) and §10(10AA) are LIFETIME limits across employers |
| a vendor's MSMED classification | `vendors.msme_status`, surfaced by `public.schedule_iii_ageing` | it is a fact about the SUPPLIER — their Udyam registration — that no ledger holds, and it is not presentational: §43B(h) (Finance Act 2023, AY 2024-25) disallows a deduction for sums payable to a micro or small enterprise beyond the MSMED §15 limit unless actually paid, so calling an unclassified vendor "Others" changes taxable income. The column has NO default; an unclassified balance is reported beside the payables table, never inside a row |
| the §195 rate for a payment to a non-resident | `domain/tds/residency.py`, refused on the purchase-bill path and named in the register's `statutory_gaps` | §194C, §194J and their neighbours charge, in their own words, sums paid "to a **resident**" — so for a non-resident payee they do not apply at all and §195 does, at rates in force under Part II of the First Schedule by NATURE of income, with surcharge and cess, displaced by the DTAA under §90(2) where a TRC and Form 10F are held. Nature of income × ninety-odd treaties × surcharge band cannot be written from memory, and §206AA's 20% floor has a non-resident carve-out (§206AA(7) with Rule 37BC) that residents do not get. Under-deducting disallows the WHOLE expenditure under §40(a)(i). The vendor's `residential_status` (migration 308) is the human step that routes the deduction to 27Q under Rule 31A(4)(b) and keeps it out of 26Q; the RATE is a second human step that has not been taken |
| which accounts hold unbilled dues | `chart_of_accounts.unbilled_dues_side` + `public.schedule_iii_unbilled_reviews` (migration 305) | both ageing notes end "Unbilled dues shall be disclosed separately", and an unbilled due has no document — having none is what makes it unbilled — so the figure is a BALANCE on accounts somebody marked. No account name decides it: "Accrued Interest" may be income receivable or an expense payable. And the review is a SECOND fact: the markings say which accounts hold them, only the review says there are no others, so an unreviewed client shows no figure rather than a zero that claims it has none |

**§89 also refuses a year the rate registry does not hold**, and that is worth
knowing: `rates_for()` substitutes `LATEST_VERIFIED_FY` for a missing year, and
§89 is a comparison of years AT THEIR OWN RATES — so a substitute makes the
whole relief a fiction that looks entirely reasonable. Since the registry holds
only 2025-26 and 2026-27, §89 does not work for most real arrears until the
earlier years' Finance Acts are added.

### 4. What does NOT need an annual edit

Recorded so nobody goes looking:

- **Due dates.** `services/compliance_engine.py` derives every one from the FY
  by rule, not from a table. It needs touching only when a date is *changed* —
  a CBDT or CBIC extension notification — never as routine.
- **GST rate slabs.** Rates are per-line on the document, not a central table.
- **The FY label itself.** Derived from the date (`ist_fy_label`), never stored
  as a constant.
- **Depreciation.** Schedule II rates come from the asset register's own
  configuration, not a statutory table in code.

## Code rules — always follow

- Never hardcode API keys — always use .env files
- Every financial calculation must have a corresponding unit test
- All GST/ITR logic must have a comment citing the relevant section of the CGST Act or IT Act
- Before any government API call, add comment: # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
- Zero business logic in the frontend. Computation, validation and statutory rules live
  in `apps/api`. (This is about logic, not about data access — see below.)
- All API responses must follow: { success: bool, data: any, error: string | null }
  (`models/common.api_response`)

## The frontend's second data path

The frontend does **not** reach the database only through FastAPI. Roughly 320
`.from("…").select(…)` calls across ~100 files read and write ~83 tables directly via
PostgREST. That is why:

- `rbac()` never runs on those calls — the only access check is RLS. Role-aware write
  policies (migrations 260/261) exist for exactly this, and
  `tests/test_direct_write_tables_are_role_guarded.py` tracks which tables are still
  unguarded.
- **Renaming or dropping a column can break the frontend while backend CI stays green.**
  `tests/test_frontend_columns_exist_pg.py` parses those select lists and checks them
  against the real schema. Run it when you touch a migration.

## Tenancy and access

- `firm` is the tenant, `client` is the accounting entity. Every row carries `firm_id`;
  every report and filing is client-scoped.
- The service-role key **bypasses RLS**, so the app-layer `.eq("firm_id", …)` filter is
  the primary isolation control, with firm-scoped RLS policies as defence in depth.
  Never write a query that omits it.
- With `USE_USER_JWT` on, requests run as `authenticated` (anon key + caller's JWT) and
  RLS is genuinely enforced on the API path too.
- RBAC: `Partner > Manager > Executive > Reviewer > Client`
  (`core/permissions.py`, applied as `rbac(resource, action)`).

## Reporting performance — the rule, not a preference

**No report may fetch rows proportional to transaction volume.** What crosses the
wire must be proportional to the size of the ANSWER, not the size of the ledger.

This is not style. Measured in production on one client with 12,836 entries /
32,936 lines: profit-loss 2.15s, trial-balance 2.06s, **cash-flow 54.34s** —
same client, same request. The three fast ones read `account_period_balances`,
132 pre-aggregated monthly buckets. The slow one shipped every line to Python
and looped. Over that client's full history it could not finish inside
`lib/api`'s 45-second abort at all, and the abort is deliberately never retried.

A report reads exactly one of:

- **a pre-aggregated table maintained by triggers** — `account_period_balances`
  (migrations 227/228) is the worked example. Right for running balances and
  anything bucketable by month;
- **a SQL function that aggregates server-side** and returns finished rows —
  `public.cash_flow_report` (migration 277) is the worked example. Right where
  the logic is per-row and cannot be pre-bucketed: AS-3 classification needs
  each entry's legs TOGETHER, which a monthly per-account total has thrown away.

Fetching raw rows and computing in Python is the third option and it is not
available. `apps/api` runs on Render in Singapore and Postgres is in Mumbai, so
every page is a cross-region round trip; the old cash-flow path made thirteen of
them to produce a document about thirty rows long.

**When a rule has to exist in SQL, MOVE it — do not copy it.** Two
implementations drift. Where a Python one must survive for mock mode and local
dev (there is no `DATABASE_URL`; the in-memory source has no SQL functions), the
two are pinned by a parity test that runs every scenario through both and
asserts they are identical — `tests/test_cash_flow_sql_parity_pg.py`. Adding the
second implementation without the parity test is the thing not to do.

Aged receivables and payables were next, and are now built BOTH ways, because
they are two different answers. The **Schedule III ageing schedules** are
twenty-four numbers, so they are a SQL function — `public.schedule_iii_ageing`
(migration 303), with `domain/reporting/ageing.py` as its mock-mode twin and
`tests/test_schedule_iii_ageing_parity_pg.py` holding the two identical. The
**per-document AR/AP ageing** (`ar_aging`, `ap_aging`) lists one row per open
document, so its answer genuinely is a row set; migration 278 made
`outstanding_paise` a generated column precisely so the FILTER could move into
the query, and what crosses the wire is what is OWED rather than everything ever
billed. Both obey the rule. Which shape a report needs is decided by the size of
its ANSWER, not by the table it reads.

## Bank data — the Account Aggregator is the only way in

Statement upload (CSV/XLSX, parsed server-side in `domain/banking/normalizer.py`)
is how bank data enters the platform today, and it is not going away. When a live
bank feed is built, it goes through India's **Account Aggregator** framework and
nothing else.

- **Register as an FIU** (Financial Information User). Banks are FIPs; a licensed
  AA — Finvu, OneMoney, CAMS Finserv, NADL, Anumati — brokers consent between
  them under RBI regulation, on ReBIT schemas. Go via a TSP (Setu, Perfios,
  Finbox, Digio) rather than building FIU plumbing directly.
- **The consent is the CLIENT's, not the CA's.** The account holder consents, and
  it is time-bound, purpose-bound and revocable. So the flow is "CA requests →
  client approves → CA sees data", with a re-consent path when it lapses. That is
  a different shape from every other screen in the app, where the CA acts alone.
- **Never screen-scrape net banking.** No credential capture, no stored bank
  logins, no third party that works that way. It breaches bank terms and RBI
  moved the industry onto AA precisely to end it. This is not a performance or
  cost trade-off to revisit.
- **AA is additive, not a replacement.** Co-operative and smaller regional banks
  are patchy as FIPs — Cosmos Bank, say — and plenty of clients will not consent.
  Upload has to keep working, at parity, for years.

Do not model the feed on QuickBooks or Xero: their bank feeds run on
Plaid/Finicity/direct OFX, which do not serve Indian banks, and Intuit withdrew
QuickBooks from India in 2023.

## Tests

Backend, from `apps/api`:

```
pytest tests/ -v                      # the mock-mode suite (~7,000 tests, no DB needed)
pytest tests/test_foo.py -v           # one module
```

Real-Postgres tests are named `test_*_pg.py` (plus `test_migrations_apply.py`). They
self-skip unless `HARNESS_PG` is set and `psql` is on PATH:

```
HARNESS_PG="host=127.0.0.1 port=5432 user=postgres password=postgres" \
  pytest tests/test_migrations_apply.py tests/test_*_pg.py -v
```

Frontend, from `apps/web`: `pnpm lint`, `pnpm exec tsc --noEmit`, `pnpm test`,
`pnpm build`.

## CI

Two **required** status checks on `main`, both in `.github/workflows/backend-ci.yml`:

- `pytest — mock mode (Python 3.11)`
- `migration apply — real Postgres 16`

Never add a `paths:` filter to the `on:` block of a workflow carrying a required check.
A path-filtered workflow does not run when the filter misses, the check never reports,
and GitHub treats that as pending forever — which makes unrelated PRs unmergeable with
no failing check to point at. Filter inside, in the `scope` job, as these workflows do.

## Migrations

- `apps/api/migrations/NNN_name.sql`, sequentially numbered from 001. Check
  `ls apps/api/migrations/` for the next free number rather than trusting a
  figure written down anywhere — including here.
- **Merging a migration to `main` applies it to the production database.** The
  `apply pending migrations — production` job runs `scripts/db/apply_migrations.py`
  against the live Supabase project on every push to `main`, once tests and the
  migration ratchet pass. There is no manual review step in between. See
  `docs/deploy-migrations.md`.
- `core/schema_guard.py` is the boot-time backstop: it surfaces code/schema drift loudly
  instead of letting writes fail silently behind broad `try/except`.

## Deployment

- API → Render, Docker, **Singapore region**. It must stay near the Mumbai Supabase; the
  reasoning and the measurements are in `render.yaml` and Render cannot move a service
  between regions.
- `apps/web` and `apps/marketing` → two separate Cloudflare Pages projects.
- `render.yaml` must declare every environment variable the backend reads —
  `tests/test_render_manifest_matches_code.py` enforces this in both directions
  (nothing read-but-undeclared, nothing declared-but-unread).
- The daily job sweep is in-process APScheduler (`jobs/scheduler.py`), gated on
  `ENABLE_SCHEDULER`, enabled in exactly one process. On Render's free tier the instance
  sleeps, so `.github/workflows/wake-before-scheduler.yml` pings `/health` across the
  window to keep it alive; the sweep also catches up on jobs whose trigger was slept
  through.

## Where the design is written down

`docs/architecture/01-08` is the authoritative design set — accounting engine, posting
kernel, financial years, opening balances, manual journals, multi-currency, GST engine,
reporting engine. Read the relevant one before changing a subsystem. `docs/audits/` and
the batch completion reports are historical records, not current specs.

## Scope

Well past MVP. Shipped and mounted: accounting/GL, GST (GSTR-1/3B/9, 2A/2B recon,
amendments, ITC reversal), TDS, income tax/ITR, payroll (see below), banking and reconciliation,
fixed assets, inventory, year-end and Schedule III, client and employee portals,
relationship/health/lifecycle intelligence, AI copilot and memory, workflow automation,
Tally migration, and prepare-only e-invoice/e-way/XBRL rails.

Don't infer scope from this list — ask. It is a description of what exists, not a
licence to extend any of it.

**Payroll specifically** is walked end to end in
`docs/audits/2026-09-01-payroll-can-it-run-a-year.md` — what works for a full
year, what does not, and what each remaining gap would cost. The short version:
the monthly cycle, the leaver and the statutory returns all work; what the
software still cannot do is FILE anything, which is deliberate and needs
commercial registrations rather than code.

One rule the settlement makes concrete, because it is easy to get backwards: a
recovery (notice pay, an advance) reduces what the employer PAYS and never
reduces §17(1). Taking notice pay back does not un-earn the salary. The ledger
records what the employer bore; the salary head records what the employee
earned, and the two legitimately differ.

## Not built yet — known, deliberate, and not to be quietly started

Two capabilities the product is expected to grow into. Both are recorded here so
nobody re-derives them from scratch, and so nobody half-builds one as a side
effect of another task. **Neither is in scope until asked for by name.**

### Filing to the government portals through the software

Today PracticeSync **prepares**: it computes GSTR-1 and GSTR-3B from the books,
produces the GSTN JSON, and the CA uploads and signs on gst.gov.in. Filing
through the app is intended, and needs:

- **GSP registration.** GSTN's filing APIs are reached through a GST Suvidha
  Provider; there is no direct public endpoint. That is a commercial and
  compliance step, not a coding one, and it gates everything else.
- **DSC / EVC signing.** A return is signed by the taxpayer's digital signature
  or an EVC OTP to their registered mobile. The signature is the taxpayer's, not
  the firm's — so the flow is "CA prepares → taxpayer or authorised signatory
  signs", which is a different shape from every other screen in the app.
- **The rule in "Code rules" still holds and gets stronger, not weaker.** Never
  auto-submit. Real filing means an explicit confirmation click, per return,
  every time — never a batch, never a scheduler, never a retry that resubmits.
- **Idempotency.** A double-submitted return is not a duplicate row, it is a
  second filing against a live portal. Any real implementation needs the
  reference recorded before the call and checked after a timeout, never a blind
  retry.

Demo filing walk-throughs exist to SHOW these flows before they are real. There
is exactly ONE implementation: the shared filing-demo framework —
`services/filing_demo/` (a flow per statutory filing, GSTR-3B included), served
by `POST /api/filing-demo/{flow}/preview` and rendered by
`components/FilingDemoWizard.tsx`. GSTR-3B used to carry a second, bespoke one
at `POST /gst-workspace/gstr3b/{id}/simulate-filing`; it was the first built and
has been deleted rather than left beside its replacement, because two demos of
one return drift and each needs its own safety argument. They are portal-faithful
in sequence, transmit nothing, write nothing, and every response carries an
honest `SIM-NOT-FILED` reference; any realistic-looking reference they display
is labelled SPECIMEN at the point of display. `ENABLE_FILING_SIMULATION`
defaults **on** — an owner decision of 2026-08-29, reversing the original
default-off, because demo filing is a core product capability and this
deployment records no real filings. The flag is the KILL SWITCH: set it to
`false` on any deployment that records real filings. **When real filing is
built it is a new endpoint and the simulation is deleted** — never repointed at
a live portal, because everything that makes it safe is the fact that it cannot
file.

The genuine path today is unchanged and stays: the CA files on the portal, then
records it here (`PATCH /gstr3b/{id}/status` with `status=submitted`), which
writes the real ARN, the filing date, and the `gst_filings` row that
`journal_period_lock_reason` reads to lock the period.

### Live bank feeds through the Account Aggregator

Fully specified already — see **"Bank data — the Account Aggregator is the only
way in"** above. Nothing about it has been built: statement upload is the only
path in today, and it stays at parity for years regardless.

Restated here only so this list is complete: register as an FIU, go via a TSP,
the consent is the CLIENT's and is time-bound and revocable, and **never
screen-scrape net banking**. Read that section before touching any of it.

## Reporting times to the user

- Always state times in IST (UTC + 5:30), never UTC. This applies to everything you tell the user — CI timings, when a job ran, when a check-in fires, timestamps read out of the database. Convert before reporting; don't make the user do the arithmetic.
- This is a PRESENTATION rule only. It does not change what is stored or scheduled: `timestamptz` columns (e.g. `scheduler_runs.started_at`) are UTC on disk, and GitHub Actions cron expressions — including the daily-sweep schedule in .github/workflows/ and any `create_trigger` cron — are evaluated in UTC. Both are correct; rewriting either to "look like IST" would move when jobs actually run.
- So: convert at the point of reporting. When you show a raw query result or edit a cron line, say which zone that value is in, since the stored value stays UTC.
- Worked example: the daily sweep is nominally 06:00 IST = 00:30 UTC. A run recorded as `2026-08-18 01:36+00` is reported as "07:06 IST" — and that hour of drift is GitHub cron lateness under load, which is what the catch-up in jobs/ exists to absorb.

## Money in the browser — one parser, and only one

`apps/web/lib/money/rupeeInput.ts` turns a typed rupee amount into integer paise
by concatenating the digits, and RETURNS NULL for anything that is not an
amount. Use it for every amount field; there is no longer a second way.

The form it replaced — `Math.round(parseFloat(x) * 100)` — was not merely
imprecise:

- `parseFloat("1,25,000")` is **1**. A CA typing an amount the way Indian
  amounts are grouped recorded one rupee.
- `parseFloat("12abc")` is 12 and `parseFloat("1e3")` is 1000 — neither is an
  amount, both were accepted.
- a blank field gives `NaN`, and `JSON.stringify` sends that as `null`.

All 61 call sites across 28 files are converted. The module also carries
`bpsFromPercentInput` (a typed percentage → basis points) and `parseQuantity`
(up to three decimals, matching `NUMERIC(10,3)` on the line tables), and
`lib/money/lineInput.parseLineAmounts` reads a document line's quantity and rate
together — used by the validator, the preview and the payload, so what a CA is
shown adding up and what is saved are the same numbers.

**Three deliberate exceptions, all in the same place.** `gstLine.ratePaiseFromRupees`
and `computeLineGst` still take the rate STRING and still do
`Math.round(rate * 100)`, and the three purchase-note previews still call them
that way. `shared/gst-parity-vectors.json` pins those to the Python backend on
exactly those strings — including `"1.005"`, which the backend truncates to 100
paise and which the new parser refuses. Converting to paise and dividing back
would put a float round-trip inside the one calculation that is pinned. What
protects them instead is upstream: `parseLineAmounts` has already refused
anything but a plain decimal by the time they see it.

`parseQuantity` is deliberately NOT named `quantityFromInput` — `gstLine.ts`
exports one of those, which COERCES to 0 and is the parity-pinned payload
builder. Two functions with one name in one directory is how the wrong one gets
called.

## Identifiers

- **GSTIN carries a check digit, and the shape regex does not test it.**
  `apps/api/domain/gst/gstin.py` is the authority; `apps/web/lib/gst/gstin.ts`
  mirrors it for keystroke feedback and the two are pinned by
  `apps/api/tests/fixtures/gstin.json`, which both suites read. Enforced where a
  human TYPES a GSTIN — onboarding, the customer and vendor create paths — and
  deliberately NOT in `models.client.validate_gstin`, which guards a Pydantic
  field that 512 invented fixture GSTINs across 95 files flow through.

## Bug fixing

- When the user reports a bug, don't just patch the one instance. Identify the underlying pattern (wrong column name, missing null check, stale label, unapplied migration, etc.) and grep/search the rest of the codebase for the same pattern before calling the fix done. Report what else was found, even if you decide not to touch it.

## Commit messages

Match the existing history. A commit explains **what was wrong**, **what the fix does and
why that shape**, and **how it was verified** — including how many new tests fail against
the previous code (the negative control). State when a change has no live effect yet, and
say so explicitly when there is no migration. Subject line is a plain sentence describing
the behaviour change, not a conventional-commits prefix.
