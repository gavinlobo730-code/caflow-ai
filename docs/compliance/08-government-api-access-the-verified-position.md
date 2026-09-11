# Government API access — the verified position

**11 September 2026.** Consolidates `07-getting-permission-to-file.md` with the
external research baseline supplied by the owner
(*CAFLOW — Government API & Compliance Integration Roadmap*, 11 September 2026),
cross-checks both, and answers the four questions that decide whether this
product can file: **who may apply, what it costs, what it unblocks, and where a
human is legally unavoidable.**

Read §0 before anything else. It governs how much weight every other line here
can carry.

---

## 0. What I could and could not verify, and why it changes the reading

**I did not open a single official page.** This environment's egress is refused
at the proxy. Tested again while writing this:

```
WebFetch https://www.incometax.gov.in/iec/foportal/help/eri/registration
    → EGRESS_BLOCKED
WebFetch https://test-dev.tdscpc.gov.in/about
    → EGRESS_BLOCKED
```

`WebSearch` works, because it runs server-side and returns *somebody else's
summary* of a page I cannot open. So the shape of the evidence throughout is:
*a search engine has read `gstn.org.in/.../eligibility-batch-5.pdf` and told me
its title and a sentence from it; I have not read a line of it.*

| Grade | Means |
|---|---|
| `[P]` | I opened the primary source and read it |
| `[S-gov]` | a search engine summarised a document at an **official** URL, and the URL is recorded in §8 |
| `[S]` | trade press, a vendor's documentation, or a professional firm's note |
| `[U]` | wanted and not found, or sources contradict each other |

**No `[P]` is awarded anywhere in this document.** That is not a formality. The
owner's instruction was *"use official sources and current 2026 requirements…
if something can't be conclusively confirmed, mark it as such instead of filling
the gap with assumptions"*, and the honest report against that instruction is
that **conclusive confirmation was not available to me for any item**. What
follows is the best available reconstruction, graded, with the gaps named.

**The same caveat applies to the uploaded research, and I cannot tell how
strongly.** It ends with a register of fifteen official URLs. A URL list is
evidence that the URLs were *found*; it is not evidence that the pages were
*read*, and I have no way to distinguish the two from the document alone. Where
it states a figure my own searches could not surface — the GSP batch-5 turnover
threshold is the main one — I have marked it as its claim rather than adopting
it as fact. That is not a criticism of it; it is the same discipline I am
applying to myself.

### One structural note on money

Every cost figure in this document is stale on its face, absent from public
sources, or single-sourced. **The document is reliable about which door to knock
on and whose signature is required. It is weak about what anything costs.**
Those are different qualities of claim and are marked differently throughout.

---

## 1. The classification you asked for

You asked for four buckets. Here they are, and the assignment is the whole
answer:

| Bucket | Means | What is in it |
|---|---|---|
| **Direct API access** | We can obtain credentials ourselves, on our own application, without a commercial counterparty | **e-invoice IRN** (NIC/IRP, ERP category) · **e-way bill** (same NIC family) · **`SW########` software id** · **DigiLocker** (via API Setu) |
| **Approval-based access** | An application to a government body that can be refused, with documents, scrutiny and a waiting period | **ITR — ERI Type 2** · **Protean PAN verification** (eligibility bar we probably fail) · **CPC-TDS developer portal** `[U]` — may or may not exist in production |
| **Partner-based access** | No route exists for us directly; we ride a licensed third party's credential | **GST returns** (GSTR-1/3B/9) — as an **ASP** under an existing **GSP** |
| **No confirmed public API** | Nothing to apply for, nobody to buy from, no programme to join | **MCA** · **EPFO** · **ESIC** · **professional tax (all states)** · **TDS statement submission** (today) · **Udyam** · **Shram Suvidha** · **Account Aggregator** (closed by decision, see §5.5) |

**But the bucket is not the binding constraint, and this is the single most
important correction to the uploaded research.** A separate axis decides whether
filing is achievable *at all*:

---

## 2. The three kinds of blocker — and only one is buyable

| Blocker | Removed by | Affects |
|---|---|---|
| **A licence or empanelment** | money and time | GST returns, ITR transmission |
| **A signature the law assigns to a named human** | **nothing** | ITR (s.140), GST returns (Rule 26), every MCA form (director's DSC), TDS statements (deductor's DSC/EVC) |
| **No channel at all** | nothing | MCA, EPFO, ESIC, professional tax |

**The second row is the one most often mistaken for the first**, and the
uploaded research makes exactly that mistake: it calls Type-2 ERI *"the clearest
direct-API route"* and lists e-Verify as a step in the flow, without recording
that **verification cannot be delegated to us at any price.** The Income Tax
Department states it flatly: *"Any request submitted by ERI on your behalf will
not be completed if it is not verified by you."* `[S]`

So the achievable product for ITR is **"we prepare, we transmit, they verify, we
record what happened"** — and no amount of ERI registration changes that. A
roadmap that promises "file directly with the government" for ITR is promising
something the Income-tax Act does not permit.

### The two rows that are genuinely complete

