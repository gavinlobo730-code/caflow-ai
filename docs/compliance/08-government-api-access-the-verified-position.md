# Government API access — the verified position

**11 September 2026.** Consolidates `07-getting-permission-to-file.md` with the
external research baseline supplied by the owner
(*CAFLOW — Government API & Compliance Integration Roadmap*, 11 September 2026),
cross-checks both, and answers the four questions that decide whether this
product can file: **who may apply, what it costs, what it unblocks, and where a
human is legally unavoidable.**

Read §0 before anything else. It governs how much weight every other line here
can carry.

**Added 11 September 2026, second pass.** §11 answers *"does any software
actually file MCA, EPFO, ESIC and PT — and if so, how?"* The answer is no, and
the way the market works around it is the useful part. §12 turns that into the
seven-step last-mile contract and says where we stand on each. §13 is the work
that follows — **Track F**, none of which needs a registration, a licence or a
counterparty. §14 answers *"are you sure of this document?"* section by section.
§15 is the list of pages I need opened, because egress is still refused here.

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

---

## 10. The emails, drafted

§7 lists nine open questions. They go to **six inboxes**, not nine — several
questions belong to the same authority and are far more likely to be answered as
one short numbered list than as three separate messages arriving in the same
queue.

### How to send these, and it matters more than the wording

- **Send from a company domain**, not Gmail. A `@practicesync.in`-style address
  is answered; a free address often is not.
- **One authority per email. Numbered questions. Nothing open-ended.** Every
  question below is answerable in one line by someone who knows. Do not ask them
  to explain a process — ask them to confirm a fact or send a current document.
- **Quote their own published material.** Each draft cites the page or document
  the question arises from. It signals the homework is done and routes the mail
  to the right desk.
- **Expect silence from some.** Follow up by phone after **seven working days**,
  quoting the email's subject line and date. Numbers are given with each draft.
- **Replace every `[SQUARE BRACKET]`** before sending. Nothing in them is
  invented here on purpose.
- **Keep every reply.** The answers are the evidence base this whole document is
  missing, and they should be filed back into
  `docs/compliance/08-…` with the date received.

> **One caution on addresses.** Every address below is `[S]` — taken from a
> search result, not from a page I could open. If one bounces, the fallback for
> each is given. No address here is invented; where I could not find one, the
> draft says so instead.

---

### Email 1 of 6 — Income Tax Department (e-Filing) · closes questions 1, 4, 7, 9

**To:** `efilingwebmanager@incometax.gov.in`
**Fallback:** e-Filing helpline **1800 103 0025** / **1800 419 0025** /
**+91-80-46122000**, 08:00–20:00 Mon–Fri, 09:00–18:00 Sat
**Subject:** `Clarification sought — ERI category selection and Third Party Software Utility Developer registration`

> Dear Sir / Madam,
>
> We are **[LEGAL ENTITY NAME]**, PAN **[PAN]**, developing an accounting and
> compliance platform for Chartered Accountants in practice. We intend to file
> Income Tax Returns for our clients' taxpayers through the Department's
> systems, and we wish to register correctly at the first attempt.
>
> We have read the ERI registration guidance at
> `https://www.incometax.gov.in/iec/foportal/help/eri/registration` and the
> Third Party Software Utility Developer user manual at
> `https://www.incometax.gov.in/iec/foportal/sites/default/files/2020-08/User_Manual_Third-Party_Utility_Provider.pdf`.
> We would be grateful for confirmation on the following.
>
> 1. Our software is used by a Chartered Accountant, who files on behalf of
>    their client. Is the correct category **ERI Type 2** (own software
>    application filing through Departmental APIs) or **ERI Type 3** (developer
>    of an offline utility, not acting on behalf of taxpayers)?
> 2. Which ERI types require a **bank guarantee**, and what is the current
>    amount? Public sources conflict on whether it attaches to Type 1 only.
> 3. What are the **current fees** for ERI registration and renewal? The figures
>    in circulation appear to pre-date GST and include service tax.
> 4. Does registration as a **Third Party Software Utility Developer** issue the
>    software provider identifier (format `SW########`) carried in the
>    `SWCreatedBy` field of the ITR JSON schema? If not, how is that identifier
>    obtained?
> 5. Does the ERI production API path require **Indian static IP addresses** to
>    be whitelisted, as the External Agency process does? If so, how many?
> 6. The API specifications published at
>    `https://www.incometax.gov.in/iec/foportal/api-specifications` are dated
>    November 2021. Is a **more current specification** available to registered
>    ERIs, and how is it obtained?
>
> We would be happy to provide any further detail.
>
> Yours faithfully,
> **[NAME]**, **[DESIGNATION]**
> **[LEGAL ENTITY NAME]** · **[PHONE]** · **[EMAIL]**

---

### Email 2 of 6 — CPC-TDS (TRACES) · closes question 2

