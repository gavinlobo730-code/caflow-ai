# 10 — Payroll

> **STATUS, 7 September 2026, annotated 8 October 2026: PARTLY SUPERSEDED — read this box before the rest.**
>
> The owner set this document aside on 7 September 2026 and directed that payroll be
> planned from the scope given that day: the customer is the **CA firm**, every module
> must be strong enough to buy on its own (breadth *and* depth), and there are no live
> users. See `docs/audits/2026-09-07-where-we-are-against-the-one-platform-goal.md`
> §12.3 for what replaces what (that file was deleted on 8 October 2026 and is
> recoverable: `git show 315e6a19:docs/audits/2026-09-07-where-we-are-against-the-one-platform-goal.md`;
> see `docs/audits/README.md`).
>
> **Still current — the model, and it follows from the customer being the firm:** the
> bureau shape (firm screen = client-month queue, client screen = employee-slip
> queue); two-axis grading, *defensible* and *changed*; named gaps instead of silent
> zeros; and the three refusals — never hold client funds or initiate payouts, never
> generate Form 16 Part B (CBDT Notification 09/2019 requires it from TRACES), never
> auto-submit to EPFO, ESIC or TRACES.
>
> **No longer current — the sequencing.** The 1 April 2027 cutover and the deliberate
> non-building of mid-year migration were a calendar device to dodge the
> opening-position problem. `payroll_opening_positions` is to be built properly
> instead: a CA firm wins clients year-round. **It is still not built** (there is no
> such table and no code for it). The deferrals came back into scope under "depth" and
> have gone different ways: bank advice **shipped** (`domain/payroll/bank_advice.py`);
> the FVU-validated 24Q file was reconsidered and is **deliberately not built**
> (`domain/tds/keying_sheet.py` is the answer instead); Form 16 distribution is still
> deferred, and Form 16 Part B is still never generated.
>
> **Also stale in detail, and replaced:** the twelve-row phase list below marked items
> as to-do that have all since shipped. It is now "What shipped, and where", with what
> is still to build listed under it. `statutory_gaps` reaches the screen: the client
> payroll page (`apps/web/app/clients/[id]/payroll/page.tsx`) reads it off the run, and
> releasing over a gap needs a typed reason.
>
> **The two defects this box named on 7 September are FIXED (8 September 2026)**,
> and three more that the fix work surfaced went with them. Recorded here because
> each is a fact about the module this document still describes wrongly elsewhere:
>
> * the ECR declared EPF wages of `basic + DA` while the run remitted on the stored
>   Code-on-Social-Security base — an internally inconsistent file, since EPFO
>   validates EPS at 8.33% of the declared wages;
> * 24Q Annexure II applied the new regime's ₹75,000 standard deduction to every
>   employee, including old-regime rows entitled to ₹50,000;
> * the **pre-commencement** PF base was the s.2(88) aggregate rather than EPF Act
>   s.6's `basic + DA + retaining allowance`, so any historic month with a medical or
>   special allowance over-deducted — and it recomputes on demand, so a reprinted
>   payslip disagreed with the challan actually remitted;
> * `/statutory-position` projected PF on `basic + DA` while `_compute_slip` deducted
>   on the wage base, so one screen said ₹1,200 and the other ₹1,680 and only the
>   second was remitted. One `_pf_wage_base` now serves both;
> * an unbound `logger` (the module uses `_logger`) would have raised `NameError` on
>   the path that reached it.
>
> Deliberately unchanged and now pinned by a test: **ESI still computes on gross.**
> The Code's definition is narrower, so ESI may err the other way — unconfirmed, and
> gross is the direction that cannot under-deduct.
>
> The reasoning below is kept because it is the record of why the model is what it is.

The payroll module, redesigned 2026-09-04. This is the design the code follows;
where they disagree, fix one of them the same day.

## Why it is being redesigned

The owner's words: *"I really don't think that the payroll side is good... for
payroll there is another software generally, and whenever a software does
accounting and payroll both, the payroll is weak. In our software we have to
change that... I know we won't be able to create it in one sidebar Payroll, we
would require more."*

That reading is right, and it is right about the **surface**, not the engine.

