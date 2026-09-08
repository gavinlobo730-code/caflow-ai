# Getting permission to file

What to apply for, in what order, what it costs, and what each one unblocks.

Confidence grades and the sourcing caveat: see `00-how-to-read-this.md`. That
caveat applies to this file in full, and the grades here are the stricter set the
7 September 2026 research pass adopted:

| Grade | Means |
|---|---|
| `[S-gov]` | a search engine summarised a document at an **official** URL, and the URL is recorded here |
| `[S]` | trade press, a vendor's documentation, or a professional firm's note |
| `[U]` | wanted and not found, or sources contradict each other |

**No `[P]` is awarded anywhere in this file.** I read no primary source.

---

## 0. The network, tested again, and why that matters to the reader

I did not take `00-how-to-read-this.md` on trust. Three tests, this session:

```
curl https://example.com               →  CONNECT tunnel failed, response 403
curl https://www.incometax.gov.in/     →  CONNECT tunnel failed, response 403
curl https://www.gst.gov.in/           →  CONNECT tunnel failed, response 403
```

The agent proxy logs all three as `connect_rejected — gateway answered 403 to
CONNECT (policy denial or upstream failure)`. `WebFetch` on `www.gst.gov.in`
returns `EGRESS_BLOCKED` from the tool itself. **`WebSearch` works**, because it
runs server-side and returns somebody else's summary of a page I cannot open.

So the shape of this document's evidence is: *a search engine has read
`gstn.org.in/assets/mainDashboard/Pdf/eligibility-batch-5.pdf` and told me its
title; I have not read a line of it.* Where that matters — and on money and
eligibility it always matters — the section says so and §8 lists the URL.

**One consequence worth stating before the owner spends anything.** Every figure
in §3's cost columns is either stale on its face, absent from public sources, or
single-sourced. The document is reliable about *which door to knock on* and
*whose signature is required*, and it is weak about *what it costs*. Those are
different qualities of claim and they are marked differently throughout.

### What this file adds to `02`, `03` and `04`

Those three answer "what is the last mile?". This one answers "what do I apply
for?", and in doing so it corrects or sharpens four things:

1. **The `SW########` probably does NOT come with ERI registration.** There is a
   separate e-filing portal user category, **Third Party Software Utility
   Developer**, with its own official user manual. `[S-gov]` See §3.4. If that
   is right it is the single cheapest unblock available and it is available now.
2. **The "4 Indian static IPs" constraint in `03` §1 came from the *External
   Agency* manual, and External Agency is a category PracticeSync cannot join** —
   it is for Central/State Government departments, approved undertaking agencies
   and RBI-approved banks. `[S-gov]` The constraint is real for **NIC e-invoice
   production** (4 static IPs, independently sourced) — whether it binds ERIs
   verbatim is now more open than `03` implied, not less.
3. **NIC issues e-invoice API credentials to "GSPs, ERPs and ECOs"**, not only to
   GSPs and ₹500-crore taxpayers. `[S]` An **ERP** category exists, and
   PracticeSync is plausibly one. That reopens a door `02` §5 recorded as
   GSP-only below ₹500 crore.
4. **TRACES 2.0 went live 1 April 2026**, and the CPC-TDS developer portal that
   `03` §4 flagged as its highest-value lead now has a little more corroboration
   — an official `gov.in` support address, organisation registration, sandbox
   and production credentials. It still has **no production URL and no published
   scheme**. `[S]`/`[U]` See §3.5; it is also my least confident claim.

Also worth recording because it changes a precondition: `01-what-exists-today.md`
§6 says a second filing-demo implementation (`components/DemoFilingModal.tsx`,
`lib/filing/demoFiling.ts`) is still live. **It is not — both files are gone**,
and `apps/web/app/deadlines/page.tsx:216` now carries a comment saying so.
`01` §6 is stale. The "delete the demo" precondition in §6 below is therefore a
single-implementation deletion.

---

## 1. The one-page answer

Read this table and then read only the sections you are about to spend money on.

