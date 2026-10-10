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
