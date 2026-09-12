# The probe pass — 12 September 2026

Sixty-five findings from `2026-09-07-findings/` re-read against `99ac94b5` by four
read-only agents, one per subsystem. This is a **second** verification pass on top of
`2026-09-11-the-verification-pass.md`, and it exists because that pass re-scored
findings without asking a question this one asks of every single item: **is the
finding's own suggested FIX sound?**

That turned out to matter more than staleness. A stale finding costs an hour of
re-reading. A finding whose suggested fix is wrong costs a regression, and two of
them here would have broken something that currently works.

Each subsystem file carries, per finding: `VERDICT / EVIDENCE / PREMISE / SHAPE /
SIZE`, with file:line for every claim.

| File | Findings | Closed | Notes |
|---|---|---|---|
| `banking.md` | 15 | 0 | none stale; two premises materially wrong |
| `accounting-and-inventory.md` | 16 | 0 (3 partial) | two findings have a **false fix** |
| `gst.md` | 16 | 1 (4 partial) | ~25% stale, one escalation |
| `purchases.md` | 18 | 4 | 22% stale; four new cross-subsystem duplicates |
| `sales.md` | 32 | 19 (5 partial) | two fixes must NOT be applied as written; two defects with no finding |
| `tds.md` | 32 | 14 (1 partial) | every critical on the compute path closed; four defects with no finding |
| `income-tax.md` | 34 | 13 (9 partial) | 64% has moved; three defects with no finding |
| `payroll.md` | 30 | 16 (2 partial) | 48% of the recorded backlog has moved; **three defects with no finding, one live** |
| `fixed-assets.md` | 20 | 10 (6 partial) | 50% stale; five defects with no finding |

The first four files were written on 12 September against `99ac94b5`; the last
five later the same day against `92392e2c`, with the same brief plus one
addition — "is the finding's own suggested FIX sound?" turned out to matter in
every slice, so it is asked of all of them.

## 1. The two false fixes — do NOT implement these as written

**ACC-23** says: "make the Balance Sheet stop synthesising the retained-earnings line
once a closing entry exists for the year — otherwise it would double count." It would
not double count. `year_end_financial_service.py:634-645` explains why and
`tests/test_year_end_financial_service.py:614-647`
(`test_a_manually_posted_closing_entry_is_not_double_counted`) pins it: deriving is
self-correcting, because the close reduces cumulative PAT by P at the same moment it
credits equity by P. **Implementing the "stop synthesising" half is what would break
the balance sheet.** Two further limbs of ACC-23 are also false — the Schedule III
reserves split already exists, and appropriations are postable today as manual
journals. The real residue is one line of UI: render `closing_entry_dates`, which is
already computed and already typed. **Do not touch `builders.py`.**

**ACC-25** says: attach files to a manual journal by uploading to the Documents bucket
and sending `[{name, url}]`. That payload is the exact failure
`domain/banking/attachments.py:23-34` was written to refuse — the bucket hands back a
**signed URL that expires in an hour**, so the attachment is a dead link by the time
anyone audits the entry, and `journal_entries.attachments` has no validation at any
layer (`models/accounting.py:277` is a bare `list[dict]`; `migrations/138` adds plain
jsonb with no CHECK), so a `javascript:`/`data:` URL is stored XSS. The working shape
is `{name, document_id}` — `apps/web/components/banking/EntryDetailModal.tsx:124`.
Reuse the banking validators; they are pure and module-agnostic.

## 2. Blockers the findings do not mention

**ACC-16** (`journal_lines.line_no`) — its suggested backfill is **refused outright**.
`migrations/251_restore_posted_journal_line_immutability.sql:105-109` puts
`trg_prevent_posted_journal_line_update` `BEFORE UPDATE OR DELETE` on `journal_lines`,
raising on any row whose parent is posted. A backfill UPDATE therefore fails for every
posted line in the database. 251's own header names the only legitimate route: a
migration that deliberately disables the trigger — "a rare, reviewable act". So the
shape is: add the column with a default (catalog-only in PG11+, no trigger fires),
DISABLE TRIGGER, backfill by `id`, re-enable, then `NOT NULL`.