**e-invoice IRN and e-way bill are the only statutory outputs software can
complete end to end**, because they are machine-facing by design and carry **no
taxpayer signature** — the IRP digitally signs the IRN itself.

That is the strategic finding of this whole document, and the uploaded research
does not contain it: it lists e-invoice and e-way bill as P0 alongside ITR, GST,
MCA, EPFO and ESIC, as though they were the same kind of thing. They are not.
**They are the only two where "PracticeSync filed it" is a true sentence.**

---

## 3. The uploaded research — what it got right, wrong, and missed

### 3.1 Right, and genuinely additive

| | |
|---|---|
| **The executive shape** | "No single government API credential unlocks all CA compliance; each ecosystem needs its own strategy" is correct and well put |
| **GSP batch-5 specifics** | Organisation forms, ≥ ₹50 lakh average turnover over three FYs with MSME relaxation, 70% overall / 60% per section technical scoring, ≥ 1 lakh transactions per month, India-based backend, a working GSP demonstration covering GSTR-1, e-invoice JSON/IRN, reconciliation, multi-GSTIN and DSC. **Our own four differently-phrased searches failed to surface the ₹50 lakh figure from any source.** If that came from the PDF, it closes a `[U]` we have carried since the first research pass — which is a real contribution |
| **IRIS IRP (`einvoice6`)** | Our prior work concentrated on NIC's `einvoice1`/`einvoice2`. The IRIS IRP developer documentation and its separate **API-integrator / solution-provider** path is a door we had not examined |
| **e-way bill onboarding mechanics** | Client ID / client secret issued by the system, plus taxpayer GSTIN and API username/password; shortlisting, pre-production credentials, testing, IP whitelisting, then the production API login. Consistent with what we had and better detailed |
| **"No credential scraping"** | Correct, and it matches this repo's standing rule against net-banking screen-scraping |
| **The architecture section** | The consent & authorisation service, credential vault, connector layer, submission state machine and immutable audit trail are all right, and §12's identity hierarchy matches what the codebase already does |

### 3.2 Wrong, or unsupported by the sources I could reach

| # | The claim | What I found |
|---|---|---|
| 1 | *"For Type-2/Type-3 ERI, upload the undertaking, bank guarantee and audit report"* | Sources consistently attach the **bank guarantee to Type 1**, not Type 2. `[S]` Type 1 is the category with *"ITD approved computing infrastructure and a due diligence certificate from a certified ISA/CISA professional"*. **This matters commercially** — it is the difference between a bank guarantee being a cost of our chosen route or not. `[U]` on the amount either way |
| 2 | *"Maharashtra… portal notice says PT registration and return-filing facilities are temporarily disabled"* | The sourced 2026 position is a **trade circular of 13 March 2026 granting temporary relaxation** because of portal issues — PTRC payment by 15 March, PTEC by 31 March, delayed registration permitted **to 30 April 2026**, and payment by PAN where registration could not complete. `[S]` That is a transient relief measure, not a standing disablement. Designing around "the portal is disabled" would be designing around a circular that has expired |
| 3 | **MCA, EPFO and ESIC marked "P0"** in the action plan | A category error. There is **nothing to apply for** in any of the three — no registration, no empanelment, no partner, no purchasable route. They cannot be a P0 *action* because there is no action. They are a P0 *design constraint*: build the file, let a human upload it |
| 4 | *Type-2 ERI is "the clearest direct-API route"* | True about the API and misleading about the outcome. See §2 — s.140 verification is not delegable, so the ERI route transmits and never completes |
| 5 | The **ERI registration flow** as described | Broadly matches what we have, but the document says *"Register/validate the PAN or TAN"* and separately references NSDL registration. The current flow appears to be **on the e-filing portal itself** (Register → Others → e-Return Intermediary), not a cheque to NSDL. `[S-gov]` Sources disagree; ours is the more recent reading. `[U]` |

### 3.3 Missing, and each of these changes the plan

| # | What is absent | Why it matters |
|---|---|---|
| 1 | **The `SW########` software-provider id**, and the e-filing portal's **"Third Party Software Utility Developer"** user category, which has its own official user manual `[S-gov]` | Every ITR JSON carries `SWCreatedBy`; **a return without an approved software id is rejected** `[S]`. This is plausibly a self-service portal registration with no net-worth bar — **the cheapest unblock in the entire document**, and the uploaded research does not mention it |
| 2 | **ERI Type 3** — *"entities that develop offline utility… pure software providers who do not themselves act on behalf of taxpayers"* `[S]` | A third structural option the document does not consider. It may be the honest description of a CA-practice platform where the **CA** files and we supply the software. Worth confirming before choosing Type 2 by default |
| 3 | **s.140 / Rule 26 signature analysis** | See §2. The difference between a licence problem and a legal-impossibility problem |
| 4 | **DigiLocker via API Setu**, and **Protean PAN verification** | Two real, documented, non-filing integrations that improve a CA platform materially. §5 |
| 5 | **The Account Aggregator decision is already made and closed** | The uploaded document does not mention AA. This repo investigated it to a conclusion — no FIU licence exists to apply for, and no published purpose code covers bookkeeping. **Route 3 (do not consume via AA) was chosen on 6 September 2026.** Nothing here reopens it. See `05-bank-data-and-the-account-aggregator.md` |
| 6 | **A live 2026 statutory change**: Maharashtra notification of **28 February 2026 amending Rule 11(3)** moved PT due dates **from month-end to the 15th** `[S]` | Checked against the code: we hold **no PT due dates at all**, so nothing is currently wrong. Recorded so that whoever adds them does not add the old ones |

