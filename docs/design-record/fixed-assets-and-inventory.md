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

- **THE CATALOGUE IS THE CLIENT'S, SO A STOCK POSTING ASKS FOR THE ITEM UNDER THE FIRM AND THE CLIENT, AND A REVERSAL READS THE LEDGER THE SAME WAY** (POST-A-109, 17-10-2026). engineering-28 put a firm filter on the four paths that post a document to stock (sale, purchase, credit note, debit note), but `service_catalogue.client_id` is NOT NULL since migration 182, so within one firm a line on client A's document naming client B's item still resolved and moved B's stock, wrote the movement under A and priced the cost of goods sold off B's average cost. **That is the live defect, and it is reachable**: nothing checks a line's item id when the document is created (`models/invoices.require_service_catalogue_id` tests only that the id is not blank, and the sales and purchase routes copy it onto the row), so the posting lookup is the only place the item was ever asked for. The four lookups carry `.eq("client_id", client_id)` now; `apply_stock_adjustment` and `apply_nrv_writedown` look their item up under both as well (the routes ask first, but these are the functions that move the stock), `apply_nrv_writedown` answers None for an item that is not this firm's and client's where it used to fall through to a placeholder name and move the stock anyway, the landed-cost preview (`landed_cost_service.read_for_bill`) no longer names another client's item, and **`inventory_location_service.create_batch` reads its item under the firm and the client** (found by the independent review: a batch took `service_catalogue_id` from the request body, a foreign key ignores row security, so another firm's or client's item id was accepted, the lot number was taken away from the item's real owner by the per-item unique key, and the answer was an existence oracle). The two reversal paths (`reverse_sale_stock`, `reverse_purchase_stock`) read the ledger by `(source_type, source_id)`, so they now read it under the firm and the client too, for the idempotency probe as well as the rows to reverse. **Those reversal filters are DEFENCE IN DEPTH, and the record says so rather than presenting them as a live defect**: both routes resolve the document under the firm before they call them, a document id is a UUID, and the probes also key on the source type, so no input is known that makes them fail today. The log note for a line that moved no stock now says "this firm and client". Measured in production on 17-10-2026, read-only: all 12,114 `inventory_stock_ledger` rows match their item's firm and client, none lacks an item, no catalogue row lacks a client, and the 9,481 sales-invoice and 2,593 purchase-bill rows each match their source document's firm and client, so no data repair is owed and the filters change no existing result. `tests/test_an_id_in_a_request_is_looked_up_under_the_firm.py` holds the behaviour, including a set whose rows share the client and differ only in the firm (the other-firm fixture also differs in client, so on its own it could not tell the two filters apart; removing only the firm filter fails nine of them). The stock count service already read its items under both. Deliberately NOT done: the stock writers (`record_stock_in`, `record_stock_out`, `record_stock_out_at_value`) still CAS-update the catalogue cache by item id alone, because every caller resolves the id under the firm and client first (the reversal paths through ledger rows read under both); and the document create doors still accept a line naming a sibling client's item, which the posting now ignores and logs (the ledger carries the 422 as its own item).

- **THE FIXED-ASSET REGISTER IS CHECKED AGAINST THE LEDGER IN BOTH DIRECTIONS, AND THE TWO CHECKS THAT ASK THE LEDGER RUN ONLY WHEN THE CALLER HANDS THEM WHAT THE LEDGER HOLDS** (POST-A-110, the residue of FA-20, 18-10-2026). `domain/fixed_assets/integrity.register_findings` ran five checks and every one read the register (or the bill behind an asset); the two asks of the LEDGER the original finding wanted were absent. **`disposed_asset_has_no_disposal_journal`:** the register says an asset was disposed of and the ledger holds no live disposal entry for it, so its cost and accumulated depreciation are still on the balance sheet and no gain or loss reached the profit and loss account; the finding carries the carrying amount still on the books. The disposal route claims the row first and posts the journal second (compensating if the post fails), so a process that dies between the two leaves exactly this, and a disposal journal that was reversed without un-disposing the asset leaves it too. **`acquisition_journal_has_no_asset`:** a live acquisition entry (source `fixed_asset`: the cost entry `FA-ACQ-` or the reclassification `FA-CAP-`, the only two writers of that source) whose asset the register does not hold, so cost sits in Fixed Assets with nothing behind it. **Live means not deleted, not reversed and not itself a reversal** (`deleted_at`, `is_reversed`, `reversal_of`): deleting an asset reverses its acquisition, which is the mechanism working and not a finding, and a reversal entry carries the original's source and must not be read as a second acquisition. Both are filed CRITICAL by the nightly sweep and "Verify Books" (money on the books the register disowns, and a disposal the ledger never saw) and have a label each in the check catalogue and a title on the Reports tab. **Shape:** the rule stays pure; it takes an optional `LedgerLinks` (the set of assets with a live disposal entry, and the live acquisition entries), and **without one the two checks are not asked**, so a caller that could not read the ledger is never told "every disposed asset is missing its entry" (an EMPTY set is an answer, and reports them all, which is why it is not the default). `services/fixed_asset_ledger_links.fetch_ledger_links` is the one fetch, read by BOTH the endpoint and the sweep, because the original module's warning stands: two copies of a fetch over the same register are how a screen and a sweep come to disagree about a client. It reads the disposal entries only for the disposed assets, in chunks (`fetch_all_in`), and the client's acquisition entries paged (`fetch_all`), both keyset-paged. Five mutations of the fetch and the rule each failed between one and three tests (no `is_reversed` filter, no `reversal_of` filter, the sweep not passing the links, the disposal read for every asset, the orphan check ignoring the held assets). `tests/test_every_check_this_engine_emits_is_named.py` pins the catalogue's count of "other checks" as a literal on purpose, and moved from 13 to 15 with this (the sentence is filled in at read time, so none changed). **Not done:** the depreciation-GL-versus-register difference, which `fixed_asset_movement.movement_gaps` already states per year; a repair (every remedy here is a judgement, and the endpoint still offers no fix button); and nothing was run against production data (no migration; the check reads existing columns, `journal_entries.source_type`, `source_id`, `is_reversed`, `reversal_of`, `deleted_at`).

