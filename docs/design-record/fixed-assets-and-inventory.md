# Design record: Fixed assets, capital work in progress, stock costing, ageing, godowns, batches and counts

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Indian tax domain rules — never violate these

- **AN ASSET UNDER CONSTRUCTION IS NOT IN THE REGISTER, AND THAT IS THE FIX**
  (FA-11a, migration 397). `fixed_assets` was the only place an asset could
  live and everything in it is depreciated, so a client building a factory
  either left it out — a balance sheet short by the whole of what had been
  spent — or put it in and had depreciation charged on something not ready for
  use, which overstates the expense, understates the asset and understates
  every later year's charge because the written-down value starts lower. AS-10
  paragraph 20 and Schedule II both start depreciation when the asset is
  AVAILABLE FOR USE. `domain/fixed_assets/cwip.py` is the rule,
  `services/cwip_service.py` fetches and posts, `routers/cwip.py` decides
  nothing — and it is a SEPARATE router deliberately, because mounting it on
  `/api/fixed-assets` is what makes the next reader reach for
  `_SCHEDULE_II_PART_C`.
  **AND IT IS A DISCLOSURE, NOT A CONVENIENCE.** MCA G.S.R. 207(E) of
  24-03-2021 — the SAME notification behind the two ageing schedules migration
  303 built — gives capital work-in-progress its own line under Non-current
  assets immediately after PP&E, an **ageing schedule** (<1y / 1-2y / 2-3y /
  >3y, split between *projects in progress* and *projects temporarily
  suspended*), and a **completion schedule** for every project overdue against
  its originally approved completion date OR over its originally approved cost.
  **`capital_wip` HAS BEEN A DECLARED YEAR-END LINE SINCE `year_end_lines.py`
  WAS WRITTEN and nothing could ever reach it** — no caption resolved there —
  so the year-end balance sheet carried a structurally nil CWIP line for every
  client. That is the half nobody could have seen.
  **THE AGEING AGES MONEY, NOT PROJECTS**, which is why the cost is
  `cwip_additions` with one row per tranche and its own `incurred_on`: a build
  begun three years ago whose last contractor bill arrived last month has
  amounts in three bands at once, and a project-level date would put all of it
  in the oldest. Exactly one year falls in the SECOND band — "less than 1 year"
  means less than — and months are counted on the calendar rather than days, so
  the answer cannot disagree with itself across a leap year.
  **SUSPENSION MOVES THE ROW AND NEVER THE BALANCE**: it is presentational, and
  reading it as a removal would take the cost off the balance sheet, which is a
  write-off nobody decided. **The schedules are AS AT A DATE** — a project
  capitalised in June is CWIP in a 31 March note and a fixed asset in a 30
  September one, which is why `capitalised_on` is recorded rather than the row
  deleted, the same discipline `stock_position_as_at` applies to stock.
  **TWO FACTS ARE REFUSED RATHER THAN GUESSED and both directions of the guess
  are wrong**: `approved_completion_date` and `approved_cost_paise` are
  nullable with no default, because defaulting the date to the project's start
  reports every project overdue on day two and defaulting the cost to what has
  been spent reports none over budget ever; a project with neither is NAMED as
  undeterminable. A reportable project with no `expected_completion_date` is
  named too rather than bucketed — a row in "more than 3 years" because nobody
  said otherwise states something false.
  **CAPITALISATION CREATES THE ASSET AND IS ONE WAY**: cost = the accumulated
  tranches (each carrying its §17(5)-blocked tax, AS-10 paragraph 9 — the same
  sentence AS-2 paragraph 6 applies to stock), `put_to_use_date` = the date it
  became ready, and `purchase_date` the SAME date rather than the project's
  start, or the register would charge three years of depreciation the moment
  it is capitalised. `acquisition_mode` is deliberately left NULL (every
  payment already happened on the tranches) and the trace lives on
  `capital_work_in_progress.capitalised_asset_id`. The account is code **1504**
  with subtype `Capital Work-in-Progress`, and the SUBTYPE is load-bearing:
  `schedule_iii.classify` buckets on it and the CWIP branch is tested BEFORE
  the tangible one, because "Capital Work in Progress - Plant" contains
  "plant".

