# What is left, 8 September 2026 (second pass, against `9fbe40d`)

The five steps of §7 of `2026-09-08-what-is-left.md` are merged and on `main`,
and migrations 338, 339 and 340 are applied to production. This is the re-score
that follows, on the habit that document argued for: **a tranche's own summary
is not evidence.**

## How this pass was done, and what it does NOT claim

The 8 September pass put nine independent readers over all 278 findings. This
one is narrower and says so:

1. the 8 September verdicts are the **baseline**;
2. `git diff 46bd46c..9fbe40d --name-only` gives the exact file set the five
   steps changed — 64 files outside tests and docs;
3. every finding the five steps claimed to close was **re-verified by probe** —
   code run, not diffs read;
4. the changed code was then read **adversarially**, looking for what the five
   steps broke;
5. each of the ten "no finding id yet" items from §4 of the previous document
   was re-checked individually.

**A finding in code the five steps did not touch keeps its 8 September verdict.**
That is the honest limit of this pass. It is not a fresh audit of the 228 open
findings; it is a check of the delta, plus a hunt for new breakage.

The verdicts that moved are written onto each finding as `rescore_2026_09_08b`.
The earlier `rescore_2026_09_08` and `verification` blocks are left alone.

---

## 1. The count

| | fixed | partial | still open |
|---|--:|--:|--:|
| **278 findings**, against `9fbe40d` | **39** | **11** | **228** |

Twelve moved to fixed since `46bd46c`: **GST-01, GST-04, IT-01, PUR-01, PUR-11,
PAY-03, PAY-17, ACC-04, SALES-15, FA-08, BANK-19, IT-29**.

**239 items of remaining work** (open + partial), by corrected severity:

| critical | high | medium | low |
|--:|--:|--:|--:|
| **1** | 80 | 120 | 38 |

By subsystem, remaining only:

| subsystem | crit | high | med | low | total |
|---|--:|--:|--:|--:|--:|
| TDS / TCS | 0 | 12 | 13 | 5 | 30 |
| Banking | 0 | 9 | 13 | 6 | 28 |
| Sales cycle | 0 | 10 | 14 | 4 | 28 |
| GST | 0 | 9 | 16 | 2 | 27 |
| Purchase cycle | 0 | 9 | 13 | 5 | 27 |
| Fixed assets & inventory | 1 | 7 | 15 | 3 | 26 |
| Accounting core | 0 | 7 | 13 | 5 | 25 |
| Income tax / ITR | 0 | 11 | 8 | 6 | 25 |
| Payroll | 0 | 6 | 15 | 2 | 23 |

**Four of the five criticals are closed.** One is left, and it is latent:

| id | state | what is left |
|---|---|---|
| **FA-02** | partial | The default WDV rate is now derived from Schedule II Part C's useful lives and is right. **The stored rows are not.** There is no backfill migration, the compute path prefers the asset's own `wdv_rate_percent`, and FA-10 leaves no edit path — so a wrong rate is frozen in for the asset's life. Production holds **zero** fixed assets, so nothing is wrong today; it goes wrong the first time a register is migrated in. |

---

## 2. What the five steps broke

Seven items. **The mock suite is 10,389 passed / 980 skipped on `main` and
catches none of them**, which is the argument for doing this pass at all.

### 2.1 Nothing records that a period was reconciled — HIGH, three faces, one cause

`gstr2a_records` is the only table the reconciliation writes, and it holds **one
row per PORTAL document**. So a period reconciled against a 2B that yields no
rows leaves no trace at all — and "no trace" is what the code everywhere reads
as "nobody has reconciled this".

**(a) Rule 36(4) does not cap when it must.** `_gstr2a_for_period` filters out
documents 2B marks `itcavl = "N"`, and `compute_gstr3b` then derives
`have_2b = len(gstr2a_records) > 0` from the **already-filtered** list. So the
flag added to tell "no file" apart from "file on file, nothing eligible"
collapses the two back together:

```
2B on file, every document itcavl='N':
   rows reaching the computer : 0
   have_2b                    : False
   ITC allowed                : Rs 500,000   capped=False
   ITC that SHOULD be allowed : Rs 0   (s.16(2)(aa): 2B allows none)

no 2B uploaded at all: ITC allowed Rs 500,000     <- identical
```

The same holds for the commonest version: a 2B on file in which **nobody
filed anything**. The CA's own screen says "the supplier has not filed"; the
return claims the credit anyway.

**(b) The Purchases column says "not reconciled" for the client who most needs
chasing.** `recon2BLabel` distinguishes the two by `periodReconciled`, and its
comment names the requirement exactly — *"the two must not read the same"*. But
`reconciledPeriods` is built from a query carrying `.not("purchase_bill_id",
"is", null)`, so only rows that **matched a bill** contribute. A client whose
suppliers filed nothing produces no matched rows, so the period never enters the
set, and every bill reads "not reconciled".

**(c) A period reconciled to an empty result reads back as never reconciled** on
the GST tab, for the same reason.

**The fix is one thing, not three:** record the reconciliation itself — a header
row per (client, period) carrying the file's GSTIN, `generated_on` and the
document count — and derive `have_2b` and `periodReconciled` from that rather
than from the presence of document rows.

