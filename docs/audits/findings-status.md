# Where the 279 findings stand

Generated from `findings-status.json`. That file is the record; this one is it,
readable. Regenerate with `python3 scripts/findings_status_md.py`.

## The number

| state | count | what it means |
|---|---|---|
| closed | **265** | re-read against the code. The defect is gone. |
| partial | **6** | part of the finding is answered, part is not. Each says which. |
| open | **2** | re-read and still true. |
| not a defect as stated | **5** | the premise is false, or the suggested fix would be worse than the defect. |
| deferred to the redesign | **1** | a navigation complaint the module hub answers. |
| **total** | **279** | |

**The work left is 8 items — 2 open and 6 partial — not 254.**
The audit documents were never amended as tranches landed, so they still list
findings fixed weeks ago. **Every one of the 279 now carries a verdict**; none
is left as "unknown".

**Every one of the 2 open findings is blocked on something outside the code** — a statutory schema, a file layout, a registration. Each blocker is named below.

## Open

| severity | finding | what it is |
|---|---|---|
| medium | **GST-25** | Composition scheme (CMP-08 / GSTR-4), e-commerce TCS (GSTR-8 and 3B 3.1.1), and GSTR-9C are enti |
| medium | **TDS-16** | No FVU/RPU-format output and no correction-statement support — the only export is a JSON blob |

### What actually blocks each of them

| finding | what actually blocks it |
|---|---|
| **GST-25** | schema per return type (CMP-08/GSTR-4, GSTR-8, GSTR-9C) — see docs/audits/what-to-fetch-for-me.md §5 |
| **TDS-16** | the NSDL file layout, and a correction-statement model |

## Partial

| severity | finding | what it is |
|---|---|---|
| high | **IT-11** | Tax audit is a four-field tracker: no Form 3CD at all, and the §44AB applicability test is decid |
| high | **TDS-22** | §194J's 2% technical-services rate and §194I's 2% plant-and-machinery rate are not modelled — bo |
| medium | **ACC-13** | No day book, no cost centres, no bill-wise references, no party ledgers in the GL |
| medium | **FA-11** | No CWIP, revaluation, impairment, component accounting, shift working, transfers or physical ver |
| medium | **PAY-27** | No bank advice file, no payslip delivery, no reimbursements or flexible benefits, no overtime or |
| medium | **SALES-23** | No automated payment-reminder cadence to customers — the automatic run was removed and only a ma |


## Not a defect as stated

| severity | finding | what it is |
|---|---|---|
| medium | **GST-26** | No HSN/SAC master is shipped — every firm builds its own library from nothing |
| medium | **PUR-27** | No expense claim or petty cash module — every small expense needs a vendor and a purchase bill |
| medium | **SALES-22** | No HSN/SAC master is exposed — every firm builds its code library from zero before it can raise  |
| medium | **TDS-10** | TCS (§206C(1H)/(1F)/(1G), Form 27EQ, Form 27D) does not exist — only a rate row nobody reads |
| low | **GST-31** | The GST portal integration router is complete, honest and reachable from no screen |

## Deferred to the redesign

| severity | finding | what it is |
|---|---|---|
| low | **PAY-28** | Payroll is a link inside the Accounting rail and its screens are split across three top-level ar |


## Closed by a code read