**This is the highest-value email in the set.** If the answer is yes, the
direct-tax side changes from "generate a file, a human uploads it" to "integrate
an API subject to empanelment".

**To:** `suvidha-support@tdscpc.gov.in`
**Fallback:** TRACES contact page at `https://contents.tdscpc.gov.in/`
**Subject:** `Query — production availability of CPC-TDS Statement Filing APIs and Suvidha Provider registration`

> Dear Sir / Madam,
>
> We are **[LEGAL ENTITY NAME]**, PAN **[PAN]**, a payroll and TDS compliance
> software provider serving deductors through Chartered Accountants in practice.
>
> We have seen the CPC-TDS developer portal describing OpenAPI 3.0 **TDS
> Statement Filing APIs for Forms 24Q, 26Q, 27Q and 27EQ**, covering data
> capture, validate, submit, submit-status and error download, with organisation
> registration, sandbox and production credentials. The only URL we can locate
> for it is `https://test-dev.tdscpc.gov.in/`, which appears to be a development
> host.
>
> We would be grateful for confirmation on the following.
>
> 1. Is the CPC-TDS developer portal **live in production**, and if so at what
>    URL?
> 2. If it is not yet live, is a **target date** available?
> 3. What is the **Suvidha Provider / TSP** category referred to in the portal's
>    access controls? Is there a published scheme, eligibility criteria or
>    notification defining it?
> 4. What is the **registration process** for an organisation wishing to obtain
>    sandbox and then production credentials, and are there any fees?
> 5. Is there a **published API specification** we may review before applying?
> 6. Does this route replace the RPU/FVU preparation and TAN-login upload
>    workflow, or run alongside it?
>
> Yours faithfully,
> **[NAME]**, **[DESIGNATION]**
> **[LEGAL ENTITY NAME]** · **[PHONE]** · **[EMAIL]**

---

### Email 3 of 6 — GSTN · closes question 3

**To:** `info@gstn.org.in`
**Cc:** `helpdesk@gst.gov.in`
**Fallback:** GSTN helpdesk **0124-4688999**
**Subject:** `Enquiry — GST Suvidha Provider empanelment status and current eligibility criteria`

> Dear Sir / Madam,
>
> We are **[LEGAL ENTITY NAME]**, PAN **[PAN]**, GSTIN **[GSTIN]**, an Indian
> company developing GST compliance software for Chartered Accountants in
> practice. We are deciding between applying for GSP empanelment and operating
> as an Application Service Provider under an existing GSP.
>
> We have reviewed the GSP ecosystem page at `https://www.gstn.org.in/gsp-ecosystem`
> and the batch-5 eligibility document at
> `https://gstn.org.in/assets/mainDashboard/Pdf/eligibility-batch-5.pdf`.
>
> 1. Are **applications for GSP empanelment currently open**? If the fifth batch
>    has concluded, is a **sixth batch** planned, and is there a way to be
>    notified?
> 2. Is the **batch-5 eligibility document the current criteria**, and does the
>    turnover threshold stated there still apply?
> 3. Is there a **fee** payable by a selected GSP to GSTN — a one-time
>    empanelment fee, an annual licence fee, or a per-transaction charge? If so,
>    what are the current rates?
> 4. Does GSTN **recognise or register ASPs** in any form, or is an ASP purely a
>    commercial arrangement with a GSP with no standing before GSTN?
> 5. Following the taxpayer advisory on **Transparency of Data Access via
>    GSP/ASP** (September 2025), how is an ASP's name registered so that it
>    appears correctly in the taxpayer's consent notification and consent
>    dashboard?
>
> Yours faithfully,
> **[NAME]**, **[DESIGNATION]**
> **[LEGAL ENTITY NAME]** · **[PHONE]** · **[EMAIL]**

---

### Email 4 of 6 — NIC e-Invoice (IRP) · closes question 5

**Send this one last, after the sandbox work**, because it is the only email
here that is stronger with evidence attached — NIC's own process expects a test
summary report.

**To:** `support.einv.api@gov.in`
**Fallback:** the e-invoice portal helpdesk at `https://einvoice1.gst.gov.in/`
**Subject:** `Request for production API access — ERP category, [LEGAL ENTITY NAME]`

