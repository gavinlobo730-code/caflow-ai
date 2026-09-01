# Payroll: could a CA actually run a client's payroll on this for a full year?

**1 September 2026.** Not an inventory of what exists — a walk-through. Onboard
an employee, run twelve months, handle a mid-year joiner and a leaver, file four
24Qs, produce the ECR and ESIC returns, close the year, issue Form 16. Wherever
the walk-through stopped, that is a finding.

Findings are ordered by what they cost, not by where they were found.

---

## Answer

**Yes for the monthly cycle, the leaver and the statutory returns. No for
anything that has to reach the government by itself.**

A firm could run a client's payroll on this today: compute the month, withhold
correctly, settle a leaver, produce the ECR and ESIC files, file the four 24Qs
and get a Form 16 out of TRACES at the end. What they could not do is file
anything through the software.

*Amended 1 September, later the same day.* When this was first written the
answer was "no for the leaver" — the settlement computed correctly and nothing
consumed it. That gap is now closed; see **The leaver, wired** below.

---

## What the walk-through broke on

### 1. A mid-year joiner was over-deducted — ₹1,46,250 on one employee

`_compute_slip` projected the year as `gross × 12`. §192(1) requires TDS on "the
estimated income of the assessee under the head Salaries" **for that financial
year**, and for someone who joined on 1 October that is six months of salary.

An October joiner on ₹2,00,000 a month earns ₹12,00,000 in the year and owes
**nothing** after the §16(ia) deduction and the §87A rebate. The twelve-month
projection withheld **₹1,46,250**. At ₹3,00,000 a month it was ₹2,56,100.

§192(3) cannot recover it, because the projection itself is what is wrong — the
money comes back only on assessment, a year later.

*Fixed.* The estimate is now what has been paid this year plus this month's pay
times the months still to come, with the months taken from the joining date.
That also picks up a mid-year raise for the remaining months without rewriting
the ones already paid. An unknown joining date still returns twelve: the
pre-existing behaviour, and the direction §192(1) makes the employer liable for
getting wrong — which is why the joining date is worth capturing.

### 2. Gratuity displayed as zero for every employee, silently

`app/payroll/statutory/page.tsx` read `emp.date_of_joining`. That is not a
column; it is `joining_date`. The page selected `"*"`, so PostgREST returned
rows without that key rather than erroring, the value was `undefined` for
everyone, and gratuity has shown as ₹0 for as long as the page has existed.

`test_frontend_columns_exist_pg.py` could not see it because it parses select
lists, and `"*"` names no columns to check.

*Fixed*, along with three other drifts on the same page — it was computing PF,
ESI and gratuity in TypeScript against CLAUDE.md's rule that computation lives
in `apps/api`:

| | what it did | what it should have done |
|---|---|---|
| PF | on **basic alone** | basic + DA (EPF Act §6) |
| employer 12% | flat 3.67 / 8.33 split | EPS capped at 8.33% of the ceiling; `eps_eligible` ignored entirely |
| ESI | no contribution periods | Rule 50 keeps a member in past the ceiling until the period ends |
| gratuity | phantom column → ₹0 | the Act's formula |

All four are now one implementation behind `GET /api/payroll/statutory-position`.

### 3. `_logger` was referenced five times and never defined

Every "read failed, carry on with the safe default" branch logged through
`_logger`. The first real read failure would have raised `NameError` from inside
the `except` — turning a graceful degradation into a 500, on the one day
something was already going wrong. *Fixed*, and pinned by tests that force a
read to fail.

### 4. Annexure II claimed professional tax for everyone

§115BAC(2)(i) computes total income without any deduction under section 16 save
clause (ia). Professional tax under §16(iii) is not available under the new
regime — and payroll withholds on the new regime by default, so it was being
claimed for everyone it was **not** available to. It understates income under
the salary head, so the annexure disagreed with TRACES' own computation of Part
B: a Form 16 wrong in the employee's favour and traceable to the employer.
*Fixed*, gated on the regime, which the annexure now carries as its own column.

### 5. §80TTA was granted with no interest income behind it

§80TTA(1) allows the deduction on interest **"included in the gross total
income"**. Uncapped, an employee who claimed ₹10,000 and reported none got
₹3,120 of relief on income never brought to tax. *Fixed* — capped at what was
reported under §192(2B).

### 6. Three deposit dates were missing from the compliance engine

It had GST, ITR, the 24Q return, MCA and advance tax — and none of the deposits
a payroll generates every month: EPF and ESI on the 15th, TDS on the 7th, and
**March's TDS on 30 April rather than 7 April**. §201(1A)(ii) charges 1.5% a
month from the date of *deduction*, so three weeks late on March costs two
months of interest. *Fixed.*

Professional tax is deliberately still absent, and pinned as absent by a test:
its due date is set by each state and there is no single rule.

---

## The leaver, wired

*Closed on 1 September, after this audit was first written.*

`POST /employees/{id}/settlement` still computes and writes nothing — settling
someone ends their employment and releases money, and that should not happen as
a side effect of a preview. `POST .../settlement/record` is the act, guarded at
`payroll:finalize` and going through the **same composition path**, so the
figures a CA approved on screen are the figures recorded.

