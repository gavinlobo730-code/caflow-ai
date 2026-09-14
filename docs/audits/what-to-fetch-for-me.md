# What to fetch for me — one list per website

*Written 14 September 2026, 22:20 IST. Supersedes nothing; it is the list I
said I would hand over once everything I could build without you was built.*

**Why this document exists.** Ten findings are not closed. Eight of them are
not blocked on code at all — they are blocked on a page this environment
cannot open. Direct egress is refused at the proxy (`curl https://example.com`
→ CONNECT 403), so every `.gov.in`, `icai.org` and bank portal is unreachable
from here. Search-engine *summaries* still reach me, which is why so much is
graded `[S]` in the codebase: I know what the sources say about these figures,
and I have never read one.

**The rule this whole codebase follows, and why I am asking instead of
guessing.** Every one of these numbers is money a CA pays over on a client's
behalf, or a file a portal will reject. A figure written from memory that is
four times too small is worse than a blank that says "go and read this" —
the blank gets read, the wrong number gets filed. So every gap below is
already a *named refusal* in the code with a sentence pointing at the document
to read. **Nothing is broken and nothing is waiting: each engine works the
moment the figure is written in.**

**How to use this.** Each section is one website and one sitting. Bring back
the file or a screenshot/copy-paste of the page — I do not need it typed up or
interpreted, and raw is better than summarised. If a page has moved or a
figure has changed since, that is itself the answer and worth telling me.

**Ranked.** §1–§3 unblock a complete feature each. §4–§6 are single numbers
holding up engines that are otherwise finished. §7 is the annual hand-off that
will come round every year regardless. §8 is the long tail — real gaps, none
urgent, and the biggest single lever in the file if you ever want it.

---

## 1. cbic-gst.gov.in — the GST late-fee and interest notifications

**Unblocks:** GST-21's remaining half. The §50 *interest* engine is built and
on screen; the §47 *late fee* refuses, and one interest rate is a named gap.

Go to **cbic-gst.gov.in → Notifications → Central Tax** and find these six.
What I need off each is small: the per-day amount, the cap, and which return
and which taxpayer it applies to.

| notification | date | what I need from it |
|---|---|---|
| **4/2018-Central Tax** | 03-01-2018 | the reduced §47 late fee for GSTR-1 — per-day figure, and the separate NIL-return figure |
| **76/2018-Central Tax** | 31-12-2018 | the same for GSTR-3B — per-day, NIL-return, and the cap |
| **19/2021-Central Tax** | 01-06-2021 | the turnover-band caps for GSTR-3B (the bands themselves and the rupee cap for each) |
| **20/2021-Central Tax** | 01-06-2021 | the same for GSTR-1 |
| **07/2023-Central Tax** | 31-03-2023 | the GSTR-9 late-fee rationalisation by turnover band, if this is the right notification number |
| **09/2022-Central Tax** | 05-07-2022 | **the single most valuable line in this file** — see below |

### The one that matters most: §50(3)

This is question 7 in `questions-for-the-owner.md`, and it is a correction I
made to my own work. §50(3) charges interest on input tax credit **wrongly
availed and utilised**. Two readings, and a *third* of the charge separates
them:

- Notification **13/2017-CT** notified **24%** — but against the ORIGINAL
  §50(3).
- The **Finance Act 2022** substituted §50(3) retrospectively from 01-07-2017,
  and Notification **09/2022-CT** appears to notify **18%** for the substituted
  text.

`SECTION_50_3_NOTIFIED_RATE_BPS` is `None` and the engine refuses rather than
picking. Over-stating takes money from a taxpayer who does not owe it, which is
the direction I will not fail in. **What I need: the text of 09/2022-CT — does
it notify 18% for §50(3), and from what date?**

> **Also worth knowing, whether or not you fetch anything:** has any
> notification after 20/2021 changed the late-fee figures? I am asking blind
> about the last four years here.

---

## 2. einvoice1.gst.gov.in — the e-invoice INV-01 schema

