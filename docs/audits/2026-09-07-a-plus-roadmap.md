# The A+ roadmap — what every module needs, module by module

**Date:** 7 September 2026
**Asked:** *"for all the modules to reach A+ what all things need to be done — make
a list of them and start working on them."*

This is the list. Work started the same day; §9 records what is already in flight.

Read `2026-09-07-where-we-are-against-the-one-platform-goal.md` first — it is the
audit this rests on. Everything here is derived from the 275 verified findings in
`2026-09-07-findings/`, plus the market comparison in §7 of that report.

---

## 0. What A+ means, so the grade is not a feeling

A module is **A+** when all five hold. Anything less is a lower letter, whatever it
looks like on screen.

1. **Correct.** No wrong statutory number reaches a CA in any realistic case, and
   every rule carries its citation. Proven by a golden-case test derived from the
   statute by a human, not from the implementation.
2. **Complete for the job.** A CA can finish the whole monthly/quarterly/annual
   task inside the product without exporting to Excel or opening another tool.
3. **Reachable.** Every capability the backend has is on a screen, and every screen
   that computes has a backend behind it. No settings page that nothing reads.
4. **Honest.** Where the product cannot know something, it says so by name and
   refuses, rather than defaulting to a plausible number. This is the house style
   and it is the strongest thing the codebase has.
5. **Fast enough and safe.** No report fetches rows proportional to the ledger; no
   browser-side money arithmetic; no unguarded direct write; an undo for anything
   destructive.

**Current grades, and the live finding counts behind them:**

| Module | Grade | Live findings | crit | high | med | low | of which gaps/missing |
|---|:--:|--:|--:|--:|--:|--:|--:|
| Accounting core | **B** | 27 | 1 | 7 | 14 | 5 | 10 |
| Banking | **B** | 29 | 0 | 9 | 14 | 6 | 10 |
| GST | **C** | 31 | 5 | 9 | 16 | 1 | 16 |
| Income tax / ITR | **C** | 34 | 4 | 14 | 10 | 6 | 15 |
| TDS/TCS | **C** | 32 | 2 | 12 | 13 | 5 | 11 |
| Sales cycle | **C** | 31 | 2 | 10 | 15 | 4 | 14 |
| Purchase cycle | **C** | 31 | 2 | 11 | 14 | 4 | 15 |
| Payroll | **C** | 30 | 2 | 8 | 18 | 2 | 8 |
| Fixed assets / inventory | **C** | 30 | 2 | 9 | 16 | 3 | 12 |
| Reporting / year-end | **B−** | *not audited* | — | — | — | — | — |
| Practice management | **B−** | *not audited* | — | — | — | — | — |
| AI / intelligence | **D** | *not audited* | — | — | — | — | — |
| Platform / security | **B−** | *not audited* | — | — | — | — | — |
| Frontend / UX | **C** | *not audited* | — | — | — | — | — |

**The four rows marked *not audited* are the honest hole.** They got my own lighter
inline pass, not a deep reader. Their grades are provisional and the work below for
them is correspondingly less certain. Auditing those five properly is item 0 of the
plan and costs about a day.

---

## 1. Accounting core — B to A+

The kernel is already the best thing in the codebase and does not need rebuilding.
What is missing is everything a Tally user reaches for on day one.

**Correctness (1 critical, 7 high)**
- Year-end adjustments cannot post: writes non-existent columns AND bypasses the
  posting kernel. **In flight.**
- Cash receipts and cash vendor payments post to the **Bank** ledger — Cash in Hand
  never moves, and the chosen bank account is discarded. One generic "Bank Account"
  ledger receives everything while bank-statement entries post to the correct
  per-account ledger, so the two disagree.
- The Trial Balance is always inception-to-date; picking an FY only moves the as-at
  date, so revenue and expense never reset.
- `entry_date` is an unvalidated string and two lock checks parse it differently, so
  `2025-4-1` passes one, fails the other, and Postgres accepts it — a shape that
  posts into a locked year.
- An auto-posted journal can be edited through the manual-journal editor.