It stores the settlement with its components, withholds under §192 (the taxable
part added to the year's income, the tax already deducted credited against it —
§192(3)'s adjustment, exactly as a monthly run makes it), posts through the one
kernel, and marks the employee resigned or terminated so no later run pays them.

**Each component lands on the line the statute puts it on**, rather than all
being lumped into §17(1):

| | line | exempt under |
|---|---|---|
| salary to last working day | §17(1) | — |
| leave encashment | §17(1) — §17(1)(va) expressly makes a payment for leave not availed *salary* | §10(10AA) |
| statutory bonus | §17(1) | — |
| gratuity | §17(3) — a termination payment | §10(10) |

Annexure II reads settlements alongside the year's slips, so the taxable part
reaches Form 16 without anyone re-keying it, and its TDS reaches 24Q.

**Two things the ledger does differently from the tax computation, on purpose.**
A recovery reduces the employer's *cost* (it is netted off the salary debit) but
never reduces §17(1) — taking notice pay back does not un-earn the salary. And a
**loan** recovery is not a cost reduction at all: the employee owed the money,
so collecting it extinguishes a receivable and gets its own credit.

The journal refuses to post if the debit and the credits disagree, rather than
defining one from the other. That is deliberate: defining the debit as the sum
of the credits is exactly how the payroll accrual's own missing-credit-leg bug
stayed hidden until this audit found it.

## What still stops a CA, and what it would take

### Nothing files anything

By design (CLAUDE.md, "Not built yet"). The ECR, the ESIC return, the 24Q and
its Annexure II are all *prepared* and downloaded for a human to upload. Real
filing needs GSP registration for GST and a `SW########` software-provider
registration for the income-tax side — commercial steps, not coding ones.

### The statutory data a human has to supply

Each of these is refused rather than guessed, and each refusal is visible in the
response as a named gap:

| what | why it cannot be derived |
|---|---|
| PT slabs for 18 of 22 states | each state's own notification, revised on its own cycle |
| LWF amounts (16 states) | same |
| minimum wage for §12 of the Bonus Act | per state, per scheduled employment, per skill grade, revised twice yearly |
| SBI's rate for Rule 3(7)(i) | published annually by the bank |
| ESIC reason codes | ESIC's own list |
| ITR JSON schemas | downloaded per form per assessment year |
| an earlier year's total income for §89 | the employee's own return |
| prior gratuity / leave exemption used | a lifetime limit across employers |

The consistent choice throughout: **a flagged gap costs a lookup; a wrong figure
costs an employee their pay and the employer the shortfall.**

### Smaller things, unfixed

- **§17(3) profits in lieu** are not modelled. Reported as a gap on Annexure II.
- **A car used wholly privately** cannot be valued — Rule 3(2) Sl. No. 1(b)
  needs the actual running expenditure and 10% of the car's cost, neither of
  which payroll holds. Refused, not guessed.
- **Gratuity is not provided for at year end.** The liability is computable
  (`/statutory-position` returns it per employee) but nothing books a provision.
- **A finalised run cannot be corrected**, only superseded. That is consistent
  with the ledger's immutability rules, but there is no reversal-and-reissue
  path for a payroll the way there is for a journal.
- **FY-versioned rate registries hold only 2025-26 and 2026-27.** §89 relief
  refuses any earlier year rather than computing it at substituted rates — which
  is correct, and means §89 does not work for most real arrears until the
  earlier years' Finance Acts are added.

---

## What was verified, and how

Every statutory figure in this work was arrived at from the statute and checked
against a worked example, not read back off the implementation. Every change
carries a negative control: the code is mutated, a **named** test must fail, the
code is restored, the test must pass again.

Two controls did not behave and both were treated as test defects rather than
passes:

- swapping `slice_.fy` for `receipt_fy` in the §89 loop **broke nothing**,
  because the registry holds only two years and they carry identical rates. The
  property had no behavioural signature at all. A synthetic year with a flat
  30% slab was injected so it does, and the control then failed it.
- one control appeared to fail another control's test. That was a stale
  `__pycache__`; re-run with the cache cleared it bit its own test.

At the close: **8,484 mock-mode tests and 569 real-Postgres tests pass.**

---

## Files this touches

| settlement recording, GL posting | `routers/payroll.py`, `services/phase2_journal_service.py` |
| area | where |
|---|---|
| declarations, Form 12BB, regime intimation | `domain/payroll/declarations.py` |
| gratuity | `domain/payroll/gratuity.py` |
| statutory bonus | `domain/payroll/bonus.py` |
| leave encashment | `domain/payroll/leave_encashment.py` |
| full & final settlement | `domain/payroll/settlement.py` |
| arrears, §89, Form 10E | `domain/payroll/arrears.py` |
| perquisites, Rule 3 | `domain/payroll/perquisites.py` |
| ECR, ESIC, 24Q, Annexure II | `domain/payroll/{ecr,esic,form24q,annexure2}.py` |
| PT / LWF state coverage | `domain/payroll/{professional_tax,lwf}.py` |
| PF, ESI, versioned rates | `domain/payroll/statutory.py` |
| deposit due dates | `services/compliance_engine.py` |
| the run itself | `routers/payroll.py` |

Migrations 295–302.
