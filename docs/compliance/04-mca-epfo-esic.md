# MCA, EPFO and ESIC — where there is no API at all

Confidence grades and the sourcing caveat: see `00-how-to-read-this.md`.
**No primary source was read directly.**

---

## 0. The answer, first

| Body | Can software file programmatically? | Realistic ceiling |
|---|---|---|
| **MCA / ROC** | **No.** No API programme of any kind. No GSP-equivalent. | Generate the XBRL instance + prepare form data; a human logs into MCA21 V3, uploads, affixes DSC, pays. |
| **EPFO** | **No.** No employer-facing API for ECR upload, challan generation, UAN allotment or KYC. | Generate a valid ECR `.txt`; the employer uploads on the Unified Portal and pays. |
| **ESIC** | **No.** No API at all — the most clearly closed of the three. | Generate the monthly-contribution Excel; the employer uploads at esic.gov.in and pays. |

**Unlike GST, there is no programme to join.** No empanelment, no sandbox, no
published specification, no commercial gate that could be paid to open. The gap
between "we prepare a perfect file" and "we file" is **a human with a browser and
a DSC**, and it is not a coding problem.

Two honest qualifications:

1. **Absence of evidence.** It can be shown that no official API is documented or
   advertised; it cannot be proven none exists behind an unpublicised agreement.
   But the vendor ecosystem uniformly describes prepare-then-upload, which is
   what you would expect if none existed.
2. **Undocumented private endpoints exist and are not usable.** The MCA XBRL
   validation tool's pre-scrutiny step calls MCA servers; portals obviously have
   internal APIs. Reverse-engineering them would be unsupported, would breach
   portal terms, and would break without notice. **Out of scope on exactly the
   same grounds CLAUDE.md rules out net-banking screen-scraping.**

---

## 1. MCA / ROC

### V3 migration — complete

- **Set 1, 9 forms, live 31 August 2022** (DIR-3 KYC, CHG-*, DPT-3/4). `[P]`
- **Set 2, 56 forms, January 2023.** `[P/S]`
- **Lot 3, the final 38 company forms, live 14 July 2025** — including **13
  annual filing forms** (AOC-4, AOC-4 XBRL, AOC-4 CFS, MGT-7, MGT-7A, CSR-2) and
  **6 audit forms** (ADT-1/2/3, CRA-2/4). `[P]`

**Nothing remains on V2.** ⚠️ V2 was reportedly fully decommissioned **30 June
2026**, with master data, form tracker and DSC association going dark in phases
from mid-May 2026. `[S]` Sources conflict on whether "V2 shut down" means 2025 or
2026; the reconciliation that fits all of them is that *company e-filing* stopped
on V2 in June 2025 and the *residual read-only surfaces* went in June 2026. **That
reconciliation is inference, not sourced.** `[U]`

> **Worth a grep:** anything in the product still pointing at V2 `mcafoportal`
> URLs is broken.

### Is there a filing API? No.

**No official MCA API documentation, no developer portal, no partner programme,
no registration path** for third-party filing. `[S — searched specifically]`

⚠️ Several SEO/AI-generated posts assert "MCA V3 features API integration for
professionals". **Treat as false or badly worded.** They are almost certainly
describing MCA's *inbound* integrations — SPICe+/AGILE-PRO-S at incorporation
genuinely does talk to PAN/TAN, GSTN, EPFO, ESIC and banks, but that is **MCA
calling them**, not vendors calling MCA — plus V3's internal prefill. One such
page lists MCA V3 as integrating with "Income Tax, GST, EPFO, ESIC, DPIIT, Banks,
Aadhaar, DigiLocker", which is exactly the SPICe+ story.

### The offline utility — the closest thing to a machine interface

For Lot-3 annual forms, V3 offers both an online web form and an **offline Excel
utility**: `[S]`

1. The user starts the filing on the portal and enters basic details.
2. **The portal generates and serves a pre-filled Excel**, populated with
   prior-year financials and company data.
3. The user completes it offline.
4. The user uploads it back for validation and submission.