---

## 4. Filing by filing — the full chain

Each subsection runs the chain you asked for: **eligibility → documents →
registration → approval → fees → credentials → sandbox → production → client
onboarding → filing → acknowledgement.** Where a link in that chain does not
exist, it says so rather than inventing one.

### 4.1 GST returns — GSTR-1, GSTR-3B, GSTR-9, GSTR-9C · **PARTNER-BASED**

| Link | Position | Grade |
|---|---|---|
| **Eligibility (GSP)** | Indian company in IT/ITeS/BFSI; backend infrastructure in India; ≥ 1 lakh GST transactions/month capacity; three years audited accounts; data privacy policy; IT Act compliance; **affidavit that GST-System data will not be used to sell financial products**. Turnover bar has fallen across batches — batch 1 ₹10 cr / batch 2 ₹5 cr / **batch 5 claimed ₹50 lakh** | `[S]`, batch-5 figure per uploaded research only |
| **Eligibility (ASP)** | **None.** No empanelment, no net worth, no application window | `[S]` |
| **Documents (GSP)** | Incorporation/partnership docs, audited financials, GST registration, PAN, MSME certificate where applicable | `[S]` |
| **Registration** | GSP: GSTN empanelment batch + technical evaluation (**≥ 70% overall, ≥ 60% per section**) + signed GSTN contract. ASP: **a commercial contract with an existing GSP** | `[S]` |
| **Approval** | GSP: batch-based, and **no open batch was found. Two independent sources state GSTN has stopped accepting new GSP registrations.** No batch 6 found | `[S]` / `[U]` |
| **Fees** | **No public price list at any tier.** GSP licence fee **not found** `[U]`. GSP→ASP per-call pricing quoted at 10 paise–₹1, single undated source — and one GSTR-1 filing is many calls | `[U]` |
| **Credentials** | GSP licence key, or an ASP client-id/secret **sub-licensed from the GSP** | `[S]` |
| **Sandbox** | Specifications public at `developer.gst.gov.in/apiportal/`; production credentials only under signed contract | `[S]` |
| **Production** | Via the GSP's connectivity arrangements | `[S]` |
| **Client onboarding** | **Per-GSTIN, client-owned, expiring, revocable.** GST portal → My Profile → **Manage API Access** → Yes, duration **6 hours to 30 days**, granted by OTP. Since **29 Sep 2025** every consent emails and SMSes the authorised signatory **naming the ASP**, and the taxpayer has a dashboard with a revoke button | `[S-gov]` |
| **Filing** | Transmit via API. **The signature is the client's** — Rule 26 requires **DSC** for a company and (per every 2026 source seen) an **LLP**; proprietorships, partnerships and HUFs may use EVC | `[S]` |
| **Acknowledgement** | ARN returned by GSTN. The codebase already has the row for it — `services/gst_filing_record_service.py` | — |

> **The decision:** a startup does not qualify as a GSP and applications appear
> closed. **The route is ASP under an existing GSP.** Choose the counterparty
> carefully — ClearTax, IRIS, Cygnet and Masters India are all GSPs *and* sell
> practice-management products that compete with this one. Read the data clauses.

**What the ASP contract also buys**, which is easy to miss: GSTIN verification,
taxpayer status and **return filing-status** APIs come through the same licence.
There is no free public endpoint for them. `[S]` That is genuinely useful to a CA
platform beyond filing.

**Code seams.** `domain/gst/portal_service.py` (the `GSTPortalProvider`
abstraction — and note `get_provider()` currently takes a name and **ignores
it**; fix before a real provider exists), `domain/gst/gstr1_builder.py` (targets
API spec v1.3 of July 2023, likely stale), `services/gst_filing_record_service.py`.

### 4.2 e-invoice IRN · **DIRECT API — and completable**

| Link | Position | Grade |
|---|---|---|
| **Eligibility** | NIC issues credentials to **"GSPs, ERPs and ECOs"** — there is an **ERP** category and we plausibly fit it. No net-worth or turnover bar found *for the ERP category* | `[S]` / `[U]` |
| **Registration (sandbox)** | `https://einv-apisandbox.nic.in/` — **self-service, free, any GSTIN, no empanelment, no IP whitelisting** | `[S]` |
| **Documents** | None for sandbox | `[S]` |
| **Approval (production)** | Test every API in pre-production with minimum success and failure cases → file a **Test Summary Report** → email `support.einv.api@gov.in` → submit **up to four static IPs** for whitelisting. One source: 4–5 days | `[S]` |
| **Fees** | Sandbox free. Production: **no fee found for the ERP route** `[U]`. The real cost is the India static-IP hop (§6) | `[U]` |
| **Credentials** | Client Id + Client Secret — **ours**. The GSTIN and the taxpayer's e-invoice portal credentials are the **client's** | `[S]` |
| **Sandbox → production** | Testing must interface the APIs with a taxpayer's **actual** ERP/accounting application, not NIC's online test tool | `[S]` |
| **Client onboarding** | Taxpayer authorises the solution provider for API access to the GSTIN | `[S]` |
| **Filing** | **No taxpayer signature. The IRP signs the IRN.** This is why this row completes | `[S]` |
| **Acknowledgement** | Signed IRN + QR returned synchronously | `[S]` |

