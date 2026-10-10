# Design record: Income tax: ITR kinds and engines, capital gains, tax audit and 3CD, losses, entity reliefs, section 43B(h)

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Indian tax domain rules — never violate these

- **§115BAC DISAPPLIES CHAPTER XII-BA, and the AMT surcharge ladder is the
  ASSESSEE's own.** `compute_amt` had no regime parameter (IT-21), so it could
  not express the disapplication at all, and it passed
  `entity_rates.firm_surcharge` — the single 12%-above-₹1-crore bracket — for
  every non-corporate assessee (IT-07), surcharging an individual at a firm's
  rate: at ₹6 crore of adjusted total income the individual ladder is 37% and
  the difference is 25 percentage points of the minimum tax. Both are LATENT —
  `itr_engine`'s only AMT caller is the firm/LLP branch — and both are fixed
  because the branch that reaches them is one entity type away. **A FIRM OR LLP
  IS OUTSIDE §115BAC**, which reaches only an individual, HUF, AOP, BOI or
  artificial juridical person, so `regime="new"` cannot waive their AMT and the
  ladder stays the firm's. The two interlock: an individual who reaches the
  charge is on the OLD regime by construction, so the new regime's surcharge
  cap never applies and the full ladder is theirs. ⚠️ The disapplying provision
  is `[S]`-graded on its CITATION and not its effect — §115JEE cross-refers to
  the §115BAC option and the Finance Act 2023 restructured §115BAC so the
  option became the one to LEAVE the regime; which sub-section it now names
  could not be read. The rule is written as the effect, with the sub-section
  deliberately not guessed.