Prefilled prior-year figures can be edited but require a mandatory reason.
**Because the workbook is issued by the portal per filing, software cannot
originate one** — the realistic play is *populate a downloaded workbook*, not
*mail one in*.

⚠️ **Whether that is feasible or fragile could not be established** `[U]`:
unknown whether the workbook is macro-enabled, password-protected, or has a
stable cell layout across versions. Needs hands-on inspection of a real download.

### XBRL — the one genuinely machine-facing artefact

**Who must file AOC-4 XBRL** — Rule 3(1), Companies (Filing of Documents and
Forms in XBRL) Rules 2015: listed companies **and their Indian subsidiaries**;
paid-up capital **≥ ₹5 crore**; turnover **≥ ₹100 crore**; or any company
preparing financials under **Ind AS**. Exempt: NBFCs, housing finance, banking
and insurance. **Once you file in XBRL, including voluntarily, all subsequent
filings must be XBRL.** `[P]`

**Two taxonomies for AOC-4** — **C&I** (the AS/Indian-GAAP one) and **Ind AS** —
chosen by reporting framework. **CRA-4** uses the separate **Costing** taxonomy.

**The confirmation that matters:** MCA released **XBRL Validation Tool V5.0**
around **12 July 2025**, and the announcement carried an explicit note addressed
to software vendors: `[P]`

> "For Software Vendors: Please ensure that the latest schema URL is used for the
> new MCA XBRL Validation Tool for all applicable taxonomies"

MCA's own filing manual states companies may create XBRL documents in-house or
via a third party, that stakeholders should check software against MCA's
published **Business Rules**, and that **MCA recommends no specific software**.
`[P]`

**So instance documents can be generated programmatically and uploaded
manually.** The workflow:

```
generate instance → validate (offline, MCA tool) → pre-scrutinise (MCA tool,
requires internet — runs MCA's SERVER-side rules) → attach to AOC-4 XBRL on V3
→ DSC → submit
```

The pre-scrutiny step is a real MCA server call **exposed only through the
desktop tool**. It is not a documented API and must not be treated as one.

⚠️ No evidence of a version newer than V5.0 was found, but the download page
could not be read. **Verify the current tool version and schema URLs before
writing any generator** — the vendor note exists precisely because these move.

> **Recommendation: version the taxonomy/schema URL the way the rate registries
> are versioned** — a `LATEST_VERIFIED` marker plus a hand-download step. That is
> exactly the ITR JSON schema pattern already in CLAUDE.md §2, and for the same
> reason: it cannot be generated or inferred, somebody downloads it.

### DSC

**Class 3 mandatory.** Associated on V3 under MCA Services → DSC Services →
Associate DSC, with different flows for **Director**, **Professional (CA/CS/CMA,
needs membership number)**, **Authorised Representative** and **Nodal officer**.
Only a **Business User** can associate a DSC. Where a form needs several
signatures, **each signatory affixes their own**. `[S]`

⚠️ Reported 15-day (upload signed PDF against the SRN) and 7-day (pay) windows
are secondary-source figures that may vary by form. **Verify before encoding them
as deadlines.** `[U]`

**Who signs what was NOT re-verified in this research** `[U]` — the general
position (AOC-4 by a director with CFO/CS where appointed, certified by a
practising professional; MGT-7 by a director and CS or PCS, with MGT-8 for larger
companies; ADT-1 filed by the company not the auditor; DIR-3 KYC by the director
and certified) should be checked against the Rules before it goes anywhere.

**Either way, the design implication holds:** the DSC is a hardware token in a
physical person's possession, and that person is usually the **client's**
director, not the CA. Same shape as GST signing and AA consent — *software
prepares, a named human signs*. Plan the UX around handoff and evidence of
handoff, never automation.

### Read APIs / company data