- **AN ASSET CATEGORY IS BOOKED TO A LEDGER BY ONE TABLE, AND THE CHART A FIRM GETS MUST HOLD EVERY LEDGER IT NAMES** (PRE-A-004, migration 482). `domain/fixed_assets/asset_ledger` is the one category-to-ledger table; `phase2_journal_service` carried it three times (acquisition, CWIP capitalisation, disposal) and the standard chart had no Office Equipment ledger, so `POST /api/fixed-assets` for that category answered 500 *after* the `fixed_assets` row was written, leaving an asset with no acquisition journal. `STANDARD_COA` now seeds code 1508 and migration 482 adds the ledger for a firm that lacks one (the lowest free code from 1508 to 1599; rows only, no existing account is touched). `tests/test_every_asset_category_has_a_ledger_on_the_standard_chart.py` holds the rule over the two tables: every `schedule_ii.PART_C` category is an explicit key, its pattern finds exactly one asset ledger on the standard chart, and no other module maps a category to a ledger. Not changed and named: `create_asset` still writes the asset row before the journal, so any OTHER missing ledger still leaves an asset with no journal (the router does not convert `_find_account`'s error); a firm whose only Office Equipment account is inactive or client-level is not topped up, because the name is unique per firm and the insert would collide.

- **A FIXED-ASSET DISPOSAL IS A SUPPLY, AND CGST §18(6) CHARGES THE HIGHER OF
  TWO LIMBS** (FA-08b, migration 383). `journal_for_asset_disposal` posted four
  lines — accumulated depreciation cleared, the whole proceeds to bank, the
  asset out at cost, the gain or loss balancing — and NO tax line at all, and
  `DisposalIn` had no field that could have driven one. So the sale of a
  capital asset was never declared: nothing in the ledger, nothing on the
  return, and the CA had to remember to raise a separate sales invoice.
  §18(6) charges "the input tax credit taken on the said capital goods ...
  reduced by such percentage points as may be prescribed **or** the tax on the
  transaction value ... **whichever is higher**", so an asset sold cheap early
  in its life pays back CREDIT rather than tax on the price — the case a plain
  output-tax line under-declares by an order of magnitude.
  `domain/gst/section_18_6.py` is the authority.
  ⚠️ **TWO RULES PRESCRIBE THE REDUCTION AND THEY DISAGREE**, so BOTH readings
  are reported and neither is chosen — the `interest_on_rule_37_reversal`
  shape, for the same reason: this is a sum the CA pays over. Rule 40(2) is
  five percentage points per **quarter or part thereof** from the invoice date;
  Rule 44(6), through Rule 44(1)(b), pro-rates the credit over the **remaining
  useful life in months out of sixty**. At 38 months that is 35% against
  36.67%. `[S]` — every `.gov.in` is refused at this environment's proxy.
  **The part DAYS count in Rule 40(2)**: three months exactly is one quarter, a
  single day more is two, so the count cannot be `ceil(whole_months / 3)`.
  **The comparison is on the TOTAL**, not head by head — Rule 44(6)'s
  "determined separately for ... central tax, State tax" governs how limb (a)
  is worked out, not how the two limbs are ranked; ranking per head would pay
  the credit limb on one head and the value limb on another, which is not a
  figure the section describes. **Every rounding goes UP** (a sum the taxpayer
  owes) and a part month does NOT count as elapsed, which leaves the remaining
  life larger and the charge larger — the direction that cannot leave a
  shortfall. **Only limb (b) is POSTED**: the tax on the transaction value is
  what the buyer paid and is not in doubt, while the excess has two readings
  and no invoice behind it, so the CA raises it — `itc_register_service`'s
  judgement about Rule 37. The **proceeds are TAX-INCLUSIVE** and the tax is
  backed out with `charge_gst.split_inclusive_charge`, so the journal balances
  with no plug and the **gain is measured on the consideration NET of tax** —
  the buyer's tax is not the seller's proceeds. Migration 383's three columns
  are all STATED: `disposal_is_supply` (nullable, NO default — a scrapping for
  nothing and a sale are the same row shape), `disposal_gst_rate_bps` and
  `disposal_is_interstate` (an asset bought locally may be sold across a state
  border, and §18(6) does not say which head the credit limb is then paid in —
  NAMED, never resolved). The return reads those columns as the document and
  declares the supply in **3.1(a), never 3.2**. Two more refusals: no credit
  taken means §18(6) does not reach the supply at all (only §9 does), and an
  asset that does not RECORD its credit position is a named gap rather than
  assumed nil. `GET /api/fixed-assets/{id}/disposal-preview` writes nothing and
  runs the same module, so what the CA is shown before confirming is what gets
  posted.

## From CLAUDE.md section: Reporting performance — the rule, not a preference

**HOW OLD THE STOCK IS, IS A QUESTION ABOUT THE UNITS AND NOT ABOUT THE ITEM**
(INV-04, migration 408). Last Moved and Days Idle come off 363 and ask whether
the ITEM has moved; an item selling steadily has a recent answer and may still
be carrying units bought three years ago behind the ones that keep turning
over. Those are the AS-2 paragraph 24 obsolescence `/items/{id}/writedown` has
always offered with nothing to decide it on. `public.stock_ageing_as_at`
buckets the units ON HAND first-in-first-out, with
`domain/reporting/stock_ageing.py` as the mock-mode twin and
`tests/test_stock_ageing_parity_pg.py` pinning them.
**THE CONSUMPTION IS AGGREGATE, NOT STEP BY STEP**, which is what makes it
order-independent the way 363 needs: with `T` the total quantity out and `cum`
the cumulative quantity in up to a receipt, what survives is
`min(qty, max(0, cum − T))`, and Σ over the receipts is the position by
construction. The step-by-step walk agrees whenever the position is
non-negative and differs only in the oversold case, where it has to invent a
rule for what a later receipt clears first.
**AGEING IS FIFO FOR EVERY CLIENT, whatever their cost formula is.** AS-2
paragraph 14's choice (migration 394) governs what an ISSUE is valued at, not
which carton was carried out, so a weighted-average client's ageing is the same
physical answer — and tests assert the two modules never read each other, since
a batch or a band leaking into costing would make specific identification (AS-2
paragraph 13) a third cost formula by accident.
**THE VALUE IS THE CARRYING AMOUNT PRO-RATED BY QUANTITY, never the layer's own
cost.** Under the weighted average the value that LEFT was the blended figure,
so the surviving layers' costs do not sum to the carrying amount — and a stock
ageing report whose total disagrees with the Inventories line is worse than no
report, because somebody will foot it. Largest remainder, so the parts sum to
the whole exactly.
**The six bands are a stated CONVENTION** — Schedule III's ageing schedules
(G.S.R. 207(E)) reach trade receivables and payables only and AS-2 sets none —
and **no provision is computed**, because AS-2 paragraph 21 makes net
realisable value an estimate of selling price less the costs to complete and
sell, a fact about the market no ledger holds. Three more refusals: nothing is
bucketed by godown or batch (`domain/inventory/batches.py` already ages by
EXPIRY, which is the other question), an item with **nothing on hand carries
`nothing_on_hand` rather than six zeroes**, which would read as a clean bill of
health beside a negative quantity, and an item whose position netted to nil is
still reported, 363's rule about a report that silently omits rows.
⚠️ **The FIFO tie-break on the row id is DETERMINISM, not correctness**, and
the difference is recorded because the obvious claim is wrong: two receipts
sharing a `movement_date` share a BAND by construction, so whichever is
consumed first the figures are identical. A negative control that dropped the
key PASSED, which is how this was found. It is kept and pinned so the two
halves walk the same layers if a later change makes layer identity matter.

**AND WHAT THAT RECEIPT COSTS INCLUDES THE TAX NOBODY CAN RECLAIM.** AS-2 (and
Ind AS 2) paragraph 6 puts "duties and taxes (OTHER THAN THOSE SUBSEQUENTLY
RECOVERABLE by the enterprise from the taxing authorities)" in the cost of
purchase — so creditable GST is excluded and always was, and credit barred by
CGST §17(5) is recoverable from nobody and belongs in cost.
`domain/inventory_service._blocked_tax_on_line` is the rule and
`apply_purchase_to_inventory` costs the receipt at the line's taxable value
PLUS it. It used to cost the receipt at the taxable value ALONE while PUR-04's
`blocked_total` block had already debited that tax to the LINE'S OWN expense
account, so the receipt journal moved only the taxable value out and the tax
stayed behind for ever: ₹1,000 of goods with ₹180 blocked leaves Inventory
₹1,000 and Expense ₹180. Closing stock understated, the period's expense
overstated, and — because the moving average is computed off the same figure —
every later COGS wrong too. **It needs no new account and no migration**: the
expense account already holds the tax, and the receipt journal resolves its
credit with the SAME fallback order the bill journal used (explicit
`expense_account_id` → `%Purchase%` → `%Expense%`), so it relieves exactly the
account that received the debit. `value_delta_paise` and the journal's
Inventory debit are one number by construction, so the tie above survives —
both move together, which is why a test asserts the expense account nets to
ZERO across the two journals. A NULL `itc_eligible` reads as ELIGIBLE, matching
migration 240's `NOT NULL DEFAULT true`; a blocked SERVICE line capitalises
nothing because it never reaches the stock ledger at all; and a purchase RETURN
relieves on the client's own cost formula (the moving average unless FIFO is
recorded — see INV-02 below), which now carries the tax. **Freight inward,
insurance and customs duty are in cost too since migration 396** — the other
two-thirds of INV-05, see the next bullet.