- **THE FOUR REINVESTMENT SECTIONS ARE NOT ONE RULE WITH FOUR NAMES** (IT-19,
  migration 385). `capital_gains_engine` computed the gain, the holding period
  and the rate and stopped, so on a house sale — where the whole gain is
  routinely exempt — the register showed tax on a gain the client may not owe
  tax on at all. `domain/income_tax/reinvestment_exemption.py` is the
  authority. **§54 exempts the LOWER of the gain and the cost; §54F is
  PROPORTIONATE** — gain × cost ÷ NET CONSIDERATION — so on a ₹1 crore sale
  with a ₹40 lakh gain and a ₹50 lakh house, §54's rule would exempt ₹40 lakh
  and §54F exempts ₹20 lakh; applying the wrong one halves the tax.
  **§54EC's ₹50 lakh spans the year of transfer AND the year after it
  together** (the second proviso), so reading it as a per-year cap doubles the
  exemption; its window is six months, and from 01-04-2018 it reaches only land
  or building — a transfer before that keeps the wider section, the fork shape
  again. **§54B is the one section a SHORT-TERM gain reaches**, because its
  charging words describe the USE of the land in the two preceding years rather
  than a holding period. The Finance Act 2023's ₹10 crore ceiling applies to
  §54 and §54F from FY 2023-24 only. **Three facts are refused and NAMED, never
  guessed**: what was SOLD (`capital_gains.transferred_asset_nature` — the
  register's `asset_type` cannot tell a residential house from a plot), how many
  other houses the assessee owned (§54F's own condition) and whether the land
  was farmed (§54B's). **No exemption amount is stored** — the caps move by
  Finance Act, so it is derived on every read, the same reason migration 278
  made `outstanding_paise` generated. **The individual-or-HUF test is its own
  tri-state and NOT `capital_gains_engine.ASSESSEE_TYPES`**, whose `other` means
  "not a RESIDENT individual or HUF" — a NON-RESIDENT individual falls there and
  §54 reaches them perfectly well. The fraction FLOORS, because the exemption is
  what tax is not charged on. ⚠️ Every figure and window is `[S]`-graded: egress
  is refused here, incometax.gov.in included, so a test pins each constant
  exactly and the screen says so.

- **FORM 3CD IS 44 CLAUSES, AND EIGHT OF THEM REUSE ENGINES THIS PRODUCT ALREADY
  HAD** (IT-11, 25-09-2026). The Tax Audit tracker recorded whether an audit
  happened and never assembled the report's own particulars, although most of
  what a real 3CD needs is already computed somewhere else in this product —
  `domain/income_tax/form_3cd.py` is the clause vocabulary, transcribed
  clause-for-clause from the Income-tax Rules 1962 form itself, and
  `services/form_3cd_service.py` is what fetches each derivable clause by
  CALLING the module that already owns the rule, never re-deriving it: clause
  18 (depreciation) reads `section_32_service`, clause 22 (MSMED §16 interest)
  and the MSME limb of clause 26 (§43B) both read `msme_43bh_service.
  for_financial_year` — one call answers both, because §16's clock is the
  same appointed day §43B(h) already computes — clause 32(a) reads
  `computation_workspace.list_bf_losses`, clause 34 groups `tds_deductions` by
  section, clause 44 splits `purchase_bills` by `vendors.
  gst_registration_status` (excluding opening/carried-over bills, the
  `opening_documents.without_carried_over` discipline), clause 14 reads
  `clients.inventory_costing_method`, and clause 8 resolves §44AB(a)/(b) from
  the Tax Audit tracker's own turnover once the CA states the activity
  (business or profession is never inferred from the amount, the same rule
  `/tax-audit/applicability` already holds). **`derived` and a CA's own
  recorded answer are two SEPARATE channels into the register, and conflating
  them is the one bug that would have shipped**: a manual note saved against a
  clause must never come back marked as a computed figure, or a screen would
  render a CA's own textarea entry as read-only the next time the register
  opens — `build_register` takes `manual` apart from `derived` for exactly
  this reason. **No migration.** `public.tax_audit_checklists` (migration
  014) has held `(firm_id, client_id, financial_year, clauses_json, status)`
  since the very first schema sweep with NO reader or writer anywhere in this
  codebase until now — the same shape a manual-clause store needs, so this is
  the first caller rather than a new table. The other 36 clauses are named
  with the form's own text and why this product does not reach them (§40A(2)
  (b) related-party payments, §269SS/269T cash loans, ICDS adjustments, Form
  61/61A/61B, CbCR, cost/excise audits, and the rest) — reachable at
  `/income-tax/tax-audit/form-3cd`, linked from the Tax Audit tracker.
  **Three derivable-looking clauses were deliberately left manual rather than
  rushed**: clause 33 (Chapter VI-A) is the CA's own claims on the ITR
  computation workspace, not a fact the books hold, so deriving it needs a
  join to a computation snapshot rather than a lookup; clause 35 (stock
  quantitative detail) and clause 40 (turnover/GP/NP ratios for the current
  AND preceding year) both have the raw figures available (`stock_position_
  as_at`, the Profit & Loss) but assembling them into the form's own row
  shape is unfinished work, not a missing capability, and is named as such
  rather than answered halfway.

- **§140A IS PAID BEFORE THE RETURN IS FURNISHED, AND A SHORT CHALLAN LANDS
  FEE FIRST** (IT-13, migration 407). §140A(1) makes the tax, interest and fee
  on a return payable *before* it is furnished and requires the return to be
  "accompanied by proof of payment" — a Challan 280, which this product held no
  record of, so Schedule IT's BSR code, date, serial number and amount were
  keyed off a bank receipt and the ITR keying sheet printed §140A as a
  structural nil. **`advance_tax_payments` could not have held it**: that table
  is keyed `UNIQUE (client_id, financial_year, installment_number)` with the
  number CHECKed to 1–4, which is §208's schedule, and self-assessment tax is
  not an instalment of anything. `domain/income_tax/self_assessment.py` is the
  authority.
  **THE EXPLANATION'S ORDER IS NOT PRO RATA AND DOES NOT READ THE CHALLAN'S OWN
  BOXES.** A payment short of the aggregate is "first adjusted towards the fee
  payable and thereafter towards the interest payable and the balance, if any,
  ... towards the tax payable" — so ₹50,000 against ₹80,000 tax + ₹12,000
  interest + ₹5,000 fee leaves **₹47,000 of TAX** outstanding where a
  proportional split would report ₹38,763, and the tax is the figure §234A and
  §234B go on charging on. The order runs off what is DUE: the provision exists
  to override the payer's own labelling, so two clients paying the same money on
  the same day with the boxes filled in differently must get the same
  outstanding tax. `appropriate` takes four scalars and an AST guard forbids it
  reaching into a challan row at all. The five-way split is nonetheless STORED,
  because it is what the DOCUMENT says; where it does not foot to the total the
  position SAYS so and **moves neither figure**, and a challan recording only
  its total is not a mismatch — that is the bank receipt the table exists to
  keep recordable.
  **`tax_payable_on_return` is §140A(1)'s own subtraction** (TDS/TCS, advance
  tax, §90/90A/91 relief, §115JAA/JD credit), floored at nil because a refund is
  §143(1)'s business, and **deliberately not read off §234A's base** — Explanation
  1 lists the same reductions and the figures coincide, but a later amendment to
  one is not an amendment to the other. It is served as
  `section_140a_tax_due_paise` on `POST /interest/234ab`, so the screen passes a
  server figure through rather than subtracting credits in the browser.
  **Uniqueness is the CHALLAN's own identity** — (firm, BSR code, deposit date,
  serial) — and there is deliberately **no key on (client, financial_year)**,
  because Schedule IT has a row per challan and a return may be accompanied by
  several. **The keying sheet's two sentences are told apart by the COUNT and
  never by the amount**: a challan recorded for nil is still a challan, and a
  sheet reading "no challan is recorded" over a record somebody entered is the
  kind of wrong that survives a review. **Nothing is posted** (a payment of the
  client's own income tax is not a transaction of the books unless the CA raises
  it) and **§140A(3) is NAMED, never scored** — §221's penalty is what the
  Assessing Officer directs, a discretion and not a formula. ⚠️ `VERIFIED` is
  False: the Explanation's wording is recorded from knowledge, egress being
  refused here, and is pinned exactly by
  `tests/test_a_short_self_assessment_challan_lands_fee_first.py`.

