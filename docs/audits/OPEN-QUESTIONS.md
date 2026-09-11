# Open questions — things only the owner can decide, or that need a source we do not have

**This file is the register. Nothing is closed here without a decision recorded
beside it, and nothing gets dropped because a context window ended.**

Three kinds of thing live here, and they are kept apart because they need
different actions:

* **A. Owner decisions** — the code is fine either way; somebody has to choose.
* **B. Facts nobody in the repo holds** — a state notification, a bank's rate, a
  schema download. Code cannot derive them and guessing produces a confidently
  wrong number in somebody's pay or return.
* **C. Commercial gates** — a registration or a licence. Months, not code.
* **E. Operational** — something outside the code is failing and somebody has to
  look at a console this session cannot reach.

Last reviewed: 11 September 2026 (after Phase 11g).

---

## A. Owner decisions

### A1. Should a filed GST return freeze the whole ledger, or only what fed it?
**Status: decided by me, reversible on one word.** Phase 12a (migration 361)
splits "closed" in two: the posting kernel enforces the CA's own deliberate
closures (firm year lock, client year-end), and the filed-return branch is
asked only where a document that FEEDS a return is written — invoices, bills,
credit and debit notes, and the manual journal.

The alternative is Tally's shape: a period lock that blocks everything. I did
not take it because GSTR-1 for June is filed on 11 July and GSTR-3B on the 20th,
while June's bank reconciliation happens after both — so a hard freeze would
stop every June receipt, payment, bank entry, depreciation charge and payroll
accrual from the 11th onwards, for every client, every month.

**If you want the harder rule, it is now a one-line change** — the kernel calls
`period_closure_reason`; pointing it at `period_lock_reason` gives you the
freeze.

### A2. `/gst/reconciliation` — keep the browser-only screen, or delete it?
Two screens reconcile GSTR-2B. The real one is on the client GST tab and writes
`gstr2a_records`. `/gst/reconciliation` matches two uploaded files in the
browser and saves nothing; it carries a banner saying so and pointing at the
other. Recorded in `docs/audits/2026-09-08-what-is-left.md` §6b. Deleting it is
safe; keeping it costs a screen nobody can act on.

### A3. Which of Phase 11's fifteen features are worth building?
**ANSWERED 10 September 2026: all of them.** "Once all the 13 phases are done
then we will go to the open questions." Kept here only so the answer is on the
record — this is no longer a question.

---

## B. Facts nobody in the repo holds

Each of these REFUSES rather than guesses, and the refusal comes back as a named
gap. Adding one is a human step. Full detail in CLAUDE.md §3b.

| # | What is missing | Where it is refused | Why it cannot be derived |
|---|---|---|---|
| B1 | Professional tax slabs for **18 more states** | `routers/payroll.py` holds only MH, TN, KA, WB; `domain/payroll/professional_tax.py` names the rest | per state, per scheduled employment, revised by notification |
| B2 | **Labour Welfare Fund** amounts for all 16 states that levy it | `domain/payroll/lwf.py` | same |
| B3 | The **seven ITR JSON schemas** per assessment year | `domain/income_tax/schemas/`, wired in `itr_schema.py` | published per form per AY at incometax.gov.in; cannot be generated |
| B4 | **DTAA rates** by country × nature of income | `public.dtaa_treaty_rates` (migration 310) | ninety-odd treaties, MFN clauses needing their own §90(1) notification, several with no FTS article at all |
| B5 | **Bonus Act §12 minimum wage** per state / employment / skill grade | `domain/payroll/bonus.py` | §12 computes on ₹7,000 **or the minimum wage, whichever is HIGHER** |
| B6 | **SBI's Rule 3(7)(i) rate** | `domain/payroll/perquisites.py` | published by the bank on the first day of the previous year |
| B7 | **ESIC reason codes** | `domain/payroll/esic.py` | ESIC's own list |
| B8 | An earlier year's **total income for §89** | `domain/payroll/arrears.py` | comes off the employee's return; the employer never held it |
| B9 | **Prior gratuity / leave exemption used** | `gratuity.py`, `leave_encashment.py` | §10(10) and §10(10AA) are LIFETIME limits across employers |
| B10 | A vendor's **MSMED classification** | `vendors.msme_status` | a fact about the SUPPLIER's Udyam registration; §43B(h) makes it change taxable income |
| B11 | Which accounts hold **unbilled dues** | `chart_of_accounts.unbilled_dues_side` + `schedule_iii_unbilled_reviews` | an unbilled due has no document; no account name decides it |

### B12. Odisha and Punjab professional tax — is the count of 22 right?
`[S]`-graded and **probably one or two too high**. The 7 September research pass
found Odisha reported as having repealed its levy from 01-04-2026 and Punjab's
charge described as a Development Tax. Neither was confirmable (egress is
blocked). The list is deliberately NOT changed: naming a state that no longer
levies produces a false GAP warning, never a wrong deduction. Settle against the
state notifications.

