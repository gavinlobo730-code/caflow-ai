# What is left, and why each one needs you

**14 September 2026.** Written at the point where I stopped being able to make
progress alone.

279 findings. **267 closed, 12 open.** Every one of the 12 is blocked on
something I cannot supply from inside this environment — a document I cannot
fetch, or a decision that is yours rather than mine. None is blocked on
engineering effort.

`docs/audits/findings-status.json` is the authority and is amended in the
commit that closes a finding; this file explains the remainder.

---

## The blocker in one line each

| # | What it needs | Who |
|---|---|---|
| GST-21 | The §47 late-fee notification rates and the §50(3) notified rate | You — read two notifications |
| GST-32 | The IRP's INV-01 schema and the 30-day reporting window | You — download a schema |
| TDS-16 | The NSDL FVU / RPU file layout | You — download a spec |
| TDS-22 | The §194I(a) and §194J(a) concessional rates | You — read the Finance Act |
| PAY-27 | Per-bank NEFT / salary-advice file formats | You — your banks' specs |
| GST-25 | CMP-08 / GSTR-4 rates, GSTR-8, and the GSTR-9C layout | You — notifications and a form |
| IT-11 | Form 3CD's clause list | You — download the form |
| INV-05 | The freight / insurance / customs apportionment basis | You — decide |
| BANK-11 | What a TRUSTED bank rule may propose | You — decide |
| PAY-26 | Whether the API gets an employee principal | You — decide |
| INV-03 | How far into inventory the product should go (batch, expiry, godown) | You — decide scope |
| FA-11 | Which of seven fixed-asset capabilities you want | You — decide scope |

---

## 1. Six that need a document I cannot fetch

Direct egress is refused at this environment's proxy — every `.gov.in`,
`icai.org`, even Wikipedia (`curl https://example.com` → CONNECT 403). That is
the network policy, not a gov.in block. Everything below is written so that
**the engine works the moment the figure is written in**; none of them needs
code from you, only the number or the layout.

### GST-21 — the §47 late fee and the §50(3) rate

`domain/gst/late_filing.py` computes §50(1) interest per head on the cash
payable (Rule 88B(1)) and it is on the screen. Two things are refused:

- **`LATE_FEE_RATES` is EMPTY.** The statutory fee is ₹100 a day per Act capped
  at ₹5,000, and no registered person has paid that since 2018 —
  Notifications **4/2018** and **76/2018** reduced it, **19/2021** and
  **20/2021** capped it by turnover band. So the figure in force depends on
  the return, the year AND the taxpayer's own turnover. I need those four
  notifications' current tables.
- **`SECTION_50_3_NOTIFIED_RATE_BPS` is `None`.** Notification **13/2017-CT**
  notified 24% against the ORIGINAL §50(3); the Finance Act 2022 substituted
  the sub-section retrospectively from 01-07-2017 and Notification
  **09/2022-CT** appears to notify **18%** for the substituted text. A third of
  the charge separates them and this is money a CA pays over on a client's
  behalf, so I refused rather than pick. I need one of the two confirmed.

### GST-32 — e-invoicing

No INV-01 payload builder exists. I need the **IRP's INV-01 JSON schema**
(einvoice1.gst.gov.in → Documents) and confirmation of the **30-day reporting
window** and the turnover band it now applies from. Note this is separate from
the GSP registration question, which `docs/compliance/07-getting-permission-to-file.md`
already covers: e-invoice IRN is one of only two statutory outputs software can
complete end to end, because the IRP signs and there is no taxpayer signature.

### TDS-16 — the quarterly statement file

`domain/tds` computes every figure a 24Q/26Q/27Q needs and there is no FVU or
RPU writer. I need the **NSDL/Protean file format specification** (the
fixed-width record layout and the FVU validation rules). This is the last mile
between "the quarter is computed" and "the quarter can be filed".

### TDS-22 — two concessional rates

`domain/tds/section_rates.py` now holds `194I(A)`, `194I(B)`, `194J(A)` and
`194J(B)` as separate limbs, and the **(b) limbs are complete** — they carry
the rate the registry already held. The **(a) limbs withhold at the parent's
higher rate and say so**, because I would not state a rate I had not read:

- **§194I(a)** — rent of PLANT, MACHINERY or EQUIPMENT (lower than land and
  buildings).
- **§194J(a)** — fees for TECHNICAL services (lower than professional fees).

Over-deducting is the safe direction (an excess is the payee's to reclaim; an
under-deduction disallows the whole expenditure under §40(a)(ia)), so nothing
is wrong today — it is just charging more than the section asks. I need the
two rates from the current Finance Act.

### PAY-27 — the salary bank advice

No NEFT / bank-advice file builder exists anywhere. Every bank has its own
fixed-width or CSV upload format. I need **the formats for the banks your
clients actually use** — not a generic one, because a generic one fails at the
bank's portal and the CA finds out on payday.

### GST-25 — the return types the product does not file

`services/filing_demo/gstr9.py` is a walk-through, not a computation. Three
absent:

- **Composition (CMP-08 and GSTR-4).** The §10 rates are in the Act, but the
  **6% for services** came by notification (2/2019-CT(R)) and I will not write
  a rate I have not read.
- **E-commerce TCS (GSTR-8, and GSTR-3B Table 3.1.1).** Needs the form layout.
- **GSTR-9C**, the reconciliation statement. Needs the form.

---

## 2. One that needs a statutory form

### IT-11 — Form 3CD