**Two live constraints to build against:** TLS 1.2 minimum and GoI IT security
standards `[S]`; the **30-day IRN reporting limit for AATO ≥ ₹10 crore**, which
reaches credit and debit notes; and an advisory of 17 June 2026 making
**Ship-to GSTIN mandatory** in the IRN and e-Way-Bill-by-IRN APIs **from
1 August 2026** `[S-gov]`. Anyone writing the payload needs that last one first.

**Code seam.** `routers/einvoice.py` — today `POST /records/{id}/irn-generated`
*records* an IRN a human obtained. A real integration is a **new endpoint beside
it**, not a repointing of that one.

### 4.3 e-way bill · **DIRECT API — and completable**

Same NIC family, own developer portal at `https://docs.ewaybillgst.gov.in/apidocs/`
`[S-gov]`. Authentication by client ID/secret plus the taxpayer's GSTIN and API
username/password `[S]`. Onboarding: shortlisting → pre-production credentials →
testing → IP whitelisting → production API login `[S]`.

> **The constraint to plan around:** the taxpayer logs in to the EWB system,
> chooses **Registration → For GSP**, and **selects a GSP from a dropdown**. If
> our name is not in NIC's list, the client cannot select us — so in practice
> this runs under whichever GSP we contract with, **and the client sees that
> name.** The same is true of the GST consent dashboard. Plan the client
> conversation around it; do not discover it at onboarding. `[S]`

Turnover tiers `[S]`: ≥ ₹500 crore have both direct API and GSP routes;
₹100–500 crore have the GSP route only.

**Code seam.** `routers/eway_bill.py`, same record-only shape.

### 4.4 ITR · **APPROVAL-BASED — transmits, never completes**

