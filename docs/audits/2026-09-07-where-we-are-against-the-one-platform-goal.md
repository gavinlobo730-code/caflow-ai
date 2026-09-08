# Where we are against the one-platform goal

**Date:** 7 September 2026
**Question asked:** *we are building one platform for Indian CAs — accounting, GST,
TDS, income tax, payroll, practice — cheap enough for SMEs. If any pillar is weak
nobody buys it. Where are we, what is broken, what is missing, and what will the
market say?*

---

## 0. How to read this, and how much to trust each part

This report has three tiers of confidence and they are not interchangeable.

**Tier 1 — I ran it myself.** Seventeen of the twenty-one critical defects below
were reproduced in this session by executing the code or querying the production
database, and the numbers printed here are the numbers those runs produced. Where
that is so, the finding says **verified**. Two claims I set out to confirm turned
out to be **wrong and are recorded as corrected**, because a report that only
confirms is not a check.

**Tier 2 — a deep reader found it and an adversarial verifier attacked it.** Nine
subsystems were each read end to end (routers, services, domain modules,
migrations, screens, tests) and returned 278 findings. On the owner's instruction
every remaining finding was then re-read by an independent verifier under three
lenses, told to *refute* rather than confirm. **Three were refuted.** Thirty-five
were corrected downward, four upward, and many were sharpened with a measured
probe. §13 reports what that pass was worth — including that my own estimate of
how many would fall was wrong by an order of magnitude.

**Tier 3 — lighter coverage.** Reporting and year-end, practice management, the AI
layer, portals and identity, platform and security, the frontend as a whole, and
the marketing site did **not** get a deep reader. What I say about them comes from
my own inline reading and is thinner. **That is a real hole in this audit and the
biggest single reason to commission a second pass.**

Market facts carry a source link. Everything about the code carries a file path.

---

## 1. The answer, in one page

**The engine is real and in several places better than what is sold in India
today. The product around it is not finished, and the gap between the two is
where the whole risk sits.**

Three sentences that between them describe the situation:

1. **The accounting core would survive an audit.** One posting kernel that refuses
   an unbalanced entry in integer paise, an atomic SQL function that re-checks the
   caller's firm before writing, four immutability triggers with exactly one
   carve-out argued from the Companies (Accounts) Rules, an edit log that captures
   the lines and not just the header. 12,899 journal entries and 33,080 lines are
   already posted in production and the trial balance ties.

2. **On top of that engine sit defects that put wrong statutory numbers in front
   of a CA.** Not edge cases. A professional billed ₹30,000 four times has **zero**
   TDS withheld when ₹12,000 was due. A client who buys in-state and sells
   inter-state is told to pay ₹1,80,000 of IGST in cash while ₹2,00,000 of their
   own credit sits unused. An exporter's IGST vanishes from GSTR-3B. And the tax
   invoice PDF the product emails to *the client's customer* carries **the CA
   firm's** name, GSTIN and PAN.

3. **The parts a CA touches every single day are the least finished parts.** GSTR-2B
   reconciliation does not actually compare anything. There is no screen to create a
   single ledger. Recurring journals, budgets and retainers live in the browser's
   `localStorage`. The income-tax module cannot compute a company, a firm or an
   LLP at all — and six of the seven clients in the production database are exactly
   those.

**So: the pillars are not weak in the way you feared, and not strong in the way you
hoped.** The foundation is stronger than the market's. The floor above it has holes
in the places people walk.

**Would a CA buy it today?** No — and not because of any missing module. Because
within the first week they would find a wrong TDS figure, a GST set-off that costs
their client real cash, and an invoice with the wrong GSTIN on it. In this market
that is not a bug report, it is the end of the relationship. Trust is the product.

**Is that recoverable?** Yes, and cheaply relative to what has been built. Most of
what is broken is a hundred to five hundred lines away from correct, because the
hard part — the statutory reasoning — is already right underneath. The work in §9
is roughly two focused quarters, not a rebuild.

---

## 2. The evidence base

Everything below rests on these. They were measured in this session, not recalled.

| | |
|---|---|
| Backend tests | **9,931 pass, 954 skipped, 0 fail** (84s, mock mode) |
| Frontend | `tsc --noEmit` clean · `eslint` clean (2 `<img>` warnings) · **750/750** unit tests pass |
| Backend size | 132,881 lines (excl. tests) + 149,432 lines of tests · 103 routers · **859 endpoints**, 842 behind `rbac()` |
| Frontend size | 129,521 lines across 433 files · 152 pages · **27 pages over 800 lines** |
| Database | **365 migrations** · applied to production automatically on merge to `main` |
| History | 50 commits, all September 2026, one author |

**The production database is the most informative single artefact in the project.**
Read 7 September 2026, 11:32 IST:

| Table | Rows | | Table | Rows |
|---|--:|---|---|--:|
| journal_entries | 12,899 | | receipts | **0** |
| journal_lines | 33,080 | | purchase_payments | **0** |
| client_sales_invoices | 5,662 | | tds_deductions | **0** |
| purchase_bills | 759 | | payroll_employees | **0** |
| audit_log | 47,367 | | fixed_assets | **0** |
| inventory_stock_ledger | 12,107 | | fee_invoices / time_entries | **0** |
| bank_transactions | 488 | | gstr1_returns / itr_filings | **0** |
| compliance_records | 133 | | scheduler_runs | 452 |
| service_catalogue | 399 | | engagements | 2 |
| clients | 7 | | firms / users | 2 / 2 |

Read that table twice. **The books have been hammered. Most of what sits
downstream of the books has never been used** — not one receipt, not one payment,
not one TDS deduction, not one employee, not one filing record. The modules this
audit found most broken are, with one exception, the modules with zero rows.

That is not a coincidence and it is the single most useful fact here: **the defects
are concentrated exactly where nobody has walked yet.** Eleven of the seventeen
verified criticals sit in code paths that have never run against real data.

**The exception is worth naming, because it is the good news.** `compliance_records`
holds 133 rows and `scheduler_runs` holds 452 across fourteen job types — obligation
generation, escalations, collections, recurring invoices and journals, the balance-cache
and reconciliation audits, the bank trusted-rules pass and the memory pipeline — every
one of them with a successful run on 7 September 2026 at 09:32 IST. The handful of
failures are all old (17–18 August, 3 September) and have since succeeded. **The daily
sweep genuinely works, unattended, and has done for six weeks.** It is the one part of
the product that has been operating rather than merely existing. (It ran at 09:32 IST
against a nominal 06:00 — the GitHub-cron lateness CLAUDE.md's catch-up logic exists to
absorb, working as designed.)

---

## 3. What is genuinely strong — do not rebuild these

I want this said plainly, because the rest of the report is about faults and that
distorts the picture. These are better than the Indian market standard, with
evidence.

**The posting kernel and the ledger.** `services/phase2_journal_service._create_journal`
is the only write path to the GL; it asserts double-entry balance in integer paise
and refuses a balanced-but-zero entry before touching the database. Migration 271
made `post_journal_atomic` a `SECURITY DEFINER` function that *re-checks the
caller's firm and client assignment in SQL* — so the tenant boundary survives even
if application code forgets it. Immutability is enforced by triggers with one
carve-out (migrations 266/275/276) argued from the proviso to Rule 3(1) of the
Companies (Accounts) Rules 2014 and from what TallyPrime's own Edit Log permits.
**This is better reasoned than Tally's equivalent, and Tally is the incumbent.**

**§195 and non-resident withholding.** `domain/tds/section_195.py` asks
*chargeability* before it asks a rate, citing *GE India Technology Centre v. CIT*
(2010) 327 ITR 456, and refuses rather than guessing in three named places.
`domain/tds/residency.py` transcribes the "to a resident" charging words of twelve
sections from the Act itself instead of inferring them. **Nothing in Tally, Busy or
Zoho Books does this.** An ordinary import from a supplier with no PE gets the right
answer — nil — where every competitor's user defaults to 20%.

**GSTR-3B Table 4.** Implemented from Circular 170/02/2022-GST's own words: 4(A)
gross, reversals split reclaimable from non-reclaimable, §17(5) in 4(B) and not
repeated in 4(D). The pre-2022 layout gets the tax right and the disclosure wrong,
which is why it survives elsewhere. Here it is right.

**The bank import.** Three independent verifications that refuse *before* writing —
balance agreement, printed-total tie-out, and a vision path whose totals come from a
**second model call shown no transactions**, so it cannot rationalise. A geometric
PDF column recovery for statements with no ruled table. **TallyPrime cannot import a
PDF statement at all.** This is the most commercially differentiated thing in the
repo.