- **A STOCK MOVEMENT WHOSE LEDGER ROW IS REFUSED PUTS THE ITEM'S CACHE BACK TO THE LEDGER'S LAST ROW, AND AN OPENING-STOCK BATCH WHOSE LEDGER INSERT IS REFUSED REVERSES THE JOURNAL IT POSTED** (POST-A-321, found by the independent review of migration 536 and reproduced at SQL level, 22-10-2026). `inventory_service._insert_and_cache` claims `service_catalogue.stock_version` and writes the item's cached quantity and average cost FIRST (the compare-and-set that guards two concurrent movements) and only then inserts the ledger row, so a refused insert (a constraint, a refusal, a network error) left the cache AHEAD of the chain, and every `apply_*` caller swallows the failure by design (a sale must still issue): the stock screen showed a movement the ledger never recorded until the next successful movement happened to chain from the ledger's last row and overwrite it. **THE CACHE IS A COPY OF THE LEDGER'S TAIL, SO THE RESTORE READS THE TAIL:** on a refused insert `_restore_stock_cache_from_ledger` reads the item's last ledger row (the row the failed movement was computed from, unchanged because the insert failed) and writes its running quantity and average cost back, or nothing (`"0"`, 0) for an item with no ledger row, which is what the ledger says; it is a compare-and-set on the version the failed movement wrote, so a movement that has since claimed the item (and so already rewrote the cache from the ledger) is left alone, and it writes the version one further on, so the counter only ever moves forward. It does not try to remember the cache's previous values: only the ledger knows what the item holds. A restore that itself fails is reported (`_insert_and_cache.restore_cache`) and the original failure still reaches the caller, which reports it as before. **THE OPENING-STOCK BATCH POSTED ITS JOURNAL FIRST, ON PURPOSE, AND NOW UNDOES IT:** `seed_opening_balances_batch` posts one Dr Inventory / Cr Opening Balance Equity entry per client before the single ledger insert so each ledger row can carry its journal's id with no backfill; a refused insert left the general ledger carrying inventory the stock ledger lacks, the tie-out the stock ledger exists to protect. `_reverse_unrecorded_opening_journals` reverses each posted entry through the one reversal path (`reverse_entry`), dated the entry's own day so it nets inside the period the entry was open in; a client whose journal was never posted (a chart without the accounts, a zero total: the documented degrade, which `post_opening_stock_journal_entry` reports once itself) has nothing to reverse and no reversal is attempted for it, and a reversal that fails is reported (`seed_opening_balances_batch.reverse_journal`) without stopping the others. **BUT A FAILURE THE CLIENT SAW IS NOT ALWAYS A FAILURE THE DATABASE HAD** (the review's finding): an insert that committed and then timed out reaches the same handler, and reversing then would leave the stock ledger carrying inventory the general ledger lacks, the mirror-image mismatch, with the rows' `journal_entry_id` pointing at a reversed entry. So the handler first asks the ledger which opening rows of these items it holds (`_opening_rows_that_landed`, read with the request's client in chunks, the privileged one being used only to write): none landed (one statement, all or none) means reverse; some landed means the journals stand and the cache is written as after any successful insert; a ledger that cannot be asked (reported as `seed_opening_balances_batch.ledger_probe`) means neither, because reversing could be as wrong as leaving it. The single-movement path needs no such probe, because its restore re-reads the ledger tail and so is right whether the insert committed or not. The cache upsert that follows a successful ledger insert is unchanged: the ledger tail is the truth and the cache a copy. **NOT DONE, ON PURPOSE:** a document whose stock movement failed is still issued and the failure is reported to Sentry only, so nothing on the document says its stock effect was not recorded; that is the stock half of POST-A-092 (atomic issue), where it is now written down together with two places the review found that answer success over an unrecorded stock effect: the bulk product import when its opening-stock seeding is refused, and a multi-line document whose line 2 fails after line 1's movement was written (the COGS journal is then skipped, so the stock ledger is ahead of the general ledger by line 1). The cache and the opening-stock journal halves are what this entry closes. Tests: `tests/test_a_refused_ledger_insert_leaves_neither_the_cache_nor_the_general_ledger_ahead.py` (11 cases, no database: the cache restored to the ledger's last row with a prior movement and with none, the version only forward, a concurrent claimer not overwritten, a failed restore reported and the original error kept, a successful movement unchanged; the batch reversing the journal for each of two clients to a zero balance and dated the entry's own day, a client with no journal left alone with no reversal attempted for it, one failed reversal reported while the other runs, a successful batch keeping its journals, an insert that committed before the client saw it fail keeping the journals and writing the cache, and a ledger that cannot be asked what landed reversing nothing and saying so).

