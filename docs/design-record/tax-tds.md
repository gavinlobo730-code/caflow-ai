# Design record: TDS and TCS: sections and thresholds, the 2026 vocabulary fork, interest, 26AS

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Indian tax domain rules — never violate these

- **From 01-04-2026 the whole TDS vocabulary changed, and `domain/tds/vocabulary.py` is the single place that knows it.** The Income-tax Act 2025 with the Income-tax Rules 2026 (CBDT Notification 22/2026, 20-03-2026, G.S.R. 198(E), plus a corrigendum) renumbered the statements — **24Q→138, 26Q→140, 27Q→144, 27EQ→143** — and the certificates — **Form 16→130** (three parts now), **16A→131** (quarterly now), **26AS→168**, **15G/15H→121**. It also collapsed the sections: **192→392**, the whole **194-series→393(1)**, **195→393(2)** (NOT 400 — one widely-copied source has that wrong), TCS→394, and returns now carry numeric payment codes 1001–1067. **Rates and thresholds are unchanged**, so `section_rates.py` holds right numbers under 1961-Act keys — and it stays that way. **This is a FORK, not a migration.** The transition is **by EVENT — credit or payment, whichever is earlier** — so periods up to 31-03-2026 keep the old forms and sections indefinitely, including belated and revised returns; both vocabularies are permanent. `act_for_date` is the definition and `act_for_fy` is derived from it, sound because commencement is exactly an FY boundary. **Translate at the boundary, never rekey a store**: ask the module where a form number or section code is emitted, and leave every rate lookup, stored challan and test on the 1961 keys. **There are TWO such boundaries on a quarterly statement and for a while only one was translated** — `tds_return_service` resolved the FORM through the vocabulary and left every deductee line's `section` as stored, so a FY 2026-27 26Q came back as Form 140 with each line citing 194J, a section that Act does not contain (TDS-17). The label now goes out as `section` and the stored 1961 code travels beside it as `section_1961`, which is load-bearing rather than decorative: s. 393(1) has no reverse, so a reader given only the label cannot recover the section that produced it — and `lib/data/tds.ts` writes the whole payload into `tds_returns.fvu_json`. A section the 2025 Act has no code for (s. 192A, say) keeps its stored code and is named in `statutory_gaps`; it is never guessed into 393(1). Challan matching accepts BOTH labels in every period — a challan records what somebody typed, not which Act governs the quarter. Three refusals are deliberate: the **s. 393 payment-code table is not FULLY held** (a wrong code is accepted and then wrong — a human step, like the ITR schemas — see the next bullet for what changed), **s. 393(1) has no reverse**, and **a form cannot be asked for without a period**. ITR-1..7 are NOT renumbered — AY 2026-27 is still the 1961 Act. Verified 2026-09-04; see `docs/compliance/03-income-tax-and-tds.md`.

- **A CONFIRMED SUBSET OF THE S. 393 PAYMENT-CODE TABLE IS NOW HELD** (25-09-2026), from a **primary source**: the file-format specification Protean (formerly NSDL) publishes for the RENUMBERED statements themselves (Form 138/140/144, current version, "for Tax Year 2026-27 onwards"), whose own Annexure 2 tables state "Nature of Payment | Section | Section code to be used in the return" against every s. 393 table entry — a `[P]`-graded read of the government's own document, the same grade GST-32's IRP validations carry, not the Act's text and not a search-engine summary of either. `domain/tds/vocabulary.payment_code_for()` answers fourteen of the sections `section_rates.py` already holds: s.192 (by a stated default — non-Government, since no client here is modelled as a government department), s.193, s.194, s.194B, s.194C (by which rate applied — its own two rows split on exactly `TDSSectionRule`'s individual/company rates, so no new fact is needed), s.194D, s.194G, s.194H, s.194I(a)/(b), s.194J(a), s.194LA, s.194Q, s.194T. **Several sections turned out to split FURTHER under the new table on a fact no rate difference had exposed**, and recording either half would be the exact guess this module exists to refuse: s.194A splits into three codes by the payee's age and the payer's kind, none of which this registry's single rate distinguishes; s.194J(b) — the professional-fee limb — shares its own citation (Table Sl. No. 6(iii).D(b)) with a DIRECTOR's remuneration under a DIFFERENT code, and s.194J(b) cannot tell a professional fee from a director's fee apart. Both stay named gaps. `payment_code_gap()` still names the whole table's incompleteness at the return level; `Vocabulary.payment_code()` is the per-line answer where one now exists, and it IS wired onto the 24Q/26Q/27Q deductee rows since TDS-INCOME-TAX-31 (`domain/tds/deductee_payment_code.py`; that bullet says which sections get a code and which are named gaps).