**The payroll statutory engine.** §192 as a genuine projection from the joining
date, not `gross × 12`. The three §115BAC objects — the Circular 04/2023
intimation, the §115BAC(6) election, the Rule 26C Form 12BB evidence — kept
strictly apart, with nothing setting one from another. ESI on Rule 50 contribution
periods. The Code on Social Security s.2(y) wage base with its 50% cap, period-aware.
§89 refusing a year whose rates are not held rather than substituting. **greytHR and
Keka do not reason at this level; they encode last year's answer.**

**The refusal discipline.** Where a statutory input cannot be derived — a state's PT
slab, SBI's Rule 3(7)(i) rate, a DTAA article, an ITR schema, a vendor's MSMED
class — the code refuses and returns a **named gap** instead of a plausible zero.
`domain/income_tax/itr_json.py` computes a complete ITR payload and then declines to
write the file because `CreationInfo.JSONCreatedBy` needs an `SW########` the
Department has not issued. **This is the single best cultural asset in the codebase
and it is worth marketing.** No competitor says what it does not know.

**Reporting performance done as an architecture, not a tweak.** Cash flow moved from
54.34 seconds to a SQL function, with a parity test pinning the Python twin to it.
Ageing built twice on purpose because the two answers have different shapes.

---

## 4. The seventeen verified critical defects

Each of these I reproduced myself in this session. The figures are from those runs.

> **STATUS, 8 September 2026 — every defect in this section is FIXED.** Nine
> commits on `claude/ca-platform-audit-roadmap-yuoad3`, each carrying its own
> negative control; `docs/audits/2026-09-07-a-plus-roadmap.md` §12 is the
> table of what landed where. **This section is left exactly as written**,
> because the reproductions are the evidence the fixes were aimed at the right
> thing, and a report rewritten after the fact cannot be checked against
> anything. Read the figures below as "what it did on 7 September", not as
> current behaviour.
>
> Three of them turned out to be bigger than this section says, and that is
> worth knowing before trusting any other section's scoping:
>
> * §194Q's ₹50 lakh is an FY **aggregate** as well as a single-payment
>   trigger, so two ₹30,00,000 bills to one seller withheld nothing at all —
>   a case this section does not contain.
> * The CII table did not merely stop at 2025-26; the 2025-26 value itself was
>   wrong (380 against six sources saying 376).
> * The capital-gains engine was not only missing the rate fork — the §2(42A)
>   **holding periods** changed on the same date too, so a non-property asset
>   held 30 months before 23-07-2024 was classified long-term where the statute
>   needed 36.
>
> One correction to this section's own framing: it treats the engine as the
> deliverable. For four of these defects the engine was fixed in one pass and
> the screens in another, and in between the figure was correct and no CA
> could see it. Scoping a statutory fix should include its callers.

### 4.1 Tax withheld: four defects, all confirmed by running the engine

`TDSComputer.resolve_tds` (`domain/tds/tds_computer.py:258-318`) is the single
source of TDS on every purchase bill. I ran it:

| What I ran | It withheld | The Act requires |
|---|--:|--:|
| §194J — four bills of ₹30,000 to one professional | **₹0** | ₹12,000 |
| §194H — three commissions of ₹15,000 | **₹0** | ₹900 |
| §194C — five bills of ₹25,000 to a company | **₹500** | ₹2,500 |
| §194Q — one purchase of ₹60,00,000 | **₹6,000** | ₹1,000 |

Two distinct bugs produce all four rows.

**(a) Only §194C carries an FY aggregate threshold.** `section_rates.py:110-150`
gives `aggregate_threshold_paise` to §194C and to nothing else. So the test at
`tds_computer.py:304` — `applies = taxable > single_threshold or (aggregate is not
None and fy_total > aggregate)` — has a dead second clause for §194J, §194H, §194A,
§194D, §194G and §194Q. But §194J's own proviso reads *"if such sum or, as the case
may be, **the aggregate of the sums** credited or paid … during the financial year
does not exceed fifty thousand rupees"*. The same words appear in §194H, §194A and
§194D. **A consultant paid ₹30,000 a quarter has nothing withheld all year.** The
assessing officer disallows 30% of the ₹1,20,000 under §40(a)(ia) and charges
§201(1A) interest from the date deduction was due.

**(b) When a threshold is crossed, tax is charged only on the crossing bill.**
`tds_computer.py:317` computes `tds = taxable_paise * rate_bps // 10000` on *this*
bill, never on `fy_total`. §194C(5)'s proviso attaches liability to the aggregate.
And `tests/test_tds_bill_engine.py:59-70` asserts `b5["tds_paise"] == 500_00` — **the
wrong number is pinned as correct by a passing test**, which is why it survived.

**(c) §194Q charges 0.1% of the whole invoice.** The section says *"a sum equal to
0.1 per cent of such sum **exceeding** fifty lakh rupees"*. Six times the correct
deduction, scaling with turnover.

> **Corrected claim.** A reader reported §194I rent as wrongly modelled per payment.
> It is not. FA 2025 sets the threshold at ₹50,000 *"for a month or part of a
> month"*, and per-payment is right. Removed.

### 4.2 GST: three defects, all confirmed by running `compute_gstr3b`

**(a) CGST and SGST credit is never cross-utilised against IGST.** I ran an
inter-state sale of ₹10,00,000 (IGST ₹1,80,000) against local purchases carrying
₹1,00,000 CGST and ₹1,00,000 SGST of credit:

```
net_igst = 1,80,000    net_cgst = 0    net_sgst = 0
```

**The correct answer is nil payable**, with ₹20,000 of SGST credit carried forward.
§49(5)(b) and (c) require the balance of CGST credit, then of SGST credit, to be
applied against IGST. `gstr3b_computer.py:714-728` only ever sets CGST against CGST
and SGST against SGST. **The CA is told to pay ₹1,80,000 in cash that is not due.**
This hits every trader who buys locally and sells out of state — which is most of
them.

**(b) Reverse-charge liability is omitted from net tax while its credit is
claimed.** One intra-state sale (CGST+SGST ₹1,80,000) plus one RCM inward supply
carrying ₹5,000 IGST:

```
rcm_igst = 5,000   itc_igst = 5,000   net = 87,500 + 87,500 = 1,75,000
```

The correct figure is ₹1,85,000 — the RCM ₹5,000 must be paid **in cash** (§49(4)
bars discharging it from credit) and only then becomes available as credit. The
liability is never added and the credit is deducted anyway, so the return is
understated by **twice** the reverse-charge tax. Every SME with GTA freight, legal
fees, director's remuneration or rent from an unregistered landlord is affected.

**(c) Zero-rated IGST disappears.** An export **with** payment of IGST — the route
taken precisely to claim the §16(3)(b) refund — of ₹10,00,000 carrying ₹1,80,000
IGST produces `outward_zero_rated = 10,00,000` and `outward_taxable_igst = 0`, and
`gstr3b_computer.py:415-418` hardcodes `"iamt": 0` in the payload. The exporter
declares the turnover and none of the tax; the ICEGATE refund has no declared
liability behind it. Reachable from the UI — `lib/invoices/classification.ts` offers
"Export with payment", "SEZ under LUT/Bond" and "Deemed export" in the invoice
editor.

**(d) GSTR-2B reconciliation compares nothing.** `routers/gst_workspace.py:850`
reads the *books* side out of the uploaded JSON itself:
`book_invoices = raw.get("book_invoices", [])`. A genuine GSTR-2B download has no
such key, so the loop runs zero times and returns *matched 0, mismatched 0, missing
0* — a clean result that means nothing. The 2B side is keyed on `docDetails` and
`sgstin`; a real GSTR-2B is `data.docdata.b2b[].inv[]` with `ctin`. Nothing anywhere
INSERTs into `gstr2a_records` (grep: zero writes). **The single most frequent monthly
task in an Indian GST practice does not work.**

**(e) The screen states repealed law.** `app/gst/reconciliation/page.tsx:628` shows
a banner: *"CGST Rule 36(4): ITC is restricted to 105% of eligible credit appearing
in GSTR-2A/2B."* Notification 40/2021-Central Tax removed the 5% cushion with
effect from 1 January 2022, and the backend says so at
`gstr3b_computer.py:539-541` (`_RULE_36_4_NUMERATOR = 100`). **The two halves of the
product state different law about the same rule**, and the half the CA reads is the
wrong one. Acting on it over-claims credit that comes back with interest.

### 4.3 Income tax: the module cannot compute the clients we actually have

