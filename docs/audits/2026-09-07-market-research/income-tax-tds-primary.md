# Income tax and TDS — research pass against sources, 2026-09-07 (IST)

Scope: FY 2025-26 and FY 2026-27, for an Indian CA firm serving SME clients.
Re-run of an earlier vendor/trade-press pass, with instructions to prefer primary sources.

---

## 0. THE HEADLINE METHODOLOGICAL FINDING: NOTHING HERE IS PRIMARY

**I could not fetch a single page. Not one.** The owner asked me to test the
network myself rather than trust the earlier session's note. I did, twice, by two
independent mechanisms, and the earlier session's finding is **confirmed and in
fact wider than recorded**.

Tested at 2026-09-07 via `curl` through the agent proxy — every one returned
`CONNECT tunnel failed, response 403`:

| Host | Result |
|---|---|
| `incometaxindia.gov.in` | 403 at proxy |
| `www.incometax.gov.in` | 403 at proxy |
| `www.tin-nsdl.com` | 403 at proxy |
| `www.protean-tinpan.com` | 403 at proxy |
| `www.tdscpc.gov.in` | 403 at proxy |
| `egazette.gov.in` | 403 at proxy |
| `cbic.gov.in` | 403 at proxy |
| `www.indiabudget.gov.in` | 403 at proxy |
| `dor.gov.in`, `finmin.nic.in`, `www.mca.gov.in` | 403 at proxy |
| `www.icai.org` | 403 at proxy |
| `prsindia.org` | 403 at proxy |

And, critically, **the block is not limited to government hosts**:

| Host | Result |
|---|---|
| `en.wikipedia.org` | 403 at proxy / `EGRESS_BLOCKED` |
| `cleartax.in` | 403 at proxy / `EGRESS_BLOCKED` |
| `taxguru.in` | 403 at proxy |
| `business-standard.com`, `thehindubusinessline.com` | 403 at proxy |

WebFetch returns a structured `{"error_type":"EGRESS_BLOCKED"}` for the same
hosts, including for a **specific official PDF URL** that a search surfaced
(`.../Key-Highlights-of-Finance-Act-2025.pdf`) and for the **official notification
page for Notification 22/2026** itself. `curl -sS "$HTTPS_PROXY/__agentproxy/status"`
records the denials as `connect_rejected — gateway answered 403 to CONNECT
(policy denial or upstream failure)`. Per `/root/.ccr/README.md` these are
organisation egress-policy denials, to be reported and not routed around.

**Consequence for this report, stated plainly:**

- **The instruction "use WebFetch on the official pages themselves" cannot be
  carried out in this environment.** Not for government sites, not for the
  fallback secondary sites either.
- The ONLY external channel that works is `WebSearch`, which returns a
  *search-engine synthesis* over result pages plus the list of URLs. I did not
  read any of those pages.
- **So there is no `[P]` in this document.** Marking anything primary would be a
  lie about provenance. The best available grade is `[S]`, and I have split it:

| Grade | Meaning here |
|---|---|
| `[S+]` | Search synthesis, corroborated by **three or more independent sources** including at least one professional/CA-firm or Big-4-adjacent publisher, with **no contradicting source seen** |
| `[S]` | Search synthesis, two or more sources agreeing |
| `[S-]` | Search synthesis, effectively one source, or sources that disagree on presentation |
| `[U]` | Unconfirmed — I saw it once, in a title or a fragment, and did not corroborate |
| `[loc]` | An **official URL was located** by search (so the document demonstrably exists at that address) but **its content was NOT read**. `[loc]` is a claim about existence only, never about content |

Every URL below is a URL I *saw in search results*. **Unless a line says
"FETCHED", I did not open it.** No line in this document says FETCHED.

---

## 0b. A FRAMING ERROR IN THE BRIEF ITSELF, WORTH FIXING BEFORE ANYTHING ELSE

The brief says "as at September 2026 (FY 2026-27, AY 2026-27)". Those two labels
**cannot both be right**, and the difference is a year of tax:

- Under the **1961 Act**, AY 2026-27 **is** FY 2025-26. FY 2026-27 is AY 2027-28.
- Under the **Income-tax Act 2025**, in force from 01-04-2026, the Assessment
  Year and the Previous Year are **abolished outright** and replaced by a single
  **"Tax Year"**. FY 2026-27 is **Tax Year 2026-27**. `[S+]`
  - "A Tax Year is a 12 month period that begins on the 1st of April... applicable
    from 01 April 2026, i.e., for income earned during FY 2026-27 onwards and this
    will be referred to as Tax Year 2026-27"
  - https://cleartax.in/s/tax-year-in-income-tax ; https://tax2win.in/guide/tax-year-income-tax-act-2025 ;
    https://www.incometax.gov.in/iec/foportal/help/all-topics/e-filing-services/objective-and-scope-new-act `[loc]`

So September 2026 straddles **two vocabularies at once**, and that is not a
pedantic point — it is exactly the fork the codebase already models:

- Returns being **filed** in Sept 2026 are for **AY 2026-27 = FY 2025-26**, under
  the **1961 Act**, on **ITR forms**, with a **Form 3CD** audit report.
- Tax being **withheld and accrued** in Sept 2026 is **Tax Year 2026-27**, under
  the **2025 Act**, on **Form 138/140/144**, under **§§392/393/394**.

Anything that answers "what applies now?" with one answer is wrong. I have kept
the two apart throughout.

---

## 1. Slabs, rebate, standard deduction, surcharge

### 1.1 Did the Finance Act 2026 change anything? — NO, not for slabs

**Claim:** The Finance Act 2026 made **no change** to slab rates or the basic
exemption limit. The Finance Act 2025 structure carries into Tax Year 2026-27
unchanged. `[S+]`

- "No income tax slab rates have changed for Tax Year 2026-27; the Finance Act
  2026 retains the same income tax slab rates for Tax Year 2026-27 as were
  applicable for the previous year, 2025-26."
- "In the Union Budget 2026, the Finance Minister did not announce any changes in
  tax slabs or basic exemption limits."
- https://taxguru.in/income-tax/finance-act-2026.html ;
  https://taxguru.in/chartered-accountant/finance-act-2026-56-key-amendments-related-icnome-tax.html ;
  https://www.hdfc.bank.in/blogs/union-budget/budget-2026-27-income-tax-act-2026-tax-slabs-stt ;
  https://cleartax.in/s/financial-changes-from-april-2026 ;
  https://www.indiabudget.gov.in/doc/memo.pdf `[loc]` (Finance Bill 2026 memorandum — NOT fetched)