**BANK-10** — the fix wants to band on "outstanding". `_banded`
(`bank_matching_service.py:220-231`) builds a PostgREST filter on **one named column**,
and outstanding is not a column on either table. Either add a generated column
(migration on `client_sales_invoices` and `purchase_bills`) or filter in Python — but
the Python route breaks `_pool_limit`, because the DB applies the cap before the Python
filter runs.

**PUR-22** — building the multi-bill payment UI as "create, then PATCH /allocate" is
**not** equivalent to creating an allocated payment. `purchase_payments.py:447` sets
`unallocated_paise = amount_paise` when there is no `purchase_bill_id`, which fires the
§194 advance-withholding branch and deducts tax on the whole payment. A later
allocation does not undo it, so one NEFT against many bills would withhold twice. Add
`allocations` to `PurchasePaymentIn` and route create through `create_payment_core`.

**PUR-20 / SALES-20** (cess) — the receive journal must still foot.
`tests/test_accounting_audit_fixes.py:71` asserts the trial balance balances. Adding
cess to the payable without a matching Dr GST Input (cess) leg breaks it, and neither
finding mentions the journal leg.

**INV-05** (freight into stock cost) — CLAUDE.md's own rule binds it: "Σ
`value_delta_paise` to a date is what ties to the Inventory control account." So
apportioned freight cannot just be added to `record_stock_in`'s total — the same amount
must flow into `post_inventory_receipt_journal_entry`'s `items[].value_paise` and be
credited to the freight account, or `stock_position_as_at` and
`check_missing_inventory_receipt_journals` both start reporting drift.

**BANK-29 / BANK-14** — both touch the statement row set that
`domain/banking/tie_out.py` walks. Dropping an opening-balance row changes the first
balance the tie-out sees; merging PDF pages changes row order. The tie-out tests are
the invariant, and are why neither is a one-liner you land unverified.

## 3. Premises that are materially FALSE

**PUR-28** — "no assignment-scope policy on any of the six Purchases tables" is wrong
for **four** of them. `purchase_bills`, `purchase_payments`, `vendors` and
`service_catalogue` all carry one in the production fixture. The mechanism is
`migrations/084_assignment_scoped_rls.sql:75-95`, a one-shot `DO` loop over
`information_schema.columns WHERE column_name = 'client_id'` — it caught everything
that existed in 2024. `debit_notes` (145) and `purchase_credit_notes` (210) came later
and were never picked up. **A fix built on the stated premise might `DROP POLICY IF
EXISTS` the four live ones.** The real hole is two tables, and the durable fix the
finding misses is a completeness guard: 084's loop never re-runs, and no test
enumerates `client_id` tables against assignment-scope coverage.

**BANK-21** — false in two of three claims. Migration 342 already built
`ledger_shape_for_bank` (`routers/banking.py:244-251`), so a card would get a Liability
ledger; and `domain/banking/posting_map.py:43-78` is purely directional, so no
posting-map change is needed. What is real: the CHECK (in **two** migrations, 054 and
093), the picker, and a **Schedule III subtype decision** — `'Bank Overdraft'` was
chosen because `bs_bucket()` substring-scans for "overdraft", which would file a credit
card under "loans repayable on demand from banks". That is the work the finding never
names.

**BANK-26** — there are **seven** adapters, of which only four name a bank; the other
three are shape-based and cover a lot of co-op and PSU exports. And the fix is cheaper
than described: `bank_statement_column_mappings` already carries `firm_id`, so a
firm-scoped fallback is a read-only change in `find_mapping` plus two call sites, no
migration. It must match on **fingerprint** exactly and never fall back on bank name.

**ACC-26** — sound on the defect, false on the consequence: `useLedgerSpan.ts` catches
the error and the period picker falls back to the FY. Zero production reach.

