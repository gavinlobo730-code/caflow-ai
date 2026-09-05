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

> ⚠️ **#102 found that the first two routes may both fail for a reason that has
> nothing to do with eligibility — see §2.** A purpose code is derivative of the
> FIU's own regulatory permission, so a partner FIU's permitted purposes come
> from *its* licence, and bookkeeping is not within an NBFC-lender's or an
> investment adviser's. Buying a SEBI RIA registration buys **CT004, Wealth
> Management and/or Advisory** — advising on investments, not writing up a
> ledger. **Read §2 before pricing either route.**

### What this means for tasks #102–#107 — REWRITTEN (task #123)

Those six tasks were written on the assumption that registering as an FIU via a
TSP is the path. **#104 in particular — "complete FIU registration/onboarding
via the chosen TSP" — described something that does not exist.**

They are now sequenced as **three gates, cheapest-and-most-fatal first**. The
reordering is the substance, not the relabelling: two questions below are free,
and either can end the project before a rupee is spent.

**Gate 0 — free, and either answer can stop everything**

| | |
|---|---|
| ~~#102~~ | ~~Is there a lawful PURPOSE for a CA keeping a client's books?~~ **ANSWERED — provisionally NO. §2.** |
| **#103** | **What percentage of THIS firm's clients could AA actually reach?** |

**#102 is upstream of FIU eligibility**, which is the non-obvious part. Eligibility
is solvable with money — buy a registration, or partner with someone who has one.
Purpose is not. The consent artefact carries a `Purpose`, the FIP validates every
fetch against it, and purpose limitation is **enforced**. If no purpose honestly
covers third-party bookkeeping, then a fully licensed FIU still could not pull
this data for this use, and every rupee spent on eligibility is wasted.

> **#102 is now answered, provisionally, and it is worse than "not found".** No
> published purpose or Fair Use Template describes third-party bookkeeping, and
> the reason is structural: a purpose is derivative of the FIU's own regulatory
> permission, and bookkeeping is not a regulated financial activity under any of
> the five regulators. **That defeats the partner route as well as the
> registration route** — see §2. What is NOT settled is whether a purpose could
> be *added*, which only Sahamati can answer, so #103–#107 stay open pending
> that question and a reading of the actual taxonomy.

**#103 settles the commercial case independently.** §3 shows a CA's client base is
precisely the population AA serves worst. If most clients are unreachable, the ROI
question is answered before the legal one.

**Gate 1 — paid, only if Gate 0 clears**

| | |
|---|---|
| **#104** | Legal opinion on eligibility, then **choose one of the three routes** |
| **#105** | DPDP obligations, incl. `DataLife` as a clock separate from consent expiry |

**Gate 2 — build, only once a route is chosen**

| | |
|---|---|
| **#106** | The consent flow — approval happens **at the AA**, callback-driven, annual re-consent |
| **#107** | Contract and pilot, shaped by whichever route #104 chose |

**Stopping is a real outcome.** If #102 finds no honest purpose, or #103 finds the
coverage is not there, the answer is to close #104–#107 and keep statement upload.
Per §3 that is the base case anyway, not a fallback.

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

### ⚠️ Purpose codes — ANSWERED, provisionally, and the answer is no (task #102)

**The question:** is there a lawful purpose under which a CA firm can pull a
client's bank data to keep that client's books? Purpose limitation is enforced —
the FIP validates every fetch against the artefact's `Purpose` — so if no purpose
honestly covers this, **no route works and no amount of spend fixes it.**

**Provisional answer: NO — and the reason is structural, not a gap in a list.**

#### What was found

The Sahamati **Fair Use Template Library** publishes 20+ templates. Those whose
identity could be confirmed from page titles `[P/S]`:

| ID | Use case |
|---|---|
| CT001 | Loan Underwriting |
| CT003 | Account Monitoring |
| CT004 | Wealth Management and/or Advisory Services |
| CT006 | Income Verification |
| CT042 | Employee/Vendor Monitoring |
| CT045 | Employee/Vendor Verification (one-time) |

The B2B half of the library covers *enterprise risk, compliance, operational
monitoring and onboarding* — employment disclosures, vendor onboarding,
compliance reporting, counterparty assessments, government programme
participation. `[S]`

**Every one of them is a data user assessing SOMEBODY ELSE'S risk.** That is the
wrong shape for this. A CA writing up a client's ledger is not assessing the
client as a counterparty; the client is the firm's **principal**, not its
subject. No template, and no purpose code, was found that describes maintaining
another person's books.

#### The structural reason — and it defeats the partner route too

This is the part that goes beyond "none published". Purpose codes are **not free
labels an FIU picks**. Sahamati's guideline **PC001** maps FIU use cases to
purpose codes *by type of use case*, and the guidance on purpose code 102
("Customer spending patterns, budget or other reportings", category *Personal
Finance*) says FIUs using it must ensure their implementation is **within the
scope of their regulatory permissions**. `[S]`

