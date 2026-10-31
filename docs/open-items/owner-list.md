# The owner's list — one place (refreshed 15 October 2026, IST; S14 confirmed again and S15 added on 27 October 2026; S16 to S20 added on 29 October 2026; the count of items waiting on you added on 30 October 2026)

Everything that is yours to decide, do or supply, and every statutory or legal point I will not assume. Kept in one place and refreshed, not scattered across replies. Each row names the ledger ids behind it (`decisions-taken-2026-10-14.md` has what I decided myself). Written in plain English: you decide the money and do what only you can do; the legal and statutory points need a primary text, a practising CA or counsel, and **nothing is built on a guess**.

**At a glance:** section 1 is the one thing that unlocks the most; section 2 is money and the commitments only you can make (13 rows, each with my recommendation); section 3 is what only you can do; section 4 is the statutory and legal questions (20, each with what stays unbuilt meanwhile); section 5 is the wait-until-asked items the new goal probably needs; section 6 is two questions the goal raises.

**How many ledger items wait on you:** the ledger README's "Who must act" line counts them and is generated from the ledger itself. It is every item lettered B (you decide first) or C (only you or someone outside can do), plus the items lettered A that carry the `waits on owner` marker. Those marked items are the ones whose question is in section 4 below: S14 (POST-A-343), S15 (POST-A-348), S16 (POST-A-055), S17 (POST-A-059 and POST-A-064), S18 (POST-A-067), S19 (POST-A-114) and S20 (POST-A-063). Answering a question removes the marker and Claude builds the item.

## 1. The single most useful thing: let me read the primary texts

Today, 14 October 2026 at 13:41 IST, I tested ten government sites from this environment and every one was refused. That is why so many statutory figures in the product are graded `[S]` (read from a summary, not from the page) and why those questions are on your list below. If you allow these sites, I read the Acts, Rules and notifications myself and only then mark a figure verified. Legal *readings* (privacy law, consent, erasure, contracts) stay with counsel or a practising CA even then; what changes is that rates, thresholds, due dates, forms and portal rules stop waiting on a person.

**How:** open the environment's settings (the cloud environment menu in the session's title bar, then Edit), go to Network access, and either choose a broader level or add these hosts under Allowed domains, leaving the package-manager box ticked. Steps: https://code.claude.com/docs/en/cloud-environments#network-access

| Host | What it holds |
|---|---|
| `www.incometax.gov.in` | income-tax e-filing site: forms, schemas, notifications, e-verification |
| `www.gst.gov.in` | GST portal: advisories, forms, due dates, the portal's step order |
| `taxinformation.cbic.gov.in` | CBIC tax information: GST Acts, Rules, notifications, circulars |
| `www.cbic.gov.in` | CBIC: notifications and circulars |
| `indiacode.nic.in` | the Acts themselves (Income-tax, CGST, Companies, DPDP, Gratuity, Bonus) |
| `egazette.gov.in` | the Gazette: Rules and notifications as notified |
| `www.epfindia.gov.in` | EPFO: wage ceilings, ECR rules |
| `www.esic.gov.in` | ESIC: ESI ceilings, contribution rules |
| `www.mca.gov.in` | MCA: Companies Act forms and Schedule III |
| `www.meity.gov.in` | MeitY: the DPDP Act and Rules |
| `einvoice1.gst.gov.in` | the e-invoice portal: schema, sandbox, bulk-upload rules |
| `www.cert-in.org.in` | CERT-In: the incident-reporting directions |

The first ten were tested and refused; the last two are the ones I would add next. Read-only: nothing is sent to any of them. (Ledger: POST-B-047.)

## 2. Money: yours to decide, with my recommendation

None of these is decided by me. Prices are what the repository's own notes say, not re-checked today.