- **THE RPU/FVU FILE ITSELF IS NOT BUILT, AND THAT IS A DECISION, NOT A GAP LEFT
  OPEN BY ACCIDENT** (TDS-16, 25-09-2026). The natural next step after a 24Q/26Q/27Q
  statement is computed is a file a CA can run through NSDL/Protean's File
  Validation Utility (FVU) and upload — and a dedicated research pass could not
  reach the primary specification at all: this environment's egress is blocked
  broadly enough that even a search summarizer's own referenced pages
  (`incometaxindia.gov.in`, `docs.oracle.com`, `en.wikipedia.org`) all failed
  `EGRESS_BLOCKED`. Every fact recovered is `[S]`-graded at best, and what it
  recovered was evidence the field list is **actively changing for the exact
  filing period this product would target**: RPU/FVU version 1.1 (Forms
  138/140/143/144, Tax Year 2026-27) reportedly removed three Challan Detail
  fields that version 1.2, released weeks later, partially reinstated under
  different names. Writing a byte-exact serialiser against a format
  demonstrably moving, from nothing better than a search engine's summary, is
  the "low-confidence guess dressed up as a specification" this file's own
  discipline refuses everywhere else — a wrong field position gets the WHOLE
  statement rejected by the FVU. **What the same pass DID corroborate** — the
  format is caret (`^`)-delimited, never comma-separated or fixed-width, with a
  strict File Header → Batch Header → Challan Detail → Deductee Detail
  hierarchy, matching what `domain/tds/challan_mapping.py` already assumed —
  is what `domain/tds/keying_sheet.py` uses instead: it takes the ALREADY
  COMPUTED figures the three `tds_return_service.py` builders produce and
  groups them under that confirmed hierarchy, so a CA keys them into the real
  RPU screens in the right order, the same posture `domain/income_tax
  /keying_sheet.py` (IT-17) already takes for the ITR. **It derives nothing and
  never claims to be the government's own file** — `NO_FVU_FILE_IS_PRODUCED` is
  on every sheet's own `gaps`. Closing this for real needs a human to download
  `tinpan.proteantech.in`'s current XLS/PDF specs with an ordinary browser (not
  blocked for a human, only for this sandbox) and round-trip a real writer
  through an actual FVU run before it is trusted — see
  `docs/compliance/03-income-tax-and-tds.md` §4.

- **A TDS threshold is a TRIGGER, not a deductible allowance, and most of the
  §194 series aggregates over the year.** §194C(5) charges where "the aggregate
  of the amounts of such sums credited or paid ... exceeds one lakh rupees", and
  §§194A/194D/194G/194H/194J carry the same "aggregate of the sums" limb. So
  crossing the limit does not exempt the earlier payments — it makes them due,
  and the charge is on the WHOLE aggregate. The bill that crosses carries the
  year's tax; every bill after it credits what was already withheld (§200), or
  the same aggregate is taxed again and again. `domain/tds/section_rates.py`
  holds which sections have an aggregate limb and `resolve_tds` takes BOTH
  `fy_prior_taxable_paise` and `fy_prior_tds_paise` — a caller passing the first
  without the second re-charges the growing aggregate on every later bill.
  **§194I and §194B deliberately have no aggregate**: §194I's limit is per month
  or part of a month, and FA 2025 made §194B per single transaction, so an FY
  aggregate on either would deduct where the statute does not charge.
  **§194Q is the one section charged on the EXCESS** — §194Q(1), "0.1 per cent
  of such sum exceeding fifty lakh rupees" — carried on the rule as
  `charge_on_excess_only` so the engine never tests a section by name. Its ₹50
  lakh is both limbs at once ("the value OR AGGREGATE OF SUCH VALUE"). What this
  engine does NOT decide for §194Q is whether it applies: the first proviso
  binds only a buyer whose own turnover exceeded ₹10 crore in the preceding FY,
  and no client turnover figure reaches it — the CA marks the vendor.

- **A FIRM PAYING ITS OWN PARTNER DEDUCTS UNDER §194T, AND A SECTION WITH NO
  RESIDENT LIMB IS A THIRD STATE** (TDS-23). §194T was inserted by the Finance
  (No. 2) Act 2024 w.e.f. 01-04-2025 — `section_rates.py`'s FIRST year, whose
  header claims that very Act — so its absence was a hole in a year marked
  `verified=True`, and every partnership and LLP client has the obligation.
  10%, **both limbs at ₹20,000** ("such amount OR THE AGGREGATE"), NOT on the
  share of profit (§10(2A)), and `SECTION_194T_FIRST_FY` names the
  commencement so a later FY 2024-25 entry cannot back-date it.
  **`domain/tds/residency` now has THREE lists, not two.** The first two answer
  one question — do the section's own charging words limit it to a resident —
  and §194T's do not ("to a partner of the firm"), so it cannot join
  `RESIDENT_ONLY_SECTIONS`, whose every entry quotes the limitation it is
  listed for. `SECTIONS_REACHING_NON_RESIDENTS` would assert something else
  again: that 10% flat on a 27Q row is RIGHT, when §195 charges the rates in
  force with surcharge and cess and no threshold — 10% is the SMALLER figure
  and an under-deduction disallows the whole expenditure under §40(a)(i). So
  `SECTIONS_UNSETTLED_FOR_A_NON_RESIDENT` REFUSES it with the reason, **asked
  BEFORE the resident-only lookup**: a section in it is by construction absent
  from that map, so falling through reaches the deliberate silence for
  unclassified sections and would allow the deduction. **§194R stays out and
  says why** — its routing is fine, but whether the Finance Act 2025 moved its
  ₹20,000 could not be confirmed here and the benefit is often IN KIND, a base
  no bill line holds. §194-IA/§194-IB/§194M stay refused for the probe pass's
  reason: Form 26QB/26QC/26QD are challan-cum-statements this product does not
  produce, and `return_type_for` routes on residency alone against migration
  014's four-value CHECK.