- **THE ITEM'S CACHED STOCK FIGURES ARE WRITTEN BY THREE FUNCTIONS ON THE PRIVILEGED CLIENT, EACH NAMING THE FIRM AND THE CLIENT, AND THE OPENING BATCH CACHES ONLY THE ROWS THE CALLER'S CLIENT READS AS THIS CLIENT'S.** (POST-A-327, 23-10-2026.) **WHAT WAS WRONG:** `service_catalogue.stock_qty_units`, `avg_cost_paise` and `stock_version` are a copy of the stock ledger's last row (the catalogue's Stock column, the product form's "stock already started" gate, the item block of the item ledger and the stock reconciliation show or compare it; the stock register, the reorder check and the next movement's cost read the LEDGER, not the copy, so a forged copy is a display and reconciliation lie and no more), and the signed-in role holds UPDATE on the table with only the assignment scope between a member and the row, so a member assigned to the client could set the copy to any figure over PostgREST (closing stock is summed from the ledger's deltas, so the books were not affected). The ledger's own note named the compare-and-set as "the one stock write that stays on the request's client", on the argument that row security confined the claim to the caller's clients and so the ledger row written next was for an item the caller could reach; a scan of every dict that builds one of the three columns found it was not the only one: **the opening-stock batch (`seed_opening_balances_batch`, now `_write_opening_cache`) UPSERTS the cache for every product it seeds, under the caller's sign-in as well.** **WHAT THE CHANGE DOES (Python only, no migration):** the claim in `_insert_and_cache` (and its NULL-version fallback), its restore after a refused ledger insert (`_restore_stock_cache_from_ledger`, which now takes the firm and the client) and the batch's upsert go through `ledger_writer(db)`, the helper that already hands the stock ledger's writer the privileged client where there is one. The privileged client carries no row security, so the two updates name `id`, `firm_id`, `client_id` and the version themselves (an item that is not this client's matches nothing, exactly as an item the caller could not see did, and the movement answers the same 409 after its retries), and the batch's upsert, which rewrites the firm, client and name of the row it finds by id, is handed only the rows that the CALLER'S client reads under this firm AND this client (one chunked read, row security the second lock; an omitted row is logged, and a read failure writes no cache and reports it, the ledger and the journals stand). Reads stay on the caller's client. **THE GUARD** (`tests/test_the_party_credit_tables_and_the_stock_ledger_are_written_with_the_privileged_client_only.py`, 29 cases, its rule widened and not relaxed): the privileged receivers may touch `service_catalogue` only in the three named writers, an update must chain the firm and the client, an upsert is the batch's alone; the functions that BUILD a cache column as a dict key, a subscript assignment or a keyword argument (a payload built in one function and written in another is the shape a rule on writers alone would miss) are exactly three, apart from two named displays that put the ledger's figure under those names and write nothing (the stock register, a report's own average cost), and no request model declares a cache column; each shape is shown to the detector; and driven through a request client that REFUSES a write naming a cache column the way `authenticated` will, a purchase and a sale, a refused ledger insert and its restore, and the opening batch (with another client's item and another firm's item under the same client id both left untouched, a membership read of more than one chunk, and a membership read that fails writing nothing) still succeed with every cache write on the privileged client. **NOT DONE, ON PURPOSE:** the database half, a trigger on `service_catalogue` that refuses a signed-in session's change of the three columns (a column grant would have to be maintained for every column added later), is migration 543 and merges only after this change has been on Render for an hour, because the old API against it fails soft and wrong: a movement's claim is refused with 42501, which is not a version conflict, so it propagates before any ledger row or stock journal is written and the callers swallow stock failures by design, so the movement is LOST silently (the opening batch inserts its ledger rows and caches nothing); POST-A-327 stayed open until then and is closed by migration 543.