**Unblocks:** GST-32 in full. There is no INV-01 payload builder anywhere in
the repo today — the e-invoice rails are "prepare-only" and prepare nothing.

This is the **highest-value item in the whole file**, and the reason is in
`docs/compliance/07-getting-permission-to-file.md`: **e-invoice IRN and e-way
bill are the only two statutory outputs software can complete end to end**,
because the IRP signs the invoice and there is no taxpayer signature to
collect. Everything else (GSTR-1, GSTR-3B, TDS, ITR) needs a GSP or ERI
registration that is months of commercial work. This one does not.

Go to **einvoice1.gst.gov.in → Specifications** (there is usually a "Schema"
and an "API" tab) and bring back:

1. **The INV-01 JSON schema** — the current version, whatever it now is. This
   is the actual `.json` file if it is downloadable, otherwise the schema
   tables from the specification PDF.
2. **The master codes lists** — UQC codes, state codes, supply type, document
   type, port codes. These are usually one page or one spreadsheet.
3. **The validation rules document** — often called "e-Invoice Schema
   Validations" or similar. This is what tells me which combinations the IRP
   rejects, and it is the difference between a builder that works and one that
   produces files the portal refuses.
4. **The 30-day reporting-window advisory.** My understanding is that
   taxpayers above a turnover threshold must report an invoice to the IRP
   within 30 days of its date, and that the threshold was lowered at some
   point. **I do not trust my own version of this** — I need the advisory
   itself: the current threshold, the current window, and from what date.

> **I will build no filing.** The `# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT`
> rule stands and gets stronger here, not weaker: a builder produces the
> payload, a CA clicks once per invoice. Registration for IRP production
> credentials is a separate commercial step and is not what I am asking for.

---

## 3. protean-tinpan.com (formerly tin-nsdl.com) — the TDS return file layout

**Unblocks:** TDS-16. The quarterly TDS statement is computed correctly today —
deductor block, deductee lines, challan matching, §201(1A) interest, the 2026
Act's form renumbering — and there is **no writer for the file the portal
actually eats**. A CA re-keys the whole quarter into the RPU.

Go to **Protean (TIN) → e-TDS/e-TCS → File Formats** and bring back:

1. **The file format for Form 24Q, 26Q, 27Q and 27EQ** — these are four
   separate layout documents, and each is a fixed-width record specification
   (file header, batch header, challan detail, deductee detail). I need all
   four; 24Q and 26Q alone cover most of a practice's volume if you want to
   split the trip.
2. **The FVU version currently accepted**, and its validation rules. There are
   usually two FVU versions live at once (one for recent quarters, one for
   older), and which applies to which period matters.
3. **The correction-statement file format** — the C1–C9 correction types and
   what each may change. A practice files corrections constantly; a builder
   that can only produce originals is half a feature.

### The question I most want answered on this trip

The Income-tax Act 2025 with the Income-tax Rules 2026 **renumbered the
statements from 01-04-2026: 24Q→138, 26Q→140, 27Q→144, 27EQ→143**. The product
already knows this (`domain/tds/vocabulary.py`) and translates at the boundary.

**Has Protean published new file layouts for the renumbered forms, or is the
FY 2026-27 quarter still filed on the old layout under a new name?** If the
layout changed, the four documents above need to be the NEW ones and I will
need the old ones too — periods up to 31-03-2026 keep the old forms
indefinitely, including belated and revised returns, so both live for years.

---

## 4. incometaxindia.gov.in — two TDS rates, and one form

### 4a. §194I and §194J — the concessional limbs *(TDS-22's remainder)*

Each of these sections charges **two** rates and the product holds one:

- **§194I(a)** — rent of *plant, machinery or equipment* is charged lower than
  rent of land, buildings or furniture.
- **§194J(a)** — *fees for technical services* (and call-centre operation) are
  charged lower than professional fees.

