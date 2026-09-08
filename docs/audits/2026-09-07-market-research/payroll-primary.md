# Indian payroll statutory position — research as at 2026-09-07

Re-run of payroll statutory research for PracticeSync (CA-firm payroll bureau model).
Owner asked for primary sources. **No primary source was obtainable.** Read section 0
before trusting any grade below.

---

## 0. Network reality — I tested it, and it is worse than "gov.in is blocked"

The instruction was to test the proxy myself rather than inherit the earlier session's
note. I did. The earlier note was right about the conclusion and understated the scope.

`WebFetch` returned `EGRESS_BLOCKED` for **every host tried**, official and unofficial:

| Host | Result |
|---|---|
| `www.epfindia.gov.in` | EGRESS_BLOCKED |
| `epfindia.gov.in` (bare) | EGRESS_BLOCKED |
| `www.esic.gov.in` | EGRESS_BLOCKED |
| `esic.gov.in` (bare) | EGRESS_BLOCKED |
| `labour.gov.in` | EGRESS_BLOCKED |
| `www.incometax.gov.in` | EGRESS_BLOCKED |
| `www.indiacode.nic.in` | EGRESS_BLOCKED |
| `taxguru.in` (secondary) | EGRESS_BLOCKED |
| `cleartax.in` (secondary) | EGRESS_BLOCKED |
| `economictimes.indiatimes.com` | fetch failed |
| **`example.com`** | **EGRESS_BLOCKED** |

`example.com` is the decisive test: this is a **blanket egress denial**, not a
gov.in-specific policy. Direct `curl` through the proxy confirms it at the transport
layer — `curl: (56) CONNECT tunnel failed, response 403` for both `epfindia.gov.in`
and `example.com`.

`curl -sS "$HTTPS_PROXY/__agentproxy/status"` shows `recentRelayFailures` full of
`connect_rejected — gateway answered 403 to CONNECT (policy denial or upstream
failure)`, including hosts a previous session tried: `egazette.gov.in`,
`www.pib.gov.in`, `incometaxindia.gov.in`, `www.tdscpc.gov.in`, `cbic-gst.gov.in`,
and `en.wikipedia.org`. `/root/.ccr/README.md` classes 403/407 as an organization
egress-policy denial and says explicitly: report it, do not retry or route around it.

**`WebSearch` does work** — it does not traverse this proxy. So everything below comes
from **search-result snippets only**. I never rendered a page.

### What this does to the grading scheme

The requested `[P] primary/official` grade **cannot be honestly awarded to a single
fact in this report**, so I have not awarded it once. Substituted scheme:

- **`[S-gov]`** — the claim traces to an official `gov.in` URL that appeared in search
  results, but **I did not fetch it**. Strongest grade available today. Treat as a
  citation someone must still open.
- **`[S]`** — secondary (law firm, Big-4, payroll vendor, legal publisher), snippet only.
  Multiple independent secondaries agreeing raises confidence but never to primary.
- **`[U]`** — unconfirmed, or sources actively contradict each other.

Every URL below is marked **NOT FETCHED** unless stated otherwise. None is stated
otherwise.

### Official documents located but unreadable — hand these to a human

These are the primary sources a person with an unrestricted browser should open. Finding
them is most of the value this run can deliver.

- `https://www.labour.gov.in/static/uploads/2026/01/de4758d5bfeffc456d7de97a801891b0.pdf`
  — MoLE, *FAQs on Labour Codes* **[S-gov, NOT FETCHED]**
- `https://www.labour.gov.in/static/uploads/2026/03/a4ccf4c6d97c4f1f36a6d83f8c64213d.pdf`
  — MoLE, *Additional FAQs on Labour Codes (as on 16.03.2026)* **[S-gov, NOT FETCHED]**
- `https://www.pib.gov.in/PressReleseDetailm.aspx?PRID=2192463` — PIB, labour codes
  effective **[S-gov, NOT FETCHED]**
- `https://www.epfindia.gov.in/site_en/revamped_ecr.php` — EPFO revamped ECR
  **[S-gov, NOT FETCHED]**
