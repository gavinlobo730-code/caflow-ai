# GST compliance for an Indian CA firm serving SMEs — re-run against primary sources
Research date: 2026-09-07 (IST). Researcher: Claude (agent session).

---

## 0. THE HEADLINE METHODOLOGICAL FINDING: NOTHING BELOW IS [P]

**Every government host is blocked. I tested it myself rather than trusting the
earlier session's note, and the note is still correct.**

`WebFetch` returned `EGRESS_BLOCKED` for every one of these:

| Host | Result |
|---|---|
| `tutorial.gst.gov.in` | EGRESS_BLOCKED |
| `www.gst.gov.in` | EGRESS_BLOCKED |
| `services.gst.gov.in` | EGRESS_BLOCKED |
| `cbic-gst.gov.in` | EGRESS_BLOCKED |
| `www.cbic.gov.in` | EGRESS_BLOCKED |
| `taxinformation.cbic.gov.in` | EGRESS_BLOCKED |
| `einvoice1.gst.gov.in` | EGRESS_BLOCKED |
| `gstcouncil.gov.in` | EGRESS_BLOCKED |
| `egazette.gov.in` | EGRESS_BLOCKED |
| `www.pib.gov.in` | EGRESS_BLOCKED |
| `incometaxindia.gov.in` / `www.incometax.gov.in` | connect_rejected |

Raw `curl` through the agent proxy fails the same way — `CONNECT tunnel failed,
response 403`, logged by the proxy as `connect_rejected (organization policy)`.
So this is not a WebFetch quirk; there is no shell workaround.