**INV-09** — the stated drift is false; `running_qty_units` is the same NUMERIC(10,3)
column re-read every movement. The real residue is that `unit_cost_paise` is computed
from the unrounded Decimal while the stored quantity is rounded to 3dp.

**PUR-29 / PUR-31** — closed by the finding being **wrong**, not by a fix. PUR-29
searched for purchase tests by filename and concluded the RCM/§17(5) branches were
untested; `tests/test_accounting_audit_fixes.py:55,66` and
`tests/test_r239_gst_computation_gaps.py:177` drive `create_purchase_bill` directly.

**GST-17** — "the thresholds are the pre-2021 ones" is wrong; the ₹5 crore → 6 digits
rung IS current Notification 78/2020. Only the bottom rung is stale. And the
wrong-threshold half has **zero live effect**, because the value feeds only a slice
that can never shorten a string and the input is hardcoded `0` on the web path.

## 4. One escalation

**GST-15 moved the WRONG way.** Its only mitigation was that the enabling data was
unreachable from the product. It is reachable now:
`apps/web/components/ClientFormModal.tsx:180-181` is a checkbox writing
`gst_advance_tax_applicable`, and `apps/web/app/clients/[id]/sales/page.tsx:3615-3616`
writes `gst_rate_bps` and `place_of_supply` onto the receipt. So a CA can tick the box
and **GSTR-1 will declare a Table 11A liability that GSTR-3B 3.1(a) never pays.** That
is a live contradiction between two returns filed for the same period, not a latent
one. It deserves promotion above medium.

## 5. Four new cross-subsystem duplicates

Beyond the PUR-07 ≡ TDS-13 and IT-09 ≡ FA-06 pairs the phase plan already names:

| Pair | One defect, two entries |
|---|---|
| **PUR-23 ≡ TDS-32** | purchase notes never reverse TDS. PUR-23 is the `tds_deductions` register half, TDS-32 the 26Q half. Fixing either alone leaves the other's symptom |
| **PUR-18 ≡ GST-24** | the same three lines at `gstr3b_computer.py:316-317`. PUR-18 adds the Bill of Entry, GST-24 adds ISD |
| **PUR-20 ≡ SALES-20** | the same missing cess column, inward and outward. 3B's cess line is only right if both land |
| **PUR-22 ≡ SALES-14** | an allocation endpoint on each side that no screen calls. Same UI shape, same advance-withholding trap |

## 6. Two shared blockers worth doing once

- **GST-17 + GST-32** both need the client's **annual aggregate turnover**, which the
  product does not store (`apps/web/lib/data/gst.ts:592` hardcodes
  `aggregate_turnover_paise: 0`). One `clients` column unblocks the HSN digit rule and
  the e-invoice eligibility/30-day check together.
- **GST-21** (`domain/gst/interest.py`, §50 and §47) blocks **GST-28**'s interest
  column. Build the interest module once.

## 7. One defect with no finding at all

`migrations/055_v131_hardening.sql:79` and `:100` create indexes
`ON bank_transactions (client_id, bank_account_id, txn_date, …)`. **Neither column
exists on that table** — it has `transaction_date`, and no `bank_account_id` at all
(confirmed against the production database on 12-09-2026: 15 live indexes, none
matching either declaration). Those two statements never took effect. Do not quote
index coverage on `bank_transactions` from migration 055.

---

# The second five slices — 12 September, against `92392e2c`

Sales, TDS, income tax, payroll and fixed assets: 148 findings, same brief. The
sections below are the cross-slice conclusions; the per-finding verdicts are in
the five files.

## 8. Defects with no finding at all — the second pass found sixteen

Ranked by what reaches money or a filed return wrongly today. Each carries its
`path:line` in the slice file.