> Dear Sir / Madam,
>
> We are **[LEGAL ENTITY NAME]**, PAN **[PAN]**, GSTIN **[GSTIN]**, an
> accounting software provider serving taxpayers through Chartered Accountants
> in practice. We have completed sandbox integration at
> `https://einv-apisandbox.nic.in/` and wish to move to production.
>
> We understand Client Id and Client Secret are issued to service providers in
> the **GSP, ERP and ECO** categories.
>
> 1. Is the **ERP category** the correct one for a SaaS accounting platform
>    generating IRNs on behalf of its users' GSTINs?
> 2. Are there **eligibility criteria** for the ERP category — turnover, net
>    worth, minimum number of client GSTINs, or any empanelment?
> 3. Is any **fee** payable for production credentials?
> 4. How many **static IP addresses** may be whitelisted, and is a specific
>    format required for the request?
> 5. What must the **Test Summary Report** contain, and is a template available?
> 6. What is the typical **time from submission to production credentials**?
> 7. Please confirm the requirements arising from the advisory of 17 June 2026
>    making **Ship-to GSTIN mandatory** in the IRN and e-Way-Bill-by-IRN APIs
>    from 1 August 2026.
>
> Yours faithfully,
> **[NAME]**, **[DESIGNATION]**
> **[LEGAL ENTITY NAME]** · **[PHONE]** · **[EMAIL]**

---

### Email 5 of 6 — Protean eGov (TIN) · closes question 8

**Expect a "no".** The published eligibility categories appear to require the
applicant's *own* TDS filings to exceed 500 deductees a quarter, which a
software provider does not. The email is worth sending because the answer is
either a route we did not know about or a `[U]` closed for good.

**To:** `tininfo@protean-tinpan.com`
**Fallback:** **020 27218080** / **08069708080**, or the Complaints/Queries form
at `https://www.protean-tinpan.com/`
**Subject:** `Eligibility query — Online PAN Verification facility for a compliance software provider`

> Dear Sir / Madam,
>
> We are **[LEGAL ENTITY NAME]**, PAN **[PAN]**, a compliance software provider
> serving Chartered Accountants and their deductor clients. We wish to verify
> PANs of deductees and vendors within our platform, with the deductor's
> authorisation.
>
> We have read the eligibility categories published at
> `https://tinpan.proteantech.in/services/online-pan-verification/pan-verification-register.html`.
>
> 1. Is there an **eligible category** for a software provider that verifies
>    PANs **on behalf of** deductors, rather than filing its own TDS returns?
> 2. If eligibility rests on the applicant's own deductee count exceeding 500 per
>    quarter, does the count of **clients served** qualify in any circumstance?
> 3. What are the **current registration charges** and the annual or
>    per-verification charges for each mode (screen-based, file-based, API)?
> 4. What is the **typical time** from application to issue of the eight-digit
>    user ID, including Income Tax Department approval?
> 5. Is an **API-based** verification mode available, and is its specification
>    shared before registration?
>
> Yours faithfully,
> **[NAME]**, **[DESIGNATION]**
> **[LEGAL ENTITY NAME]** · **[PHONE]** · **[EMAIL]**

---

### Email 6 of 6 — DigiLocker / API Setu · the non-filing one worth doing

**No email address confirmed.** Onboarding appears to run through the partner
portal at `https://partners.apisetu.gov.in/signin`, which uses DigiLocker
MeriPehchaan credentials. **Register there first**; use the text below for the
application's free-text fields, or for a support ticket if the portal offers one.

**Route:** `https://partners.apisetu.gov.in/signin` → register as a Partner
Organisation → apply for **Requester** access
**Reference:** `https://www.digilocker.gov.in/web/partners/`
**Subject (if a ticket is available):** `Requester onboarding query — verified document pull for a CA compliance platform`

> We are **[LEGAL ENTITY NAME]**, PAN **[PAN]**, CIN **[CIN]**, an accounting and
> compliance platform used by Chartered Accountants in practice. We wish to
> become a **DigiLocker Requester** so that a client can share verified copies of
> PAN, incorporation and registration documents with their Chartered Accountant
> during engagement onboarding, with the client's consent, instead of emailing
> scans.
>
> 1. Is a **private limited company providing SaaS to Chartered Accountants**
>    eligible to onboard as a Requester?
> 2. What **documents** must accompany the application?
> 3. Is there an **onboarding fee**, and are there per-transaction charges?
> 4. What does the **testing and audit** step involve, and how long does it
>    typically take?
> 5. Which **document types** are available to a Requester in our use case —
>    specifically PAN, Aadhaar (masked), and MCA incorporation documents?
>
> **[NAME]**, **[DESIGNATION]** · **[PHONE]** · **[EMAIL]**

---

### Tracking the replies

| # | To | Closes | Sent | Chased | Answered | Answer |
|---|---|---|---|---|---|---|
| 1 | `efilingwebmanager@incometax.gov.in` | Q1, Q4, Q7, Q9 | | | | |
| 2 | `suvidha-support@tdscpc.gov.in` | Q2 | | | | |
| 3 | `info@gstn.org.in` | Q3 | | | | |
| 4 | `support.einv.api@gov.in` | Q5 | | | | |
| 5 | `tininfo@protean-tinpan.com` | Q8 | | | | |
| 6 | API Setu partner portal | DigiLocker | | | | |