**`POST /api/income-tax/compute` has no entity type.** Its request model
(`routers/income_tax.py:64-108`) takes an individual's heads and always computes on
individual slabs with the §87A rebate. Meanwhile `compute_entity_tax`
(company/firm/LLP rates), `compute_mat`, `compute_amt`, the §44AD/§44ADA/§44AE
presumptive engine, `regime_election`, `book_to_tax_bridge`, `itr_json` and
`itr_schema` are complete, tested — and imported by **nothing** outside their own
package. I checked: `grep` for importers outside `domain/income_tax/` returns zero.

The production client book is **4 Private Limited, 1 LLP, 1 Partnership, 1
Proprietorship**. A CA opening Tax Computation for the Pvt Ltd is shown tax on the
individual new-regime slab — nil to ₹4 lakh, then 5% — with a ₹60,000 rebate. A
company pays 22%/25%/30% from the first rupee and gets no rebate. **Six of seven
clients cannot be computed at all.**

**A capital loss reduces tax on salary.** I ran it:

```
salary ₹20,00,000                      → tax ₹1,92,400
salary ₹20,00,000 + STCG of −₹5,00,000 → tax   ₹88,400
```

`itr_engine.py:394` has no `max(0, …)` and the negative flows into gross total
income. §71(3) allows a capital loss against capital gains only; §74 carries the
rest forward. **Tax understated by ₹1,04,000 on a perfectly natural data entry**,
with no warning emitted.

**§80G has no qualifying limit.** Salary ₹10,00,000, one donation of ₹9,00,000 at
50% → deduction **₹4,50,000**, taxable income ₹5,00,000, tax nil.
`Donation80G.eligible_paise()` is `amount × pct // 100` and never sees gross total
income. §80G(4) caps the qualifying amount at 10% of adjusted GTI — about ₹47,500
of deduction here. **Overstated by roughly ₹4 lakh.**

**Capital gains ignore the date of transfer.** A sale on 10 June 2024 is charged at
the post-23-July-2024 rates:

| Transfer | Engine | Statute then |
|---|--:|--:|
| Equity STCG, sold 10-Jun-2024 | 20% | 15% (§111A) |
| Equity LTCG, sold 10-Jun-2024 | 12.5%, ₹1.25L exempt | 10%, ₹1L exempt (§112A) |

The Budget-2024 rates are applied unconditionally; `sale_date` is used only for the
holding period and the CII lookup. Live for updated returns under §139(8A) and any
reassessment.

### 4.4 Payroll: two wrong statutory outputs

*(Both fixed 8 September 2026, along with three more the fix work surfaced: the
pre-commencement EPF §6 wage base, a second PF implementation in
`/statutory-position` that had drifted from the one that remits, and an unbound
`logger`. See the a-plus roadmap §12.)*

**The ECR cannot reconcile at the EPFO portal.** The slip stores
`pf_wages_paise = _wb.wages_paise` — the Code on Social Security s.2(y) base with
its deemed add-back — and the contribution is computed on that. `domain/payroll/ecr.py:240`
then **re-derives** the declared wage as `basic + da + one_time_pf_wages`, ignoring
the stored column. I ran a basic ₹10,000 / HRA ₹18,000 structure:

```
s.2(y) wage base: ₹14,000  (add-back ₹4,000)
contributions remitted on it: employee ₹1,680, EPS ₹1,166, EPF ₹514
ECR declares EPF_WAGES = ₹10,000
```

₹1,166 of EPS against ₹10,000 of declared wages is 11.66% where EPFO validates
8.33%. **The portal rejects the line, or accepts a false wage declaration** — and
the CA finds out on the 15th, after the run is finalised and the journal posted.
Low basic with high HRA is the ordinary Indian structure at these salary levels.

**24Q Annexure II gives every employee the new regime's ₹75,000 standard
deduction.** `routers/payroll.py:4410` passes
`rates.new_regime_standard_deduction_paise` unconditionally; `annexure2.py:302`
applies it as `min(standard_deduction, salary)` for every row — although the row
*carries* `uses_new_regime` and correctly consults it for professional tax twelve
lines earlier. An old-regime employee is entitled to ₹50,000. **Income under the
head Salaries understated by ₹25,000 per old-regime employee**, on the annexure
TRACES uses to build Form 16 Part B. This is the same mistake the module already
fixed for §16(iii), one line away.

### 4.5 Two defects the client and their customer actually see