**It is not a blanket block, which is what makes the finding precise.** WebFetch
*succeeded* on `raw.githubusercontent.com` and `github.com` in the same session.
It *failed* on `en.wikipedia.org`, `cleartax.in`, `idtc.icai.org`,
`www.anthropic.com` and `r.jina.ai`. `web.archive.org` is refused by WebFetch
itself with a distinct message ("Claude Code is unable to fetch from
web.archive.org"), so the Wayback Machine is not a route to the gazette either.
The allowlist looks developer-oriented (package registries, code hosts) and
excludes the whole public web, government included.

**Consequence for the grades the owner asked for: I fetched no official page, so
I award NO `[P]` in this document.** To keep the report useful I split `[S]`:

- **`[S-gov]`** — the search engine's own summariser read a document *at an
  official `gov.in` URL* (I list the URL). The wording below is that
  summariser's rendering of the official text. I did not see the document.
  This is the best grade available in this environment.
- **`[S]`** — trade press, vendor blog, or professional-firm note.
- **`[U]`** — unconfirmed, contradicted, or asserted only by low-quality sources.

Anything an implementer would rely on for money or a deadline should be
re-verified from the URLs below on an unblocked network before it ships.

---

## 1. IMS (Invoice Management System)

### 1a. What the mechanism is — actions, deemed acceptance, GSTR-2B timing

**Claim: the three actions are Accept, Reject and Pending, and a fourth state
"No Action" is the default.**
URL: https://tutorial.gst.gov.in/downloads/news/revised_advisory_on_ims.pdf
and https://tutorial.gst.gov.in/downloads/news/final_faqs_on_ims_22_09_2024.pdf
NOT fetched (search-summary of the official PDF). Grade **[S-gov]**.

**Claim (deemed acceptance): "By default all the records will flow into 'No
Action' category and records with 'No Action' will be deemed accepted at the
time of GSTR-2B generation." The advisory adds that "the taxpayer's intervention
will only be required in case a record needs to be Rejected or kept Pending."**
URL: https://tutorial.gst.gov.in/downloads/news/revised_advisory_on_ims.pdf
NOT fetched. Grade **[S-gov]**.

> This is the load-bearing sentence for the product. Silence = accepted. A CA who
> never opens IMS still gets a GSTR-2B, populated with everything the suppliers
> filed. See §1d for a widely-repeated blog claim that this reversed in April
> 2026 — it did not, on the evidence I have.

**Claim (the deadline, relative to GSTR-2B generation): draft GSTR-2B is
generated on the 14th of the following month from IMS actions as they stand then.
The recipient may still act, or change an earlier action, after the 14th and up
to the filing of GSTR-3B — but must then RECOMPUTE GSTR-2B from the IMS dashboard
for the change to reach GSTR-3B. There is no cap on the number of recomputes
before filing. After GSTR-3B for that month is filed, no further action is
possible for that month.**
URLs: https://tutorial.gst.gov.in/downloads/news/revised_advisory_on_ims.pdf ,
https://tutorial.gst.gov.in/downloads/news/draft_manual_ims.pdf
NOT fetched. Grade **[S-gov]**.

> So the operative deadline is **the filing of GSTR-3B, not the 14th** — the 14th
> is only when the *draft* is cut. The recompute step is the trap: an action taken
> on the 16th that is never recomputed silently does not reach the return.

**Claim (when GSTR-2B is NOT generated at all): (i) for a QRMP taxpayer, no
GSTR-2B for months 1 and 2 of the quarter — it is quarterly only; (ii) if the
previous period's GSTR-3B has not been filed, the system does not generate
GSTR-2B, and the taxpayer must file the pending GSTR-3B and then generate it
on demand via "Compute GSTR-2B" on the IMS dashboard.**
URL: https://tutorial.gst.gov.in/downloads/news/revised_advisory_on_ims.pdf
NOT fetched. Grade **[S-gov]**.

### 1b. What happens to a "Pending" record

**Claim: a pending record does NOT enter GSTR-2B and does not enter GSTR-3B. It
stays on the IMS dashboard until it is accepted or rejected, or until the s.16(4)
cut-off, after which it is removed from IMS.**
URLs: https://tutorial.gst.gov.in/downloads/news/revised_advisory_on_ims.pdf ,
https://tutorial.gst.gov.in/downloads/news/additional_faqs_ims_17_10_2024.pdf
NOT fetched. Grade **[S-gov]**.

**Claim (narrowed from the October 2025 tax period): "Pending" is no longer open
-ended for every document type. The pending window is expressed as *the due date
of the GSTR-3B of the applicable GSTR-2B period, plus one tax period*; when it
expires the pending action is disabled and the recipient must accept or reject.
Pending is NOT available at all for: an original credit note rejected by the
recipient; an upward amendment of a credit note rejected by the recipient
(whatever was done to the original); and a downward amendment of a credit note
where the original credit note was rejected.**
URL: https://tutorial.gst.gov.in/downloads/news/creative_faq_on_gstr9_for_24_25_dt_15_oct_25_v6_final.pdf
(the search index titles this "FAQs on New Changes in IMS from October 2025 Tax
Period" despite the gstr9-looking filename — treat the filename as unverified)
NOT fetched. Grade **[S-gov]**, with the URL/title mismatch flagged.

> **Two statements of the pending limit are in circulation and I could not
> reconcile them**: "until the s.16(4) cut-off" (the 2024 FAQs) and "GSTR-3B due
> date + one tax period" (the Oct-2025 FAQs). The most likely reading is that the
> short window applies to credit notes and their amendments and the s.16(4) limit
> still governs invoices/debit notes, but **that reconciliation is mine, not the
> advisory's — treat it as [U] and check before coding a timer.**

### 1c. Other IMS mechanics found

- **ITC-reversal declaration (from the Oct 2025 tax period):** the recipient may
  declare *how much* ITC is to be reversed on a record. "Yes" with no value means
  full reversal; a partial reversal takes an amount and **remarks are mandatory**.
  URL: as above. NOT fetched. **[S-gov]**
- **Credit notes may be kept pending for up to 1 month** (Oct 2025 change).
  URL: as above. NOT fetched. **[S-gov]**
- **Bill of Entry in IMS (from Oct 2025):** a new "Import of Goods" section; BoEs
  (including SEZ imports) appear for action; the recipient may **accept or keep
  pending only** — and **no action on a BoE is deemed accepted**.
  URL: https://tutorial.gst.gov.in/downloads/news/creative_advisory_on_boe_in_ims_final_30th_october_2025.pdf
  NOT fetched. **[S-gov]**
- **Supplier-side consequence of a rejection:** if the recipient rejects a credit
  note and files GSTR-3B, the corresponding liability is **added back to the
  supplier's GSTR-3B of the subsequent period**.
  URL: https://tutorial.gst.gov.in/downloads/news/revised_advisory_on_ims.pdf
  NOT fetched. **[S-gov]**
- **IMS Offline Tool (Excel-based), announced ~21-23 April 2026**, for individual
  and bulk actions on records from GSTR-1 / GSTR-1A / IFF; downloads as a zip;
  has a "Validate Sheet" button.
  URLs: https://www.gst.gov.in/newsandupdates/read/658 and
  https://tutorial.gst.gov.in/downloads/news/advisory_on_ims_offline_tool_23rd_april_2026.pdf
  NOT fetched. **[S-gov]**
- **Error tolerance during rollout:** GSTN advised that where a mistaken IMS
  action auto-populated wrong ITC/liability into GSTR-3B, the taxpayer **may edit
  it before filing**. NOT fetched, secondary reproduction. **[S]**

### 1d. IS IMS MANDATORY? — the answer is more careful than the trade press says

**What is actually established:**

**Claim: s.38 of the CGST Act was SUBSTITUTED with effect from 01-10-2025, by the
Finance Act 2025, brought into force by Notification No. 16/2025–Central Tax
dated 17-09-2025. The substituted s.38 is headed "Communication of details of
inward supplies and input tax credit" and drops the "auto-generated statement"
language that used to describe GSTR-2B.**
URLs: https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter9/section38_v1.00.html
(text) and, for the commencement notification, secondary reproductions
(https://taxreply.com/gstnotifications-html/Notification-No-16-2025-2140.html).
NOT fetched. Grade **[S-gov]** for the section text; **[S]** for the notification.

**Claim: Rule 67B was inserted into the CGST Rules by the CGST (Fourth Amendment)
Rules 2025, Notification No. 18/2025–Central Tax dated 31-10-2025, providing for
the increase in the SUPPLIER's GSTR-3B liability where the recipient rejects an
original credit note or a specified amendment.**
NOT fetched; secondary only. Grade **[S]**.

**What is NOT established — and what I think is wrong:**

- **"IMS became mandatory on 1 October 2025."** Grade **[U]**. This is a blog
  formulation. What is documented is that s.38 was rewritten so that the ITC
  statement is the IMS-shaped one — i.e. IMS became the *legal plumbing*. Nothing
  I found imposes a duty to *take an action*, and the deemed-acceptance rule is
  the direct evidence that no such duty exists: a taxpayer who does nothing gets
  a valid GSTR-2B.
- **"From 1 April 2026, silence is no longer deemed acceptance — it is deemed
  REJECTION."** Grade **[U], and I believe it is FALSE.** Source:
  https://treelife.in/taxation/gst-amendments-effective-from-1st-april-2026/ and
  similar. It directly contradicts the official IMS advisory, which was still
  being served as the current advisory in searches run today, and no notification
  or advisory reversing deemed acceptance surfaced in any search. **Do not build
  to this.** (The same page also self-contradicts, saying two paragraphs later
  that not acting on a credit note *is* deemed acceptance.)
- **"Zero Mismatch Policy from 1 April 2026 — the portal blocks filing on any
  GSTR-2B vs GSTR-3B difference."** Grade **[U]**. Single blog, no notification,
  no advisory. Reads invented.
- **"ITC hard block / Table 4 of GSTR-3B becomes non-editable."** Grade **[U]**,
  and the sources **disagree with each other on the date**: some say the April
  2026 tax period, some say the July 2026 tax period. One of the more careful
  write-ups states plainly that **"a specific, dated GSTN advisory confirming it
  is fully live has not been located"**, describing it as Finance-Ministry-sourced
  reporting of an intention. My own searches against `tutorial.gst.gov.in`,
  `gst.gov.in` and `services.gst.gov.in` for a Table 4 / 4A(5) locking advisory
  returned **nothing**. **Not confirmed.** This matters commercially — it is the
  single change that would make IMS action genuinely compulsory — so it is worth
  re-checking first on an unblocked network.

**The defensible summary for a CA firm today:** IMS is the statutory route by
which ITC is communicated (s.38, from 01-10-2025), and *using* it is optional in
the narrow sense that inaction is acceptance — but inaction accepts everything a
supplier filed, including what should have been rejected, and a rejected credit
note now pushes liability back to the supplier under Rule 67B. It is
operationally compulsory and legally permissive.

---

## 2. GSTR-1A

**Claim: FORM GSTR-1A was inserted by Notification No. 12/2024–Central Tax dated
10-07-2024. It is OPTIONAL, and it lets a supplier add or amend particulars of a
supply for the CURRENT tax period.**
URL: https://tutorial.gst.gov.in/downloads/news/creative_faqs_on_gstr1a_fo_cr25785.pdf
(official FAQ, "FAQ on GSTR-1A - Amendment to GSTR 1"); notification number from
secondary. NOT fetched. Grade **[S-gov]** for the mechanics, **[S]** for the
notification number and date.

**Claim (the window): GSTR-1A opens AFTER GSTR-1 for the period is filed and
closes when GSTR-3B for that same period is filed. It was made available from
August 2024, first usable to amend the July 2024 GSTR-1. Amendments made in
GSTR-1A flow into the GSTR-3B liability for the same period.**
Same URLs. NOT fetched. Grade **[S-gov]** / **[S]**.

**Why this now matters far more than it did in 2024 [S]:** since outward liability
in GSTR-3B Tables 3.1 and 3.2 became non-editable (§3c below), **GSTR-1A is the
only pre-3B correction route left**. A wrong invoice value, wrong GSTIN or wrong
place of supply in GSTR-1 flows straight into a locked GSTR-3B unless GSTR-1A is
used first.

---

## 3. Current due dates

### 3a. The table

| Return | Due date | Grade / source |
|---|---|---|
| GSTR-1, monthly | 11th of the following month | [S] |
| GSTR-1, quarterly (QRMP) | 13th of the month following the quarter | [S-gov] tutorial.gst.gov.in FAQ; example given: Apr–Jun 2026 → 13 Jul 2026 |
| IFF (QRMP months 1 & 2, optional) | 13th of the following month | [S] |
| GSTR-3B, monthly | 20th of the following month | [S] |
| GSTR-3B, quarterly (QRMP) | **22nd** for Category X States/UTs, **24th** for Category Y | [S] |
| PMT-06 (QRMP monthly tax, M1 & M2) | 25th of the following month | [S] |
| CMP-08 (composition, quarterly) | **18th** of the month succeeding the quarter | [S-gov] Rule 62 — https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter8/rule62_v1.00.html and https://tutorial.gst.gov.in/userguide/returns/Manual_CMP02.htm |
| GSTR-4 (composition, annual) | **30 June** following the FY, **from FY 2024-25 onwards** (was 30 April up to FY 2023-24) | [S] — proviso to Rule 62 inserted by Notification 12/2024–CT dated 10-07-2024 |
| GSTR-9 (annual) | 31 December following the FY | [S-gov] Rule 80 |
| GSTR-9C (reconciliation) | 31 December following the FY, filed **along with** the annual return | [S-gov] Rule 80(3) — https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter8/rule80_v1.00.html |

NOT fetched — every row above is a search summary, not a document I read.

### 3b. Any 2026 changes to the due dates themselves

**None found.** No notification changing GSTR-1 / GSTR-3B / GSTR-9 / CMP-08 /
GSTR-4 due dates in 2026 surfaced in any search. Grade **[U] (absence of
evidence, not evidence of absence)** — I cannot browse the notification index.

**One negative that IS worth recording: GSTR-9 / GSTR-9C for FY 2024-25 were NOT
extended.** Multiple professional bodies (BCAS, MPTLBA, CTPA, Indore) made
representations in Dec 2025 asking for 31 January 2026, citing the reporting
changes made by Notifications 12/2024-CT and 13/2025-CT. CBIC did not extend; the
deadline stayed **31 December 2025** and late fee under s.47 ran. Grade **[S]**.
Sources: taxscan.in/top-stories/…-1441242 , taxguru.in, a2ztaxcorp.net.

### 3c. Related deadline mechanics that changed and that a CA firm feels daily

- **GSTR-3B outward liability hard-locked from the JULY 2025 tax period** (returns
  filed from August 2025): Tables 3.1(a), 3.1(b), 3.1(c), 3.1(e) and 3.2,
  auto-populated from GSTR-1 / GSTR-1A / IFF, are **non-editable**. Per **GSTN
  Advisory No. 606 dated 07-06-2025**. Reported as still the operative advisory as
  at 29 July 2026. Grade **[S]** (secondary only; I could not reach
  services.gst.gov.in to read advisory 606). Note the history: this was first
  announced for January 2025 and **deferred** after trade representations — so its
  successor phases should be treated as provisional until seen live.
- **Sequential filing:** s.39(10) — GSTR-3B for a period cannot be filed unless
  GSTR-1 for that period is filed. Rule 59(6) — GSTR-1 cannot be filed if the
  preceding period's GSTR-3B is unfiled. Grade **[S-gov]** (Rule 59 at
  taxinformation.cbic.gov.in; GSTR-1 FAQ at tutorial.gst.gov.in).
- **Advances no longer flow into Table 3.2 from the October 2025 tax period.**
  Grade **[S-gov]**.
- **From the January 2026 tax period the portal auto-populates the "Tax Liability
  Breakup Table" in GSTR-3B by DOCUMENT DATE**, for supplies reported in
  GSTR-1/1A/IFF that belong to an earlier tax period. Grade **[S-gov]** —
  surfaced from tutorial.gst.gov.in. Related: "Advisory on Re-Computation of
  Interest under Table 5.1", https://tutorial.gst.gov.in/downloads/news/advisory_on_interest_calculator_6th_march_2026.pdf
  (06-03-2026). Both NOT fetched. **This is a 2026 change worth chasing** — it
  affects how interest is computed on late-reported invoices.

---

## 4. GSTR-9C applicability and GSTR-9 exemption

**GSTR-9C — claim: every registered person whose aggregate turnover during the FY
EXCEEDS ₹5 crore must furnish a SELF-CERTIFIED reconciliation statement in FORM
GSTR-9C along with the annual return, on or before 31 December following the end
of that FY.** (Self-certified — the CA/CMA *certification* requirement was removed
in 2021; GSTR-9C is no longer an audit.)
URL: https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter8/rule80_v1.00.html
NOT fetched. Grade **[S-gov]**.

**GSTR-9 exemption — claim: registered persons with aggregate annual turnover up
to ₹2 crore are exempt from filing the annual return, and this is now PERMANENT
rather than year-by-year: Notification No. 15/2025–Central Tax (17-09-2025),
issued under the first proviso to s.44(1), exempts them "for the financial year
2024-25 AND ONWARDS". Filing remains available voluntarily.**
NOT fetched; secondary only (taxguru.in, taxo.online, taxtmi.com — the last
reproducing the parallel Haryana SGST notification 46/GST-2). Grade **[S]**.

> **This is a real change against the secondary-sourced picture.** Up to FY
> 2023-24 the ≤₹2 crore exemption was re-notified every single year (e.g.
> Notification 14/2024-CT for FY 2023-24), so any product that models it as an
> annual switch needs a standing rule instead. Corollary for a compliance engine:
> **the ≤₹2 crore case no longer goes stale each April.**

**So the three bands, current:** ≤ ₹2 crore — GSTR-9 optional, no GSTR-9C.
> ₹2 crore and ≤ ₹5 crore — GSTR-9 mandatory, no GSTR-9C. > ₹5 crore — both.

**Late fee under s.47(2) for the annual return — Circular No. 246/03/2025-GST**
(URL: https://cbic-gst.gov.in/pdf/cir-cgst-246-03-2025.pdf, NOT fetched,
**[S-gov]** for the URL / **[S]** for the reading): the late fee attaches to the
*complete* annual return, i.e. GSTR-9 **and** GSTR-9C where 9C is required. It
runs from the due date to the date GSTR-9 is filed; and for GSTR-9C, from the
later of (the GSTR-9 filing date, the annual-return due date) to the date GSTR-9C
is filed. It is auto-computed, and a new **Table 17 "Late Fee Payable and Paid"**
was added under Part V of GSTR-9C to carry it. Excess late fee on delayed
complete annual returns **up to FY 2022-23** was waived.

---

## 5. The three-year filing bar

**Claim (statute): the Finance Act 2023 inserted s.37(5), s.39(11), s.44(2) and
s.52(15) into the CGST Act, barring a registered person from furnishing the
relevant statement/return after the expiry of THREE YEARS from its due date.
These were brought into force on 01-10-2023 by Notification No. 28/2023–Central
Tax dated 31-07-2023 (which notified ss. 137–148 and 155–162 of the Finance Act
2023 from 01-10-2023, and ss. 149–154 from 01-08-2023).**
URLs: https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter9/section39_v1.00.html
and https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter9/section37_v1.00.html
NOT fetched. Grade **[S-gov]** for the section text; **[S]** for the notification.

**s.39(11) in the statute's own words, as rendered by the search summary of the
official page** — "*A registered person shall not be allowed to furnish a return
for a tax period after the expiry of a period of three years from the due date of
furnishing the said return*", followed by a **proviso** that the Government may,
on the Council's recommendations, by notification and subject to conditions and
restrictions, **allow a registered person or a class of registered persons to
furnish the return even after the expiry of those three years.** Grade **[S-gov]**.

> The proviso matters: the bar is hard on the portal but not absolute in law.

**Claim (when it went live on the portal): NOT on 01-10-2023 — nearly two years
later. GSTN issued an advisory on 07-06-2025 saying the restriction would be
implemented from the JULY 2025 tax period, i.e. returns become unfileable from
1 AUGUST 2025, and warning taxpayers to clear anything expiring by 31-07-2025.
An earlier advisory (Oct 2024) had promised "early 2025" and slipped.**
NOT fetched; secondary only (businesstoday.in, taxo.online, cleartax.in,
teamleaseregtech.com, taxreply.com). Grade **[S]**.

**Forms covered: GSTR-1, 3B, 4, 5, 5A, 6, 7, 8 and 9.** Grade **[S]**.

**Live effect as at Sept 2026 [S]:** the bar now rolls monthly. A recent GSTN
advisory reported returns for the month/quarter **ending September 2022** as
barred, and urged taxpayers to clear anything three years old.

**Unbarring — flagged, NOT confirmed [U]:** one secondary source
(livelawbiz.com) reports GSTN has launched an **"Application for Unbarring
Returns"** module on the portal, letting a taxpayer apply online to lift the
system restriction. This would be the operational face of the s.39(11) proviso.
My targeted searches against `gst.gov.in` / `tutorial.gst.gov.in` for it returned
**nothing**, and I have no date, no advisory number and no notification.
**Do not tell a client this exists without checking.**

---

## 6. e-invoicing

### 6a. Applicability threshold as at 2026

**Claim: the threshold is AATO exceeding ₹5 crore in ANY financial year from
2017-18 onwards, with effect from 01-08-2023 — Notification No. 10/2023–Central
Tax dated 10-05-2023, amending Notification No. 13/2020–Central Tax dated
21-03-2020. It is UNCHANGED as at 2026.**
NOT fetched; secondary (cleartax.in, businesstoday.in, tallysolutions.com).
Grade **[S]**.

**Claim: a reduction to ₹2 crore (and ₹3 crore) has been DISCUSSED at Council
level but NOT notified as at mid-2026. Treat any lower figure as a proposal.**
Grade **[S]**. One vendor page phrases it well and honestly: "*Until a
notification is officially issued, any lower figure should be treated as a
proposal and confirmed against CBIC notifications.*"

**Once liable, always liable:** the trigger is *any* preceding FY from 2017-18,
so a business that crossed ₹5 crore once does not fall out of e-invoicing when
turnover drops. Grade **[S]**.

**Exempt classes (Notification 13/2020-CT, as amended, plus 61/2020-CT):**
insurer; banking company; financial institution; NBFC; goods transport agency
(road transport of goods); supplier of passenger transportation service; supplier
of services by way of admission to exhibition of cinematograph films in multiplex
screens; **SEZ units** (61/2020-CT). Grade **[S]**.
> Note the asymmetry: **SEZ *units* are exempt; SEZ *developers* are not.**
> Flagged as **[U]** — implied by several sources, not confirmed.

### 6b. The 30-day reporting time limit

**Claim: an IRN cannot be generated for a document older than 30 days from its
document date. Applied first to AATO ≥ ₹100 crore from 01-11-2023 (GSTN advisory
dated 13-09-2023; IRPs began validating 01-11-2023), then LOWERED to AATO ≥ ₹10
crore with effect from 01-04-2025 (GSTN advisory dated 05-11-2024).**
URLs seen in results but NOT fetched:
https://einvoice1.gst.gov.in/Documents/advisory.pdf (NIC advisory),
https://einvoice2.gst.gov.in/Documents/advisory270325.pdf (27-03-2025 advisory),
https://services.gst.gov.in/services/advisoryandreleases/read/543 .
Grade **[S]** (the reproductions are consistent across cleartax.in, kpmg.com,
taxreply.com and the IRIS IRP pages on the `einvoice6.gst.gov.in` host).

**Who it applies to: taxpayers with AATO ≥ ₹10 crore. Taxpayers between ₹5 crore
and ₹10 crore must e-invoice but currently face NO time limit.** Grade **[S]**.

**What it applies to: invoices, credit notes AND debit notes.** Grade **[S]**.

**Enforcement: the IRP refuses IRN generation past the window and returns an
error. Since ITC under s.16(2)(a) needs a valid tax invoice, and an e-invoice
without an IRN is not a valid tax invoice, a missed window is not a filing
inconvenience — it strands the customer's credit.** The consequence sentence is
my inference marked **[U]**; the refusal itself is **[S]**.

**Coming change [S-gov]:** an advisory dated **17-06-2026** announces that
**Ship-to GSTIN becomes mandatory in the IRN and e-Way-Bill-by-IRN APIs where
ship-to information is present**, in production **from 01-08-2026**.
URL: https://tutorial.gst.gov.in/downloads/news/advisory_einvoice_api_ewb_by_irn_approved.pdf
NOT fetched. Anyone integrating the e-invoice API needs this.

---

## 7. Rule 36(4) — the 5% cushion

**Confirmed: the 5% provisional cushion is GONE, with effect from 01-01-2022.**

**But the common shorthand "Rule 36(4) was removed/omitted" is WRONG, and the
distinction matters.** Rule 36(4) was **SUBSTITUTED**, not omitted, and it is
still in force — now as an absolute condition rather than a percentage.

Amendment history, all **[S]** (from taxguru.in, cleartax.in, fintaxblog.com,
gstgyaan.com; consistent across all of them):

| Change | Notification | From |
|---|---|---|
| Rule 36(4) introduced, cap **20%** | 49/2019-CT, 09-10-2019 | 09-10-2019 |
| **20% → 10%** | 75/2019-CT, 26-12-2019 | 01-01-2020 |
| **10% → 5%** | 94/2020-CT, 22-12-2020 | 01-01-2021 |
| **Sub-rule (4) SUBSTITUTED — percentage gone** | **40/2021-CT, 29-12-2021** | **01-01-2022** |
| Cosmetic: in clause (b), "input tax credit in respect of" inserted after "the details of" | 19/2022-CT, 28-09-2022 | 01-10-2022 |

**Current text of Rule 36(4), as rendered by the search summary of the official
CBIC page** — no ITC shall be availed by a registered person in respect of
invoices or debit notes whose details are required to be furnished under s.37(1)
**unless** (a) the supplier has furnished those details in FORM GSTR-1 or via the
invoice furnishing facility, **and** (b) the details have been **communicated to
the registered person in FORM GSTR-2B under sub-rule (7) of rule 60**.
URL: https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter5/rule36_v1.00.html
NOT fetched. Grade **[S-gov]**.

**The statutory half of the same change:** s.16(2)(**aa**) — ITC only where the
supplier has furnished the invoice/debit note in the statement of outward
supplies **and** it has been communicated to the recipient — was inserted by
s.109 of the Finance Act 2021 and brought into force **01-01-2022** by
**Notification No. 39/2021–Central Tax dated 21-12-2021** (which notified ss.
108, 109 and 113–122 of the Finance Act 2021 from that date). Grade **[S]**.

> ⚠️ **A TRAP I HIT, RECORDED BECAUSE IT WILL CATCH THE NEXT PERSON.** One search
> summary of the *official* CBIC Rule 36 page returned the **pre-2022 5% text**
> while simultaneously stating the rule had been substituted with effect from
> 01-01-2022. The CBIC repository pages carry amendment footnotes and struck-through
> history, and a summariser can lift the superseded wording as if it were live.
> Two further searches were needed to pin the current text. **Any automated
> extraction from these pages must be checked against the amendment history, not
> trusted on first read.**

---

## 8. §49(5) and Rule 88A — the set-off order

### 8a. s.49(5) CGST Act, in the statute's own words

Search summaries of the official CBIC page,
https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter10/section49_v1.00.html
and secondary reproductions (indiankanoon.org/doc/18746069/, lawcrux.com,
aaptaxlaw.com). NOT fetched. Grade **[S-gov]** for (a); **[S]** for (b)–(f).

The amount of input tax credit in the electronic credit ledger may be used to
make payment towards output tax, in the following manner —

- **(a)** "*integrated tax shall first be utilised towards payment of integrated
  tax and the amount remaining, if any, may be utilised towards the payment of
  central tax and State tax, or as the case may be, Union territory tax, **in that
  order***"
- **(b)** "*the central tax shall first be utilised towards payment of central tax
  and the amount remaining, if any, may be utilised towards the payment of
  integrated tax*"
- **(c)** "*the State tax shall first be utilised towards payment of State tax and
  the amount remaining, if any, may be utilised towards payment of integrated
  tax*" — **with a proviso** that State-tax credit may go to integrated tax "*only
  where the balance of the input tax credit on account of central tax is not
  available for payment of integrated tax*"
- **(d)** "*the Union territory tax shall first be utilised towards payment of
  Union territory tax and the amount remaining, if any, may be utilised towards
  payment of integrated tax*" — with the equivalent proviso
- **(e)** "*the central tax shall **not** be utilised towards payment of State tax
  or Union territory tax*"
- **(f)** the State tax or Union territory tax shall **not** be utilised towards
  payment of central tax — Grade **[U]**: the exact wording of (f) did not come
  back in any search; the *substance* is confirmed by the summary of s.49(5) as a
  whole ("*central tax shall not be utilised towards payment of State tax or
  Union territory tax, and State tax or Union territory tax shall not be utilised
  towards payment of central tax*"). Treat the mirror rule as certain, the exact
  clause lettering as unverified.

### 8b. Rule 88A CGST Rules, verbatim

Grade **[S-gov]** — URL
https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter9/rule88a_v1.00.html
NOT fetched; the wording below was returned identically by two independent
searches and matches the secondary reproductions.

> **88A. Order of utilization of input tax credit.** — Input tax credit on account
> of integrated tax shall first be utilised towards payment of integrated tax, and
> the amount remaining, if any, may be utilised towards the payment of central tax
> and State tax or Union territory tax, as the case may be, **in any order**:
> Provided that the input tax credit on account of central tax, State tax or Union
> territory tax shall be utilised towards payment of integrated tax, central tax,
> State tax or Union territory tax, as the case may be, **only after the input tax
> credit available on account of integrated tax has first been utilised fully**.

**Inserted by Notification No. 16/2019–Central Tax dated 29-03-2019.** Grade
**[S]**.

### 8c. The interaction, stated carefully

- **s.49A** — ITC on account of central tax, State tax or UT tax "*shall be
  utilised towards payment of any such tax only after the input tax credit
  available on account of integrated tax has first been utilised fully*".
  **s.49B** empowers the Government, on the Council's recommendation, to prescribe
  the order and manner, subject to s.49(5). Both **[S-gov]** (URLs
  `.../section49a_v1.00.html`, `.../section49b_v1.00.html`). NOT fetched.
- **The one point an implementer gets wrong:** s.49(5)(a) says IGST credit spills
  to CGST and SGST/UTGST "**in that order**"; **Rule 88A, made under s.49B,
  relaxes this to "in any order"**. So the operative rule is *any order*, and code
  written to the bare statutory words will over-constrain the set-off. CBIC
  **Circular No. 98/17/2019-GST** (https://cbic-gst.gov.in/pdf/Circular-98-17-2019-GST.pdf,
  NOT fetched, **[S-gov]** for the URL) is the clarification with worked
  illustrations. Grade **[S]** for the reading.

**Net operative order:**
1. IGST credit → IGST liability first.
2. Remaining IGST credit → CGST and SGST/UTGST **in any order** (taxpayer's choice).
3. CGST / SGST / UTGST credit usable **only after IGST credit is exhausted in full**.
4. CGST credit → CGST, then IGST. SGST → SGST, then IGST (only where no CGST
   credit is available for IGST). UTGST likewise.
5. **CGST is never set against SGST/UTGST, and SGST/UTGST is never set against
   CGST** — in either direction, absolutely.

**Not checked:** whether s.49A, s.49B or Rule 88A have been amended since 2019.
Nothing in any search suggested so, but I could not read a current bare act.
Grade **[U]** on currency.

---

## 9. Other things found that a CA-firm product should know

- **GST 2.0 rate rationalisation, effective 22-09-2025** (56th GST Council,
  03-09-2025): the slab structure collapsed to **5% and 18%**, with a **40%**
  demerit rate for selected sin/luxury goods, and compensation cess merged into
  the new rates for most items. Grade **[S]** (EY, A&M, Lexology, IRIS).
  Not asked for, but it dates every rate table written before Sept 2025.
- **AATO amendment window for FY 2025-26** was open **01–31 July 2026**, with
  officer review 01–15 August 2026. Grade **[S]**. Relevant because AATO drives
  e-invoicing and the 30-day rule.
- **e-Way Bill:** a new e-Way Bill portal and a **voluntary closure** facility for
  e-way bills are referenced in 2026 GSTN material. Grade **[U]** — not chased.
- **GSTR-9/9C for FY 2024-25 changed shape** via Notifications 12/2024-CT and
  13/2025-CT, chiefly by demanding much more granular ITC reporting (reversals and
  re-availments under Rules 37 and 37A, cross-year adjustments). Grade **[S]**.
  Official FAQs, NOT fetched:
  https://tutorial.gst.gov.in/downloads/news/faq_on_gstr9_for_24_25_dt_15_oct_25_v6_final.pdf (15-10-2025)
  and https://tutorial.gst.gov.in/downloads/news/combined_faq_on_gstr_9_and_9c_17122025.pdf (17-12-2025).

---

## 10. What to re-verify first on an unblocked network

Ranked by (how load-bearing) × (how weakly sourced):

1. **The GSTR-3B Table 4 ITC lock** — date and whether it is live at all.
   `services.gst.gov.in/services/advisory/advisoryandreleases`. Currently **[U]**
   with sources disagreeing between April 2026 and July 2026, and one source
   admitting no dated advisory exists.
2. **That deemed acceptance still means ACCEPTED** — re-read
   `tutorial.gst.gov.in/downloads/news/revised_advisory_on_ims.pdf`. A blog claim
   that it flipped to deemed rejection in April 2026 is loose in the wild and
   would invert the product's behaviour.
3. **The IMS pending window** — s.16(4) vs "GSTR-3B due date + one tax period",
   and which document types each applies to.
4. **Notification 15/2025-CT** — that the ≤₹2 crore GSTR-9 exemption really is
   standing ("and onwards") and not annual.
5. **Notifications 16/2025-CT and 18/2025-CT** — the s.38 substitution and Rule
   67B, currently secondary-only.
6. **The "Application for Unbarring Returns" module** — exists or not.
7. **s.49A / s.49B / Rule 88A currency** — that the 2019 position still stands.

## 11. Full list of official URLs identified but NOT fetched

Every one of these was surfaced by search and is blocked from this environment.

- https://tutorial.gst.gov.in/downloads/news/revised_advisory_on_ims.pdf
- https://tutorial.gst.gov.in/downloads/news/final_faqs_on_ims_22_09_2024.pdf
- https://tutorial.gst.gov.in/downloads/news/additional_faqs_ims_17_10_2024.pdf
- https://tutorial.gst.gov.in/downloads/news/draft_manual_ims.pdf
- https://tutorial.gst.gov.in/downloads/news/creative_faq_on_gstr9_for_24_25_dt_15_oct_25_v6_final.pdf
- https://tutorial.gst.gov.in/downloads/news/creative_advisory_on_boe_in_ims_final_30th_october_2025.pdf
- https://tutorial.gst.gov.in/downloads/news/advisory_on_ims_offline_tool_23rd_april_2026.pdf
- https://tutorial.gst.gov.in/downloads/news/creative_faqs_on_gstr1a_fo_cr25785.pdf
- https://tutorial.gst.gov.in/downloads/news/faq_on_gstr9_for_24_25_dt_15_oct_25_v6_final.pdf
- https://tutorial.gst.gov.in/downloads/news/combined_faq_on_gstr_9_and_9c_17122025.pdf
- https://tutorial.gst.gov.in/downloads/news/advisory_einvoice_api_ewb_by_irn_approved.pdf
- https://tutorial.gst.gov.in/downloads/news/advisory_on_interest_calculator_6th_march_2026.pdf
- https://tutorial.gst.gov.in/userguide/returns/Manual_gstr2b.htm
- https://tutorial.gst.gov.in/userguide/returns/Manual_CMP02.htm
- https://tutorial.gst.gov.in/userguide/returns/GSTR_1.htm
- https://tutorial.gst.gov.in/userguide/returns/GSTR3B.htm
- https://www.gst.gov.in/newsandupdates/read/658
- https://services.gst.gov.in/services/advisory/advisoryandreleases
- https://services.gst.gov.in/services/advisoryandreleases/read/543
- https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter9/section37_v1.00.html
- https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter9/section38_v1.00.html
- https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter9/section39_v1.00.html
- https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter10/section49_v1.00.html
- https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter10/section49a_v1.00.html
- https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter10/section49b_v1.00.html
- https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter5/rule36_v1.00.html
- https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter8/rule59_v1.00.html
- https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter8/rule62_v1.00.html
- https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter8/rule80_v1.00.html
- https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/rules/cgst_rules/active/chapter9/rule88a_v1.00.html
- https://cbic-gst.gov.in/pdf/Circular-98-17-2019-GST.pdf
- https://cbic-gst.gov.in/pdf/cir-cgst-246-03-2025.pdf
- https://cbic-gst.gov.in/hindi/central-tax-notifications.html
- https://einvoice1.gst.gov.in/Documents/advisory.pdf
- https://einvoice2.gst.gov.in/Documents/advisory270325.pdf
- https://gstcouncil.gov.in/node/4326  (Notification 39/2021-CT)
