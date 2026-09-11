# Open questions — things only the owner can decide, or that need a source we do not have

**This file is the register. Nothing is closed here without a decision recorded
beside it, and nothing gets dropped because a context window ended.**

**Last rewritten: 11 September 2026**, after migration 366. Everything that had
been answered, fixed or overtaken was REMOVED rather than left with a "FIXED"
banner on it — the record of what was fixed lives in
`docs/audits/WHERE-WE-STOPPED.md`, and a register half full of closed items
stops being read. What is below is open.

Five kinds of thing, kept apart because they need different actions:

* **A. Owner decisions** — the code works either way; somebody has to choose.
* **B. Facts nobody in the repo holds** — a state notification, a bank's rate, a
  schema download. Code cannot derive them, and guessing produces a confidently
  wrong number in somebody's pay or return.
* **C. Standing decisions, and what would reopen each** — already decided, kept
  because the trigger matters.
* **D. Known-wrong, reported, deliberately not fixed** — real defects with a
  reason for the delay.
* **E. Needs a human with a browser or a login** — nothing in the repo can get it.

---

## ⚠️ Read this before working from any audit document

**Sixteen of twenty-two audit claims checked on 11 September 2026 were stale or
already closed.** Six "nothing anywhere does X" claims, six of the seven §2
items in `2026-09-08b-what-is-left.md`, and four of its eight §4 carry-overs.