| # | What | My recommendation | Ledger |
|---|---|---|---|
| 1 | Paid always-on API host, and paid outgoing mail | Approve the smallest paid always-on plan and the cheapest paid mail tier before the demo. The free host sleeps and takes about 56 seconds to wake; sign-up and invite mail has already hit the shared limit. The plan note says about $7 a month for the smallest paid API plan (not re-checked); the mail price is unknown. Load-test before buying more memory. | D1, POST-B-058, POST-B-054, POST-B-067 |
| 2 | Supabase plan with daily backups, then point-in-time recovery, then an independent off-site copy | Keep at least the plan with daily backups now. Add point-in-time recovery and a nightly independent copy (India region) before any pilot brings real client data. A scratch project for a timed restore rehearsal costs a little. | D2, PRE-B-012, POST-B-057, POST-B-064 |
| 3 | Domain, one brand, and the sending domain | Pick one brand and one domain, buy it when ready, then a staged cutover (sign-in redirects and emailed links change). Everything else is built against placeholders. | D6, PRE-B-016, POST-B-053 |
| 4 | Paid AI terms: Gemini no-training terms, and Groq's retention in writing | Approve paid Gemini (usage-based, cheap) and read Groq's retention terms in writing. Two builds wait on this: the assistant's read-only tools (POST-B-082) and batch invoice upload (POST-B-083). I build the per-firm AI off switch regardless. | D5, PRE-B-013, POST-B-082, POST-B-083 |
| 5 | A staging copy (second database project and second API service) | Approve before the first pilot with real data. Production has diverged from the migrations before, so a rehearsal copy is worth having. | D12, POST-B-049 |
| 6 | A paid reviewer on retainer for the money code | At least one, before the first paying pilot, listed as a code owner for the money code. | D12, POST-B-056 |
| 7 | An independent penetration test | Yes, after my security batches land so the report is not a list of known holes; three quotes; scope it so it can also serve any due-diligence certificate the registrations ask for. | D13, POST-B-007 |
| 8 | Indian technology-law counsel | Name the legal entity and two contact addresses first (section 3), then two counsel quotes. Scope: privacy notice, terms, processor agreement, breach procedure, the privacy-law questions in section 4. Expect 2 to 4 weeks for documents. | D3, POST-B-259, POST-B-266, POST-B-051, POST-B-262 |
| 9 | Payment gateway (Razorpay merchant KYC) | Only when you want online payment live. No real payment at the first demo; the screens say 'coming soon' until the gateway is live. | POST-B-195, CKPT-4, CKPT-5 |
| 10 | Pricing, plans and the founding price | Invoice the first firms by hand. Set the founding price with the pilot firms rather than publishing a list price; state the GST treatment and annual amounts when you do publish. | POST-B-273, POST-B-265, D10 |
| 11 | India-hosted static-IP outbound hop for the tax-portal registrations | Decide when you start the registrations, not before: it is a deployment line item with a long tail that gates two registrations. | POST-B-249, POST-B-062 |
| 12 | A load test, a bigger database size, memory for two API workers | Only if pilot load shows a need, after the paid-plan decision. | POST-B-068, POST-B-067 |
| 13 | What each plan promises: the user and client limits on the pricing page (1 user and 25 clients, 5 users and 150 clients, unlimited), the 'Priority support' line, the phone-support tier on the support page and the 'dedicated onboarding specialist' for Practice and Firm | Drop every one you cannot staff today; keep a line only when a named person will honour it. Nothing in the product enforces a plan limit, so a number on the page is a promise made by you, not by the software. The free trial, the 'no card' line and the annual saving are already gone from the site. | POST-B-264 |

## 3. Only you can do these

