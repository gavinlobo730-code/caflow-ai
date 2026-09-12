# Where the 278 findings stand

Generated from `findings-status.json`. That file is the record; this one is it,
readable. Regenerate with `python3 scripts/findings_status_md.py`.

## The number

| state | count | what it means |
|---|---|---|
| closed | **47** | re-read against the code. The defect is gone. |
| closed_by_commit | **158** | named in a merged commit on `main` **and** in an in-code comment saying what it closed. Two independent traces; not a re-read. |
| closed_by_commit_only | **21** | named in a commit and nowhere else. The weakest state here — read these before quoting them as done. |
| partial | **14** | part of the finding is answered, part is not. Each says which. |
| open | **30** | re-read and still true. |
| unverified | **7** | a probe was inconclusive. Treat as unknown, **not** as open. |
| not a defect as stated | **1** | the premise is false, or the suggested fix would be worse than the defect. |
| deferred to the redesign | **1** | a navigation complaint the module hub answers. |
| **total** | **279** | |

**The work left is about 51 items — 30 open, 14 partial,
7 unverified — not 254.** The audit documents were never amended as
tranches landed, so they still list findings fixed weeks ago.

**And of the 30 open, most are not code problems.** Nearly every one needs a
migration; a handful need a statutory document a person has to read.

## Open

| severity | finding | what it is |
|---|---|---|
| high | **ACC-06** | Recurring journals, budgets and retainers are stored in browser localStorage — not in the databa |
| high | **GST-11** | QRMP quarterly returns cannot be computed, saved or recorded — every period in the return engine |
| high | **GST-20** | One GSTIN per client — no multi-state / multi-branch registration model |
| medium | **ACC-19** | Multi-currency is fully built across five phases but cannot be switched on for any firm or clien |
| medium | **BANK-11** | The rule engine is one case-insensitive substring plus an amount range and a direction — no rege |
| medium | **FA-08b** | No output tax on a fixed-asset disposal — the split half of FA-08 |
| medium | **FA-11** | No CWIP, revaluation, impairment, component accounting, shift working, transfers or physical ver |
| medium | **GST-24** | Table 4(A) rows for import IGST and ISD are permanently zero, and ISD is now compulsory |
| medium | **GST-32** | E-invoicing prepares nothing — no INV-01 JSON, no 30-day reporting-window check, and no e-invoic |
| medium | **INV-02** | Moving average is the only costing method — no FIFO and no standard cost |
| medium | **INV-03** | No batches/expiry, godowns, item groups, alternate units, reorder levels, BOM or stock transfers |
| medium | **INV-05** | Inventory cost excludes freight and non-creditable GST — closing stock and COGS are understated |
| medium | **INV-08** | Physical verification is one item at a time, with no count sheet and no session |
| medium | **IT-31** | 26AS reconciliation never feeds the computation — the TDS credit on the return is a number the C |
| medium | **PAY-23** | Statutory bonus is computed only inside a leaver's settlement — there is no annual bonus run for |
| medium | **PAY-25** | The payroll journal posts one Salaries Expense account and defines the debit as the sum of the c |
| medium | **PAY-26** | The employee portal shows a payslip list and a leave number and nothing else a self-service port |
| medium | **PAY-27** | No bank advice file, no payslip delivery, no reimbursements or flexible benefits, no overtime or |
| medium | **PUR-16** | A second, orphaned vendor master at /accounting/suppliers that no purchase path reads |
| medium | **PUR-19** | Reverse-charge bills produce no self-invoice (§31(3)(f)) and no payment voucher (§31(3)(g)) |
| medium | **PUR-20** | GST compensation cess cannot be recorded on a purchase, so the cess ITC is lost for every client |
| medium | **PUR-22** | One payment settling several bills is not reachable from the Purchases screen — the multi-bill a |
| medium | **PUR-23** | Issuing a debit note (purchase return) does not resync the TDS register, so 26Q keeps reporting  |
| medium | **PUR-24** | AP ageing lists only bills, so unallocated vendor advances are invisible and the ageing total do |
| medium | **PUR-25** | No purchase orders, goods receipt notes or three-way matching |
| medium | **PUR-26** | No recurring purchase bills, though recurring sales invoices are fully built |
| medium | **SALES-21** | No quotation, proforma invoice, sales order or delivery challan — the sales cycle starts at the  |
| medium | **TDS-16** | No FVU/RPU-format output and no correction-statement support — the only export is a JSON blob |
| medium | **TDS-32** | Purchase debit and credit notes never reverse TDS, so a return after deduction leaves the regist |
| low | **GST-31** | The GST portal integration router is complete, honest and reachable from no screen |

### What actually blocks each of them

