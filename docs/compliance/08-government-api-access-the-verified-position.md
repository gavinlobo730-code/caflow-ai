---
classification: Internal — for circulation
title: Government Filing Access
subtitle: What PracticeSync can file today, what it cannot, why — and what we are building instead
meta: Prepared by | PracticeSync engineering
meta: Date | 11 September 2026
meta: Status | For information. One decision recorded, none requested.
meta: Supersedes | docs/compliance/07-getting-permission-to-file.md (retained as the underlying playbook)
footer: PracticeSync — Government filing access — 11 September 2026
---

## Contents

| § | Section | For |
|---|---|---|
| **1** | Executive summary | Everyone. One page. |
| **2** | What we can file, and what stops us | The master table — every statutory output, its access class, its blocker |
| **3** | Eligibility, thresholds, fees and process | The reference section. What each registration requires and costs |
| **4** | How the market works around it | Competitive position. Nobody else files these either |
| **5** | What we are building instead — Track F | The engineering response, and why it needs no permission |
| **6** | Confidence, and what would change our mind | How much weight each claim carries, and what is still open |
| **A–D** | Appendices | Filing-by-filing detail, other integrations, drafted enquiries, research record |

---

# 1. Executive summary

PracticeSync computes every statutory return an Indian practice files. It
**transmits none of them.** This paper establishes whether that is a gap we can
close, what closing it would cost, and what the right response is meanwhile.

:::key The finding
**Of the eleven statutory outputs the product prepares, exactly two can be
completed end to end by software: the e-invoice IRN and the e-way bill.** Every
other one requires either a registration we do not hold or a human signature no
software can supply.

Four of them — ==MCA, EPFO, ESIC and professional tax== — cannot be filed by
**any** software, from any vendor, because no filing API exists to be granted.
:::

That last point is the commercially important one, and it was the question this
round of work set out to answer. We checked whether competitors do what we
cannot. They do not.

:::verdict What the market actually does
greytHR, Keka, Zoho Payroll, Pocket HRMS, factoHR and HROne all do exactly what
PracticeSync does: **generate the file, a human uploads it.** greytHR's own
documentation puts its ceiling in the same words this paper uses for ours —
*"all that you need to do is upload it to EPFO Unified portal."*

The ROC packages (Gen CompLaw, Webtel) open the MCA session from inside the
product, but a human still supplies the login and the OTP.

One vendor, RazorpayX Payroll, markets "auto-filing". The mechanism is stored
portal credentials. **That route is closed to us for reasons set out in §4.3,
and we would decline it if it were open.**
:::

### What this means commercially

**We are not behind on filing. Nobody is ahead.** The competitive ground in this
market is not the act of transmission — it is the distance between *"the
software computed the number"* and *"the acknowledgement is on record"*. Every
serious vendor has invested there, and that investment is invisible in a feature
list.

That distance is entirely ours to close. It needs no registration, no licence,
no counterparty and no money — only engineering.

:::verdict Decision recorded
**No registrations are being pursued at this time.** Not GSP, not ERI, not NIC
production credentials. This paper exists so that the decision is informed and
so that resuming costs days rather than months — the eligibility chains, the
sequences and the drafted enquiries are all set out below.

**Track F proceeds instead** (§5): seven engineering phases that make the
prepare-and-upload path excellent rather than adequate. Two of the seven fix
defects already found. None requires anyone's permission.
:::

### What it also found

Reading the portals' own material, rather than summaries of it, found faults in
our own software. That is the strongest argument for continuing to do so:

- ==ESI contributions were being computed to the paise. ESIC rounds both shares
  **up to the next whole rupee**.== On ₹15,500 of wages we deducted ₹116.25
  where the portal raises the challan for ₹117 — short, in the same direction,
  on every employee whose wages are not a clean multiple. **Fixed, with twelve
  tests.** No client was affected: no payroll has been finalised.
- ==Our ESIC upload file is a CSV. The portal requires an Excel `.xls`.== The
  contents are correct; the container is not, so a CA using it would be
  rejected at the portal after doing the work. **Track F1.**
- ==ESIC and professional tax have no filing record at all.== There is nowhere
  to put a challan number, so the obligation never closes. **Track F2.**
- ==No digital signature certificate is tracked anywhere.== An expired or
  unassociated DSC is the single most common cause of a stalled MCA filing.
  **Track F7.**

### How much to trust this paper

:::warn Read this before relying on any figure
**This paper is reliable about which door to knock on and whose signature is
required. It is weak about what anything costs and how long it takes.**

Direct access to Indian government websites is blocked from our build
environment. Almost every claim here rests on a search engine's summary of a
page, or on a vendor's own description. One primary document was obtained and
read in full — ESIC's filing manual — and it immediately overturned two things
we believed.

Every claim carries a confidence grade. §6 sets out what we would act on now
and what we would not spend money on without confirming.
:::

---

# 2. What we can file, and what stops us

### The four access classes

| Class | Means | Statutory outputs in it |
|---|---|---|
| **Direct API** | A published interface we may use on our own credentials | e-invoice IRN, e-way bill |
| **Approval-based** | A registration is available and we could apply | ITR (ERI) |
| **Partner-based** | Reachable only through a licensed intermediary | GST returns (GSP) |
| **No confirmed public API** | No interface exists, and no programme to join | MCA, EPFO, ESIC, professional tax, TDS statements |

### Every statutory output