| # | What | Why it is yours | Ledger |
|---|---|---|---|
| 1 | Look at the dashboards and tell me what they say: Supabase plan, backups, password and sign-in limits; the Supabase sign-in settings, and in particular whether a new account must confirm its e-mail address before it can sign in (a client's portal invitation is accepted by signing in with the invited address, so I need to know a stranger cannot sign up with someone else's address unconfirmed); whether Sentry error reporting is on in the Render dashboard; which tier the Gemini and Groq keys are on and what 'Check now' says on the AI status screen for each; whether the mail sender is verified. | They are your accounts; I cannot see them. | PRE-B-012, POST-B-020, POST-B-052, PRE-B-013, PRE-B-014, PRE-B-016 |
| 2 | Name: the legal entity that contracts with firms and its address; a grievance contact; a security contact address; two people who get alerts when the system is down. | Only you can name them. Until then the footer links and the security page stay unbuilt. | D3, POST-B-267, POST-B-018, POST-B-050 |
| 3 | The demo: who attends, two or three real team accounts with client assignments, one active portal contact, which client's ledger is safe to show, and the live rehearsal sessions (seed the demo firm and walk it; sign-up as a stranger; the core scenarios; the portals; checking six outputs against one consenting client's filed figures; printing the outgoing documents). | People and one real client's consent; the sessions need you present. | CKPT-7, PRE-B-001, PRE-B-003, PRE-B-006, PRE-B-007, PRE-B-008, PRE-B-009, PRE-B-010, PRE-B-011, POST-B-001 |
| 4 | The pilots: three firms running 15 to 60 SME clients on Tally, a practising CA adviser who runs weekly calls, the founding price, and written consent from each client whose books are used in parallel. No real client data until the processor agreement and a restore drill exist. | Only you can recruit them and obtain consent. | D10, POST-B-262, POST-C-002 |
| 5 | The registrations (last stage of the build): the free software-developer registration and the free e-invoice sandbox are self-service and could be started after the demo. The production routes (ERI, GSP, NIC) are months of commercial work. My recommendation: start the free ones after the demo and decide the others with at least three written quotes; applying early costs lead time, not code, but may cost money. | They are in your name and need KYC and quotes. | D7, POST-B-247, POST-B-248, POST-B-251, POST-B-112, POST-B-113, POST-B-114, POST-B-122 |
| 6 | The website move from Cloudflare Pages to Cloudflare Workers (removes a hidden 100-rule limit that has already broken page reloads once). | It is your Cloudflare account and it changes how the live site is served. I verify every route on a preview first; then you move the domain. | D15, POST-B-055 |
| 7 | Documents only you can supply: a real Tally export for the voucher import; a real e-invoice response file for the bulk import; Protean's current specification for the TDS statement file; the Income-tax Act 2025 return forms and schemas once published (the annual hand-off). | They come from outside this environment. | POST-B-175, POST-B-298, POST-B-117, POST-B-132, POST-B-133, POST-B-119 |
| 8 | GitHub settings: a dedicated least-privilege login for the automated smoke test (and its secret); optionally you as required approver for production migrations (see section 6). | Settings and secrets in your GitHub account. | POST-B-022, POST-B-063 |
| 9 | Optional: send the drafted purpose-code enquiry to Sahamati/ReBIT. It is free and is the primary source for the bank-feed question in section 4. | An outward message in your name. | POST-B-243, POST-B-245 |
| 10 | One of two things for the spreadsheet reader that imports user files: allow this environment to reach `cdn.sheetjs.com` (so the fixed build of the reader can be fetched and checked), or tell me to move the importer to another library. The old reader carries two known advisories (prototype pollution and a slow-pattern attack) and the fix is only published there. Separate from this, moving the web app from Next 14 to 15 is a major upgrade I can do alone, and overlaps the Dependabot Next 16 question. | It is your network setting, or a choice of library for a screen that reads your clients' uploads. | POST-A-174 |

## 4. Statutory and legal points I will not assume

Each row: the exact question, the document or section needed, who can supply it, and what stays unbuilt meanwhile. A figure the ledger quotes below is quoted as the ledger has it (a summary, graded `[S]`), not as something I have read.

### S1. Privacy law: lawful basis and consent

- **Question:** Which lawful basis covers sending a client's documents to AI providers and any cross-client benchmarking? Is relying on the narrow ground the ledger calls s.7(a) enough, or must a consent path (free, specific, informed, withdrawable) be built? Does a plain sentence in the privacy summary that names typed into the assistant are sent as typed satisfy the notice duty?
- **Needed:** The DPDP Act 2023 and the DPDP Rules 2025 as notified; the AI providers' written terms.
- **Who can supply it:** Counsel (a legal reading).
- **Stays unbuilt meanwhile:** Any benchmarking or training on client data (none exists today); the consent path; payroll pre-filling an employee's own return; consent and purpose tagging of records.
- **Ledger:** POST-B-081, POST-B-084, POST-B-263, POST-B-157, POST-B-316

### S2. Privacy law: rights requests, breach notices, logs