- **The engine is ahead of the Indian market.** §192 is a real projection, not
  an annualisation. The three §115BAC objects — the Circular 04/2023 intimation,
  the §115BAC(6) election, the Rule 26C Form 12BB evidence — are kept apart and
  nothing sets one from another. ESI is modelled on Rule 50 contribution periods
  rather than the current month's wage. §89 compares years at their **own** rates
  and refuses a year the registry does not hold. Where a statutory input cannot
  be derived, the code refuses and returns a **named gap**. As at 4 September 2026
  that was fifteen domain modules and thirty-six endpoints, with a full-year
  walk-through behind it (`docs/audits/2026-09-01-payroll-can-it-run-a-year.md`,
  deleted 8 October 2026: `git show 315e6a19:docs/audits/2026-09-01-payroll-can-it-run-a-year.md`).
- **The surface is not a product.** As at 4 September 2026, from the same audit: six
  pages, 5,644 lines, of which `app/payroll/page.tsx` was 1,793. Payroll was one link
  inside Accounting's rail. Attendance was reachable by no route at all. There was no
  screen anywhere that showed a **firm** its payroll across clients — and a firm is
  what we sell to. Those figures are the state the redesign started from, not the
  state now: see "What shipped, and where".

And the surface is not merely thin. It computes statutory files in the browser,
by rules the backend fixed months ago. See **Live defects** below: those ship
before any navigation changes, because wrong numbers do not wait for an argument
about tabs.

## The model: the bureau, not the employer

Every dedicated payroll product — greytHR, Keka, Zoho Payroll, Gusto, Rippling —
assumes **one employer running its own payroll**. We are not that. A CA firm runs
payroll *for* many client companies. The owner's own reference point is
**BrightPay**, which is built for UK payroll bureaux, with BrightPay Connect as
the client-and-employee layer.

That single fact decides the design:

| | dedicated payroll product | PracticeSync |
|---|---|---|
| the tenant | the employer | the **CA firm** |
| the home screen | this month's payroll | **this month across every client** |
| who processes | the employer's HR | the **firm** |
| what the employer does | everything | **supplies inputs, approves, pays** |
| what the employee does | self-service HR | **sees their payslip and how their TDS was arrived at** |

The owner's boundary, in their words: *"our job is not HR, ours is the compliance
part. The client's HR will look into the hiring and stuff. CA only needs the
inputs."* So: **no recruitment, no performance, no engagement, no biometrics, no
LMS.** Those are listed under *Deliberately not built* and are not to be started.

### The two grains