So a purpose is derivative of the FIU's own registration, exactly as FIU status
itself is (§0). Which means:

> **Partnering with a regulated FIU does not rescue purpose-fit.** A partner
> FIU's permitted purposes flow from *its* licence. Pulling a client's bank data
> so a third-party CA can write up their books is not within an NBFC-lender's or
> an investment adviser's regulatory permission. Option 1 of the three in §0
> solves eligibility and still fails here.

It also sharpens the SEBI-RIA idea floated in §0 as "most plausible". An RIA maps
onto **CT004, Wealth Management and/or Advisory** — advising on investments. It
does not map onto bookkeeping. Acquiring that registration would buy a purpose
the product does not want.

**Bookkeeping is not a regulated financial activity under any of the five
regulators.** That is why no purpose covers it, and it is not the kind of gap a
Fair Use Template can close — a template sets *bounds* on an existing purpose,
it does not create regulatory permission.

#### A near-miss to not repeat

ICAI's Code of Ethics bars a CA from listing on **service-marketplace
aggregators**. `[S]` That is a different word wearing the same clothes — nothing
to do with **Account** Aggregators, and it is not evidence either way here. It
surfaces on the obvious searches, so it is recorded to stop somebody citing it.

#### ⚠️ The sourcing limit, which is worse than last time

**Not one primary source could be read.** Every `WebFetch` in this session was
refused by the network egress proxy — `api.rebit.org.in`,
`specifications.rebit.org.in`, `sahamati.org.in`, and, on a control attempt,
**`en.wikipedia.org` as well**. The block is not specific to Indian government or
regulator hosts; **fetching is unavailable, full stop.** Search snippets were the
only channel.

So the purpose-code fragments remain contradictory and **must still not be
written down as a table** — an earlier round had `103` = loan application and
`104` = collection monitoring against another source's `101` = "Loan" (a
*category*, not a purpose). This round adds `102` = "Customer spending patterns,
budget or other reportings", *Personal Finance*. Three fragments, no authority.
`[U]`

#### What is settled, and what is not

The task's stop condition is *"no honest purpose exists **and** none can be
added"*. Only the first half is established, and only provisionally:

- **Established `[S, triangulated]`** — no published purpose or template
  describes third-party bookkeeping, and the framework's design explains why.
- **NOT established** — whether one could be added. That is a question for
  **Sahamati** (RBI-recognised SRO since 05-06-2026) and nobody else. A TSP
  cannot answer it and is paid to say yes.

**So #103–#107 are NOT closed on this evidence.** Two things must happen first,
and both are somebody with a browser rather than more research from here:

1. **Read the actual taxonomy** — `api.rebit.org.in/purpose/`, the
   `sahamati.org.in/aa-community-guidelines-purpose-codes/` page, and guideline
   **PC001**. If a purpose does cover this, everything above is wrong and cheaply
   corrected.
2. **Ask Sahamati directly**, in these words: *"Under which purpose code, if any,
   may a chartered accountancy firm obtain a client's bank transaction data for
   the purpose of maintaining that client's books of account — and if none
   exists, what is the process for proposing one?"*

**If the answer is none and none can be added, close #103–#107 and keep
statement upload.** That remains a legitimate outcome: §3 already argues upload
is the base case rather than a fallback, because a CA's client base is precisely
the population AA serves worst.

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

Each now has an owner in the rewritten sequence above, and the two free ones
come first:

| # | To verify | Task |
|---|---|---|
| 1a | ~~Whether any code fits third-party bookkeeping~~ — **answered provisionally NO, §2.** No published purpose or template describes it, and purposes are derivative of the FIU's own regulatory permission | ~~#102~~ **done** |
| 1b | **Read the actual taxonomy** (`api.rebit.org.in/purpose/`, Sahamati's purpose-codes page, guideline **PC001**) and **ask Sahamati whether a purpose can be ADDED.** Still no purpose code should be written from research — every fetch was blocked, including Wikipedia | **#102 follow-on**, gates #103–#107 |
| 2 | **Current FIP coverage for the client types a CA actually serves** — from Sahamati's own matrices, against a real client book | **#103** (gate 0) |
| 3 | **The FIU eligibility position, with a legal opinion**, and the full text of the NBFC-AA Directions 2025 | **#104** (gate 1) |
| 4 | Whether the reciprocity duty binds an FIU holding no financial information | **#104** (gate 1) |
| 5 | The complete FI-type enumeration | **#106** (gate 2) |

Note the swap: items 1 and 2 were listed last in the first pass and are now
first, because they cost nothing and either can close the whole line of work.