**The sales-invoice PDF names the CA firm as the supplier.**
`services/invoice_pdf_service.py:355` calls `_load_firm(firm_id)` — the CA practice
— and lines 148-160 print that row as the supplier block under the heading *"TAX
INVOICE (Issued under Section 31, CGST Act 2017 read with Rule 46)"*: the practice's
name, **GSTIN and PAN**. The builder was written for the practice's own fee
invoices and reused verbatim for the client's sales. It also hardcodes
`SAC_CODE = "998211"` (legal and accounting services — the CA's own code) and
`GST_RATE_PCT = 18`, so a 5% invoice prints "CGST @ 9%" beside a 5% amount.

It reaches people through **four** paths: the "Download PDF" button on the sales
screen, the invoice-email path, the dunning emails in `collections_service.py:359`,
and **the client portal** at `routers/portal_data.py:52`. The client's customer
tries to claim ITC against a GSTIN that never made the supply. Rule 46(a)/(b)/(l)
defects, and a misuse of the practice's own registration.

**Posting a year-end adjustment is impossible in production.**
`routers/year_end_adjustments.py:504-532` inserts a journal entry carrying `source`
and `source_ref_id` — the live columns are `source_type` and `source_id` — and omits
`client_id` and `entry_type`, both `NOT NULL` with no default. I confirmed the
column list against the production database directly. It also writes
`journal_entries` and `journal_lines` with two separate inserts, **bypassing the
posting kernel** and its balance assertion. The CA completes the whole year-end
workflow — draft, submitted, approved — clicks Post, and gets a 500. Nothing reaches
the ledger, so the signed Balance Sheet and P&L are the unadjusted ones.

### 4.6 Depreciation: the default rates are not Schedule II rates, and posting fails

**The "Companies Act 2013 Schedule II" rate table is not Schedule II.**
`routers/fixed_assets.py:41-51` ships `_DEFAULT_WDV_RATES`, duplicated verbatim in
`app/clients/[id]/fixed-assets/page.tsx:64-74` and labelled on the form as *"Companies
Act 2013 Sch II rate pre-filled for selected category"*. Schedule II Part C
prescribes useful **lives**, from which the WDV rate is `R = 1 − (residual/cost)^(1/n)`
at the 5% residual cap. I computed both columns:

| Category | Shipped | Schedule II life | Correct rate |
|---|--:|--:|--:|
| Building | 5.00% | 60y (RCC) | 4.87% ✓ |
| Plant & Machinery | 15.33% | 15y | **18.10%** |
| Furniture & Fixtures | 10.00% | 10y | **25.89%** |
| Office Equipment | 13.91% | 5y | **45.07%** |
| Computer & IT | 31.67% | 3y end-user / 6y server | **63.16% / 39.30%** |
| Vehicles | 25.89% | 8y | **31.23%** |

Only Building is right. Office Equipment is understated more than threefold,
Furniture and Computers more than twofold. And the origin of the wrong numbers is
visible in them: **Furniture 10.00% and Intangibles 25.00% are the *Income Tax Act*
rates**, and 25.89% — the correct 10-year figure — has been put against Vehicles,
which Schedule II gives 8 years. The table is a mixture of two statutes under one
statute's name.

A ₹1,00,000 laptop charges ₹31,670 in year one instead of ₹63,160. Every asset
created without the CA overriding the rate depreciates wrongly for its whole life,
so profit and net block are overstated in the signed financial statements.

**And the monthly depreciation post cannot complete.**
`routers/fixed_assets.py:313` posts the journal, then line 318 updates the register
with `"depreciation_posted_through": period`, where `period` is `YYYY-MM` by
`_PERIOD_RE` at line 53. I checked the column in production — it is `date` — and ran
the cast there:

```
select '2026-04'::date  →  ERROR 22007: invalid input syntax for type date
```

So the Dr Depreciation / Cr Accumulated Depreciation entry lands on the ledger and
the register update then fails. **Accumulated depreciation stays ₹0 and WDV stays at
cost, permanently**, no matter how many times the CA retries — and the kernel's
dedupe stops the retry from at least being visible as a double post.

That is the second of the four year-end operations that cannot complete in
production, alongside §4.5's year-end adjustment. Both write columns that have never
existed. Both would have been caught by one integration test against a real schema.

### 4.7 One security finding I confirmed against production

Twelve `SECURITY DEFINER` functions are executable by the **`anon`** role — the
public key that is inlined into the static frontend bundle. The one that matters:

```
get_cash_payments_above_threshold(p_firm_id uuid, p_client_id uuid, p_threshold_paise bigint)
```

It takes the tenant as an *argument* and does no caller-identity check at all
(`migrations/288_s40a3_detects_payments_not_receipts.sql:60-138`), so anyone
holding the public anon key plus a firm and client UUID can read that client's cash
payments — narrations, dates, amounts, counterparty accounts. **Client UUIDs appear
in URLs** (`/clients/<uuid>/…`), so they are not secret in the way this design
assumes. `get_public_columns` and `get_public_schema_columns` also expose the schema
to anonymous callers. Leaked-password protection is off on Supabase Auth. Two
`_backup_247_*` tables and `_mig247_targets` are still sitting in production with
RLS on and no policy.

Not a breach — a UUID still has to come from somewhere. But it is an
unauthenticated read path whose only protection is that a UUID is long, and the
fix is one `REVOKE`.

---

## 5. The pattern behind all of it — read this section twice

Fifteen unrelated defects, four root causes. Fixing the causes is worth more than
fixing the instances.

### 5.1 Every module's engine is finished and its last mile is not

This is the shape of the whole codebase. §195 reasons about chargeability — and the
vendor's TDS rate is collected on a form and never used. The GSTR-3B Table 4 layout
is argued from the circular — and the set-off two functions later ignores §49(5).
The payroll engine projects §192 properly — and the ECR re-derives the wage base by
hand. The entity-rate and MAT engines are complete and correct — and no endpoint
imports them.

**The intellectual work is done and the wiring is not.** That is genuinely good
news: wiring is cheap and cannot be faked, whereas the reasoning underneath is
expensive and is already paid for. But it means feature counts and test counts
overstate readiness badly, and no amount of new module-building improves it.

### 5.2 The same computation exists twice, and the second copy is stale

CLAUDE.md forbids business logic in the frontend, and it is violated in exactly the
places that matter most:

- `/payroll/reports` recomputes employer PF on basic alone and ESI without Rule 50 —
  the four exact drifts the statutory page was fixed for in September.
- The TDS projection screen computes §192 in TypeScript with hardcoded FY 2025-26
  new-regime rates, no old regime.
- `/tds` computes TDS in the browser from a stale rate table and writes the result
  straight to `tds_deductions` over PostgREST, so `rbac()` never runs.
- The reconciliation screen states the repealed 105% rule the backend rejects.

Every one is a second implementation that drifted. The repo already knows this
pattern — it deleted a whole second filing-demo implementation in commit #433 for
precisely this reason — but the rule was applied to demos and not to arithmetic.

### 5.3 A settings screen that nothing reads is worse than no settings screen

`invoice_pdf_service.py` reads **neither** branding **nor** invoice settings. So the
firm configures a numbering prefix, a series, bank and UPI details, footer text, a
logo and a template — and the PDF that goes out uses none of it, with SAC 998211 at
18%. Recurring journals, budgets and retainers persist to browser `localStorage`
(`app/accounting/recurring/page.tsx:46`, `budget/page.tsx:42`,
`retainer/page.tsx:80`) — not shared, not backed up, gone when the CA clears their
cache or opens the app on another machine. The Schedule III Mapping screen changes
nothing. The AIS screen persists nothing.

A CA who configures something and watches it not happen concludes the product is a
mock-up. **This is the fastest way to lose a trial and it is entirely avoidable.**

### 5.4 The tests are extensive and cannot see these bugs

9,931 tests pass. Every defect in §4 survives them, and one — the §194C catch-up —
is **pinned as correct** by `tests/test_tds_bill_engine.py:59-70`. The suite tests
that functions do what they do; almost nothing tests a *statutory outcome* against
an independently worked example. `test_frontend_columns_exist_pg.py` parses select
lists and so cannot see `select("*")`; the year-end adjustment writes columns that
have never existed and nothing noticed.

**What is missing is a statutory golden-case suite**: thirty or forty worked
examples — a §194C ladder, an IGST set-off, an export with payment, an old-regime
Annexure II, a company computation, a Schedule II WDV rate — each with the answer
derived from the Act by a human and asserted end to end. That suite would have
caught twelve of the seventeen. The remaining five write columns that do not exist,
and **one integration test against a real schema** would have caught those.

---

## 6. Module scorecard

Grades from the deep readers; my own for the Tier-3 rows, marked *(light)*. "Buy it
alone" is the question the founder actually asked: would a CA pay for this module on
its own merits?

| Module | Grade | Buy it alone today? | The one thing that decides it |
|---|:--:|---|---|
| Accounting core / GL | **B** | Not yet | Kernel is audit-grade; no ledger-creation screen, flat CoA, TB always inception-to-date |
| Banking | **B** | Not yet | Best-in-market import; no BRS with unpresented cheques, no cash book, no undo |
| Sales cycle | **C** | No | PDF carries the CA's GSTIN; no discount field; numbering settings read by nothing |
| Purchase cycle | **C** | No | TDS thresholds wrong; §17(5) unsettable; no TDS on payments |
| GST | **C** | No | Set-off wrong, RCM omitted, 2B recon compares nothing, no IMS |
| TDS | **C** | No | Aggregate thresholds absent; no FVU output; no §201(1A) interest |
| Income tax / ITR | **C** | No | Cannot compute a company, firm or LLP at all |
| Payroll | **C** | Not yet | Engine ahead of the market; ECR won't reconcile; half the engine has no screen |
| Reporting / year-end *(light)* | **B−** | Not yet | Statements and Schedule III strong; year-end adjustments cannot post |
| Practice management *(light)* | **B−** | Not yet | Obligation generation and the daily sweep genuinely run in production; billing and time are unexercised |
| AI layer *(light)* | **D** | No | See §7.4 — it cannot read the books |
| Fixed assets / inventory | **C** | Not yet | Inventory engine is good; depreciation rates wrong and posting fails (§4.6) |
| Platform / security *(light)* | **B−** | n/a | Tenancy design is good; anon RPCs and dead backup tables in production |
| Frontend / UX *(light)* | **C** | n/a | 27 pages over 800 lines; 4,537-line sales page; 297 direct DB calls from the browser |

---

## 7. What the market expects that we do not have

Sources are linked; prices exclude 18% GST unless stated.

### 7.1 The compliance features that are simply absent

**IMS — the Invoice Management System — has been mandatory since 1 April 2026**, and
we have nothing. Not a table, not a column, not a screen (grep: zero references
outside two docs). A supplier's invoice lands in the recipient's IMS dashboard and
the recipient must accept, reject or hold it before GSTR-2B is generated on the
14th; **no action is deemed acceptance**. This is now a monthly obligation for every
regular taxpayer, and it is the single largest functional gap in the GST module.
([SmartGST guide](https://smartgst.in/blog/gst-invoice-management-system-ims-mandatory-guide-2026), [GSTN advisory](https://tutorial.gst.gov.in/downloads/news/revised_advisory_on_ims.pdf))

Also absent, each verified by grep: **GSTR-9C** (reconciliation statement),
**composition returns** (CMP-08, GSTR-4), **GSTR-1A**, **multi-GSTIN per client** —
one client, one registration, so a two-state business cannot be modelled at all.
On the income-tax side: **no Form 3CD**, no §32 block-of-assets depreciation, no
brought-forward loss utilisation, no §54/§54F/§54EC exemptions. On TDS: **no
FVU/RPU-format output** — the export is a JSON blob, and a TDS product a CA buys is
one that produces a file the FVU accepts — no correction statements, no §201(1A)
interest, no §234E late fee, no 27Q, no TCS at all.

### 7.2 What a CA replaces, and what it costs them today

| What they run now | Price | Source |
|---|---|---|
| TallyPrime Silver / Gold | ₹22,500 / ₹67,500 perpetual, + TSS ₹4,500 / ₹13,500 a year | [ERP Research](https://www.erpresearch.com/pricing/tallyprime) |
| Zoho Books | ₹899–₹9,999 / month; free under ₹25 lakh turnover; **files GSTR-1 and 3B directly as a registered GSP** | [Patron Accounting](https://www.patronaccounting.com/blog/zoho-books-pricing-india-2026) |
| Winman CA-ERP | from ~₹9,850/yr, pricing on request | [Techjockey](https://www.techjockey.com/detail/winman-ca-erp) |
| Saral IncomeTax / KDK Spectrum Cloud | ₹6,090 / ₹6,300 a year | [CA practice software](https://ca-practice-management-software.in/best-income-tax-software-for-ca/) |
| Zoho Payroll | free to 10 employees, then ₹40/head; ₹1,000/mo for 25 | [SalaryBox](https://salarybox.in/blog/how-much-does-payroll-software-cost-in-india-complete-pricing-guide-2026/) |
| greytHR / Keka / RazorpayX | ₹2,495 for 50 / ₹6,999–9,999 for 100 / free to 20 | [itforsme](https://www.itforsme.in/pricing/payroll-software-india/) |
| Jamku / ERPCA (practice mgmt) | from ₹6,500/yr for 5 users / ₹200 per user per month | [Finexo](https://finexo.in/blog/practice-management/top-10-practice-management-software-for-ca-firms-in-india-2026) |

**A small firm's whole stack is roughly ₹40,000–₹80,000 a year.** That is the number
to price against, and it is not much. The market is **100,138 registered CA firms
and 183,642 professionals, with over 72% single-partner**
([The Finance Story, on ICAI data](https://thefinancestory.com/mid-sized-indian-ca-firms-employing-20-percent-audit-workforce)) —
so the median customer is one CA with a few staff, which shapes everything about
onboarding, support cost and willingness to pay.

### 7.3 The two capabilities competitors have that we have decided not to build

Both are recorded as deliberate in CLAUDE.md and I am not reopening them — but the
market comparison has to state them plainly, because a prospect will ask.

**We do not file.** Zoho Books files GSTR-1 and GSTR-3B from inside the product
because Zoho is a registered GSP. ClearTax does the same. RazorpayX auto-files PF,
ESI, PT and TDS. We prepare and the CA uploads. Filing needs GSP registration and an
`SW########` from the Department — commercial steps, not code. **This is defensible
for a CA audience** (they want the confirmation click anyway, and the software says
so honestly) and **indefensible for an SME audience**, which matters if the pricing
strategy targets SMEs directly.

**We have no bank feed.** The Account Aggregator line was closed on purpose after
finding that no published AA purpose code covers third-party bookkeeping. Statement
upload is the path, and it is unusually good. But every cloud competitor's demo
opens with a live bank feed and ours will not.

### 7.4 The AI story does not yet exist

This one is not in CLAUDE.md as deliberate, and it matters because "AI-first" is the
positioning. `domain/ai_copilot_service.py:195-260` builds the context it sends to
Groq: client counts, health scores, lifecycle stage, compliance-record counts,
GSTIN and PAN. **It does not read the ledger.** No trial balance, no journal, no GST
figures, no TDS. So it can discuss practice status and cannot answer "what is this
client's ITC this month" or "why did gross margin fall" — the questions that would
make a CA open it daily.

Meanwhile the market has moved: **Suvit, the AI-for-Indian-accountants product, has
been acquired and is now Vyapar TaxOne**, doing invoice and bank extraction into
Tally, GST reconciliation, IMS integration and WhatsApp document collection
([Vyapar TaxOne](https://taxone.vyapar.com/gst-reconciliation-feature)).

Two things worth noting while we are here. Client **PAN and GSTIN are sent to Groq**
on every copilot call — a DPDP question worth answering before launch. And
"replacing WhatsApp" today means `wa.me` deep links built one client at a time
(`app/notifications/whatsapp/page.tsx:149`) — a click-to-open helper, not a WhatsApp
Business API integration.

### 7.5 The switching cost we have not paid down

`domain/tally/migration_service.py:184-270` parses Tally XML `LEDGER` and `VOUCHER`
elements only. Grep for `BILLALLOCATIONS`, `INVENTORYENTRIES`, `STOCKITEM`,
`COSTCENTRE`, `GODOWN`: **zero**. So a migration brings ledgers, balances and
journal lines — and loses **bill-wise references** (so invoice-level AR/AP
outstanding is gone), all inventory, all cost centres and all godowns. For a market
where every prospect's data is in Tally, the importer is the product's front door,
and right now it drops the two things a CA checks first: the party ageing and the
stock.

---

## 8. The rest of the findings

Appendix A holds the remaining ~230 findings by subsystem, each with a file
reference. **They are single-source and not adversarially verified** — see §0. The
ones I would look at first, because they are cheap and change the daily experience:

- Cash receipts and cash vendor payments post to the **Bank** ledger; Cash in Hand
  never moves, and the selected bank account is discarded (ACC-02, ACC-03, SALES-08).
- The Trial Balance is always inception-to-date; choosing an FY only moves the
  as-at date, so revenue and expense never reset (ACC-08).
- Deleting a middle draft credit note **permanently wedges** that client's
  numbering for the rest of the year (SALES-04).
- Seven union territories and states cannot be selected as a place of supply
  (SALES-06).
- No discount field on a sales invoice — not per line, not at document level
  (SALES-11).
- A draft payroll run that was never finalised is counted as TDS already deducted
  (PAY-04).
- The payslip PDF carries the CA firm's name, same root cause as §4.5 (PAY-03).
- Form 16/16A creation always fails against the real database — the UI sends
  "Form 16A" and the CHECK constraint expects something else (TDS-04).
- `tds_deductions` and `tds_returns` are written directly from the browser with no
  role check (TDS-11).
- Both firm-level payroll screens load every payslip of every run the firm has ever
  produced into the browser (PAY-16).

---

## 9. What to do, in order

Sequenced by what stops a CA trusting the product, not by effort.

**Stage 1 — nothing wrong reaches a CA (4–6 weeks).** Everything in §4. The §49(5)
set-off and the RCM liability in GSTR-3B; zero-rated IGST; the four TDS threshold
and computation bugs, *with the test that pins the wrong number corrected first*;
the capital-loss floor, §80G's qualifying limit and the capital-gains transfer date;
the ECR wage base and the Annexure II standard deduction; the Schedule II rate table
recomputed from useful lives and the `YYYY-MM`-into-a-`DATE` post; a separate invoice
PDF builder that reads the **client** as supplier with real per-line rates; the
year-end adjustment insert routed through the posting kernel; `REVOKE` on the anon
RPCs. **Then the statutory golden-case suite from §5.4** — without it, Stage 1 will
regress.

**Stage 2 — the daily loop actually closes (6–8 weeks).** A real GSTR-2B
reconciliation that reads the books from the database and parses the portal's own
JSON, persisting to `gstr2a_records`. **IMS** — accept/reject/pending, because it is
compulsory now. A ledger-creation screen and a hierarchical chart of accounts.
Recurring journals, budgets and retainers moved out of `localStorage` into the
database. Cash receipts to the cash ledger and the selected bank account honoured.
FY-scoped trial balance. Delete every frontend computation named in §5.2.

**Stage 3 — the modules a CA would buy alone (8–12 weeks).** Entity tax: wire
`entity_rates`, `minimum_tax` and `presumptive` to an endpoint and a screen, because
six of seven real clients need it. FVU-format 24Q/26Q output with §201(1A) interest
and §234E. The payroll surface from `docs/architecture/10-payroll.md` — that plan is
sound and partly delivered already. Bill-wise references and inventory in the Tally
importer.

**Stage 4 — the reasons to stay (ongoing).** An AI that reads the ledger and cites
the voucher it read. A BRS with unpresented cheques. Multi-GSTIN clients. WhatsApp
Business API rather than deep links.

**One thing to decide before Stage 1, not after:** whether to keep selling breadth
or to narrow. Fourteen modules at grade C beat nothing, but they do not beat Tally
plus ClearTax plus Winman. Three modules at grade A might.

---

## 10. What the market will say

**If it launched this month**, unchanged: a CA trials it, imports a Tally file, sees
the ageing missing, raises a test invoice, finds their own GSTIN on their client's
tax invoice, and stops. Word travels through ICAI study circles and WhatsApp groups
faster than any marketing, and the story would be *"it puts the CA's GSTIN on the
client's invoice"* — which is memorable in the worst way. **This is the outcome to
avoid at any cost, and it is entirely avoidable.**

**After Stages 1 and 2**, honestly positioned: a real product for a specific
customer — the small firm running 15–60 SME clients, on Tally today, tired of
re-keying between Tally, ClearTax and Excel. The pitch that works is not
"everything in one place", because everyone claims that. It is narrower and true:
*your client's books, GST return, TDS and payroll are the same ledger, so the
figures cannot disagree — and where we don't know a state's slab, we say so instead
of deducting zero.* No competitor makes the second claim, and every CA has been
burned by a spreadsheet that quietly returned zero.

Expect the objections to be: *does it file?* (no — say so first, not when asked),
*can I get my Tally data in?* (must become yes), *what happens if you shut down?*
(have an export answer), and *why would I trust a new product with my clients'
books?* — which is answered by the refusal discipline, the edit log, and by nothing
else.

**After Stages 1–3**, the honest ceiling is a strong regional position: a few
hundred firms, ₹15,000–₹40,000 per firm per year, growing by referral. That is a
real business — 200 firms at ₹25,000 is ₹50 lakh ARR — and it is a long way from
displacing Tally, which has thirty years of muscle memory and a perpetual licence
the CA has already bought.

**The realistic wedge is not "cheaper Tally".** It is the two things nothing else in
this market does: **one ledger behind every statutory output**, and **a product that
names what it does not know**. Both are already built. Neither is currently visible
to a user, because the defects in §4 are in the way.

**The honest risk:** the same engineering culture that produced the §195 chargeability
reasoning and the three-way bank import verification also shipped a browser page
that computes payroll PF on basic alone. Depth without a finishing pass is how
fourteen C-grade modules happen. The discipline that makes Stage 1 stick is not more
cleverness — it is the golden-case suite, and treating any screen that computes as a
defect.

---

## 11. The six questions, and the owner's answers

Asked and answered on 7 September 2026. The answers are recorded here because three
of them change the plan, and §12 is written to them.

| # | Question | Answer |
|---|---|---|
| 1 | CA firm or SME as the customer? | **The CA firm.** |
| 2 | Breadth or depth? | **Both.** Every module strong enough to buy alone. |
| 3 | Anyone using it? | **No — dummy data only.** |
| 4 | Does `10-payroll.md` still stand? | **Ignore it; work from the fresh scope.** |
| 5 | Re-run market research on primary sources? | **Yes.** |
| 6 | Verify the remaining findings? | **Yes, verify them.** |

**Answer 1 settles three open tensions.** Not filing is defensible for a CA audience,
who want the confirmation click anyway; the client portal is a collection-and-approval
surface for the CA's client, not a product the SME buys; pricing is per firm.

**Answer 3 is the biggest sequencing change in this report** — see §12.1.

**Answer 4 leaves `docs/architecture/10-payroll.md` in an odd position.** CLAUDE.md
treats `docs/architecture/` as authoritative, so a doc the owner has set aside must be
marked superseded rather than quietly ignored, or the next reader will follow it. What
survives from it and what does not is set out in §12.3.

---

## 12. The plan under the fresh scope

### 12.1 Nobody is using it, so build the machinery first

§9 was written to "stop wrong numbers reaching a CA". With no CA using it, nothing is
reaching anyone, and the order inverts: **make correctness provable first, so the
fixes stay fixed.**

That is not an academic preference. 9,931 tests pass and every defect in §4 survives
them — and `tests/test_tds_bill_engine.py:59-70` **pins the wrong §194C figure as
correct**. Fix §194C without fixing that test first and the next change re-breaks it
in silence. Likewise, the two "writes a column that has never existed" defects
(§4.5 year-end adjustment, §4.6 depreciation) are not two bugs; they are the absence
of any integration test against a real schema. With no users, that harness — a
disposable Postgres, migrations applied, every write path exercised — can be built
properly now instead of retrofitted under pressure later.

Two smaller consequences: production is dummy data, so the dead `_backup_247_*`
tables and `_mig247_targets` can be dropped and the `anon` RPC grants revoked with no
migration window; and schemas can still change freely, which will not be true for
long.

### 12.2 "Both" is right as a destination and wrong as a simultaneous instruction

Taking fourteen modules to buy-it-alone quality is a materially bigger programme than
§9 was sized for. On top of everything in §4 it means, at minimum: IMS, GSTR-9C,
composition returns, GSTR-1A and multi-GSTIN in GST; FVU output, correction
statements, §201(1A), §234E, 27Q, TCS and §197 certificates in TDS; entity
computation, Form 3CD, §32 block depreciation, loss carry-forward and the §54 family
in income tax; a hierarchical chart of accounts with a ledger screen, cost centres,
bill-wise references and an FY-scoped trial balance in accounting; a real BRS, a cash
book and import undo in banking; opening positions, an attendance contract and the
month-end pack in payroll; closing stock as at a date, FIFO and batches in inventory.

**That is about a year for a small team, not two quarters.** The modules still have to
be ordered, and the order that fits a CA's own calendar is: **monthly before quarterly
before annual** — GST, bank and invoices first, then TDS, then ITR, audit and
year-end. That way every quarter of work lands on something the firm uses that month.

### 12.3 Payroll, rebuilt from the fresh scope

**Keep** from `10-payroll.md`, because it follows directly from answer 1:

- **The bureau model.** greytHR, Keka, Zoho Payroll and factoHR all assume one
  employer running its own payroll. A CA firm runs payroll *for* many client
  companies. So the firm screen is a **client-month** queue and the client screen is
  an **employee-slip** queue.
- **Two-axis grading** — *defensible* (is every input present and in force?) and
  *changed* (what moved since last month, and why?) — because grading only on change
  lets a stable error stay green for ever.
- **Named gaps** instead of silent zeros.
- **The three refusals**: never hold client funds or initiate payouts; never generate
  Form 16 Part B (CBDT Notification 09/2019 requires it from TRACES); never
  auto-submit to EPFO, ESIC or TRACES.

**Drop its calendar device.** The doc set a 1 April 2027 cutover and deliberately did
*not* build mid-year migration, using the calendar to dodge the opening-position
problem — `_tds_already_deducted_this_fy` reads only slips this platform produced, so
a mid-year client has no prior withholding on file and §192 withholds from a fiction.
With no live users and no April deadline to hit, **build `payroll_opening_positions`
properly** — YTD salary, YTD TDS, lifetime §10(10) and §10(10AA) used. A CA firm wins
clients year-round, and a payroll module that can only onboard in April will not be
adopted.

**Bring its deferrals back**, because "depth" requires them: the FVU-validated 24Q,
Form 16 Part A/B distribution, and bank advice. On bank advice the doc's objection —
a per-bank format zoo growing per client — is fair, and the answer is not the whole
zoo: a generic NEFT/RTGS CSV plus SBI, HDFC and ICICI covers most of the market, and
the payment stays the client's own act.

### 12.4 The analytics layer — "something they get addicted to"

This was the weakest part of my first report and it deserves a real answer, because it
is the only part of the brief about *winning* rather than *not losing*.

**The asset nobody else has.** ClearTax sees returns but not books. Tally sees books,
one client at a time, on a desktop. Jamku sees tasks but no numbers. greytHR sees
payroll but no ledger. **PracticeSync holds every client's ledger of one firm in one
schema**, and `account_period_balances` (migrations 227/228) already pre-aggregates it
to 132 monthly buckets per client — so firm-wide cross-client analysis reads buckets,
not 33,080 journal lines. It is cheap here and architecturally impossible for a
competitor to bolt on.

**Why the intelligence surfaces do not bite today.** They read the wrong things.
`domain/ai_insight_service.py:140` generates insights from *compliance-record status*.
`services/intelligence_service.py` computes risk from client metadata.
`domain/ai_copilot_service.py:195-260` sends Groq client counts, health scores and
lifecycle stage — no trial balance, no GST figure, no TDS.
`get_cross_client_patterns` is a hardcoded stub returning invented names, honestly
labelled as such in its own docstring and reachable from no screen (`api.aiInsights`
does not expose it, and no page calls that surface at all). **The screens exist, the
ledger exists, and nothing connects them** — the same wiring-on-finished-parts shape
as every other finding here.

**What to build, most addictive first:**

1. **The firm's morning queue.** One row per client-obligation, graded, with a reason
   sentence — a queue, not charts. This replaces the Excel tracker every firm keeps.
   The bank module already proved the shape (`draft_*` columns, graded rows, "Pass N
   ready") and `compliance_engine` already derives every due date by rule; apply one
   to the other.

2. **Ledger-grounded exceptions, computed nightly, each with its statutory
   consequence and a rupee amount.** Things a CA cannot see by eye: an expense
   approaching a TDS threshold with nothing withheld — *which directly prevents the
   §40(a)(ia) disallowance the engine currently causes*; ITC against 2B once §4.2(d)
   is real; GST output falling while bank credits rise (unbilled sales); cash payments
   over ₹10,000, where `get_cash_payments_above_threshold` **already exists** and needs
   only a `REVOKE` and a screen; MSME creditors past 45 days under §43B(h), where
   `schedule_iii_ageing` already computes the ageing; round-number journals, weekend
   postings, entries by a departed user.

3. **Cross-client — the part only this architecture can do.** The same vendor GSTIN
   treated differently across two clients. One supplier's late GSTR-1 blocking ITC for
   six clients at once. Shared directors. Benchmarks: *"this client's gross margin is
   12 points below your six other trading clients."* The `relationships` and
   `ownership-map` screens already exist to hang it on.

4. **Practice economics.** Fee against hours against client; which client is
   unprofitable; which staff member is behind. This is what makes the **partner**
   addicted rather than the article clerk, and `time_tracking`, `billing` and
   `fee_billing_service` already hold the inputs.

5. **The artefact the CA sends their client.** A branded monthly one-pager — GST
   filed, TDS deposited, top five expenses, receivables ageing, three things to fix.
   The CA looks good; the client asks for it again; the CA keeps paying. The reporting
   engine already produces every number on it.

**The sequencing rule.** None of this ships before the numbers underneath are right.
An anomaly detector running on a set-off that ignores §49(5) produces confident
nonsense — worse than no analytics, because it teaches the CA to distrust the
product's judgement, and judgement is what they are being asked to buy. So analytics
is Stage 3 work; but its **data model** — nightly exception rows, per client, per
firm, each carrying a citation and an amount — belongs in Stage 2, so Stage 3 is a
rendering job rather than a rebuild.

---

## 13. The verification pass (answer 6) — and what it was actually worth

Every finding that had not already been checked was re-read by an independent
verifier under three lenses — **literal** (does the code do this?), **guards** (is
something else already preventing it?) and **reach** (does it get to a user?) —
told to try to *refute* rather than confirm, and to default to refuted where the
code could not be made to say it. Where a probe would settle it, they ran one.

### 13.1 I predicted 15–25% would fall. About 1% did.

| | |
|---|--:|
| Findings | **278** |
| Verified by hand, by me | 20 |
| Verified by an independent adversarial reader | 256 |
| **Refuted** | **3** |
| Severity corrected downward | 45 |
| Severity corrected upward | 6 |
| Unverified | **0** |

**That prediction was wrong and the direction matters.** The readers were far more
accurate than I gave them credit for, which raises confidence in the whole set —
including the parts nobody has re-read. What the pass mostly did was not *delete*
findings but **sharpen** them: correct a line number, name a guard that bounds the
blast radius, replace a hand-waved consequence with a measured one.

The three refutations, in fairness to them:

- **SALES-07** — customer-deducted TDS on a receipt *can* be recorded, through
  `components/banking/SettleDocumentsModal.tsx:194` → `bank_posting_service.py:1022`
  → `create_receipt_core`, reachable from the bank Entries tab. The auditor's grep
  missed it. A narrower gap survives: the standalone receipt form has no TDS field.
  **Two verifiers disagreed on this one** — a re-run confirmed what the first had
  refuted — and I settled it by hand. It is the only such disagreement, and it is
  the argument for keeping the probe in the record rather than only the verdict.
- **PUR-29** — RCM and §17(5) on the purchase path *are* tested
  (`tests/test_accounting_audit_fixes.py:56-88`). The auditor misread its own grep.
- **GST-23** — the GSTR-1 ARN modal *does* exist and mirrors the GSTR-3B one.

### 13.2 The refutation that found something worse

**GST-23 was wrong about the missing feature and right that something was broken.**
Chasing it down, the verifier found that *both* mark-filed paths write the return
row **directly over PostgREST** (`apps/web/lib/data/gst.ts:657-697`) instead of
calling the backend `PATCH …/status`. I confirmed this myself:

- only the backend's `record_filing` writes `public.filings`
  (`gst_filing_record_service.py:120`, called from `gst_workspace.py:526` and `:747`);
- `journal_period_lock_reason` reads `public.filings` to decide whether a filed
  return freezes its period (migrations `266:316`, `267:65`);
- `apps/web/lib/api/index.ts` exposes no GST status endpoint at all.

**So a CA marks a GST return as filed and the period does not lock.** The books stay
editable behind a filed return — precisely what the immutability design exists to
prevent, and what CLAUDE.md describes as the genuine path. Production fits: one
`gstr3b_returns` row sitting at `ca_approved` with no ARN, and `filings` empty.

### 13.3 Three tests that hide or encode the defect

This is the sharpest systemic result of the pass, and it upgrades §5.4 from a
recommendation to a finding.

1. **`tests/test_tds_bill_engine.py:59-70`** asserts `b5["tds_paise"] == 500_00` —
   the §194C figure that ignores the aggregate. The wrong number is pinned as
   correct.
2. **`tests/test_tds_section_rates.py:117-122`** asserts ₹6,000 on a ₹60 lakh
   §194Q purchase, commented "0.1% of ₹60L". The statute charges 0.1% of the
   amount *exceeding* ₹50 lakh — ₹1,000. A second wrong number pinned as correct.
3. **`tests/test_direct_write_tables_are_role_guarded.py`** — the security test
   that enumerates every table the browser writes directly. I ran its own scanner:
   it finds 21 tables and **`tds_deductions` is not among them**, though
   `app/tds/page.tsx` inserts into it twice. Its regex allows 400 characters
   between `.from("…")` and the write verb; those call sites sit 441, 561 and 729
   characters away. **The test passes green while asserting a falsehood**, so
   `tds_deductions` and `tds_returns` are neither guarded nor flagged as open.

A fourth, `tests/test_capital_gains_engine.py:98-101`, pins the §50AA debt-fund
bug with a 2020 acquisition date.

Two tests encode a wrong statutory number, one pins a third, and one gives false
security assurance. **Fix the tests before the code**, or the fixes will not hold.

One more of the same family, found while checking a payroll finding: the
September audit reported that `_logger` was referenced five times and never
defined, fixed it, and said it was "pinned by tests that force a read to fail".
`routers/payroll.py:3478` still calls **`logger`** — the module defines `_logger`
at line 74 — inside an `except Exception:` block, so the first real read failure
raises `NameError` *from within the handler* and a graceful degradation becomes a
500. It is the only bare `logger.` in the file. The fix went one direction and this
site was the other.

### 13.4 What the probes measured

Verifiers were told to run something where running would settle it. Several did,
and the numbers are better than any argument:

- **`services/bank_register_service.py:212-215`** does
  `min(filtered, key=lambda l: all_lines.index(l))` — O(n²). Measured:
  **29.185 seconds of CPU** on 12,836 rows, against 0.071s for the register build
  itself. The Bank Book's default view is unfiltered, which is the worst case.
- **`routers/inventory.py:42-59`** read **all 5,000 ledger rows in 6 round trips**
  for a single item that had never moved; the loop breaks only on a short page,
  so `remaining` never empties. Its own docstring claims the opposite.
- **§195 on a recorded 10% treaty rate** returns 10.40% for a foreign company and
  11.44% for a non-corporate payee — surcharge and cess stacked on top of a treaty
  rate that is already the whole liability.
- **Rule 37 reversal** returned ₹18,000 where ₹9,000 is right on a half-debit-noted
  bill: `journal_for_debit_note` already credits GST Input, so it double-reverses.
- **`/statutory-position` computes PF on basic + DA** while the run uses the
  s.2(88) base — ₹1,200 against ₹1,680 a month on CLAUDE.md's own worked example.
  Two screens, two PF figures, same employee.
- **A ₹1,00,000 computer at the shipped 31.67% WDV** is worth **₹330.64 after
  fifteen years** — there is no useful-life terminal condition on the WDV path.

### 13.5 A wrong statutory due date for every company client

`AUDIT_ENTITY_TYPES` in `apps/web/app/income-tax/page.tsx:81-89` holds
`"private_limited"`, `"public_limited"`, `"llp"`, … in snake_case. The database
CHECK constraint (`migrations/001_initial_schema.sql:23-26`) and the client form
(`ClientFormModal.tsx:8-11`) both store `'Private Limited'` — title case, with a
space. `isAuditCase` lowercases but never substitutes the space, so:

| Stored | Lowercased | In the set? |
|---|---|:--:|
| `LLP`, `Partnership`, `Trust` | `llp`, `partnership`, `trust` | yes |
| **`Private Limited`** | `private limited` | **no** |
| **`Public Limited`** | `public limited` | **no** |

It fails on exactly the two multi-word types — which are exactly the companies. So
every Private Limited and Public Limited client is given a **31 July** ITR
deadline where Explanation 2(a) to §139(1) fixes **31 October** unconditionally.
Four of the seven clients in production are Private Limited.

It is worse than a display bug: the verifier found that *three* implementations of
this date exist (`compliance.py:152`, `:209` and
`compliance_obligation_service.py:398`) and none of them receives an audit flag
either — so fixing the string alone would not fix the date.

### 13.6 Four findings the pass made *more* serious

`PAY-20` and `PAY-21` were raised to high — the first for the two-PF-figures split
above, the second because **a payroll run cannot be recomputed or discarded**: no
DELETE, no recompute, one insert path, and `create_run` 409s on a second run for
the same month, so a wrong draft is uncorrectable through the product. `PAY-29`
was raised because the payslip omits UAN, PF/ESIC numbers and bank details.
`ACC-27` was raised: two lock checks parse `entry_date` differently, so `2025-4-1`
passes the firm-level check, is rejected by the kernel's parser, and Postgres
accepts it as a DATE — a shape that posts into a locked year.

### 13.7 Where it stands

**275 findings survive.** After verification:

| Severity | Count |
|---|--:|
| critical | 20 |
| high | 89 |
| medium | 130 |
| low | 36 |

By kind: 99 bugs, 81 gaps, 30 missing features, 21 glitches, 20 data-integrity,
9 fine-tune, 6 performance, 5 UX, 4 security. Every finding in
`2026-09-07-findings/` now carries a `verification` block recording status, the
corrected severity, what is actually true, and the probe where one was run.

---

## 14. The primary-source re-run (answer 5) — and why it could not be done

**The environment blocks it, and I proved that rather than assuming it.** Every
government host refuses at the proxy:

```
curl https://example.com   →  CONNECT tunnel failed, response 403
$HTTPS_PROXY/__agentproxy/status  →  connect_rejected: "gateway answered 403 to
CONNECT (policy denial)" for en.wikipedia.org, tin-nsdl.com, tdscpc.gov.in, …
```

The block is not a gov.in policy — Wikipedia and anthropic.com fail the same way,
while `github.com` and the package registries succeed. It is this remote
environment's **network policy**, chosen when the environment was created and
changeable by you (see the Claude Code on the web docs). `WebSearch` works
because it runs server-side; `WebFetch` and `curl` do not.

**So no `[P]` grade was earned anywhere.** What the three researchers produced is
a best-effort `[S-gov]` tier — the search engine's summary of a document *at an
official URL*, with the URL recorded — plus ordinary `[S]` secondary sources.
Full write-ups and the list of URLs to fetch first are in the session working
files; the ranked re-verify lists are the most useful part.

### 14.1 The one live wrong number the re-run found

**`CII_BY_FY["2025-26"] = 380` (`capital_gains_engine.py:63`) should be 376**, and
an index for FY 2026-27 has since been notified at **384** (Notification 85/2026,
15 July 2026). Six independent professional publishers — RSM, Taxmann, Mondaq,
DPNC, CAclubindia and Business Standard — agree on 376 for FY 2025-26, and the
researcher found **no source anywhere saying 380**. Every other value in the table
cross-checks correctly; only the newest entry is off, which is the signature of a
figure typed in before the notification landed.

Because `cii_for()` falls back to `LATEST_CII_FY`, **every indexed computation
today uses 380** — wrong year *and* wrong value. Blast radius is bounded to the
grandfathered §112 option on immovable property, but within it the indexed cost is
overstated by ~1.06%, understating the gain and the tax, silently.

**Do not move `LATEST_CII_FY` on this evidence alone.** Correct 376, add 384, and
say in the commit that the verification is secondary-source — moving the
human-verified marker without a human read is exactly the failure CLAUDE.md warns
about.

### 14.2 What the re-run confirmed, and it matters that it did

**The Income-tax Act 2025 / Rules 2026 renumbering is corroborated in full** —
24Q→138, 26Q→140, 27Q→144, 27EQ→143, and the section moves — by multiple
independent professional sources, with nothing contradicting it. CLAUDE.md and
`domain/tds/vocabulary.py` are right, which is worth knowing given how much rests
on them. One residual risk: a **corrigendum, G.S.R. 286(E) dated 16 April 2026**,
exists and could not be read, so any *specific* form number carries that caveat.

**Form 16 Part B must come from TRACES** — confirmed, which vindicates the
decision not to generate it.

### 14.3 Four things nobody has told this codebase about

Each is `[S]` or `[S-gov]` and each needs a human with a browser before it is
acted on — but all four are live and none appears anywhere in the repo.

1. **GST 2.0 rate rationalisation, in force 22 September 2025.** The 56th Council
   collapsed the slabs to **5% and 18%**, with a **40% demerit rate** and cess
   merged into the rates. `apps/web/lib/invoices/gst.ts:16` offers
   `[0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 12, 18, 28]` — **no 40%**, so a
   demerit-goods invoice cannot be raised from the UI at all. (The backend takes
   any rate, and 12% and 28% must stay for historical periods, so this is an
   additive fix.)

2. **The three-year filing bar is live and rolling.** CGST §§37(5), 39(11), 44(2)
   and 52(15) bar a return more than three years past its due date; GSTN
   implemented it from the **July 2025 tax period**, so the window closes monthly.
   For a firm with 50 clients this is a standing risk nobody can track by hand —
   and it is the single best argument for the exception engine in §12.4.

3. **The e-invoice 30-day reporting limit** now applies at **AATO ≥ ₹10 crore**
   (from 01-04-2025), to invoices, credit notes and debit notes. Miss the window
   and the IRP refuses the IRN, which strands the customer's ITC.

4. **IMS: the operative deadline is the GSTR-3B filing, not the 14th** — and the
   trap is the **recompute**. An action taken after the draft 2B is cut on the
   14th does not reach the return unless GSTR-2B is explicitly recomputed. Deemed
   acceptance (silence = accepted) is confirmed; a blog claim that this flipped to
   deemed *rejection* in April 2026 is loose in the wild and, on this evidence, is
   wrong. Re-verify before building.

### 14.4 Payroll — five claims that touch CLAUDE.md directly

All `[S]`, none confirmable here, all worth a human hour:

- **The EPF, EPS and EDLI Schemes were replaced by 2026 versions**, notified
  29 June 2026 under the Social Security Code, with the old schemes reportedly
  valid only to a transition **ending 20 November 2026**. Rates carried forward
  unchanged; the instrument did not. If true, this is ten weeks away.
- **The wage provision is Social Security Code s.2(88), not Code on Wages
  s.2(y).** Both EPFO and ESIC cite 2(88). The substance is identical, so nothing
  computes differently — but `wage_base.py` and CLAUDE.md cite it imprecisely.
- **The 50% rule may reach ESI, gratuity and bonus**, which CLAUDE.md deliberately
  decided it does not. Sources contradict each other on ESI, so the researcher
  graded it `[U]` and recommended changing nothing: gross is the direction that
  cannot under-deduct. **Agreed — leave `_compute_esi` alone until someone reads
  the FAQ.**
- **CLAUDE.md's "twenty-two states levy PT" looks wrong** — sources say 20–21,
  Odisha reportedly repealed it from 01-04-2026, and Punjab's levy is a
  Development Tax, not PT. Maharashtra's due date moved to the 15th from March 2026.
- **Fixed-term employees earn gratuity pro rata after one year**, not five. The
  gratuity module assumes five.

### 14.5 What to do about the sourcing problem itself

The honest position is that this codebase has now had **two** research passes that
could not read a single primary source, and `docs/compliance/00-how-to-read-this.md`
already says why that is a materially weaker guarantee. Three options, in order of
cost:

1. **Change this environment's network policy** to allow the gov.in hosts. Cheapest
   by far, and it makes every future pass better.
2. **Fetch the ranked list by hand** — the researchers each produced one, ordered
   by (how load-bearing) × (how weakly sourced). The top items are the IMS advisory,
   Notification 22/2026 with its corrigendum, the two CII notifications, and the
   MoLE wage-definition FAQs.
3. **Accept `[S-gov]` for planning and require `[P]` before shipping** any figure
   into a computation. This is what the codebase already does for rate registries
   via `LATEST_VERIFIED_FY`, and it works.

---

## Appendix A — the full finding set

The 278 structured findings are committed alongside this report in
`2026-09-07-findings/` — one JSON per subsystem, each finding carrying kind,
severity, file-and-line evidence, what a CA would experience, what the
market-standard tool does, a suggested fix and an effort estimate. Load them into
the issue tracker rather than re-deriving them; that directory's README explains the schema.

**Coverage gap, stated plainly:** reporting and year-end, practice management, the AI
layer, portals and identity, platform and security, the frontend as a whole, and the
marketing site received only my own lighter pass. A second audit pass over those
seven is the first thing I would do after Stage 1.