**WHAT ELSE THE GOODS COST TO GET HERE IS RECORDED AGAINST THE BILL, AND THE
BASIS IS A POLICY THE STANDARD DOES NOT GIVE** (INV-05, migration 396). AS-2
paragraph 6 puts "freight inwards and other expenditure directly attributable
to the acquisition" in the cost of purchase alongside the non-recoverable
duties above; the receipt costed a line at its taxable value plus its blocked
tax and nothing else, so a client who paid to bring a consignment in carried
stock at less than it cost, expensed the freight in the month it was billed
rather than when the goods sold, and — the cost formula running off the same
figure — got every later COGS wrong with it.
`domain/inventory/landed_cost.py` is the rule and
`services/landed_cost_service.py` fetches, previews and carries over.
**AS-2 SETTLES WHAT GOES IN AND NOT HOW TO SPLIT IT**, so the basis is an
accounting policy rather than a derivation — by value is wrong for a container
of identical t-shirts, by quantity is wrong for 200 chairs and 20 tables, and
₹50,000 of freight over exactly that consignment is ₹14,285.71 / ₹35,714.29 by
value against ₹45,454.55 / ₹4,545.45 by quantity. **BOTH are built, value is
the default**, the policy is `clients.landed_cost_basis` and one consignment
may override it with `purchase_bills.landed_cost_basis` — the shape every
product in this tier ships (TallyPrime appropriate-by-quantity / by-value per
expense ledger, Zoho Books quantity/value on save, QuickBooks Enterprise
quantity/amount/percentage; Xero has no allocation at all). Owner decision of
14-09-2026. **Weight and volume are NAMED and not offered**: the most accurate
basis for freight specifically, and `service_catalogue` holds no weight, so it
needs a column and a figure typed per item first. Both columns are nullable
with **no default and no backfill**, so a client with nothing recorded is told
the default is a policy they have not stated.
**`applied_at` IS THE BOUNDARY AND IT IS STAMPED AFTER THE JOURNAL.** A charge
recorded after the receipt is KEPT and REPORTED rather than silently left out
or quietly folded in — migration 251 makes the posted journal immutable, so
whether to reverse is the CA's decision, and the row carries the sentence
saying so. Stamping before the journal would leave a charge marked done on a
receipt that failed, which is the one outcome the feature exists to stop.
**EACH CHARGE KEEPS ITS OWN ACCOUNT**: the receipt credits the goods line's
expense account for the line's own cost and each charge's account for its
share, split with `split_pro_rata`, which returns the weights EXACTLY when the
amount equals their total — so the ordinary case needs no branch and the
journal balances with no plug. The split is largest remainder for the same
reason `domain/gst/discount.py` is. **A SERVICE LINE TAKES NO SHARE** (it never
reaches the stock ledger, so the share would simply vanish out of the cost),
and a charge with nothing to attach to stays UNAPPLIED and keeps being
reported rather than being marked done. **The Bill of Entry's non-creditable
duty carries itself over** — basic customs duty and the social welfare
surcharge, which migration 389 could name as cost and not act on for want of a
basis — from BOTH doors, create and PATCH, because a carry-over on create
alone is one correction away from a stale figure; restating is safe by
construction since the update is `.is_("applied_at", "null")`.