**What the Finance Act 2026 DID change (relevant to SME clients: almost nothing;
relevant to trading clients: STT):** `[S]`
- STT on **sale of options** 0.1% → **0.15%** of premium
- STT on **options exercised** 0.125% → **0.15%** of intrinsic value
- STT on **futures** 0.02% → **0.05%** of traded price
- Applies to transactions on or after **01-04-2026**
- https://taxguru.in/income-tax/stt-rates-futures-options-hiked-1st-april-2026.html
- A "56 key amendments" listing exists at
  https://taxguru.in/chartered-accountant/finance-act-2026-56-key-amendments-related-icnome-tax.html —
  **I did not read it**, so I cannot say the other 55 are immaterial. `[U]` on
  completeness. This is the largest single unclosed hole in this report.

### 1.2 New regime slabs — FY 2025-26 AND FY 2026-27 (identical)

`[S+]`, corroborated across many sources, and matching the repo exactly.

| Total income | Rate |
|---|---|
| up to ₹4,00,000 | Nil |
| ₹4,00,001 – ₹8,00,000 | 5% |
| ₹8,00,001 – ₹12,00,000 | 10% |
| ₹12,00,001 – ₹16,00,000 | 15% |
| ₹16,00,001 – ₹20,00,000 | 20% |
| ₹20,00,001 – ₹24,00,000 | 25% |
| above ₹24,00,000 | 30% |

- https://cleartax.in/s/income-tax-slabs ; https://www.axismaxlife.com/blog/tax-savings/income-tax-slab-2025-26 ;
  https://www.bajajfinserv.in/investments/income-tax-slabs ;
  https://www.rsm.global/india/insights/tax-insights/new-income-tax-slab
- Official-URL sighting, content not read:
  https://www.incometaxindia.gov.in/documents/20117/14614782/Key-Highlights-of-Finance-Act-2025.pdf/... `[loc]` — **fetch refused, EGRESS_BLOCKED**

### 1.3 Old regime slabs — FY 2025-26 and FY 2026-27 (unchanged for years)

`[S+]` — nil to ₹2,50,000; 5% to ₹5,00,000; 20% to ₹10,00,000; 30% above.
Senior (60–79) basic exemption ₹3,00,000; very senior (80+) ₹5,00,000.
- https://cleartax.in/s/income-tax-slabs ; https://www.bajajfinserv.in/investments/income-tax-slabs

### 1.4 §87A rebate

| Regime | Ceiling | Max rebate |
|---|---|---|
| New (§115BAC) | total income ≤ **₹12,00,000** | **₹60,000**, with marginal relief |
| Old | total income ≤ **₹5,00,000** | **₹12,500**, no marginal relief |

`[S+]` — https://cleartax.in/s/income-tax-rebate-us-87a ; https://tax2win.in/guide/section-87a ;
https://www.canarahsbclife.com/blog/tax-saving/what-is-tax-rebate-under-section-87a

**Load-bearing carve-out, and a common wrong answer:** from **FY 2025-26 onwards
the Finance Act 2025 puts it beyond argument that §87A does NOT apply to income
taxed at special rates** — §111A STCG, §112A and §112 LTCG are excluded from the
rebate whatever the taxpayer's total income. `[S+]`
- "the law explicitly excludes income taxed at special rates — including STCG
  under Section 111A and LTCG under Section 112/112A — from the scope of the 87A
  rebate, irrespective of the taxpayer's total income level"
- https://taxguru.in/income-tax/section-87a-section-156-rebate-tax-payable-rs-12-lakh.html ;
  https://www.jmfinancialservices.in/blogs-and-articles/section-87a-rebate-vs-capital-gains-tax ;
  https://www.caclubindia.com/articles/section-87a-marginal-relief-fy-2026-27-the-rs-12l-cliff-the-capital-gains-carve-out-and-6-worked-examples-56062.asp
- Note the "₹12.75 lakh tax-free" line every vendor page repeats is **salary only**
  (₹12L + ₹75k standard deduction) and silently assumes no special-rate income.

### 1.5 Standard deduction

- New regime: **₹75,000** `[S+]`
- Old regime: **₹50,000** `[S+]`
- https://cleartax.in/s/income-tax-slabs ; https://www.axismaxlife.com/blog/tax-savings/income-tax-slab-2025-26

### 1.6 Surcharge — individuals

| Total income exceeds | Old regime | New regime |
|---|---|---|
| ₹50 lakh | 10% | 10% |
| ₹1 crore | 15% | 15% |
| ₹2 crore | 25% | 25% |
| ₹5 crore | **37%** | **capped at 25%** |

`[S+]` — https://www.bankbazaar.com/tax/surcharge-on-income-tax.html ;
https://cleartax.in/s/marginal-relief-surcharge ;
https://www.bajajfinserv.in/what-is-surcharge-on-income-tax

- Marginal relief available at every surcharge threshold. `[S+]`
- Surcharge on **capital-gains income (§111A/§112A/§112) and dividend is capped at
  15%** in both regimes — the repo carries this as
  `capital_gains_surcharge_cap_percent: 15`; I saw it only obliquely in search,
  so `[S-]` on the confirmation, though it is long-standing law.
- Cess: **4% Health & Education Cess** on tax + surcharge, both regimes. `[S+]`

### 1.7 Cross-check against the repo — CLEAN

`domain/income_tax/statutory_rates.py` FY 2025-26 and FY 2026-27 entries match
**every** figure above, including the 25% new-regime surcharge cap, the 15%
capital-gains surcharge cap, both rebate shapes and both standard deductions.

**Actionable:** the FY 2026-27 entry currently carries `verified=False`. On the
evidence above (Finance Act 2026 changed no slab) it is **correct**. Whether to
flip it to `verified=True` is a judgement call the repo's own convention answers:
`verified` means *a human checked it against the Finance Act*, and I could not
open the Finance Act. **I would leave it False** and record why — see §10.

---

## 2. Entity rates, MAT and AMT — FY 2026-27

### 2.1 Domestic company `[S+]`

| Basis | Rate | Surcharge | Cess |
|---|---|---|---|
| Default | **30%** | 7% >₹1cr, 12% >₹10cr | 4% |
| Turnover-based | **25%** | 7% / 12% | 4% |
| **§115BAA** | **22%** | **flat 10%** | 4% |
| **§115BAB** (new manufacturing) | **15%** | **flat 10%** | 4% |