| # | Where | What |
|---|---|---|
| **1** | `domain/tds/section_rates.py:324-374` | **A bill dated in any FY before 2025-26 is withheld at FY 2025-26's post-Finance-Act-2025 thresholds, silently, and the direction is UNDER-deduction.** `tds_rates_for` falls back to `LATEST_VERIFIED_TDS_FY` for any unknown year, PAST as well as future, and `vendor_tds` passes the bill's own FY. Measured: `resolve_tds('194J', 40_000_00, fy='2024-25')` → nil, where FY 2024-25's ₹30,000 threshold made ₹4,000 due. Nothing warns — the resident path has no equivalent of `section_195_rates.rates_are_verified`. §40(a)(ia) disallows the whole expenditure |
| **2** | `routers/payroll.py:713-731` | **The SECOND reverse of a payroll run gives nothing back, so PAY-08 reopens one cycle later.** `_undo_loan_recoveries` skips by `loan_id` for the whole run, and `_record_loan_movement` is append-only with no unique key. finalise → reverse → finalise → reverse leaves the loan written down 2× and restored 1×. Live through the UI, and no test re-finalises. The table already supports the fix: restore the NET signed `amount_paise` per `(run_id, loan_id)` |
| **3** | `apps/web/app/tds/returns/page.tsx:145,152,153` | **The firm-level TDS return screen fabricates a TAN (`MUMB00000A`), a deductor PAN (`AAAAA0000A`) and an address, and saves the return under them.** `_validate_26q` only checks length, so the payload validates clean and persists as `prepared`. Materially worse than TDS-28, which is "the CA re-types it" |
| **4** | `apps/web/app/clients/[id]/sales/page.tsx:3623` | **The inter- vs intra-state split for a GSTR-1 Table 11A advance is decided in the browser and stored verbatim.** `is_interstate: advancePos !== clientStateCode`, and `clients.state_code` is nullable — so for a client with no state code recorded, EVERY advance is declared inter-state, putting IGST in Table 11A where CGST+SGST is due. The invoice path already derives this server-side |
| **5** | `routers/payroll.py:6019-6042` | **`/statutory-position` ignores salary revisions**, so the projection and the payslip disagree — the same class PAY-20 closed, reopened through the drawer PAY-11 built |
| **6** | `apps/web/app/clients/[id]/fixed-assets/page.tsx:261-267` | **The Register tab shows soft-deleted assets and its Gross Block includes them.** Every backend read excludes them; this direct PostgREST select has no `deleted_at` filter, so the Delete dialog's promise ("the asset leaves the register") is false and the tab disagrees with every other view by the deleted asset's cost |
| **7** | `services/phase2_journal_service.py` (4 sites) | **`asset.get('asset_code', default)` where the column is NULLABLE.** A default substitutes only when the KEY is absent, so a NULL code produced the literal reference `FA-DEPN-None-{period}` — the same reference for every code-less asset of a client in that month, which the kernel dedupes on. The second asset's charge never reached the GL while its register row moved |
| **8** | `services/invoice_pdf_service.py:294-322` | **Server-side request forgery through firm branding URLs.** `_remote_image` fetches any `http(s)` URL with `follow_redirects=True` on every fee-invoice render; `logo_url`, `secondary_logo_url` and `upi_qr_url` are free-form strings with no host allowlist. Blind and bounded (3s, 2MB, failures silent), so a probe primitive rather than exfiltration — the missing control is an allowlist at the write boundary |
| **9** | `routers/fixed_assets.py:637` | **Asset creation with claimable ITC is not lock-checked**, while correct and delete on the same asset are. So a June asset with June ITC can be created after June's GSTR-3B is filed, and then cannot be corrected |
| **10** | `models/payroll.py` | **`eps_eligible` and `gratuity_act_covered` are settable from nowhere** — not on `EmployeeIn`, not on `EmployeeUpdateIn`, not in the CSV importer, not on a form — and are read defaulting **True**. A member GSR 609(E) excludes from EPS gets 8.33% diverted on the ECR, a statutory return, with no way to correct it |
| **11** | `domain/payroll/professional_tax.py:96-99` | **PT ticked with no state withholds ₹0 forever and raises no gap** — a blank code returns `modelled=True`, so `is_gap` is False. The same blank field silences the LWF gap. Article 276 makes the employer liable |
| **12** | `domain/income_tax/itr_engine.py:341` | **`exempt_income_paise` is collected, transmitted, accepted — and never read.** A live input on the client Tax Computation tab that changes nothing and says nothing |
| **13** | `domain/income_tax/itr_engine.py:453-457` | **IT-08's own working never leaves the engine.** `basic_exemption_absorbed_paise` and `basic_exemption_absorption` exist so a CA can check which gain the exemption was set against; no router and no screen reads either |
| **14** | `tests/test_a_section_the_engine_cannot_answer_for_is_refused.py:87-96` | **A guard test that cannot fail.** The loop iterates registry sections but the body calls `return_type_for(residency)`, which never sees `section` — so the assertion is identical for every key and the guard its docstring describes does not exist |
| **15** | `apps/web/app/tds/page.tsx:39,41,42` | The CSV importer requires `tds_rate`, `fy` and `quarter` and discards all three. A CA who types a quarter the date contradicts gets the date's, silently |
| **16** | `domain/income_tax/book_to_tax_bridge.py:28-30` | The module's central claim — "NOTHING IN THIS CODEBASE IMPLEMENTS THE SECOND ONE" — is now false, and will mislead the next reader into rebuilding §32 |