The clause is fully recordable today: `194I(A)`, `194I(B)`, `194J(A)` and
`194J(B)` are in the registry, the clause codes are taken from the ITD's own
ITR-6 schema in this repo, and the **(b)** limbs are complete because they are
the rate already held. The **(a)** limbs deliberately withhold at the *parent's
higher* rate and carry a `rate_gap` saying so — an under-deduction disallows
the whole expenditure under §40(a)(ia), while an excess is the payee's to
reclaim, so over-deducting is the only safe direction to fail in.

**I need: the bare current text of §194I and §194J.** Acts → Income-tax Act →
the section. I am not asking you to interpret it; the rate is stated in the
clause and the proviso.

### 4b. Form 3CD *(IT-11's remainder)*

The §44AB **applicability** question is closed — the product decides clauses
(a) and (b), names (c)/(d)/(e) as untested, and the tracker no longer guesses
a business or a profession from the amount. What is missing is **Form 3CD
itself**: the tax-audit report a CA actually files.

Go to **Forms → Income Tax Forms → Form 3CD** and bring back the **current
form, all clauses 1–44 with sub-clauses**. It was substantially amended
recently and I do not know which version is in force.

If the **e-filing JSON schema for Form 3CA / 3CB-3CD** is downloadable
alongside the ITR schemas, that too — it is what turns a clause workspace into
something that can actually be filed.

---

## 5. gst.gov.in → Downloads → Offline Tools — the three returns that are absent

**Unblocks:** GST-25. `services/filing_demo/gstr9.py` is a walk-through, not a
computation, and three whole return types have no builder:

| return | who files it | what I need |
|---|---|---|
| **CMP-08 and GSTR-4 (annual)** | a composition dealer under §10 | the offline utility, and its JSON schema |
| **GSTR-8** | an e-commerce operator collecting TCS under §52 | the same, plus how 3B Table 3.1.1 relates to it |
| **GSTR-9C** | the reconciliation statement beside GSTR-9 | the offline utility and its schema |

The GSTN "Returns Offline Tool" download page usually carries a schema
document per return. That document, not the tool itself, is what I need.

`domain/gst/registrations.py` already knows these return types exist and names
the form each registration owes — an ISD files GSTR-6, a §51 deductor GSTR-7,
a §52 operator GSTR-8 — so the refusal is already accurate. Building them is
the next step, not a correction.

---

## 6. Your clients' banks — the salary-payment file *(PAY-27)*

**This is the one that is not a single website, and it needs a decision from
you before any fetching.**

Payroll runs end to end today: the slips, the statutory deductions, the
journal, the leaver, the ECR. What it cannot do is produce the **bulk payment
file** a CA uploads to net banking to pay a month's salaries in one go —
so the CA types every employee's account number every month, which is where
payroll mistakes actually happen.

There is no single format. Two questions, and the first is yours:

1. **Which banks do your payroll clients actually bank with?** Three or four
   names is enough to start. Building for a bank nobody uses is wasted work.
2. For each: the **bulk salary upload / bulk NEFT file specification** from
   that bank's *corporate* net-banking documentation. This is usually a short
   PDF or an Excel template with a header row — much smaller than anything else
   in this file.

**The NPCI NACH Credit format** is the closest thing to a standard here and is
worth having whether or not the per-bank files are: if your clients pay salary
by NACH mandate rather than by NEFT upload, one format covers all of them.

> **Nothing in this asks for a credential.** The product will produce a *file*
> the CA uploads themselves. No stored bank logins, no screen-scraping of net
> banking, ever — that is in `docs/compliance/05-…` and in the code as a guard.

---

## 7. The annual hand-off — ITR JSON schemas

**Not a finding. It comes round every year and this year's is already stale.**

`domain/income_tax/schemas/` holds seven files, currently spanning versions
V0.1 to V1.2:

```
ITR1_2026_Main_V1.1   ITR2_2026_Main_V1.2   ITR3_2026_Main_V1.1
ITR4_2026_Main_V1.1   ITR5_2026_Main_V1.1   ITR6_2026_Main_V1.0
ITR7_2026_Main_V0.1
```

