# What is left, 8 September 2026

Every one of the 275 findings in `2026-09-07-findings/` was re-checked against
the code as merged (`46bd46c`). Nine readers, one per subsystem, each required
to produce a **probe** — a quoted line of current code, a grep with its output,
or a command they ran — before writing "fixed". They were told to default to
STILL OPEN, and were read-only on the repository so a tempting one-line fix
could not become unreviewed code.

The verdicts are on each finding as `rescore_2026_09_08`. The 7 September
`verification` block is deliberately **left alone**: it is the evidence the
fixes were aimed at the right thing, and a report rewritten after the fact
cannot be checked against anything.

---

## 0. A correction to the record

The merge commit on `main` says **"Nineteen of the twenty confirmed
criticals"**. That is wrong. The true figure:

| | |
|---|---|
| **fully fixed** | **15** |
| **partially fixed** | **3** — FA-02, GST-01, PUR-01 |
| **never touched** | **2** — GST-04, IT-01 |

The error was counting findings *worked on* rather than findings *closed*.
PUR-01 and PUR-02 describe one TDS defect from two angles: PUR-02 closed, PUR-01
did not. FA-02 corrected the default rate and not the stored rows. GST-01
corrected the money and not the record. **IT-01 was never touched at all** — it
was conflated with IT-02/03/04, which were fixed.

That miscount is the reason this document exists, and it is the argument for
re-scoring after any large tranche rather than trusting the tranche's own
summary.

---

## 1. The shape of what remains

| | fixed | partial | still open |
|---|--:|--:|--:|
| **275 findings** | **27** | **15** | **233** |

Those three columns are **against `46bd46c`**, which is what makes them
checkable. Section 2's work has since closed **ACC-04** (medium) and
**SALES-15** (high, five of its six paths), and turned **FA-08** (high) from a
wrong number into a refusal — so the live figures are three better than the
table. The table is deliberately not rewritten: a count that moves every commit
stops being evidence of anything, and the commit it was taken against is how a
reader checks it.

**248 items of remaining work** (open + partial), by corrected severity:

| critical | high | medium | low |
|--:|--:|--:|--:|
| 5 | 83 | 124 | 36 |

By subsystem, remaining only:

| subsystem | crit | high | med | low | total |
|---|--:|--:|--:|--:|--:|
| TDS / TCS | 0 | 12 | 13 | 5 | 30 |
| Banking | 0 | 9 | 14 | 6 | 29 |
| GST | 2 | 9 | 16 | 1 | 28 |
| Purchase cycle | 1 | 10 | 13 | 4 | 28 |
| Sales cycle | 0 | 10 | 14 | 4 | 28 |
| Fixed assets & inventory | 1 | 8 | 15 | 3 | 27 |
| Income tax / ITR | 1 | 11 | 9 | 6 | 27 |
| Accounting core | 0 | 7 | 14 | 5 | 26 |
| Payroll | 0 | 7 | 16 | 2 | 25 |

Five subsystems moved by **0 or 1 finding**: the tranche was deep, not broad.
Accounting moved by one; banking's backend is byte-identical to the audit tree.

---

## 2. Fix first: what the last tranche broke

These are **new**, they are on `main`, and none of them has a finding id. They
come before anything else on this list.

> **CLOSED, 8 September 2026.** All nine are done, across three commits on
> `claude/ca-platform-audit-roadmap-yuoad3`. Each carries a negative control —
> how many of its new tests fail against the previous code:
>
> | | what was done | negative control |
> |---|---|--:|
> | 2.1–2.4 | the deduction is bounded by the payment; the draft-credit argument is refuted in-code; four sections gain the aggregate limb; a `tds_is_a_fy_catch_up` gap | 2 (cap), 5 (sections) |
> | 2.5 | the guard is rewritten as the RULE, not three spellings of it; **17 files** converted to the one parser | 4 tests / 26 sites |
> | 2.6 | `_annual_pt_paise` sums the months instead of multiplying one; the existing test had the defect written into it and is corrected | 6 of 10 |
> | 2.7 | the payslip letterhead is the EMPLOYER; `load_employer` refuses a missing client rather than falling back to the firm | 5 of 8 |
> | 2.8 | `cii_for` anchors to the table's newest year, not the verification marker; §80G(5D) is tri-state at the screen; Total Output Tax includes zero-rated IGST; **ACC-04 closed** (migration 338); **SALES-15 closed** for notes and every issue path; **FA-08 refuses** a disposal with unposted depreciation | 8 (338), 6 (SALES-15), 5 (FA-08), 9 (ACC-04 service) |
> | 2.9 | measured against production rather than estimated — see below | — |
>
> **Two "probably nil" blast radii were CHECKED against the live database**, on
> the principle that probably-nil is not the same as nil:
>
> * the pre-Code PF change orphaning historic slips — production holds **0
>   payroll slips, 0 employees, 0 ECR filings and one draft run** (2026-08), so
>   nothing was stored at the old base and nothing was remitted on it;
> * the 26Q consequence in 2.9 — production holds **759 purchase bills, none
>   with TDS**, 0 rows in the TDS register and 0 TDS filings, so no already-filed
>   quarter can disagree with anything.
>
> Both remain true statements about *this* deployment on *this* date, and the
> reasoning stays here because a second deployment will not have the same book.