| Route | What | Notes |
|---|---|---|
| V3 master data lookup | company/LLP master data, DIN, charge index | Free, **web UI not an API** `[S]` |
| View Public Documents | actual filed documents | Paid; a ₹100/company figure appeared but is **unverified and likely stale** `[U]` |
| **data.gov.in OGD dataset** | bulk company master data — CIN, name, status, class, capital, RoC, activity | **MCA's genuine open-data publication.** ZIP bulk download. **Point-in-time snapshot, not live** — do not use for status checks `[P]` |
| Commercial resellers | Probe42, Signzy, Karza, Tofler, FileSure | License or scrape; **MCA endorses none** `[S]` |

### Operational reality — plan for the portal being down

- **A fire at the MCA21 data centre on 5 June 2026** forced a DR switchover and
  degraded services during a peak filing window. `[P — MCA's own account]`
- **General Circular 03/2026 dated 8 July 2026** extended the Companies
  Compliance Facilitation Scheme 2026 to **31 August 2026**, citing data-centre
  restoration. ICSI sought a further extension on 20 August 2026; **none had been
  notified** as at the sources seen. `[S]`
- ICSI has filed **repeated representations** about V3 session timeouts, lost
  drafts and attachment failures. `[S]`

> **Any MCA-facing feature must be resumable and must never infer a filing
> outcome from a failed interaction.** The documented record is of instability
> during exactly the weeks the feature would be used.

---

## 2. EPFO

### The ECR file — format confirmed

Plain **text**, **11 fields**, delimiter **`#~#`**: `UAN`, `MEMBER_NAME`,
`GROSS_WAGES`, `EPF_WAGES`, `EPS_WAGES`, `EDLI_WAGES`, `EPF_CONTRI_REMITTED`,
`EPS_CONTRI_REMITTED`, `EPF_EPS_DIFF_REMITTED`, `NCP_DAYS`,
`REFUND_OF_ADVANCES`. `[P — EPFO's own PDF]`

Validations include EPS wages ≤ ₹15,000, EDLI wages ≤ ₹15,000, EPF wages ≥ EPS
wages per member, NCP days ≤ days in month.

⚠️ One source mentioned a `||` delimiter. **Believed wrong** — `#~#` is what the
ECR 2.0 sources overwhelmingly say.

### ⭐ The revamped ECR — VERIFIED, effective wage month September 2025

**VERIFIED 2026-09-04**, including a search for a deferral or relaxation. The
launch had one, it has expired, and enforcement is fully live.

**Two circulars, not one**: the launch circular of **26 September 2025**, and a
**FAQ circular of 8 October 2025**. `[P/S]`

**The file format did NOT change** — confirmed by EPFO's own material and by a
payroll vendor answering exactly this question. The `.txt` layout and the 11-field
`#~#` schema are unchanged; employers upload the same file. **Only the workflow
and the validations changed.** `[P/S]`

What did change:

1. **Return and payment are separated, and ordered.** The employer must
   **submit and approve the return FIRST**, and only then generate the challan
   and pay. Two states per month, in sequence.
2. **Sequential month-wise filing is enforced by blocking**, not advised.
   *"You cannot file for October if September is still pending."* `[S]`
   There was an **initial four-month relaxation** at launch; after it, the system
   blocks a Regular Return for a month unless the data from **four months prior**
   is fully filed and validated. From wage month September 2025 that relaxation
   expired around January 2026 — **it is fully live now**.
3. **Pending pre-September-2025 months must also be filed through the revamped
   system** (FAQ 3, circular 08-10-2025).
4. **THREE return types**, which the first research pass under-described:
   - **Regular** — contributions for all active members for a wage month;
   - **Supplementary** — to add employees registered *after* that month's
     Regular Return was approved;
   - **Revised** — to correct wages or contribution details already submitted.
5. **§7Q interest and §14B damages are auto-computed by EPFO** and surfaced in
   the *Due Deposit Balance Summary* at challan generation. **§7Q interest is
   payable with the principal**; **§14B damages may be paid forthwith or
   later** — an option, not the same obligation.
6. **System-based validations** now reject what previously passed silently —
   wages, UAN validity, ineligible pension contributions.