- **A STRAIGHT-LINE ASSET KEEPS THE OPENING ACCUMULATED DEPRECIATION OF ITS YEAR, SO THE NOTE SHOWS THE YEAR'S CHARGE AND NOT THE LAST MONTH'S** (27-10-2026, no migration). **WHAT WAS WRONG:** `_annual_depreciation_for_period` returns the charge, the financial year and "the accumulated depreciation the year opened at", and the router stores the last of them on the asset after EVERY posting (`depreciation_fy_start_accum_paise`, migration 239). For a written-down-value asset the opening was resolved properly, reusing the stored figure for the rest of the year. For every other method the function returned early with the LIVE accumulated depreciation, so a straight-line asset's opening slid forward a month at a time. Nothing computed from the CHARGE could notice (cost, salvage and life never move), the function's own docstring said straight line was unaffected, and the existing straight-line test discarded the third value. What reads the stored figure is the fixed-assets note (`fixed_asset_movement`): it takes the year's charge as accumulated less opening, so twelve months of ₹1,333.33 showed as one month, and for an asset bought during the year the closing accumulated depreciation and the net block were short by the other eleven. The ledger was right throughout, so the register and the books disagreed (the note said so, which is how it was found). **HOW IT WAS FOUND, AND WHY NOTHING ELSE COULD HAVE:** by posting twelve months of depreciation for a machine and a straight-line software asset through the real API on a real database and then asking for the ITR-6 Part A (POST-A-344): the register's total net block was ₹14,266.63 away from the ledger's. The mock-mode doubles hold the row the code wrote, so a test of the posting that did not then ask the NOTE about the row could not see it. **THE FIX:** the opening is resolved once, for every method, by the rule WDV already used (the stored figure while the year is the stored year, the live balance on the first posting of a year), and only the charge differs by method. **PRODUCTION:** read on 27-10-2026, it holds four assets, all written-down-value, so no stored row is wrong and no repair is run; a straight-line asset posted before this fix would carry the balance before its last posting as its opening; posting further months of that year does not heal it, while reversing the year back to its first month and posting again, or the first posting of the next financial year, takes the live balance as the opening. **VERIFIED:** the full mock-mode suite on this tree, 27,772 passed, 5,587 skipped, 2 failed (both in the test that resolves `example.com`, which fails the same way on unmodified main in a container with no outbound name resolution); the eight new tests, four of which fail on the previous code (the opening sliding forward, the note's charge and closing balance for a new asset, the note's opening for an asset held from an earlier year, and the resolver itself); and the whole scenario again on a real database through the real API, where the register's total net block now equals the ledger's to the paisa (it was ₹14,266.63 away) and the per-line difference is exactly the software's amortisation, ₹15,599.96, which is POST-A-345's case. Lint ratchet 0 new, 0 stale. **NOT VERIFIED:** a straight-line asset on production (there is none).

