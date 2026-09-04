# Bank data — the Account Aggregator

Confidence grades and the sourcing caveat: see `00-how-to-read-this.md`.
**No primary source was read directly.**

---

## 0. The finding that changes the existing plan — VERIFIED

`CLAUDE.md:404` instructs, as step one of this work:

> **Register as an FIU** (Financial Information User). … Go via a TSP (Setu,
> Perfios, Finbox, Digio) rather than building FIU plumbing directly.

**VERIFIED 2026-09-04: that is not achievable as written.** The verification
deliberately searched for the opposite — for any route letting an unregulated
SaaS company become an FIU. Every such search returned the same answer.

### The definitional text

From the **RBI (Non-Banking Financial Companies – Account Aggregator)
Directions, 2025** `[P via summary]`:

> **"Financial Information User"** means an entity **registered with and
> regulated by any financial sector regulator**.

> **"Financial Sector Regulator"** … shall mean the Reserve Bank of India,
> Securities and Exchange Board of India, Insurance Regulatory and Development
> Authority of India, Pension Fund Regulatory and Development Authority **and
> Department of Revenue, Ministry of Finance**.

**There is no FIU licence to apply for and no unregulated-FIU tier.**
Eligibility is *derivative*: you are an FIU **because** you already hold a
registration from one of those five. A company holding none of them cannot be
one, and **a TSP cannot confer it** — a TSP is itself unregulated and merely
builds the FIU module *for* a regulated FIU.

The framework is designed this way on purpose: it **never allows raw financial
data to flow to an unregulated party**.

### The Department of Revenue does not open a door

The 2025 Directions add DoR to the regulator list, which looks like a way in for
tax-adjacent software. It is not. DoR is there because:

> Department of Revenue shall be the regulator of **GSTN for this specific
> purpose**, and GST Returns, viz. Form GSTR-1 and Form GSTR-3B, shall be the
> Financial Information.

**GSTN is named as an FIP, not an FIU**, and DoR's inclusion is scoped to that.

### A CA firm does not qualify either

ICAI regulates chartered accountants professionally and ethically, but **it is
not one of the financial sector regulators**. A CA firm is therefore not
FIU-eligible in its own capacity. `[S — this was inference in the first pass and
is now sourced.]`

### The three real options, unchanged but now firm

| Route | What it means | Risk |
|---|---|---|
| **Partner with a regulated FIU** | An NBFC / bank / SEBI-registered adviser is the FIU; PracticeSync builds the product layer on top | The scrutinised pattern below |
| **Acquire a registration** | Most plausibly **SEBI Investment Adviser**; an NBFC licence is heavier and carries the reciprocity duty | Regulatory perimeter creep for duties unrelated to the product |
| **Do not consume via AA** | Statement upload stays the only path | Zero exposure — and coverage (§3) says this is the base case anyway |

The partnership route is explicitly the documented one: *"a pure-play fintech
startup without an NBFC licence, lending licence or investment advisory
registration has two options: obtain a licence, or partner with a regulated
entity that acts as the FIU while you build the product on top."* `[S]`

⚠️ **But the shell-FIU pattern is watched.** The question regulators ask is
*whether the regulated entity is using the information for its own regulated
activity, or whether its FIU status is enabling another business to access the
ecosystem*. There are documented instances of **AAs being barred by FIPs** after
market-facing TSPs built non-compliant journeys. `[S]` That is a supply-side
kill switch outside your control.

⚠️ **Reciprocity.** RBI circular of **26 October 2023**: a regulated entity
joining as an **FI-U must necessarily join as an FIP** where it holds financial
information. `[S]` The NBFC route therefore inherits an obligation to *publish*
into the ecosystem.

### What this means for tasks #102–#107

Those six tasks are written on the assumption that registering as an FIU via a
TSP is the path. **#104 in particular — "complete FIU registration/onboarding
via the chosen TSP" — describes something that does not exist.** #102 asks
exactly the right question and its answer is now known. The sequence needs
rewriting around the three options above before any of it is actioned.

## 1. The ecosystem

**16–18 licensed AAs** (Sahamati reports 17 operating plus 1 in-principle; another
summary says 16 — use the band). `[P/S]` Named: OneMoney (FinSec), Finvu
(Cookiejar), CAMSfinserv, NADL, Anumati (Perfios), SurakshAA (Protean), Setu AA
(Agya), Saafe, INK, Tally Edge, Yodlee Finsoft, CRIF Connect, Cygnet, Digio, PB
Financial, ScoreMe, OMS Fintech. `[S — vendor listicles, not RBI's register.
Verify before contracting.]`

**PhonePe exited** — announced February 2025, registration cancelled by RBI **26
August 2025**, citing inability to onboard as many FIPs as planned. `[S]`

⚠️ **"17 licensed" overstates the real choice set by roughly 2.5×.** One source
puts meaningful traction at about **seven**; the rest are small-scale, still in
sandbox, or have no live FIP integrations. `[S]`

**Sahamati** became the RBI-recognised **SRO for the ecosystem on 5 June 2026**
`[S — recent enough to re-verify]`. It is **not a licensing authority**. It runs
the **Central Registry** (the directory of live entities, endpoints and public
keys), a **UAT registry**, the **Certification Framework**, the optional
**SahamatiNet Router**, the **Community Code of Conduct** and the **Fair Use
Template Library**.

## 2. Consent — the architecture, not a checkbox

The flow `[P — read from Sahamati's own repository]`:

1. `FIU → POST /Consent` — data types, duration, purpose.
2. **AA → customer**: the AA renders the request in *its own* app. **The customer
   approves at the AA, never at the FIU.**
