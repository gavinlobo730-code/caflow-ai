# The phase plan — 254 items in twelve phases, grouped by fix shape

Against `9fbe40d`. Supersedes the ordering in `2026-09-08b-what-is-left.md` §8,
which was a next-five list rather than a plan for the whole backlog.

## The organising idea

Phases are **not** modules. A module-shaped plan ("do GST, then payroll") makes
every phase a fresh start: new files, new statute, new test fixtures, and the
same class of defect fixed six times in six places without anyone noticing it
was one defect.

These phases group by **fix shape** — the kind of change, not the subsystem it
lands in. Each phase therefore:

1. teaches **one pattern**, applied N times, so items 2..N are much cheaper
   than item 1;
2. ends with **one guard test** that fails if the class comes back. That is the
   lesson of the money parser: the fix was cheap and lasted only until the next
   spelling, because the guard named three spellings instead of the rule;
3. is a **single reviewable PR** with one argument to check, rather than a
   grab-bag.

## What the 254 actually is

| | count | note |
|---|--:|---|
| open + partial findings | 239 | |
| regressions the last tranche introduced | 7 | no finding ids |
| §4 carry-overs from the 8 Sep pass | 8 | no finding ids |
| **tracked items** | **254** | |

Of the 239 findings, **1 is critical and 80 are high**. All 81 are assigned
below, with none left over and none assigned twice.

**Two are outright duplicates**, found by two readers in two subsystems:

* **PUR-07 ≡ TDS-13** — the §197 lower-deduction certificate. Both scored
  "weeks"; it is one piece of work.
* **IT-09 ≡ FA-06** — §32 block-of-assets depreciation and the dead
  `build_bridge`. Scored "months" and "weeks"; it is one piece of work.

So 81 criticals and highs are **79 distinct changes**, and the same ratio very
probably holds across the mediums — which is why the effort roll-ups below are
upper bounds.

---

## The phases

Effort is the audit's own per-finding estimate, rolled up at hours≈0.5d,
days≈3d, weeks≈10d, months≈40d. **It double-counts** wherever a phase fixes one
root cause behind several findings, which is the whole point of the grouping —
treat each number as a ceiling, not a forecast.

### Phase 0 — Undo my own damage · 7 items · ~4 days · **DONE**

The seven regressions the last tranche introduced (`2026-09-08b` §2). No finding
ids; two are high. **First, for the same reason §2 came first last time:** new
breakage on `main` outranks old breakage, and one of these destroys data.

**Closed.** Migration 341 adds `gstr2b_reconciliations` — one row per (client,
period) recording that a 2B was reconciled at all — and puts `document_type`
into the 2B natural key. `compute_gstr3b` now TAKES `have_2b` instead of
deriving it from a list the caller has already filtered; `gst_return_service`
answers it from the header. The service paginates. `rates_verified` now means
verified *for the year asked*, and names both years when it substitutes. The
payslip route reports the real refusal. `domain/reporting/pdf_text.py` is the
one place that knows a core-font PDF cannot print ₹, and three services stopped
emitting it. Three UTC "today"s in `routers/fixed_assets.py` became IST.

*Guard:* `tests/test_a_reconciliation_records_that_it_happened.py` — 13 tests,
**8 fail against the previous code**. The other five are honest: two assert
primitives that were already correct (the cap function, the parser — the bugs
were in the caller and in the index), two exercise files the revert could not
remove, and one is the control that the FY guard must not simply always answer
False.

*Two things the guard caught that the re-score had missed:* `_PLAIN_HEADER` in
`invoice_pdf_service` still carried ₹, so the simple invoice layout printed a
box in its column head; and a first version of the PDF guard flagged the two
COMMENTS explaining why "Rs." is used — the money-parser mistake again, fixed by
walking the AST for emitted string literals rather than grepping the file.

### Phase 1 — The ledger model: cash is not bank · 6 findings · ≤32 days · **DONE**
`ACC-02 ACC-03 SALES-08 BANK-20 BANK-02 FA-07`