### B13. Earlier years' Finance Acts, for §89
`rates_for()` substitutes `LATEST_VERIFIED_FY` for a missing year, and §89 is a
comparison of years AT THEIR OWN RATES — so a substitute makes the whole relief
a fiction that looks reasonable. The registry holds only 2025-26 and 2026-27, so
**§89 does not work for most real arrears** until earlier years are added.

### B14. FY 2024-25 capital gains cannot be represented
`statutory_rates.FYTaxRates` holds one CG rate set per FY, and the Finance
(No. 2) Act 2024 forked the rates on 23-07-2024 — so 2024-25 straddles. Adding
it needs pre/post buckets, as the ITR form itself splits them. Post-fork years
only, today.

### B15. Is the ESI wage base narrower under the Code?
`_compute_esi` uses gross; the Code on Social Security's definition is narrower,
so ESI may err the other way. **Unconfirmed, deliberately unchanged, and pinned
by a test** so a later change is deliberate. Gratuity likewise.

### B16. The §92E tax-audit report date
Deliberately not modelled: "one month prior" to 30 November is 30 October by
calendar arithmetic while professional sources commonly say 31 October, and that
one-day difference is unconfirmed.

### B17. Which ITR due date applies to an LLP, firm, trust or individual
`compliance_obligation_service.itr_due_date_for_client` decides only three cases
on facts the app holds and REFUSES the rest, returning 31 July (the earlier of
the two) with `decided: false` and a named gap. §44AB turns on the year's
turnover, an LLP's audit on LLP Act §34(4) with Rule 24(8), a trust's on
§12A(1)(b) — none of those figures is held against a client.

### B18. Which tax head a written-off stock ITC reversal belongs to
A §17(5)(h) write-off reverses credit that was taken on some mix of CGST/SGST
and IGST bills, and the write-off does not know which — the inventory module
carries no lot-to-bill link, so nothing in the books says whether the destroyed
goods came in interstate. INV-06 splits **intra-state by default** (odd paise to
CGST), writes the caveat into the register row's `notes`, and takes
`itc_reversal_is_interstate` on the adjustment so the CA can say otherwise. The
total reversed is right either way; only the head split is approximated.
Refusing outright would leave Table 4(B)(1) empty, which was the defect. Lot-
level tracking would settle it properly and is not built.

---

## C. Commercial gates — months, not code

`docs/compliance/07-getting-permission-to-file.md` is the playbook.

| # | Gate | State |
|---|---|---|
| C1 | Third Party Software Utility Developer registration (`SW########`) | **self-service, available now** |
| C2 | NIC e-invoice sandbox | **free now** |
| C3 | ERI Type-2 (income tax filing) | months of commercial work |
| C4 | GSP or an ASP sub-licence (GST filing) | months; gates everything GST |
| C5 | NIC production credentials (e-invoice / e-way bill) | months |
| C6 | An India static-IP egress hop | needed by several of the above |
| C7 | MCA, EPFO, ESIC filing | **no route exists** — there is no API to be granted |
| C8 | Account Aggregator (live bank feeds) | **CLOSED** — no FIU licence exists to apply for and no published purpose code covers bookkeeping. Route 3 (do not consume via AA) chosen 2026-09-06. Reopens only if a purpose code is added |

e-invoice IRN and e-way bill remain the only two statutory outputs software can
complete end to end, because the IRP signs and there is no taxpayer signature.

---

## D. Known-wrong things I have reported and deliberately not fixed

### D1. `app/calendar/page.tsx` builds 14 deadlines in the browser, and two are wrong
AOC-4 shows 29 October where §137 gives 30 October, MGT-7 shows 28 November
where §92 gives 29 November, and all 14 assume a 30 September AGM for every
client. Allow-listed and reported rather than fixed, because the fix is to
delete the browser copy and read `services/compliance_engine.py` — a Phase 7
shape, not a date edit.

### D2. `/api/copilot/intelligence/*` still aggregates firm-wide
ACC-17 drew the line for the seven reporting endpoints (Phase 12b). The copilot
intelligence and executive-dashboard endpoints have the same shape and were left
— an Executive omitting `client_id` there still gets the whole practice.

### D3. FA-02 — the last remaining critical, latent
Needs a backfill as well as a code fix, and the right time is **while production
still holds zero fixed assets**. After the first register is migrated in, it
becomes a data-repair job.

---

## E. Operational — things outside the code that need somebody to look

### E1. Render deploys fail on a health-check timeout — DIAGNOSED 11 Sep 2026
**Raised by the owner, who supplied the Render event log. No longer a mystery.**

**Every failed deploy gives the same reason, verbatim:**

> Timed out after waiting for internal **health check** to return a successful
> response code

**It is not a build failure and not a bad commit.** The owner re-triggered the
SAME commit — `a8c1dac`, the Phase 11e merge — manually at 11:42, and it went
**live at 11:44**. Identical code, identical image: the auto-deploy timed out
and the manual retry succeeded. The event log shows that alternating all the way
back: 11b live, 11c failed, 11d live, 11e failed, 9d failed, 8 failed, 7h live,
6 failed, 5 failed, 4 failed, 1b live, 1a failed. Cloudflare Pages deployed both
frontends successfully on every one of those commits.