| Link | Position | Grade |
|---|---|---|
| **Eligibility** | A company with **net worth ≥ ₹1 crore**, **or** a firm of Chartered Accountants, Advocates or Company Secretaries with a valid PAN | `[S]` |
| **Documents** | **Due-diligence certificate from a licensed CISA or ISA professional** `[S]`. Bank guarantee: attached to **Type 1** in the sources I reached, contrary to the uploaded research | `[S]` / `[U]` |
| **Registration** | On the e-filing portal: Register → **Others** → **e-Return Intermediary** → Register as New Applicant → choose ERI type → PAN/TAN → OTP | `[S-gov]` |
| **Approval** | Departmental. **No published SLA, no practitioner account found.** At least three serial manually-reviewed gates. **Plan in quarters** | `[U]` |
| **Fees** | **Both published figures are stale on their face.** ₹27,245 = ₹25,000 refundable deposit + ₹2,245 "inclusive of service tax currently 12.24%" — a 2007-08 rate. A separate ₹4,600 = ₹4,000 + 15% service tax, 2015-17. Service tax ended in 2017. **Write "₹5k–₹30k order of magnitude, confirm on the portal"** | `[S]`, stale |
| **Validity** | **Two years**, renewed with effect from 1 April | `[S]` |
| **Credentials** | ERI credentials — **ours** (or the CA firm's). Type-2 ERIs create sessions with their own ERI credentials | `[S-gov]` |
| **Sandbox** | **None public.** No developer portal. Specifications are a static page of PDFs, **every one dated November 2021** — assume a newer spec exists behind an ERI login | `[S-gov]` |
| **Client onboarding** | Add Client, then **consent-based prefill**: we submit the request, **the OTP goes to the taxpayer's registered mobile**, data arrives only after they enter it. The taxpayer never shares a portal password with us — that is the design, and should be the product's | `[S-gov]` |
| **Filing** | Transmit by API. **Verification is the taxpayer's and cannot be delegated (s.140)** | `[S]` |
| **Acknowledgement** | ITR-V / acknowledgement number — but **the return is not filed until e-verified** | `[S]` |

**Three client-owned clocks the product must model** `[S]`: ERI client validity
**7 days to 1 year** (extendable by 6 months); every ERI service request must be
verified **within 7 days** or it lapses; an ITR must be e-verified **within 30
days** of filing or it is treated as not filed.

> **The structuring decision, and it must be made before anyone applies.** If the
> operating company does not clear ₹1 crore net worth, the CA-firm route is open
> — but **the ERI registration, the client consents and the statutory
> obligations then belong to that firm, not to the product company.** Every
> taxpayer's return goes out under that firm's ERI id. Unwinding it later means
> re-consenting every client. And **ERI Type 3** (§3.3) may be a third option
> worth pricing before defaulting to Type 2.

**Code seam.** `domain/income_tax/itr_json.py` already refuses in the right
place — `if not software_provider_id(): raise SoftwareProviderNotRegistered`,
reading `ITR_SOFTWARE_PROVIDER_ID` from `render.yaml`. Note the **second**
refusal behind it: `ITRPayload` carries tax figures and no `PersonalInfo`,
`FilingStatus`, `Verification` or bank details, so the `SW########` unblocks the
field but does **not** by itself produce a filable return.

### 4.5 TDS / TCS statements · **NO CONFIRMED PUBLIC API — with one open lead**

**Today, and both documents agree:** prepare in the **RPU** (free Java desktop
GUI), validate with the **FVU** to produce a `.fvu`, upload at incometax.gov.in
under the **TAN login** with **DSC or EVC**, receive a token number. TRACES 2.0
processes in about 2–4 hours. **RPU and FVU are still in the loop in 2026** —
TRACES 2.0 did not remove them. `[S]`

**Whose credential:** all of it the **client's**. There is nothing for us to
register for on the current path.

**The lead, which is the highest-value open question on the direct-tax side.**
A **CPC-TDS developer portal** offers *"secure, OpenAPI 3.0 based TDS Statement
Filing APIs for Forms 24Q, 26Q, 27Q and 27EQ, covering data capture, validate,
submit as well as submit status and error download"*, with organisation
registration, application configuration, **sandbox and production credentials**,
and promotion from sandbox to production. It is described as built for *"ERPs,
payroll products and enterprise platforms"*. Support: `suvidha-support@tdscpc.gov.in`.
`[S]`

**And why nobody should plan against it yet:** **every result still points at
`https://test-dev.tdscpc.gov.in/`** — literally a development host. `[S-gov]` by
URL, `[U]` in substance. No production developer-portal URL was found across
this session's and the prior pass's searches. No scheme, no criteria, no CBDT
notification defining a "TDS Suvidha Provider". `[U]`

The uploaded research reached the same conclusion by a different route
(*"did not find a current public government developer onboarding page"*) and did
not find the portal at all. **Two emails to `suvidha-support@tdscpc.gov.in`
would settle it and cost nothing** — see §6.

**One thing no registration fixes.** `domain/tds/vocabulary.py` deliberately
does not hold the s.393 **payment-code table**, and an API makes that worse: a
wrong payment code is *accepted* and then wrong. The range is **1001–1092, not
1001–1067** — 1068–1092 are the s.394 TCS codes, so anything range-checking at
≤ 1067 rejects every valid TCS code. `[S]`

### 4.6 TDS certificates — Form 16 → 130, Form 16A → 131 · **NO API, AND THERE WILL NOT BE ONE**

Both parts of Form 16 must be generated and downloaded **from TRACES** — CBDT
Circular 04/2013 for Part A, CBDT (Systems) Notification 09/2019 for Part B — and
a certificate issued in any other format is **invalid even with accurate data**.
`[S]` Under the 2025 Act it is stricter: Rule 215(1) with s.395(4)(b) is
reported to require the whole of **Form 130** to come from TRACES, and it cannot
be issued until the quarterly **Form 138** has been filed and processed. `[S]`

> Any roadmap item shaped *"generate Form 130"* is not buildable by anyone. The
> buildable shape is: get Annexure II exactly right → return filed and processed
> → fetch and distribute the TRACES-issued certificate.
> `routers/payroll.py::form_24q_annexure_ii` already says *"THERE IS NO FORM 16
> GENERATOR HERE, AND THERE SHOULD NOT BE."* Leave it.

### 4.7 MCA · **NO CONFIRMED PUBLIC API**

**No filing API, no developer portal, no partner programme, nothing to apply
for.** `[S]`, re-searched this session and again returning nothing. MCA V3
material describes a better *human* experience — centralised dashboard, prefill,
real-time validation — and MCA's *inbound* integrations with Income Tax, GST,
EPFO and ESIC at incorporation. **That is MCA calling them, not an API for us.**

**Whose credential:** the **client's director's Class 3 DSC**, associated on V3
under MCA Services → DSC Services → Associate DSC. Roughly **₹850–₹4,500**
depending on validity and token `[S]` — the client's cost, and the item that most
often stalls a filing.

**The one machine-facing artefact is the XBRL instance**, and MCA addresses
software vendors about it directly: **MCA XBRL Validation Tool V5.0, July 2025**,
covering AOC-4 XBRL (C&I and Ind AS) and CRA-4 XBRL `[S-gov]`. One vendor
changelog of 6 August 2026 reports no change in the C&I 2016 taxonomy `[S]`. No
version beyond V5.0 found.

**Code seams.** `routers/xbrl_engine.py`, `domain/income_tax/xbrl_service.py`
(whose `http://www.mca.gov.in/...` strings are XML **namespace URIs**, never
dereferenced — do not "fix" them), `routers/mca_workspace.py`. Version the
taxonomy URL the way the rate registries are versioned.

### 4.8 EPFO · **NO CONFIRMED PUBLIC API**

**No employer API exists and there is no programme to join.** `[S]` Searched
again this session; EPFO 3.0's announced features are member-side (auto-claims,
UPI/ATM withdrawal) plus employer conveniences — **auto-computed ECR carried
forward from the previous month, and OTP-based authentication replacing DSC**.
Neither is an API. `[S]`