- **Turnover reference year — this is the bit people get wrong.** The 25% rate is
  tested on turnover **two years back**, not the current year: *for AY 2026-27, the
  turnover of **PY 2023-24** must not exceed ₹400 crore*. `[S+]`
  - "For AY 2026-27, a domestic company is taxed at 25% on its total income if the
    total turnover or gross receipts of the previous year 2023-24 does not exceed
    ₹400 crores"
  - https://taxguru.in/income-tax/income-tax-rates-ay-2026-27-ay-2027-28.html ;
    https://taxguru.in/income-tax/corporate-tax-rate-applicable-ay-2021-2022-ay-2022-2023.html ;
    https://www.taxscan.in/top-stories/22-25-or-30-which-corporate-tax-rate-applies-to-your-domestic-company-1446350
  - The repo encodes this as `company_turnover_lookback_years: 2` — **correct**.
- §115BAA / §115BAB companies are **outside MAT** entirely. `[S+]`
  https://cleartax.in/s/section-115-baa-tax-rate-domestic-companies

### 2.2 Firm / LLP `[S+]`

**30%** flat, surcharge **12%** above ₹1 crore, cess 4%. Matches the repo.

### 2.3 Foreign company `[S+]` — **AND THIS IS A REPO GAP**

**35%** on general income (reduced from 40% by the **Finance Act 2024**, effective
from 01-04-2024), plus surcharge **2%** on income ₹1–10 crore and **5%** above
₹10 crore, plus 4% cess. A 50% rate survives for certain royalty / FTS income
under old approved agreements.
- https://taxsummaries.pwc.com/india/corporate/taxes-on-corporate-income ;
  https://investmentpolicy.unctad.org/investment-policy-monitor/measures/4789/cuts-corporate-income-tax-rate-for-foreign-companies ;
  https://taxguru.in/income-tax/income-tax-rates-financial-year-2025-26-ay-2026-27.html

**`domain/income_tax/entity_rates.py` has no foreign-company rate at all** — it
holds `firm_*`, `company_*`, `s115baa_*`, `s115bab_*` and nothing else. For an SME
practice that may well be deliberate scope. Flagging it, not proposing it.

### 2.4 MAT §115JB `[S+]`

**15%** of book profit + surcharge + 4% cess. Credit carry-forward **15 years**.
Matches the repo.

### 2.5 AMT §115JC / §115JEE `[S+]` — repo is RIGHT, and right in the subtle way

- Rate **18.5%** (**15%** for a co-operative society) + surcharge + cess.
- The **₹20 lakh adjusted-total-income cushion in §115JEE applies ONLY to an
  individual, HUF, AOP, BOI and artificial juridical person.**
- **A firm or an LLP gets no cushion at all** — AMT applies irrespective of the
  amount of adjusted total income.
- "the benefit of threshold exemption is not available to the partnership firm,
  LLP and other non-corporate assessee"
- https://www.legalwiz.in/blog/llp-taxation-income-tax-alternate-minimum-tax-amt ;
  https://disytax.com/section-115jc-alternate-minimum-tax-amt-on-llps-individuals/ ;
  https://www.taxmanagementindia.com/visitor/detail_manual.asp?ID=1204

I checked the repo against this because a flat ₹20 lakh threshold would have been
a real under-taxation bug. It is **not** a bug: `domain/income_tax/minimum_tax.py`
gates the cushion on `_THRESHOLD_ELIGIBLE = {individual, huf, aop, boi,
artificial_juridical_person}` and its refusal message says in terms "a firm or LLP
gets no such cushion". Correct, and correctly explained.

### 2.6 MAT/AMT under the 2025 Act — a live drafting story worth knowing `[S]`

MAT and AMT are consolidated into **§206** of the Income-tax Act 2025. An earlier
draft of the Bill **dropped the cross-reference to Chapter VI-A-equivalent
deductions**, which would have dragged LLPs — including an LLP whose only income
was 12.5% LTCG — into AMT at 18.5%. The **revised draft restored it**.
- https://tax.cyrilamarchandblogs.com/2025/04/amt-does-it-impose-additional-taxes-under-income-tax-bill-2025/ ;
  https://www.caalley.com/news-updates/indian-news/new-income-tax-bill-restores-alternate-minimum-tax-relief-for-llps ;
  https://taxclue.in/blog/mat-minimum-alternate-tax-income-tax-act-2025-section-206
- I could not verify the **final enacted** §206 text. `[U]` on the as-enacted
  position. If PracticeSync computes AMT for an LLP under the 2025 Act, this needs
  a human read of §206 before it is trusted.

### 2.7 One unconfirmed renumbering lead

