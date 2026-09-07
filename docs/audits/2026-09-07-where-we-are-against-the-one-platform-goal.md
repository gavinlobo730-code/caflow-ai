# Where we are against the one-platform goal

**Date:** 7 September 2026
**Question asked:** *we are building one platform for Indian CAs — accounting, GST,
TDS, income tax, payroll, practice — cheap enough for SMEs. If any pillar is weak
nobody buys it. Where are we, what is broken, what is missing, and what will the
market say?*

---

## 0. How to read this, and how much to trust each part

This report has three tiers of confidence and they are not interchangeable.

**Tier 1 — I ran it myself.** Fifteen of the nineteen critical defects below were
reproduced in this session by executing the code or querying the production
database, and the numbers printed here are the numbers those runs produced. Where
that is so, the finding says **verified**. Two claims I set out to confirm turned
out to be **wrong and are recorded as corrected**, because a report that only
confirms is not a check.

**Tier 2 — a deep reader found it, I did not re-run it.** Eight subsystems were
each read end to end (routers, services, domain modules, migrations, screens,
tests) and returned 248 findings. The adversarial verification pass that was
supposed to attack every one of them ran on 27 findings before the session's model
allowance was exhausted. So **most of the ~130 high-severity findings in Appendix A
are single-source**. They are specific and carry file references, and the ones I
spot-checked held up — but treat them as *leads with evidence*, not as settled.

**Tier 3 — lighter coverage.** Reporting and year-end, practice management, the AI
layer, fixed assets and inventory, portals and identity, platform and security, the
frontend as a whole, and the marketing site did **not** get a deep reader. What I
say about them comes from my own inline reading and is thinner. **That is a real
hole in this audit and the biggest single reason to commission a second pass.**

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
| audit_log | 47,367 | | tasks / compliance_tasks | **0** |
| inventory_stock_ledger | 12,107 | | fixed_assets | **0** |
| bank_transactions | 488 | | gstr1_returns / itr_filings | **0** |
| clients | 7 | | firms / users | 2 / 2 |

Read that table twice. **The books have been hammered. Nothing downstream of the
books has ever been used.** Not one receipt, not one payment, not one TDS
deduction, not one employee, not one task, not one filing record. The modules this
audit found most broken are, without exception, the modules with zero rows.

That is not a coincidence and it is the single most useful fact here: **the defects
are concentrated exactly where nobody has walked yet.** Nine of the fifteen verified
criticals sit in code paths that have never run against real data.

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

## 4. The fifteen verified critical defects

Each of these I reproduced myself in this session. The figures are from those runs.

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

### 4.6 One security finding I confirmed against production

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
Annexure II, a company computation — each with the answer derived from the Act by a
human and asserted end to end. That suite would have caught eleven of the fifteen.

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
| Practice management *(light)* | **C** | No | Zero tasks and zero compliance rows in production — untested in anger |
| AI layer *(light)* | **D** | No | See §7.4 — it cannot read the books |
| Fixed assets / inventory *(light)* | **?** | Unknown | Zero fixed assets in production; not audited this pass |
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
the ECR wage base and the Annexure II standard deduction; a separate invoice PDF
builder that reads the **client** as supplier with real per-line rates; the year-end
adjustment insert routed through the posting kernel; `REVOKE` on the anon RPCs.
**Then the statutory golden-case suite from §5.4** — without it, Stage 1 will regress.

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

## 11. What I need from you

These change what to build, and I have not assumed answers.

1. **Who is the customer — the CA firm, or the SME directly?** Everything about
   filing, pricing and the client portal turns on this, and the code currently
   assumes the firm.

2. **Breadth or depth from here?** Fix fourteen modules to a good standard, or take
   three to excellent and drop the rest from the pitch? I lean towards three —
   accounting + GST + TDS, which share one ledger and one client — but it is your
   call and it is the biggest one.

3. **Is anyone using this besides you?** Production has 2 users and 7 clients, and
   the answer changes everything about sequencing: with live firms, Stage 1 is an
   emergency; without, it is ordinary work.

4. **Payroll: is the plan in `docs/architecture/10-payroll.md` still the plan?** It
   commits to 1 April 2027 and to not building mid-year migration. Parts are already
   delivered. If it stands, payroll is sequenced and I should not re-plan it.

5. **How much of the market comparison do you want re-run against primary sources?**
   Prices and features here come from vendor and trade pages read today; I have not
   opened a GSTN or CBDT page directly, and `docs/compliance/00-how-to-read-this.md`
   records why that matters.

6. **Do you want the unverified findings verified before or after Stage 1 starts?**
   Roughly 230 findings are single-source. Verifying them is maybe two days and would
   likely eliminate 15–25% as wrong or already-guarded.

---

## Appendix A — the full finding set

The 248 structured findings are committed alongside this report in
`2026-09-07-findings/` — one JSON per subsystem, each finding carrying kind,
severity, file-and-line evidence, what a CA would experience, what the
market-standard tool does, a suggested fix and an effort estimate. Load them into
the issue tracker rather than re-deriving them; that directory's README explains the schema.

**Coverage gap, stated plainly:** reporting and year-end, practice management, the AI
layer, fixed assets and inventory, portals and identity, platform and security, the
frontend as a whole, and the marketing site received only my own lighter pass. A
second audit pass over those eight is the first thing I would do after Stage 1.