The **applicability** half is closed: `domain/income_tax/tax_audit.py` decides
§44AB(a) and (b) from the nature of the activity (an INPUT now, not inferred
from the amount — the old screen told a ₹60 lakh trader a profession's
threshold applied), applies the proviso only when all three cash figures are
stated, and NAMES clauses (c), (d) and (e) as untested on every answer.

What remains is **Form 3CD itself** — a clause workspace, which needs a
migration and the form's own clause list. Forty-four clauses written from
memory onto a statutory annexure is precisely what this codebase refuses
everywhere else. I need the current Form 3CD.

---

## 3. Two decisions that are yours

### INV-05 — what else belongs in the cost of stock

The blocked-tax third is **closed**: AS-2 ¶6 puts non-recoverable tax in the
cost of purchase, and a receipt now carries the §17(5)-blocked GST that used to
strand itself in the expense account for ever.

**Freight inward, insurance and customs duty are still not in cost.** Closing
that needs a migration AND your decision, because the apportionment basis is
something Tally asks the user rather than deriving:

> A ₹50,000 freight bill covers a container of 200 chairs and 20 tables. Do you
> apportion **by value**, **by quantity**, or **by weight**?

All three are defensible under AS-2. The answer changes every unit cost, every
COGS and the closing stock, so it is a policy, not a default — and once chosen
it has to be the same for all inventories of a similar nature (AS-2 ¶16).

### BANK-11 step 3 — what a trusted bank rule may propose

Steps 1 and 2 are **closed** (migration 380): a rule now says which field it
reads, which operator, several alternative patterns, and which rule wins. Every
default reproduces the old behaviour exactly.

Step 3 is widening what a rule may PROPOSE — split legs, a party, a TDS
treatment. **That is your call and not mine**, because a rule a Manager marks
trusted posts with nobody watching. It is the one place the product acts
unprompted. Matching wider was safe to build (a CA types every pattern, and the
widest case was always reachable with an empty pattern); posting wider is a
different question.

### PAY-26 — an employee principal on the API

I established this today and it is worth reading before anyone re-derives it.

The employee portal has four tabs and reaches the database **only over
PostgREST**, under migration 262's per-command policies. There is **no employee
authentication dependency for the API at all** — `core/portal_auth` has a
CLIENT principal and no employee equivalent.

So the finding's own highest-value half — showing an employee HOW their TDS was
arrived at, whose engine already exists as `GET /api/payroll/tds-projection` —
cannot be served without first adding a second unauthenticated-principal auth
surface to the API. That is an architectural and security decision, not a
backlog fix, so I stopped rather than build it.

(Form 16 in the same finding is separately unbuildable: no generator exists,
and from 01-04-2026 the form is **130**, in three parts.)

---

## 4. Two that need a scope decision

`CLAUDE.md` says plainly: *"Don't infer scope from this list — ask. It is a
description of what exists, not a licence to extend any of it."* These two are
where that bites.

### INV-03 — batch, expiry, godown, item group, alternate unit, reorder level

None of it exists in any migration. Each is real for some clients and noise for
others: batch and expiry matter enormously to a pharma or food distributor and
not at all to a consultancy. **How many of your clients hold stock that needs
batch tracking?** If the answer is "one or two", this is a different and smaller
build than if it is "most of them".

### FA-11 — CWIP, revaluation, impairment, componentisation, shift factor

Seven separate capabilities behind one finding number, and they are not one
feature:

- **CWIP** and the **transfer log** are ordinary Schedule III presentation and
  I would build them without asking.
- **Componentisation** and the **shift factor** are Schedule II Part C
  judgements about a specific asset.
- **Revaluation** is an accounting-policy MODEL under AS-10 — whether the
  product offers it at all is a product decision, and offering it means
  building the revaluation reserve and the depreciation split that follows.
- **Impairment** is AS-28 and a subsystem of its own.

Tell me which of the seven you want and I will build those.

---

## 5. One thing that is not a finding, and it is the most urgent

**The branch carries 14 unmerged migrations — 382 to 395 — against a production
mark of 381.**

Merging a migration to `main` applies it to the production database; there is no
manual step in between (`docs/deploy-migrations.md`). So these fourteen are
written, applied against a real Postgres in CI, and **not in production**.

This is not a staleness problem a fixture refresh can fix — the mark records
what production has APPLIED, and a migration reaches production by merging.

The guard that used to count unmerged migrations has been **replaced by a
stronger one** in this branch rather than loosened again: the in-flight
exclusion now covers only objects an unapplied migration CREATES (it used to
excuse a finding if any pending migration merely MENTIONED the name, which
shielded the busiest tables in the schema), so the shielded count is measured
directly and is currently **zero of production's 279 tables**. CI is green
either way. But the migrations still want merging, and the longer the branch
runs the larger a single production apply becomes.

---

## What the 268 closed ones did, in one paragraph

The backlog began at 279 findings across fourteen modules. What came out of it
is not a list of patches: the statutory engines are now single authorities with
their refusals written down (`domain/gst/`, `domain/tds/`, `domain/income_tax/`,
`domain/payroll/`, `domain/inventory/`, `domain/fixed_assets/`), every figure a
CA pays over is either computed from a section or refused with the reason, and
the places where a number cannot be known are NAMED on the answer rather than
guessed. The ratchets are the durable part — a guard that states the RULE
rather than a spelling of it, so the next person to break one finds out at CI
instead of at a portal.