- **Question:** Exactly what must be built, and by when, for a person's request about their data, a breach notice to the regulator and to people, reporting to CERT-In, the grievance contact, how long access logs are kept, and where security logs are kept and for how long. The ledger quotes 'Rule 14', 'Rule 7', '72 hours', 'Rule 6', '12 months' and '180 days in India'; none was read from the text.
- **Needed:** The DPDP Rules 2025 as notified; CERT-In's directions of 28 April 2022.
- **Who can supply it:** Counsel.
- **Stays unbuilt meanwhile:** Any statutory clock, deadline or purge job inside the registers and logs. I build the request register, breach register, grievance page and access log with none of those inside them, so nothing is deleted and no deadline is asserted. Publishing the retention position.
- **Ledger:** POST-B-008, POST-B-009, POST-B-261, POST-B-271, POST-B-051, POST-B-061

### S3. Erasure and retention

- **Question:** Once statutory retention has lapsed, what does erasure require? How long may profile history, soft-deleted documents and vouchers be kept, and does scrubbing a record in place satisfy it (the ledger names s.8(7))?
- **Needed:** DPDP Act s.8(7) and the Rules; Companies Act s.128(5); the Income-tax record-keeping periods.
- **Who can supply it:** Counsel with a practising CA.
- **Stays unbuilt meanwhile:** Scrub-in-place erasure; any retention job (nothing is deleted meanwhile, which is how it behaves today); the retention period on soft-deleted documents.
- **Also asked here (28 October 2026):** must the log of statement emails sent to a customer be KEPT after that customer is permanently deleted, or may it go with the customer? Today it goes with the customer, as it always did; the books it was drawn from (invoices, receipts, notes) already stop the delete. Needed: the same texts as above, read for a mail log.
- **Ledger:** POST-B-296, POST-B-313, POST-B-017, POST-B-271

### S4. Notice, terms and processor agreement

- **Question:** The wording of the privacy notice, terms of service and processor agreement, the sub-processor list, and recording acceptance of the terms at sign-up and invite.
- **Needed:** Counsel's drafts; the contracting entity (D3).
- **Who can supply it:** Counsel.
- **Stays unbuilt meanwhile:** Publishing the notice and terms; recording acceptance. I draft the factual data-flow statement (what leaves India and to which provider) meanwhile.
- **Ledger:** POST-B-259, POST-B-266, POST-B-270, D3

### S5. Client lock: what a locked year must refuse

- **Question:** For a client whose year is locked, which payments, return saves, TDS entries and reversals must be refused, and how does each interact with an already-filed return?
- **Needed:** A practising CA's view, case by case.
- **Who can supply it:** A practising CA.
- **Stays unbuilt meanwhile:** Cases (a) to (c) of the lock list; case (d) stays as it is.
- **Ledger:** POST-B-170

### S6. Income tax and TDS

- **Question:** (a) The 30-day e-verification clock after filing (the ledger cites Notification 5/2022 DGIT(Systems)) and whether it carries over under the 2025 Act. (b) How Form 16/130 reaches employees (the TRACES route) and the 2025-Act form numbering. (c) The bad-debt deduction (the ledger recalls s.36(1)(vii) with s.36(2)) and partnership remuneration and interest limits (the ledger cites s.40(b)). (d) The wording of the cash-basis warning for companies and tax-audit clients (Companies Act s.128; IT Act s.145 and s.44AB/44AA). (e) Whether the registry's foreign-company rate matches the Finance Act for each year. (f) The statutory sentences inside the six starter workflows (stale TDS form numbers, the s.208 threshold wording, the GSTR-9 tables sentence). (g) The transfer-pricing documentation test (the threshold and what it is measured on, the international and specified-domestic tests, and the Income-tax Act 2025 provisions that replace s.92 to s.92F); the related-party loans screen's Rs 1 crore flag was removed until it is supplied. (h) The block rates and which block each kind of asset belongs to (Appendix I to the Income-tax Rules, for the years the demo and a pilot firm will use), so the section 32 depreciation allowance can be computed and a company's, LLP's or firm's book-to-tax bridge can complete.
- **Needed:** The notifications and sections named; the Finance Acts; the Income-tax Act 2025 and its Rules; TRACES documentation. Appendix I to the Income-tax Rules as notified for the year, and the section 32 provisos.
- **Who can supply it:** Claude once the government sites are reachable (section 1) for texts; a practising CA for the readings in (b), (c) and (f).
- **Stays unbuilt meanwhile:** The e-verification clock and queue; Form 16 delivery; any deduction or limit calculation (the write-off and partnership builds contain none); any transfer-pricing flag or count; the cash-basis warning; the starter workflows are not installed until a practising CA has read them. The section 32 block register has no rates seeded, so the book-to-tax bridge of a client with fixed assets stays incomplete and the demo's companies, LLP and firm have no computed return.
- **Ledger:** POST-B-120, D14, POST-B-147, POST-B-172, POST-B-173, POST-B-187, CKPT-9, POST-C-204, POST-C-205 (POST-B-126, the foreign-company rate, was decided on 14 October 2026 and is no longer in the ledger; see `decisions-taken-2026-10-14.md`)