| Output | Class | What actually gates it | Signature required | Can software complete it? |
|---|---|---|---|---|
| **e-invoice IRN** | Direct API | NIC production credentials | ==None — the IRP signs== | **Yes** |
| **e-way bill** | Direct API | NIC production credentials | ==None — the IRP signs== | **Yes** |
| **GSTR-1 / 3B / 9** | Partner | ==GSP contract== | Taxpayer DSC or EVC OTP | Prepares only |
| **ITR 1–7** | Approval | ==ERI registration== | Taxpayer, IT Act s.140 | Prepares and transmits; never completes |
| **TDS 24Q / 26Q / 27Q** | None confirmed | No API. RPU → FVU → portal upload | Deductor DSC | Prepares only |
| **Form 16 / 16A** | None, and there will not be one | Certificates are generated **by TRACES**, from the return | n/a | Prepares working papers only |
| **MCA — AOC-4, MGT-7, ADT-1** | None confirmed | No filing API at all | ==Director's Class 3 DSC== | Prepares only |
| **EPFO ECR** | None confirmed | No employer API | Portal login | Prepares only |
| **ESIC monthly contribution** | None confirmed | No API, no developer portal | Portal login | Prepares only |
| **Professional tax** | None confirmed | ==Per state — 22 separate systems== | Portal login | Prepares only |

:::note Why the two that work, work
e-invoice and e-way bill are completable for a structural reason, not a
commercial one: **the Invoice Registration Portal signs the document itself.**
There is no taxpayer signature to collect, so there is no human step software
can be asked to fake. Everywhere else, the law puts a person's signature on the
filing — and that is a feature of the law, not a limitation of the product.
:::

### The three kinds of blocker, and only one is buyable

| Blocker | Example | Can money solve it? |
|---|---|---|
| **Commercial** — a registration or contract | GSP, ERI, NIC credentials | **Yes.** Time and fees |
| **Legal** — a signature the law assigns to a person | s.140 verification, director's DSC | ==**No.** Not at any price== |
| **Absent** — no interface exists | MCA, EPFO, ESIC, PT | **No.** Nothing to buy |

Seven of the ten rows above are blocked by something money cannot move. That is
the single most important shape in this paper: **the filing gap is mostly not a
budget problem.**


---

# 3. Eligibility, thresholds, fees and process

This is the reference section. It answers, for each route that could be opened:
**who may apply, what financial bar applies, what it costs, what documents are
required, and in what order the steps happen.**

Nothing here is being acted on. It is recorded so that a decision to proceed
costs days of preparation rather than months of rediscovery.

:::warn Every figure in this section carries a confidence grade
Fees and thresholds are the weakest claims in this paper. Treat them as the
brief for a question, not as the answer. §6 says which we would act on.
:::

### 3.1 At a glance

| Route | Who may apply | Financial bar | Fee | Realistic time | Status today |
|---|---|---|---|---|---|
| **e-invoice sandbox** | Anyone with a GSTIN | ==None== | ==Free== | Same day | ==Open, self-service== |
| **Third Party Software Utility Developer** | Software developers | ==None found== | ==None found== | Days | ==Open, self-service== |
| **NIC e-invoice production** | "GSPs, ERPs and ECOs" — ERP category plausibly fits us | None found for the ERP category | Not found | ~1 week after testing | Open |
| **ERI (income tax)** | ==A company with net worth ≥ ₹1 crore, **OR a firm of Chartered Accountants**, Advocates or Company Secretaries with a valid PAN== | ₹1 crore net worth — **but the CA-firm limb has no net-worth test** | ==₹4,600== processing, to "NSDL - ERI" | Quarters — departmental review, no published SLA | Open |
| **GSP (GST)** | Indian company in IT/ITeS/BFSI, infrastructure in India, 3 years audited accounts | Turnover bar fell across batches: ₹10 cr → ₹5 cr → ==₹50 lakh claimed for batch 5, uncorroborated== | ==No public price list at any tier== | Quarters, if open at all | ==Two sources say GSTN has stopped accepting new GSPs. No open batch found== |
| **ASP (under a GSP)** | ==No empanelment, no net worth, no window== | ==None== | Commercial. Per-call pricing quoted at 10 paise–₹1, single undated source | Weeks — it is a contract negotiation | ==Open. This is the realistic GST route== |

:::key The two most decision-relevant lines in that table
**1. A firm of Chartered Accountants may apply for ERI in its own right.** The
₹1 crore net-worth bar attaches to the *company* limb; the professional-firm
limb is a separate qualification with no financial test found. If that reading
holds, ==the ITR route is open to this firm on a ₹4,600 fee and a document
set==, not on a balance sheet.

**2. GSP is almost certainly closed, and it does not matter.** The route to GST
filing is ASP under an existing GSP — ==no empanelment, no net worth, no
application window==. It is a commercial negotiation, not a qualification.
:::

### 3.2 GST returns — the ASP route, step by step

**Eligibility:** none. An ASP is a commercial counterparty of a GSP, not a
registrant of GSTN.

**The sequence:**

1. Select a GSP and negotiate. ==Read the data clauses carefully: ClearTax,
   IRIS, Cygnet and Masters India are all GSPs *and* sell practice-management
   products that compete with this one.==
2. Sign. Receive a sub-licensed client-id and secret.
3. Build against the public specifications at `developer.gst.gov.in/apiportal/`.
   Production credentials come only under the signed contract.
4. **Per-client onboarding, which is the part to design the customer
   conversation around.** The client, not us, grants access: GST portal → My
   Profile → **Manage API Access** → Yes, for a duration of ==6 hours to 30
   days==, granted by OTP. Since **29 September 2025** every consent emails and
   SMSes the authorised signatory ==naming the ASP==, and the taxpayer has a
   dashboard with a revoke button.
5. Transmit. **The signature is the client's** — Rule 26 requires a ==DSC for a
   company and an LLP==; proprietorships, partnerships and HUFs may use EVC.
6. GSTN returns an ARN. The product already has the record for it.

:::note What the ASP contract also buys
GSTIN verification, taxpayer status and **return filing-status** APIs come
through the same licence. There is no free public endpoint for any of them.
That is independently useful to a practice platform — arguably more useful,
day to day, than transmission itself.
:::