- **A STRAIGHT-LINE ASSET'S YEAR IS CAPPED AT WHAT WAS LEFT WHEN THE YEAR OPENED, SO ITS LAST YEAR POSTS WHAT IS LEFT AND THE ASSET REACHES ITS SALVAGE VALUE** (27-10-2026, no migration; found by an independent read of the change above, not by a failing test). **WHAT WAS WRONG:** `_compute_annual_depreciation` caps a year's figure at what is left to depreciate (`min(annual, wdv_now - floor)`) and `wdv_now` is the asset's cost less the accumulated depreciation of the row it is handed. A written-down-value asset was handed a snapshot carrying the balance the year OPENED at (task #232), so its year's figure is worked out once; a straight-line asset was handed the live row, because the function returned early for every method but WDV and its docstring said straight line was unaffected ("cost, salvage and life never move"). That is true of the figure and false of the cap. In every year but the last the cap sits far above the figure and nothing shows; in the last year each month posted lowered the cap, so each month's charge was smaller than the one before: on a cost of 1,20,000.00 over five years bought on 1 April the fifth year posted 15,552.08 of 24,000.00 and 8,447.92 was never depreciated (the tail ran on after the end of the life without reaching salvage); an asset brought over from another system carrying more than its straight-line share is capped the same way. The register, the ledger and the fixed-assets note all agreed with each other and were all short, which is why nothing disagreed. **THE FIX:** `_annual_depreciation_for_period` hands `_compute_annual_depreciation` the year's opening snapshot for every method, so the cap and the "fully depreciated" test are judged from the balance the year opened at and the year's figure is fixed once. **PRODUCTION:** it holds no straight-line asset (read 27-10-2026), so nothing was posted wrongly and no repair is run; a straight-line asset posted by an earlier version would have its last year short by the amount above and is repaired by reversing and posting that year again. **VERIFIED:** eight new tests posting five years of months through the route, six of which fail on the previous code (the figure shrinking inside the year, the fifth year, the cost not written off, an asset brought over with most of its cost carried); and on a real database through the real API, a straight-line asset over its whole life: the previous code left 8,447.92 of 1,20,000.00 undepreciated and the ledger's accumulated depreciation agreed with it (1,11,552.08), the fix writes off 1,20,000.00 to the paisa in the register and the ledger. **NOT DONE, ON PURPOSE:** the monthly figure is the year's figure divided by twelve and floored, so a cost that does not divide into twelve discards up to eleven paise a year (8 paise a year on 1,00,000.00 over five years, held by the tests as the only shortfall allowed), and the final year of an asset bought part-way through a year is spread over twelve months at the smaller figure, which is the convention for written-down value too; moving either is a rule about rounding and the last partial year, and is not taken here.