### 2.2 A credit note and a debit note with the same number wipe the period — HIGH

`uq_gstr2a_records_document` is `(client_id, return_period, section,
supplier_gstin, invoice_number)`. **`document_type` is not in it.** In `cdnr`,
`typ` "C" and "D" are credit and debit notes, and a supplier's two series are
independent — the same number in both is ordinary. Run on `main`:

```
documents parsed: 2
   key: ('cdnr', '27AAAAA0000A1Z5', 'CN-1')
   key: ('cdnr', '27AAAAA0000A1Z5', 'CN-1')
DUPLICATE NATURAL KEY IN ONE FILE: True
```

`reconcile_2b` then does **delete-then-insert with no transaction**: the
`DELETE` for the period commits, the `INSERT` raises on the unique index, and
the period's previous reconciliation is gone with nothing written in its place.
A first upload of such a file writes nothing at all.

Fix: put `document_type` in the index (a migration), and make the replace
atomic — the codebase already uses RPCs for exactly this shape.

### 2.3 The new service has no pagination — MEDIUM

`read_book_bills` and `read_reconciliation` each do a bare `.execute()`.
PostgREST caps at 1000 rows. **Eleven** sibling services carry a `_paginate_all`
for this, including `gst_return_service`, whose own comment says the failure
"appears only on a client with a busy month, which is the one whose return most
needs the rows". A client with more than 1000 purchase bills in a month has the
excess silently dropped from the book side, and every 2B document for those
bills is then reported as `missing_in_books` — telling the CA to chase documents
they already hold. Production's whole book is 759 bills, so this is latent.

### 2.4 The entity computation reaches the year fallback, and stamps it verified — MEDIUM

IT-01 gave a company, firm and LLP a computation path. `entity_rates`,
`minimum_tax` and `statutory_rates` all hold only 2025-26 and 2026-27, and all
of them **fall back rather than fail**. Run on `main`:

```
asked for fy      : 2024-25
response .fy      : 2025-26
response .rates_verified: True
```

The substituted year IS in the payload, which is better than nothing. But
`rates_verified: true` is an affirmative claim that a Finance Act was checked
for the year the caller asked about, and nothing refuses. This is the trap
CLAUDE.md's "What has to be updated every financial year" section is written
about; IT-01 widened the set of callers who can fall into it.

### 2.5 The payslip refusal is delivered as "Salary slip not found" — LOW

PAY-03's `load_employer` correctly refuses a run with no client. But
`GET /payroll/slips/{id}/payslip.pdf` maps **every** `ValueError` to
`404 "Salary slip not found"` — so the CA is told the slip does not exist when
it does, and the real reason (the run carries no client) never reaches them.
The ZIP route on the same file gets this right: `HTTPException(404, str(e))`.

### 2.6 The ₹ glyph is broken on the payslip too — MEDIUM

Flagged on 8 September for the fee invoice and the customer statement. It is
wider than that, and step 3 edited one of the affected files without noticing.
Rendered and read back, rather than reasoned about:

```
'PAYSLIP  Net Pay: ■1,234.56'
'STATEMENT Invoiced: ■1,000.00'
```

Helvetica is WinAnsiEncoding and has no U+20B9. Per file: `payslip_pdf_service`
₹×5 / Rs.×0, `statement_pdf_service` ₹×3 / Rs.×0, `year_end_pdf_service` ₹×7 /
Rs.×0. `invoice_pdf_service` and `engagement_pdf_service` handle it and their
comments say why. **The payslip is a document an employee receives**, and the
year-end schedules go into a signed set.

### 2.7 The disposal default date is still UTC — LOW

`routers/fixed_assets.py` lines 493, 653 and 784 use
`datetime.now(timezone.utc)` while the module imports `core.ist_clock`. Line 653
is the disposal date default — inside the path step 1 edited for FA-08. At
00:20 IST on 1 April, that defaults a disposal to 31 March: the previous
financial year, quite possibly one the CA has just locked.

---

## 3. Two corrections to the 8 September record

Both were listed there as findings; both are wrong, and saying so is the point
of re-checking rather than re-copying.

- **`rbac("banking", "approve")` is NOT unenforced.** The claim was "enforced by
  no route, so any remedy of the form 'gate this on Manager+' has nothing to
  gate on". It is enforced at `routers/banking.py:2118` —
  `can(current_user.get("role") or "", "banking", "approve")` — on the
  trusted-rule promotion path, imperatively rather than as an `rbac()`
  dependency. The grep that produced the finding looked only for the dependency
  form.

- **`annexure2.py` does not cap §16(ia) at §17(1) alone.** The code computes
  `gross_salary = 17(1) + 17(2) + 17(3)`, then `net = gross − exempt_10`, then
  caps the standard deduction at `net`. §17(2) and §17(3) are in the base. The
  real defect is that both fields are **never populated** — which is PAY-07, an
  existing finding, not a separate capping bug.

---

## 4. The other eight items from §4, re-checked

All still open. Probes, not assertions:

| item | probe on `9fbe40d` |
|---|---|
| `post_draft` bypasses the client year lock | `journal_posting_service.post_draft` calls `period_validation_service.validate_posting_date(firm_id, entry_date)` — **firm-scoped only**. `period_lock_service.assert_open(db, firm_id, client_id, …)` exists and takes a `client_id`; this path does not use it. |
| The capital-gains fork never reached `itr_engine` | `date_of_transfer`, `transfer_date`, `sale_date`, `fork` — **none** appears in `itr_engine.py`. `capital_gains_engine` knows the fork; the engine that calls it is still FY-keyed. |
| The filing date is never collected | `gst_filing_record_service`: `filed_date=filed_date or ist_today().isoformat()`. `filings.filed_date` is the day the ARN was typed. |
| `/gst`'s 32-second request | `services/bank_register_service.py:212-213` — `min(filtered, key=lambda l: all_lines.index(l))` then `all_lines.index(earliest)`. The O(n²) is still there and now has an address. |
| PAY-22 is a one-liner | `(basic + da) * months_in_year` is computed at `routers/payroll.py:1161`. `salary_for_80ccd2_paise` is a real field, wired through `routers/income_tax.py:224` and `declarations.py:389` — and **`routers/payroll.py` never passes it**. |
| PAY-10 is milder than its evidence | unchanged; the module is display-only and the stale header comment is what makes it read worse. |
| The ₹ sign | §2.6 above — confirmed and wider. |
| Three UTC "today"s | §2.7 above — confirmed, lines 493 / 653 / 784. |

---

## 5. The 80 highs, unchanged in shape

Same seven themes as 8 September; the ids are in the findings files. Three of
them shrank:

1. **Cash does not exist.** ACC-02, ACC-03, SALES-08, BANK-20 — cash receipts
   and cash vendor payments post to *Bank*, Cash in Hand never moves, no cash
   book, no petty cash.
2. **Reconciliation is a tick-off, not a BRS.** BANK-04/05/06/09 — no
   unpresented cheques, no deposits in transit, an "Adjustments" plug that can
   force a tie-out into a signed PDF, no undo for a mis-imported statement.
3. **Finished backends no screen reaches.** PAY-11 (seven capabilities including
   the leaver settlement), IT-13 (§234A/§234B), IT-16 (presumptive), IT-17,
   PUR-05 (§17(5) blocked credit), PUR-14, GST-13, SALES-13.
4. **TDS has a second implementation in the browser.** TDS-05, with TDS-03,
   TDS-04, TDS-11, TDS-15, TDS-09 (no 27Q), TDS-22.
5. **GSTR-1 cases the portal rejects.** GST-07, GST-08, SALES-10, SALES-06,
   SALES-09, GST-11 (no QRMP), GST-20.
6. **Nothing can be corrected.** FA-10, ACC-05, PAY-12, SALES-04, ACC-09.
7. **State that is not in the database.** ACC-06 — recurring journals, budgets
   and retainers in one browser's `localStorage`.

---

## 6. What no code closes — a human must supply it

Unchanged from 8 September. See CLAUDE.md §3b. Professional tax for 18 more
states and LWF for all 16; the seven ITR JSON schemas per assessment year; DTAA
rates; the Bonus Act §12 minimum wage; SBI's Rule 3(7)(i) rate; ESIC reason
codes; prior-year income for §89 and lifetime §10(10)/§10(10AA) exemption used;
vendor MSMED classification.

## 7. Commercial gates — months, not code

Unchanged. `docs/compliance/07-getting-permission-to-file.md`. Free now: the
Third Party Software Utility Developer registration, the NIC e-invoice sandbox.
Months of commercial work: ERI Type-2, GSP or an ASP sub-licence, NIC production
credentials, an India static-IP egress hop. No route exists for MCA, EPFO or
ESIC. Account Aggregator is closed. e-invoice IRN and e-way bill remain the only
two statutory outputs software can complete end to end.

---

## 8. Suggested order

1. **§2.1 and §2.2 together.** Both are in the reconciliation the last tranche
   shipped, both need a migration, and §2.2 destroys data. §2.1 is the one that
   makes a return claim credit §16(2)(aa) withholds — the module was shipped to
   stop exactly that.
2. **§2.3, §2.4, §2.6** — an afternoon each. §2.6 is the only one a CA's
   *employee* sees.
3. **FA-02's backfill**, while production still holds zero assets. After the
   first register is migrated in, it needs a data fix as well as a code one.
4. **The §4 carry-overs**, cheapest first: PAY-22 is genuinely one line;
   `post_draft`'s missing `client_id` is one argument; the UTC dates are three.
5. **Then the roadmap's Stage 2 → 3 → 4**, unchanged, which the closure of
   GST-04 opened.

Two things this pass adds to the habits list:

- **A green suite is not a rescore.** 10,389 tests pass on `main` and every one
  of §2's seven items is live. The tests were written against the fix that was
  intended, not against the shapes it missed.
- **Re-check the previous pass's findings, not just its verdicts.** Two of the
  8 September items were wrong (§3), and both were wrong because a grep matched
  one spelling of the thing it was looking for. That is the same defect as the
  money-parser guard, in a document rather than in code.
