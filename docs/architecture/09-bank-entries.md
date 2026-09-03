# 09 — Bank entries

The bank module, redesigned 2026-09-03. This is the design the code follows;
where they disagree, fix one of them the same day.

## Why it was redesigned

The Categorize tab was QuickBooks Online's bank feed, near-verbatim: *For
review / Categorized / Excluded*, *Set ledger*, *Apply suggestions*, *Match /
Add*, a Rules tab last. The owner's complaints, in their words:

1. "Even if I apply the suggestions I won't be able to see where they have
   been applied." True. The row's Ledger column had been removed (a trade the
   CA chose at the time), so a line coded by *Apply suggestions* sat in *For
   review* looking like an uncoded one, distinguishable only by a green tint.
   The outcome panel listed them once; dismiss it and the information was gone.
2. "For review / Categorised / Excluded looks fully like QuickBooks." It was.
3. "Set ledger — no problem in it, but doesn't sound too good."

Underneath, the engine is better than QBO's — see the 2026-08-02 audit, Part 4
— and none of that showed. The product spoke QuickBooks over a Tally-grade
kernel.

## The model: a statement line becomes a voucher

A CA does not "categorise" a bank line. A bank line **becomes a voucher**, and
Indian accounting has had three words for the three kinds since before
software:

| The bank says | So the entry is a | Bank side | The one question a human ever answers |
|---|---|---|---|
| money **in** | **Receipt** | Dr Bank | *from whom, or which ledger?* — a customer (settles their invoice, possibly short by TDS the customer withheld) or an income ledger (interest, a cash sale) |
| money **out** | **Payment** | Cr Bank | *to whom, or which ledger?* — a vendor (settles their bill, possibly net of TDS we withheld) or an expense ledger (rent; bank charges with their GST) |
| own account ↔ own account | **Contra** | both | *which other account?* — nearly always already found by the transfer matcher |

Three consequences, and they are the whole design:

- **The kind is never chosen.** Direction decides it. The debit/credit side
  is derived. `domain/banking/entry.py::kind_for` is the only place that
  says so, and it is a function of the row, not a stored value.
- **The only human input is the counter-side** — a party or a ledger. That is
  what "Set ledger" was asking; the screen now asks it as *Book under…* and
  offers customers with their open invoices on a receipt, vendors with their
  open bills on a payment, and the chart ordered by what this client actually
  uses (`ledger_order`).
- **The verb is Pass.** "Pass the entry" is what every Indian accountant says;
  it is what Tally's users do all day. *Passed* is the state. Not "Post" (our
  internal word, which confused readers), not "Record", not "Add".

## Every line carries a draft, and the CA passes it

The machine always proposes; nothing is a separate "apply suggestions" step.
On import, on a rule change, and on demand, `bank_entry_service.redraft`
writes onto each open line the best proposal it can defend, WITH its grade
and its reason:

| source | what it proposes | grade |
|---|---|---|
| `rule` | the ledger (and GST treatment) a rule the CA wrote names | **ready** — a human wrote it |
| `document` | one open invoice/bill/receipt/payment with the same amount, unambiguously | **ready** when exact and alone; **proposed** when short (TDS?) or when several could fit |
| `history` | how this payee was coded before, with the evidence | **ready** when unanimous over ≥ 3 postings; **proposed** otherwise |
| `transfer` | the counterpart line on another own account | **ready** when high-confidence and unambiguous; **proposed** otherwise |
| *(none)* | — | the line **needs you** |

The grade is the thing that makes 3,000 lines a day workable. The owner's
objection to "draft then approve" was exactly right — *"a CA can't be
approving 3,000 transactions a day"* — and the answer is that approval is by
**confidence, not by line**:

- **Pass N ready** is one click. It passes every `ready` draft, in chunks of
  fifty with a progress bar, and each line that could not pass says why on
  the line (`draft_error`) and drops to *needs you*.
- *Proposed* lines need a human, one at a time or by selection; the row says
  what it is asking — "short by ₹2,500 — TDS at 10%?", "3 invoices fit
  this amount".
- In a real firm the Executive clears the queue and the Manager or Partner
  reviews; RBAC already has the roles (`banking.write` is Executive+).

Nothing about the posting model changed. `bank_posting_service.post` is
still the one path, still refuses a locked period, still writes an
immutable journal that a correction reverses. What changed is that the
draft is **on the row** — so a CA can see what is about to be passed and
what was — and that the bulk action passes rather than merely codes.

### Where the draft lives

Columns on `bank_transactions` (migration 322): `draft_account_id`,
`draft_category`, `draft_entity_type`, `draft_entity_id`, `draft_source`,
`draft_rule_id`, `draft_grade`, `draft_reason`, `draft_gst_rate_bps`,
`draft_is_interstate`, `draft_error`, `drafted_at`. A draft is never an
answer: passing it applies it (sets `account_id`/`category`, or matches the
document, or pairs the transfer — through the existing services) and then
posts. A CA's own coding (`account_id`, `matched_entity_id`, splits, a
confirmed pair) always outranks it and is itself *ready*.

Materialising it is what makes the state a SQL filter, the counts a SQL
count, and *Pass N ready* a query rather than a recomputation over every
open line. The queue used to rebuild rules, history and candidate pools on
every page read; it now reads stored columns and the detail modal fetches
live candidates for the one line that is open.

### `entry_state`