One idea, applied at two grains, and it is the same idea the bank module already
proved (migration 322's `draft_*` columns, "Pass N ready"):

- **At the firm, a row is a CLIENT-MONTH.** Forty rows, one per client, graded.
- **At the client, a row is an EMPLOYEE SLIP.** Thirty rows, graded.

**The firm level is where a month is FOUND and STARTED. The client level is where
a month is COMPLETED.**

### The grade has two dimensions, and one of them is not "did it change"

Grading only by change is how a *stable* error stays green forever. So a row
carries both:

- **Defensible** — a standing check, re-evaluated every month independently of
  the last: is every input this slip rests on present and in force? PT state
  modelled, UAN, ESIC IP, PAN, a salary structure in force, inputs closed, no
  leaver still active past their exit date, loans reconciling.
- **Changed** — what moved since the last approved month, attributed to a cause
  (revision, LOP, new joiner, declaration verified).

| grade | means |
|---|---|
| `ready` | defensible **and** unchanged, or changed with every change explained |
| `check` | defensible, but something moved that nobody has accounted for |
| `blocked` | not defensible — a named gap, with the statutory consequence stated |

`blocked` is never passed in bulk. Neither is anything that posts a journal,
publishes to a person, or moves money.

### Month one is a first-class problem

A client mid-year has YTD salary, YTD TDS, and exemptions already used elsewhere.
Without those, §192 withholds from a fiction and §10(10)/§10(10AA) lifetime caps
are wrong. So `payroll_opening_positions` is the payroll analogue of the opening
balances this platform already treats as first-class, and a client without one
cannot reach `ready` in its first month.

## Navigation

Payroll becomes the **13th top-level workspace**, not a link inside Accounting.
Six sections.

> **A hard constraint that shaped this.** `apps/web/public/_redirects` holds
> **98 dynamic rules against Cloudflare Pages' cap of 100.** Every route below is
> therefore **static**, and per-employee and per-run detail are **drawers on a
> query parameter**, not routes. A per-client route tree is unbuildable at any
> price. This is also a standing risk worth its own task, independent of payroll.

| entry | scope | what it is | state, 8 October 2026 |
|---|---|---|---|
| **Month** (`/payroll`) | firm | The client-month queue. The bureau's screen on the 3rd and the 10th. | Built as the firm payroll screen with a client picker. The graded queue, one row per client with a ready, check or blocked grade, is **not built**. |
| **People** (`/payroll/people`) | firm | Roster across every client, one employee form, one bulk import, the exception index. | Built. |
| **Declarations** (`/payroll/declarations`) | firm | Kept exactly as it is — see below. | Built, as it was. |
| **Statutory** (`/payroll/statutory`) | firm | Deposits · Filings · Year-end. | Built as the statutory deductions screen; it computes nothing in the browser. |
| **Reports** (`/payroll/reports`) | firm | Rebuilt server-side. | Built, server-side. |
| **Attendance** (`/payroll/attendance`) | firm | Not in the original table: the audit's complaint was that attendance was reachable by no route. | Built; the server decides loss of pay. |
| **Setup** (`/payroll/setup`) | firm | Calendars, statutory identity, pay components, **state coverage**. | **Not built, by decision.** `/settings/statutory-values` is the state-coverage screen and `PayrollPanel` links to it; a second screen for one fact is the mistake the codebase records at `/accounting/retainer`. |
| **Client → Payroll** (`/clients/[id]/payroll`) | client | Inputs · Register · Release · Outputs. The existing route, rebuilt as a shell. | Built. The four tabs exist, with File, Bonus and Setup beside them. |
| **Client portal → Payroll** | client | Register to review, statutory dues, **approve or return**, published payslips. | **Not built.** |
| **Employee portal → Pay** | employee | Payslip, **how your TDS was arrived at**, Form 12BB, Form 16. | Partly: payslips (their own PDF door) and the TDS projection. |

**Declarations is deliberately unchanged.** It is already the standard every
other payroll screen is held to: it computes nothing, renders server-issued
notices verbatim, and states the month-10 proof cut-off once and honestly. It is
promoted from a button to a named entry and otherwise left alone.

**State coverage is a screen, not a footnote.** It publishes which states' PT and
LWF we model, as of which notification, with the affected client and employee
counts beside each refusal. It turns our largest liability into the one claim no
competitor makes: we say what we do not know.

### The client month, in four verbs

The four tabs exist on `/clients/[id]/payroll`. The table below is the design, and
parts of it were not built as written: **no code carries "approver ≠ locker", the
per-slip ready, check or blocked grade, or "Approve N ready"**. What stands in for
them is `statutory_gaps` (the *defensible* half, as named gaps) and the month-on-month
variance in `domain/payroll/month_on_month.py`, which names every component that moved
(the *changed* half).

| tab | the CA's job | verb |
|---|---|---|
| **Inputs** | LOP, joiners, leavers, revisions effective this month, unverified declarations, the gaps this roster will hit. An *absent* row is an explicit "not entered", never a zero. | Close inputs |
| **Register** | The graded per-employee list, variance against the last approved month, slip drawer. | Approve N ready |
| **Release** | Three gated steps, never batched: **Lock** (posts the accrual, approver ≠ locker) → **Publish payslips** → **Record payment**. Reverse is present, never primary, and demands a reason. | — |
| **Outputs** | This client-month's shelf — payslips, register, ECR, ESIC, PT basis, bank advice, 24Q feed — each *exists* or *blocked, because…*, every one **server-built**. | Download, then Mark handed over |

## Live defects as at 2026-09-04 — ALL FIVE NOW ADDRESSED

Each was verified by reading the code when this design was written, and each has
since been fixed. **The descriptions are kept as the record of what was wrong**,
because four of the five are the kind of mistake that gets made again; each now
opens with what closed it.

| # | Was | Now |
|---|---|---|
| 1 | ECR/ESI built in the browser, by wrong rules | **Fixed** — browser generators deleted, server-built |
| 2 | Payroll accrual dated to the button press, in UTC | **Fixed** — dated to the payroll month |
| 3 | Salary amounts parsed with `parseFloat` | **Fixed** — no `parseFloat` in the payroll page |
| 4 | Employees could read draft payslips | **Fixed** — migration 323 |
| 5 | No attendance row paid everybody a full month | **Partly** — the number is unchanged; the silence is gone |

**Item 5 is the one to read.** It is the only one where the computed figure did
not change: what changed is that the run now says nobody entered anything. That
distinction is the whole fix, and it is the same shape as `statutory_gaps`.

**References below name a SYMBOL, not a line.** They were written as
`payroll.py:1472` and similar, and every one had drifted within days — `:1472` is
now a retention refusal sentence added by a later task. A line number into a
living file is a pointer that rots silently, and `file::symbol` is the convention
CLAUDE.md already uses.

### 1. The ECR and ESI files the CA downloads were computed in the browser, by wrong rules

> **FIXED 2026-09-04.** Both are server-built — `api.payroll.runEcr` /
> `runEsic`, backed by `domain/payroll/ecr.py` and `domain/payroll/esic.py`. The
> browser generators are deleted, and `apps/web/app/payroll/page.tsx` carries a
> comment above the TDS 24Q block recording that they are not coming back.

`apps/web/app/payroll/page.tsx` built the EPFO ECR client-side. The server's
correct `GET /runs/{run_id}/ecr` and `/esic` **had no caller in the web app.**
The browser version:

- hardcoded **`NCP_DAYS` to 0** — every employee's loss-of-pay days remitted
  to EPFO as zero;
- put **PAN in `MEMBER_ID`**, or fabricated `EMP0001` when there was no PAN. The
  field is the **UAN**. A fabricated member id in a statutory remittance file;
- computed **EPF wages on basic alone**. EPF Act §6 is basic **+ DA** — the exact
  bug the September audit had already fixed in the backend;
- tested ESI eligibility as `gross_paise <= 2100000` for the current month,
  ignoring **Rule 50 contribution periods** — also already fixed in the backend;
- computed ESI contributions in **floating point**.

This was CLAUDE.md's "zero business logic in the frontend" rule being violated in
the one place where violating it produces a wrong statutory filing.

### 2. The payroll accrual was dated to the button press, in UTC

> **FIXED.** `services/phase2_journal_service.py::journal_for_payroll` now posts
> with `entry_date=month_end_date(run["month"])`. The comment there records that
> the same change fixed a second bug the original write-up missed: `_create_journal`
> dedupes on `(client, reference_no, entry_date)`, so with `today` in the key a
> **re-finalisation on a later day produced a SECOND accrual for the same month.**

The journal was posted with `entry_date=str(datetime.now(timezone.utc).date())`.
Finalising August's payroll on 3 September dated the accrual **3 September** —
August's P&L carried no salary cost and September carried two months, in books
this firm produces. And between 00:00 and 05:30 IST the UTC date is **yesterday**,
so a March run finalised just after IST midnight could land in the wrong
**financial year**.

### 3. Employee salary amounts were parsed with `parseFloat`

> **FIXED.** There is no `parseFloat` anywhere in `apps/web/app/payroll/page.tsx`.

The employee form did `rsToP(parseFloat(form.basic_rs) || 0)`.
`parseFloat("1,25,000")` is **1**. CLAUDE.md records that all 61 money call sites
were converted to `lib/money/rupeeInput.ts` and that there is no longer a second
way. This form was a second way. The CSV importer eleven hundred lines below it
carried a comment explaining this exact trap — and was fixed while the form
beside it was not.

### 4. Employees could read draft payslips

> **FIXED by migration 323**, which adds the missing predicate:
> `AND run_id IN (SELECT public.my_payroll_run_ids())`.

Migration 262 created:

```sql
CREATE POLICY "employee_reads_own_payslips" ON public.payroll_slips
  FOR SELECT TO authenticated
  USING (employee_id IN (SELECT public.my_employee_ids()));
```

No predicate on the run's status, and `payroll_runs.status` is
`draft | review | finalized`. The employee portal query had no status filter
either. A CA creating a draft run to check the numbers exposed every linked
employee's unapproved payslip.

It was **latent, not live** — production held zero payroll employees and none
linked to a login — and it would have gone live with the first portal invite. The
fix belongs in the RLS policy, as the frontend reads that table directly, so a
page filter would not have been a control.

### 5. No attendance row means everybody is paid a full month

> **PARTLY FIXED, and the remaining half is deliberate.** The computation is
> unchanged: `routers/payroll.py::_compute_slip` still defaults `working_days`
> and `days_present` to **26** and `lop_days` to **0**. What changed is that a
> missing row is no longer indistinguishable from a confirmed one —
> `attendance` is `None` when nothing was entered, the slip carries
> `attendance_entered`, and `routers/payroll.py::_attendance_gap` returns a named
> gap per employee in the run's response.
>
> It **warns rather than blocks**, matching `_statutory_gaps` exactly, and that is
> a decision rather than an omission: a run is a DRAFT — nothing posted, nothing
> paid, no journal until Finalize — so refusing to compute it would stop a CA
> seeing the very figures that tell them what is missing. The original write-up
> below asked for a block; the shipped answer is a named gap, for the same reason
> the unmodelled professional-tax states report themselves instead of deducting
> nothing in silence.

`_compute_slip` defaults `working_days` and `days_present` to **26** and
`lop_days` to **0**. The `attendance` table's own columns default to 26 as well
(migrations 027, 054, 093).

So a client who has sent **nothing** — no LOP, no absence, no inputs at all —
produces a run in which every employee is paid for a full month. "Nobody told us
anything" and "26 days present, confirmed" are the same value, and the CA could
not tell them apart.

This was the most dangerous defect in the module, because it failed **silently
and in the employee's favour**, and it compounded with defect 1: a full-month
default means no LOP, which made the ECR's hardcoded `NCP_DAYS = 0` look
consistent.

## Go to market

> **Hypothesis, not finding.** This section was written on 4 September 2026, before any
> customer was asked, and nothing in this repository tests it. The beachhead and the
> demo below are what the author believed would work. Two parts of it were withdrawn on
> 7 September and are marked.

**The pricing posture is not restated here.** This section recorded a 4 September
decision to bundle payroll into one subscription, with no payroll SKU and no
per-employee meter. The 7 September scope ("every module strong enough to buy on its
own") and later code comments do not agree on whether payroll is bundled, bought on
its own, or priced per employee per month. That is the owner's to confirm. Nothing in
the model or in what is built below depends on the answer.

**The wedge, and its limit.** *Your client's payroll posts into the ledger you
already close for them — the salary journal, the PF and ESI payables and the §192
TDS in that trial balance the moment you finalise, in the same paise, with no
export and no per-employee bill.* No competitor can say it: greytHR, Keka, Zoho
Payroll and factoHR keep no ledger for the client's books.

But it is only **literally true where we already hold the ledger.** For a firm
whose client books are in Tally, the salary journal posts into a trial balance
nobody is using, and the sentence becomes a promise instead of a demonstration.

**So the beachhead is firms already on PracticeSync for accounting** — 15–60
clients, of whom 3–12 have employees, payroll run today in Excel or one
single-employer login per client, 10–150 employees each, monthly salaried. Zero
acquisition cost, no new contract. The figures in that sentence are the author's
estimate and were not measured.

**WITHDRAWN 7 September 2026: the 1 April 2027 cutover, and "not building mid-year
migration is the enforcement mechanism".** The argument was that a mid-year import has
no prior withholding on file, so §192 withholds from a fiction, and that at 1 April
every opening position (year-to-date salary, year-to-date TDS, the lifetime
§10(10)/§10(10AA) amounts used) is zero, which is the only opening position that
cannot be got wrong. The first half is still a fact: `_tds_already_deducted_this_fy`
reads only slips this platform produced, so a client converted mid-year withholds
without what the previous system withheld. The conclusion was withdrawn: a CA firm
wins clients year-round, so the answer is to build the opening position, not to
forbid mid-year clients. See "Still to build" below.

**What makes the product survivable at any price is refusing to fund a compliance
research desk.** Twenty states' PT slabs, sixteen LWF regimes and minimum wages
revised twice yearly cannot be maintained against zero marginal revenue. Instead, a
firm-scoped table where the **CA records what they read** — a state's PT slab, an LWF
amount, the minimum wage for Bonus Act §12, SBI's Rule 3(7)(i) rate, an ESIC reason
code — each with its notification reference, date and author, reusable across every
client of that firm and printed on the register beside the computed figures. **That
shipped** (migration 327, `domain/payroll/firm_rates.py`, the
`/settings/statutory-values` screen).

One mechanism converts six *refused-by-design* blockers into two minutes of data
entry, and makes our marginal cost of the next state **zero**. It is also why the
beachhead does not have to be a single state.

**The cost brake, in place of a price:** payroll is enabled per client by a
Partner, not switched on firm-wide. That keeps one subscription intact, stops
payroll appearing for clients that have none, and gives us the employee-month
distribution — a firm at 5,000 employee-months is a platform-tier conversation,
not a payroll invoice. *The rationale was written for a bundled subscription, which
is the open question above. The switch itself is built and does not depend on it:
migration 332, and `payroll:enable` is Partner-only in `core/permissions.py`.*

**The demo is the prospect's own last month**, imported and re-run. It rarely
ties, because a hand-built sheet under §115BAC usually still deducts professional
tax on Annexure II, or annualises the withholding instead of projecting it. Then
one employee is posted to a state we do not model, and the system **names the
gap** rather than deducting zero in silence. Every CA has been burned by a
spreadsheet formula that quietly returned zero. *This is the sales story and is
untested.*

## What shipped, and where

This replaces the twelve-row "v1 — build to end-December 2026" table, which sized
each item in weeks and days. Every one of its twelve items has shipped. Phase 1 was
never a redesign: it was the wrong numbers, and every item was verified above.

| # | what | where it is |
|---|---|---|
| 1 | Employee master extended to everything the statutory outputs need, and one server-side bulk import: whole-file validation, whole-file refusal, idempotent on employee code | `domain/payroll/employee_import.py`; UAN and IFSC format checks in `domain/payroll/identity.py` |
| 2 | Per-client establishment identity: EPF establishment code, ESIC employer code, LIN, the client's own TAN, PT registration | migration 325 (`client_statutory_identity`, `client_pt_registrations`) |
| 3 | Attendance and LOP as a server-side contract with an explicit **not entered** | migrations 324 and 326; `domain/payroll/attendance.py`; `routers/payroll.py::_attendance_gap` |
| 4 | Firm-supplied statutory values | migration 327; `domain/payroll/firm_rates.py`; the `/settings/statutory-values` screen |
| 5 | The defensible release: `statutory_gaps` rendered, and releasing over one needs a typed reason | `routers/payroll.py::_reason_for_releasing_with` and `finalize_run`; finalising is Partner-only (`payroll:finalize`) |
| 6 | Run-lifecycle correctness: accrual dated to the payroll month in IST, the employer's PF, EDLI, admin charge and ESI in their own expense head, an unreleased run recomputed or deleted, a reversal that puts a loan back | `services/phase2_journal_service.py::journal_for_payroll`; migrations 375 and 367; `POST /api/payroll/runs/{run_id}/recompute` and `DELETE` |
| 7 | One-time and variable earnings: incentive, bonus, arrears, ex-gratia | `domain/payroll/one_time_earnings.py`; migration 331 |
| 8 | Salary structures wired, so a named structure applies to an employee and a revision records the structure that produced it | `domain/payroll/salary_structure.py`; migration 330 |
| 9 | Month-end pack: the salary register and every payslip in one zip, built by the server | `GET /api/payroll/runs/{run_id}/payslips.zip` |
| 10 | One payroll surface: the 13th top-level workspace, six screens (`/payroll`, `/payroll/people`, `/payroll/declarations`, `/payroll/statutory`, `/payroll/reports`, `/payroll/attendance`) | `components/panels/PayrollPanel.tsx`; `lib/workspace/workspaceConfig.ts` |
| 11 | Payroll dates in the deadline view, and a payroll column on the client list | `services/compliance_engine.py::payroll_deposit_due_dates`; `payroll_enabled` in `apps/web/app/clients/page.tsx` |
| 12 | Per-client payroll enablement, the cost brake | migration 332; `payroll:enable` in `core/permissions.py` |

Shipped beyond the twelve: bank advice, the month-on-month variance and department
cost reports (`domain/payroll/bank_advice.py`, `month_on_month.py`,
`department_cost.py`, served under `/api/payroll/reports/`), the bonus register
(`domain/payroll/bonus_register.py`) and an employee-portal door for a payslip PDF and
the §192 projection (`routers/portal_employee.py`).

Defects 1–4 above shipped inside items 5, 6 and 1; defect 5 is item 3.

### Still to build

- **Opening positions for a client mid-year** (`payroll_opening_positions`: no table,
  no code), with the **previous employer's salary and TDS under §192(2)**. Without
  them §192 withholds from a position that omits what came before.
- **The client portal's payroll surface**: register to review, statutory dues, approve
  or return.
- **The graded client-month queue** (ready, check, blocked per client and per slip)
  and "Approve N ready".

Not on this list because it was decided against: the FVU-validated 24Q file
(`domain/tds/keying_sheet.py` instead) and a Form 16 Part B generator.

**Deferred with reasons, not forgotten.** A formula engine for pay heads (the
classic payroll trap — configuration grows to fill the schedule and nothing
statutory ships). The cross-client work queue and batch operations (designing a
forty-client board with zero payroll clients means guessing every column; the
first cohort tells us the columns). Leave management. Form 16 distribution, first
owed June 2028. Employee-portal depth and bulk invites, because every one of them
scales support by employee count against zero marginal revenue, which is exactly
what competitors are pricing for. **No longer deferred:** bank advice (shipped; the
payment is still the client's act, and the file moves no money). **Reconsidered and
decided against:** the FVU-validated 24Q file, because a byte-exact writer against a
format that is still moving is a guess that gets a whole statement rejected; the
keying sheet takes its place (`domain/tds/keying_sheet.py`). **Withdrawn:** mid-year
migration as something to refuse, see "Go to market".

## Deliberately not built

Not oversights. Recruitment and applicant tracking; performance, appraisals and
goals; engagement, surveys and rewards; biometric devices, geo-fencing and shift
rostering; learning management; asset management and background verification;
professional-services automation for the *client's* business.

Three that are subtler and matter more:

- **Holding client funds or initiating salary payouts.** The CA is not the
  account holder and must never move a client's salary money. We produce the
  bank advice; the client pays. Same rule as `never screen-scrape net banking`.
- **A Form 16 Part B generator.** CBDT Notification 09/2019 requires Part B from
  TRACES. Competitors advertising "digitally signed Form 16 in one click" are
  producing something a CA cannot rely on.
- **Auto-submission to EPFO, ESIC or TRACES.** The house rule gets *stronger*
  with scale: a double-submitted return is a second filing against a live portal.

## What this design rests on, and where it is weak

The market research behind it is **second-hand**. This environment's proxy blocks
all external hosts and the session's web-search budget was exhausted partway
through, so no agent opened a vendor page; product findings came from search-index
summaries of vendor documentation, and two questions — how bureaux collect period
inputs, and the operating month end to end — returned nothing at all. Every claim
about a competitor should be treated as *reported*, not verified.

The code-grounded half was sound when written: as at 4 September 2026, 125
capabilities with file-and-line evidence, 44 structural problems, and the four
defects above independently re-verified, all from the audit
`docs/audits/2026-09-01-payroll-can-it-run-a-year.md` (deleted 8 October 2026;
`git show 315e6a19:docs/audits/2026-09-01-payroll-can-it-run-a-year.md`). Those counts
are a snapshot and have not been redone.

**The strongest case against this design:** it is a large surface for a module
with, today, zero employees in production. The first two items of the list above were
justified whatever happened next; the rest were a bet that payroll becomes a service
the firm sells. All twelve have been built, so if that bet is wrong, we have built a
bureau console for one client.
The phase order is chosen so that bet is made late and cheaply.