### 3.3 Income tax — ERI, step by step

**Eligibility:** a company with net worth ≥ ₹1 crore, ==**or a firm of
Chartered Accountants**, Advocates or Company Secretaries with a valid PAN==.

**Two types**, and the distinction decides the cost:

| | Type 1 | Type 2 |
|---|---|---|
| What it is | An intermediary running **ITD-approved computing infrastructure** | An entity with ==**its own software application**== |
| Which are we | — | ==This one== |
| Bank guarantee | ==Required== | ==Not required, on the sources reached== |
| ISA/CISA due-diligence certificate | Required | Required |

**The sequence:** e-filing portal → Register → **Others** → **e-Return
Intermediary** → Register as New Applicant → choose ERI type → PAN/TAN → OTP →
upload documents → ==₹4,600 processing fee by cheque or DD to "NSDL - ERI"== →
departmental review.

:::warn The honest position on ERI
The Type 1 / Type 2 split and the ₹4,600 fee are ==secondary sources agreeing
with each other==, which is precisely the failure mode this paper warns about
elsewhere. The bank-guarantee **amount** was not found anywhere.

**Approval has no published SLA and no practitioner account was found. Plan in
quarters, across at least three serially reviewed gates.**

Reading the department's own registration page is the single highest-value
verification outstanding.
:::

**And it still never completes a filing.** ==Income-tax Act s.140 assigns
verification to a named person — the individual, the karta, the managing
director.== An ERI transmits the return; the taxpayer verifies it. That is not
a product limitation and no registration removes it.

### 3.4 e-invoice and e-way bill — the two that complete

**Eligibility:** NIC issues credentials to *"GSPs, ERPs and ECOs"*. There is an
**ERP** category and we plausibly fit it; ==no net-worth or turnover bar was
found for that category==.

**The sequence:**

1. ==Sandbox: `einv-apisandbox.nic.in` — self-service, free, any GSTIN, no
   empanelment, no IP whitelisting.== Available today.
2. Test every API in pre-production with minimum success **and failure** cases.
3. File a **Test Summary Report**; email `support.einv.api@gov.in`.
4. Submit ==up to four static IPs== for whitelisting. One source: 4–5 days.
5. Production. **No taxpayer signature — the IRP signs the IRN.**

:::warn Three constraints to build against, and one is dated
- TLS 1.2 minimum, GoI IT security standards.
- The ==30-day IRN reporting limit for AATO ≥ ₹10 crore==, which reaches credit
  and debit notes.
- An advisory of 17 June 2026 makes ==**Ship-to GSTIN mandatory** in the IRN and
  e-Way-Bill-by-IRN APIs from 1 August 2026==. Anyone writing the payload needs
  that one first.
:::

:::stop The constraint nobody discovers until onboarding
On the e-way bill system the taxpayer chooses **Registration → For GSP** and
==selects a GSP from a dropdown==. If our name is not in NIC's list, the client
cannot select us — so in practice this runs under whichever GSP we contract
with, ==and the client sees that name on their own portal==. The GST consent
dashboard behaves the same way.

Plan the client conversation around it. Do not discover it at onboarding.
:::

### 3.5 The four with no route at all

MCA, EPFO, ESIC and professional tax have **no filing API, no developer portal,
no partner programme and nothing to apply for.** There is no eligibility to
meet and no fee to pay, because there is no door.

What each of them *does* cost, and who pays:

| | What gates a filing | Whose cost |
|---|---|---|
| **MCA** | ==The client director's Class 3 DSC==, associated on V3 under DSC Services → Associate DSC. Roughly ==₹850–₹4,500== depending on validity and token | The client's. ==And it is the item that most often stalls a filing== — which is why Track F7 exists |
| **EPFO** | Employer portal login. From ==11 March 2026 the portal serves only summary-level ECR downloads==, dropping employee-wise detail — so **our records become the only per-employee history** | The client's |
| **ESIC** | Employer portal login, 17-digit code | The client's |
| **Professional tax** | ==Administered per state — any API would be 22 separate integrations, not one== | The client's |

:::note One structural note on MCA
The only machine-facing artefact MCA offers is the **XBRL instance**, and MCA
addresses software vendors about it directly — MCA XBRL Validation Tool V5.0,
July 2025, covering AOC-4 XBRL and CRA-4 XBRL. That is a *validation* tool, not
a filing interface. MCA's own integrations with Income Tax, GST, EPFO and ESIC
at incorporation are **MCA calling them**, not an API for us.
:::


---

# 4. How the market works around it

The question this section answers is not academic. If competitors file what we
cannot, the gap is a commercial problem. If they do not, it is not a gap at all.

We searched deliberately for a counterexample — phrasings designed to *find* a
vendor that files directly, rather than to confirm that none does.

### 4.1 Four mechanisms, and only one of them is an API

| | Mechanism | Who does it | What actually happens | An API? |
|---|---|---|---|---|
| **A** | **Generate-and-upload** | greytHR, Keka, Zoho Payroll, Pocket HRMS, factoHR, HROne, and every TDS package | Software emits the exact file. A human logs in and uploads it | **No** |
| **B** | **Portal-assisted upload** | Gen CompLaw, Webtel — the ROC packages | Software opens the MCA session from inside the product; ==the human still supplies the login and the OTP==; the DSC signs on the human's machine | **No** |
| **C** | **Stored credentials** | RazorpayX Payroll | ==The customer types their portal credentials into the vendor's dashboard. The vendor operates the portal as the customer== | **No** |
| **D** | **A published filing API** | ==Nobody, for these four== | — | — |

:::key The load-bearing evidence
**greytHR**, the market leader in Indian payroll, on its own product:

*"You can automatically generate the ECR file with greytHR. The ECR file is
ready with just a click and all that you need to do is upload it to EPFO
Unified portal."*