- **A RETURN OF INCOME HAS THREE KINDS, AND `itr_filings` HELD ONE** (IT-23,
  migration 381). §139(1) is the ORIGINAL, §139(5) the REVISED and §139(8A) the
  UPDATED return (ITR-U) — and the table could not have carried a second one
  whatever the code did, because migration 319 declares
  `UNIQUE (firm_id, client_id, financial_year, itr_form)`. A revised return
  sits BESIDE the original: the original's acknowledgement number and date are
  fields on the new return's own form. 381 narrows that constraint to
  `WHERE return_type = 'original'` and adds no uniqueness to the other two —
  §139(5) expressly allows a revised return to be revised again, and
  §139(8A)'s once-only bar is about a return FURNISHED, which a constraint
  cannot tell from a draft, so `itr_workflow.already_furnished_updated_return`
  WARNS instead. **`domain/income_tax/return_type.py` is the authority** and
  `GET /api/itr/return-kinds` serves it, so the filing screen holds labels and
  no dates. The earlier receipt is READ off the original where this product
  prepared it (the `domain/tds/deductor.resolve` shape) and REFUSED where
  nobody holds it. ⚠️ **The two windows and §140B's bands are `[S]`**: §139(5)
  is 31 December of the AY and NAMES the completion-of-assessment limb it
  cannot see, §139(8A) reports BOTH the 48-month (Finance Act 2025) and
  24-month dates and answers `is_open = None` where they disagree about today,
  and §140B's 25/50/60/70 table is `verified=False` throughout and **REFUSES an
  assessment year it does not hold** rather than falling back — the trap the
  FY-versioned registries have, on money a client pays over.

- **The Finance (No. 2) Act 2024 forked capital gains on 23-07-2024, and it is
  the DATE OF TRANSFER that decides.** §111A 15%→20%, §112A 10%/₹1,00,000 →
  12.5%/₹1,25,000, §112 20%-with-indexation → 12.5%-without, and §2(42A)'s
  holding periods moved — a non-property, non-listed asset needed **36** months
  before that date, not 24. A transfer before it is governed by the earlier law
  indefinitely, the same "fork, not migration" shape as the TDS vocabulary, and
  the register holds real historical transfers. §2(42A) also runs to the day
  **immediately preceding** transfer, so the test is `sale > purchase + N
  months`, not a whole-month count. The fifth proviso to §112(1) — the lower of
  12.5% without indexation and 20% with it — reaches only a **resident
  individual or HUF**, only immovable property, and only property acquired
  before the cutoff; `domain/income_tax/capital_gains_engine.py` withholds it
  and says why rather than granting it by default. **FY 2024-25 straddles the
  fork**, so `statutory_rates.FYTaxRates` (one CG rate set per FY) cannot
  represent that year — it holds only post-fork years today, and adding 2024-25
  needs pre/post buckets, as the ITR form itself splits them.