**Completeness — the Tally-parity list, which is the real gap**
- **A screen to create or edit a single ledger.** There is none. Only bulk CSV
  import. This alone disqualifies the module today.
- **A hierarchical chart of accounts.** `parent_id` exists and production has 133
  accounts with **zero** parents. Groups and sub-groups are how a CA thinks.
- **Cost centres.** Absent entirely.
- **Bill-wise references** (the `Agst Ref` / `New Ref` model). Absent — and it is
  what makes party ageing meaningful.
- **A day book** — one chronological register of every voucher. The Journal tab
  deliberately shows only manual entries, so no such view exists anywhere.
- Voucher-type numbering series, narration templates, recurring journals **in the
  database** (they are in browser `localStorage` today, along with budgets and
  retainers), opening balance by bill, drill-through from a ledger line to its
  voucher.
- A year-end closing process: the P&L is never transferred to reserves.
- An unlock path for a locked FY — once finalised it can never be reopened.
- An audit-log screen that can show one entry's history (it shows the 200 most
  recent firm-wide rows), which is what Rule 3(1)'s edit-log expectation is for.

**Honesty / performance**: multi-currency entitlement flags are read in nine places
and written nowhere; `/api/accounting/accounts` is fine now but the Account Groups
screen is a flat list under a heading that promises groups.

---

## 2. Banking — B to A+

The import is the most commercially differentiated thing in the product. The
reconciliation around it is not finished.

**Correctness (9 high)**
- A statement printing a page subtotal labelled "Total" is refused outright, blaming
  the column mapping.
- Overdraft and Cash Credit accounts get an **Asset** ledger and the picker will not
  offer a Liability one — so every OD account is on the wrong side of the balance
  sheet.
- A foreign-currency bank account imports and posts at **1:1**.
- Two genuinely identical transactions on a statement with no balance column are
  silently merged, and a UNIQUE index enforces the collapse — so the fix needs a
  migration.
- The trusted-rules nightly sweep posts a line the CA had **recoded**, keeping the
  rule's ledger, not theirs.
- An undone reconciliation leaves the register reading `R`.
- Four banking files still do `rsToP(parseFloat(...))` on money, including the
  modal that builds posted allocation and TDS figures.

**Completeness**
- **A real BRS** — unpresented cheques and deposits in transit. Today it is a
  statement-line tick-off, and "Adjustments" is an unvalidated plug that can force a
  tie-out and produce a signed PDF.
- **A cash book** — cash vouchers, cash register, petty cash.
- **Undo for a mis-imported statement.** There is none, in the backend or the UI.
- Per-account column mappings are stored but no screen manages them.
- Loan EMI splitting (principal/interest), credit-card statements, an exception
  engine that is wired up (`needs_review` is never set true).

**Performance**: the Bank Book's `all_lines.index(l)` inside a `min()` is O(n²) —
**29.185 seconds of CPU on 12,836 rows**, measured. The statement upload is
`async def` but does blocking PDF rasterisation and up to twenty vision calls on the
event loop, with `gunicorn --workers 1`, so one upload stalls the whole API.

---

## 3. GST — C to A+ (the biggest single lift, and the most commercially urgent)

**Correctness (5 critical)** — all in flight:
- §49(5)(b)/(c) cross-utilisation missing: ₹1,80,000 demanded in cash when nil is due.
- RCM liability omitted from net tax while its credit is claimed.
- Zero-rated (export with payment) IGST dropped from 3.1(b).
- GSTR-2B reconciliation compares nothing — the books side is read out of the
  uploaded file.
- The screen states the **105% Rule 36(4) cushion repealed on 01-01-2022**, which
  the backend correctly rejects.

**Completeness — what a GST product must have and this does not**
- **IMS.** Mandatory since 01-04-2026. Accept / Reject / Pending, deemed
  acceptance, the recompute step. **Nothing exists** — no table, no column, no
  screen. This is the single largest functional gap in the product.
- **A real 2B reconciliation** reading `purchase_bills` from the database and
  parsing the portal's own JSON (`data.docdata.b2b[].inv[]`), persisting to
  `gstr2a_records`, with a per-bill match status.