### 2.1 A purchase bill can be permanently wedged — CONFIRMED BY TWO READERS

Charging TDS on the FY aggregate means the tax can exceed the bill it lands on.
That is the statute. What was not done is guarding the arithmetic downstream:
`routers/purchase_bills.py` computes `net_payable_paise = total_paise -
tds_paise` unguarded, and the kernel credits Trade Payables with exactly that.
`journal_lines` carries `CHECK (credit_paise >= 0)` (migration 003).

Reproduced independently by the TDS and purchase readers, same probe: a §194J
vendor bills ₹49,000 (under threshold, nil withheld) then ₹2,000 → ₹5,100
withheld, `net_payable_paise = -₹3,100`. The entry balances, so the kernel's
assertion passes and mock mode writes it happily; **production rejects with
23514** and `receive_purchase_bill` rolls the status back, leaving the bill a
draft for ever. Migration 278's generated `outstanding_paise` goes negative too,
so AP ageing and the vendor statement inherit it.

**No mock test can see this** — `journal_for_purchase_bill` returns `None` under
`_USE_MOCK` before touching a line — and the new production-types write guard
checks column *types*, not CHECK constraints.

### 2.2 The §200 credit is given for tax that was never deducted

`_resolve_bill_resident_tds` builds one list of earlier bills and uses it for
both limbs. Including **drafts** is right for the THRESHOLD — §194C(5)'s "likely
to be credited", and the comment argues it. It is wrong for the CREDIT: §200
reaches only tax "deducted and paid to the credit of the Central Government". A
draft ₹1,00,000 §194J bill beside a posted one makes the posted bill withhold
₹10,000 against ₹20,000 due. Under-withholding — the §40(a)(ia) direction.

### 2.3 Four sections were left silently undecided, and documented as deliberate

§§193, 194, 194K and 194LA did not get the aggregate limb; §193 and §194 were
named in PUR-01's own `suggested_fix`. Four ₹4,000 §193 bills — ₹16,000 against
a ₹10,000 limit — still withhold ₹0. Worse, `section_rates.py` now says *"Two
sections deliberately have NO aggregate"* when six do not.

### 2.4 The 26Q deductee row is internally inconsistent on the crossing bill

The register writes that bill's own taxable value and the section rate beside
the aggregate-based tax, so a line reads *₹2,000 paid, 10%, ₹5,100 deducted*.
The year totals correctly across rows; no single row does.

### 2.5 The money-parser guard is under-specified, and CLAUDE.md overclaims it

`every-amount-field-uses-the-one-parser.test.ts` is three `parseFloat`-shaped
regexes. Running those regexes over the tree misses **six files of the same
defect class**:

| file | form | effect |
|---|---|---|
| `lib/banking/splitLegs.ts` | `Math.round(Number(cleaned) * 100)` | posts to the GL via split-replace; `"1e3"` → ₹1,000, `"abc"` → a zero leg |
| `app/engagements/page.tsx` | `parseInt(strip non-digits) * 100` | **`"1234.56"` → ₹1,23,456 — a 100× OVERSTATEMENT** |
| `app/pipeline/page.tsx` | same | same, on the monthly fee |
| `app/income-tax/deductions/page.tsx` | `parseFloat` and `* 100` split across two statements | slips the regex; **this file was edited in the same commit** |
| `app/income-tax/ais/page.tsx` | same | |
| `components/portal/TaxDeclarationTab.tsx` | hand-rolled digit/fraction split | |

CLAUDE.md now asserts the test "is what holds the claim up now — prose was not
the guard." Prose was replaced by an under-specified regex and the same claim
re-made. The fix is a POSITIVE assertion — every `*_paise` payload field traces
to `paiseFromRupeeInput` — not three negative string matches.

### 2.6 One change LOOKS like a fix and is not — PAY-17