**Question 6 — "all fees, everywhere" — is not a separate email.** It is asked
inside each of the five above, because a fee question answered by the authority
that charges it is the only kind worth having.

**Send 1, 2, 3 and 5 today.** They cost nothing, they commit to nothing, and
until they are answered every cost and eligibility line in this document is an
estimate. Send 4 after the sandbox work, and start 6 whenever convenient.

---

## 11. How the competitors actually do it

You asked the right question: *if we cannot file MCA, EPFO, ESIC and PT through
our software, can anybody?* I went looking for a counterexample — searches
deliberately phrased to find a vendor that files directly, not to confirm that
none does. What came back is more useful than a yes or a no.

### 11.1 Four mechanisms, and only one of them is an API

| | Mechanism | Who does it | What actually happens | Is it an API? |
|---|---|---|---|---|
| **A** | **Generate-and-upload** | greytHR, Keka, Zoho Payroll, Pocket HRMS, factoHR, HROne, RelyOn Saral, and every TDS package | Software emits the exact file the portal eats. A human logs in and uploads it. | **No** |
| **B** | **Portal-assisted upload** | Gen CompLaw (SAG Infotech), Webtel — the ROC packages | Software opens the MCA session *from inside the product*, the human supplies the login and the OTP, the DSC signs on the human's machine, the software pushes the form up and reads the status back. | **No** |
| **C** | **Stored credentials and a robot** | RazorpayX Payroll is the clearest case | The customer types their government-portal credentials into the vendor's dashboard. The vendor's system then operates the portal *as the customer*. | **No** |
| **D** | **A published filing API** | **Nobody, for these four** | — | — |

**There is no mechanism D for MCA, EPFO, ESIC or professional tax.** Not for
us, not for greytHR, not for Razorpay, not for anybody. The ceiling is not a
limitation of PracticeSync. It is a property of the portals.

### 11.2 The quotes, so you can weigh the evidence yourself

All of these are `[S]` — search-engine summaries of vendor pages. **Direct
fetches are still refused by the egress proxy** (I tried again this session:
`blog.saginfotech.com` returned `EGRESS_BLOCKED`), so I have not opened a single
one of these pages. Read them as "the vendor's own marketing says", not as
"verified".

- **greytHR** — *"You can automatically generate the ECR file with greytHR. The
  ECR file is ready with just a click and all that you need to do is upload it
  to EPFO Unified portal."* That sentence is the whole finding. The market
  leader in Indian payroll describes its EPFO ceiling in the same words this
  document uses for ours.
- **Keka** — *"Keka allows you to generate a ready-to-upload PF ECR report for
  easy filing… click the Download icon to export the report in Excel, PDF, or
  Text format."*
- **Zoho Payroll** — *"The EPF-ECR report that is necessary for filing EPF
  returns and the ESIC report for filing ESI returns are structured in the
  format expected by the government."* Structured in the format. Not
  transmitted.
- **Pocket HRMS / factoHR / HROne** — the same shape; an "ESI Return File"
  report whose purpose is the portal's bulk upload.
- **Gen CompLaw (SAG Infotech)** — *"allows users to directly get login on MCA
  portal from software after that users can upload the e-form on portal"*, with
  DSC selection per director and expiry tracking. This is mechanism B, and note
  what it still requires: **a human login and a human OTP.** MCA V3 sends the
  OTP to the registered mobile **and** the email, which makes unattended
  automation structurally impossible, not merely discouraged.
- **RazorpayX Payroll** — the marketing is unambiguous: it *"auto-files and pays
  TDS, PF, PT and ESIC"*, with *"no manual intervention"*. The mechanism only
  shows up in the support FAQ: *"TDS challans could be unavailable due to
  incorrect IT credentials provided on the Payroll Dashboard, as a result,
  Payroll is unable to fetch the challans."*

  **That one sentence is the answer to "how do they do it".** The customer hands
  over their income-tax portal credentials and the platform signs in as them.
  I want to be precise about the limit of this evidence: it establishes stored
  credentials **for the income-tax portal, for fetching challans**. It does not
  prove the same mechanism for EPFO, ESIC and PT — but since no API exists for
  those three either, there is no third possibility, and the inference is
  strong. Grade the mechanism `[S]`, the inference to the other three `[S]`/
  reasoned.

### 11.3 Three things that make Razorpay's route unavailable to us — and wrong even if it were available

This is not squeamishness. Four specific differences:

1. **They are a payment aggregator; we are not.** Razorpay can actually *move
   the money* — that is their licensed business. A large part of "auto-pays PF,
   PT, ESI and TDS" is a payment rail we do not have and should not build. The
   filing and the payment are being conflated in that marketing.
2. **They serve one employer; a CA firm serves two hundred.** A single company
   storing its own EPFO password in its own payroll tool is a decision that
   company makes about itself. A CA firm holding two hundred clients' portal
   credentials is a different object: one breach exposes every client at once,
   and it is the single most attractive target in the product.