==That sentence is the finding.== If an EPFO API existed, greytHR would be using
it. **Zoho Payroll** is the same — its EPF-ECR and ESIC reports are *"structured
in the format expected by the government"*. Structured. Not transmitted.
:::

### 4.2 The one vendor that claims otherwise

RazorpayX Payroll markets that it *"auto-files and pays TDS, PF, PT and ESIC"*
with *"no manual intervention"*. The mechanism appears only in its support FAQ:

> *"TDS challans could be unavailable due to incorrect IT credentials provided
> on the Payroll Dashboard, as a result, Payroll is unable to fetch the
> challans."*

The customer hands over portal credentials and the platform signs in as them.

**The limit of that evidence, stated precisely:** it establishes stored
credentials for the *income-tax portal*, for *fetching challans*. It does not
prove the same for EPFO, ESIC and PT — but since no API exists for those three
either, there is no third possibility.

### 4.3 Why that route is closed to us, and would be declined if it were open

:::stop Four reasons, none of them squeamishness
**1. They are a payment aggregator; we are not.** Razorpay can move the money —
that is their licensed business. Much of "auto-pays PF, PT, ESI and TDS" is a
payment rail, not a filing capability. The marketing conflates the two.

**2. They serve one employer. A CA firm serves two hundred.** A company storing
its own EPFO password in its own payroll tool is a decision that company makes
about itself. ==A practice holding two hundred clients' portal credentials is
the single most attractive target in the product, and one breach exposes every
client at once.==

**3. DPDP makes it the firm's problem, in writing.** A client's portal
credential is the client's personal data held by the firm as Data Fiduciary —
with duties to secure it, notify on breach, and erase it on withdrawal of
consent, on top of whatever the portal's own terms say about credential sharing.

**4. The product has already decided this, for bank data.** Our engineering
rules say: *never screen-scrape net banking; no credential capture, no stored
bank logins.* ==A rule that bends for the EPFO portal is not a rule.==
:::

**So there is no route we are missing.** There is one we cannot take, and one we
are declining.

---

# 5. What we are building instead — Track F

### 5.1 Filing is step five of seven, and it is the only blocked one

| | Step | Blocked by anyone outside us? |
|---|---|---|
| 1 | **Compute** the figures from the books | No |
| 2 | **Emit the exact artefact** — byte-exact, right extension, right encoding | No |
| 3 | **Pre-flight** — refuse here everything the portal would refuse there | No |
| 4 | **Hand off in portal order** — the screen the CA works from, portal open alongside | No |
| 5 | **File** | ==**Yes — and only this one**== |
| 6 | **Capture the acknowledgement** — ARN / TRN / SRN / CRN, date, receipt | No |
| 7 | **Reconcile and lock** — the challan posts to the ledger; the acknowledgement closes the obligation | No |

==Six of the seven are ours.== Here is where we actually stand, read off the
code rather than remembered:

| Filing | 1 Compute | 2 Artefact | 3 Pre-flight | 4 Handoff | 6 Ack | 7 Lock + ledger |
|---|---|---|---|---|---|---|
| **GSTR-1 / 3B** | yes | yes | partial | ==no== | **yes** | **yes** |
| **EPFO ECR** | yes | yes | partial | ==no== | record exists | ==no== |
| **ESIC** | yes | ==CSV — portal wants `.xls`== | yes | ==no== | ==none== | ==no== |
| **Professional tax** | 4 of 22 states | ==nothing== | n/a | ==no== | ==none== | ==no== |
| **MCA** | yes | XBRL instance | partial | ==no== | status exists | n/a |
| **TDS 24Q / 26Q** | yes | yes | yes | ==no== | challans recorded | partial |

### 5.2 The seven phases

Lettered, not numbered, so they cannot collide with the twelve phases of the
existing engineering plan. ==None of them needs a registration, a licence, a
counterparty or a rupee.== Ordered by harm removed per unit of work.

| | Phase | Size | What it fixes |
|---|---|---|---|
| **F1** | **The ESIC file the portal accepts** | Small | A live defect. Our CSV is rejected at the portal after the CA has done the work |
| **F2** | **One statutory filing record, for everything** | Medium | ESIC and PT have nowhere to put a challan number, so obligations never close |
| **F3** | **The handoff screen** | Medium | The CA alt-tabs between four screens and a spreadsheet to answer "what do I type in this box" |
| **F4** | **The challan is money** | Small | Statutory liability accounts never clear; year-end shows a liability the client has paid |
| **F5** | **Professional tax: the artefact** | Medium | Four states are computed and no challan or return is produced for any of them |
| **F6** | **The never-do list, as code** | Small | Three product rules that are prose today and should be tests |
| **F7** | **The DSC register** | Small | ==Nothing anywhere tracks a digital signature certificate.== An expired or unassociated DSC is the most common cause of a stalled MCA filing |

:::key F1 was redesigned mid-research, and the reason generalises
The first draft said: emit our own `.xls`, every cell text, the portal's column
order. **ESIC's own manual forbids exactly that** —

*"Download Sample MC Template from the portal — only this template should be
used, and refrain from using any other sheet even if prepared in similar looking
format."*

So F1 became: ==the CA uploads the portal's own template, and we fill it== —
matching by insurance number, writing only days, wages, reason code and last
working day. It cannot drift when ESIC revises the template, it performs the
reconciliation the CA does by hand today, and it needs no source we cannot get.

**The constraint improved the design.** That is the argument for reading the
portals' own material rather than summaries of it.
:::

:::stop F6 — the three rules that protect everything above
1. **No field anywhere collects a government-portal password, PIN or OTP.**
2. **No column anywhere stores a portal credential or token.**
3. **Nothing transmits to a `.gov.in` host.** ==This is true by accident today —
   there is no such call. A test makes it true on purpose==, and makes the day
   somebody adds one a deliberate decision with a review attached.
