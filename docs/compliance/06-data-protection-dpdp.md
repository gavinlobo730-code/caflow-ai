# Data protection — the DPDP Act and Rules

Confidence grades and the sourcing caveat: see `00-how-to-read-this.md`.
**No primary source was read directly.**

---

## 0. Why this is the section with a real deadline

Everything else in this directory is optional work gated on a registration
somebody might never pursue. **This is not.** DPDP applies to PracticeSync
whether or not GST filing, ERI registration or the Account Aggregator is ever
built, and it has dates.

## 1. Status — settled, and phased

The **Digital Personal Data Protection Rules, 2025** were notified by MeitY on
**13 November 2025** and gazetted **14 November** (G.S.R. 843–846(E)) — 23 rules
plus schedules. `[S — very widely and consistently reported]`

| Phase | Date | What comes into force |
|---|---|---|
| 1 | **13 Nov 2025** | Definitions; **the Data Protection Board is constituted and can take complaints** |
| 2 | **13 Nov 2026** | **Consent Manager registration opens** |
| 3 | **13 May 2027** | **All substantive Data Fiduciary obligations** — notice, consent, security, breach reporting, retention/erasure, data-principal rights, SDF duties, cross-border |

⚠️ A minority of sources write 14 Nov / 14 May, counting from gazette
publication rather than notification. Use the 13th and note the ±1 day.

> **From today (September 2026): about 20 months to the substantive obligations,
> about 2 months to the Consent Manager date, and the Board is already live.**

## 2. Scope — narrower than it first looks, but not where it matters

A **Data Principal is an individual**, and DPDP governs **digital personal
data**. A private limited company's GST returns, trial balance and bank
statements are **not personal data**. `[S]`

But the exemption is narrower than it sounds for this product. In scope:

- **sole proprietors and individual assessees** — the whole ITR module;
- **partners, directors and authorised signatories** — PAN, DIN, contact details;
- and above all **payroll**: employee PAN, Aadhaar-linked UAN, ESIC number,
  salary, bank account, Form 12BB family and dependant data.

> **Payroll is the highest-exposure surface in the product, by a distance.**

Extraterritorial: applies to processing outside India relating to offering goods
or services to data principals in India. `[S]`

## 3. Two hats, and the contract that follows

- The **CA firm is a Data Fiduciary** for its clients' personal data — it decides
  what is collected, why, how long, and with whom it is shared. `[S]`
- **PracticeSync is a Data Processor** for that data.
- **PracticeSync is also a Data Fiduciary in its own right** — for the firm's
  staff accounts, billing contacts, telemetry and support correspondence.

> **A Data Processing Agreement with every CA firm is coming whether or not
> anyone writes one.** Rule 6 obliges the fiduciary to flow equivalent security
> obligations down by contract, so firms will start asking well before May 2027,
> and it will become a sales gate.

## 4. Lawful basis — do not architect on §7(a)

Consent under **§6** must be free, specific, informed, unconditional and
unambiguous, by clear affirmative action, with **withdrawal as easy as giving**.

**§7(a) "certain legitimate uses"** permits processing without consent for the
purpose for which the principal **voluntarily provided** the data. A client
handing their CA a PAN and bank statements to get a return filed looks like a
textbook case.

⚠️ **But it is genuinely contested.** One line of argument requires the principal
to have **initiated the sharing unprompted** — which a CA's document-request
checklist arguably defeats. `[S — actively disputed]`

> **Build the consent path. It is a superset.** And note §7(a) would **not** cover
> secondary uses at all — training AI on client documents, analytics,
> benchmarking. Those need consent regardless, which is directly relevant given
> the product sends documents to Groq and Gemini.

## 5. The obligations, and the two worth starting now

**Rule 3 — Notice.** A **standalone** notice, not buried in terms, in plain
language, with an **itemised list** of data collected, the specific purposes, and
**direct links** to withdraw consent, exercise rights and complain. `[S]`

**Rule 6 — Security safeguards.** The most directly actionable, and it carries a
hard number: `[S]`

- encryption, obfuscation, masking **or** tokenisation;
- access control;
- continuous monitoring and logging for detection and investigation, with
  **logs retained at least one year**;
- business continuity and backup;
- **contractual flow-down of equivalent safeguards to processors**.

**Rule 7 — Breach notification, two stages:** `[S]`

1. To the Board **without delay** on becoming aware.
2. To the Board **within 72 hours** — updated description, remedial measures,
   findings on cause.
3. To **affected principals without delay**, in plain language.

> **The clock starts on awareness, not on finishing the investigation.**
> Penalty for notification failure: up to **₹200 crore**.

**Rule 8 — Retention and erasure.** Erase on withdrawal or when the purpose is
served. A **three-year inactivity** limit with **48-hour advance notice** applies
to specified classes in the Third Schedule (e-commerce, social media, online
gaming above user thresholds).

> A CA practice platform is **almost certainly not** in those classes `[U —
> confirm against the Third Schedule]`, and it would collide with statutory
> retention (Companies Act, IT Act, GST) if it were. **DPDP does not override a
> retention duty imposed by another law** — but the interaction needs a written
> position per data category.

