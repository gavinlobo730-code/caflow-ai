# Design record: Bank entries, credit card accounts, matching rules, multi-currency and the AS 11 revaluation

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Where the design is written down

**Bank entries (09) in one paragraph, because it is easy to rebuild the old
thing by accident:** a statement line becomes a voucher — Receipt, Payment or
Contra, decided by direction and never chosen. The machine writes its best
proposal ONTO the row (`draft_*` columns, migration 322), graded `ready` or
`proposed` with a reason sentence, never a percentage. `entry_state` is a
trigger-maintained column (Python twin `domain/banking/entry.py`, pinned by a
parity test) — application code never writes it. The verb is **Pass**; "Pass N
ready" is chunked and resumable; a `proposed` draft is never passed in bulk. A
rule a Manager+ marks **trusted** passes its lines with no click, as
`created_by = trusted_by` — the one place the product acts unprompted, an owner
decision of 2026-09-03 that reversed the earlier "draft only" rule. The
posting path is still only `bank_posting_service.post`, and **which BANK
LEDGER either path posts to comes from one lookup**,
`BankPostingService.bank_account_id_for` — `bank_transactions` carries no
`bank_account_id` of its own, only `statement_id`, so the account is one hop
away through `bank_statements` and `match_and_settle_multi` was building its
receipt and payment payloads without it (ACC-03). `domain/accounting/
payment_account.resolve_payment_account` then fell through to the firm's
generic `%Bank%` ledger, so a line PASSED from the queue and the SAME line
SETTLED against a document landed in two different ledgers — the defect that
module's own docstring says it exists to end. The lookup returns None rather
than raising, because a transaction with no statement must still settle and the
resolver falls back exactly as before AND SAYS it fell back. **AND THE CA IS NOW TOLD, ON THE ROW AND IN THE CONFIRMATION** (D14,
24-09-2026 — that used to read *"`is_fallback` and `reason` still reach no
caller"*, and WHERE to tell them was the open owner decision). The row half is
`payment_account.row_notice`, which ASKS `document_names_no_account` rather
than restating branch 3's predicate — one rule, two callers, because a screen
re-deriving "did this fall back" from its own reading of the columns is how a
disclosure comes to disagree with the posting it describes. `stamp` /
`stamp_all` put it on every receipt and purchase-payment response under
`posting_account_notice`, **always present and null where the posting was
attributable** (`journal_source`'s discipline: an absent key and a null key
read the same to a screen and are different bugs).
**A BROWSER MIRROR EXISTS AND IT IS NOT AN OVERSIGHT**:
`apps/web/lib/accounting/postingAccountNotice.ts`, because the client Sales tab
reads `receipts` STRAIGHT OVER POSTGREST and no API response reaches it —
pinned by `tests/fixtures/posting_account_notice.json`, asserted from the
Python side.
**TWO OF THE THREE FALLBACKS ARE DELIBERATELY INVISIBLE ON A ROW**: a recorded
bank account with no ledger of its own, and a cash payment at a client with no
Cash in Hand, are facts about the chart of accounts at the moment of POSTING,
and seeing them from a list would need a lookup per row. They reach the CA in
the confirmation. A silent row is not a claim that the posting was
attributable.
⚠️ **And the unlinked-account branch was LYING.** It fell through to branch 3
and came back *"No bank account was recorded on this document"* — false, and it
sends the CA to set a field that is already set. `NOTICE_ACCOUNT_NOT_LINKED` is
its own sentence now, and a test asserts the three are three. It was invisible
for as long as nothing rendered them, which is the argument for rendering a
computed disclosure rather than computing one nobody reads.
**WHAT THE PARSER FOUND IN THE NARRATION IS BUILT ONCE**, by
`domain/banking/narration.parsed_view`, because there were two identical dict
literals — one per service — and BOTH omitted `cheque_no` (BANK-28), which
`ParsedNarration` has carried since the module was written and `describe()` has
always named in the summary. A cheque has no UTR, so the leaf number is the only
thing that tells one from the next, and plenty of Indian statements carry no
reference COLUMN at all — only a narration. So `match_and_settle_multi`'s
settlement reference falls back **caller → the file's own `reference_no` → the
parsed UTR → the parsed cheque number**, and that ORDER is the rule: a parse is a
reading of somebody else's document and must never displace what a person or the
statement itself said. The screens drop the cheque number where it merely repeats
`reference_no`.
**`bank_posting_service.post` is
INR-only and refuses rather than converting** — it calls `_create_journal` with
no `txn_currency`, so the kernel takes INR at rate 1 and a USD line reading
1,000.00 would be booked as one thousand RUPEES: balanced, footing, and wrong by
the exchange rate. Both the import (`banking_service._import_core`) and the post
refuse a non-INR `bank_accounts.currency`. `match_and_settle_multi` is
deliberately NOT guarded — it carries currency and exchange_rate through to
receipt/payment creation and is the path that already works; teaching
`post()`/`_plan()` the same needs a rate per statement line and a decision on
where the FX gain or loss leg lands, and `_create_journal`'s balance assertion is
exactly what an unbalanced FX leg breaks. `docs/audits/` and
the batch completion reports are historical records, not current specs.

**MULTI-CURRENCY HAS THREE GATES AND TWO OF THEM ARE NOW WRITABLE** (ACC-19).
`resolve_currency_policy` is `active = L1 AND L2 AND L3` — the environment kill
switch `MULTI_CURRENCY_ENABLED`, `firms.multi_currency_entitled` and
`clients.multi_currency_enabled`. All five multi-currency phases are BUILT and
none of it could be switched on: L2 and L3 (migration 146) were READ by policy.py
and six routers and **WRITTEN BY NOTHING** — no endpoint, no Pydantic field, no
screen, no seed — so only a manual UPDATE against the database could activate
any of it. `PUT /api/currencies/entitlement` and
`PUT /api/currencies/policy?client_id=` write them, Partner-only, and
`/settings/multi-currency` is the screen. **SELF-SERVE is an owner decision of
13-09-2026**: there is no billing or entitlement machinery in this product, so a
commercial gate has nothing to hang off; if it is ever sold the column does not
move and a plan check goes in FRONT of the endpoint. **The platform gate is shown
and never offered** — `core/feature_flags` says "No DB dependency", which is the
point of a kill switch. **The read says WHICH gate is down**, because `active:
false` alone is what made the feature unusable: a Partner ticked something and
could not tell. Turning a client ON is REFUSED with a sentence where it would be
inert — the firm is not entitled, or the client's functional currency is not INR,
Capability B (presentation and translation) being unbuilt — while turning it OFF
is never refused. `GET /api/currencies/entitlement` answers the firm gate with no
client in the request, because a firm with no clients yet is exactly the firm
this gets switched on for.

**THE AS 11 YEAR-END REVALUATION WAS BUILT, TESTED AND UNREACHABLE.** AS 11
paragraph 11 retranslates a MONETARY item held in a foreign currency at the
CLOSING rate on each balance sheet date and paragraph 13 takes the difference
to the profit and loss account, so a client with an open USD receivable at
31 March carries it at the rate it was invoiced at until somebody restates it.
`domain/currency/fx_revaluation_service.py` has done exactly that since
Multi-Currency Phase 4 — idempotent, self-healing, period-aware, posting
through the one kernel and auto-reversing on day 1 of the next period — with
**ZERO production importers**. `revalue()` is the only writer of
`fx_revaluations`, so `GET /api/fx-reports/unrealized` reported a structural
nil for every client however many foreign documents they held, while
`services/fx_reporting_service.py`'s own header claimed those tables were
"written by the Phase-4 settlement + revaluation paths" — true of settlement,
false of revaluation. The `capital_wip` shape again. ACC-19 made migration
122's gates WRITABLE on 13-09-2026, which turned a dormant phase into a live
gap: a firm can now switch multi-currency on and the year-end step it needs
has no door.
`routers/fx_revaluation.py` is that door, and it is **its own router
deliberately** — `routers/fx_reports.py` says "read-only FX reporting" in its
first line, and a POST that writes journals under that prefix would make the
next reader believe the contract still holds. Same reasoning that kept CWIP
off `/api/fixed-assets`.
**THE PREVIEW IS THE POSTING'S OWN WALK.** `plan()` was EXTRACTED from
`revalue()` rather than written beside it, so what a CA is shown before
confirming is what gets posted — two compositions of `_exposure` +
`_prior_runs` would drift, and a test counts the `_exposure` call sites.
`plan()` does **not raise on a missing rate**: a preview is most useful before
any rate is typed, because the whole point of opening it is to learn which
currencies need one, so a row with no rate carries `rate_gap` and no target.
`revalue()` keeps its strict refusal — an exchange difference is a real
posting and a rate nobody supplied cannot be guessed.
**THE PREVIEW REPORTS `closure_reason`, NOT THE FIRM-FY VALIDATOR AND NOT
`lock_reason`** — exactly what will actually refuse the post. The firm-FY
validator alone UNDER-reports, because the kernel asks `period_closure_reason`
for every entry (migration 361) and would refuse a finalised client year-end
the preview had said nothing about; `lock_reason` would OVER-report, because
**CGST Rule 34 fixes the rate of exchange at the TIME OF SUPPLY**, so
restating the rupee carrying amount afterwards cannot change a figure any
filed GSTR-1 or GSTR-3B reported. `revalue`'s own client-lock debt is
pre-existing and stays acknowledged in
`test_every_dated_posting_path_asserts_the_client_lock.py`.
**Nothing schedules it** — the closing rate is a fact somebody records and the
entry hits the P&L, so it is a CA action on a period they named; a test
asserts no job mentions it. **Re-running is the CORRECTION path**, posting
only the delta to the new target, and the panel SAYS so: a CA who believes a
second run duplicates will avoid the button after a rate changes and the
accounts stay wrong.

**A COMPANY CREDIT CARD IS A BANK ACCOUNT, AND THE DOUBLE ENTRY NEEDED NO
CHANGE** (BANK-21, migration 386). `bank_accounts.account_type` admitted four
values and none of them was a card, so the statement could not be imported, the
spend could not be coded through the bank workflow, and the monthly payment out
of the current account posted to whatever ledger somebody picked.
`domain/banking/account_kind.py` is the authority. **`posting_map.build_lines`
is direction-driven, so a LIABILITY ledger makes it already right both ways
round** — Dr Expense / Cr Card on a purchase (money out of the card account in
exactly the sense the posting map means), Dr Card / Cr Bank on a payment — and
nothing in the posting map, the settlement or the reversal moves. A test asserts
the posting map still does not mention a card, because a branch on the account
type there would be a second rule to keep in step. **What differs is the SIGN OF
THE BALANCE**: a card's is a credit balance and its own statement states it the
other way up, as an amount owed. So there is ONE convention inside the product —
ledger sign, positive is a debit balance — and exactly three translations at the
edge: the opening balance the CA types, the balances read off an imported
statement (`mirror_imported_statement`, which must run BEFORE `statement_check`
or a file that adds up perfectly is refused), and the register's response. A
MOVEMENT never flips: a ₹500 purchase is ₹500 on either kind of account.
**An OVERDRAFT is owed to the bank and is NOT mirrored** — it is drawn against a
bank account whose balance the bank prints the ordinary way, overdrawn as
negative; a card statement never prints a negative. **The Transfer derivation
now asks a FACT** — is this chart row the linked ledger of one of the client's
own bank accounts — because `_looks_like_bank_or_cash` requires `account_type ==
'Asset'`, which a card's and an overdraft's ledger never is, so paying the
company card out of the current account was coded "Other" and posted as an
expense against a liability ledger instead of a Contra. `None` means "not
established" and the name test answers as it always did. `entry_type_for` still
calls a card purchase a "Payment"; that is recorded, not fixed — the three
values are what `journal_entries.entry_type` allows and the accounting is right
either way. ⚠️ The card subtype presents under **Short-term Borrowings** with
the overdraft one; `[S]`, because Schedule III could not be read here and Other
Current Liabilities is defensible — both are current liabilities, so no total
moves, only which caption.

**A MATCHING RULE SAYS WHICH FIELD IT READS AND WHICH RULE WINS** (migration
380, BANK-11 steps 1 and 2). Until then `domain/banking/rules.rule_matches` was
one case-insensitive substring of the NARRATION plus an amount range and a
direction, and precedence was creation order with **no way to change it** — so a
broad rule written in April permanently shadowed the narrow one written in July,
and the only remedy was to delete and re-create the broad rule, which loses its
TRUSTED flag. The row now carries `priority` (lower first, default 100),
`match_field` (`description | reference_no | payee_name | any`), `match_operator`
(`contains | starts_with | equals`) and `description_patterns`, so "NEFT from any
of these three customers" is one rule and a UTR or cheque number is matchable at
all. **Every default reproduces the old behaviour exactly** — `by_precedence` is
`(priority, created_at, id)`, so at the default the order is still creation
order and no existing rule changes which transactions it fires on or which rule
it beats. `MATCH_FIELDS` maps the rule's own value to the KEYS of the
transaction dict, so a caller that renames a field breaks there rather than
silently matching nothing; a rule naming a field its caller did not supply does
not fire, which is the safe direction. **WHAT A RULE MAY PROPOSE IS UNCHANGED
and that is deliberate**: a trusted rule posts unattended, so widening the
PAYLOAD — split legs, a party, a TDS treatment — widens what happens with nobody
watching. That is step 3, an owner decision, and a guard asserts
`RuleSuggestion` gained no field. Matching wider is different in kind: a CA
types every pattern, and the widest case was always reachable (an empty pattern
matches everything). Both doors validate — a validator only on create is one
PATCH from being none — and both read the ENGINE's own maps rather than a third
list.