:::

### 5.3 What Track F does not do

It does not make us able to file, and no amount of engineering will. The four
blocked filings stay blocked until a portal opens an API, and this paper's
honest reading is that none of them is close.

What Track F does is make PracticeSync the product where ==the upload never
bounces and the acknowledgement always lands in the books== — which, on the
evidence in §4, is the only axis anyone in this market is competing on.


---

# 6. Confidence, and what would change our mind

### 6.1 Why the grading exists

Direct access to Indian government websites is refused by our build
environment's network policy. Tested repeatedly across several days, including
while writing this paper:

```
incometax.gov.in/iec/foportal/help/eri/registration   → BLOCKED
test-dev.tdscpc.gov.in/about                          → BLOCKED
www.gstn.org.in/assets/.../eligibility-batch-5.pdf    → BLOCKED
```

Web search works, because it runs elsewhere and returns **somebody else's
summary** of a page. So the shape of most evidence here is: *a search engine has
read a document and reported a sentence from it; nobody on this side has read a
line.*

| Grade | Means |
|---|---|
| [P] | The primary source was opened and read |
| [S-gov] | A search engine summarised a document at an **official** URL |
| [S] | Trade press, vendor documentation, or a professional firm's note |
| [O] | ==A person here opened the page and reported what it says== |
| [U] | Wanted and not found, or sources contradict |

==No claim in this paper is graded [P].== One document was obtained in full and
read — ESIC's filing manual, which happened to be mirrored on a commercial cloud
host — and it is graded [S-gov] because it is a copy of unknown vintage.

### 6.2 What we would act on now

| Claim | Why it holds |
|---|---|
| **MCA, EPFO, ESIC and PT have no filing API** | Four search angles across several sessions, phrased to find a counterexample. The strongest confirmation is indirect and therefore good: ==the market leaders describe their own ceiling in the same words== |
| **e-invoice and e-way bill are the only two completable outputs** | Structural, not empirical — the IRP signs, so there is no taxpayer signature to collect. The reasoning does not depend on a source |
| **GST filing needs a GSP; ITR filing needs an ERI** | Consistent across every source, and consistent with how both systems are built |
| **TDS goes up as an FVU zip with a DSC, and there is no API** | Every description of the route is identical: RPU → FVU → upload → DSC |
| **Never take stored portal credentials** | ==A decision, not a fact. It needs no source== |

### 6.3 What we would not spend a rupee on without confirming

| Claim | Why it is weak |
|---|---|
| ==**Every cost figure in this paper**== | Stale on its face, absent from public sources, or single-sourced. The most expensive kind of wrong |
| **The GSP ₹50 lakh turnover threshold** | An external research document's claim, which our own searches could not surface. Recorded as its claim, not adopted |
| **ERI Type 1 / Type 2 and the ₹4,600 fee** | ==Secondary sources agreeing with each other.== The bank-guarantee amount was not found at all. This is the highest-value single page still unread |
| **The CPC-TDS developer portal** | One lead we could not open. It may be a real programme or an internal test host. The difference is large |
| **The Maharashtra PT due-date change of 28-02-2026** | [S]. Which is why the product holds ==no PT due dates at all== rather than holding wrong ones |
| **That 22 states levy professional tax** | Probably one or two too high. Deliberately unchanged: ==the error direction is benign — a false gap warning, never a wrong deduction== |

### 6.4 What is still open, and what would close it

Six pages would resolve most of the weakness above. They need a person at an
ordinary browser.

| Priority | Page | What it settles |
|---|---|---|
| **1** | ITD's ERI registration page | ==Type 1 vs Type 2, the fee, whether the bank guarantee applies to us and how much==. Could move ITR from "quarters and a bank instrument" to "₹4,600 and a document set" |
| **2** | GSTN GSP eligibility | ==The turnover threshold==, and whether applications are open at all |
| **3** | `test-dev.tdscpc.gov.in` | Real developer programme, or internal host? The only lead toward a TDS API |
| **4** | Third Party Software Utility Developer registration | ==The cheapest real step in this paper.== Prerequisites and what it entitles us to |
| **5** | ESIC zero-wage reason codes | Closes a refusal the product deliberately makes today. ==Needs an employer login we do not hold== |
| **6** | Maharashtra PT notification, 28-02-2026 | The real due date, before Track F5 writes one down |

:::note Four enquiries are already drafted
Appendix C carries complete emails — recipients, subject lines and bodies — to
the Income Tax Department, CPC-TDS, GSTN, NIC, Protean eGov and DigiLocker,
each citing the published page the question arises from.

**None has been sent**, consistent with the decision in §1 not to pursue
registrations. They exist so that resuming costs an afternoon.
:::

### 6.5 The bottom line

:::verdict Three sentences
**We cannot file, most competitors cannot file, and for four of the statutory
outputs nobody can.**

The two outputs software *can* complete end to end — e-invoice and e-way bill —
are open on a free, self-service sandbox today, and are the only registrations
worth revisiting first when the decision changes.

==Everything else worth doing in the next quarter is engineering we already
control, and this round of reading the portals' own material found four defects
in our own software that no amount of registration would have fixed.==
:::



# Appendix A — Filing by filing, the full chain

Each subsection runs the chain you asked for: **eligibility → documents →
registration → approval → fees → credentials → sandbox → production → client
onboarding → filing → acknowledgement.** Where a link in that chain does not
exist, it says so rather than inventing one.

### A.1 GST returns — GSTR-1, GSTR-3B, GSTR-9, GSTR-9C · **PARTNER-BASED**

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

### A.2 e-invoice IRN · **DIRECT API — and completable**