3. `/Consent/accept` — the AA mints a **consent artefact**.
4. AA notifies both FIU and FIP; the FIP validates against the artefact on every
   later request.
5. `/Consent/revoke` — **by the customer, at any time**; access terminates
   immediately.

**Data fetch is asynchronous and two-legged**: `FIU POST /FI/Request` → AA → FIP
→ session id → FIP `POST /FI/Notification` when ready → `AA POST /FI/fetch` →
`AA POST /FI/Notification` to FIU → `FIU POST /FI/fetch`. **Anything built here
is callback-driven, not request/response.** API surface is ReBIT **v2.x**; v1 is
on a published deprecation calendar. Each hop verifies a **detached JWS**.

### The artefact's fields

`consentStart`/`consentExpiry`; `consentMode` (VIEW/STORE/QUERY/STREAM);
**`fetchType`** (ONETIME or PERIODIC); `consentTypes`
(PROFILE/SUMMARY/TRANSACTIONS); `fiTypes`; `Frequency {unit, value}`;
**`DataLife {unit, value}`**; `DataFilter`; `Purpose {code, refUri, text,
Category}`. `[S]`

> **`DataLife` is a separate clock from `consentExpiry`.** Expiry stops new
> fetches; data life obliges **deletion of what you already hold**.

### Fair Use Templates cap the parameters

Sahamati's library sets **outer bounds** per use case, and the Code of Conduct
binds members. Recovered examples `[P/S]`: **Spend and Investment Analytics —
≤ 45 data pulls, consent validity ≤ 1 year**; short-term loans — validity ≤ tenure
+ 3 months; and **a consent artefact can never be irrevocable**.

Monthly bookkeeping sits comfortably inside ≤45 pulls / ≤1 year — but **it forces
annual re-consent per client**, which is a renewal workflow, not a one-off
onboarding step.

### ⚠️ Purpose codes — unresolved, and a real design question

ReBIT publishes the taxonomy at `api.rebit.org.in/purpose/`. **Both that and its
mirror were blocked, and the recovered fragments contradict each other** — one
gives `103` = process a loan application and `104` = monitor for collection;
another shows `code: 101, text: "Loan"`, which is a *category*, not a purpose.
**Do not write purpose codes from this research.** `[U]`

> **More importantly: no purpose code was found that describes *a chartered
> accountant maintaining a client's books*.** The nearest published analogue is
> "Spend and Investment Analytics". Purpose limitation is **enforced, not
> advisory**, so purpose-fit is a blocker to resolve *first*, not a formality.

### FI types — and GST is one

**23 FI types** across banking, insurance, pension, investments and tax `[P/S]`.
Confirmed: `DEPOSIT`, `TERM_DEPOSIT`, `RECURRING_DEPOSIT`, `EQUITIES`,
`MUTUAL_FUNDS`, `INSURANCE_POLICIES`, `NPS`, **`GSTR1_3B`**. `[U for the full
enumeration.]`

**GST is an FI type.** Schema `gstr1_3b_v1.1.0.xsd`, GSTN as the FIP regulated
for this purpose by the **Department of Revenue**, carrying Profile,
BusinessDetails and returns data, with the **fetch window capped at 18 months**.
`[P/S]`

> Scope discipline: that is **filed-return data**, not the invoice-level 2A/2B
> data the product reconciles. And **no ITR / income-tax FI type exists** — no
> proposal to make e-Return Intermediaries FIUs was found. `[U]`

## 3. Coverage — which independently confirms CLAUDE.md

**Live and reliable:** all major public and private sector banks. `[S]`

**Patchy or absent:**

> "Cooperative banks, Regional Rural Banks, small finance banks largely not
> AA-enabled." `[S]`

**And patchy *within* live banks, by account type** — the subtler trap `[S]`:

| Account type | Coverage |
|---|---|
| Savings, individual, singly held | all ~72 banks |
| Current account, sole proprietor | ~65 of 72 |
| Fixed and recurring deposits | **only ~40% of banks** |
| Jointly held and non-individual | significantly worse |

Sahamati publishes the per-bank per-account-type matrix and the FIP↔AA matrix.
No AA covers all ~176–179 FIPs; live counts run **Anumati 80+, CAMS 70+,
OneMoney 65+, Finvu 60+, NADL 60+** — which is why FIUs contract with several.

> **A CA's client base is precisely the population AA serves worst**: partnership
> firms, private limited companies, HUFs, and current accounts at co-operative
> and regional banks. CLAUDE.md names Cosmos Bank as the example and it holds up.
>
> **Statement upload staying at parity for years is not a hedge. It is the base
> case.**

## 4. Costs

**No published rate cards.** `[U]` Three models dominate `[S]`: per-consent
("a few rupees to tens of rupees per consent fulfilled"), subscription ("starts
in the lakhs per month"), or hybrid. All-in first-year **₹5–25 lakh+** — a single
blog's industry estimate, an order of magnitude, not a quote.

Model **per-client-per-month**, not per-fetch: a PERIODIC consent for monthly
bookkeeping is roughly 12–45 fetches per client per year.

⚠️ Several of the biggest TSPs **also own an AA** (Setu/Agya, Perfios/Anumati).
Buying both from one vendor is convenient and costs you leverage on FIP coverage.

## 5. Verify before relying on any of this

1. **The FIU eligibility position, with a legal opinion.** Task #123.
2. The full text of the NBFC-AA Directions 2025.
3. **The ReBIT purpose code list, and whether any code fits third-party
   bookkeeping.**
4. Whether the reciprocity duty binds an FIU holding no financial information.
5. The complete FI-type enumeration.
6. Current FIP coverage for the client types a CA actually serves.
