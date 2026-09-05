# Income tax and TDS — ERI, ITR, TRACES

Confidence grades and the sourcing caveat: see `00-how-to-read-this.md`.
**No primary source was read directly.**

---

## 0. Read this section first: the statutory ground HAS moved under the code

**VERIFIED 2026-09-04** by targeted search across many independent sources,
including adversarial searches looking for a deferral or rollback. No primary
document could be opened (see `00`), but the corroboration is broad, specific,
and internally consistent — notification number, rule number, section numbers,
due dates and transition rule all agree across unrelated sources.

**This is no longer an open question. It is a live gap in the product.**

### The instrument

**Income-tax Act, 2025** and **Income-tax Rules, 2026**, effective **1 April
2026**. The Rules were notified by **CBDT Notification No. 22/2026 dated
20 March 2026 (G.S.R. 198(E))**; a **corrigendum** was issued afterwards to
correct errors, so check the corrected text rather than the original. `[S]`

"Previous year / assessment year" becomes a single **"tax year"**.

### The statements — renumbered

| 1961 Act | 2025 Act | Prescribed under |
|---|---|---|
| 24Q (salary) | **138** | Rule 219; ss. 392 and 393(1) |
| 26Q (resident non-salary) | **140** | Rule 219; s. 397 |
| 27Q (non-resident) | **144** | s. 397(3)(b) |
| 27EQ (TCS) | **143** | |

### The certificates and statements — renumbered

| 1961 Act | 2025 Act | Note |
|---|---|---|
| Form 16 | **130** | now **three** parts (A/B/C), not two. **Still TRACES-generated and cannot be issued manually** |
| Form 16A | **131** | now issued **quarterly**, not annually |
| Form 26AS | **168** | annual tax credit statement, integrating AIS data |
| Form 15G + 15H | **121** | merged |

### ⭐ The section codes changed too — this was NOT in the first research pass

TDS provisions were scattered across ss. 192–196D and the whole 194-series. The
2025 Act consolidates them into a **compact, table-driven architecture under
ss. 392–402**: `[S]`

| 1961 Act | 2025 Act |
|---|---|
| s. 192 (salary) | **s. 392** |
| the 194-series (194A, 194C, 194H, 194I, 194J …) | **s. 393(1)**, one umbrella with a table |
| **s. 195** (payments to non-residents) | **s. 393(2)** |
| TCS (206C series) | **s. 394** |
| s. 139 (return of income) | **s. 263** |

TDS challans and returns now use **numeric payment codes 1001–1067**
corresponding to table entries in s. 393.

> ⚠️ **Correction to an earlier source.** One search result stated s. 195 moved
> to **s. 400**. Targeted follow-up shows that is **wrong**: s. 195 is now
> **s. 393(2)**, and **s. 400(2)** is the unrelated provision making CBDT
> circulars on DTAA application binding. This is exactly why the claims here are
> triangulated rather than taken from the first hit.

**Rates and thresholds are substantively UNCHANGED.** `[S]` So
`domain/tds/section_rates.py` still holds the right *numbers*; what has moved is
the *labels* — the section a payment is reported under.

### The transition rule — by EVENT, not by filing date

The Income Tax Department's own position: applicability depends on **the credit
or the payment, whichever is earlier**. `[P via summary]`

- that event **on or before 31 March 2026** → **1961 Act, old forms**
- that event **on or after 1 April 2026** → **2025 Act, new forms**

Commencement does not affect liabilities or obligations that arose under the
1961 Act for tax years beginning before 1 April 2026. So a **belated or revised
Q4 FY 2025-26 return is still Form 24Q** — the old forms stay correct for old
periods indefinitely, which is why the product needs **both** vocabularies, not
a migration from one to the other.

### ⚠️ The deadline has already passed

**Q1 TY 2026-27** (April–June 2026) was due **31 July 2026** on Forms 138 / 140 /
143 / 144. Today is September 2026.

And the failure is not cosmetic:

> **Filings submitted under the old form numbers for this period get rejected at
> validation.** Citing an old section code (194C rather than 393(1)) "may lead to
> processing errors" requiring a correction statement. `[S]`