3. **DPDP makes it the firm's problem, in writing.** A client's portal
   credential is the client's personal data held by the firm as Data Fiduciary.
   The obligation to secure it, to notify on breach, and to erase it on
   withdrawal of consent all attach — on top of whatever the portal's own terms
   of use say about sharing credentials.
4. **The product has already decided this, for bank data.** `CLAUDE.md`:
   *"Never screen-scrape net banking. No credential capture, no stored bank
   logins, no third party that works that way."* A rule that bends for the EPFO
   portal is not a rule. The same paragraph also says why AA consent approval
   never renders in our UI and why there is no OTP field anywhere in the filing
   demo. Mechanism C is the same mistake wearing a different hat.

**So: there is no route we are missing.** There is a route we are declining,
and one we cannot take.

### 11.4 The finding that actually matters

The vendors are not winning on *filing*. They cannot file either.

They win on the **last mile** — the distance between "the software computed the
number" and "the acknowledgement is on record". Every one of them has invested
there, and that investment is invisible in a feature list: the file is
byte-exact so the upload never bounces; the fields appear in the order the
portal asks for them; the challan comes back into the books; the next month is
blocked until this one is acknowledged.

That is where PracticeSync has real ground to take, and it needs no
registration, no licence, no counterparty and no money. It is entirely code.

---

## 12. The last-mile contract — seven steps, and filing is only the fifth

For every statutory output there are seven things software can do. Filing is
one of them, and it is the only one that is blocked.

| | Step | Blocked by anyone outside us? |
|---|---|---|
| 1 | **Compute** the figures from the books | No |
| 2 | **Emit the exact artefact** the portal accepts — byte-exact, right extension, right encoding | No |
| 3 | **Pre-flight** — refuse here everything the portal would refuse there | No |
| 4 | **Hand off in portal order** — the screen the CA works from while the portal is open in the next tab | No |
| 5 | **File** | **Yes — and only this one** |
| 6 | **Capture the acknowledgement** — TRN / ARN / SRN / CRN, date, amount, receipt PDF | No |
| 7 | **Reconcile and lock** — the challan posts to the GL, the acknowledgement closes the obligation and locks the period | No |

**Six of the seven are ours.** Here is where we actually stand, read off the
code rather than remembered:

| Filing | 1 Compute | 2 Artefact | 3 Pre-flight | 4 Handoff | 6 Acknowledgement | 7 Lock + GL |
|---|---|---|---|---|---|---|
| **GSTR-1 / 3B** | yes | yes (GSTN JSON) | partial | no | **yes** — `PATCH /gstr3b/{id}/status` writes the real ARN and the `public.filings` row | **yes** |
| **EPFO ECR** | yes | yes — `.txt`, 11 fields, `#~#`, format re-verified 04-09-2026 | partial — `ecr_sequence` knows which months are outstanding and which return type is due | no | `public.epfo_ecr_filings` (migration 335) exists | no GL posting of the challan |
| **ESIC** | yes | **CSV — and the portal wants `.xls`** | yes, and better than most: the file is **withheld** until the CA supplies a reason code for every zero-wage member | no | **no record at all** | no |
| **Professional tax** | 4 of 22 states; the gap is named, not silent | **nothing** — no return, no challan | n/a | no | **no record at all** | no |
| **MCA** | yes | XBRL instance (validation tool V5.0) | partial | no | `mca_workspace` filings carry a status and a completion | n/a |
| **TDS 24Q/26Q** | yes | yes | yes — refuses a quarter with no §192 challan | no | challans recorded | partial |

Two lines in that table are concrete defects rather than missing features, and
both came out of this research:

- **The ESIC file is the wrong type.** `domain/payroll/esic.py::to_csv` emits
  comma-separated text. The ESIC bulk upload takes an **Excel file**, and the
  published guidance is specific: all columns formatted as **Text**, **no
  formulas**, saved in the older **Excel 97-2003 `.xls`** format. `[S]` A CA who
  downloads our file and uploads it will be rejected at the portal, after doing
  the work. Everything *inside* the file is right — this is the last inch.
- **ESIC and PT have no filing record.** There is nowhere to put the challan
  number, so the obligation never closes and nothing locks. EPFO has the table;
  the other two do not.

---

## 13. What follows for the software — Track F

These are not from the 278-finding audit and do not belong in the twelve phases
of `2026-09-08c-the-phase-plan.md`. They are a separate track, and I have
lettered them so they cannot collide with a phase number. **None of them needs a
registration, a licence, a counterparty or a rupee.**

Ordered by ratio of harm-removed to work.

### F1 — The ESIC file the portal actually accepts · *small, and it is a live defect*