| Link | Position | Grade |
|---|---|---|
| **Eligibility** | NIC issues credentials to **"GSPs, ERPs and ECOs"** — there is an **ERP** category and we plausibly fit it. No net-worth or turnover bar found *for the ERP category* | `[S]` / `[U]` |
| **Registration (sandbox)** | `https://einv-apisandbox.nic.in/` — **self-service, free, any GSTIN, no empanelment, no IP whitelisting** | `[S]` |
| **Documents** | None for sandbox | `[S]` |
| **Approval (production)** | Test every API in pre-production with minimum success and failure cases → file a **Test Summary Report** → email `support.einv.api@gov.in` → submit **up to four static IPs** for whitelisting. One source: 4–5 days | `[S]` |
| **Fees** | Sandbox free. Production: **no fee found for the ERP route** `[U]`. The real cost is the India static-IP hop (§6.4) | `[U]` |
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

### A.3 e-way bill · **DIRECT API — and completable**

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

### A.4 ITR · **APPROVAL-BASED — transmits, never completes**

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
> re-consenting every client. And **ERI Type 3** (raised by the external research) may be a third option
> worth pricing before defaulting to Type 2.

**Code seam.** `domain/income_tax/itr_json.py` already refuses in the right
place — `if not software_provider_id(): raise SoftwareProviderNotRegistered`,
reading `ITR_SOFTWARE_PROVIDER_ID` from `render.yaml`. Note the **second**
refusal behind it: `ITRPayload` carries tax figures and no `PersonalInfo`,
`FilingStatus`, `Verification` or bank details, so the `SW########` unblocks the
field but does **not** by itself produce a filable return.

### A.5 TDS / TCS statements · **NO CONFIRMED PUBLIC API — with one open lead**

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
would settle it and cost nothing** — see §6.4.

**One thing no registration fixes.** `domain/tds/vocabulary.py` deliberately
does not hold the s.393 **payment-code table**, and an API makes that worse: a
wrong payment code is *accepted* and then wrong. The range is **1001–1092, not
1001–1067** — 1068–1092 are the s.394 TCS codes, so anything range-checking at
≤ 1067 rejects every valid TCS code. `[S]`

### A.6 TDS certificates — Form 16 → 130, Form 16A → 131 · **NO API, AND THERE WILL NOT BE ONE**

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

### A.7 MCA · **NO CONFIRMED PUBLIC API**

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

### A.8 EPFO · **NO CONFIRMED PUBLIC API**

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

### A.9 ESIC · **NO CONFIRMED PUBLIC API**

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

### A.10 Professional tax · **NO CONFIRMED PUBLIC API, IN ANY STATE**

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


# Appendix B — Other integrations worth having

You asked for "any other APIs that can genuinely improve the platform". These
are the ones that survived checking. Two of them are real and reachable.

### B.1 DigiLocker (via API Setu) · **DIRECT API** — recommended

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

### B.2 Protean PAN verification · **APPROVAL-BASED** — probably blocked

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

### B.3 eSign / DSC · **PARTNER-BASED**

MCA forms, GST returns for companies and LLPs, and TDS statements all end in a
signature. eSign is provided by licensed **ESPs** under CCA. Both documents agree
on the one rule that matters: **never store users' DSC private keys centrally.**
Support a compliant signing architecture instead. `[U]` on ESP commercials.

### B.4 GSTIN verification and return filing-status · **bundled with the ASP contract**

Not a separate integration. GSTN exposes GSTIN validation, taxpayer status and
return filing-history endpoints **only through a GSP** — there is no free public
API. `[S]` Worth naming explicitly when negotiating the ASP contract, because it
is genuinely useful (vendor verification, §16(2)(aa) support) and you are
already paying for the pipe.

### B.5 Account Aggregator · **CLOSED BY DECISION — do not reopen**

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

### B.6 Udyam and Shram Suvidha · **NO CONFIRMED PUBLIC API**

Both documents agree, and neither found an onboarding path. Udyam is useful for
the **MSME classification the §43B(h) tracker needs** — a fact about the
*supplier* that no ledger holds — so if an API ever appears it closes a real gap.
Not today. `[U]`

---


# Appendix C — The enquiries, drafted and unsent

§6.4.4 lists nine open questions. They go to **six inboxes**, not nine — several
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


# Appendix D — Research record

How this paper was produced, what an external research baseline got right and
wrong, where every claim came from, and what has been corrected since.

---

## D.1 The external research baseline — right, wrong, and missing

### D.1.1 Right, and genuinely additive

| | |
|---|---|
| **The executive shape** | "No single government API credential unlocks all CA compliance; each ecosystem needs its own strategy" is correct and well put |
| **GSP batch-5 specifics** | Organisation forms, ≥ ₹50 lakh average turnover over three FYs with MSME relaxation, 70% overall / 60% per section technical scoring, ≥ 1 lakh transactions per month, India-based backend, a working GSP demonstration covering GSTR-1, e-invoice JSON/IRN, reconciliation, multi-GSTIN and DSC. **Our own four differently-phrased searches failed to surface the ₹50 lakh figure from any source.** If that came from the PDF, it closes a `[U]` we have carried since the first research pass — which is a real contribution |
| **IRIS IRP (`einvoice6`)** | Our prior work concentrated on NIC's `einvoice1`/`einvoice2`. The IRIS IRP developer documentation and its separate **API-integrator / solution-provider** path is a door we had not examined |
| **e-way bill onboarding mechanics** | Client ID / client secret issued by the system, plus taxpayer GSTIN and API username/password; shortlisting, pre-production credentials, testing, IP whitelisting, then the production API login. Consistent with what we had and better detailed |
| **"No credential scraping"** | Correct, and it matches this repo's standing rule against net-banking screen-scraping |
| **The architecture section** | The consent & authorisation service, credential vault, connector layer, submission state machine and immutable audit trail are all right, and its identity hierarchy matches what the codebase already does |