### S7. TDS statement file and payment codes

- **Question:** Protean's current specification of the statement file (the FVU upload) and the complete table of section-393 payment codes; and which extra facts to record on a supplier or bill to pick the code.
- **Needed:** Protean's current file-format specification (the owner downloads it); the section 393 table.
- **Who can supply it:** The owner downloads the primary document; a practising CA confirms the facts.
- **Stays unbuilt meanwhile:** The statement-file writer; payment codes outside the confirmed subset. The extra facts can be recorded (no codes are guessed).
- **Ledger:** POST-B-132, POST-B-133

### S8. GST rules and dates

- **Question:** The three-year bar on filing a late return and how it is measured; the due dates of CMP-08, GSTR-4 and GSTR-9C; the GSTR-1A form and the advisory the ledger calls 606; the GSTR-9 primary documents; the readings of Rules 42 and 43 and the open readings of Rules 37 and 37A; the notification reference behind each HSN/SAC rate; the portal's current step order for GSTR-1 and GSTR-3B (for the handoff screen).
- **Needed:** CGST Act and Rules as amended; the notifications and advisories named; the GST portal's help pages.
- **Who can supply it:** Claude once the government sites are reachable; a practising CA for the Rule 42/43/37/37A readings.
- **Stays unbuilt meanwhile:** The filing-bar tracker; the three due dates in the calendar; GSTR-1A; GSTR-9 tables 10-14, 15, 16 and 18; the one-click reversal; the Rule 42 working; the GST handoff screen. The HSN master ships as a check that demands a notification reference on every row, with no rows.
- **Ledger:** POST-B-095, POST-B-099, POST-B-097, POST-B-098, POST-B-093, POST-B-111, POST-B-101, POST-B-107, POST-B-253

### S9. Payroll statutory figures

- **Question:** The ESI wage ceiling for disabled employees (the ledger says Rs 25,000, graded `[S]`); how ESI Rule 50 treats an earlier month that is still a draft; each state's professional-tax slabs, return form and due date; each state's Labour Welfare Fund table; the minimum-wage figure the Bonus Act forms need; the gratuity formula for a year-end provision; the PF-on-actual-wages legal position; s.17(3) profits in lieu of salary; the valuation of a car used wholly privately.
- **Needed:** The ESI Act and notification; the Code on Social Security; each state's notifications; the Payment of Bonus and Gratuity Acts.
- **Who can supply it:** Claude once the government sites are reachable for the Acts; a practising CA for Rule 50 and the PF position; the owner or a CA for state notifications.
- **Stays unbuilt meanwhile:** The disability flag and ceiling; the continuity change; every state's table beyond the four held; Bonus Act Forms C and D; the gratuity provision; the other perquisite and salary items. The professional-tax due-date record (each firm types its state's date) is built with no figures inside.
- **Ledger:** POST-B-145, POST-B-146, POST-B-151, POST-B-152, POST-B-159, POST-B-162, POST-B-163, POST-B-161, POST-B-166, POST-B-169

### S10. Account Aggregator bank feeds

- **Question:** Does an Account Aggregator purpose code exist, or can one be added, that covers an agent keeping a client's books? I did not make 'do not use the Account Aggregator' permanent, because bank feeds are in the last stage of the goal.
- **Needed:** The ReBIT/Sahamati purpose-code list; the drafted enquiry.
- **Who can supply it:** The owner sends the enquiry; counsel reads the answer.
- **Stays unbuilt meanwhile:** Any Account Aggregator consent flow. Statement upload remains the base case and never goes away.
- **Ledger:** POST-B-245, POST-B-243, POST-B-228

### S11. The ITR e-verification and the 2025-Act forms

