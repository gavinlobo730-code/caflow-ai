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