- **§43B(h) IS DERIVED FROM THE PURCHASE LEDGER, AND THE LIMIT IS FIFTEEN DAYS**
  (PUR-15). The Finance Act 2023 inserted clause (h) with effect from AY
  2024-25: a sum payable to a MICRO or SMALL enterprise beyond the MSMED §15
  time limit is deductible only in the previous year it is ACTUALLY PAID.
  **The first proviso to §43B does not reach clause (h)** — paying before the
  §139(1) return date saves every other §43B item and not this one, which is
  the commonest mistake with it and is on every answer.
  `domain/income_tax/section_43b_h.py` is the rule,
  `services/msme_43bh_service.py` fetches its inputs, and
  `GET /api/income-tax/msme-43bh` serves it. `/accounting/msme-tracker` renders
  it and computes nothing: it used to ask the CA to re-key every bill into
  `msme_payments` over PostgREST — so the figure drifted from the books,
  `rbac()` never ran, and the whole statutory rule lived in TypeScript, where
  it read the agreement type off a per-invoice dropdown. **`msme_payments` is
  no longer read or written**; dropping it is a migration and an owner
  decision. Two directions, both computed: what accrued this year and missed
  its limit is added back, and an EARLIER year's disallowance actually paid
  during this year comes back as a deduction — so every live bill is read, not
  only the year's own. **Micro and small only** (MSMED §2(n)); an unclassified
  vendor is named, never assumed. **The disallowance is the DEDUCTION** —
  taxable value plus §17(5)-blocked tax — not the gross invoice, because
  creditable GST is credit and not an expense; and a bill capitalised into a
  fixed asset is reported with nothing disallowed, since only the depreciation
  is claimed. **TDS withheld counts as paid to the supplier**, the same §199
  reasoning `domain/gst/itc_reversal.py` applies to Rule 37. ⚠️ §15 runs from
  ACCEPTANCE and the books hold the BILL DATE; the proxy gives the earliest due
  date and so the largest disallowance, which puts the item in front of the CA
  rather than hiding it, and every answer says so.