`routers/payroll.py:1103` went from `pt * 12` to `pt * months_in_year` in the
same sweep that fixed PAY-06. For a full-year employee `months_in_year` IS 12,
so the defect is **bit-identical** for exactly the case PAY-17 names. Measured
at HEAD on an old-regime Tamil Nadu employee at ₹50,000: month 9 still feeds
**₹15,000** of §16(iii) professional tax against a real annual ₹2,500, and the
TDS still comes out ₹1,690 against ₹1,950 in the flat months — the same numbers
the 7 September pass measured.

This is the dangerous shape. Anyone diffing the file, or reading the commit,
would score it closed. Only running it says otherwise.

### 2.7 A third payslip document still names the CA firm — PAY-03

The supplier-identity confusion was fixed in `invoice_pdf_service.py` and
`statement_pdf_service.py`. **`services/payslip_pdf_service.py:116` was never
touched**: `firm_name = firm.get("name") …`, rendered as the document title, on
the payslip handed to the client's *employee*. `run["client_id"]` is selected
and discarded two lines later.

Both guard tests written in that tranche are file-scoped and neither sweeps the
PDF services, so nothing catches it. Third instance, third file.

### 2.8 Seven smaller ones, all introduced or newly exposed

- **`cii_for` regressed.** `LATEST_CII_FY` was held at 2025-26 (deliberately —
  384 is secondary-sourced) while 2026-27 was added to the table. The fallback
  reads the anchor, so `cii_for('2027-28')` returns **376** — older *and lower*
  than the table's own newest value. Over-taxes. The docstring's "falls back to
  the latest known FY" is no longer true of the code.
- **The §80G(5D) tri-state is collapsed at the only screen that feeds it.** The
  engine distinguishes "paid in cash", "not in cash" and "not stated", and warns
  on the third. `deductions/page.tsx` types the field `boolean` and sends
  `false` when unchecked, so the warning can never fire from the UI.
- **"Total Output Tax" now contradicts the row above it.**
  `app/gst/gstr3b/page.tsx:350` still sums only `taxable_*`, so it excludes the
  zero-rated IGST the same screen now prints, and disagrees with the Table 6
  liability it sets off.
- **ACC-04 widened by one source type.** Year-end adjustment journals now carry
  `source_type='year_end_adjustment'`, which correctly blocks discard — but
  `edit_posted_journal` has no such test, so one more auto-posted entry can be
  rewritten away from the document behind it.
- **SALES-15 went from theoretical to live.** Before the period-lock fix,
  `journal_period_lock_reason` could never fire for anything. It now fires for
  sales invoices and purchase bills, and still not for credit notes, sales debit
  notes, receipts or invoice issue.
  **Closed for five of those six.** Credit-note create/update/issue,
  sales-debit-note create/update/issue and `issue_invoice` now call
  `period_lock_service.assert_open`. **Receipts are deliberately excluded**, and
  the argument is in `services/receipt_service.py` beside the decision: a
  receipt moves Bank and Debtors and touches no output tax, and the only filing
  types written to `public.filings` are GSTR-1 and GSTR-3B — returns of
  SUPPLIES, not of collections. Blocking one would refuse an ordinary thing
  (a payment received 20 June, entered 15 July, after GSTR-1 went on the 11th)
  for no statutory gain. A test pins the premise: if
  `gst_filing_record_service.FILING_TYPE_*` ever grows past those two, the
  decision has to be retaken.
- **FA-08 became more convincing while staying wrong.** Accumulated depreciation
  was frozen at 0 for everyone before FA-01; it is now a real number, so the
  stale WDV shown at disposal looks trustworthy for the first time.
  **Now refused rather than computed.** `dispose_asset` will not post while any
  whole month between the purchase and the disposal month is undepreciated, and
  it names them in order — the same rule, and the same reasoning, that
  `post_depreciation` already applies to a skipped month: "each month is its own
  journal needing its own CA review". The part month between the last month end
  and the disposal date is still uncharged, and the response now says so
  (`part_month_depreciation_not_charged`) instead of absorbing it into the gain.
  Charging it properly — pro-rating on days, as the purchase month is — remains
  FA-08's own item.
- **The pre-Code PF fix orphaned historic slips.** For a month ending before
  21-11-2025 on ₹10,000 basic + ₹2,000 medical + ₹3,000 special, HEAD now
  computes a ₹10,000 base and ₹1,200 of PF; the previous code computed ₹15,000
  and ₹1,800 — and any slip finalised before the fix **stored and remitted
  ₹1,800**. `/statutory-position` for that month now disagrees with the stored
  payslip: the exact inverse of PAY-20, with no backfill and no list of affected
  slips. Blast radius is probably nil (payroll v1 landed 4 September 2026), but
  it is unrecorded, and "probably nil" is not the same as checked.

