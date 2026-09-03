# 10 — Payroll

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
  be derived, the code refuses and returns a **named gap**. Fifteen domain
  modules, thirty-six endpoints, and a full-year walk-through behind it
  (`docs/audits/2026-09-01-payroll-can-it-run-a-year.md`).
- **The surface is not a product.** Six pages, 5,644 lines, of which
  `app/payroll/page.tsx` is 1,793. Payroll is one link inside Accounting's rail.
  Attendance is reachable by no route at all. There is no screen anywhere that
  shows a **firm** its payroll across clients — and a firm is what we sell to.

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

| entry | scope | what it is |
|---|---|---|
| **Month** (`/payroll`) | firm | The client-month queue. The bureau's screen on the 3rd and the 10th. |
| **People** (`/payroll/people`) | firm | Roster across every client, one employee form, one bulk import, the exception index. |
| **Declarations** (`/payroll/declarations`) | firm | Kept exactly as it is — see below. |
| **Statutory** (`/payroll/statutory`) | firm | Deposits · Filings · Year-end. |
| **Reports** (`/payroll/reports`) | firm | Rebuilt server-side. |
| **Setup** (`/payroll/setup`) | firm | Calendars, statutory identity, pay components, **state coverage**. |
| **Client → Payroll** (`/clients/[id]/payroll`) | client | Inputs · Register · Release · Outputs. The existing route, rebuilt as a shell. |
| **Client portal → Payroll** | client | Register to review, statutory dues, **approve or return**, published payslips. |
| **Employee portal → Pay** | employee | Payslip, **how your TDS was arrived at**, Form 12BB, Form 16. |

**Declarations is deliberately unchanged.** It is already the standard every
other payroll screen is held to: it computes nothing, renders server-issued
notices verbatim, and states the month-10 proof cut-off once and honestly. It is
promoted from a button to a named entry and otherwise left alone.

**State coverage is a screen, not a footnote.** It publishes which states' PT and
LWF we model, as of which notification, with the affected client and employee
counts beside each refusal. It turns our largest liability into the one claim no
competitor makes: we say what we do not know.

### The client month, in four verbs

| tab | the CA's job | verb |
|---|---|---|
| **Inputs** | LOP, joiners, leavers, revisions effective this month, unverified declarations, the gaps this roster will hit. An *absent* row is an explicit "not entered", never a zero. | Close inputs |
| **Register** | The graded per-employee list, variance against the last approved month, slip drawer. | Approve N ready |
| **Release** | Three gated steps, never batched: **Lock** (posts the accrual, approver ≠ locker) → **Publish payslips** → **Record payment**. Reverse is present, never primary, and demands a reason. | — |
| **Outputs** | This client-month's shelf — payslips, register, ECR, ESIC, PT basis, bank advice, 24Q feed — each *exists* or *blocked, because…*, every one **server-built**. | Download, then Mark handed over |

## Live defects — these ship before any of the above

Each was verified by reading the code, not inferred.

### 1. The ECR and ESI files the CA downloads are computed in the browser, by wrong rules

`apps/web/app/payroll/page.tsx:279` builds the EPFO ECR client-side. The server's
correct `GET /runs/{run_id}/ecr` and `/esic` **have no caller in the web app.**
The browser version:

- hardcodes **`NCP_DAYS` to 0** — every employee's loss-of-pay days are remitted
  to EPFO as zero;
- puts **PAN in `MEMBER_ID`**, or fabricates `EMP0001` when there is no PAN. The
  field is the **UAN**. A fabricated member id in a statutory remittance file;
- computes **EPF wages on basic alone**. EPF Act §6 is basic **+ DA** — the exact
  bug the September audit fixed in the backend;
- tests ESI eligibility as `gross_paise <= 2100000` for the current month,
  ignoring **Rule 50 contribution periods** — also already fixed in the backend;
- computes ESI contributions in **floating point**.

This is CLAUDE.md's "zero business logic in the frontend" rule being violated in
the one place where violating it produces a wrong statutory filing. **Delete both
browser generators; call the server.**

### 2. The payroll accrual is dated to the button press, in UTC

`services/phase2_journal_service.py` posts the payroll journal with
`entry_date=str(datetime.now(timezone.utc).date())`. Finalising August's payroll
on 3 September dates the accrual **3 September** — August's P&L carries no salary
cost and September carries two months, in books this firm produces. And between
00:00 and 05:30 IST the UTC date is **yesterday**.

It must be the payroll month in IST. The idempotency comment at
`routers/payroll.py:1472` already admits the dedup key is wrong for the same
reason.

### 3. Employee salary amounts are parsed with `parseFloat`

`app/payroll/page.tsx:531` — `rsToP(parseFloat(form.basic_rs) || 0)`.
`parseFloat("1,25,000")` is **1**. CLAUDE.md records that all 61 money call sites
were converted to `lib/money/rupeeInput.ts` and that there is no longer a second
way. This form is a second way. The CSV importer eleven hundred lines below it
carries a comment explaining this exact trap — and was fixed while the form
beside it was not.

### 4. Employees can read draft payslips

Migration 262:

```sql
CREATE POLICY "employee_reads_own_payslips" ON public.payroll_slips
  FOR SELECT TO authenticated
  USING (employee_id IN (SELECT public.my_employee_ids()));
```

No predicate on the run's status, and `payroll_runs.status` is
`draft | review | finalized`. The employee portal query has no status filter
either. A CA creating a draft run to check the numbers exposes every linked
employee's unapproved payslip.

**Latent, not live** — production holds zero payroll employees and none linked to
a login. It goes live with the first portal invite. Fix belongs in the RLS
policy: the frontend reads that table directly, so a page filter is not a control.

## Phases

Phase 1 is not a redesign. It is the wrong numbers.

| phase | what | why in this order |
|---|---|---|
| **1** | The four defects above, plus `statutory_gaps` reaching a screen and a payslip PDF the CA can actually download. | Live wrong numbers, and none of it needs the new IA. |
| **2** | `payroll_calendars`, per-client statutory identity, `payroll_opening_positions`, the two-dimensional grade. | The data the queue is derived from. Nothing visible yet. |
| **3** | **Month** — the client-month queue, Draft N ready, Generate N output sets. Payroll becomes a workspace. | The screen that makes a firm a bureau. |
| **4** | The client month rebuilt as Inputs · Register · Release · Outputs, over the existing route. | Where the month is completed. |
| **5** | **People** — one form, one import, the exception index. **Setup** — components, structures, state coverage. | Removes the two-forms-one-table hole. |
| **6** | Client portal payroll (review, dues, approve/return) and employee portal Pay. | The two portals the owner asked for. |
| **7** | **Statutory** (deposits, challan recording, filings shelf) and **Reports** rebuilt server-side. | Closes the loop into the ledger we already own. |

Leave management, bank advice files, and the remaining state PT/LWF tables are
sized and deferred; each is a named gap until built.

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

The code-grounded half is sound: 125 capabilities with file-and-line evidence,
44 structural problems, and the four defects above independently re-verified.

**The strongest case against this design:** it is a large surface for a module
with, today, zero employees in production. Phases 1 and 2 are justified whatever
happens next; phases 3 onward are a bet that payroll becomes a service the firm
sells. If that bet is wrong, we will have built a bureau console for one client.
The phase order is chosen so that bet is made late and cheaply.