One 2026 change with a product consequence: **from 11 March 2026 the portal
serves only summary-level ECR downloads**, dropping employee-wise detail — so
**our own records become the only per-employee history.** `[S]`

**Code seams.** `domain/payroll/ecr.py` (format unchanged — `.txt`, 11 fields,
`#~#`), `domain/payroll/ecr_sequence.py`, `public.epfo_ecr_filings`
(migration 335). The honest ceiling is already built.

### 4.9 ESIC · **NO CONFIRMED PUBLIC API**

**No API, no developer portal, no specification, no programme.** The most clearly
closed of the three; a further search this session returned only contribution-rate
content. `[S]` Employer logs in with the 17-digit code, files the monthly
contribution, generates a challan, pays.

The uploaded research says *"official ESIC material shows system
integrations/web services exist in controlled contexts"* — I could not
corroborate that, and it is consistent with government-to-government
integration rather than a SaaS developer programme. Its own conclusion —
*"CAFLOW should not build around unofficial scraping or credential
automation"* — is right.

**Code seam.** `domain/payroll/esic.py`, whose refusal to invent numeric reason
codes is more right than when it was written, given ESIC's October 2025 circular
on zero-day filings.

### 4.10 Professional tax · **NO CONFIRMED PUBLIC API, IN ANY STATE**

No PT API onboarding route was identified for any state, by either document.
PT is administered **per state**, which means any API would be twenty-two
separate integrations, not one.

**Where we actually are, which neither document states:** `routers/payroll.py`
holds PT slabs for **four** states — Maharashtra, Tamil Nadu, Karnataka, West
Bengal — of the **twenty-two** that `domain/payroll/professional_tax.py` records
as levying it. The gap is not silent: creating a payroll run returns
`statutory_gaps` naming every employee whose state levies a deduction the run did
not compute.

**The 2026 facts worth carrying:**

- Maharashtra notification of **28 February 2026 amending Rule 11(3)** moved PT
  due dates **from month-end to the 15th**. `[S]` We hold no PT due dates, so
  nothing is wrong today — **do not add the old ones.**
- The trade circular of **13 March 2026** granted temporary relaxation for
  March 2026 compliances because of portal problems, with registration permitted
  to 30 April 2026. `[S]` A transient measure, not a design constraint.
- The count of twenty-two levying states is `[S]`-graded and **probably one or
  two too high** — Odisha is reported to have repealed from 01-04-2026 and
  Punjab's charge is described as a Development Tax. Deliberately unchanged: the
  error direction is benign (a false gap warning, never a wrong deduction).

---

## 5. The other integrations worth having

You asked for "any other APIs that can genuinely improve the platform". These
are the ones that survived checking. Two of them are real and reachable.

### 5.1 DigiLocker (via API Setu) · **DIRECT API** — recommended