| finding | what actually blocks it |
|---|---|
| **ACC-06** | tables for the templates, budgets and retainers |
| **GST-11** | schema for a quarterly filing preference, plus IFF |
| **GST-20** | a registrations table; clients.gstin is singular today |
| **BANK-11** | a match_type column, or a second pattern column — the rule row has neither |
| **FA-08b** | a migration for the disposal's tax split, and a decision on CGST s.18(6) |
| **FA-11** | a migration per item. One hazard the finding does not name: a shift multiplier folded into wdv_rate_percent would make schedule_ii_departure report every double-shift asset as a Part C departure, so it must be its own column |
| **GST-32** | the IRP schema, and the 30-day reporting-window rule |
| **INV-03** | substantial inventory schema |
| **INV-05** | apportionable-cost columns, and the same amount must flow into the inventory journal or stock_position_as_at stops tying to the control account |
| **INV-08** | a session table |
| **PAY-23** | a bonus register, and the state minimum wage the Act computes on |
| **PAY-25** | a per-department or per-account split needs somewhere to record the mapping |
| **PAY-26** | schema for claims |
| **PAY-27** | each bank's own file format |
| **PUR-16** | ONE migration — vendors has 34 of the 36 columns already; only credit_limit_paise has no equivalent (payment_terms_days maps to credit_days). Repointing the screen without it would silently drop a recorded credit limit |
| **PUR-19** | document series and templates |
| **PUR-20** | cess columns on the line tables |
| **PUR-22** | no migration (226 already has the table), but it is NOT the frontend-only change an earlier reading of this called it. The right shape is to make the router route to create_payment_core with a one-element allocation for the single-bill case, unifying the two paths — a change to a money path that posts to the GL, and one to make with the owner reachable rather than overnight |
| **PUR-25** | three new document types |
| **PUR-26** | a schedule table; the sales side is the pattern to copy |
| **SALES-21** | four new document types |
| **TDS-16** | the NSDL file layout, and a correction-statement model |

## Partial

| severity | finding | what it is |
|---|---|---|
| high | **GST-10** | GSTR-9 is a tab that can never hold anything: no computation, and no UI that creates a draft |
| high | **IT-11** | Tax audit is a four-field tracker: no Form 3CD at all, and the §44AB applicability test is decid |
| high | **PUR-15** | The MSME §43B(h) tracker is a manually re-keyed side table with the whole statutory rule compute |
| medium | **ACC-14** | Opening balances cover only aggregate AR, aggregate AP and bank — every other account, and every |
| medium | **FA-19** | Rule 43 capital-goods ITC apportionment does not exist |
| medium | **GST-28** | Rule 37A has a reason code but no report; Rule 37 has no interest and no posting help |
| medium | **PAY-10** | The TDS projection screen computes §192 in TypeScript with hardcoded FY 2025-26 new-regime rates |
| medium | **PAY-15** | Attendance and LOP cannot be entered from the client Payroll tab at all — they live on a firm-wi |
| medium | **PAY-24** | Leave is half-built: balances are invented in TypeScript as 12/12/15, nothing accrues or carries |
| medium | **PUR-18** | Import of goods has no path — no Bill of Entry, so the IGST paid to customs cannot be recorded a |
| medium | **PUR-27** | No expense claim or petty cash module — every small expense needs a vendor and a purchase bill |
| medium | **TDS-20** | The 26AS pipeline accepts only pasted tab/pipe-delimited text and offers no current-year option  |
| low | **GST-23** | GSTR-1 has no way to record the real ARN and filing date from the client workspace, so its perio |
| low | **SALES-18** | Statutory rules live in TypeScript with no backend counterpart, against the house rule "zero bus |

## Unverified — a probe was inconclusive

These need a code read before they can be scheduled. Do NOT treat them as open.

| severity | finding | what it is |
|---|---|---|
| high | **IT-19** | No §54/§54F/§54EC/§54B reinvestment exemptions and no §112A grandfathering under §55(2)(ac) |
| high | **IT-22** | The Budget-2024 grandfathered 20%-with-indexation option is offered for property acquired ON OR  |
| medium | **IT-23** | The ITR filing workflow offers only ITR-3/5/6/7, has no revised or updated return path, and the  |
| medium | **IT-27** | The §115BAC(6) regime-election engine — Form 10-IEA, the due date, the once-only withdrawal lock |
| medium | **IT-28** | §50AA is applied to every debt mutual fund regardless of acquisition date, and listed bonds and  |
| medium | **SALES-23** | No automated payment-reminder cadence to customers — the automatic run was removed and only a ma |
| medium | **TDS-10** | TCS (§206C(1H)/(1F)/(1G), Form 27EQ, Form 27D) does not exist — only a rate row nobody reads |