**Where the time goes, and it is our code.** `apps/api/main.py` does all of this
at MODULE IMPORT time, before uvicorn can answer anything:

1. `validate_config()`;
2. `run_startup_check()` (`core/schema_guard.py`), which calls `get_supabase()`
   and queries the live schema — **a cross-region round trip, Singapore to
   Mumbai**, on a cold connection;
3. `start_scheduler()` — APScheduler;
4. `log_scheduler_startup_health()` — another database read;
5. the slept-through-jobs catch-up kick.

On Render's FREE tier the instance is cold and CPU-throttled, so the import
graph of a large FastAPI app plus those round trips sometimes lands inside
Render's health-check window and sometimes does not. That is exactly the
coin-flip the event log shows, and exactly why a manual retry on a warm
scheduler succeeds.

**What it costs today.** Nothing is corrupted and nothing is lost — but a failed
deploy means Render keeps serving the PREVIOUS image, while
`apply pending migrations — production` (a GitHub Actions job, not part of the
Render deploy) applies every merged migration regardless. So after a failed
deploy the database is ahead of the code until somebody clicks Manual Deploy.
Safe direction — new columns and functions the old code does not call — and
`schema_guard` is the backstop for the other direction. But it is a manual step
on every merge that nobody is reminded to take.

**The fix, not yet made, because it touches the deploy path of a live service
and is the owner's call:** make `/health` answerable before the expensive boot
work rather than after it. Concretely — move (2), (3), (4) and (5) out of module
import and into a FastAPI `lifespan`/startup hook that runs them on a background
thread, keeping `/health` returning 503 while the schema check is outstanding
(which is what task #244 wanted) rather than keeping the whole process from
answering at all. Raising Render's health-check timeout is the smaller change
and treats the symptom; both are worth doing and the second is free.

**Deliberately not investigated further mid-phase**, at the owner's direction:
"keep this in the open questions so that once you are done with all the phases
we can go through this together."

---

## F. Pages I need opened — egress is refused here

Added 11 September 2026. The owner offered: *"if there are any websites that you
can't go through and need info from them you can tell me I can go through them
and give you images."* The full list with what is needed off each page is
**§6.4 of `docs/compliance/08-government-api-access-the-verified-position.md`**;
this is the register entry so it is not lost.

### F1. The ESIC monthly-contribution Excel template — BLOCKS Track F1

`esic.gov.in` → employer login → File Monthly Contribution → *Sample MC Excel
Template*. Need the file itself, or row 1 headers + row 2 sample + sheet name,
and the stated accepted extension.

**PARTLY CLOSED 11-09-2026.** ESIC's own filing manual was obtained and read,
which settled the format (`.xls`, Excel 97-2003, all columns Text, no formulas)
and — more usefully — settled the DESIGN: the manual says to use the portal's
template and *not* a lookalike, so Track F1 fills the CA's own downloaded
workbook rather than minting one. A real template is now wanted only as a test
fixture. `domain/payroll/esic.py` emitting CSV remains the live defect.

### F2. The ESIC zero-wage reason codes — closes a named refusal

Same screen. The codes, their meanings, and which require a last working day.
This is one of the rows on `CLAUDE.md`'s "statutory data a human has to supply"
table; the list closes it.

### F3. The EPFO ECR upload screen after the Sept-2025 revamp

Format instructions, the Regular / Supplementary / Revised selector, the wage
month dropdown, the Due Deposit Balance Summary. Confirms the `.txt` / 11 field
/ `#~#` format is genuinely unchanged and tells Track F3 what to mirror.

### F4. `test-dev.tdscpc.gov.in` — real developer programme, or internal host?

The only lead anywhere toward a TDS filing API. If real, §4.5 changes. If it is
an internal test host with a public DNS name, I close the lead.

### F5. ERI registration — type, fee, bank guarantee

`incometax.gov.in/iec/foportal/help/eri/registration`. Email 1 of the six drafted
in §10 exists only because I could not read this page.

### F6. GSTN GSP eligibility — is there a turnover threshold?

The uploaded external research claims ₹50 lakh; my searches could not corroborate
it. Most likely single number to decide whether the GSP route is open to a firm
this size.

### F7–F13

Third Party Software Utility Developer registration page; SAG Infotech's Gen
CompLaw MCA pages (confirms mechanism B in §11); RazorpayX statutory-compliance
docs (confirms mechanism C); greytHR's ECR page (the load-bearing quote);
Maharashtra PT notification 28-02-2026 on Rule 11(3); Odisha PT repeal and
Punjab Development Tax (see B12 — same question, this is how to close it);
current MCA XBRL validation tool version.

**Standing note:** if any page says something different from what
`08-government-api-access-the-verified-position.md` says, that is the most
valuable outcome of the exercise. Send it and the document gets corrected with a
line saying what changed.
