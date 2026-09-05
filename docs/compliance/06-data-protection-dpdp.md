# Data protection — the DPDP Act and Rules

Confidence grades and the sourcing caveat: see `00-how-to-read-this.md`.
**No primary source was read directly.**

---

## 0. Why this is the section with a real deadline

Everything else in this directory is optional work gated on a registration
somebody might never pursue. **This is not.** DPDP applies to PracticeSync
whether or not GST filing, ERI registration or the Account Aggregator is ever
built, and it has dates.

## 1. Status — VERIFIED, settled, and phased

**VERIFIED 2026-09-04**, including a search specifically for an extension,
deferral or industry reprieve. **None found**, and several sources say plainly
that no grace period is expected.

The **Digital Personal Data Protection Rules, 2025** were notified **13 November
2025** (G.S.R. 846(E) is the number most consistently cited for the Rules
themselves) and start an **eighteen-month phased rollout**. `[P/S]`

The phasing is set by **Rule 1 (Commencement)** and is unusually precise — it
names which rules switch on when:

| Phase | Date | Rules in force |
|---|---|---|
| 1 | **13 Nov 2025** | **Rules 1, 2 and 17–21** — definitions, and the Data Protection Board's own constitution and procedure |
| 2 | **13 Nov 2026** | **Rule 4** — Consent Manager registration opens |
| 3 | **13 May 2027** | **Rules 3, 5–16, 22 and 23** — notice, consent, security safeguards, breach reporting, retention and erasure, children's data, data-principal rights, SDF duties, cross-border |

> ⚠️ **Correction to an earlier draft of this file.** It said the Board "is
> constituted and can take complaints", implying exposure today. That
> overstates it. What commenced in November 2025 is the Board's own
> constitution and procedure (Rules 17–21) — **not the Data Fiduciary duties**,
> which are Rules 3 and 5–16 and do not exist until 13 May 2027. One source
> puts the Board's inquiry and penalty machinery at **13 Nov 2026**. `[S]`
>
> So there is, as yet, **nothing for a Data Fiduciary to be penalised for**.
> The deadline is real and fixed; the exposure is not retrospective.

**From today (September 2026): roughly 20 months to the substantive obligations,
and about 2 months to the Consent Manager date.**

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
hard number. **Verified 2026-09-04** `[S]`:

- **encryption in transit and at rest** (or obfuscation, masking, tokenisation);
- **access control on a need-to-know basis**, and authentication controls
  including **multi-factor authentication**;
- monitoring and **logging of personal-data access**, with **logs retained at
  least one year**;
- **regular security vulnerability assessments**;
- documented **incident response procedures**;
- business continuity and backup;
- **contractual flow-down of equivalent safeguards to processors**.

> The detail matters: this is not "have good security". It names MFA, need-to-know
> access, vulnerability assessment and a one-year access log as specific
> obligations — each of which is a discrete engineering task with a lead time.

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

1. **Rule 6** — encryption/tokenisation, MFA, access logging and the processor
   flow-down clauses. **See §5a: two of these are in a different state than this
   list assumed.**
2. **Rules 8 and 14** — tag every row with the **consent, purpose and retention
   expiry** that justifies it.

> On (2): *"If every record knows which consent and purpose it belongs to,
> expiring or deleting data on consent revocation or retention lapse becomes a
> query, not an archaeology project."* `[S]`
>
> That is **also exactly what an Account Aggregator `DataLife` would demand**, so
> it is not wasted work under either future. Build it once.

---

## 5a. What the code actually does — READ, not assumed (task #124)

Everything above is sourced from outside. This section is different: it is what
the repository and the production database say, checked on **2026-09-05**. Treat
it as fact about *this codebase*, not as a legal claim.

It corrects the section above in three places.

### MFA is BUILT, and it ships dark

Not a gap to fill — a switch to throw, plus a scope decision.

`core/auth.mfa_guard` requires an **aal2** token for roles in
`MFA_REQUIRED_ROLES`, and `main.py` already attaches it. But:

- **`REQUIRE_MFA` defaults OFF.** The guard is a no-op pass-through until it is
  set — deliberately, so it could ship before being validated in staging.
- **`MFA_REQUIRED_ROLES` defaults to `Partner` alone.**
- It guards **four** routers: assignments, identity, practice, billing — the
  firm-administration surfaces.
- **Payroll is not among them.** The separate platform-admin path
  (`require_platform_admin_mfa`) genuinely enforces aal2 today, but that is for
  destructive platform operations, not for the data.

So Rule 6's MFA obligation is a configuration and coverage question:
turn it on, decide the roles, and decide whether the surface that holds
**employee PAN, UAN, ESIC number, salary and bank account** should be behind it.
Per §2 that is the highest-exposure surface in the product.

> ⚠️ **Two of those bullets are corrected in §5c, which read production rather
> than the code.** `REQUIRE_MFA` defaults off *in code* but `render.yaml`
> records it as **`true` in production** — "ships dark" describes the default,
> not the deployment. And the real problem turned out not to be the flag at
> all: both Partners hold verified TOTP factors, and **every session since they
> enrolled is `aal1`, authenticated by password alone**. MFA was enrolled and
> never asked for. §5c has the measurements, the three fail-opens that caused
> it, and the role and surface decisions.

### The one-year log floor is already met — and the risk runs the other way

Rule 6 wants access logs kept **at least** a year. There is **no purge of
`audit_log` anywhere** — no job, no script, no scheduled sweep — and `UPDATE`
and `DELETE` are both blocked by database trigger. Retention is unbounded.

So this is not work. What it needs is to be *known*, because the failure mode is
somebody adding a tidy-up later and silently dropping below the floor. Noted in
`services/audit_service.py` where a person writing that purge would look.

### ⚠️ The erasure question is not open — it is answered, and it is worse

The earlier note called this an open question. It is not open; it just had not
been looked at. **Migration 111 puts an audit trigger on every firm-scoped table
with an `id` column**, minus a fixed exclusion list, and the trigger writes
**`to_jsonb(NEW)` and `to_jsonb(OLD)` — complete row snapshots** — into
`audit_log`, which is append-only by trigger.

Payroll is **not** on the exclusion list (which covers the audit log itself,
event feeds, derived tables, AI output and a few child tables). Neither are
customers, vendors or clients.

**Measured in production on 2026-09-05:** 46,311 audit rows since 19 June 2026,
and **1,469 of them already carry a `pan`, `uan` or `bank_account_number`** in
their snapshot — 1,304 customer, 160 vendor, 3 client, 2 firm. Payroll shows 2
rows only because payroll has barely been used yet; the mechanism covers it and
fires the moment it is.

> Not every one of those 1,469 is personal data — a private limited company's PAN
> is not. It is an upper bound, and the direction of travel is what matters.

**So personal identifiers are accumulating, at roughly 7,000 rows a year at
current low usage, in a table nothing can delete from.** And it cannot be fixed
retroactively: those rows can be neither edited nor deleted, by design. Every
month it runs, the permanent residue grows.

### The position

Two questions were being conflated.

**(a) Erasing a principal's record from the live tables.** Governed by statutory
retention, not by DPDP alone — DPDP does not override a retention duty imposed by
another law. Where the Companies Act, IT Act or GST require the record to be
kept, the answer to an erasure request is a **refusal with a reason**, in the
shape this codebase already uses everywhere else — never a silent no-op. That
needs a written retention position per data category, which is task #126.

**(b) Erasing the copy inside `audit_log`.** Different problem, and the real one.
The resolution is to **minimise what the log holds rather than delete from it**.
The log exists to show *who changed what, and when*. It does not need a
column-wise copy of the whole row to do that. `to_jsonb(NEW)` is the cheapest
thing to write and the most expensive thing to hold for ever.

The honest tension: shrinking the snapshot weakens the audit trail, which
CLAUDE.md treats as load-bearing — the proviso to Rule 3(1) of the Companies
(Accounts) Rules 2014 requires an edit log, and **the log is what is immutable,
not the entry**. So this is a trade-off for an owner, not a unilateral fix.