- `https://www.epfindia.gov.in/site_docs/PDFs/MiscPDFs/ContributionRate.pdf` — EPFO
  *Present Rates of Contribution* **[S-gov, NOT FETCHED]**
- `https://roap.esic.gov.in/attachments/circularfile/2020_Applicability_of_ESI_under_Code_on_Social_Security_2020_and_registration_through_SPREE_1766053840.pdf`
  — ESIC circular on SS Code applicability **[S-gov, NOT FETCHED]**
- `https://www.epfindia.gov.in/site_en/circulars.php` — EPFO circulars index
  **[S-gov, NOT FETCHED]**

Gazette numbers surfaced in snippets (unverified against eGazette, which is also
blocked): **S.O. 2701(E) dated 29-05-2026** (EPF wage ceiling under SS Code s.2(89));
**S.O. 4711(E) dated 25-08-2026** (bonus eligibility threshold under Code on Wages
s.26(1)).

---

## 1. EPF — ceiling, rate, EPS diversion, EDLI, admin charges

### 1a. The wage ceiling is still ₹15,000 — but the *instrument* changed, and there is a live proposal to raise it

**Claim:** The EPF wage ceiling remains **₹15,000/month**. It was **re-notified** on
**29 May 2026** under **s.2(89) of the Code on Social Security, 2020** (reported as
S.O. 2701(E)), replacing the EPF Act 1952 basis for the same number. Unchanged in
amount since September 2014.
**Grade: [S]** — consistent across four independent secondaries.
- `https://www.scconline.com/blog/post/2026/06/01/15000-wage-ceiling-epf-coverage-membership-contributions/` — SCC Online — **NOT FETCHED**
- `https://www.livelaw.in/law-firms/law-firm-articles-/epf-scheme-2026-ceiling-always-15000-what-has-actually-changed-what-should-hr-do-now-540422` — LiveLaw — **NOT FETCHED**
- `https://kpmg.com/xx/en/our-insights/gms-flash-alert/2026/flash-alert-2026-153.html` — KPMG GMS Flash Alert 2026-153 — **NOT FETCHED**
- `https://www.mondaq.com/india/employee-benefits-compensation/1819844/social-security-schemes-notified-what-employers-need-to-know` — Mondaq — **NOT FETCHED**

**⚠ Live proposal — NOT law.** Press reports of **early August 2026** say the Finance
Ministry cleared raising the PF/pension wage ceiling **₹15,000 → ₹25,000**. **Union
Cabinet approval pending; no gazette notification issued.** Several outlets float
**1 April 2027** as a likely effective date — that is journalistic expectation, not
policy. Background: a **Supreme Court direction of January 2026** told the Centre and
EPFO to decide on revision within four months.
**Grade: [U]** for the ₹25,000 figure and any date; **[S]** only for "a proposal exists
and is not yet law".
- `https://www.sgcms.com/regulatory-updates/epf-wage-ceiling-at-%E2%82%B925000-what-has-been-decided-and-what-has-not/` — **NOT FETCHED**
- `https://www.newsonair.gov.in/supreme-court-directs-centre-epfo-to-decide-on-revision-of-epfs-wage-ceiling-within-four-months/` — News on AIR (gov) — **[S-gov, NOT FETCHED]**

**Action for the codebase:** the *number* in `domain/payroll/statutory.py` is right.
The *authority* recorded against it is stale, and ₹25,000 is a watch item with a
plausible 1-Apr-2027 landing — i.e. it would land inside FY 2027-28, not this one.

### 1b. ⚠ CONTRADICTION — the 1952/1995/1976 schemes have been REPLACED

