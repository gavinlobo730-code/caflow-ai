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

### A4. Which spelling goes on the printed financial statements?

**NEW, 11 September 2026, and it is the only genuinely open decision here.**

Three places in the product name the lines of a Schedule III financial
statement, and they disagree on spelling — the screen a CA picks from says
"Employee Benefits Expense" and "Short-term Borrowings", the code that prints
the statement says "Employee Benefit Expense" and "Short Term Borrowings".
Because the two do not match exactly, **nine of the fifty mappings CAs have
already made in production are silently discarded** and the statement falls
back to guessing from the account's subtype.

Making them agree is straightforward. **Which spelling is canonical is not**,
because these words are PRINTED on a statutory document and the authority is
Schedule III itself — which could not be read: `icai.org` and every `.gov.in`
are refused at the egress proxy.

**Recommendation: adopt the screen's spellings.** They are what CAs have been
choosing, they are what production holds, and they match the Act as far as
memory goes. That is convergence, not a reading of the statute, which is why it
is a question rather than a decision already taken.

**Nothing is blocked either way.** An alias table honours a mapping whichever
way it was spelled, so the nine discarded choices are recovered regardless; only
the printed wording turns on the answer.

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

## C. Commercial gates — PARKED, not pending

**Owner decision, 11 September 2026: no registrations are being pursued.**
Nothing in this section is a question, a task, or something anybody is waiting
on. It is here so that a later decision to resume starts from research already
done rather than from scratch.

What that covers: the Third Party Software Utility Developer registration, the
NIC e-invoice sandbox and production credentials, ERI for income-tax filing,
GSP or an ASP sub-licence for GST filing, and an India static-IP egress hop.

Two things are worth remembering if it ever reopens, and both are in
`docs/compliance/08-government-api-access-the-verified-position.md`:

- **e-invoice and e-way bill are the only two statutory outputs software can
  complete end to end**, and their sandbox is free and self-service. They are
  the cheapest place to restart.
- **MCA, EPFO, ESIC and professional tax have no route at all** — no API, no
  programme, nothing to apply for, for us or for any competitor. That one is
  not a decision; it is a fact about the portals.

**Account Aggregator (live bank feeds) stays CLOSED** on its own merits, decided
2026-09-06 — no FIU licence exists for a firm like this to apply for, and no
published purpose code covers bookkeeping. It reopens only if a purpose code is
added, which nobody is waiting on.

---

## D. Known-wrong things I have reported and deliberately not fixed

### D1. The calendar's MCA deadlines — FIXED 11 September 2026

**The invented AGM was the serious half, not the off-by-one.** AOC-4 showed
29 October where §137 gives 30 and MGT-7 showed 28 November where §92 gives 29,
because the browser counted the AGM day itself. But it also assumed the AGM was
**30 September for every client**, which is wrong for every company whose
meeting was not — and a CA reading a firm-wide calendar could not tell a
computed row from an assumed one.

`mca_companies.last_agm_date` has held the real date since migration 038, whose
own comment reads *"AGM date drives AOC-4/MGT-7 deadline"*. The browser copy
never read it.

`GET /api/mca-workspace/calendar/firm` now computes ADT-1, AOC-4 and MGT-7 from
each company's own AGM through `compliance_engine.mca_due_date`, scoped to the
caller's clients. **A company with no AGM date recorded is NAMED, not
defaulted** — returned in `without_agm_date` and shown on the calendar as a
gap, because 30 September is a plausible guess and a plausible guess on a
statutory deadline is how a filing is missed.

**Still in the browser, and still owed:** the other eleven deadlines — GST, TDS,
ITR and DIR-3 KYC. Those are rule-based and fall out of the calendar date alone,
so they are correct today; they nevertheless duplicate
`services/compliance_engine.py`, which is the Phase 7 shape this entry
originally described. The three that needed a client FACT are the ones that
could not stay.

### D2. `/api/copilot/intelligence/*` aggregates firm-wide — FIXED 11 Sep 2026

**And it was worse than this entry said.** `firm:read` is `_AT_LEAST_MANAGER`,
so `/executive-dashboard` reached a Manager too, not only an Executive. Four
endpoints passed a bare `firm_id`: `/intelligence/compliance`,
`/intelligence/workflows`, `/intelligence/relationships` and
`/executive-dashboard`. `/intelligence/client/{id}` was guarded from the start —
the line had been drawn and stopped one endpoint short.

The relationship endpoint was the worst of the four: it feeds client PANs and
email domains into an AI prompt to find related parties, so it disclosed
identifying data about clients the caller is not assigned to.

**A second leak the entry never mentioned.** These summaries cache on
`(firm_id, summary_type, entity_id)` with `entity_id=None` on every call — so
scoping the queries alone would still have served a Partner's firm-wide answer
to the next Executive who asked, from cache. The scope is now part of the key.

Each of the three exemption reasons in `test_router_client_scope.py` was
answered rather than overridden, and **all four exemptions are removed** — the
guard now enforces this permanently:

- *"narrowing without changing the cache key would still serve a firm-wide
  response"* → the scope IS the key.
- *"workflow_failures/approvals carry no client_id, and the repository does not
  expose the join"* → **out of date**: `client_ids_for_instances` exists and the
  workflow router already uses it. One query, not one per row.