A search-result **title** rendered §115BAA as "**Section 200**" of the 2025 Act
(https://eztax.in/section-115baa-tax-rate-explained). Single sighting, title only.
`[U]`. Do not encode.

---

## 3. §44AD / §44ADA / §44AE `[S+]`

| Provision | Standard limit | Enhanced limit | Condition for enhanced | Deemed income |
|---|---|---|---|---|
| **§44AD** business | turnover ≤ **₹2 crore** | **₹3 crore** | cash **receipts** ≤ 5% of turnover | **8%**, or **6%** on non-cash/digital receipts |
| **§44ADA** specified profession | gross receipts ≤ **₹50 lakh** | **₹75 lakh** | cash **receipts** ≤ 5% of gross receipts | **50%** |
| **§44AE** goods carriage (≤10 vehicles) | no turnover limit | — | — | **₹1,000 per tonne GVW per month** for a heavy vehicle (>12,000 kg); **₹7,500 per month** otherwise |

- https://legalsuvidha.com/blog/presumptive-taxation-44ad-44ada ;
  https://www.regitom.com/presumptive-taxation-44ad-44ada-ay-2026-27 ;
  https://www.startbusiness.co.in/blog/presumptive-taxation-in-india ;
  https://cleartax.in/s/section-44ad-presumptive-scheme

**Every one of these matches `domain/income_tax/presumptive.py`** including the
₹12,000 kg heavy-vehicle boundary and the 10-vehicle cap.

### 3.1 The distinction most easily got wrong, and it is a real one

**§44AD's 5% test looks at RECEIPTS ONLY. §44AB's 5% test looks at receipts AND
payments.** They are different tests with the same-sounding percentage. `[S+]`

- "Section 44AD's enhanced threshold requires only the cash receipts test ≤ 5% —
  one condition... Section 44AD never looks at payments."
- "For Section 44AB, the first proviso substitutes ten crore rupees... where two
  conditions are simultaneously satisfied: the aggregate of all amounts received
  ... in cash does not exceed five per cent ... **and** the aggregate of all
  payments made ... in cash does not exceed five per cent"
- https://cleartax.in/s/section-44ad-presumptive-scheme ;
  https://www.taxsocial.pro/article/tax-audit-limit-ay-2026-27-section-44ab-44ad-44ada-thresholds-cash-receipts-test-basic-exemption-limit-decoded ;
  https://taxguru.in/income-tax/tax-audit-fy-2025-26-section-44ab-form-3cd-nuances-ay-2026-27.html

So a business with 3% cash receipts and 40% cash payments gets §44AD's ₹3 crore
but **not** §44AB's ₹10 crore. If PracticeSync ever shares one "cash ratio" gate
between the two, that is a wrong answer in a very common SME shape.

---

## 4. §44AB tax audit, and the due dates

### 4.1 Thresholds `[S+]`

| Who | Threshold | Enhanced |
|---|---|---|
| Business | turnover > **₹1 crore** | **₹10 crore** where cash **receipts** ≤5% **AND** cash **payments** ≤5% |
| Profession | gross receipts > **₹50 lakh** | — (no digital proviso) |

- https://cleartax.in/s/tax-audit-section-44ab ;
  https://www.caclubindia.com/articles/tax-audit-under-section-44ab-for-ay-2026-27-latest-rules-with-due-date-forms-and-penalty--56092.asp ;
  https://www.regitom.com/tax-audit-section-44ab-ay-2026-27-complete-guide
- Official-URL sighting, content not read:
  https://www.incometaxindia.gov.in/w/section-44ab-38 `[loc]`

### 4.2 Due dates for **AY 2026-27 (= FY 2025-26)** `[S+]`

| What | Date |
|---|---|
| Tax audit report (Form 3CA/3CB + **3CD**) | **30 September 2026** |
| ITR-1 / ITR-2, non-audit | **31 July 2026** |
| ITR-3 / ITR-4, non-audit | **31 August 2026** `[S]` — see note |
| ITR, audit case | **31 October 2026** |
| ITR, transfer-pricing case | **30 November 2026** |
| Belated / revised return | **31 December 2026** |

- https://cleartax.in/s/due-date-tax-filing ;
  https://www.pgtandassociates.com/post/tax-audit-for-ay-2026-27-thresholds-forms-3ca-3cb-3cd-30-september-deadline ;
  https://computaxonline.com/blog/post/2026/08/23/tax-audit-ay-2026-27-due-date-3ca-3cb-3cd ;
  https://www.caclubindia.com/articles/income-tax-audit-last-date-for-the-ay-202627-56060.asp
- **No extension announced** for AY 2026-27 as at the search date; one source
  notes CBDT signalled no extension was expected because forms and utilities
  released on schedule. `[S]`
- ⚠️ **The 31 August 2026 date for non-audit ITR-3/ITR-4 is a staggered due date
  I saw in only one synthesis.** `[S-]`. It is **not** what
  `services/compliance_engine.py` derives (31 July / 31 Oct), and it is not what
  §139(1) says on its face. **Do not encode it without a human reading a CBDT
  notification.** Flagged, not adopted.
- Penalty §271B: lower of 0.5% of turnover or ₹1,50,000. `[S]`

### 4.3 Two forward-looking changes to note `[S]`

- **Form 3CD becomes "Form 26"** for Tax Year 2026-27 onwards under the 2025 Act;
  audits for AY 2026-27 still use 3CA/3CB + 3CD.
  https://www.glomiq.com/blog/form-3cd-ay-2026-27-changes-checklist ;
  https://www.caclubindia.com/articles/tax-audit-under-section-44ab-for-ay-2026-27-latest-rules-with-due-date-forms-and-penalty--56092.asp
- **ICAI raised the per-partner tax-audit ceiling from 45 to 60** with effect from
  01-04-2026. `[S-]` (one synthesis; `icai.org` unreachable to confirm). Relevant
  to a CA firm's capacity planning, not to computation.

---

## 5. Capital gains

### 5.1 Rates either side of 23 July 2024 `[S+]`

| Provision | Before 23-07-2024 | On/after 23-07-2024 |
|---|---|---|
| **§111A** STCG, listed equity/equity MF/business trust with STT | **15%** | **20%** |
| **§112A** LTCG, same assets | 10% above ₹1,00,000 | **12.5%** above **₹1,25,000** |
| **§112** LTCG, other assets | 20% **with** indexation | **12.5% without** indexation |

- https://learn.quicko.com/short-term-capital-gain-tax-on-shares-section-111a ;
  https://cleartax.in/s/long-term-capital-gains-on-shares ;
  https://taxguru.in/income-tax/capital-gain-tax-reinstatement-indexation-benefit.html
- §112A's **31 January 2018 grandfathering** of pre-existing gains is unchanged. `[S+]`
- The **₹1.25 lakh** §112A exemption applies from **FY 2024-25** onwards. `[S+]`

### 5.2 Indexation and the immovable-property grandfather `[S+]`

Indexation was **withdrawn generally**. It survives as an **option, on land and
buildings only, acquired before 23-07-2024**, for a **resident individual or HUF**:
the taxpayer computes both ways — 12.5% without indexation, and 20% with — and
**pays the lower**.
- "a second proviso reinstates the benefit for land and buildings acquired before
  this date if the tax exceeds the pre-amendment computation"
- https://taxguru.in/income-tax/capital-gain-tax-reinstatement-indexation-benefit.html
- The repo's comment in `capital_gains_engine.py` — "the Budget 2024 grandfather
  clause is specific to immovable property" — is **correct**, and correctly
  excludes gold, bonds and unlisted shares from the option.

### 5.3 ⚠️ COST INFLATION INDEX — TWO FINDINGS, ONE OF THEM A LIVE WRONG NUMBER

**Finding A — an index for FY 2026-27 HAS been notified. It is 384.** `[S+]`

- "CBDT has notified the Cost Inflation Index (CII) for FY 2026-27 at **384** via
  **Notification No. 85/2026-Income Tax**... Effective from 1 April 2026, it
  applies to Tax Year 2026-27"
- Cited by search as dated **15 July 2026**.
- Note the section citation in the sources is **§72(8)(a) of the Income-tax Act
  2025** — i.e. the notification is issued under the **new** Act, consistent with
  the fork.
- https://taxguru.in/income-tax/cost-inflation-index-fy-2026-27-notified-384-cbdt-notification-85-2026.html ;
  https://www.angelone.in/news/economy/cbdt-announces-cost-inflation-index-for-fy-2026-27 ;
  https://abcaus.in/income-tax/cost-inflation-index-up-to-date-table.html ;
  https://cleartax.in/s/cost-inflation-index
- Corroborated by an **@IncomeTaxIndia** post quoted in results:
  "CBDT notifies the Cost Inflation Index (CII) for FY 2026-2027 vide Notification
  No. 85/2026. The Cost Inflation Index for FY 2026-27 relevant to tax year
  2026-27 is 384" — https://x.com/IncomeTaxIndia/status/2077586020464570562 `[loc]`,
  **not fetched**, and a social post is not the notification.

**Finding B — THE REPO'S FY 2025-26 CII IS WRONG. It says 380. The notified
figure is 376.** `[S+]`, and this is the most consequential thing in this report.

- "CBDT has, vide **Notification No. 70/2025 dated 01st July 2025**, notified the
  Cost Inflation Index (CII) for FY 2025-26 (AY 2026-27) at **376**."
- Five independent professional publishers agree on 376, including a Big-4-adjacent
  firm and a national daily's headline:
  - https://www.rsm.global/india/insights/cbdt-notifies-cost-inflation-index-cii-376-fy-2025-26
  - https://www.taxmann.com/post/blog/cbdt-notified-376-as-cost-inflation-index-cii
  - https://www.mondaq.com/india/income-tax/1647412/cost-inflation-index-notified-for-fy-2025-26
  - https://www.dpncindia.com/cost-inflation-index-notified-for-fy-2025-26
  - https://www.caclubindia.com/news/cbdt-notifies-cost-inflation-index-for-fy-2025-26-at-376-25031.asp
  - https://www.business-standard.com/amp/economy/news/cbdt-notifies-cost-inflation-index-at-376-for-fy26-125070201178_1.html
- **I found no source anywhere saying 380.**

Verified in the repo directly:

```
apps/api/domain/income_tax/capital_gains_engine.py:63
    ..., "2023-24": 348, "2024-25": 363, "2025-26": 380,
```

Every **other** value in the repo's table that I could cross-check is right —
2021-22 = 317, 2022-23 = 331, 2023-24 = 348, 2024-25 = 363 all corroborated
(https://taxadda.com/cost-inflation-index-cii/ ; https://arthgyaan.com/blog/latest-cost-inflation-index-cii.html).
**Only the newest entry, 2025-26, is off** — which is the signature of a value
typed in before the notification landed and never reconciled.

**Impact.** `cii_for()` falls back to `LATEST_CII_FY` for an unknown year, so
**today, in FY 2026-27, every indexed computation uses 380** — a number that is
both the wrong year *and* the wrong value for the year it names. The blast radius
is bounded, exactly as CLAUDE.md says, to the grandfathered immovable-property
option under §112 — but within that option the indexed cost is overstated by
roughly **1.06%** (380/376), which understates the gain and therefore the tax, and
does so **silently and confidently**.

**The fix is a two-line data change, not one:** correct `"2025-26": 380 → 376`,
add `"2026-27": 384`, and move `LATEST_CII_FY` to `"2026-27"`.

**But note the repo's own rule and do not skip it:** `LATEST_CII_FY` is the
human-verified marker, and I could not open either notification. On the strength
of six agreeing professional sources I would **correct 376 and add 384**, and I
would **say in the commit that the verification is secondary-source**, because
moving the marker without a human read is precisely the "silently promotes a guess
to a verified figure" failure CLAUDE.md warns about.

---

## 6. TDS — thresholds and rates

### 6.1 The Finance Act 2025 threshold changes, effective 01-04-2025 `[S+]`

| Section | Nature | Threshold FY 2025-26 (and FY 2026-27) | Rate |
|---|---|---|---|
| **§194A** | interest — bank/post office, non-senior | **₹50,000** (was ₹40,000) | 10% |
| **§194A** | interest — bank/post office, **senior citizen** | **₹1,00,000** (was ₹50,000) | 10% |
| **§194A** | interest — other than bank | **₹10,000** (was ₹5,000) | 10% |
| **§194C** | contractor | **₹30,000 single / ₹1,00,000 aggregate p.a.** — **unchanged** | 1% indiv/HUF, 2% others |
| **§194H** | commission / brokerage | **₹20,000** (was ₹15,000) | **2%** (halved from 5% w.e.f. Oct 2024) |
| **§194I** | rent | **₹50,000 per month or part of a month** (was ₹2,40,000 p.a.) | 2% plant & machinery, 10% land/building/furniture |
| **§194J** | professional / technical fees | **₹50,000** (was ₹30,000) | 10% professional, 2% technical |
| **§194Q** | purchase of goods | purchase > **₹50 lakh** from a seller, **and** buyer's preceding-FY turnover > **₹10 crore** | **0.1%** on the excess (**5%** if no PAN) |
| **§194T** | payment to a partner by a firm/LLP | **₹20,000** aggregate p.a. | **10%** |

- https://taxgarden.in/blog/tds-threshold-changes-fy-2025-26-budget-2025-new-limits-india ;
  https://www.indiafilings.com/learn/tds-rule-changes-from-1st-april-2025 ;
  https://www.bssridhar.com/tds-tcs-rates-for-fy-2025-26/ ;
  https://blog.tdsman.com/2026/03/tds-tcs-rate-chart-fy-2026-27/ ;
  https://taxgarden.in/blog/tds-on-interest-section-194a-393-guide-india-fy-2026-27
- Third-party PDF rate charts sighted (not fetched):
  https://www.tdsman.com/downloads/TDS_and_TCS-rate-chart-2027.pdf `[loc]` ;
  https://gowthama.com/updates/TDSRateChartFY2025-26.pdf `[loc]` ;
  https://apcca.com/wp-content/uploads/2025/04/TDS-TCS-CHART-FY-2025-26.pdf `[loc]`

### 6.2 ⚠️ §194I is a MONTHLY test now, and sources present it two different ways

One synthesis said "annual threshold raised from ₹2,40,000 to ₹6,00,000". Another
said "₹50,000 in any single month, instead of the earlier aggregate-for-the-year
basis". **These are not the same rule** and the second is the statutory shape.

₹6,00,000 is merely 12 × ₹50,000 and only coincides where rent is level. For
**uneven rent** — a lumpy commercial lease, a part-year tenancy, a one-off
equipment hire — an annual ₹6L test **under-deducts**: rent of ₹60,000 for three
months (₹1.8L a year) is under ₹6L annually but over ₹50,000 in each of those
months, and TDS is due. `[S]` on the monthly reading, `[S-]` on which the sources
settle to, because they genuinely disagree in presentation.

**Recommendation: implement the monthly test and treat any ₹6,00,000 constant in
the code as a bug.** I did not audit the repo's §194I implementation.

### 6.3 §194T is genuinely new and catches almost every SME firm client `[S+]`

From **01-04-2025**, a partnership firm or LLP must deduct **10%** on salary,
remuneration, commission, bonus **and interest** paid to a **partner**, once the
**aggregate** across all those heads exceeds **₹20,000** in the FY. Excludes
drawings, capital repayment and share of profit. Deduct at credit or payment,
whichever is earlier — so a year-end credit of partner remuneration triggers it.
- https://taxguru.in/income-tax/section-194t-10-percent-tds-partnership-firm-payments-partners.html ;
  https://www.taxmann.com/post/blog/section-194-t-tds-on-payments-to-partners/ ;
  https://cleartax.in/s/section-194t-tds-on-payment-by-partnership-firm-to-partners ;
  https://www.vjmglobal.com/blog/tds-on-payment-made-to-partners-w-e-f-1st-april-2025
- **The ₹20,000 is aggregate, not per head** — deducting only where a single head
  crosses ₹20,000 is the wrong test. `[S+]`

### 6.4 §206AB / §206CCA — CONFIRMED OMITTED `[S+]`

Both **omitted by the Finance Act 2025 with effect from 1 April 2025**. The higher
"twice the rate, or 5%, whichever is higher" deduction for non-filers of ITR is
**gone**; TDS/TCS now runs at normal rates regardless of the payee's filing status,
and deductors no longer have to run the "specified person" check.
- https://taxguru.in/income-tax/budget-2025-removal-higher-tds-tcs-non-filers-april-2025.html ;
  https://www.taxscan.in/budget-2025-removes-of-higher-tds-tcs-u-s-section-206ab-section-206cca-for-for-non-filers-of-income-tax-return/486254 ;
  https://pattic.org/tds-compliance-simplified-section-206ab-omitted-from-1st-april-2025-2/ ;
  https://www.lexology.com/library/detail.aspx?g=ba8c4eec-4134-400c-8bda-49dd70093c41
- **§206AA (no-PAN, 20% floor) is NOT affected and remains in force.** Do not
  conflate the two — they are different sections with different triggers.

### 6.5 §194Q vs §206C(1H) — the overlap is resolved, in §194Q's favour `[S+]`

- **§206C(1H) TCS on sale of goods ceased to operate from 01-04-2025.** The
  seller no longer collects 0.1% TCS on receipts above ₹50 lakh; **the buyer
  continues to deduct under §194Q**. Form 27EQ reporting and Form 27D certificates
  for this item fall away.
- https://taxguru.in/income-tax/tcs-sale-goods-removed-april-1-2025-faqs.html ;
  https://www.aiaccountant.com/blog/tcs-on-sale-of-goods ;
  https://www.lexology.com/library/detail.aspx?g=ba8c4eec-4134-400c-8bda-49dd70093c41
- ⚠️ **Sources disagree on the mechanism, and it matters for how you write the
  code comment.** Most say "omitted". One practitioner says the Finance Bill 2025
  **inserted a proviso making §206C(1H) inapplicable** rather than omitting the
  sub-section, so "legally the section remains in the Act but is not operational"
  (https://x.com/AbhasHalakhandi/status/1886819252134363216). `[S-]` on which.
  **Practically identical from 01-04-2025; textually different.** Cite the effect,
  not the mechanism, until someone reads the enacted Finance Act 2025.
- Historic rule, still needed for FY 2024-25 and earlier and therefore for any
  revised return: where both could apply, **§194Q prevailed** and the seller was
  relieved of §206C(1H).

### 6.6 Rates and thresholds carry into FY 2026-27 UNCHANGED `[S+]`

- "The TDS rates and monetary thresholds for FY 2026-27 have been retained at
  existing levels. From 1 April 2026, the Income-tax Act, 2025 consolidates TDS
  provisions under Section 393, without changing the applicable rates."
- "Although the section numbers have changed, the TDS rates and threshold limits
  largely remain the same."
- https://onefinops.com/tools/tds-rate-chart ; https://blog.tdsman.com/2026/03/tds-tcs-rate-chart-fy-2026-27/ ;
  https://cleartax.in/s/tds-and-tcs-changes-from-april-2026 ; https://aaaa.co.in/tds-applicability-rate-chart-2026-27/

**This directly vindicates the repo's design decision** to renumber only at the
emission boundary and leave `section_rates.py` keyed on 1961-Act section numbers.
Nothing found contradicts it.

---

## 7. THE INCOME-TAX ACT 2025 / RULES 2026 RENUMBERING — **CONFIRMED**, with one correction

This was flagged as load-bearing, so I have been correspondingly careful about
what I can and cannot say.

**What I could NOT do:** read Notification 22/2026. Its official page exists at
https://www.incometaxindia.gov.in/w/notification-no.-22/2026-f.-no.-370142/41/2025-tpl-/-g.s.r.-198-e- `[loc]`
and **WebFetch on that exact URL returned `EGRESS_BLOCKED`.** I therefore cannot
grade any of this `[P]`.

**What I can say:** every element of the repo's mapping was corroborated by
multiple independent professional and trade sources, and **I found nothing
contradicting any of it**.

### 7.1 The notification itself `[S+]`

- **Income-tax Rules, 2026**, notified by **Notification No. 22/2026 /
  G.S.R. 198(E) dated 20 March 2026**, under **§533 of the Income-tax Act, 2025**.
- In force **1 April 2026**.
- Consolidates 511 rules / 399 forms into **333 rules / 190 forms**.
- **A corrigendum exists: G.S.R. 286(E) dated 16 April 2026.** `[S]`
  https://a2ztaxcorp.net/cbdt-issues-corrigendum-to-income-tax-rules-2026-notification-to-correct-errors-and-ensure-accurate-implementation/
  — CLAUDE.md already mentions "plus a corrigendum"; this dates it. **I could not
  read what it corrects**, which is a real residual risk on any specific form number.
- https://www.taxmann.com/post/blog/cbdt-notifies-income-tax-rules ;
  https://taxguru.in/income-tax/cbdt-notifies-income-tax-rules-2026-income-tax-forms.html ;
  https://ksandk.com/newsletter/income-tax-rules-2026-key-changes/

### 7.2 TDS/TCS statements — **CONFIRMED** `[S+]`

| Old | New | Notes |
|---|---|---|
| 24Q | **138** | salary, under §392; also specified senior citizens |
| 26Q | **140** | non-salary, residents |
| 27Q | **144** | non-residents |
| 27EQ | **143** | TCS |

- "From the quarter ended 30 June 2026, Form 24Q becomes Form 138, Form 26Q
  becomes Form 140, Form 27Q becomes Form 144 and the TCS return Form 27EQ becomes
  Form 143."
- https://www.taxscan.in/top-stories/income-tax-forms-138-140-replace-24q-26q-new-tds-reporting-rules-for-salary-and-non-salary-payments-1444578 ;
  https://taxguru.in/income-tax/tds-forms-138-140-replace-forms-24q-26q-fy-2026-27.html ;
  https://www.outlookmoney.com/tax/changes-in-tds-tcs-rules-forms-138-and-140-replace-old-forms-24q-and-26q-heres-what-you-need-to-know ;
  https://taxupdate.in/income-tax/811/new-tds-tcs-return-forms-fy-2026-27-form-138-140-143-144-due-31-july-2026/
- **Due dates unchanged: 31 Jul, 31 Oct, 31 Jan, 31 May.** `[S+]` — Q4 is 31 May,
  confirming `compliance_engine.tds_return_due_date`'s Q4 exception survives.

### 7.3 Certificates and statements — **CONFIRMED** `[S+]`

| Old | New | Authority cited |
|---|---|---|
| Form 16 | **130** | **Rule 215(1)**, issued under **§395(4)(b)** |
| Form 16A | **131** | now issued **quarterly**, not annually |
| Form 26AS | **168** | **Rule 245**, the Annual Information Statement |
| Forms 15G / 15H | **121** | merged into one form |

- https://cleartax.in/s/new-income-tax-forms ; https://taxroutine.com/form-no-131-analysis/ ;
  https://taxhandout.com/new-form-no-121-income-tax-rules-2026/ ;
  https://rnegi.com/form-16-and-16a-replaced-new-forms-130-and-131-explained/ ;
  https://ebizfiling.com/blog/form-131-of-income-tax-act-process-and-applicability/
- Official-URL sightings, **not fetched**:
  https://www.incometaxindia.gov.in/documents/d/guest/fn-130-131-132-133 `[loc]` —
  titled "Form No. 130_131_132_133 (Earlier Form No. 16/16A/16B/16C/16D/16E/27D)",
  which is itself strong corroboration of the mapping from the department's own
  file naming; and https://www.incometaxindia.gov.in/documents/d/guest/form-130-faqs `[loc]`
- **CLAUDE.md's "Form 16→130 (three parts now)" and "16A→131 (quarterly now)" are
  both CONFIRMED.** `[S]`
  - Form 130 **Part A** identification (with a new employment-period field),
    **Part B** quarter-wise TDS summary with the Form 138 receipt numbers,
    **Part C** Annexure I (salary computation) or Annexure II (specified senior
    citizens 75+).
  - https://www.patronaccounting.com/blog/form-130-vs-form-16-salary-tds-2026 ;
    https://www.shriramlife.com/blog/advice/what-is-form-130

### 7.4 Sections — **CONFIRMED, including that §195 → 393(2) and NOT 400** `[S+]`

| 1961 Act | 2025 Act |
|---|---|
| §192 (and §192A) | **§392** |
| §194-series to residents — 194C, 194J, 194I, 194H, 194A, 194D, 194DA, 194N, 194R, 194S… | **§393(1)** |
| §195 | **§393(2)**, Table **Sl. No. 17** |
| TCS (206C and neighbours) | **§394** |
| §194B / 194BB winnings, cash withdrawal, §194T partners | **§393(3)** |

- "The earlier Section 195 of the Income-tax Act, 1961 is now covered under
  **Section 393(2) [Table: Sl. No. 17]**, effective from 1st April, 2026."
- https://bcajonline.org/journal/income-tax-act-2025-tds-tcs-provisions/ ;
  https://cleartax.in/s/tds-and-tcs-changes-from-april-2026 ;
  https://www.india-briefing.com/news/section-393-income-tax-act-2025-tds-rules-rates-compliance-guide-44450.html/ ;
  https://blog.tdsman.com/2026/07/tds-on-payments-to-non-residents-section-3932-section-195/ ;
  https://www.taxtmi.com/tmi_notes?id=1885
- **CLAUDE.md's parenthetical "(NOT 400 — one widely-copied source has that wrong)"
  is vindicated.** Every source I saw says 393(2). I saw no source saying 400.
- **§393(1) having no reverse mapping is confirmed by construction** — it absorbs
  the whole resident 194-series into one sub-section with a table, so a 393(1)
  reference alone cannot identify which 1961 section it came from.

### 7.5 ⚠️ **CORRECTION TO CLAUDE.md: the payment-code range is 1001–1092, not 1001–1067**

CLAUDE.md says "returns now carry numeric payment codes **1001–1067**". The actual
allocation is: `[S]`

| Range | Covers |
|---|---|
| **1001–1004** | §392 — salary |
| **1005–1038** | §393(1) — non-salary, residents |
| **1039–1057** | §393(2) — non-residents |
| **1058–1067** | §393(3) — winnings, cash withdrawal, partners |
| **1068–1092** | **§394 — TCS** |

- https://www.terra-insight.com/resources/section-393-payment-code-reference/ ;
  https://www.terra-insight.com/insights/tds-payment-codes-1001-1092-india/ ;
  https://www.india-briefing.com/news/section-393-income-tax-act-2025-tds-rules-rates-compliance-guide-44450.html/
- **1067 is exactly where TDS ends and TCS begins**, which explains the error: the
  written range is right for **TDS only** and silently drops the **25 TCS codes**.
  If any validation in the codebase range-checks a payment code at ≤1067, it will
  **reject every valid TCS code**.
- Worked examples seen: **1023/1024** = §393(1) Sl. 6(i) contractor (the §194C
  equivalent, split individual/other); **1031** = §194Q purchase of goods;
  **1057** = §393(2) Sl. 17 non-resident; **1067** = §393(3) partner payments
  (§194T equivalent). `[S-]` on the individual code numbers — single publisher.
- **This does not disturb the repo's refusal to hold the payment-code table.**
  That refusal looks better after this pass, not worse: a single-publisher table
  of 92 codes is precisely the kind of thing that is confidently wrong.

### 7.6 The fork, and the transition rule — **CONFIRMED** `[S+]`

- "For all proceedings, assessments, notices, **TDS certificates**, and filings
  relating to **Financial Year 2025-26 and earlier**, the **old forms under the
  Income-tax Rules, 1962 will continue to apply**."
- https://cleartax.in/s/new-income-tax-forms
- **This is the "permanent fork, not a migration" position, in a source's own
  words.** CLAUDE.md's design — translate at the emission boundary, keep both
  vocabularies forever, never rekey a store — is corroborated.
- I found **no source** describing the transition test as "credit or payment,
  whichever is earlier". That is CLAUDE.md's own formulation and it is the correct
  general TDS trigger, but I could not independently confirm it as the stated
  commencement rule. `[U]` — not refuted, just not found.

---

## 8. Form 16 Part B must come from TRACES — **CONFIRMED, and now BROADER**

### 8.1 The 1961-Act position `[S+]`

- **CBDT (Systems) Notification No. 09/2019, dated 6 May 2019.**
- Mandatory for **all deductors** to issue **Part B of Form 16 by downloading it
  from the TRACES portal**, for all sums deducted **on or after 1 April 2018**
  under §192.
- Depends on correct data in **Annexure II of Form 24Q**; TRACES stamps a **unique
  TDS certificate number**; the deductor must then authenticate it by manual or
  digital signature under **Rule 31(6)**.
- https://taxguru.in/income-tax/generation-form-16-part-traces.html ;
  https://taxguru.in/income-tax/revised-procedure-issue-part-tds-certificate-form-no16.html ;
  https://www.taxscan.in/tds-certificate-part-b-form-16-download-traces-portal-cbdt/35510 ;
  https://www.in.kpmg.com/taxflashnews/KPMG-Flash-News-Part-B-of-Form-16.pdf `[loc]` (KPMG flash news PDF, **not fetched**)
- Official PDF of the notification located at
  https://www.incometax.gov.in/iec/foportal/sites/default/files/2020-07/notification_09_2019.pdf `[loc]`
  — **host blocked, not fetched.**

**So the answer to Q8 is yes: third-party software cannot lawfully mint Part B.**
It can prepare and file the Form 24Q that TRACES generates Part B *from*, and it
can store and distribute the downloaded PDF. It cannot be the source of the
certificate.

### 8.2 The 2025-Act position is **stricter**, and this extends the repo's rule `[S]`

Under **Rule 215(1)** of the Income-tax Rules 2026 read with **§395(4)(b)**:

- **Form 130 as a whole** — not merely a Part B — **must be generated through and
  downloaded from TRACES.** The employer cannot self-generate it.
- **It cannot be issued at all until the quarterly Form 138 has been filed and
  processed.**
- The same constraint is stated for banks issuing certificates for pension and
  interest deducted under §393(1).
- https://www.kanakkupillai.com/learn/income-tax-form-130-replaces-form-16/ ;
  https://fimaco.in/form-130-income-tax-act-2025/ ;
  https://taxguru.in/income-tax/income-tax-form-130-replaces-form-16-salary-pension-tds-certificate.html ;
  https://www.5paisa.com/stock-market-guide/tax/form-130-new-form-16

**Practical consequence for PracticeSync:** whatever the product does today for
Form 16 Part B, the Form 130 rule is **wider** — the whole certificate, gated on a
filed-and-processed return. Any roadmap item shaped like "generate Form 130" is
not buildable; the buildable shape is "file Form 138, then fetch and distribute
the TRACES-generated Form 130". Worth checking before anyone specifies it.

---

## 9. CROSS-CHECK: repo registries vs. this research

Coverage printed from the repo at the time of writing:

```
slabs        years=['2025-26', '2026-27']     LATEST_VERIFIED_FY     = 2025-26
entity       years=['2025-26', '2026-27']
presumptive  years=['2025-26', '2026-27']
minimum tax  years=['2025-26', '2026-27']
TDS          years=['2025-26', '2026-27']     LATEST_VERIFIED_TDS_FY = 2025-26
CII          2001-02 … 2025-26                LATEST_CII_FY          = 2025-26
```

| Area | Verdict |
|---|---|
| Slabs, rebate, standard deduction, surcharge (both FYs, both regimes) | **matches** — every figure |
| Entity rates: firm 30%/12%, company 30%/25%/7%/12%, 115BAA 22%, 115BAB 15%, flat 10% surcharge, 2-year turnover lookback | **matches** |
| Foreign company 35% | **absent from the repo** — gap, possibly deliberate scope |
| Presumptive: 44AD 2cr/3cr 8%/6%, 44ADA 50L/75L 50%, 44AE ₹1,000-per-tonne / ₹7,500, 12,000 kg, 10 vehicles | **matches** |
| MAT 15%, credit 15 years | **matches** |
| AMT 18.5%, ₹20L cushion **denied to firm/LLP** | **matches, and correctly reasoned in the code** |
| CII 2021-22 → 2024-25 | **matches** |
| **CII 2025-26 = 380** | **WRONG — notified value is 376** |
| **CII 2026-27** | **missing — notified value is 384** |
| CLAUDE.md "payment codes 1001–1067" | **incomplete — 1001–1092; 1068–1092 is TCS** |
| CLAUDE.md renumbering (forms and sections) | **fully corroborated, nothing refuted** |
| CLAUDE.md "rates and thresholds unchanged under the 2025 Act" | **corroborated** |
| CLAUDE.md TDS return due dates incl. Q4 = 31 May | **corroborated, survives the renumbering** |

---

## 10. What I would and would not act on

**Act on (data changes, low risk, clear evidence):**
1. `CII_BY_FY["2025-26"]` **380 → 376**. Six independent professional sources,
   a named notification (70/2025 of 01-07-2025), zero dissent. This is a live
   wrong number in a shipped calculation.
2. Add `CII_BY_FY["2026-27"] = 384` (Notification 85/2026). Move `LATEST_CII_FY`.
3. Correct the CLAUDE.md payment-code range to **1001–1092**, and note the
   1068–1092 TCS block. Check for any `<= 1067` range validation.

**Say out loud in the commit:** the verification is **secondary-source only**,
because the egress policy blocks every government host. That is exactly the
distinction `LATEST_VERIFIED_FY` exists to preserve, and papering over it would
defeat the mechanism.

**Do NOT act on without a human reading the primary text:**
- Flipping `verified=True` on any FY 2026-27 registry entry.
- The "31 August 2026" staggered ITR-3/ITR-4 due date — single synthesis,
  contradicts `compliance_engine`, and a wrong due date is a missed deadline.
- Individual §393 payment code numbers (1023, 1031, 1057, 1067) — one publisher.
- The as-enacted §206 AMT text under the 2025 Act.
- Anything the **corrigendum G.S.R. 286(E) of 16-04-2026** may have moved.

**The open hole I could not close:** the **55 other Finance Act 2026 amendments**.
I confirmed slabs did not change and STT did. I have no visibility into the rest,
and a listing exists that I could not read.

---

## 11. Recommendation on the research method itself

This environment **cannot do primary-source statutory research**. That is not a
retry-able failure and it is not specific to `.gov.in` — Wikipedia and every
Indian tax publisher are blocked at the same proxy with the same 403.

Two honest options:

1. **Have a human fetch and drop the PDFs into the repo.** The list is short and
   known: Finance Act 2025 and 2026 (First Schedule), Notification 22/2026 +
   G.S.R. 286(E), Notifications 70/2025 and 85/2026 (CII), Notification 09/2019.
   That converts this entire document from `[S]` to `[P]` in one pass, and it is
   the same hand-off the repo already accepts for the **ITR JSON schemas** — a
   precedent, not a new burden.
2. **Ask an administrator to allowlist the statutory hosts** for sessions doing
   compliance work: `incometaxindia.gov.in`, `incometax.gov.in`, `egazette.gov.in`,
   `cbic.gov.in`, `indiabudget.gov.in`.

Until one of those happens, treat everything above as **well-corroborated
secondary research**, and keep the `verified` flags honest.