**Claim:** On **29 June 2026** MoLE notified the **Employees' Provident Fund Scheme,
2026**, the **Employees' Pension Scheme, 2026** and the **Employees' Deposit Linked
Insurance Scheme, 2026**, collectively replacing EPF Scheme 1952, EPS 1995 (and EFPS
1971) and EDLI 1976. Reported effective immediately on notification.
**Grade: [S]** — four independent secondaries including Business Standard, SCC Online
and KPMG.
- `https://www.businesstoday.in/personal-finance/news/story/new-epf-scheme-2026-notified-as-part-of-code-on-social-security-540258-2026-07-01` — **NOT FETCHED**
- `https://www.business-standard.com/finance/personal-finance/epf-scheme-2026-notified-what-changes-for-your-pf-account-pension-126070200508_1.html` — **NOT FETCHED**
- `https://www.scconline.com/blog/post/2026/07/05/employees-pension-scheme-2026-key-changes/` — **NOT FETCHED**
- `https://mercans.com/resources/statutory-alerts/india-new-epf-eps-edli-schemes-2026-under-the-code-on-social-security-effective-29-june-2026/` — **NOT FETCHED**

**⚠ Transition deadline.** Schemes under the EPF Act are reported valid for a **one-year
transition ending 20 November 2026**, to the extent not inconsistent with the SS Code.
That is **~10 weeks from today**. **Grade: [S]**, single-source-shaped — verify before
relying on it.

### 1c. Rates — all reported carried forward UNCHANGED into the 2026 schemes

| Item | Position | Grade |
|---|---|---|
| Employee contribution | **12%** of wages | [S] |
| Employer contribution | **12%**, split | [S] |
| EPS diversion | **8.33%** of wages, restricted to the ceiling | [S] |
| EPS monetary cap | **₹1,250/month** (8.33% × ₹15,000) | [S] |
| Central Govt EPS contribution | **1.16%** of wages up to ceiling | [S] |
| Higher-pension joint-option cases | extra **1.16%** on wages above ₹15,000 → effective **9.49%** | [S] |
| EDLI | **0.5%** of wages, **capped ₹75/employee/month**, employer only | [S] |
| EPF administrative charges | **0.5%** of EPF wages, **minimum ₹500/month**; **₹75** if no contributory member that month | [S] |
| EDLI inspection charges (EDLI-exempted establishments) | **0.005%, minimum ₹1** | [S] |

Sources (all **NOT FETCHED**):
`https://mercans.com/glossary/employees-provident-fund-epf-contribution/`,
`https://www.comply360.in/employees-pension-scheme-eps-2026-what-changed-what-remains-and-what-employers-must-do/`,
`https://www.ramco.com/resources/ebook/payroll/india-social-security-compliance-guide-epf-eps-edli`,
`https://knnindia.co.in/news/newsdetails/sectors/rate-of-admin-charges-payable-by-employer-under-epf-scheme-reduced-to-050`.

**No 2025/2026 notification changing any of these rates was found.** What changed is
the *instrument* (2026 schemes) and the *base* (see §2), not the percentages.

**Grade note:** the `₹75` EDLI cap and the `₹500` admin minimum come from payroll-vendor
glossaries, the weakest class of source used here. Both are arithmetically consistent
with the long-standing position (0.5% × ₹15,000 = ₹75), which is corroborative but not
proof. Confirm against the EPFO *ContributionRate.pdf* listed in §0.

---

## 2. ⚠ Code on Wages / Code on Social Security commencement — CONFIRMED, and it reaches further than the codebase assumes

### 2a. Commencement: 21 November 2025 — CONFIRMED

**Claim:** All four labour codes — Code on Wages 2019, Code on Social Security 2020,
Industrial Relations Code 2020, OSH Code 2020 — came into force **21 November 2025**.
**Grade: [S]**, but with unusually broad agreement: PIB (gov), KPMG, BDO, DLA Piper,
Herbert Smith Freehills Kramer, PwC India, and the US payroll association all concur.
This is as close to settled as this run can get without a fetch.
- `https://www.pib.gov.in/PressReleseDetailm.aspx?PRID=2192463` — PIB — **[S-gov, NOT FETCHED]**
- `https://www.bdo.in/en-gb/insights/alerts-updates/alert-implementation-of-labour-codes-key-provisions-notified-effective-21-november-2025` — **NOT FETCHED**
- `https://kpmg.com/xx/en/our-insights/gms-flash-alert/flash-alert-2025-267.html` — **NOT FETCHED**
- `https://www.hsfkramer.com/notes/employment/2025-posts/india-labour-codes-implemented-a-landmark-reform` — **NOT FETCHED**
- `https://www.pwc.in/tax-knowledge-hub/new-labour-codes.html` — **NOT FETCHED**

