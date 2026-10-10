PracticeSync — an AI-first platform that aims to become the one platform Indian chartered accountants and their clients run their whole practice on. It is built to be so complete, and so much better than every tool on the market, that practices replace those tools with it, Tally included. Practice management, accounting, GST, TDS, income tax, payroll, banking and compliance, all on one ledger.

Naming: the product is **PracticeSync**. The repo, the Supabase project, log prefixes
(`caflow.*`), some seed data and a few mock URLs still say `caflow` / `CAflow AI`. That
is known cosmetic legacy — do not "tidy" it opportunistically. It appears in import
paths, env keys and migration history, and a careless rename breaks all three.

**What is still open lives in `docs/open-items/README.md`** (one line per item,
before or after the demo, by who must act). Read it for any "what is left"
question; the audit documents that used to answer it were deleted on 8 October
2026 (see the paragraph near the end of this file).

## Goal and context

- **What PracticeSync is.** An AI-first platform for Indian chartered accountants and the businesses they serve. The goal
  is to be so complete and so much better than every platform in the Indian market that a practice replaces those tools
  with it. That means accounting software such as Tally, practice-management tools, GST, TDS and income-tax tools,
  payroll, and the spreadsheets between them. The aim is to become the standard platform of the Indian market by being
  better, not by forcing anyone. It is well past MVP (see Scope).
- **Where it stands today.** The goal is the direction, not yet a fact about the product. Today it runs beside Tally,
  the Tally importer writes customer and vendor masters only, and the production footprint is about 7 clients, with no
  paying firm and no reference firm yet (the strategy note of 30 September 2026 in
  `docs/open-items/decisions-and-strategy.md`). It is **not released to the public and will not be until it is fully
  complete**. What the product says about itself follows what it does today, and moves up only as it earns each claim.
- **How it gets to market, in order.**
  1. Build and test now, until the base works smoothly.
  2. The demo to practising CAs, once the owner says it is ready.
  3. **Pilot firms.** After the demo the first firms get the software and run it **in parallel** with the tools they use
     today. They tell us what is not working and what to change. They are small CA firms with about 15 to 150 SME
     clients that keep their books in Tally today, starting in one city. They are told plainly that the filing
     walk-throughs are simulations and that they file on the portal themselves.
  4. The portal integrations are added last (see Filing).
  5. **Public release only when the product is fully complete**, which means after the full integrations. The aim then
     widens to larger firms and more cities.

  A CA moves a client's books only at a year boundary, so the move happens firm by firm and client by client.
- **The rare asset is being believed, and it is how the market is won.** A reputation for telling the truth is what the
  product has that a rival does not. Every public claim and every screen must be true. A screen says what it read, what
  it did not and what it will not do, and an unknown is never shown as a value. A wrong number, a false claim or a
  silent cost is the failure that matters most. Breadth and speed come second to being believed, because being believed
  is what lets the breadth be sold.
- **Filing is part of the goal, and it is the last stage of the build.** The best platform has to file as well as
  prepare, and the product is not complete until real filing works. Until then the product **prepares** and the CA files
  on the government portal and records it here. The filing walk-throughs are simulations: each shows how real filing will
  work, says on the screen that it is a simulation, and transmits and files nothing. The only genuine filing record is
  the one the CA makes after filing on the portal. When real filing arrives, nothing is ever auto-submitted: each return
  needs the CA's explicit confirmation. Real filing needs registrations (GSP, ERI, NIC) that are the owner's.
- **The next milestone.** Showing practising CAs the seeded demo firm on the live deployment, once the owner says it is
  ready. The pilot firms follow. The demo has no date, so everything is built now.
- **What the goal does and does not change.** It decides what gets built and in what order. It relaxes no rule in this
  file.
- **The owner.** A founder with chartered-accountant domain knowledge who does not read code, wants plain-English
  reports and decides the money; the standing instructions below say who decides what.
- **Where to look.** `docs/open-items/README.md` for what is left; `docs/architecture/` for the design set;
  `docs/design-record/` for the long per-area decision records (indexed below); `docs/compliance/` for what each
  statutory output computes and what gates its last mile.

## How to work on this repo: the owner's standing instructions

Set by the owner on 9 and 10 October 2026. They apply to every session and are not to be
asked for again. Where one of them differs from a default, this section wins.

- **Who decides what.** Claude decides every open question, using three tests in order: it is
  lawful and follows the rules in this file, it is safe for the data of a CA's clients, and it
  is best for the product. The owner decides **money** (a paid server tier or more memory, paid
  mail, the Supabase plan, backups or an off-site copy, a staging copy, a second reviewer, a
  penetration test, counsel fees, the domain, paid AI terms, the payment gateway, pricing,
  plans and subscriptions) and does whatever only the owner can do (dashboards, KYC, quotes,
  who attends the demo, pilot firms). Claude does not decide those: it collects them in one
  short list, each with a recommendation, and brings it to the owner.
- **Statutory and legal points are never assumed.** If a decision or a build depends on a rate,
  threshold, due date, section, form, notification, wage ceiling, interest period or filing
  rule, or on a legal reading (privacy law, consent, erasure, breach reporting, retention, a
  contract), and Claude has not confirmed it from a primary source it actually read, it does
  not pick a cautious default and does not build on it. It writes down the exact question, the
  document, section or figure it needs, who can supply it (the owner, a practising CA or
  counsel) and what stays unbuilt meanwhile, puts that on the owner's list, and carries on
  with work that does not depend on it. Nothing is marked verified unless the primary text was
  read; the `[S]` and `[P]` grades in this file record what was read and are not a licence to
  assume. A mechanism that holds no statutory figure of its own (an empty table the owner
  fills) is fine; if unsure whether even that embeds an assumption, ask first.
- **Before or after the demo.** The demo has no date, so everything is built now, in order of
  impact: security gaps, privacy-law deadlines, anything false on a screen and statutory
  correctness first, then the other recommended builds by impact, then the small tail. An item
  the ledger says should wait until a client asks for it stays unbuilt. Building stops only
  when the owner says the demo is final.
- **Deletions.** The owner allows deleting repository files, dead endpoints and dead tables
  wherever Claude judges it safe and it does not lower quality: confirm nothing reads it, keep
  it recoverable from git, tests green. Pushing tags and closing pull requests still need the
  owner's go-ahead.
- **Pull requests.** One theme per pull request: about ten hours-sized items, four days-sized
  items, one weeks- or months-sized item, or one rule of a mechanical sweep. At most three are
  open at once and they are merged one at a time, each only when both required checks are green
  and it is current with `main` (squash). Branch from `origin/main` and, after a merge, reset
  the work branch to `main`. Close an item's ledger line in the same commit as its work. Before
  each batch, confirm every item in it is still true against the code and close any that is
  already done or moot. A change that touches no backend or frontend file skips the heavy
  checks; a migration merged to `main` applies to production (see Migrations).
- **Sub-agents and workflows.** The default is to do the work directly. Sub-agents are for
  narrow, independent, read-only research, or an independent review of one specific diff: at
  most three at a time, each briefed with the goal, the files and what is already ruled out.
  There is no Workflow run and no fan-out over the whole ledger unless the owner asks for one by
  name, and never a draft, review and finalise pipeline per chunk of the ledger: a 160-agent run
  launched on 10 October 2026 was stopped within minutes because every agent re-reads code and
  this container ran two at a time, and it would have cost far more than the owner expected. If
  a task would need more than five agents, tell the owner the rough cost first and wait. Say
  plainly when credits look low.
- **Telling the owner.** Plain English, with no file paths or function names: the owner has
  chartered-accountant domain knowledge and does not read code. All times in IST. Report
  faithfully what was verified, what was not and what is waiting on whom. The owner's list
  (money, tasks only the owner can do, statutory and legal needs) is kept in one place and
  refreshed, not scattered across replies.
- **Pace and start.** Steady: one batch at a time, with the next prepared while the checks of
  the last run. Building starts on 15 October 2026 at 04:30 IST, after the owner's weekly
  credits refresh; the start is scheduled.

## Design record index

The long per-area design write-ups were moved out of this file on 10 October 2026 so every session loads less.
They are verbatim in `docs/design-record/`. **Before changing an area, open its record file** and read the entries
listed for it below; each headline is the rule in one line. Entries that stayed in this file are not listed.

### `docs/design-record/ai.md` (5 entries): AI providers, the model gateway, redaction, budgets and what a model may and may not do

- A MODEL MAY WORD A COMPUTED FACT AND MAY NOT ADD TO IT, AND A SCREEN THAT CANNOT COMPUTE A FIGURE SAYS SO
- EVERY MODEL CALL GOES THROUGH ONE DOOR PER PROVIDER, AND A READING IS A PROPOSAL, NOT A WRITE
- THE AI PATH IS PROVEN LIVE, OR IT SAYS IT IS UNVERIFIED
- A FIRM MAY CAP ITS OWN MONTHLY AI USE AND A PARTNER CAN READ WHAT IT USED, AND NOTHING IS A DEFAULT
- A SCREEN THAT SENDS A CA'S CONTENT TO A MODEL SAYS WHICH PROVIDER, AND THAT IT LEAVES INDIA, BEFORE THE CLICK

### `docs/design-record/annual-update-and-statutory-data.md` (3 entries): What changes every financial year and the statutory data a human must supply

- The pre-commencement branch takes its own figure, and that is not cosmetic
- what | where it is refused | why it cannot be derived |
- Depreciation — but read this, it changed

### `docs/design-record/banking-and-multicurrency.md` (5 entries): Bank entries, credit card accounts, matching rules, multi-currency and the AS 11 revaluation

- Bank entries (09) in one paragraph, because it is easy to rebuild the old thing by accident:
- MULTI-CURRENCY HAS THREE GATES AND TWO OF THEM ARE NOW WRITABLE
- THE AS 11 YEAR-END REVALUATION WAS BUILT, TESTED AND UNREACHABLE
- A COMPANY CREDIT CARD IS A BANK ACCOUNT, AND THE DOUBLE ENTRY NEEDED NO CHANGE
- A MATCHING RULE SAYS WHICH FIELD IT READS AND WHICH RULE WINS

### `docs/design-record/banking.md` (1 entries): Bank data: Account Aggregator position, bank entries, credit cards, matching rules

- Register as an FIU

### `docs/design-record/deployment-and-operations.md` (5 entries): Deployment, monitoring, request ids, service levels, runbooks and security headers

- A CHECK ASKS THE THING ITSELF, AND AN ALERT MUST BE ABLE TO MATCH WHAT IS SENT
- EVERY REQUEST HAS AN ID, AND ONE JSON LINE, AND THE LINE NEVER NAMES THE PATH THE CALLER TYPED
- A TARGET IS JUDGED OVER A MONTH AND FAILS NOTHING; A BUDGET FAILS ONE RUN
- THE INCIDENT RUNBOOK SAYS IT HAS NOT BEEN TESTED AND LEAVES THE FACTS ONLY A HUMAN HOLDS AS BLANKS
- THE TWO SITES AND THE API SEND SECURITY HEADERS, THE POLICY'S HOSTS ARE READ FROM THE BUILD AND NEVER WILDCARDED, AND EVERY ROUTE 

### `docs/design-record/documents-sales-purchase.md` (10 entries): Sales and purchase documents and cycles, templates, supplier master, ledger drill-through

- THE DEMO SEEDER HAS BEEN RUN OVER A REAL DATABASE, AND EVERY DEFECT IT EXPOSED IS A RULE NOW
- A TEMPLATE CHANGES THE LAYOUT AND NEVER THE PARTICULARS, AND THE PRACTICE'S TEMPLATE REACHES THE PRACTICE'S OWN DOCUMENT ONLY
- THE SALES CYCLE BEGINS BEFORE THE TAX INVOICE, AND ONLY ONE OF THE FOUR DOCUMENTS IS THE ACT'S
- AN IMPORT OF GOODS IS PAID FOR TWICE AND ONLY ONE OF THEM IS THE SUPPLIER'S
- A REVERSE-CHARGE PURCHASE OWES TWO DOCUMENTS AND THEY ARE NOT ONE RULE WITH TWO NAMES
- A JOURNAL'S SUPPORTING DOCUMENTS ARE A DRAFT-ONLY EDIT, AND THE SCREEN SAYS SO
- A LEDGER ROW NAMES THE DOCUMENT BEHIND IT, AND THREE FILES HAVE TO AGREE ABOUT WHAT THAT MEANS
- THE SUPPLIER MASTER IS `public.vendors`, AND `public.suppliers` IS RETIRED
- THE PURCHASE CYCLE BEGINS BEFORE THE BILL, AND THE GOODS RECEIPT IS A STATUTORY FACT
- A VENDOR PAYMENT RECORDS WHICH BILLS IT SETTLED IN TWO SHAPES, AND EVERY READER MUST KNOW BOTH

### `docs/design-record/engineering-and-ci.md` (4 entries): Tests, lint and coverage ratchets, CI, dependency lock, migrations and the schema-drift check

- THE BACKEND HAS A LINT RATCHET, A PROPERTY SUITE, ONE PAGER, ONE DOOR TO THE DATABASE CLIENT AND A COVERAGE FLOOR, AND EACH IS A R
- THE SMOKE WALK RUNS BY ITSELF, NIGHTLY AND ON DEMAND, AND IS NOT A CHECK ANYTHING WAITS ON
- EACH MIGRATION IS ONE TRANSACTION, AND A REMEMBERED FAILURE KEEPS THE PIPELINE RED
- THE SCHEMA-DRIFT CHECK HEALS ITSELF AND COVERS THE TABLES AND FUNCTIONS THE CODE CALLS

### `docs/design-record/filing-and-compliance.md` (2 entries): Filing to government portals, trackers and the period lock

- AND THE PRODUCT WORDS THAT POSITION ONCE
- THERE ARE TWO TRACKERS AND BOTH LOCK THE PERIOD

### `docs/design-record/fixed-assets-and-inventory.md` (11 entries): Fixed assets, capital work in progress, stock costing, ageing, godowns, batches and counts

- AN ASSET UNDER CONSTRUCTION IS NOT IN THE REGISTER, AND THAT IS THE FIX
- AN ASSET CATEGORY IS BOOKED TO A LEDGER BY ONE TABLE, AND THE CHART A FIRM GETS MUST HOLD EVERY LEDGER IT NAMES
- A FIXED-ASSET DISPOSAL IS A SUPPLY, AND CGST §18(6) CHARGES THE HIGHER OF TWO LIMBS
- HOW OLD THE STOCK IS, IS A QUESTION ABOUT THE UNITS AND NOT ABOUT THE ITEM
- AND WHAT THAT RECEIPT COSTS INCLUDES THE TAX NOBODY CAN RECLAIM
- WHAT ELSE THE GOODS COST TO GET HERE IS RECORDED AGAINST THE BILL, AND THE BASIS IS A POLICY THE STANDARD DOES NOT GIVE
- THE COST FORMULA IS A CLIENT POLICY, AND ONLY ONE FUNCTION FORKS ON IT
- THE SIGNIFICANT ACCOUNTING POLICIES NOTE STATES THE FORMULA THAT PRICED THE YEAR, READ FROM THE LEDGER'S OWN STAMPS
- STOCK HAS A PLACE AND A LOT, AND ONE OF THEM CHANGES WHICH RETURN A MOVEMENT IS IN
- AN ITEM IS STOCKED IN ONE UNIT, TRANSACTED IN ANOTHER, AND REORDERED AT A LEVEL SOMEBODY CHOSE
- A PHYSICAL STOCK COUNT IS ONE SESSION, AND THE VARIANCE IS A FACT ABOUT THE COUNT DATE

### `docs/design-record/frontend.md` (4 entries): Frontend rules: payload shapes, the browser's second data path, money input, loading and recurring screens

- A PAYLOAD IS NOT A LIST UNTIL SOMETHING HAS CHECKED, AND THE STATE TYPE HIDES IT
- A THIRD path existed and it was not a database at all: `localStorage`
- A RECURRING ANYTHING SHARES ONE CADENCE ENGINE
- A LOADING REGION SAYS WHEN THE SERVER IS SLOW, A SIGNED-IN TAB KEEPS IT AWAKE, AND THE WALK SCANS WHAT IT RENDERS FOR ACCESSIBILIT

### `docs/design-record/identifiers.md` (3 entries): Identifiers: GSTIN, UAN, IFSC, party identifiers in imports, the firm's own GSTIN, FY and AY labels, ITR forms

- A TALLY IMPORT IS A BULK IMPORT OF AN IDENTIFIER SOMEBODY TYPED, AND IT WITHHOLDS RATHER THAN REFUSES
- THE FIRM'S OWN GSTIN LIVES IN TWO COLUMNS AND ONLY ONE IS READ
- THE SEVEN ITR FORMS ARE `domain/income_tax/itr_json.ITR_FORMS`, derived from the `ITRForm` Literal the field mappings and the comm

### `docs/design-record/ledger-and-money.md` (5 entries): The general ledger, posting kernel, period locks, money columns, reports and interest/cheque/price-list features

- A VOUCHER'S LINES HAVE AN ORDER AND TWO FUNCTIONS RECORD IT
- THE LIVE REPORTS LEAVE AS A SERVER-MADE PDF OR EXCEL THAT IS THE SCREEN, AND A REPORT THAT DOES NOT FOOT IS NOT PRINTED
- INTEREST A CLIENT CHARGES ITS OWN CUSTOMER IS COMPUTED AND PREPARED AS A DRAFT, NEVER POSTED OR INVOICED ON ITS OWN
- A POST-DATED CHEQUE IS A MEMORANDUM UNTIL A DUE CHEQUE IS CONVERTED, AND CONVERSION IS AN ORDINARY RECEIPT OR VENDOR PAYMENT
- A PRICE LIST IS A PRE-FILL SOURCE FOR AN INVOICE LINE'S RATE AND NOTHING ELSE

### `docs/design-record/opening-balances-and-imports.md` (2 entries): Opening balances as documents and the bulk imports of a migrated client's books

- A MIGRATED CLIENT'S BOOKS COME OVER IN BULK, AND EVERY IMPORT SAYS WHAT IT DID NOT DO
- THE UPLOAD SCREENS WERE DRIVEN IN A BROWSER ONCE, AND AN EXCEL DATE CELL IS A SERIAL NUMBER

### `docs/design-record/payroll.md` (7 entries): Payroll: accrual, PF on actual wages, bonus, monthly review, declarations

- THE PAYROLL ACCRUAL HAS TWO DEBITS, AND THE EMPLOYER SHARE COMES OFF THE SLIPS
- THE STATUTORY BONUS IS AN ANNUAL DEBT AND THE PRODUCT COMPUTED IT ONLY FOR LEAVERS
- THE THREE QUESTIONS ASKED ON THE 3RD OF THE MONTH, AND THE ONE THAT MOVES MONEY REFUSES A DRAFT
- PF ON ACTUAL WAGES ABOVE THE CEILING IS AN ELECTION THE EMPLOYER RECORDS, ONE EMPLOYEE AT A TIME, AND THE PRODUCT NEITHER INFERS N
- PAYROLL LEDGER ACCOUNTS ARE STILL FOUND BY NAME, AND KEY-FIRST IN THE ACCRUAL ALONE WOULD BE WORSE THAN THE RENAME PROBLEM
- A DRAFT payroll run has deducted nothing
- A DECLARED DEDUCTION HAS A DOCUMENT BEHIND IT, NOT A SENTENCE ABOUT ONE

### `docs/design-record/reporting.md` (5 entries): Reporting: Schedule III captions, report performance, paging, exports

- The fixed-assets note is a MOVEMENT, and there is one of it
- PAGING IS NOT THE SAME AS BOUNDING, AND A RECONCILIATION NEEDED BOTH
- A read that IS a row set has its own rule, and it is one line: page it
- THE RULE IS ABOUT THE BROWSER TOO, and that is where it was still being broken
- AN OFFSET-PAGED READ NEEDS A UNIQUE TOTAL ORDERING, and the ordering a screen already had is usually not one

### `docs/design-record/screens-and-site.md` (14 entries): Screens that state what they read, double-click and keyboard rules, the public site's claims, dates and empty states