## Not a defect as stated

| severity | finding | what it is |
|---|---|---|
| medium | **GST-26** | No HSN/SAC master is shipped — every firm builds its own library from nothing |

## Deferred to the redesign

| severity | finding | what it is |
|---|---|---|
| low | **PAY-28** | Payroll is a link inside the Accounting rail and its screens are split across three top-level ar |

## Closed by a commit, with nothing in the code naming them

The weakest evidence in this file. 88% of the commit-closed findings carry an
in-code comment naming them and saying what they closed; these do not, so a
promotion to `closed` should start here.

| severity | finding | what it is |
|---|---|---|
| high | **BANK-07** | The Bank Book fetches every transaction on the account and computes the running balance in Pytho |
| high | **GST-08** | GSTR-1 Table 7 (B2CS) uses a blended rate inferred from the whole invoice, producing rates that  |
| high | **GST-16** | The GSTR-1 validator never runs on the path a CA actually uses |
| high | **SALES-03** | Invoice PDF always states "tax payable on reverse charge basis: No", and never prints the place  |
| high | **SALES-06** | Goa, Puducherry, Ladakh, Dadra & Nagar Haveli and Daman & Diu, Lakshadweep and Andaman & Nicobar |
| high | **SALES-09** | GSTR-1 Table 11A/11B (tax on advances, §13(2)) is unreachable — the three columns it needs are n |
| high | **TDS-11** | tds_deductions and tds_returns are written directly from the browser with no role check, and the |
| high | **TDS-22** | §194J's 2% technical-services rate and §194I's 2% plant-and-machinery rate are not modelled — bo |
| medium | **ACC-15** | A discarded draft journal can be resurrected and posted, because post_draft never selects delete |
| medium | **BANK-18** | The import module's most important refusals reach the CA as raw JSON: "API error 422: {\"detail\ |
| medium | **BANK-21** | Credit-card accounts are not supported at all |
| medium | **BANK-24** | Bank-charge input tax credit is posted with no supplier GSTIN or invoice reference, so it can ne |
| medium | **GST-21** | No §50 interest and no §47 late fee anywhere in the product |
| medium | **GST-25** | Composition scheme (CMP-08 / GSTR-4), e-commerce TCS (GSTR-8 and 3B 3.1.1), and GSTR-9C are enti |
| medium | **GST-30** | A test encodes the assumption behind the reverse-charge underpayment, so the suite cannot catch  |
| medium | **PUR-28** | Client-assignment scope is enforced on every purchase API endpoint and on none of the Purchases  |
| medium | **SALES-22** | No HSN/SAC master is exposed — every firm builds its code library from zero before it can raise  |
| medium | **TDS-19** | The 26AS parser mislabels Part B (TCS) as TDS and Part D (refunds) as self-assessment tax, and n |
| medium | **TDS-23** | Eight commonly-used TDS sections are absent from the registry, including §194T on payments to pa |
| low | **ACC-16** | Journal lines have no ordering column, so a voucher's Dr/Cr lines display in arbitrary order and |
| low | **ACC-25** | The journal editor never sends attachments, though the kernel, the model and the database all su |

## Closed by a code read