- **GSTR-9C**, **composition** (CMP-08, GSTR-4), **GSTR-1A**.
- **Multi-GSTIN per client.** One client, one registration today, and the return
  tables are `UNIQUE (client_id, period)` — so a two-state business cannot be
  modelled at all.
- **QRMP** quarterly returns and IFF: every period in the return engine is one
  calendar month.
- GSTR-9 is a tab that can never hold anything — no computation, no draft creation.
- §47 late fee and §50 interest are computed nowhere.
- Non-GST outward supplies dropped from 3.1(e); deemed exports and SEZ filed as
  physical exports in 6A, losing the recipient GSTIN; B2CS uses a blended rate that
  produces rates which do not exist.
- The correction window always reports 30 November — the "or the annual return,
  whichever is earlier" limb is never wired, which tells a CA a correction is
  available when it is not.
- The GSTR-1 validator never runs on the path a CA actually uses.
- **The three-year filing bar** — live since the July 2025 period and rolling
  monthly. Nothing tracks it. For a firm with 50 clients this is a standing risk
  nobody can track by hand.
- GST 2.0 (22-09-2025) added a **40% demerit rate** the invoice editor cannot select.

**Reachability**: the module's most differentiating backend work — amendments, the
exception report, the ITC register, advances, portal sync — has **no screen at all**.

---

## 4. Income tax / ITR — C to A+

**Correctness (4 critical, 14 high)** — the first four in flight:
- **No entity computation path exists.** `compute_entity_tax`, MAT/AMT and the
  presumptive engine are complete, tested and imported by *nothing*. Six of seven
  production clients are companies/LLP/firm and cannot be computed at all.
- A capital **loss** entered as a negative reduces tax on salary (§71(3)).
- §80G has no qualifying limit (§80G(4)) and no cash cap (§80G(5D)).
- Capital gains ignore the **date of transfer** — pre-23-07-2024 sales charged at
  Budget-2024 rates; holding period counted in whole months, not days.
- §112's grandfathered indexation option applied to assessees who do not have it —
  **₹2,42,126 understated on one probe, today**.
- §234A and §234B exist and are exposed by no endpoint; **no** interest reaches
  `net_payable` at all, 234C included.
- The tax-audit due date is wrong in all three places it is implemented.
- `CII_BY_FY["2025-26"]` is **380 where six sources say 376**, and FY 2026-27 (384)
  is missing, so every indexed computation today uses the wrong year *and* value.

**Completeness**
- **Form 3CD** — the tax-audit report. Absent; the module is a four-field tracker.
- **§32 block-of-assets depreciation** — WDV blocks, the 180-day half-rate rule,
  additional depreciation. Implemented nowhere, and the book-to-tax bridge that
  needs it is dead code.
- **Brought-forward losses** stored and displayed but never entering the
  computation, with no screen to create or utilise them.
- **§54/54F/54EC/54B** reinvestment exemptions and §112A grandfathering under
  §55(2)(ac).
- AIS/TIS import that persists (the screen keeps everything in React state).
- §139(5) revised and §139(8A) updated returns; only 4 of 7 ITR forms; a UNIQUE
  constraint actively blocks recording a revised return beside its original.
- The per-client Tax Computation workspace collects **five figures** — no
  deductions, no house property, no capital gains.

---

## 5. TDS/TCS — C to A+

**Correctness** — the threshold family is in flight:
- FY aggregate thresholds missing for §194J/H/A/D/G/Q; catch-up on the crossing
  bill; §194Q charging 0.1% of the whole invoice.
- §194I and §194J sub-rates ignored (2% cases charged at 10%): **₹1,00,000 withheld
  where ₹20,000 is due** on equipment rent.
- §195 payee class ignored — a foreign firm priced as a company.
- Surcharge and cess stacked **on top of a DTAA treaty rate**.
- The vendor's TDS rate is collected, displayed on a list, and never used.
- 26AS Part D refunds counted as TDS credits; the (PAN, section) match key collapses
  multiple rows.
- §194IA is offered in the vendor dropdown and the engine raises on it.