A documented onboarding path for a private entity: **apply online → obtain an
API key → develop/host APIs → integrate → testing and audit.** `[S]` DigiLocker
exposes **Issuer** APIs (organisations pushing documents into citizens' lockers)
and **Requester** APIs (organisations consuming verified documents), through
**API Setu**, an open API platform of MeitY. `[S]`

**Why it matters to a CA platform:** client onboarding is a document-collection
problem — PAN, Aadhaar, incorporation certificate, bank statements. A verified
DigiLocker pull replaces "email me a scan" and gives a document with provenance.
This is the highest-value non-filing integration available, and **the uploaded
research does not mention it.**

`[U]`: fees, audit requirements, and whether a CA-practice SaaS qualifies as a
Requester — none confirmed.

### 5.2 Protean PAN verification · **APPROVAL-BASED** — probably blocked

Protean (formerly NSDL eGov) is **authorised by the Income Tax Department** to
run online PAN verification. `[S]`

**The eligibility bar is the finding**, and it is likely disqualifying:
eligible categories are entities required to furnish **AIR/SFT**, stock and
commodity exchanges and clearing corporations, and **companies and government
deductors filing TDS/TCS returns with more than 500 deductee counts per
quarter**, vetted at application. `[S]`

**Documents:** Terms & Conditions and an NDA on the entity's letterhead, an
authorisation letter where the DSC holder differs from the authorised signatory,
DSC screenshots and the incorporation certificate. **Approval by the Income Tax
Department**, then registration charges, then an eight-digit user id. Charges
refunded only if ITD rejects. `[S]` Amount `[U]`.

> **Read honestly: we probably do not qualify today**, because the deductee-count
> route is about our *own* TDS filings, not our clients'. Worth one email to
> confirm whether a SaaS serving deductors has any category at all. `[U]`

### 5.3 eSign / DSC · **PARTNER-BASED**

MCA forms, GST returns for companies and LLPs, and TDS statements all end in a
signature. eSign is provided by licensed **ESPs** under CCA. Both documents agree
on the one rule that matters: **never store users' DSC private keys centrally.**
Support a compliant signing architecture instead. `[U]` on ESP commercials.

### 5.4 GSTIN verification and return filing-status · **bundled with the ASP contract**

Not a separate integration. GSTN exposes GSTIN validation, taxpayer status and
return filing-history endpoints **only through a GSP** — there is no free public
API. `[S]` Worth naming explicitly when negotiating the ASP contract, because it
is genuinely useful (vendor verification, §16(2)(aa) support) and you are
already paying for the pipe.

### 5.5 Account Aggregator · **CLOSED BY DECISION — do not reopen**

Not in the uploaded research, and it must not be re-derived. This repo
investigated AA to a conclusion: **there is no FIU licence to apply for** (the
RBI Directions define an FIU as an entity already regulated by a financial-sector
regulator — ICAI is not one), and **no published purpose code covers keeping a
client's books.** The five codes are for wealth management, financial advisory,
underwriting, lending monitoring and account verification. **Purpose defeats the
partner route too**, because a partner FIU's permitted purposes come from its own
licence.

**Route 3 — do not consume via AA — was chosen on 6 September 2026**, with no
counsel engaged and nothing spent. Statement upload stays the path. Full
reasoning in `05-bank-data-and-the-account-aggregator.md`. **Never declare
purpose code 102.**

### 5.6 Udyam and Shram Suvidha · **NO CONFIRMED PUBLIC API**

Both documents agree, and neither found an onboarding path. Udyam is useful for
the **MSME classification the §43B(h) tracker needs** — a fact about the
*supplier* that no ledger holds — so if an API ever appears it closes a real gap.
Not today. `[U]`

---

## 6. What to do, in what order

Sorted by **irreversibility and information value**, not by commercial prize.
GST returns are the biggest prize and sit at #8 deliberately: items 1–5 cost
nothing, commit to nothing, and each closes a question the rest of the plan is
currently guessing at.

### Wave 0 — this week. No money, no commitment, no counterparty.

| # | Action | Unblocks |
|---|---|---|
| 1 | Register as **Third Party Software Utility Developer** on the e-filing portal; obtain the `SW########` | `itr_json.py`'s `SoftwareProviderNotRegistered` — a config change, not a code change. **Highest ratio of unblock to cost in this document** |
| 2 | Register on **`einv-apisandbox.nic.in`**; build and test the IRN rails | `routers/einvoice.py` — **the one filing software can complete** |
| 3 | Email **`suvidha-support@tdscpc.gov.in`**: is the CPC-TDS developer portal live in production, at what URL, and what does the TSP category require? | Potentially the entire direct-tax filing side |
| 4 | Read `gstn.org.in/.../eligibility-batch-5.pdf` on an unblocked network; email GSTN asking whether GSP applications are open | Settles build-vs-buy on GST. **"Closed" is a perfectly good answer** that saves a quarter |
| 5 | Confirm the **ERI type and bank-guarantee** question directly on the portal — Type 1 vs Type 2 vs Type 3, and which carries the guarantee | Removes the one commercial contradiction between the two research documents |
| 6 | Fix `get_provider()` to honour its argument | Nothing today; prevents a silent-wrong-answer the day a GSP provider exists |

### Wave 1 — weeks to months. Small money, one real decision.

| # | Action | Note |
|---|---|---|
| 7 | **Decide the ERI entity**: product company (net worth ≥ ₹1 cr) vs a CA firm vs Type 3 | **Decide before applying.** Whoever registers owns the client consents and the obligations |
| 8 | Stand up an **India-hosted static-IP egress hop** | Gates NIC e-invoice production (≤ 4 static IPs) and probably the ERI path. `apps/api` is on Render in **Singapore** by design and Render cannot move regions. **Start before either application completes** |
| 9 | Open **GSP/ASP conversations** — three or four vendors | Ask: current API version matrix; whether GSTR-9 can be *filed* not just fetched; GSTR-9C at all; the bulk file-based GSTR-2B path; per-call and per-return pricing; **what name appears in the client's consent dashboard**; data-use clauses |
| 10 | **DigiLocker Requester** application | Client onboarding with provenance |

### Wave 2 — quarters. Real money, serial manual gates.

| # | Action | Unblocks |
|---|---|---|
| 11 | **ERI application** — documents, ISA/CISA due-diligence certificate, departmental approval | ITR transmission (never completion — s.140) |
| 12 | **ASP contract signed**, sub-licence issued, first client's Manage API Access consent captured | GST returns |
| 13 | NIC **e-invoice production** — test summary report, IPs whitelisted | Live IRN generation |

### Never — recorded so nobody starts them

**MCA, EPFO, ESIC and professional tax filing integrations.** No registration, no
empanelment, no partner, no purchasable route. The only interfaces are
undocumented private endpoints inside the portals, and driving those is out of
scope on exactly the grounds this repo rules out net-banking screen-scraping. If
somebody proposes RPA against the EPFO portal: a documented case of precisely
that exists `[S]`, and it is the clearest available evidence that **no API
exists**, not a precedent.

---

## 7. What is not confirmed, and how to close each one

Every item here is `[U]`. None should enter a plan or a customer promise until
closed.

| # | Open question | How to close it | Cost |
|---|---|---|---|
| 1 | Does the **Third Party Software Utility Developer** registration issue the `SW########`? | Read the official user manual; register | Free |
| 2 | Is the **CPC-TDS developer portal** live in production, and what is a TSP? | Email `suvidha-support@tdscpc.gov.in` | Free |
| 3 | Are **GSP applications open**, and is batch 5's bar really ₹50 lakh? | Read the batch-5 PDF; email GSTN | Free |
| 4 | Which **ERI type** carries the bank guarantee, and how much? | The portal, or a call to ITD | Free |
| 5 | Does the **ERP category** for NIC e-invoice production have a turnover or net-worth bar? | Ask `support.einv.api@gov.in` with the test summary | Free |
| 6 | **All fees**, everywhere. Every figure in this document is stale, absent or single-sourced | Each authority directly | Free to ask |
| 7 | Does **ERI Type 3** fit a CA-practice platform better than Type 2? | ITD | Free |
| 8 | Does any **PAN verification** category admit a SaaS serving deductors? | Protean | Free |
| 9 | Whether the **ERI production path** needs Indian static IPs, as NIC's does | ITD, at application | Free |

**Nine open questions. Eight of them cost nothing but an email.** That is the
main practical conclusion of this document: the research is cheap and has not
been done, and doing it will change the plan more than any amount of further
desk work.

---

## 8. Source register

Official URLs, **none of them fetched by me** — recorded so the next person on an
unblocked network can go straight to them.

**Income tax / ERI**
- `https://www.incometax.gov.in/iec/foportal/api-specifications`
- `https://www.incometax.gov.in/iec/foportal/help/eri/registration`
- `https://www.incometax.gov.in/iec/foportal/help/perform-eri-registration`
- `https://www.incometax.gov.in/iec/foportal/help/addclient`
- `https://www.incometax.gov.in/iec/foportal/sites/default/files/2020-08/User_Manual_Third-Party_Utility_Provider.pdf`
- `https://www.incometax.gov.in/iec/foportal/help/register-for-efiling-external-agency` — the category we must **not** chase

**GST**
- `https://www.gstn.org.in/gsp-ecosystem`
- `https://gstn.org.in/assets/mainDashboard/Pdf/eligibility-batch-5.pdf`
- `https://developer.gst.gov.in/apiportal/`
- `https://tutorial.gst.gov.in/downloads/news/taxpayer_advisory_on_transparency_of_data_access_via_gsp_api.pdf`
- `https://tutorial.gst.gov.in/downloads/news/advisory_einvoice_api_ewb_by_irn_approved.pdf`

**e-invoice / e-way bill**
- `https://einv-apisandbox.nic.in/`
- `https://einvoice6.gst.gov.in/content/api-integration/` — IRIS IRP
- `https://docs.ewaybillgst.gov.in/apidocs/on-boarding-process.html`
- `support.einv.api@gov.in`

**TDS**
- `https://test-dev.tdscpc.gov.in/` — **a development host; no production URL found**
- `suvidha-support@tdscpc.gov.in`
- `https://tinpan.proteantech.in/downloads/e-tds/eTDS-download-regular.html`
- `https://tinpan.proteantech.in/services/online-pan-verification/pan-verification-register.html`

**MCA / payroll / other**
- `https://www.mca.gov.in/XBRL/MCA-validation.html`
- `https://www.epfindia.gov.in/site_en/Online_ECR.php`
- `https://www.esic.gov.in/`
- `https://www.mahagst.gov.in/en/profession-tax-and-allied-acts-gr`
- `https://apisetu.gov.in/digilocker` · `https://www.digilocker.gov.in/web/partners/`
- `https://return.shramsuvidha.gov.in/` · `https://www.udyamregistration.gov.in/`

---

## 9. The bottom line

**The platform is not unnecessary without filing, but the claim has to be
accurate.**

- **Two statutory outputs are fully completable by software** — e-invoice IRN and
  e-way bill — and both are reachable on a **free, self-service sandbox today**.
- **Two more are transmittable** with registration: ITR (ERI) and GST returns
  (ASP under a GSP). Both end with the client's signature, by law, and no
  licence changes that.
- **Four have no channel at all** — MCA, EPFO, ESIC, professional tax — and the
  honest ceiling is a perfect file plus a human with a browser. That is what
  every competitor also does, including the GSPs.
- **One is genuinely open and unresearched** — the CPC-TDS developer portal. If
  it is real in production it is the largest single change available to this
  roadmap, and finding out costs one email.

The product's existing posture — prepare precisely, refuse to auto-submit, record
what the human did — is the correct one for six of the nine, and is the same
posture the market leaders hold. What is missing is not architecture. It is nine
emails.