| Filing | Channel | Registration that gates it | Whose credential | Can software complete the act? |
|---|---|---|---|---|
| **GSTR-1 / IFF** | GSTN API via **GSP** | GSP licence (ours) **or** an ASP sub-licence from a GSP (ours) + the client's Manage API Access consent | **Both.** Licence ours; the API consent and the signature are the **client's** | **No** — taxpayer signs (DSC for company/LLP, EVC otherwise) |
| **GSTR-3B** | same | same | same | **No** |
| **GSTR-9** | same; FILE via API reported available `[S]` | same | same | **No** |
| **GSTR-9C** | `[U]` — assume portal only | — | client's, plus the certifying CA's DSC | **No** |
| **ITR** | ITD ERI **Type 2** APIs | **ERI Type-2** (ours) **+ `SW########` software-provider id** (ours) | Registration ours; **verification is the taxpayer's and cannot be delegated** (s.140) | **No** — transmit yes, complete no |
| **TDS statements** (24Q/26Q/27Q → 138/140/144) | Today: RPU → FVU → upload at incometax.gov.in under **TAN login** | None for the file itself; the TAN login is the deductor's | **Client's** (the deductor's TAN, and their DSC/EVC) | **No** today. Possibly yes if the CPC-TDS API is real — §3.5 |
| **Form 16 → 130, 16A → 131** | TRACES generation only | — | — | **Never.** No registration changes this |
| **EPFO ECR** | Employer uploads `.txt` on the Unified Portal | None exists | **Client's** (establishment login) | **No** |
| **ESIC monthly contribution** | Employer uploads Excel at esic.gov.in | None exists | **Client's** | **No** |
| **MCA forms + AOC-4 XBRL** | Human on MCA21 V3 | None exists | **Client's director's DSC** | **No** |
| **e-invoice IRN** | NIC IRP API | NIC API credentials as **GSP / ERP / ECO** (ours), or the client's own above the turnover line | Credentials ours; the GSTIN is the client's | **YES** — the IRP signs the IRN; there is no taxpayer signature step |
| **e-way bill** | NIC EWB API | Same NIC route; the taxpayer picks a **GSP from a dropdown** | same | **YES** |

**The two rows that say YES are the whole strategic finding of this document.**
e-invoicing and e-way bill are the only statutory outputs where software can
complete the act end to end, because they are machine-facing by design and carry
no taxpayer signature. Everything else ends with a named human or has no channel
at all.

---

## 2. What is decided by paperwork and what is decided by law

Before the registrations, the distinction that stops wasted effort. Three
different things block the last mile and only one of them is buyable:

- **A licence or empanelment** — GST returns, ITR. Money and time solve it.
- **A signature the law assigns to a named person** — s.140 verification of an
  ITR, Rule 26 GST authentication, a director's DSC on AOC-4. **No licence
  removes this.** The best achievable product is "we prepare, they sign, we
  record what happened".
- **No channel at all** — MCA, EPFO, ESIC. Nothing to apply for, nothing to buy,
  no partner to go through. The ceiling is a perfect file and a human with a
  browser.

`04-mca-epfo-esic.md` §0 already says the third. This file adds that the second
is the more common blocker, and it is the one most often mistaken for the first.

---

## 3. Filing by filing

### 3.1 GST returns — GSTR-1, GSTR-3B, GSTR-9, GSTR-9C

**Channel.** Three tiers, unchanged: `taxpayer/CA → ASP (us) → GSP (licensed) →
GSTN`. Specifications are public at `developer.gst.gov.in/apiportal/`; production
credentials are a licence key GSTN issues only under a signed contract. `[S]`
Multiple restatements agree that **to reach the GST APIs you must be either a GSP
or an ASP riding a GSP's sub-licence** — there is no taxpayer-direct returns API
at any turnover. `[S]`

**Registration.** *GST Suvidha Provider* (GSTN empanelment, contract, licence
key) or an *ASP* arrangement, which needs **no empanelment at all** — you contract
commercially with a GSP and they generate your client-id/secret as a sub-licence
from their own. `[S]`

**Whose credential.** Split, and this is the part product design keeps getting
wrong:

- the **GSP/ASP licence is ours**;
- the **per-GSTIN API consent is the client's** — GST portal → My Profile →
  Manage API Access → Yes, with a duration between **6 hours and 30 days**,
  granted by OTP, and terminable by the taxpayer at any moment `[S]`;
- the **signature is the client's**. Under Rule 26 a registered person under the
  Companies Act — and, per every 2026 source seen, an **LLP** — must authenticate
  by **DSC**; proprietorships, partnerships and HUFs may use EVC. `[S]` The
  COVID-era provisos allowing companies EVC were date-bounded (one source gives
  27 April – 31 August 2021). Sources still conflict, but the 2026 weight is on
  *DSC still mandatory for companies and LLPs* — which is the answer that costs
  more, so plan for it.

**And since 29 September 2025 the consent is announced and revocable.** GSTN's
taxpayer advisory on *Transparency of Data Access via GSP/ASP* `[S-gov]`
(`https://tutorial.gst.gov.in/downloads/news/taxpayer_advisory_on_transparency_of_data_access_via_gsp_api.pdf`,
not fetched) confirms that every OTP consent triggers an email and SMS to the
authorised signatory **naming the ASP**, and that the taxpayer gets a dashboard
listing active ASP consents with a revoke button. Being an ASP is a named,
revocable relationship with each client, not an implementation detail.

**Cost and time.** *Not found* for the GSP licence itself — **there is no public
price list for anything in this tier.** What was found:

| Item | Figure | Grade |
|---|---|---|
| GSTN's own charge for taxpayer registration lifecycle | nil | `[S]` — and irrelevant; it is not the GSP contract |
| GSP → ASP per API call | 10 paise – ₹1 | `[S]`, single undated source (carried from `02` §7). One GSTR-1 filing is many calls |
| GSTN → GSP cost recovery | free in year 1 | `[S]`, describes 2017-18, almost certainly stale `[U]` |
| Integration timeline | 15–25 business days | `[S]` vendor marketing; excludes contracting and legal, which is the long pole |
| GSP licence fee | **not found** | `[U]` |

**Eligibility, and the sentence that matters.** GSP criteria have loosened across
five batches: batch 1 wanted **₹5 crore paid-up capital and ₹10 crore average
turnover over three years**; batch 2 relaxed to **₹2 crore and ₹5 crore** `[S]`.
Non-financial criteria are consistent and harder: Indian company in IT/ITeS/BFSI;
**backend infrastructure in India**; capacity for **≥ 1 lakh GST transactions per
month**; a data privacy policy; IT Act compliance; three years of audited
accounts; **at least 60% in each section and 70% overall in a technical
evaluation** `[S]`; and an **affidavit undertaking that data sourced from the GST
System will not be used to sell financial products to taxpayers, directly or
through subsidiaries or parents** `[S]`.

A batch-5 eligibility PDF exists at an official URL
(`https://www.gstn.org.in/assets/mainDashboard/Pdf/eligibility-batch-5.pdf`,
`[S-gov]`, **not fetched**). `02` §1 records a claim that batch 5 asks only ₹50
lakh average turnover. **Four differently-phrased searches this session failed to
surface that figure from any source.** It is neither confirmed nor refuted —
treat it as `[U]` and read the PDF before it enters a plan.

> **So, plainly: a startup does not qualify as a GSP directly, and applications
> appear to be closed anyway.** Two independent secondary sources state that
> GSTN has stopped accepting new GSP registrations and that "there is only one
> option — become an ASP". `[S]` No batch 6 was found. **The route for
> PracticeSync is ASP under an existing GSP, and that needs no empanelment,
> no net worth and no application window — only a commercial contract.**
>
> The one caveat worth naming: several full-suite GSPs (ClearTax, IRIS, Cygnet,
> Masters India) sell practice-management products that compete with this one.
> Choose the counterparty accordingly, and read the data clauses.

**Code seam.** `apps/api/domain/gst/portal_service.py` — the abstract
`GSTPortalProvider` with one `ManualGSTProvider`. Its sharp edge is live:

```python
def get_provider(provider_name: str = "manual") -> GSTPortalProvider:
    return ManualGSTProvider()
```

It takes a name and ignores it. Today harmless; the day a GSP provider exists, a
caller asking for it by name silently gets manual data and no error. **Wire the
switch in the same commit that adds the provider.** Also
`apps/api/domain/gst/gstr1_builder.py` (targets GSTN API spec v1.3 of July 2023,
likely stale — get the current version from the GSP under NDA) and
`apps/api/services/gst_filing_record_service.py`, whose docstring already says it
is *"the row a GSP integration will later fill in from the portal's response
rather than from a CA typing it"*. That shape does not need changing.

### 3.2 e-invoice IRN — the one that is open today

**Channel.** Direct API to an IRP. Six authorised IRPs, `einvoice1`–`einvoice6`;
NIC runs 1 and 2. `[S]`

**Registration.** `https://einv-apisandbox.nic.in/` — **self-service, free, any
GSTIN, no empanelment**. Register, get Client Id and Client Secret for the
sandbox, no IP whitelisting. `[S]`

Production is where the gate sits, and the finding here is better than `02` §5
recorded: **"Client Id and Client Secret are provided to Service Providers like
GSPs, ERPs and ECOs"** `[S]`. There is an **ERP** category. The production
process for it: test every API in pre-production with a minimum number of success
and failure cases, file a **Test Summary Report** and email it to
**`support.einv.api@gov.in`**, submit **up to four static IPs** for whitelisting,
and wait — one source says 4–5 days for verification and whitelisting. `[S]`
Testing must be done by interfacing the APIs with a taxpayer's actual
ERP/accounting application, not through NIC's online test tool. `[S]`

**Whose credential.** The Client Id/Secret would be **ours** as an ERP. The
GSTIN, and the taxpayer's own username/password on the e-invoice portal, are the
**client's**. There is **no taxpayer signature** — the IRP digitally signs the
IRN. That is why this row can say YES.

**Cost and time.** Sandbox: free. Production: no fee found for the ERP route
`[U]`; the cost is the static-IP hop (see §4, wave 1) and the test effort.

**Eligibility.** No net-worth or turnover bar was found **for the ERP category**
`[U]`. What is well-sourced is the *taxpayer* ladder, and sources contradict each
other on it: one says direct taxpayer API access starts at **₹500 crore** with
₹5–500 crore going through a GSP/ERP's client-id; another says **₹10 crore**;
another says ₹5–10 crore got access from 1 January 2023. `[S]`/`[U]` **That
conflict does not block us**, because the ERP category is a different door — but
it does mean the client-facing copy must not state a threshold from this
document.

Separately: **TLS 1.2 minimum**, adherence to GoI IT security standards and the
IT Act 2000, and NIC reserves the right to block or suspend for malicious
traffic. `[S]`

> **This is the cheapest real integration available and the only one that needs
> no commercial conversation to start.** `02` §5 already said the sandbox is
> open; what is new is that the *production* route has a category we may fit,
> not only "GSP or ₹500 crore".

**Code seam.** `apps/api/routers/einvoice.py`. Today
`POST /records/{id}/irn-generated` **records** an IRN a human obtained. A real
integration is a new endpoint beside it, not a repointing of that one. Note the
30-day IRN reporting limit for AATO ≥ ₹10 crore (an IRP validation, not advice,
and it reaches credit and debit notes) and the advisory dated 17 June 2026 making
**Ship-to GSTIN mandatory in the IRN and e-Way-Bill-by-IRN APIs from 1 August
2026** `[S-gov]`
(`https://tutorial.gst.gov.in/downloads/news/advisory_einvoice_api_ewb_by_irn_approved.pdf`,
not fetched) — anyone integrating needs that before writing the payload.

### 3.3 e-way bill

**Channel.** NIC, not GSTN, with its own developer portal at
`https://docs.ewaybillgst.gov.in/apidocs/`. `[S-gov]`

**Registration.** Same NIC family as e-invoice. The taxpayer-side step is
explicit and is a product surface: after production access, the taxpayer logs in
to the EWB system, chooses **Registration → For GSP**, **selects a GSP from a
dropdown**, validates an OTP, and creates a username and password. `[S]`
Companies above ₹500 crore have both direct API access and the GSP route;
₹100–500 crore have the GSP route only. `[S]`

> **The dropdown is the constraint.** If our name is not in NIC's list, a client
> cannot select us — which means the EWB path in practice runs through whichever
> GSP we contract with, under their name, and the client will see that name.
> The same is true of the GST consent dashboard (§3.1). Plan the client
> conversation around it; do not discover it at onboarding.

**Whose credential.** Client-id/secret ours (or the GSP's); EWB username and
password the **client's**. No signature.

**Cost, time, eligibility.** Not separately published; bundled into the GSP
contract in every case examined — the same GSP typically serves GSTN returns,
NIC e-way bill and the IRP under one agreement. `[S]`

**Code seam.** `apps/api/routers/eway_bill.py`, same record-only shape.

### 3.4 ITR — two registrations, not one

This is the section that changed most.

**Channel.** ITD ERI APIs. There is no public developer portal and no open
sandbox; the specifications are a static page of PDFs at
`https://www.incometax.gov.in/iec/foportal/api-specifications` — Login, Add
Client, Prefill, Submit Flow, e-Verify, ITR-V — **every one dated November 2021**
`[S-gov]` (e.g. `.../2021-11/ERI%20API%20Specification_v1.1.pdf`,
`.../2021-11/API_SubmitFlow_v1.1.pdf`, not fetched). Given TRACES 2.0 and the
2025 Act both landed in 2026, assume a newer spec exists behind an ERI login and
do not plan against the 2021 PDFs.

**Registration #1 — e-Return Intermediary, Type 2.** Type 2 is "builds its own
software and files through ITD APIs", which is the target. Registration is now
done **on the e-filing portal itself**: Register → **Others** tab → Category
**e-Return Intermediary** → Register as New Applicant → choose the ERI type →
enter PAN/TAN → OTP. `[S-gov]`
(`https://www.incometax.gov.in/iec/foportal/help/eri/registration`, not fetched.)
That is a materially different picture from the cheque-to-NSDL story in `03`, and
it is the first thing to confirm on an unblocked network.

*Eligibility*: a company with **net worth ≥ ₹1 crore**, or a **firm of Chartered
Accountants, Advocates or Company Secretaries** with a valid PAN. `[S]` A
**due-diligence certificate from a licensed CISA or ISA professional** is a
required document. `[S]`

> **The structuring decision, and it must be made before anyone applies.** If the
> operating company does not clear ₹1 crore net worth, the CA-firm route is open
> — but **the ERI registration, the client consent and the statutory obligations
> then belong to that firm, not to the product company.** Every taxpayer whose
> return goes out does so under that firm's ERI id. That is a partnership
> structure, not a paperwork detail, and unwinding it later means re-consenting
> every client. Decide it deliberately.

*Cost*: **both published figures are stale on their face.** ₹27,245 = ₹25,000
refundable security deposit + ₹2,245 "inclusive of service tax currently 12.24%"
— 12.24% dates to about 2007-08. A separate ₹4,600 figure is ₹4,000 + 15% service
tax, the 2015-17 rate. Service tax was replaced by GST in 2017. `[S]` **Do not
put either in a plan; write "₹5k–₹30k order of magnitude, confirm on the
portal".** Registration is valid **two years**, renewed with effect from 1 April.
`[S]`

*Time*: no published SLA and no practitioner account found `[U]`. The path has
at least three serial, manually-reviewed gates — application and documents, the
ISA/CISA certificate, and departmental approval. **Plan in quarters.**

**Registration #2 — the `SW########`, and it is probably separate.** The ITR JSON
schema's `CreationInfo` block carries `SWVersionNo`, `SWCreatedBy`,
`JSONCreatedBy`, `JSONCreationDate`, `IntermediaryCity` and `Digest`, and the
`SW*` fields hold an id like `SW20000709` / `SW19001101` / `SW10002146` issued to
approved third-party software. **A return without an approved software id is
automatically rejected.** `[S]`

The e-filing portal has a **user category "Third Party Software Utility
Developer"** alongside Individual, HUF, External Agency, Chartered Accountants
and Tax Deductor and Collector, and there is an official user manual for
registering under it: `[S-gov]`

```
https://www.incometax.gov.in/iec/foportal/sites/default/files/2020-08/User_Manual_Third-Party_Utility_Provider.pdf
```

**Not fetched.** No source explicitly says "this registration issues the
`SW########`", so the link between the two is my inference — but the category
exists, the manual exists, and the id demonstrably exists, which is three-quarters
of the case. If it holds, it is the **cheapest unblock in this whole document**:
a self-service portal registration that turns a live `raise` into a config
change.

**Registration #3 that we should NOT chase — External Agency.** `03` §1 records a
UAT / 4-Indian-static-IP / TLS-1.2 process, flagged as "verify it applies to
ERIs verbatim". It does not obviously apply, because **External Agency
registration is for Central and State Government departments, approved
undertaking agencies and RBI-approved banks** `[S-gov]`
(`https://www.incometax.gov.in/iec/foportal/help/register-for-efiling-external-agency`,
not fetched). The UAT mechanics are real for that category — IPs emailed to
`efilingwebmanager@incometax.gov.in` with a set subject line, temporary test
credentials, a final UAT report for competent-authority approval — but **they are
not evidence about the ERI path.** `03`'s flag was right; the answer is now
"probably a different category", not "probably applies".

**Whose credential.** The ERI registration is ours (or the CA firm's). **The
verification is the taxpayer's and cannot be delegated** — s.140, and the ITD
says so flatly: *"Any request submitted by ERI on your behalf will not be
completed if it is not verified by you."* `[S]` Prefill is consent-based: the ERI
submits the request, the OTP goes to the **taxpayer's** registered mobile, and the
prefill data arrives only after the taxpayer enters it. `[S-gov]` The taxpayer
never shares a portal password with the ERI — that is the design, and it should
be the product's design too.

**Three clocks the product must model**, all client-owned: ERI client validity
**7 days to 1 year** (extendable by up to 6 months); every ERI service request
must be verified by the taxpayer **within 7 days** or it lapses; and an ITR must
be e-verified **within 30 days** of filing or it is treated as not filed
(Notification 5/2022 DGIT-Systems, effective 1 August 2022). `[S]`

**Code seam.** `apps/api/domain/income_tax/itr_json.py`. It already refuses in
exactly the right place:

```python
if not software_provider_id():
    raise SoftwareProviderNotRegistered(...)
```

reading `ITR_SOFTWARE_PROVIDER_ID`, which is already declared in `render.yaml`
and enforced in both directions by `tests/test_render_manifest_matches_code.py`.
Note the second refusal behind it — `ReturnIncomplete` — is *not* a registration
problem: `ITRPayload` carries tax figures and no `PersonalInfo`, `FilingStatus`,
`Verification` or bank details, so obtaining the `SW########` unblocks the field
but does not by itself produce a filable return. Also
`apps/api/domain/income_tax/schemas/` and `itr_schema.py`'s `SCHEMA_FILES` — the
hand-download step in CLAUDE.md §2 does not go away when the registration lands.

### 3.5 TDS statements — 24Q/26Q/27Q, and 138/140/144 from 01-04-2026

**Channel today.** Unchanged and manual: prepare in the **RPU** (a free Java
desktop GUI from Protean/TIN), validate with the **FVU** to produce a `.fvu`
file, then upload at incometax.gov.in under the **TAN login**, authenticating
with **DSC or EVC**, and receive a token number. TRACES 2.0 processes in about
2–4 hours. `[S]` **RPU and FVU are still in the loop in 2026** — TRACES 2.0 did
not remove them. `[S]`

**Whose credential.** All of it the **client's**: the TAN, the e-filing login for
that TAN, and the DSC or EVC. There is nothing here for us to register for on the
current path. That is why `apps/api/domain/payroll/form24q.py` emits a working
paper with `# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Not an FVU file` rather
than attempting the real thing.

**The lead that could change all of it.** `03` §4 called the CPC-TDS developer
portal its highest-value lead. This session adds corroboration and does not
close it:

- **TRACES 2.0 went live 1 April 2026** at `traces.tdscpc.gov.in`. `[S]`
- A CPC-TDS developer portal offers **OpenAPI 3.0 TDS Statement Filing APIs for
  Forms 24Q, 26Q, 27Q and 27EQ**, covering data capture, validate, submit,
  submit-status and error download, described as *"built for ERPs, payroll
  products and enterprise platforms"*. `[S]`
- It has **organisation registration, application creation, sandbox and
  production credentials, and administrator activation** — one source says most
  approvals complete in **1–24 hours** — and an official support address,
  **`suvidha-support@tdscpc.gov.in`**. `[S]`
- Access controls are described as restricting **"internal or sensitive APIs"**
  to authorised **TSP** users. `[S]`

And what is still missing, which is why nobody should plan against it yet:

- **Every result still points at `https://test-dev.tdscpc.gov.in/`** — literally
  a development host. `[S-gov]` by URL, `[U]` in substance. No production
  developer-portal URL was found in six searches.
- **No scheme, no criteria, no CBDT notification, no announcement** defining what
  a "TDS Suvidha Provider" is or how one is empanelled. Four differently-phrased
  searches returned GST Suvidha Provider material instead. `[U]`

> **Two emails would settle it**, and they cost nothing:
> `suvidha-support@tdscpc.gov.in` asking (a) whether the developer portal is
> live in production and at what URL, and (b) what the TSP category requires. If
> the answer is yes, the direct-tax side flips from "generate a file, a human
> uploads it" to "integrate an API subject to empanelment", and it would be the
> first real filing API on the direct-tax side.

**One thing the registration would not fix.** `apps/api/domain/tds/vocabulary.py`
deliberately does not hold the s. 393 **payment-code table**, and an API makes
that worse rather than better: a wrong payment code is *accepted* and then wrong.
The 7 September research also found the range is **1001–1092, not 1001–1067** —
1068–1092 are the s. 394 TCS codes, so **anything that range-checks a code at
≤1067 rejects every valid TCS code.** `[S]` The table remains a human step.

### 3.6 TDS certificates — Form 16 → 130, Form 16A → 131

**There is no registration, and there will not be one.** Both parts of Form 16
must be generated and downloaded from TRACES — CBDT Circular 04/2013 for Part A,
CBDT (Systems) Notification 09/2019 for Part B — and a certificate issued in any
other format is invalid **even with accurate data**. `[S]`

Under the 2025 Act it is **stricter**: Rule 215(1) of the Income-tax Rules 2026
read with s. 395(4)(b) is reported to require **the whole of Form 130** to come
from TRACES, and it **cannot be issued at all until the quarterly Form 138 has
been filed and processed**. `[S]`

> Any roadmap item shaped "generate Form 130" is not buildable by anyone. The
> buildable shape is: get Annexure II of the 138/24Q exactly right → the return
> is filed and processed → fetch and distribute the TRACES-issued certificate.
> `apps/api/routers/payroll.py::form_24q_annexure_ii` already says
> *"THERE IS NO FORM 16 GENERATOR HERE, AND THERE SHOULD NOT BE."* Leave it.

### 3.7 EPFO ECR

**No employer API exists, and there is no programme to join.** `[S]` Searched
again this session against EPFO 3.0 coverage: the announced features are
member-side (auto-claims, UPI/ATM withdrawal) plus employer conveniences —
**auto-computed ECR carried forward from the previous month, and OTP-based
authentication replacing DSC for login and ECR submission**. `[S]` Neither is an
API. One further 2026 change worth knowing: **from 11 March 2026 the portal
serves only summary-level ECR downloads**, dropping employee-wise detail, so the
product's own records become the only per-employee history. `[S]`

**Whose credential.** Entirely the **client's** establishment login.

**Code seam.** `apps/api/domain/payroll/ecr.py` (the file; format unchanged —
`.txt`, 11 fields, `#~#`), `apps/api/domain/payroll/ecr_sequence.py` and
`public.epfo_ecr_filings` (migration 335) for the month sequence and return type.
Nothing here needs a registration; the honest ceiling is already built.

### 3.8 ESIC

**No API, no developer portal, no specification, no programme.** The most clearly
closed of the three. `[S]`, and a fifth search this session returned only
contribution-rate content. Employer logs in with the 17-digit code, files the
monthly contribution, generates a challan, pays.

**Whose credential.** The **client's**.

**Code seam.** `apps/api/domain/payroll/esic.py`, whose refusal to invent numeric
reason codes is independently confirmed and, given ESIC's October 2025 circular
on zero-day filings, more right than when it was written.

### 3.9 MCA — forms and AOC-4 XBRL

**No filing API, no developer portal, no partner programme, nothing to apply
for.** `[S]`, re-searched this session against 2026 MCA V3 coverage: the V3
material describes a better *human* experience — a centralised dashboard across
client companies, prefill, real-time validation — and MCA's *inbound* integrations
with Income Tax, GST, EPFO and ESIC at incorporation. **That is MCA calling them.**

**Whose credential.** The **client's director's Class 3 DSC**, associated on V3
under MCA Services → DSC Services → Associate DSC. Where a form needs several
signatures each signatory affixes their own. A Class 3 DSC costs roughly
**₹850–₹4,500** depending on validity and whether a token is included `[S]` — the
client's cost, not ours, and worth knowing because it is the cheapest item in
this document and the one that most often stalls a filing.

**The one machine-facing artefact is the XBRL instance**, and MCA addresses
software vendors about it directly. The current validator is **MCA XBRL
Validation Tool V5.0, released July 2025**, covering AOC-4 XBRL (C&I and Ind AS)
and CRA-4 XBRL (Costing) `[S-gov]` — MCA's own announcement, seen via its social
posts and `https://www.mca.gov.in/XBRL/MCA-validation.html`, not fetched. The
vendor note points at a schema URL under `mca.gov.in/V3XBRL/` `[S]`, and one
vendor changelog dated 6 August 2026 reports **no change in the C&I 2016
(non-Ind-AS) taxonomy** `[S]`. No version beyond V5.0 was found.

**Code seam.** `apps/api/routers/xbrl_engine.py` and
`apps/api/domain/income_tax/xbrl_service.py` (whose `http://www.mca.gov.in/...`
strings are XML **namespace URIs**, never dereferenced — do not "fix" them), plus
`apps/api/routers/mca_workspace.py`. Version the taxonomy/schema URL the way the
rate registries are versioned: a `LATEST_VERIFIED` marker plus a hand-download
step.

---

## 4. The sequenced plan

Ordered by **lead time × how much it unblocks**, and deliberately front-loaded
with things that are free, self-service and reversible.

### Wave 0 — start this week. No money, no commitment, no counterparty.

| # | Action | Unblocks | Why first |
|---|---|---|---|
| 1 | Register as **Third Party Software Utility Developer** on the e-filing portal; obtain the `SW########` | `itr_json.py`'s `SoftwareProviderNotRegistered`; a config change, not a code change | Self-service, PAN + OTP, no net worth. **If §3.4 is right this is the highest ratio of unblock to cost in the document.** Read the user manual first |
| 2 | Register on **`einv-apisandbox.nic.in`** with any GSTIN; build and test the IRN rails | `routers/einvoice.py` — the one filing software can complete | Free, no empanelment, no commercial conversation. `02` §5's point, still true |
| 3 | Email **`suvidha-support@tdscpc.gov.in`**: is the CPC-TDS developer portal live in production, at what URL, and what does the TSP category require? | Potentially the entire direct-tax filing side | Two emails against a possible step-change. Costs nothing to ask and closes a `[U]` that has been open since the first research pass |
| 4 | Read `gstn.org.in/.../eligibility-batch-5.pdf`; email GSTN asking whether GSP applications are open | Settles build-vs-buy on GST | Free; and "closed" is a perfectly good answer that saves a quarter of wasted effort |
| 5 | Fix `get_provider()` to honour its argument | Nothing today; prevents a silent-wrong-answer later | Ten minutes now, versus a class of bug this codebase has repeatedly had to unpick. Do it before the provider exists, not with it |

### Wave 1 — weeks to months. Small money, one real decision.

| # | Action | Unblocks | Note |
|---|---|---|---|
| 6 | **Decide the ERI entity**: product company (net worth ≥ ₹1 crore) or a CA firm | Everything downstream on ITR | **Decide before applying.** Whoever registers owns the client consents and the obligations, and switching later means re-consenting every client |
| 7 | Stand up an **India-hosted static-IP egress hop** for filing calls | NIC e-invoice production (≤ 4 static IPs, confirmed) and probably the ERI production path (`[U]` — see §3.4) | `apps/api` runs on Render in **Singapore** by design (`render.yaml` carries the measurements) and Render cannot move a service between regions. This is a deployment line item with a long tail that gates two separate registrations — **start it before either application completes**, not after one is approved |
| 8 | Open **GSP/ASP commercial conversations** — three or four vendors | GSTR-1, 3B, 9 | Ask specifically: current API version matrix; whether GSTR-9 can be *filed* not just fetched; GSTR-9C at all; the bulk file-based GSTR-2B path (the row API breaks past ~1,000 invoices); per-call and per-return pricing; what appears in the client's consent dashboard under our name; and the data-use clauses, given several GSPs compete with us |

### Wave 2 — quarters. Real money, serial manual gates.

| # | Action | Unblocks |
|---|---|---|
| 9 | **ERI Type-2 application** — documents, ISA/CISA due-diligence certificate, departmental approval | ITR transmission (never ITR completion — s.140) |
| 10 | **ASP contract signed**, sub-licence key issued, first client's Manage API Access consent captured | GST returns |
| 11 | NIC **e-invoice production credentials** — test summary report to `support.einv.api@gov.in`, IPs whitelisted | Live IRN generation |

### Never — recorded so nobody starts them

MCA, EPFO and ESIC filing integrations. **There is no registration, no
empanelment, no partner and no purchasable route.** The only interfaces are
undocumented private endpoints inside the portals, and driving those is out of
scope on exactly the grounds CLAUDE.md rules out net-banking screen-scraping. If
somebody proposes RPA against the EPFO portal, note that a documented case of
precisely that exists `[S]` and that it is the clearest available evidence *that
no API exists*, not a precedent.

### Why this order and not another

Waves 0 and 1 are not sorted by importance. GST returns are the biggest
commercial prize and sit at #8. The sorting is by **irreversibility and
information value**: items 1–4 cost nothing, commit to nothing, and each closes a
question the rest of the plan is currently guessing at. Item 7 is unglamorous
infrastructure sequenced early **only** because it gates two applications and
cannot be compressed once they are in flight. Item 6 is a structuring decision
that becomes expensive the moment an application is submitted under the wrong
entity.

---

## 5. What comes WITH the licence

A registration is not only an unlock. Each one attaches duties, and two of them
attach a suspension risk that the product must survive.

**As an ASP (no empanelment, but not no obligations).** You inherit the GSP's
contractual flow-downs, and since 29 September 2025 **you are named to every
client** in their consent notification and consent dashboard, with a revoke
button beside your name. `[S-gov]` Practical consequences: consent is expiring
(6h–30d), client-owned, and **revocable without telling you**. Model it as
first-class state that degrades gracefully; an integration that errors on a
revoked consent will look like a product fault.

**As a GSP (if ever).** Backend infrastructure in India; capacity for ≥ 1 lakh
transactions/month; a documented privacy policy; IT Act compliance; three years
of audited accounts; a technical evaluation to pass; and an **affidavit that GST
System data will not be used to sell financial products, directly or through
subsidiaries or parents**. `[S]` That affidavit is a real constraint on future
product lines, not boilerplate.

**As an ERI.** Verify the authenticity of the client's PAN and TAN; ensure the
return is filed in time and **verified** by the taxpayer; guarantee the privacy
of client data; honour the 7-day service-request window; renew every two years
from 1 April. `[S]` An ISA/CISA due-diligence certificate at application means an
external assessor sees the system.

**As an NIC ERP.** Adhere to Government of India IT security standards and the IT
Act 2000; TLS 1.2 minimum; **NIC reserves the right to block or suspend services
if malicious traffic is detected**. `[S]` A shared client-id means one client's
runaway retry loop is everyone's outage.

**Under DPDP, all of them.** Every registration widens the set of third-party
personal data flowing through the platform and adds processor relationships. See
`06-data-protection-dpdp.md`; substantive duties bite 13 May 2027, which is
inside the timeline of anything in wave 2.

**And the duty nobody plans for: revocation.** A GSP licence key, an ERI
registration and an NIC client-id can each be suspended, and a client's GST API
consent can be revoked in a single click at any moment. Every integration must
have a working manual path behind it on the day it is switched on — which,
conveniently, is exactly what the product does today and must not lose.

---

## 6. What must be true in the product before any of this is turned on

Non-negotiable, and none of it is optional per filing type.

1. **Idempotency, with the reference written before the call.** A
   double-submitted return is not a duplicate row; it is a second filing against
   a live portal. Record the intent and its reference **before** the request,
   check status **after** a timeout, and **never blind-retry**. Note that
   `apps/web/lib/api/index.ts` aborts at **45 seconds** (`45_000`) and the abort
   is deliberately never retried — a filing call must not live behind that abort
   at all. The recovery path is "ask the portal what happened", never "send it
   again".
2. **An explicit confirmation click, per return, every time.** Never a batch,
   never a scheduler, never a retry that resubmits. This is a CLAUDE.md "Code
   rules" entry and it gets stronger when filing becomes real, not weaker.
3. **The signature stays on the portal.** No EVC OTP field, no Aadhaar OTP
   capture, no stored portal password, whatever the field is labelled. The
   tokenised-handoff shape already exists in
   `apps/api/routers/engagement_sign_public.py` — 256-bit bearer token, every
   query constrained to the token's row, a client-safe projection, IST-dated
   expiry, an honest 503-vs-404 split — and a consent or signing request should
   follow it rather than invent a second one.
4. **Consent and expiry as model objects, not flags.** Three clock designs are
   now known and they are the same shape: GST API access (6h–30d, revocable,
   announced), ERI client validity (7 days–1 year) with a 7-day service-request
   window, and the 30-day ITR e-verification deadline. Build one design that
   carries all three, with a pending-verification queue and reminders.
5. **An audit trail written in the same transaction**, unswallowed —
   `apps/api/services/audit_service.py`, the discipline already used for journal
   deletions.
6. **Delete the demo for that flow.** `apps/api/services/filing_demo/` holds
   eight (`gstr1`, `gstr3b`, `gstr9`, `itr`, `tds_return`, `pf_ecr`, `esi`,
   `mca`). When a real channel exists for one of them it is a **new endpoint**
   and that flow is **deleted** — never repointed, because everything that makes
   it safe is the fact that it cannot file. `apps/web/scripts/one-filing-demo-and-the-kill-switch-reaches-it.test.ts`
   holds the one-implementation line, and every screen offering the wizard must
   probe `fetchFilingDemoCapabilities` first.
7. **`ENABLE_FILING_SIMULATION=false`** on any deployment that records a real
   filing. It defaults on today because this deployment records none. It is the
   kill switch, and it only reaches server-side flows — which is why the
   browser-side rival was deleted.
8. **Fix `get_provider()` in the same commit that adds a provider** (§3.1). Not
   after.
9. **A real filing must write the record the lock already reads.**
   `apps/api/services/gst_filing_record_service.py` builds the `filings` row that
   `journal_period_lock_reason` matches on, and its field-by-field notes explain
   which omissions make the lock silently skip a row. Fill that row from the
   portal's response instead of from a CA typing it; do not add a second table.

---

## 7. The decision table — what software can file at all

Kept separate from §1 because it answers a different question: *is this
automatable by anyone, however good the software?*

| Filing | Software can transmit | Software can complete | What blocks completion |
|---|---|---|---|
| e-invoice IRN | ✅ | ✅ | nothing — the IRP signs |
| e-way bill | ✅ | ✅ | nothing |
| GSTR-1 / IFF | ✅ via GSP | ❌ | Rule 26 — DSC (company/LLP) or EVC OTP to the **taxpayer's** phone |
| GSTR-3B | ✅ via GSP | ❌ | same |
| GSTR-9 | ✅ probable `[S]` | ❌ | same |
| GSTR-9C | `[U]` | ❌ | same, plus the certifying CA's own DSC |
| ITR | ✅ via ERI Type-2 | ❌ | **s. 140.** The ITD says an ERI request not verified by the taxpayer will not be completed. 30-day clock |
| TDS statement | ❌ today; `[U]` if the CPC-TDS API is real | ❌ | the deductor's TAN login and DSC/EVC |
| Form 16 → 130, 16A → 131 | ❌ | ❌ | **TRACES-generated only.** Circular 04/2013, Notification 09/2019; Rule 215(1) r/w s. 395(4)(b) is stricter still. **No registration changes this** |
| EPFO ECR | ❌ | ❌ | no employer API exists |
| ESIC contribution | ❌ | ❌ | no API exists |
| MCA forms / AOC-4 XBRL | ❌ | ❌ | no API; and the DSC is the client's director's |

Two readings worth taking away. **First**, the only fully automatable outputs are
the two the product currently only *records*, which is an argument for
sequencing them first. **Second**, six of the twelve rows cannot be completed by
anybody's software, so a competitor claiming end-to-end filing on those is either
driving a portal UI behind a captcha or overstating. That is useful in a sales
conversation and it is useful in a roadmap.

---

## 8. What to verify first on an unblocked network

Ranked by (how load-bearing) × (how weakly sourced). Every URL below was surfaced
by search and **not fetched**.

1. **Does the "Third Party Software Utility Developer" registration issue the
   `SW########`?** — the cheapest unblock in the document rests on an inference.
   `https://www.incometax.gov.in/iec/foportal/sites/default/files/2020-08/User_Manual_Third-Party_Utility_Provider.pdf`
2. **Is the CPC-TDS developer portal live in production, and what is a "TSP"?** —
   a step-change on the direct-tax side, sourced only to a `test-dev` host.
   `https://test-dev.tdscpc.gov.in/` and `https://test-dev.tdscpc.gov.in/help`;
   email `suvidha-support@tdscpc.gov.in`.
3. **Are GSP applications open, and what does batch 5 actually require?** —
   decides build-vs-buy on the largest revenue surface.
   `https://www.gstn.org.in/assets/mainDashboard/Pdf/eligibility-batch-5.pdf`
   (and `.../eligibility-batch-4.pdf` for the trend).
4. **Rule 26 — is DSC still mandatory for companies and LLPs?** — decides the
   addressable market for an EVC-only design. Carried over from `02` §9 and still
   contradicted between sources.
   `https://taxinformation.cbic.gov.in/` → CGST Rules → Rule 26.
5. **Current ERI fee, process and whether registration is open**, on the portal
   rather than from 2007-era figures.
   `https://www.incometax.gov.in/iec/foportal/help/eri/registration`
6. **Does the 4-static-IP / UAT process bind ERIs, or only External Agencies?**
   `https://www.incometax.gov.in/iec/foportal/help/register-for-efiling-external-agency`
   and `https://www.incometax.gov.in/iec/foportal/api-specifications`
7. **Has the ERI API spec moved since November 2021?** A frozen-since-2021 spec is
   implausible after TRACES 2.0 and the 2025 Act.
   `https://www.incometax.gov.in/iec/foportal/sites/default/files/2021-11/ERI%20API%20Specification_v1.1.pdf`
8. **The NIC ERP category** — is there an eligibility bar, and must the four
   static IPs be Indian? `https://einv-apisandbox.nic.in/onboarding.html`,
   `https://einv-apisandbox.nic.in/apicredentials.html`,
   `https://einv-apisandbox.nic.in/FaqsonAPI.html`
9. **Ship-to GSTIN mandatory from 1 August 2026** in the IRN and EWB-by-IRN APIs.
   `https://tutorial.gst.gov.in/downloads/news/advisory_einvoice_api_ewb_by_irn_approved.pdf`
10. **The GSP/ASP transparency advisory**, for the exact consent and revocation
    mechanics a product surface must match.
    `https://tutorial.gst.gov.in/downloads/news/taxpayer_advisory_on_transparency_of_data_access_via_gsp_api.pdf`
11. **Whether GSTR-9 can be filed via API, and GSTR-9C at all.** Ask the GSP under
    NDA; no public source settles it.
12. **The current MCA XBRL tool version and schema URLs.**
    `https://www.mca.gov.in/XBRL/MCA-validation.html`

Items 1–3 are the ones where a wrong answer costs a quarter. Items 4–6 are the
ones where a wrong answer costs a redesign.

---

## 9. The three claims in this file I would least like to be wrong about

Stated separately because someone is about to spend money.

1. **That the `SW########` comes from the Third Party Software Utility Developer
   registration** (§3.4). The category exists `[S-gov]`, the manual exists
   `[S-gov]`, the id exists and rejects returns without it `[S]` — but **no
   source connects the three explicitly.** The connection is mine. It is item 1
   in §8 for that reason.
2. **That the CPC-TDS filing API is a real thing one can register for** (§3.5).
   Every description of it is consistent and detailed; every URL is a `test-dev`
   host; no scheme, criteria or announcement exists anywhere I could reach. It
   would be the largest single unlock in the document and it may be a staging
   environment somebody left indexed.
3. **That GSP applications are closed and the ASP route is the only one** (§3.1).
   Two secondary sources say so plainly; against that, GSTN still publishes a
   batch-5 eligibility PDF, and no batch-6 announcement would be expected to
   reach trade press quickly. "Closed" and "not currently advertised" look
   identical from here.

A fourth, lower stakes but worth naming: **the e-invoice direct-API turnover
threshold is contradicted across sources** (₹500 crore / ₹10 crore / ₹5 crore).
It does not block the ERP route, but it must not appear in anything client-facing
until it is read from a notification.