### D.1.2 Wrong, or unsupported by the sources I could reach

| # | The claim | What I found |
|---|---|---|
| 1 | *"For Type-2/Type-3 ERI, upload the undertaking, bank guarantee and audit report"* | Sources consistently attach the **bank guarantee to Type 1**, not Type 2. `[S]` Type 1 is the category with *"ITD approved computing infrastructure and a due diligence certificate from a certified ISA/CISA professional"*. **This matters commercially** — it is the difference between a bank guarantee being a cost of our chosen route or not. `[U]` on the amount either way |
| 2 | *"Maharashtra… portal notice says PT registration and return-filing facilities are temporarily disabled"* | The sourced 2026 position is a **trade circular of 13 March 2026 granting temporary relaxation** because of portal issues — PTRC payment by 15 March, PTEC by 31 March, delayed registration permitted **to 30 April 2026**, and payment by PAN where registration could not complete. `[S]` That is a transient relief measure, not a standing disablement. Designing around "the portal is disabled" would be designing around a circular that has expired |
| 3 | **MCA, EPFO and ESIC marked "P0"** in the action plan | A category error. There is **nothing to apply for** in any of the three — no registration, no empanelment, no partner, no purchasable route. They cannot be a P0 *action* because there is no action. They are a P0 *design constraint*: build the file, let a human upload it |
| 4 | *Type-2 ERI is "the clearest direct-API route"* | True about the API and misleading about the outcome. See §2 — s.140 verification is not delegable, so the ERI route transmits and never completes |
| 5 | The **ERI registration flow** as described | Broadly matches what we have, but the document says *"Register/validate the PAN or TAN"* and separately references NSDL registration. The current flow appears to be **on the e-filing portal itself** (Register → Others → e-Return Intermediary), not a cheque to NSDL. `[S-gov]` Sources disagree; ours is the more recent reading. `[U]` |

### D.1.3 Missing, and each of these changes the plan

| # | What is absent | Why it matters |
|---|---|---|
| 1 | **The `SW########` software-provider id**, and the e-filing portal's **"Third Party Software Utility Developer"** user category, which has its own official user manual `[S-gov]` | Every ITR JSON carries `SWCreatedBy`; **a return without an approved software id is rejected** `[S]`. This is plausibly a self-service portal registration with no net-worth bar — **the cheapest unblock in the entire document**, and the uploaded research does not mention it |
| 2 | **ERI Type 3** — *"entities that develop offline utility… pure software providers who do not themselves act on behalf of taxpayers"* `[S]` | A third structural option the document does not consider. It may be the honest description of a CA-practice platform where the **CA** files and we supply the software. Worth confirming before choosing Type 2 by default |
| 3 | **s.140 / Rule 26 signature analysis** | See §2. The difference between a licence problem and a legal-impossibility problem |
| 4 | **DigiLocker via API Setu**, and **Protean PAN verification** | Two real, documented, non-filing integrations that improve a CA platform materially. Appendix B |
| 5 | **The Account Aggregator decision is already made and closed** | The uploaded document does not mention AA. This repo investigated it to a conclusion — no FIU licence exists to apply for, and no published purpose code covers bookkeeping. **Route 3 (do not consume via AA) was chosen on 6 September 2026.** Nothing here reopens it. See `05-bank-data-and-the-account-aggregator.md` |
| 6 | **A live 2026 statutory change**: Maharashtra notification of **28 February 2026 amending Rule 11(3)** moved PT due dates **from month-end to the 15th** `[S]` | Checked against the code: we hold **no PT due dates at all**, so nothing is currently wrong. Recorded so that whoever adds them does not add the old ones |

---

---

## D.2 Source register

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

---

## D.3 Verified directly, and corrected since

Egress is refused to me, so this is the only route to primary evidence. Each
entry says what was opened, what it showed, and what changed as a result.
**Graded `[O]`.**

### 11 September 2026

**`esic.in/ESICInsurance1/App_Themes/Help/MC_Template1.xls` → 404.** `[O]`
That URL came out of a search snippet and is dead. Worth recording for its own
sake: it is a small, concrete instance of the failure mode §6.4.1 warns about — a
search engine reported a path that does not exist, and nothing short of opening
it would have told us.

**`portal.esic.gov.in/EmployerPortal/.../Portal_Loginnew.aspx`** `[O]` — the
employer login page carries a standing notice:

> *"We Are Migrating To One Unit One Identifier. Government of India plans to do
> away with all employer codes being issued by separate labour enforcement
> agencies such as ESIC, EPFO, O/O CIC(C) and DGMS etc by replacing them with new
> Labour Identification Number (LIN). Your unit has already been allotted a LIN…
> Please verify the information associated with your LIN before the current
> employer codes are rendered useless."*

**We already model this and no change is needed.** Migration 325 gives
`client_statutory_registrations` a `lin` column alongside
`esic_employer_code` and `epf_establishment_code`, and `routers/payroll.py`
reads all three. Recorded so that nobody reads the notice later and starts a
migration that already happened.

Two things it does tell us, though. First, the notice is undated and has been
live for years, so **do not treat "employer codes are rendered useless" as
imminent** — but do not drop the codes either; keep all three, which is what we
do. Second, whenever that convergence does land, `esic_gaps` and the ECR's
establishment-code gap become one question, not three.

**No ESIC employer login available.** `[O]` The owner is a CA firm without an
employer registration of its own and did not have a client login to hand. That
is a permanent constraint on §6.4.4 items 1–3, not a delay — and it is the reason
F1 was redesigned to fill the CA's own downloaded template rather than mint
one. **The constraint improved the design.**

### The process discovery — and its limit, which I got wrong the first time