**Rule 13 — Significant Data Fiduciary.** Annual **DPIA** and independent audit;
**algorithmic due diligence** (the AI copilot is in scope of the concept); an
**India-based DPO answerable to the Board of Directors**; and **targeted
localisation** the Government may specify. Designation is **by Central Government
notification**, not self-assessment, on volume/sensitivity and risk criteria.
`[S]` ⚠️ Numbering moved between draft and final Rules — SDF was Rule 12 in the
draft, **Rule 13** in the final. Much published commentary still uses the draft
numbering.

A single-country CA SaaS is an unlikely SDF. A platform holding payroll for a
large share of India's SMEs is a **less unlikely** one over time.

**Rule 14 — Data principal rights.** Access, correction, erasure, grievance
redressal, nomination; the means of exercising them must be **published**.
⚠️ A "90 days" grievance cap appeared once and could not be corroborated. `[U]`

**Rule 15 — Cross-border transfer.** **Permissive default with a negative list** —
transfer abroad is permitted unless the Government restricts it by order. India
chose this over an adequacy model. `[S]`

> **Directly relevant to this deployment.** Postgres is in Mumbai, but `apps/api`
> runs on **Render in Singapore**, and Groq and Gemini calls leave India
> entirely. **Under Rule 15 as notified, that is permitted by default.** Two
> caveats: an SDF designation could reach specified categories under Rule 13, and
> the negative list can be issued at any time. **A policy risk to monitor, not a
> settled problem.**

**Penalties:** up to **₹250 crore** for failure to take reasonable security
safeguards where a breach occurs; **₹200 crore** for notification failure and
children's-data violations. **All monetary — no criminal sanction.** `[S]`

### The two items worth starting now

1. **Rule 6** — one-year log retention, encryption/tokenisation, and the
   processor flow-down clauses.
2. **Rules 8 and 14** — tag every row with the **consent, purpose and retention
   expiry** that justifies it.

> On (2): *"If every record knows which consent and purpose it belongs to,
> expiring or deleting data on consent revocation or retention lapse becomes a
> query, not an archaeology project."* `[S]`
>
> That is **also exactly what an Account Aggregator `DataLife` would demand**, so
> it is not wasted work under either future. Build it once.

⚠️ **An open question nobody addressed:** how a DPDP erasure request interacts
with the **append-only `audit_log`** — which CLAUDE.md correctly treats as the
thing that is immutable — and with statutory retention. `[U]` It is a real
question and it needs a written position before May 2027.

## 6. Consent Managers — and why the product must not become one

A **Consent Manager** is a DPDP-registered entity through which a principal
gives, manages and withdraws consent. Registration conditions: incorporated in
India, **net worth ≥ ₹2 crore**, conflict-of-interest policy, secure
infrastructure, audit-ready logging. `[S]`

**First Schedule Part B carries a hard conflict rule: a Consent Manager may not
act as Data Fiduciary or Data Processor for the same data principals it serves.**

> **So PracticeSync must not become a Consent Manager. That rule would forbid the
> product.**

## 7. Where AA and DPDP meet

**Does AA consent satisfy DPDP consent? Substantively largely yes; formally
unresolved.** `[S]`

The AA framework already implements notice, purpose limitation, collection and
usage limitation, and explicit revocable machine-readable consent — the DPDP
principles, built years earlier. Sahamati's position is that the regimes read
harmoniously **if AAs register as Consent Managers for the financial sector**.

But Rule 4 requires *any* entity performing consent-manager functions to register
with the Board, while AAs are licensed and supervised by RBI. Whether an AA must
*additionally* register, and which regulator's enforcement prevails, is unsettled
— commentary calls it a **"regulatory paradox"**. `[U — registration only opens
13 Nov 2026, so probably nothing has happened yet.]`

> **The practical position: AA consent covers *acquiring* the data from the FIP.
> It does not discharge what you then do with it.** Notice, purpose limitation,
> security, retention, erasure and data-principal rights all still land on you.
> **Two consent layers, not one.**

### Why a CA-facing product is structurally different

Every AA use case in the published material is **first-party** — a lender pulling
its own applicant's data. A CA product is **third-party by construction**.

1. **The consent is the client's and is given at the AA** — not in your UI, not
   delegated. CLAUDE.md already says this and it is right.
2. **The client can revoke without telling the CA.** The product must degrade
   gracefully mid-engagement, and needs a re-consent journey plus the annual
   renewal the ≤1-year fair-use validity forces.
3. **Two Data Fiduciaries in the chain, and the FIU is neither.** The client is
   the principal, the CA firm the fiduciary, PracticeSync the processor — but
   under the AA framework the **FIU** is accountable for purpose limitation, and
   the FIU cannot be either of them (see `05`). **Whoever the regulated FIU is,
   they are accountable for a purpose being served by two other parties.** That
   is the hardest thing to paper in a partnership structure, and it is a reason
   to be sceptical of the shell-FIU route on commercial grounds as well as
   regulatory ones.
4. **Professional confidentiality and DPDP are additive.** ICAI's duty and DPDP
   sit on top of each other; neither displaces the other, and confidentiality now
   has to be **documented and demonstrable** rather than merely professional.