> **What this means for the code** (task #122). `GET /runs/{run_id}/ecr` builds a
> file **per run**, with no notion of return type and no notion of month
> sequence — verified by grep; the only mention of either in the ECR path is the
> marker added by this work.
>
> The file it emits is still **correct**, because the format did not change. What
> is missing is everything around it:
>
> - **"Which months are outstanding, in order"** has to become a first-class
>   concept. A client with a gap cannot file the current month at all, so a
>   product that hands a CA this month's file without saying "August is blocking
>   it" is handing them something the portal will refuse.
> - **Return type** is a real distinction. A late joiner is a *Supplementary*
>   return, not a re-filed Regular one.
> - **Never compute §7Q or §14B here.** EPFO computes them. A second
>   implementation of a statutory interest calculation is exactly the drift this
>   codebase keeps removing, and the CA would have two numbers with no way to
>   tell which the portal will accept.

### Rates — and what actually moved in 2025

| Account | What | Rate |
|---|---|---|
| A/c 1 | EPF — employee 12% + employer 3.67% | |
| A/c 10 | EPS — employer | 8.33%, capped at ₹15,000 → max ₹1,250 |
| A/c 2 | EPF **admin charges** | **0.50%**, w.e.f. 1 June 2018 (was 0.65%, before that 0.85%) |
| A/c 21 | **EDLI** — employer | 0.50%, capped at ₹15,000 → max ₹75 |
| A/c 22 | EDLI admin | **Nil since 1 April 2017** |

Minimum for A/c 2: **₹500/month** functional, **₹75/month** non-functional. `[S]`

> **Every one of these matches `domain/payroll/statutory.py` exactly.** `[S]`
>
> ⚠️ One shared open item: the **₹500 minimum was set in the 0.65% era**, and
> **neither the research nor the code has a primary source confirming it survived
> the June 2018 cut.** Both assert ₹500. That is agreement, not verification.

**No 2025 admin-charge notification was found.** What actually moved in 2025:

- **EDLI benefit reforms** (237th CBT): minimum ₹50,000 where death occurred
  before a year of continuous service; a gap of up to two months counts as
  continuous; benefit admissible where death occurs within six months of the last
  contribution. `[S]` **These are benefit-side and change nothing an employer
  remits or a payroll engine computes.**
- The **revamped ECR** above.
- The **Labour Codes** below.

### UAN / KYC

**No official API.** `[S]` UAN generation and activation via Aadhaar face
authentication on **UMANG** `[P]`; bulk UAN generation without Aadhaar rolled out
in 2025; employer-portal KYC approval queue. Third-party "EPFO APIs" are
**verification** services (Signzy, AadhaarKYC) — a different thing, and none of
them file.

> A documented case exists of an employer using **RPA (UiPath) to drive the EPFO
> portal UI**. That is the clearest available evidence that no API exists. `[S]`

**EPFO 3.0** is a cloud re-platforming programme focused on *member* services
(UPI/ATM withdrawal, auto-claims). Some coverage claims "better payroll
integration"; **no employer API was announced.** Treat as aspiration. `[S]`

---

## 3. ESIC

**Mechanism:** employer logs in → File Monthly Contribution → key in online **or
download the sample Excel template** for the month → fill → upload → submit →
generate challan → pay. `[S]`

**Columns (six per insured person):** `IP Number` (10 digits), `IP Name`, `No. of
Days`, `Total Monthly Wages`, `Reason Code`, `Last Working Day`.

⚠️ The frequently repeated rules — **all columns formatted as Text**, saved as
**Excel 97-2003 `.xls`** — trace to guidance from around **2011**. They may still
hold (the portal is old), but **verify against a freshly downloaded template**.
Getting this wrong produces silent upload rejections. `[U]`

**Rates:** employer **3.25%**, employee **0.75%**, ceiling **₹21,000/month**
(₹25,000 for employees with disability), unchanged since 1 July 2019. `[P/S]`
⚠️ Proposals to raise the ceiling to ₹25,000–₹30,000 have been reported
repeatedly; **₹21,000 still stands** as at the 2026 sources seen, but this is
exactly the figure that moves by notification.

**API: none.** Searched specifically — no documentation, no developer portal, no
web-service spec. ESIC's published technical contact is an IT support desk, which
is the opposite of a developer programme.

### Reason codes — the research independently confirms the code's refusal

**Four differently-phrased searches failed to obtain an authoritative numeric
mapping.** `[U]` What could be established: codes are **numeric**, entered against
an IP with zero days/wages, `0` where the question does not arise; some require a
Last Working Day; categories include *On Leave, Left Service, Retired, Out of
Coverage, Expired, Non-Implemented Area, Retrenchment*. Only two numeric mappings
surfaced, both from low-quality sources. **Published guides disagree on the
numbering.**

> `domain/payroll/esic.py` already says, in the code:
>
> > "The numeric coding could not be confirmed against an authoritative ESIC
> > source when this was written. Published guides disagree about which number
> > means what."
>
> **Independent research reached the identical conclusion.** The module's
> decision — refuse, name the employee as a problem for the CA, withhold the
> file, and auto-write `0` only where wages are positive — is correct and
> nothing here argues for changing it.
>
> ⚠️ **ESIC issued a circular in October 2025 flagging misuse of filings showing
> zero-day workers.** `[S]` Zero-day rows are now under active scrutiny, which
> **raises** the cost of a wrong reason code. The refusal is more right now than
> when it was written.

**IP registration:** mandatory within **10 days** of joining; produces a 10-digit
insurance number; mobile and bank details mandatory per an ESIC circular of 29
June 2020; a **Bulk IP Aadhaar Upload** Excel facility exists. `[S]`

---

## 4. Cross-cutting: the Labour Codes and the 50% wage rule

**VERIFIED 2026-09-04**, including adversarial searches for a deferral, a stay
or transitional relief. None found. No primary document could be opened (see
`00`), but the chain is corroborated across independent sources and, unlike the
rest of this file, **it changes a number the product computes today**.

### The chain of commencement

| Date | What |
|---|---|
| **21 Nov 2025** | All four Labour Codes in force (PIB). The EPF Act 1952 and ESI Act 1948 stand subsumed into the **Code on Social Security 2020** |
| **8 May 2026** | Final **Rules under the Code on Social Security** notified |
| **29 May 2026** | Ministry of Labour notification declaring **₹15,000 the wage ceiling for Chapter III (EPF)** under the new Code |

So the framework is not "commenced but awaiting rules" any more. The rules are
notified and the ceiling has been formally re-notified under the new Code.

### The rule

**s. 2(y), Code on Wages 2019** defines wages as **basic pay + dearness
allowance + retaining allowance**, then lists exclusions (HRA, conveyance,
overtime, employer PF contribution, statutory bonus and others). Then:

> the exclusions **shall not exceed 50% of total remuneration**, and **the excess
> shall be deemed to form part of wages**.

**The Code on Social Security adopts that definition for computing PF
contributions.** `[S]`

> It is best read, as one commentary titles it, as **a cap on exclusions, not a
> ceiling on wages**. It does not force basic to be 50% of CTC; it adds back
> whatever excess there is.

**Both ceilings are unchanged** — EPF **₹15,000**, ESI **₹21,000** (unchanged
since January 2017). That is what bounds the damage.

### ✅ FIXED — what the code does now

`routers/payroll.py` computed `pf_wages = basic + da` with no add-back. It now
calls `domain/payroll/wage_base.compute`, which applies §2(y) for any payroll
month **ending on or after 21-11-2025** and reproduces the old figure exactly
for every earlier month.

The failure it closes, and the arithmetic is a test rather than a claim:

```
total remuneration        28,000   (10,000 basic + 18,000 HRA)
exclusions = 64% of total  ->  excess over the 14,000 half = 4,000 deemed wages

wages OLD (basic + DA)    10,000
wages NEW (with add-back) 14,000   <- both under the 15,000 ceiling
employee PF @12%           1,200  ->  1,680
```

**₹480 a month on each side.** Above the ceiling nothing changes, because
`min(wages, 15000)` already made the add-back moot.

**Which components are excluded, and the rule for deciding.** Of what the
product models, exactly two are named by the statute closely enough to classify
without judgement — **HRA** is clause (f) verbatim, **LTA** is clause (d), *"the
value of any travelling concession"*. Everything else stays on the wage side,
deliberately:

- it is **the direction that cannot under-deduct** — misclassifying a wage as
  excluded short-credits an employee's provident fund and draws §7Q interest;
  the opposite merely over-states;
- and the two obvious candidates do not survive reading the clauses. A cash
  **medical allowance** is not clause (b), which is amenities *in kind* excluded
  by government order. A **special allowance** is not clause (e), which is about
  defraying expenses actually entailed by the job — and *RPFC v. Vivekananda
  Vidyamandir* (2019) held universally-paid allowances to be basic wages.

So a component the module has never heard of is treated as a wage, and adding an
excluded one is a deliberate act requiring a clause to cite.

**One-time earnings are outside the test.** A bonus is an exclusion at (a) and a
commission at (i), but putting them in the *denominator* would raise the 50% half
and shrink the add-back — the direction that under-deducts. Arrears of basic and
DA still reach the base on top, as they always did.

**Migration 334** stores `pf_wages_paise`, `pf_wages_addback_paise` and
`pf_wages_rule_applied` on every slip, following the rule of migrations 295 and
329: a figure the ECR and the ledger must agree on is stored, never recomputed
from inputs that can move. **There is no backfill, deliberately** — slips before
commencement were right for their period, and released slips record what the
employer actually remitted. Correcting an under-remitted past month is a CA's
decision with a statutory consequence, not a migration.

### ESI — the error probably runs the OTHER way, and this is less certain

`_compute_esi` takes **gross**, which was right under ESI Act §2(9), where
"wages" was already broad. Under the Code's definition ESI wages would be the
**narrower** basic + DA + retaining allowance **with the same 50% add-back** —
which is generally **less than gross**.

So where the EPF base is probably **under**-stated, the ESI base may be
**over**-stated. `[U]` Sources still routinely describe ESI as computed "on
gross wages", and whether the Code's narrower definition displaces §2(9) for
contribution purposes is exactly the sort of question that needs a practitioner
rather than a search engine. **Do not change the ESI base on the strength of
this paragraph.**

Note also that ESI **eligibility** (₹21,000) is assessed on gross and is
separate from the contribution base, and Rule 50's contribution-period
continuation already works correctly in `domain/payroll/statutory.py`.

### Gratuity

Gratuity under the Payment of Gratuity Act is computed on "wages", so the same
redefinition reaches it. Not separately verified here. `[U]`

### What to do about it

**Not a formula tweak.** It needs, in order:

1. A **CA to confirm** the add-back applies as described for EPF, and to settle
   the ESI question above.
2. A per-employee **salary-structure input** the product does not currently
   hold: the split of total remuneration into wage and excluded components. The
   employee master has basic and DA; it does not have "what fraction of total
   remuneration is excluded", which is what the rule needs.
3. **Period-awareness**, since months before 21 Nov 2025 are computed on the old
   definition and must stay that way.

Until (1) and (2) exist, the honest behaviour is the one this codebase already
uses everywhere else: **compute what can be computed, and report the gap by
name** — the `statutory_gaps` shape in `routers/payroll.py`, so a CA sees which
employees have a structure where the add-back could bite rather than getting a
confident wrong number.

Tracked as task #121.

## 5. Verify before relying on any of this

1. **The 50% wage rule and the current state of Labour Code rules.** Highest
   priority — it changes computed deductions, not just paperwork.
2. The ESIC Excel template's current formatting rules, against a fresh download.
3. Whether the MCA V3 offline workbook can be populated programmatically.
4. The current MCA XBRL tool version and schema URLs.
5. Whether the ₹500 A/c-2 minimum survived the June 2018 rate cut.
6. Whether the Shram Suvidha unified EPFO/ESIC monthly return is live and usable
   — **the only place in this landscape where a "one file, two agencies" idea
   exists**, and worth a look. `[U]`
7. The MCA 15-day/7-day SRN windows, and who signs what.
8. Whether anything in the product still points at MCA V2 URLs.