Chasing the ESIC template turned up *User Manual for Filing the Monthly
Contribution and Payment of dues* — ESIC's own 27-page manual — sitting on a
vendor forum's file store, and **that fetch succeeded.** It is the first
genuinely primary document read in this whole exercise.

**I then wrote here that "the proxy blocks `.gov.in`, it does not block
mirrors". That was wrong, and it was wrong on a sample of one.** Tested
immediately after, in the same session:

```
www.gstn.org.in/assets/.../eligibility-batch-5.pdf   → EGRESS_BLOCKED
taxindiaonline.com/RC2/pdfdocs/Press_Release_...pdf  → EGRESS_BLOCKED
tin.tin.nsdl.com/eri                                 → DNS: no such host
```

`gstn.org.in` is not a `.gov.in` and it is blocked; `taxindiaonline.com` is an
ordinary trade site and it is blocked too. So the rule is **not** "government
blocked, mirrors open".

What actually worked was the file's HOST: the ESIC manual was served from
`…s3.dualstack.us-west-2.amazonaws.com`. The honest reading is **a document
sitting on a major global cloud host or CDN can come through, while Indian
domains — official or commercial — do not.** That is much narrower than what I
claimed, and it is a matter of where a file happens to be parked rather than a
method I can steer.

**So the corrected method is: it is worth ONE search for a cloud-hosted copy of
any document that matters, and it is not a substitute for somebody opening the
page.** The ESIC win was real and worth having. It was also luck.

### ESIC's filing manual — what it settled, and the defect it found

Read in full, 27 pages `[S-gov]`. It **confirmed** what
`domain/payroll/esic.py` already had: the six columns and their order
(10-digit IP number, IP name, no. of days, total monthly wages, reason for zero
wages, last working day), days as a whole number **rounded up**, all columns in
Text format, `.xls` / Excel 97-2003, dates `dd/mm/yyyy` or `dd-mm-yyyy`
zero-padded.

It **added four things**, three of which raise the stakes on a refusal this
product already makes:

1. **"Once 0 wages given, IP will be removed from the employer's record.
   Subsequent Months will not have this IP listed under the employer."**
   A zero-wage row does not report a month — it takes the person OFF the
   establishment. An employee on a full month of unpaid leave, reported as
   zero, loses ESI coverage. This is now the strongest argument for the
   module's refusal to invent a reason code: the guess does not merely
   misreport, it de-registers somebody.
2. **A last working day is required for exactly six reasons** — left service,
   retired, out of coverage, expired, non-implemented area, retrenchment —
   *"For other reasons, last working day must be left BLANK."* We still do not
   hold the numeric codes (the portal surfaces them at filing time, which is
   exactly what the module said), but we now hold which reasons are terminal.
   **§6.4.4 item 2 is therefore half-closed**: the semantics are settled, the
   numbers are not.
3. **The upload is all-or-nothing** against the portal's own list of mapped
   IPs — *"successful transaction only when all the Employees' (who are
   currently mapped in the system) details are entered perfectly"*. A file
   missing one person fails entirely. This makes F1's reconciliation a hard
   requirement rather than a nicety.
4. **The portal computes the contributions**, not us — *"IP Contribution and
   Employer contribution calculation will be automatically done by the
   system."* The file carries days and wages only. The module is right not to
   emit contribution columns.

And one fact that belongs beside the return rather than in it: **a submitted
monthly contribution cannot be modified, and a supplementary can only
INCREASE it** — *"No way contribution amount submitted during monthly
contribution will reduce."* An over-declaration has no ordinary route back.
That is a warning the F3 handoff screen must carry.

**The defect it found.** The manual says of the figure the portal computes:
*"Employee Contribution will be calculated and displayed. This is rounded to
next higher rupee."* The same has applied to the employer's share since
October 2004. `routers/payroll.py::_compute_esi` **floored to the paise** —
`math.floor(gross × bps / 10000)` — and the paise is not a unit ESI works in.

On ₹15,500 of wages the employee share is ₹116.25 exactly: we deducted and
posted ₹116.25 while the portal raises the challan for ₹117. Short, in the same
direction, on every employee whose wages are not a clean multiple, every month
— and under-remitted ESI is the **employer's** liability with interest. Fixed
in this session's commit, with the rounding in one helper both shares go
through, twelve tests of which eight fail against the old rule, and the two
existing tests that had pinned the defect updated with the reason stated rather
than silently.

**This is the return on opening one page.** Three days of searching produced
`[S]`-graded prose; one mirrored manual produced a confirmed format, four new
rules, and a live money defect.


### What the same session did get on ERI, without a page being opened

Search only, so `[S]` — but more specific than Appendix A.4 held, and consistent across
sources:

- **Two types.** Type 1 is an intermediary running ITD-approved computing
  infrastructure, requiring **a due-diligence certificate from a certified
  ISA/CISA professional and a bank guarantee**. Type 2 is an entity with **its
  own software application** — which is the category a product like this one
  would sit in.
- **The registration processing fee is ₹4,600**, by cheque or demand draft in
  favour of **"NSDL - ERI"**. `[S]`
- The bank guarantee attaches to **Type 1**, not to Type 2, on these sources.
  **The amount was not stated anywhere I could reach.**

**This matters more than it looks and it changes Appendix A.4's emphasis.** The
document has been carrying "ERI registration, fees, bank guarantee" as one
undifferentiated blocker. If the guarantee really is Type-1-only, then the
route relevant to us — Type 2, own software — may cost ₹4,600 and a document
set rather than a bank instrument, which is a completely different order of
commitment.

**Do not act on that yet.** It rests on secondary sources agreeing with each
other, which is exactly the failure mode §6.4.1 describes; the ITD's own
registration page is §6.4.4 item 5 and remains the thing to read. But it moves
that item from "worth doing" to **the highest-value single page on the list**.