- *"narrowing the input set would change what the analysis IS"* → true, and the
  one place scoping changes meaning. PAN cross-matching only says something
  across the whole book, so a narrowed "no related parties" reads as a clean
  bill of health for the firm. The privacy duty still wins, so the answer is
  narrowed **and says so**: `analysed_client_count` and `scoped` are on the
  response.
- Template analytics aggregate per template with no client dimension and cannot
  be narrowed, only withheld — a scoped caller now gets none rather than counts
  that silently span clients they may not see.

### D3. FA-02 — CLOSED 11 September 2026, and two of its premises were stale

Re-checked against the code rather than the record, and most of it had already
been overtaken:

- **"No edit path (FA-10)"** — wrong now. `PATCH /{asset_id}` exists and
  `wdv_rate_percent` is in `_TIER_C_FIELDS`, so a rate is correctable as a
  prospective revision of an estimate (Schedule II Part C Note 7, AS 10).
- **"It goes wrong the first time a register is migrated in"** — there is no
  bulk import. `POST ""` is the only path that creates an asset, it uses the
  Schedule II derived default, the Tally migration service writes no fixed
  assets, and no frontend writes the table directly.
- Production holds **zero** fixed assets, so there was nothing to back-fill.

**What was genuinely left, and is now built:** nothing told anybody that an
asset's stored basis disagrees with Schedule II. A row written before the rate
was derived from Part C carries an Income-tax Act block rate — Furniture at 10%
where Part C gives 25.89% — and under-depreciates for the asset's whole life,
silently.

**A backfill migration would have been the wrong fix**, and the statute is why:
Schedule II **Part A** expressly permits a different useful life or residual
value provided it is **disclosed and justified**. Nothing in the schema
distinguishes a stale default from a deliberate judgement, so a migration would
have overwritten the judgement, changed the depreciation charge and moved the
profit.

So it is REPORTED, as a fourth finding on `/register-integrity` — the endpoint
that already reports and repairs nothing. The CA corrects it or discloses it.
Conforming means matching **any** class the category offers, not the default, or
a CA who picked Schedule II's second life would be flagged for following the
table.

---

## E. Operational — things outside the code that need somebody to look

### E1. Render deploys fail on a health-check timeout — FIXED 11 September 2026

**Owner approved the fix; done.** The schema-drift check, the scheduler start,
its health log and the catch-up sweep all ran at module import — before uvicorn
binds a socket — and three of the four make a Singapore-to-Mumbai round trip.
Render's deploy health check timed out on every one of them, on code that was
fine, which a manual re-deploy of the same commit proved each time.

They now run on a daemon thread started from a FastAPI `lifespan`, and `/health`
answers 200 immediately with `schema: "checking"`.

**The trade-off, recorded because it is a real one.** Task #244 made a deploy
that depends on an unapplied migration fail its own health check. That is now
DELAYED rather than removed: `/health` flips to 503 the moment drift is found,
so the exposure goes from *"no deploy ever succeeds"* to *"a deploy with real
drift serves traffic for about one Mumbai round trip"*. The old behaviour was
failing every good deploy to guard against a rare bad one.

`tests/test_health_answers_before_the_slow_boot.py` pins all of it, including
the trap: **answering 503 while merely unchecked reproduces the original bug
exactly**, because Render cannot tell "still checking" from "broken".

**⚠️ One thing was NOT done, because it cannot be.** Raising Render's
health-check timeout was the other half of the plan. Render's blueprint exposes
only `healthCheckPath` — there is no timeout field in `render.yaml` — so there
is nothing to raise from here. The code fix stands alone.

**Still true and unchanged:** after any failed deploy the database is ahead of
the code until somebody clicks Manual Deploy, because migrations apply through a
separate GitHub Actions job. Fewer failed deploys means that happens less, not
never.

---

## F. Pages that would need a human with a browser — MOSTLY CLOSED

### What closed on 11 September 2026

**ESIC's own filing manual was obtained and read in full.** It settled the file
format, confirmed the six columns we already emit, and — more usefully — settled
the DESIGN: ESIC says to fill the portal's own template and not a lookalike, so
Track F1 fills the CA's downloaded workbook rather than minting one. It also
found a live defect: ESI contributions round UP to the next whole rupee and we
were computing to the paise. Fixed.

### What is parked with the registrations

The ERI registration page, GSTN's GSP eligibility criteria, `test-dev.tdscpc.gov.in`
and the Third Party Software Utility Developer page all existed to price
registrations nobody is pursuing. **Parked.** They are listed with what is needed
off each in §6.4 of the filing-access paper, so resuming costs an afternoon.

### The one that is still a real product gap

**The ESIC numeric reason codes.** They explain why an insured person had zero
wages in a month, and ESIC surfaces the list only inside the employer portal at
filing time. `domain/payroll/esic.py` deliberately refuses to invent one and
withholds the whole file until a CA supplies it — which the manual now shows is
more right than when it was written, because **a zero-wage row removes that
person from the establishment**, so a guessed code would de-register somebody
rather than merely misreport them.

**Needs an ESIC employer login, which this firm does not have.** Not blocking:
the refusal is safe and the CA can type the code. It closes the day somebody is
next inside a client's ESIC portal.

### Two statutory facts that would tidy things up, neither urgent

Odisha's reported professional-tax repeal and Punjab's Development Tax (see
B12 — naming a state that no longer levies produces a false gap warning, never a
wrong deduction), and the current MCA XBRL validation tool version.