**Completeness — what makes a TDS product buyable**
- **FVU/RPU-format output.** The only export is a JSON blob. A CA buys a TDS product
  that produces a file the FVU accepts; without it the module cannot be sold.
- **Challan management**: challan 281 preparation, OLTAS/e-pay linkage, mapping
  deductions to challans (today every deductee row is stamped with the first challan
  found for its section).
- **§201(1A) interest and §234E late fee** — computed nowhere a CA can use.
- **27Q** (non-residents are computed, registered, then deliberately excluded).
- **TCS entirely** — §206C(1)/(1F)/(1G), Form 27EQ, Form 27D.
- **§197 lower-deduction certificates** — no number, rate, threshold or validity.
- Form 16/16A creation always fails against the real database (the UI sends
  "Form 16A"; the CHECK constraint expects something else).
- Correction statements.
- No 24Q filing deadline and no monthly deposit deadline in the compliance calendar.

**Security**: `tds_deductions` and `tds_returns` are written directly from the
browser with no role check — and the test that exists to catch exactly this **passes
green while missing them**, because its scanner window is 400 characters and the
call sites sit 441, 561 and 729 away.

---

## 6. Sales cycle — C to A+

**Correctness**
- The invoice PDF names the **CA firm** as supplier with the firm's GSTIN and PAN,
  hardcodes SAC 998211 and an 18% rate, and omits quantity, unit, per-line rate,
  place of supply and the reverse-charge statement. Four call paths including the
  client portal. **In flight.**
- Deleting a middle draft credit note **permanently wedges** that client's numbering
  for the rest of the year.
- Seven states and union territories cannot be selected as a place of supply.
- The Outstanding tile sums full invoice totals for partly-paid invoices and ignores
  credit notes; it is also period-scoped, so it is not a receivable balance at all.
- Every receipt debits one firm-wide "Bank" ledger, and the system-account lookup is
  not client-filtered — so the debit can land on **another client's** bank account.
- The receipt series uses a UTC clock, so 1 April between 00:00 and 05:30 IST lands
  in the wrong financial year.

**Completeness**
- **A discount field.** None — not per line, not at document level. Every SME
  invoice has one.
- **Automatic numbering.** Manual by a recorded decision, but the Settings screen
  configures a prefix and series that **nothing reads** — as do branding, invoice
  templates, bank/UPI details and footer text.
- Export/SEZ invoices produce a GSTR-1 the portal rejects (shipping bill number,
  date and port code hardcoded empty).
- An unallocated advance receipt can never be applied to a later invoice.
- TDS deducted by the customer is recordable only through the bank-settle path, not
  the standalone receipt form.
- Credit limits, dunning that reaches the client's customer, e-invoice/e-way payload
  generation (today both only *record* what a human obtained).

---

## 7. Purchase cycle — C to A+

**Correctness**
- The TDS threshold family above, on the path that actually posts.
- §17(5) blocked credit is still debited to GST Input, leaving a permanent phantom
  asset — and it is **unsettable from any screen**, while the editor *warns* about
  §17(5) and offers nothing to act on. These two must be fixed together: fixing the
  UI alone makes a latent wrong number live.
- Rule 37 ignores debit and credit notes and **double-reverses**: ₹18,000 where
  ₹9,000 is right.
- A purchase bill can be created into a period whose GSTR-3B is filed — the lock
  covers update but not create.
- No TDS on vendor payments or advances at all.

**Completeness**
- **RCM self-invoice** (§31(3)(f)) and the payment voucher.
- **Import of goods** — IGST on the Bill of Entry lands in 4(A)(5) rather than
  4(A)(1).
- §197 certificates; ITC on capital goods; Rule 36(4)/2B matching that reads the
  purchase register the platform already holds.
- MSMED §43B(h) is a manually re-keyed side table with the statutory rule computed
  in TypeScript, disconnected from the ledger.
- Duplicate-bill detection on amount and date, not only bill number.
- A second, orphaned vendor master at `/accounting/suppliers` that no purchase path
  reads.

---

## 8. Payroll — C to A+