**The codebase's 21-11-2025 commencement date is CONFIRMED at [S].**

### 2b. The 50% rule — confirmed in substance; note the section number

**Claim:** The definition carves out HRA, conveyance, overtime, employer PF
contribution, commission, gratuity, retrenchment compensation, sums to defray special
expenses, and house accommodation/utilities. **First proviso: where those exclusions
exceed 50% of total remuneration, the excess is deemed to be wages.** Effect: basic + DA
+ retaining allowance must effectively be ≥ 50% of total remuneration.
**Grade: [S]**, multiple independent sources.
- `https://www.mondaq.com/india/employee-benefits-compensation/1833552/understanding-the-50-wage-rule-under-the-code-on-wages-2019-a-cap-on-exclusions-not-a-ceiling-on-wages` — **NOT FETCHED**
- `https://ksandk.com/employment-law/guides/fifty-percent-wage-rule/` — **NOT FETCHED**

**Naming point for the codebase.** CLAUDE.md and `domain/payroll/wage_base.py` cite
**Code on Wages s.2(y)**. The provision actually operating on EPF and ESI is
**s.2(88) of the Code on Social Security, 2020**, which mirrors it. Both the EPFO and
ESIC instructions found in this run cite **2(88)**. The substance is identical; the
citation in the code comments is imprecise, and a CA reading the working would notice.

### 2c. ⚠ CONTRADICTION — does it apply to ESI, gratuity and bonus?

The MoLE FAQs are reported as saying **excess allowances are treated as wages for PF,
ESI, bonus AND gratuity**, from the same 21-11-2025 date, with **no retrospective
recovery** for service before that date. Gratuity, ESI and other retirement benefits are
themselves **excluded from the total-remuneration denominator**; the employer's PF/pension
share and statutory bonus **are included** in it.
**Grade: [S]** — traced to the two labour.gov.in FAQ PDFs in §0, but read through
secondary summaries, **not fetched**.
- `https://www.scconline.com/blog/post/2026/04/26/ministry-faqs-four-labour-codes-india-2026/` — **NOT FETCHED**
- `https://www.gdsnco.in/2026/03/17/additional-faqs-on-labour-codes-as-on-16-03-2026/` — **NOT FETCHED**

**This directly contradicts two deliberate decisions recorded in CLAUDE.md:** that ESI is
left on gross, and that gratuity is left unchanged. See §3b — but note the sources
conflict there, so the ESI half is `[U]`, not settled against us.

---

## 3. ESI

### 3a. Rates and ceiling — UNCHANGED, confirmed

| Item | Position | Grade |
|---|---|---|
| Employee | **0.75%** | [S] |
| Employer | **3.25%** | [S] |
| Total | 4.00% | [S] |
| Wage ceiling | **₹21,000/month** | [S] |
| Ceiling, employees with disability | ₹25,000/month | [S] |
| Last revised | July 2019 | [S] |

- `https://tallysolutions.com/business-guides/esi-contribution-rate-2026-current-percentage-for-employer-employee/` — **NOT FETCHED**
- `https://equily.in/compliance/esi-contribution-guide` — **NOT FETCHED**

Also confirmed **[S]**: the ₹21,000 threshold "continues to apply … until new rules are
notified" (MoLE FAQ, via secondary).

### 3b. ⚠ The computation base is CONTESTED — flag, do not act yet

ESIC issued implementing instructions **10 and 11 December 2025**, making **December 2025
the first affected payroll cycle**. Beyond that the secondaries **openly disagree**:

- **Position A** — contributions are now computed on **s.2(88) "core wages"** including
  the 50% add-back, replacing gross.
  `https://www.key4comply.com/blogposts/esic-compliance-in-2026-why-wage-definition-has-replaced-gross-pay/` — **NOT FETCHED**
- **Position B** — **eligibility** is tested on the new wage definition, but the
  **contribution is still charged on gross pay**, with the 50% logic reaching only
  benefit computation.
  `https://www.patronaccounting.com/blog/esic-calculation-compliance-complex-business-structures` — **NOT FETCHED**

One vendor page states both positions in adjacent sentences, which is itself evidence the
market has not settled this. Karma Global's write-up is titled around "confusion over
quantifying ESI applicability" — practitioners are contesting it too.
`https://karmamgmt.com/blog/new-labour-codes-2025-esic-applicability-wage-definition` — **NOT FETCHED**

**Grade: [U].** **Recommendation: change nothing in `_compute_esi` on this evidence.**
CLAUDE.md already records the ESI-on-gross choice as unconfirmed and pinned by a test,
and gross is the direction that cannot under-deduct. What has changed is that this is no
longer a quiet open question — there is a dated ESIC instruction behind it, and the
comment in the code should say so and name 2(88). Resolving it needs the ESIC circular
in §0 fetched by a human.

### 3c. Contribution periods — UNCHANGED

**Claim:** Two six-month contribution periods, **1 April–30 September** and
**1 October–31 March**, each with a benefit period beginning three months later
(Apr–Sep funds Jan–Jun following; Oct–Mar funds Jul–Dec). An employee whose wages cross
₹21,000 mid-period **stays covered to the end of that period**. Half-yearly returns
**11 November** and **11 May**.
**Grade: [S].** No source called this "Rule 50" by name — the ESI (Central) Rules 1950
citation is **[U]** and may have been superseded by rules under the SS Code.
- `https://futurexsolutions.com/esi-salary-limit-2026/` — **NOT FETCHED**
- `https://ezhrm.in/esi-return-filing-2026-hr-guide/` — **NOT FETCHED**

---

## 4. EPFO revamped ECR — workflow changed, FILE FORMAT DID NOT

**Claim (workflow):** Revamped/re-engineered ECR applies from **wage month September
2025** onward. Changes:
- **Sequential filing enforced** — cannot file a later wage month until the earlier one
  is filed and processed. October 2025 is blocked while September 2025 is pending.
  **The earlier note is CONFIRMED [S].**
- **Return filing and payment are segregated** — submit the return first, then generate
  the challan and pay, rather than one combined act.
- **Nil returns mandatory** for months with zero contributory members, to preserve the
  sequence.
- All filings made after rollout use the revamped system, **including catch-up filings
  for earlier missed months**.

**Claim (format):** **"There is no change in the existing ECR file format."** It remains
a plain `.txt`, **`#~#`-delimited**, **11 fields** per member. The "25 fields → 11
fields" reduction that appears in several write-ups is the **ECR 2.0 change of ~2017**,
not a 2025/2026 change — do not read it as recent.
Validation rules restated: EPF wages ≤ gross wages; EPS wages ≤ EPF wages; EDLI wages =
EPF wages, max ₹15,000. Upload by the 15th.
**Grade: [S].**
- `https://www.epfindia.gov.in/site_en/revamped_ecr.php` — **[S-gov, NOT FETCHED]** — the page to open
- `https://www.sgcms.com/regulatory-updates/re-engineered-electronic-challan-cum-return-ecr/` — **NOT FETCHED**
- `https://karmamgmt.com/blog/epfo-revamped-ecr-september-2025-key-features-compliance` — **NOT FETCHED**
- `https://updates.complianceage.com/revamped-epfo-ecr-faqs-2025/` — EPFO FAQs, via secondary — **NOT FETCHED**

**Bureau relevance:** sequential filing is the operationally sharp one. A bureau running
many client establishments cannot let any single establishment fall a month behind
without blocking every later month for that establishment.

---

## 5. Professional tax