### 2.9 Deployment consequence, not a defect

Bills already in the database carry marginal-only `tds_paise`. The first bill
posted after this deploy credits those too-small figures and charges the full
aggregate, which self-corrects the year — but **an already-filed 26Q quarter
will now disagree with the register**.

---

## 3. The five criticals still open

| id | state | what is left |
|---|---|---|
| **GST-04** | untouched | The 2A/2B reconciliation does not read the books, does not parse a real GSTR-2B JSON, and persists nothing. Byte-identical parser; zero writers of `gstr2a_records`; `/gst/reconciliation` contains no API call at all. Gates GST-19 and GST-28, and PUR-11 is the same defect from the purchase side. |
| **IT-01** | untouched | No tax computation path for a company, firm or LLP. `entity_rates`, `minimum_tax` and `presumptive` are complete, tested, and imported by nothing outside their own package. |
| **FA-02** | partial | The default rate is right; **the stored rows are not**. No backfill migration, the compute path prefers the stored rate, and FA-10 leaves no edit path — so a wrong rate is frozen in for the asset's life. Production holds zero fixed assets today, so this is latent until a register is migrated in. |
| **GST-01** | partial | The money is right everywhere; **the record is not**. `SaveGSTR3BRequest` has no cash column, so `gstr3b_returns.net_tax_paise` and hence `filings.tax_payable_paise` store the credit-settled figure rather than what was paid. One screen still shows only Net Tax. ~1 hour. |
| **PUR-01** | partial | §§193, 194, 194K, 194LA — see §2.3. |

---

## 4. The 83 highs, grouped so they can be planned

Themes rather than a list; the ids are in the findings files.

1. **Cash does not exist.** ACC-02, ACC-03, SALES-08, BANK-20 — cash receipts
   and cash vendor payments post to *Bank*, Cash in Hand never moves, there is
   no cash book and no petty cash. Every receipt debits one firm-wide "Bank"
   ledger and the account the CA picked is discarded.
2. **Reconciliation is a tick-off, not a BRS.** BANK-04/05/06/09 — no
   unpresented cheques, no deposits in transit, an unexplained "Adjustments"
   plug that can force a tie-out into a signed PDF, and no undo for a
   mis-imported statement.
3. **Finished backends no screen reaches.** PAY-11 (seven payroll capabilities
   including the leaver settlement), IT-13 (§234A/§234B), IT-16 (presumptive),
   IT-17 (ITR field placements), PUR-05 (§17(5) blocked credit), PUR-14,
   GST-13, SALES-13. Computed, tested, rendered by nothing.
4. **TDS has a second implementation in the browser.** TDS-05 — `/tds` computes
   TDS in TypeScript from a hardcoded stale table and writes straight to
   `tds_deductions`. With TDS-03, TDS-04, TDS-11 (no role check), TDS-15,
   TDS-09 (no 27Q), TDS-22 (§194J 2% technical and §194I 2% plant both
   over-deduct at 10% — the copilot prompt *describes* the split the engine
   cannot compute).
5. **GSTR-1 cases the portal rejects.** GST-07 (deemed exports filed as
   physical), GST-08 (a blended B2CS rate that does not exist), SALES-10
   (hardcoded shipping bill and port), SALES-06 (seven states/UTs unselectable),
   SALES-09 (Table 11A/11B unreachable), GST-11 (no QRMP), GST-20 (one GSTIN
   per client).
6. **Nothing can be corrected.** FA-10 (no edit/reverse/delete an asset),
   ACC-05 (a locked FY never reopens), PAY-12 (joining date silently
   discarded), SALES-04 (deleting a draft credit note wedges numbering for
   ever), ACC-09 (no screen to create or edit a ledger).
7. **State that is not in the database.** ACC-06 — recurring journals, budgets
   and retainers live in one browser's `localStorage`.

**Also found by this pass, no finding id yet:**

- **`post_draft` bypasses the client year lock.** It checks the FIRM period
  lock only. Draft creation goes through the kernel so it cannot be created
  into a locked year; approval flips `is_posted` directly. Draft raised while
  open → year-end finalised → approved from the queue puts an entry inside a
  client year ACC-05 says the kernel refuses.
- **The capital-gains fork did not reach `itr_engine.py`.** It is still
  FY-keyed. `POST /api/income-tax/compute` with `fy="2024-25"` charges post-fork
  rates **and returns `rates_verified: true`** — an affirmative claim that a
  Finance Act was checked for a year nobody entered.