The engine is genuinely ahead of the Indian market. The surface cannot reach half of
it, and two statutory outputs are wrong.

**Correctness** — both in flight:
- The **ECR declares basic+DA while the contribution was computed on the s.2(88)
  base** — EPS at 11.66% of declared wages where EPFO validates 8.33%. The file is
  rejected or is a false declaration.
- 24Q Annexure II gives **every** employee the new regime's ₹75,000 standard
  deduction; old-regime employees are entitled to ₹50,000.
- `/statutory-position` computes PF on basic+DA while the run uses s.2(88):
  ₹1,200 vs ₹1,680 for the same employee on two screens.
- §10(13A) HRA and professional tax annualised as `month × 12` regardless of months
  employed: an October joiner's tax ₹85,800 vs ₹73,320 correct.
- Professional tax projected on the month's own levy, so a Tamil Nadu employee's
  year under-withholds ~₹1,525.
- The payslip PDF is headed with the **CA firm's** name, not the employing client.
- A draft run that was never finalised counts as TDS already deducted.
- `routers/payroll.py:3478` calls an undefined `logger` inside an `except` block.

**Completeness**
- **A run cannot be recomputed or discarded** — no DELETE, no recompute, and a
  second run for the month 409s. A wrong draft is uncorrectable through the product.
- **Seven finished backend capabilities have no screen**: the leaver settlement,
  arrears/§89 relief, perquisites, salary revisions, loans, the 24Q Annexure II, and
  applying a salary structure.
- `payroll_opening_positions` — YTD salary, YTD TDS, lifetime §10(10)/§10(10AA) — so
  a client can be onboarded in any month rather than only in April.
- The employee master collects neither PAN, joining date, UAN, ESIC number, bank
  details nor PT state on the client-workspace form; `eps_eligible` and
  `gratuity_act_covered` are settable **nowhere**.
- One-time and variable earnings; the month-end pack (bulk payslips, register,
  statutory summary); bank advice (generic NEFT/RTGS plus SBI/HDFC/ICICI).
- The payslip omits UAN, PF/ESIC numbers and bank details.
- Both firm-level screens load every payslip of every run the firm has ever produced.

---

## 9. Fixed assets and inventory — C to A+

**Correctness** — both in flight:
- The **"Schedule II" default WDV rates are not Schedule II rates**: Office
  Equipment 13.91% against 45.07%, Computers 31.67% against 63.16%; Furniture 10%
  and Intangibles 25% are the *Income Tax Act* rates. Two statutes under one name.
- Monthly depreciation **cannot complete**: `"YYYY-MM"` written into a `date` column,
  so the journal posts and the register never updates.
- Depreciation is monthly-only with no catch-up and silently skips a missed month.
- Disposal does not charge depreciation to the disposal date, so every mid-year sale
  has a wrong gain or loss.
- Asset acquisition always credits Bank — no vendor, no GST/ITC, no link to the bill.
- The auto-generated Fixed Assets note reports a theoretical annual charge that need
  not match what was posted.
- The stock ledger's running balance does not foot, and migration 250 rebuilt
  production's totals in a **different order** from the one the code chains by.

**Completeness**
- **No edit path for an asset at all** — only create, depreciate, dispose. An
  impairment leaves depreciation charging on the un-impaired base for ever.
- §32 block-of-assets depreciation (shared with income tax).
- CWIP, revaluation, impairment, component accounting, shift working, transfers,
  physical verification.
- **Closing stock as at a date** — there is no such figure, which is required for
  any interim statement.
- FIFO and standard cost; batches and expiry; godowns; item groups; alternate units;
  reorder levels; BOM; stock transfers.

---

## 10. The five modules that were never deep-audited

Item 0 of the plan. Their grades are provisional and this list is what my own
lighter pass found, not a reader's.

- **Reporting / year-end (B−)**: the statements and Schedule III notes are strong;
  year-end adjustments cannot post; the Schedules stage errors on every tab because
  the frontend requests a route that is not mounted; the Schedule III Mapping screen
  changes nothing.
