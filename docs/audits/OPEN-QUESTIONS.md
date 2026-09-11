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

### E1. Render keeps emailing "deploy failed for practicesync-api"
**Raised by the owner 11 September 2026, on the Phase 11e merge (#482). The
emails have been arriving for a while and been ignored.**

**What it means, and what it does not.** Render auto-deploys `practicesync-api`
on every push to `main`. A failed deploy means the **container did not come up
on the new commit** — Render keeps serving the PREVIOUS image, so the API stays
up but may be running older code than `main`. It is not a database failure and
not a test failure: CI was green on every one of these commits.

**Why it is not obviously harmless.** Three things are worth checking together:

* **The migrations applied anyway.** `apply pending migrations — production` is
  a GitHub Actions job, not part of the Render deploy, so every migration
  merged to `main` has been applied to the live database whether or not the API
  redeployed. That leaves production's SCHEMA ahead of production's CODE. That
  is the safer direction — new columns old code ignores — and
  `core/schema_guard.py` is the boot-time backstop for the other direction. But
  it is exactly the drift `docs/schema-drift.md` exists to talk about, and it
  has been accumulating silently for an unknown number of commits.
* **The service IS answering.** `.github/workflows/wake-before-scheduler.yml`
  pings `/health` across the scheduler window and those runs are succeeding, so
  something is live. That is evidence the API is up — not evidence of WHICH
  COMMIT it is running.
* **The daily job sweep runs in that process.** If the live image is old, the
  scheduler running the compliance sweep is old too.

**One narrowing fact, from the PR events of the same morning.** Cloudflare Pages
deployed BOTH frontend projects — `practicesync` and `practicesync-ai` —
successfully on the same commits Render failed on (#482 head `865cc80`, #483
head `9b0a1d8`, deploy successful on each). So this is not a repo-wide problem
and not a bad commit: it is specific to the backend's Docker build or its boot
on Render. That rules out the whole class of "the tree is broken" causes and
points at the image or the container's start-up.

**What cannot be answered from inside this session.** Render's build log is the
only thing that says WHY the deploy failed, and this environment's egress is
refused at the proxy, so it cannot be fetched. The first step is a human
opening the Render dashboard for `practicesync-api` → Events → the failed
deploy → the build log. Everything after that depends on what it says.

**What to check once the log is in hand** — the four failures this shape usually
is, cheapest first: a Docker build step that needs a file the image does not
copy; a `requirements.txt` install failing on a pinned version; the free
instance running out of memory during the build; or the health check timing out
on boot because `schema_guard` is refusing to start against a schema it does not
recognise — which would be the one that ties back to the bullet above.

**Deliberately not investigated further mid-phase**, at the owner's direction:
"keep this in the open questions so that once you are done with all the phases
we can go through this together."