- AN ABSENT VALUE IS UNKNOWN, AND A GENUINE ZERO IS A READING
- A RETURN FOR ONE OF SEVERAL REGISTRATIONS SAYS ITS DOCUMENTS ARE NOT SPLIT
- A SCREEN'S WEIGHT, ITS FIRST TWO FIELDS AND ITS FOCUS ARE RULES OVER THE WHOLE TREE, AND THE DEMO FORM DOES NOT RETRY
- A SENTENCE ON THE PUBLIC SITE IS A CLAIM WITH A LEDGER ENTRY, A FIRM'S FIRST DAY IS A CHECKLIST THE DATA TICKS, AND FOUR PRACTICE-
- THE SCHEDULED-REPORT RULE IS ONE PURE MODULE, A SCHEDULE PREPARES AND A PERSON SENDS, AND AN AGEING REPORT IS NOT A POSITION AT A 
- ONLINE PAYMENT IS OFFERED ONLY WHERE A REAL GATEWAY IS SET UP, THE SERVER SAYS SO IN WORDS, AND THE BROWSER HOLDS NONE OF THEM
- THE PRACTICE'S OWN MAIL HAS ONE FIRM-WIDE SWITCH, IT IS OFF UNLESS SOMEBODY SAYS ON, AND THE SCREEN SAYS WHEN IT IS OFF
- THE FOOTER'S PRIVACY LINK OPENS A PLAIN SUMMARY, EVERY SENTENCE OF IT IS HELD, AND IT SAYS WHAT IT LEAVES OUT
- A BUTTON THAT WRITES IGNORES A SECOND CLICK, A LIST ROW IS OPERABLE FROM THE KEYBOARD, NOTHING ASKS WITH A BROWSER POP-UP, AND A L
- A SCREEN'S NAME IS ONE COMPONENT, A DATE IS ONE MODULE, AND AN EMPTY LIST SAYS WHAT TO DO NEXT TO WHOEVER IS LOOKING
- THE MONEY EDITORS HAVE A BROWSER DRIVE, NIGHTLY, AND IT FOUND WHAT EVERY SOURCE GUARD PASSED
- A DATE A PERSON TYPES IS READ BY ONE RULE AND TYPED INTO ONE FIELD, AND NO LOCK IS IN EITHER
- SEVEN DEMO-FACING STATEMENTS STOPPED OVERSTATING WHAT THE CODE KNOWS OR DOES
- A PRINTED SCREEN IS NOT CLIPPED, NOT BLANKED, AND NAMES ITS CLIENT

### `docs/design-record/tax-gst.md` (34 entries): GST: returns, e-invoice and e-way, ITC and the 2B reconciliation, late fees, HSN and UQC, registrations

- A CLIENT IS ONE LEGAL PERSON AND MAY HOLD SEVERAL GSTINs, and until migration 390 the return tables forbade it
- FOUR RETURNS A REGULAR REGISTRATION NEVER FILES NOW HAVE A BUILDER, AND THREE OF THEM CHECK WHAT A CA RECORDS RATHER THAN COMPUTIN
- A PLACE OF SUPPLY HAS FOUR SOURCES AND ONE RESOLVER
- WHAT KIND OF SUPPLY AN INVOICE IS HAS ONE AUTHORITY, AND THE E-INVOICE RECORD MAY NOT CONTRADICT IT
- WHICH SUPPLIES MUST CARRY AN IRN IS `domain/gst/irn_scope.py`, AND THE RULE HAS TWO INDEPENDENT LIMBS
- AND WHAT THE PORTAL WOULD ACCEPT IS A SECOND AUTHORITY, STRICTER THAN THE ACT
- A LINE SAYS GOODS OR SERVICES, THE CODE USUALLY ANSWERS, AND THE COLUMN IS THE OVERRIDE
- A NIL ON A GSTR-3B SAYS WHICH KIND OF NIL IT IS
- GSTR-3B TABLE 4(A) HAS FIVE ROWS, AN IMPORT OF SERVICES OWNS ONE OF THEM, AND TWO ARE STRUCTURALLY NIL
- A BANK LINE THE CA MARKED AS CARRYING GST IS A DOCUMENT, AND THE DOCUMENT IS THE TRANSACTION
- THE ANNUAL RETURN CONSOLIDATES THE YEAR'S OWN RETURNS, AND NOTHING ADDED THEM UP
- A RETURN PERIOD IS NOT ALWAYS A MONTH, AND THE QUARTER'S KEY WAS ALREADY CHOSEN
- THE INVOICE FURNISHING FACILITY IS ONE CALENDAR MONTH AT A TIME, FOR REGISTERED RECIPIENTS ONLY, AND STORES NOTHING
- GSTR-3B Table 3.1(a) carries GSTR-1 TABLE 11, and the ledger cannot
- GSTR-3B Table 6 — the set-off has FOUR steps, and the total is not the challan
- THE SET-OFF RUNS AGAINST THE LEDGER'S BALANCE, NOT JUST THIS RETURN'S 4(C)
- A RULE 37 REVERSAL CARRIES §50(1) INTEREST, AND THE CLOCK IS NO LONGER IN THE RULE
- RULE 37A IS THE SUPPLIER'S DEFAULT AND RULE 37 IS THE RECIPIENT'S; THEY SHARE A BOX AND NOTHING ELSE
- WHAT BEING LATE COSTS IS `domain/gst/late_filing.py`, and half of it is a REFUSAL
- COMPENSATION CESS HAS TWO LIMBS, ITS OWN LEDGERS, AND IS NEVER PART OF `total_gst_paise`
- A discount on the invoice reduces the value of supply; a discount after it does not, and the two are different sections
- A TAX INVOICE'S NUMBER IS A STATUTORY FIELD WITH FOUR LIMBS, and the product used to enforce two
- HOW MANY DIGITS OF HSN A RETURN MUST CARRY IS `domain/gst/hsn_digits`, AND THE TABLE THAT USED TO LIVE IN THE BUILDER WAS A HYBRID
- TABLE 13 DECLARES SERIAL RANGES, AND THE BUILDER EMITTED A COUNT WITH NO RANGE AT ALL
- A UNIT QUANTITY CODE IS A CODE, NOT A WORD, and the one module that knew which codes exist had ZERO IMPORTERS
- An e-way bill's validity is arithmetic on the distance, and the distance is a field nobody used to ask for
- A LIVE E-WAY BILL SAYS WHEN IT LAPSES, AND THAT IS NOT A COMPLIANCE ROW
- §16(2)(aa) IS ASKED OF EACH DOCUMENT, AND RULE 36(4) WAS APPLIED TO A PER-HEAD SUM
- RULE 43 IS BUILT AND RULE 42 IS NOT, and the missing input was never the arithmetic
- THE MAIN GSTR-1 BUILD CARRIES THE AMENDMENTS THE PERIOD OWES, AND THE DEDUPE IS WHAT MAKES DEFAULT-ON SAFE
- A GSTR-2B FILE SAYS WHICH MONTH IT IS FOR AND WHOSE IT IS, AND THE UPLOAD BELIEVES THE FILE
- A 2B FILE IS ROUTED BY THE GSTIN INSIDE IT, A PROBABLE MATCH IS ONLY EVER A SUGGESTION, A DRAFT BILL IS ADDRESSED BY KEY AND RATED
- THE GSTR-3B IS TIED OUT AGAINST THE GSTR-1 THAT WAS FILED, AND A NIL THERE SAYS WHICH KIND
- FORM GST ITC-04 IS DERIVED FROM THE JOB-WORK CHALLANS, GOODS COME BACK IN LOTS, AND THE PERIOD IS NOT CHOSEN

### `docs/design-record/tax-income-tax.md` (13 entries): Income tax: ITR kinds and engines, capital gains, tax audit and 3CD, losses, entity reliefs, section 43B(h)

- §115BAC DISAPPLIES CHAPTER XII-BA, and the AMT surcharge ladder is the ASSESSEE's own
- THE FOUR REINVESTMENT SECTIONS ARE NOT ONE RULE WITH FOUR NAMES
- FORM 3CD IS 44 CLAUSES, AND EIGHT OF THEM REUSE ENGINES THIS PRODUCT ALREADY HAD
- §140A IS PAID BEFORE THE RETURN IS FURNISHED, AND A SHORT CHALLAN LANDS FEE FIRST
- A RETURN OF INCOME HAS THREE KINDS, AND `itr_filings` HELD ONE
- The Finance (No. 2) Act 2024 forked capital gains on 23-07-2024, and it is the DATE OF TRANSFER that decides
- §43B(h) IS DERIVED FROM THE PURCHASE LEDGER, AND THE LIMIT IS FIFTEEN DAYS
- HOW LONG A CARRIED-FORWARD LOSS LIVES IS PER HEAD, AND ONE OF THEM IS NOT EIGHT YEARS
- WHETHER §44AB applies is `domain/income_tax/tax_audit.py`, and the NATURE OF THE ACTIVITY is an input, never inferred from the amo
- §115BAC(6) WAS MODELLED AND NOTHING COULD ASK IT
- A HUF, AN AOP AND A BOI ARE ASSESSEES, NOT INDIVIDUALS, AND THE ENGINE ASKS A TABLE WHO EACH RELIEF REACHES
- THE SECTION 234C PROVISO IS APPLIED, ON THE INCOME'S OWN TAX
- HOUSE PROPERTY AND SALARY ARE WORKINGS, KEPT AS INPUTS AND RECOMPUTED, AND THEY FEED A BOX ON THE CA'S CLICK

### `docs/design-record/tax-tds.md` (11 entries): TDS and TCS: sections and thresholds, the 2026 vocabulary fork, interest, 26AS

- From 01-04-2026 the whole TDS vocabulary changed, and `domain/tds/vocabulary.py` is the single place that knows it
- A CONFIRMED SUBSET OF THE S. 393 PAYMENT-CODE TABLE IS NOW HELD
- THE RPU/FVU FILE ITSELF IS NOT BUILT, AND THAT IS A DECISION, NOT A GAP LEFT OPEN BY ACCIDENT
- A TDS threshold is a TRIGGER, not a deductible allowance, and most of the §194 series aggregates over the year
- A FIRM PAYING ITS OWN PARTNER DEDUCTS UNDER §194T, AND A SECTION WITH NO RESIDENT LIMB IS A THIRD STATE
- §206C IS IN THE TDS REGISTRY AND A VENDOR MAY NEVER CARRY IT
- What being late costs is `domain/tds/interest.py`, and "month or part of a month" is NOT the same arithmetic there as in §234A
- §194I AND §194J EACH CHARGE TWO RATES, AND BOTH ARE NOW HELD
- A SECTION THE ENGINE CANNOT ANSWER FOR IS REFUSED WITH ITS OWN REASON, AND THE REASONS ARE NOT INTERCHANGEABLE
- The 26AS reconciliation is the same rule and had the same defect (TDS-21)
- NOT EVERY PART OF FORM 26AS IS A CREDIT, and the client-as-DEDUCTEE reconciliation used to sum all of them

### `docs/design-record/tenancy-and-security.md` (15 entries): Tenancy, per-person access, principals, RLS tests, uploads, PIN, sessions and storage

- EVERY QUERY ON A FIRM TABLE CARRIES ITS FIRM'S SCOPE OR IS NAMED ON A FROZEN LIST, THE TABLE SET IS THE SNAPSHOT'S, AND HOW LITTLE
- ACCESS IS DECIDED PER PERSON, AND A ROLE IS THE TEMPLATE IT FALLS BACK TO
- THERE ARE THREE PRINCIPALS AND ONLY ONE OF THEM IS STAFF
- AN EMPLOYEE HAS A PAYSLIP DOOR ON THEIR OWN PRINCIPAL, AND THE REACHABILITY CHECK NOW ASKS WHO THE CALLER IS
- PRODUCTION DEFAULTS THE TWO SAFETY SWITCHES ON, AND THE DEPLOYMENT CAN NOW SAY WHAT IT RESOLVED
- THE CALLER'S ADDRESS IS THE ONE OUR OWN PROXY WROTE, NOT THE FIRST `X-Forwarded-For` ENTRY THE CALLER TYPED
- AN UPLOADED FILE IS READ WITHIN A BOUND, RECOGNISED BY ITS BYTES AND NAMED BY US
- A DOCUMENT'S UPLOADER AND REVIEWER ARE ROWS OF `users`, NOT OF THE RETIRED `team_members`
- THE BROWSER SENTRY SETTINGS ARE ONE MODULE AND THERE IS NO REPLAY
- A SUSPENDED OR SIGNED-OUT MEMBER IS NOBODY TO THE DATABASE
- A STORED FILE OPENS ONLY FOR THE STAFF ASSIGNED TO ITS CLIENT
- `fx_rates` IS GLOBAL ON PURPOSE AND ITS WRITE POLICY NOW SAYS WHO
- THE YEAR-LOCK PIN IS A HASH IN A TABLE NOBODY SIGNED IN CAN READ, AND EVERY GUESS AT IT IS COUNTED
- ENGAGEMENT SIGN TOKENS ARE STILL STORED IN THE CLEAR, DELIBERATELY NOT FIXED YET
- EVERY ACTOR IS TRIED AGAINST EVERY TABLE THE BROWSER REACHES, AND THE ANSWER IS A REVIEWED FILE, SO A HOLE IS A RED CELL AND NOT S

### `docs/design-record/workflow-and-team.md` (3 entries): Workflow engine slices and the Team screen's permission notice

- MIGRATION 481 IS THE SCHEMA FOR BOTH WORKFLOW HALVES, AND NOTHING READS IT YET
- A SAVED WORKFLOW RUNS EVERY STEP IT WAS SAVED WITH, AND A PERSON WHO PRESSES RUN RUNS THAT WORKFLOW
- THE TEAM SCREEN SAYS WHAT A BLOCK REACHES, AND A GUARD KEEPS THE SENTENCE TRUE

## Repo layout

Three apps, not two:

- `apps/api` — FastAPI (Python 3.11). **All** business logic lives here.
- `apps/web` — Next.js 14, the product. Static export (`output: "export"` in
  `next.config.mjs`), deployed to Cloudflare Pages.
- `apps/marketing` — separate Next.js marketing site, its own Cloudflare Pages project.

## Tech stack

- Frontend: Next.js 14, TypeScript, Tailwind CSS, shadcn/ui primitives in
  `apps/web/components/ui/` (vendored source — there is no `components.json`, so the
  shadcn CLI will not work; add primitives by hand).
- Backend: FastAPI (Python 3.11)
- Database: Supabase (Postgres), project region ap-south-1 (Mumbai)
- Package manager: pnpm for frontend, pip for backend

### AI providers — every key is backend-only

`apps/web` builds as a static export, so it has no server and can read nothing but
`NEXT_PUBLIC_*` values, which are inlined into the browser bundle. An AI key in the
frontend environment is at best ignored and at worst published. All AI calls happen in
`apps/api`, with keys in `apps/api/.env` ONLY.

- **Groq** — chat/text features and PDF (text-only) invoice extraction. Needs
  `GROQ_API_KEY`. Default model `openai/gpt-oss-120b` (`groq_text.DEFAULT_TEXT_MODEL`
  is the authority), overridable via `GROQ_TEXT_MODEL`. The default was
  `llama-3.3-70b-versatile` until 29-09-2026, when Groq retired it for this account
  (a live `model_not_found` 404); this file kept naming the dead one for a day after.
- **Gemini** — image-based invoice extraction (photographed or scanned bills, and a
  PDF with no text layer — see below), in `routers/document_intelligence_v1.py`.
  Needs `GEMINI_API_KEY`. Default model `gemini-3.5-flash`, overridable via
  `GEMINI_VISION_MODEL`.

Why two providers: Groq's vision models returned a live 404 `model_not_found` on this
account; Gemini's free tier is multimodal-native and already provisioned. The PDF/text
path stayed on Groq and works fine. Treat the model names above as current defaults,
not as contracts — `gemini-2.5-flash` was retired by Google ahead of its announced
shutdown, and the code reads the env var precisely so the next retirement is a config
change. The code is the authority; keep this file in step with it.

**What reaches a provider, and what it may not** (ai-03, ai-09, ai-15, ai-17,
security_privacy-12/22 — the AI-safety sweep of 30-09-2026). Five rules, each with a
guard that states the rule rather than a spelling of it:

- **A tax identifier never leaves for an AI provider.** `domain/ai/redaction.py`
  replaces anything shaped like a PAN or a GSTIN (shape, not checksum — the GSTIN a CA
  pastes is the transposed one) with `[PAN]` / `[GSTIN]` at the ONE place a chat request
  is built (`groq_text.chat`, and the two modules that build their own:
  `routers/ai_copilot.py`, `financial_analysis_service.py`). The builders no longer ask
  for a name, PAN or GSTIN in the first place; the redactor is what stops the next
  builder that forgets. **It does NOT pseudonymise NAMES** and the reversible
  `Client A` / `Vendor 3` layer is unbuilt. **Document extraction is exempt by name**,
  not by silence: the supplier's GSTIN is printed on the invoice being read.
  `tests/test_no_model_call_site_sends_an_identifier.py` lists every sender to Groq and
  fails a new one. **The assistant's client brief carries NO NAME — the client is "this client" plus its
  entity type** (02-10-2026, the owner's decision, which ends the one place the two
  features disagreed: the firm-level copilot sends counts and never a name, and the
  brief used to open with the client's legal name). `build_client_brief(entity_type,
  hub_payload)` has no name parameter, so there is nothing to forget to leave out (the
  signature is asserted), `routers/assistant._client_brief` reads no name column (an
  AST check), and a behavioural test drives the real handler with a distinctively
  named client and reads every message handed to the model. ⚠️ **What a CA TYPES into
  the question or the conversation is sent as typed**: a client's name written there is
  not removed, because redaction covers a PAN or GSTIN shape and not a name, and the
  reversible `Client A` layer is still unbuilt. Nothing was found to send a name
  elsewhere: the firm copilot's context is counts, the client-level copilot is a 410,
  and the dashboard and digest narration are given counts and labels.
- **A PDF with no text layer is a SCAN and is never sent to the text model.** It was
  sent as "[PDF content — base64 prefix, no extractable text layer]: …" under an
  "extract invoice fields" prompt, and since confidence is presence-based a plausible
  vendor and invoice number could come back from gibberish. `_extract_pdf_text` returns
  `None` for a scan; `_extract_scanned_pdf` reads up to `SCANNED_PDF_PAGE_LIMIT` (3)
  pages as pictures through the Gemini path, or refuses in words (image reading off,
  unreadable file, more than three pages — **never read in part**, because a reading
  that stops at page three drops the line items on page four and says nothing).
- **Every route that reaches a model is rate limited, per firm AND per user.**
  `middleware/rate_limit.ai_limit(bucket)` is a dependency declared AFTER `rbac()` so a
  permission refusal spends nothing; `enforce` is the same check for a route that only
  sometimes reaches a model (a statement upload is a model call only when it is a scan).
  Buckets differ on purpose: `chat` 20/min, `intelligence` 10, `extract` 10, `vision` 5,
  a user getting half the firm's share (never under three). A refusal is a 429 with
  `Retry-After`. `tests/test_every_route_that_reaches_a_model_is_rate_limited.py` derives
  the AI routes from the routes' own source and fails an unlimited one. ⚠️ **The windows
  are in-process**: right for one worker, wrong for several, and forgotten on restart.
  **A firm may cap its own monthly AI use, and no firm has a limit unless a Partner sets
  one** (ai-17, migration 476, the bullet after the AI-status one below). The count is
  tokens and pages from `ai_usage_events`; **there is deliberately no default allowance and
  no rupee figure**.
- **The executive dashboard and the copilot's global context answer for the CALLER's
  clients.** `allowed_client_ids` used to feed only the cache key, so a scoped Manager
  got every other client's name in `churn_signals` — with the cache correctly keeping
  their answer apart from a Partner's, which made it look handled. Clients, overdue
  tasks, compliance records and workflow failures/approvals are all narrowed, and the
  payload says `scoped` the way the relationship view does.
- **A reply shows its citation, and says when there is none.** `/api/assistant` parses
  the trailing `Source:` line off the answer; the page rendered only the answer. It is
  shown now, three states kept apart: a citation, none given (`""`, which is also what a
  marker with nothing after it is — `split_source` no longer returns the truthy
  `"Source: "`), and unknown (`undefined`, a message saved before the field existed,
  which is NOT rendered as missing).
- **A stored reply names the model that gave it.** `add_message` and
  `create_recommendation` defaulted `model_used` to the retired Llama and the column's
  own default (migration 069) is the same string; they record `groq_text.text_model()`
  now. The column default is left — changing it is a migration — and is wrong only for a
  row written by something that does not set the label.

_Longer design records for this area were moved to `docs/design-record/ai.md`; see the Design record index._

## Money and the general ledger

- **Every rupee calculation uses integer paise arithmetic, never floating point.**
  Monetary columns are `*_paise BIGINT`. ₹1 = 100 paise.
- **One posting kernel, no alternative paths.** Every accounting event that touches the
  GL is written by `services/phase2_journal_service._create_journal`. It asserts
  double-entry balance and dedupes on `(client_id, reference_no, entry_date)` before
  inserting. Sales, purchases, receipts, payments, credit/debit notes, banking, payroll,
  fixed assets, opening balances, manual journals and reversals all route through it. Do
  not add a second write path. ⚠️ **"All route through it" is exact for the Python kernel and
  not for the database**: an ordinary rupee receipt posts its journal inside the receipt's own
  transaction through the `settle_receipt_atomic` database function (migrations 160 and 235)
  and not through `post_journal_atomic`, and a manual journal's lines are rewritten by
  `edit_posted_journal`, so three database functions write the ledger. The public site
  therefore says "one ledger" and never "one posting path";
  `tests/test_the_hero_figures_are_counted_facts.py` pins the closed set of writers, the
  agreement of the hero's figures with the page's counters and that wording.
- The live GL is `journal_entries` + `journal_lines` only. A posted entry can never be
  hard-DELETEd or rewritten in place (DB triggers), and a correction to a real
  transaction is an append-only reversal. But immutability is not absolute, and the
  code is the authority on where the line falls: a **manual** entry may be edited
  (migration 266) or soft-deleted (275, 276) while its period is open, judged by
  `journal_period_lock_reason` — the CA locks the year, or a return covering the date is
  filed. Migration 276 also lets a reversed entry and its reversal go together, since a
  pair strands nothing and nets to zero. This tracks Indian law rather than exceeding it:
  the proviso to Rule 3(1) of the Companies (Accounts) Rules 2014 requires an **edit
  log**, which presumes entries can change, and TallyPrime's Edit Log — mandatory and
  non-disableable — still lets a voucher be deleted. The log is what is immutable, not
  the entry. Every deletion writes the whole entry, its lines and their account names to
  `audit_log` in the same transaction, unswallowed.
- **"Closed" is TWO different things, and which one applies decides who asks.**
  `domain`-side there is one definition, in SQL (migration 361), split by kind:
  `period_closure_reason` is the CA's own deliberate acts — the firm locked the
  financial year, or this client's year-end was finalised — and `period_lock_reason`
  is those two plus *a return covering the date has been filed*, calling the first
  rather than restating it. **The posting kernel asks only the closures**, so nothing
  reaches the GL inside a year somebody closed. The filed-return branch is asked where
  a document that FEEDS a return is written — sales invoices, purchase bills, credit
  and debit notes, and the manual journal, which can move any account including the tax
  ledgers — and by the edit and delete paths (266/275/276). It is deliberately NOT in
  the kernel: GSTR-1 for June is filed on the 11th of July and GSTR-3B on the 20th,
  while June's bank reconciliation happens after both, so a kernel refusal would stop
  every June receipt, payment, bank entry, depreciation charge and payroll accrual from
  the 11th onwards. `services/period_lock_service.py` holds the Python twins, pinned to
  the SQL by `tests/test_period_lock_reason_parity_pg.py`.
  **A RECEIPT IS ONE OF THOSE DOCUMENTS FOR ONE CLASS OF CLIENT, AND THE
  ARGUMENT FOR LEAVING EVERY OTHER RECEIPT OPEN STILL STANDS** (SALES-15).
  Both receipt paths asked only the firm-FY validator, on a recorded argument
  — "a receipt moves Bank and Debtors and touches no output tax" — that GST-15
  falsified by half: for a client marked `gst_advance_tax_applicable`, CGST
  §13(2) charges tax on an advance for SERVICES when it is RECEIVED, so the
  receipt is declared in GSTR-1 Table 11A and discharged in GSTR-3B Table
  3.1(a). `receipt_service._assert_open_where_a_receipt_feeds_a_return` asks
  the lock for exactly those clients. **It is UNCONDITIONAL on the receipt's
  own shape**, the fixed asset's reasoning below: gating on whether the receipt
  leaves an unallocated balance would be wrong twice, because
  `table_11_sections` measures what was adjusted BY THE PERIOD END off the
  ALLOCATION's `created_at` — so a back-dated receipt allocated in full today
  has no allocation dated inside June and its whole amount lands in June's 11A
  — and a receipt with no rate or place of supply is NAMED in that return's
  `gaps`, which is also part of what was filed. **Every other client is
  untouched and that is the point**: Notification 66/2017-Central Tax removed
  the charge on advances for GOODS, the flag is off by default, and recording a
  20 June payment on 15 July stays an ordinary thing to do.
  **A FIXED ASSET is one of those documents.** `create_asset` asked only
  `period_validation_service.validate_posting_date` — firm-FY, no client_id, so
  it cannot see a filed return — while `correct_asset` and `delete_asset` both
  called `assert_open` and always had. A CA could create a June asset after
  June's GSTR-3B was filed and then be refused when they tried to fix it, and
  create-but-not-correct cannot be right whichever way the rule should fall.
  It falls on `assert_open` because the acquisition journal debits `%GST Input%`
  from `itc_claimable_paise`, which feeds Table 4(A) — a capitalised purchase
  IS a document that feeds a return. Unconditional rather than gated on whether
  ITC was recorded: a rule that depends on the order two fields are filled in
  is not a rule. Depreciation's own refusal is separate, deliberate and
  test-pinned; that one is an owner decision to re-take, not a bug to swap.
- **A journal line's account belongs to the entry's own firm and client**, enforced by a
  statement-level trigger on `journal_lines` (migration 360) rather than inside each
  posting function — `account_id` carries only a global FK to `chart_of_accounts(id)`,
  so before it every account id in the database satisfied it. A `chart_of_accounts`
  row with `client_id IS NULL` is a firm-level account and is allowed on any of that
  firm's entries.
- **What a document still has OPEN is `outstanding_paise`, and the note columns'
  signs are not guessable from their names.** Migration 278 put it on
  `client_sales_invoices` and `purchase_bills` as `GENERATED ALWAYS ... STORED`
  precisely so the formula lives once, in the schema — read the column, do not
  re-subtract. `total - paid` is a DIFFERENT figure: it omits the CGST §34 note
  terms, and **migration 210 added the INCREASE document to both sides at
  once**, so `credit_note_paise` ADDS on `purchase_bills` while `credited_paise`
  SUBTRACTS on `client_sales_invoices` (`debit_note_paise` adds on invoices,
  `debited_paise` subtracts on bills). Four places in the bank module computed
  this and two had it wrong; both bank paths now go through
  `domain/banking/matcher.invoice_open_paise` / `bill_open_paise`, which read the
  column where the row came from Postgres and transcribe 278's expression where
  it did not (mock mode, the in-memory doubles). A settlement candidate carries
  BOTH figures — `amount_paise` is the document's face value, `outstanding_paise`
  what is left — because `FindMatchModal` renders "· ₹X open" only when the two
  differ. **And every piece of MATCHING ARITHMETIC runs on the second**
  (BANK-10): `matcher.candidate_open_paise` is the one definition, read by the
  fetch band, the in-memory re-test, `rank_suggestions` and
  `candidate_search.search` alike. The ranker was the last place still
  subtracting the FACE value, so a ₹1,18,000 invoice half settled by an advance
  and cleared by a ₹59,000 credit came out "short by ₹59,000" — outside the 25%
  band, so offered nowhere, on the commonest settlement an Indian practice sees.
  Two things fall out of it and both are deliberate: the old +15 "matches
  outstanding balance" bonus is GONE, because it now restates `difference == 0`
  exactly and a term restating its own branch only inflates documents that
  happen to carry the column; and a bank line LARGER than what is open is no
  longer offered by the ranker at all, because offering it invites an allocation
  bigger than the document can take — the unbanded search still finds it and
  says the line is larger, which is what that screen is for. `None` means the
  face value IS the open figure, which is true of the three candidate kinds that
  carry no such column.
- `created_by` / `posted_by` FK to `public.users.id` (the internal user id), **not** the
  Supabase auth id. **`audit_log.actor_id` IS THE MIRROR IMAGE AND TAKES THE AUTH
  ID**, because migration 111's trigger — which writes the great majority of that
  table's rows, on every firm-scoped table — reads `auth.uid()` into it and looks
  the email up `WHERE u.auth_user_id = v_actor`. The column has **no FK** (082
  declares a bare `actor_id UUID`), so nothing refused the other one: on
  24-09-2026, 157 `audit_service.log_event` calls passed the auth id and **37
  passed `current_user.get("id")`**, and `GET /api/audit?actor_id=` filters
  `.eq()` on it, so "everything this person did" returned whichever HALF shared
  the flavour of id that was asked for — silently, on this product's Companies
  (Accounts) Rules 2014 Rule 3(1) edit log and its DPDP Rule 6 access log.
  `tests/test_the_audit_log_names_one_kind_of_actor.py` is the rule.
  ⚠️ **THERE ARE TWO FUNCTIONS CALLED `log_event`** —
  `services/audit_service.log_event` → `public.audit_log`, and
  `task_extras_repo.log_event` → `public.task_timeline`, whose `actor_id` is
  `TEXT` (migration 063) and correctly holds the INTERNAL id. A sweep matching on
  the NAME rewrote four of the second one's call sites before the diff was read;
  the guard tells them apart on the CALL SHAPE (a bare `Name` against an
  `Attribute` on a repository), never on a list of files.
- Money crosses the API as raw integer `*_paise`. The frontend formats to ₹. Rupee
  conversion happens only at the statutory payload boundary — see
  `domain/gst/money.py`: 2-decimal rupees for GSTR-1, whole rupees for GSTR-3B
  (CGST Act §170, half rounded up).

_Longer design records for this area were moved to `docs/design-record/ledger-and-money.md`; see the Design record index._

## Indian tax domain rules — never violate these

- GSTIN format: 2-digit state code + PAN (10 chars) + 1 digit entity number + Z + 1 check digit
- PAN format: AAAAA9999A (5 uppercase letters + 4 digits + 1 uppercase letter)
- Financial year: April 1 to March 31
- GSTR-1 due date: 11th of the following month
- GSTR-3B due date: 20th of the following month
- GSTR-9 (annual): 31st December
- TDS return (24Q salary / 26Q residents / 27Q non-residents — Rule 31A(2) sets one due date per quarter regardless of form): Q1 31 Jul, Q2 31 Oct, Q3 31 Jan, Q4 31 May. Q4 is the exception — it is NOT the end of the month following quarter end (that would be 30 Apr). services/compliance_engine.py::tds_return_due_date is the authority; keep any prose in step with it. **The DUE DATES above survive the 2025 Act unchanged. The FORM AND SECTION NUMBERS do not — see the next bullet.**
- **An estimated Cost Inflation Index says so, and is not written into the
  register.** The CII for a year is notified partway through it, usually around
  June, so `cii_for` legitimately falls back for a sale in the first weeks of a
  year — and the fallback UNDERSTATES the indexed cost and OVERSTATES the gain.
  `cii_is_notified` is the question `cii_for` cannot answer (it returns an int
  either way), `CapitalGainsResult.indexation_is_estimated` carries it — a
  DIFFERENT fact from `is_slab_rate_estimate`, which is about the rate — and it
  is stamped once at `compute_capital_gains`'s entry rather than on each of the
  eight branches, because it is a property of the two DATES. The estimator
  still answers, flagged. The REGISTER stores `indexed_cost_paise` as NULL
  instead (the column is nullable): nothing recomputes a stored row, so a
  figure taken from an unnotified year is wrong the moment the notification
  lands, and an absence a CA can fill in beats a stale number that reads as
  computed.
- **A filing cannot leave draft on a computation nobody has reviewed.**
  `POST /api/itr/snapshots/{id}/review` existed from the start and had NO
  CALLER (IT-30), so every `tax_computation_snapshots` row was permanently
  `draft` — while the computation screen already rendered a green tick for
  `reviewed`, a state it had no way to reach. The screen marks one reviewed
  now, and `itr_workflow.transition_itr_status` reads
  `itr_filings.computation_snapshot_id` on the way OUT OF DRAFT only (re-asking
  in review would block the review → draft step a reviewer uses to send a
  return back). **A filing that pins NOTHING is allowed through**: the column is
  nullable and a CA who computed outside the product has no snapshot to pin, so
  refusing would make the pin mandatory by accident.

- **A FIRST depreciation posting may start at any month and now says what that
  forecloses** (FA-04). `depreciation_posted_through` only moves forward, so an
  asset bought in April and first depreciated in December loses April–November
  permanently: the single-month path 409s on them, the range runner skips them,
  and reversal reaches the last month only. Starting late is nonetheless RIGHT
  and test-pinned — an asset brought over from Tally mid-life already carries
  its accumulated depreciation and its first posting here is whatever month the
  CA takes over in, so refusing the skip would refuse every migrated asset.
  So it WARNS: `foreclosed_months` names them and the notice says to reverse
  and restart if the asset was acquired here. Same shape as Rule 46(b)'s
  invoice-number sequence gap, for the same reason.
- **A MAIL TO A CLIENT NAMES WHOEVER IS ACTUALLY THE SENDER, AND THE FINDING'S TEXT WOULD HAVE UNDONE SALES-13** (practice_management-04). Every send used one From and no Reply-To. The finding asked for the FIRM's name and contact address on engagement letter, invoice, statement and reminder; that is right for the engagement letter alone (the practice writing to its own client). An invoice, statement or reminder is sent on a CLIENT's behalf to the CLIENT's customer, so those carry the CLIENT's name and `clients.email`. One mechanism (`from_header`, `reply_to_header`, one `_envelope` for both transports), the party decided by who the sender is. The address half of `from` never changes (a per-firm sending domain with DKIM needs DNS on each firm's side). No name keeps the default sender and no or malformed address sets no Reply-To, so a mail is never pointed at the wrong party to fill a gap; `from_header` strips controls, angle brackets, quotes, separators and `@` from a name so a typed client name cannot inject a header or pose as an address. Internal notifications are untouched.

- **A §37(3) AMENDMENT RE-DECLARES THE WHOLE ENTRY, so an export amendment
  carries its shipping bill.** `domain/gst/amendments.build_invoice_amendment`
  emitted three empty strings for `sbpcode`/`sbnum`/`sbdt` on `expa`
  (SALES-10) while the main build has emitted the real values since migration
  349 — so amending an export's VALUE replaced a filed entry that had a
  shipping bill with one that did not, and CGST Rule 96(1) matches the refund
  against exactly those three fields at customs. `exception_report`'s document
  index carries them now (`None` on a non-export, because three blanks there
  would read as an export with nothing recorded) and the amendment declares
  the BOOKS side. Absent still means three empty strings: the portal accepts
  an export declared before the shipping bill exists.
- **A CUSTOMER RECEIPT SETTLES CASH PLUS THE TAX THEY WITHHELD.**
  `ReceiptIn.tds_paise` posts Dr Bank + Dr TDS Receivable / Cr Trade
  Receivables and the settlement is `amount + tds` — IT Act §198 deems the tax
  deducted to be income received and §199 gives the deductee credit for it — so
  a ₹1,00,000 invoice paid ₹90,000 net of ₹10,000 §194J is settled in full. No
  screen sent the field until SALES-07, so the invoice stayed part-unpaid and
  no TDS Receivable existed to claim against. The box is hidden on a FOREIGN
  receipt because `create_foreign_receipt` refuses any non-zero value, and the
  unallocated figure on the screen measures against the settlement rather than
  the cash, which is the same figure the server's over-allocation refusal uses.
- **`tds_deductions.return_type` and `tds_returns.return_type` store the 1961-Act
  ROUTING KEY permanently — 24Q/26Q/27Q/27EQ — on both sides of the 2026 fork.**
  `vocabulary.statement_form` returns the number the PERIOD's own Act uses (140
  for a FY 2026-27 26Q) and that is a DISPLAY value. Writing it into the column
  hits migration 037's CHECK, which is what the firm-level TDS screen did from
  1 April 2026 onwards, surfacing as "Failed to save TDS return" with no reason.
  `CreateReturnRequest.return_type` is a `Literal` of the four so it cannot come
  back. Translate at the boundary, never rekey a store.
- **A TDS statement's deductor block is READ, never defaulted** —
  `domain/tds/deductor.py`, from `client_statutory_identity.tan` (migration 325,
  created for exactly this) and the client's own PAN, legal name and postal
  address. A caller-supplied value wins where one is given and is validated on
  the way through; where neither exists the build is REFUSED with one sentence
  per missing identifier. The firm-level screen used to invent
  `"MUMB00000A"` / `"AAAAA0000A"`, both well-formed, so every validator passed
  and a quarter saved under a TAN belonging to nobody — a return filed against
  somebody else's account, with §200/§201 exposure staying on the real deductor.
- **THE DEDUCTOR BLOCK IS SERVED, NOT RE-TYPED** (TDS-28).
  `GET /api/tds/deductor?client_id=` resolves it through the same
  `domain/tds/deductor.resolve` the compute path refuses with, off the same
  two rows (`_deductor_sources` — `client_statutory_identity.tan` and the
  client's own PAN, legal name and address). Nothing served it before, so the
  compliance screen opened four blank boxes and the CA typed the TAN, the
  legal name and the PAN every quarter, for every client — and a quarter filed
  under a mistyped TAN is filed against somebody else's account. The endpoint
  NAMES the gaps rather than refusing, because a screen opening a form needs
  to say what to go and record; the boxes stay editable, and a value already
  typed is not overwritten when the panel reopens.
- **THE TDS WORKSPACE ANSWERS A FAILURE WITH ITS OWN SENTENCE, AND A CONTENDED SNAPSHOT SAVE TAKES THE NEXT VERSION** (tds_income_tax-34). Twelve handlers (the audit counted nine) ended `return api_response(False, None, str(e))`; for a PostgREST failure that is the error dict (table, column, constraint, hint) inside an HTTP 200. `_could_not(exc, action)` logs the traceback and words the refusal through `core.exceptions.unhandled_failure`, the speaker `main.py` applies to every uncaught exception, so there is no second wording table; the guard is the RULE on broad handlers (`except Exception`/bare), not on the twelve sites, and leaves the narrow `except ValueError` that words the engine's own 422 because that message is authored there. `utcnow()` stamped five records naive. A duplicate `"194J(B)"` key was deleted with every registry compared byte-identical against git HEAD, so no figure moves. `save_computation_snapshot` retries on SQLSTATE 23505 and ONLY 23505 (migration 319's UNIQUE already existed; the finding's 'no guard' was wrong), re-reading the maximum version, five attempts, then the router's existing 409.

- **A TDS ENGAGEMENT OWES TWELVE MONTHLY DEPOSITS, NOT FOUR STATEMENTS**
  (TDS-12). Rule 30(2) binds every deductor other than an office of the
  government, and `compliance_engine.tds_deposit_due_date` had exactly one
  caller — `payroll_deposit_due_dates` — so the compliance calendar carried a
  monthly deposit for SALARY and nothing at all for the §194 series.
  `_tds_obligations` emits `TDS_NON_SALARY_DEPOSIT` for every month of the FY.
  **Its own obligation type**, not a second `TDS_SALARY_DEPOSIT` row: two
  deposits with different section codes on the challan and different registers
  behind them, one generated for a PAYROLL engagement and one for a TDS one,
  and the dedup key is `(obligation_type, period_start)` so sharing a type
  would silently drop one.
- **§206AB was omitted by the Finance Act 2025 w.e.f. 01-04-2025, so
  `tds_validator.is_higher_rate_applicable` takes an FY** and answers the
  ordinary rate for a later year. Not deleted: §206AB governs a period up to
  31-03-2025 indefinitely, including a belated or revised return filed today —
  the same fork shape as the TDS vocabulary. Omitting the FY means current law.
  ⚠️ The omission is `[S]`-graded — egress is refused at this environment's
  proxy — so it is a named constant, `SECTION_206AB_OMITTED_FROM_FY`.
- **What is due for deposit this month is `domain/tds/deposit_due.py`, and it
  is the NON-SALARY side only.** `GET /api/tds-workspace/deposit-due` groups
  `tds_deductions` by section for one DEDUCTION month into a challan-281
  worksheet, with §201(1A)(ii) computed per ROW (two deductions in one month
  are days apart, so a section-level clock charges both or neither) and the
  due date from `compliance_engine.tds_deposit_due_date` — Rule 30(2) binds
  every non-government deductor, salary and not, and there is deliberately no
  second copy of the seventh-and-March arithmetic. §192 tax is computed in
  payroll and never reaches `tds_deductions`, so every worksheet SAYS so; a
  §192 row found in the register is named as a gap. `tds_challans` finally
  carries the split — `amount_paise` is the TOTAL and tax is the remainder
  after surcharge, interest and penalty, so a request sending none of the three
  behaves exactly as before — and `minor_head` is settable (200 = paid over by
  the deductor, 400 = against a demand; the company / non-company split is the
  MAJOR head 0020/0021, which migration 037's inline comment had backwards).

- **`public.tds_section_limits` is NOT the TDS rate master and nothing may read
  it.** Migration 037 seeded it once with pre-Finance-Act-2025 thresholds and
  pre-2024 rates, and its ₹1,00,000 aggregate §194C row has never existed in
  any database (`section` is the primary key, both 194C rows went in under
  `ON CONFLICT DO NOTHING`). It is the one table whose name reads like the
  authority. Migration 371 makes it say so in the database and
  `tests/test_the_dead_tds_rate_master_has_no_readers.py` holds the other half.
  Do NOT correct the figures in place — `domain/tds/section_rates.py` is the
  FY-versioned authority and a second one in SQL is what the posting-kernel
  rule exists to prevent. A DROP is the right end state and needs the
  production-fixture refresh in `docs/schema-drift.md`.

- **A capital LOSS does not relieve other income** (§71(3), §74), and **§80G has
  a ceiling** (§80G(4): 10% of adjusted gross total income, where adjusted GTI
  is GTI less the capital-gains buckets and less every other Chapter VI-A
  deduction). §80G's four categories are the PRODUCT of two independent facts
  about the donee — the percentage and whether the qualifying limit applies —
  so `Donation80G` carries both, defaulting to "subject to the limit" because
  that is the residual category the section itself puts an unlisted donee in.
  §80G(5D) bars a cash donation over ₹2,000 outright.
- Advance tax due dates: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
- ITR (IT Act §139): 31 July, or 31 October where audit applies, or 30 November
  where a §92E transfer-pricing report is required
- **The §44AB AUDIT REPORT is due a month before the RETURN, and they are two
  dates.** Explanation (ii) to §44AB (substituted by the Finance Act 2020,
  w.e.f. AY 2020-21) defines the "specified date" as "date one month prior to
  the due date for furnishing the return of income under sub-section (1) of
  section 139" — so **30 September**, not the 31 October the return is due.
  Dating the report at the return's date shows every audit client a deadline a
  month late, on the obligation whose lateness carries §271B (0.5% of turnover,
  capped at ₹1,50,000), and it is the wrong sequence: §139(1)'s own date
  assumes the report is already on record.
  `compliance_engine.tax_audit_report_due_date` DERIVES it from
  `itr_due_date` rather than stating it, so a CBDT extension of one moves the
  other. The §92E variant is deliberately not modelled — "one month prior" to
  30 November is 30 October by calendar arithmetic while professional sources
  commonly say 31 October, and that one-day difference is unconfirmed.
- **Which ITR date applies is decided, or refused, in
  `compliance_obligation_service.itr_due_date_for_client`.** Explanation 2 to
  §139(1) settles it on facts the app holds in exactly three cases: (a)(i) a
  Companies Act company is 31 October on entity type alone; (a)(ii) a client
  with an active audit engagement is 31 October; (aa) a §92E report is
  30 November and outranks both. Everything else — LLP, Partnership, Trust,
  Proprietorship, Individual — is REFUSED: §44AB turns on the year's turnover,
  an LLP's audit on LLP Act §34(4) with Rule 24(8) (a different test entirely),
  a trust's on §12A(1)(b), and none of those figures is held against a client.
  The refusal returns 31 July, the EARLIER of the two, with `decided: false`
  and a named gap — early costs nothing, late costs §234A interest at 1% a
  month, a §234F fee and the §80 carry-forward.
- MCA/ROC offsets from the AGM date: ADT-1 +15d (§139), AOC-4 +30d (§137), MGT-7 +60d (§92)
- **GSTR-3B Table 4** follows Notification 14/2022-Central Tax with Circular
  170/02/2022-GST, live on the portal from 01-09-2022: 4(A) is **gross** (it is
  auto-populated from GSTR-2B, so netting blocked credit out of it breaks the
  tie-up), 4(B)(1) takes reversals "absolute in nature and not reclaimable"
  (Rules 38/42/43 and §17(5)), 4(B)(2) takes the reclaimable ones (Rule 37/37A,
  §16(2)(b)/(c)), and 4(C) = 4(A) − 4(B). §17(5) goes in 4(B) and is **not**
  repeated in 4(D). Table 6 sets off 4(C), never 4(A) — §49(4) allows payment
  only from credit available in the credit ledger, and credit reversed in the
  same return is not. `domain/gst/gstr3b_computer.py` carries the circular's
  wording and is the authority; the pre-2022 layout looks plausible and gets the
  tax right, which is why it survived so long.

- **§34(2)'s window is measured from the ORIGINAL SUPPLY's financial year, not the
  note's own period, and the two diverge constantly.** A June 2025 invoice credited
  in January 2027 sits in a wide-open period — January 2027's GSTR-1 is not filed —
  and outside a window that shut on 30 November 2026.
  `routers/credit_notes.py` asked only about the note's own date (is its year
  locked, is its return filed); both are right and both are about the wrong period,
  so a note that can never lawfully reduce output tax was accepted and posted
  (SALES-25a). `domain/gst/credit_note_window.py` is the rule and **it WARNS rather
  than refusing**: §34(2) bars the tax ADJUSTMENT, not the document, so a
  post-window commercial credit note is lawful and simply carries no GST. Derived
  on every read rather than stored — it is a function of three dates and would go
  stale the day GSTR-9 is furnished. **§34(3) debit notes have NO such window**:
  §34(4) requires declaration in the month of issue and sets no outer limit. Do not
  add one.
- **Correction window** (CGST §37(3), §39(9), §16(4)): 30 November following the FY, **or
  the date GSTR-9 was furnished, whichever is EARLIER**. Filing the annual return early
  shuts the window early. `compliance_engine.correction_window_closes()` is the function
  to use — `november_30_cutoff()` is only the statutory outer limit and will tell a CA a
  correction is available when it is not. **The GSTR-9 date is RESOLVED FROM THE BOOKS**
  by `gst_amendment_service.annual_returns_filed` (`gstr1_returns` with
  `return_type='gstr9'`, `status='submitted'`), keyed **per financial year** — the source
  periods of one call straddle years, so a single date applied to all of them shortens
  the wrong one — and converted **UTC → IST** before the date is taken, because 20:00 UTC
  on 30 November is 1 December in India and the two fall on opposite sides of the cutoff.
  It used to take an `annual_return_filed_on` parameter that nothing ever passed, so every
  window reported the 30 November limit (GST-09).
- **§195 asks CHARGEABILITY before it asks a rate, and the resident sections do
  not reach a non-resident at all.** §194C, §194J and their neighbours charge, in
  their own words, sums paid "to a **resident**"; §195 charges a payment to a
  non-resident, "at the rates in force" under Part II of the First Schedule and
  §115A — by the NATURE of the income, with no threshold, plus surcharge and 4%
  cess, which the resident series does not carry. But §195 reaches only a sum
  "**chargeable** under the provisions of this Act" (*GE India Technology Centre
  (P) Ltd v. CIT* (2010) 327 ITR 456), so an ordinary import from a supplier with
  no permanent establishment is business profits, not chargeable here, and the
  right withholding is **nil** — not 20%. `domain/tds/section_195.py` asks the
  questions in that order and refuses rather than guessing; §206AA's 20% no-PAN
  floor has a non-resident carve-out (§206AA(7) with Rule 37BC) residents do not
  get. Under-deducting disallows the WHOLE expenditure under §40(a)(i).
- **§192 withholding rests on THREE separate things, and conflating any two gets
  it wrong.** (1) The employee's regime INTIMATION to the employer — CBDT
  Circular 04/2023 — governs withholding only, and the same circular says
  expressly that it "would not amount to exercising option in terms of
  sub-section (6) of section 115BAC". (2) The §115BAC(6) ELECTION governs the
  return: Form 10-IEA where there is business income, the return itself where
  there is not (`domain/income_tax/regime_election.py`). (3) The Rule 26C
  FORM 12BB statement is the evidence, and prescribes exactly four claims —
  §10(13A), §10(5), §24(b) and Chapter VI-A. `domain/payroll/declarations.py`
  keeps them apart; nothing sets one from another.

- **A §192 PROJECTION IS THE RUN'S OWN FIGURE.**
  `GET /api/payroll/tds-projection` answers off `_compute_slip` — the same
  function the payroll run pays from — so what the screen projects for November
  is what November's run deducts. It replaced `lib/services/payrollTdsEstimate.ts`,
  a slab ladder with its own §87A rebate and §2(29C) brackets, hard-coded to FY
  2025-26 and deliberately not FY-versioned: from 1 April it was last year's tax,
  stated confidently, with no old regime, no declaration and annual-over-twelve
  where §192(3) governs. A projected month assumes a FULL month's attendance and
  no undecided bonus, and says so — LOP is a fact about a month that has
  happened, and §192(1) estimates on salary, which a payment nobody has decided
  is not.
- **Under the new regime §115BAC(2) allows §16(ia) and nothing else from
  section 16** — professional tax under §16(iii) is NOT deductible, nor is
  §10(13A) HRA, §10(5) LTA, or any Chapter VI-A head except §80CCD(2) (and
  §80CCH(2)/§80JJAA, neither a salary declaration). Since payroll withholds on
  the new regime by default, a deduction applied unconditionally is applied to
  everyone it is not available to.
- **The two Schedule III ageing schedules are NOT the same shape.** MCA
  Notification G.S.R. 207(E) of 24-03-2021 added both to the notes to the
  balance sheet. Trade RECEIVABLES age in five columns from six months (`<6m |
  6m–1y | 1–2y | 2–3y | >3y`), rows (i)–(iv) splitting undisputed/disputed ×
  considered good/doubtful. Trade PAYABLES age in FOUR columns from one year
  (`<1y | 1–2y | 2–3y | >3y`), rows (i) MSME, (ii) Others, (iii) Disputed
  dues–MSME, (iv) Disputed dues–Others. Both age from the DUE DATE of payment,
  or from the transaction date where none is specified. Giving the payables
  table the receivables' columns is the easy mistake and it is a wrong
  disclosure. Only MICRO and SMALL are row (i) — MSMED §22 and §2(n) both stop
  at small, so a MEDIUM enterprise is registered under MSMED and still belongs
  in Others. These are the **Division I** (AS) tables; Division II (Ind AS)
  splits the doubtful receivables row into "significant increase in credit risk"
  and "credit impaired". `domain/reporting/ageing.py` and
  `public.schedule_iii_ageing` (migration 303) are the authority and are pinned
  to each other by a parity test.
- Never auto-submit anything to any government portal — always require explicit CA confirmation click

`services/compliance_engine.py` is the single source for every due date above. If prose
and that module disagree, the module wins and the prose gets fixed.

- **s.194A HAS TWO RAISED LIMITS AND THEY HANG ON THE PAYER AS WELL AS THE PAYEE** (TDS-INCOME-TAX-30, migration 454). One Rs 10,000 limit was held, with the Finance Act 2025 limits for a bank deposit (Rs 50,000) and a senior citizen's deposit (Rs 1,00,000) marked "not modelled". The finding's own reading (bank / senior / other as payee classes) would have UNDER-deducted on the commonest s.194A payment: the senior limit exists only INSIDE the bank-deposit limb, so a company paying a pensioner interest on a loan withholds at Rs 10,000 whoever is paid. `vendors.interest_threshold_class` is therefore a three-answer class (ordinary, bank_deposit, bank_deposit_senior), nullable with no backfill, and `ordinary` is a word for taking a class back because PATCH drops a null. `resolve_tds(threshold_class=)` refuses a class on a section with one limit and ignores it before FY 2025-26. NULL reads as Rs 10,000 (the lower, which cannot under-deduct), so no existing supplier's withholding changes. Deliberately NOT done: interest paid TO a bank (s.194A(3)(iii)) is named, not modelled; `THRESHOLD_CLASSES_194A_VERIFIED` is False.

- **A 2025-ACT DEDUCTEE ROW CARRIES ITS s.393 PAYMENT CODE, OR NAMES WHY NOT** (TDS-INCOME-TAX-31). `payment_code_for` existed and nothing put it on a statement line. `domain/tds/deductee_payment_code.py` puts it on each deductee row of the 24Q/26Q/27Q builders (keys always present, null for a 1961-Act period). s.194C's code is read off the PAN's fourth character (P/H -> 1023; C,F,A,T,B,L,J,G -> 1024), never off the stored rate; s.192 -> 1002 with a stated non-government assumption; 194A, 194J(b) and the bare 194I/194J are named gaps, each with its own reason, and the keying sheet names rows with no code. Deliberately NOT done: the table is still a confirmed subset, and no RPU/FVU file is produced (TDS-16).

- **AN AIS FIGURE IS WHAT OTHERS REPORTED, SO IT IS OFFERED LINE BY LINE AND APPLIED ONLY TO AN EMPTY BOX** (TDS-INCOME-TAX-10, migration 455). The AIS import computed nothing and the computation read only the 26AS claim. `services/ais_computation_service.py` offers salary, interest and dividend with every payer behind each; accept fills a box only when it is empty, a typed figure that differs is flagged with the difference and kept, and a decision is stored on the figure it was made on so a changed statement shows it as stale and does not apply it (the `ais_service._carry_forward` choice, for the same reason). A sale of securities, a property sale, rent and a foreign remittance are refused a prefill with four different reasons (a consideration is not a gain; rent needs the house-property worksheet). The three working-paper panels hold no rate and no arithmetic and their fallback vocabularies are pinned from Python. Deliberately NOT done: the AIS key names were not checked against a real portal download; nothing is applied or filed by the server.

_Longer design records for this area were moved to `docs/design-record/tax-tds.md`, `docs/design-record/tax-income-tax.md`, `docs/design-record/payroll.md`, `docs/design-record/fixed-assets-and-inventory.md`, `docs/design-record/documents-sales-purchase.md`, `docs/design-record/tax-gst.md`, `docs/design-record/filing-and-compliance.md`; see the Design record index._

## What has to be updated every financial year

Indian tax rates, limits and forms change annually. This is the complete list of
what goes stale, where it lives, and how to tell. **It is deliberately short:
only things that actually change by statute or notification are here.** If
something is not on this list, it does not need an annual edit.

### The trap that makes this list necessary

Every rate lookup falls back rather than failing:

```python
def rates_for(fy):
    if fy in RATES_BY_FY:
        return RATES_BY_FY[fy]
    return RATES_BY_FY[LATEST_VERIFIED_FY]   # <- silently LAST year's rates