- **Practice management (B−)**: obligation generation and the daily sweep genuinely
  run in production (452 successful runs). Billing, time and collections are
  unexercised. WhatsApp is `wa.me` deep links, one client at a time — not the
  Business API.
- **AI / intelligence (D)**: the copilot sends Groq client counts, health scores and
  lifecycle stage — **no trial balance, no GST figure, no TDS**. Cross-client
  patterns are a hardcoded stub. The whole AI-insights surface is reachable from no
  screen. Client PAN and GSTIN go to Groq on every call, which is a DPDP question.
- **Platform / security (B−)**: twelve SECURITY DEFINER functions executable by
  `anon`, one of which takes the tenant as an argument; leaked-password protection
  off; dead `_backup_247_*` tables in production. **In flight.**
- **Frontend / UX (C)**: 27 pages over 800 lines (the largest is 4,537); 297 direct
  PostgREST calls with 23 tables written straight from the browser; `_redirects`
  holds 98 dynamic rules against Cloudflare's hard cap of **100**.

---

## 11. The order to do it in

Derived from §12 of the audit: **make correctness provable first**, then monthly
before quarterly before annual, because that way every quarter of work lands on
something the firm uses that month.

| # | Stage | What | Why here |
|---|---|---|---|
| 0 | **Prove it** | The statutory golden-case suite. Thirty to forty worked examples derived from the Act by a human and asserted end to end. **Fix the four tests that pin wrong numbers first.** Plus one integration test against a real schema — five defects are "writes a column that never existed". | Nobody is using the product, so nothing is bleeding. Without this, every fix below can silently regress, and two already have a test asserting the wrong answer. |
| 1 | **Nothing wrong reaches a CA** | Every critical in §§1–9. **In flight today.** | These are what lose the first trial. |
| 2 | **The monthly loop closes** | GST: IMS, a real 2B reconciliation, multi-GSTIN, QRMP. Bank: BRS, cash book, undo, the O(n²). Sales/purchase: discount, numbering, §17(5), RCM self-invoice. Accounting: ledger screen, hierarchical CoA, day book, `localStorage` → database. | This is the work a CA does 12 times a year. It is where retention is won. |
| 3 | **Quarterly and the modules sold alone** | TDS: FVU output, challans, §201(1A)/§234E, 27Q, TCS, §197. Payroll: opening positions, the seven unreachable capabilities, recompute/discard, the month-end pack. | Quarterly pain, and the two modules a CA would buy standalone. |
| 4 | **Annual** | Income tax: entity computation wired up, Form 3CD, §32 blocks, loss carry-forward, the §54 family. Year-end: adjustments, the schedules stage. Assets: edit path, Schedule II done from useful lives. | Annual, so it can follow — but it must exist before the first year-end a client reaches. |
| 5 | **The reasons to stay** | The analytics layer from §12.4 of the audit: the firm's morning queue, ledger-grounded exceptions, cross-client intelligence, practice economics, the client-facing one-pager. | Cannot ship before the numbers are right. An anomaly detector on a wrong set-off teaches CAs to distrust the product's judgement. |
| 6 | **Real filing** | Replace each demo flow with its live rail as each registration lands. See `docs/compliance/07-getting-permission-to-file.md`. | Gated by paperwork, not code. Runs in parallel from today. |

**Honest sizing.** Stage 0 is days. Stage 1 is weeks. Stages 2–4 are the bulk —
call it three quarters for a small team, and that is with the engines already
built. Stage 5 is a quarter. Anyone promising all fourteen modules at A+ inside a
quarter is going to hand you code that does not work.

**What that buys at each stage:** after Stage 1 the product is safe to demo. After
Stage 2 a CA can run a client's month end to end and would keep paying. After
Stage 3 the TDS and payroll modules are independently buyable. After Stage 4 the
product covers a full statutory year. After Stage 5 it is differentiated rather
than merely complete.

---

## 12. Stage 0 and Stage 1, landed 8 September 2026

Everything listed below is **merged, tested and pushed**, each with a stated
negative control — how many tests fail against the previous code. Nine commits
on `claude/ca-platform-audit-roadmap-yuoad3`. Read this section as the record of
what moved, not as a plan.