**Claim (count):** Roughly **20–21 states and UTs** levy PT. Sources disagree on the
exact number and the disagreement is explainable, not sloppy — it turns on three edge
cases below.
**Grade: [S]** for the list; **[U]** for any single headline number.

Named as levying: **Maharashtra, Karnataka, Tamil Nadu, Telangana, Andhra Pradesh,
West Bengal, Gujarat, Kerala, Madhya Pradesh, Assam, Bihar, Jharkhand, Chhattisgarh,
Odisha, Sikkim, Tripura, Meghalaya, Manipur, Mizoram, Nagaland**, and **Puducherry** (UT).

Named as NOT levying: **Delhi, Uttar Pradesh, Haryana, Uttarakhand, Rajasthan,
Himachal Pradesh, Jammu & Kashmir, Goa, Chandigarh**.

**Three edge cases that explain the 20-vs-21 spread — all payroll-relevant:**
1. **Punjab** — levies a flat **₹200/month (₹2,400/yr)** as **Development Tax** under the
   *Punjab State Development Tax Act 2018*, **not** as professional tax. A payroll engine
   that only knows "PT" under-deducts in Punjab. **[S]**
2. **Odisha** — reported to have **repealed PT with effect from 1 April 2026**. **[U]** —
   single-source; material if true, because Odisha appears on most "levies PT" lists that
   predate it.
3. **Chhattisgarh** — levy reported **exempted by notification**, so nothing is deducted
   today despite the Act existing. **[U]**

- `https://tmservices.co.in/professional-tax-state-wise-rates-2026/` — **NOT FETCHED**
- `https://www.indpayroll.com/blog/professional-tax-slab-rates-by-state-in-india-2026-complete-guide` — **NOT FETCHED**
- `https://employmentlaw.lkslaw.com/professional-tax` — L&S law firm — **NOT FETCHED**

**Claim (no national due date): CONFIRMED [S].** PT is a state levy; due dates and
frequency vary by state. Worked examples found: **Maharashtra** monthly by the **15th**
(changed from March 2026); **Karnataka** by the **20th** of the following month;
**Tamil Nadu** **half-yearly** (Aug for Apr–Sep, Jan for Oct–Mar), returns by 31 Oct and
30 Apr; **West Bengal** annual, **31 July**. Constitutional cap **₹2,500 per person per
FY** (60th Amendment, 1988).
- `https://www.zoho.com/in/payroll/academy/taxes-and-compliance/professional-tax-rules.html` — **NOT FETCHED**
- `https://vakilsearch.com/article/professional-tax-due-date/` — **NOT FETCHED**

**⚠ Note against CLAUDE.md:** it says PT is modelled for four states out of **"the
twenty-two states that levy it."** No source in this run supports 22; the range found is
20–21, and Odisha may have just left it. The figure in CLAUDE.md looks stale by one or
two. Maharashtra's due-date change from March 2026 also post-dates the current
`routers/payroll.py` literals and should be checked.

---

## 6. Payment of Bonus — both ceilings CONFIRMED, and freshly re-notified

**Claim:** On **25 August 2026** MoLE issued two notifications under the **Code on
Wages, 2019**, both **retrospective to 21 November 2025**:
- **Eligibility ceiling ₹21,000/month** — notified under **s.26(1)**, reported as
  **S.O. 4711(E)**. (Successor to Payment of Bonus Act s.2(13).)
- **Calculation ceiling — ₹7,000/month OR the applicable minimum wage, whichever is
  HIGHER.** (Successor to s.12.)

**Both figures in CLAUDE.md are CONFIRMED [S], and the "whichever is higher" reading is
explicitly confirmed** — including the trap the codebase already guards against, that
treating ₹7,000 as a ceiling rather than a floor underpays.

- `https://www.scconline.com/blog/post/2026/08/26/bonus-rules-under-code-on-wages-eligibility-calculation/` — **NOT FETCHED**
- `https://ascent-hr.com/notification/ministry-of-labour-employment-notifies-monthly-wage-threshold-for-bonus-eligibility/` — **NOT FETCHED**
- `https://www.staffnews.in/2026/09/bonus-calculation-wages-ceiling-at-rs-7000.html` — **NOT FETCHED**
- `https://www.govtstaff.com/2026/09/bonus-calculation-wages-ceiling.html` — **NOT FETCHED**

