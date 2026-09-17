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
- **A VOUCHER'S LINES HAVE AN ORDER AND TWO FUNCTIONS RECORD IT** (ACC-16, migration
  384). `journal_lines.line_order` is the zero-based position the line held in the
  jsonb array the posting was called with, read out with `WITH ORDINALITY` by
  `post_journal_atomic` AND by `edit_posted_journal` — the second matters because a
  correction DELETEs every line and re-inserts them, so leaving it alone would have
  lost the CA's order the first time they fixed the voucher, silently. Taking the
  order from the array is what let every posting function stay unchanged: a field
  every caller must set is a field some caller will not. **Nothing already posted is
  backfilled** and that is a decision — migration 251 makes a posted line immutable,
  so a backfill would mean disabling that trigger against production for a DISPLAY
  order. An existing line keeps `line_order` NULL and
  `domain/accounting/line_order.py` orders it at read time: debits before credits,
  then `created_at`, then `id`. That chain is TOTAL, which is the property that
  matters — the same voucher renders the same way on every read. **There is
  deliberately no TypeScript mirror**: the one place a CA sees a voucher's lines is
  `GET /api/accounting/journal/{id}`, and the browser's own `journal_lines` embed
  only SUMS debits. A guard fails if `apps/web` ever mentions the column, because
  PostgREST can express neither "debits before credits" nor a fallback chain as an
  `ORDER BY` and the rule would then need mirroring —
  `tests/fixtures/journal_line_order.json` is already the table for it.
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
- **"Closed" is TWO different things, and which one applies decides who asks.**
  `domain`-side there is one definition, in SQL (migration 361), split by kind:
  `period_closure_reason` is the CA's own deliberate acts — the firm locked the
  financial year, or this client's year-end was finalised — and `period_lock_reason`
  is those two plus *a return covering the date has been filed*, calling the first
  rather than restating it. **The posting kernel asks only the closures**, so nothing
  reaches the GL inside a year somebody closed. The filed-return branch is asked where
  a document that FEEDS a return is written — sales invoices, purchase bills, credit
  and debit notes, and the manual journal, which can move any account including the tax
  ledgers — and by the edit and delete paths (266/275/276). It is deliberately NOT in
  the kernel: GSTR-1 for June is filed on the 11th of July and GSTR-3B on the 20th,
  while June's bank reconciliation happens after both, so a kernel refusal would stop
  every June receipt, payment, bank entry, depreciation charge and payroll accrual from
  the 11th onwards. `services/period_lock_service.py` holds the Python twins, pinned to
  the SQL by `tests/test_period_lock_reason_parity_pg.py`.
  **A RECEIPT IS ONE OF THOSE DOCUMENTS FOR ONE CLASS OF CLIENT, AND THE
  ARGUMENT FOR LEAVING EVERY OTHER RECEIPT OPEN STILL STANDS** (SALES-15).
  Both receipt paths asked only the firm-FY validator, on a recorded argument
  — "a receipt moves Bank and Debtors and touches no output tax" — that GST-15
  falsified by half: for a client marked `gst_advance_tax_applicable`, CGST
  §13(2) charges tax on an advance for SERVICES when it is RECEIVED, so the
  receipt is declared in GSTR-1 Table 11A and discharged in GSTR-3B Table
  3.1(a). `receipt_service._assert_open_where_a_receipt_feeds_a_return` asks
  the lock for exactly those clients. **It is UNCONDITIONAL on the receipt's
  own shape**, the fixed asset's reasoning below: gating on whether the receipt
  leaves an unallocated balance would be wrong twice, because
  `table_11_sections` measures what was adjusted BY THE PERIOD END off the
  ALLOCATION's `created_at` — so a back-dated receipt allocated in full today
  has no allocation dated inside June and its whole amount lands in June's 11A
  — and a receipt with no rate or place of supply is NAMED in that return's
  `gaps`, which is also part of what was filed. **Every other client is
  untouched and that is the point**: Notification 66/2017-Central Tax removed
  the charge on advances for GOODS, the flag is off by default, and recording a
  20 June payment on 15 July stays an ordinary thing to do.
  **A FIXED ASSET is one of those documents.** `create_asset` asked only
  `period_validation_service.validate_posting_date` — firm-FY, no client_id, so
  it cannot see a filed return — while `correct_asset` and `delete_asset` both
  called `assert_open` and always had. A CA could create a June asset after
  June's GSTR-3B was filed and then be refused when they tried to fix it, and
  create-but-not-correct cannot be right whichever way the rule should fall.
  It falls on `assert_open` because the acquisition journal debits `%GST Input%`
  from `itc_claimable_paise`, which feeds Table 4(A) — a capitalised purchase
  IS a document that feeds a return. Unconditional rather than gated on whether
  ITC was recorded: a rule that depends on the order two fields are filled in
  is not a rule. Depreciation's own refusal is separate, deliberate and
  test-pinned; that one is an owner decision to re-take, not a bug to swap.
- **A journal line's account belongs to the entry's own firm and client**, enforced by a
  statement-level trigger on `journal_lines` (migration 360) rather than inside each
  posting function — `account_id` carries only a global FK to `chart_of_accounts(id)`,
  so before it every account id in the database satisfied it. A `chart_of_accounts`
  row with `client_id IS NULL` is a firm-level account and is allowed on any of that
  firm's entries.
- **What a document still has OPEN is `outstanding_paise`, and the note columns'
  signs are not guessable from their names.** Migration 278 put it on
  `client_sales_invoices` and `purchase_bills` as `GENERATED ALWAYS ... STORED`
  precisely so the formula lives once, in the schema — read the column, do not
  re-subtract. `total - paid` is a DIFFERENT figure: it omits the CGST §34 note
  terms, and **migration 210 added the INCREASE document to both sides at
  once**, so `credit_note_paise` ADDS on `purchase_bills` while `credited_paise`
  SUBTRACTS on `client_sales_invoices` (`debit_note_paise` adds on invoices,
  `debited_paise` subtracts on bills). Four places in the bank module computed
  this and two had it wrong; both bank paths now go through
  `domain/banking/matcher.invoice_open_paise` / `bill_open_paise`, which read the
  column where the row came from Postgres and transcribe 278's expression where
  it did not (mock mode, the in-memory doubles). A settlement candidate carries
  BOTH figures — `amount_paise` is the document's face value, `outstanding_paise`
  what is left — because `FindMatchModal` renders "· ₹X open" only when the two
  differ. **And every piece of MATCHING ARITHMETIC runs on the second**
  (BANK-10): `matcher.candidate_open_paise` is the one definition, read by the
  fetch band, the in-memory re-test, `rank_suggestions` and
  `candidate_search.search` alike. The ranker was the last place still
  subtracting the FACE value, so a ₹1,18,000 invoice half settled by an advance
  and cleared by a ₹59,000 credit came out "short by ₹59,000" — outside the 25%
  band, so offered nowhere, on the commonest settlement an Indian practice sees.
  Two things fall out of it and both are deliberate: the old +15 "matches
  outstanding balance" bonus is GONE, because it now restates `difference == 0`
  exactly and a term restating its own branch only inflates documents that
  happen to carry the column; and a bank line LARGER than what is open is no
  longer offered by the ranker at all, because offering it invites an allocation
  bigger than the document can take — the unbanded search still finds it and
  says the line is larger, which is what that screen is for. `None` means the
  face value IS the open figure, which is true of the three candidate kinds that
  carry no such column.
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
- TDS return (24Q salary / 26Q residents / 27Q non-residents — Rule 31A(2) sets one due date per quarter regardless of form): Q1 31 Jul, Q2 31 Oct, Q3 31 Jan, Q4 31 May. Q4 is the exception — it is NOT the end of the month following quarter end (that would be 30 Apr). services/compliance_engine.py::tds_return_due_date is the authority; keep any prose in step with it. **The DUE DATES above survive the 2025 Act unchanged. The FORM AND SECTION NUMBERS do not — see the next bullet.**
- **From 01-04-2026 the whole TDS vocabulary changed, and `domain/tds/vocabulary.py` is the single place that knows it.** The Income-tax Act 2025 with the Income-tax Rules 2026 (CBDT Notification 22/2026, 20-03-2026, G.S.R. 198(E), plus a corrigendum) renumbered the statements — **24Q→138, 26Q→140, 27Q→144, 27EQ→143** — and the certificates — **Form 16→130** (three parts now), **16A→131** (quarterly now), **26AS→168**, **15G/15H→121**. It also collapsed the sections: **192→392**, the whole **194-series→393(1)**, **195→393(2)** (NOT 400 — one widely-copied source has that wrong), TCS→394, and returns now carry numeric payment codes 1001–1067. **Rates and thresholds are unchanged**, so `section_rates.py` holds right numbers under 1961-Act keys — and it stays that way. **This is a FORK, not a migration.** The transition is **by EVENT — credit or payment, whichever is earlier** — so periods up to 31-03-2026 keep the old forms and sections indefinitely, including belated and revised returns; both vocabularies are permanent. `act_for_date` is the definition and `act_for_fy` is derived from it, sound because commencement is exactly an FY boundary. **Translate at the boundary, never rekey a store**: ask the module where a form number or section code is emitted, and leave every rate lookup, stored challan and test on the 1961 keys. **There are TWO such boundaries on a quarterly statement and for a while only one was translated** — `tds_return_service` resolved the FORM through the vocabulary and left every deductee line's `section` as stored, so a FY 2026-27 26Q came back as Form 140 with each line citing 194J, a section that Act does not contain (TDS-17). The label now goes out as `section` and the stored 1961 code travels beside it as `section_1961`, which is load-bearing rather than decorative: s. 393(1) has no reverse, so a reader given only the label cannot recover the section that produced it — and `lib/data/tds.ts` writes the whole payload into `tds_returns.fvu_json`. A section the 2025 Act has no code for (s. 192A, say) keeps its stored code and is named in `statutory_gaps`; it is never guessed into 393(1). Challan matching accepts BOTH labels in every period — a challan records what somebody typed, not which Act governs the quarter. Three refusals are deliberate: the **s. 393 payment-code table is not held** (a wrong code is accepted and then wrong — a human step, like the ITR schemas), **s. 393(1) has no reverse**, and **a form cannot be asked for without a period**. ITR-1..7 are NOT renumbered — AY 2026-27 is still the 1961 Act. Verified 2026-09-04; see `docs/compliance/03-income-tax-and-tds.md`.
- **A TDS threshold is a TRIGGER, not a deductible allowance, and most of the
  §194 series aggregates over the year.** §194C(5) charges where "the aggregate
  of the amounts of such sums credited or paid ... exceeds one lakh rupees", and
  §§194A/194D/194G/194H/194J carry the same "aggregate of the sums" limb. So
  crossing the limit does not exempt the earlier payments — it makes them due,
  and the charge is on the WHOLE aggregate. The bill that crosses carries the
  year's tax; every bill after it credits what was already withheld (§200), or
  the same aggregate is taxed again and again. `domain/tds/section_rates.py`
  holds which sections have an aggregate limb and `resolve_tds` takes BOTH
  `fy_prior_taxable_paise` and `fy_prior_tds_paise` — a caller passing the first
  without the second re-charges the growing aggregate on every later bill.
  **§194I and §194B deliberately have no aggregate**: §194I's limit is per month
  or part of a month, and FA 2025 made §194B per single transaction, so an FY
  aggregate on either would deduct where the statute does not charge.
  **§194Q is the one section charged on the EXCESS** — §194Q(1), "0.1 per cent
  of such sum exceeding fifty lakh rupees" — carried on the rule as
  `charge_on_excess_only` so the engine never tests a section by name. Its ₹50
  lakh is both limbs at once ("the value OR AGGREGATE OF SUCH VALUE"). What this
  engine does NOT decide for §194Q is whether it applies: the first proviso
  binds only a buyer whose own turnover exceeded ₹10 crore in the preceding FY,
  and no client turnover figure reaches it — the CA marks the vendor.
- **§115BAC DISAPPLIES CHAPTER XII-BA, and the AMT surcharge ladder is the
  ASSESSEE's own.** `compute_amt` had no regime parameter (IT-21), so it could
  not express the disapplication at all, and it passed
  `entity_rates.firm_surcharge` — the single 12%-above-₹1-crore bracket — for
  every non-corporate assessee (IT-07), surcharging an individual at a firm's
  rate: at ₹6 crore of adjusted total income the individual ladder is 37% and
  the difference is 25 percentage points of the minimum tax. Both are LATENT —
  `itr_engine`'s only AMT caller is the firm/LLP branch — and both are fixed
  because the branch that reaches them is one entity type away. **A FIRM OR LLP
  IS OUTSIDE §115BAC**, which reaches only an individual, HUF, AOP, BOI or
  artificial juridical person, so `regime="new"` cannot waive their AMT and the
  ladder stays the firm's. The two interlock: an individual who reaches the
  charge is on the OLD regime by construction, so the new regime's surcharge
  cap never applies and the full ladder is theirs. ⚠️ The disapplying provision
  is `[S]`-graded on its CITATION and not its effect — §115JEE cross-refers to
  the §115BAC option and the Finance Act 2023 restructured §115BAC so the
  option became the one to LEAVE the regime; which sub-section it now names
  could not be read. The rule is written as the effect, with the sub-section
  deliberately not guessed.