Emit `.xls` (BIFF8, Excel 97-2003), every cell a **text** cell, no formulas, the
column order the portal's own template uses. Keep the CSV as a second download
for the CA's own checking — but the primary button must produce the thing that
uploads.

Two rules carry over from the money work and matter here: the IP number is
**ten digits and can lead with a zero**, so it must be written as text or Excel
eats the zero; and days are whole numbers rounded **up**, which the domain
module already does.

**Seam:** `domain/payroll/esic.py`, `routers/payroll.py::run_esic`.
**Guard:** a test that opens the emitted workbook and asserts every cell's type
is text and the file's magic bytes are BIFF8 — the rule, not a spelling of it.
**⚠️ Verify the template first** — this is the top item on the screenshot list
in §14. I do not want to rebuild the file from a search summary.

### F2 — One statutory filing record, for everything · *medium; unblocks F3 and F4*

Today GST has `public.filings`, EPFO has `public.epfo_ecr_filings`, MCA has its
own workspace table, and ESIC and PT have nothing. Five shapes for one idea.

One table — `public.statutory_filings` — with a row created **before** the CA
walks to the portal, carrying: firm, client, obligation, period, the artefact's
**SHA-256**, the amount, and a status moving `prepared → handed off → filed →
acknowledged`. The acknowledgement carries the portal's own reference (ARN /
TRN / SRN / CRN), the date **in IST**, and the receipt.

Three properties that have to hold, and each of them is a bug that has already
happened somewhere in this codebase:

- **The hash is of the artefact that was handed over.** If the books change
  after the handoff, the record must be able to say the filed file no longer
  matches the books. That is the difference between a record and a decoration.
- **The acknowledgement is what locks the period**, through
  `journal_period_lock_reason`, exactly as a filed GSTR-3B already does. Not
  the handoff — the acknowledgement.
- **It never writes itself.** No scheduler, no batch, no inference from "the
  due date passed". A human types the reference they were given.

Do **not** migrate GST off `public.filings` in the same change. Add the new
table for the four that have nothing, prove it, and converge later — moving
the one path that currently locks periods correctly is how you break the one
thing that works.

### F3 — The handoff screen · *medium; this is the one CAs will feel*

One screen per obligation, opened next to the portal. It shows, in the order
the portal asks for them: the identity fields (establishment code, TAN, PTRC),
the period, the totals the portal will ask you to confirm, the download button,
and a single field for the reference that comes back.

The value is not the download — they already have that. It is that the CA
stops alt-tabbing between four screens and a spreadsheet to answer "what do I
type in this box".

**Constraint, and it is absolute:** no credential field, no OTP field, no
embedded portal frame. Not for EPFO, not for ESIC, not for MCA. The filing-demo
work already established this and
`apps/web/scripts/one-filing-demo-and-the-kill-switch-reaches-it.test.ts` is the
precedent for holding a line like this with a test rather than a paragraph.

### F4 — The challan is money · *small once F2 exists*

A PF, ESI, PT or TDS challan is a payment. It has to reach the general ledger,
through `_create_journal` like everything else, dated on the payment date, with
the challan reference as the `reference_no` so the dedupe key is the real one.

Today the payroll accrual posts and the remittance does not, which means the
statutory liability accounts never clear and the year-end shows a liability the
client has actually paid.

### F5 — Professional tax: the artefact, not the slabs · *medium; deliberately narrow*

Keep refusing to write twenty states' slabs from memory — that decision stands
and is right. But the **challan and return artefact** for the four states we do
compute is a different thing, and it is missing entirely.

Start with **Maharashtra PTRC**, because it is the largest and because we
already know a date fact about it worth honouring: the notification of
28-02-2026 amending Rule 11(3) moved the due date from month-end to **the
15th** `[S]`. Karnataka Form 5A next.

**Do not add PT due dates until that notification is confirmed** — §4.10 says
why, and holding no date is better than holding a wrong one.

### F6 — The never-do list, as code · *small; and it protects everything above*

Three rules, currently prose in `CLAUDE.md` and this file, that should be tests:

1. **No field anywhere in `apps/web` collects a government-portal password,
   PIN, or OTP.** A grep-shaped guard over input names, labels and
   placeholders — stated as the rule (a credential-shaped input), not as a
   spelling of it, the way the paise guard was rewritten.
2. **No stored portal credential column.** Nothing in `apps/api` may write a
   column whose name says it holds a portal password or token.
3. **Nothing transmits to a `.gov.in` host.** Today it is true by accident —
   there is no such call. A test makes it true on purpose, and makes the day
   somebody adds one a deliberate decision with a review attached.

Rule 3 is the one that matters most, because it is the guard that survives
everything above being built.

### What Track F does not do

It does not make us able to file, and no amount of code will. The four blocked
filings stay blocked until a portal opens an API, and §4.7–4.10 is my honest
reading that none of them is close.