| severity | finding | what it is |
|---|---|---|
| critical | **ACC-01** | Posting a year-end adjustment is impossible in production — the endpoint writes columns that do  |
| critical | **FA-01** | Monthly depreciation writes "YYYY-MM" into a DATE column — the register update fails after the j |
| critical | **FA-02** | The default "Schedule II" WDV rates are not Schedule II rates — a computer depreciates at half t |
| critical | **GST-01** | GSTR-3B net tax payable omits the reverse-charge liability (Table 3.1(d)) while still claiming i |
| critical | **GST-02** | IGST on a zero-rated (export/SEZ with payment) supply is dropped from GSTR-3B Table 3.1(b) |
| critical | **GST-03** | The 2A/2B reconciliation screen tells the CA on-screen that ITC is capped at 105% — superseded l |
| critical | **GST-04** | GSTR-2B reconciliation never reads the books, does not parse a real GSTR-2B JSON, and persists n |
| critical | **GST-05** | CGST/SGST credit is never cross-utilised against IGST liability, so cash payable is overstated |
| critical | **IT-01** | No tax computation path exists for a company, firm or LLP — the entity-rate and MAT/AMT engines  |
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
| high | **ACC-02** | Cash receipts and cash vendor payments are posted to the Bank ledger — Cash in Hand never moves |
| high | **ACC-03** | Every receipt and vendor payment posts to one generic "Bank Account" ledger, while bank-statemen |
| high | **ACC-05** | A client's financial year, once locked by finalising the year-end engagement, can never be reope |
| high | **ACC-06** | Recurring journals, budgets and retainers are stored in browser localStorage — not in the databa |
| high | **ACC-07** | The Audit Log screen shows only the 200 most recent firm-wide rows and cannot show one entry's e |
| high | **ACC-09** | The chart of accounts is flat, and there is no screen anywhere to create or edit a single ledger |
| high | **ACC-10** | The Schedule III Mapping screen changes nothing — the statements bucket by account_subtype subst |
| high | **BANK-01** | A statement that prints a page subtotal labelled "Total" is refused outright, with a message bla |
| high | **BANK-02** | Overdraft and Cash Credit bank accounts are given an Asset ledger, and the ledger picker will no |
| high | **BANK-04** | The "Bank Reconciliation Statement" is a statement-line tick-off; it has no unpresented cheques  |
| high | **BANK-05** | "Adjustments" is an unexplained plug number that can force a reconciliation to tie out and produ |
| high | **BANK-06** | There is no way to delete or undo a mis-imported statement — nothing in the backend or the UI |
| high | **BANK-07** | The Bank Book fetches every transaction on the account and computes the running balance in Pytho |
| high | **BANK-08** | The statement upload endpoint is `async def` but does blocking PDF rasterisation and up to twent |
| high | **BANK-09** | Two genuinely identical transactions on a statement with no balance column are silently merged i |
| high | **BANK-20** | There is no cash book — no cash vouchers, no cash register, no petty-cash screen |
| high | **FA-03** | The Depreciation tab recomputes the annual charge in TypeScript with the exact bug the backend f |
| high | **FA-04** | Depreciation is monthly-only with no catch-up, and a missed month can never be posted |
| high | **FA-05** | The auto-generated Fixed Assets note reports a theoretical annual charge that need not match any |
| high | **FA-06** | IT Act §32 block-of-assets depreciation does not exist, and the book-to-tax bridge that needs it |
| high | **FA-07** | Asset acquisition always credits Bank — no vendor, no GST/ITC, and no link to the purchase bill, |
| high | **FA-08** | Disposal does not charge depreciation up to the disposal date, so the gain/loss on every mid-yea |
| high | **FA-10** | No way to edit, correct, reverse or delete an asset once created |
| high | **GST-07** | Deemed exports and SEZ supplies are filed as physical exports in Table 6A, losing the recipient' |
| high | **GST-08** | GSTR-1 Table 7 (B2CS) uses a blended rate inferred from the whole invoice, producing rates that  |
| high | **GST-10** | GSTR-9 is a tab that can never hold anything: no computation, and no UI that creates a draft |
| high | **GST-11** | QRMP quarterly returns cannot be computed, saved or recorded — every period in the return engine |
| high | **GST-12** | The "Add GST Filing" modal on /gst throws on every save — the period is "MMM YYYY" and is parsed |
| high | **GST-13** | The module's most differentiating backend work — amendments, exception report, ITC register, adv |
| high | **GST-14** | Two contradictory "filed" states: /gst marks filings in compliance_calendar over PostgREST and n |
| high | **GST-16** | The GSTR-1 validator never runs on the path a CA actually uses |
| high | **GST-20** | One GSTIN per client — no multi-state / multi-branch registration model |
| high | **INV-01** | There is no closing-stock-as-at-a-date figure, and the date-filtered stock ledger's running bala |
| high | **INV-06** | A §17(5)(h) ITC reversal on a stock write-off is posted to the GL but can never reach GSTR-3B Ta |
| high | **IT-05** | The per-client Tax Computation workspace collects only five figures — no deductions, no house pr |
| high | **IT-06** | §234C interest is charged on the first three instalments for a §44AD/§44ADA presumptive assessee |
| high | **IT-09** | IT Act §32 depreciation (block of assets, WDV, the 180-day half-rate rule, additional depreciati |
| high | **IT-10** | Brought-forward losses are stored and displayed but never enter the computation, and there is no |
| high | **IT-12** | The tax audit report due date is wrong in both places it appears — the compliance calendar uses  |
| high | **IT-13** | §234A and §234B are implemented and tested but exposed by no endpoint and no screen — only §234C |
| high | **IT-14** | Holding period is counted in whole calendar months rather than days, so a holding one day short  |
| high | **IT-15** | The ITR deadline tracker conflates assessment year with financial year — the period it stores an |
| high | **IT-16** | The presumptive engine for §44AD, §44ADA and §44AE is reachable from nothing — no endpoint, no r |
| high | **IT-17** | itr_field_placements() — 'this figure goes in this field' against the Department's own committed |
| high | **IT-18** | The AIS screen persists nothing — the whole reconciliation lives in React state and is gone on r |
| high | **IT-19** | No §54/§54F/§54EC/§54B reinvestment exemptions and no §112A grandfathering under §55(2)(ac) |
| high | **IT-22** | The Budget-2024 grandfathered 20%-with-indexation option is offered for property acquired ON OR  |
| high | **PAY-03** | The payslip PDF is headed with the CA FIRM's name, not the client company that actually employs  |
| high | **PAY-06** | The §10(13A) HRA salary base is annualised as this month × 12 regardless of how many months the  |
| high | **PAY-09** | /payroll/reports recomputes employer PF on basic alone and ESI without Rule 50 — the four exact  |
| high | **PAY-11** | Seven finished backend capabilities have no screen anywhere — including the leaver settlement an |
| high | **PAY-12** | PATCH /employees silently discards joining_date, and the edit form sends it — so a wrong joining |
| high | **PAY-14** | A leaver's settlement TDS never reaches the quarterly 24Q, though it does reach the annual Annex |
| high | **PAY-16** | Both firm-level payroll screens load every payslip of every run the firm has ever produced into  |
| high | **PAY-29** | The payslip omits UAN, PF/ESIC numbers, bank account, employer contributions and YTD figures |
| high | **PUR-03** | Surcharge and 4% cess are added on top of a DTAA treaty rate, over-deducting on every foreign pa |
| high | **PUR-05** | §17(5) blocked credit cannot be set from any screen — the API field, the DB column and the retur |
| high | **PUR-06** | The vendor's TDS rate is collected on a form, shown in a list column, and never used by the comp |
| high | **PUR-07** | No §197 lower-deduction or nil-deduction certificate anywhere — no certificate number, rate, thr |
| high | **PUR-08** | A purchase bill can be created and received into a period whose GSTR-3B has already been filed — |
| high | **PUR-09** | The Rule 37 report ignores debit notes and purchase credit notes, over-reversing ITC on any bill |
| high | **PUR-10** | No TDS is deducted or recorded on a vendor payment — advances to contractors withhold nothing, a |
| high | **PUR-11** | The GSTR-2A/2B reconciliation asks the CA to export and re-upload the purchase register the plat |
| high | **PUR-13** | §194Q deducts 0.1% on the whole purchase value instead of on the value exceeding ₹50 lakh, and h |
| high | **PUR-14** | The TDS register's statutory gaps are computed on every receive and never reach a screen — the e |
| high | **PUR-15** | The MSME §43B(h) tracker is a manually re-keyed side table with the whole statutory rule compute |
| high | **SALES-03** | Invoice PDF always states "tax payable on reverse charge basis: No", and never prints the place  |
| high | **SALES-04** | Deleting a middle draft credit note (or sales debit note) permanently wedges that client's numbe |
| high | **SALES-05** | The Sales screen's "Outstanding" tile overstates receivables — it sums the full invoice total fo |
| high | **SALES-06** | Goa, Puducherry, Ladakh, Dadra & Nagar Haveli and Daman & Diu, Lakshadweep and Andaman & Nicobar |
| high | **SALES-08** | Every receipt debits one firm-wide "Bank" ledger — cash receipts land in Bank, and the selected  |
| high | **SALES-09** | GSTR-1 Table 11A/11B (tax on advances, §13(2)) is unreachable — the three columns it needs are n |
| high | **SALES-10** | Export/SEZ invoices produce a GSTR-1 the portal will reject — shipping bill number, date and por |
| high | **SALES-11** | No discount field anywhere on a sales invoice — not per line, not at document level |
| high | **SALES-13** | Firm branding, invoice templates, bank/UPI details and footer text are stored by a full Settings |
| high | **SALES-14** | An unallocated advance receipt can never be applied to a later invoice from any screen, and it n |
| high | **TDS-03** | "Prepare a Return" on /tds/returns cannot work in production — it sends no auth token, and the d |
| high | **TDS-04** | Form 16/16A certificate creation always fails silently against the real database — the UI sends  |
| high | **TDS-05** | The /tds page computes TDS in the browser from a hardcoded, stale rate table and writes it strai |
| high | **TDS-06** | On a 26Q working paper every deductee row is stamped with the first challan found for its sectio |
| high | **TDS-07** | §194IA is offered in the vendor TDS-section dropdown but is unknown to the engine — every bill f |
| high | **TDS-09** | There is no 27Q return builder — non-resident deductions are computed, registered and then delib |
| high | **TDS-11** | tds_deductions and tds_returns are written directly from the browser with no role check, and the |
| high | **TDS-13** | No §197 lower-deduction certificate anywhere, and vendors.tds_rate_bps is captured, displayed an |
| high | **TDS-14** | The purchase-bill editor previews a TDS figure the backend will not compute — no threshold, no § |
| high | **TDS-15** | The /tds screen's Challans tab never saves anything, and its Returns and Certificates tabs read  |
| high | **TDS-26** | §195 surcharge picks the wrong ladder and the wrong 'other sums' rate for a non-resident firm, L |
| medium | **ACC-04** | An auto-posted journal (sales invoice, purchase bill, payroll, depreciation) can be edited throu |
| medium | **ACC-08** | The Trial Balance is always inception-to-date — choosing a financial year only moves the as-at d |
| medium | **ACC-11** | POST /api/accounting/accounts cannot set account_subtype, so every account a CA creates lands in |
| medium | **ACC-12** | A filed return locks EDITING a period but not POSTING into it — the two halves of the same rule  |
| medium | **ACC-14** | Opening balances cover only aggregate AR, aggregate AP and bank — every other account, and every |
| medium | **ACC-15** | A discarded draft journal can be resurrected and posted, because post_draft never selects delete |
| medium | **ACC-17** | Reporting endpoints aggregate across the WHOLE firm when client_id is omitted, for a caller who  |
| medium | **ACC-18** | The Lock Financial Year screen offers a hardcoded list of years ending at 2025-26 — the current  |
| medium | **ACC-19** | Multi-currency is fully built across five phases but cannot be switched on for any firm or clien |
| medium | **ACC-21** | post_journal_atomic validates the entry's firm and client but never checks that the LINE account |
| medium | **ACC-22** | No drill-through from a ledger line to the voucher behind it |
| medium | **ACC-24** | The Account Groups screen renders nothing useful for a normally-onboarded firm |
| medium | **ACC-27** | entry_date is an unvalidated string on the journal models, so a malformed date reaches the datab |
| medium | **BANK-03** | A foreign-currency bank account can be created, and its statement imports and posts to the ledge |
| medium | **BANK-10** | Auto-match never suggests a part payment against a partially-paid invoice, because the amount ba |
| medium | **BANK-11** | The rule engine is one case-insensitive substring plus an amount range and a direction — no rege |
| medium | **BANK-13** | The exception-rules engine — materiality, duplicates, cash withdrawals, new payees — is complete |
| medium | **BANK-14** | A PDF whose first page has ruled table lines and whose later pages do not silently loses the lat |
| medium | **BANK-15** | Transfer detection scans only the newest 1,000 lines, and is re-run from scratch for every 100-l |
| medium | **BANK-16** | The nightly trusted-rule sweep will auto-post a line the CA coded themselves, and credit it to t |
| medium | **BANK-18** | The import module's most important refusals reach the CA as raw JSON: "API error 422: {\"detail\ |
| medium | **BANK-19** | Two banking screens parse typed rupees outside lib/money/rupeeInput, against the "one parser, an |
| medium | **BANK-21** | Credit-card accounts are not supported at all |
| medium | **BANK-23** | The reconciliation shows only POSTED statement lines, so an unposted line in the period produces |
| medium | **BANK-24** | Bank-charge input tax credit is posted with no supplier GSTIN or invoice reference, so it can ne |
| medium | **BANK-26** | Six statement layouts are auto-detected; every other bank needs a manual mapping, and the mappin |
| medium | **BANK-27** | An opening balance can be saved with no opening-balance date, and the Bank Book then folds pre-o |
| medium | **FA-09** | The year-end Fixed Assets schedule sums only journal lines dated inside the FY, so prior years'  |
| medium | **FA-12** | Fixed-asset reads are unpaginated — a client with more than 1000 assets silently loses gross blo |
| medium | **FA-13** | WDV depreciation never ends: useful life is ignored for WDV and salvage defaults to zero, so an  |
| medium | **FA-14** | An explicitly entered 0% rate or 0-year life is treated as 'not supplied' and silently replaced  |
| medium | **FA-15** | The Reports tab labels lifetime figures with a financial year it never filters by |
| medium | **FA-16** | 'Post All for Period' is N sequential requests with every error swallowed |
| medium | **FA-18** | The depreciation-schedule endpoint is unreachable from any screen |
| medium | **FA-19** | Rule 43 capital-goods ITC apportionment does not exist |
| medium | **FA-20** | Nothing reconciles the fixed-asset register against the GL except one year-end note |
| medium | **GST-06** | Non-GST outward supplies are dropped from GSTR-3B Table 3.1(e) and counted nowhere |
| medium | **GST-09** | The correction window always reports 30 November — the "or the annual return, whichever is earli |
| medium | **GST-15** | GSTR-1 Table 11 advance tax is computed into the filed payload while the advances report tells t |
| medium | **GST-17** | The HSN digit requirement is computed and then never applied or warned about, and the thresholds |
| medium | **GST-18** | GSTR-1 Table 13 (documents issued) is missing the serial-number range the form requires |
| medium | **GST-19** | Rule 36(4) is applied as an aggregate per-head cap, not invoice-level 2B matching, and the cappe |
| medium | **GST-21** | No §50 interest and no §47 late fee anywhere in the product |
| medium | **GST-22** | The GSTR-3B screen prints taxable VALUES in the IGST column and shows none of tables 3.1(d), 3.1 |
| medium | **GST-24** | Table 4(A) rows for import IGST and ISD are permanently zero, and ISD is now compulsory |
| medium | **GST-27** | The 2A/2B reconciliation engine is business logic in TypeScript and parses money with parseFloat |
| medium | **GST-28** | Rule 37A has a reason code but no report; Rule 37 has no interest and no posting help |
| medium | **GST-29** | GSTIN check-digit validation is not applied on any GST return path |
| medium | **GST-30** | A test encodes the assumption behind the reverse-charge underpayment, so the suite cannot catch  |
| medium | **GST-32** | E-invoicing prepares nothing — no INV-01 JSON, no 30-day reporting-window check, and no e-invoic |
| medium | **INV-02** | Moving average is the only costing method — no FIFO and no standard cost |
| medium | **INV-03** | No batches/expiry, godowns, item groups, alternate units, reorder levels, BOM or stock transfers |
| medium | **INV-04** | No stock ageing, movement analysis, slow-moving or non-moving report |
| medium | **INV-05** | Inventory cost excludes freight and non-creditable GST — closing stock and COGS are understated |
| medium | **INV-07** | Opening the Inventory tab walks the client's ENTIRE stock ledger |
| medium | **INV-08** | Physical verification is one item at a time, with no count sheet and no session |
| medium | **IT-08** | The unexhausted basic exemption limit is never absorbed against §111A / §112 capital gains, so a |
| medium | **IT-20** | §80CCD(2) is capped at 10% of salary for a non-government employee under the NEW regime, where t |
| medium | **IT-23** | The ITR filing workflow offers only ITR-3/5/6/7, has no revised or updated return path, and the  |
| medium | **IT-24** | The Form 26AS parser is fixed-column and silently drops every line it cannot read, then marks th |
| medium | **IT-25** | The ITR due date is chosen by entity type rather than by whether an audit applies, so a small fi |
| medium | **IT-27** | The §115BAC(6) regime-election engine — Form 10-IEA, the due date, the once-only withdrawal lock |
| medium | **IT-28** | §50AA is applied to every debt mutual fund regardless of acquisition date, and listed bonds and  |
| medium | **IT-29** | The Cost Inflation Index stops at FY 2025-26, so every indexed cost computed and STORED in the c |
| medium | **IT-31** | 26AS reconciliation never feeds the computation — the TDS credit on the return is a number the C |
| medium | **IT-32** | The Chapter VI-A surface stops at seven sections — no §80E, §80EE/EEA, §80DD/DDB, §80U, §80GG, § |
| medium | **PAY-04** | A draft payroll run that was never finalised is counted as TDS already deducted, months already  |
| medium | **PAY-05** | pt_applicable with no pt_state withholds zero professional tax and is reported as a gap by nothi |
| medium | **PAY-07** | §17(2) perquisites are valued, stored and reported on Form 16 but never enter the monthly §192 w |
| medium | **PAY-08** | Reversing a payroll run does not restore employee loan balances, so re-finalising the same run r |
| medium | **PAY-10** | The TDS projection screen computes §192 in TypeScript with hardcoded FY 2025-26 new-regime rates |
| medium | **PAY-13** | The client workspace's own employee form collects neither PAN, joining date, UAN, ESIC number, b |
| medium | **PAY-15** | Attendance and LOP cannot be entered from the client Payroll tab at all — they live on a firm-wi |
| medium | **PAY-17** | Annual professional tax for §16(iii) is estimated as this month's PT × 12 — six times the year's |
| medium | **PAY-18** | `logger` is undefined in the /employee-exceptions error path — a failed declarations read raises |
| medium | **PAY-19** | The payroll module's own statutory calendar contradicts compliance_engine: it invents a PT due d |
| medium | **PAY-20** | /statutory-position computes PF on basic+DA, not the s.2(y) wage base the payroll run uses, so t |
| medium | **PAY-21** | A payroll run cannot be recomputed or discarded — reversal reopens it at 'review' with the origi |
| medium | **PAY-22** | §80CCD(2)'s 14%/10% cap is applied to gross salary instead of basic+DA, so a large employer-NPS  |
| medium | **PAY-23** | Statutory bonus is computed only inside a leaver's settlement — there is no annual bonus run for |
| medium | **PAY-24** | Leave is half-built: balances are invented in TypeScript as 12/12/15, nothing accrues or carries |
| medium | **PAY-25** | The payroll journal posts one Salaries Expense account and defines the debit as the sum of the c |
| medium | **PAY-26** | The employee portal shows a payslip list and a leave number and nothing else a self-service port |
| medium | **PUR-04** | §17(5) blocked credit is still debited to GST Input in the journal, leaving a permanent phantom  |
| medium | **PUR-12** | The reconciliation screen tells the CA that ITC is restricted to 105% of GSTR-2A — a cushion rep |
| medium | **PUR-16** | A second, orphaned vendor master at /accounting/suppliers that no purchase path reads |
| medium | **PUR-18** | Import of goods has no path — no Bill of Entry, so the IGST paid to customs cannot be recorded a |
| medium | **PUR-19** | Reverse-charge bills produce no self-invoice (§31(3)(f)) and no payment voucher (§31(3)(g)) |
| medium | **PUR-20** | GST compensation cess cannot be recorded on a purchase, so the cess ITC is lost for every client |
| medium | **PUR-21** | AI-extracted invoice figures are never arithmetically validated and are never reconciled against |
| medium | **PUR-22** | One payment settling several bills is not reachable from the Purchases screen — the multi-bill a |
| medium | **PUR-23** | Issuing a debit note (purchase return) does not resync the TDS register, so 26Q keeps reporting  |
| medium | **PUR-24** | AP ageing lists only bills, so unallocated vendor advances are invisible and the ageing total do |
| medium | **PUR-25** | No purchase orders, goods receipt notes or three-way matching |
| medium | **PUR-26** | No recurring purchase bills, though recurring sales invoices are fully built |
| medium | **PUR-28** | Client-assignment scope is enforced on every purchase API endpoint and on none of the Purchases  |
| medium | **SALES-07** | TDS deducted by the customer (§194J / §194Q) cannot be recorded on a receipt from any screen |
| medium | **SALES-12** | Sales invoice numbering is entirely manual; the Invoice Settings numbering series a CA configure |
| medium | **SALES-15** | Credit notes, sales debit notes and receipts can be posted into a period whose GSTR-1 has alread |
| medium | **SALES-16** | Nothing checks that a reverse-charge or nil/exempt invoice actually carries zero tax, so the boo |
| medium | **SALES-17** | The e-way bill threshold is tested against taxable value instead of consignment value including  |
| medium | **SALES-19** | The export/SEZ treatment is captured twice in two different vocabularies that can disagree, and  |
| medium | **SALES-20** | No GST compensation cess on a sales line |
| medium | **SALES-21** | No quotation, proforma invoice, sales order or delivery challan — the sales cycle starts at the  |
| medium | **SALES-24** | Receipt and credit-note numbers take their financial year from today's date, not the document da |
| medium | **SALES-25** | No warning when a credit note is issued outside the §34(2) window, and no customer credit limit  |
| medium | **SALES-26** | Nowhere in the sales screens can a CA see what a single invoice still owes |
| medium | **SALES-27** | A line with no HSN/SAC silently prints 998211 — the CA-services SAC — on any invoice, including  |
| medium | **SALES-28** | E-invoice and e-way bill are record-keeping ledgers only — no JSON is produced, no applicability |
| medium | **SALES-29** | An invoice can be created and issued with no place of supply, and only the GSTR-1 build discover |
| medium | **TDS-08** | No §201(1A) interest and no §234E late fee are computed anywhere a CA can use them |
| medium | **TDS-12** | The compliance calendar has no 24Q filing deadline and no monthly non-salary TDS deposit deadlin |
| medium | **TDS-17** | For FY 2026-27 the 26Q payload names the form 140 while every deductee line still cites a 1961-A |
| medium | **TDS-19** | The 26AS parser mislabels Part B (TCS) as TDS and Part D (refunds) as self-assessment tax, and n |
| medium | **TDS-20** | The 26AS pipeline accepts only pasted tab/pipe-delimited text and offers no current-year option  |
| medium | **TDS-23** | Eight commonly-used TDS sections are absent from the registry, including §194T on payments to pa |
| medium | **TDS-25** | Form 15CA cannot be recorded against a foreign remittance, so the gap the engine raises can neve |
| medium | **TDS-28** | The 26Q/24Q from-books flow makes the CA re-type the TAN, deductor name, PAN and address every q |
| medium | **TDS-29** | The browser-built return reports every deduction as fully deposited, so the 'deducted exceeds de |
| medium | **TDS-30** | Nothing computes what TDS is due for deposit this month, so there is no challan-281 worksheet to |
| medium | **TDS-32** | Purchase debit and credit notes never reverse TDS, so a return after deduction leaves the regist |
| low | **ACC-16** | Journal lines have no ordering column, so a voucher's Dr/Cr lines display in arbitrary order and |
| low | **ACC-20** | A legacy PATCH /api/accounting/journal/{id}/post is still mounted, Partner-callable, and backed  |
| low | **ACC-23** | No year-end closing process: the P&L is never transferred to reserves and the FY 'close' only se |
| low | **ACC-25** | The journal editor never sends attachments, though the kernel, the model and the database all su |
| low | **ACC-26** | GET /api/accounting/ledger-span raises instead of degrading when there is no database, unlike ev |
| low | **BANK-12** | Deleting a matching rule silently strips the trusted-rule attribution from every entry it posted |
| low | **BANK-17** | Undo reverses the journal of a line that sits inside a completed, certified reconciliation, with |
| low | **BANK-22** | A statement imported without a bank account posts every line to a generic "Bank" ledger and is i |
| low | **BANK-25** | Every imported statement shows an amber "pending" chip forever — import_status is written once a |
| low | **BANK-28** | The narration parser extracts channel, UTR, VPA, IFSC and counterparty but never a cheque number |
| low | **BANK-29** | A statement's opening/closing-balance row becomes a zero-amount bank line that clogs the queue a |
| low | **FA-17** | The Add Asset form's Asset Code field is silently discarded |
| low | **GST-23** | GSTR-1 has no way to record the real ARN and filing date from the client workspace, so its perio |
| low | **INV-09** | Stock quantity is NUMERIC(10,3) with no unit conversion, so high-count or fine-grained items bre |
| low | **INV-10** | Stock adjustments and NRV write-downs are reachable only two clicks deep, from inside one item's |
| low | **IT-07** | AMT surcharge for an individual or HUF uses the partnership firm's 12%-above-₹1-crore ladder ins |
| low | **IT-21** | AMT is charged without the §115JC(5) carve-out for a person who has opted into §115BAC — which i |
| low | **IT-26** | The §10(13A) HRA exemption is folded into Chapter VI-A 'total deductions' and gross total income |
| low | **IT-30** | Snapshots stay 'draft' forever — the review endpoint exists but no screen calls it, and the work |
| low | **IT-33** | The advance-tax hub card hardcodes the FY 2025-26 instalment calendar, so it shows last year's d |
| low | **IT-34** | The deductions planner fires two RBAC-gated compute calls on every debounced state change, inclu |
| low | **PAY-30** | UAN, ESIC number and IFSC are format-checked on bulk import but accepted unvalidated on the sing |
| low | **PUR-17** | POST /purchase-bills/from-document bypasses the whole compute engine and cannot succeed for a ve |
| low | **PUR-29** | Reverse charge and §17(5) eligibility have no test coverage on the purchase-bill compute path at |
| low | **PUR-30** | A dead _TDS_DEFAULT_BPS table at the top of purchase_bills.py carries a §194H rate that is 2.5x  |
| low | **PUR-31** | Vendor payment numbering is count+1, so a deleted or compensated payment guarantees a collision  |
| low | **PUR-32** | Duplicate-bill detection is exact-match on vendor plus bill number only, so an OCR typo or a dup |
| low | **SALES-18** | Statutory rules live in TypeScript with no backend counterpart, against the house rule "zero bus |
| low | **SALES-30** | A credit note's is_interstate can be inherited from another client's invoice in the same firm |
| low | **SALES-31** | SalesInvoiceIn.place_of_supply is accepted by the API and silently ignored in production |
| low | **SALES-32** | No TCS on sales, and the rate registry's note about §206C(1H) looks stale |
| low | **TDS-18** | Saving a computed FY 2026-27 return violates the tds_returns CHECK constraint, because the paylo |
| low | **TDS-21** | The TDS workspace's 26AS comparison keys on (PAN, section) in a dict, so multiple deductions for |
| low | **TDS-24** | §206AB is implemented and unit-tested as current law, but was omitted by the Finance Act 2025 wi |
| low | **TDS-27** | tds_section_limits ships seeded with pre-Finance-Act-2025 thresholds and pre-2024 rates, and its |
| low | **TDS-31** | A dead default-rate map in the purchase-bills router carries a §194H rate cut two years ago |
| ? | **FA-08b** |  |

---

## Why this file exists

`docs/audits/2026-09-11-the-verification-pass.md` measured the backlog ~10%
stale. Five days later `docs/audits/2026-09-12-the-probe-pass/` measured the
same backlog **38-59% stale by subsystem**, because five tranches had landed
and nothing re-scored. A hand-check on 12 September found nineteen more.

A status only ever written by an audit is wrong by the time it is read. This
one is amended in the same commit that closes a finding.