**Two notes.**
1. The Payment of Bonus Act 1965 is now **Chapter VIII of the Code on Wages**. The
   *authority* to cite has moved even though both numbers survived. `domain/payroll/bonus.py`
   should cite Code on Wages s.26 alongside the 1965 Act.
2. **One search summary asserted the Code on Wages was "not fully notified as of April
   2026" and that the Bonus Act still governs.** That is **contradicted** by the
   overwhelming 21-11-2025 commencement evidence in §2a and by the 25-08-2026
   notifications themselves. Recorded here only so nobody rediscovers it and is misled —
   it looks like stale pre-commencement copy resurfacing in a 2026 page.
3. **`domain/payroll/bonus.py`'s refusal to guess the minimum wage remains correct.**
   Nothing found supplies a national minimum-wage table; it is still per state, per
   scheduled employment, per skill grade.

---

## 7. Gratuity — formula, qualifying period and exemption all UNCHANGED

| Item | Position | Grade |
|---|---|---|
| Formula | **last drawn salary × 15 × completed years ÷ 26** | [S] |
| Qualifying period | **5 years** continuous service | [S] |
| **Fixed-term employees** | **pro rata after 1 year** under the SS Code — not 5 | [S] |
| s.10(10) exemption | **₹20 lakh**; raised from ₹10 lakh in March 2018; **not revised since** | [S] |

- `https://cleartax.in/s/gratuity-calculator` — **NOT FETCHED**
- `https://corridalegal.com/social-security-code-gratuity-rules-eligibility-and-calculation-guide/` — **NOT FETCHED**
- `https://ezhrm.in/new-gratuity-rules-india-2026-labour-codes-changed/` — **NOT FETCHED**

**⚠ Two things for the codebase.**
- The **fixed-term 1-year pro-rata entitlement** is a real behavioural difference. If
  `gratuity.py` applies a flat 5-year gate, it under-pays fixed-term employees. Worth
  grepping.
- Per §2c the **s.2(88) wage base is reported to reach gratuity too**, which sits against
  CLAUDE.md's "Gratuity likewise [not changed]". Same `[U]` caveat as ESI — the base
  question is unsettled in secondaries and needs the MoLE FAQ fetched.

---

## 8. §192 withholding — CONFIRMED, with the section renumbering the codebase already knows about

**Claim (default regime): CONFIRMED.** The **new regime is the default** since FY 2023-24.
If an employee gives **no intimation**, the employer must withhold under the new regime.
Crucially, and matching CLAUDE.md exactly: **the intimation to the employer "would not
automatically be tantamount to exercising the option in terms of s.115BAC(6)"** — the
employee may still choose a different regime in the return. This is the
**Circular 04/2023** position and it is **intact**.
**Grade: [S]** — BDO and IndiaFilings both restate the circular's wording.
- `https://www.bdo.in/en-gb/insights/alerts-updates/direct-tax-alert-cbdt-issues-clarification-regarding-tax-deduction-at-source-by-employer` — **NOT FETCHED**
- `https://www.indiafilings.com/learn/cbdt-clarification-on-tds-from-salary-under-new-tax-regime` — **NOT FETCHED**

**No superseding circular for FY 2026-27 was found.** That is an absence of evidence
through a search-only channel, **not** evidence of absence — CBDT issues an annual salary-TDS
circular and one may exist. **[U]** on "no newer circular".

**Claim (standard deduction, FY 2026-27):**
- **New regime: ₹75,000**
- **Old regime: ₹50,000**
- Consequent zero-tax point ~**₹12.75 lakh** gross for salaried under the new regime
  (₹12 lakh rebate threshold + ₹75,000).
**Grade: [S].**
- `https://cleartax.in/s/standard-deduction-salary` — **NOT FETCHED**
- `https://www.keka.com/tds-on-salary` — **NOT FETCHED**