What Track F does is make PracticeSync the product where **the upload never
bounces and the acknowledgement always lands in the books** — which, on the
evidence in §11, is the only axis anyone in this market is actually competing
on.

---

## 14. "Are you sure of this document?" — the honest answer, section by section

No, not uniformly. And the parts I am least sure of are the parts that cost
money, which is the worst possible distribution. So here it is broken up, because
"how confident are you" is not one question.

**Nothing in §1–§10 was contradicted by this session's research.** That is
reassurance of a limited kind: I went looking for a counterexample to the
"no API" verdicts and did not find one. Absence of a counterexample after
targeted searching is real evidence. It is not proof.

### What I would act on now

| Claim | Why I am confident |
|---|---|
| **MCA, EPFO, ESIC and PT have no filing API** | Four independent search angles each session, including searches phrased to find a vendor that files directly. The strongest confirmation is indirect and therefore good: the market leaders describe their own ceiling in the same words — *"all that you need to do is upload it to EPFO Unified portal"*. If an API existed, greytHR would be using it. |
| **e-invoice IRN and e-way bill are the only two statutory outputs software can complete end to end** | Structural, not empirical: the IRP signs, so there is no taxpayer signature to collect. That reasoning does not depend on a source. |
| **GST filing needs a GSP; ITR filing needs an ERI** | Consistent across every source, and consistent with the architecture of both systems. |
| **TDS statements go up as an FVU zip with a DSC, and there is no API** | Re-confirmed this session. Every description of the route is the same: RPU → FVU → upload → DSC. |
| **Never take stored portal credentials** | A decision, not a fact. It does not need a source. |

### What I would not spend a rupee on without confirming first

| Claim | Why it is weak |
|---|---|
| **Every cost figure in the document** | Stale on its face, absent from public sources, or single-sourced. Already flagged in §0 and I am repeating it because it is the most expensive kind of wrong. |
| **The GSP batch-5 ₹50 lakh turnover threshold** | The uploaded research's claim, which my own searches could not surface. Recorded as its claim, not adopted. |
| **The CPC-TDS developer portal (`test-dev.tdscpc.gov.in`)** | A single lead I could not open. It may be a real developer programme or an internal test host with a public DNS name. The difference is large. |
| **ERI registration mechanics — type, fees, bank guarantee** | Reconstructed from summaries. The shape is probably right; the numbers may not be. |
| **The Maharashtra PT due-date change of 28-02-2026** | `[S]`. This is why §4.10 says *do not add the old dates* rather than adding new ones. |
| **The count of twenty-two PT-levying states** | Already flagged as probably one or two too high. Benign error direction, so deliberately unchanged. |

### What changed in this session

- **New and useful:** §11. Nobody can file these four. The competitive position
  is the last mile, not the API.
- **Two concrete defects found**, both in §12 and both fixable this week: the
  **ESIC file is CSV where the portal wants `.xls`**, and **ESIC and PT have no
  filing record at all**.
- **Still `[S]` throughout.** I tried a direct fetch again this session and it
  was refused at the proxy. Nothing in this document has been promoted to `[P]`.

### The one thing I want to be unmistakable

This document is **reliable about which door to knock on and whose signature is
required.** It is **weak about what anything costs and how long it takes.**
Those are different qualities of claim, and I have tried to mark them
differently on every line. Where you are about to commit money or a contract,
treat this as the brief for the question, not as the answer.

---

## 15. What I need you to open — a working list

You offered to open pages and send images. That is genuinely the binding
constraint here, so here is a precise list rather than a vague ask. Each entry
says **what I need off the page**, because a screenshot of the wrong part of a
page costs us both a round trip.

Ordered so that the top of the list changes code this week and the bottom
changes a business decision later. **If you only do three, do 1, 2 and 3.**

### Tier 1 — blocks Track F, which starts as soon as this lands

**1. The ESIC monthly-contribution Excel template.**
`https://www.esic.gov.in` → employer login → File Monthly Contribution → the
**"Sample MC Excel Template"** link. A search surfaced what looks like a direct
path — `esic.in/ESICInsurance1/App_Themes/Help/MC_Template1.xls` — but I would
rather have the one the live portal offers today.

*What I need:* **the file itself if you can attach it** (best), otherwise a
screenshot of it open in Excel showing **row 1 headers, row 2 sample data, the
sheet name and tab count**. Also whether the portal page states an accepted
extension (`.xls` vs `.xlsx`) and any instruction about cell format.
*Why:* F1 rebuilds our ESIC export to match it byte for byte. I do not want to
rebuild a statutory file from a search summary.

**2. The ESIC reason codes.**
Same screen: the dropdown or help text listing the reasons for **zero wages**,
with their numeric codes, and which ones require a last working day.
*What I need:* a screenshot of the full list, codes visible.
*Why:* `domain/payroll/esic.py` deliberately refuses to invent these and
withholds the file until the CA supplies one. With the real list we can offer
the CA a correct dropdown instead of a blank field — and that refusal becomes a
feature rather than a gap. This is on the "human has to supply it" table in
`CLAUDE.md`; you would be closing it.

