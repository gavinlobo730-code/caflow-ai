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

### Phase 4 — TDS statutory correctness · 9 findings (8 distinct) · ≤60 days
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

### Phase 5 — A GSTR-1 the portal accepts · 8 findings · ≤24 days
`GST-07 GST-08 SALES-06 SALES-10 SALES-09 GST-16 SALES-03 GST-12`

Deemed exports filed as physical; a blended B2CS rate that does not exist; seven
states and UTs unselectable; shipping bill and port hardcoded; Table 11A/11B
unreachable; the validator never running on the path a CA uses; the Add Filing
modal throwing on every save; the invoice PDF always saying "reverse charge: No".

*Shape:* one payload builder, one validator, and the validator actually wired to
the path in use.
*Guard:* the validator runs on the CA's path, not only on the test's.

### Phase 6 — You can correct a mistake · 5 findings · ≤17 days
`SALES-04 FA-10 ACC-09 PAY-12 BANK-06`

Deleting a middle draft credit note wedges that client's numbering permanently;
no way to edit, reverse or delete an asset; no screen to create or edit a
ledger; `PATCH /employees` silently discards `joining_date`; no undo for a
mis-imported statement.

*Shape:* an append-only correction path, the pattern migrations 266/275/276
already established for journals.

### Phase 7 — Screens for engines that already work · 12 findings · ≤78 days
`IT-13 IT-16 IT-17 IT-05 IT-10 IT-18 PAY-11 PAY-29 GST-13 PUR-05 SALES-13 SALES-14`

§234A/§234B, the presumptive engine, ITR field placements, brought-forward
losses, seven payroll capabilities including the leaver settlement, GST
amendments and the ITC register, §17(5) blocked credit, invoice branding,
applying an advance receipt. **All computed, all tested, rendered by nothing.**

*Shape:* pure wiring — no new statutory logic, so the risk per day is the lowest
in the plan and the visible progress per day is the highest.
*Note:* `PUR-05` says in terms "Backend needs no change."

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

### Phase 9 — Banking import and a real BRS · 4 findings · ≤14 days
`BANK-01 BANK-09 BANK-04 BANK-05`

A statement printing a "Total" subtotal is refused with a message blaming the
CA; two genuinely identical transactions are silently merged; the "Bank
Reconciliation Statement" has no unpresented cheques or deposits in transit; and
"Adjustments" is an unexplained plug that can force a tie-out into a signed PDF.

### Phase 10 — Depreciation, both books · 7 findings (6 distinct) · ≤62 days
`FA-02 FA-04 FA-05 IT-09≡FA-06 IT-06 IT-12`

Contains **the last open critical**. FA-02's default rate is right and the
stored rows are not; there is no backfill and no edit path. **Do this while
production still holds zero fixed assets** — after the first register is
migrated in it becomes a data migration as well as a code fix.

Then §32 block-of-assets (the IT-09/FA-06 duplicate), the missed-month catch-up,
the note that reports a theoretical charge, §234C for a presumptive assessee,
and the §44AB report due date.

### Phase 11 — The remaining big builds · 15 findings · ≤168 days
`IT-11 IT-19 GST-10 GST-11 GST-20 PUR-15 ACC-06 ACC-10 SALES-11 INV-01 INV-06 PUR-09 SALES-05 PAY-09 PAY-14`

Form 3CD, §54 reinvestment exemptions, GSTR-9, QRMP, multi-GSTIN, the MSME
§43B(h) tracker, recurring journals out of `localStorage`, Schedule III mapping
that changes something, invoice discounts, closing stock as at a date.

These are **features, not defects** — a different kind of decision, and the
right place to ask which ones a CA will actually pay for rather than building
all fifteen.

### Phase 12 — The 158 mediums and lows · ≤699 days, and that is the loosest number here

They ride along with their phase: a TDS medium is cheap once Phase 3 has
deleted the browser copy, a GST medium is cheap once Phase 5 owns the payload.
**68 of the 158 are "hours"-sized.** Nothing here is a reason to delay a sale.

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