**Closed across three PRs.** 1a (#462): `domain/accounting/payment_account.py` is
the one resolver, and SIX posting paths ask it — three of which no finding named
(the foreign-currency receipt and both FX payment paths). Migration 342 gives
receipts and purchase payments a `bank_account_id`; overdraft ledgers are
re-classified to Liability/'Bank Overdraft', a subtype CHECKED against
`bs_bucket()` rather than chosen. 1b part 1 (#463): migration 343 gives an asset
its acquisition facts, and `acquisition_mode` decides the credit leg — the
`from_bill` case posts NO acquisition entry, only a reclassification, which is
what stops the double count. 1b part 2: the cash book, with the one rule a bank
book does not have.

*Guard:* `test_no_posting_path_names_a_ledger_by_string.py` — the rule, walked
over the AST. Its debt list is down to one entry (`opening_balance_service`,
deliberate and correct), and a second test fails if that stops being true.

*The routing constraint this phase ran into, recorded because the next screen
will hit it too:* `public/_redirects` was at Cloudflare Pages' cap of 100
dynamic rules, and every new `/clients/[id]/*` page costs 2. The cash book ships
as a component on the existing bank-book route for that reason. The proven
lever — merging a static sibling into its dynamic sibling, 3 rules per pair, six
already done — has exactly ONE candidate left (`year-end/xbrl` into
`:engagementId`), and taking it would mean calling "xbrl" an engagement id. The
budget needs real work before the next page.

Every one of these is the same line of code in six places: a posting path names
a ledger by string instead of resolving the account the user chose. Cash
receipts land in Bank, Cash in Hand never moves, an OD account is given an Asset
ledger, and buying an asset always credits Bank.

*Why first among the real work:* it is a **general-ledger correctness** problem.
Every report downstream — trial balance, P&L, balance sheet, cash flow — reads
the wrong ledger, and no later phase can be trusted while it holds.
*Guard:* no posting path may name a ledger by string literal.
*Falls out free:* the cash book (BANK-20) is a screen once the ledger is right.

### Phase 2 — A filed period is closed, and a locked one can reopen · 3 + 1 · ~5 days · **DONE**
`PUR-08 ACC-05 GST-14` + the `post_draft` carry-over

Same `period_lock_service` machinery already used for SALES-15. A bill can still
be received into a filed GSTR-3B period; a locked year never reopens; `/gst` and
the workspace disagree about what "filed" means; `post_draft` checks the firm
lock and not the client's.

*Shape:* one helper, four call sites, one vocabulary for "filed".
*Guard:* every create/post path asserts the lock — the shape I already built.

**What it actually took, which was wider than four call sites.** Reading the
four document routers side by side showed the omission was the whole PURCHASE
half, not two endpoints: sales invoices, sales credit notes and sales debit
notes assert the lock on create, on both dates of an edit and again at issue,
while purchase bills asserted it only on edit and purchase credit and debit
notes not at all. **Ten call sites**, one rule. It matters more on that side —
a sales document slipping into a filed period overstates output tax the return
already declared; a purchase document claims INPUT CREDIT the return never
took, and §16(4) puts that credit in the current period instead.

Three things were found on the way that the findings did not name:

- **`post_draft` read two columns it never selected.** It tested
  `je.get("deleted_at")` to refuse a soft-deleted draft and logged the timeline
  against `je.get("client_id")`, while `_SELECT` asked for neither — so both
  were always `None`. A soft-deleted draft could be posted to the books, and
  every `post_draft` timeline row was written with no client. Invisible to the
  suite because FakeDB skips its column projection when the select carries an
  embed, and that one carries `journal_lines(...)`.
- **The year-end lock could never have been written.** Both routers passed
  `current_user["auth_user_id"]` into `client_year_locks.locked_by`, which FKs
  `public.users(id)`; production holds no user whose ids match. The INSERT
  would raise 23503 *after* the engagement row had been written
  `status='locked'` — engagement finalised and terminal, client's year still
  open. Latent only because production has no year-end engagements.
- **The guard written for that exact bug was pinning it.**
  `test_the_audit_log_actor_is_deliberately_untouched` asserted a literal
  string that, in that file, matched only the `lock_year_if_completing` call —
  the wrong one. And the `_pg` sweep looks for the column name and the auth id
  in one window of source, so a value crossing a function boundary is invisible
  to it. Both are fixed, and the sweep now follows the parameter through the
  call chain.

*Also done here, because the ratchet demanded it:* the production schema
snapshot was 12 migrations stale and `ADDED_AFTER_THE_SNAPSHOT` had grown to 41
entries — one over its own cap. Refreshed and proved equal to production
(md5 `dff5c56d…`, 3,999 columns in 270 tables); the list is back to 3.

### Phase 3 — One TDS engine, and the browser copy deleted · 8 findings · ≤19 days · **DONE**
`TDS-05 TDS-11 TDS-03 TDS-15 TDS-04 TDS-14 PUR-06 PUR-14`

`/tds` computes TDS in TypeScript from a stale hardcoded table and writes
straight to `tds_deductions` — **with no role check** (TDS-11 is the security
finding). The screens around it fail against the real database in three
different ways. The engine that would give the right answer is already tested.

*Shape:* delete the second implementation, point the screens at the engine.
This is exactly the filing-demo lesson in CLAUDE.md: two implementations of one
thing drift, and one of them is silently exempt from the guard.
*Guard:* the zero-business-logic-in-the-frontend rule, made testable for TDS.

**All eight done: TDS-11, TDS-05, PUR-06, TDS-03, TDS-15, TDS-04, TDS-14,
PUR-14.**

**The browser's table was wrong in EIGHT ways, not the two TDS-05 named.**
Checked row by row against `section_rates.py` and each is now a test:
§194C flat at the company rate (an individual/HUF is 1% — **double**);
§194D flat 5% against 2% individual / 10% company (**wrong both ways**, and the
company case *under*-deducts, which disallows the expenditure under §40(a)(ia));
§194H 5% against 2% since the Finance (No. 2) Act 2024; §194Q on the whole sum
where §194Q(1) charges on the **excess** over ₹50 lakh (₹6,000 vs ₹1,000 on a
₹60 lakh purchase); §194IA offered at 1% and **absent from the engine**; §192
leaving the previous rate in the box so salary wrote at 10% into a 26Q register;
no threshold anywhere; no FY aggregate, so §200 never credited.

**And the table had THREE copies.** `/tds`'s `TDS_SECTIONS`, the vendor form's
`TDS_DEFAULT_RATES`, and the rates baked into the vendor form's section dropdown
*labels* — where §194D and §194H both read "(5%)". The third is what seeded
`vendors.tds_rate_bps`, which is PUR-06's dead field: production's five §194C
vendors carry 200 bps, the **company** rate, so honouring it would have doubled
every individual contractor's withholding. The field is gone from the form.

**Two structural facts nobody had written down:**
- `tds_26q_from_books` builds the return from **`purchase_bills`**, never from
  `tds_deductions`. The /tds register is a parallel book no return path reads.
- The two registers therefore do not share an FY aggregate. Unifying them means
  keying both halves on the PAN; it changes a delicately argued, heavily tested
  path, so it is **named on every row as a gap** rather than half-done.

*Also found by the guard, and not Phase 3's:* `lib/services/payrollTdsEstimate.ts`
computes §192 salary TDS in the browser. Its own docstring already declares it a
standing CLAUDE.md violation tracked as **roadmap R2.10**, so it is allowlisted
with that reference rather than absorbed here.

**Two more unguarded direct writes the corrected scan found, now closed.**
Widening the guard from a 400-character window to the whole statement did not
only surface the four TDS tables — it also found `loans` and `fixed_deposits`,
inserted straight from `app/accounting/loans/page.tsx`. Both carried firm and
assignment rules and **no role rule**, so a Reviewer assigned to a client could
record or amend that client's borrowings: principal, outstanding balance,
interest rate, EMI — figures the cash-flow report and the risk screen read.
Neither table has an API endpoint, so there was no `rbac()` tier to mirror and
they sat in `AWAITING_DECISION` until the owner answered on 2026-09-09:
**Executive+ for insert, update and delete alike**, on the reasoning that a
client handed to an Executive is theirs to run. Migration 346 writes that rule.
The delete tier is deliberately not raised a rank — an Executive who cannot undo
their own typo without a Manager is a rule that gets worked around.

*Named follow-up, not done here:* because these are browser writes, a delete
still leaves **no `audit_log` row** — `log_event` runs only on the API path. The
role rule stops a Reviewer; it cannot record what a legitimate Executive
removed. Closing that means giving the pair a real endpoint, the way the TDS
register got one in this phase. It is a Phase 7 shape (a screen for an engine),
not a Phase 3 one.

**TDS-03 was four breaks, and the fourth was invisible to 10,000 tests.**
`POST /returns` never supplied `tds_returns.quarter_end` — `DATE NOT NULL`, no
default, migration 037 — so the insert raised on any real database while every
mock-mode test passed, because a dict store has no NOT NULL. The other three:
`compute26Q`/`compute24Q` sent no `Authorization` header at all; the register
never wrote `financial_year`; and it wrote `quarter` as the compound
`"Q3 2025-26"` while every reader filtered `.eq("quarter","Q3")` — the format
migration 014 gave this one column, where `tds_returns`, `tds_challans` and
`tds_certificates` have always held the year separately and CHECKed
`quarter IN ('Q1'..'Q4')`. Migration 347 puts the register on the schema's own
vocabulary. A fifth, found on the way: `getTDSChallans` filtered the quarter and
not the year, so a Q3 return reconciled against every Q3 the client had ever
deposited.

**The missing Authorization header was 11 call sites, not 2.** Sweeping the
tree for the pattern rather than the finding: 11 of 36 `fetch` calls to this
backend carried no Bearer token, and every one reaches an `rbac()`-guarded
route that answers 401 without one. Seven of them are the WHOLE of
`app/clients/[id]/fixed-assets/page.tsx`, each sending `credentials: "include"`
— a cookie this API does not read, which is what made it look like an auth
decision had been taken. Also `documents.parse` (so document parsing had never
worked once) and the HRA calculator. All 11 fixed;
`apps/web/scripts/every-api-call-is-authenticated.test.ts` states the rule, with
`app/sign/page.tsx`'s tokenised public endpoints as the named exception.

**TDS-15 and TDS-04 are the same defect in two directions**, and both were live:
a screen writing a value the CHECK forbids (`"Form 16A"` where migration 037
accepts `'16A'`, so every certificate draft was rejected and the refusal was
swallowed into an HTTP 200 nobody read), and a screen comparing against values
the CHECK cannot store (`"Pending"|"Filed"|"Overdue"` on `tds_returns`, so three
counters read 0/0/0 for ever). The /tds Challans tab additionally had no writer
and no reader at all — the modal pushed a row into React state and
`POST /api/tds-workspace/challans` had no caller.

**TDS-14 — the bill editor's TDS is now the server's answer, not the browser's.**
The editor showed `estimateForeignTds(base, vendor.tds_rate_bps)` and subtracted
it as "Net payable", while the save branches on RESIDENCY first and then applies
the section threshold, the year's AGGREGATE and the §206AA floor — or §195 by
nature of income with surcharge and cess, or a refusal. So a sub-threshold §194J
bill previewed tax and saved zero, and a §194C individual previewed the company
rate. `POST /api/purchase-bills/tds-preview` runs the save's own code path
(`_compute_bill_lines_and_totals`, reached through the same vendor and currency
resolvers, which were extracted for it), and the editor renders its figure, its
reason, and its refusal. `estimateForeignTds` and `convertBaseToForeignMinor`
are DELETED with their tests, not merely uncalled — a rate × base helper left in
the tree is one import away from being the preview again.

**PUR-14 — five gap codes computed on every foreign-supplier bill since the
register was written, and none of them had ever reached a screen.** The receive
response has always carried `tds_register.gap_details`; the purchases page read
`result.success` and nothing else. Both receive paths now capture them, and a
bulk receive deduplicates by vendor and sentence. A failed register sync is the
loudest case: `_sync_tds_register` deliberately never raises, so a bill can be
in the books and missing from 26Q — which is exactly why it has to be said on
the screen instead.

⚠️ **The status-vocabulary check found ELEVEN more files, and they are not
Phase 3's.** `tests/test_frontend_status_values_match_the_check_pg.py` carries
them as a shrinking ratchet with the values each uses. They belong to their own
modules' phases — GST (5), MCA (7), sales, payroll, lifecycle — and fixing them
inside the TDS phase is the scope creep this plan exists to prevent. **One is
confirmed real rather than a heuristic's guess and should be picked up early:**
`app/mca/page.tsx` UPDATEs `mca_filings` with `status: "Filed"` where the CHECK
accepts `'filed'`, so marking an ROC filing as filed is rejected by the
database and does nothing.

### Phase 4 — TDS statutory correctness · 9 findings (8 distinct) · ≤60 days · **4a–4d DONE, 4e–4h DEFERRED**
`TDS-07 TDS-22 TDS-26 PUR-03 TDS-06 PUR-10 TDS-09 PUR-07≡TDS-13`

§194IA unknown to the engine but offered in the dropdown; §194J's 2% technical
rate and §194I's 2% plant rate unmodelled; §195 picking the wrong surcharge
ladder; surcharge and cess added on top of a DTAA rate; every 26Q deductee row
stamped with the first challan found; no TDS on a vendor payment; no 27Q; no
§197 certificate.

*Shape:* identical to the §194 aggregate-limb work already done — a rule in
`section_rates.py`, a branch in `resolve_tds`, a test per section.
*Guard:* the section registry test, extended.
*Runs after Phase 3 deliberately:* fixing the engine while a browser copy still
overrides it fixes nothing a CA can see.

**SPLIT, 2026-09-09 — an owner decision, and the reason is that the eight are
not one shape.** Four are the ENGINE being wrong on a payment it already
computes: a wrong answer reaches a CA today. The other four are things the
software does not do at all, each a screen, a table or a file format, and none
of them is smaller for being done beside the first four. Grouping by fix shape
is what this plan is for, so:

| | Findings | What it is | State |
|---|---|---|---|
| **4a–4d** | TDS-07, PUR-03, TDS-26, TDS-22 | the engine's four wrong answers | **DONE** |
| **4e–4h** | PUR-10, TDS-06, TDS-09, PUR-07≡TDS-13 | four new builds — TDS on a vendor payment, challan→deduction mapping, the 27Q builder, §197 certificates | **deferred to a later phase, not started** |

What landed, and the one thing each turned on:

- **4a (TDS-07)** — a section the engine cannot answer for is REFUSED where it
  is recorded, on the vendor, not discovered on the bill. The dangerous case
  was not the §194IA 422 the finding named: recording §192 on a vendor made the
  engine withhold NIL in silence, because salary is not in the purchase-bill
  registry at all.
- **4b (PUR-03)** — a DTAA rate is a CEILING on the whole tax, not a base to
  add surcharge and cess to. §90(2) compares finished totals. Owner decision:
  ₹10,00,000 on a ₹1 crore royalty at a 10% treaty rate, not ₹11,44,000.
- **4c (TDS-26)** — a boolean is not a classification. Part II of the First
  Schedule gives a different surcharge ladder to a foreign company, an
  individual/HUF, a firm/LLP, an AOP/BOI and a co-operative; the engine had
  `is_company`, fed by the PAN's 4th character, so a foreign firm, an AOP and
  every payee with NO PAN got the foreign-company ladder and UNDER-deducted —
  which disallows the whole expenditure under §40(a)(i). Migration 348 records
  the class; two ladders that are not held are refused rather than guessed.
- **4d (TDS-22)** — §194I and §194J each charge two limbs at two rates and the
  registry holds one. Shipped as a NAMED GAP, not a rate: the two concessional
  figures are not held anywhere verified — this repository stated §194-I(a) as
  2% in one file and 5% in another — and a split registry key would have put an
  unconfirmable clause code on a 26Q deductee row, which is worse than the
  over-deduction it would fix. The withholding stays at the higher rate, which
  over-deducts recoverably, and the bill says so.

**Why 4e–4h are deferred rather than dropped.** Each is a real gap and PUR-10
is the one a CA meets soonest — a vendor payment outside the purchase-bill path
withholds nothing. But they are builds, and this plan's own rule is that a
phase teaches one pattern and ends with one guard test. Four screens and a file
format do not share a pattern with four engine corrections. They are carried
forward whole, with their findings and their severities unchanged.

### Phase 5 — A GSTR-1 the portal accepts · 8 findings · ≤24 days · **DONE**
`GST-07 GST-08 SALES-06 SALES-10 SALES-09 GST-16 SALES-03 GST-12`

Deemed exports filed as physical; a blended B2CS rate that does not exist; seven
states and UTs unselectable; shipping bill and port hardcoded; Table 11A/11B
unreachable; the validator never running on the path a CA uses; the Add Filing
modal throwing on every save; the invoice PDF always saying "reverse charge: No".

*Shape:* one payload builder, one validator, and the validator actually wired to
the path in use.
*Guard:* the validator runs on the CA's path, not only on the test's.

**Shipped as 5a–5f. Rescored first, and one finding had moved:** SALES-03 was
half fixed already — the reverse-charge line was conditional and the place of
supply printed — so only its IRN/QR half remained. Four of the others turned
out wider than written.

| | Findings | What it was |
|---|---|---|
| **5a** | GST-12, SALES-06 | the Add Filing modal threw a RangeError on EVERY save (the option's `value` and `label` were one string and two readers parsed it differently). Two more defects sat in the same three lines: the month end was read back through UTC (every period ended a day early in IST) and GSTR-9's due date read the CALENDAR year off the period, so January–March showed a date a year late. The browser's `getDueDate` is deleted — `GET /api/compliance/due-dates/calculate` existed all along with `api.compliance.calculateDueDates` already in `lib/api` and NO CALLER, the same shape Phase 3 deleted for TDS |
| **5b** | GST-08 | Table 7 declared blended rates that do not exist in the tariff — 11.5% for a 5%+18% invoice, 13.26% for four rates. The tax TOTAL was always right, which is why it survived |
| **5c** | GST-16 | the validator ran on two endpoints no screen calls. **GSTR-3B had the identical hole** and is fixed too. `lib/data/gst.ts` also marked every return `"validated"` unconditionally |
| **5d** | GST-07, SALES-10 | SEZ supplies and deemed exports were filed in Table 6A, **which has no `ctin`** — so the recipient's GSTIN, the thing their refund claim matches on, was dropped. They belong in 6B/6C inside `b2b`. `inv_typ` was emitting this application's own strings. An export made ON PAYMENT of IGST was filed as WOPAY. Migration 349 adds the shipping-bill columns, which nothing anywhere had |
| **5e** | SALES-09 | four columns migration 286 added, that `gst_advance_service` has read ever since and **nothing has ever written** — including the client flag that gates the whole table, which had no model field, no endpoint and no screen |
| **5f** | SALES-03 | Rule 46(r), the IRN and the IRP's signed QR. Printed only where `status == "generated"` AND an IRN exists; a simulated one is never rendered |

**Three things this phase found that were not in the audit:**

1. **A FIFTH Indian-state list** (`components/ClientFormModal.tsx`), on the
   CLIENT master where `state_code` drives CGST+SGST against IGST downstream. A
   client in Ladakh could not be onboarded. The guard found it on its first run.
2. **Fifty sites producing a calendar date from a UTC instant**, across thirty
   files — including the default date of the invoice editor, the purchase-bill
   editor and all four note editors. For anyone in IST between 00:00 and 05:30
   those defaulted to YESTERDAY, on a Rule 46(b) particular. `lib/dateMath.ts`
   already documented the fix and named the helper; two other modules said so
   too; nothing checked.
3. **A pre-existing hole in the frontend column checker.** `_skip_args` was
   quote-aware and not comment-aware, so an apostrophe in a comment inside a
   payload (`screen's job`) opened a string that never closed and the whole
   write went UNSCANNED — silently, which is the direction that matters. Fixed
   with `blank_comments()`; the write scan went from ~230 to 256 references.

**Four guard tests, each stating the RULE rather than a spelling of it** — no
calendar date cut out of a UTC instant, one state master, the due date comes
from the engine, a return with errors is not "validated".

### Phase 6 — You can correct a mistake · 5 findings · ≤17 days · **DONE**
`SALES-04 FA-10 ACC-09 PAY-12 BANK-06`

Deleting a middle draft credit note wedges that client's numbering permanently;
no way to edit, reverse or delete an asset; no screen to create or edit a
ledger; `PATCH /employees` silently discards `joining_date`; no undo for a
mis-imported statement.

*Shape:* an append-only correction path, the pattern migrations 266/275/276
already established for journals.

**Shipped as 6a–6d. Rescored first, and three of the five were wider than
written.**

| | Findings | What it was |
|---|---|---|
| **6a** | PAY-12 | `EmployeeUpdateIn` had no `joining_date`, and Pydantic ignores unknown keys, so the edit form's value was dropped in silence and a wrong joining date could never be corrected — it decides gratuity's five years (Payment of Gratuity Act s.4(1)), the EPS eligibility test and a leaver's pay. It was **one of eleven** create/update pairs, so the guard is a SCAN: every create-model field is on the update model or named in `IMMUTABLE_ON_UPDATE` with a reason. It found two more real drops — Form 15CA/15CB on a purchase bill, and `is_reverse_charge` editable on a sales invoice but not a purchase bill |
| **6b** | SALES-04 | **seven** copies of `count("exact") + 1`, not the three the audit recorded, plus six more in the mock branches. COUNT+1 is deterministic, so a deleted middle draft returns a taken number on every one of the retry's six attempts, for the rest of the FY. And a **second** bug found while scoping it: migration 210 created `sales_debit_notes` and `purchase_credit_notes` with a per-FIRM unique key while their routers number per CLIENT — exactly what 151 fixed for invoices and 159 for debit notes — so the firm's **second client could not raise either document at all**. Migration 350 |
| **6c** | FA-10, BANK-06 | an asset was final the moment it was saved (no PATCH, no DELETE, no way to unwind a month, and migration 245 revokes UPDATE/DELETE from `authenticated` so PostgREST could not help). Three tiers now: a rename writes, a corrected cost reverses and re-posts through the kernel at a revision reference, a revised life or rate is prospective. Plus a reverse-the-last-month endpoint, which is what makes the tier-B refusal actionable, and a soft delete. Migration 351. BANK-06's statement delete is HARD and takes the lines with it, because the import dedupes on `(client_id, import_hash)` and rows left behind would silently skip every line of the re-import |
| **6d** | ACC-09 | `parent_group`/`sub_group` have existed since migration 057 and only the CSV import ever wrote them, so Account Groups rendered one "Ungrouped → General" block for any normally-seeded firm. `createAccount`/`updateAccount` existed in `lib/api` with no caller anywhere. Both now write the groups; `parent_id` becomes editable and its "this is a gap, not a decision" entry in `IMMUTABLE_ON_UPDATE` is deleted |

**What Phase 6 confirmed about the method.** The rescore paid for itself for the
third phase running: 5 findings were 5 findings, but three of them had a second
defect inside that nobody had written down, and the numbering one was a launch
blocker on two document types. And the guard lesson repeated in a new place —
`test_accounts_endpoint_is_the_tenants_own.py` pinned the literal sentence
"name, code and is_active", so growing the update model broke a test that was
asserting a SPELLING. It now asserts the PROPERTY: the refusal lists whatever
`AccountUpdateIn` actually carries.

### Phase 7 — Screens for engines that already work · 12 findings · ≤78 days
`IT-13 IT-16 IT-17 IT-05 IT-10 IT-18 PAY-11 PAY-29 GST-13 PUR-05 SALES-13 SALES-14`

§234A/§234B, the presumptive engine, ITR field placements, brought-forward
losses, seven payroll capabilities including the leaver settlement, GST
amendments and the ITC register, §17(5) blocked credit, invoice branding,
applying an advance receipt. **All computed, all tested, rendered by nothing.**

*Shape:* pure wiring — no new statutory logic, so the risk per day is the lowest
in the plan and the visible progress per day is the highest.
*Note:* `PUR-05` says in terms "Backend needs no change."

**DONE — 10 September 2026, in twelve commits (7a-7l).** 7a-7g merged as
PR #472 (`714c1c84`); 7h-7l follow in one PR.

"Pure wiring" was right about the shape and wrong about the yield. Rescoping
each finding against the code before building it changed what got built in six
of the twelve, and three real defects that no finding names were found on the
way:

| what the finding said | what the code said |
|---|---|
| GST-13: three endpoints unreachable | sixteen were; two of the three named were already wired |
| GST-13: give `gst_portal` a screen | it must NOT have one — only `ManualGSTProvider` exists, so it would report "not filed" for every filed return. Pinned by a test |
| SALES-13: pass branding through the shared PDF helpers | that undoes three earlier commits (invoice supplier, customer statement, payslip employer). Branding is threaded through the tax-invoice path only |
| IT-18: "invented figures" across document intelligence | every one is narrower than claimed except one line the finding does not mention — `detect_document_risks` invented the client's book income as 85% of the AIS figure and reported the difference as a risk |

Found and fixed while there, in no finding: the receipts screen's
"Unallocated" column ignored customer-deducted TDS, so a fully-paid §194J
receipt showed -₹2,000 for ever; `amount_in_words` raised IndexError above a
crore; and the AIS screen's own "Est. Tax Impact (30%)" was a rupee figure
computed from nothing the screen knew.

Two guards now state the RULE rather than a spelling of it — a finished payroll
endpoint and a finished GST endpoint must be reachable from `apps/web`, with
every exception REGISTERED and given a reason. The GST one carries nine.

7l is the only Phase 7 item that needed a migration (**352**, the AIS
reconciliation), and refreshing the production guards fixture it put over the
ten-migration ratchet is in the same PR — see `apps/api/tests/fixtures/README.md`.

### Phase 8 — Performance: the wire carries the answer · 4 findings · ≤10 days
`BANK-07 BANK-08 PAY-16 ACC-07`

The Bank Book ships every transaction to Python (`bank_register_service.py:212`
is an `index()` inside a loop); the upload endpoint is `async def` around
blocking rasterisation and twenty vision calls; both firm payroll screens load
every payslip the firm ever produced; the audit log shows 200 rows and cannot
show one entry's history.

*Shape:* one rule, already written down in CLAUDE.md and already applied to
cash-flow and the ageing schedules. Cheapest phase per finding in the plan.
*Guard:* make the existing rule testable.

**DONE — 10 September 2026, in four commits (8a–8d).**

| # | What it was | Measured |
|---|---|---|
| 8a BANK-07 | the Bank Book paged every transaction on the account and computed the register, the summary and the divergence in Python — with one QUADRATIC step | `min(filtered, key=all_lines.index)` **22.8s** of CPU on 12,836 rows (the audit measured 29.2s in production) against 0.069s to build the whole register. Migration 353's `public.bank_register` answers in **0.106s**, one call |
| 8b BANK-08 | three `async def` routes doing blocking work on the event loop | **eleven**, not three. Ten are now plain `def`; the webhook keeps the raw body it needs and hands its blocking half to the threadpool |
| 8c PAY-16 | both payroll screens loaded every payslip the firm ever produced | four tabs now fetch their own slice, one aggregates server-side, and `/api/payroll/slips` REFUSES a request that names no run, month or employee |
| 8d ACC-07 | the Rule 3(1) edit log capped at 200 rows firm-wide, filtered in the browser, with no per-entry history | every filter in the database, cursor paging, and a History panel on the journal entry |

Two things worth carrying forward. **The quadratic step was also unnecessary** —
`filtered` is a comprehension over `all_lines`, so `filtered[0]` is the same
row; the SQL move was the structural fix and the one-line fix was free beside
it. And **the column checker earned its keep**: 8c's first draft filtered
`payroll_runs` on a `financial_year` column that does not exist, and
`test_backend_columns_exist_pg.py` failed against the real schema before CI
ever saw it.

Two guards state a rule rather than a spelling: an `async def` route may not
await only the request body (`ALLOWED_ASYNC` is EMPTY, and that is the answer),
and a payslip read must name what it is about.


### Phase 9 — Banking import and a real BRS · 4 findings · ≤14 days
`BANK-01 BANK-09 BANK-04 BANK-05`

A statement printing a "Total" subtotal is refused with a message blaming the
CA; two genuinely identical transactions are silently merged; the "Bank
Reconciliation Statement" has no unpresented cheques or deposits in transit; and
"Adjustments" is an unexplained plug that can force a tie-out into a signed PDF.

**DONE — 10 September 2026, in four commits (9a–9d).**

| # | What it was | What it is |
|---|---|---|
| 9a BANK-09 | two identical transactions hashed the same and one was silently dropped, reported as `duplicates_skipped` — which means "already imported", a different statement about a different row | every row is kept. Re-import idempotency comes from an OCCURRENCE COUNT rather than an ordinal, so it survives an overlapping re-import; no migration needed, because migration 224's unique index only collides when both rows keep the same hash |
| 9b BANK-01 | `printed_totals` took the FIRST totals row, which on a multi-page statement is a page subtotal — and the import was then refused with a message blaming the CA's column mapping | the FILE has to say which row totals the statement: one row, or several with exactly one "Grand Total". Several with none is reported AMBIGUOUS and falls back to the typed balances. A genuine mismatch is now a stop rather than a wall — a written reason imports it, recorded beside the differences it excused (migration 354), never counted as verified |
| 9c BANK-05 | `adjustments_paise` was a bare integer on the generic PATCH: no reason, no audit row, nothing on the document, written by any Executive, and it satisfied the gate that freezes a certified PDF | one write path, Manager+ (`banking.approve`, which no router had ever referenced), a mandatory reason printed beside the figure, an audit row and a timeline warning, with migration 355's CHECKs holding the pairing in both directions |
| 9d BANK-04 | every row the reconciliation knew about was a STATEMENT line; nothing in the module read `journal_entries` or `journal_lines`, so an unpresented cheque had no row anywhere in the product | the two-sided statement, computed by `public.bank_reconciling_items` (migration 356) with `domain/banking/brs.py` as the mock-mode twin and 11 parity scenarios holding them identical. Frozen into the snapshot at completion, so the certified document does not move when next month is imported |

Three things worth carrying forward.

**The obvious fix for 9b was the wrong one.** The finding suggests picking
whichever candidate agrees with the parsed sums. That makes the check prove
itself — a misread statement would select the row that agreed with the
misreading — and the whole value of the printed totals is that they come from
outside the reading being checked. There is a guard test named after it.

**9b's rule already existed in prose on the other path.** `vision.TOTALS_PROMPT`
tells the model in as many words that "a page subtotal … is NOT it". The
deterministic parser had the same rule written nowhere and enforced nowhere.

**9c stopped short of the accounting answer on purpose.** Making an adjustment a
posted journal is what the finding calls "better still", and it is wrong until
9d exists: most of what is plugged there is a TIMING item, which belongs on the
book side of the BRS, not in the ledger. Now that 9d is built, what is left in
that field is genuinely journal-shaped — which is the condition for retiring it.

### Phase 10 — Depreciation, both books · 7 findings (6 distinct) · ≤62 days
`FA-02 FA-04 FA-05 IT-09≡FA-06 IT-06 IT-12`

Contains **the last open critical**. FA-02's default rate is right and the
stored rows are not; there is no backfill and no edit path. **Do this while
production still holds zero fixed assets** — after the first register is
migrated in it becomes a data migration as well as a code fix.

Then §32 block-of-assets (the IT-09/FA-06 duplicate), the missed-month catch-up,
the note that reports a theoretical charge, §234C for a presumptive assessee,
and the §44AB report due date.

**DONE — 10 September 2026, in seven commits (10a–10g).**

**FA-02, the critical, was already closed and is recorded here rather than
re-fixed.** Verified against the code: `_DEFAULT_WDV_RATES` is DERIVED from
Schedule II Part C's useful lives and every value matches the finding's own
corrected figures (Computers 63.16%, Office equipment 45.07%, Furniture 25.89%,
P&M 18.10%, Vehicles 31.23%, Buildings 4.87%); `Intangibles` and `Other` return
`None`, so `_compute_annual_depreciation` RAISES rather than charging a
made-up rate; the frontend's duplicate table is gone and the page reads the
classes off the backend; and a tier-C correction applies a revised rate
PROSPECTIVELY, which is what AS 10 / Ind AS 16 §51 requires of a change in
estimate. Production holds zero fixed assets, so 08b's "no backfill" is moot.

| # | What it was | What it is |
|---|---|---|
| 10a IT-12 | the Tax Audit Tracker headed itself `Due: 30 November` as a hardcoded string — wrong by two months against the REPORT and by one against the return | Explanation (ii) to §44AB makes the specified date one month before the §139(1) date: 30 September and 31 October. A stateless endpoint answers both, and the screen asks |
| 10b IT-06 | the §208 four-instalment schedule applied to every caller, so a §44AD/§44ADA assessee paying in full on 15 March — exactly as §211(1)'s proviso requires — was charged ₹4,050 of §234C interest | one flag, supplied and never inferred, selecting §234C(1)(b): one instalment, no tolerance. The SAVE path goes with it, because four stored instalments beside a one-instalment interest figure disagree on the same screen |
| 10c FA-04 | closing a year on a 200-asset register was 2,400 browser requests, one per asset per month | one server-side run over a range, through the SAME `_post_one_month` the single endpoint calls, chunked at 200 months because `lib/api` aborts at 45s, reporting per asset what it posted and where it stopped |
| 10d FA-05 | the fixed-assets note reported the THEORETICAL annual charge for every asset regardless of what was posted, dropped a sold asset out of gross block entirely, and had no additions or deductions columns | a Schedule III movement per class, with the charge read off the ledger via `account_period_balances` and any disagreement with the register STATED rather than absorbed |
| 10e IT-09≡FA-06 | §32 existed nowhere; `book_to_tax_bridge` said so in its own docstring and marked itself incomplete for every client | `domain/income_tax/section_32.py` — the block, the second proviso's 180 days on PUT TO USE with a derived cutoff, §43(6)(c)'s deduction order, and §50's two limbs |
| 10f | and the bridge was imported by no router at all | migration 357's block register, a service that derives additions and deletions from the fixed-asset register, and three endpoints. The bridge fetches its own §32 figure and still withholds the line while anything is outstanding |
| 10g | a CA could not enter an opening written-down value | `/income-tax/section-32`, leading with whether the figure is safe to use rather than with the total |

Four things worth carrying forward.

**A guard written for one screen found a defect on another.**
`a-statutory-due-date-is-never-a-literal.test.ts` states the rule — no screen
asserts a statutory due date of its own — and swept the whole of `apps/web`.
`app/calendar/page.tsx` builds FOURTEEN deadlines from browser literals, and two
have already drifted from `compliance_engine`: **AOC-4 shows 29 Oct against the
engine's 30 Oct, and MGT-7 shows 28 Nov against 29 Nov** (§137 is AGM + 30 days,
§92 is AGM + 60). Both one day early — the safe direction, and still wrong. It
also assumes a 30 September AGM for every company. **NOT FIXED**, and
allow-listed with that reason: routing all fourteen through the backend and
stating the AGM assumption where it is made is its own change, not a rider on a
commit about §44AB.

**A test caught a real bug in the §32 engine.** The first draft left a collapsed
block's balance in the closing written-down value, which would relieve the same
money twice — once as a §50 capital loss, then again as depreciation in every
year that followed.

**Refusing to hold a statutory table is sometimes the answer, not a gap.**
Appendix I has a dozen plant-and-machinery classes. But a block IS a rate under
§2(11), so the CA who decides which block an asset falls in has already decided
it — and a test asserts the engine holds no table at all, so there is nothing
there to be silently wrong.

**Paying a debt at the moment it starts to matter.** `post_depreciation` was on
the acknowledged list of paths that check the FY lock but not the CLIENT's. One
month behind a click a CA has just looked at is one thing; twelve months in one
call is another, so 10c paid it.

### Phase 11 — The remaining big builds · 15 + 4 findings · ≤168 days
`IT-11 IT-19 GST-10 GST-11 GST-20 PUR-15 ACC-06 ACC-10 SALES-11 INV-01 INV-06 PUR-09 SALES-05 PAY-09 PAY-14`
**+ the four deferred out of Phase 4:** `PUR-10 TDS-06 TDS-09 PUR-07≡TDS-13` —
TDS on a vendor payment, challan→deduction mapping, the 27Q builder, §197
certificates. They land here because they are builds, which is what this phase
is; they are NOT features, so the "which ones will a CA pay for" question below
does not reach them. PUR-10 is the one to take first — a vendor payment made
outside the purchase-bill path withholds nothing at all today.

#### 11a · PUR-10 — DONE. An advance to a contractor withholds
Migration 358, `services/vendor_tds.py`, both payment paths, the journal, the
register, and the payments screen.

§194 and §195 charge "at the time of credit ... or at the time of PAYMENT
thereof, whichever is EARLIER", and only the credit half existed: both resolvers
lived inside `routers/purchase_bills.py` as private functions, so the payment
path had no engine to call. A ₹5,00,000 mobilisation advance withheld ₹0 where
§194C charges ₹10,000, with §201(1A) interest from the payment date and a
§40(a)(ia) disallowance of 30% of the expenditure.

**The hard half was not the charge, it was not charging twice.** An advance and
the bill that later absorbs it are ONE sum credited-or-paid. Adding both to the
year's aggregate charges ₹10,00,000 on ₹5,00,000 and leaves Trade Payables with
a debit balance equal to the over-deduction. So a bill absorbs the outstanding
advance pool and records what it took in
`purchase_bills.tds_advance_adjusted_paise`; the pool is
`Σ payments.tds_base_paise − Σ bills.tds_advance_adjusted_paise`, needing no
matching table. Reversing an advance a bill already absorbed puts the sum back
into the aggregate rather than leaving it charged nowhere.

**Two things it deliberately does not do.** A payment in a FOREIGN currency does
not withhold — the vendor is credited in their own currency while the tax is
remitted in rupees, so the cash leg is not "amount − tax" — and says so as a
named gap (`foreign_advance_not_withheld`) rather than reporting a silent zero.
And an advance to a non-resident is REFUSED where §195 cannot resolve
chargeability, exactly as the bill path refuses, because under-deduction there
disallows the whole expenditure under §40(a)(i).

**One unrecorded defect found on the way.** `lib/purchases/registerNotes.ts`
typed `gap_details` as `string[]` while `describe_gaps` has always returned
`[{code, message}]`, so every statutory gap the register reported reached
`{n.text}` as an object — which React refuses to render. The screen PUR-14 built
to stop the silence crashed instead. Fixed, and pinned by a payload test rather
than another source scan.

#### 11b · TDS-06 + TDS-09 — DONE. The statement a deduction goes on, and the challan it sits under
`domain/tds/challan_mapping.py`, `tds_27q_from_books`, and no migration at all.

**TDS-06 was two wrong answers on one row.** The CIN came from
`next(c for c in challans if section matches)` — the FIRST challan for the
section, in an `.order("id")` order arbitrary with respect to time — and Rule
30(2) gives a quarter THREE monthly deposits all carrying the same section, so
every June deductee was stamped with April's BSR code. The FVU cross-checks a
deductee row against the challan it sits under, so the statement is rejected —
or accepted, and every one of those deductees' 26AS entries reads 'U'. The
salary mirror was blunter: `challans[0]`. Separately, the deposited column
apportioned the section's whole quarterly deposit by weight, so a bill fully
deposited on 7 May read as partly deposited whenever the QUARTER was short.

The fix is FIFO by date within a parent section, and it needs no new column.
**A first draft gave every challan a deduction MONTH** — Rule 30(2) makes one —
and it was wrong about the artefact: the RPU's challan row has no
deduction-month field, and one challan may legitimately carry a catch-up
covering two months. Forcing a month on it read a single 7 June challan paying
April and May as leaving April unpaid, which is a wrong return. The existing
apportionment test caught it.

**TDS-09 had everything except somewhere to file it.** §195 deductions were
computed, registered with country and TIN and surcharge and cess, excluded from
26Q by name, and given a calendar deadline — with no builder. `tds_27q_from_books`
reads the same posted books 26Q reads, split on RESIDENCY rather than on section
(§194E, §194LB/§194LC and §196D all charge non-residents too), and a NIL
remittance is a row with a reason rather than an absence.

**And it closed a hole 11a had just opened.** An advance withholds, posts to TDS
Payable and reaches the register — and `tds_26q_from_books` read only
`purchase_bills`, so the deduction was in the ledger, in the register, and off
the statement, with the reconciliation failing because the GL movement included
it. Both vendor returns now read both kinds of posted document.

#### 11c · PUR-07 ≡ TDS-13 — DONE. A certificate is a rate, a number, a period AND an amount
Migration 359, `domain/tds/lower_deduction.py`, and a screen.

A transport contractor produces a §197 certificate at 0.5% instead of 2% and
there was nowhere to record it: `vendors` had no certificate column of any kind
and `resolve_tds` took no certificate parameter, so a holder was always withheld
at the full rate. The CA's only options were to turn TDS off on the vendor —
losing the register row, the 26Q deductee line and the challan — or to accept
the over-deduction. `tds_deductions.is_lower_deduction` and
`.lower_deduction_cert` had existed since migration 037 with nothing ever
writing to them, so the FVU fields the certificate number is required in were
permanently blank.

**Half of TDS-13's evidence was already stale.** "captured, displayed and then
ignored" describes `vendors.tds_rate_bps`, which PUR-06 had already deleted from
the vendor form and the importer — precisely because §197(1) plus Rule 28AA(4)
make a certificate four facts and a bare percentage carries none of them.

**Three refusals.** §197(1) reaches a listed set of sections and §194Q is not
among them. §206AA(4) bars a certificate where the application has no PAN, so a
no-PAN vendor keeps the 20% floor. Two certificates in force in one year is
refused rather than resolved to the lower one.

**The ceiling is a ceiling.** Rule 28AA(4) issues a certificate for a specified
AMOUNT, so the year is charged at two rates — the certified slice at the
certificate's and the excess at the section's. Substituting the rate outright,
which is the obvious implementation, under-deducts by ₹15,000 on a ₹60,00,000
year against a ₹50,00,000 certificate, exactly where the AO stopped certifying.

**One over-deduction the tests caught while being written.** The certificate was
first selected by THIS DOCUMENT's date. Because §194 charges on the year's
AGGREGATE, a bill dated after the certificate expired recomputed the whole year
at the section rate and re-charged the earlier certified slice: ₹40,000 withheld
across a year where ₹25,000 was due, which the §200 credit cannot undo because
the cumulative it is subtracted from was already wrong. The certificate is now
selected by OVERLAP with the financial year, and `covers()` answers the separate
question of whether a given document sits inside it.

**The snapshot fixture was refreshed as part of this.**
`production_types.ADDED_AFTER_THE_SNAPSHOT` had reached nine migrations against
its own cap of eight — the cap doing exactly what it exists for. Refreshed
against production rather than widened: thirteen tables re-captured whole, and
the whole-schema md5 checked against the live database
(`032ab2c4faf8496eefc6ff2fae0148a1`, 4,081 columns in 274 tables).

#### 11d · PUR-09 + SALES-05 + PAY-09 — DONE. The number is already right; stop recomputing it

Three findings, one shape: a figure the server already computes correctly,
re-derived somewhere else and wrong there.

* **PUR-09** — the Rule 37 report read `total − paid − tds` and knew nothing
  about §34 notes, so a bill half settled by a purchase RETURN showed its gross
  value as unpaid and reversed the credit on it a SECOND time — the debit note's
  own journal has already credited GST Input. ₹18,000 reversed where ₹9,000 was
  due, the CA under-claims for the month, and the Rule 37(4) re-availment never
  fires because there was no payment to trigger it. **Both sides of the
  proportion move**: the credit still availed AND the current value of the
  supply. Netting only the amount is worse than netting neither.
* **SALES-05** — the Sales screen's Outstanding tile summed GROSS invoice
  totals. `paid_paise` was fetched and not subtracted; `credited_paise` was not
  even selected. ₹10,00,000 billed with ₹8,00,000 collected and ₹50,000 credited
  read as ₹10,00,000 owing. `outstanding_paise` is a generated column (migration
  278) and one resolver now serves all five call sites. The tile is also
  period-scoped, so it says **"Outstanding This FY"** like its neighbours rather
  than implying a receivable balance.
* **PAY-09** — the CTC report re-derived employer PF as 12% of BASIC and ESI
  from a current-month ceiling test, in a CSV the CA hands to the client: the
  four exact drifts `app/payroll/statutory/page.tsx` was rewritten to remove,
  reappearing one screen over. ₹1,200 shown where the stored slip says ₹1,800 +
  ₹75 EDLI + ₹75 admin — about ₹9,000 a year per employee, for an employee with
  no DA at all.

  **And the honest half:** the PF admin charge is floored at ₹500 per
  ESTABLISHMENT, applied to the RUN, so a sum of member shares under-states it.
  The table shows each employee's own share — which is their cost — and says so
  where it totals them, pointing at the Statutory summary for the remittable
  figure. A guard asserts both halves.

#### 11e · INV-06 + PAY-14 — DONE. A figure the books hold that the return never saw

* **INV-06** — a stock write-off reverses ITC in the GL, citing §17(5)(h), and
  GSTR-3B Table 4(B)(1) got nothing: `itc_reversal_register`'s CHECK refused
  every permanent ground, on the reasoning that a permanent reversal "is derived
  from the documents". True of a cancelled purchase; not true of a write-off,
  which has no document — the supply happened and the goods were destroyed.
  Migration 362 widens the CHECK to the five permanent grounds and makes
  `reclaimable` a GENERATED column, because whether credit can come back is a
  property of the ground and not a decision. A reclaim against a permanent
  parent is refused by the service AND by a trigger.
* **PAY-14** — a leaver's §192 deduction was on the challan and off Form 24Q.
  The quarterly Annexure I was assembled from `payroll_runs` alone while the
  annual Annexure II reads `payroll_settlements`, so the two disagreed by
  exactly the settlement TDS — which TRACES reads as a short-deduction default,
  and the employee gets no 26AS credit until Q4. The settlement is appended as a
  SLIP-SHAPED row into the same month bucket, so it goes through the identical
  PAN, §206AA and challan gates rather than a second assembly path.

Also carried: the guards fixture refresh, because
`test_the_in_flight_exclusion_cannot_excuse_everything` refused to run eleven
migrations behind its cap of ten. Re-captured and proved by reproducing
production's own checksum; **280 insertions, zero deletions** — nothing had
drifted, the fixture was just short of what 352–361 added.

#### 11f · INV-01 — DONE. What the stock was worth on a date, and a balance column that foots

Two halves of one finding, and the second is the one that is easy to miss.

* **There was no closing-stock-as-at-a-date figure anywhere.** `list_stock_items`
  takes no date; nothing computed one. So at year end the CA could not produce
  the stock statement that ties to the Inventories line, or the quantitative-
  details working paper. Migration 363's `public.stock_position_as_at` sums the
  ledger's **deltas** — one row per item, per the reporting rule — with
  `domain/reporting/stock_position.py` as its mock-mode twin and
  `tests/test_stock_position_parity_pg.py` holding the two identical.
* **The drill-down's Balance column did not add up.** The running totals are
  chained in INSERTION order — deliberately, so a bill received late does not
  fall out of the chain — while the ledger is DISPLAYED in date order, and the
  screen rendered the stored columns beside it. With a 1 July bill entered after
  a 10 July sale it showed "+20 → balance 110" above "−10 → balance 90". Neither
  row foots and a CA reconciling stock cannot tell why. Migration 250 had
  already rebuilt those totals in display order, which is not the order new
  movements chain in, so the two have been disagreeing about the current
  position as well.

**Why the deltas and never the running totals**: addition commutes, so
Σ delta over `movement_date <= D` is the same whatever order the rows went in —
and it is the RIGHT number, because the inventory journal posts exactly
`value_delta_paise` at exactly `movement_date`. The statement ties to the
Inventory control account by construction. Over an item's whole history it also
equals the stored running total, because `_compute_stock_out` force-closes so
that "the deltas always sum to the running value"; a test pins that invariant.

The chain itself is untouched — it is load-bearing — and the derived figures go
in NEW response keys (`balance_qty_units`, `balance_value_paise`) rather than
relabelling what the database holds.

#### 11g · SALES-11 — DONE. A discount on the invoice, and §15(3)(a) applied to it

There was no discount concept anywhere on the sales-invoice path — no Pydantic
field, no column, no editor control — and the taxable value was `qty x rate`
with nothing subtracted. A trading client giving a 5% trade discount could only
have it netted into the rate by hand, which loses the disclosure the customer's
copy shows, makes the invoice un-reconcilable to the price list, and forfeits
the relief, which §15(3)(a) makes conditional on the discount being **recorded
in the invoice**.

**§15(3)(b) is a different remedy and is deliberately out of reach.** A discount
given AFTER the supply is excluded only where it was agreed at or before the
supply, is linked to the invoices, and the recipient has REVERSED the
attributable ITC — that is the §34 credit note, not a field on one. So
`SalesInvoiceLineIn` carries the discount and the shared `InvoiceLineIn` the
note routes use does not, and a PG test asserts no note table grew a discount
column.

**The design decisions worth keeping:**

* the AMOUNT is stored and the PERCENTAGE is only a disclosure — a percentage of
  an integer paise amount does not generally land on an integer, so recomputing
  it at read time would give a different number from the one taxed;
* the GROSS is not stored: it is `taxable + discount` by construction, so a
  third column could only disagree with the other two;
* a document-level discount is allocated PRO-RATA across the lines before tax,
  because GST is charged per line at the line's own rate — 5% off a bill of 18%
  goods and 5% services is not 5% off one number;
* LINE first, then DOCUMENT on what is left: taking both off the gross would
  compound two reliefs the customer was quoted as one;
* every rounding FLOORS (a larger discount is less tax, so flooring cannot
  under-declare) and the split uses LARGEST REMAINDER so the parts sum to the
  whole — a pro-rata split that loses a paise makes the invoice total differ
  from the figure the customer was quoted;
* a discount larger than the line is REFUSED, not capped, on the table
  (migration 364), in the service, and in the preview.

`shared/gst-parity-vectors.json` grew twelve discount documents pinning the
browser mirror to the Python, and the PDF's summary block was extracted into
`summary_lines()` so "is the discount on the document" — which is the statutory
test — finally has an answer a test can give.

---

Left in Phase 11, all features rather than defects:

Form 3CD, §54 reinvestment exemptions, GSTR-9, QRMP, multi-GSTIN, the MSME
§43B(h) tracker, recurring journals out of `localStorage`, Schedule III mapping
that changes something.

### Phase 12 — The 158 mediums and lows · ≤699 days, and that is the loosest number here

They ride along with their phase: a TDS medium is cheap once Phase 3 has
deleted the browser copy, a GST medium is cheap once Phase 5 owns the payload.
**68 of the 158 are "hours"-sized.** Nothing here is a reason to delay a sale.

#### 12a — one definition of "closed", and the two kinds of it · ACC-21, ACC-27, ACC-12 · **DONE**

Three accounting-core findings that turned out to be one subject.

* **ACC-21** — `post_journal_atomic` validated the ENTRY's firm and client and
  then inserted the LINES with no check at all; `journal_lines.account_id` had
  one global FK to `chart_of_accounts(id)`, so every account id in the database
  satisfied it. Migration 360 puts the rule on the TABLE — a statement-level
  trigger with a transition table, so it costs one anti-join whatever the row
  count, and a writer that is not one of the two functions the finding named
  gets the rule anyway. Measured against production first: 33,080 lines, 0 that
  the rule would refuse.
* **ACC-27** — an `entry_date` the kernel could not parse made the kernel SKIP
  the year lock. Reachable, because the firm-level check parses with
  `strptime("%Y-%m-%d")` and the kernel with `date.fromisoformat`, so
  `"2025-4-1"` passed one, failed the other, and posted into a closed client
  year. Now refused at the Pydantic boundary and, unconditionally, in the
  kernel.
* **ACC-12** — the headline. Migration 361 folds all three reasons behind one
  definition, and **splits them by kind rather than by caller**, which is the
  part the finding's own suggested fix flags and is easy to get wrong:

  | | what it is | who asks |
  |---|---|---|
  | `period_closure_reason` | the firm locked the year, or this client's year-end is finalised — deliberate acts, reopenable | the posting **kernel**, so nothing reaches the ledger without it |
  | `period_lock_reason` | those two, then a return covering the date has been filed | wherever a document that **feeds a return** is written — invoices, bills, credit and debit notes, and now the manual journal |

  Putting the filed-return branch in the kernel is the obvious reading of the
  finding and would have frozen the practice: GSTR-1 for June is filed on 11
  July and GSTR-3B on the 20th, while June's bank reconciliation happens after
  both, every month, for every client. From the 11th no June receipt, payment,
  bank entry, depreciation charge or payroll accrual could be recorded — and it
  would have overturned, silently, the argued decision in `receipt_service.py`
  that a receipt is deliberately not locked by a filed return.

  The second function CALLS the first rather than restating it, in SQL and in
  the Python twin alike, and
  `tests/test_period_lock_reason_parity_pg.py` runs every scenario through all
  four and asserts they agree.

**The guard:** `test_every_dated_posting_path_asserts_the_client_lock.py`
already existed and its debt list shrank by one (`manual_journal_service.create`).
Its header now records what the list means since 361 — every path on it gets
the closures from the kernel, and what it is still missing is the filed-return
branch, which matters only where the fact written could change what the return
said.

#### 12b — a report is scoped, and a window that has shut says so · ACC-17, GST-09 · **DONE**

* **ACC-17** — the seven reporting endpoints treat an omitted `client_id` as
  "all clients", and `_FIRMWIDE_ROLES` is `{Role.PARTNER}`, so an Executive or
  a Manager assigned to three clients got the consolidated trial balance, P&L,
  balance sheet, Schedule III and cash flow of the whole practice. Not a
  hand-made request either: `/accounting/schedule-iii` offers "All Clients" as
  an ordinary control. The scope now lives **on the ledger source**, built per
  request from `effective_client_ids`, rather than threaded through nine report
  methods — a source cannot be asked an unscoped question, and a fetch added
  later inherits the rule. The router's own "Recorded, not fixed" comment is
  gone.
* **GST-09** — `correction_window_closes` has always implemented "30 November
  **or the annual return, whichever is earlier**", and no production caller ever
  supplied the date, so every window reported the outer limit. The GSTR-9 date
  is now resolved from `gstr1_returns`, and **two things the obvious fix gets
  wrong** are pinned by tests: it is one date **per financial year** (the source
  periods of one call straddle years, and a single date shortens the wrong one),
  and it is an **IST** date (`submitted_at` is UTC on disk; 20:00 UTC on 30
  November is 1 December in India, and the two readings fall on opposite sides
  of the cutoff). The filing demo's own copy of the question was wired the same
  way, through the same function.

**Still open in Phase 12**: the remaining mediums and lows, and
`/api/copilot/intelligence/*`, which is the one place still aggregating
firm-wide for an assignment-scoped caller.

---

## Totals, and how much to believe them

| | findings | ceiling |
|---|--:|--:|
| Phases 0–10 (every critical and high) | 81 + 7 | ~253 person-days |
| Phase 11 (features) | 15 | ~168 |
| Phase 12 (medium + low) | 158 | ~699 |

**Read the first row and discount it.** 253 person-days is the sum of
independent per-finding estimates for work that is deliberately batched, and two
of the pairs are literally the same change written twice. The measured
compression on the themed highs was 5.1 findings per change. **Phases 0–10 are
realistically 120–160 person-days** — call it six to eight months of one
engineer, or a good deal less at the rate the last five steps went.

## The rule this plan is built to obey

Every phase ends with a guard test, and the guard states **the rule, not a
spelling of it**. That is the single most expensive lesson of this engagement:
the money-parser guard was written, passed, and let nine defects through — twice
— because it named `parseFloat`, `Math.round(parseFloat` and `parseFloat(…)*100`
instead of "nothing whose name ends in `_paise` may be built by a coercion."

A phase that closes its findings and ships no guard has not finished; it has
bought time.