**incometax.gov.in → Downloads → Income Tax Returns.** The Department
republishes these *within* an assessment year as well as between them, and the
version in the filename changes. ITR-7 at **V0.1** is the one I would most like
refreshed — a `V0.x` is a first draft.

These cannot be generated or inferred. The failure mode is specific and nasty:
field paths MOVE between versions, and a path that silently resolves to the
wrong node validates perfectly and reports the wrong tax. An earlier version of
this work picked `TaxPayableOnDeemedTI` (the MAT branch) instead of
`TaxPayableOnTI` on ITR-5 and ITR-6 and it passed every check.

Replace the seven files, and I will update `SCHEMA_FILES` and re-run the
field-path tests.

---

## 8. The long tail — real gaps, none urgent

Each of these is a *named refusal* in the code: the software says what it
cannot compute and why, rather than producing a figure. None blocks a finding.
I list them because you offered to fetch things, and because the first one is
the largest single improvement available anywhere in this file.

### 8a. Professional tax — 18 states, and this is the big one

`domain/payroll/professional_tax.py` records **22 states** as levying
professional tax and models **four**: Maharashtra, Tamil Nadu, Karnataka and
West Bengal. The other eighteen:

> Andhra Pradesh · Assam · Bihar · Chhattisgarh · Gujarat · Jharkhand · Kerala
> · Madhya Pradesh · Manipur · Meghalaya · Mizoram · Nagaland · Odisha ·
> Puducherry · Punjab · Sikkim · Telangana · Tripura

An employee in any of them has professional tax **named as a gap on the payroll
run** rather than silently deducted at zero — which is right, and is still a
CA doing arithmetic by hand every month.

What I need per state is one small table: **the monthly salary slabs and the
deduction for each**, from that state's own professional-tax notification. They
are short — usually four or five rows. **Gujarat, Telangana, Andhra Pradesh and
Kerala** are probably the four that cover most real employees; start there if
you start at all.

⚠️ **Two of the 22 are doubtful and I did not remove them.** Odisha is reported
as having repealed its levy from 01-04-2026, and Punjab's charge is described
in some places as a *Development Tax* rather than professional tax. Neither was
confirmable here. The error direction is benign — naming a state that no longer
levies produces a false gap warning, never a wrong deduction — so settle it
against the state notification before either comes out.

### 8b. Labour Welfare Fund — 16 states, none modelled

`domain/payroll/lwf.py` records 16 states as levying it and holds **no
amounts at all**. LWF is small money (tens of rupees, half-yearly or yearly)
and is a real statutory deduction. Same shape of ask as 8a, and lower value.

### 8c. Minimum wage for §12 of the Payment of Bonus Act

The annual bonus register is built (migration 395) and §12 computes on
**₹7,000 or the minimum wage, whichever is HIGHER**. Treating ₹7,000 as the
ceiling underpays by about half in most states. The wage varies per state, per
scheduled employment and per skill grade, and is revised twice yearly — so I
refuse rather than guess, and the client-year figure is a field the CA fills
in. A table would let it default sensibly.

### 8d. SBI's lending rate for Rule 3(7)(i)

One number a year. The perquisite value of an interest-free or concessional
loan is computed against **the State Bank of India's rate as on the first day
of the previous year**. `domain/payroll/perquisites.py` refuses without it.
SBI publishes it; it is a single figure.

### 8e. ESIC reason codes

ESIC's own list, used when an employee exits mid-month. Small, and it makes
the ECR cleaner rather than fixing anything wrong.

---

## What is NOT in this file

Two things remain open that no document will settle, so that you are not
looking for them:

- **BANK-11 step 3** — whether a *trusted* bank rule may propose more than it
  does now (a split across two legs, a party tag). That is a decision about how
  much happens with nobody watching, not a fact to look up. It is waiting on
  you and I have written down why I have not just built it.
- **The Account Aggregator line** — closed, deliberately, and not reopened by
  anything above. `docs/compliance/05-…` §7 records the four gate questions and
  their answers. Statement upload stays the way bank data enters the product.

Everything else I could build without you is built.