- **§206C IS IN THE TDS REGISTRY AND A VENDOR MAY NEVER CARRY IT.** TCS is tax
  COLLECTED by a seller from a buyer and reported on **Form 27EQ**; the
  registry entry exists as reference data and says so in its own comment
  ("do not assume TCS is an implemented feature because a rate exists here").
  Nothing refused it until 12-09-2026 and the supplier screen's section
  dropdown is served straight from the registry, so a vendor could be marked
  §206C and every bill from them withheld 0.1% of the WHOLE amount — the
  entry's threshold is ZERO — with the row stamped 26Q, because
  `residency.return_type_for` routes on RESIDENCY and never sees the section.
  Three things wrong at once: on a bill you are PAYING there is nothing to
  collect, 26Q is the wrong return, and no TCS path computes it.
  `deduction_section_refusal` is the one place that decides this (§192 is the
  other refusal), and `GET /api/tds/sections` serves its answer as
  `vendor_eligible` so a screen cannot keep a second exclusion list.
  **AND §206C(1H) CEASED TO OPERATE FROM 01-04-2025** — the seller no longer
  collects on receipts above ₹50 lakh and the BUYER deducts under §194Q, so the
  overlap is resolved in §194Q's favour and Form 27EQ / Form 27D for this item
  fall away. The registry's comment said "unchanged, 0.1%" for a year after
  that (SALES-32). The 0.1% ENTRY STAYS at its historic rate, because a belated
  or revised 27EQ for FY 2024-25 is filed at it — the fork shape again — and
  the cessation is `section_rates.SECTION_206C_1H_CEASED_FROM_FY`, a named
  constant like `SECTION_206AB_OMITTED_FROM_FY` and NOT a `rate_gap` (that
  field means "this limb's own rate is not held", and a test holds it to
  exactly that). ⚠️ `[S+]`, and the EFFECT is cited rather than the mechanism:
  most sources say the sub-section was omitted, one reads the Finance Act 2025
  as inserting a proviso that leaves the text in the Act and makes it
  inapplicable. Identical from 01-04-2025, different textually.

- **What being late costs is `domain/tds/interest.py`, and "month or part of a
  month" is NOT the same arithmetic there as in §234A.** §201(1A) has two
  limbs, two rates and two clocks: (i) 1% per month or part from the date tax
  was DEDUCTIBLE to the date DEDUCTED, (ii) 1.5% from the date DEDUCTED to the
  date PAID OVER. Limb (ii)'s clock starts at the deduction, not the Rule 30(2)
  due date — so tax deducted 25 June and deposited 8 July is one day late and
  carries TWO months, 3%. The Rule 30(2) date decides only WHETHER there is a
  default. §234E is the odd one: ₹200 a DAY, capped at the statement's own tax,
  payable before the statement can be delivered (§234E(4)) — counting it in
  months makes it thirty times too small, and it used to live only inside
  `services/filing_demo/tds_return.py`, which transmits nothing. ⚠️ The
  month convention is `[S]`-graded: §234A counts a PERIOD (anniversary to
  anniversary, which is what
  `advance_tax_interest_engine._months_or_part` does and is right there),
  while §201(1A) is administered on CALENDAR months — 30 June to 1 July is two.
  Egress is refused here so neither could be confirmed, and the calendar count
  is never smaller, so the error direction cannot understate a deductor's
  exposure. Two refusals: tax **never deducted** has no end date for limb (i)
  (the proviso to §201(1) runs it to the date the PAYEE filed), and an unpaid
  deduction with no as-at date gets a sentence rather than a figure.

- **§194I AND §194J EACH CHARGE TWO RATES, AND BOTH ARE NOW HELD** (TDS-22,
  closed 25-09-2026). §194I charges rent of plant, machinery or equipment at a
  lower rate than rent of land, buildings or furniture; §194J charges fees for
  technical services at a lower rate than professional fees. `domain/tds/
  section_rates.py` holds one key per section plus four clause limbs —
  `194I(A)`, `194I(B)`, `194J(A)`, `194J(B)` — and **all four are complete**:
  the (b) limbs carry the rate the registry already held (land/building/
  furniture rent, and professional fees), and **the (a) limbs now carry their
  own confirmed 2%**, read directly from the bare text of both sections on
  incometaxindia.gov.in (Income-tax Act, 1961) — a `[P]`-graded primary source,
  not a recollection: "two per cent for the use of any machinery or plant or
  equipment" (§194-I(a)) and "two per cent ... in case of fees for technical
  services (not being a professional service)" (§194J(1)), against 10% for the
  other limb of each. Neither limb carries a `rate_gap` any more.
  **THE BARE SECTIONS STILL WARN, and the warning's job changed.** A payment
  recorded under the bare "194I" or "194J" — no clause chosen — still cannot
  tell which limb it is, so it withholds at the higher rate by default
  (over-deducting is the recoverable direction: an excess is the payee's to
  reclaim, while an under-deduction disallows the whole expenditure under
  §40(a)(ia)). The `rate_gap` on the bare section now NAMES the confirmed 2%
  and 10% and tells the CA to record the clause to get it directly, rather
  than saying the rate is unheld.
  **NOT MODELLED, and named rather than guessed**: §194J's proviso also cuts
  the rate to 2% for a payee whose business is *only* operating a call centre
  — a fact about the payee's business, not a clause of the bill, and this
  registry carries no payee-level facts of that kind.
  **The clause CODES are a primary source inside this repository** — the ITD's
  own ITR-6 AY 2026-27 schema, `domain/income_tax/schemas/ITR6_2026_Main_V1.0.json`,
  enumerates `4-IA:194I(a)`, `4-IB:194I(b)`, `94J-A:194J(a)`, `94J-B:194J(b)` —
  which is what removed the recorded objection that "an invented code on a
  statutory return is worse than the over-deduction it would fix". A test
  asserts them against that file, so a later schema version that spells them
  differently fails rather than drifts.
  **THE KEYS ARE UPPER CASE and that is load-bearing**: every lookup in the
  module is `.upper().strip()`, so a lower-case key is never found and the
  failure is SILENT — `parent_of()` falls through to returning the key
  unchanged, the FY aggregate quietly becomes per-clause instead of the
  section's, and the withholding drops below what §194J's proviso charges.
  Two things must therefore never test a name and always ask `parent_of()`:
  the FY aggregate, and challan matching (a CA types "194J"). §197 eligibility
  asks it too — `GET /api/tds/sections` resolves the parent before checking
  `SECTIONS_197`, because §197(1) names sections and telling a CA their
  plant-hire payment cannot carry a certificate *because they said which kind
  of rent it was* would be a defect created by adding the limb.