**3. The EPFO ECR upload screen, post-revamp.**
`https://unifiedportal-emp.epfindia.gov.in` → ECR/Returns → ECR Upload.
*What I need:* the screen showing the **file-format instructions** (field count,
separator, extension), the **return-type selector** (Regular / Supplementary /
Revised), and the wage-month dropdown. Plus, if visible, the Due Deposit Balance
Summary showing how 7Q and 14B are presented.
*Why:* confirms the format is genuinely unchanged (we believe 11 fields, `#~#`,
`.txt`) and tells us exactly what F3's handoff screen must mirror.

### Tier 2 — changes a money decision, not a code decision

**4. `https://test-dev.tdscpc.gov.in`** — the landing page, and whatever an
"About" or "Register" link shows.
*What I need:* enough to tell whether this is a **real developer programme you
can apply to** or an internal test host. One screenshot of the landing page is
probably enough.
*Why:* it is the only lead anywhere toward a TDS filing API. If it is real, it
changes §4.5. If it is an internal host, I close the lead and stop mentioning it.

**5. `https://www.incometax.gov.in/iec/foportal/help/eri/registration`**
*What I need:* the **ERI types** (Type 1 vs Type 2), the **fee**, whether a
**bank guarantee** is required and how much, and the document checklist.
*Why:* ITR filing through the software runs entirely through this, and Email 1
in §10 exists only because I could not read this page.

**6. The GSTN GSP eligibility document** — search `gstn.org.in` for the GSP /
eligibility page, or try
`gstn.org.in/assets/mainDashboard/Pdf/eligibility-batch-5.pdf`.
*What I need:* the **eligibility criteria**, especially any **turnover or net
worth** threshold, and whether applications are currently open.
*Why:* the uploaded research claims ₹50 lakh; I could not corroborate it. This
is the single number most likely to decide whether the GSP route is open to a
firm your size.

**7. The Third Party Software Utility Developer registration page** on
`incometax.gov.in` (Downloads / e-Filing utilities → the `SW########` number).
*What I need:* the application form or the user manual PDF — the part listing
**prerequisites and what the registration entitles you to**.
*Why:* §6 Wave 0 says this one is self-service and available now. It is the
cheapest real step in the whole document and I would like to be sure of it
before you spend an afternoon on it.

### Tier 3 — confirms §11, cheap to do

**8.** `https://blog.saginfotech.com/roc-software-handle-mca-ver-3-forms-filing`
and `https://saginfotech.com/GenCompanye-filer.aspx`
*What I need:* the paragraphs describing **how a form reaches the MCA portal** —
specifically whether the software logs in, and whether the OTP is typed by the
user.
*Why:* mechanism B in §11.1 rests on one summarised sentence.

**9.** `https://razorpay.com/docs/payroll/statutory-compliance/` and the FAQ page.
*What I need:* anything stating **which credentials the customer must provide**
for PF, ESI, PT and TDS, and any wording about acting on the customer's behalf.
*Why:* §11.3 turns on this. If Razorpay turns out to have some arrangement I
have not imagined, I want to know before I write them off.

**10.** `https://www.greythr.com` — their EPFO/ECR help page.
*What I need:* the sentence about the ECR file and uploading to the EPFO portal.
*Why:* it is the load-bearing quote of §11. Worth having first-hand.

### Tier 4 — tidies statutory facts we already hold

**11.** The Maharashtra PT notification of **28-02-2026** amending **Rule 11(3)**
— `mahagst.gov.in`, Acts & Rules / Notifications.
*Why:* F5 needs the real due date before it writes one down.

**12.** Odisha's PT repeal (reported effective **01-04-2026**) and Punjab's
Development Tax — the state notifications.
*Why:* would let us correct the list of levying states in
`domain/payroll/professional_tax.py` from twenty-two to the true number.

**13.** `mca.gov.in` → MCA Services → **XBRL** → validation tool.
*What I need:* the **current version number and its date** — we hold V5.0,
July 2025.
*Why:* a taxonomy change is a silent break in `domain/income_tax/xbrl_service.py`.

### How to send them

Whatever is easiest — a screenshot is fine, the file itself is better for item 1,
and for a long page the section heading plus the paragraph is enough. **If a page
is behind a login you would rather not screenshot** (items 1, 2 and 3 all need an
employer login), say so and skip it; I will design F1 to read the template the
CA uploads rather than assuming its shape, which is the better design anyway and
was going to be my fallback.

And if a page turns out to say something different from what is in this
document — that is the most valuable outcome of the exercise, not a problem.
Send it and I will correct the document and say what it changes.