- **THE FOUR REINVESTMENT SECTIONS ARE NOT ONE RULE WITH FOUR NAMES** (IT-19,
  migration 385). `capital_gains_engine` computed the gain, the holding period
  and the rate and stopped, so on a house sale — where the whole gain is
  routinely exempt — the register showed tax on a gain the client may not owe
  tax on at all. `domain/income_tax/reinvestment_exemption.py` is the
  authority. **§54 exempts the LOWER of the gain and the cost; §54F is
  PROPORTIONATE** — gain × cost ÷ NET CONSIDERATION — so on a ₹1 crore sale
  with a ₹40 lakh gain and a ₹50 lakh house, §54's rule would exempt ₹40 lakh
  and §54F exempts ₹20 lakh; applying the wrong one halves the tax.
  **§54EC's ₹50 lakh spans the year of transfer AND the year after it
  together** (the second proviso), so reading it as a per-year cap doubles the
  exemption; its window is six months, and from 01-04-2018 it reaches only land
  or building — a transfer before that keeps the wider section, the fork shape
  again. **§54B is the one section a SHORT-TERM gain reaches**, because its
  charging words describe the USE of the land in the two preceding years rather
  than a holding period. The Finance Act 2023's ₹10 crore ceiling applies to
  §54 and §54F from FY 2023-24 only. **Three facts are refused and NAMED, never
  guessed**: what was SOLD (`capital_gains.transferred_asset_nature` — the
  register's `asset_type` cannot tell a residential house from a plot), how many
  other houses the assessee owned (§54F's own condition) and whether the land
  was farmed (§54B's). **No exemption amount is stored** — the caps move by
  Finance Act, so it is derived on every read, the same reason migration 278
  made `outstanding_paise` generated. **The individual-or-HUF test is its own
  tri-state and NOT `capital_gains_engine.ASSESSEE_TYPES`**, whose `other` means
  "not a RESIDENT individual or HUF" — a NON-RESIDENT individual falls there and
  §54 reaches them perfectly well. The fraction FLOORS, because the exemption is
  what tax is not charged on. ⚠️ Every figure and window is `[S]`-graded: egress
  is refused here, incometax.gov.in included, so a test pins each constant
  exactly and the screen says so.
- **An estimated Cost Inflation Index says so, and is not written into the
  register.** The CII for a year is notified partway through it, usually around
  June, so `cii_for` legitimately falls back for a sale in the first weeks of a
  year — and the fallback UNDERSTATES the indexed cost and OVERSTATES the gain.
  `cii_is_notified` is the question `cii_for` cannot answer (it returns an int
  either way), `CapitalGainsResult.indexation_is_estimated` carries it — a
  DIFFERENT fact from `is_slab_rate_estimate`, which is about the rate — and it
  is stamped once at `compute_capital_gains`'s entry rather than on each of the
  eight branches, because it is a property of the two DATES. The estimator
  still answers, flagged. The REGISTER stores `indexed_cost_paise` as NULL
  instead (the column is nullable): nothing recomputes a stored row, so a
  figure taken from an unnotified year is wrong the moment the notification
  lands, and an absence a CA can fill in beats a stale number that reads as
  computed.
- **A filing cannot leave draft on a computation nobody has reviewed.**
  `POST /api/itr/snapshots/{id}/review` existed from the start and had NO
  CALLER (IT-30), so every `tax_computation_snapshots` row was permanently
  `draft` — while the computation screen already rendered a green tick for
  `reviewed`, a state it had no way to reach. The screen marks one reviewed
  now, and `itr_workflow.transition_itr_status` reads
  `itr_filings.computation_snapshot_id` on the way OUT OF DRAFT only (re-asking
  in review would block the review → draft step a reviewer uses to send a
  return back). **A filing that pins NOTHING is allowed through**: the column is
  nullable and a CA who computed outside the product has no snapshot to pin, so
  refusing would make the pin mandatory by accident.
- **A RETURN OF INCOME HAS THREE KINDS, AND `itr_filings` HELD ONE** (IT-23,
  migration 381). §139(1) is the ORIGINAL, §139(5) the REVISED and §139(8A) the
  UPDATED return (ITR-U) — and the table could not have carried a second one
  whatever the code did, because migration 319 declares
  `UNIQUE (firm_id, client_id, financial_year, itr_form)`. A revised return
  sits BESIDE the original: the original's acknowledgement number and date are
  fields on the new return's own form. 381 narrows that constraint to
  `WHERE return_type = 'original'` and adds no uniqueness to the other two —
  §139(5) expressly allows a revised return to be revised again, and
  §139(8A)'s once-only bar is about a return FURNISHED, which a constraint
  cannot tell from a draft, so `itr_workflow.already_furnished_updated_return`
  WARNS instead. **`domain/income_tax/return_type.py` is the authority** and
  `GET /api/itr/return-kinds` serves it, so the filing screen holds labels and
  no dates. The earlier receipt is READ off the original where this product
  prepared it (the `domain/tds/deductor.resolve` shape) and REFUSED where
  nobody holds it. ⚠️ **The two windows and §140B's bands are `[S]`**: §139(5)
  is 31 December of the AY and NAMES the completion-of-assessment limb it
  cannot see, §139(8A) reports BOTH the 48-month (Finance Act 2025) and
  24-month dates and answers `is_open = None` where they disagree about today,
  and §140B's 25/50/60/70 table is `verified=False` throughout and **REFUSES an
  assessment year it does not hold** rather than falling back — the trap the
  FY-versioned registries have, on money a client pays over.
- **THE PAYROLL ACCRUAL HAS TWO DEBITS, AND THE EMPLOYER SHARE COMES OFF THE
  SLIPS** (PAY-25). Schedule III Division I Part II presents Employee Benefits
  Expense as (a) salaries and wages, (b) contribution to provident and other
  funds, (c) share based payments and (d) staff welfare. `_build_payroll_lines`
  posted ONE debit for gross PLUS the employer's 12% PF, EDLI, the EPF
  administrative charge and the employer's 3.25% ESI, so **(b) was nil on every
  payroll client's note and (a) was overstated by exactly the contribution** —
  and the split cannot be recovered afterwards, because one posted debit
  carries no record of how much of it was contribution and a posted journal
  cannot be rewritten (migration 251). It has to be two lines at the moment of
  posting or it is not recoverable at all. Salaries takes **gross** (§17(1));
  `Contribution to Provident and Other Funds` (5016, migration 375) takes the
  employer side. The **administrative CHARGE is a fee, not a contribution**,
  and is grouped there anyway because it is remitted on the same challan and is
  universally presented with PF. **The employer share is summed off
  `payroll_slips`, paged** — `payroll_runs` stores only the COMBINED
  `total_pf_paise` / `total_esi_paise` and has no column for either employer
  half, so reading the slips is the only way, and it also means an old run
  finalised after the change splits correctly with no cached figure to drift.
  **The subtype `Employee Benefits` is load-bearing**: `schedule_iii.classify`
  buckets on it, so both accounts land under one caption and the P&L total is
  unchanged — only the note's sub-split moves, which is what makes this safe
  against books already holding one-line entries. **The range guard became an
  EXACT identity** (`gross + contribution == sum(credits)`), because the debit
  is no longer defined as sum(credits) and the kernel's balance check does its
  job again — it caught a fixture on the first run whose `total_net_paise` had
  deducted BOTH halves of the 12% from the employee's pay. Deliberately NOT
  extended to `_build_settlement_lines`: a leaver's F&F payload carries no
  employer contribution at all, so there is nothing there to split.
- **THE STATUTORY BONUS IS AN ANNUAL DEBT AND THE PRODUCT COMPUTED IT ONLY FOR
  LEAVERS** (PAY-23, migration 395). `domain/payroll/bonus.py` has implemented
  the Payment of Bonus Act 1965 since the payroll module was built, and its one
  caller was a leaver's settlement — so a client's CONTINUING employees, which
  is all of them most years, were never computed for. §10 makes the minimum
  payable "whether or not the employer has any allocable surplus", §19 makes it
  due within eight months of the accounting year's close and §28 makes
  non-payment an offence: it is a liability the balance sheet owes.
  `domain/payroll/bonus_register.py` is the register and calls `bonus.compute`
  rather than restating any of its sections. **EVERY EMPLOYEE APPEARS,
  INCLUDING THE ONES THE ACT DOES NOT REACH**, each with its own reason —
  §2(13)'s ₹21,000 ceiling, §8's thirty days, §9's forfeiture — because a
  register that silently drops them cannot be checked against the payroll.
  **§19's date is DERIVED from the year's own close**, not stated as 30
  November, so a client whose accounting year is not the financial year gets
  their own; the proviso allowing an extension on application is NAMED rather
  than assumed.
  **THE SERVICE READS THREE COLUMNS THAT EACH HAVE AN OBVIOUS WRONG
  NEIGHBOUR.** §2(21) salary is `basic_paise` plus DA and NOT the slip's
  `gross_paise`, which carries every allowance the section excludes; a month
  worked is a RELEASED run (PAY-04's reasoning — a draft has paid nobody, and
  here it would put a month of salary into a statutory debt); and §8's count is
  `attendance.days_present`, days ACTUALLY worked, not `working_days`, which is
  the establishment's days in the month. **An unrecorded working-day count is
  read as NEITHER nil NOR thirty**: nil would disqualify every employee at a
  client who runs payroll without attendance and hide the debt, thirty would
  assert a fact nobody holds — so the figure is shown, the employee is named,
  and the gap travels on the LINE as well as the summary.
  Migration 395 stores only what no ledger holds: the employer's own §10/§11
  rate (defaulted to the §10 minimum, which is owed whatever the surplus turns
  out to be) with §12's minimum wage, and §9 dismissals **CHECKed to the Act's
  five grounds** — a free-text reason would let "poor performance" forfeit a
  statutory debt, which §9 does not reach. ⚠️ **One §12 minimum wage per
  client-year is a stated simplification** (the section compares per SCHEDULED
  EMPLOYMENT and per skill grade) and the wage TABLE itself remains the human
  step §3b records. Nothing is posted — the provision is a journal the CA
  raises — and Form C (Rule 4(c)) and Form D (Rule 5) are named rather than
  produced.

- **A DRAFT payroll run has deducted nothing** (PAY-04).
  `_tds_already_deducted_this_fy` and `_members_contributing_earlier_this_period`
  read `payroll_runs` with no status predicate while every other reader has
  filtered on `_PAYROLL_RELEASED` (`finalized`, `paid`) since migration 323 made
  RLS agree. Reading a draft credits the employee with §192 tax nobody withheld,
  so the month's withholding comes out too SMALL — and §192(1) makes the
  EMPLOYER liable for the shortfall with §201(1A) interest — and it keeps
  somebody in ESI past the ₹21,000 ceiling on a contribution that never
  happened.
  **AND THAT RULE IS WHAT MAKES A DRAFT REBUILDABLE** (PAY-21, closed
  17-09-2026). `POST /api/payroll/runs/{run_id}/recompute` deletes the slips
  and rebuilds them, and `DELETE /api/payroll/runs/{run_id}` throws an
  unreleased run away so migration 237's unique index stops making the month
  permanently uncreatable — without either, a run computed before the
  attendance was entered could only be fixed against the database, and
  reversing a finalised one reopens it at `review` with the SAME slips.
  Both are safe precisely because a draft has posted no journal, registered no
  §192 TDS and recorded no loan recovery, and because the two readers above
  count only RELEASED runs, so a rebuild cannot disturb what an earlier month
  withheld. `create_run`'s slip-building body is `_compute_and_store_slips` and
  BOTH doors call it — two copies would be two payrolls that agree until one is
  changed. A finalised or paid run is refused with a 409 naming the reversal
  path. **`_PAYROLL_UNRELEASED` is its own tuple and NOT the inverse of
  `_PAYROLL_RELEASED`**: the two answer different questions — which runs COUNT,
  and which have not yet paid anybody — and writing either as "not the other"
  would make a fifth status silently join both.
- **A FIRST depreciation posting may start at any month and now says what that
  forecloses** (FA-04). `depreciation_posted_through` only moves forward, so an
  asset bought in April and first depreciated in December loses April–November
  permanently: the single-month path 409s on them, the range runner skips them,
  and reversal reaches the last month only. Starting late is nonetheless RIGHT
  and test-pinned — an asset brought over from Tally mid-life already carries
  its accumulated depreciation and its first posting here is whatever month the
  CA takes over in, so refusing the skip would refuse every migrated asset.
  So it WARNS: `foreclosed_months` names them and the notice says to reverse
  and restart if the asset was acquired here. Same shape as Rule 46(b)'s
  invoice-number sequence gap, for the same reason.
- **AN ASSET UNDER CONSTRUCTION IS NOT IN THE REGISTER, AND THAT IS THE FIX**
  (FA-11a, migration 397). `fixed_assets` was the only place an asset could
  live and everything in it is depreciated, so a client building a factory
  either left it out — a balance sheet short by the whole of what had been
  spent — or put it in and had depreciation charged on something not ready for
  use, which overstates the expense, understates the asset and understates
  every later year's charge because the written-down value starts lower. AS-10
  paragraph 20 and Schedule II both start depreciation when the asset is
  AVAILABLE FOR USE. `domain/fixed_assets/cwip.py` is the rule,
  `services/cwip_service.py` fetches and posts, `routers/cwip.py` decides
  nothing — and it is a SEPARATE router deliberately, because mounting it on
  `/api/fixed-assets` is what makes the next reader reach for
  `_SCHEDULE_II_PART_C`.
  **AND IT IS A DISCLOSURE, NOT A CONVENIENCE.** MCA G.S.R. 207(E) of
  24-03-2021 — the SAME notification behind the two ageing schedules migration
  303 built — gives capital work-in-progress its own line under Non-current
  assets immediately after PP&E, an **ageing schedule** (<1y / 1-2y / 2-3y /
  >3y, split between *projects in progress* and *projects temporarily
  suspended*), and a **completion schedule** for every project overdue against
  its originally approved completion date OR over its originally approved cost.
  **`capital_wip` HAS BEEN A DECLARED YEAR-END LINE SINCE `year_end_lines.py`
  WAS WRITTEN and nothing could ever reach it** — no caption resolved there —
  so the year-end balance sheet carried a structurally nil CWIP line for every
  client. That is the half nobody could have seen.
  **THE AGEING AGES MONEY, NOT PROJECTS**, which is why the cost is
  `cwip_additions` with one row per tranche and its own `incurred_on`: a build
  begun three years ago whose last contractor bill arrived last month has
  amounts in three bands at once, and a project-level date would put all of it
  in the oldest. Exactly one year falls in the SECOND band — "less than 1 year"
  means less than — and months are counted on the calendar rather than days, so
  the answer cannot disagree with itself across a leap year.
  **SUSPENSION MOVES THE ROW AND NEVER THE BALANCE**: it is presentational, and
  reading it as a removal would take the cost off the balance sheet, which is a
  write-off nobody decided. **The schedules are AS AT A DATE** — a project
  capitalised in June is CWIP in a 31 March note and a fixed asset in a 30
  September one, which is why `capitalised_on` is recorded rather than the row
  deleted, the same discipline `stock_position_as_at` applies to stock.
  **TWO FACTS ARE REFUSED RATHER THAN GUESSED and both directions of the guess
  are wrong**: `approved_completion_date` and `approved_cost_paise` are
  nullable with no default, because defaulting the date to the project's start
  reports every project overdue on day two and defaulting the cost to what has
  been spent reports none over budget ever; a project with neither is NAMED as
  undeterminable. A reportable project with no `expected_completion_date` is
  named too rather than bucketed — a row in "more than 3 years" because nobody
  said otherwise states something false.
  **CAPITALISATION CREATES THE ASSET AND IS ONE WAY**: cost = the accumulated
  tranches (each carrying its §17(5)-blocked tax, AS-10 paragraph 9 — the same
  sentence AS-2 paragraph 6 applies to stock), `put_to_use_date` = the date it
  became ready, and `purchase_date` the SAME date rather than the project's
  start, or the register would charge three years of depreciation the moment
  it is capitalised. `acquisition_mode` is deliberately left NULL (every
  payment already happened on the tranches) and the trace lives on
  `capital_work_in_progress.capitalised_asset_id`. The account is code **1504**
  with subtype `Capital Work-in-Progress`, and the SUBTYPE is load-bearing:
  `schedule_iii.classify` buckets on it and the CWIP branch is tested BEFORE
  the tangible one, because "Capital Work in Progress - Plant" contains
  "plant".
- **The Finance (No. 2) Act 2024 forked capital gains on 23-07-2024, and it is
  the DATE OF TRANSFER that decides.** §111A 15%→20%, §112A 10%/₹1,00,000 →
  12.5%/₹1,25,000, §112 20%-with-indexation → 12.5%-without, and §2(42A)'s
  holding periods moved — a non-property, non-listed asset needed **36** months
  before that date, not 24. A transfer before it is governed by the earlier law
  indefinitely, the same "fork, not migration" shape as the TDS vocabulary, and
  the register holds real historical transfers. §2(42A) also runs to the day
  **immediately preceding** transfer, so the test is `sale > purchase + N
  months`, not a whole-month count. The fifth proviso to §112(1) — the lower of
  12.5% without indexation and 20% with it — reaches only a **resident
  individual or HUF**, only immovable property, and only property acquired
  before the cutoff; `domain/income_tax/capital_gains_engine.py` withholds it
  and says why rather than granting it by default. **FY 2024-25 straddles the
  fork**, so `statutory_rates.FYTaxRates` (one CG rate set per FY) cannot
  represent that year — it holds only post-fork years today, and adding 2024-25
  needs pre/post buckets, as the ITR form itself splits them.
- **A FIRM PAYING ITS OWN PARTNER DEDUCTS UNDER §194T, AND A SECTION WITH NO
  RESIDENT LIMB IS A THIRD STATE** (TDS-23). §194T was inserted by the Finance
  (No. 2) Act 2024 w.e.f. 01-04-2025 — `section_rates.py`'s FIRST year, whose
  header claims that very Act — so its absence was a hole in a year marked
  `verified=True`, and every partnership and LLP client has the obligation.
  10%, **both limbs at ₹20,000** ("such amount OR THE AGGREGATE"), NOT on the
  share of profit (§10(2A)), and `SECTION_194T_FIRST_FY` names the
  commencement so a later FY 2024-25 entry cannot back-date it.
  **`domain/tds/residency` now has THREE lists, not two.** The first two answer
  one question — do the section's own charging words limit it to a resident —
  and §194T's do not ("to a partner of the firm"), so it cannot join
  `RESIDENT_ONLY_SECTIONS`, whose every entry quotes the limitation it is
  listed for. `SECTIONS_REACHING_NON_RESIDENTS` would assert something else
  again: that 10% flat on a 27Q row is RIGHT, when §195 charges the rates in
  force with surcharge and cess and no threshold — 10% is the SMALLER figure
  and an under-deduction disallows the whole expenditure under §40(a)(i). So
  `SECTIONS_UNSETTLED_FOR_A_NON_RESIDENT` REFUSES it with the reason, **asked
  BEFORE the resident-only lookup**: a section in it is by construction absent
  from that map, so falling through reaches the deliberate silence for
  unclassified sections and would allow the deduction. **§194R stays out and
  says why** — its routing is fine, but whether the Finance Act 2025 moved its
  ₹20,000 could not be confirmed here and the benefit is often IN KIND, a base
  no bill line holds. §194-IA/§194-IB/§194M stay refused for the probe pass's
  reason: Form 26QB/26QC/26QD are challan-cum-statements this product does not
  produce, and `return_type_for` routes on residency alone against migration
  014's four-value CHECK.
- **§206C IS IN THE TDS REGISTRY AND A VENDOR MAY NEVER CARRY IT.** TCS is tax
  COLLECTED by a seller from a buyer and reported on **Form 27EQ**; the
  registry entry exists as reference data and says so in its own comment
  ("do not assume TCS is an implemented feature because a rate exists here").
  Nothing refused it until 12-09-2026 and the supplier screen's section
  dropdown is served straight from the registry, so a vendor could be marked
  §206C and every bill from them withheld 0.1% of the WHOLE amount — the
  entry's threshold is ZERO — with the row stamped 26Q, because
  `residency.return_type_for` routes on RESIDENCY and never sees the section.
  Three things wrong at once: on a bill you are PAYING there is nothing to
  collect, 26Q is the wrong return, and no TCS path computes it.
  `deduction_section_refusal` is the one place that decides this (§192 is the
  other refusal), and `GET /api/tds/sections` serves its answer as
  `vendor_eligible` so a screen cannot keep a second exclusion list.
  **AND §206C(1H) CEASED TO OPERATE FROM 01-04-2025** — the seller no longer
  collects on receipts above ₹50 lakh and the BUYER deducts under §194Q, so the
  overlap is resolved in §194Q's favour and Form 27EQ / Form 27D for this item
  fall away. The registry's comment said "unchanged, 0.1%" for a year after
  that (SALES-32). The 0.1% ENTRY STAYS at its historic rate, because a belated
  or revised 27EQ for FY 2024-25 is filed at it — the fork shape again — and
  the cessation is `section_rates.SECTION_206C_1H_CEASED_FROM_FY`, a named
  constant like `SECTION_206AB_OMITTED_FROM_FY` and NOT a `rate_gap` (that
  field means "this limb's own rate is not held", and a test holds it to
  exactly that). ⚠️ `[S+]`, and the EFFECT is cited rather than the mechanism:
  most sources say the sub-section was omitted, one reads the Finance Act 2025
  as inserting a proviso that leaves the text in the Act and makes it
  inapplicable. Identical from 01-04-2025, different textually.
- **A CLIENT IS ONE LEGAL PERSON AND MAY HOLD SEVERAL GSTINs, and until
  migration 390 the return tables forbade it** (GST-20). CGST §25(1) requires
  registration in EVERY State or Union territory a taxable supply is made from,
  and §25(2)'s proviso allows a separate registration per place of business
  within one state — so a depot, a second office, a warehouse-state e-commerce
  registration are all the same legal person with several GSTINs and several
  sets of returns. `clients.gstin` held exactly one, and **both
  `gstr1_returns` and `gstr3b_returns` were `UNIQUE (client_id, period)`**, so a
  second registration could not have had its own June GSTR-1 whatever the code
  did; the CA's only route was a second fake "client" per GSTIN, which then
  splits the ACCOUNTING of one entity across two ledgers and breaks every
  client-scoped report. 390 narrows both keys to `(client_id, period, gstin)`.
  `domain/gst/registrations.py` is the authority.
  **`clients.gstin` IS NOT REPLACED and that is the part to read before
  "tidying" it.** It stays the PRIMARY and remains the only place the primary is
  stored; `client_gst_registrations` holds the ADDITIONAL ones ONLY, and
  `all_registrations` presents the union. The obvious alternative — move every
  registration into the table and leave `clients.gstin` as a cache — was
  rejected because a cache needs ONE write path and that column already has
  several (onboarding, the client edit screen, migration 073's seed), so it
  would drift the first time somebody edited a client and surface as a return
  filed under the wrong registration. **There is deliberately NO backfill**, for
  the same reason.
  **A GSTIN THE CLIENT DOES NOT HOLD IS REFUSED, NEVER DEFAULTED TO THE
  PRIMARY** — in the domain module and again as a 422 in
  `services/client_gst_registration_service.resolve` — because filing one
  registration's return under another's number is the exact failure this
  feature exists to prevent, and it is invisible until the portal rejects it or,
  worse, accepts it. The PRIMARY COMES FIRST in the list for the mirror-image
  reason: a screen opens on `[0]`, and that has to be the registration every
  existing document already carries.
  **The narrowed key made `_existing_return` load-bearing**: a save path still
  matching on (client, period) alone now finds the OTHER registration's return
  and revises it, silently replacing one state's figures with another's, so the
  GSTIN is a required parameter there with no default.
  ⚠️ **THE TWO `gstin` COLUMNS ARE NOT THE SAME SHAPE, and the difference
  decides whether narrowing constrains anything.** `gstr1_returns.gstin` is NOT
  NULL from migration 036; `gstr3b_returns.gstin` is NULLABLE, because 036's
  CREATE TABLE omitted it and **migration 234 added it as a bare `TEXT`** with
  nothing to back-fill from. Postgres treats NULLs as DISTINCT in a unique
  index, so `(client_id, period, gstin)` enforces NOTHING on a row saved
  without one — narrowing the key would have REMOVED what `UNIQUE (client_id,
  period)` gave those rows rather than refining it. 390 closes it twice: it
  **back-fills both tables' NULL gstin from `clients.gstin` BEFORE dropping the
  old constraint** (that constraint guarantees at most one row per (client,
  period), so the update cannot collide — and before 390 a client held exactly
  one registration, so `clients.gstin` IS what such a row was prepared under: a
  repair of 234's omission, not a guess), and keys both indexes on
  **`coalesce(gstin, '')`**, which is a no-op on `gstr1_returns` today and is
  written anyway because these two columns have already drifted apart once.
  **No `SET NOT NULL`**: merging applies this to production with no review step
  in front of it, and one unbackfillable row would abort the deploy and block
  every later migration behind it.
  **`files_gstr1_and_3b` exists so no caller tests the type by name** — a
  composition dealer files CMP-08 and GSTR-4 under §10, an ISD files GSTR-6, a
  §51 deductor GSTR-7 and a §52 operator GSTR-8, and `OTHER_RETURN_FORMS` holds
  the sentence so the refusal names the form that registration actually owes
  rather than saying only that this one is unavailable. An SEZ unit, an SEZ
  developer, a casual and a non-resident taxable person DO file the ordinary
  pair. **`state_code` is DERIVED from the GSTIN's first two characters**, never
  taken from the caller (the column CHECKs `state_code = left(gstin, 2)`), and
  the prefix is taken rather than `gstin.state_code` for `place_of_supply`'s
  reason — the question is which state, not whether the check digit is right.
  **Closing is not deleting**: §29 cancellation sets `effective_to`, because the
  returns for every period the registration was live are still owed and the rows
  already filed under it are keyed on its GSTIN; `withdraw` is for a
  registration recorded in ERROR and is refused once any return exists under it.
- **A PLACE OF SUPPLY HAS FOUR SOURCES AND ONE RESOLVER**, and the invoice
  declares the field TWICE. `domain/gst/place_of_supply.recipient_place_of_supply`
  is the chain — what the caller stated (CGST Rule 46(n) makes it the
  document's own particular), then the customer's recorded state, then the
  first two characters of the customer's GSTIN (CGST §25), then the SUPPLIER's
  own state (IGST §12(2)(b)(ii), the unregistered walk-in, and it must be last)
  — and `("", "unknown")` where even that is absent, because `clients.gstin` is
  nullable. **The GSTIN branch takes the PREFIX, not `gstin.state_code`**: the
  question is which state, not whether the registration number is well-formed,
  and falling through on a bad check digit would silently turn an inter-state
  supply intra-state. `SalesInvoiceIn` carries BOTH `supply_state_code` and
  `place_of_supply`; until SALES-31 the real create path read only the first
  while the mock branch read both, so a caller filling in the second had it
  honoured under test and discarded in production. Both are validated against
  the state list now (as `ReceiptIn.place_of_supply` has been since GST-15),
  the edit path too, and a request whose two disagree is refused rather than
  silently resolved one way.
- **WHAT KIND OF SUPPLY AN INVOICE IS HAS ONE AUTHORITY, AND THE E-INVOICE
  RECORD MAY NOT CONTRADICT IT** (SALES-19). `domain/gst/treatment.
  treatment_for_invoice` derives the treatment — regular, export or SEZ, with
  or without payment, deemed export — from the invoice's own `supply_type` and
  `invoice_type`, the pair GSTR-1 is actually built from, reading the EXPORT
  ROUTE off the tax actually charged (IGST §16(3): (b) on payment of IGST,
  refunded under §54, against (a) under an LUT or bond with nothing charged —
  Table 6A's `exp_typ` turns on exactly that, and asking for the wrong one asks
  for the wrong refund under the wrong rule). `einvoice_records.gst_treatment`
  is a SECOND record of the same fact, captured when a CA prepares an IRN, and
  `POST /api/einvoice/records` stored whatever was sent while the picker seeded
  itself `"regular"` and was never told what the invoice said — so a record
  could contradict its own invoice and the compliance panel rendered both
  labels at once. `treatment_for_record` is the rule and the door **422s a
  disagreement rather than resolving it**: taking the caller's value keeps the
  wrong export route on the document a human keys the IRP from, and taking the
  derived value silently discards what somebody just chose on a screen that
  offered them the choice — `SalesInvoiceIn`'s shape where the two state fields
  disagree. **A record naming no invoice this product holds is NOT refused**:
  `sales_invoice_id` is optional (a record may be prepared for an invoice
  raised elsewhere), so there is nothing to reconcile and refusing would make
  the link mandatory by accident. The picker is READ-ONLY where the server
  decided one, because a screen must never invite a CA to type something the
  server will refuse — the `attachmentsReadOnly` discipline.
- **THE SALES CYCLE BEGINS BEFORE THE TAX INVOICE, AND ONLY ONE OF THE FOUR
  DOCUMENTS IS THE ACT'S** (SALES-21, migration 392). A client quotes, takes an
  order, delivers against it and bills afterwards; the product started at the
  invoice, so a CA either raised it EARLY — declaring a supply that had not
  happened and paying tax on it a month before the money arrived — or kept the
  quotation in a spreadsheet and re-typed every line when it converted.
  `domain/sales/order_cycle.py` is the commercial chain and
  `domain/gst/delivery_challan.py` is CGST Rule 55; the service, the router and
  the screen decide nothing either of them decides.
  **A quotation, a proforma invoice and a sales order are COMMERCIAL papers the
  Act does not know** — CGST §7 charges a SUPPLY and an offer is not one — so
  none of the six tables carries a `journal_entry_id`, nothing posts, nothing
  moves stock, and a test asserts no return builder reads any of them. **The
  proforma is the trap**: it looks like an invoice, is often numbered like one,
  and a GSTR-1 that picked one up would declare a supply that never happened.
  **It is never numbered from the tax-invoice series** — Rule 46(b) requires
  that series to be CONSECUTIVE and unique for the FY, so consuming a number
  for a document that may never become a supply puts a permanent gap in it and
  reusing the number later puts two documents on one. `series_kind_of` gives
  each kind its own; uniqueness is per client PER KIND, so a quotation and a
  proforma may share a number and two quotations may not.
  **A DELIVERY CHALLAN IS THE ACT'S, AND TWO OF ITS REASONS START A CLOCK
  WHOSE EXPIRY IS A DEEMED SUPPLY.** §143(3) deems inputs not received back
  within ONE YEAR to have been supplied to the job worker **on the day they
  were sent out** — so the tax falls due in a return already filed, with
  §50(1) interest from that return's own due date — and §143(4) is the same at
  THREE years for capital goods; §31(7) gives goods sent on approval SIX
  MONTHS from removal. Neither clock is visible in any ledger (the goods left,
  nothing was billed, no journal moved), so the challan is the only document
  either can be computed from, which is the point of the module rather than a
  convenience. **`goods_kind` is nullable with NO default and is REFUSED,
  never guessed**: defaulting to inputs reports a deemed supply two years
  early and defaulting to capital goods hides one for two years, and moulds,
  dies, jigs, fixtures and tools are outside both (second proviso to §143(1)) —
  named as its own answer, because "no clock" and "a clock nobody computed"
  must not look the same on a screen. An extension under the proviso is
  RECORDED and honoured only where it is LATER than the statutory date. A
  month-end deadline walks BACK to the month's last day (31 August plus six
  months is 28 February), never forward, because forward is a day late on a
  deemed supply.
  **Rule 55(1)'s nine clauses are checked and TWO ARE CONDITIONAL**: (vii) tax
  rate and amount only "where the transportation is for supply to the
  consignee" — so a job-work despatch carries none, and the service zeroes the
  rate rather than asking the caller to remember — and (viii) place of supply
  only on an inter-State movement. Rule 55(2)'s three legends are printed
  verbatim because the rule prescribes the WORDS. **What an order still has
  open is DERIVED, never stored** (migration 278's reasoning applied to a
  quantity), from challan lines read `.in_` over THIS order's line ids and
  their parents' statuses — a cancelled challan has delivered nothing.
  Over-delivery is REFUSED, never clamped. Three things are named rather than
  guessed: **ITC-04's periodicity** (Rule 45(3) turns on the principal's own
  preceding-year turnover, which no column holds, so both readings are shown
  and neither chosen), **what has been INVOICED against an order** (an invoice
  line carries no link back to an order line, so the figure is honestly zero
  rather than a description match), and Rule 55(5)'s four steps, whose gaps
  are reported. ⚠️ Every period and every clause of Rule 55 is `[S]`-graded and
  pinned by a test — egress is refused here — and `compute_line_gst` MOVED to
  `domain/sales/line_tax.py` with `routers/sales_invoices` re-exporting it, so
  `shared/gst-parity-vectors.json` still pins the one implementation.

- **A §37(3) AMENDMENT RE-DECLARES THE WHOLE ENTRY, so an export amendment
  carries its shipping bill.** `domain/gst/amendments.build_invoice_amendment`
  emitted three empty strings for `sbpcode`/`sbnum`/`sbdt` on `expa`
  (SALES-10) while the main build has emitted the real values since migration
  349 — so amending an export's VALUE replaced a filed entry that had a
  shipping bill with one that did not, and CGST Rule 96(1) matches the refund
  against exactly those three fields at customs. `exception_report`'s document
  index carries them now (`None` on a non-export, because three blanks there
  would read as an export with nothing recorded) and the amendment declares
  the BOOKS side. Absent still means three empty strings: the portal accepts
  an export declared before the shipping bill exists.
- **A CUSTOMER RECEIPT SETTLES CASH PLUS THE TAX THEY WITHHELD.**
  `ReceiptIn.tds_paise` posts Dr Bank + Dr TDS Receivable / Cr Trade
  Receivables and the settlement is `amount + tds` — IT Act §198 deems the tax
  deducted to be income received and §199 gives the deductee credit for it — so
  a ₹1,00,000 invoice paid ₹90,000 net of ₹10,000 §194J is settled in full. No
  screen sent the field until SALES-07, so the invoice stayed part-unpaid and
  no TDS Receivable existed to claim against. The box is hidden on a FOREIGN
  receipt because `create_foreign_receipt` refuses any non-zero value, and the
  unallocated figure on the screen measures against the settlement rather than
  the cash, which is the same figure the server's over-allocation refusal uses.
- **`tds_deductions.return_type` and `tds_returns.return_type` store the 1961-Act
  ROUTING KEY permanently — 24Q/26Q/27Q/27EQ — on both sides of the 2026 fork.**
  `vocabulary.statement_form` returns the number the PERIOD's own Act uses (140
  for a FY 2026-27 26Q) and that is a DISPLAY value. Writing it into the column
  hits migration 037's CHECK, which is what the firm-level TDS screen did from
  1 April 2026 onwards, surfacing as "Failed to save TDS return" with no reason.
  `CreateReturnRequest.return_type` is a `Literal` of the four so it cannot come
  back. Translate at the boundary, never rekey a store.
- **A TDS statement's deductor block is READ, never defaulted** —
  `domain/tds/deductor.py`, from `client_statutory_identity.tan` (migration 325,
  created for exactly this) and the client's own PAN, legal name and postal
  address. A caller-supplied value wins where one is given and is validated on
  the way through; where neither exists the build is REFUSED with one sentence
  per missing identifier. The firm-level screen used to invent
  `"MUMB00000A"` / `"AAAAA0000A"`, both well-formed, so every validator passed
  and a quarter saved under a TAN belonging to nobody — a return filed against
  somebody else's account, with §200/§201 exposure staying on the real deductor.
- **THE DEDUCTOR BLOCK IS SERVED, NOT RE-TYPED** (TDS-28).
  `GET /api/tds/deductor?client_id=` resolves it through the same
  `domain/tds/deductor.resolve` the compute path refuses with, off the same
  two rows (`_deductor_sources` — `client_statutory_identity.tan` and the
  client's own PAN, legal name and address). Nothing served it before, so the
  compliance screen opened four blank boxes and the CA typed the TAN, the
  legal name and the PAN every quarter, for every client — and a quarter filed
  under a mistyped TAN is filed against somebody else's account. The endpoint
  NAMES the gaps rather than refusing, because a screen opening a form needs
  to say what to go and record; the boxes stay editable, and a value already
  typed is not overwritten when the panel reopens.
- **A TDS ENGAGEMENT OWES TWELVE MONTHLY DEPOSITS, NOT FOUR STATEMENTS**
  (TDS-12). Rule 30(2) binds every deductor other than an office of the
  government, and `compliance_engine.tds_deposit_due_date` had exactly one
  caller — `payroll_deposit_due_dates` — so the compliance calendar carried a
  monthly deposit for SALARY and nothing at all for the §194 series.
  `_tds_obligations` emits `TDS_NON_SALARY_DEPOSIT` for every month of the FY.
  **Its own obligation type**, not a second `TDS_SALARY_DEPOSIT` row: two
  deposits with different section codes on the challan and different registers
  behind them, one generated for a PAYROLL engagement and one for a TDS one,
  and the dedup key is `(obligation_type, period_start)` so sharing a type
  would silently drop one.
- **§206AB was omitted by the Finance Act 2025 w.e.f. 01-04-2025, so
  `tds_validator.is_higher_rate_applicable` takes an FY** and answers the
  ordinary rate for a later year. Not deleted: §206AB governs a period up to
  31-03-2025 indefinitely, including a belated or revised return filed today —
  the same fork shape as the TDS vocabulary. Omitting the FY means current law.
  ⚠️ The omission is `[S]`-graded — egress is refused at this environment's
  proxy — so it is a named constant, `SECTION_206AB_OMITTED_FROM_FY`.
- **What being late costs is `domain/tds/interest.py`, and "month or part of a
  month" is NOT the same arithmetic there as in §234A.** §201(1A) has two
  limbs, two rates and two clocks: (i) 1% per month or part from the date tax
  was DEDUCTIBLE to the date DEDUCTED, (ii) 1.5% from the date DEDUCTED to the
  date PAID OVER. Limb (ii)'s clock starts at the deduction, not the Rule 30(2)
  due date — so tax deducted 25 June and deposited 8 July is one day late and
  carries TWO months, 3%. The Rule 30(2) date decides only WHETHER there is a
  default. §234E is the odd one: ₹200 a DAY, capped at the statement's own tax,
  payable before the statement can be delivered (§234E(4)) — counting it in
  months makes it thirty times too small, and it used to live only inside
  `services/filing_demo/tds_return.py`, which transmits nothing. ⚠️ The
  month convention is `[S]`-graded: §234A counts a PERIOD (anniversary to
  anniversary, which is what
  `advance_tax_interest_engine._months_or_part` does and is right there),
  while §201(1A) is administered on CALENDAR months — 30 June to 1 July is two.
  Egress is refused here so neither could be confirmed, and the calendar count
  is never smaller, so the error direction cannot understate a deductor's
  exposure. Two refusals: tax **never deducted** has no end date for limb (i)
  (the proviso to §201(1) runs it to the date the PAYEE filed), and an unpaid
  deduction with no as-at date gets a sentence rather than a figure.
- **What is due for deposit this month is `domain/tds/deposit_due.py`, and it
  is the NON-SALARY side only.** `GET /api/tds-workspace/deposit-due` groups
  `tds_deductions` by section for one DEDUCTION month into a challan-281
  worksheet, with §201(1A)(ii) computed per ROW (two deductions in one month
  are days apart, so a section-level clock charges both or neither) and the
  due date from `compliance_engine.tds_deposit_due_date` — Rule 30(2) binds
  every non-government deductor, salary and not, and there is deliberately no
  second copy of the seventh-and-March arithmetic. §192 tax is computed in
  payroll and never reaches `tds_deductions`, so every worksheet SAYS so; a
  §192 row found in the register is named as a gap. `tds_challans` finally
  carries the split — `amount_paise` is the TOTAL and tax is the remainder
  after surcharge, interest and penalty, so a request sending none of the three
  behaves exactly as before — and `minor_head` is settable (200 = paid over by
  the deductor, 400 = against a demand; the company / non-company split is the
  MAJOR head 0020/0021, which migration 037's inline comment had backwards).
- **§194I AND §194J EACH CHARGE TWO RATES, AND THE CLAUSE IS NOW RECORDABLE
  WITHOUT THE RATE BEING INVENTED** (TDS-22). §194I charges rent of plant,
  machinery or equipment at a lower rate than rent of land, buildings or
  furniture; §194J charges fees for technical services at a lower rate than
  professional fees. `domain/tds/section_rates.py` holds one key per section
  plus four clause limbs — `194I(A)`, `194I(B)`, `194J(A)`, `194J(B)` — and the
  distinction matters twice: **the (b) limbs ARE the rate the registry already
  holds** (land/building/furniture rent, and professional fees), so selecting
  one is complete and carries no gap, while **the (a) limbs withhold at the
  parent's higher rate and say so** in `rate_gap`. Nothing in the module states
  2%: an under-deduction disallows the whole expenditure under §40(a)(ia) while
  an excess is the payee's to reclaim, so over-deducting is the direction a
  rate nobody has read off the Finance Act may take.
  **The clause CODES are a primary source inside this repository** — the ITD's
  own ITR-6 AY 2026-27 schema, `domain/income_tax/schemas/ITR6_2026_Main_V1.0.json`,
  enumerates `4-IA:194I(a)`, `4-IB:194I(b)`, `94J-A:194J(a)`, `94J-B:194J(b)` —
  which is what removed the recorded objection that "an invented code on a
  statutory return is worse than the over-deduction it would fix". A test
  asserts them against that file, so a later schema version that spells them
  differently fails rather than drifts.
  **THE KEYS ARE UPPER CASE and that is load-bearing**: every lookup in the
  module is `.upper().strip()`, so a lower-case key is never found and the
  failure is SILENT — `parent_of()` falls through to returning the key
  unchanged, the FY aggregate quietly becomes per-clause instead of the
  section's, and the withholding drops below what §194J's proviso charges.
  Two things must therefore never test a name and always ask `parent_of()`:
  the FY aggregate, and challan matching (a CA types "194J"). §197 eligibility
  asks it too — `GET /api/tds/sections` resolves the parent before checking
  `SECTIONS_197`, because §197(1) names sections and telling a CA their
  plant-hire payment cannot carry a certificate *because they said which kind
  of rent it was* would be a defect created by adding the limb.

- **`public.tds_section_limits` is NOT the TDS rate master and nothing may read
  it.** Migration 037 seeded it once with pre-Finance-Act-2025 thresholds and
  pre-2024 rates, and its ₹1,00,000 aggregate §194C row has never existed in
  any database (`section` is the primary key, both 194C rows went in under
  `ON CONFLICT DO NOTHING`). It is the one table whose name reads like the
  authority. Migration 371 makes it say so in the database and
  `tests/test_the_dead_tds_rate_master_has_no_readers.py` holds the other half.
  Do NOT correct the figures in place — `domain/tds/section_rates.py` is the
  FY-versioned authority and a second one in SQL is what the posting-kernel
  rule exists to prevent. A DROP is the right end state and needs the
  production-fixture refresh in `docs/schema-drift.md`.
- **AN IMPORT OF GOODS IS PAID FOR TWICE AND ONLY ONE OF THEM IS THE SUPPLIER'S**
  (PUR-18, migration 389). IGST on imported goods is not charged by the
  supplier: IGST §5(1)'s proviso puts the levy under Customs Tariff Act §3(7),
  collected under the Customs Act, so it is paid to CUSTOMS against a **Bill of
  Entry** — often the largest single ITC item of an importer's month. This
  product had no such document, so putting it on the vendor's bill overstated
  Trade Payables by the whole of it and leaving it off lost the credit, while
  GSTR-3B Table **4(A)(1) filed NIL** against a GSTR-2B whose own `impg`
  section shows the document. `domain/gst/bill_of_entry.py` is the rule.
  **THE ASSESSMENT IS NOT ONE FIGURE.** CGST §2(62)(a) puts "the integrated
  goods and services tax charged on import of goods" in INPUT TAX and Rule
  36(1)(d) makes the bill of entry the document it rests on; **basic customs
  duty and the social welfare surcharge are recoverable from nobody**, so AS-2
  paragraph 6 makes them COST — the same sentence that keeps blocked §17(5) GST
  in the cost of goods (INV-05a), and the blocked part of the import's own tax
  goes the same way. Treating the assessment as one figure claims credit that
  does not exist. **`ImportOfGoods` IS ITS OWN TYPE, NOT A FLAG ON
  `PurchaseTransaction`**, and it has no `is_reverse_charge` and no CGST or
  SGST field: reverse-charge tax is SELF-assessed and creates a Table 3.1(d)
  liability, this tax was collected by customs and creates none, and IGST §7(2)
  makes an import inter-state so no other head can arise. A flag beside
  `is_import_of_services` would invite the next reader to set
  `is_reverse_charge` too — every other import is — and declare a liability the
  client does not owe. **The journal touches NO accounts payable**: customs is
  owed, not the supplier. **IMPG is capped LAST** of the five 4(A) rows, because
  the two reverse-charge rows carry tax already paid in cash that Rule 36(4)
  cannot reach, while import credit rides inside the cap (2B communicates it in
  its own section). Only `status = 'posted'` documents reach the return — a
  draft has no journal, and that gap is the books-vs-ledger difference the
  reconciliation exists to catch. **4(A)(4) ISD is now the ONLY named 4(A)
  gap.** Four refusals are recorded rather than guessed: deferred payment of
  duty (Customs Act §47(2) proviso), a §27 refund, the duty is **not
  apportioned into stock cost** (the basis is INV-05's open half and an owner
  decision), and Rule 46(h)'s UQC has no line detail to come from. The seeded
  `Customs Duty` account is code **5022** with subtype `Cost of Materials` —
  both load-bearing: 5021 is Depreciation Expense and `ON CONFLICT DO NOTHING`
  would have skipped the insert silently, and `schedule_iii.pl_bucket` has no
  entry for `Direct Expense`, which is why migration 197 moved 5000 and 5001
  off it.

- **A REVERSE-CHARGE PURCHASE OWES TWO DOCUMENTS AND THEY ARE NOT ONE RULE WITH
  TWO NAMES** (PUR-19, migration 388). The reverse-charge ACCOUNTING was
  complete — the tax kept out of what the vendor is owed, the liability
  self-accounted, GSTR-3B declaring it — and the product produced neither
  document the CGST Act makes the RECIPIENT issue. **§31(3)(f) reaches only a
  supply received from a supplier who is NOT REGISTERED; §31(3)(g) reaches
  EVERY §9(3)/(4) payment**, registered supplier or not — so a payment to a
  registered goods transport agency owes a voucher and owes no self-invoice,
  and asking the registration question in `payment_voucher_due` would import
  (f)'s limb into a section that does not carry it. The self-invoice is not
  paperwork: it is the document the input credit RESTS on (Rule 36(1)(b) with
  §16(2)(a)). `domain/gst/rcm_documents.py` is the authority and decides all of
  it; the router and the screen decide nothing.
  **REGISTRATION HAS THREE STATES AND THE THIRD IS REFUSED, NOT GUESSED.** A
  valid GSTIN on the vendor IS the registration — read through
  `domain/gst/gstin.problem_with`, so a malformed one reports itself instead of
  being read as registered — `vendors.gst_registration_status` answers it where
  there is no GSTIN, and NULL is *unrecorded*, named as a gap: one guess mints
  a document the Act does not ask for and the other withholds the one the
  credit rests on. The column is nullable with **no default** and CHECKed to
  the two settled answers, so `unrecorded` cannot be STORED as a string; both
  API doors (`VendorIn` and `VendorUpdateIn`) normalise case and refuse it with
  a sentence saying it is the ABSENCE of a value, and both screens that record
  it — the client Vendors tab and the firm-level Supplier Master — serve the
  picker from `GET /api/rcm-documents/registration-states` rather than
  spelling the pair. A `Decision`'s **`reasons` and `gaps` are different
  things** and the panel renders them differently: reasons mean the Act does
  not ask for the document (settled), gaps mean nobody can yet tell
  (actionable). The particulars are built in the domain module rather than in
  the PDF, so what the endpoint serves and what the CA prints are one object.
  Four refusals are recorded rather than guessed: **no consolidated month-end
  self-invoice** (`[S]`, tied to the withdrawn Notification 8/2017-CT(R)),
  whether §9(4) applies is the bill's own `is_reverse_charge` and is the CA's
  answer, a cancelled registration is not modelled, and **Rule 46(h)'s UQC is
  absent because `purchase_bill_lines` has no unit column** — named, never
  invented. Numbering goes through the one `domain/gst/invoice_series`
  authority, and uniqueness is per client **per kind**, because Rule 46(b)
  allows "one or multiple series" and these are two.

- **A SECTION THE ENGINE CANNOT ANSWER FOR IS REFUSED WITH ITS OWN REASON, AND
  THE REASONS ARE NOT INTERCHANGEABLE** (TDS-23). `deduction_section_refusal`
  is the one place that decides it, and what a CA has to go and do differs per
  section — a shared "no rate held" paragraph says the wrong thing about most
  of them. **§192** computes a silent nil, **§206C** is TCS collected by a
  seller, and **§194N is the third DIRECTION refusal**: it is charged on a
  banking company, a co-operative bank or a post office on cash the ACCOUNT
  HOLDER withdraws, so on a bill your client is PAYING there is nothing to
  withhold — when it bites the client is the **deductee** and the credit
  appears in their Form 26AS. Saying only "no rate held" there would invite
  somebody to add one. **§194R, §194O and §194S are refused on the BASE as much
  as the rate**, and each carries its own sentence in
  `_SECTIONS_WITH_NO_FIGURE_AND_THE_REASON`: §194R's benefit is often in kind,
  §194O's base is the *participant's* sale rather than any bill the operator
  receives, and §194S has no virtual-digital-asset document at all — with
  §194S(2) requiring the tax paid before consideration in kind is released.
  **§194-IA/IB/M stay refused** because Form 26QB/26QC/26QD are
  challan-cum-statements this product does not produce. A test asserts the
  three answers are DIFFERENT, on the answers rather than on the data, so
  moving a reason in or out cannot make it vacuous.

- **A JOURNAL'S SUPPORTING DOCUMENTS ARE A DRAFT-ONLY EDIT, AND THE SCREEN SAYS
  SO** (ACC-25). `JournalEntryIn` has taken validated attachments since the
  first half of this finding; `JournalEntryUpdateIn` had none, so the editor
  rendered the control on an entry being corrected, the CA typed a link, and
  the PATCH sent everything except it. Both doors now validate through the same
  `domain/attachments` parser — a validator on one door only is one PATCH from
  being none, and this is the door reached SECOND, after the entry already
  looks legitimate. `None` means unchanged; an **empty list removes them**,
  which the service's header filter keeps and the `None` case drops.
  **A POSTED entry is REFUSED rather than ignored**, because
  `prevent_posted_journal_modification` (last defined in migration 274) lets a
  posted header change only inside `journal_edit_in_progress()`, and the one
  thing that sets it is `edit_posted_journal` — which rewrites LINES and
  carries no attachments. Teaching it attachments means replacing the posting
  kernel's own edit RPC, an owner decision rather than a convenience. The
  editor gates on `attachmentsReadOnly = readOnly || isPosted`, a STRICTER
  state than `readOnly` (a locked year or a filed return), so a CA is never
  invited to type something the server will refuse.

- **A LEDGER ROW NAMES THE DOCUMENT BEHIND IT, AND THREE FILES HAVE TO AGREE
  ABOUT WHAT THAT MEANS** (ACC-22, migration 400).
  `journal_entries.source_type` / `source_id` have existed since migration 104
  and have been filled in by all twenty-six posting paths since commit
  99ac94b5 — whose own message says *"This commit is the missing premise; the
  drill-through itself is a separate change."* The ledger was the half that
  never READ them, so a CA looking at "Trade Receivables 1,18,000 Dr" had a
  narration, a reference and nothing to open, which is the one keystroke Tally
  has trained them to expect and the only quick way to find WHICH document
  drifted when the GL and a sub-ledger disagree.
  **The two keys are ALWAYS PRESENT and null where the entry carries none.**
  An absent key and a null key read the same to `line.source_type ?? null` and
  are different bugs: null is "this entry has no document", absent is "this
  build did not send it" — the screen renders the first and cannot detect the
  second. Both `builders.ledger` and migration 400's `account_ledger_page`
  emit them unconditionally, and 400 is derived from **283**, still the last
  definer, because `CREATE OR REPLACE` replaces the whole body.
  **The ROUTE map is the browser's and the VOCABULARY is Python's.**
  `apps/web/lib/accounting/sourceDocument.ts` says which screen and which
  sub-tab each source opens — a fact about Next.js routes the backend cannot
  hold — and is pinned from the Python side by
  `tests/test_the_browser_can_open_the_document_the_ledger_names.py`: every
  member of `journal_source.ALL_SOURCES` is routed, is one of the three in
  `ENTRY_IS_THE_RECORD`, or is REFUSED with its own sentence. A guard written
  in `apps/web` would assert that file against a copy of itself, the Schedule
  III caption lesson. **Two sources are refused and the reasons are not
  interchangeable**: a `settlement`'s screen is keyed on the EMPLOYEE and the
  row carries the settlement id, and a `year_end_adjustment` lives under its
  ENGAGEMENT and the row carries the adjustment id. Sending a CA to a list that
  cannot show the document is worse than an unclickable row, because it reads
  as "this is the document".
  **One deep-link convention — `?tab=<id>&doc=<uuid>` — and one highlight.**
  A param per kind (`?invoice=`, `?bill=`, `?run=`) would be a second
  vocabulary; `DataTable`'s `highlightRowId` rings the row and scrolls it into
  view in ONE place rather than teaching five screens their own idea of
  "open". A row that is filtered or paged out is simply not found: nothing is
  forced into view and no filter is cleared, because a deep link must not
  silently change what the reader is looking at. The tab is validated against
  each screen's own `TABS` and read from `window.location.search` inside an
  effect — `apps/web` is a static export, so nothing may touch `window` during
  render.
  **Two guards that named a LOCATION broke on a move that did not break their
  rule**, and both were restated: `test_a_journal_source_reads_as_english`
  asserted `function sourceLabel` lived in the accounting page (it now finds
  the single definition by searching `apps/web`), and
  `the-book-can-be-read-not-only-posted-to` asserted the same spelling (it now
  asserts the page IMPORTS it). That is the third time this pattern has been
  fixed in this file's history; write the rule, not a spelling of it.

- **THE SUPPLIER MASTER IS `public.vendors`, AND `public.suppliers` IS RETIRED**
  (PUR-16). Migration 030 created a second one and `/accounting/suppliers` was
  its only writer, straight over PostgREST; every purchase path — bill
  creation, TDS withholding, AP ageing, the Schedule III payables note, GSTR-2B
  matching, §43B(h) — reads `vendors`. The credit limit was the harmless half
  (nothing anywhere reads one, on a vendor OR a client, and migration 378's
  column comment says `RECORDED, NOT ENFORCED` rather than implying a control
  that does not exist). **The TDS SECTION was not**: a CA who picked 194J on
  that screen wrote `suppliers.tds_section`, the bill read
  `vendors.tds_section`, found NULL and withheld nothing — and §40(a)(ia)
  disallows the WHOLE expenditure for an under-deduction, with §201(1) putting
  the tax on the deductor and §201(1A) interest on top. The screen goes through
  `/api/vendors` now, so `rbac()` runs. **Three field names differ and one is a
  different UNIT** — `supplier_name`→`name`, `payment_terms_days`→`credit_days`,
  `tds_rate_percent`→**`tds_rate_bps`**, so a percentage written into the
  basis-points column stores 10 where 1000 is meant and withholds 0.1% instead
  of 10%. **No data was migrated and that is a measurement, not a decision**:
  `public.suppliers` held ZERO rows in production on 13-09-2026. Marked dead in
  the database rather than DROPped, the same shape as migration 371 — a DROP
  moves both sides of the production-fixture comparison at once and needs the
  refresh in `docs/schema-drift.md`.
- **THE PURCHASE CYCLE BEGINS BEFORE THE BILL, AND THE GOODS RECEIPT IS A
  STATUTORY FACT** (PUR-25, migration 393). A client raises a purchase order,
  receives the goods against it and only then books the supplier's invoice;
  neither of the first two documents existed, so there was nothing to check
  the bill against — and no record at all of WHEN the goods arrived. That
  second absence is statutory twice over. **CGST §16(2)(b)** allows the input
  tax credit only where the recipient "has received the goods or services",
  and a March invoice for goods that arrive in April carries credit belonging
  to April. **MSMED §15 runs its fifteen days from ACCEPTANCE**, and the
  Explanation to §2(b) makes acceptance the day of ACTUAL DELIVERY — so
  `domain/income_tax/section_43b_h.py` had to use the bill date as a proxy and
  carried `ACCEPTANCE_DATE_NOT_HELD` on **every** answer. The proxy is the
  EARLIER date and therefore manufactures disallowances on bills paid in time;
  a goods receipt is the real one, and the caveat is now emitted only for the
  bills that actually fell back.
  `domain/purchases/order_cycle.py` is the commercial chain and
  `domain/purchases/three_way_match.py` is the comparison and the two statutes
  it settles.
  **IT REPORTS; IT NEVER BLOCKS A BILL.** A supplier who short-ships or
  over-charges has still sent one and the CA still has to book what arrived —
  refusing would push the entry outside the system, which is worse than a
  mismatch nobody looked at. The one thing refused is an over-RECEIPT against
  the order, because goods on the premises in excess of what was ordered mean
  the ORDER is wrong. **NO TOLERANCE IS APPLIED AND NONE IS INVENTED**: "within
  2%" is a firm's procurement policy rather than a rule, and every answer says
  so. **NO PRICE VARIANCE IS POSTED** — INV-05a costs a receipt at the BILL's
  own taxable value plus its §17(5)-blocked tax, so the bill IS the cost and a
  variance account would double-count. **A BILL WITH NO ORDER IS NOT A
  FINDING**: most purchases a practice sees — fees, rent, utilities — are never
  ordered.
  **NEITHER DOCUMENT POSTS OR MOVES STOCK.** The expense, the credit and the
  payable all arise when the bill is received. Goods received and not invoiced
  are a real accrual and building one needs a GRNI account and a reversal path
  — an owner decision, named rather than half-built.
  **`rejected_qty` IS ITS OWN FIGURE, not a smaller quantity**, because
  §16(2)(b) asks what was RECEIVED and §2(b) asks what was ACCEPTED and one
  number cannot answer both; what the order still owes is measured on what was
  KEPT. **The ACCEPTANCE date is the LAST receipt, not the first** — a
  part-shipped order is accepted when the goods the bill covers have all
  arrived — and an **objection removed** (§2(b)'s second limb) displaces it,
  which is LATER and so can only remove a disallowance, never create one.
  **The YEAR of the add-back is still the BILL's**: §43B(h) disallows a
  deduction claimed in the year the expense ACCRUED in, so only the fifteen-day
  clock moves. **`purchase_bill_lines` carries no `firm_id`** and is scoped
  through its parent bill — naming the column would be PGRST204 and no read at
  all, so the tenant check happens at the parent and a test pins both halves.

- **§43B(h) IS DERIVED FROM THE PURCHASE LEDGER, AND THE LIMIT IS FIFTEEN DAYS**
  (PUR-15). The Finance Act 2023 inserted clause (h) with effect from AY
  2024-25: a sum payable to a MICRO or SMALL enterprise beyond the MSMED §15
  time limit is deductible only in the previous year it is ACTUALLY PAID.
  **The first proviso to §43B does not reach clause (h)** — paying before the
  §139(1) return date saves every other §43B item and not this one, which is
  the commonest mistake with it and is on every answer.
  `domain/income_tax/section_43b_h.py` is the rule,
  `services/msme_43bh_service.py` fetches its inputs, and
  `GET /api/income-tax/msme-43bh` serves it. `/accounting/msme-tracker` renders
  it and computes nothing: it used to ask the CA to re-key every bill into
  `msme_payments` over PostgREST — so the figure drifted from the books,
  `rbac()` never ran, and the whole statutory rule lived in TypeScript, where
  it read the agreement type off a per-invoice dropdown. **`msme_payments` is
  no longer read or written**; dropping it is a migration and an owner
  decision. Two directions, both computed: what accrued this year and missed
  its limit is added back, and an EARLIER year's disallowance actually paid
  during this year comes back as a deduction — so every live bill is read, not
  only the year's own. **Micro and small only** (MSMED §2(n)); an unclassified
  vendor is named, never assumed. **The disallowance is the DEDUCTION** —
  taxable value plus §17(5)-blocked tax — not the gross invoice, because
  creditable GST is credit and not an expense; and a bill capitalised into a
  fixed asset is reported with nothing disallowed, since only the depreciation
  is claimed. **TDS withheld counts as paid to the supplier**, the same §199
  reasoning `domain/gst/itc_reversal.py` applies to Rule 37. ⚠️ §15 runs from
  ACCEPTANCE and the books hold the BILL DATE; the proxy gives the earliest due
  date and so the largest disallowance, which puts the item in front of the CA
  rather than hiding it, and every answer says so.
- **A VENDOR PAYMENT RECORDS WHICH BILLS IT SETTLED IN TWO SHAPES, AND EVERY
  READER MUST KNOW BOTH** (PUR-22). `purchase_payments.purchase_bill_id` is the
  legacy single-bill FK, written with NO allocation row;
  `purchase_payment_allocations` (migration 226) is the multi-bill shape,
  written with that column NULL. **The column says which SHAPE a payment is,
  not merely which bill it happened to pay** — `reversal_service.reverse_payment`
  branches on it, rolling the bill back by the payment's whole AP relief where
  it is set and by each allocation's own amount where it is NULL, so writing it
  from the allocation path would send a PARTLY allocated payment down the legacy
  branch and roll back more than it settled. That is why both shapes survive,
  why `POST /api/purchase-payments` refuses a request carrying both, and why the
  single-bill path was left exactly as it was when the endpoint learned to take
  `allocations` and hand them to `purchase_payment_service.create_payment_core`
  — the multi-bill engine whose only caller had been the bank match queue, so
  one NEFT against six bills meant six payments, six fabricated references and
  six journal entries. **A reader that knows one shape is silently wrong about
  the other**, and one was: `msme_43bh_service._payments` read only the bridge
  table, so §43B(h) saw every bill paid from the Purchases screen as NEVER PAID
  and added a timely payment back to taxable income — invisibly, because "no
  payment found" and "paid late" produce the same disallowance. Each shape has
  its own not-undone test: `is_voided` on the allocation row, `is_reversed` on
  the payment row, both filtered in PYTHON so a row lacking the key reads as
  live. `GET /api/purchase-payments?purchase_bill_id=` unions the two and
  stamps `allocated_to_bill_paise`, because `amount_paise` stops being the
  bill's figure the moment one payment settles several.
- **HOW LONG A CARRIED-FORWARD LOSS LIVES IS PER HEAD, AND ONE OF THEM IS NOT
  EIGHT YEARS.** `domain/income_tax/loss_set_off.py` decides WHICH HEAD a
  brought-forward loss may reach; `domain/income_tax/loss_carry_forward.py` is
  the separate authority for HOW LONG — §72(3) eight assessment years for a
  business loss, **§73(4) FOUR for a speculation loss**, §74(2) eight for
  either capital head and §71B eight for house property. The computation
  screen's own label read "§72 (Business, 8 yrs) · §74 (Capital, 8 yrs)",
  hardcoded — true of three heads and silent about the fourth — and the
  engine's expiry refusal quoted "§72(3)/§74's eight assessment years" for
  every head including speculation. Both name the head's own section now, and
  `GET /api/itr/loss-types` serves the vocabulary so the form holds neither a
  head nor a period.
  **`brought_forward_losses` WAS READ AND NEVER WRITTEN** (IT-10's other half):
  `POST /api/itr/bf-losses` has existed since migration 156 with no caller and
  the panel listing them was read-only, so every client showed "No
  carried-forward losses recorded" for ever with a fully built set-off engine
  behind it. **`expiry_assessment_year` was a REQUIRED caller-supplied field**,
  so the one statutory fact in the row was whatever was typed; it is derived
  now and a caller-supplied value still WINS (`domain/tds/deductor.resolve`'s
  shape). **Two refusals rather than guesses**: `other` means the head is not
  identified, so no section fixes a period and it is refused rather than given
  eight years, and **§32(2) unabsorbed depreciation and §73A's specified-business
  loss carry forward INDEFINITELY** and are absent from the stored vocabulary —
  named on the form, because recording one as `other` with any expiry would
  expire a loss that never expires. ⚠️ Every period is `[S]`-graded, `VERIFIED`
  is False and each is pinned by a test: the error direction is unsafe BOTH
  ways, since too short expires relief the client is entitled to and too long
  claims relief they are not.
- **A capital LOSS does not relieve other income** (§71(3), §74), and **§80G has
  a ceiling** (§80G(4): 10% of adjusted gross total income, where adjusted GTI
  is GTI less the capital-gains buckets and less every other Chapter VI-A
  deduction). §80G's four categories are the PRODUCT of two independent facts
  about the donee — the percentage and whether the qualifying limit applies —
  so `Donation80G` carries both, defaulting to "subject to the limit" because
  that is the residual category the section itself puts an unlisted donee in.
  §80G(5D) bars a cash donation over ₹2,000 outright.
- Advance tax due dates: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
- ITR (IT Act §139): 31 July, or 31 October where audit applies, or 30 November
  where a §92E transfer-pricing report is required
- **The §44AB AUDIT REPORT is due a month before the RETURN, and they are two
  dates.** Explanation (ii) to §44AB (substituted by the Finance Act 2020,
  w.e.f. AY 2020-21) defines the "specified date" as "date one month prior to
  the due date for furnishing the return of income under sub-section (1) of
  section 139" — so **30 September**, not the 31 October the return is due.
  Dating the report at the return's date shows every audit client a deadline a
  month late, on the obligation whose lateness carries §271B (0.5% of turnover,
  capped at ₹1,50,000), and it is the wrong sequence: §139(1)'s own date
  assumes the report is already on record.
  `compliance_engine.tax_audit_report_due_date` DERIVES it from
  `itr_due_date` rather than stating it, so a CBDT extension of one moves the
  other. The §92E variant is deliberately not modelled — "one month prior" to
  30 November is 30 October by calendar arithmetic while professional sources
  commonly say 31 October, and that one-day difference is unconfirmed.
- **WHETHER §44AB applies is `domain/income_tax/tax_audit.py`, and the NATURE
  OF THE ACTIVITY is an input, never inferred from the amount.** §44AB(a)
  reaches a person carrying on BUSINESS and §44AB(b) a person carrying on a
  PROFESSION — different clauses, different figures, and which applies is a
  fact about the client. The Tax Audit tracker used to decide it in three lines
  of TypeScript: above ₹1 crore "business", between ₹50 lakh and ₹1 crore
  "profession", so a trader with ₹60 lakh of turnover — whom clause (a) does
  not reach at all — was told an audit was mandatory, and §271B charges 0.5% of
  turnover capped at ₹1,50,000 on exactly that obligation. **The proviso to
  §44AB(a) needs FOUR figures, not two**: cash receipts against turnover AND
  cash payments against total payments, and the payments denominator cannot be
  derived from turnover — so the ₹10 crore limb is applied only when all three
  are stated, and the base figure stands otherwise, which is the direction that
  cannot cause a missed audit. **Clauses (c), (d) and (e) are NOT tested and are
  NAMED on every answer**, a "not required" one included: each compares DECLARED
  profit against a figure deemed by §44AE/§44BB/§44BBB/§44ADA/§44AD(4), and no
  turnover box carries that. ⚠️ Every year is `verified=False` — the figures are
  `[S]`-graded, reconciled against `presumptive.py`'s 5% cash test rather than
  read off a Finance Act. One reconciliation is worth keeping: **the Finance Act
  2023's ₹75 lakh is §44ADA's PRESUMPTIVE limit, not §44AB(b)'s AUDIT
  threshold** — `apps/web/lib/income-tax/taxAuditThresholds.ts` said otherwise
  in its own comment and is deleted.
- **Which ITR date applies is decided, or refused, in
  `compliance_obligation_service.itr_due_date_for_client`.** Explanation 2 to
  §139(1) settles it on facts the app holds in exactly three cases: (a)(i) a
  Companies Act company is 31 October on entity type alone; (a)(ii) a client
  with an active audit engagement is 31 October; (aa) a §92E report is
  30 November and outranks both. Everything else — LLP, Partnership, Trust,
  Proprietorship, Individual — is REFUSED: §44AB turns on the year's turnover,
  an LLP's audit on LLP Act §34(4) with Rule 24(8) (a different test entirely),
  a trust's on §12A(1)(b), and none of those figures is held against a client.
  The refusal returns 31 July, the EARLIER of the two, with `decided: false`
  and a named gap — early costs nothing, late costs §234A interest at 1% a
  month, a §234F fee and the §80 carry-forward.
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
- **A NIL ON A GSTR-3B SAYS WHICH KIND OF NIL IT IS.** Four rows of this
  product's GSTR-3B are nil because nothing here can DERIVE them, and on a
  filed return that is indistinguishable from a client who had none: **3.1.1(i)
  and 3.1.1(ii)** (§9(5) e-commerce — nothing marks a supply as made through an
  operator, so an aggregator's sales are counted in 3.1(a) like any other
  outward supply), **Table 5** (exempt / nil-rated / non-GST INWARD supplies — a
  purchase bill is not classified that way here) and **4(D)(2)** (§16(4) and the
  place-of-supply rules, neither tracked). Each carried its reason in a source
  COMMENT beside the literal zero, which is the right place for the next
  programmer and no place at all for the CA about to file. `_undeclarable_rows`
  in `services/gst_return_service.py` is the one list and it CALLS
  `_table_4a_gaps` rather than restating it, so the 4(A) rows keep one
  definition. **`table_4a_gaps` itself was served since GST-24 and rendered by
  nothing**, so even the ISD sentence reached nobody. No figure changes — what
  an underivable row needs is a document this product does not model, not a
  number from memory — and a test asserts no reason states a rate or an amount.
  **BOTH GSTR-3B SCREENS RENDER IT, FROM ONE COMPONENT** (GST-22).
  `components/gst/Gstr3bFindings.tsx` carries this panel, Table 5.1 and the
  bank-line note; the per-client tab spelled all three out inline and
  `computeGSTR3B` dropped the four keys on the way through, so the FIRM-LEVEL
  screen showed none of them and the two disagreed about how much of the return
  they show. Three older guards had that page's PATH written into them and
  failed on a move that did not break their rule — `scripts/panelSource.ts`
  resolves a panel by a phrase only it contains and asserts there is exactly
  one, which is the same rule stated once instead of three times.
- **GSTR-3B TABLE 4(A) HAS FIVE ROWS, AN IMPORT OF SERVICES OWNS ONE OF THEM,
  AND TWO ARE STRUCTURALLY NIL** (GST-24). `itc_avl_rows` emits all five in the
  GSTN utility's order and used to put the WHOLE reverse-charge credit on
  4(A)(3) ISRC — the DOMESTIC §9(3)/(4) line. An import of services is
  reverse-charged too (Notification 10/2017-IT(R) entry 1), so on the books it
  is indistinguishable from a GTA or advocate bill, and it went out on the
  wrong line. IGST §2(11) defines it — supplier outside India, recipient in
  India — and the only fact separating them is
  `vendors.residential_status`, read through
  `domain/tds/residency.is_non_resident` rather than compared as a string,
  because **NULL is a real third state and must not move a figure**: an
  unclassified vendor stays exactly where every vendor already is.
  **The split touches the ROW and nothing else** — the 3.1(d) liability, the
  4(A) total, 4(C) and the challan are pinned unchanged by a parametrised
  test, because `imps_*` is a SUBSET of `rcm_*` accumulated inside the same
  branch and never added to it. **The two capped rows are capped IN ORDER**:
  IMPS takes the ceiling first and ISRC takes what is left, since capping each
  independently against the same ceiling lets them together exceed it and file
  a 4(A) that does not reconcile with its own 4(C). **4(A)(4) ISD stays nil and NAMES why**
  (`table_4a_gaps`): an ISD invoice is not modelled. A nil meaning "we cannot
  see it" is not a nil meaning "there was none". **4(A)(1) IMPG left that list
  on 2026-09-14** — migration 389 gave the Bill of Entry a document, see the
  PUR-18 bullet above — and it is still not a reverse-charge row: the tax is
  collected at customs, not self-assessed, so it never touches 3.1(d).
- **A BANK LINE THE CA MARKED AS CARRYING GST IS A DOCUMENT, AND THE
  DOCUMENT IS THE TRANSACTION** (BANK-24). The posting drawer has always let a
  CA say "there is 18% GST inside this ₹590", and `bank_posting_service` then
  posts a real Dr GST Input leg (CGST §16 — a bank charge is an input service
  received in the course or furtherance of business). GSTR-3B is built from
  DOCUMENTS, and a bank line is not a purchase bill, so the credit the CA
  declared never reached Table 4(A) — while `_gl_gst_movements` DOES read the
  GST Input account, so the same rupees came back as an unexplained
  books-vs-ledger ITC difference every month, on a return about to be filed.
  Money IN was the same defect and worse: `build_inclusive_lines(is_credit=
  True)` credits GST Output, so an outward supply's liability sat in the ledger
  and no return declared it. Migration 382 records the rate that was POSTED on
  `bank_transactions` — `draft_gst_rate_bps` (322) cannot serve, because the
  caller may override it and a line posted with no draft carries NULL — and
  **that is what keeps the reconciliation's two sides independently derived**:
  reading the tax back out of `journal_lines` would make this slice compare the
  ledger with itself, the same reason Table 4(B) is built from documents.
  `domain/gst/bank_charge_gst.py` is the rule; the inward side goes to
  **4(A)(5) "All other ITC"** (not 4(A)(3) — the bank charges the tax and pays
  it over, and the reverse-charge row would also create a 3.1(d) liability that
  does not exist) and the outward side to **3.1(a)** through the one
  `_outward_transactions` Rule 43's turnover also reads. Three refusals are
  deliberate: **a recorded ZERO declares nothing** (it posts identically to an
  unmarked line, so nothing says whether a receipt is nil-rated, exempt,
  outside the levy — or not a supply at all), **never Table 3.2** (no recipient
  state, no recipient class; the `SalesTransaction` defaults keep it out by
  construction — do not helpfully fill them in), and **no §17(5) split**. What
  cannot be computed is NAMED on every answer that carries one: §16(2)(aa)
  wants a supplier document a bank line does not hold, and an outward supply
  with no tax invoice will not be in the GSTR-1 the portal compares this return
  against (Rule 46). **No GSTIN is invented** — the finding's own suggested fix
  would have put one on a bank table so the 2B match passed, which is claiming
  a document exists.
- **A FIXED-ASSET DISPOSAL IS A SUPPLY, AND CGST §18(6) CHARGES THE HIGHER OF
  TWO LIMBS** (FA-08b, migration 383). `journal_for_asset_disposal` posted four
  lines — accumulated depreciation cleared, the whole proceeds to bank, the
  asset out at cost, the gain or loss balancing — and NO tax line at all, and
  `DisposalIn` had no field that could have driven one. So the sale of a
  capital asset was never declared: nothing in the ledger, nothing on the
  return, and the CA had to remember to raise a separate sales invoice.
  §18(6) charges "the input tax credit taken on the said capital goods ...
  reduced by such percentage points as may be prescribed **or** the tax on the
  transaction value ... **whichever is higher**", so an asset sold cheap early
  in its life pays back CREDIT rather than tax on the price — the case a plain
  output-tax line under-declares by an order of magnitude.
  `domain/gst/section_18_6.py` is the authority.
  ⚠️ **TWO RULES PRESCRIBE THE REDUCTION AND THEY DISAGREE**, so BOTH readings
  are reported and neither is chosen — the `interest_on_rule_37_reversal`
  shape, for the same reason: this is a sum the CA pays over. Rule 40(2) is
  five percentage points per **quarter or part thereof** from the invoice date;
  Rule 44(6), through Rule 44(1)(b), pro-rates the credit over the **remaining
  useful life in months out of sixty**. At 38 months that is 35% against
  36.67%. `[S]` — every `.gov.in` is refused at this environment's proxy.
  **The part DAYS count in Rule 40(2)**: three months exactly is one quarter, a
  single day more is two, so the count cannot be `ceil(whole_months / 3)`.
  **The comparison is on the TOTAL**, not head by head — Rule 44(6)'s
  "determined separately for ... central tax, State tax" governs how limb (a)
  is worked out, not how the two limbs are ranked; ranking per head would pay
  the credit limb on one head and the value limb on another, which is not a
  figure the section describes. **Every rounding goes UP** (a sum the taxpayer
  owes) and a part month does NOT count as elapsed, which leaves the remaining
  life larger and the charge larger — the direction that cannot leave a
  shortfall. **Only limb (b) is POSTED**: the tax on the transaction value is
  what the buyer paid and is not in doubt, while the excess has two readings
  and no invoice behind it, so the CA raises it — `itc_register_service`'s
  judgement about Rule 37. The **proceeds are TAX-INCLUSIVE** and the tax is
  backed out with `charge_gst.split_inclusive_charge`, so the journal balances
  with no plug and the **gain is measured on the consideration NET of tax** —
  the buyer's tax is not the seller's proceeds. Migration 383's three columns
  are all STATED: `disposal_is_supply` (nullable, NO default — a scrapping for
  nothing and a sale are the same row shape), `disposal_gst_rate_bps` and
  `disposal_is_interstate` (an asset bought locally may be sold across a state
  border, and §18(6) does not say which head the credit limb is then paid in —
  NAMED, never resolved). The return reads those columns as the document and
  declares the supply in **3.1(a), never 3.2**. Two more refusals: no credit
  taken means §18(6) does not reach the supply at all (only §9 does), and an
  asset that does not RECORD its credit position is a named gap rather than
  assumed nil. `GET /api/fixed-assets/{id}/disposal-preview` writes nothing and
  runs the same module, so what the CA is shown before confirming is what gets
  posted.
- **THE ANNUAL RETURN CONSOLIDATES THE YEAR'S OWN RETURNS, AND NOTHING ADDED
  THEM UP** (GST-10). CGST §44 with Rule 80(1): GSTR-9 consolidates the
  financial year's GSTR-1 and GSTR-3B, and the portal opens it once every one
  of them is furnished and auto-populates from them. The GSTR-9 tab loaded a
  saved draft and **nothing created one** — every figure was already in the
  product and nothing totalled them. `domain/gst/gstr9_builder.py` is the
  authority for Tables 4, 5, 6, 7, 8, 9 and 17; `services/gstr9_service.py`
  fetches; `GET /api/gst-workspace/gstr9/compute` serves; the screen decides
  nothing, saves nothing and files nothing.
  **IT READS `payload_json`, NOT `gstr3b_returns`' OWN PER-HEAD PAISE COLUMNS.**
  Migration 036 declared them and **`save_gstr3b` has never written one** — it
  stores `tax_liability_paise`, `itc_claimed_paise`, `net_tax_paise`,
  `rcm_cash_paise`, `cash_payable_paise` and the two JSON blobs, and every other
  column keeps its `DEFAULT 0`. Reading them would give a confident nil for
  every month of every client, which is the worst possible answer on an annual
  return. Twenty-four header rows and their payloads for a year — proportional
  to the ANSWER.
  **A STORED RUPEE FIGURE COMES BACK THROUGH `Decimal(str(v))`, NEVER
  `int(v * 100)`.** GSTR-1's payload is 2-decimal rupees and GSTR-3B's is whole
  rupees, and in binary floating point `0.29 * 100` is 28.999999999999996 — a
  paisa lost, on some values only, twelve months over, on a return that has to
  foot. That is not a precision loss overall: the annual return consolidates
  what was DECLARED, and what was declared was those rupees.
  **TABLE 4(A)'s FIVE ROWS ARE TABLE 6's ROWS.** GST-24 split imports of
  services out of the domestic reverse-charge line and PUR-18 gave imports of
  goods a document, so IMPG→6E, IMPS→6F, ISRC→6C+6D and OTH→6B are already told
  apart in the return being consolidated; there is nothing to apportion. And
  the `b2b` section carries Tables **4B, 4D, 4E and 5B** at once, told apart
  only by `inv_typ` — a test reads `gstr1_builder._INV_TYP` so a value added
  there without a home here fails rather than falling into 4B and declaring a
  deemed export as an ordinary B2B supply.
  **TABLE 7 IS THE ONE GSTR-3B CANNOT ANSWER.** Its Table 4(B) has two boxes,
  permanent and reclaimable, and Rules 38, 42, 43 and §17(5) share one;
  `itc_reversal_register` records the statutory GROUND (migration 362), which
  is exactly what Table 7 asks for. A ground with no row is NAMED and kept OUT
  of the total rather than folded into "other reversals". **The year is
  selected by `period`, the register's own MMYYYY of the GSTR-3B the row was
  declared in** — there is no reversal DATE column, and §44 with Rule 80(1)
  consolidates the returns FURNISHED for the year, so the period is the right
  key as well as the only one. `.in_` over the twelve named periods and never
  a range: MMYYYY is TEXT, so `'042025' > '032026'` and a `gte`/`lte` would
  drop the first nine months of every year and keep three belonging to the
  next. The first draft filtered on an invented `reversal_date` and the mock
  suite agreed, because the FIXTURE invented it too — which is why that test
  module now asserts every fixture key against the production snapshot.
  **A NIL ON AN ANNUAL RETURN DECLARES THAT NOTHING WAS OWED, so a row nobody
  can derive carries a NOTE and renders as a dash.** Six are refused and named:
  Table **6B's three-way split** (inputs / capital goods / input services — no
  column records it and it is a judgement about USE; the TOTAL is derived, only
  the apportionment is not), **6C against 6D** (recorded on
  `vendors.gst_registration_status` but not carried by the monthly 3B being
  consolidated), **Rule 39 / 6G** (no ISD invoice is modelled), **TRAN-I and
  TRAN-II**, **8C** (a fact about the NEXT year's returns), and **8A** (the
  portal auto-populates it; totalling a year of `gstr2a_records` is a read
  proportional to transaction volume for a four-number answer — a stored
  per-period total is the right next step and is a migration). **A month FILED
  but whose payload this product never held** is named too: its tax is in the
  3B row and its Table 4 breakdown is not.
  **Tables 10–14, 15, 16, 18 and 19 are NOT built and each says why** —
  §47's late-fee rates are deliberately EMPTY in `domain/gst/late_filing.py`,
  so Table 19 must not invent one. ⚠️ The FORM's own numbering and row labels
  are `[S]`, written from knowledge because every `.gov.in` is refused at this
  environment's proxy; the FIGURES are not affected, each being a total of
  figures this product computed and the CA filed.
- **GSTR-3B Table 3.1(a) carries GSTR-1 TABLE 11, and the ledger cannot.**
  §13(2) puts the time of supply for SERVICES at the earlier of invoice or
  payment, so tax on an advance received for services falls due on receipt,
  before any invoice exists; Notification 66/2017-Central Tax removed the
  charge for GOODS (§12(2) proviso), which is why the whole of Table 11 is
  gated on the client's own `gst_advance_tax_applicable` and why it is off by
  default. `gst_advance_service.table_11_sections` builds the GSTR-1 rows AND
  totals the same buckets in paise for 3.1(a) — one `split_inclusive_charge`
  per bucket, because two independent computations of one figure is how the
  two returns came to disagree: 3B had no advances input at all, so a client
  with the flag on filed a GSTR-1 declaring a liability and a GSTR-3B that
  discharged none of it (GST-15). **11A less 11B, and both halves are
  required** — the invoice that consumes an earlier period's advance is in
  this period's sales and carries its whole value again, so 11A alone would
  replace an under-declaration with a double charge. The net is deliberately
  NOT clamped. **It is not in Table 3.2**: a receipt records no recipient
  class, so a 3.2 bucket would assert a fact the books do not hold. And it is
  **declared but not posted** — a receipt journal is Bank Dr / Trade
  Receivable Cr with no output-tax leg — so `gst_return_service` holds it out
  of the books-to-ledger comparison and NAMES the amount
  (`advance_tax_excluded_paise`) rather than reporting every advance-bearing
  client as permanently unreconciled.
- **GSTR-3B Table 6 — the set-off has FOUR steps, and the total is not the
  challan.** §49(5)(a) spends IGST credit on IGST and then, with Rule 88A, on
  CGST and SGST; §49(5)(b) then lets CGST credit pay CGST **and then IGST**, and
  §49(5)(c) lets SGST credit pay SGST and then IGST. CGST is worked before SGST
  because the proviso to §49(5)(c) allows SGST credit against IGST only where
  CGST credit is not available for it. §49(5)(e)/(f) bar CGST↔SGST entirely.
  Implementing only the IGST limb left local credit stranded and demanded cash
  the client did not owe. **Reverse-charge tax is never part of that**: §49(4)
  allows the credit ledger to pay only "output tax", and §2(82) defines output
  tax as EXCLUDING "tax payable by him on reverse charge basis" — so §9(3)/(4)
  tax is always cash, always on top, and `cash_payable_paise` rather than
  `net_*` is the challan figure. **A zero-rated supply carries tax when it is
  made on payment of tax** (§16(3)(b), refunded under §54); nil only under an
  LUT or bond (§16(3)(a)). `domain/gst/gstr3b_computer.py` is the authority for
  all three, and the callers carry them — a figure the computer gets right and
  no screen shows is not a fixed bug.
- **A RULE 37 REVERSAL CARRIES §50(1) INTEREST, AND THE CLOCK IS NO LONGER IN
  THE RULE** (GST-28). Rule 37(1) with the second proviso to §16(2) requires
  credit on a bill 180 days unpaid to be paid back "along with interest payable
  thereon under section 50", and `rule37_report` stated the tax and stopped.
  The RATE is settled: §50(3) reaches credit "wrongly availed AND UTILISED",
  which Rule 37 credit is not — it was validly availed and the consideration
  went unpaid — so §50(1)'s 18% applies, and that also matters because §50(3)'s
  own notified rate is a named gap here. ⚠️ **The PERIOD is not settled**:
  Notification 19/2022-Central Tax substituted the whole of Rule 37 from
  01-10-2022 and its sub-rule (3), which ran the clock "from the date of
  availing credit on such supplies", did not survive the substitution. So
  `interest_on_rule_37_reversal` takes the window rather than choosing it, and
  the report shows BOTH readings — from availment and from the 180th day — with
  the caveat naming what was omitted. Picking one silently would over- or
  under-state a sum the client pays over. The panel sums over the bills THIS
  return carries, never every overdue bill: Rule 37(1) puts each reversal in
  one specific return, and an earlier one's interest belongs to a return
  already filed. **A one-click "Post this reversal" is deliberately NOT built**
  — `itc_register_service` records why, and a guard asserts no such button
  appeared.
- **RULE 37A IS THE SUPPLIER'S DEFAULT AND RULE 37 IS THE RECIPIENT'S; THEY
  SHARE A BOX AND NOTHING ELSE** (GST-28, second half). `itc_reversal_register`
  has accepted a `rule_37a` ground since migration 362 and GSTR-3B Table
  4(B)(2) has a slot for it, and nothing produced a figure. Rule 37A
  (Notification 26/2022-Central Tax): where a supplier DECLARED the invoice in
  GSTR-1 but has not furnished the GSTR-3B for that period by the **30th of
  September** following the end of the FY the credit was availed in, the
  recipient reverses it by the **30th of November** following — and an
  unreversed credit is payable with §50 interest. `domain/gst/rule_37a.py` is
  the rule and `services/rule_37a_service.py` fetches.
  **BOTH DATES HANG OFF THE END OF THE AVAILMENT YEAR**, which is the part that
  is easy to get wrong twice over: the FY's own September and November would be
  a year early, and "sixty days after the supplier's date" two months late.
  **THE ONE FACT THIS PRODUCT CANNOT HOLD IS WHETHER THE SUPPLIER FILED**, and
  it is NAMED on every answer rather than guessed — GSTR-2B is generated FROM
  filed GSTR-1s, so a document appearing in it proves the GSTR-1 and says
  nothing about the 3B, and `gstr2a_records.supplier_filed_on` is the trap
  (it is the GSTR-1's date, so reading it would report every supplier as
  compliant). Guessing "filed" leaves a reversal undone with interest running;
  guessing "not filed" reverses credit the client is entitled to.
  `supplier_filed_gstr3b` is typed `null` in the browser so a screen cannot
  fill it in.
  **THE POPULATION IS THE MATCHED DOCUMENTS**, read from `gstr2a_records`
  rather than from `purchase_bills`: the rule reaches a supply whose invoice
  the supplier DID declare in GSTR-1, which is exactly what a 2B match proves,
  and a bill missing from 2B is §16(2)(aa) and belongs in the reconciliation.
  An empty answer is a NAMED gap, not a clean bill of health. **The §50
  interest is deliberately NOT computed** — the rule does not say which date it
  runs from, and `late_filing.interest_on_rule_37_reversal` already shows two
  readings for the same silence in Rule 37; a single figure here would be a
  third answer to an open question. Nothing is posted: the CA raises the
  journal and registers it with ground `rule_37a`, which is RECLAIMABLE
  (4(B)(2), released into 4(D)(1)) because the rule lets the credit be
  re-availed once the supplier files. ⚠️ Every date is `[S]`-graded and pinned.

- **WHAT BEING LATE COSTS IS `domain/gst/late_filing.py`, and half of it is a
  REFUSAL.** §50(1) interest is COMPUTED — 18% (Notification 13/2017-Central
  Tax), and Rule 88B(1) is the load-bearing part: where the supplies are
  declared in a return furnished after the due date, interest runs only on
  "that portion of the tax which is paid by debiting the electronic CASH
  ledger", so a head the credit ledger discharged in full bears NONE however
  late the return is, and charging on the gross output tax demands several
  times what is due. `cash_payable_*` is that base and is the same figure Table
  6 pays the challan with. Rule 88B(2) is the other case — tax NOT declared in
  the return, found in a §73/§74 proceeding — and there it IS the whole tax
  from the date it fell due, so a caller that used the cash figure would
  understate it. **§50(3) REFUSES TWICE OVER.** Its base is credit wrongly
  availed **AND UTILISED** (Rule 88B(3)), never the availed figure — credit
  availed and never utilised bears nothing, so the substitution would charge a
  taxpayer who owes nothing. And **its RATE is a named gap, not 24%**: the
  Act's own ceiling is "not exceeding twenty-four per cent" and Notification
  13/2017-CT notified 24% against the ORIGINAL sub-section, but the Finance
  Act 2022 substituted §50(3) retrospectively from 01-07-2017 and Notification
  09/2022-CT appears to notify **18%** for the substituted text. A THIRD of
  the charge separates the two and this is money a CA pays over on the
  client's behalf, so over-stating takes it from somebody who does not owe it —
  the opposite direction from the ESI rounding, and the reason this one refuses
  where that one rounds up. `SECTION_50_3_NOTIFIED_RATE_BPS` is `None` and the
  engine works the moment a figure is written in.
  **THE §47 LATE FEE IS NOT COMPUTED AT ALL.** The statutory ₹100 a day per Act
  capped at ₹5,000 is held so nobody has to look up what the notifications
  reduced, and is deliberately NOT a fallback — no registered person has paid
  it since 2018 (Notifications 4/2018 and 76/2018 reduced it; 19/2021 and
  20/2021 capped it by turnover band), and ₹200 a day where ₹50 is notified is
  four times a figure a CA would pay over. `LATE_FEE_RATES` is EMPTY and adding
  a row is a human step like the state professional-tax slabs. Two conventions
  are stated rather than assumed: **DAYS, not months** (due 20 July, paid 21
  July is one day — NOT the §201(1A) "month or part of a month" arithmetic,
  which would be thirty times wrong here), and **rounded UP**, because interest
  is a sum the taxpayer OWES and understating it leaves a residual demand —
  the same direction ESI takes and the opposite of the GST discount, which
  floors because there understating cannot under-declare tax. ⚠️ Two `[S]`
  points, both failing generous: the divisor is 365 even in a leap year, and
  the 2020 concessional-rate notifications are NOT held, so a period they
  covered is charged at 18% and SAYS SO in its caveats.
  **`filed_on` is OPTIONAL everywhere it appears** — a return being prepared
  has no filing date, and defaulting to today would put a figure on Table 5.1
  that changes every day the return is not filed.

- **COMPENSATION CESS HAS TWO LIMBS, ITS OWN LEDGERS, AND IS NEVER PART OF
  `total_gst_paise`.** GST (Compensation to States) Act 2017 §8(2) levies "on
  the basis of VALUE, QUANTITY or on such basis", and real Schedule entries use
  each: aerated waters and motor vehicles ad valorem, coal at so much per
  tonne, cigarettes a percentage PLUS a figure per thousand. So a line carries
  `cess_rate_bps` AND `cess_specific_paise_per_unit` (migration 374, the second
  named to match `firm_hsn_rate_history`'s column from migration 181) and the
  charge is their SUM — a single percentage column silently under-charges coal
  and tobacco. `domain/gst/compensation_cess.py` is the authority and
  `apps/web/lib/money/cessLine.ts` the keystroke mirror, pinned by
  `shared/gst-parity-vectors.json`. **The AMOUNT is derived, never typed**, for
  the reason cgst/sgst/igst are derived from `gst_rate_percent`. **Both
  roundings match the GST heads** — floor the ad valorem limb, truncate the
  per-unit one — because §11(2) applies the CGST Act mutatis mutandis and a
  cess rounding the other way would disagree with the GST on its own line.
  **§11(2)'s proviso is what keeps it separate all the way down**: credit of
  this cess "shall be utilised only towards payment of cess", so it has its own
  asset (`Compensation Cess Input Credit`) and its own liability
  (`Compensation Cess Payable`) rather than the GST Input/Output ledgers,
  `gstr3b_computer` keeps the head out of the §49(5) set-off ladder, and it is
  in `total_paise` (the customer owes it) and NOT in `total_gst_paise` (what
  Table 6 sets off). **The two ledger NAMES avoid the substrings "GST Input"
  and "GST Output" deliberately** — those are `_find_account`'s ILIKE
  fallbacks, matched `.limit(1)` with no ordering, so a cess account matching
  one could be returned for a CGST lookup on any chart without per-head
  accounts, which is every chart this product seeds. The per-unit figure is per
  the LINE'S OWN UQC; nothing converts tonnes to kilograms. **No rate table is
  held**: which cess reaches which HSN is Schedule data that moves by Council
  notification, the same human step as the state PT slabs. Three things are
  named rather than modelled — a "whichever is HIGHER" Schedule entry (record
  the limb that applies), the four §34 NOTE tables (they have no cess column,
  so a note against a cess-bearing invoice is reported in the return's
  `cess_gaps` rather than silently declaring nil), and no upper bound on the
  rate, because Schedule column (4) carries entries above 100%.
- **A discount on the invoice reduces the value of supply; a discount after it
  does not, and the two are different sections.** §15(3)(a) excludes a discount
  "given before or at the time of the supply if such discount has been **duly
  recorded in the invoice**" — so the tax is charged on the NET and the relief
  is conditional on the document showing it, which is why the discount is a
  column of its own rather than a smaller rate, and why the PDF prints gross,
  deduction and net. §15(3)(b) reaches a POST-supply discount only where it was
  established in an agreement at or before the time of supply, is specifically
  linked to the invoices, AND the recipient has **reversed the attributable
  ITC** — that is the §34 credit note, not a field on one, and
  `models.invoices.InvoiceLineIn` (which the note routes use) deliberately has
  no discount field while `SalesInvoiceLineIn` does. `domain/gst/discount.py`
  is the rule; a **document-level** discount is allocated pro-rata across the
  lines BEFORE tax, because GST is charged per line at the line's own rate and
  a bill-level deduction could not otherwise be taxed on an invoice with mixed
  rates. Line discount first, then the document one on what is left. Every
  rounding floors — a larger discount is less tax, so flooring is the direction
  that cannot under-declare — and the pro-rata split uses largest-remainder so
  the parts sum to the whole exactly. `apps/web/lib/money/gstLine.ts` mirrors
  all of it and `shared/gst-parity-vectors.json` pins the two.
- **A TAX INVOICE'S NUMBER IS A STATUTORY FIELD WITH FOUR LIMBS, and the product
  used to enforce two.** CGST Rule 46(b) requires "a CONSECUTIVE SERIAL NUMBER not
  exceeding SIXTEEN CHARACTERS ... containing alphabets or numerals or special
  characters hyphen or dash and slash ... UNIQUE FOR A FINANCIAL YEAR".
  `domain/gst/invoice_series.py` is the authority for all four.
  **Length and the character set REFUSE** — at create, at edit, at bulk import and
  at issue; no legitimate series needs seventeen characters or a `#`, and both the
  GSTR-1 schema and the IRP reject them anyway. **A break in the SEQUENCE only
  WARNS**, because a gap has legitimate causes — a client arriving mid-year with a
  series already running, a cancelled invoice, or a second series, which the rule
  expressly allows ("one or multiple series"). **Uniqueness is enforced stricter
  than the rule** — per client full stop, not per FY (migrations 151/209).
  **Numbering is no longer "fully manual"**: that decision was recorded in three
  places and is reversed as of 2026-09-12 (SALES-12). `invoice_settings`
  (migration 126) has always held the firm's prefix, FY flag, padding and starting
  number; nothing read them. `services/sales_numbering_service.py` now does, and
  `GET /api/sales-invoices/next-number` suggests the next number for the form to
  pre-fill. The box stays editable and what is written is still whatever the
  request carries — Tally's "Automatic (Manual Override)", which is the mode a
  practice actually runs. **The rule has exactly two implementations**, the Python
  authority and `apps/web/lib/invoices/gst.ts`'s keystroke mirror, pinned by
  `tests/fixtures/invoice_number.json` which both suites read; `models/invoices.py`
  delegates rather than carrying a third. **A series with the FY switched OFF does
  not restart each April** — the client-wide unique index would reject the
  collision — so the sequence keeps climbing, and that falls out of matching on the
  series head rather than being special-cased.
- **HOW MANY DIGITS OF HSN A RETURN MUST CARRY IS `domain/gst/hsn_digits`, AND
  THE TABLE THAT USED TO LIVE IN THE BUILDER WAS A HYBRID OF TWO
  NOTIFICATIONS** (GST-17, migration 401). `_required_hsn_digits` returned 6
  above ₹5 crore, 4 above ₹1.5 crore and 0 below — the ₹1.5 crore rung is the
  PRE-2021 table's and the digit counts beside it are the POST-2021 table's,
  so it existed in no notification at all. **Notification 78/2020-Central Tax**
  (15-10-2020, in force 01-04-2021) is 6 digits above ₹5 crore on every supply
  and **4 digits on B2B at or below it**, optional only on B2C — so a client
  with ₹1 crore of turnover was told HSN was optional when four digits are
  required on every B2B supply however small the turnover. Both tables are
  held and the PERIOD decides, because a belated GSTR-1 for a 2019 period is
  filed under the rule in force then: the fork shape again.
  **NOTHING TRUNCATES, AND NOTHING EVER DID.** The requirement's one consumer
  was `code = (line.hsn_sac_code or "")[:max(required, len(code))]`, a slice
  whose length is the LARGER of the requirement and the code's own length — so
  it can never shorten anything. A 2-digit HSN at ₹10 crore came back as `99`,
  was filed as `99`, and appeared in no gap list. The code is filed exactly as
  recorded now (the notification sets a FLOOR, so a longer code is already
  compliant and truncating for real would file a number the client never
  issued) and the shortfall is REPORTED in `payload_gaps`, beside Table 12's
  unit gaps and for GST-29's reasons. **The digit check runs BEFORE the walk's
  `continue`**, which is the one place it must differ from the UQC gap: a line
  with no HSN is exactly what the requirement is about and is the line Table 12
  drops, so checking after the skip would report every shortfall except the
  complete absence.
  **THE SPLIT IS PER SUPPLY, NOT PER RETURN** — resolved inside the loop from
  the invoice's own category against `classifier.B2B_SECTION_CATEGORIES`
  (derived, not listed, because B2C is the side where the requirement falls
  away and a miss would UNDER-report).
  **AGGREGATE TURNOVER IS THE PRECEDING YEAR'S, IS RECORDED, AND `None` IS A
  THIRD STATE.** CGST §2(6) is computed on the PAN, ALL-INDIA, and includes
  exempt supplies, exports and inter-State supplies between distinct persons —
  a second registration's supplies count toward it — so it cannot be derived
  from one client's books, and it is NOT `tax_audits.turnover_paise` (§44AB
  turnover, different figure, different year). Migration 401's
  `client_gst_turnover` holds it per financial year (a single column on
  `clients` would be overwritten each April and re-tier every belated return),
  keyed on the year the figure MEASURES with the preceding-year hop in
  `governing_financial_year`. `lib/data/gst.ts` used to send
  `aggregate_turnover_paise: 0`, which is a REAL turnover meaning "below every
  threshold" — so every client was silently told HSN was optional and no gap
  was ever reported. It sends nothing now and the service resolves it; `None`
  takes the STRICTEST reading and says so, because under-reporting the
  requirement files a return the portal rejects while over-reporting costs a
  glance. The unrecorded sentence is emitted ONCE and only where a shortfall
  was actually found — a client whose codes are all six digits owes nothing
  whatever their turnover was. ⚠️ Both tables are `[S]`-graded (egress is
  refused here) and every threshold and digit count is pinned exactly by
  `tests/test_how_many_hsn_digits_a_return_must_carry.py`.

- **A UNIT QUANTITY CODE IS A CODE, NOT A WORD, and the one module that knew
  which codes exist had ZERO IMPORTERS.** `models/uqc.py` held CBIC's fixed
  44-code list and named, in its own docstring, every place it was meant to be
  used; three validators cited `VALID_UQC_CODES` in their COMMENTS and none
  imported it. So `gstr1_builder` put `line.unit` straight into Table 12's
  `uqc` and three things reached a return unremarked: **`'PIECES'`** where the
  code is `PCS`, **`None`** — a JSON null where the schema wants a string — and
  **10 BOX + 5 PCS summed to 15 and filed as BOX**, a quantity that is not a
  quantity of either. The same `public.tds_section_limits` shape: a module
  whose name reads like the authority and which nothing reads.
  `domain/gst/uqc.py` is the authority now, with the RULE over the list —
  `problem_with` is shaped like `gstin.problem_with` deliberately, one shape
  for "what is wrong with this identifier". It moved out of `models/` because
  that is the API boundary and a domain module importing from it is the wrong
  direction, the same reasoning that moved Schedule II Part C out of
  `routers/fixed_assets.py`; `models/uqc.py` re-exports.
  **NOTHING REFUSES, AND THAT IS GST-29's SPLIT APPLIED TO A DIFFERENT
  IDENTIFIER.** The carve-out the old validators recorded is still right — a
  product or a line may carry a pre-dropdown free-text unit (`HRS` for service
  hours), and refusing at the API boundary would make that row un-editable for
  any unrelated change. What was wrong was the conclusion drawn from it, *"the
  dropdown only offers valid UQC codes, so new data is compliant by
  construction"*, which is a claim about EVERY write door — and this codebase
  has found that claim false twice already. So the document is never refused
  and the RETURN reports, as `payload_gaps`, which the GSTR-1 screen already
  renders. The three answers are **NOT interchangeable** and a test says so:
  an absent unit cites Rule 46(h), a wrong one names the code it probably
  meant (`closest_code` is a suggestion and never a substitution, matched on
  the LABEL rather than by edit distance, which would pair `TON` with `TUB`),
  and a mixture names both units and says the quantity below is their sum.
  **THE FILED FIGURE IS NOT CHANGED.** Whether Table 12 may carry two rows for
  one HSN under different UQCs could not be checked — every `.gov.in` is
  refused at this environment's proxy — so the mixed case is REPORTED and the
  aggregation left alone, the `interest_on_rule_37_reversal` discipline: state
  the open question rather than answer it from memory. The real fix is the
  CA's anyway, since one HSN should have one unit.
  **ALL SIX DOORS ASK THE AUTHORITY** — `ServiceCatalogueIn`/`UpdateIn`,
  `InvoiceLineIn`, `PurchaseBillLineIn`, `FirmHsnLibraryIn`/`UpdateIn` — and
  the last pair had **no validator at all**, which mattered most because
  `routers/hsn.py` serves that `uqc` as a HINT that pre-fills an invoice line,
  so a value typed there propagates. The guard derives the door list from the
  AST and checks PER CLASS, because a module-level walk passes when only one of
  a create/PATCH pair is guarded. **`apps/web/lib/constants/uqc.ts` is the
  keystroke mirror** — seven editors render their dropdown from it — pinned
  from the PYTHON side, the Schedule III caption lesson: a guard in `apps/web`
  asserting the browser against a copy of itself passes whenever both drift
  together. There is deliberately **no endpoint**: a 44-entry constant that
  moves by CBIC notification would be a Singapore-to-Mumbai round trip, and the
  parity test already prevents the drift an endpoint would.
- **§34(2)'s window is measured from the ORIGINAL SUPPLY's financial year, not the
  note's own period, and the two diverge constantly.** A June 2025 invoice credited
  in January 2027 sits in a wide-open period — January 2027's GSTR-1 is not filed —
  and outside a window that shut on 30 November 2026.
  `routers/credit_notes.py` asked only about the note's own date (is its year
  locked, is its return filed); both are right and both are about the wrong period,
  so a note that can never lawfully reduce output tax was accepted and posted
  (SALES-25a). `domain/gst/credit_note_window.py` is the rule and **it WARNS rather
  than refusing**: §34(2) bars the tax ADJUSTMENT, not the document, so a
  post-window commercial credit note is lawful and simply carries no GST. Derived
  on every read rather than stored — it is a function of three dates and would go
  stale the day GSTR-9 is furnished. **§34(3) debit notes have NO such window**:
  §34(4) requires declaration in the month of issue and sets no outer limit. Do not
  add one.
- **An e-way bill's validity is arithmetic on the distance, and the distance is a
  field nobody used to ask for.** Rule 138(10) as amended by Notification
  94/2020-CT: one day per **200 km or part thereof**, or per **20 km** for Over
  Dimensional Cargo — and "one day" is **midnight** of the day following
  generation, per the Explanation, not a rolling 24 hours, so a bill raised at
  23:55 has five minutes of its first day left. `domain/gst/eway_validity.py`
  computes it; the Prepare screen now asks for distance, vehicle type and transport
  mode; `GET /api/eway-bill/records/{id}/validity` pre-fills the expiry, which used
  to default to TODAY. **The portal stays authoritative** — every answer carries
  `source`, a recorded date that disagrees is reported and never refused, and a
  missing distance returns a named gap rather than a guess. ⚠️ **The slabs are
  `[S]`-graded**, written from knowledge because this environment's proxy refuses
  every `.gov.in`; the pre-2021 slab was 100 km, so a misreading fails generous.
  Two deliberate refusals: the **20 km slab keys only on `vehicle_type =
  'over_dimensional'`** (the value the CHECK actually allows), and a
  `transport_mode = 'ship'` row takes the ordinary slab with a caveat, because the
  row cannot distinguish a multimodal ship LEG from a movement wholly by ship and
  the generous reading is the one that shows an expired bill as live.
- **Correction window** (CGST §37(3), §39(9), §16(4)): 30 November following the FY, **or
  the date GSTR-9 was furnished, whichever is EARLIER**. Filing the annual return early
  shuts the window early. `compliance_engine.correction_window_closes()` is the function
  to use — `november_30_cutoff()` is only the statutory outer limit and will tell a CA a
  correction is available when it is not. **The GSTR-9 date is RESOLVED FROM THE BOOKS**
  by `gst_amendment_service.annual_returns_filed` (`gstr1_returns` with
  `return_type='gstr9'`, `status='submitted'`), keyed **per financial year** — the source
  periods of one call straddle years, so a single date applied to all of them shortens
  the wrong one — and converted **UTC → IST** before the date is taken, because 20:00 UTC
  on 30 November is 1 December in India and the two fall on opposite sides of the cutoff.
  It used to take an `annual_return_filed_on` parameter that nothing ever passed, so every
  window reported the 30 November limit (GST-09).
- **§195 asks CHARGEABILITY before it asks a rate, and the resident sections do
  not reach a non-resident at all.** §194C, §194J and their neighbours charge, in
  their own words, sums paid "to a **resident**"; §195 charges a payment to a
  non-resident, "at the rates in force" under Part II of the First Schedule and
  §115A — by the NATURE of the income, with no threshold, plus surcharge and 4%
  cess, which the resident series does not carry. But §195 reaches only a sum
  "**chargeable** under the provisions of this Act" (*GE India Technology Centre
  (P) Ltd v. CIT* (2010) 327 ITR 456), so an ordinary import from a supplier with
  no permanent establishment is business profits, not chargeable here, and the
  right withholding is **nil** — not 20%. `domain/tds/section_195.py` asks the
  questions in that order and refuses rather than guessing; §206AA's 20% no-PAN
  floor has a non-resident carve-out (§206AA(7) with Rule 37BC) residents do not
  get. Under-deducting disallows the WHOLE expenditure under §40(a)(i).
- **§115BAC(6) WAS MODELLED AND NOTHING COULD ASK IT.**
  `domain/income_tax/regime_election.py` has held both clauses with Rule 21AGA
  since it was written and had **no production caller** — the only mention of
  it outside its own file and tests was a COMMENT in
  `domain/payroll/declarations.py`. Its own docstring says why that mattered:
  *"A missed Form 10-IEA taxes a client on the new regime for a year they
  planned around the old one, and it cannot be cured after the due date. A
  withdrawal made without realising it is final closes an option worth lakhs
  over a career. Neither failure is visible in the return — it computes
  cleanly either way."* `GET /api/income-tax/regime-election` serves it and the
  computation screen renders it **beside the regime picker**, because which
  regime is CHEAPER is not the same question as what choosing it REQUIRES.
  **A GET, deliberately** — it reads and writes nothing, and a POST would need
  an entry on `test_write_requires_write_permission.py`'s compute-only
  allowlist that every preview has to earn. The wire format for an earlier
  year is `FY:action` (`2024-25:withdrew`), parsed in the ROUTER because the
  format is the endpoint's business and the rule is not.
  **PRIOR HISTORY IS AN INPUT AND SILENCE IS ITS OWN ANSWER.** The product
  holds no filing history, so clause (i)'s once-only withdrawal cannot be
  derived; supplying nothing is answered as `history_unknown`, which is a
  DIFFERENT answer from "the option is available". Assuming availability is
  the dangerous direction — it tells a CA the old regime is open when their
  client spent it years ago.
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
- **A §192 PROJECTION IS THE RUN'S OWN FIGURE.**
  `GET /api/payroll/tds-projection` answers off `_compute_slip` — the same
  function the payroll run pays from — so what the screen projects for November
  is what November's run deducts. It replaced `lib/services/payrollTdsEstimate.ts`,
  a slab ladder with its own §87A rebate and §2(29C) brackets, hard-coded to FY
  2025-26 and deliberately not FY-versioned: from 1 April it was last year's tax,
  stated confidently, with no old regime, no declaration and annual-over-twelve
  where §192(3) governs. A projected month assumes a FULL month's attendance and
  no undecided bonus, and says so — LOP is a fact about a month that has
  happened, and §192(1) estimates on salary, which a payment nobody has decided
  is not.
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

That trap was live until 2026-09-08 and is now closed, but read what actually
happened, because the fallback was the SECOND problem. `CII_BY_FY` stopped at
2025-26 and held **380** for it — and 380 was itself wrong; six independent
sources say **376**. So `cii_for("2026-27")` returned last year's index AND
last year's index was a figure nobody had checked. Both are fixed: 2025-26 is
376, 2026-27 is 384, and `LATEST_CII_FY` deliberately stays at `"2025-26"`
because both figures are secondary-sourced and moving the anchor promotes a
guess to a verified figure. Post Budget 2024 indexation survives only as the
grandfathered option on immovable property, so the blast radius was small —
which is exactly why it sat there unnoticed.

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
| `domain/tds/section_195_rates.py` | §195 rates on payments to non-residents, by NATURE of income (§115A), plus the two Part II surcharge ladders and cess | Finance Act. **Every year is currently `verified=False`** — reconciled, not confirmed line by line |
| `domain/income_tax/capital_gains_engine.py` | `CII_BY_FY` + `LATEST_CII_FY` | one CBDT notification, usually around June |
| `domain/income_tax/tax_audit.py` | §44AB(a)/(b) thresholds and the proviso's ₹10 crore limb (`LATEST_VERIFIED_FY` is `None` — **no year has been confirmed**) | Finance Act |

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

**The PF wage BASE changed on 21-11-2025 and is now handled.** The Code on
Social Security subsumed the EPF Act and adopts that Code's own wage
definition — **Code on Social Security 2020 `s.2(88)`**, which is the operative
provision for provident fund; the Code on Wages `s.2(y)` is the same words in
the other Code, and citing it for a PF computation is imprecise. The listed
EXCLUSIONS are capped at **50% of total remuneration** and the excess is
**deemed wages**. `domain/payroll/wage_base.py` implements it, period-aware,
and migration 334 stores the working on the slip.

**The pre-commencement branch takes its own figure, and that is not cosmetic.**
`compute()` used to return the s.2(88) wage aggregate for an earlier month too,
and the router had — correctly, for s.2(88) — folded medical, special and other
allowance into it. EPF Act **s.6** named three things: "basic wages, dearness
allowance and retaining allowance". So an October 2025 month on ₹10,000 basic
with ₹2,000 medical and ₹3,000 special deducted ₹1,800 where s.6 gives ₹1,200 —
wrong on every historic month carrying an allowance, and it recomputes on
demand, so a reprinted payslip disagreed with the challan actually remitted.
`pre_code_wages_paise` is now passed explicitly and the docstring says what it
is rather than claiming a reproduction that was false. Of the
components modelled, only **HRA** (clause f) and **LTA** (clause d, "the value
of any travelling concession") are excluded; everything else stays on the wage
side, because that is the direction that cannot under-deduct and because a cash
medical allowance is not clause (b) and a special allowance is not clause (e)
(*RPFC v. Vivekananda Vidyamandir*, 2019). Rates and both ceilings are
unchanged — it was only the base they apply to that moved. **ESI is deliberately
NOT changed**: `_compute_esi` uses gross, the Code's definition is narrower, so
ESI may err the other way — unconfirmed, and pinned by a test so a later change
is deliberate. Gratuity likewise. Verified 2026-09-04; see
`docs/compliance/04-mca-epfo-esic.md`.

**ESI CONTRIBUTIONS ROUND UP TO THE NEXT WHOLE RUPEE — both shares.** ESIC's
filing manual, of the figure the portal computes: *"Employee Contribution will
be calculated and displayed. This is rounded to next higher rupee"*; the same
has applied to the employer's share since October 2004. `_compute_esi` floored
to the paise until 11-09-2026, which under-remitted on every wage that is not a
clean multiple — and the employer carries that shortfall with interest. Note it
runs the OPPOSITE way to the GST discount rounding, which floors: there,
flooring cannot under-declare tax; here, rounding up cannot under-deduct
contribution. Both take the direction that is safe for the person who would
otherwise carry the liability, which is why they differ.

**Partly a gap: professional tax and the Labour Welfare Fund.** PT slabs are
still bare literals in `routers/payroll.py`, covering **Maharashtra, Tamil Nadu,
Karnataka and West Bengal** — four of the twenty-two states
`domain/payroll/professional_tax.py` records as levying it. LWF has no amounts
at all.

⚠️ **That count of twenty-two is `[S]`-graded and probably one or two too high.**
The 7 September 2026 research pass found Odisha reported as having repealed its
levy from 01-04-2026 and Punjab's charge described as a Development Tax rather
than professional tax. Neither was confirmable — egress is blocked, see
`docs/audits/2026-09-07-market-research/` — and the list is deliberately NOT
changed on that evidence, because the error direction is benign: naming a state
that no longer levies produces a false GAP warning, never a wrong deduction.
Settle it against the state notifications before removing either.

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
| whether a supplier has a WRITTEN payment agreement, and for how long | `vendors.msmed_agreement_days` (migration 373), recorded on the Schedule III ageing screen | MSMED §15 requires payment "on or before the date agreed upon ... IN WRITING, or, where there is no agreement in this behalf, before the appointed day", and §2(b) makes the appointed day fifteen days from acceptance. So the limit is **FIFTEEN days by default and forty-five only under a written agreement** — forty-five is the number every article quotes and it is the exception. Whether such an agreement exists is a fact about a contract no ledger holds, and `credit_days` is NOT evidence of one: it is a commercial term, and reading it as the §15 period would give 30 days where the Act gives 15 on every vendor carrying the default. NULL means no written agreement, which is the statutory default rather than an absence. A recorded period above 45 is STORED as the contract says and capped by the engine, which says it capped |
| the DTAA rate for a payment to a non-resident | `public.dtaa_treaty_rates` (migration 310) — one row per (country, nature), firm-scoped; `vendors.treaty_rate_bps` is now only a per-vendor override. Refused on the purchase-bill path when a TRC is held and nothing is recorded | §194C, §194J and their neighbours charge, in their own words, sums paid "to a **resident**" — so for a non-resident payee they do not apply at all and §195 does, at rates in force under Part II of the First Schedule by NATURE of income, with surcharge and cess, displaced by the DTAA under §90(2) where a TRC and Form 10F are held. Nature of income × ninety-odd treaties × surcharge band cannot be written from memory, and §206AA's 20% floor has a non-resident carve-out (§206AA(7) with Rule 37BC) that residents do not get. Under-deducting disallows the WHOLE expenditure under §40(a)(i). The ACT side is now computed — `domain/tds/section_195_rates.py` holds §115A and Part II by nature of income, with surcharge and cess — but §90(2) gives the assessee whichever of the Act and the AGREEMENT is more beneficial, and the agreement cannot be: ninety-odd treaties, differing royalty/FTS/interest articles, MFN clauses needing their own §90(1) notification (*AO v. Nestle SA*, 2023), and several — the UAE and Singapore among them — with no FTS article at all. So a CA reads the agreement once per country and nature and records what they read (Settings → DTAA Treaty Rates); the engine then applies §90(2) to the two numbers it has, and REFUSES where a TRC is on file and nothing is recorded, because falling back to the Act rate would over-deduct exactly where somebody has established a treaty applies. **"No article" is an ANSWER, not a missing rate**: several agreements — the UAE and Singapore among them — have no FTS article, which makes the income Article 7 business profits and not taxable here without a PE, so it needs the same no-PE declaration chargeability does |
| the §47 GST late-fee rates | `domain/gst/late_filing.LATE_FEE_RATES`, empty; the refusal reaches the screen as a sentence naming the notification | the statutory figure is ₹100 a day per Act capped at ₹5,000, and nobody has paid it since 2018 — Notifications 4/2018 and 76/2018 reduced it and 19/2021 and 20/2021 capped it by turnover band, so the figure in force depends on the return, the year AND the taxpayer's own turnover. This environment's proxy refuses every `.gov.in`, and a late fee written from memory is a number a CA would pay over. §50 INTEREST is computed — its rates are in the Act |
| the §50(3) interest rate | `domain/gst/late_filing.SECTION_50_3_NOTIFIED_RATE_BPS`, `None`; the refusal names both notifications and the Act's ceiling | the sub-section charges "not exceeding twenty-four per cent as may be notified". Notification 13/2017-CT notified 24% against the ORIGINAL §50(3); the Finance Act 2022 substituted it retrospectively from 01-07-2017 and Notification 09/2022-CT appears to notify 18% for the substituted text. A THIRD of the charge separates them, egress is refused here, and this is a sum paid over on the client's behalf — over-stating takes money from a taxpayer who does not owe it. §50(1)'s 18% is held because 13/2017-CT notified it against text that has not moved |
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
- **Depreciation — but read this, it changed.** There IS a statutory table in
  code now: `routers/fixed_assets.py::_SCHEDULE_II_PART_C` holds Schedule II
  Part C's useful LIVES, and the WDV rate is derived from them as
  `R = 1 − (residual/cost)^(1/n)` with residual capped at 5% (Part C Note 5).
  It still does not belong in the April sweep — lives change only by MCA
  amendment, not by Finance Act — which is why it is listed here rather than
  above. What it replaced was a set of flat literals in which Furniture 10.00%
  and Intangibles 25.00% were **Income-tax Act block rates** sitting under a
  form field labelled "Companies Act 2013 Sch II rate", every one of them
  under-depreciating. An asset's own stored `wdv_rate_percent` still wins over
  the default whenever it has one.

  **Schedule II Part C and the rules over it live in
  `domain/fixed_assets/`** (`schedule_ii.py` for the table,
  `integrity.py` for the five register checks), not in the router. Three
  callers read them — the categories endpoint the Add Asset drawer pre-fills
  from, `GET /register-integrity`, and `reconciliation_service`'s nightly sweep
  — and a service importing a router to reach a statutory table is the wrong
  direction and one refactor from a cycle. `routers/fixed_assets.py`
  re-exports the old names so existing imports still work.
  `integrity.COLUMNS` is the projection BOTH fetchers use: a column added to
  one query and not the other makes that one quietly answer "clean" on a
  finding it could not see.

  **AND A REDUCING BALANCE HAS TO BE TOLD WHERE TO STOP.** A WDV charge
  approaches its floor and never reaches it, so with the column's default
  `salvage_value_paise = 0` an asset was depreciated for ever — and the derived
  rates above sharpened that, because a rate derived from the life lands the
  asset exactly on its residual at the end of the life, so the overshoot begins
  precisely when the asset is fully depreciated. `_wdv_residual_at_end_of_life`
  is the terminal, and it is derived from the ROW'S OWN rate and life by
  running the same yearly chain the charges run — not from a 5%-of-cost
  constant (which would be a different asset's arithmetic wherever the CA
  recorded their own rate) and not from the closed form `cost × (1 −
  rate/100)^life` (which is a paise below where the flooring actually lands, so
  the asset takes a ₹0.01 charge in the year after it finished). The floor is
  `max(stored salvage, that residual)` — a salvage the CA deliberately recorded
  above the residual still wins. A row with **no useful life** keeps exactly the
  behaviour it has, because there is nothing to derive from; `register-integrity`
  reports those as `wdv_asset_has_no_stopping_point` rather than writing a life
  in, since a life is a Part C judgement about that asset and guessing one moves
  the profit. Straight line already terminates and is untouched, trailing paisa
  included.

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
- **`core.authz`'s ASSIGNMENT scoping never runs there either, and the policy that
  replaces it stopped being applied in 2024.** Migration 084 gave every `client_id`
  table a RESTRICTIVE `<table>_assignment_scope` policy — a Partner short-circuits to
  TRUE, everyone else needs a `user_client_assignments` row — with a one-shot `DO`
  loop that HAS NEVER RUN AGAIN. Six tables created since are read straight from the
  browser and had firm-wide access only until migration 370: `bank_accounts` (093),
  `debit_notes` (145), `purchase_credit_notes` / `sales_debit_notes` (210),
  `gstr2b_reconciliations` (341), `tds_lower_deduction_certificates` (359). About 44
  more are still in that state and are deliberately NOT fixed — nothing reaches them
  from the browser — so the durable half is the rule, asserted:
  `tests/test_a_table_the_browser_reads_is_assignment_scoped_pg.py`. **Do not "fix" it
  by re-running 084's loop**: migration 262 replaced the payroll policies with
  per-command ones so the EMPLOYEE PORTAL can read a payslip, and a portal principal —
  a portal user, an employee — has no `users` row, so `can_access_client` denies them
  their own record.
- **Renaming or dropping a column can break the frontend while backend CI stays green.**
  `tests/test_frontend_columns_exist_pg.py` parses those select lists and checks them
  against the real schema. Run it when you touch a migration.
- **A THIRD path existed and it was not a database at all: `localStorage`.**
  Three screens kept the CA's own work in the browser (ACC-06). All three are
  on tables now, and the three turned out to be three different jobs — which
  is the lesson worth keeping, because the finding read as one.
  `/accounting/budget` went onto `account_budgets` (migration 376);
  `/accounting/recurring` onto `recurring_journal_templates` (377), the only
  genuine build of the three; and `/accounting/retainer` onto
  **`billing_schedules`, which was already built** —
  `arrangement IN ('retainer','one_time','package')` since migration 073,
  `billing_service.generate_for_schedule` producing a DRAFT through the sales
  engine, and three methods in `lib/api` with no callers. That inverts the
  argument `BrowserOnlyNotice` used to make in its own docstring — that these
  screens "have no alternative" — and makes it exactly the pattern this file
  warns about at `/gst/reconciliation`: a banner disowning a rival
  implementation. **Before writing such a notice onto a fourth screen, grep
  the backend for what it duplicates.**
  Two classes of defect found on the way are worth knowing, because neither
  was in the finding and both are the kind that hide behind "it's only stored
  locally". The retainer screen RENDERED a document headed TAX INVOICE under
  the firm's own GSTIN, numbered from a browser-local counter (two devices
  collide, so Rule 46(b)'s "unique for a financial year" cannot hold) and
  taxed at a hardcoded CGST 9% + SGST 9% — the wrong tax for every
  inter-state client — with a Print button. And the recurring screen's "Post
  Now" wrote `status: "posted"` STRAIGHT TO THE LEDGER, dated TODAY rather
  than the occurrence, so a rent journal due on the 1st and remembered on the
  7th landed on the 7th.
  **`BrowserOnlyNotice` is deleted**: with no screens left it would only invite
  a fourth, and `apps/web/scripts/a-browser-only-screen-says-so.test.ts`
  inverts to state the durable rule — no page under `app/` may store the
  user's WORK in the browser (a remembered tab or an unsent draft is a
  per-viewer convenience and is allowlisted with its reason), and none of the
  three may regress.
- **A RECURRING ANYTHING SHARES ONE CADENCE ENGINE**, `domain/recurrence.py`.
  `recurring_invoice_service` owned the occurrence arithmetic and it was
  right, so recurring journals could have copied it — and two cadence engines
  drifting means one feature posts in a month the other skips. It was MOVED;
  the invoice service imports and re-exports the names so its callers are
  untouched. The rule inside it that is easy to get wrong: **a month end clamps
  against the ORIGINAL day, not the previous occurrence.** A monthly template
  starting 31 January runs 31 Jan, 28 Feb, **31 Mar** — clamping each step
  against its predecessor walks the whole series permanently back to the 28th
  after one February.
  **A generated journal is a DRAFT and is stamped `source_type = 'manual'`**,
  which looks wrong and is not: `manual_journal_service._is_manual` is
  `(source_type or "") == "manual"` and migrations 275/338 refuse the edit and
  discard paths on anything else, so any other value hands the CA a draft they
  are invited to review and forbidden to amend. The trace lives on
  `journal_entries.recurring_template_id` (migration 377), which no guard
  reads. A failed occurrence is RECORDED in `recurring_journal_runs` and the
  template does NOT advance — a template that cannot post needs a CA, and
  advancing past a failure would skip the month silently.
  **There are THREE of these now** — sales invoices (107), journals (377) and
  PURCHASE BILLS (379, PUR-26) — and the third exists because the purchase side
  is where a missed month costs more than an expense: most of the §194 series
  charges on the YEAR'S AGGREGATE, so rent (§194I) or a retainer (§194J) that
  nobody entered changes what the NEXT bill should withhold, and with it the
  Rule 30(2) deposit and the quarterly statement.
  `services/recurring_purchase_bill_service.py` generates a **DRAFT** bill
  through the ordinary bill engine and never RECEIVES one — receiving is what
  posts Dr Expense / Dr GST Input / Cr Trade Payables, withholds the TDS and
  claims the credit. **`bill_no` is left blank on purpose**: it is the VENDOR'S
  own document number, a fact about the landlord's books, and half the key
  `domain/gst/itc_matching` uses — inventing one puts a number the supplier
  never issued onto a document the 2B reconciliation reads. `our_reference` is
  ours and is stamped. The per-line facts that decide money —
  `itc_eligible` (CGST §17(5)), `expense_account_id`, `tds_applicable` — travel
  on the TEMPLATE, because defaulting them at generation would re-decide every
  month what the CA decided once; and a line with no catalogue item is refused
  at SAVE time, since `PurchaseBillLineIn` has required one since migration 206
  and the alternative is failing inside an unattended 06:00 IST job.
- **The migrations and production have drifted before, in both halves of the
  schema.** `tests/test_schema_matches_production_pg.py` (columns) and
  `tests/test_guards_match_production_pg.py` (RLS switches, policies,
  constraints) compare a migration-built database against point-in-time
  production snapshots in `tests/fixtures/`, and assert only the directions
  that break something. `docs/schema-drift.md` explains both; the fixtures go
  stale by design and their README says how to refresh them.

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
- **THERE ARE THREE PRINCIPALS AND ONLY ONE OF THEM IS STAFF.** `rbac()` decides
  a staff request; `core/portal_auth.get_current_portal_client` is the CLIENT
  principal (a real Supabase JWT, no staff `users` row, no RBAC role); and
  `get_current_portal_employee` is the EMPLOYEE one (PAY-26). All three are
  authenticated — an employee has held a Supabase identity since migration 262,
  `payroll_employees.auth_user_id` with `portal_enabled`, which is exactly what
  that migration's RLS reads. What did not exist was any way for the API to
  RESOLVE one, so everything the product COMPUTES was unreachable to an employee
  however well it worked for the CA: the §192 projection answers off
  `_compute_slip`, the run's own engine, and it is precisely the working an
  employee asks their employer for in January.
  **THE EMPLOYEE PRINCIPAL IS DELIBERATELY NARROWER THAN THE CLIENT ONE** (owner
  decision, 14-09-2026): **read-only**, **self-scoped** and with **no client
  switcher**. The self-scoping is what makes it safe and it is STRUCTURAL rather
  than checked — no endpoint in `routers/portal_employee.py` takes an
  `employee_id` or a `client_id`, so there is no parameter to tamper with, and a
  test asserts that on the SIGNATURE so an id added later fails rather than
  becoming a way in. `portal_enabled` is asked SEPARATELY from `auth_user_id`
  because they are two different facts — `revoke_employee_portal` clears the
  second and may leave the first, so a check on the binding alone keeps a
  revoked employee signed in — and the refusal is one generic 403 for every
  cause, the oracle `employee_portal_service` raises one generic 404 to avoid.
  **`"PortalEmployee"` IS NOT AN RBAC ROLE**: `PERMISSIONS` has no entry for it,
  so `rbac()` denies it everywhere, which is correct and is why no endpoint may
  carry both. **The computation is the payroll module's** —
  `routers/payroll.compute_tds_projection`, called by both doors, which answer
  differently only about WHO may ask (200 with `success: false` for staff, 403
  for an employee whose own principal no longer matches a live row). A second
  withholding engine for the employee's side of the screen is exactly what
  PAY-10 deleted. **There is deliberately no `/me`**: the portal already reads
  its own `payroll_employees` row over PostgREST, and the reachability ratchet
  named the duplicate on the first run.
- **ACCESS IS BY ROLE, AND THERE IS NO PER-MEMBER OVERRIDE.** `rbac()` decides
  every request from the role alone. The Team screen used to render a "Module
  Access Matrix" of per-member toggles headed *"Changes are saved instantly.
  Overrides the role default for that individual"* — and every clause was
  false: the toggles wrote into `localStorage`, reaching no other user, device
  or server, and nothing in `core/permissions.py` could have honoured them
  anyway. A Partner who unticked Payroll for an Executive believed they had
  removed access and had not. The grid is READ-ONLY now, and a browser
  carrying old overrides has them purged, because "custom" asserted a
  restriction that never existed.
- **A screen showing what a role can reach ASKS.** `GET /api/identity/permissions`
  answers for the caller (what to render); `GET /api/identity/role-matrix`
  answers for all five roles (what the Team screen shows a Partner). Both are
  `get_accessible_resources` and neither is a security boundary. The Team
  screen's own `ROLE_DEFAULTS` copy had drifted in the expensive direction —
  it showed an Executive reaching Clients and Tasks only, when PERMISSIONS
  gives them accounting, gst, income_tax, mca, report and tds besides, and it
  gave a Manager Billing they do not have while withholding the Reports and
  Settings they do.

## Schedule III captions — one vocabulary, and the screen is served it

`apps/api/domain/reporting/schedule_iii.py` owns the caption list and is the
only place allowed to. `GET /api/accounting/schedule-iii/captions` serves it to
the mapping screen, which until 11-09-2026 carried its own hardcoded copy.

That copy had drifted in **both** directions at once, and it was measurable: it
offered five captions the classifier had never heard of, and spelled five others
differently — so **nine of the fifty mapped accounts in production were being
silently discarded**, the CA's decision saved and then ignored while the
statement went back to guessing from the subtype.

- **Canonical spelling is the screen's** — hyphenated `Short-term`, plural
  `Employee Benefits Expense` — an owner decision of 11-09-2026 taken on
  convergence (screen, stored data and classifier agreed) rather than on a
  reading of Schedule III, which could not be reached: `icai.org` and every
  `.gov.in` are refused at this environment's egress proxy.
- **`CAPTION_ALIASES` honours the older spellings** so nothing already stored is
  lost, and `canonical_caption()` is the only resolver — `bs_bucket`,
  `pl_bucket` and `classify` all go through it. **`Fixed Assets` is NOT an
  alias**: Schedule III makes it a heading over Tangible and Intangible, so it
  resolves from the account's own subtype rather than being guessed flat.
- **A subtype's hyphens are folded** before the keyword scan, so a human typing
  `Long-term Borrowings` as a subtype matches the `long term` keywords.
- **`apps/web/lib/accounting/scheduleIiiCaptions.ts` is a FALLBACK, not a third
  classifier**, and both halves of that are enforced. Every screen prefers the
  backend's `schedule_iii_caption` and reaches the browser copy only through a
  `??`, for the window where the frontend has redeployed ahead of the backend.
  The client Balance Sheet did NOT, until 11-09-2026: `fromSection` dropped the
  caption the API had always sent and `bsBucket()` guessed one from the
  subtype — and `bsBucket` cannot see `schedule_iii_mapping`, so **13 of the 26
  mapped balance-sheet accounts in production were shown under a different
  caption than the year-end statements gave them**, including a Long-term
  Investment presented as Other Current Assets.
  `apps/api/tests/test_the_browser_fallback_speaks_the_engines_vocabulary.py`
  holds the line from the side that owns the vocabulary — a guard written in
  `apps/web` would assert the engine against a copy of itself and pass whenever
  both drifted together, which is what the mapping screen's hardcoded list did
  for months.
- **`Tax Expense` is absent from `PL_EXP_ORDER` on purpose.** Schedule III
  Part II presents tax below profit before tax and the client P&L tab has no
  below-the-line row, so listing it among the operating expenses would fold it
  into total expenses. The extra-bucket fallback renders it separately. Pinned
  by a test, because it reads exactly like an omission.

- **The year end speaks the same taxonomy in a second spelling, and the
  translation is one table.** The statements are keyed on snake_case LINE CODES
  (`trade_receivables`, `cash_and_bank`) rather than captions;
  `domain/reporting/year_end_lines.py` holds the codes, the
  caption→code table, and `schedule_line_for_account` — the one function that
  says which line an account belongs on, deriving it from the account's type,
  subtype and the CA's own `schedule_iii_mapping` through `classify`. It lived
  in a ROUTER until 11-09-2026 while the two modules that needed it most read a
  CACHE of its answer, `account_group_mappings`, instead.
- **A row in `account_group_mappings` is an OVERRIDE, not the source**, and the
  correction is worth the space because of what the old shape did. That table
  is written only by `POST/PUT` on `routers/year_end_mappings.py` and, until
  11-09-2026, by its own `GET /mappings/defaults`. No screen has ever called
  any of them, so it holds **zero rows in production** — against 133 accounts,
  50 carrying a `schedule_iii_mapping` the CA recorded by hand. And
  `generate_financial_statements` sent every account it could not find there to
  `other_current_assets`, a debit-normal balance-sheet line. With no rows that
  is EVERY account, so the asset side came to Σ(debit − credit) over the whole
  ledger — **nil** — and so did equity and liabilities, and revenue, and every
  expense. The function's own `total_assets == total_equity_and_liabilities`
  guard passed on `0 == 0`: **a Balance Sheet of zeros certifying that it
  balanced.** Both readers now derive and treat a stored row as an override.
- **The auto-initialisation was removed rather than fixed.** That `GET` used to
  classify the firm's whole chart of accounts and INSERT the answers — a write
  behind a `read` action, and worse, it FROZE a derived answer. These rows are
  never re-derived and outrank the derivation, so the first CA to open the
  screen would have permanently detached the year-end statements from their own
  `/accounting/schedule-iii` decisions — for the accounts existing at that
  moment and no others, so half the chart would obey the CA and half would not.
- **There is deliberately NO second mapping screen.** `/accounting/schedule-iii`
  is already where a CA records this decision. A year-end mapping screen in the
  line-code vocabulary would be a second place to say the same thing, which is
  the mistake this file keeps having to record.

- **The fixed-assets note is a MOVEMENT, and there is one of it.**
  `domain/reporting/fixed_asset_movement.py` computes opening gross block,
  additions, deductions, closing, the same four for accumulated depreciation,
  and net block at both ends — per asset class, from already-fetched rows, with
  no database handle. Three callers read it and none re-derives it: the
  year-end note (`routers/year_end_notes.py`), `GET
  /api/fixed-assets/movement`, and both year-end PDFs. Its rules are worth
  knowing before touching any of them. **Every asset, disposed included** — an
  asset sold during the year is a DEDUCTION, and filtering it out is what made
  last year's closing fail to tie to this year's opening; only a soft-deleted
  row is excluded, because migration 351 makes that a row created by mistake.
  **The CHARGE comes off the ledger** (`account_period_balances`, twelve
  pre-aggregated rows) and the per-class split from the register's own
  `accumulated_depreciation_paise − depreciation_fy_start_accum_paise`, which
  speaks only for the asset's CURRENT depreciation FY — so an earlier year
  reports `split_known = False` rather than a split that silently omits an
  asset, and **where the two disagree the difference is STATED**
  (`movement_gaps`), never absorbed. **With no financial year it reports the
  register AS IT STANDS**, closing figures only, and says so: a movement with
  no period is not a conservative answer, it is a wrong one. The caveats are
  rendered wherever the figures are — the Reports tab, the notes screen and
  both PDFs — because a movement shown without the sentence saying the ledger
  and the register disagree is exactly the disclosure a reader would rely on.

## Opening balances — the ledger takes a total, ageing needs documents

**AN OPENING BALANCE IS MADE OF DOCUMENTS, AND UNTIL MIGRATION 391 IT WAS THREE
TOTALS** (ACC-14). `opening_balance_service._plan_opening` computes exactly
three targets — aggregate Trade Receivables (Σ `customers.opening_balance_paise`),
aggregate Trade Payables and each bank — which is the right shape for the
GENERAL LEDGER and useless for ageing. Every AR/AP ageing screen and the
Schedule III ageing note (MCA G.S.R. 207(E) of 24-03-2021) bucket by the DUE
DATE of each open document, and a control-account total has no dates, so on day
one the whole opening receivable ages to nothing. Tally takes opening balances
bill by bill with dates for exactly this reason.

- **An opening document is an ORDINARY row in `client_sales_invoices` /
  `purchase_bills`** carrying the OLD system's own number and date, with
  `is_opening` true. That is what makes a receipt allocate against it
  (`receipt_allocations` is an FK to that very table), a statement list it, the
  collections queue chase it and the bank match queue offer it — all unchanged.
  A separate table would have needed every one of those taught about it.
- **IT POSTS NO JOURNAL.** `customers.opening_balance_paise` stays the single
  source of the ledger's AR leg and `opening_balance_service` is untouched. The
  document is the BILL-WISE BREAKUP of that balance, not a second posting of it.
  So the two must AGREE, and where they do not the difference is NAMED rather
  than absorbed — `domain/accounting/opening_documents.reconcile`, rendered on
  the Opening Balances tab. An ageing schedule that does not foot to its own
  control account is worse than either figure alone.
- **IT DECLARES NO TAX AND WITHHOLDS NOTHING.** The GST was charged and declared
  where the document was issued; any TDS was deducted, deposited and reported on
  a statement filed from there. Every tax field is zero and `total_paise` is
  simply what is owed. That zero is also what keeps it out of the 26Q build,
  whose own reads are `.gt("tds_paise", 0)` and `.eq("tds_section", "195")`.
- **`purchase_bills.outstanding_paise` IS GENERATED FROM `net_payable_paise`,
  NOT `total_paise`** (migration 278) — the one asymmetry between the two
  tables, and writing only the total would leave every opening bill outstanding
  at ZERO, invisible to AP ageing and to the Schedule III payables note. A
  real-Postgres test proves it both ways round.
- **`is_opening` SAYS ONE THING, and every reader that feeds a statutory output
  asks it**: `domain/accounting/opening_documents.without_carried_over`. The
  GSTR-1/3B build (declaring a carried-over supply again pays the tax twice, and
  claiming its credit again doubles Table 4(A)), the GSTR-2B reconciliation (no
  2B counterpart, ever — it would report as "missing in 2B" every month and send
  the CA to chase a supplier about a bill from before the engagement), the Rule
  37 report (the 180 days never started here), §43B(h) (the deduction was
  claimed in a year whose return was prepared elsewhere), the tax-invoice PDF,
  Rule 46(b)'s series, and all four §34 note routes. The list is the RULE, in
  `tests/test_an_opening_balance_is_made_of_documents.py::EXCLUDES`, with the
  readers that SHOULD see one recorded beside it so an absent filter is a
  decision.
- **THE FILTER READS THE KEY OFF THE ROW, so a narrow `select()` that omits
  `is_opening` makes it a silent no-op.** A guard walks each module's AST and
  fails a literal projection on either table that is neither `*` nor names the
  column. And `carried_over` reads an ABSENT key as an ORDINARY document — the
  direction that cannot silently drop a real supply from a return.
- **§43B(h)'s other direction is NAMED, not computed**: an earlier year's
  disallowance actually PAID during this year comes back as a deduction, and
  nothing on a carried-over bill records whether it was disallowed. The answer
  lists them rather than showing a nil that reads as "none".
- **A §194 FY AGGREGATE CANNOT BE CARRIED OVER AT ALL**, and the module says so
  rather than approximating. The aggregate is measured on what was CREDITED
  during the year, while an opening balance records what is still OWED — a bill
  credited in April and settled before the migration counts toward the limit and
  is not carried over. `resolve_tds` already takes `fy_prior_taxable_paise` and
  `fy_prior_tds_paise` from its caller for exactly this reason.
- **THE OTHER DOUBLE COUNT: two mechanisms open one position and neither
  corrects the other.** `opening_balance_service` posts the masters under
  `source_type='Opening'`; `trial_balance_import_service` posts an imported
  trial balance under `'TrialBalance'`, deliberately separate (its header
  explains why, and that separation is right). Nothing COMPARED them, so a CA
  who enters the bank opening balance on the bank master AND imports a trial
  balance carrying a Bank row opens the account twice and the balance sheet is
  out by exactly it, silently. `double_openings` reports every account with a
  NON-ZERO position in both — non-zero on both sides, because a delta engine
  legitimately leaves a net-zero pair behind on an account whose master balance
  went to zero. **No difference is offered**: which of the two is the mistake is
  the CA's answer, and a single netted figure would read as one to post.
- **The old system's document NUMBER is not checked against Rule 46(b)** — it is
  a fact about a document somebody else issued, the same way
  `purchase_bills.bill_no` is the vendor's own, and refusing a series this
  product never generated would make a migration impossible for the clients who
  most need one. Per-client uniqueness still applies (migration 151), because a
  carried-over number that collides with one this client will issue is a real
  conflict the CA has to resolve.

## Reporting scope — "all clients" means the caller's clients

A reporting endpoint called with no `client_id` means "all clients", and that is
right only for a Partner: `_FIRMWIDE_ROLES` is `{Role.PARTNER}` (`core/authz.py`),
so an Executive or a Manager is assignment-scoped. `routers/accounting.py`'s
`_reporting_service(current_user)` builds the ledger source with
`effective_client_ids`, and the scope lives **on the source** rather than on each
report — a source is created per request from the caller's own scope, so a fetch
added later inherits the rule instead of having to remember it. `None` means no
restriction; an EMPTY set means nothing, never "no filter". Before ACC-17 the seven
reporting endpoints aggregated across the whole firm, and the Schedule III screen
offers "All Clients" as an ordinary control, so it did not need a hand-made request.

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

**A read that IS a row set has its own rule, and it is one line: page it.**
PostgREST caps a response at ~1000 rows (`db-max-rows`) and reports nothing
when it does, so a truncated read is indistinguishable from a complete one and
every figure computed from it is confidently wrong. `core/db_paging.fetch_all`
is the one helper — keyset, never OFFSET, stopping on a short page — and it is
the one to import; eleven modules still carry a private `_paginate_all` copy,
and adding a twelfth is the thing not to do. Two guards state the rule rather
than a spelling of it: `tests/test_paginated_selects_carry_their_key.py` fails a
paged query whose `.select()` omits the cursor column (which works perfectly
until the thousandth row and then cannot advance), and it scans `fetch_all`
alongside the private copies — it did not, so for a while a call site MOVED OUT
of the rule by moving to the shared helper. Two traps at the call site:
`fetch_all` imposes its own `ORDER BY id`, so an ordering the endpoint wants is
applied to the rows it got BACK, never inside the paged query; and sort keys are
coalesced, because a nullable column such as `fixed_assets.asset_code` raises
`TypeError` in Python where the database sorted it happily.

**THE RULE IS ABOUT THE BROWSER TOO, and that is where it was still being
broken.** Everything above is written for `apps/api`, and the frontend reaches
~83 tables directly over PostgREST — where the same ~1000-row cap applies, with
the same silence. `/accounting/budget` read `journal_lines` joined to
`journal_entries`, FIRM-WIDE, once per quarter, unpaged, and computed the
actuals in the browser: on any client with real volume every figure was short
by an unknown amount and every variance wrong, confidently, with no error
(ACC-06). The answer is one row per Revenue and Expense account — about fifty —
so it is now `GET /api/accounting/budgets`, reading `account_period_balances`
through **`ReportingService.period_net_by_account`**, which is the primitive to
reach for whenever one screen needs SEVERAL windows over the same accounts: it
fetches the chart and the buckets ONCE and projects each window through the
same `_passbook_lines` the Trial Balance uses. Four `trial_balance` calls would
have been eight Singapore-to-Mumbai round trips for one screen.
`core.ist_clock.fy_quarters` keeps the windows month-aligned (derived from
`fy_bounds`, never restating April), which is what lets the pre-aggregated
buckets answer exactly with no edge month to replay.

**Closing stock as at a date is the same shape, and it also carries a rule about
WHICH COLUMN answers a dated question.** `public.stock_position_as_at`
(migration 363) sums `inventory_stock_ledger`'s DELTAS to a date — one row per
item — with `domain/reporting/stock_position.py` as its mock-mode twin and
`tests/test_stock_position_parity_pg.py` pinning them. It never reads the
stored running totals, and that is not a style choice: those are chained in
INSERTION order (`_last_ledger_row` explains why, and it is right), so the
running total on a row is the position as at when it was RECORDED, not as at its
`movement_date`. Σ `value_delta_paise` to a date is also what ties to the
Inventory control account, because the inventory journal posts exactly that
delta at exactly that date. For the same reason a ledger's **Balance column is a
property of the order it is shown in** and is derived at display time from an
opening figure, never rendered from the stored chain.

**AND WHAT THAT RECEIPT COSTS INCLUDES THE TAX NOBODY CAN RECLAIM.** AS-2 (and
Ind AS 2) paragraph 6 puts "duties and taxes (OTHER THAN THOSE SUBSEQUENTLY
RECOVERABLE by the enterprise from the taxing authorities)" in the cost of
purchase — so creditable GST is excluded and always was, and credit barred by
CGST §17(5) is recoverable from nobody and belongs in cost.
`domain/inventory_service._blocked_tax_on_line` is the rule and
`apply_purchase_to_inventory` costs the receipt at the line's taxable value
PLUS it. It used to cost the receipt at the taxable value ALONE while PUR-04's
`blocked_total` block had already debited that tax to the LINE'S OWN expense
account, so the receipt journal moved only the taxable value out and the tax
stayed behind for ever: ₹1,000 of goods with ₹180 blocked leaves Inventory
₹1,000 and Expense ₹180. Closing stock understated, the period's expense
overstated, and — because the moving average is computed off the same figure —
every later COGS wrong too. **It needs no new account and no migration**: the
expense account already holds the tax, and the receipt journal resolves its
credit with the SAME fallback order the bill journal used (explicit
`expense_account_id` → `%Purchase%` → `%Expense%`), so it relieves exactly the
account that received the debit. `value_delta_paise` and the journal's
Inventory debit are one number by construction, so the tie above survives —
both move together, which is why a test asserts the expense account nets to
ZERO across the two journals. A NULL `itc_eligible` reads as ELIGIBLE, matching
migration 240's `NOT NULL DEFAULT true`; a blocked SERVICE line capitalises
nothing because it never reaches the stock ledger at all; and a purchase RETURN
relieves on the client's own cost formula (the moving average unless FIFO is
recorded — see INV-02 below), which now carries the tax. **Freight inward,
insurance and customs duty are in cost too since migration 396** — the other
two-thirds of INV-05, see the next bullet.

**WHAT ELSE THE GOODS COST TO GET HERE IS RECORDED AGAINST THE BILL, AND THE
BASIS IS A POLICY THE STANDARD DOES NOT GIVE** (INV-05, migration 396). AS-2
paragraph 6 puts "freight inwards and other expenditure directly attributable
to the acquisition" in the cost of purchase alongside the non-recoverable
duties above; the receipt costed a line at its taxable value plus its blocked
tax and nothing else, so a client who paid to bring a consignment in carried
stock at less than it cost, expensed the freight in the month it was billed
rather than when the goods sold, and — the cost formula running off the same
figure — got every later COGS wrong with it.
`domain/inventory/landed_cost.py` is the rule and
`services/landed_cost_service.py` fetches, previews and carries over.
**AS-2 SETTLES WHAT GOES IN AND NOT HOW TO SPLIT IT**, so the basis is an
accounting policy rather than a derivation — by value is wrong for a container
of identical t-shirts, by quantity is wrong for 200 chairs and 20 tables, and
₹50,000 of freight over exactly that consignment is ₹14,285.71 / ₹35,714.29 by
value against ₹45,454.55 / ₹4,545.45 by quantity. **BOTH are built, value is
the default**, the policy is `clients.landed_cost_basis` and one consignment
may override it with `purchase_bills.landed_cost_basis` — the shape every
product in this tier ships (TallyPrime appropriate-by-quantity / by-value per
expense ledger, Zoho Books quantity/value on save, QuickBooks Enterprise
quantity/amount/percentage; Xero has no allocation at all). Owner decision of
14-09-2026. **Weight and volume are NAMED and not offered**: the most accurate
basis for freight specifically, and `service_catalogue` holds no weight, so it
needs a column and a figure typed per item first. Both columns are nullable
with **no default and no backfill**, so a client with nothing recorded is told
the default is a policy they have not stated.
**`applied_at` IS THE BOUNDARY AND IT IS STAMPED AFTER THE JOURNAL.** A charge
recorded after the receipt is KEPT and REPORTED rather than silently left out
or quietly folded in — migration 251 makes the posted journal immutable, so
whether to reverse is the CA's decision, and the row carries the sentence
saying so. Stamping before the journal would leave a charge marked done on a
receipt that failed, which is the one outcome the feature exists to stop.
**EACH CHARGE KEEPS ITS OWN ACCOUNT**: the receipt credits the goods line's
expense account for the line's own cost and each charge's account for its
share, split with `split_pro_rata`, which returns the weights EXACTLY when the
amount equals their total — so the ordinary case needs no branch and the
journal balances with no plug. The split is largest remainder for the same
reason `domain/gst/discount.py` is. **A SERVICE LINE TAKES NO SHARE** (it never
reaches the stock ledger, so the share would simply vanish out of the cost),
and a charge with nothing to attach to stays UNAPPLIED and keeps being
reported rather than being marked done. **The Bill of Entry's non-creditable
duty carries itself over** — basic customs duty and the social welfare
surcharge, which migration 389 could name as cost and not act on for want of a
basis — from BOTH doors, create and PATCH, because a carry-over on create
alone is one correction away from a stale figure; restating is safe by
construction since the update is `.is_("applied_at", "null")`.

**THE COST FORMULA IS A CLIENT POLICY, AND ONLY ONE FUNCTION FORKS ON IT**
(INV-02, migration 394). AS-2 paragraph 14 permits FIFO **or** weighted
average, and the product had only the second — so a client whose books are
kept on FIFO had a closing stock figure, and therefore a profit, that its own
accounting policy note did not describe. `domain/inventory/costing.py` is the
authority. **A RECEIPT COSTS THE SAME UNDER BOTH**: the formulas assign cost to
what goes OUT, and the running value rises by the receipt's own invoice cost
either way — so the fork is entirely inside `record_stock_out`, the
oversold-absorb split is common to both, and `domain/reporting/stock_position`
needs no change at all (a test asserts it never mentions the formula).
**Paragraph 16 makes it a property of the ENTERPRISE'S inventories**, so it
lives on `clients.inventory_costing_method` and no caller may choose one:
`CostingPolicy` carries the client it belongs to and a movement REFUSES a
policy that is not its own, which keeps passing it down a cached read rather
than a choice — the posting paths resolve it once per document, because
`clients` is a Singapore-to-Mumbai round trip and an invoice has as many lines
as it has lines.
**NULL IS NOT A DEFAULT DRESSED UP AS ONE.** The client column is nullable
with no default and no backfill, and reads as the weighted average — which is
a FACT, not a guess: every book in this product was kept that way because it
was the only formula there was. The LEDGER column
(`inventory_stock_ledger.costing_method`) IS defaulted and backfilled, for the
opposite reason — the value is known for every existing row — and it is what
makes AS-5 paragraph 32's disclosure derivable from the ledger instead of
remembered. A CHANGE IS PROSPECTIVE: nothing is ever re-costed, so
`switch_refusal` requires a date and refuses one stock has already moved on or
after, because re-costing would move a closing stock figure already in a filed
return.
**A LAYER CARRIES ITS VALUE, NOT A UNIT COST**, and that is the same decision
`_compute_stock_in` makes blending the average from the exact total: three
units costing ₹100 have a unit cost of 3,333 paise and a value of 10,000, and
`3 × 3,333` is 9,999. A layer takes the ledger's own `value_delta_paise`, a
whole layer is consumed at its whole value and a part layer is split by
quantity with the remainder keeping exactly what is left — so the layers tie
to the books to the paise, and the one paise that would otherwise appear on
every awkward receipt cannot be mistaken for the real difference a
cancellation reversal leaves. **The layers are DERIVED from the ledger, never
stored** (migration 278's reasoning), replayed forward from the last row whose
running quantity was at or below zero — the force-close pairs that with a
value of exactly zero, so nothing before it can matter — **carrying that row's
own oversold deficit**, without which a receipt clearing an oversell becomes a
layer of its whole quantity. **`record_stock_out_at_value` is deliberately NOT
forked**: a cancellation reversal removes the value the original movement
added because the journal side reverses that entry at its original value, which
is not a FIFO concept at all, so `rebase` puts the layers back on the books
afterwards rather than pretending the two agree. Standard cost is REFUSED and
named (AS-2 paragraph 17 — two judgements no ledger holds, and it needs a
variance account and a revision cycle to mean anything).

**STOCK HAS A PLACE AND A LOT, AND ONE OF THEM CHANGES WHICH RETURN A MOVEMENT
IS IN** (INV-03a, migration 398). `inventory_stock_ledger` recorded WHAT moved,
WHEN and for how much, and never WHERE or WHICH LOT — so a client with two
warehouses had one undifferentiated pile and a client whose goods expire had no
way to say which ones. Owner decision of 14-09-2026 over the alternatives in the
same finding (item group, reorder level, alternate unit): all three together,
because all three touch the stock ledger.
**A GODOWN IS NOT DECORATION.** CGST §25(1) requires registration in every State
a taxable supply is made from and §25(2)'s proviso allows a second within one
state, so a godown carries its own `state_code` and the registration it operates
under. **Schedule I paragraph 2 with §25(4) then makes a transfer between two
godowns under DIFFERENT registrations a supply even without consideration** — a
tax invoice is owed — while a transfer under the SAME registration is not a
supply at all and travels on a Rule 55(1)(c) delivery challan.
`domain/inventory/location.py` states it and **REFUSES to mint the invoice**:
the value is §15 with Rule 28 (open market value, like goods, or 90% of the
recipient's onward price, at the supplier's option) and which the client elects
is recorded nowhere here. The decision is a **TRI-STATE** — the third is where a
registration is not recorded, because one guess mints a document the Act does
not ask for and the other omits one it does. **The comparison is on the
REGISTRATION, never the state**: two Maharashtra godowns under different GSTINs
ARE distinct persons.
**A BATCH IS A TRACEABILITY AND EXPIRY DEVICE AND NOT A COST FORMULA**, and that
is the line the feature must not cross. AS-2 paragraph 14 permits FIFO or
weighted average and migration 394 made the choice a client policy; paragraph
13's specific identification — costing an issue at its own batch's cost — is a
THIRD formula, and a batch column is exactly what invites it in silently. A test
asserts `record_stock_out` never mentions a batch. **First-expiry-first-out is a
PICKING order, suggested and never applied**, for the same reason.
**BOTH LEDGER COLUMNS ARE NULLABLE AND NOTHING IS BACK-FILLED.** Every movement
already recorded happened at a location and in a lot nobody wrote down; stamping
a default godown on them would assert they all happened THERE. NULL is a REAL
GROUP in the detail report, not a row to drop, and the total still ties to the
Inventory control account because it is the same deltas either way.
**`stock_position_detail_as_at` IS A SECOND GRAIN, NOT A SECOND ANSWER** — it
sums the SAME deltas grouped per (item, godown, batch), so its total is
`stock_position_as_at`'s total by construction, and a real-Postgres test asserts
exactly that alongside the ordinary SQL/Python parity. **Stock is good ON its
expiry date** (a shelf life runs to the end of the stated day; reading it the
other way writes off a day of sound stock and reverses §17(5)(h) credit that is
not yet due), and **a batch with no date is its own bucket, never "later"** —
stock that does not expire and stock whose date nobody recorded are opposite
situations. A **transfer posts NO journal**: within one entity the stock is
worth what it was worth before it was carried across the yard, and the two rows
carry equal and opposite value. **The value moved is the SOURCE godown's own**,
not the item's blended average, or the per-godown position drifts from the total
it must sum to.

**A PHYSICAL STOCK COUNT IS ONE SESSION, AND THE VARIANCE IS A FACT ABOUT THE
COUNT DATE** (INV-08, migration 387). Adjustment was one item per API call and
one modal per item, reachable only from inside an item's ledger drill-down — so
a 31 March stock-take with a hundred variances was a hundred retyped
quantities, a hundred §17(5)(h) decisions and a hundred journals with no common
reference tying them to the count. `domain/inventory/count_session.py` is the
RULE (which lines vary, by how much, in which direction, and which cannot post
yet); it reads nothing and posts nothing.
`services/stock_count_service.py` fetches its inputs and posts through
`domain/inventory_service.apply_stock_adjustment` once per varying line — the
SAME function the single-item path calls, so there is no second stock write
path — with the session's own `reference_no` on every one.
**THE SYSTEM QUANTITY IS ON BOTH SIDES OF TIME.**
`stock_count_lines.system_qty_units` is what the books said when the sheet was
OPENED, kept so the CA can see the books moved under them; the variance that
POSTS is recomputed at post time against the position AS AT THE COUNT DATE,
because a 30 March purchase bill entered on 2 April changes what the books say
for 31 March and posting the snapshot's variance would re-introduce the very
difference that bill corrected. Where the two disagree the sheet SAYS so, and
**no variance is stored** for the same reason — a stored one is wrong the
moment a backdated document lands. **`reverse_itc` is nullable with no default
and a SHORTAGE cannot post without it** (whether damaged stock's credit must be
reversed is a CA judgement, since it might still be sold at a discount), while
a SURPLUS needs no decision and is REFUSED if it claims one. Both refusals are
per LINE: a hundred-line sheet with two undecided posts the ninety-eight and
names the two, because refusing the batch sends the CA back to the
hundred-clicks path. **The batch is not atomic and cannot be** — each
adjustment is its own journal through the posting kernel — so a line that
failed is NAMED in the response and re-posting the session is refused rather
than doubling the lines that succeeded. **`post_session` asks BOTH period
questions**, which `routers/inventory.py:adjust_stock` does not: a shortage
registers its §17(5)(h) reversal on GSTR-3B Table 4(B)(1) (INV-06), so a count
sheet IS a document that feeds a return and `period_lock_service.assert_open`
applies — unconditionally, not gated on whether any line happens to carry a
reversal, the same reasoning a fixed asset's acquisition takes.

## GSTR-2B reconciliation — the books are read in `apps/api`, and the answer is kept

The one purchase-side task an Indian practice performs every month is "which of
my client's bills has the supplier not filed, and how much ITC must I hold
back". §16(2)(aa) makes it decisive rather than informational: credit is
available only where the supplier has furnished the invoice and it has been
communicated to the recipient, and **GSTR-2B is that communication**.

- **`domain/gst/gstr2b.py` parses the real envelope** — `data.docdata` with
  `b2b`, `b2ba`, `cdnr`, `cdnra`, `impg`, `impgsez`. Three things about the file
  are easy to get wrong and are written down there: the tax is on the **rate
  lines** (`inv.items[]`), never on `inv.val`, which is the whole invoice value
  INCLUDING tax; `itcavl`/`rsn` are part of the document and a match that drops
  them tells a CA the credit is safe when the portal has said it is not; and a
  **credit note reduces** credit, so `cdnr` type "C" is signed negative.
- **`domain/gst/itc_matching.py` is the matcher**, and it has FOUR answers.
  `missing_in_2b` (we hold a bill nobody filed — chase the SUPPLIER) and
  `missing_in_books` (they filed something we have no bill for — chase the
  DOCUMENT) are opposite problems, and one figure for both sends the CA to the
  wrong party. The document number is folded per SEGMENT (`INV/2025-26/0042` ==
  `INV-2025-26-42`) because a false "missing" is a phone call that costs the CA
  their credibility; the AMOUNT is never fuzzy, because a tolerance on the tax
  is a tolerance on the credit claimed.
- **`services/gst_2b_reconciliation_service.py` reads `purchase_bills` itself**
  and writes `gstr2a_records` (migration 340). The caller sends the portal file
  and nothing else: asking a screen to supply the purchase register it is
  reconciling is asking it to supply the answer, which is exactly what
  `raw["book_invoices"]` did. A re-upload REPLACES, and an unparseable file
  persists NOTHING — a zero written and called reconciled is the false clean
  result this replaced.
- **One screen, since 11-09-2026.** There were two. `/gst/reconciliation`
  matched two uploaded files in the browser, saved nothing, and forgot the
  answer on refresh; it carried a banner disowning itself, which is a warning
  label rather than a fix. **Deleted on the owner's decision.** The real one is
  the client GST tab's GSTR-2B Recon, and it is per-client by nature — the
  firm-level GST page cannot know whose books to reconcile, so its link was
  removed rather than repointed.
  `apps/web/scripts/the-2b-reconciliation-reads-the-books.test.ts` now asserts
  the file is absent and that nothing links to the route, so a second
  implementation cannot reappear quietly.
- **Not built:** invoice-wise Rule 36(4). The reconciliation now knows per
  document whether 2B allows the credit; `gstr3b_computer` still caps in
  aggregate.
- **RULE 43 IS BUILT AND RULE 42 IS NOT, and the missing input was never the
  arithmetic** (FA-19). A client making both taxable and exempt supplies
  reverses one-sixtieth of the credit on each COMMON capital good every month
  for five years, apportioned by exempt turnover — Tc, Tm, Tr, Te, per head
  because Rule 43(2) says so. `domain/gst/rule_43.py` is the authority,
  `services/gst_rule_43_service.py` fetches its two inputs, and
  `GET /api/gst-workspace/itc/rule-43` serves the working beside the return.
  **The one fact nobody held was which of Rule 43(1)'s three uses an asset is
  put to** — the tax split has been on `fixed_assets` since migration 343 —
  so migration 372 adds `rule_43_use`, nullable, no default, CHECKed to
  `common | exclusively_exempt | exclusively_taxable`. **A NULL is REFUSED and
  NAMED, never assumed**, because guessing is unsafe in both directions:
  assuming common reverses credit §16(1) gives, assuming exclusively taxable
  leaves Te undeclared with Rule 43(1)(h) interest running on it. Same shape as
  `vendors.msme_status`. **E and F come from
  `gst_return_service.outward_turnover`**, which builds the outward side
  through the same `_outward_transactions` `gstr3b_from_books` uses — extracted
  rather than copied, so a working and its return cannot disagree about what
  was supplied. E is nil-rated + exempt + non-GST (§2(47) reading in §2(78)) and
  **deliberately NOT zero-rated** (IGST §16(1) allows that credit and 43(1)(b)
  names such supplies as other than exempted); F is all four (§2(112)).
  ⚠️ **An OUTWARD supply the RECIPIENT pays tax on is missing from F**, because
  `compute_gstr3b` accumulates a taxable supply only `if not
  s.is_reverse_charge` — right for Table 3.1(a) and wrong for §2(112), which
  excludes only INWARD reverse-charge supplies. A GTA's or an advocate's own
  outward supplies are their turnover. A smaller F makes Te LARGER, which is
  the safe direction, and the answer SAYS so for the period rather than being
  silently generous. **Te
  rounds UP** — it is added to output tax and 43(1)(h) charges interest, so
  understating it is a shortfall that grows; the division happens ONCE on the
  aggregate, not per asset. **It POSTS NOTHING**: the CA raises the reversal
  journal and registers it with ground `rule_43`, which
  `itc_register_service` has accepted since migration 362 and nothing could
  produce a figure for. Three things are named as not modelled rather than
  approximated: the (a)→(c) and (b)→(c) transitions (the provisos' five
  percentage points per quarter need a HISTORY of the classification, which is
  a second table), the Explanation to 43(1)(g)'s excise exclusions, and Rule 42
  itself — the inputs-and-input-services twin, still absent.
- **The 26AS reconciliation is the same rule and had the same defect
  (TDS-21).** `POST /tds-workspace/form26as/upload` asked the caller for BOTH
  sides — `raw_data.tds_entries` AND `raw_data.book_deductions` — with the tab
  a textarea saying so, while the register sits in `tds_deductions`. It reads
  the register itself now; a `book_deductions` key still sent is ignored and
  named in `ignored_request_keys`. **`domain/tds/deductor_26as.py` is the
  matcher and is deliberately NOT
  `domain/income_tax/form26as_matcher.py`**: that one is the
  client-as-DEDUCTEE direction, keyed on the DEDUCTOR's TAN or name, and this
  is client-as-DEDUCTOR, keyed on the DEDUCTEE's PAN and section. Reusing it
  would put a deductee's PAN in a field named `deductor_tan` and emit outcome
  sentences about the wrong party. What both share is the discipline —
  exact-amount pass before any variance pass, every pass CONSUMES, and totals
  over the FULL population on each side — and that is stated in each. The old
  code was a `{(pan, section): entry}` dict comprehension: it kept one 26AS row
  per identity, matched it against any number of book rows, and had **no
  26AS-side leftover bucket at all**, so a portal row the register was missing
  was never reported. A deduction with no deductee PAN is its own named bucket
  rather than matched — 26AS is keyed on the PAN, and pairing two blank-PAN
  rows on section and amount is the guess §206AA exists because nobody should
  make.
- **NOT EVERY PART OF FORM 26AS IS A CREDIT, and the client-as-DEDUCTEE
  reconciliation used to sum all of them.** `_PART_RECORD_TYPE` in
  `domain/income_tax/form26as_service.py` names each part and
  `CREDIT_RECORD_TYPES` says which count: **A / A1 / A2** is TDS deducted FROM
  the client and **B** is TCS collected from them (§206C(4)) — both credits;
  **C** is advance and self-assessment tax the client PAID THEMSELVES, **D** is
  a refund already received, and **F** is §194-IA tax the client deducted as
  BUYER of property. Those three are real facts and not TDS credits, so
  including them made 26AS exceed the book register by exactly the advance tax,
  for every client who paid any, every year. `split_by_credit` keeps the first
  two in the comparison and reports the rest as `not_a_tds_credit` — set aside,
  never dropped, and rendered on the screen. Two traps. **A2 and F point
  OPPOSITE ways** — seller and buyer of the same §194-IA — so the audit
  finding's own fix of filtering "A2/F" together would drop a genuine credit,
  and they are deliberately kept apart; the parser cannot in fact tell A2 from
  A (`PART\s+([A-Z])` keeps one letter), which is safe only because all three
  are credits. And **the extras are merged into the RETURN, never into
  `summary`**, because `summary` is spread straight into the
  `form_26as_reconciliations` INSERT — a key that is not a column of that table
  fails on the live database and passes in mock mode, which is the exact shape
  migration 291 was written to repair on this same table.
- **What the 26AS parser could not read is NAMED, and an unreadable file is
  refused rather than saved as an empty year.** `read_26as_text` returns a
  `Reading26AS` carrying the records AND every skipped line with its 1-based
  number and the reason; there is deliberately no wrapper handing back only
  the records. The split is tab-or-pipe only, which is a real limit rather than
  an oversight — a 26AS pasted out of a PDF viewer is space-separated and
  splitting on runs of spaces would cut deductor names in half — so such a file
  reports every line as skipped, `looks_unrecognised` is true, and the router
  422s. An EMPTY 26AS is still correctly empty: `looks_unrecognised` is
  content-with-no-records, not no-records.

## Bank data — the Account Aggregator is the only way in

Statement upload (CSV/XLSX, parsed server-side in `domain/banking/normalizer.py`)
is how bank data enters the platform today, and it is not going away. When a live
bank feed is built, it goes through India's **Account Aggregator** framework and
nothing else.

**The DPDP duties over bank data are live NOW and do not wait for AA.** An
uploaded statement holds the client's account number and, in every narration, the
name or UPI handle of a COUNTERPARTY who is usually a stranger to the engagement
— the largest population of third-party data principals in the product. It is a
`bank_data` category in `domain/dpdp/retention.py` (Companies Act s. 128(5)
reaches it expressly, as the "vouchers relevant to any entry"), and the
bank-account delete names the statute and the date. See
`docs/compliance/06-data-protection-dpdp.md` §5e — which also records why the
AA consent artefact's `DataLife` clock would collide with the eight-year period,
and why that does not arise under upload.

- **Register as an FIU** (Financial Information User). Banks are FIPs; a licensed
  AA — Finvu, OneMoney, CAMS Finserv, NADL, Anumati — brokers consent between
  them under RBI regulation, on ReBIT schemas. Go via a TSP (Setu, Perfios,
  Finbox, Digio) rather than building FIU plumbing directly.
  **⚠️ THIS STEP IS NOT ACHIEVABLE AS WRITTEN — verified 2026-09-04, including
  searches that specifically looked for a way in and did not find one.** The RBI
  NBFC-AA Directions 2025 (which supersede the 2016 Master Direction) define an
  FIU as *"an entity registered with and regulated by any financial sector
  regulator"*, and that means RBI, SEBI, IRDAI, PFRDA or the Department of
  Revenue. **There is no FIU licence to apply for and no unregulated tier**;
  eligibility is derivative of a registration you already hold, and a TSP cannot
  confer it because a TSP is itself unregulated. The framework is built so raw
  financial data never reaches an unregulated party. The Department of Revenue's
  presence in that list does NOT help — it is there because DoR regulates GSTN
  *for the specific purpose* of GSTN being an **FIP**. A CA firm does not
  qualify either: ICAI is not a financial sector regulator. So the options are
  to **partner with a regulated FIU** (watch the shell-FIU pattern — FIPs have
  barred AAs over non-compliant downstream journeys), **acquire a registration**
  (SEBI RIA is most plausible; an NBFC brings a reciprocity duty to join as an
  FIP too), or **not consume via AA at all**. The six AA tasks are now sequenced
  around those three as **three gates, cheapest-and-most-fatal first**, and the
  ordering carries a finding of its own: **purpose-fit is UPSTREAM of FIU
  eligibility.** Eligibility is solvable with money; purpose is not. A consent
  artefact carries a `Purpose`, the FIP validates every fetch against it, and
  purpose limitation is enforced. **Gate 0a is ANSWERED, NO, and the taxonomy
  itself is now the authority for it (#130, §2b)** rather than an inference from
  absence. The five published purpose codes are **101** Wealth Management (SEBI
  RIAs, stock brokers), **102** Customer spending patterns/budget/other
  reportings (SEBI RIAs, PFRDA Retirement Advisors — *financial advisory*),
  **103** Aggregated Statement (lenders, insurers — underwriting and income
  verification), **104** monitoring of accounts (lenders — repayment health) and
  **105** one-time account verification (stock brokers). **Every entry names the
  class of licensee it is for**, which is the proof that a purpose is DERIVATIVE
  OF THE FIU'S OWN REGULATORY PERMISSION — and none describes an agent keeping
  the customer's own books. **So purpose defeats the PARTNER route too**, not
  just the do-it-yourself one: a partner FIU's permitted purposes come from its
  licence, and buying a SEBI RIA registration buys wealth-management advice, not
  ledger-keeping. ⚠️ **The near-miss is 102** — its NAME sounds like bookkeeping
  and its scope is advisory by SEBI/PFRDA registrants; Sahamati's own "use the
  most appropriate code, based on judgement" guidance points straight at it, and
  the FIP validates every fetch against the artefact's `Purpose`. **Do not
  declare 102** — not as a placeholder, not for a pilot. Grades are `[S]`, from
  search snippets of the publisher's pages: **every fetch is still refused** by
  the egress proxy on a third day, Wikipedia included, so nothing here is `[P]`.
  What is NOT settled is whether a purpose could be ADDED, and **the owner has
  decided not to ask** (2026-09-06, §7): the proposal channel runs through FIU
  membership §0 says we cannot hold, so the realistic asker is a partner FIU —
  the route purpose already forecloses. The enquiry stays drafted in §2a so
  reopening costs one email, but **nothing is outstanding and nobody is waiting
  on anybody.** **The whole line is CLOSED — §7**: route 3 has no counterparty, so
  #107's contract and pilot have no subject, and §7 carries the four gate
  questions and their answers in ONE table rather than eight cross-references.
  Verified before closing: no AA code, no config, no migration anywhere, and the
  one compliance marker (`domain/banking/normalizer.py`, the AA seam) rewritten
  so it states the decision instead of reading as pre-work. **Gate 0b (#103) is measured too, and points the
  same way**: the live book is 7 clients and 2 bank accounts — too small for an
  honest percentage, and one was not invented — but the composition needs no
  sample size. **Zero individual clients** (4 Private Limited, 1 LLP, 1
  Partnership, 1 Proprietorship), every account a **Current** account, and one of
  the two banks is **Cosmos Bank**, the co-operative this file already named as
  the AA gap. The one well-served AA case — savings, individual, singly held,
  ~72 banks — does not appear at all. **On that basis #104 has CHOSEN ROUTE 3 —
  do not consume via AA — provisionally, with no counsel engaged and nothing
  spent.** The asymmetry that makes that decidable now: routes 1 and 2 (partner,
  or acquire a registration) both require paid counsel and are the routes gate 0
  argues against, while route 3 requires none, costs nothing and forecloses
  nothing. **#105–#107 are not started and should not be** — they specify work
  under a route not taken. The one thing that reopens gate 1 is #130 finding a
  purpose exists or can be added; the counsel brief is already written in §0a so
  the money is spent once, on the right questions. **Stopping is a real
  outcome**, not a failure — statement upload is the base case regardless. See
  `docs/compliance/05-bank-data-and-the-account-aggregator.md`.
- **The consent is the CLIENT's, not the CA's.** The account holder consents, and
  it is time-bound, purpose-bound and revocable. So the flow is "CA requests →
  client approves → CA sees data", with a re-consent path when it lapses.
  **That shape is NOT new to the app** — `routers/engagement_sign_public.py`
  already does CA-sends-a-tokenised-link → client-acts-without-a-login, with a
  256-bit bearer token, every query constrained to the token's row, a client-safe
  projection, IST-dated expiry and an honest 503-vs-404 split. A consent request
  should follow it rather than invent a second one. **What IS different is one
  step**: the engagement letter is accepted ON OUR PAGE, and an AA consent is
  approved AT THE AA. Put an "I agree" in our UI and the consent is ours, from an
  unregulated party, and worthless. See `docs/compliance/05-…` §6 — the shape is
  specified there and deliberately not built.
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
- **`CREATE OR REPLACE FUNCTION` REPLACES THE WHOLE DEFINITION, so derive the new
  body from the migration that LAST defined that function — found by NUMBER, not
  from memory and not from the one you happen to be reading.** A replacement either
  carries every earlier change forward or silently reverts it, and the revert
  compiles, deploys and passes a mock suite. Migration 384 got this wrong twice
  before the real-Postgres suite caught it: the first attempt was hand-written and
  lost the balance guard, the `jsonb_populate_record` column list and the
  `deleted_at` filter; the second was derived faithfully from migration 243 — and
  243 was the WRONG ANCESTOR, because 271 had made `post_journal_atomic` SECURITY
  DEFINER and 274 had folded in the reversal stamp. Merging it would have
  reproduced exactly the production incident 274's own header records:
  `permission denied for table journal_entries`, 42501, the reversal committed and
  its original left unflagged. `grep -ln "FUNCTION.*<name>" migrations/*.sql | sort
  | tail -1` is the answer. The guard shape that survives is in
  `tests/test_a_voucher_shows_its_lines_in_order.py`: it reconstructs the ancestor
  by scanning the migration directory, so it cannot be pointed at a stale one, and
  a parametrised clause test names the privilege model and every invariant a
  careless rewrite drops.
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
- **The slow half of startup runs on a thread, and must stay there.** The
  schema-drift check, the scheduler start, its health log and the catch-up
  sweep are started by `main._lifespan` on a daemon thread — not at module
  import, where they used to be. Three of the four make a Singapore-to-Mumbai
  round trip, and doing that before uvicorn binds timed out Render's deploy
  health check on every deploy for weeks. `/health` answers 200 with
  `schema: "checking"` while the check is outstanding and flips to 503 on real
  drift; **answering 503 while merely unchecked reproduces the original bug**,
  because Render cannot tell "still checking" from "broken".
  `tests/test_health_answers_before_the_slow_boot.py` is the guard.
- The daily job sweep is in-process APScheduler (`jobs/scheduler.py`), gated on
  `ENABLE_SCHEDULER`, enabled in exactly one process. On Render's free tier the instance
  sleeps, so `.github/workflows/wake-before-scheduler.yml` pings `/health` across the
  window to keep it alive; the sweep also catches up on jobs whose trigger was slept
  through.

## Compliance, integrations and filing

`docs/compliance/` is the single place that says, for every statutory output:
what the product computes today, what the last mile actually is, and **what gates
closing it** — which is almost never code. Read it before estimating any filing
or integration work, and read `docs/compliance/00-how-to-read-this.md` first for
how much to trust the rest.

Places in the code where a registration, empanelment or licence gates the work
carry a scoped marker naming its section:

```
grep -rn 'TODO(compliance)' apps/api apps/web
```

That convention is deliberate and narrow — the codebase otherwise has **no**
`TODO`/`FIXME` markers at all and prefers prose comments beside the code.
`tests/test_compliance_markers_point_somewhere_real.py` fails a marker with no
doc path or one pointing at a file that does not exist.

## Where the design is written down

`docs/architecture/01-09` is the authoritative design set — accounting engine, posting
kernel, financial years, opening balances, manual journals, multi-currency, GST engine,
reporting engine, bank entries. Read the relevant one before changing a subsystem.

**Bank entries (09) in one paragraph, because it is easy to rebuild the old
thing by accident:** a statement line becomes a voucher — Receipt, Payment or
Contra, decided by direction and never chosen. The machine writes its best
proposal ONTO the row (`draft_*` columns, migration 322), graded `ready` or
`proposed` with a reason sentence, never a percentage. `entry_state` is a
trigger-maintained column (Python twin `domain/banking/entry.py`, pinned by a
parity test) — application code never writes it. The verb is **Pass**; "Pass N
ready" is chunked and resumable; a `proposed` draft is never passed in bulk. A
rule a Manager+ marks **trusted** passes its lines with no click, as
`created_by = trusted_by` — the one place the product acts unprompted, an owner
decision of 2026-09-03 that reversed the earlier "draft only" rule. The
posting path is still only `bank_posting_service.post`, and **which BANK
LEDGER either path posts to comes from one lookup**,
`BankPostingService.bank_account_id_for` — `bank_transactions` carries no
`bank_account_id` of its own, only `statement_id`, so the account is one hop
away through `bank_statements` and `match_and_settle_multi` was building its
receipt and payment payloads without it (ACC-03). `domain/accounting/
payment_account.resolve_payment_account` then fell through to the firm's
generic `%Bank%` ledger, so a line PASSED from the queue and the SAME line
SETTLED against a document landed in two different ledgers — the defect that
module's own docstring says it exists to end. The lookup returns None rather
than raising, because a transaction with no statement must still settle and the
resolver falls back exactly as before AND SAYS it fell back. ⚠️ `is_fallback`
and `reason` still reach no caller: the resolver runs inside eight
journal-line builders, so surfacing them is a refactor through the kernel's
callers and WHERE a CA is told is an owner decision.
**WHAT THE PARSER FOUND IN THE NARRATION IS BUILT ONCE**, by
`domain/banking/narration.parsed_view`, because there were two identical dict
literals — one per service — and BOTH omitted `cheque_no` (BANK-28), which
`ParsedNarration` has carried since the module was written and `describe()` has
always named in the summary. A cheque has no UTR, so the leaf number is the only
thing that tells one from the next, and plenty of Indian statements carry no
reference COLUMN at all — only a narration. So `match_and_settle_multi`'s
settlement reference falls back **caller → the file's own `reference_no` → the
parsed UTR → the parsed cheque number**, and that ORDER is the rule: a parse is a
reading of somebody else's document and must never displace what a person or the
statement itself said. The screens drop the cheque number where it merely repeats
`reference_no`.
**`bank_posting_service.post` is
INR-only and refuses rather than converting** — it calls `_create_journal` with
no `txn_currency`, so the kernel takes INR at rate 1 and a USD line reading
1,000.00 would be booked as one thousand RUPEES: balanced, footing, and wrong by
the exchange rate. Both the import (`banking_service._import_core`) and the post
refuse a non-INR `bank_accounts.currency`. `match_and_settle_multi` is
deliberately NOT guarded — it carries currency and exchange_rate through to
receipt/payment creation and is the path that already works; teaching
`post()`/`_plan()` the same needs a rate per statement line and a decision on
where the FX gain or loss leg lands, and `_create_journal`'s balance assertion is
exactly what an unbalanced FX leg breaks. `docs/audits/` and
the batch completion reports are historical records, not current specs.

**MULTI-CURRENCY HAS THREE GATES AND TWO OF THEM ARE NOW WRITABLE** (ACC-19).
`resolve_currency_policy` is `active = L1 AND L2 AND L3` — the environment kill
switch `MULTI_CURRENCY_ENABLED`, `firms.multi_currency_entitled` and
`clients.multi_currency_enabled`. All five multi-currency phases are BUILT and
none of it could be switched on: L2 and L3 (migration 146) were READ by policy.py
and six routers and **WRITTEN BY NOTHING** — no endpoint, no Pydantic field, no
screen, no seed — so only a manual UPDATE against the database could activate
any of it. `PUT /api/currencies/entitlement` and
`PUT /api/currencies/policy?client_id=` write them, Partner-only, and
`/settings/multi-currency` is the screen. **SELF-SERVE is an owner decision of
13-09-2026**: there is no billing or entitlement machinery in this product, so a
commercial gate has nothing to hang off; if it is ever sold the column does not
move and a plan check goes in FRONT of the endpoint. **The platform gate is shown
and never offered** — `core/feature_flags` says "No DB dependency", which is the
point of a kill switch. **The read says WHICH gate is down**, because `active:
false` alone is what made the feature unusable: a Partner ticked something and
could not tell. Turning a client ON is REFUSED with a sentence where it would be
inert — the firm is not entitled, or the client's functional currency is not INR,
Capability B (presentation and translation) being unbuilt — while turning it OFF
is never refused. `GET /api/currencies/entitlement` answers the firm gate with no
client in the request, because a firm with no clients yet is exactly the firm
this gets switched on for.

**THE AS 11 YEAR-END REVALUATION WAS BUILT, TESTED AND UNREACHABLE.** AS 11
paragraph 11 retranslates a MONETARY item held in a foreign currency at the
CLOSING rate on each balance sheet date and paragraph 13 takes the difference
to the profit and loss account, so a client with an open USD receivable at
31 March carries it at the rate it was invoiced at until somebody restates it.
`domain/currency/fx_revaluation_service.py` has done exactly that since
Multi-Currency Phase 4 — idempotent, self-healing, period-aware, posting
through the one kernel and auto-reversing on day 1 of the next period — with
**ZERO production importers**. `revalue()` is the only writer of
`fx_revaluations`, so `GET /api/fx-reports/unrealized` reported a structural
nil for every client however many foreign documents they held, while
`services/fx_reporting_service.py`'s own header claimed those tables were
"written by the Phase-4 settlement + revaluation paths" — true of settlement,
false of revaluation. The `capital_wip` shape again. ACC-19 made migration
122's gates WRITABLE on 13-09-2026, which turned a dormant phase into a live
gap: a firm can now switch multi-currency on and the year-end step it needs
has no door.
`routers/fx_revaluation.py` is that door, and it is **its own router
deliberately** — `routers/fx_reports.py` says "read-only FX reporting" in its
first line, and a POST that writes journals under that prefix would make the
next reader believe the contract still holds. Same reasoning that kept CWIP
off `/api/fixed-assets`.
**THE PREVIEW IS THE POSTING'S OWN WALK.** `plan()` was EXTRACTED from
`revalue()` rather than written beside it, so what a CA is shown before
confirming is what gets posted — two compositions of `_exposure` +
`_prior_runs` would drift, and a test counts the `_exposure` call sites.
`plan()` does **not raise on a missing rate**: a preview is most useful before
any rate is typed, because the whole point of opening it is to learn which
currencies need one, so a row with no rate carries `rate_gap` and no target.
`revalue()` keeps its strict refusal — an exchange difference is a real
posting and a rate nobody supplied cannot be guessed.
**THE PREVIEW REPORTS `closure_reason`, NOT THE FIRM-FY VALIDATOR AND NOT
`lock_reason`** — exactly what will actually refuse the post. The firm-FY
validator alone UNDER-reports, because the kernel asks `period_closure_reason`
for every entry (migration 361) and would refuse a finalised client year-end
the preview had said nothing about; `lock_reason` would OVER-report, because
**CGST Rule 34 fixes the rate of exchange at the TIME OF SUPPLY**, so
restating the rupee carrying amount afterwards cannot change a figure any
filed GSTR-1 or GSTR-3B reported. `revalue`'s own client-lock debt is
pre-existing and stays acknowledged in
`test_every_dated_posting_path_asserts_the_client_lock.py`.
**Nothing schedules it** — the closing rate is a fact somebody records and the
entry hits the P&L, so it is a CA action on a period they named; a test
asserts no job mentions it. **Re-running is the CORRECTION path**, posting
only the delta to the new target, and the panel SAYS so: a CA who believes a
second run duplicates will avoid the button after a rate changes and the
accounts stay wrong.

**A COMPANY CREDIT CARD IS A BANK ACCOUNT, AND THE DOUBLE ENTRY NEEDED NO
CHANGE** (BANK-21, migration 386). `bank_accounts.account_type` admitted four
values and none of them was a card, so the statement could not be imported, the
spend could not be coded through the bank workflow, and the monthly payment out
of the current account posted to whatever ledger somebody picked.
`domain/banking/account_kind.py` is the authority. **`posting_map.build_lines`
is direction-driven, so a LIABILITY ledger makes it already right both ways
round** — Dr Expense / Cr Card on a purchase (money out of the card account in
exactly the sense the posting map means), Dr Card / Cr Bank on a payment — and
nothing in the posting map, the settlement or the reversal moves. A test asserts
the posting map still does not mention a card, because a branch on the account
type there would be a second rule to keep in step. **What differs is the SIGN OF
THE BALANCE**: a card's is a credit balance and its own statement states it the
other way up, as an amount owed. So there is ONE convention inside the product —
ledger sign, positive is a debit balance — and exactly three translations at the
edge: the opening balance the CA types, the balances read off an imported
statement (`mirror_imported_statement`, which must run BEFORE `statement_check`
or a file that adds up perfectly is refused), and the register's response. A
MOVEMENT never flips: a ₹500 purchase is ₹500 on either kind of account.
**An OVERDRAFT is owed to the bank and is NOT mirrored** — it is drawn against a
bank account whose balance the bank prints the ordinary way, overdrawn as
negative; a card statement never prints a negative. **The Transfer derivation
now asks a FACT** — is this chart row the linked ledger of one of the client's
own bank accounts — because `_looks_like_bank_or_cash` requires `account_type ==
'Asset'`, which a card's and an overdraft's ledger never is, so paying the
company card out of the current account was coded "Other" and posted as an
expense against a liability ledger instead of a Contra. `None` means "not
established" and the name test answers as it always did. `entry_type_for` still
calls a card purchase a "Payment"; that is recorded, not fixed — the three
values are what `journal_entries.entry_type` allows and the accounting is right
either way. ⚠️ The card subtype presents under **Short-term Borrowings** with
the overdraft one; `[S]`, because Schedule III could not be read here and Other
Current Liabilities is defensible — both are current liabilities, so no total
moves, only which caption.

**A MATCHING RULE SAYS WHICH FIELD IT READS AND WHICH RULE WINS** (migration
380, BANK-11 steps 1 and 2). Until then `domain/banking/rules.rule_matches` was
one case-insensitive substring of the NARRATION plus an amount range and a
direction, and precedence was creation order with **no way to change it** — so a
broad rule written in April permanently shadowed the narrow one written in July,
and the only remedy was to delete and re-create the broad rule, which loses its
TRUSTED flag. The row now carries `priority` (lower first, default 100),
`match_field` (`description | reference_no | payee_name | any`), `match_operator`
(`contains | starts_with | equals`) and `description_patterns`, so "NEFT from any
of these three customers" is one rule and a UTR or cheque number is matchable at
all. **Every default reproduces the old behaviour exactly** — `by_precedence` is
`(priority, created_at, id)`, so at the default the order is still creation
order and no existing rule changes which transactions it fires on or which rule
it beats. `MATCH_FIELDS` maps the rule's own value to the KEYS of the
transaction dict, so a caller that renames a field breaks there rather than
silently matching nothing; a rule naming a field its caller did not supply does
not fire, which is the safe direction. **WHAT A RULE MAY PROPOSE IS UNCHANGED
and that is deliberate**: a trusted rule posts unattended, so widening the
PAYLOAD — split legs, a party, a TDS treatment — widens what happens with nobody
watching. That is step 3, an owner decision, and a guard asserts
`RuleSuggestion` gained no field. Matching wider is different in kind: a CA
types every pattern, and the widest case was always reachable (an empty pattern
matches everything). Both doors validate — a validator only on create is one
PATCH from being none — and both read the ENGINE's own maps rather than a third
list.

**`docs/audits/findings-status.md` is where to start on any "what is left"
question, and it is the ONLY status record that is kept up to date.** Every
other document below is a SNAPSHOT taken on a date and never amended, which is
why each successive pass found the one before it stale — 10% on 11 September,
then 38-59% by subsystem on 12 September, then another nineteen by hand the
same evening. `findings-status.json` is the record and is amended in the same
commit that closes a finding; `findings-status.md` is it made readable, and
`scripts/findings_status_md.py` regenerates it. **Amend the JSON in the commit
that closes the finding** — a status only ever written by an audit is wrong by
the time it is read.

Read its four states before quoting a number: `closed` was re-read against the
code, `closed_by_commit` was named in a merged commit and NOT re-read (usually
fixed, occasionally only cited), `unverified` means a probe was inconclusive
and is NOT the same as open, and `open` was re-read and is still true. Nearly
every open item is blocked on a migration or on a statutory document a person
has to read, and the table says which.

**The rest of `docs/audits/` — the passes below, all from 7-12 September 2026 —
are the ANALYSIS behind those verdicts. They are still worth reading for WHY a
finding is what it is and whether its suggested fix is sound; they are no
longer to be trusted for WHETHER it is open:**

| File | What it is |
|---|---|
| `2026-09-07-where-we-are-against-the-one-platform-goal.md` | the full platform audit against the one-platform goal: 278 findings, the module scorecard, the market comparison, and the staged plan. §13 records the verification pass |
| `2026-09-07-findings/` | the 278 findings as JSON, one file per subsystem. **Sort by `verification.corrected_severity`, not `severity`** — the raw severity is the reader's first impression, the corrected one survived an adversarial check |
| `2026-09-07-a-plus-roadmap.md` | what each of the 14 modules needs to reach A+, defined as five testable properties, in a seven-stage order that starts by proving correctness |
| `2026-09-08c-the-phase-plan.md` | **the plan being worked to.** All 254 remaining items in twelve phases grouped by FIX SHAPE rather than by module, so each phase teaches one pattern and ends with one guard test. Every critical and high is assigned; two duplicate pairs are named (PUR-07≡TDS-13, IT-09≡FA-06) |
| `2026-09-11-the-verification-pass.md` | **the current remaining-work list. Start here.** All 163 medium/low findings re-checked against the code by nine read-only agents: 131 still open, 15 partial, 17 closed — so the backlog is ~10% stale, not the ~73% a spot-check had suggested. §2 is the part that matters: **seven findings whose severity went UP** because Phase 7 built the screens that had been holding them latent, and nothing re-scored them. §3 carries two live defects with no finding at all. §6 is the build order |
| `2026-09-12-the-probe-pass/` | **read this before scheduling any of the above.** All 213 findings re-read against the code by nine read-only agents — one slice file per subsystem — asking the one question the 11 September pass did not: *is the finding's own suggested FIX sound?* **It was not, thirteen times.** Two would break working, test-pinned behaviour (**ACC-23** a balance sheet that is currently self-correcting, **ACC-25** the expiring-signed-URL and stored-XSS hole `domain/banking/attachments.py` exists to close); eleven more would break something smaller (**SALES-13** prints the CA practice's UPI ID on the client's own outward invoice, **TDS-23** turns a visible 422 into a silently mis-routed 26Q row, **TDS-19** drops a genuine §194-IA credit, **FA-14**'s `is None` divides by zero). Also five materially false premises (PUR-28's fix might DROP the four live policies it claims are absent), and **sixteen defects with no finding at all**. **Stale rates far above the 10% the 11 September pass measured** — sales 59%, payroll 53%, fixed assets 50%, TDS 44% — so the finding JSONs are no longer a usable work list on their own and these ten slice files are |
| `2026-09-08b-what-is-left.md` | the previous remaining-work list, re-scored against `9fbe40d`. **Superseded by the 11 September pass** — its severities predate the screens Phase 7 shipped. Kept because its §2 is the record of what the last tranche introduced |

`docs/audits/2026-09-07-market-research/` holds the statutory re-check behind
them. **Nothing in it is graded `[P]`** — direct egress is refused at the proxy
(`curl https://example.com` → CONNECT 403), which is this environment's network
policy rather than a gov.in block, so every claim rests on a search engine's
summary of a page nobody opened. Each file ends with a ranked re-verify list.

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
  signs". As with AA consent, **that shape already exists** in
  `routers/engagement_sign_public.py` and should be followed rather than
  re-invented; and as with AA consent, the signing itself happens on the PORTAL,
  never in our UI — an EVC OTP field in this app is a credential capture surface
  whatever it is labelled.
- **The rule in "Code rules" still holds and gets stronger, not weaker.** Never
  auto-submit. Real filing means an explicit confirmation click, per return,
  every time — never a batch, never a scheduler, never a retry that resubmits.
- **Idempotency.** A double-submitted return is not a duplicate row, it is a
  second filing against a live portal. Any real implementation needs the
  reference recorded before the call and checked after a timeout, never a blind
  retry.

**`docs/compliance/07-getting-permission-to-file.md` is the playbook**: what to
apply for, in what order, what it costs, and what each one unblocks. Read it
before starting any of this. Its headline: the Third Party Software Utility
Developer registration that yields `SW########` is self-service and available
now, while ERI, GSP and NIC production credentials are months of commercial
work — and **e-invoice IRN and e-way bill are the only two statutory outputs
software can complete end to end**, because the IRP signs and there is no
taxpayer signature.

Demo filing walk-throughs exist to SHOW these flows before they are real. There
is exactly ONE implementation: the shared filing-demo framework —
`services/filing_demo/` (a flow per statutory filing, GSTR-3B included), served
by `POST /api/filing-demo/{flow}/preview` and rendered by
`components/FilingDemoWizard.tsx`. **Two rivals have been deleted rather than
left beside it**, because two demos of one return drift and each needs its own
safety argument: the bespoke `POST /gst-workspace/gstr3b/{id}/simulate-filing`,
and a browser-side one (`DemoFilingModal` + `lib/filing/demoFiling`) reachable
from `/deadlines`. The second is the cautionary one — it minted the reference
and validated IN THE BROWSER, wrote `demo_filings` over PostgREST so `rbac()`
never ran, and **never called the server, so `ENABLE_FILING_SIMULATION` did not
reach it**: turning the kill switch off left it simulating filings anyway.
`apps/web/scripts/one-filing-demo-and-the-kill-switch-reaches-it.test.ts` holds
the line, and every screen offering the wizard must probe
`fetchFilingDemoCapabilities` first. A demo belongs on the screen where the
RETURN lives, never on the deadline list — a deadline row is not a return.

**Fidelity is a product requirement, and so is disowning the result.** CAs are
being shown these flows to judge whether real filing will be worth switching
for, so each walks the portal's actual sequence — IMS before GSTR-3B Table 4,
GSTR-1A before §37(3), GSTR-9C beside GSTR-9, the §140A challan, the ECR's
wage-month order, SRN-is-not-filed on MCA. And every flow states **what changes
when this is real**, which `envelope()` RAISES without, so the honesty is
structural rather than a reminder; three of them say plainly that no
registration is even waiting, because TDS, PF and ESI have no API to be
granted. **There is no OTP input anywhere in it** — an EVC field in this app is
a credential capture surface whatever it is labelled, and it is also simply
wrong: the OTP is typed on the portal, never in the software that prepared the
return.

They are portal-faithful
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
writes the real ARN, the filing date, and the **`public.filings`** row that
`journal_period_lock_reason` reads to lock the period. (There is no
`gst_filings` table — this file said so for a long time.
`services/gst_filing_record_service.py` is the authority.) Until 2026-09-08 no
screen called that endpoint: `lib/data/gst.ts` wrote `status: "submitted"`
straight into `gstr3b_returns` over PostgREST, so `rbac()` never ran, the
backend's `record_filing` never ran either, and **a filed return did not lock
its period**. It now PATCHes, and checks `res.success` — the GST workspace
router answers refusals as HTTP 200 with `{success: false}`, so an unchecked
call showed "Filed" for a request the server had declined.

### Live bank feeds through the Account Aggregator

Fully specified already — see **"Bank data — the Account Aggregator is the only
way in"** above. Nothing about it has been built: statement upload is the only
path in today, and it stays at parity for years regardless.

Restated here only so this list is complete: register as an FIU, go via a TSP,
the consent is the CLIENT's and is time-bound and revocable, and **never
screen-scrape net banking**. Read that section before touching any of it.

**The consent flow's SHAPE is written down and nothing is built** —
`docs/compliance/05-…` §6. It exists so a first attempt does not put an "I agree"
control on our own page: the request, the tokenised link, the expiry and the
audit all follow `routers/engagement_sign_public.py`, and the ONE step that does
not transfer is the approval, which happens at the AA. Six refusals are recorded
there, including never render the approval, never touch an OTP, never treat a
consent as durable (the client can revoke without telling the CA), and never
declare purpose code 102.

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

**That claim has now been wrong twice, and how it was wrong the second time is
the part worth keeping.** "All 61 call sites across 28 files are converted"
stood here unguarded while **nine more** lived on until 2026-09-08 — the bank
settlement modal (which posts to the GL), the bank match filter, the bank rules
editor, the recurring journal, client billing, the budget grid and the GSTR-2A
import. `components/banking/shared.ts::rsToP` was the reason: it took a `number`
and did `Math.round(rs * 100)`, so every caller had to `parseFloat` first. It
now takes the text as typed and returns null.

Prose was then replaced by **three regexes** — `rsToP(parseFloat`,
`Math.round(parseFloat` and `parseFloat(…) * 100` — and the same claim was
re-made on top of them. Running those three over the tree the next day found
**sixteen more files** none of them matched, because none of them is the rule.
Each names one SPELLING, and the defect has as many spellings as there are ways
to write a number:

```
parseInt(s.replace(/[^0-9]/g, ""), 10) * 100   // "1234.56" -> ₹1,23,456
Math.round(Number(cleaned) * 100)              // "1e3"     -> ₹1,000
Number(whole) * 100 + Number(frac)             // "1.2.3"   -> ₹1.02
```

So the guard is now the RULE rather than a spelling of it, in two directions:
**nothing whose name ends in `_paise`/`Paise`/`_bps`/`Bps` may be built with a
numeric coercion or a multiplication by 100**, and **a function whose own name
says it makes paise out of text must delegate to `lib/money/rupeeInput.ts` by
name**. A cast of a value ALREADY in the unit — `Number(row.tds_paise ?? 0)`,
because PostgREST returns a bigint as a string — is allowed and is the only
thing that is. The three original regexes are kept as a third test because each
of them is a bug that shipped. Against the code of 2026-09-08 the new check
fails on **26 sites across 17 files**; the three regexes passed on every one.

The module also carries
`bpsFromPercentInput` (a typed percentage → basis points) and `parseQuantity`
(up to three decimals, matching `NUMERIC(10,3)` on the line tables), and
`lib/money/lineInput.parseLineAmounts` reads a document line's quantity and rate
together — used by the validator, the preview and the payload, so what a CA is
shown adding up and what is saved are the same numbers.

**One deliberate exception, and the three files that call it — four allowlisted
paths in all.** `gstLine.ratePaiseFromRupees` and `computeLineGst` still take
the rate STRING and still do `Math.round(rate * 100)`, and the three
purchase-note previews still call them that way. `shared/gst-parity-vectors.json` pins those to the Python backend on
exactly those strings — including `"1.005"`, which the backend truncates to 100
paise and which the new parser refuses. Converting to paise and dividing back
would put a float round-trip inside the one calculation that is pinned. What
protects them instead is upstream: `parseLineAmounts` has already refused
anything but a plain decimal by the time they see it.

`parseQuantity` is deliberately NOT named `quantityFromInput` — `gstLine.ts`
exports one of those, which COERCES to 0 and is the parity-pinned payload
builder. Two functions with one name in one directory is how the wrong one gets
called.

**A QUANTITY HAS THE SAME RULE AND ITS OWN GUARD, and the guard is the RULE
rather than a list of doors** (INV-09). Every quantity column in this schema is
`NUMERIC(10,3)` (migrations 050, 188, 210), so a fourth decimal is accepted,
rounded by Postgres, and the money computed from what was TYPED no longer
matches what was stored — which is the Inventory-control tie-out this file makes
load-bearing. `domain/quantity.quantity_violation` is the one rule; the
OPENING-STOCK door did not ask it while five others did, so
`opening_qty_units=1.2345` was accepted where the identical figure on a stock
adjustment was refused. `tests/test_a_quantity_door_asks_the_column_how_many_
decimals.py` derives the door list from the AST — every Pydantic field whose
name says quantity and whose annotation is NUMERIC, so a bool like
`quantity_is_provisional` is not one — checks **per class** (a module-level walk
passes when only one of a create/PATCH pair is guarded, which is exactly what
these two were), and follows **one level of indirection**, because
`models/invoices.py` legitimately factors the check into `_validate_quantity`
and a scan seeing only the direct call would push the next author into copying
it back. On the browser side the importer goes through `toQty`, the helper the
invoice and bill line importers already use, and **`num()` — a bare `parseFloat`
— is deleted**: its last call site gated a receipt's amount on a value it did
not parse, so `"1200abc"` passed at 1200 while `toPaise` returned NaN, and
`NaN <= 0` is FALSE, so the row was built with `amount_paise: NaN`, which
`JSON.stringify` sends as **null**.

## Identifiers

- **GSTIN carries a check digit, and the shape regex does not test it.**
  `apps/api/domain/gst/gstin.py` is the authority; `apps/web/lib/gst/gstin.ts`
  mirrors it for keystroke feedback and the two are pinned by
  `apps/api/tests/fixtures/gstin.json`, which both suites read. Enforced
  wherever a human TYPES a GSTIN — onboarding, and the customer and vendor
  **create, BULK-IMPORT and PATCH** paths. **That list used to say "create
  paths" and the code matched it, which was the defect** (GST-29): a CSV import
  and an edit form are both places a human types a GSTIN, and both were open.
  §16(2)(aa) sends the credit to whoever the GSTIN names, so a valid-shaped
  wrong one hands a customer's credit to a stranger, correctable only by an
  amendment inside the §37(3) window; on the purchase side it is why a bill
  sits in "missing in 2B" for ever while the CA chases the wrong party. The
  bulk paths report it as a per-item error rather than 422-ing the batch, which
  is that endpoint's own design.
  **And on the paths that FILE with one, since GST-29's second half.**
  `domain/gst/validator.GSTValidator.validate_gstin` was a bare shape regex
  and so was `core/validators.validate_gstin` — the one
  `routers/gst_workspace.py` records a filed return through — so a
  valid-shaped wrong GSTIN built the whole GSTR-1 or GSTR-3B and offered it
  for filing under a registration belonging to somebody else. Both delegate
  to `problem_with` now. The CLIENT'S OWN GSTIN is a hard refusal (the return
  is filed under it); the COUNTERPARTY's is REPORTED in the return's own
  exception list, because refusing a whole build for one wrong customer is
  how a CA learns to skip the validator. **`core/validators` no longer holds
  a GSTIN pattern at all** — the pattern is an invitation to answer the
  question the cheap way. `models/parties.CustomerIn` and `VendorIn` read the
  shared function, so the refusal now happens at the MODEL; the bulk path
  builds them inside a per-item `try`, so one bad row is still one row's
  error. **THREE FIXTURE GSTINs WERE CORRECTED, NOT THE GUARD** —
  `27AAAAA0000A1Z5`, `27AABCU9603R1ZX` and `27BBBBB1111B1Z5` all had wrong
  check digits and were used in 77 files, including two frontend
  placeholders that taught a CA an example their own keystroke validator
  rejects.
  **TWO STATE LISTS, DELIBERATELY DIFFERENT.**
  `domain/gst/validator.VALID_STATE_CODES` is for a PLACE OF SUPPLY and
  includes **96** (outside India, where an export goes);
  `domain/gst/gstin.VALID_STATE_CODES` is for the first two characters of a
  GSTIN and does not, because a GSTIN is a registration in a state.
  Collapsing them would either refuse every export or accept a GSTIN that
  cannot exist.
  Deliberately still NOT in `models.client.validate_gstin`, which guards a
  Pydantic field that 512 invented fixture GSTINs across 95 files flow through.
  Closing the bulk door showed how load-bearing that carve-out is:
  `test_customer_bulk_create`'s own fixtures both ended in `5`, so the import
  path had only ever been exercised with GSTINs the portal would reject. The
  fixtures were corrected, not the guard relaxed.

- **THE FIRM'S OWN GSTIN LIVES IN TWO COLUMNS AND ONLY ONE IS READ.**
  `public.firms` carries `gst_number` (migration 003) AND `gstin` (014, given
  its CHECK by 112/316), nothing has ever synced them, and the two sides of the
  product picked different ones: BOTH screens that edit the firm profile wrote
  `gst_number` **straight over PostgREST** — Settings and the onboarding
  wizard's UPDATE step — while every backend reader read `gstin`. So a CA who
  typed their GSTIN into Settings got a fee invoice with **no supplier GSTIN**
  on it (CGST Rule 46(a)) and, because `_state_code(None)` is None, the whole
  tax on a LOCAL supply landed in **IGST** instead of splitting CGST+SGST.
  `POST /api/onboarding/firm` has always written `gstin` correctly; it is only
  the screens' own update path that did not, so which route a firm came in
  through decided whether its own GSTIN was readable at all.
  **Measured before acting, because the severity turns on it**: on 17-09-2026
  production held 2 firms with BOTH columns NULL — latent, and live the moment
  anybody typed one in. The `capital_wip` shape: built, reachable, structurally
  nil.
  `domain/firm/identity.py` is the authority: **`gstin` is the column,
  `gst_number` is READ as a fallback and never written**, and `gstin_of` is the
  only reader. One writer, `PATCH /api/firms/profile` (Partner-only), which is
  also where the **CHECK DIGIT** is tested — `firms_gstin_format` is a shape
  regex and accepts a transposition, and that GSTIN goes on every fee invoice
  the practice raises with nothing downstream to re-check it. Writing BOTH
  columns was rejected: it would make `gst_number` a cache with two writers,
  the shape this file records going wrong on `clients.gstin` and on the retired
  supplier table. **A narrow `select()` that names one column and not the other
  makes the fallback a silent no-op** — `routers/practice.py` did exactly that
  — so every read names BOTH, the same trap
  `domain/accounting/opening_documents` records for `is_opening`.
  **AND EACH OF THE THREE PROJECTIONS IS WRITTEN OUT AT ITS CALL SITE rather
  than shared through `identity.COLUMNS`**, which reads like the thing to
  factor out and is not: `tests/test_backend_columns_exist_pg.py` checks every
  `.select()` in `apps/api` against the real schema AS A STRING, and a
  projection reached through a name — a `", ".join(...)`, a module constant —
  is invisible to it; so is the guard written for this very feature, which
  passed having looked at NOTHING until the three became literals. That guard
  reads the **AST** now, not a regex, because the literal these fifteen columns
  produce spans three adjacent strings and a regex sees only the first — it was
  vacuous twice, for two different reasons, and carries a floor saying how many
  projections it must find.
  **Migration 399 back-fills `gstin` from `gst_number`** where the first is
  empty and comments both columns, so the fallback is inert for every existing
  row. It deliberately does NOT drop `gst_number` (that moves both sides of the
  production-fixture comparison at once and needs the refresh in
  `docs/schema-drift.md` — migration 371's decision about
  `public.tds_section_limits`), does not `SET NOT NULL`, and **leaves a row
  whose `gstin` is malformed but not empty alone**: `firms_gstin_format` is NOT
  VALID, so such a row can exist, and preferring the superseded column over a
  value somebody recorded in the canonical one would be a guess about the
  firm's own legal identity. ⚠️ The shape carries over; the CHECK DIGIT does
  not, and the migration says so.

- **A UAN and an IFSC are format-checked at every door; an ESIC number is
  not, and that is a decision.** Both patterns live once, in
  `domain/payroll/identity.py` — `UAN_RE` (12 digits, EPFO's own format) and
  `IFSC_RE` (RBI's four letters, `0`, six alphanumerics). They already existed
  in `employee_import.py` (which refuses a whole file) and `ecr.py` (which
  refuses a member at file build); what had no check was the API, so a UAN
  typed on the form was stored and wedged the ECR months later, at the moment
  the CA was trying to file. `EmployeeIn` and `EmployeeUpdateIn` both validate
  now — a validator only at the create door is one PATCH from being none.
  **`esi_number` stays a presence check**: nothing in this codebase validates
  its format anywhere, no length is confirmable here, and a pattern written
  from memory would refuse legitimate numbers for every client. Same judgement
  as the EPF establishment code, the LIN and the state PT slabs.
- **A YEAR PICKER IS DERIVED FROM THE CLOCK, NEVER LISTED** —
  `lib/dates/periods.financialYearChoicesAround` for a financial year and
  `assessmentYearChoicesAround` for an assessment year, the second DERIVED FROM
  the first (IT Act §2(9) with §3: AY = FY + 1) rather than parsing the date
  again. Two functions each working out "the current year" are two controls
  that can describe different periods.
  `scripts/a-financial-year-choice-comes-from-the-clock.test.ts` is the guard,
  and its own history is the lesson: it forbade `<option value="2025-26">` and
  nothing else, so twelve more screens spelled the same defect as
  `const FY_OPTIONS = ["2025-26", …]` and **eight of them ended at a year
  already past**. It now matches the array form too, and strips comments first.
- **A financial-year label is a TYPE, not a `str`.** Annotate every route
  parameter and request-model field that takes one `FYLabel` (or
  `OptionalFYLabel`) from `apps/api/models/fy.py`;
  `core.ist_clock.normalise_fy_label` is the authority. It accepts `YYYY-YY`
  and `YYYY-YYYY`, canonicalises to `YYYY-YY`, and refuses a second half that
  does not follow the first — which a shape regex cannot: `2026-28` passes
  `^\d{4}-\d{2}$` and then means 2026-27, because `fy_bounds` and the older
  private parsers read the first four characters and ignore the rest. That is
  a wrong return, not a rejected request.
  `tests/test_fy_labels_are_validated.py` fails if a new one goes in bare.

  **`fy: FYLabel = Query(...)` validates NOTHING.** FastAPI builds the field
  from `Query()` in the default position and discards the Annotated metadata
  carrying the validator — silently, so the endpoint reads as guarded. Write
  `Annotated[FYLabel, Query(...)]` instead (add `= ...` where argument order
  needs a default). Pydantic's `Field()` in the default position does NOT
  behave this way, which is what makes the assumption easy.

  `fy_bounds` stays deliberately lenient: it is a domain function whose caller
  already knows the label is a label, and several callers depend on that.
  Strictness belongs at the boundary.

  **AN ASSESSMENT YEAR IS THE SAME RULE AND HAS ITS OWN TYPE.** `AYLabel` /
  `OptionalAYLabel` were written in the same sweep and exactly one router used
  them, so six boundary fields still took an AY as a bare `str` and `2026-28`
  meant 2026-27 there for the same reason — while
  `tests/test_fy_labels_are_validated.py` scanned only `financial_year`, which
  is the "a guard states one spelling of its own rule" shape that file's own
  header warns about. It scans both families now, with a per-family vacuity
  floor (one combined floor would have stayed green on the fifty-odd FY entry
  points alone). **The two are NOT interchangeable and a test says so**: both
  validate identically, so only the NAME keeps them apart, and AY 2026-27 is
  FY 2025-26 — a route that muddles them reconciles the wrong statement
  against the wrong return.

- **THE SEVEN ITR FORMS ARE `domain/income_tax/itr_json.ITR_FORMS`, derived
  from the `ITRForm` Literal the field mappings and the committed Department
  schemas are keyed on** (IT-23). The filing screen held its own list of four
  and `itr_workflow`'s docstring agreed with it, so a SALARIED client
  (ITR-1/ITR-2) or a PRESUMPTIVE one (ITR-4) could not have a filing record
  created at all — most of a practice's ITR volume — while verified paths and
  a schema for all seven sat unused. `itr_workflow.validated_form` is the one
  place that decides (canonicalising as it goes, because the value is stored
  and then filtered on), `GET /api/itr/forms` serves the list, and
  `apps/web/.../tax/filing/page.tsx` keeps a fallback array for the redeploy
  window only — the Schedule III caption shape. A test forbids a third copy.
  **`record_filing_acknowledgement` is part of the state machine**: it wrote
  `status = "filed"` with no read of the current status, so a draft could be
  marked filed past the review and partner review the tax screen promises are
  mandatory. The permitted states are derived from `_TRANSITIONS`, and an
  already-filed return is REFUSED rather than silently re-acknowledged — the
  acknowledgement number is a fact about what the portal did. **Still not
  built: the §139(5) revised and §139(8A) updated return**, which need a
  `return_type` and a migration replacing migration 319's
  `UNIQUE (firm_id, client_id, financial_year, itr_form)`.

## Bug fixing

- When the user reports a bug, don't just patch the one instance. Identify the underlying pattern (wrong column name, missing null check, stale label, unapplied migration, etc.) and grep/search the rest of the codebase for the same pattern before calling the fix done. Report what else was found, even if you decide not to touch it.

## Commit messages

Match the existing history. A commit explains **what was wrong**, **what the fix does and
why that shape**, and **how it was verified** — including how many new tests fail against
the previous code (the negative control). State when a change has no live effect yet, and
say so explicitly when there is no migration. Subject line is a plain sentence describing
the behaviour change, not a conventional-commits prefix.