- **A SECTION THE ENGINE CANNOT ANSWER FOR IS REFUSED WITH ITS OWN REASON, AND
  THE REASONS ARE NOT INTERCHANGEABLE** (TDS-23). `deduction_section_refusal`
  is the one place that decides it, and what a CA has to go and do differs per
  section — a shared "no rate held" paragraph says the wrong thing about most
  of them. **§192** computes a silent nil, **§206C** is TCS collected by a
  seller, and **§194N is the third DIRECTION refusal**: it is charged on a
  banking company, a co-operative bank or a post office on cash the ACCOUNT
  HOLDER withdraws, so on a bill your client is PAYING there is nothing to
  withhold — when it bites the client is the **deductee** and the credit
  appears in their Form 26AS. Saying only "no rate held" there would invite
  somebody to add one. **§194R, §194O and §194S are refused on the BASE as much
  as the rate**, and each carries its own sentence in
  `_SECTIONS_WITH_NO_FIGURE_AND_THE_REASON`: §194R's benefit is often in kind,
  §194O's base is the *participant's* sale rather than any bill the operator
  receives, and §194S has no virtual-digital-asset document at all — with
  §194S(2) requiring the tax paid before consideration in kind is released.
  **§194-IA/IB/M stay refused** because Form 26QB/26QC/26QD are
  challan-cum-statements this product does not produce. A test asserts the
  three answers are DIFFERENT, on the answers rather than on the data, so
  moving a reason in or out cannot make it vacuous.

## From CLAUDE.md section: GSTR-2B reconciliation — the books are read in `apps/api`, and the answer is kept

- **The 26AS reconciliation is the same rule and had the same defect
  (TDS-21).** `POST /tds-workspace/form26as/upload` asked the caller for BOTH
  sides — `raw_data.tds_entries` AND `raw_data.book_deductions` — with the tab
  a textarea saying so, while the register sits in `tds_deductions`. It reads
  the register itself now; a `book_deductions` key still sent is ignored and
  named in `ignored_request_keys`. **`domain/tds/deductor_26as.py` is the
  matcher and is deliberately NOT
  `domain/income_tax/form26as_matcher.py`**: that one is the
  client-as-DEDUCTEE direction, keyed on the DEDUCTOR's TAN or name, and this
  is client-as-DEDUCTOR, keyed on the DEDUCTEE's PAN and section. Reusing it
  would put a deductee's PAN in a field named `deductor_tan` and emit outcome
  sentences about the wrong party. What both share is the discipline —
  exact-amount pass before any variance pass, every pass CONSUMES, and totals
  over the FULL population on each side — and that is stated in each. The old
  code was a `{(pan, section): entry}` dict comprehension: it kept one 26AS row
  per identity, matched it against any number of book rows, and had **no
  26AS-side leftover bucket at all**, so a portal row the register was missing
  was never reported. A deduction with no deductee PAN is its own named bucket
  rather than matched — 26AS is keyed on the PAN, and pairing two blank-PAN
  rows on section and amount is the guess §206AA exists because nobody should
  make.

- **NOT EVERY PART OF FORM 26AS IS A CREDIT, and the client-as-DEDUCTEE
  reconciliation used to sum all of them.** `_PART_RECORD_TYPE` in
  `domain/income_tax/form26as_service.py` names each part and
  `CREDIT_RECORD_TYPES` says which count: **A / A1 / A2** is TDS deducted FROM
  the client and **B** is TCS collected from them (§206C(4)) — both credits;
  **C** is advance and self-assessment tax the client PAID THEMSELVES, **D** is
  a refund already received, and **F** is §194-IA tax the client deducted as
  BUYER of property. Those three are real facts and not TDS credits, so
  including them made 26AS exceed the book register by exactly the advance tax,
  for every client who paid any, every year. `split_by_credit` keeps the first
  two in the comparison and reports the rest as `not_a_tds_credit` — set aside,
  never dropped, and rendered on the screen. Two traps. **A2 and F point
  OPPOSITE ways** — seller and buyer of the same §194-IA — so the audit
  finding's own fix of filtering "A2/F" together would drop a genuine credit,
  and they are deliberately kept apart; the parser cannot in fact tell A2 from
  A (`PART\s+([A-Z])` keeps one letter), which is safe only because all three
  are credits. And **the extras are merged into the RETURN, never into
  `summary`**, because `summary` is spread straight into the
  `form_26as_reconciliations` INSERT — a key that is not a column of that table
  fails on the live database and passes in mock mode, which is the exact shape
  migration 291 was written to repair on this same table.