- **Question:** Covered by S6(a) and the annual hand-off in section 3; listed here so the 2025-Act return forms are not forgotten.
- **Needed:** Forms and schemas under the Income-tax Act 2025 once published.
- **Who can supply it:** The owner downloads them.
- **Stays unbuilt meanwhile:** The 2025-Act fork of the return forms.
- **Ledger:** POST-B-119

### S12. Companies Act annual filings (MCA)

- **Question:** Which companies file MGT-7A instead of MGT-7, and does a filed MGT-7A discharge the annual-return obligation (60 days after the AGM) that the calendar generates for every company?
- **Needed:** Rule 11 of the Companies (Management and Administration) Rules 2014 as amended, and the MGT-7A instruction kit; or a practising CA's or company secretary's answer for an OPC and a small company.
- **Who can supply it:** Claude once the government sites are reachable (section 1) for the texts; a practising CA or company secretary for the reading.
- **Stays unbuilt meanwhile:** Any matching of MGT-7A to an obligation. The MCA workspace says an MGT-7A is matched to none, and the MGT-7 obligation stays open until it is marked filed from Compliance.
- **Ledger:** POST-C-209

### S13. A deposit against a demand (challan 281, minor head 400)

- **Question:** Can a challan paid against a demand raised on regular assessment (minor head 400) ever settle tax a deductor deducted at source, for the monthly deposit rule, the interest and default sections and the challan details of the quarterly statement, or is it always a separate liability from the tax deducted?
- **Needed:** The Income-tax Act and Rules on a deposit against a demand, and the ITNS 281 instructions; or a practising CA's answer.
- **Who can supply it:** Claude once the government sites are reachable (section 1) for the texts; a practising CA for the reading.
- **Stays unbuilt meanwhile:** Any rule that treats minor head 400 differently from 200. Today every reader counts a challan of either minor head as a deposit of the quarter's deductions, which can understate a default; the deposit position carries a warning saying so and the Challans tab shows each challan's minor head, so a demand payment can be told apart.
- **Ledger:** POST-C-210

### S14. ITR-3, ITR-5 and ITR-6 Part A: which box each line of the books answers

- **Question:** For each line of the year-end statements (the Schedule III balance sheet and profit and loss account), which box of Part A of ITR-3, ITR-5 and ITR-6 does it belong in? In particular: where a debit balance in reserves goes in the funds-sourced-and-applied form (ITR-3 and ITR-5); which group other long-term liabilities, long-term provisions and other non-current assets belong in on those two forms; whether finance costs as Schedule III defines them belong wholly in the interest box; and which column of Schedule DPM each of the three additional-depreciation columns is, because ITR-5 and ITR-6 name them differently from ITR-3 and in a different order.
- **Needed:** The instructions to ITR-3, ITR-5 and ITR-6 for AY 2026-27, and the printed Schedules DPM, DOA and DEP.
- **Who can supply it:** Claude once the government sites are reachable (section 1) for the instructions, which would let the table be read against the primary text and not only a CA's memory of it; a practising CA for the reading either way. Confirmed on 27-10-2026: the environment's network policy refuses the connection to incometax.gov.in (a 403 on the tunnel), so nothing of this can be read from here until the setting in section 1 is changed.
- **Stays unbuilt meanwhile:** The flag that says the table is confirmed (every answer says it is not); any use of Part A by the ITR JSON writer; the heads of the profit and loss account and the trading account (POST-A-343). Part A is offered as a keying aid, with the split of every group the books keep whole left to the CA, and the figures for the three renamed columns shown on the row and written into no box.
- **Ledger:** POST-C-211, POST-A-343, POST-B-342

### S15. Cash paid for an intangible asset: operating or investing in the cash-flow statement?

- **Question:** Under AS 3, are cash paid to acquire an intangible asset (software, a licence, goodwill) and cash received on selling one investing cash flows, and is capital work in progress read the same way? The product shows both as operating today.
- **Needed:** The text of AS 3 on investing activities, or a practising CA's answer.
- **Who can supply it:** Claude once the government sites are reachable (section 1) for the text; a practising CA for the reading.
- **Stays unbuilt meanwhile:** The change to the cash-flow classifier in the Python builder and the SQL function (POST-A-348). The new accumulated-amortisation ledger is classified to match the shared depreciation ledger, so it does not worsen the statement.
- **Ledger:** POST-C-212, POST-A-348