- **AN INTANGIBLE ASSET'S AMORTISATION HAS A LEDGER OF ITS OWN, ONE FUNCTION SAYS WHICH, AND A PARTNER MOVES WHAT THE SHARED LEDGER HOLDS** (POST-A-345, migration 553, 27-10-2026). **WHAT WAS WRONG:** `journal_for_depreciation` credited the one `%Accumulated Depreciation%` ledger for every category and the disposal journal debited it, and the standard chart seeds exactly one (subtype Fixed Asset, which Schedule III presents on the tangible line). So a client with an amortised licence or software had the tangible line too low and the intangible line too high by the licence's whole accumulated amortisation, while the register (which keeps each asset's own figure) was right; the total balanced and the register's split between the two kinds (POST-A-344) had to be withheld for such a client. **THE TRAP, which shaped everything below:** a disposal must debit the ledger the asset's depreciation was credited to, so an asset with some history in the shared ledger and some in a new one is cleared from the wrong one, and the two ledgers still add to the right total while each is wrong by the asset's whole figure. **THE SHAPE:** `fixed_assets.accumulated_account_id` is a pointer (NULL means the shared ledger found by pattern, which is every asset before the change); migration 553 adds an `Accumulated Amortisation` ledger (code 1591 or the lowest free to 1599, subtype `Intangible Fixed Asset`, copying the CA's own mapping) beside each firm's Intangible Assets ledger, and `STANDARD_COA` carries it. The subtype is load-bearing: `classify` tests "intangible" first so the ledger lands on the intangible line, and it contains `fixed`, which is what keeps the cash-flow statement treating it as investing (with the cost ledger's own subtype an amortisation credit became a working-capital movement and the statement stopped reconciling, reproduced). `Phase2JournalService._accumulated_account_id` is the ONE function both the depreciation journal and the disposal journal ask; a pointed ledger that is missing, inactive, another practice's or not an asset ledger fails in a 422 sentence and is NEVER replaced by the shared ledger. **WHICH ASSETS BELONG THERE is one predicate** (`services/fixed_asset_accumulated_ledger`): the asset's cost ledger and the Accumulated Amortisation ledger classify to the SAME Schedule III line, by the account's subtype and the CA's own mapping, so a chart whose Intangible Assets ledger sits on the tangible line (migration 093's) keeps its assets in the shared ledger beside their cost. It is asked by asset creation, by capital work-in-progress capitalisation and by a category correction before any depreciation (an asset that already carries accumulated depreciation is refused a category that would put it in another ledger); the opening-register import stays unrouted on purpose, because it posts nothing and the carried-over part sits wherever the opening balances put it. **THE MOVE IS A PARTNER'S POSTING THE PRODUCT PREPARES:** a stateless preview (a stored draft goes stale), then a post under `accounting`/`approve`. **THE DATE decides which balance sheets change, so it is never defaulted and it is a MONTH END that is not in the future** (a mid-month date would split a month the ledger never splits). The entry for what the shared ledger held at that date is dated that date; the months posted AFTER it move in entries dated the END OF THEIR FINANCIAL YEAR (or, in the current year, today, or the latest month end among the months that entry holds when that is later, so that no entry ever debits a ledger before the credit it moves exists in it), so the balance sheet at every year end from the stated date is exact, an earlier one keeps the split it had, and a date BETWEEN year ends is partly corrected by exactly the months not yet moved: the preview says so in words and the real-database test proves the sentence with figures. One journal per asset and date (`FA-AMORT-RECLASS-<code>`, `-T2` and on), a new journal source type with drill-through. The amount moved is the register's figure, split into what the asset's own depreciation entries put in the shared ledger and the carried-over rest (depreciation an asset arrived with from other books). **THE CARRIED-OVER PART IS NEVER TAKEN FROM A LEDGER BY DEFAULT:** the shared ledger also holds the tangible assets' credit, so a balance check alone passes and a blank that meant "the shared ledger" would take a tangible asset's credit and leave the tangible line too high. The preview refuses until the Partner names the ledger; the server offers the active asset ledgers of the practice that hold a credit for this client and look like an accumulated-depreciation ledger (never Cash in Hand or a bank account in overdraft), choosing the shared ledger is a valid answer made on purpose, and a named ledger must be an active asset ledger of this practice and this client that is neither the new ledger nor on its Schedule III line (a move between two ledgers on one line fixes nothing). An asset where the ledger holds MORE than the register is left where it is and named. **IT REFUSES, WITH NOTHING NETTED:** a shared ledger (or the ledger named for the carried-over part) that holds less for this client than would have left it AS AT EVERY MONTH END from the first entry to the month of today, not only on the days an entry is dated (read from the monthly balances; a debit posted to the same ledger a month after the entry, such as the disposal of a tangible asset whose depreciation sits there, would otherwise take the tangible line's contra into debit on every later balance sheet and pass); a new ledger that already carries a credit nothing explains, or less than the assets pointed at it account for; a date before an asset with brought-over depreciation existed; an asset whose move did not finish; a balance that cannot be read; and a closed year at ANY date an entry will be dated. **FAILURE IS TOLD FROM THE LEDGER, NOT FROM MEMORY.** Each asset is CLAIMED first by compare-and-set on its pointer and previewed accumulated figure, the journals follow, and on a failure what is LIVE for the asset in the ledger is reversed (a call that timed out after it committed is found too) and the claim is undone only when nothing is left live; if a reversal fails the claim STAYS, the asset is reported as partly moved with its live entries, and the Undo, which works from the ledger and can be run again, finishes it. The Undo reverses each entry on the day it is dated, takes the pointer back with the same compare-and-set and NEVER puts it back over a ledger it emptied; it is refused while live depreciation or a disposal of the asset touches the new ledger (a month posted and since reversed does not count), for a disposed asset and in a closed year. **WHAT "DID NOT FINISH" MEANS IS READ FROM THE LEDGER:** an asset is half moved when an entry of its reclassification is still live while its pointer is empty (an Undo took it back and could not reverse everything), or when its pointer names the new ledger and the credit the new ledger holds for it (its live depreciation, reclassification and disposal entries) is not the register's figure (a claim that posted nothing, or only part). Such an asset is listed with a "Finish undo" button, is not offered for a second move (which would have moved it twice), blocks a new preview with the sentence saying so, and **cannot be disposed of or deleted**: a disposal debits whichever ledger the pointer names for the whole register figure while the two ledgers hold part each, and the undo refuses a disposed asset, so there would be no way back. **THE REGISTER UPDATES OF DEPRECIATION, DISPOSAL AND MONTH REVERSAL COMPARE-AND-SET ON THE POINTER THEY USED**, so a reclassification that commits in between makes the stale request undo its own journal and answer 409; a month posted before the move is refused its reversal in words, a reclassified asset cannot be deleted until it is undone, a disposal dated before the latest live reclassification entry is refused (it would debit the new ledger on a day it held nothing), and the generic journal reversal refuses the new source type and names the dedicated undo. Register integrity names an intangible asset still in the shared ledger (in words that are true for an asset not yet amortised too) and a disagreement between the new ledger and the assets pointed at it, with its direction, and its reply says when those two checks could not be run, so "nothing to report" is never said over a check that did not happen. **THE SCREEN** (Depreciation tab) asks a summary endpoint that reads the register, the chart and the reclassification entries (no balance sheet figure), says in the server's words when the chart cannot take the change (only for a client that holds an intangible asset, and in words a chartered accountant can act on), sends the date and ledger the preview was made for and not whatever the boxes hold now (editing either throws the preview away, and an answer that is not the newest request's is dropped, so a slow answer for an earlier date, ledger or client never lands on the current one; the mount is keyed on the client), keeps the ledger choice mounted while it re-asks, builds its confirmation from the server's figures, counts and dates (nothing is worked out in the browser) and hides the buttons from anyone who is not a Partner while the server refuses them regardless; a Python test reads the screen's types and fails when a key stops being served. **ROLLOUT IN TWO MERGES because the order is what makes it safe:** the migration with the readers (nothing wrote the pointer), then, once the migration is applied and checked on production, the writers; the rollback file RAISES while any pointer or reclassification journal exists. **VERIFIED:** the full mock-mode suite on this tree (only the two tests that resolve example.com fail, as on unmodified main in a container with no outbound name resolution); 11 real-Postgres tests through the real routes and journals on a real database (the two ledger lines tie to the register before and after to the paisa; year-end exactness and the between-dates shortfall with figures; a second client of the firm untouched; brought-over depreciation moved only from the ledger named; a later debit to the shared ledger refusing the move; a claimed-and-never-posted asset refused for disposal and finished by the Undo), and the real-Postgres schema and guard set against the production snapshots; 61 negative controls on the server, the screen and its guards, every one caught (one of them needed a new test, and each review finding has a test that fails without its fix); two rounds of independent read-only review whose findings are listed in the commit; and the screen driven in Chromium against the real API and database (a mid-month date refused in the server's words, a preview with months after the date, the preview discarded on a date edit, the confirmation, the post, an Undo, and a half-moved asset's "Finish undo"). **NOT DONE:** an account remap inside the kernel's reversal (refused instead); the cost ledger's own cash-flow subtype (POST-A-348, waiting on POST-C-212); an automatic choice of the ledger a carried-over part sits in (the server cannot know, so it asks); the three small gaps the final review left (a month reversal racing a post of the same month, a category correction racing the first month, the nightly reconciliation not naming the skipped amortisation checks: POST-A-349); and the choice of the ledger for brought-over depreciation was not clicked through in a browser (the server side is tested through the route and on a real database), and nobody at a firm has used the screen. **TWO OF THE THREE SMALL GAPS ARE DONE (POST-A-349, 28-10-2026).** (2) A category correction that re-decides the asset's ledger now CLAIMS it before the acquisition entry is touched: the compare-and-set on the pointer and the accumulated figure is the first thing that changes (with the new category, and an edit-log row of its own written first), so a refusal means nothing moved, and a first month that starts after the claim is credited to the new ledger, which is the right one. The correction's last write carries no pointer and is a compare-and-set on the accumulated figure instead (found by the independent review: without it a month posted on the OLD cost after the claim, credited to the new ledger because the pointer is already the new one, would have been left beside a cost that changed under it), so such a month is answered 409 with the cost left as it was; a correction that fails after the claim is completed by sending it again, after reversing that month if one landed. (3) The nightly reconciliation files `fixed_asset_register.accumulated_amortisation_checks_not_run` (a warning, in the catalogue, with the same sentence the register-integrity reply gives, both from `checks_could_not_run`) when the two Accumulated Amortisation checks were skipped because a read failed; a chart with no such ledger is not a failure. (1), a month reversed while the same month is posted, is NOT done and is now sized days: a half-done reversal and a half-done post leave the same state, so it needs a lease marker written by the reversal (a migration), written down in the ledger line.

**A DOCUMENT THAT MOVES STOCK SAYS, ON THE RESPONSE THAT ISSUED IT, WHEN THE STOCK DID NOT ALL MOVE (POST-A-092, THE STOCK HALF; 29-10-2026).**
A sales invoice, a purchase bill, a credit note and a purchase debit note move stock AFTER they are committed
(`inventory_service.apply_sale_to_inventory`, `apply_purchase_to_inventory`, `apply_credit_note_to_inventory`,
`apply_debit_note_to_inventory`) and swallow every failure on purpose, because a refused ledger row or a chart of accounts with no
Inventory or Cost of Goods Sold account must never un-issue a document that is already in the books and the return. The failure
went to Sentry and nowhere else, so the document read as complete while the stock ledger and the Inventory control account lacked
it. The four functions now RETURN what they did, as a `domain/inventory/stock_effect.StockEffect`: the goods lines they reached,
the lines whose stock-ledger row was written, whether the journal behind the movements was posted (`not_owed` where a movement has
no cost basis yet, `posted`, `not_posted`), and the type of any exception. A caller that ignores the return behaves exactly as
before; what the functions WRITE is unchanged. The four routes bind the return, put `stock_effect` on the response through
`attach()` (and `failed()` where the function itself broke its promise not to raise), and the nine screen sites read it through
`lib/documents/stockEffect` and print the SERVER's sentence: a toast on the sales screens (a warning kind, held 15 seconds, because
it carries a sentence to read), an amber `StockEffectNotice` panel on the purchases screens (the kind the TDS register's gaps
already use), and the invoice editor's done message. **Three rules held by tests.** (1) ABSENT MEANS "NO GOODS LINE" AND NEVER "ALL
WELL": a document with no goods line carries no `stock_effect` key at all, `recorded: true` is a separate, explicit answer, and the
browser reads a present field in the wrong shape as a problem with a fallback sentence and never as silence. (2) THE SENTENCE IS
WRITTEN ONCE, ON THE SERVER, from four failure shapes that are not one (nothing moved; part moved and the journal was skipped; all
moved and the journal was not posted; an error after the work), names the document by its own number so a bulk run's sentence is
about a document, and never carries the exception's message, which can hold an identifier: only its type is kept, for the log.
(3) `tests/test_every_screen_that_moves_stock_through_a_document_reads_what_the_server_says_about_it.py` finds the routes from the
routers (the function that calls `attach`, its decorator and its prefix) and every place the web app posts to one, and requires the
response to be read before the next call site, so a fifth route that learns to attach the answer is in the rule from that day. The
typed client's `api.salesInvoices.issue` had no caller and was deleted, because a typed member the rule cannot follow to its callers
is a second way in. **NOT DONE, and written into the ledger line (POST-A-092):** a retry that completes the missing lines (the
sentence says to adjust stock by hand or cancel and enter the document again); a trace on the document itself (the sentence is
shown once, and the nightly reconciliation still compares from the ledger side, so it does not name a goods document with no
movement at all); the bulk product import's opening-stock seeding, which still answers success when it is refused; and the repair
of a half-moved document, which is now REPORTED ("stock was recorded for only 1 of its goods lines") but still leaves the stock
ledger ahead of the general ledger by the lines that moved, because the COGS journal is posted from a total only reached when every
line moved. **FOUND BY AN INDEPENDENT READ OF THE DIFF, AND FIXED IN THE SAME CHANGE.** (a) `moved_lines == goods_lines` is not "every line moved" while the loop is unfinished: `goods_lines` counts the lines REACHED, so a purchase whose first of two lines raised after its stock row was written read as a journal-only failure; `StockEffect.lines_done` is set when the loop ends and `_stopped` claims an unposted journal only after it. (b) A call that raised before the first goods line was counted knows nothing about what the document carries, so its sentence says "any goods on it may not have been ..." and sends the CA to the stock report; it used to say the goods did not move, for a service-only invoice too. (c) The advice and the accounts are per document: a credit note and a debit note have no cancel route, so they are told to adjust stock by hand and never to cancel; a sale and a sales return name Inventory with Cost of Goods Sold, a receipt and a purchase return name Inventory with a Purchases or Expense account (the accounts the journal helpers look up). (d) A warning that travels as the editor's done message was a green success toast for four seconds: the flash link now carries `flashKind=warning`, the list shows it as a warning for fifteen seconds, and `showToast` clears the previous timer so a later toast is not wiped by an earlier one. (e) A panel's sentences are cleared when the client changes. **WHAT THE RULE STILL DOES NOT PROVE:** the screen rule proves each call site reads the response through the one module, not that the result reaches the screen (a read whose result is dropped passes), and a goods line the function skips without trying (a purchase line with no cost, a line naming an item that is not this client's) is not counted as one, so a document made only of those carries no `stock_effect` and the unresolved item is still only logged.
The screens were not driven in a browser.


**A BULK PRODUCT IMPORT SAYS WHICH PRODUCTS IT CREATED WITHOUT THE OPENING STOCK THE FILE ASKED FOR, AND IT ASKS THE STOCK LEDGER AND DOES NOT INFER IT FROM THE SEEDING HAVING RETURNED (POST-A-092, THE BULK-IMPORT HALF; 30-10-2026).**
`POST /api/service-catalogue/bulk` inserts the products and then seeds an opening stock row for each goods line that came with a quantity and a cost. The seeding never raises, by design (one bad opening balance must not fail a 300-product import), and it also returns when its ledger insert was refused, so the route answered a plain success whatever it did: the catalogue rows kept `opening_qty_units` and `opening_cost_paise` while the item's stock stayed at 0, and the failure reached Sentry only. The route now asks the stock ledger which of the items that came with an opening balance have an opening row (`inventory_service.items_with_an_opening_row`, the probe `_opening_rows_that_landed` already used, returning the ids now) and answers `opening_stock` (`domain/inventory/opening_stock_report`): the count asked, the count recorded, the items with none by name, whether the ledger could be read, and one sentence. A batch that landed in full has no sentence; a ledger that could not be read is "could not check" with no count claimed, never "recorded"; the products are created in every case, as before. The import screen pushes the server's sentence into the result's list as written and counts nothing itself. Deliberately NOT done: a retry that completes the missing opening rows, and the same answer for the single-product create and the product edit, whose seeding is per item and equally swallowed. The failure path was produced on the in-memory double, not against a real Postgres, and the screen was not driven in a browser.