The options, and a recommendation:

| | Option | Effect |
|---|---|---|
| **A** | **Redact on write** — exclude a named list of identifier columns from the snapshot, for the tables that carry them | Stops the residue growing; the log still shows the change happened and which fields moved. **Recommended.** |
| B | Tokenise or hash the identifiers in the snapshot | Same effect, more machinery, and a hash of a PAN is still a re-identifiable value |
| C | Do nothing, and rely on the log being a record required by law under Rule 3(1) | A real argument, but it needs the legal opinion before it can be relied on — and it does nothing about volume |
| D | Add the payroll tables to migration 111's exclusion list | Worst of both: loses audit coverage exactly where the data is most sensitive |

**A for what is written from here; C as the legal backstop for the 1,469 rows
already there**, since they can neither be edited nor deleted whatever anyone
decides.

### ✅ DECIDED AND BUILT — migration 336

**A, taken.** `public.audit_redact` replaces the VALUE of a person's government
and financial identifiers in every trigger-written snapshot; `audit_capture`
routes both `to_jsonb(NEW)` and `to_jsonb(OLD)` through it.

**The key survives, only the value goes.** Dropping the key would lose the fact
that the field changed at all — the row would look identical to one where it did
not. `bank_account_no` still appears on both sides of the update that changed it,
each carrying `[redacted]`, so the log still answers *who changed what, and
when*. What is given up is the before/after value of one field: the part DPDP
objects to holding for ever, and the part an audit trail needs least.

Redacted — derived from the live schema, not from memory:

`pan` · `deductee_pan` · `deductor_pan` · `landlord_pan` · `lender_pan` ·
`vendor_pan` · `aadhaar_last4` · `uan` · `bank_account_no` · `account_number` ·
`date_of_birth` · `deductee_tin` · `tax_identification_number`

