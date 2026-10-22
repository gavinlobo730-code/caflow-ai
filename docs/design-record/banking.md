# Design record: Bank data: Account Aggregator position, bank entries, credit cards, matching rules

Moved verbatim from `CLAUDE.md` on 10 October 2026 (the owner asked for the always-loaded file to be slimmed).
Nothing here was rewritten. Wherever the text says "this file" or "CLAUDE.md" it means the design record as a whole
(this directory plus `CLAUDE.md`). Each entry below is one block of the old file, in its original order, under the
section it came from. `CLAUDE.md` lists every entry's headline in its "Design record index".

## From CLAUDE.md section: Bank data — the Account Aggregator is the only way in

- **Register as an FIU** (Financial Information User). Banks are FIPs; a licensed
  AA — Finvu, OneMoney, CAMS Finserv, NADL, Anumati — brokers consent between
  them under RBI regulation, on ReBIT schemas. Go via a TSP (Setu, Perfios,
  Finbox, Digio) rather than building FIU plumbing directly.
  **⚠️ THIS STEP IS NOT ACHIEVABLE AS WRITTEN — verified 2026-09-04, including
  searches that specifically looked for a way in and did not find one.** The RBI
  NBFC-AA Directions 2025 (which supersede the 2016 Master Direction) define an
  FIU as *"an entity registered with and regulated by any financial sector
  regulator"*, and that means RBI, SEBI, IRDAI, PFRDA or the Department of
  Revenue. **There is no FIU licence to apply for and no unregulated tier**;
  eligibility is derivative of a registration you already hold, and a TSP cannot
  confer it because a TSP is itself unregulated. The framework is built so raw
  financial data never reaches an unregulated party. The Department of Revenue's
  presence in that list does NOT help — it is there because DoR regulates GSTN
  *for the specific purpose* of GSTN being an **FIP**. A CA firm does not
  qualify either: ICAI is not a financial sector regulator. So the options are
  to **partner with a regulated FIU** (watch the shell-FIU pattern — FIPs have
  barred AAs over non-compliant downstream journeys), **acquire a registration**
  (SEBI RIA is most plausible; an NBFC brings a reciprocity duty to join as an
  FIP too), or **not consume via AA at all**. The six AA tasks are now sequenced
  around those three as **three gates, cheapest-and-most-fatal first**, and the
  ordering carries a finding of its own: **purpose-fit is UPSTREAM of FIU
  eligibility.** Eligibility is solvable with money; purpose is not. A consent
  artefact carries a `Purpose`, the FIP validates every fetch against it, and
  purpose limitation is enforced. **Gate 0a is ANSWERED, NO, and the taxonomy
  itself is now the authority for it (#130, §2b)** rather than an inference from
  absence. The five published purpose codes are **101** Wealth Management (SEBI
  RIAs, stock brokers), **102** Customer spending patterns/budget/other
  reportings (SEBI RIAs, PFRDA Retirement Advisors — *financial advisory*),
  **103** Aggregated Statement (lenders, insurers — underwriting and income
  verification), **104** monitoring of accounts (lenders — repayment health) and
  **105** one-time account verification (stock brokers). **Every entry names the
  class of licensee it is for**, which is the proof that a purpose is DERIVATIVE
  OF THE FIU'S OWN REGULATORY PERMISSION — and none describes an agent keeping
  the customer's own books. **So purpose defeats the PARTNER route too**, not
  just the do-it-yourself one: a partner FIU's permitted purposes come from its
  licence, and buying a SEBI RIA registration buys wealth-management advice, not
  ledger-keeping. ⚠️ **The near-miss is 102** — its NAME sounds like bookkeeping
  and its scope is advisory by SEBI/PFRDA registrants; Sahamati's own "use the
  most appropriate code, based on judgement" guidance points straight at it, and
  the FIP validates every fetch against the artefact's `Purpose`. **Do not
  declare 102** — not as a placeholder, not for a pilot. Grades are `[S]`, from
  search snippets of the publisher's pages: **every fetch is still refused** by
  the egress proxy on a third day, Wikipedia included, so nothing here is `[P]`.
  What is NOT settled is whether a purpose could be ADDED, and **the owner has
  decided not to ask** (2026-09-06, §7): the proposal channel runs through FIU
  membership §0 says we cannot hold, so the realistic asker is a partner FIU —
  the route purpose already forecloses. The enquiry stays drafted in §2a so
  reopening costs one email, but **nothing is outstanding and nobody is waiting
  on anybody.** **The whole line is CLOSED — §7**: route 3 has no counterparty, so
  #107's contract and pilot have no subject, and §7 carries the four gate
  questions and their answers in ONE table rather than eight cross-references.
  Verified before closing: no AA code, no config, no migration anywhere, and the
  one compliance marker (`domain/banking/normalizer.py`, the AA seam) rewritten
  so it states the decision instead of reading as pre-work. **Gate 0b (#103) is measured too, and points the
  same way**: the live book is 7 clients and 2 bank accounts — too small for an
  honest percentage, and one was not invented — but the composition needs no
  sample size. **Zero individual clients** (4 Private Limited, 1 LLP, 1
  Partnership, 1 Proprietorship), every account a **Current** account, and one of
  the two banks is **Cosmos Bank**, the co-operative this file already named as
  the AA gap. The one well-served AA case — savings, individual, singly held,
  ~72 banks — does not appear at all. **On that basis #104 has CHOSEN ROUTE 3 —
  do not consume via AA — provisionally, with no counsel engaged and nothing
  spent.** The asymmetry that makes that decidable now: routes 1 and 2 (partner,
  or acquire a registration) both require paid counsel and are the routes gate 0
  argues against, while route 3 requires none, costs nothing and forecloses
  nothing. **#105–#107 are not started and should not be** — they specify work
  under a route not taken. The one thing that reopens gate 1 is #130 finding a
  purpose exists or can be added; the counsel brief is already written in §0a so
  the money is spent once, on the right questions. **Stopping is a real
  outcome**, not a failure — statement upload is the base case regardless. See
  `docs/compliance/05-bank-data-and-the-account-aggregator.md`.

- **WHAT A BANK TAUGHT THE IMPORTER IS LISTED BESIDE THE IMPORT, A FAILED READ IS NOT "NOTHING TAUGHT", AND A LAYOUT CAN BE FORGOTTEN** (POST-A-117). When a bank's export is not one of the layouts the statement importer recognises, a CA maps its columns by hand and the mapping is saved for that bank account and that exact header row (`bank_statement_column_mappings`, migration 314; the same layout at another of the firm's accounts finds it, BANK-26). `GET /api/banking/statements/column-mappings` ("so a CA can see and correct what a bank taught us") and its DELETE had no screen and sat on the frozen list of computed answers nobody can open, so a mapping that had gone wrong, or one for a layout the bank has since changed, could be neither seen nor taken back. The list answers a WINDOW now (the newest hundred by default, the server's ceiling as `max_limit`, one row more read than shown so `has_more` is the read's, ordered by `created_at` then `id`), with only the columns a person reads (not the layout fingerprint or the creator's id), and **a failed read RAISES**: `list_mappings` used to log it and answer an empty list, which a screen whose whole job is to show "what has been taught" would have drawn as "nothing", a different statement from "could not be read" (`find_mapping`, which an import depends on, still tolerates a failed lookup on purpose, because an import must not be blocked by it). The accounts panel shows each layout as "Date ← "Txn Date" · Description ← "Narration"" using the header labels the CA saw (the positions alone are unreadable and go stale when the bank renames a column), a position the saved header cannot name is shown as "column N" and never as an invented label, and an account that is no longer listed is said so. **Forget** is offered only to a person who may write banking, asks first and names the account, says the next upload of that layout will ask again and that statements already imported are not changed, and refreshes the list. Three states stay apart: it could not be loaded, none saved yet (with what saves one), and the rows. The browser's list of eight field names is a copy of the normalizer's `MAPPING_KEYS` and a Python test holds the two equal and in order, so a field added on the server cannot vanish from the screen. The two endpoints left the frozen list and the `/api/banking` unreached budget fell from 8 to 6. Not done: editing a layout in place (forgetting it and importing again is the correction), and showing which statements were imported under which layout.

- **A LAYOUT FOUND ELSEWHERE IN THE PRACTICE IS OFFERED FOR READING AND NEVER OVERWRITTEN BY A SAVE** (POST-A-300, 22-10-2026). `bank_column_mapping_service.find_mapping` looks at the account's own layout first and then, for a layout nobody drew for this account, at any account of the firm with the same `header_fingerprint` (BANK-26, deliberate and good for READING an import), and says which it found in `match_scope` (`account` or `firm`). `save_mapping` updated whatever row `find_mapping` returned, so a correction made while importing client B's statement changed the layout stored for client A's account while B's account still had none: the write half of a read-only convenience. It now updates a row only when `match_scope` is `account` and otherwise inserts one for the account (the unique index is per (bank_account_id, header_fingerprint), so the insert cannot collide with A's), and the update names the firm and the account as well as the row id. The same edit stamps `updated_at` with an explicit Indian-clock timestamp instead of the string `now()`, which Postgres happens to read as the current time and which the double that enforces production's column types rightly refuses. It also removes a trap for the day the table is scoped by client for writes, when the old shape would have been a silent zero-row update for a member who is not a Partner. Held by an in-memory double and by `test_a_trial_balance_import_and_a_corrected_bank_layout_hold_on_the_real_schema_pg.py` (the same file holds the trial-balance import's real-schema cases), as a Partner signed in with their own token and as the privileged client.