| What | Where it landed | Negative control |
|---|---|---|
| TDS aggregate thresholds on §§194A/D/G/H/J; the charge on the FY aggregate with §200 credit; §194Q on the excess AND aggregating | `domain/tds/`, `routers/purchase_bills.py` | 12 tests, +2 for the §194Q aggregate limb, +3 existing tests that were pinning wrong numbers |
| GSTR-3B §49(5)(b)/(c) cross-utilisation; reverse charge as cash under §49(4)/§2(82); zero-rated IGST — **and all nine callers, to the screen** | `domain/gst/gstr3b_computer.py`, both services, `routers/gst.py`, 5 web files | 24 + 5 + 10 |
| Capital gains forked on 23-07-2024 with the holding-period change and the §112(1) fifth proviso; the CII 380→376 correction; §71(3)/§74 loss floor; §80G(4) ceiling and §80G(5D) cash bar | `domain/income_tax/`, `routers/income_tax.py`, 3 web files | 21 + 17 |
| ECR wage base; Annexure II regime split; the pre-Code EPF §6 base; one PF implementation; HRA annualisation; an unbound `logger` | `domain/payroll/`, `routers/payroll.py` | 17 of 23 |
| Schedule II lives replacing Income-tax Act block rates; `YYYY-MM` into a `date` column; the silent month skip | `routers/fixed_assets.py`, the web register | 6 / 39 / 15 / 7 / 2 / 7 |
| The sales-invoice PDF naming the **client** as supplier, with the Rule 46 fields | `services/invoice_pdf_service.py` | 18 of 23 |
| Year-end adjustments through the posting kernel; a filed GST return locking its period | `routers/year_end_adjustments.py`, `lib/data/gst.ts` | 8 of 11, 10 of 10 |
| Nine money fields still reading "1,25,000" as ₹1, including the bank settlement that posts to the GL | 8 web files | 4 of 4, and a repo-wide sweep now guards it |
| The copilot quoting TDS thresholds FA 2025 had raised — now generated from the registry | `routers/assistant.py` | 3 of 4 |
| Filing-demo fidelity for the CA trials, with the not-filed signal made structural and the OTP field removed | `services/filing_demo/`, the wizard | 38 backend, 4 of 5 web |
| The registration playbook for GSP, ERI and the rest | `docs/compliance/07-…` | n/a |

**Two things learned that are worth carrying into Stage 2.**

First, *fixing the engine is half the job*. Four of these — the GSTR-3B cash
figure, the §80G fields, the capital-gains assessee type, the filing demo's
payment table — were computed correctly and reached no screen, because the
engine and its callers were changed in different passes. A figure no CA is
shown is not a fixed bug, and "the computer is right" is not the test.

Second, *the prose was never the guard*. Three of the defects above were things
CLAUDE.md asserted were already true: every money site converted, the
pre-commencement PF base reproducing `basic + DA`, no statutory depreciation
table in code. Each is now held by a test instead of a sentence.

### The original list, as written on 7 September

Started the day this list was written:

- TDS aggregate thresholds, §194C catch-up, §194Q on the excess — **and the two
  tests that pin the wrong numbers, fixed first**.
- GSTR-3B §49(5) cross-utilisation, RCM liability in cash, zero-rated IGST.
- Income tax: capital-loss floor, §80G qualifying limit and cash cap, capital-gains
  transfer date, holding period in days.
- Payroll: the ECR wage base, Annexure II standard deduction, the statutory-position
  parity, HRA annualisation, the `logger` crash.
- Fixed assets: Schedule II rates derived from useful lives, the `YYYY-MM`-into-`date`
  posting failure, the silent month skip.
- The sales-invoice PDF rendering the **client** as supplier, with Rule 46 fields.
- Year-end adjustments routed through the posting kernel; the GST period lock
  actually engaging.
- The ITR due date for companies, decided on the backend; the `anon` RPC revocation.
- Filing-demo fidelity for the CA trials, with the not-filed signal strengthened.
- The registration playbook for GSP, ERI and the rest.