**ITR forms are the exception and are NOT renumbered yet.** CBDT notified
ITR-1..7 for **AY 2026-27** on 30 March 2026 under the **1961 Act**, because
AY 2026-27 covers FY 2025-26. The 2025 Act reaches income-tax *returns* in 2027,
for tax year 2026-27. `[S]` So the ITR JSON schema work in
`domain/income_tax/` is unaffected this season.

**Due dates are unchanged** — 31 Jul / 31 Oct / 31 Jan / 31 May — matching
`compliance_engine.tds_return_due_date` and CLAUDE.md. `[S]`

### What this means for the code, concretely

**BUILT — `domain/tds/vocabulary.py`** (task #125). The shape is a period-aware
form and section vocabulary carrying **both sets permanently**, the same
discipline `compliance_engine` applies to due dates: derived from the period by
rule, never a stored constant.

**It is a fork, not a migration, and that is the whole design.** A belated or
revised FY 2025-26 statement filed today is still Form 24Q citing s. 192, and
there is no date after which that stops being true. Nothing was replaced.

What it resolves from the period:

| | 1961 Act | 2025 Act |
|---|---|---|
| statements | 24Q · 26Q · 27Q · 27EQ | 138 · 140 · 144 · 143 |
| certificates | 16 · 16A · 26AS · 15G/15H | 130 · 131 · 168 · 121 |
| sections | 192 · 194-series · 195 · 206C | 392 · **393(1)** · 393(2) · 394 |

`act_for_date` is the definition — the transition is by **event**, credit or
payment whichever is earlier — and `act_for_fy` is derived from it. The two
agree because commencement falls on 1 April 2026, which is exactly an FY
boundary, so no return straddles it. That is stated in the module rather than
relied on silently.

Three things it **refuses** rather than guessing:

- **The s. 393 payment-code table (1001–1067) is not held.** Sixty-seven guessed
  codes would be sixty-seven wrong labels, and a wrong payment code is
  *accepted* and then wrong — worse than a rejection, because nothing tells the
  CA. `payment_code_gap()` names it, and it rides on the 24Q/138 working paper
  so a complete-looking file says which column is missing. **This is a human
  step**, like the ITR schemas and the state PT slabs.
- **s. 393(1) has no reverse.** The whole 194-series collapsed into it, so
  asking which of 194C, 194J or 194H a line was means inventing one.
- **A form cannot be asked for without a period.** Defaulting to today would
  file a belated FY 2025-26 statement on Form 138 — the exact bug.

Two changes the wiring forced, both about *stored* data meeting the fork:

- **`domain/payroll/form24q.py` now requires `financial_year`** and emits the
  period's section. Twelve existing tests failed on the missing argument, and
  one was asserting `section == "192"` on FY 2026-27 fixtures — it had been
  pinning the bug.
- **Challan matching accepts BOTH section labels, in every period.** A challan
  records a deposit somebody typed in, and which label they used depends on when
  they typed it, not on which Act governs the quarter. Filtering on one name
  drops the deposit and raises "no challan recorded" against a quarter that was
  paid on time.

**`domain/tds/section_rates.py` is deliberately NOT rekeyed.** The rates are
unchanged and the 1961-Act keys stay; translation happens at the boundary where
a statement is emitted. A test pins that, so a later rekeying is a decision
rather than a tidy-up.

**ITR is untouched**, as above — AY 2026-27 is still the 1961 Act, and a test
pins that too.

---

## 1. ERI — the route to filing ITRs

### What it is

The **Electronic Furnishing of Return of Income Scheme, 2007**, notified by
**Notification 210/2007 dated 27 July 2007** under **s.139(1B) and s.139D** read
with **Rule 12(3)**. `[P]`

⚠️ **Whether the scheme survives the 2025 Act unchanged, and what the s.139(1B)
equivalent is, could not be established.** `[U]` s.139 generally maps to s.263,
but no source addresses the ERI enabling power. **The whole ERI route rests on
this.**

### The three types — and a stale framing to ignore

Per the **official portal** `[P]`:

- **Type 1** — files using the **ITD's own or ITD-approved utilities** on the
  portal. Gets bulk ITR upload/view. A human uploads JSON.
- **Type 2** — builds **its own software** and files **through ITD APIs**, with
  its own ERI User ID and password. **This is the target.**
- **Type 3** — builds its own **offline utility** for users. No portal client
  management.

⚠️ ClearTax, Tax2win, BankBazaar and IndiaFilings all describe Type 1/Type 2
differently — as an infrastructure-certification distinction. That reads like the
**pre-2021 NSDL-era** classification. **Where they disagree with the portal, the
portal wins.** `[S, stale]`

### Eligibility

Eligible classes include a **company incorporated in India with net worth ≥ ₹1
crore**, and separately **a firm of chartered accountants** or an individual CA.
`[S]`

> If PracticeSync's operating entity is a private limited company, **net worth ≥
> ₹1 crore is the gate** — unless the application goes through a CA firm, which
> is a genuinely different structuring option worth considering early.

### What ERI status permits, and the consent model

File ITRs and statutory forms for added clients (PAN and TAN); **add clients**
with taxpayer consent; **download pre-filled data** (consent-based). `[P]`

**The consent model is the most product-relevant fact here** `[P]`:

- The taxpayer grants a validity period: **minimum 7 days, maximum 1 year**,
  never exceeding the ERI's own registration validity.
- An ERI can extend a client's validity by **up to 6 months**.
- **Every service request must be verified by the taxpayer within 7 days** of the
  Transaction ID being generated, or it lapses.

> This is structurally identical to the Account Aggregator consent shape in
> `05-bank-data-and-the-account-aggregator.md`: time-bound, client-granted,
> expiring, revocable. **A "CA acts alone" screen will not work.** Consent state,
> expiry, renewal prompts and a 7-day pending-verification queue are first-class
> model objects — and the ITD and AA versions should share one design.

**A lighter alternative worth knowing about:** a taxpayer can add a **CA** by
ICAI membership number to file **statutory forms** and e-verify assigned forms.
That is a different portal role, needs **no registration by the software vendor
at all**, and does **not** cover filing the ITR itself. `[P]`

### The APIs

No public developer portal, no open sandbox, no self-serve keys. What exists is a
**static page of PDF specifications** at
`incometax.gov.in/iec/foportal/api-specifications`: Login, Add Client, Prefill,
Submit Flow, e-Verify Return, ITR-V. REST over HTTPS, JSON. `[P]`

⚠️ **Every file on that page is dated October/November 2021.** Given the 2025
Act, TRACES 2.0 and the renumbering all landed in 2026, a frozen-since-2021 spec
is implausible. **Assume a newer spec exists behind an ERI login and do not plan
against the 2021 PDFs.** `[U]`

**Not confirmed as available by API** `[U]`: AIS/TIS download, Form 26AS,
challan/e-Pay Tax, Form 10E, Form 10-IEA, ITR-U, rectification, refund status.
A vendor page claiming ERIs get "instant pre-fill of AIS, 26AS, Form 16" is
**marketing copy**; what is confirmed is the **Prefill** API, which is not the
same thing.

### ⚠️ The constraint that hits this deployment specifically

From the **External Agency** registration manual `[P, but a different registration
category — verify it applies to ERIs verbatim]` `[U]`:

- UAT source IPs emailed to ITD; ITD issues test credentials and test scenarios.
- Final UAT test report emailed back for **competent-authority approval**.
- **TLS 1.2 minimum.**
- **Production access granted by whitelisting a maximum of 4 Indian static IPs.**
- The ERI shares its **DSC public key** with ITD for signature validation.

> **`apps/api` runs on Render in Singapore**, deliberately, to sit near the
> Mumbai Supabase (`render.yaml` carries the measurements). Render is not in
> India and does not offer static egress IPs on all plans. Satisfying a 4-IP
> Indian whitelist needs an **India-hosted static-IP egress hop** that the
> filing calls route through. That is a **deployment change, not a code change**,
> and it is its own line item.

### Buying instead of building

**Sandbox (by Quicko)** resells ERI API access — you integrate with them, they
hold the ERI registration. Real endpoint shape `[S]`:

```
GET https://api.sandbox.co.in/itd/eri/tax-payers/:pan/itrs/:assessment_year/itr-v
```

> **The trade-off, stated plainly:** this sidesteps registration, net worth,
> ISA/CISA certification, UAT and the 4-IP whitelist — but **the client's consent
> is granted to the aggregator's ERI, not to PracticeSync.** That is a material
> thing to have to tell a CA firm about their clients' data, and it puts a third
> party between the product and a statutory filing.

### Costs — both published figures look frozen

| Figure | Assessment |
|---|---|
| **₹4,600** to "NSDL - ERI" by cheque/DD | ₹4,000 + **15% service tax** — the 2015–17 rate, superseded by GST in 2017. Probably a 2016-era number `[S]` |
| **₹27,245** = ₹25,000 refundable deposit + ₹2,245 "inclusive of service tax currently 12.24%" | 12.24% dates to ~2007-08. Almost certainly never updated `[P, stale]` |

**Do not put either in a plan.** Write "₹5k–₹30k order of magnitude, confirm with
Protean". Registration is reportedly valid **two years**, renewed from 1 April.

**Timelines: no published SLA and no practitioner account found.** `[U]` But the
Type-2 path has **at least four serial, email-driven, manually-reviewed gates** —
application + documents, ISA/CISA due-diligence certificate, ITD UAT
certification, production IP whitelisting. **Plan in quarters, not weeks**, and
say so rather than inventing a figure.

⚠️ One claim to **not** carry forward: that ERI registration requires ISO 27001
or a third-party penetration test. That came from a low-quality aggregator and
reads as paraphrase. The concrete, repeatedly-cited requirement is the
**ISA/CISA due-diligence certificate**. `[U]`

## 2. Verification — the taxpayer signs, and no one can do it for them

**s.140** `[P]`: an **individual verifies personally**; an HUF's **karta**; a
company's **managing director**. A power-of-attorney holder only where the
individual is absent from India or incapacitated, with the PoA attached.

Methods: DSC (Class 3 token + emsigner; **mandatory for companies and audit
cases**), Aadhaar OTP, EVC via pre-validated bank or demat account, net banking,
bank ATM, or physical ITR-V posted to CPC Bengaluru. `[P]`

**The 30-day window.** Notification 5/2022 (DGIT Systems) dated 29 July 2022,
effective 1 August 2022, cut verification from 120 days to **30 days**. **An
unverified return is treated as not filed.** `[P/S]`

**Can an ERI or CA verify for the taxpayer? No** — stated flatly on the official
pages: *"Any request submitted by ERI on your behalf will not be completed if it
is not verified by you."* `[P]` The one exception is a registered **Authorized
Signatory or Representative Assessee**, which is a different role from ERI.

> **Model it as a pending-verification queue with a 30-day clock and a separate
> 7-day ERI-service-request clock, with reminders.** And build nothing that
> captures a client's Aadhaar OTP or portal password — the same reasoning that
> rules out net-banking screen-scraping in CLAUDE.md applies here exactly.

## 3. ITR JSON schemas — confirming what CLAUDE.md already says

Published under Downloads → Income Tax Returns: JSON schema, validation rules,
a **schema change document** per version, and offline utilities. `[P]`

**Versioning within an assessment year is real and frequent** `[P]` — ITR-1
AY 2025-26 went V1.0 (30 May 2025) → V1.1 (30 Jul) → V1.2 (1 Jan 2026); ITR-3 and
ITR-6 reached V1.3.

**Is there a programmatic route? Half.** The files are static assets on
predictable-ish paths fetchable without login — but **there is no index, no API,
no feed, and no stable naming convention.** The directory segment is the release
year-month, the filename embeds a version, and naming is inconsistent
(`ITR-7_2026_Main_V0.1.json` vs `ITR 4_Schema change document_AY2026-27_V1.1_0.pdf`,
note the trailing `_0`). **You cannot construct next year's URL.**

> So CLAUDE.md §2 is correct and stays: **a human downloads them.**
>
> One refinement worth adopting: also pull the **schema change document** per
> version. It is the closest thing to a changelog, and it is exactly the artefact
> the field-path tests need — it would have caught the
> `TaxPayableOnDeemedTI` / `TaxPayableOnTI` mistake CLAUDE.md records.

## 4. TDS returns — the messier half

### How it works today

1. **Prepare** in the **RPU** — a free Java desktop app from Protean/TIN.
2. **Validate** with the **FVU** (`TDS_FVU_STANDALONE.jar`), which emits a
   **`.fvu` file**: the deductor's flat text statement checked against the
   prescribed format and wrapped as the canonical upload payload. Not a
   signature, not an acknowledgement — a validated payload.
3. **Submit** at a TIN-FC physically with a signed Form 27A, or online at the
   e-filing portal under the **TAN login**, signed with DSC or EVC.
4. Receive a **15-digit token / provisional receipt**.

`[P/S]` Under the new regime, physical filing is reportedly gone — electronic
only — but the preparation path is unchanged: still RPU, still FVU, then upload.

### Are the utilities usable programmatically?

- **RPU: no, and you don't need it.** It is a GUI. What matters is the **TIN file
  format specification** for the flat text statement; every commercial vendor
  generates that directly and skips the RPU. ⚠️ **Whether that spec is publicly
  published for third parties could not be confirmed** `[U]` — and it is the
  load-bearing dependency for building TDS return generation.
- **FVU: yes, weakly.** It is a `.jar` invocable from a shell, so it can be
  wrapped server-side in a JVM container. ⚠️ **Whether Protean's licence permits
  hosting the FVU inside a multi-tenant SaaS could not be confirmed** `[U]`. Get
  that in writing — it is the kind of thing that is fine for a desktop product
  and not obviously fine for a hosted one.

### ⚠️ The highest-value lead in this whole document

Search results describe a **CPC-TDS developer portal** offering *"OpenAPI 3.0
based TDS Statement Filing APIs for Forms 24Q, 26Q, 27Q and 27EQ, covering data
capture, validate, submit as well submit status and error download"*, with a
sandbox, organisation registration, and a help section listing **"TSP Test
Certify"**.

Found only at **`test-dev.tdscpc.gov.in`**. `[U]`

Three reasons to flag rather than assert: the host is literally `test-dev`, a
development environment; **no production URL was found**; and **"TSP Test
Certify" implies a TDS Suvidha Provider empanelment scheme** analogous to the GST
GSP gate — for which **no announcement, criteria or scheme could be found at
all**.

> **Verify this first.** If a production CPC-TDS API with a TSP scheme exists, it
> turns the TDS half from "generate a file, a human uploads it" into "integrate
> an API, subject to empanelment" — and it would be the first real filing API on
> the direct-tax side.

## 5. TRACES, and why Form 16 cannot be self-generated

TRACES is the **deductor-side** system: Form 16/16A generation, Form 26AS, conso
files (needed to prepare a correction statement), justification reports, default
notices, challan status, Form 13.

**Both parts of Form 16 must come from TRACES. This is settled law.** `[P]`

- **Part A** — **CBDT Circular 04/2013 dated 17 April 2013**: mandatory to
  generate and download Part A (and Form 16A) **only from TRACES**, for sums
  deducted on or after 1 April 2012. Certificates issued in any other format —
  **even with accurate data — are invalid**.
- **Part B** — **CBDT (Systems) Notification 09/2019 dated 6 May 2019**: Part B
  must also come from TRACES, for deductions on or after 1 April 2018. To get it
  right, **the deductor must report correct data in Annexure II of Form 24Q**.

> **The codebase already gets this right, and it is worth pointing at.**
> `routers/payroll.py:4050` says: *"THERE IS NO FORM 16 GENERATOR HERE, AND THERE
> SHOULD NOT BE."* The product's job is to compute the numbers, get **Annexure
> II** exactly right so TRACES generates a correct Part B, and then fetch and
> distribute the TRACES-issued PDF. Any Form 16 the product renders itself is a
> working document and must be labelled as one — the same discipline as the
> `SPECIMEN` labelling in `services/filing_demo/`.

**Does TRACES have an API? Historically no** — which is why every TDS vendor
advertising "direct TRACES integration" is in fact driving the web UI behind a
captcha. The only evidence otherwise is the unconfirmed dev host above.

## 6. Verify before relying on any of this

1. **Whether the 2025 Act renumbering is real and what it does to §0.** Highest
   priority. Task #125.
2. **Whether the CPC-TDS OpenAPI portal and a TSP scheme exist in production.**
3. Whether the ERI scheme survives the 2025 Act, and the s.139(1B) equivalent.
4. Whether the ITD API spec has been updated since November 2021.
5. Whether the UAT / 4-IP / TLS-1.2 process applies to ERIs verbatim.
6. Whether ERIs get AIS/TIS/26AS by API at all.
7. Whether the TIN e-TDS file format spec is publicly published.
8. Whether Protean's licence permits hosting the FVU in a SaaS.
9. Current ERI fees and the approval SLA; whether registration is open.