### S16. GST "turnover in the State": does it include a supply the recipient pays the tax on?

- **Question:** For the Rule 43 turnover (F) that decides how much input credit on capital goods is reversed, is "turnover in the State" in the CGST Act the value of ALL taxable supplies except INWARD supplies on which the recipient pays tax under reverse charge, so that a goods transport agency's or an advocate's own OUTWARD supplies (tax paid by the recipient) belong in it? The code already says so in a warning beside the answer, but its figure leaves those supplies out; the error runs in the safe direction (credit reversed is larger than it should be).
- **Needed:** CGST Act s.2(112) and Rule 43 as in force for the period.
- **Who can supply it:** Claude once the government sites are reachable (section 1) for the text; a practising CA for the reading.
- **Stays unbuilt meanwhile:** Adding outward reverse-charge supplies to F. The answer keeps naming the amount it left out.
- **Ledger:** POST-A-055

### S17. GSTR-3B Table 5 and Table 4(D)(2): which facts fill them

- **Question:** (a) Table 5 (exempt, nil-rated and non-GST inward supplies): which class of inward supply goes in the portal's two rows (the one headed for composition-scheme, exempt and nil-rated supplies, and the non-GST one), and is the split inter-state or intra-state by the supplier's state against the recipient's? (b) Table 4(D)(2) (ineligible credit under s.16(4) and the place-of-supply rules): which facts about a purchase must be recorded to derive it, and how is a bill outside the s.16(4) time limit told from one inside?
- **Needed:** The GSTR-3B form, its instructions and the GSTN JSON schema for the period; CGST Act s.16(4) and s.17(5) in force; the circular on Table 4 (170/02/2022-GST).
- **Who can supply it:** Claude once the government sites are reachable (section 1) for the texts; a practising CA for the reading of the rows.
- **Stays unbuilt meanwhile:** A classification field on purchase bills for Table 5 and the per-bill s.16(4) facts for 4(D)(2). Both rows stay nil and are named to the CA as rows this product cannot derive.
- **Ledger:** POST-A-059, POST-A-064

### S18. E-invoice: does the 30-day reporting limit reach credit and debit notes?

- **Question:** Does the IRP's 30-day limit on reporting an invoice (for a taxpayer with turnover of Rs 10 crore and over, from 01-04-2025) also apply to credit and debit notes, and from when? The ledger's source is a research summary, not the notification.
- **Needed:** The notification or the IRP's advisory that sets the limit, and the e-invoice schema's treatment of document types CRN and DBN.
- **Who can supply it:** Claude once the government sites are reachable (section 1); a practising CA for the reading.
- **Stays unbuilt meanwhile:** Extending the missing-IRN list to notes (it lists invoices only and says notes are not covered).
- **Ledger:** POST-A-067

### S19. Section 32(1)(iia): the second half of additional depreciation

- **Question:** For an asset put to use for fewer than 180 days in the year it was acquired, the third proviso to s.32(1)(iia) is read as allowing the other half of the additional depreciation in the FOLLOWING year. Is that the reading, and does the 20% rate and the whole clause stand as the code holds them? The module marks the rate and the reading as unconfirmed.
- **Needed:** Income-tax Act 1961 s.32(1)(iia) and its provisos as applicable to the year, and the position under the 2025 Act.
- **Who can supply it:** Claude once the government sites are reachable (section 1) for the text; a practising CA for the reading.
- **Stays unbuilt meanwhile:** The carry-forward of the second half to the next year. The answer keeps naming it as a gap.
- **Ledger:** POST-A-114

### S20. GSTR-9 Table 8A: what the portal fills and what the books must supply

- **Question:** Table 8A (input credit as per the auto-populated statements) is derived from the GSTR-2B statements for the year. For which years is 8A filled from GSTR-2B and for which from GSTR-2A, and may the product store one total per month from the 2B reconciliation to fill it?
- **Needed:** The GSTR-9 form and instructions for each year in the correction window; the notifications that moved 8A from 2A to 2B.
- **Who can supply it:** Claude once the government sites are reachable (section 1); a practising CA for the reading.
- **Stays unbuilt meanwhile:** The stored per-month 2B totals and the derived 8A. The return names 8A as a figure the product cannot see.
- **Ledger:** POST-A-063