```

`entity_rates`, `presumptive`, `minimum_tax`, `section_rates` and `cii_for` all
do the same. So a missing year is **not an error — it is a confidently wrong
number**, computed at last year's rates and presented with no warning. That is
the whole reason this has to be a checklist someone works through, rather than
something that surfaces on its own.

That trap was live until 2026-09-08 and is now closed, but read what actually
happened, because the fallback was the SECOND problem. `CII_BY_FY` stopped at
2025-26 and held **380** for it — and 380 was itself wrong; six independent
sources say **376**. So `cii_for("2026-27")` returned last year's index AND
last year's index was a figure nobody had checked. Both are fixed: 2025-26 is
376, 2026-27 is 384, and `LATEST_CII_FY` deliberately stays at `"2025-26"`
because both figures are secondary-sourced and moving the anchor promotes a
guess to a verified figure. Post Budget 2024 indexation survives only as the
grandfathered option on immovable property, so the blast radius was small —
which is exactly why it sat there unnoticed.

### 1. The FY-versioned rate registries

Same shape in each: a `*_BY_FY` dict, and a `LATEST_VERIFIED_FY` naming the last
year a human checked against the Finance Act. **Add the new year's entry, then
move `LATEST_VERIFIED_FY` — moving it without adding the entry silently promotes
a guess to a verified figure.**

| File | Holds | Changes with |
|---|---|---|
| `domain/income_tax/statutory_rates.py` | slabs (both regimes), §87A rebate, surcharge brackets and marginal relief, cess | Finance Act |
| `domain/income_tax/entity_rates.py` | firm / LLP / domestic and foreign company rates | Finance Act |
| `domain/income_tax/presumptive.py` | §44AD, §44ADA, §44AE turnover limits and deemed rates | Finance Act |
| `domain/income_tax/minimum_tax.py` | MAT §115JB, AMT §115JC rates and thresholds | Finance Act |
| `domain/tds/section_rates.py` | TDS rates AND per-section thresholds (`LATEST_VERIFIED_TDS_FY`) | Finance Act, and mid-year CBDT notifications |
| `domain/tds/section_195_rates.py` | §195 rates on payments to non-residents, by NATURE of income (§115A), plus the two Part II surcharge ladders and cess | Finance Act. **Every year is currently `verified=False`** — reconciled, not confirmed line by line |
| `domain/income_tax/capital_gains_engine.py` | `CII_BY_FY` + `LATEST_CII_FY` | one CBDT notification, usually around June |
| `domain/income_tax/tax_audit.py` | §44AB(a)/(b) thresholds and the proviso's ₹10 crore limb (`LATEST_VERIFIED_FY` is `None` — **no year has been confirmed**) | Finance Act |

CII is the odd one out: it is notified *partway through* the year it applies to,
so at 1 April the entry legitimately does not exist yet. Check again mid-year.

Print current coverage before deciding anything:

```
cd apps/api && python3 -c "
from domain.income_tax import statutory_rates as s, entity_rates as e, presumptive as p, minimum_tax as m, capital_gains_engine as c
from domain.tds import section_rates as t
for n, d in [('slabs',s.RATES_BY_FY),('entity',e.RATES_BY_FY),('presumptive',p.LIMITS_BY_FY),
             ('minimum tax',m.RATES_BY_FY),('TDS',t.TDS_RATES_BY_FY),('CII',c.CII_BY_FY)]:
    print(f'{n:12} latest {max(d)}')"