One column, maintained by a trigger from the row's own columns, with the
Python twin in `domain/banking/entry.py::entry_state` and the two pinned by
`tests/test_bank_entry_state_parity_pg.py`. The states, in the order the
screen shows them:

| state | meaning | how it is decided |
|---|---|---|
| `needs_you` | nothing defensible to propose, or a pass failed | no coding, no draft, or `draft_error` set |
| `proposed` | a draft the CA should look at | `draft_grade = 'proposed'` |
| `ready` | can be passed as it stands | coded by the CA (ledger, document, split, pair) or `draft_grade = 'ready'` |
| `covered` | the receiving side of a passed transfer | `transfer_is_primary = false` and the primary is posted |
| `passed` | in the books | `match_status = 'posted'` |
| `set_aside` | deliberately not an entry (a bank error, a reversed line) | `match_status = 'ignored'` |

`has_splits` is trigger-maintained from `bank_transaction_splits`, so a split
line is *ready* without a separate write path having to remember it.

## Trusted rules: the one place the product acts without a click

Decided by the owner 2026-09-03, reversing audit Tier 4.3's "auto-add may
reach draft only". The reasoning:

- A rule is written by a human, for one client, on one narration pattern.
  "Bank charges → Bank Charges + 18% GST, every time" is not a judgement
  the CA wants to re-make three hundred times a year.
- A bank journal is **reversible** — an ordinary append-only reversal — and
  it is not a filing. The government-portal rule ("never auto-submit") is
  about filings and is untouched; it gets stronger, not weaker, when real
  filing is built.
- Zoho Books does this. Tally cannot (no feed). QBO does it badly, by
  writing on click.

So a rule can be **promoted to trusted**:

- Promotion needs `banking.approve` (Manager+). An Executive can write a
  rule; only a Manager or Partner can let it post.
- A trusted rule must name a ledger (`suggested_account_id`) — it cannot
  post without one — and records `trusted_by` and `trusted_at`. The CHECK
  in migration 322 refuses a trusted rule that lacks either.
- **Its lines post on the authority of the person who trusted it.**
  `journal_entries.created_by` and `bank_transactions.posted_by` are
  `trusted_by`; `posted_by_rule_id` names the rule; the audit row carries
  `source = bank_trusted_rule`. "Passed by rule *Bank charges*, trusted by
  Priya on 3 Sep" is the sentence the register shows. There is no system
  user, because there is no such person to answer for it.
- Un-trusting a rule stops it at once: the sweep reads `is_trusted` from the
  rule at pass time, not from the draft.

When it runs: after an import, the screen passes the trusted drafts with
the same chunked call and progress bar as *Pass N ready*, so the CA sees
them go; and `jobs/scheduler.py`'s daily sweep (`bank_trusted_rules`)
passes any left over — a statement uploaded and the tab closed, a rule
promoted after the import. The CA can see everything a rule passed in the
Rules tab and in the Entries list under *Passed*, filterable by rule, and
can undo any of it.

## The screens

Five tabs, in the order a month is worked: **Accounts · Entries · Bank Book
· Reconcile · Rules**.

- **Entries** — the working list. Count chips *To do · Ready · Needs me ·
  Proposed · Passed · Set aside*, a bank-account filter, search. One primary
  action: **Pass N ready**. Columns: Date · Bank narration (counterparty,
  channel chip, UTR on hover) · **Entry** — the voucher line as it will be
  passed: `Receipt · Silver Oak Industries · INV-042`, `Payment · Bank
  Charges · 18% GST`, `Contra · Cosmos Bank`, or the question in amber —
  · Spent · Received · Status · Action (*Pass* / *Answer* / *Undo* /
  *Restore*). Clicking a line opens the detail modal, which keeps every
  capability the old one had: ledger, party with open documents, TDS-short
  settlement, GST rate and place of supply, split across ledgers or
  documents, transfer pairing, attachments, the parsed narration, and the
  history evidence sentence.
- **Bank Book** — the register, renamed to what it is: the bank ledger with
  a running balance, cleared status (C/R), and the self-check against the
  bank's own balance column. Read-only, as before.
- **Reconcile** — labelled BRS. Unchanged in substance; it was already to
  accountant standard.
- **Rules** — each rule shows what it matches now (*N open lines*), what it
  has passed, and the Trusted switch with who trusted it.
- **Accounts** — unchanged in substance.

`app/clients/[id]/bank/page.tsx` is the shell only; each tab is its own file
under `components/banking/`. The 4,964-line page was the reason "make the
row a bit more flexible" changes went unreviewed.

## What this deliberately does not do

- It does not put a percentage on a draft. Grades are *ready* / *proposed*
  and the reason is a sentence with evidence — "coded to Bank Charges 8 of
  the last 9 times" — because a CA cannot audit "92%".
- It does not learn from unposted rows, invent a ledger, or pass a
  *proposed* draft in bulk.
- It does not auto-pair transfers or auto-match documents outside a pass:
  a draft is applied only when it is passed, so a rejected proposal leaves
  no trace to undo.
- It does not touch reconciliation, posting or the register services
  beyond reading `entry_state`.

## Sequence

1. Migration 322 + `entry.py` + `bank_entry_service` + endpoints + tests,
   with the old endpoints still serving the old screen.
2. The five tabs rebuilt on the new endpoints.
3. The old queue/batch endpoints deleted with the old screen — two queues
   of one statement drift — and their tests ported.