## 9. Four more findings whose suggested FIX must not be applied as written

Added to ACC-23 and ACC-25 in §1.

- **SALES-13** — its sales-invoice branch would print the CA practice's UPI ID
  and bank account on the client's OUTWARD invoice, asking the client's customer
  to pay the accountant. `invoice_pdf_service.py:842-847` refuses it in words.
  That is SALES-01 re-created as a payment-instruction error, which is worse.
- **SALES-22** — reverses the written liability-posture decision at
  `docs/FIRM_HSN_LIBRARY.md:10-45` ("Caflow asserts no classification content of
  any kind, anywhere a user can see it") without acknowledging it exists. Owner
  reversal first; the code is downstream and easy.
- **TDS-23** — adding `194IA`/`194IB`/`194M` to the registry converts a visible
  422 into a **silently mis-routed 26Q row**: those are challan-cum-statement
  sections (26QB/26QC/26QD) and `return_type_for` picks the statement by
  residency alone. Two tests pin the refusal. `194N` is charged by a bank on its
  customer and is a category error in a vendor list. The safe subset is `194T`.
- **TDS-19** — "filter to the TDS/TCS record types only, adding A2/F" drops a
  genuine §194-IA credit: Part A2 is tax deducted FROM the client as seller
  (a credit that must stay) and Part F is tax the client deducted AS BUYER
  (which must not). They point opposite ways.
- **IT-10** — "write the utilisation back when a snapshot is saved" would consume
  a brought-forward loss on drafts that are never filed, and double-consume
  across versions. The write-back belongs on the filing transition.
- **IT-29** — "refuse to PERSIST an indexed cost computed on an estimated index"
  would refuse to record a real transfer every April-to-June, because the CBDT
  notifies the CII partway through the year.
- **PAY-04** — sound for the TDS read, **wrong for the ESI read**: filtering
  `_members_contributing_earlier_this_period` to released runs makes an
  unfinalised April drop a member out of Rule 50 coverage in May, under-deducting
  ESI, which is the direction the whole Rule 50 fix was written against.
- **PAY-30** — sound for UAN and IFSC (the regexes already exist in
  `employee_import.py`); its "10-digit ESIC check" is invented and would refuse
  legitimate numbers.
- **FA-04** — "make the 409 per-period so gaps can be filled" cannot be done
  against a single `depreciation_posted_through` DATE, and `reverse_depreciation`
  depends on it being a contiguous high-water mark. It is a per-month postings
  table and a rewrite of the reversal path, not a comparison change.
- **FA-08** — its depreciation limb asked to post four journals behind a click
  the CA thinks is about a sale. The refusal that shipped is correct; do not
  re-open it against the finding's text. The GST-on-disposal limb is sound.
- **FA-13** — deriving the terminal from 5% of cost changes the charge on every
  existing WDV asset whose salvage is 0, against two pinning tests, and overrides
  a salvage the CA deliberately recorded. Default it at CREATE instead.
- **FA-14** — "use `is None` rather than `or`" makes an explicit
  `useful_life_years = 0` reach a division by zero. Pair it with `Field(ge=1)`.
- **FA-02's completion hazard** — a backfill migration rewriting
  `wdv_rate_percent` would silently overwrite a Schedule II Part A judgement and
  move the profit. Its deliberate absence is the fix, not an omission.

## 10. New duplicate pairs from the second five

| Pair | One defect, two entries |
|---|---|
| **TDS-01 ≡ PUR-01** | not previously named; both closed by the same change |
| **SALES-09 residual ≡ GST-15** | `advances_report` says Table 11 is not computed while `table_11_sections` computes it into the filed payload |
| **SALES-10 ≡ GST-07** | GST-07 the SEZ/deemed-export half (closed), SALES-10 the shipping-bill half (open on the `expa` amendment path) |
| **SALES-22 ≡ GST-26** | same defect, same evidence; SALES-22's fix collides with Decision A |
| **SALES-32 ≡ TDS-10** | SALES-32 is the stale §206C(1H) comment (hours); TDS-10 is building TCS |
| **IT-24 ≈ TDS-20** | same function. IT-24 carries the SILENCE (`parse_errors` never written, `parse_status='parsed'` on zero records), TDS-20 the FORMAT. Fixing IT-24 alone turns a silent zero into a hard refusal for every real TRACES download — they must land together |
| **PAY-03 ≡ SALES-01** | the CA practice printed where the client belongs, in three PDF services. All closed, each fixed file-locally — there is still no sweep over `services/*_pdf_service.py`, which is why the payslip survived two rounds |
| **PAY-09 ≡ FA-03** | the browser re-deriving a figure the backend already computed |
| **PAY-10 ≡ TDS-05** | a hardcoded statutory rate table in TypeScript; deliberately kept apart by an allowlist |
| **FA-05 half ≡ FA-15 half** | both need one FY-scoped fixed-asset movement; building them separately creates the third implementation |
| **IT-07 → IT-21** | an ordering dependency: IT-21's §115JC(5) carve-out makes part of IT-07's fix unreachable. Do IT-21 first |
| **PAY-22 ≉ IT-20** | explicitly NOT a duplicate. PAY-22 is the §80CCD(2) BASE (closed); IT-20 is the RATE (open). Same computation, and the 11 September pass warned about exactly this confusion |

## 11. What the second pass changes about the backlog's shape

Stale rates by slice: sales **59%** (19 of 32 closed), TDS **44%**, income tax
**38% closed and 26% partial**, payroll **53%**, fixed assets **50%**. Against
the 11 September pass's measured ~10%, that is not a contradiction — five
tranches landed in between and none re-scored. It does mean **the finding files
are no longer a usable work list on their own**; these ten slice files are.

Two shapes recur across all nine slices and are worth naming as patterns rather
than as findings:

- **An engine that is finished, correct and reachable from no screen.** FA-07
  (credit-purchase and ITC on an asset), IT-09 (the book-to-tax bridge), IT-13
  (§234A/B), IT-16 (presumptive), IT-17 (ITR field placements), FA-05 (the
  Schedule III movement), SALES-09 (the advances report). In every case the hard
  two-thirds is done and what is missing is a form.
- **A figure the server computes and the response drops.** IT-08's absorption
  working, FA-08's `part_month_depreciation_not_charged`, INV-04's
  `last_movement_date`. CLAUDE.md's own line applies: a figure the computer gets
  right and no screen shows is not a fixed bug.