| severity | finding | what it is |
|---|---|---|
| critical | **ACC-01** | Posting a year-end adjustment is impossible in production — the endpoint writes columns that do  |
| critical | **FA-01** | Monthly depreciation writes "YYYY-MM" into a DATE column — the register update fails after the j |
| critical | **GST-01** | GSTR-3B net tax payable omits the reverse-charge liability (Table 3.1(d)) while still claiming i |
| critical | **GST-02** | IGST on a zero-rated (export/SEZ with payment) supply is dropped from GSTR-3B Table 3.1(b) |
| critical | **GST-03** | The 2A/2B reconciliation screen tells the CA on-screen that ITC is capped at 105% — superseded l |
| critical | **GST-05** | CGST/SGST credit is never cross-utilised against IGST liability, so cash payable is overstated |
| critical | **IT-02** | A capital LOSS entered as a negative figure reduces slab tax on salary — §71(3) set-off restrict |
| critical | **IT-03** | §80G is allowed in full at 50% or 100% with no qualifying limit of 10% of adjusted gross total i |
| critical | **IT-04** | The capital-gains engine ignores the date of transfer, so every pre-23-July-2024 sale is charged |
| critical | **PAY-01** | The EPFO ECR declares EPF wages of basic+DA while the contribution remitted was computed on the  |
| critical | **PAY-02** | 24Q Annexure II gives every employee the new-regime ₹75,000 standard deduction, including old-re |
| critical | **PUR-01** | §194J/§194H/§194A/§194D/§194G thresholds are applied per payment when the statute applies them t |
| critical | **PUR-02** | When the §194C ₹1L aggregate is crossed, TDS is deducted only on the crossing bill, not on the c |
| critical | **SALES-01** | Sales-invoice PDF names the CA FIRM as the supplier, with the CA firm's GSTIN and PAN, on the cl |
| critical | **SALES-02** | Invoice PDF prints a hardcoded 18% / 9% / 9% tax rate on every invoice regardless of the actual  |
| critical | **TDS-01** | Annual-aggregate thresholds are not modelled for §194J, §194H, §194A, §194D, §194G or §194Q — th |
| critical | **TDS-02** | §194Q withholds 0.1% of the whole invoice instead of 0.1% of the sum exceeding ₹50 lakh — a six- |
| high | **FA-03** | The Depreciation tab recomputes the annual charge in TypeScript with the exact bug the backend f |
| high | **FA-08** | Disposal does not charge depreciation up to the disposal date, so the gain/loss on every mid-yea |
| high | **IT-14** | Holding period is counted in whole calendar months rather than days, so a holding one day short  |
| high | **IT-15** | The ITR deadline tracker conflates assessment year with financial year — the period it stores an |
| high | **PAY-03** | The payslip PDF is headed with the CA FIRM's name, not the client company that actually employs  |
| high | **PAY-06** | The §10(13A) HRA salary base is annualised as this month × 12 regardless of how many months the  |
| high | **PUR-13** | §194Q deducts 0.1% on the whole purchase value instead of on the value exceeding ₹50 lakh, and h |
| medium | **ACC-11** | POST /api/accounting/accounts cannot set account_subtype, so every account a CA creates lands in |
| medium | **BANK-19** | Two banking screens parse typed rupees outside lib/money/rupeeInput, against the "one parser, an |
| medium | **FA-16** | 'Post All for Period' is N sequential requests with every error swallowed |
| medium | **FA-18** | The depreciation-schedule endpoint is unreachable from any screen |
| medium | **GST-17** | The HSN digit requirement is computed and then never applied or warned about, and the thresholds |
| medium | **GST-18** | GSTR-1 Table 13 (documents issued) is missing the serial-number range the form requires |
| medium | **GST-27** | The 2A/2B reconciliation engine is business logic in TypeScript and parses money with parseFloat |
| medium | **INV-04** | No stock ageing, movement analysis, slow-moving or non-moving report |
| medium | **INV-07** | Opening the Inventory tab walks the client's ENTIRE stock ledger |
| medium | **IT-24** | The Form 26AS parser is fixed-column and silently drops every line it cannot read, then marks th |
| medium | **IT-25** | The ITR due date is chosen by entity type rather than by whether an audit applies, so a small fi |
| medium | **PAY-13** | The client workspace's own employee form collects neither PAN, joining date, UAN, ESIC number, b |
| medium | **PAY-17** | Annual professional tax for §16(iii) is estimated as this month's PT × 12 — six times the year's |
| medium | **PAY-18** | `logger` is undefined in the /employee-exceptions error path — a failed declarations read raises |
| medium | **PUR-12** | The reconciliation screen tells the CA that ITC is restricted to 105% of GSTR-2A — a cushion rep |
| medium | **SALES-24** | Receipt and credit-note numbers take their financial year from today's date, not the document da |
| medium | **SALES-25** | No warning when a credit note is issued outside the §34(2) window, and no customer credit limit  |
| medium | **SALES-27** | A line with no HSN/SAC silently prints 998211 — the CA-services SAC — on any invoice, including  |
| low | **PUR-29** | Reverse charge and §17(5) eligibility have no test coverage on the purchase-bill compute path at |
| low | **PUR-30** | A dead _TDS_DEFAULT_BPS table at the top of purchase_bills.py carries a §194H rate that is 2.5x  |
| low | **PUR-31** | Vendor payment numbering is count+1, so a deleted or compensated payment guarantees a collision  |
| low | **PUR-32** | Duplicate-bill detection is exact-match on vendor plus bill number only, so an OCR typo or a dup |
| low | **TDS-31** | A dead default-rate map in the purchase-bills router carries a §194H rate cut two years ago |

---

## Why this file exists

`docs/audits/2026-09-11-the-verification-pass.md` measured the backlog ~10%
stale. Five days later `docs/audits/2026-09-12-the-probe-pass/` measured the
same backlog **38-59% stale by subsystem**, because five tranches had landed
and nothing re-scored. A hand-check on 12 September found nineteen more.

A status only ever written by an audit is wrong by the time it is read. This
one is amended in the same commit that closes a finding.