**THE COST FORMULA IS A CLIENT POLICY, AND ONLY ONE FUNCTION FORKS ON IT**
(INV-02, migration 394). AS-2 paragraph 14 permits FIFO **or** weighted
average, and the product had only the second — so a client whose books are
kept on FIFO had a closing stock figure, and therefore a profit, that its own
accounting policy note did not describe. `domain/inventory/costing.py` is the
authority. **A RECEIPT COSTS THE SAME UNDER BOTH**: the formulas assign cost to
what goes OUT, and the running value rises by the receipt's own invoice cost
either way — so the fork is entirely inside `record_stock_out`, the
oversold-absorb split is common to both, and `domain/reporting/stock_position`
needs no change at all (a test asserts it never mentions the formula).
**Paragraph 16 makes it a property of the ENTERPRISE'S inventories**, so it
lives on `clients.inventory_costing_method` and no caller may choose one:
`CostingPolicy` carries the client it belongs to and a movement REFUSES a
policy that is not its own, which keeps passing it down a cached read rather
than a choice — the posting paths resolve it once per document, because
`clients` is a Singapore-to-Mumbai round trip and an invoice has as many lines
as it has lines.
**NULL IS NOT A DEFAULT DRESSED UP AS ONE.** The client column is nullable
with no default and no backfill, and reads as the weighted average — which is
a FACT, not a guess: every book in this product was kept that way because it
was the only formula there was. The LEDGER column
(`inventory_stock_ledger.costing_method`) IS defaulted and backfilled, for the
opposite reason — the value is known for every existing row — and it is what
makes AS-5 paragraph 32's disclosure derivable from the ledger instead of
remembered. A CHANGE IS PROSPECTIVE: nothing is ever re-costed, so
`switch_refusal` requires a date and refuses one stock has already moved on or
after, because re-costing would move a closing stock figure already in a filed
return.
**A LAYER CARRIES ITS VALUE, NOT A UNIT COST**, and that is the same decision
`_compute_stock_in` makes blending the average from the exact total: three
units costing ₹100 have a unit cost of 3,333 paise and a value of 10,000, and
`3 × 3,333` is 9,999. A layer takes the ledger's own `value_delta_paise`, a
whole layer is consumed at its whole value and a part layer is split by
quantity with the remainder keeping exactly what is left — so the layers tie
to the books to the paise, and the one paise that would otherwise appear on
every awkward receipt cannot be mistaken for the real difference a
cancellation reversal leaves. **The layers are DERIVED from the ledger, never
stored** (migration 278's reasoning), replayed forward from the last row whose
running quantity was at or below zero — the force-close pairs that with a
value of exactly zero, so nothing before it can matter — **carrying that row's
own oversold deficit**, without which a receipt clearing an oversell becomes a
layer of its whole quantity. **`record_stock_out_at_value` is deliberately NOT
forked**: a cancellation reversal removes the value the original movement
added because the journal side reverses that entry at its original value, which
is not a FIFO concept at all, so `rebase` puts the layers back on the books
afterwards rather than pretending the two agree. Standard cost is REFUSED and
named (AS-2 paragraph 17 — two judgements no ledger holds, and it needs a
variance account and a revision cycle to mean anything).

**THE SIGNIFICANT ACCOUNTING POLICIES NOTE STATES THE FORMULA THAT PRICED THE YEAR, READ FROM THE LEDGER'S OWN STAMPS** (POST-A-108). `routers/year_end_notes` said "valued on the moving average cost basis" for every client with a goods item and called that true by construction; since migration 394 a client may be on FIFO, so a FIFO client's signed note misstated an accounting policy (AS-2 paragraph 14). The note now reads which formula priced THIS YEAR's movements from `inventory_stock_ledger.costing_method` inside the engagement's own dates, not from `clients.inventory_costing_method` alone, because that column is TODAY's policy and a client switched to FIFO on 01-04-2026 had a FY 2025-26 costed on the weighted average. `_decide_inventory_formula` (pure) has four answers: one formula priced the year (stated, and if the recorded formula now differs the CA is asked to confirm the date it took effect); two formulas priced movements in the year (a change of accounting policy, stated with its dates, AS-5 paragraphs 29 and 32, prospective and nothing re-costed, and "Effect of the change" goes on the CA's list because the effect is not a figure this module may compute; overlapping dates claim no change date); no movement in the year (the recorded formula, said to be exactly that, and a client with nothing recorded gets the byte-identical moving-average sentence because that was the only formula the product had); and unavailable (no formula asserted, the item goes on the CA's list). **A godown transfer prices nothing** (`costing.MOVEMENT_TYPES_THAT_PRICE_NOTHING`): it moves value at the source godown's own cost and posts no journal, but `inventory_location_service.transfer` inserted its rows without `costing_method`, so migration 394's NOT NULL DEFAULT `moving_average` stamped them, and a FIFO client with one transfer read as having changed policy. The readers now skip transfer rows (nothing back-fills the ledger, so history needs the read-side filter) and the writer stamps the formula in force; `tests/test_every_writer_of_the_stock_ledger_stamps_its_formula.py` finds every writer of the ledger by AST and fails one whose payload cannot be shown to carry the stamp, spreads included. A note already generated stays as it was until regenerated, and a locked note is never replaced by Generate. Seen and not changed: `services/form_3cd_service._clause_14` reads the current `clients.inventory_costing_method` for a past year, and `inventory_costing_policy_service.movement_on_or_after` still counts transfers, which can only refuse or suggest a later date.

**STOCK HAS A PLACE AND A LOT, AND ONE OF THEM CHANGES WHICH RETURN A MOVEMENT
IS IN** (INV-03a, migration 398). `inventory_stock_ledger` recorded WHAT moved,
WHEN and for how much, and never WHERE or WHICH LOT — so a client with two
warehouses had one undifferentiated pile and a client whose goods expire had no
way to say which ones. Owner decision of 14-09-2026 over the alternatives in the
same finding (item group, reorder level, alternate unit): all three together,
because all three touch the stock ledger.
**A GODOWN IS NOT DECORATION.** CGST §25(1) requires registration in every State
a taxable supply is made from and §25(2)'s proviso allows a second within one
state, so a godown carries its own `state_code` and the registration it operates
under. **Schedule I paragraph 2 with §25(4) then makes a transfer between two
godowns under DIFFERENT registrations a supply even without consideration** — a
tax invoice is owed — while a transfer under the SAME registration is not a
supply at all and travels on a Rule 55(1)(c) delivery challan.
`domain/inventory/location.py` states it and **REFUSES to mint the invoice**:
the value is §15 with Rule 28 (open market value, like goods, or 90% of the
recipient's onward price, at the supplier's option) and which the client elects
is recorded nowhere here. The decision is a **TRI-STATE** — the third is where a
registration is not recorded, because one guess mints a document the Act does
not ask for and the other omits one it does. **The comparison is on the
REGISTRATION, never the state**: two Maharashtra godowns under different GSTINs
ARE distinct persons.
**A BATCH IS A TRACEABILITY AND EXPIRY DEVICE AND NOT A COST FORMULA**, and that
is the line the feature must not cross. AS-2 paragraph 14 permits FIFO or
weighted average and migration 394 made the choice a client policy; paragraph
13's specific identification — costing an issue at its own batch's cost — is a
THIRD formula, and a batch column is exactly what invites it in silently. A test
asserts `record_stock_out` never mentions a batch. **First-expiry-first-out is a
PICKING order, suggested and never applied**, for the same reason.
**BOTH LEDGER COLUMNS ARE NULLABLE AND NOTHING IS BACK-FILLED.** Every movement
already recorded happened at a location and in a lot nobody wrote down; stamping
a default godown on them would assert they all happened THERE. NULL is a REAL
GROUP in the detail report, not a row to drop, and the total still ties to the
Inventory control account because it is the same deltas either way.
**`stock_position_detail_as_at` IS A SECOND GRAIN, NOT A SECOND ANSWER** — it
sums the SAME deltas grouped per (item, godown, batch), so its total is
`stock_position_as_at`'s total by construction, and a real-Postgres test asserts
exactly that alongside the ordinary SQL/Python parity. **Stock is good ON its
expiry date** (a shelf life runs to the end of the stated day; reading it the
other way writes off a day of sound stock and reverses §17(5)(h) credit that is
not yet due), and **a batch with no date is its own bucket, never "later"** —
stock that does not expire and stock whose date nobody recorded are opposite
situations. A **transfer posts NO journal**: within one entity the stock is
worth what it was worth before it was carried across the yard, and the two rows
carry equal and opposite value. **The value moved is the SOURCE godown's own**,
not the item's blended average, or the per-godown position drifts from the total
it must sum to.

**AN ITEM IS STOCKED IN ONE UNIT, TRANSACTED IN ANOTHER, AND REORDERED AT A
LEVEL SOMEBODY CHOSE** (INV-03's other two conveniences and INV-09 part 3 — each
finding deferred the alternate unit to the other, so neither built it; migration
409). A wholesaler buys cement in tonnes and sells it in bags; a stationer buys
pens in boxes of twelve and sells them singly. One `unit` meant the CA re-typed
a converted quantity onto every line or kept two catalogue rows for one physical
item, at which point the on-hand figure is split across two rows and ties to
nothing. `domain/inventory/units.py` is the rule and `domain/inventory/reorder.py`
the report.
**THE LEDGER NEVER LEARNS A SECOND UNIT EXISTS.** `inventory_stock_ledger` holds
`quantity_delta` and `stock_position_as_at` sums the deltas, so a movement
recorded in either unit would add boxes to pieces. The conversion happens at the
DOOR and nothing stores a quantity in the alternate unit — a test asserts
`record_stock_out`, the position reader and the costing module never mention it,
the same discipline migration 398 took about a batch, because a column that
COULD change what is stored is the one that eventually does. `to_alternate`
exists for DISPLAY and is recomputed on every read (migration 278's reasoning
applied to a quantity).
**THE CONVERSION REFUSES WHERE THREE DECIMALS CANNOT HOLD IT.** Every quantity
column is `NUMERIC(10,3)`, so truncating understates what moved and leaves stock
on the books that has gone, while rounding up writes off stock that is there —
`quantity_violation`'s own argument, and neither direction is safe.
**`units_per_alternate` IS NAMED FOR ITS DIRECTION**: `conversion_factor` does
not say which way it points, and a factor applied upside down is a 144× error on
a box of twelve that still looks like a plausible quantity. Both or neither,
CHECKed; the alternate must be a real UQC and must differ from the primary —
REFUSED where `unit` only normalises, because that carve-out exists for rows
predating the dropdown and a column added by 409 has none.
**AN ABSENT REORDER LEVEL IS ITS OWN STATE AND IS NEVER ZERO.** Zero is a real
answer — "tell me when it runs out" — so reading NULL as zero records a decision
nobody made and parks every item in the "above" bucket for ever. At the level
counts as needing a reorder (a strict `<` holds the order until the item is
already short), and the on-hand figure is the LEDGER's, never the cached
`stock_qty_units` migration 188 documents as a cache: a purchasing prompt off a
drifted one says there is stock there is not.
**THE ITEM GROUP NEEDED NO COLUMN.** `service_catalogue.category` has been free
text since migration 180 and NOTHING ever grouped by it — the `capital_wip`
shape a third time. Two spellings fold to one group, the first spelling is the
label, and an unrecorded group is its own row rather than dropped. Nothing
statutory turns on any of it.

**A PHYSICAL STOCK COUNT IS ONE SESSION, AND THE VARIANCE IS A FACT ABOUT THE
COUNT DATE** (INV-08, migration 387). Adjustment was one item per API call and
one modal per item, reachable only from inside an item's ledger drill-down — so
a 31 March stock-take with a hundred variances was a hundred retyped
quantities, a hundred §17(5)(h) decisions and a hundred journals with no common
reference tying them to the count. `domain/inventory/count_session.py` is the
RULE (which lines vary, by how much, in which direction, and which cannot post
yet); it reads nothing and posts nothing.
`services/stock_count_service.py` fetches its inputs and posts through
`domain/inventory_service.apply_stock_adjustment` once per varying line — the
SAME function the single-item path calls, so there is no second stock write
path — with the session's own `reference_no` on every one.
**THE SYSTEM QUANTITY IS ON BOTH SIDES OF TIME.**
`stock_count_lines.system_qty_units` is what the books said when the sheet was
OPENED, kept so the CA can see the books moved under them; the variance that
POSTS is recomputed at post time against the position AS AT THE COUNT DATE,
because a 30 March purchase bill entered on 2 April changes what the books say
for 31 March and posting the snapshot's variance would re-introduce the very
difference that bill corrected. Where the two disagree the sheet SAYS so, and
**no variance is stored** for the same reason — a stored one is wrong the
moment a backdated document lands. **`reverse_itc` is nullable with no default
and a SHORTAGE cannot post without it** (whether damaged stock's credit must be
reversed is a CA judgement, since it might still be sold at a discount), while
a SURPLUS needs no decision and is REFUSED if it claims one. Both refusals are
per LINE: a hundred-line sheet with two undecided posts the ninety-eight and
names the two, because refusing the batch sends the CA back to the
hundred-clicks path. **The batch is not atomic and cannot be** — each
adjustment is its own journal through the posting kernel — so a line that
failed is NAMED in the response and re-posting the session is refused rather
than doubling the lines that succeeded. **`post_session` asks BOTH period
questions**, which `routers/inventory.py:adjust_stock` does not: a shortage
registers its §17(5)(h) reversal on GSTR-3B Table 4(B)(1) (INV-06), so a count
sheet IS a document that feeds a return and `period_lock_service.assert_open`
applies — unconditionally, not gated on whether any line happens to carry a
reversal, the same reasoning a fixed asset's acquisition takes.