- **HOW LONG A CARRIED-FORWARD LOSS LIVES IS PER HEAD, AND ONE OF THEM IS NOT
  EIGHT YEARS.** `domain/income_tax/loss_set_off.py` decides WHICH HEAD a
  brought-forward loss may reach; `domain/income_tax/loss_carry_forward.py` is
  the separate authority for HOW LONG — §72(3) eight assessment years for a
  business loss, **§73(4) FOUR for a speculation loss**, §74(2) eight for
  either capital head and §71B eight for house property. The computation
  screen's own label read "§72 (Business, 8 yrs) · §74 (Capital, 8 yrs)",
  hardcoded — true of three heads and silent about the fourth — and the
  engine's expiry refusal quoted "§72(3)/§74's eight assessment years" for
  every head including speculation. Both name the head's own section now, and
  `GET /api/itr/loss-types` serves the vocabulary so the form holds neither a
  head nor a period.
  **`brought_forward_losses` WAS READ AND NEVER WRITTEN** (IT-10's other half):
  `POST /api/itr/bf-losses` has existed since migration 156 with no caller and
  the panel listing them was read-only, so every client showed "No
  carried-forward losses recorded" for ever with a fully built set-off engine
  behind it. **`expiry_assessment_year` was a REQUIRED caller-supplied field**,
  so the one statutory fact in the row was whatever was typed; it is derived
  now and a caller-supplied value still WINS (`domain/tds/deductor.resolve`'s
  shape). **Two refusals rather than guesses**: `other` means the head is not
  identified, so no section fixes a period and it is refused rather than given
  eight years, and **§32(2) unabsorbed depreciation and §73A's specified-business
  loss carry forward INDEFINITELY** and are absent from the stored vocabulary —
  named on the form, because recording one as `other` with any expiry would
  expire a loss that never expires. ⚠️ Every period is `[S]`-graded, `VERIFIED`
  is False and each is pinned by a test: the error direction is unsafe BOTH
  ways, since too short expires relief the client is entitled to and too long
  claims relief they are not.

- **WHETHER §44AB applies is `domain/income_tax/tax_audit.py`, and the NATURE
  OF THE ACTIVITY is an input, never inferred from the amount.** §44AB(a)
  reaches a person carrying on BUSINESS and §44AB(b) a person carrying on a
  PROFESSION — different clauses, different figures, and which applies is a
  fact about the client. The Tax Audit tracker used to decide it in three lines
  of TypeScript: above ₹1 crore "business", between ₹50 lakh and ₹1 crore
  "profession", so a trader with ₹60 lakh of turnover — whom clause (a) does
  not reach at all — was told an audit was mandatory, and §271B charges 0.5% of
  turnover capped at ₹1,50,000 on exactly that obligation. **The proviso to
  §44AB(a) needs FOUR figures, not two**: cash receipts against turnover AND
  cash payments against total payments, and the payments denominator cannot be
  derived from turnover — so the ₹10 crore limb is applied only when all three
  are stated, and the base figure stands otherwise, which is the direction that
  cannot cause a missed audit. **Clauses (c), (d) and (e) are NOT tested and are
  NAMED on every answer**, a "not required" one included: each compares DECLARED
  profit against a figure deemed by §44AE/§44BB/§44BBB/§44ADA/§44AD(4), and no
  turnover box carries that. ⚠️ Every year is `verified=False` — the figures are
  `[S]`-graded, reconciled against `presumptive.py`'s 5% cash test rather than
  read off a Finance Act. One reconciliation is worth keeping: **the Finance Act
  2023's ₹75 lakh is §44ADA's PRESUMPTIVE limit, not §44AB(b)'s AUDIT
  threshold** — `apps/web/lib/income-tax/taxAuditThresholds.ts` said otherwise
  in its own comment and is deleted.

- **§115BAC(6) WAS MODELLED AND NOTHING COULD ASK IT.**
  `domain/income_tax/regime_election.py` has held both clauses with Rule 21AGA
  since it was written and had **no production caller** — the only mention of
  it outside its own file and tests was a COMMENT in
  `domain/payroll/declarations.py`. Its own docstring says why that mattered:
  *"A missed Form 10-IEA taxes a client on the new regime for a year they
  planned around the old one, and it cannot be cured after the due date. A
  withdrawal made without realising it is final closes an option worth lakhs
  over a career. Neither failure is visible in the return — it computes
  cleanly either way."* `GET /api/income-tax/regime-election` serves it and the
  computation screen renders it **beside the regime picker**, because which
  regime is CHEAPER is not the same question as what choosing it REQUIRES.
  **A GET, deliberately** — it reads and writes nothing, and a POST would need
  an entry on `test_write_requires_write_permission.py`'s compute-only
  allowlist that every preview has to earn. The wire format for an earlier
  year is `FY:action` (`2024-25:withdrew`), parsed in the ROUTER because the
  format is the endpoint's business and the rule is not.
  **PRIOR HISTORY IS AN INPUT AND SILENCE IS ITS OWN ANSWER.** The product
  holds no filing history, so clause (i)'s once-only withdrawal cannot be
  derived; supplying nothing is answered as `history_unknown`, which is a
  DIFFERENT answer from "the option is available". Assuming availability is
  the dangerous direction — it tells a CA the old regime is open when their
  client spent it years ago.

- **A HUF, AN AOP AND A BOI ARE ASSESSEES, NOT INDIVIDUALS, AND THE ENGINE ASKS A TABLE WHO EACH RELIEF REACHES** (TDS-INCOME-TAX-16, migration 453). `clients.entity_type` was CHECKed to eight values with none of the three, so each was recorded as "Individual" and computed on the individual slabs with the s.87A rebate ("an assessee, being an individual resident"), the s.16(ia) standard deduction (a salary deduction) and the senior-citizen slab ("every individual"). Migration 453 widens the CHECK (NOT VALID then VALIDATE) and rewrites nothing: a HUF already recorded as Individual stays one until edited, because a mistyped PAN is the record this change may not overrule. `domain/income_tax/relief_reach.py` is a table of who each relief reaches by the section's own words and `itr_engine` asks it (s.87A, s.16(ia), the senior slab, the unused-basic-exemption absorption) instead of testing a kind by name; an individual-only claim (s.80CCD, 80E, 80EE, 80U, 80GG, salary, s.10(13A)) on a HUF/AOP/BOI is REFUSED with the section's words quoted, never dropped; a kind absent from a row is refused the relief. A HUF keeps s.80C/80D/80TTA/80DD/80DDB and the absorption provisos (they name it), so parity tests show the three reliefs are the ONLY differences. `domain/income_tax/aop_boi.py` resolves s.167B from two facts about the members no record holds (shares determinate; a member above the exemption limit), so they are tri-state inputs to the computation and an unstated one is REFUSED, because "slab" under-charges and "top rate" over-charges: top rate from the first rupee where shares are indeterminate or a member is above the limit, slabs without s.87A otherwise; the rate is read off the slab table's last bracket, never stated, and capital gains at the top rate are refused rather than choosing between two readings. s.44AD names a HUF and s.44ADA(1) does not; the two used to share one set because a HUF could not be recorded, and are split. The server serves the default ITR form (HUF ITR-2, AOP/BOI ITR-5), the reliefs a kind does not get (the screen hides those boxes) and whether to ask the two s.167B questions; every browser list of entity types is pinned from Python. Deliberately NOT done: no stored client is re-typed; form eligibility is not enforced at filing creation; `clients.constitution` (dead, own CHECK) is left alone; s.167B's provisos (a member above the MMR, an all-company AOP, a non-resident member, s.86) are named on every answer; the s.2(29C) "including surcharge" reading is [S] and uses the lower, own-bracket figure. Every section reading is [S]-graded and pinned exactly.

- **THE SECTION 234C PROVISO IS APPLIED, ON THE INCOME'S OWN TAX** (TDS-INCOME-TAX-21). `compute_234c_interest` measured every instalment against the whole year's tax, so a gain realised on 20 March was treated as foreseeable on 15 June. The proviso excuses the shortfall a capital gain, winnings or dividend that arose AFTER the instalment's date caused, provided the tax on that income is paid in the instalments that remain, or by 31 March where none does. `UnforeseenIncome` is an optional input, so no client's figure changes until a CA supplies one. An income is excluded from every instalment whose due date is strictly before it arose; the condition is tested on that income's own tax, with payments from the date it arose to its settle-by date taken against each income in the order they arose and never counted twice; a failed condition gives no relief and a sentence. An item outside the year, of an unknown kind or with negative tax is a 422, not clamped. `GET /advance-tax/unforeseen-income` OFFERS the capital gains register's transfers (tax plus cess, an estimate) and the CA includes or removes each; the server's per-income verdict is rendered. Deliberately NOT done: the dividend limb is the least certain, `UNFORESEEN_PROVISO_VERIFIED` is False and every answer carries the caveat; the offered tax has no surcharge or annual s.112A exemption.

- **HOUSE PROPERTY AND SALARY ARE WORKINGS, KEPT AS INPUTS AND RECOMPUTED, AND THEY FEED A BOX ON THE CA'S CLICK** (TDS-INCOME-TAX-14, -15, migration 455). Both were one typed figure that was really the result of a working done on paper. `domain/income_tax/house_property.py` works s.22-27 per property and for the head: the higher of expected and actual rent (vacancy, standard rent), Rule 4 unrealised rent only where its conditions are stated, the 30% of net annual value, interest on accrual, the self-occupied cap (Rs 2,00,000 or Rs 30,000 by three stated facts, shared across both houses, withdrawn under s.115BAC(2)), five equal pre-construction instalments inside that cap, a co-owner's share with the owner's own interest; a third self-occupied house is refused (which two is the assessee's choice and changes the tax) and the loss set-off cap stays the ENGINE's. `domain/income_tax/schedule_s.py` is Schedule S: a block per employer, ESOP/RSU valued from shares and two prices and never negative, s.10 exemptions each tagged with whether s.115BAC(2) leaves it, the standard deduction taken once and never above the salary; its `engine_inputs` are what the existing boxes take and the identity that holds is asserted against the real engine (Schedule S income = the engine's salary head less the HRA exemption, because the engine reports salary before HRA). Payroll's perquisite valuations are not wired: they value what an employer provides and a salaried return's client is the employee, whose Form 16 carries that valuation. `income_tax_worksheets` keeps only the CA's inputs; nothing derived is stored, because the regime is chosen on the computation screen and a stored income is wrong the day it flips (migration 278's reasoning). Deliberately NOT done: arrears (s.25A/25B), letting with furniture, s.192(1C) start-up ESOP deferment, each s.10 exemption's own ceiling and the s.16(ii) allowance are named on every answer; every reading is [S]-graded.
