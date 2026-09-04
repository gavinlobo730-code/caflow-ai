# Income tax and TDS — ERI, ITR, TRACES

Confidence grades and the sourcing caveat: see `00-how-to-read-this.md`.
**No primary source was read directly.**

---

## 0. Read this section first: the statutory ground may have moved under the code

⚠️ **This is the largest single finding in this document and it is NOT verified.**
It post-dates the assistant knowledge cutoff and rests entirely on secondary
sources, though corroboration across independent ones is strong. `[S]`

Research indicates the **Income-tax Act, 2025 came into force 1 April 2026**,
with new **Income-tax Rules, 2026**. "Previous year / assessment year" becomes a
single **"tax year"**, and the forms are renumbered:

| 1961 Act | 2025 Act |
|---|---|
| 24Q (salary TDS statement) | **138** |
| 26Q (resident non-salary) | **140** |
| 27Q (non-resident) | **144** |
| 27EQ (TCS) | **143** |
| Form 16 | **130** |
| Form 16A | **131** |
| Form 16B | **132** |
| Form 27D | **133** |
| Form 26AS | **168** |
| Form 15G + 15H | merged into **121** |
| 3CA / 3CB / 3CD (tax audit) | consolidated into **26** |
| s.139 (return of income) | **s.263** |

**The transition is by PERIOD, not by filing date.** FY 2025-26 (AY 2026-27) is
governed entirely by the 1961 Act — returns filed during 2026 still use ITR-1..7,
Form 16 and Form 26AS, and Q4 FY 2025-26 TDS is still 24Q/26Q. The new numbering
starts with income from **1 April 2026**.

**Today is September 2026.** On that reading, Q1 TY 2026-27 (quarter ended 30
June 2026, due 31 July 2026) should already have been filed on Form 138/140 —
a deadline that has passed.

**What this means for the code.** 25 files under `apps/api` carry `24Q`/`26Q`/`27Q`
vocabulary — `domain/payroll/form24q.py`, `annexure2.py`, the whole of
`domain/tds/`, `services/tds_return_service.py`,
`services/filing_demo/tds_return.py`, `routers/payroll.py` and more. **Nothing in
the codebase mentions the 2025 Act, "tax year", or any new form number.**

If confirmed, this needs **period-aware form vocabulary carrying both sets for
several years** — bigger and more certain work than any filing integration, and
due whether or not ERI registration ever happens. It is the same shape
`compliance_engine` already uses for due dates: derive from the period by rule,
never a constant.

One reassurance: **TDS due dates appear unchanged** (31 Jul / 31 Oct / 31 Jan /
31 May), which matches `compliance_engine.tds_return_due_date` and CLAUDE.md.

**Also reported:** TRACES was replaced by **TRACES 2.0** on 1 April 2026 at
`traces.tdscpc.gov.in`; login is PAN + password + captcha with no separate User
ID, and legacy functions sit under a "Compliance under Income-tax Act, 1961"
section. `[S]`

> **Verify against the bare Act and the CBDT notifications before changing one
> line.** This is precisely the kind of confidently-wrong regulatory fact the
> codebase already refuses to act on from memory. Tracked as task #125.

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