| claim | what was actually there |
|---|---|
| FA-10 — no edit path for a fixed asset | the edit path existed |
| the workflow repository has no join | the join existed |
| F7 — nothing tracks a DSC | `dsc_records` since migration **014** |
| F5 — PT needs state slabs a human must supply first | `firm_pt_slabs` since migration **327** |
| FA-02 — no edit path, a wrong rate frozen for life | an edit path, a detector, and a statutory reason not to backfill |
| `/api/dsc` has no caller *(this session's own new ratchet)* | it had two — the guard matches paths, not verbs |

Four of those would have shipped a **second implementation of something that
already worked**. One was produced by a guard written the same week.

**So the ~228 remaining findings are LEADS, not a work list.** Read the code
before building against any of them, including anything written this session.

---

## A. Owner decisions

### A1. Does the §80CCD(2) salary base include arrears of an earlier year?

**The only genuinely open decision here, and it blocks a one-line fix.**

`routers/payroll.py` computes `(basic + da) * months_in_year` and passes it as
`basic_plus_da_paise` (the §10(13A) HRA base) but **never passes
`salary_for_80ccd2_paise`**, which `declarations.compute` accepts and
`itr_engine` uses. The fallback is `req.gross_salary_paise` — which includes
HRA and every other allowance, the exact things the **Explanation to §80CCD**
expressly excludes ("'salary' includes dearness allowance, if the terms of
employment so provide, but excludes all other allowances and perquisites").

**So the 14% cap is computed on too large a base and §80CCD(2) is OVER-allowed,
under-stating tax.** That is PAY-22, and it is live.

**What is not settled** is which figure to pass. The `basic_plus_da_paise`
already computed is deliberately the RECURRING basic and DA, with arrears
excluded — and that exclusion exists for a §10(13A) reason (last year's arrears
must not inflate this year's HRA base) that does not obviously carry to
§80CCD(2), whose cap is "of his salary **in the previous year**" and whose
employer contribution may well have been made on the arrears too.

**Recommendation: pass the recurring basic + DA now.** It is unambiguously
closer to the statute than gross, and the error direction is safe — a smaller
base means a smaller deduction means more tax, never less. The arrears question
can then be settled without anything being wrong in the meantime.

### A2. Should the rule-based deadlines move out of the browser?

`app/calendar/page.tsx` still computes **twelve** deadlines in the browser —
GSTR-1, GSTR-3B, GSTR-9, the four advance-tax instalments, the four TDS return
quarters, and DIR-3 KYC. **They are correct today**: every one falls out of the
calendar date alone with no client fact involved, which is why they survived
when the three MCA ones (which need each company's own AGM date) had to move
server-side.

They nevertheless duplicate `services/compliance_engine.py`, which CLAUDE.md
names as the single source for every due date. Two implementations of one rule
drift; these have not yet.

**Not urgent, and it is a judgement about how much duplication to carry.**

---

## B. Facts nobody in the repo holds

Each of these REFUSES rather than guesses, and the refusal comes back as a named
gap in the response. Adding one is a human step. Full detail in CLAUDE.md §3b.

| # | What is missing | Where it is refused | Why it cannot be derived |
|---|---|---|---|
| B1 | Professional tax slabs for **18 more states** | `routers/payroll.py` holds only MH, TN, KA, WB; `domain/payroll/professional_tax.py` names the rest | per state, per scheduled employment, revised by notification. **Partly relieved**: `public.firm_pt_slabs` (migration 327) lets a firm record any state's slabs against the notification they read |
| B2 | **Labour Welfare Fund** amounts for all 16 states that levy it | `domain/payroll/lwf.py` | same, and with no firm-entry table yet |
| B3 | The **seven ITR JSON schemas** per assessment year | `domain/income_tax/schemas/`, wired in `itr_schema.py` | published per form per AY at incometax.gov.in; cannot be generated |
| B4 | **DTAA rates** by country × nature of income | `public.dtaa_treaty_rates` (migration 310) | ninety-odd treaties, MFN clauses needing their own §90(1) notification, several with no FTS article at all |
| B5 | **Bonus Act §12 minimum wage** per state / employment / skill grade | `domain/payroll/bonus.py` | §12 computes on ₹7,000 **or the minimum wage, whichever is HIGHER** |
| B6 | **SBI's Rule 3(7)(i) rate** | `domain/payroll/perquisites.py` | published by the bank on the first day of the previous year |
| B7 | **ESIC reason codes** | `domain/payroll/esic.py` | ESIC's own list — see E1 |
| B8 | An earlier year's **total income for §89** | `domain/payroll/arrears.py` | comes off the employee's return; the employer never held it |
| B9 | **Prior gratuity / leave exemption used** | `gratuity.py`, `leave_encashment.py` | §10(10) and §10(10AA) are LIFETIME limits across employers |
| B10 | A vendor's **MSMED classification** | `vendors.msme_status` | a fact about the SUPPLIER's Udyam registration; §43B(h) makes it change taxable income |
| B11 | Which accounts hold **unbilled dues** | `chart_of_accounts.unbilled_dues_side` + `schedule_iii_unbilled_reviews` | an unbilled due has no document; no account name decides it |
| B12 | **Which director signs which MCA form** | nothing holds it | `mca_directors` exists and `dsc_records` carries a PAN, so the join is possible — but the FACT of who signs what is a human decision nobody records. Until it exists, no "your signatory's DSC expires before this due date" warning can be honest |
| B13 | **Per-state professional tax RETURN formats** | not built | the remaining half of Track F5. The slab half is done (migration 327 + a 460-line Settings screen); the artefact is a different layout per state, the same twenty-two-way fan |

### B14. Does the ESIC portal still refuse `.xlsx` in 2026?

**This is now the ONLY thing that would reopen Track F1's dependency decision.**

F1's `.xls` half was decided NO on 11 September 2026: filling the portal's own
Excel 97-2003 template needs `xlrd` + `xlwt` + `xlutils`, two of them without a
release since 2017 and the reader pointed at an untrusted upload inside the
service holding every client's general ledger. The manual saying Excel 97-2003
traces to guidance from around **2011**, and egress is blocked here, so the
premise cannot be checked.

**Nothing is blocked.** What actually bounces an ESIC upload is a missing
insured person, not a file format — the upload is all-or-nothing against the
portal's own mapped list — and that check is built
(`domain/payroll/esic_mapped_ips.py`). If somebody confirms `.xlsx` is accepted,
the template work becomes cheap and the dependency question disappears
entirely.

### B15. Odisha and Punjab professional tax — is the count of 22 right?
`[S]`-graded and **probably one or two too high**. The 7 September research pass
found Odisha reported as having repealed its levy from 01-04-2026 and Punjab's
charge described as a Development Tax. Neither was confirmable (egress is
blocked). The list is deliberately NOT changed: naming a state that no longer
levies produces a false GAP warning, never a wrong deduction. Settle against the
state notifications.

### B16. Earlier years' Finance Acts, for §89
`rates_for()` substitutes `LATEST_VERIFIED_FY` for a missing year, and §89 is a
comparison of years AT THEIR OWN RATES — so a substitute makes the whole relief
a fiction that looks reasonable. The registry holds only 2025-26 and 2026-27, so
**§89 does not work for most real arrears** until earlier years are added.

### B17. FY 2024-25 capital gains cannot be represented
`statutory_rates.FYTaxRates` holds one CG rate set per FY, and the Finance
(No. 2) Act 2024 forked the rates on 23-07-2024 — so 2024-25 straddles. Adding
it needs pre/post buckets, as the ITR form itself splits them. Post-fork years
only, today.

### B18. Is the ESI wage base narrower under the Code?
`_compute_esi` uses gross; the Code on Social Security's definition is narrower,
so ESI may err the other way. **Unconfirmed, deliberately unchanged, and pinned
by a test** so a later change is deliberate. Gratuity likewise.

### B19. The §92E tax-audit report date
Deliberately not modelled: "one month prior" to 30 November is 30 October by
calendar arithmetic while professional sources commonly say 31 October, and that
one-day difference is unconfirmed.

### B20. Which ITR due date applies to an LLP, firm, trust or individual
`compliance_obligation_service.itr_due_date_for_client` decides only three cases
on facts the app holds and REFUSES the rest, returning 31 July (the earlier of
the two) with `decided: false` and a named gap. §44AB turns on the year's
turnover, an LLP's audit on LLP Act §34(4) with Rule 24(8), a trust's on
§12A(1)(b) — none of those figures is held against a client.

### B21. Which tax head a written-off stock ITC reversal belongs to
A §17(5)(h) write-off reverses credit taken on some mix of CGST/SGST and IGST
bills, and the write-off does not know which — the inventory module carries no
lot-to-bill link. INV-06 splits **intra-state by default** (odd paise to CGST),
writes the caveat into the register row's `notes`, and takes
`itc_reversal_is_interstate` on the adjustment so the CA can say otherwise. The
total reversed is right either way; only the head split is approximated.
Lot-level tracking would settle it and is not built.

---

## C. Standing decisions, and what would reopen each

Not questions. Recorded because the REOPENING TRIGGER is the useful part.

| decision | taken | what would reopen it |
|---|---|---|
| **A filed return closes only what FED it**, not the whole ledger — the posting kernel asks the CA's own closures, the filed-return branch guards documents that feed a return (migration 361) | 11 Sep 2026 | Wanting Tally's harder rule. Verified to be **one call site**: `phase2_journal_service` asks `period_lock_service.closure_reason` once, and pointing that at `lock_reason` gives the freeze. Read the reasoning first — GSTR-1 for June is filed on 11 July and GSTR-3B on the 20th, while June's bank reconciliation happens after both, so a hard freeze stops every June receipt, payment, bank entry, depreciation charge and payroll accrual from the 11th onwards |
| **Schedule III captions take the SCREEN's spelling** — hyphenated `Short-term`, plural `Employee Benefits Expense` | 11 Sep 2026 | Actually reading Schedule III. The decision rests on convergence (screen, stored data, classifier agreed), not on the statute — `icai.org` and every `.gov.in` are refused at the egress proxy. `CAPTION_ALIASES` honours the older spellings, so nothing stored is lost either way |
| **No BIFF8 dependencies** for the ESIC template | 11 Sep 2026 | B14 above — confirmation that the portal still refuses `.xlsx` |
| **A DSC is never hard-deleted from the screen** — renew supersedes instead | 11 Sep 2026 | A soft-delete column on `dsc_records`. Today a delete would destroy the record that a certificate ever existed |
| **No registrations are being pursued** — TPSUD, NIC e-invoice, ERI, GSP, an India static-IP hop | 11 Sep 2026 | A decision to file through the software. e-invoice and e-way bill are the cheapest restart (free, self-service sandbox, and the only two statutory outputs software can complete end to end). **MCA, EPFO, ESIC and professional tax have no route at all** — that one is not a decision, it is a fact about the portals |
| **Account Aggregator stays closed** | 6 Sep 2026 | A published purpose code covering bookkeeping. No FIU licence exists for a firm like this, and purpose defeats the partner route too. Nobody is waiting on anybody |

---

## D. Known-wrong, reported, deliberately not fixed

### D1. The capital-gains fork never reached `itr_engine`

`domain/income_tax/capital_gains_engine.py` knows the 23-07-2024 fork —
§111A 15%→20%, §112A 10%/₹1,00,000 → 12.5%/₹1,25,000, §112 20%-with-indexation
→ 12.5%-without, and §2(42A)'s moved holding periods. **The engine that calls it
is still FY-keyed**: `date_of_transfer`, `transfer_date`, `sale_date` and `fork`
have **zero occurrences** in `itr_engine.py`.

It is the DATE OF TRANSFER that decides, and a transfer before the cutoff is
governed by the earlier law indefinitely. Related to B17 — FY 2024-25 cannot be
represented at all until the rate registry gets pre/post buckets, so these two
are one piece of work.

### D2. `filings.filed_date` records when the ARN was typed

`gst_filing_record_service` does `filed_date=filed_date or ist_today()`, so a
return filed on the portal on the 11th and recorded here on the 14th is dated
the 14th. That date feeds `journal_period_lock_reason`, so the period unlocks
three days late — and the correction-window calculation (CGST §37(3), §39(9),
§16(4)) reads the same column.

Nothing collects the real date. The fix is a field on the record-filing call,
not a computation.

### D3. 137 of 904 mounted endpoints have no caller

Tracked as a ratchet — `tests/test_every_mounted_endpoint_has_a_way_in.py`, with
a per-prefix `BUDGET` and a `TOTAL_BUDGET` that may only fall. Not a question
and not a single defect: several are false positives no prose can clear (a path
suffix built from a variable is genuinely a call and no static scan of this
shape sees it), and some are deliberate.

**It found a real one on its first working day.** `/api/fixed-assets`
`register-integrity` — the whole of FA-02's remedy — reached no screen, and
CLAUDE.md's rule is that a figure the computer gets right and no screen shows is
not a fixed bug. The budget is the mechanism for working the rest down.

### D4. The 2B replace still has a non-atomic fallback

Migration 366's `replace_gstr2b_reconciliation` makes the real path one
transaction. The **statement-by-statement path remains for mock mode**, which has
no `DATABASE_URL` and no SQL functions, and the service falls back to it if the
RPC is unavailable — a local dev copy, or the window between a deploy and the
migration job.

Deliberate: falling through is strictly better than refusing to reconcile at
all, which is the behaviour that shipped for months. It logs a warning when it
happens. **It stops being a fallback the day mock mode gets transactions**, which
is not planned.

---

## E. Needs a human with a browser or a login

### E1. The ESIC numeric reason codes

They explain why an insured person had zero wages in a month, and ESIC surfaces
the list only inside the employer portal at filing time.
`domain/payroll/esic.py` deliberately refuses to invent one and withholds the
whole file until a CA supplies it — which the filing manual shows is more right
than when it was written, because **a zero-wage row removes that person from the
establishment**, so a guessed code would de-register somebody rather than merely
misreport them.

**Needs an ESIC employer login, which this firm does not have.** Not blocking:
the refusal is safe and the CA can type the code. It closes the day somebody is
next inside a client's ESIC portal.

### E2. Two statutory facts that would tidy things up, neither urgent

Odisha's reported professional-tax repeal and Punjab's Development Tax (B15 —
naming a state that no longer levies produces a false gap warning, never a wrong
deduction), and the current MCA XBRL validation tool version.

### E3. Schedule III itself

Every claim this product makes about Schedule III caption wording, and the
Division I / Division II ageing split, rests on memory and on convergence
between the screen and the classifier. `icai.org` and every `.gov.in` are
refused at this environment's egress proxy (`curl https://example.com` →
CONNECT 403 — a network policy, not a gov.in block). One reading of the actual
schedule would settle the C-table caption decision and confirm the ageing
tables.