**Claim (renumbering) — CONFIRMS the codebase's TDS fork:** from **1 April 2026**, salary
TDS is **s.392 of the Income-tax Act, 2025**; salary paid **up to 31 March 2026** stays
under **s.192** of the 1961 Act. This independently corroborates
`domain/tds/vocabulary.py`'s **192 → 392** mapping and the by-event boundary.
**Grade: [S].**
- `https://taxgarden.in/blog/tds-on-salary-section-192-392-employer-guide-india` — **NOT FETCHED**

**Open:** what **s.115BAC** is renumbered to under the 2025 Act was **not established**.
Sources for FY 2026-27 still say "115BAC", which may be habit rather than accuracy.
**[U]** — needs checking before any user-facing string cites a regime section for
FY 2026-27.

---

## 9. Summary of contradictions and confirmations against CLAUDE.md

**Contradicts / supersedes:**
1. **EPF/EPS/EDLI Schemes 1952/1995/1976 replaced by the 2026 Schemes** (notified
   29-06-2026). Rates carried forward; the instrument did not. **[S]**
2. **Transition for old-Act schemes reportedly ends 20 November 2026** (one year from commencement) —
   ~10 weeks out. **[S]**
3. **EPF ceiling re-notified under SS Code s.2(89)** on 29-05-2026 — number right,
   authority stale. **[S]**
4. **s.2(88), not Code on Wages s.2(y), is the provision EPFO/ESIC actually cite.** **[S]**
5. **The 50% wage base is reported to reach ESI, gratuity and bonus** — against two
   deliberate "not changed" decisions. **[U]**, sources conflict; do not act yet.
6. **PT: "twenty-two states" in CLAUDE.md is unsupported** — 20–21, with Odisha possibly
   repealed from 01-04-2026 and Punjab levying a Development Tax that is not PT. **[S]/[U]**
7. **Maharashtra PT due date moved to the 15th from March 2026** — check the literals in
   `routers/payroll.py`. **[S]**
8. **Fixed-term employees: gratuity pro rata after 1 year**, not 5. **[S]**

**Confirms (no change needed):**
- 21-11-2025 commencement **[S, broad agreement]**
- EPF 12%, EPS 8.33%/₹1,250, EDLI 0.5%/₹75, admin 0.5%/min ₹500 **[S]**
- ESI 0.75%/3.25%, ₹21,000, Apr–Sep / Oct–Mar periods **[S]**
- ECR **file format unchanged**; workflow sequential **[S]**
- Bonus ₹21,000 eligibility and ₹7,000-or-minimum-wage-**whichever-higher** calculation **[S]**
- Gratuity 15/26, 5 years, s.10(10) ₹20 lakh **[S]**
- New regime default; intimation ≠ s.115BAC(6) election; SD ₹75,000 / ₹50,000 **[S]**
- 192 → 392 from 01-04-2026 **[S]**

**Unresolved, needs a human with an unrestricted browser:**
- ESI computation base: gross vs s.2(88) wages (§3b)
- Whether the 50% base truly reaches gratuity (§7)
- Whether a FY 2026-27 CBDT salary-TDS circular supersedes 04/2023 (§8)
- The s.115BAC successor section number under the 2025 Act (§8)
- Odisha PT repeal; Chhattisgarh exemption (§5)
- Exact gazette references S.O. 2701(E) and S.O. 4711(E)
- The ₹25,000 EPF ceiling proposal's Cabinet status (§1a)

---

## 10. Method note

- Tool used: **`WebSearch` only**. `WebFetch` and `curl` are blocked for all hosts.
- **No page in this document was fetched.** Every URL is a search-result URL.
- **No `[P]` grade is awarded anywhere in this report**, because none can be honestly
  earned through a search-only channel.
- Where sources conflicted I recorded the conflict rather than picking a winner (§3b, §5, §6).
- Figures are reported as found. Nothing here was written from model memory; anything I
  could not source is marked `[U]` or listed in §9 as unresolved.