**Four near-misses deliberately left alone**, because over-redaction turns an
audit log into a list of timestamps: `gstin`/`supplier_gstin` (a business
registration, public on the portal, and the key a CA reads to know which
registration a change touched), `ifsc`/`ifsc_code`/`bank_ifsc` (a branch code
identifies a branch, not a person — harmless once the account number beside it is
gone), `bank_account_id` (a uuid FK, not an account number), and
`esic_employer_code` (the employer's registration). **Names, emails and phone
numbers are also kept** — personal data, but they are how a human reads an audit
row at all. That is the line to move first if the position must be stricter, and
the list is a single array constant so moving it is a one-line migration.

**Why this does not weaken the edit log.** Rule 3(1) is about accounting entries
— who altered a voucher, when, and what moved. A PAN, a UAN, an Aadhaar fragment
and a bank account number are none of those; no money moves when one changes, and
nothing in the list appears on `journal_entries`, `journal_lines` or any amount
column.

**One writer, because only one writer does this.** Measured before building: of
893 service-role rows written by `audit_service.log_event`, ZERO carry an
identifier — that path takes small hand-built intent dicts, not row snapshots.
All 1,470 identifier-bearing rows came through the trigger. A Python twin would
have been a second implementation of one rule, built for a case that does not
occur.

**The 1,469 already written are unchanged**, and cannot be otherwise: `audit_log`
blocks UPDATE and DELETE. Option C — the Rule 3(1) argument — remains the
position on those, and still wants the legal opinion behind it.

### What this became

| Task | | Kind |
|---|---|---|
| ~~#126~~ | ~~Write the retention position per data category, then refuse erasure with a reason~~ | **DONE — see §5b.** `domain/dpdp/retention.py`; the payroll delete now names the statute and the date |
| ~~#127~~ | ~~Decide what `audit_log` may hold~~ | **DONE — migration 336.** The residue stopped growing on the day it merged |
| ~~#128~~ | ~~Turn `REQUIRE_MFA` on, and decide whether payroll sits behind it~~ | **DONE — see §5c**, and it WAS a build: MFA was enrolled and never asked for. Roles → `Partner,Manager`; payroll behind the guard |
| ~~#129~~ | ~~Give the customer, vendor and client deletes the same statutory refusal~~ | **DONE — see §5d.** Customer and vendor wired; the client delete turned out not to erase anything |

None of it is urgent in the penalty sense — there is nothing to be penalised for
until 13 May 2027. **#127 was the one that was time-sensitive anyway**, because
it was the only item whose cost rose every month it waited; it is done.

## 5b. The retention position — WRITTEN AND BUILT (task #126)

`apps/api/domain/dpdp/retention.py` is the position. This table is written from
`position()` in that module, so the two cannot drift; the module is the
authority and this is its readable form.

### Why the position had to come first

DPDP **s. 8(7)** obliges erasure on withdrawal or when the purpose is served —
*"unless retention is necessary for compliance with any law for the time being
in force."* Every erasure request therefore runs into a prior question: which
law requires this kept, and until when? Until that was written down, tagging
every row with a retention expiry had nothing to write into the column, and
every answer to a data principal was invented on the spot.

### What the code was doing instead

**Every deletion guard in the codebase is REFERENTIAL.** `delete_employee`
refuses while a payslip exists; `delete_customer` while an invoice does;
`delete_client` while any history does. Each says "something points at this
row" — a different question from the one DPDP asks, and one that fails in a way
that gets worse with time:

> **A REFERENTIAL REFUSAL NEVER LAPSES.** A payslip from FY 2018-19 refused
> erasure in 2019 and would refuse it identically in 2050, long after every
> statute had released the record. From 13 May 2027 that is a standing failure
> to erase — and the refusal named no statute and no date, so nobody could tell
> whether it was right.

A retention duty is the opposite shape: **it ends**, and the date is computable.

### The anchor is the part that is easy to get wrong

Every period is measured from a different event, and reading them all as
"N years from the end of the financial year" is wrong in the direction that
destroys records. For **FY 2020-21**, the same books are held under three duties
that end on three different days:

| Duty | Measured from | Released |
|---|---|---|
| Companies Act s. 128(5) | the eight FYs immediately preceding | **31-03-2029** |
| Income-tax Rule 6F(5) | six years from the end of the **assessment** year | **31-03-2028** |
| CGST s. 36 | 72 months from the **annual-return due date** | **31-12-2027** |

**GST is the trap.** Seventy-two months runs from the GSTR-9 due date
(31 December following the FY) — *81 months* from the FY end, not 72. Anchoring
it to 31 March releases the record **nine months early**. The rule calls
`compliance_engine.gstr9_due_date` rather than restating 31 December, so an
extension moves it; a test pins that it asks rather than copies.

**Longest duty wins.** A payroll record is at once the employer's books, an
income-tax record and a provident-fund record, so the category is released only
when the last duty lapses.

### The position

| Category | Holds | Duties | Whose duty |
|---|---|---|---|
| **books_of_account** | a proprietor's or partner's name, PAN and bank details on the documents making up the ledger | Companies Act s. 128(5); IT Rule 6F(5); CGST s. 36 | client |
| **gst_returns** | GSTIN, and a proprietor's PAN within it | CGST s. 36; Companies Act s. 128(5) | client |
| **payroll** | PAN, UAN, ESIC number, date of birth, bank account, salary, Form 12BB — **the highest-exposure personal data in the product** | IT Rule 6F(5); Companies Act s. 128(5); **EPF ⚠**; **ESI ⚠** | client (as employer) |
| **tds_records** | the deductee's PAN and amounts against it | IT Rule 6F(5); Companies Act s. 128(5) | client |
| **income_tax_records** | an individual assessee's whole return | IT Rule 6F(5) | client |
| **client_onboarding** | PAN, GSTIN, identity documents, engagement record | PMLA s. 12 — 5 years | **firm** |
| **access_logs** | who read or changed what, and when | DPDP r. 6 — ≥ 1 year, a **floor** not a ceiling | **platform** |
| **support_correspondence** | whatever a person wrote to the firm | none identified | — |
| **product_telemetry** | which screens an account opened | none identified | — |

**Almost none of this is PracticeSync's own duty**, which is why `duty_holder`
reaches the refusal sentence. Telling an employee "we won't delete this" when
the truthful answer is "your employer must keep this until 2034" is a different
statement, and only one of them is true.

### ⚠ Two duties are real and their periods are NOT established

**EPF** and **ESI** are both in the state the state PT slabs and the s. 393
payment codes are in: the duty is certain, the period is not written here.

- **EPF** — search returns *75 years from the date of entry*, sourced to HR
  commentary rather than to a paragraph of the Scheme. A provident-fund
  entitlement is lifelong, so a very long period is plausible, **which is
  exactly why guessing it is unsafe**: it would put a specific date into a
  refusal a CA then relies on.
- **ESI** — Regulation 66 gives five years from the last entry for the
  **Accident Book specifically**. Whether the same period governs the register
  of employees is asserted by secondary sources and was not confirmed against
  the regulation that covers it. A period read off the wrong regulation is worse
  than none.

Adding either is a human step: read the provision, add it to the module.

### The refusal direction is REVERSED here, deliberately

Elsewhere an unmodelled statutory figure means *do not compute* — an unlisted PT
state deducts nothing. Here it must mean **do not delete**, because the action
being authorised is irreversible:

- an **unknown category** refuses. The registry is closed; a category nobody has
  classified is not an unregulated one.
- an **unestablished period** refuses and names itself as a gap.
- an **unanswerable question** (a period-anchored duty asked without a period)
  refuses and says what to ask again with.
- a category with **no duty at all** is erasable — different from an unread one,
  and only this one releases.

All three kinds of refusal are reported together. An earlier version returned on
the first it found, so a payslip whose month could not be read said "tell me the
period" and never mentioned EPF and ESI — which do not depend on the period at
all. A refusal naming one of three reasons invites the reader to fix that one
and expect the record to be released.

### What is wired, and what is not

**Wired:** `DELETE /payroll/employees/{id}`. Payroll is the doc's own named
highest-exposure surface and an employee is the paradigm data principal, so this
is where an erasure request actually lands. It now answers with the statute, the
duty-holder and the date — for FY 2025-26 payroll, *until 31 March 2034* — plus
the two unestablished duties, instead of "this employee has payroll history".

**Also wired, in #129:** the customer and vendor permanent deletes. Their
dependency queries now return each table's own date column — they differ
(`invoice_date`, `receipt_date`, `bill_date`, …) and reading the wrong one
anchors retention to the wrong year — and the newest dated record drives the
refusal. `services/party_erasure.py` writes the sentence once for both.

**Not wired, because it is not an erasure path:** `DELETE /clients/{id}`.
`client_repo.soft_delete` sets `deleted_at` and destroys nothing, so a retention
refusal there would tell a CA they may not *hide* a client until 2034 — false,
and unhelpful. A test pins that the endpoint stays free of one, and fails if
that soft delete ever starts destroying rows.

**Also not built:** publishing the position under Rule 14. `position()` emits
the structure a notice or a DPA annexe needs, and nothing serves it yet.

### Sourcing

Search results only. **No primary source could be fetched** — `indiankanoon.org`
and `taxinformation.cbic.gov.in` are both blocked by the network egress proxy
from the build environment, so the grades in `00-how-to-read-this.md` apply and
each rule carries its own `confidence`. Nothing is graded `[P]`. Verified
2026-09-05.

## 5c. MFA — the flag was never the blocker (task #128)

### What the task assumed, and what production says

#128 was written as "configuration and scope, not a build": validate
`REQUIRE_MFA` in staging, turn it on, decide the roles and surfaces. Two of
those three premises did not survive contact with the data.

**`render.yaml` already says `REQUIRE_MFA` is `true` in production** — it is
`sync: false`, so the value lives in the Render dashboard and no test can see
it, but the manifest's own comment records it as on and gives its evidence.
§5a's "it ships dark" describes the CODE DEFAULT, not the deployment.

**And it has never bitten anyone.** Measured 2026-09-05: the four routers the
guard is attached to — assignments, identity, practice, billing — have seen **no
activity at all** since MFA was enrolled on 2026-08-15. Not one event in
`audit_log`. Whatever the dashboard holds, the control had never once met a real
request.

### The finding: MFA is enrolled and is not being asked for

| measured on production, 2026-09-05 | |
|---|---|
| users | 2, both Partner |
| with a **verified** TOTP factor | **2** (enrolled 2026-08-15) |
| sessions created since enrolment | **89** |
| …of those, `aal2` | **1** — on enrolment day itself |
| …of those, carrying a `totp` AMR claim | **1** |
| browser writes to `audit_log` on 3 September | **162**, from `aal1` sessions |

Every session since enrolment authenticated with `password` alone. The app is in
daily use on those sessions. **So the challenge is not happening**, and turning
enforcement up — or adding a daily-use surface to the guard — would have 403'd
both of the product's users.

### Why, by reading: three fail-opens in a row

```
try {
  const { data } = await auth.mfa.getAuthenticatorAssuranceLevel();
  return !!data && data.currentLevel === "aal1" && data.nextLevel === "aal2";
} catch { return false; }          //  (1) an error means "nothing owed"
```

1. `catch { return false }` turns *I could not tell* into *nothing is owed*, and
   a null `data` does the same.
2. The caller repeated it: `.catch(() => setMfaPending(false))`.
3. `AuthGuard` rendered the app while the answer was still `null`.

It also asks the wrong oracle. `nextLevel` is derived from the **user object the
client happens to hold**, so a session restored from storage whose cached user
carries no `factors` array reports `aal1` — nothing owed — for an account with a
verified factor in the database. That matches the shape of the evidence exactly:
the challenge worked on enrolment day, when the user object was fresh, and has
not been asked for since.

`lib/auth/mfaAssurance.ts` now asks **both** oracles and believes whichever
reports a factor, treats a null payload as no answer, retries, and then fails
**closed**. `lib/auth/guardDecision.ts` makes "unresolved is not permission" a
tested predicate rather than an inline line nobody could test.

> **What this does not prove.** That it makes production sessions `aal2`. The
> evidence establishes the OUTCOME; the fix removes a fail-open that would
> produce exactly that outcome. Confirming cause needs one real login against
> the deployed app, which no test here can do.

### The two decisions

**Roles: `Partner,Manager`** (was `Partner`). The guard filters by role, so the
role list and the guarded routers have to be chosen together — payroll RBAC is
**Manager+**, so putting payroll behind the guard while the list held only
Partner would leave every Manager who runs payroll unchallenged. Enforced-looking
and not enforced. Executive and Reviewer are deliberately out: neither can reach
payroll nor any of the four administration routers, so adding them would be a
login step protecting nothing. **If a surface they can reach ever goes behind the
guard, this list must be revisited in the same change** — a test asserts the pair.

**Surfaces: payroll joins the four.** It is the highest-exposure personal data in
the product and the first guarded router that holds DATA rather than firm
administration.

### The one step left, and why it is the owner's

`MFA_REQUIRED_ROLES` is not declared in `render.yaml` — it is exempt, so
production reads the **code default**, which this change moves to
`Partner,Manager`. That much ships with the merge.

`REQUIRE_MFA` itself is `sync: false` and cannot be read or set from here.
Nothing in this change turns it on or off. After deploying, confirm the fix did
what the evidence says it should:

```sql
SELECT s.created_at::date, s.aal,
       string_agg(DISTINCT c.authentication_method, ',') AS methods
  FROM auth.sessions s
  LEFT JOIN auth.mfa_amr_claims c ON c.session_id = s.id
 WHERE s.created_at >= now() - interval '2 days'
 GROUP BY 1, 2 ORDER BY 1 DESC;
```

**`aal2` with a `totp` claim means it worked.** Another day of `aal1` /
`password` means it did not, and payroll is now behind a guard whose flag may be
on — so check this before the next payroll run, not after.

## 5d. The party deletes, and the question #126 left open (task #129)

### Two reasons under one sentence

`delete_customer` and `delete_vendor` refused with a single line — *"this
customer has linked accounting records and cannot be permanently deleted"* —
which names no law, gives no date, and never lapses. But the guard was doing
**two different jobs** under that one sentence, and they come apart:

| reason | does it end? |
|---|---|
| **Retention** — the law requires the record kept | **yes**, on a computable date |
| **Referential** — other rows point at this one | **no**, while the documents exist |

That matters because the customer FKs are `ON DELETE CASCADE`, and two of the
vendor tables carry a `vendor_id` with **no FK at all** — so a hard delete
either destroys linked records silently or strands them pointing at a party that
no longer exists.

`services/party_erasure.py` writes the sentence once for both routers, and says
which reason applies.

### The dates come from each table's own column

The dependency queries selected `id` alone. They now select the table's own date
column, and the **newest** dated record drives the refusal — retention runs from
the financial year of the record, so the most recent one is held longest:

| table | column | | table | column |
|---|---|---|---|---|
| `client_sales_invoices` | `invoice_date` | | `purchase_bills` | `bill_date` |
| `receipts` | `receipt_date` | | `purchase_payments` | `payment_date` |
| `credit_notes` | `credit_note_date` | | `debit_notes` | `debit_note_date` |
| `recurring_invoice_templates` | **none** | | `purchase_credit_notes` | `credit_note_date` |

**The recurring template is undated deliberately.** It is a SCHEDULE, not an
accounting record: `start_date` says when billing begins, not when a transaction
happened, so dating a statutory duty from it would anchor retention to a diary
entry. It still blocks the delete — a live template pointing at a deleted
customer is a bug — but on referential grounds, which is the honest reason. An
opening balance is undated for the same reason, and the refusal says so rather
than invoking a statute it cannot date.

### A lapsed duty does NOT permit the delete — the answer to #126's open question

Retention lapsing means **the law no longer requires you to keep this**. It does
not mean nothing else needs it: the invoices are still referenced by posted
journal entries, by GST returns already filed, and by the ageing schedules.
Cascading them away because a statute stopped compelling their retention would
destroy posted books to satisfy a request the law does not make.

So the refusal stands either way, and what changes is **what it says**:

- before the date — *"Companies Act 2013 (s. 128(5)) requires the client to keep
  books of account … until 31 March 2034. Until then this customer cannot be
  permanently deleted."*
- after it — *"Statutory retention over this customer's records has lapsed — no
  law now requires them kept. It still cannot be permanently deleted: … deleting
  the customer would cascade them away."*

A CA can now see whether the obstacle is the law or the books.

### The client delete is not an erasure path

#129 asked for all three. `DELETE /clients/{id}` calls
`client_repo.soft_delete`, which sets `deleted_at` / `is_deleted` and **destroys
nothing**. Putting a retention refusal there would tell a CA they may not *hide*
a client until 2034 — false, and unhelpful. Erasure refusals belong on paths that
erase. A test pins that the endpoint stays free of one, and fails if that soft
delete ever starts destroying rows.

## 6. Consent Managers — and why the product must not become one

A **Consent Manager** is a DPDP-registered entity through which a principal
gives, manages and withdraws consent. **Verified 2026-09-04** `[S]`.

**First Schedule Part A** — registration conditions: incorporated in India,
**net worth ≥ ₹2 crore** (inflation-adjusted annually), conflict-of-interest
policy, secure infrastructure, audit-ready logging.

**First Schedule Part B** carries the conflict rule, and it is confirmed:

> A Consent Manager **may not simultaneously act as Data Fiduciary or Data
> Processor for the same data principal whose consent it manages.**

Part B also requires **non-discrimination** — consent flows facilitated neutrally
across all fiduciaries, no preferential treatment — and **transparent published
pricing**, with no revenue from data sharing or consent manipulation. The role is
designed as a *data-blind neutral intermediary*.

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