- **A TDS STATEMENT IS FILED ON A DATE THE CA STATES, FROM CA APPROVED, STAYS FILED, AND CLOSES ITS QUARTERLY OBLIGATION** (found by driving the TDS doors for the demo firm, 19-10-2026). Five defects on `PATCH /api/tds-workspace/returns/{id}/status`, each reproduced over a real database. (1) `filing_date` was free text stored into `filed_at`: `2999-01-01` was recorded as the day of filing, and the screen's "Mark as Filed" modal sent no date at all, so the stamp was the instant the button was pressed, which is not the day the CA filed on the portal and is the day the late-filing fee and the calendar turn on. It is a required, never-defaulted, real date not in the future (`compliance_record_service.clean_filed_date`, the rule the GST and ITR doors apply, with the field named `filing_date` in the sentence) and not before the quarter the statement reports on has ended, a check the explicit `acknowledge_incomplete` override skips because that override exists to record what the product would otherwise hold back. THE DOOR JUDGES IT AND ANSWERS `success: false` WITH A SENTENCE (`_the_filing_date`), not as a validation error on the request model: the independent review ran the first version, and a future date came back as the framework's raw 422, which carries no `error` and reached the screen as a bare "Failed to mark as filed". It is stored as midnight UTC spelled out (`2025-10-28T00:00:00+00:00`), which is 05:30 IST on the same day, so the UTC date and the Indian date of the stored instant agree whatever time zone a session runs in. The modal asks for it, starts it blank for every statement (opening it, computing another statement, a client change and a successful filing all clear the PRN, the acknowledgement number and the date, the review having found them carried over from the last statement), bounds the box at today as a hint, and shows its own refusals inside the dialog, because the page's error callout sits under the backdrop while it is open. (2) A pending or prepared statement could be taken straight to filed on the request's own `ca_approved` flag, so a filed statement could carry no approver and no approval time; a statement is now filed from CA approved only, which is where the screen already offered it. (3) A filed statement could be moved back to pending or prepared, leaving a PRN and a filing date on a statement the screen then called unfiled, while `_revise_tds_return` has always said a filed statement is final here and a correction is a correction statement on TRACES; `_TDS_RETURN_FURNISHED` is asked now by this door as well. (4) An update that matched no row (the statement removed or changed in the meantime, or the caller's row security refusing the change: PostgREST answers all three with an empty list) was answered `{}` as a success with the audit row and the timeline entry written; it is a refusal and writes nothing, and the update is conditional on the status that was READ, so two requests to mark one statement filed (a double click) cannot both pass the checks and have the second overwrite the first's PRN. (5) Recording the PRN moved `tds_returns` and left the calendar's obligation Not Started. `services/tds_return_closes_obligation` closes the client's `TDS24Q`, `TDS26Q` or `TDS27Q` obligation for that quarter (compliance type `TDS`, the quarter's own first and last day from `domain/tds/section_rates.quarter_dates`, the one quarterly calendar the due dates and the stored `quarter_end` already read, keyed on the statement's ROUTING KEY and not on the Act's form number, which changes from FY 2026-27) THROUGH `mark_filed` via `services/obligation_closure`, with the stated date and the PRN, for a caller who may write Compliance (per person), never touching an obligation already Filed, and never failing the recording; its sentences name the statement as the calendar's own title does (`TDS 26Q Q2 FY 2025-26`, `TDS 140 Q1 FY 2026-27`, from `vocabulary_for`); the response carries `compliance_obligation` and the TDS returns screen shows the server's sentence through `lib/compliance/obligationNote` when the calendar was left open. **WHAT IT DELIBERATELY DOES NOT CLOSE**: the monthly deposit obligations (`TDS_NON_SALARY_DEPOSIT`, `TDS_SALARY_DEPOSIT`), because a statement reports deposits and is not one, and a month can carry several challans under several sections; and Form 27EQ, which has no obligation on the calendar to close (the answer says so). Both are on the ledger (POST-A-267). `tests/test_a_tds_return_is_filed_on_a_stated_date_and_closes_its_obligation.py` pins the closer's codes to `compliance_obligation_service._tds_obligations` and its windows to the generator's own, so a code or a quarter renamed there cannot leave this closing nothing. Deliberately NOT done: the door still answers its refusals as HTTP 200 with `success: false`, which the screen reads, because changing the contract is its own change; a statement with unresolved `validation_errors` (a deduction with no challan recorded, say) can still be approved and filed, because the CA may have deposited outside this product and decides.

- **THE TDS DEPOSIT WORKSHEET ASKS THE CHALLAN REGISTER WHAT HAS BEEN DEPOSITED, AND A DEPOSITED DEDUCTION'S INTEREST STOPS AT ITS CHALLAN'S DATE** (found by seeding the demo firm's challans, 19-10-2026). `GET /api/tds-workspace/deposit-due` (`domain/tds/deposit_due.py`) read "deposited" from two columns of each deduction row, `challan_date` and `status`, which `tds_deductions` has carried since migration 014 and which NOTHING in the product writes: `POST /challans` never touched them. So after the tax was paid on the due date and the challan recorded, the worksheet still said the whole month was outstanding and charged §201(1A)(ii) interest from each deduction to TODAY, growing every day, on tax that had reached the government on time (a July 2025 deduction deposited on 7 August 2025 showed ₹6,027.66 outstanding and ₹1,446.63 of interest when read on 19 October 2026: sixteen part-months at 1.5%), while the quarterly statement, built on the same register, called the same tax fully deposited. It now asks the register, by `challan_mapping`, the function the statement asks which challan paid which deduction (first in first out within a section, a challan typed `194J` matching a deduction under either limb): the deductions of the QUARTER up to the end of the month asked about and the challans recorded for that financial year and quarter, because a short April moves its shortfall to the later deductions and a month-only match would hide it. A challan settles its `tds_paise` plus its `surcharge_paise`, which is what left the bank less the interest and the penalty (`create_challan` stores `tds_paise` as the remainder, so a cess sits inside it: the form has no cess field), against the deduction's tax, surcharge and cess; the statement matches `tds_paise` against `tds_paise`, which agrees for every resident section and differs for a section 195 payment by the surcharge and cess. A salary challan settles nothing on this non-salary sheet. EACH CHALLAN A DEDUCTION DREW ON IS JUDGED BY ITS OWN DATE (`Assignment.parts`, added to the mapping beside the first challan the statement names): a deduction of ₹100 made on 20 April, ₹60 paid by 7 May and ₹40 on 20 August, bears interest on the ₹40 for five part-months, where dating it by its first challan would have said nil. A deduction only partly covered has its covered parts judged by their challans' dates and the rest as unpaid. THE MATCH IS BY ORDER AND NOT BY DATE, so a challan dated before the deduction it was matched to (the only challan of a quarter is April's, dated 7 May, and May's deduction on 20 May drew on it) is not counted as paying it: tax cannot have been paid over before it was deducted, and counting it would show the deduction deposited on 7 May with no interest, silently; the sheet names it (`challan_before_deduction`) and leaves the tax outstanding until the date is looked at. The sheet also says what it read (`deposits_read_from`: how many non-salary challans for which quarter and year, or that there are none), so a CA looking at tax shown outstanding can see where "deposited" comes from. The two reads add no ordering of their own, because `fetch_all` pages by keyset on `id` and a second ordering makes its cursor skip and repeat rows (the independent review ran 2,500 rows through the first version and got 4,173 back with 701 missing, from a quarter of more than a thousand deductions); a rule over every `fetch_all` caller holds it. one the register does not cover falls back to its own `challan_date` for a row somebody marked by hand (the column is kept for that and for nothing else), and where both speak the register is believed. Like the statement, it counts only challans labelled with the deduction's own financial year and quarter, so a catch-up challan typed under another quarter is not seen by either. Deliberately NOT done: the purchase-return note read the same two unwritten columns and took every deduction as not yet deposited (closed afterwards: see the purchase-return entry below); a recorded challan still posts nothing to the ledger and is tied to no bank line (POST-A-272); the match is first in first out and a CA cannot override which challan paid which deduction, which `challan_mapping` records as waiting for a screen that records the choice.

- **THE DEMO'S TDS DEPOSITS ARE THE WORKSHEET'S AND ITS STATEMENTS ARE THE BOOKS', AND THE NUMBERS A BANK OR THE PORTAL WOULD ISSUE SAY THEY ARE A SEED'S** (PRE-A-004 slice 3c, 19-10-2026). The challan, return and filing screens rendered nothing on the seeded firm. `seed_demo_firm._tds` runs after the income-tax stage, for every client that deducts tax. **Challans.** For each posted month (April to February; March is the draft month) it asks `GET /api/tds-workspace/deposit-due` and records one challan per section with tax outstanding, for exactly the outstanding amount, on the worksheet's own due date (Rule 30(2), computed by the server); and the §192 tax of each finalized or paid payroll run, read from the run, under section 192 on the same month's due date. A deposit whose due date is still to come is skipped and counted, and so is the statement of a quarter holding one, which is not built: `seed()` always passes the year's last month, so a `--financial-year` still running would otherwise have its later quarters refused for the deposit the seeder had decided not to make (the review found it; the first tests only used a last month `seed()` can never send). A salary deposit still to come holds back the 24Q alone, a resident one the 26Q alone. The branch code is `0000000`, which no bank holds, and the serial starts `SEED-`, because both are numbers off a bank's counterfoil that only the person who paid knows; the only check on the branch code is its seven-digit format (migration 112), which all zeros passes, and nothing checks that the branch exists. Everything else the stage states is a label of the door it drives (the minor head 200, the section number 192 for the payroll leg, the forms 26Q and 24Q); every amount and every date comes back from a door. **Statements.** Form 26Q, and 24Q for a client whose payroll withheld tax, built by the server (`/api/tds/26q|24q/from-books`), saved the way the screen saves it (the whole built payload), and taken prepared, CA approved and filed on the quarter's due date for every quarter that has ended before the draft month and whose due date has passed; the last quarter (it holds the draft month) is prepared and left, as the last GST return is. A quarter with no deduction in it gets no statement. The receipt number is `SEED-PRN-...`. A statement carrying validation errors, a challan gap, a ledger difference or a payment to a non-resident it leaves out (27Q is not built here), or having no deductee in a quarter whose challans were just recorded (the worksheet reads the deduction register and the statement the posted bills, so two readings of one quarter disagree), is a finding and is never saved or filed, and the obligation each filing leaves open is named. A READ THE SERVER REFUSES IS A FINDING TOO: the plain `Api.get` does not check the envelope and the TDS workspace answers a failure as HTTP 200 with `success: false` and no data, which the first version read as a month with nothing owed (no challan, no finding); the worksheet and the payroll list now go through `_data_of`, a 4xx is reported and a 401, 403, 429 or 5xx stops the run, and a month whose worksheet or challan could not be recorded names its quarter's statement as not built instead of the statement being refused for a gap the challans did not cause. A section 192 row on the non-salary worksheet is not deposited (payroll owns that section and it is deposited from the run). On a real stack: 45 challans (34 non-salary, 11 salary), 16 statements filed, 6 prepared, 6 quarters with no deduction, 16 calendar obligations closed, nothing refused. **What driving the doors found, each fixed in its own change first:** a statement could be marked filed with no date, from any state, and moved back (the status door); and the deposit worksheet charged interest on tax a recorded challan had paid (it read two columns nothing writes). With the second fixed, re-running the stage adds no non-salary challan, because the worksheet then says nothing is outstanding (the salary challans are not covered by the worksheet and are added again: the seeder only ever adds, and is not meant to be run twice over one firm). **Deliberately NOT done, each said in the docs:** the challans post nothing to the ledger and the seeded bank statement carries no line for them, so TDS Payable keeps its credit (POST-A-272); no Form 16A is recorded (those come from TRACES) and there is no 26AS; the six quarters with no deduction keep their obligation on the calendar, because the generator emits a statement obligation for every quarter of a TDS engagement and a CA files a nil statement or marks it from Compliance; every deposit is made on its due date, so the demo shows no §201(1A)(ii) interest; the TDS figures stand on the eleven posted months like the rest of the year.

- **A NOTE ON A PURCHASE RETURN SAYS WHETHER THE TAX HAS GONE BY ASKING THE CHALLAN REGISTER, AND THE REGISTER'S OWN COPY OF THE SENTENCE WAS BUILT AND THROWN AWAY** (POST-A-271, found by seeding the demo firm's TDS challans, 19-10-2026). When a purchase return (a debit note) or a supplier's undercharge note (a purchase credit note) stands against a bill the tax was withheld on, `domain/tds/purchase_return.credit_moved_after_deduction` writes the sentence that names which answer applies: the tax has not gone, so the deduction may still be recomputed, or it has, so it stands and the deductor carries an excess deposit. The quarterly statement builders (26Q and 27Q, `services/tds_return_service._credit_moved_gaps`) called it with NO deposit fact, and an absent fact resolved to "not yet deposited", so every note in a quarter whose tax HAD been deposited was told "The tax has not been paid over — no challan date is recorded against this deduction". Reproduced on the real stack: a part-paid bill of the seeded firm, ₹72.80 withheld and deposited on 7 October 2025 by a recorded challan, read that on a statement whose own deductee row showed it deposited. The module's docstring had warned of exactly this ("a CALLER that simply forgets to pass them gets the recompute branch"), and a test pinned that the REGISTER's call passed the facts; the statement's two calls were covered by nothing. The register (`tds_register_service.sync_for_bill`) read `tds_deductions.challan_date` and `status` (in the schema since migration 014, written by nothing: `POST /challans` never touches the deductions it paid) and built the same sentence, then used only its truthiness for the generic gap CODE, so that read was a query per noted bill whose answer nobody used. It now calls `credit_has_moved`, the one rule for whether a note moved the credit, and reads nothing; the two columns are not read by anything in this path any more. **THE STATEMENT'S OWN CHALLAN MATCH IS THE ONLY SOURCE, AND THE POSITION IS A REQUIRED ARGUMENT**: `_credit_moved_gaps` takes the `Mapping` the builder has already made and builds each bill's `DepositPosition` from `challan_mapping.dated_parts`, the rule the deposit worksheet's interest also uses (one place: a part whose challan carries no date is not counted, and one dated before the deduction is not counted and is reported as refused). `credit_moved_after_deduction` and `deposit_state` take `position` with no default (the old `challan_date`, `deduction_status` and `deposit_facts_known` arguments, which no caller passed after the change, are deleted), so a caller cannot get the unpaid answer by omission; `None` means "no position could be made" (a bill with no date to compare a challan's with) and is its own answer, "cannot be told", not "unpaid". The sentence now has five endings and they are not interchangeable: deposited in full (names the last challan's date, says the deduction stands); NEW, partly deposited (says how much has gone and how much has not, names the two answers, says the deduction is part of each and that how they combine is a CA's decision, and computes nothing: three monthly deposits are matched first in first out, so a short deposit leaves the last deduction part-paid, and whether a practising CA reads the part paid as standing and the rest as recomputable is not confirmed from a primary source here, POST-C-206); nothing deposited, which now says "as far as the books show" and that a payment made outside the product would change it (an absent record is not proof); cannot be told (a challan matched but dated before the tax was deducted, even beside another that paid part, because the part the refused challan stood for is unknown and not unpaid); and, decided FIRST, a note that RAISES what stands credited, which says the deduction may be SHORT (the direction that carries §201(1A) interest) whatever the challans paid, where the old text said "excess deposit on ₹0". The sentence states TAX TO THE PAISA where it has paise: it used whole-rupee truncation, so ₹72.80 read "₹72" and a part-paid deduction's two amounts did not add up. "Record the challan date on the deduction" became "record the challan that paid it, with its date, in the challan register", because nothing records a date on a deduction. The statement's deductee row counts a challan dated before the deduction as deposit and the sentence does not, and says so: that is the one place they differ, and it is deliberate. A payment date that is a timestamp is dated by its day (`as_date` returned a datetime unchanged and `dated_parts` then raised a TypeError that would have aborted the statement build). `tests/test_a_purchase_return_after_the_tax_was_withheld.py` holds every caller of the sentence writer in the backend (outside the tests and the module itself, bare or attribute call) to passing a position, with a floor so the scan cannot go blind, and the signature test holds `position` required and keyword-only; the older rule tests were ported to positions. Deliberately NOT done: the two columns are not stamped from the register (a stored derived fact goes stale when a challan is edited, and nothing needs it); the sentence is still only in the statement's `statutory_gaps` (the per-bill register carries a code); a §195 payment with surcharge and cess reads as part-paid here as it does on the statement's own deductee row, because the statement matches a challan's tax head against the deduction's total (inherited from the statement and recorded in the worksheet entry above); no real-Postgres test was committed, because the change is in what the statement does with rows it already reads, and the real stack was driven instead (the same note read "has not been paid over" before and "paid over on 2025-10-07" after).

- **THE HUB'S "TDS DEDUCTED AND NOT YET DEPOSITED" IS THE CHALLAN REGISTER'S ANSWER, COMPUTED WHERE THE ROWS ARE, AND IT READ A COLUMN A BILL-DERIVED DEDUCTION NEVER CARRIES** (found by opening the seeded demo firm in a browser, 19-10-2026). The hub's TDS tile summed `tds_deductions.tds_paise WHERE challan_no IS NULL`. A deduction a purchase bill writes never has `challan_no` (nor `challan_date`, nor a `status` other than `deducted`): `POST /challans` records the challan and never touches the deductions it paid. So EVERY bill-derived deduction counted as undeposited whatever had been paid in: with every deduction of the seeded year deposited by a recorded challan, the dashboard read ₹1,94,614.98 and one client's overview ₹63,647.88, on the figure a CA opens the hub for and wrong in the direction that sends them to chase a deposit they made. It is the third reader of those columns found in this thread (the deposit worksheet and the purchase-return note were the first two) and the first that is a number rather than a sentence. **The answer is the register's**: a challan pays the deductions of its own financial year and quarter under its own section, first in first out (`domain/tds/challan_mapping`), so what a group (client, financial year, quarter, section) still owes is `max(0, deducted − paid)` whatever the order of the fill, and the tile is the sum of those. **It is computed in the database** (`public.tds_undeposited_paise(p_firm_id, p_client_ids)`, migration 522, a SECURITY INVOKER read-only SQL function: row security still applies to a signed-in caller, `anon` and PUBLIC cannot execute it; the hub calls it as the service role) because CLAUDE.md's reporting rule forbids a firm-wide tile from fetching rows proportional to the ledger. `None` clients is every client of the firm, a list is those clients, an EMPTY list is nobody and answers 0, as every other tile treats it; the all-clients case is resolved to the firm's own client ids first, so both cases ask the same indexed question (`client_id = ANY(array)`) and a client hub over 400,000 synthetic deductions takes about 20 ms where an `IS NULL OR` form took about 150 ms and scanned the table. The function's name is a LITERAL in `hub_service._tds_undeposited`: `core/schema_guard` and the rpc-existence test read `.rpc("name"` and cannot see a name held in a variable (the first version passed it as a parameter and a required test went red). A figure the database did not give is not shown as 0: an absent answer raises and `_safely` makes it a tile with no figure. **The Python twin** `domain/tds/undeposited.py` is a LITERAL PORT OF THE SQL, and its only user is the in-memory database double the suites use (`tests/e2e_harness.py`; production runs the SQL). `tests/test_the_undeposited_tds_asks_the_challan_register_pg.py` holds the two identical over a real Postgres (scenario by scenario, a boundary test for each quarter and year edge with a challan for the right quarter and one for the neighbour, the odd spellings below, and the clients asked for), and `tests/test_the_undeposited_tds_asks_the_challan_register.py` holds the port to the register's own match (`deposit_due.mapping_from_register`) for every key of the section registry in both years. **A section is grouped as typed, trimmed of ASCII whitespace, upper-cased, with a trailing bracketed limb dropped** (`194J(B)` → `194J`; no section is `(NO SECTION)` on a deduction and nothing on a challan; a non-breaking space is part of the text, in both halves). For every section the registry holds that is `section_rates.parent_of`, which is what the statement and the worksheet group by, and the registry cannot be asked from SQL, so the pattern stands in for it: the tests go red the day a key is added whose parent is not its bracket-stripped text, which is when the function needs a lookup and not a pattern. **For a section the registry does NOT hold, the tile and the statement differ**: the statement groups by the text itself, the tile by the bracket-stripped text, so a deduction under `194Z(A)` is paid by a challan typed `194Z` on the tile and is not on the statement (a challan's section is free text, and this is pinned by a test so it cannot change by accident). Each row counts at least nil, as `challan_mapping.assign` does (a negative row neither pays nor owes); salary (§192, three spellings) is in neither side, because payroll deposits it and neither half of this register carries it; a deduction with no usable date is left out, as the worksheet leaves it. A challan's capacity is its tax plus its surcharge against the deduction's tax, surcharge and cess, which is what the deposit worksheet matches; the quarterly statement matches tax against tax, and the two agree for every resident section (no surcharge, no cess) and differ for a §195 payment by exactly those. **WHAT THE TILE DOES NOT SAY**: it asks whether the register covers the tax, not whether a challan was dated on or after the deduction (the statement's note and the worksheet judge that and report a pre-dated challan); and **a challan number typed on a HAND-KEYED deduction is a note and not a deposit**: the manual deduction form and import can write `challan_no`, the old tile excluded such a row, and the new one counts it as undeposited unless the challan is recorded in the register, exactly as the statement and the worksheet do (which ignore the field), so the three agree and a CA who keyed the number is told on all three to record the challan (a test pins it). **Same defect, not fixed here and now on the ledger (POST-A-273)**: Form 3CD clause 34's "tax deducted not deposited" counts a deduction as deposited from `status` or `challan_no`, so for a deduction a purchase bill wrote it reports the whole tax as undeposited, in a tax-audit output; and the TDS screen's deductions table prints a "Challan No" column from the same field, which is a dash for every bill-derived deduction. Deliberately NOT done: the dead columns are not dropped (a column drop needs the production-fixture refresh in `docs/schema-drift.md`, and the manual path writes `challan_no`); the tile is not a count of deductions or an ageing of them; the function is granted to `authenticated` as migrations 277 and 363 grant theirs, although only the service-role hub calls it (a signed-in direct caller gets an assignment-narrowed figure, because both tables carry the assignment-scope policy).