- **The ₹ sign prints as the letter "n"** on the fee invoice and the customer
  statement. Helvetica has no ₹ glyph. The statement — emailed to the client's
  customer — prints "Invoiced: n1,000.00". The new sales layout writes `Rs.` and
  its comment says why, so this was seen and left in the other two.
- **`rbac("banking", "approve")` is enforced by no route**, so any remedy of the
  form "gate this on Manager+" has nothing to gate on.
- **Three UTC "today"s in `routers/fixed_assets.py`** while the module imports
  `core.ist_clock`: at 00:20 IST on 1 April the default period is the previous
  financial year.
- **The filing date is never collected.** `record_filing` falls back to
  `ist_today()`, so `filings.filed_date` is the day the ARN was typed.
- **`/gst`'s 32-second request.** BANK-07 measured 12,836 rows: `build_register`
  0.071s, then 32.4s of CPU from a `list.index` inside a loop.
- **`annexure2.py` caps §16(ia) at §17(1) alone**, excluding §17(2) perquisites
  and §17(3) profits in lieu, which are also income under the head Salaries.
  Pre-existing; missed by the original readers.
- **PAY-22 is a one-liner now.** `(basic + da) * months_in_year` already exists
  at `routers/payroll.py:1101`; passing it as `salary_for_80ccd2_paise` closes
  the finding.
- **PAY-10 is milder than its own evidence reads.** The header of
  `payrollTdsEstimate.ts` claims `app/payroll/page.tsx` persists browser-computed
  slips. That page does not import it, and there is no browser-side
  `payroll_slips` insert anywhere. The module is display-only; the stale comment
  is what makes the finding look worse than it is.

---

## 5. What no code closes — a human must supply it

Refusals by design; the code names the gap rather than guessing. See CLAUDE.md
§3b.

| what | why it cannot be derived |
|---|---|
| Professional tax slabs for 18 more states, LWF for all 16 | per state, per employment, per skill grade, revised twice yearly. Thirty-six wrong deductions is worse than a flagged gap. |
| The seven ITR JSON schemas, per assessment year | published per form per AY at incometax.gov.in; cannot be generated or inferred |
| DTAA rates | nature of income × ninety-odd treaties, MFN clauses needing their own §90(1) notification |
| Minimum wage (Bonus Act §12) | §12 computes on ₹7,000 **or the minimum wage, whichever is HIGHER** |
| SBI's Rule 3(7)(i) rate; ESIC reason codes | published by the bank / by ESIC |
| Prior-year income for §89; lifetime gratuity and leave exemption used | comes off the employee's return; the employer never held it |
| Vendor MSMED classification | a fact about the SUPPLIER. §43B(h) changes taxable income, so "Others" by default is not presentational |

---

## 6. Commercial gates — months, not code

`docs/compliance/07-getting-permission-to-file.md`.

- **Free and available now:** Third Party Software Utility Developer
  registration (the `SW########`); the NIC e-invoice sandbox.
- **Months of commercial work:** ERI Type-2, GSP or an ASP sub-licence, NIC
  production credentials, an India static-IP egress hop.
- **No route exists:** MCA, EPFO, ESIC — nothing to apply for.
- **Closed:** Account Aggregator. The published purpose taxonomy has no code for
  bookkeeping, which forecloses the partner route as well.
- **e-invoice IRN and e-way bill are the only two statutory outputs software can
  complete end to end**, because the IRP signs and there is no taxpayer
  signature.

---

## 7. Suggested order

1. **§2 in full.** New breakage from the last tranche, on `main` now. §2.1 is
   the only one that can wedge a client's book.
2. **GST-01 and PUR-01 to completion** — both are an hour or two, and both are
   criticals currently counted as done.
3. **PAY-03 and PAY-17**, because both are cheap and both are currently
   mis-scored by anyone reading the diff rather than running the code.
4. **IT-01** — the engines exist and are tested. This is wiring, and it is the
   difference between "personal tax" and "tax".
5. **GST-04 + PUR-11 together.** One defect from two ends; closing it is what
   lets a CA finish a month inside the product. This opens Stage 2 of
   `2026-09-07-a-plus-roadmap.md`.
6. Then the roadmap's Stage 2 → 3 → 4 order, which is unchanged.

Two habits this pass argues for, both cheap:

- **Re-score after a tranche.** This one found 8 regressions and a miscount of
  the headline number. The tranche's own summary said none of that.
- **When a fix lands in an engine, grep the SCREENS for the same figure.** Four
  of the regressions are a screen left behind by its engine.
- **A changed line is not a fixed defect.** PAY-17's literal changed and its
  behaviour did not. Score by running, never by diffing.