### S21. A revised and an updated return: how does each one's set-off of a brought-forward loss sit beside the return it follows?

- **Question:** (a) A revised return under section 139(5): does the brought-forward loss it sets off REPLACE what the original return set off for that year, so a loss record should show only the revised return's use? The product assumes so (it is how the code already treats a revised return, as re-declaring a year already declared) and has not read it from the Act. (b) An UPDATED return under section 139(8A): does its set-off replace the return it updates, or add to it, and does the proviso to sub-section (8A), which limits what an updated return may change, limit what it can do with a loss that was carried forward? The product writes a filed return's use of a loss back to the loss record; for an original it adds the use, for a revised return it replaces the same year's earlier use, and for an updated return it writes nothing and says so. The computation also offers a year's earlier use back whenever that year is computed again, which is the same assumption for any kind of return.
- **Needed:** Income-tax Act 1961 section 139(5) and section 139(8A) with its provisos, and sections 72(1), 74 and 80 as they apply to a loss carried into a revised or an updated return; for tax years from 2026-27, the corresponding sections of the Income-tax Act 2025.
- **Who can supply it:** Claude once the government sites are reachable (section 1) for the text; a practising CA for the reading.
- **Stays unbuilt meanwhile:** Writing an updated return's use back to the loss records, and teaching the computation which kind of return it is for. The answer says no loss record was changed. The revised-return replacement stays built, graded [S], and is named here so you can overrule it.
- **Ledger:** POST-A-366

## 5. Wait-until-asked items the goal probably needs

Because the goal is to replace every platform, some items I decided to leave until a client asks will probably be needed. They stay parked, and you do not have to answer; this is the list to pull from. Say the word and I move any of them to the front. My default: build them in the order a pilot firm or the demo audience asks, after the base is solid.

| Id | What |
|---|---|
| POST-B-180 | Decide bill-wise references on journal lines (Tally-style) |
| POST-B-182 | Decide cost-centre extensions: balance sheet, hierarchy, sharing, budgets |
| POST-B-185 | Decide Ind AS (Division II) ageing variant of Schedule III receivables note |
| POST-B-189 | Decide whether chart of accounts needs a real multi-level hierarchy |
| POST-B-191 | Decide whether to build multi-currency Capability B (translation, consolidation) |
| POST-B-256 | Decide whether to model XBRL applicability and taxonomy choice |
| POST-B-282 | Decide the interface-language posture: D8 extraction or regional languages |
| POST-B-102 | Decide whether to build ISD (GSTR-6, Rule 39) and GSTR-7 returns |
| POST-B-127 | Decide whether to build the named house-property and Schedule S gaps |
| POST-B-217 | Decide whether manufacturing (bill of materials, production voucher) is in scope |
| POST-B-338 | Decide whether PracticeSync prepares an LLP's Form 11 and Form 8 |
| POST-B-153 | Decide on pay-head formulas, bulk employee invites and portal Form 12BB |
| POST-B-154 | Decide the scope of leave management: full workflow or typed balances |
| POST-B-134 | Decide whether the product should collect TCS (s.206C) and file Form 27EQ/27D |
| POST-B-135 | Decide whether to build statements for clients whose books are elsewhere |
| POST-B-142 | Decide whether to model s.194R, s.194O and s.194S |
| POST-B-144 | Decide whether to produce Forms 26QB, 26QC and 26QD |
| POST-B-093 | Build Rule 42 (inputs and input services) ITC reversal working |
| POST-B-094 | Mark supplies made through an e-commerce operator for GSTR-3B 3.1.1 |

## 6. Two questions the new goal raises

1. **The marketing site is publicly reachable today** (at `practicesync.pages.dev`) while the product is not to be released to the public until it is fully complete. Keep it as it is, put it behind a password, or take it down? **My recommendation: keep it** as long as every statement on it is true (a guard test holds it to the code), and add nothing promotional until the product has earned it; revisit when the pilots start.
2. **Do you want to be the required approver for production migrations?** (POST-B-063.) A migration merged to `main` applies to production today with no human in between. Adding you as approver is safer but stops my migrations until you click each time. **My recommendation: not yet** (about 7 clients, no pilot data); switch it on the day the first pilot brings real client data.