```

### 2. The ITR JSON schemas — these must be downloaded by hand

`domain/income_tax/schemas/`, wired up in `itr_schema.py`'s `SCHEMA_FILES`.

The Income Tax Department publishes a new JSON schema per form per assessment
year, at **incometax.gov.in → Downloads → Income Tax Returns**, and the filename
carries a version that changes *within* a year too (the set on disk today spans
V0.1 to V1.2). They cannot be generated or inferred — somebody downloads them.

**So yes, this is an annual hand-off, and it is the only item on this list that
cannot be done from inside the repo.** Replace the seven files, update
`SCHEMA_FILES` to the new names, and re-run the field-path tests — the paths move
between versions, and `itr_json.py` writes against them. A path that silently
resolves to the wrong node is the failure mode here: an earlier version of this
work picked `TaxPayableOnDeemedTI` (the §115JB/§115JC MAT branch) instead of
`TaxPayableOnTI` on ITR-5 and ITR-6, which validated perfectly and reported the
wrong tax.

### 3. Payroll statutory limits — PF and ESI are versioned; PT is not yet

`domain/payroll/statutory.py` now holds the EPF and ESI figures in the same
`*_BY_FY` + `LATEST_VERIFIED_FY` shape as everything else: the ₹15,000 EPF
ceiling and 12% rate, the EPS 8.33% / ₹1,250 diversion, EDLI and admin charges,
and the ₹21,000 ESI ceiling with its 0.75% / 3.25% rates.

They change by EPFO / ESIC notification rather than on an annual cycle, so they
do not belong in the April sweep — but they are now printable, so add them to
any coverage check you run:

```
cd apps/api && python3 -c "
from domain.payroll.statutory import RATES_BY_FY, LATEST_VERIFIED_FY
print('payroll     latest', max(RATES_BY_FY), '| verified', LATEST_VERIFIED_FY)"
```

**The PF wage BASE changed on 21-11-2025 and is now handled.** The Code on
Social Security subsumed the EPF Act and adopts that Code's own wage
definition — **Code on Social Security 2020 `s.2(88)`**, which is the operative
provision for provident fund; the Code on Wages `s.2(y)` is the same words in
the other Code, and citing it for a PF computation is imprecise. The listed
EXCLUSIONS are capped at **50% of total remuneration** and the excess is
**deemed wages**. `domain/payroll/wage_base.py` implements it, period-aware,
and migration 334 stores the working on the slip.

**ESI CONTRIBUTIONS ROUND UP TO THE NEXT WHOLE RUPEE — both shares.** ESIC's
filing manual, of the figure the portal computes: *"Employee Contribution will
be calculated and displayed. This is rounded to next higher rupee"*; the same
has applied to the employer's share since October 2004. `_compute_esi` floored
to the paise until 11-09-2026, which under-remitted on every wage that is not a
clean multiple — and the employer carries that shortfall with interest. Note it
runs the OPPOSITE way to the GST discount rounding, which floors: there,
flooring cannot under-declare tax; here, rounding up cannot under-deduct
contribution. Both take the direction that is safe for the person who would
otherwise carry the liability, which is why they differ.

**Partly a gap: professional tax and the Labour Welfare Fund.** PT slabs are
still bare literals in `routers/payroll.py`, covering **Maharashtra, Tamil Nadu,
Karnataka and West Bengal** — four of the twenty-two states
`domain/payroll/professional_tax.py` records as levying it. LWF has no amounts
at all.

⚠️ **That count of twenty-two is `[S]`-graded and probably one or two too high.**
The 7 September 2026 research pass found Odisha reported as having repealed its
levy from 01-04-2026 and Punjab's charge described as a Development Tax rather
than professional tax. Neither was confirmable — egress is blocked, see
`docs/audits/2026-09-07-market-research/` — and the list is deliberately NOT
changed on that evidence, because the error direction is benign: naming a state
that no longer levies produces a false GAP warning, never a wrong deduction.
Settle it against the state notifications before removing either.

What is no longer a gap is the SILENCE. `domain/payroll/professional_tax.py` and
`domain/payroll/lwf.py` carry which states levy each, so an unmodelled state now
reports itself: creating a payroll run returns `statutory_gaps` naming every
employee whose state levies a deduction the run did not compute. A zero for
Delhi and a zero for Gujarat used to be the same number meaning opposite things.

The amounts are deliberately not written from memory — twenty states' slabs and
sixteen states' LWF figures, each moving by its own notification, would be
thirty-six confidently wrong deductions in people's pay, and a wrong deduction
is worse than a flagged gap: the employee is short-paid and the employer still
owes the right figure. **Adding a state is a human step**, like the ITR schemas:
read the current state notification, add the table, move the code out of the
unmodelled set.

### 3b. The other statutory data a human has to supply

Not annual — each moves on its own cycle — but all of it shares one shape: the
code REFUSES rather than guessing, and the refusal comes back as a named gap in
the response. Adding any of them is a human step, like the ITR schemas.

**§89 also refuses a year the rate registry does not hold**, and that is worth
knowing: `rates_for()` substitutes `LATEST_VERIFIED_FY` for a missing year, and
§89 is a comparison of years AT THEIR OWN RATES — so a substitute makes the
whole relief a fiction that looks entirely reasonable. Since the registry holds
only 2025-26 and 2026-27, §89 does not work for most real arrears until the
earlier years' Finance Acts are added.

### 4. What does NOT need an annual edit

Recorded so nobody goes looking:

- **Due dates.** `services/compliance_engine.py` derives every one from the FY
  by rule, not from a table. It needs touching only when a date is *changed* —
  a CBDT or CBIC extension notification — never as routine.
- **GST rate slabs.** Rates are per-line on the document, not a central table.
- **The FY label itself.** Derived from the date (`ist_fy_label`), never stored
  as a constant.

_Longer design records for this area were moved to `docs/design-record/annual-update-and-statutory-data.md`; see the Design record index._

## Code rules — always follow

- Never hardcode API keys — always use .env files
- Every financial calculation must have a corresponding unit test
- All GST/ITR logic must have a comment citing the relevant section of the CGST Act or IT Act
- Before any government API call, add comment: # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
- Zero business logic in the frontend. Computation, validation and statutory rules live
  in `apps/api`. (This is about logic, not about data access — see below.)
- All API responses must follow: { success: bool, data: any, error: string | null }
  (`models/common.api_response`)

_Longer design records for this area were moved to `docs/design-record/frontend.md`; see the Design record index._

## The frontend's second data path

The frontend does **not** reach the database only through FastAPI. Roughly 320
`.from("…").select(…)` calls across ~100 files read and write ~83 tables directly via
PostgREST. That is why:

- `rbac()` never runs on those calls — the only access check is RLS. Role-aware write
  policies (migrations 260/261) exist for exactly this, and
  `tests/test_direct_write_tables_are_role_guarded.py` tracks which tables are still
  unguarded.
- **`core.authz`'s ASSIGNMENT scoping never runs there either, and the policy that
  replaces it stopped being applied in 2024.** Migration 084 gave every `client_id`
  table a RESTRICTIVE `<table>_assignment_scope` policy — a Partner short-circuits to
  TRUE, everyone else needs a `user_client_assignments` row — with a one-shot `DO`
  loop that HAS NEVER RUN AGAIN. Six tables created since are read straight from the
  browser and had firm-wide access only until migration 370: `bank_accounts` (093),
  `debit_notes` (145), `purchase_credit_notes` / `sales_debit_notes` (210),
  `gstr2b_reconciliations` (341), `tds_lower_deduction_certificates` (359). About 44
  more are still in that state and are deliberately NOT fixed — nothing reaches them
  from the browser — so the durable half is the rule, asserted:
  `tests/test_a_table_the_browser_reads_is_assignment_scoped_pg.py`. **Do not "fix" it
  by re-running 084's loop**: migration 262 replaced the payroll policies with
  per-command ones so the EMPLOYEE PORTAL can read a payslip, and a portal principal —
  a portal user, an employee — has no `users` row, so `can_access_client` denies them
  their own record.
- **Renaming or dropping a column can break the frontend while backend CI stays green.**
  `tests/test_frontend_columns_exist_pg.py` parses those select lists and checks them
  against the real schema. Run it when you touch a migration.
- **The migrations and production have drifted before, in both halves of the
  schema.** `tests/test_schema_matches_production_pg.py` (columns) and
  `tests/test_guards_match_production_pg.py` (RLS switches, policies,
  constraints) compare a migration-built database against point-in-time
  production snapshots in `tests/fixtures/`, and assert only the directions
  that break something. `docs/schema-drift.md` explains both; the fixtures go
  stale by design and their README says how to refresh them.

_Longer design records for this area were moved to `docs/design-record/frontend.md`; see the Design record index._

## Tenancy and access

- `firm` is the tenant, `client` is the accounting entity. Almost every row carries
  `firm_id` (23 tables the API reads do not: child lines and allocations keyed on a
  parent, `firms` itself and a few global reference tables, see the engineering-28
  bullet below); every report and filing is client-scoped.
- The service-role key **bypasses RLS**, so the app-layer `.eq("firm_id", …)` filter is
  the primary isolation control, with firm-scoped RLS policies as defence in depth.
  Never write a query that omits it, unless the row is keyed on an id a verified gate or a
  scoped read already vouched for or the query is on the frozen list
  `tests/fixtures/firm_scope_allowlist.txt` (the engineering-28 bullet below).
- With `USE_USER_JWT` on, requests run as `authenticated` (anon key + caller's JWT) and
  RLS is genuinely enforced on the API path too.
- RBAC: `Partner > Manager > Executive > Reviewer > Client`
  (`core/permissions.py`, applied as `rbac(resource, action)`).

- **THE TEAM GRID IS REAL, AND WHAT IT REPLACED IS WORTH KNOWING.** It used to
  render per-member toggles headed *"Changes are saved instantly. Overrides the
  role default for that individual"* — and every clause was false: the toggles
  wrote into `localStorage`, reaching no other user, device or server, and
  nothing in `core/permissions.py` could have honoured them anyway. A Partner
  who unticked Payroll for an Executive believed they had removed access and
  had not. It was left READ-ONLY rather than deleted because the need was real;
  migration 403 built the need (see the per-person bullet above). **The
  browser-local map is still PURGED on load and deliberately NOT migrated into
  `user_permissions`**: nobody can tell at this distance which of those ticks
  was an intention and which was somebody finding out what the control did, so
  carrying them into a screen that now MEANS something would silently reassert
  decisions against a control that did nothing.
- **A screen showing what a role can reach ASKS.** `GET /api/identity/permissions`
  answers for the CALLER — resolved against their own overrides, so it agrees
  with what `rbac()` will do — and carries `role_defaults` beside it so a screen
  can show what the person has that their role does not give them;
  `GET /api/identity/role-matrix` answers for all five roles (the template);
  `GET /api/identity/users/{id}/permissions` answers for one member, with all
  three maps, because showing only the effect makes an inherited permission and
  a deliberate one look identical. All three are
  `get_accessible_resources` and none is a security boundary — `rbac()` is. The Team
  screen's own `ROLE_DEFAULTS` copy had drifted in the expensive direction —
  it showed an Executive reaching Clients and Tasks only, when PERMISSIONS
  gives them accounting, gst, income_tax, mca, report and tds besides, and it
  gave a Manager Billing they do not have while withholding the Reports and
  Settings they do.

- **A LOGIN TOKEN MUST HAVE BEEN ISSUED FOR THIS PRODUCT, AND A SESSION WE CANNOT VERIFY IS REFUSED** (SECURITY-PRIVACY-21). Both `get_current_user` and `get_jwt_user` decoded a Supabase JWT with `verify_aud` off and no issuer or required-claims check, so any validly signed token from the same signing key, including one minted for another audience, was accepted. `core/auth.decode_supabase_jwt` is now the ONE decode and both doors call it: audience `authenticated`, issuer `{SUPABASE_URL}/auth/v1` (or `SUPABASE_JWT_ISSUER` where the project has a custom auth domain) and `exp`, `sub`, `iat` required. **The revocation compare used to swallow an unreadable timestamp and let the request through; it now answers 401 and logs at ERROR**, because a check that fails open is not a check. A naive `iat` is read as UTC (`_instant_epoch`). ⚠️ **The issuer is the one value this code cannot confirm**: a human must decode a live token's `iss` before deploy, and a custom auth domain needs `SUPABASE_JWT_ISSUER`, or every login 401s. That fails CLOSED by design. Deliberately NOT done: the algorithm list is unchanged, and no check was relaxed for dev/test header-auth mode.

- **AN UNSIGNED REQUEST TO THE PUBLIC WEBHOOK WRITES NOTHING DURABLE** (SECURITY-PRIVACY-23). `payment_service.process_webhook` called `audit_log` for every request whose signature failed, and `audit_log.firm_id` is `NOT NULL`, so the row could not even be attributed to a firm: the append-only edit-log table was an unauthenticated write target, and an attacker could fill it. An unsigned request now leaves no `audit_log` row and is counted in `core/rate_window.SlidingWindowLimiter` (100 per address per 60 s, a refused hit is not recorded, at most 4096 keys), answered 429 with `Retry-After`; a capped sample (20 per hour) is logged so an attack is still visible. The body is capped at 256 KB on `Content-Length` and again after reading. A correctly signed webhook is processed exactly as before. Deliberately NOT done: the limiter is per process and in memory, so with several instances the ceiling multiplies; the protection that matters is that an unsigned request costs no row, and a shared store would be a new dependency for abuse damping.

_Longer design records for this area were moved to `docs/design-record/tenancy-and-security.md`; see the Design record index._

## Schedule III captions — one vocabulary, and the screen is served it

`apps/api/domain/reporting/schedule_iii.py` owns the caption list and is the
only place allowed to. `GET /api/accounting/schedule-iii/captions` serves it to
the mapping screen, which until 11-09-2026 carried its own hardcoded copy.

That copy had drifted in **both** directions at once, and it was measurable: it
offered five captions the classifier had never heard of, and spelled five others
differently — so **nine of the fifty mapped accounts in production were being
silently discarded**, the CA's decision saved and then ignored while the
statement went back to guessing from the subtype.

- **Canonical spelling is the screen's** — hyphenated `Short-term`, plural
  `Employee Benefits Expense` — an owner decision of 11-09-2026 taken on
  convergence (screen, stored data and classifier agreed) rather than on a
  reading of Schedule III, which could not be reached: `icai.org` and every
  `.gov.in` are refused at this environment's egress proxy.
- **`CAPTION_ALIASES` honours the older spellings** so nothing already stored is
  lost, and `canonical_caption()` is the only resolver — `bs_bucket`,
  `pl_bucket` and `classify` all go through it. **`Fixed Assets` is NOT an
  alias**: Schedule III makes it a heading over Tangible and Intangible, so it
  resolves from the account's own subtype rather than being guessed flat.
- **A subtype's hyphens are folded** before the keyword scan, so a human typing
  `Long-term Borrowings` as a subtype matches the `long term` keywords.
- **`apps/web/lib/accounting/scheduleIiiCaptions.ts` is a FALLBACK, not a third
  classifier**, and both halves of that are enforced. Every screen prefers the
  backend's `schedule_iii_caption` and reaches the browser copy only through a
  `??`, for the window where the frontend has redeployed ahead of the backend.
  The client Balance Sheet did NOT, until 11-09-2026: `fromSection` dropped the
  caption the API had always sent and `bsBucket()` guessed one from the
  subtype — and `bsBucket` cannot see `schedule_iii_mapping`, so **13 of the 26
  mapped balance-sheet accounts in production were shown under a different
  caption than the year-end statements gave them**, including a Long-term
  Investment presented as Other Current Assets.
  `apps/api/tests/test_the_browser_fallback_speaks_the_engines_vocabulary.py`
  holds the line from the side that owns the vocabulary — a guard written in
  `apps/web` would assert the engine against a copy of itself and pass whenever
  both drifted together, which is what the mapping screen's hardcoded list did
  for months.
- **`Tax Expense` is absent from `PL_EXP_ORDER` on purpose.** Schedule III
  Part II presents tax below profit before tax and the client P&L tab has no
  below-the-line row, so listing it among the operating expenses would fold it
  into total expenses. The extra-bucket fallback renders it separately. Pinned
  by a test, because it reads exactly like an omission.

- **The year end speaks the same taxonomy in a second spelling, and the
  translation is one table.** The statements are keyed on snake_case LINE CODES
  (`trade_receivables`, `cash_and_bank`) rather than captions;
  `domain/reporting/year_end_lines.py` holds the codes, the
  caption→code table, and `schedule_line_for_account` — the one function that
  says which line an account belongs on, deriving it from the account's type,
  subtype and the CA's own `schedule_iii_mapping` through `classify`. It lived
  in a ROUTER until 11-09-2026 while the two modules that needed it most read a
  CACHE of its answer, `account_group_mappings`, instead.
- **A row in `account_group_mappings` is an OVERRIDE, not the source**, and the
  correction is worth the space because of what the old shape did. That table
  is written only by `POST/PUT` on `routers/year_end_mappings.py` and, until
  11-09-2026, by its own `GET /mappings/defaults`. No screen has ever called
  any of them, so it holds **zero rows in production** — against 133 accounts,
  50 carrying a `schedule_iii_mapping` the CA recorded by hand. And
  `generate_financial_statements` sent every account it could not find there to
  `other_current_assets`, a debit-normal balance-sheet line. With no rows that
  is EVERY account, so the asset side came to Σ(debit − credit) over the whole
  ledger — **nil** — and so did equity and liabilities, and revenue, and every
  expense. The function's own `total_assets == total_equity_and_liabilities`
  guard passed on `0 == 0`: **a Balance Sheet of zeros certifying that it
  balanced.** Both readers now derive and treat a stored row as an override.
- **The auto-initialisation was removed rather than fixed.** That `GET` used to
  classify the firm's whole chart of accounts and INSERT the answers — a write
  behind a `read` action, and worse, it FROZE a derived answer. These rows are
  never re-derived and outrank the derivation, so the first CA to open the
  screen would have permanently detached the year-end statements from their own
  `/accounting/schedule-iii` decisions — for the accounts existing at that
  moment and no others, so half the chart would obey the CA and half would not.
- **There is deliberately NO second mapping screen.** `/accounting/schedule-iii`
  is already where a CA records this decision. A year-end mapping screen in the
  line-code vocabulary would be a second place to say the same thing, which is
  the mistake this file keeps having to record.

_Longer design records for this area were moved to `docs/design-record/reporting.md`; see the Design record index._

## Opening balances — the ledger takes a total, ageing needs documents

**AN OPENING BALANCE IS MADE OF DOCUMENTS, AND UNTIL MIGRATION 391 IT WAS THREE
TOTALS** (ACC-14). `opening_balance_service._plan_opening` computes exactly
three targets — aggregate Trade Receivables (Σ `customers.opening_balance_paise`),
aggregate Trade Payables and each bank — which is the right shape for the
GENERAL LEDGER and useless for ageing. Every AR/AP ageing screen and the
Schedule III ageing note (MCA G.S.R. 207(E) of 24-03-2021) bucket by the DUE
DATE of each open document, and a control-account total has no dates, so on day
one the whole opening receivable ages to nothing. Tally takes opening balances
bill by bill with dates for exactly this reason.

- **An opening document is an ORDINARY row in `client_sales_invoices` /
  `purchase_bills`** carrying the OLD system's own number and date, with
  `is_opening` true. That is what makes a receipt allocate against it
  (`receipt_allocations` is an FK to that very table), a statement list it, the
  collections queue chase it and the bank match queue offer it — all unchanged.
  A separate table would have needed every one of those taught about it.
- **IT POSTS NO JOURNAL.** `customers.opening_balance_paise` stays the single
  source of the ledger's AR leg and `opening_balance_service` is untouched. The
  document is the BILL-WISE BREAKUP of that balance, not a second posting of it.
  So the two must AGREE, and where they do not the difference is NAMED rather
  than absorbed — `domain/accounting/opening_documents.reconcile`, rendered on
  the Opening Balances tab. An ageing schedule that does not foot to its own
  control account is worse than either figure alone.
- **IT DECLARES NO TAX AND WITHHOLDS NOTHING.** The GST was charged and declared
  where the document was issued; any TDS was deducted, deposited and reported on
  a statement filed from there. Every tax field is zero and `total_paise` is
  simply what is owed. That zero is also what keeps it out of the 26Q build,
  whose own reads are `.gt("tds_paise", 0)` and `.eq("tds_section", "195")`.
- **`purchase_bills.outstanding_paise` IS GENERATED FROM `net_payable_paise`,
  NOT `total_paise`** (migration 278) — the one asymmetry between the two
  tables, and writing only the total would leave every opening bill outstanding
  at ZERO, invisible to AP ageing and to the Schedule III payables note. A
  real-Postgres test proves it both ways round.
- **`is_opening` SAYS ONE THING, and every reader that feeds a statutory output
  asks it**: `domain/accounting/opening_documents.without_carried_over`. The
  GSTR-1/3B build (declaring a carried-over supply again pays the tax twice, and
  claiming its credit again doubles Table 4(A)), the GSTR-2B reconciliation (no
  2B counterpart, ever — it would report as "missing in 2B" every month and send
  the CA to chase a supplier about a bill from before the engagement), the Rule
  37 report (the 180 days never started here), §43B(h) (the deduction was
  claimed in a year whose return was prepared elsewhere), the tax-invoice PDF,
  Rule 46(b)'s series, and all four §34 note routes. The list is the RULE, in
  `tests/test_an_opening_balance_is_made_of_documents.py::EXCLUDES`, with the
  readers that SHOULD see one recorded beside it so an absent filter is a
  decision.
- **THE FILTER READS THE KEY OFF THE ROW, so a narrow `select()` that omits
  `is_opening` makes it a silent no-op.** A guard walks each module's AST and
  fails a literal projection on either table that is neither `*` nor names the
  column. And `carried_over` reads an ABSENT key as an ORDINARY document — the
  direction that cannot silently drop a real supply from a return.
- **§43B(h)'s other direction is NAMED, not computed**: an earlier year's
  disallowance actually PAID during this year comes back as a deduction, and
  nothing on a carried-over bill records whether it was disallowed. The answer
  lists them rather than showing a nil that reads as "none".
- **A §194 FY AGGREGATE CANNOT BE CARRIED OVER AT ALL**, and the module says so
  rather than approximating. The aggregate is measured on what was CREDITED
  during the year, while an opening balance records what is still OWED — a bill
  credited in April and settled before the migration counts toward the limit and
  is not carried over. `resolve_tds` already takes `fy_prior_taxable_paise` and
  `fy_prior_tds_paise` from its caller for exactly this reason.
- **THE OTHER DOUBLE COUNT: two mechanisms open one position and neither
  corrects the other.** `opening_balance_service` posts the masters under
  `source_type='Opening'`; `trial_balance_import_service` posts an imported
  trial balance under `'TrialBalance'`, deliberately separate (its header
  explains why, and that separation is right). Nothing COMPARED them, so a CA
  who enters the bank opening balance on the bank master AND imports a trial
  balance carrying a Bank row opens the account twice and the balance sheet is
  out by exactly it, silently. `double_openings` reports every account with a
  NON-ZERO position in both — non-zero on both sides, because a delta engine
  legitimately leaves a net-zero pair behind on an account whose master balance
  went to zero. **No difference is offered**: which of the two is the mistake is
  the CA's answer, and a single netted figure would read as one to post.
- **The old system's document NUMBER is not checked against Rule 46(b)** — it is
  a fact about a document somebody else issued, the same way
  `purchase_bills.bill_no` is the vendor's own, and refusing a series this
  product never generated would make a migration impossible for the clients who
  most need one. Per-client uniqueness still applies (migration 151), because a
  carried-over number that collides with one this client will issue is a real
  conflict the CA has to resolve.

_Longer design records for this area were moved to `docs/design-record/opening-balances-and-imports.md`; see the Design record index._

## Reporting scope — "all clients" means the caller's clients

A reporting endpoint called with no `client_id` means "all clients", and that is
right only for a Partner: `_FIRMWIDE_ROLES` is `{Role.PARTNER}` (`core/authz.py`),
so an Executive or a Manager is assignment-scoped. `routers/accounting.py`'s
`_reporting_service(current_user)` builds the ledger source with
`effective_client_ids`, and the scope lives **on the source** rather than on each
report — a source is created per request from the caller's own scope, so a fetch
added later inherits the rule instead of having to remember it. `None` means no
restriction; an EMPTY set means nothing, never "no filter". Before ACC-17 the seven
reporting endpoints aggregated across the whole firm, and the Schedule III screen
offers "All Clients" as an ordinary control, so it did not need a hand-made request.

## Reporting performance — the rule, not a preference

**No report may fetch rows proportional to transaction volume.** What crosses the
wire must be proportional to the size of the ANSWER, not the size of the ledger.

This is not style. Measured in production on one client with 12,836 entries /
32,936 lines: profit-loss 2.15s, trial-balance 2.06s, **cash-flow 54.34s** —
same client, same request. The three fast ones read `account_period_balances`,
132 pre-aggregated monthly buckets. The slow one shipped every line to Python
and looped. Over that client's full history it could not finish inside
`lib/api`'s 45-second abort at all, and the abort is deliberately never retried.

A report reads exactly one of:

- **a pre-aggregated table maintained by triggers** — `account_period_balances`
  (migrations 227/228) is the worked example. Right for running balances and
  anything bucketable by month;
- **a SQL function that aggregates server-side** and returns finished rows —
  `public.cash_flow_report` (migration 277) is the worked example. Right where
  the logic is per-row and cannot be pre-bucketed: AS-3 classification needs
  each entry's legs TOGETHER, which a monthly per-account total has thrown away.

Fetching raw rows and computing in Python is the third option and it is not
available. `apps/api` runs on Render in Singapore and Postgres is in Mumbai, so
every page is a cross-region round trip; the old cash-flow path made thirteen of
them to produce a document about thirty rows long.

**When a rule has to exist in SQL, MOVE it — do not copy it.** Two
implementations drift. Where a Python one must survive for mock mode and local
dev (there is no `DATABASE_URL`; the in-memory source has no SQL functions), the
two are pinned by a parity test that runs every scenario through both and
asserts they are identical — `tests/test_cash_flow_sql_parity_pg.py`. Adding the
second implementation without the parity test is the thing not to do.

Aged receivables and payables were next, and are now built BOTH ways, because
they are two different answers. The **Schedule III ageing schedules** are
twenty-four numbers, so they are a SQL function — `public.schedule_iii_ageing`
(migration 303), with `domain/reporting/ageing.py` as its mock-mode twin and
`tests/test_schedule_iii_ageing_parity_pg.py` holding the two identical. The
**per-document AR/AP ageing** (`ar_aging`, `ap_aging`) lists one row per open
document, so its answer genuinely is a row set; migration 278 made
`outstanding_paise` a generated column precisely so the FILTER could move into
the query, and what crosses the wire is what is OWED rather than everything ever
billed. Both obey the rule. Which shape a report needs is decided by the size of
its ANSWER, not by the table it reads.

**AND THE BROWSER'S PAGER IS `lib/supabase/selectAll.ts`, WHICH EXPORTS TWO OF
THEM.** `selectAll` pages by OFFSET in widening waves (1, 2, 4, 4 … requests at
a time) and `selectAllKeyset` pages by cursor — and WHICH to use is not a
preference: with `.range()` Postgres must produce every row before the offset in
order to skip it, and producing a row runs its embedded aggregate, so **a query
that EMBEDS a related table runs that aggregate over the whole table on every
page**. Measured on the Journal tab, 12,836 entries with lines embedded: 1,342 ms
and 54,180 buffers per page against 32 ms and 15,758. Embed → keyset; no embed →
`selectAll`, whose waves the sequential cursor cannot match.

⚠️ **THE FIRST ATTEMPT AT THIS WROTE A THIRD PAGER**, `lib/data/pageAll.ts`,
because nothing grepped for what already existed — the mistake this file records
at `/accounting/retainer` and warns about at `/gst/reconciliation`. It was the
guard that found it, on its own first run. Two more spellings of that guard were
tried and both fired on correct code: matching the NAME collides with
`useDataTable.selectAllFiltered`, which ticks checkboxes and pages nothing, and
matching a `.range(` near any loop collides with `lib/data/tasks.ts`, which
pages by a CALLER-supplied offset. What distinguishes a hand-rolled pager is
that the same code decides the offset AND loops over it, so
`scripts/an-export-reads-every-row.test.ts` finds a loop's body by brace depth
and looks for the paging call INSIDE it. Its two pager-invariant assertions are
COUNTS rather than matches for the same reason: the module holds two pagers, and
a negative control that broke one stayed green on the other's copy of the line.

**Closing stock as at a date is the same shape, and it also carries a rule about
WHICH COLUMN answers a dated question.** `public.stock_position_as_at`
(migration 363) sums `inventory_stock_ledger`'s DELTAS to a date — one row per
item — with `domain/reporting/stock_position.py` as its mock-mode twin and
`tests/test_stock_position_parity_pg.py` pinning them. It never reads the
stored running totals, and that is not a style choice: those are chained in
INSERTION order (`_last_ledger_row` explains why, and it is right), so the
running total on a row is the position as at when it was RECORDED, not as at its
`movement_date`. Σ `value_delta_paise` to a date is also what ties to the
Inventory control account, because the inventory journal posts exactly that
delta at exactly that date. For the same reason a ledger's **Balance column is a
property of the order it is shown in** and is derived at display time from an
opening figure, never rendered from the stored chain.

_Longer design records for this area were moved to `docs/design-record/reporting.md`, `docs/design-record/fixed-assets-and-inventory.md`, `docs/design-record/tax-gst.md`; see the Design record index._

## GSTR-2B reconciliation — the books are read in `apps/api`, and the answer is kept

The one purchase-side task an Indian practice performs every month is "which of
my client's bills has the supplier not filed, and how much ITC must I hold
back". §16(2)(aa) makes it decisive rather than informational: credit is
available only where the supplier has furnished the invoice and it has been
communicated to the recipient, and **GSTR-2B is that communication**.

- **`domain/gst/gstr2b.py` parses the real envelope** — `data.docdata` with
  `b2b`, `b2ba`, `cdnr`, `cdnra`, `impg`, `impgsez`. Three things about the file
  are easy to get wrong and are written down there: the tax is on the **rate
  lines** (`inv.items[]`), never on `inv.val`, which is the whole invoice value
  INCLUDING tax; `itcavl`/`rsn` are part of the document and a match that drops
  them tells a CA the credit is safe when the portal has said it is not; and a
  **credit note reduces** credit, so `cdnr` type "C" is signed negative.
- **`domain/gst/itc_matching.py` is the matcher**, and it has FOUR answers.
  `missing_in_2b` (we hold a bill nobody filed — chase the SUPPLIER) and
  `missing_in_books` (they filed something we have no bill for — chase the
  DOCUMENT) are opposite problems, and one figure for both sends the CA to the
  wrong party. The document number is folded per SEGMENT (`INV/2025-26/0042` ==
  `INV-2025-26-42`) because a false "missing" is a phone call that costs the CA
  their credibility; the AMOUNT is never fuzzy, because a tolerance on the tax
  is a tolerance on the credit claimed.
- **`services/gst_2b_reconciliation_service.py` reads `purchase_bills` itself**
  and writes `gstr2a_records` (migration 340). The caller sends the portal file
  and nothing else: asking a screen to supply the purchase register it is
  reconciling is asking it to supply the answer, which is exactly what
  `raw["book_invoices"]` did. A re-upload REPLACES, and an unparseable file
  persists NOTHING — a zero written and called reconciled is the false clean
  result this replaced.
- **One screen, since 11-09-2026.** There were two. `/gst/reconciliation`
  matched two uploaded files in the browser, saved nothing, and forgot the
  answer on refresh; it carried a banner disowning itself, which is a warning
  label rather than a fix. **Deleted on the owner's decision.** The real one is
  the client GST tab's GSTR-2B Recon, and it is per-client by nature — the
  firm-level GST page cannot know whose books to reconcile, so its link was
  removed rather than repointed.
  `apps/web/scripts/the-2b-reconciliation-reads-the-books.test.ts` now asserts
  the file is absent and that nothing links to the route, so a second
  implementation cannot reappear quietly.
- **What the 26AS parser could not read is NAMED, and an unreadable file is
  refused rather than saved as an empty year.** `read_26as_text` returns a
  `Reading26AS` carrying the records AND every skipped line with its 1-based
  number and the reason; there is deliberately no wrapper handing back only
  the records. The split is tab-or-pipe only, which is a real limit rather than
  an oversight — a 26AS pasted out of a PDF viewer is space-separated and
  splitting on runs of spaces would cut deductor names in half — so such a file
  reports every line as skipped, `looks_unrecognised` is true, and the router
  422s. An EMPTY 26AS is still correctly empty: `looks_unrecognised` is
  content-with-no-records, not no-records.

- **A GST SCREEN CHOOSES A REGISTRATION FROM THE SERVER'S LIST AND THE PICKER DOES NOT PRETEND TO FILTER** (GST-17). `components/gst/RegistrationPicker` offers only registrations that file GSTR-1 and GSTR-3B, primary first, and `lib/gst/registrationChoice` holds the three rules (the list's order is kept; a GSTIN the client does not hold is REFUSED, never defaulted to the primary; a registration that files another return is not offered). Every registration in the server's listing carries `documents_not_split_caveat`, and the picker shows it beside the choice **because no invoice, bill or note records its registration (attributing each document to a registration is open work)**: choosing changes the GSTIN a return is filed under and not the documents in it. approve, mark-filed and the download act on the GSTIN the SERVER built the return for; the firm-level reads were keyed on (client, period) only. GSTR-2B has deliberately no picker (the upload names its own recipient GSTIN).

- **INVOICES THAT OWE AN IRN AND HAVE NONE ARE LISTED, AND THE TWO LIMBS ARE NOT ONE** (GST-20). `GET /api/einvoice/missing-irn` applies `irn_scope.assess` to issued, live, non-opening invoices and drops those with a live IRN. Rule 48(5) makes an invoice that needed an IRN and has none not an invoice, so the recipient's credit goes with it. **Rule 48(4)'s Rs 5 crore decides whether an IRN is OWED; the IRP's Rs 10 crore decides whether there is a CLOCK**, so a client between them has invoices listed as `no_reporting_limit` with no deadline, never dropped and never given a clock nobody imposes. Five window states, none standing in for another; the thirty days, the floor and the 01-04-2025 start are `[S]` constants with `VERIFIED` False. **An unrecorded turnover is a third state and never 'below the floor'**: for one client the invoices are listed with the clock marked assumed, firm-wide the client is NAMED and not assessed. The e-invoicing ratchet (any preceding year from 2017-18) reaches the clock. `MissingIrnPanel` says in words when it could not check, because an empty panel means 'none do'. Prepare-only; credit and debit notes are named as not covered.

_Longer design records for this area were moved to `docs/design-record/tax-gst.md`, `docs/design-record/tax-tds.md`; see the Design record index._

## Bank data — the Account Aggregator is the only way in

Statement upload (CSV/XLSX, parsed server-side in `domain/banking/normalizer.py`)
is how bank data enters the platform today, and it is not going away. When a live
bank feed is built, it goes through India's **Account Aggregator** framework and
nothing else.

**The DPDP duties over bank data are live NOW and do not wait for AA.** An
uploaded statement holds the client's account number and, in every narration, the
name or UPI handle of a COUNTERPARTY who is usually a stranger to the engagement
— the largest population of third-party data principals in the product. It is a
`bank_data` category in `domain/dpdp/retention.py` (Companies Act s. 128(5)
reaches it expressly, as the "vouchers relevant to any entry"), and the
bank-account delete names the statute and the date. See
`docs/compliance/06-data-protection-dpdp.md` §5e — which also records why the
AA consent artefact's `DataLife` clock would collide with the eight-year period,
and why that does not arise under upload.

- **The consent is the CLIENT's, not the CA's.** The account holder consents, and
  it is time-bound, purpose-bound and revocable. So the flow is "CA requests →
  client approves → CA sees data", with a re-consent path when it lapses.
  **That shape is NOT new to the app** — `routers/engagement_sign_public.py`
  already does CA-sends-a-tokenised-link → client-acts-without-a-login, with a
  256-bit bearer token, every query constrained to the token's row, a client-safe
  projection, IST-dated expiry and an honest 503-vs-404 split. A consent request
  should follow it rather than invent a second one. **What IS different is one
  step**: the engagement letter is accepted ON OUR PAGE, and an AA consent is
  approved AT THE AA. Put an "I agree" in our UI and the consent is ours, from an
  unregulated party, and worthless. See `docs/compliance/05-…` §6 — the shape is
  specified there and deliberately not built.
- **Never screen-scrape net banking.** No credential capture, no stored bank
  logins, no third party that works that way. It breaches bank terms and RBI
  moved the industry onto AA precisely to end it. This is not a performance or
  cost trade-off to revisit.
- **AA is additive, not a replacement.** Co-operative and smaller regional banks
  are patchy as FIPs — Cosmos Bank, say — and plenty of clients will not consent.
  Upload has to keep working, at parity, for years.

Do not model the feed on QuickBooks or Xero: their bank feeds run on
Plaid/Finicity/direct OFX, which do not serve Indian banks, and Intuit withdrew
QuickBooks from India in 2023.

_Longer design records for this area were moved to `docs/design-record/banking.md`; see the Design record index._

## Tests

Backend, from `apps/api`:

```
pytest tests/ -v                      # the mock-mode suite (no DB needed; no test pins a count, so none is stated)
pytest tests/test_foo.py -v           # one module
```

Real-Postgres tests are named `test_*_pg.py` (plus `test_migrations_apply.py`). They
self-skip unless `HARNESS_PG` is set and `psql` is on PATH:

```
HARNESS_PG="host=127.0.0.1 port=5432 user=postgres password=postgres" \
  pytest tests/test_migrations_apply.py tests/test_*_pg.py -v
```

Frontend, from `apps/web`: `pnpm lint`, `pnpm exec tsc --noEmit`, `pnpm test`,
`pnpm build`.

_Longer design records for this area were moved to `docs/design-record/engineering-and-ci.md`; see the Design record index._

## CI

Two **required** status checks on `main`, both in `.github/workflows/backend-ci.yml`:

- `pytest — mock mode (Python 3.11)`
- `migration apply — real Postgres 16`

Never add a `paths:` filter to the `on:` block of a workflow carrying a required check.
A path-filtered workflow does not run when the filter misses, the check never reports,
and GitHub treats that as pending forever — which makes unrelated PRs unmergeable with
no failing check to point at. Filter inside, in the `scope` job, as these workflows do.

- **THE BACKEND INSTALLS FROM A HASH-PINNED LOCK AND THE IMAGE HOLDS NO TEST SUITE** (engineering-04, ops-27). `requirements.txt` held fifteen floating `>=` lines among its pins and there was no lock, so a build next month could resolve to versions the suite never ran on; pytest sat in the production file; and `COPY . .` carried all of `tests/`, with every production-schema snapshot, into the image Render serves. `requirements.in` is what a person edits; `requirements.txt` is pip-compile's output (every package, transitive included, pinned with the sha256 of each file); `requirements-dev.in`/`.txt` add pytest and the tools only the test and lint job uses (ruff, hypothesis, pytest-cov, pytest-xdist: see the lint-ratchet bullet under Tests) and are constrained to the first (`-c requirements.txt`) so CI cannot test a different version of a shared library from the one the image installs. The Dockerfile and all three installs in `backend-ci.yml` use `--require-hashes`; `.dockerignore` leaves `tests/` and the dev files out (**`migrations/` stays: the schema guard reads it at boot**); the `docker image` workflow (not required, scoped inside the job, weekly too) builds the image and asserts no `/app/tests`, `import pytest` fails, `pip freeze` equals the lock (`scripts/ci/compare_freeze_to_lock.py`) and `import main` works. **To change a dependency, edit the `.in` and recompile; never edit the `.txt`.** No runtime major was bumped and the pip-audit ratchet was unchanged when the lock was introduced (30 advisories, 30 in the baseline). **On 02-10-2026 six of Dependabot's eight grouped bumps were taken and two were HELD BACK, on a measurement and not a guess** (each bump installed alone into a copy of the baseline environment, then the six together): python-dotenv 1.2.3, python-multipart 0.0.32, uvicorn 0.54.0, groq 1.7.0, PyJWT 2.15.1 and sentry-sdk 2.71.0 are in the lock (route count, OpenAPI paths and the status code of every operation unchanged against the baseline), and the baseline fell to 9 advisories: 21 lines were deleted, 13 of them PyJWT's (the auth path's own library), 7 python-multipart's and 1 python-dotenv's, which is the file's own rule. **fastapi 0.141.1 and supabase 2.31.0 are NOT taken and a later person bumping either must read this first.** fastapi moves starlette to 1.x and stores each included router as one `_IncludedRouter` in `app.routes`, so the 57 test modules that walk `app.routes` see 3 `APIRoute`s and fail (the app itself serves the same 965 paths); and it turns 24 operations that answer 422 for a missing required query parameter into a 500, because a parameter declared `Annotated[FYLabel, Query(...)] = ...` (the spelling the FY-label bullet allows where argument order needs a default) puts an `Ellipsis` in the validation error's `input` and `jsonable_encoder` raises on it; the same is true of a plain `Annotated[str, Query(description=...)] = ...`, and without the trailing `= ...` it returns 422. supabase 2.31.0 removes `postgrest._sync.client.SyncClient` and `SyncPostgrestClient.create_session`, which `core/supabase_client._force_http1` imports and calls inside a try that LOGS and carries on, so production would keep running on HTTP/2 and silently re-open the multi-thread h2 bug that function exists to fix (`LocalProtocolError: Received pseudo-header in trailer`) while logging an error with a traceback per per-request client; the new client has `ClientOptions(httpx_client=...)` as the seam, so that one is a code change and not a bump. `uvicorn.workers` is deprecated in favour of the `uvicorn-worker` package; the Dockerfile still uses it and it boots. Not measured: the full suite under either held-back package, and the multipart upload path under real concurrency. Not run: Docker is not available here, so the image workflow's first run is on GitHub; the base image is not pinned by digest; arm64 wheels were not checked.

_Longer design records for this area were moved to `docs/design-record/engineering-and-ci.md`, `docs/design-record/frontend.md`; see the Design record index._

## Migrations

- `apps/api/migrations/NNN_name.sql`, sequentially numbered from 001. Check
  `ls apps/api/migrations/` for the next free number rather than trusting a
  figure written down anywhere — including here.
- **Merging a migration to `main` applies it to the production database.** The
  `apply pending migrations — production` job runs `scripts/db/apply_migrations.py`
  against the live Supabase project on every push to `main`, once tests and the
  migration ratchet pass. There is no manual review step in between. See
  `docs/deploy-migrations.md`.
- **`CREATE OR REPLACE FUNCTION` REPLACES THE WHOLE DEFINITION, so derive the new
  body from the migration that LAST defined that function — found by NUMBER, not
  from memory and not from the one you happen to be reading.** A replacement either
  carries every earlier change forward or silently reverts it, and the revert
  compiles, deploys and passes a mock suite. Migration 384 got this wrong twice
  before the real-Postgres suite caught it: the first attempt was hand-written and
  lost the balance guard, the `jsonb_populate_record` column list and the
  `deleted_at` filter; the second was derived faithfully from migration 243 — and
  243 was the WRONG ANCESTOR, because 271 had made `post_journal_atomic` SECURITY
  DEFINER and 274 had folded in the reversal stamp. Merging it would have
  reproduced exactly the production incident 274's own header records:
  `permission denied for table journal_entries`, 42501, the reversal committed and
  its original left unflagged. `grep -ln "FUNCTION.*<name>" migrations/*.sql | sort
  | tail -1` is the answer. The guard shape that survives is in
  `tests/test_a_voucher_shows_its_lines_in_order.py`: it reconstructs the ancestor
  by scanning the migration directory, so it cannot be pointed at a stale one, and
  a parametrised clause test names the privilege model and every invariant a
  careless rewrite drops.
- `core/schema_guard.py` is the boot-time backstop: it surfaces code/schema drift loudly
  instead of letting writes fail silently behind broad `try/except`.

_Longer design records for this area were moved to `docs/design-record/engineering-and-ci.md`; see the Design record index._

## Deployment

- API → Render, Docker, **Singapore region**. It must stay near the Mumbai Supabase; the
  reasoning and the measurements are in `render.yaml` and Render cannot move a service
  between regions.
- `apps/web` and `apps/marketing` → two separate Cloudflare Pages projects. **Which
  hostname is which is not guessable**: the product is the Cloudflare project
  `practicesync-ai` and it serves at **`caflow-ai.pages.dev`** (the project's `pages.dev`
  name predates the rename and cannot change); **`practicesync.pages.dev` is the
  MARKETING site**, a different project built from `apps/marketing`. Both build from
  this repo, so every PR shows two Cloudflare checks and two bot comments.
- **THE REDIRECT FILE IS A 100-RULE BUDGET THAT FAILS SILENTLY, AND CLOUDFLARE COUNTS IT
  BY POSITION** (30-09-2026). A static export cannot serve `/clients/<any id>/...` by
  itself, so `apps/web/public/_redirects` rewrites every such URL to the pre-built
  `_placeholder` page; `scripts/generate-redirects.js` writes it from the `app/` tree on
  every build (never hand-edit). Cloudflare Pages allows 2,000 static and **100
  dynamic** rules, and **once its parser has met the first dynamic rule (one with a
  `:placeholder` or `*`) every later rule counts as dynamic — a plain literal rule
  included.** Rules past the cap are dropped with no warning. The generator used to sort
  its 32 literal shadow-leaf rules in among the dynamic ones, so Cloudflare counted 98 +
  32 = 130 and silently dropped rules 109-138: `/relationships/*` and all twelve splats,
  including `/clients/:id/*`. Every reload, bookmark or shared link into
  `/clients/<id>/<section>/` returned 404 in production while in-app navigation (the
  client router never asks the server) looked fine, and the old "98 of 100" test stayed
  green because it counted by SYNTAX. **Literal rules are emitted FIRST now**, and
  `scripts/generate-redirects.test.ts` measures `cloudflareDynamicCount` (rules from the
  first dynamic one onward) and asserts the order on a synthetic tree as well as `app/`.
  **Do not interleave them again, and do not read the budget off a count of lines that
  contain `:` or `*`.** Budget: 98 dynamic + 40 static, so **one more page under a
  dynamic prefix costs 2 and lands on 100, and one that opens a new splat group costs 3
  and breaks it** — decision D10: no new dynamic route under `/clients/[id]`; a new
  section there is a QUERY PARAMETER on an existing route. A route with no `:` of its
  own can still be shadowed by a sibling's placeholder (`/health/critical` vs
  `/health/:client_id`), which is what `staticLeafShadowRules` is for.
  **THE PLANNED WAY OUT IS DECISION D26 (`docs/plan/THE-PLAN.md`) AND NOTHING OF IT IS
  BUILT**: migrate `apps/web` from Pages to a Cloudflare Worker with static assets, and
  do the `_placeholder` rewrite in ~15 lines of a `fetch` handler that runs only on
  `/clients/*` page loads. The cap disappears, and so do `generate-redirects.js` and D10
  as a constraint. **Moving to Workers alone does NOT help** — `_redirects` has the
  identical 100-dynamic limit there, so the rewrite must move out of the file and into
  code. No new subscription (Workers Free is 100,000 requests a day; static-asset
  requests are free and unlimited). It is the OWNER'S Cloudflare account and it changes
  how the live site is served, so it needs their cutover: verify every route shape on a
  preview URL first, then move the domain. Status is OPEN and is the owner's call; do
  not start it unasked.
  **To verify a redirect change live**, request every rule's own URL on
  `caflow-ai.pages.dev` after the deploy lands (about 4 minutes) — but a splat's test URL
  must be a REAL page under it (`/clients/x/accounting/`, not `/clients/x/a/b/`), or it
  404s with the rule working. This sandbox's egress allows only that exact host, so
  preview-deployment URLs (`<hash>.caflow-ai.pages.dev`) cannot be reached from here:
  the check happens on production after the merge.
- `render.yaml` must declare every environment variable the backend reads —
  `tests/test_render_manifest_matches_code.py` enforces this in both directions
  (nothing read-but-undeclared, nothing declared-but-unread).
- **The slow half of startup runs on a thread, and must stay there.** The
  schema-drift check, the scheduler start, its health log and the catch-up
  sweep are started by `main._lifespan` on a daemon thread — not at module
  import, where they used to be. Three of the four make a Singapore-to-Mumbai
  round trip, and doing that before uvicorn binds timed out Render's deploy
  health check on every deploy for weeks. `/health` answers 200 with
  `schema: "checking"` while the check is outstanding and flips to 503 on real
  drift; **answering 503 while merely unchecked reproduces the original bug**,
  because Render cannot tell "still checking" from "broken".
  `tests/test_health_answers_before_the_slow_boot.py` is the guard.
- The daily job sweep is in-process APScheduler (`jobs/scheduler.py`), gated on
  `ENABLE_SCHEDULER`, enabled in exactly one process. On Render's free tier the instance
  sleeps, so `.github/workflows/wake-before-scheduler.yml` pings `/health` across the
  window to keep it alive; the sweep also catches up on jobs whose trigger was slept
  through.

_Longer design records for this area were moved to `docs/design-record/deployment-and-operations.md`; see the Design record index._

## Compliance, integrations and filing

`docs/compliance/` is the single place that says, for every statutory output:
what the product computes today, what the last mile actually is, and **what gates
closing it** — which is almost never code. Read it before estimating any filing
or integration work, and read `docs/compliance/00-how-to-read-this.md` first for
how much to trust the rest.

Places in the code where a registration, empanelment or licence gates the work
carry a scoped marker naming its section:

```
grep -rn 'TODO(compliance)' apps/api apps/web
```

That convention is deliberate and narrow — the codebase otherwise has **no**
`TODO`/`FIXME` markers at all and prefers prose comments beside the code.
`tests/test_compliance_markers_point_somewhere_real.py` fails a marker with no
doc path or one pointing at a file that does not exist.

## Where the design is written down

`docs/architecture/01-11` is the authoritative design set — accounting engine, posting
kernel, financial years, opening balances, manual journals, multi-currency, GST engine,
reporting engine, bank entries, and the practice's own revenue loop and knowledge base.
Read the relevant one before changing a subsystem.

**THE FIRM'S OWN PRACTICE IS A CLIENT, AND ITS DESIGN RECORD IS `docs/architecture/11-revenue-ops-and-knowledge.md`** (POST-A-177). It covers the internal client (`clients.is_internal`), guardrails G1 to G4 (Partner-only; out of every client population; one linked customer; no payroll), the schedule -> draft -> issue -> receipt lifecycle with `uq_client_sales_invoices_billing_run`, collections, time capture and the knowledge base, written from the code and not from the June batch reports. `tests/test_the_revenue_ops_design_record_names_what_exists.py` holds every route, migration, function and path it names, and its "not built" statements expire (KB search is title-only; the Manager is firm-wide in the KB alone; six observed defects, now POST-A-215 and POST-A-216): when one fails, fix the record the same day. **A severity argued from "nothing reaches this" is a test** (POST-A-179): `tests/test_an_unreachable_premise_fails_when_it_becomes_reachable.py` is the register; add an entry when you write that sentence, delete it when the item closes.

**`docs/open-items/` ANSWERS "WHAT IS LEFT", AND THE AUDIT DOCUMENTS THAT USED TO
ARE DELETED** (2-8 October 2026). Start at `docs/open-items/README.md`: six
files of one-line items, split by WHEN (before or after the demo) and by WHO
must act (`A` Claude alone, `B` the owner decides or a live session is needed
and Claude builds, `C` only the owner or someone outside this container), with
stable ids (`PRE-A-001`, `POST-B-017`; never renumbered, a closed item's line
is deleted and its id is not reused). It was built from every raw open item in
the audit, finding, plan and compliance documents and in this file, merged
where they described one task; `checked-closed.md` lists what the sweep found
already done so nobody reopens it, `decisions-and-strategy.md` holds the 15
owner decisions and the staged roadmap, and `deletion-plan.md` records what was
deleted and what was kept and why. `apps/api/tests/test_the_open_items_ledger_is_well_formed.py`
keeps it one line per item with unique ids, no dangling citation and current
counts (`python3 scripts/open_items_counts.py`). **Close an item by deleting
its line in the same commit as the change, then rerun that script**; an item's
facts go stale like any snapshot, so read the code before acting on one. The
ids here (`PRE-A-001`) are another namespace beside `rm/area-NN`, the UPPERCASE
audit ids and the `D<n>` decisions: never equate them.

**Deleted on 8 October 2026, with the owner's approval:** everything under
`docs/audits/` (the 2026-07 to 2026-09 audits, `findings-status.json` and `.md`
with the script that rendered it, the 278 finding JSON files, the market
research, the probe pass, the phase plans and the question files), four log and
question files under `docs/plan/` and nineteen early completion, hardening,
E2E and audit reports at the top of `docs/`. Every one is recoverable exactly
as it stood at merge commit `315e6a1980053c5db5e00646d16624d48e358907`
(`git show 315e6a19:docs/audits/<file>`; the full list is in
`deletion-plan.md`; a tag could not be pushed from the session that did it).
**A finding id quoted in this file or in a source comment (`GST-18`, `PAY-27`,
`TDS-16`) names a finding in that deleted record**, and a comment or document
that cites `docs/audits/...` is now a historical reference. What is still open
from them is a ledger line, and what they proved closed is in
`checked-closed.md`. The statutory readings they graded are graded `[S]` or
`[P]` where this file states them; the market research behind them never
reached `[P]`, because egress to the government sites is refused from this
container, so every claim in it rested on a search engine's summary of a page
nobody opened.

- **THE COMING-SOON REGISTER IS ONE FILE AND IS HELD TO THE CODE** (9-10-2026). docs/open-items/coming-soon.md lists, one COMING-NNN row each, every statement a person is shown that something is planned, coming, not built or not switched on: where, exact words in guillemets, gate, owner letter, ledger ids. tests/test_the_coming_soon_register_is_well_formed.py checks it is TRUE (format, ids, ledger ids exist, paths exist, a shown row's words are still in its files, switch/flow/claim names exist) and that a filing row uses none of domain.filing_posture.FORBIDDEN_REGISTRATION_CLAIMS (held once; the posture test imports it) and says planned where a registration gates it. House words: coming soon for a product feature, planned plus the gate for filing, not switched on for an owner switch. NOT built: the scan that finds wording with no row. The row is edited in the feature's own commit. The guard is a browser reader: tests_reading_the_browser.py now matches a whole apps/web/... literal. Two rows were on a frozen no-ledger-line set until the ledger lines POST-B-338 and POST-B-339 were added, so that set is empty and the goal is to keep it so.

_Longer design records for this area were moved to `docs/design-record/banking-and-multicurrency.md`, `docs/design-record/workflow-and-team.md`; see the Design record index._

## Scope

**What exists today.** Well past MVP. Shipped and mounted: accounting/GL, GST (GSTR-1/3B/9, 2A/2B recon,
amendments, ITC reversal), TDS, income tax/ITR, payroll (see below), banking and reconciliation,
fixed assets, inventory, year-end and Schedule III, client and employee portals,
relationship/health/lifecycle intelligence, AI copilot and memory, workflow automation,
Tally migration, and prepare-only e-invoice/e-way/XBRL rails.

**What the goal still needs.** The target scope is everything a practice and its clients use in India, enough to
replace every platform on the market (see Goal and context). `docs/open-items/README.md` is the live list of what is
still missing; the list above is only what exists. The last stage is real filing through the portals and live bank
feeds (next section), which wait on registrations only the owner can obtain.

The list above describes what exists. It is not a statement of what may be built: what to build, and in what order,
is decided under the standing instructions at the top of this file. Two things are held back by name, in the next
section.

**Payroll specifically** is walked end to end in
the 1 September 2026 payroll audit (deleted on 8 October 2026; `git show
315e6a19:docs/audits/2026-09-01-payroll-can-it-run-a-year.md`) — what works for a full
year, what does not, and what each remaining gap would cost. The short version:
the monthly cycle, the leaver and the statutory returns all work; what the
software still cannot do is FILE anything, which is deliberate and needs
commercial registrations rather than code.

One rule the settlement makes concrete, because it is easy to get backwards: a
recovery (notice pay, an advance) reduces what the employer PAYS and never
reduces §17(1). Taking notice pay back does not un-earn the salary. The ledger
records what the employer bore; the salary head records what the employee
earned, and the two legitimately differ.

## Not built yet — known, deliberate, and not to be quietly started

Two capabilities the product is expected to grow into. Under the goal they are the LAST STAGE of the build: the
product is not complete until real filing works. Both are recorded here so nobody re-derives them from scratch, and so
nobody half-builds one as a side effect of another task. **Neither is started until the owner starts it by name**: both
need registrations and commercial steps only the owner can take, and nothing in code can stand in for them. Until then
the filing walk-throughs stay simulations.

### Filing to the government portals through the software

Today PracticeSync **prepares**: it computes GSTR-1 and GSTR-3B from the books,
produces the GSTN JSON, and the CA uploads and signs on gst.gov.in. Filing
through the app is intended, and needs:

- **GSP registration.** GSTN's filing APIs are reached through a GST Suvidha
  Provider; there is no direct public endpoint. That is a commercial and
  compliance step, not a coding one, and it gates everything else.
- **DSC / EVC signing.** A return is signed by the taxpayer's digital signature
  or an EVC OTP to their registered mobile. The signature is the taxpayer's, not
  the firm's — so the flow is "CA prepares → taxpayer or authorised signatory
  signs". As with AA consent, **that shape already exists** in
  `routers/engagement_sign_public.py` and should be followed rather than
  re-invented; and as with AA consent, the signing itself happens on the PORTAL,
  never in our UI — an EVC OTP field in this app is a credential capture surface
  whatever it is labelled.
- **The rule in "Code rules" still holds and gets stronger, not weaker.** Never
  auto-submit. Real filing means an explicit confirmation click, per return,
  every time — never a batch, never a scheduler, never a retry that resubmits.
- **Idempotency.** A double-submitted return is not a duplicate row, it is a
  second filing against a live portal. Any real implementation needs the
  reference recorded before the call and checked after a timeout, never a blind
  retry.

**`docs/compliance/07-getting-permission-to-file.md` is the playbook**: what to
apply for, in what order, what it costs, and what each one unblocks. Read it
before starting any of this. Its headline: the Third Party Software Utility
Developer registration that yields `SW########` is self-service and available
now, while ERI, GSP and NIC production credentials are months of commercial
work — and **e-invoice IRN and e-way bill are the only two statutory outputs
software can complete end to end**, because the IRP signs and there is no
taxpayer signature.

Demo filing walk-throughs exist to SHOW these flows before they are real. There
is exactly ONE implementation: the shared filing-demo framework —
`services/filing_demo/` (a flow per statutory filing, GSTR-3B included), served
by `POST /api/filing-demo/{flow}/preview` and rendered by
`components/FilingDemoWizard.tsx`. **Two rivals have been deleted rather than
left beside it**, because two demos of one return drift and each needs its own
safety argument: the bespoke `POST /gst-workspace/gstr3b/{id}/simulate-filing`,
and a browser-side one (`DemoFilingModal` + `lib/filing/demoFiling`) reachable
from `/deadlines`. The second is the cautionary one — it minted the reference
and validated IN THE BROWSER, wrote `demo_filings` over PostgREST so `rbac()`
never ran, and **never called the server, so `ENABLE_FILING_SIMULATION` did not
reach it**: turning the kill switch off left it simulating filings anyway.
`apps/web/scripts/one-filing-demo-and-the-kill-switch-reaches-it.test.ts` holds
the line, and every screen offering the wizard must probe
`fetchFilingDemoCapabilities` first. A demo belongs on the screen where the
RETURN lives, never on the deadline list — a deadline row is not a return.

**Fidelity is a product requirement, and so is disowning the result.** CAs are
being shown these flows to judge whether real filing will be worth switching
for, so each walks the portal's actual sequence — IMS before GSTR-3B Table 4,
GSTR-1A before §37(3), GSTR-9C beside GSTR-9, the §140A challan, the ECR's
wage-month order, SRN-is-not-filed on MCA. And every flow states **what changes
when this is real**, which `envelope()` RAISES without, so the honesty is
structural rather than a reminder; three of them say plainly that no
registration is even waiting, because TDS, PF and ESI have no API to be
granted. **There is no OTP input anywhere in it** — an EVC field in this app is
a credential capture surface whatever it is labelled, and it is also simply
wrong: the OTP is typed on the portal, never in the software that prepared the
return.

They are portal-faithful
in sequence, transmit nothing, write nothing, and every response carries an
honest `SIM-NOT-FILED` reference; any realistic-looking reference they display
is labelled SPECIMEN at the point of display. `ENABLE_FILING_SIMULATION`
defaults **on** — an owner decision of 2026-08-29, reversing the original
default-off, because demo filing is a core product capability and this
deployment records no real filings. The flag is the KILL SWITCH: set it to
`false` on any deployment that records real filings. **When real filing is
built it is a new endpoint and the simulation is deleted** — never repointed at
a live portal, because everything that makes it safe is the fact that it cannot
file.

The genuine path today is unchanged and stays: the CA files on the portal, then
records it here (`PATCH /gstr3b/{id}/status` with `status=submitted`), which
writes the real ARN, the filing date, and the **`public.filings`** row that
`journal_period_lock_reason` reads to lock the period. (There is no
`gst_filings` table — this file said so for a long time.
`services/gst_filing_record_service.py` is the authority.) Until 2026-09-08 no
screen called that endpoint: `lib/data/gst.ts` wrote `status: "submitted"`
straight into `gstr3b_returns` over PostgREST, so `rbac()` never ran, the
backend's `record_filing` never ran either, and **a filed return did not lock
its period**. It now PATCHes, and checks `res.success` — the GST workspace
router answers refusals as HTTP 200 with `{success: false}`, so an unchecked
call showed "Filed" for a request the server had declined.

### Live bank feeds through the Account Aggregator

Fully specified already — see **"Bank data — the Account Aggregator is the only
way in"** above. Nothing about it has been built: statement upload is the only
path in today, and it stays at parity for years regardless.

Restated here only so this list is complete: register as an FIU, go via a TSP,
the consent is the CLIENT's and is time-bound and revocable, and **never
screen-scrape net banking**. Read that section before touching any of it.

**The consent flow's SHAPE is written down and nothing is built** —
`docs/compliance/05-…` §6. It exists so a first attempt does not put an "I agree"
control on our own page: the request, the tokenised link, the expiry and the
audit all follow `routers/engagement_sign_public.py`, and the ONE step that does
not transfer is the approval, which happens at the AA. Six refusals are recorded
there, including never render the approval, never touch an OTP, never treat a
consent as durable (the client can revoke without telling the CA), and never
declare purpose code 102.

_Longer design records for this area were moved to `docs/design-record/filing-and-compliance.md`; see the Design record index._

## Reporting times to the user

- Always state times in IST (UTC + 5:30), never UTC. This applies to everything you tell the user — CI timings, when a job ran, when a check-in fires, timestamps read out of the database. Convert before reporting; don't make the user do the arithmetic.
- This is a PRESENTATION rule only. It does not change what is stored or scheduled: `timestamptz` columns (e.g. `scheduler_runs.started_at`) are UTC on disk, and GitHub Actions cron expressions — including the daily-sweep schedule in .github/workflows/ and any `create_trigger` cron — are evaluated in UTC. Both are correct; rewriting either to "look like IST" would move when jobs actually run.
- So: convert at the point of reporting. When you show a raw query result or edit a cron line, say which zone that value is in, since the stored value stays UTC.
- **A STORED INSTANT AND `ist_today()` ARE NOT COMPARABLE UNTIL ONE OF THEM
  MOVES.** A `timestamptz` comes back from PostgREST in UTC, so `.date()` on it
  is the UTC calendar date; `ist_today()` is the Indian one. From **18:30 to
  24:00 UTC — 00:00 to 05:30 IST the next day** — they are different days, and
  every comparison between them is wrong for those five and a half hours.
  Convert the STAMP (`.astimezone(IST).date()`), never the question: a firm's
  day is the Indian one. Found on 24-09-2026 in
  `recurring_task_service._is_already_generated_today`, where it made the
  idempotency check answer "not generated today" about a config generated
  minutes earlier, so the sweep generated the task AGAIN; and in
  `customer_statement_service.ar_aging` / `vendor_statement_service.ap_aging`,
  where it dated an ageing report YESTERDAY and shifted every bucket boundary.
  ⚠️ **The earlier naive-clock sweep missed all three because it searched for
  `date.today()` and these write `datetime.now(timezone.utc).date()`** — the
  same defect in a different spelling, which is this file's most-repeated
  lesson. And `_as_ist_date`'s string branch does NOT save you: it takes
  `d[:10]`, which is right for a date string and gives the UTC date for a
  timestamp string. Parse to a datetime first.
- **A METRIC AND THE GUARD THAT ENFORCES IT MUST COUNT THE SAME POPULATION.**
  `docs/plan/THE-PLAN.md`'s hex metric is a coarse `grep` over `app/` and
  `components/`; the guard splits three populations, strips comments and honours
  an allowlist. The coarse count read 170 against a recorded 116 and the 19
  September checkpoint wrote that up as a regression — of 54 literals nobody had
  added. An overnight run starting from it would have spent its first hour
  hunting them. When the two disagree, the guard is the authority and the metric
  is the thing to fix.
- **AND A DATE TOLD TO A PERSON OR TO A MODEL IS THE SAME RULE.** `domain/
  ai_copilot_service` opened the copilot's system prompt with
  `f"DATE: {datetime.utcnow().strftime('%d %B %Y')}"`, and four more places told
  the model "REAL DATA AS OF <date>" the same way — so in that 00:00–05:30 IST
  window the model reasoned from YESTERDAY when a CA asked what was due, and
  "the 20th against the 19th" is the difference between due today and due
  tomorrow. **The two questions are separated rather than merged**: an INSTANT
  is `datetime.now(timezone.utc)`, aware, and a DATE a person or a model reads
  is `ist_now()`. Merging them is what would break the other half — `now` in
  that module also built `expires_at`, and an IST-offset string compared against
  a UTC one sorts five and a half hours away from the instant it names, so a
  cached summary would never expire. **`datetime.utcnow()` is banned there and
  is deprecated from Python 3.12** for exactly this reason: it returns a naive
  datetime that only convention calls UTC.
- **A RUPEE FIGURE WRITTEN FOR A PERSON IS GROUPED THE INDIAN WAY, AND THE
  GROUPING HAS ONE IMPLEMENTATION PER LANGUAGE.** `f"{1234567:,}"` is
  `1,234,567`; decision D6 wants **12,34,567**. `domain/money_text.py` is the
  backend authority — `group_indian`, `rupees_paise`, `whole_rupees` — and
  `apps/web/lib/money/format.ts` the browser's, on `Intl.NumberFormat("en-IN")`;
  `shared/money-grouping-vectors.json` pins the two and BOTH suites read it.
  `domain/reporting/pdf_money` re-exports the three and **deliberately emits no
  unit**: ReportLab's core fonts are WinAnsiEncoding and have no U+20B9 glyph,
  so a PDF writes "Rs." and everything else writes ₹ — the grouping is
  universal, the unit is the medium's. **NEVER split a paise value by hand**:
  `f"{p // 100:,}.{p % 100:02d}"` groups the wrong way AND inverts a negative,
  because `//` floors and `%` follows it, so -1 paise prints "-1.99". That was
  live at ten sites, including the email a client's own customer receives.
  `whole_rupees` TRUNCATES toward zero and the browser's `formatWhole`
  deliberately does not — it keeps the paise so an unrounded row shows on a
  return-prep screen — so those two are NOT pinned to each other and the
  fixture says why.
- Worked example: the daily sweep is nominally 06:00 IST = 00:30 UTC. A run recorded as `2026-08-18 01:36+00` is reported as "07:06 IST" — and that hour of drift is GitHub cron lateness under load, which is what the catch-up in jobs/ exists to absorb.

## PDFs — one palette, and it is the product's

`apps/api/services/pdf_style.py` is the only place a PDF colour is decided, and
its values are the `ps.*` and `state.*` tokens in
`apps/web/tailwind.config.ts` — the one palette in this repository with a
recorded contrast audit behind it.

**IT REPLACED FOUR HEADER COLOURS ACROSS SIX DOCUMENTS**: `#0F172A` on the bank
reconciliation and the customer statement, `#1f2937` on the sales invoice and
the payslip, **`#1a3c5e` navy on the year-end pack — the set a CA SIGNS**, and
`#1a1a1a` on the engagement letter, with three body greys beside them. A
practice printing all four in one morning got four documents that looked like
four products, and the one with the most authority was furthest off.

**TWO OF THE CHANGES ARE CONTRAST FIXES, NOT CONSISTENCY.** The invoice's and
the payslip's `small` style was reportlab's stock `colors.grey` — **#808080,
3.95:1 on white at 8pt**, below WCAG 1.4.3 — and it carries the Rule 46
citation, the bank details a customer pays into and the employer's PF and ESI
numbers. The reconciliation drew its tie-out rule in **#94A3B8**, which is the
value `tailwind.config.ts` records moving the hint step OFF at 2.56:1, below
even 1.4.11's 3:1 for a non-text component; `subtotal_rule` is DARKER than what
it replaced, because that line is the one mark saying which figures are being
added and it has to survive a laser printer.

**MAPPING IS BY ROLE, NEVER BY NEAREST HEX.** A "this reconciles" fill is a
READY SURFACE (`state.ready-surface`, #ECFDF5); matching on proximity would
have chosen `state.ready-hover`, which happens to be the #DCFCE7 that was there
and means *a ready row under the cursor* — something a printed page does not
have. A test asserts that specific wrong answer is not taken.

**IT CHANGES NO FONT SIZE AND NO COLUMN WIDTH.** `data_table_style` requires
`font_size` and `padding` with NO defaults, and a test asserts calling it
without them raises: T5a-4b measured the invoice's nine columns against real
worst-case content and found seven too narrow, and a shared module that quietly
renormalised them would re-break exactly that. It also sets no font family
beyond Helvetica — which face carries U+20B9 is an open licence decision, and
this module must not pre-empt it.

**THE GUARD IS ON THE PYTHON SIDE**
(`tests/test_one_pdf_style_and_every_document_shares_it.py`), the Schedule III
caption lesson: one written in `apps/web` would assert the browser against a
copy of itself. It reads source with docstrings stripped (these modules explain
their old palettes in prose), and it has a RENDER limb — a service can import
the module, satisfy every scan, and still paint the old colour through a branch
no scan looks at.

⚠️ **T5a-4's own guard went blind and was restated, not relaxed.**
`test_a_document_that_runs_to_two_pages_says_so` derived "does this table have
a header row" by reading a LITERAL `TableStyle` command list. Moving two
services onto the shared builder left them with no literal, so the guard read
them as headerless and failed them for carrying `repeatRows=1` — their header
rows had not moved. It follows a call into `pdf_style` now. That is the rule
this file keeps having to record: **write the rule, not a spelling of it.**

**Three dead constants went with the conversion** — `_SUBHEAD_BG`, `_BLACK` and
`_DRAFT_RED` in the year-end service, none of them read by anything. The last
is the one worth naming: a constant called DRAFT_RED reads as though the pack
stamps a draft, and it never has.

## Money in the browser — one parser, and only one

`apps/web/lib/money/rupeeInput.ts` turns a typed rupee amount into integer paise
by concatenating the digits, and RETURNS NULL for anything that is not an
amount. Use it for every amount field; there is no longer a second way.

The form it replaced — `Math.round(parseFloat(x) * 100)` — was not merely
imprecise:

- `parseFloat("1,25,000")` is **1**. A CA typing an amount the way Indian
  amounts are grouped recorded one rupee.
- `parseFloat("12abc")` is 12 and `parseFloat("1e3")` is 1000 — neither is an
  amount, both were accepted.
- a blank field gives `NaN`, and `JSON.stringify` sends that as `null`.

**That claim has now been wrong twice, and how it was wrong the second time is
the part worth keeping.** "All 61 call sites across 28 files are converted"
stood here unguarded while **nine more** lived on until 2026-09-08 — the bank
settlement modal (which posts to the GL), the bank match filter, the bank rules
editor, the recurring journal, client billing, the budget grid and the GSTR-2A
import. `components/banking/shared.ts::rsToP` was the reason: it took a `number`
and did `Math.round(rs * 100)`, so every caller had to `parseFloat` first. It
now takes the text as typed and returns null.

Prose was then replaced by **three regexes** — `rsToP(parseFloat`,
`Math.round(parseFloat` and `parseFloat(…) * 100` — and the same claim was
re-made on top of them. Running those three over the tree the next day found
**sixteen more files** none of them matched, because none of them is the rule.
Each names one SPELLING, and the defect has as many spellings as there are ways
to write a number:

```
parseInt(s.replace(/[^0-9]/g, ""), 10) * 100   // "1234.56" -> ₹1,23,456
Math.round(Number(cleaned) * 100)              // "1e3"     -> ₹1,000
Number(whole) * 100 + Number(frac)             // "1.2.3"   -> ₹1.02
```

So the guard is now the RULE rather than a spelling of it, in two directions:
**nothing whose name ends in `_paise`/`Paise`/`_bps`/`Bps` may be built with a
numeric coercion or a multiplication by 100**, and **a function whose own name
says it makes paise out of text must delegate to `lib/money/rupeeInput.ts` by
name**. A cast of a value ALREADY in the unit — `Number(row.tds_paise ?? 0)`,
because PostgREST returns a bigint as a string — is allowed and is the only
thing that is. The three original regexes are kept as a third test because each
of them is a bug that shipped. Against the code of 2026-09-08 the new check
fails on **26 sites across 17 files**; the three regexes passed on every one.

The module also carries
`bpsFromPercentInput` (a typed percentage → basis points) and `parseQuantity`
(up to three decimals, matching `NUMERIC(10,3)` on the line tables), and
`lib/money/lineInput.parseLineAmounts` reads a document line's quantity and rate
together — used by the validator, the preview and the payload, so what a CA is
shown adding up and what is saved are the same numbers.

**One deliberate exception, and the three files that call it — four allowlisted
paths in all.** `gstLine.ratePaiseFromRupees` and `computeLineGst` still take
the rate STRING and still do `Math.round(rate * 100)`, and the three
purchase-note previews still call them that way. `shared/gst-parity-vectors.json` pins those to the Python backend on
exactly those strings — including `"1.005"`, which the backend truncates to 100
paise and which the new parser refuses. Converting to paise and dividing back
would put a float round-trip inside the one calculation that is pinned. What
protects them instead is upstream: `parseLineAmounts` has already refused
anything but a plain decimal by the time they see it.

`parseQuantity` is deliberately NOT named `quantityFromInput` — `gstLine.ts`
exports one of those, which COERCES to 0 and is the parity-pinned payload
builder. Two functions with one name in one directory is how the wrong one gets
called.

**A QUANTITY HAS THE SAME RULE AND ITS OWN GUARD, and the guard is the RULE
rather than a list of doors** (INV-09). Every quantity column in this schema is
`NUMERIC(10,3)` (migrations 050, 188, 210), so a fourth decimal is accepted,
rounded by Postgres, and the money computed from what was TYPED no longer
matches what was stored — which is the Inventory-control tie-out this file makes
load-bearing. `domain/quantity.quantity_violation` is the one rule; the
OPENING-STOCK door did not ask it while five others did, so
`opening_qty_units=1.2345` was accepted where the identical figure on a stock
adjustment was refused. `tests/test_a_quantity_door_asks_the_column_how_many_
decimals.py` derives the door list from the AST — every Pydantic field whose
name says quantity and whose annotation is NUMERIC, so a bool like
`quantity_is_provisional` is not one — checks **per class** (a module-level walk
passes when only one of a create/PATCH pair is guarded, which is exactly what
these two were), and follows **one level of indirection**, because
`models/invoices.py` legitimately factors the check into `_validate_quantity`
and a scan seeing only the direct call would push the next author into copying
it back. On the browser side the importer goes through `toQty`, the helper the
invoice and bill line importers already use, and **`num()` — a bare `parseFloat`
— is deleted**: its last call site gated a receipt's amount on a value it did
not parse, so `"1200abc"` passed at 1200 while `toPaise` returned NaN, and
`NaN <= 0` is FALSE, so the row was built with `amount_paise: NaN`, which
`JSON.stringify` sends as **null**.

## Identifiers

- **GSTIN carries a check digit, and the shape regex does not test it.**
  `apps/api/domain/gst/gstin.py` is the authority; `apps/web/lib/gst/gstin.ts`
  mirrors it for keystroke feedback and the two are pinned by
  `apps/api/tests/fixtures/gstin.json`, which both suites read. Enforced
  wherever a human TYPES a GSTIN — onboarding, and the customer and vendor
  **create, BULK-IMPORT and PATCH** paths. **That list used to say "create
  paths" and the code matched it, which was the defect** (GST-29): a CSV import
  and an edit form are both places a human types a GSTIN, and both were open.
  §16(2)(aa) sends the credit to whoever the GSTIN names, so a valid-shaped
  wrong one hands a customer's credit to a stranger, correctable only by an
  amendment inside the §37(3) window; on the purchase side it is why a bill
  sits in "missing in 2B" for ever while the CA chases the wrong party. The
  bulk paths report it as a per-item error rather than 422-ing the batch, which
  is that endpoint's own design.
  **And on the paths that FILE with one, since GST-29's second half.**
  `domain/gst/validator.GSTValidator.validate_gstin` was a bare shape regex
  and so was `core/validators.validate_gstin` — the one
  `routers/gst_workspace.py` records a filed return through — so a
  valid-shaped wrong GSTIN built the whole GSTR-1 or GSTR-3B and offered it
  for filing under a registration belonging to somebody else. Both delegate
  to `problem_with` now. The CLIENT'S OWN GSTIN is a hard refusal (the return
  is filed under it); the COUNTERPARTY's is REPORTED in the return's own
  exception list, because refusing a whole build for one wrong customer is
  how a CA learns to skip the validator. **`core/validators` no longer holds
  a GSTIN pattern at all** — the pattern is an invitation to answer the
  question the cheap way. `models/parties.CustomerIn` and `VendorIn` read the
  shared function, so the refusal now happens at the MODEL; the bulk path
  builds them inside a per-item `try`, so one bad row is still one row's
  error. **THREE FIXTURE GSTINs WERE CORRECTED, NOT THE GUARD** —
  `27AAAAA0000A1Z5`, `27AABCU9603R1ZX` and `27BBBBB1111B1Z5` all had wrong
  check digits and were used in 77 files, including two frontend
  placeholders that taught a CA an example their own keystroke validator
  rejects.
  **THREE STATE LISTS, DELIBERATELY DIFFERENT, AND A FOURTH THAT IS A PICKER.**
  `domain/gst/validator.VALID_STATE_CODES` is for a PLACE OF SUPPLY and
  includes **96** (outside India, where an export goes) and not 99;
  `domain/gst/gstin.VALID_STATE_CODES` is for the first two characters of a
  GSTIN and is the other way round, because a GSTIN is a registration in a
  state and nobody is registered outside India;
  `core/validators._VALID_STATE_CODES` is a REGISTRATION's state for the firm's
  own profile and an internal client, so it holds both. Collapsing any pair
  would either refuse every export or accept a GSTIN that cannot exist. **The
  third was reported as dead and is not** — `validate_state_code` and
  `derive_state_code` read it, and `routers/practice` and
  `internal_client_service` read them — so `core/validators` now NAMES all
  three beside the one it declares, which is where a fourth would be added.
  `apps/web/lib/constants/indianStates.ts` is not a validator at all: it is the
  PICKER, and it deliberately omits the DEAD codes 25 and 28, because they may
  not be chosen for a NEW document while a historical one must still parse.
  **A PARTY'S OWN `state_code` IS THE SECOND LINK OF THE PLACE-OF-SUPPLY CHAIN
  AND HAD NO RULE ON IT AT ALL.** Both halves of the resolver returned it as
  stored, while the GSTIN branch four lines below has always been gated with a
  comment saying "so a truncated or garbage value cannot become a place of
  supply" — and no door refused one, although the identical value typed into
  `SalesInvoiceIn.place_of_supply` has been refused for months. So an invoice's
  CGST+SGST-against-IGST split ran off an unvalidated field.
  `models/parties._state_code_problem` refuses it at all FOUR doors (create and
  PATCH, customer and vendor — a validator on one door is one PATCH from being
  none) against the PLACE-OF-SUPPLY list, because an export customer's state IS
  96. The RESOLVER falls through instead of raising: it is a fallback chain, an
  unusable link is what the next one is for, and that also repairs rows written
  before the door existed or straight over PostgREST.
  Deliberately still NOT in `models.client.validate_gstin`, which guards a
  Pydantic field that 512 invented fixture GSTINs across 95 files flow through.
  Closing the bulk door showed how load-bearing that carve-out is:
  `test_customer_bulk_create`'s own fixtures both ended in `5`, so the import
  path had only ever been exercised with GSTINs the portal would reject. The
  fixtures were corrected, not the guard relaxed.

- **A UAN and an IFSC are format-checked at every door; an ESIC number is
  not, and that is a decision.** Both patterns live once, in
  `domain/payroll/identity.py` — `UAN_RE` (12 digits, EPFO's own format) and
  `IFSC_RE` (RBI's four letters, `0`, six alphanumerics). They already existed
  in `employee_import.py` (which refuses a whole file) and `ecr.py` (which
  refuses a member at file build); what had no check was the API, so a UAN
  typed on the form was stored and wedged the ECR months later, at the moment
  the CA was trying to file. `EmployeeIn` and `EmployeeUpdateIn` both validate
  now — a validator only at the create door is one PATCH from being none.
  **`esi_number` stays a presence check**: nothing in this codebase validates
  its format anywhere, no length is confirmable here, and a pattern written
  from memory would refuse legitimate numbers for every client. Same judgement
  as the EPF establishment code, the LIN and the state PT slabs.
- **A YEAR PICKER IS DERIVED FROM THE CLOCK, NEVER LISTED** —
  `lib/dates/periods.financialYearChoicesAround` for a financial year and
  `assessmentYearChoicesAround` for an assessment year, the second DERIVED FROM
  the first (IT Act §2(9) with §3: AY = FY + 1) rather than parsing the date
  again. Two functions each working out "the current year" are two controls
  that can describe different periods.
  `scripts/a-financial-year-choice-comes-from-the-clock.test.ts` is the guard,
  and its own history is the lesson: it forbade `<option value="2025-26">` and
  nothing else, so twelve more screens spelled the same defect as
  `const FY_OPTIONS = ["2025-26", …]` and **eight of them ended at a year
  already past**. It now matches the array form too, and strips comments first.
- **A financial-year label is a TYPE, not a `str`.** Annotate every route
  parameter and request-model field that takes one `FYLabel` (or
  `OptionalFYLabel`) from `apps/api/models/fy.py`;
  `core.ist_clock.normalise_fy_label` is the authority. It accepts `YYYY-YY`
  and `YYYY-YYYY`, canonicalises to `YYYY-YY`, and refuses a second half that
  does not follow the first — which a shape regex cannot: `2026-28` passes
  `^\d{4}-\d{2}$` and then means 2026-27, because `fy_bounds` and the older
  private parsers read the first four characters and ignore the rest. That is
  a wrong return, not a rejected request.
  `tests/test_fy_labels_are_validated.py` fails if a new one goes in bare.

  **`fy: FYLabel = Query(...)` validates NOTHING.** FastAPI builds the field
  from `Query()` in the default position and discards the Annotated metadata
  carrying the validator — silently, so the endpoint reads as guarded. Write
  `Annotated[FYLabel, Query(...)]` instead (add `= ...` where argument order
  needs a default). Pydantic's `Field()` in the default position does NOT
  behave this way, which is what makes the assumption easy.

  `fy_bounds` stays deliberately lenient: it is a domain function whose caller
  already knows the label is a label, and several callers depend on that.
  Strictness belongs at the boundary.

  **AN ASSESSMENT YEAR IS THE SAME RULE AND HAS ITS OWN TYPE.** `AYLabel` /
  `OptionalAYLabel` were written in the same sweep and exactly one router used
  them, so six boundary fields still took an AY as a bare `str` and `2026-28`
  meant 2026-27 there for the same reason — while
  `tests/test_fy_labels_are_validated.py` scanned only `financial_year`, which
  is the "a guard states one spelling of its own rule" shape that file's own
  header warns about. It scans both families now, with a per-family vacuity
  floor (one combined floor would have stayed green on the fifty-odd FY entry
  points alone). **The two are NOT interchangeable and a test says so**: both
  validate identically, so only the NAME keeps them apart, and AY 2026-27 is
  FY 2025-26 — a route that muddles them reconciles the wrong statement
  against the wrong return.

_Longer design records for this area were moved to `docs/design-record/identifiers.md`; see the Design record index._

## A screen says what it read, what it did not, and what it will not do

Five small rules from the 30-09-2026 sweep, each with a guard, and all of them one
shape: **an unknown is never rendered as a value, and a label never promises more
than the code does.**

- **A STORED GST RATE IS NEVER ROUNDED ON THE WAY INTO A SCREEN** (GST-01/02). Six
  editors loaded `gst_rate_bps` with `Math.round(bps / 100)` and the sales invoice saved
  with `parseInt`, so 7.5% reopened as 8% and 1.5% as 2%, and a re-save wrote the wrong
  tax into GSTR-1 and GSTR-3B. `lib/invoices/gst.gstRateToPercent` divides and never
  rounds (it is NOT named `…FromBps`: `every-amount-field-uses-the-one-parser` reads a
  name ending in `Bps` that takes a string as a paise maker), and `gstRateOptions` adds
  a stored rate that is not on the list to the dropdown instead of losing it. The list
  carries 40% (IGST §5(1), from 22-09-2025, `[S]`) beside the 12% and 28% that
  documents before that date still carry. `shared/gst-parity-vectors.json` gained seven
  vectors, **appended** — the `documents` vectors select cases by POSITION.
- **AN UNVERIFIED YEAR SAYS SO IN WORDS, AND PAYROLL ASKS IT** (TDS-INCOME-TAX-19,
  PAYROLL-09). `statutory_rates.fy_rate_gap` is the one sentence, in two kinds — a
  year the registry does not hold (a substitution) and one it holds but has not read
  against its Finance Act (carried forward) — and `itr_engine._stamp_rate_provenance`
  and `routers/payroll._withholding_rate_gap` both take it from there. **Consequence
  worth knowing: while FY 2026-27 is unverified, every payroll run for that year
  carries a statutory gap, so finalising needs the typed reason the release path
  already demands.** That is the finding's own design, not a side effect; verifying the
  year (a human step, `docs/compliance/`) turns it off, and the gap is recomputed at
  release so the draft need not be rebuilt.
- **THE PUBLIC SITE IS HELD TO THE CODE FROM THE PYTHON SIDE**
  (`tests/test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py`; the
  marketing app has no test runner). MFA is required of Partner and Manager on the routers
  that carry `mfa_guard`, not "every sign-in"; the audit log records changes, not views;
  the database is in Mumbai, the API in Singapore, and AI calls leave India; the Tally
  importer writes customer and vendor masters only (the Migration Center's copy is built
  from `lib/migration/writtenTypes.ts`, pinned to `WRITTEN_ITEM_TYPES`); no ITR JSON or FVU
  file is produced; a client cannot upload to the portal; TDS return dates are
  Q1 31 Jul · Q2 31 Oct · Q3 31 Jan · Q4 31 May, asserted against `compliance_engine`. The
  TDS certificate screen **records** a register row and says the certificate comes from
  TRACES; the returns screen offers "the prepared figures", not an e-filing upload.

_Longer design records for this area were moved to `docs/design-record/screens-and-site.md`; see the Design record index._

## Bug fixing

- When the user reports a bug, don't just patch the one instance. Identify the underlying pattern (wrong column name, missing null check, stale label, unapplied migration, etc.) and grep/search the rest of the codebase for the same pattern before calling the fix done. Report what else was found, even if you decide not to touch it.

## Commit messages

Match the existing history. A commit explains **what was wrong**, **what the fix does and
why that shape**, and **how it was verified** — including how many new tests fail against
the previous code (the negative control). State when a change has no live effect yet, and
say so explicitly when there is no migration. Subject line is a plain sentence describing
the behaviour change, not a conventional-commits prefix.
