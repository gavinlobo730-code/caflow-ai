# Bank module — QuickBooks Online gap audit

**Date:** 2026-08-02
**Scope:** the Bank section (`/clients/[id]/bank`) and everything behind it — statement
import, categorization, matching, posting to the books, and reconciliation.
**Benchmark:** QuickBooks Online (QBO) Banking, incl. Bank Feeds, Bank Rules, Receipts,
and the Reconcile workflow.

> **On the benchmark.** The QBO behaviour described here is from product knowledge, not
> from a live QBO tenant. QBO ships changes continuously, so treat specific screen names
> and menu paths as approximate. The *capability model* — what the feature does and why
> a bookkeeper reaches for it — is stable and is what the gap analysis is built on.
> Everything said about **our** platform is verified against the code and cited by file
> and line.

---

## Verdict

Our banking **engine** is in good shape — in several respects genuinely better than
QBO's, because it was built on top of an immutable double-entry kernel rather than
bolted onto an editable transaction table. The **product around the engine** is where
the gap is, and it is wider than the code volume suggests.

Three complete, tested backend features are **unreachable from the UI**. They are not
half-built: they work, they have tests, and no user can trigger them. That is the
cheapest, highest-value work on this list — the build cost is already sunk.

The single biggest structural gap versus QBO is that we have no **bank register** and no
**payee** concept, and our categorization vocabulary is a fixed 11-item list rather than
the chart of accounts. Those three shape almost everything a bookkeeper does daily.

---

## Part 1 — What we have today (verified)

### Import
| Capability | Status | Evidence |
|---|---|---|
| CSV + XLSX upload, parsed **server-side** | ✅ | `routers/banking.py:231` |
| Bank-specific column adapters — HDFC, SBI, ICICI, Axis, generic, single-signed-amount+Dr/Cr | ✅ | `domain/banking/normalizer.py` `_ADAPTERS` |
| Per-transaction dedup hash (incl. running balance, so two identical same-day debits survive) | ✅ | `domain/banking/dedup.py:transaction_hash` |
| Per-file hash — re-uploading the same export is idempotent | ✅ | `domain/banking/dedup.py:file_hash` |
| 10 MB upload cap, empty-file and parse-failure handling | ✅ | `routers/banking.py:245-254` |
| Multiple bank accounts per client, with opening balance + COA link | ✅ | `migrations/093_payroll_assets_banking_modernized.sql:124` |
| Foreign-currency bank accounts + period-end revaluation | ✅ | `migrations/150`, `domain/currency/fx_revaluation_service.py` |

### Categorize & match
| Capability | Status | Evidence |
|---|---|---|
| Work queue with 5 views (unmatched / categorized / matched / needs_review / all) | ✅ | `routers/banking.py:311` |
| Controlled 11-value category vocabulary, DB CHECK-enforced | ✅ | `domain/banking/categories.py` |
| Bulk categorize (multi-select → one category) | ✅ | `bank/page.tsx:164` |
| Ranked match suggestions, confidence 0–100 with stated reasons | ✅ | `domain/banking/matcher.py:rank_suggestions` |
| Rule engine — narration contains / amount range / debit-credit type | ✅ | `domain/banking/rules.py` |
| Rules correctly scoped per client (one client's rule can't leak onto another's txns) | ✅ | `bank_matching_service.py:241-257` |
| Match / unmatch to invoice, bill, receipt, payment, journal | ✅ | `routers/banking.py:352,370` |
| **Split one receipt across multiple invoices/bills**, with TDS | ✅ backend | `bank_posting_service.py:367` |
| Ignore a transaction | ✅ | `routers/banking.py:421` |

### Post to books
| Capability | Status | Evidence |
|---|---|---|
| Posting preview before committing | ✅ | `routers/banking.py:474` |
| Posts a **draft** journal → approval queue → posted (never auto-posts) | ✅ | `bank_posting_service.py:216` |
| Direction-driven double entry; category only picks the counter account | ✅ | `domain/banking/posting_map.py` |
| Control accounts auto-resolved (AR/AP/GST); everything else must be chosen explicitly — **no GL account is ever guessed** | ✅ | `posting_map.py:AUTO_COUNTER / EXPLICIT_COUNTER` |
| Bank-to-bank transfer posting (Contra) | ✅ | `posting_map.py:build_transfer_lines` |
| Settles the underlying invoice/bill on post, CAS-guarded against double settlement | ✅ | `bank_posting_service.py:268` |
| Integer paise throughout | ✅ | all of the above |

### Reconcile
| Capability | Status | Evidence |
|---|---|---|
| Reconciliation session per account per period, opening/closing balances | ✅ | `bank_reconciliation_service.py:127` |
| Exact-integer tie-out with `reconciles` boolean | ✅ | `domain/banking/reconciliation.py:tie_out` |
| Reconcile / unreconcile individual lines | ✅ | `routers/banking.py:586,602` |
| **Cannot complete** unless (a) it ties out AND (b) every in-period line is reviewed | ✅ | `bank_reconciliation_service.py:282-297` |
| **Snapshot frozen at completion** — a later edit can't silently rewrite history | ✅ | `bank_reconciliation_service.py:301` |
| Completed sessions immutable | ✅ | `bank_reconciliation_service.py:48` |
| Report + CSV export | ✅ | `routers/banking.py:631,644` |
| Audit-log entries for session state changes | ✅ | `bank_reconciliation_service.py:308` |

**Test coverage:** 107 backend tests across `test_bank_feed_import.py` (28),
`test_bank_matching.py` (29), `test_bank_posting.py` (24), `test_bank_reconciliation.py`
(21), `test_banking_service.py` (5), plus `test_e2e_banking.py`,
`test_e2e_banking_reconcile.py`, `test_multi_invoice_bank_allocation.py`,
`test_r235_banking_hardening.py`, `test_r2_11_bank_parser_hardening.py`.

---

## Part 2 — Three features that are built, tested, and unreachable

These are not "gaps versus QuickBooks". They are things we already paid to build and are
currently getting zero value from. Each is a small frontend change away from working.

### 2.1 Bank rules have no UI at all — so the rule engine can never fire

The engine is complete: `rules.py` evaluates narration/amount/type conditions,
`bank_matching_service.queue()` runs every active rule over the queue and stamps
`suggested_category` on each row, and the UI *renders* it —
`bank/page.tsx:298` shows `Suggested: {t.suggested_category}` in the category dropdown.

But there is **no way to create a rule.** `GET /api/banking/rules` and
`POST /api/banking/rules` exist (`routers/banking.py:660,675`) and are not referenced
anywhere in `apps/web` — the frontend API client (`lib/api/index.ts:222-267`) has no
`rules` method at all. `bank_matching_rules` can only ever be empty, so
`suggest_category()` always returns `None` and that "Suggested:" branch is dead.

**Impact:** the single most-loved QBO banking feature is 100% built on our side and 0%
usable. **Fix: one rules screen + one API client method.**

### 2.2 A rule can specify a GL account and a narration — nothing reads them

`bank_matching_rules` has `suggested_account_id` and `suggested_narration`
(`migrations/093_payroll_assets_banking_modernized.sql:194-195`), and `MatchingRuleIn` accepts both
(`models/banking.py:232,234`). Grepping the whole backend, those two columns are read by
**nothing** outside the model definition. `suggest_category()` returns only the category
(`domain/banking/rules.py:42-44`).

**Impact:** even once rules have a UI, they can only suggest one of 11 coarse categories —
they cannot say "code this to *Bank Charges*". That is most of what a rule is for.

### 2.3 TDS-short settlement is plumbed end-to-end except the input field

The Indian everyday case: a customer pays a ₹1,00,000 invoice, deducts 10% TDS under
s.194J, and remits ₹90,000. The bank line is ₹90,000; the invoice must still be settled
in full.

`match_and_settle_multi` handles this exactly right — it takes `tds_paise` and raises the
settlement cap accordingly (`bank_posting_service.py:413`). The API client type declares
`tds_paise?: number` (`lib/api/index.ts:259`). But `grep -i tds` over
`app/clients/[id]/bank/page.tsx` returns **nothing** — the modal never collects it, so it
is always 0.

Worse, the 1:1 suggestion path can't help either: `rank_suggestions` has a hard
exact-amount gate — `if c.amount_paise != txn_amount_paise: continue`
(`domain/banking/matcher.py:70`). A ₹90,000 receipt against a ₹1,00,000 invoice returns
**zero suggestions**. The user's only route is the button labelled *"Split across
multiple invoices"* (`bank/page.tsx:315`) — which does not sound like where you go to
settle **one** invoice.

**Impact:** the most common receipt pattern in Indian practice has no discoverable path,
and the matcher actively hides the right answer.

---

## Part 3 — QuickBooks vs us, feature by feature

Legend: ✅ have · ⚠️ partial · ❌ missing · 🔒 built but unreachable (Part 2)

### A. Getting transactions in

| QuickBooks | Us | Notes |
|---|---|---|
| Direct **bank feeds** — connect the account, auto-refresh daily | ❌ | We are upload-only. In India the correct equivalent is the RBI **Account Aggregator** framework, not screen-scraping — see Part 6. |
| Manual upload: CSV, **QBO / OFX / QFX**, and PDF (newer) | ⚠️ | CSV + XLSX only. No OFX/QFX; no **MT940** (what most Indian corporate net-banking actually exports); no PDF. |
| Column mapper UI when a CSV doesn't match | ❌ | Our adapters are hard-coded by bank. An unrecognised layout fails with a parse error and the user has no recourse. |
| **Receipts inbox** — email/photo a receipt, OCR it, match it to a bank line | ❌ | We *have* the OCR engine (`routers/document_intelligence_v1.py`, Gemini) but it is wired to invoices only, not to bank transactions. |
| Duplicate protection | ✅ | Ours is stronger — hash includes the running balance, so genuine duplicate-looking rows survive. |

### B. The review queue

| QuickBooks | Us | Notes |
|---|---|---|
| **For Review / Categorized / Excluded** tabs | ⚠️ | We have 5 queue views, but no **Excluded** view. `ignore` sets status `ignored` (`routers/banking.py:421`) with **no un-ignore endpoint** — an accidental ignore is unrecoverable through the UI. |
| **Bank register** per account — running balance, inline edit, sort, filter, `R`/`C` cleared column | ❌ | We have no register view at all. This is the screen a bookkeeper lives in. |
| **Payee** on every line, with auto-create | ❌ | `bank_transactions` has no payee column. We infer party only via narration substring for scoring (`matcher.py:84`). |
| **Split** one line across several **categories/accounts** | ⚠️🔒 | We split across several **invoices** — a different axis. Splitting ₹50,000 into Rent ₹40,000 + Electricity ₹10,000 is impossible. |
| Category = **full chart of accounts** | ❌ | We have a fixed 11-value vocabulary (`categories.py`). Correct as a control, but a bookkeeper wants "Bank Charges", not "Other". |
| **Batch actions** — Accept / Modify / Exclude many at once | ⚠️ | Bulk *categorize* only (`bank/page.tsx:164`). No batch accept, no batch exclude. |
| **Undo** a categorization back to For Review | ⚠️ | `unmatch` exists; no undo once a draft journal is created. |
| **Attachments** on a transaction | ❌ | No attachment column or endpoint. |
| Memo / notes field | ❌ | Not on `bank_transactions`. |
| **Transfer auto-detection** — pairs the two sides so cash isn't double-counted | ❌ | We can *post* a transfer (`posting_map.build_transfer_lines`) but never detect one. Both sides sit in the queue as unrelated lines. |
| **"Find other matches"** — search all open docs by date range / amount / party | ❌ | We return a fixed top-5 (`matcher.py:64,103`) with no search. |
| **Partial payment** / resolve difference (bank fee, early-payment discount) | ⚠️🔒 | Blocked by the exact-amount gate; only reachable through the split modal. |
| Rules: full CRUD, priority order, all/any conditions, **auto-add**, copy, **apply to existing** | 🔒 | See 2.1/2.2. We have create + list only — no edit, no delete, no ordering, no re-run over existing rows. |
| "We categorized this the same way last time" — learns from history | ❌ | No history-based suggestion. |

### C. Posting

| QuickBooks | Us | Notes |
|---|---|---|
| Accepting a line writes straight to the books | ✅ **better** | We post a **draft** that goes through an approval queue. QBO has no such gate; for a CA firm this is the right default. |
| Preview before committing | ✅ **better** | QBO has no posting preview. |
| Accounts can be guessed | ✅ **better** | We refuse to guess a GL account outside AR/AP/GST (`posting_map.py`). |
| Editing a posted transaction | ✅ **different** | Our journals are immutable; corrections are reversals. QBO lets you edit in place, which is exactly how QBO reconciliations silently break. |

### D. Reconciliation

| QuickBooks | Us | Notes |
|---|---|---|
| Beginning balance auto-populated from the last reconciliation | ❌ | Ours is typed in by hand every time (`bank/page.tsx` form `opening`). Typo → a reconciliation that ties out to the wrong number. |
| **Beginning-balance-doesn't-match** detection + guided fix | ❌ | Not detected. |
| Live running **Difference** while you tick items | ⚠️ | Computed on the report; not a persistent live indicator. |
| Filter / sort / search inside the reconcile screen | ❌ | Flat list, 3 views. |
| Save and finish later | ✅ | Sessions persist. |
| **Undo a completed reconciliation** (accountant tool) | ❌ | Completed sessions are hard-locked (`bank_reconciliation_service.py:48`). Safe, but there is no legitimate escape hatch — QBO gives accountants one, deliberately. |
| **Reconciliation Discrepancy Report** — previously-reconciled lines later changed/deleted | ❌ | We have `reconciliation_service.py` (the integrity engine behind Verify Books), but it does not check reconciled-then-mutated bank lines. |
| Reconciliation **history list** + prior reports | ⚠️ | Sessions list exists; report is per-session; no PDF. |
| Report as PDF | ⚠️ | CSV only (`routers/banking.py:644`). |
| Cannot complete with unreviewed lines | ✅ **better** | QBO lets you finish with a non-zero difference and dumps it into an adjustment. We refuse (`bank_reconciliation_service.py:295`). |
| Frozen historical snapshot | ✅ **better** | QBO reconciliation reports are recomputed live, which is why they drift. |

---

## Part 4 — Where we are already ahead

Worth stating plainly, because the TODO below should not trade any of it away:

1. **Draft-then-approve posting.** Nothing reaches the ledger without a human approval
   step. QBO writes on click.
2. **No guessed GL accounts.** Only AR/AP/GST resolve automatically; everything else is
   an explicit choice.
3. **Immutable journals.** Corrections are reversals, so a reconciled period cannot be
   quietly rewritten underneath you — the root cause of most QBO reconciliation pain.
4. **Reconciliation that refuses to lie.** Two independent conditions, both hard.
5. **Frozen completion snapshot.** A completed reconciliation is a historical fact.
6. **Integer paise everywhere.** No float in any money path.
7. **Multi-currency bank accounts with period-end revaluation**, which QBO handles only
   on higher tiers.

---

## Part 5 — TODO, prioritized

Sizes are rough engineering bands: **S** ≈ 1–2 days, **M** ≈ 3–5 days, **L** ≈ 1–2 weeks,
**XL** ≈ a month or more.

### Tier 0 — Unlock what we already built (do first) — ✅ SHIPPED 2026-08-02

All five items are implemented and merged. Additions beyond the original scope,
found while doing the work:

- The exact-amount gate existed **twice** — in `rank_suggestions` *and* in the
  candidate SQL (`.eq("total_paise", amount)`), so relaxing the ranker alone
  would have changed nothing. Both were widened.
- Rules had no ordering at all, so "first matching rule wins" depended on
  whatever order Postgres returned. Fetch is now ordered by `created_at`.
- `suggested_category` on a rule was never validated against the controlled
  vocabulary, so an invalid rule stored fine and failed only when the CA tried
  to accept it. Validated at write time.
- An ignored row that still carried a category or a link reappeared under
  Categorized/Matched as live work. Ignored rows now show only in their own
  view and in "all".
- A short match is routed to the settlement modal (party, document and TDS
  prefilled) rather than a plain Accept, which would have quietly under-settled
  the invoice — the new ranking would otherwise have created a fresh footgun.

| # | Item | Size | Why first |
|---|---|---|---|
| ✅ 0.1 | **Bank Rules screen** — list, create, edit, delete, activate/deactivate; plus `api.banking.rules` client methods | **M** | Turns a fully-built, fully-tested engine from dead code into the headline feature. Cheapest value on the whole list. |
| ✅ 0.2 | **Honour `suggested_account_id` + `suggested_narration`** in `suggest_category()`; return a small rule-result object instead of a bare string | **S** | Two columns already exist and are read by nothing. Without this, rules can only suggest 1 of 11 coarse categories. |
| ✅ 0.3 | **TDS field in the settlement modal**, and rename the entry point from *"Split across multiple invoices"* to something like *"Match with allocation / TDS"* | **S** | The most common Indian receipt pattern currently has no discoverable path. |
| ✅ 0.4 | **Relax the exact-amount gate** — surface near-amount candidates as lower-confidence with an explicit `difference_paise` and a reason ("₹10,000 short — TDS?") | **S** | `matcher.py:70` currently hides the correct answer for every short-paid invoice. Keep the gate for *high* confidence; stop using it to filter. |
| ✅ 0.5 | **Un-ignore endpoint + Excluded view** | **S** | An accidental Ignore is currently unrecoverable. |

**Tier 0 is done.** Next up is Tier 1 (see below), starting with the bank register.

### Tier 1 — The screens a bookkeeper lives in

| # | Item | Size | Notes |
|---|---|---|---|
| ✅ 1.1 | ~~**Bank register** per account — running balance, sort, filter, cleared status~~ **Shipped 2026-08-03** | **L** | Read-only, as planned — a posted journal is immutable, so an edit box would promise what the ledger refuses. Balance is computed server-side over the WHOLE account before filtering, so a filtered view still shows true balances (`view_opening_balance_paise` is what makes it add up on screen). Cleared is three-state: blank / **C** (claimed by an open reconciliation) / **R** (part of a *completed* one) — collapsing those two would report a sign-off that never happened. Goes beyond QBO on one point: Indian statements carry a balance column and the importer keeps it, so the register **self-checks** against the bank's own figure and reports the first divergence — the signature of a missing, duplicated or misdated line. |
| ✅ 1.2 | ~~**Split a line across multiple GL accounts** (not just invoices)~~ **Shipped 2026-08-03** | **M** | `bank_transaction_splits` (migration 256) + an n-leg journal. The two-leg assumption in `build_lines` is now bypassed rather than removed — it is still the right builder for an ordinary posting. **The splits must sum EXACTLY to what the bank moved**: no rounding plug, no auto-balance. That is a cross-row rule, so it lives in an RPC (`replace_bank_transaction_splits`) that deletes, inserts and verifies in one transaction — a deferred constraint trigger would not work, because PostgREST commits each statement separately. Refused where it would produce a wrong ledger: on a transfer, on a **matched settling transaction** (it settles the document in full — splitting would leave the control account and the sub-ledger disagreeing), and combined with a GST rate (that needs a rate *per* split — see below). |
| ✅ 1.3 | ~~**Payee on `bank_transactions`** + customer/vendor lookup + auto-fill~~ **Shipped 2026-08-03** | **M** | Migration 257. `payee_id` deliberately carries **no foreign key** — the reference is polymorphic, because a payee is often neither a customer nor a vendor (a landlord, a utility, the bank itself), and inventing vendor records for them would be worse than the problem. It is a convenience for filtering and learning, never a settlement target; settlement still uses `matched_entity_*`, re-checked on every use. Auto-fill reuses the 6.2 narration parser: the parsed counterparty is matched against the client's real customers/vendors so the CA gets a **link**, falling back to a plain name when nothing matches. |
| ✅ 1.4 | ~~**Learn-from-history suggestions** — "last time this payee was coded to X"~~ **Shipped 2026-08-03** | **M** | The key is the hard part, and it is **not** the narration: an Indian UPI line carries a UTR, so every one is unique and a raw-string key never learns anything. The key is `payee_id` when a party is linked, else the **normalised** counterparty (6.2), so 'Acme Pvt. Ltd.' and 'ACME PRIVATE LIMITED' learn as one payee. Only **posted** decisions teach — a draft is a proposal, and learning from unposted rows would let one mistaken suggestion, accepted once, become the evidence for suggesting itself. Returns **evidence, not a score**: "coded this way 8 of the last 9 times" plus the alternatives that lost, because a CA cannot audit '92% confident'. |
| ✅ 1.5 | ~~**Transfer auto-detection** — pair opposite-sign, same-amount lines across two of the client's own accounts~~ **Shipped 2026-08-03** | **M** | Migration 258. **Detection was only half the feature.** `build_transfer_lines` already writes the COMPLETE double entry, so a detected pair whose sides both post double-counts the cash anyway — the exact overstatement this prevents, just arrived at more tidily. Hence `transfer_is_primary`: exactly one side (the outflow) carries the journal, the counterpart is excluded from the ready-to-post queue AND refused in `_plan`. Pairing goes through an atomic RPC because a half-paired row — one side pointing at a partner that doesn't point back — would be free to post its own journal. Exact paise, opposite directions, different accounts, within a few days; **ambiguity is reported, not resolved** (three ₹50,000 movements on one day have no single correct pairing, and each line is used in at most one pair).
| ✅ 1.6 | ~~**"Find other matches"** — searchable candidate picker with date/amount/party filters, not a fixed top-5~~ **Shipped 2026-08-07** | **M** | Lengthening the ranked list would have fixed nothing: the problem was never that the right answer ranked sixth, it is that `suggestions()` **never fetched it** — an amount band on invoices/bills, exact-amount equality on receipts/payments. So the band is **lifted**, not widened: any document the direction permits is reachable, including one larger than the bank line (the old band was one-sided, so a ₹9,000 invoice against a ₹10,000 deposit had no route at all). What is *not* relaxed is what the ledger permits — **direction is a rule, not a filter**: money arriving cannot settle a purchase bill however the search box is filled in, and asking for a forbidden type is a **422 rather than an empty result**, because silently returning nothing reads as "there are none", a different and misleading answer. Draft/cancelled/fully-paid/soft-deleted stay unreachable for the same reason. With the band gone, "closest amount" starts doing real work, so results rank by \|difference\|, then date proximity, then `entity_id` — a **total** order, without which paging could repeat or drop a row. Paged with a true total plus a `truncated` flag, so "nothing matches" is distinguishable from "too much matched". A short hit still routes to the settlement modal rather than a one-click link, exactly as in the ranked list. |
| ✅ 1.7 | ~~**Batch accept / batch exclude** alongside the existing bulk categorize~~ **Shipped 2026-08-03** | **S** | One request for the whole selection, returning an outcome for **every** row. The existing bulk categorize fires one request per row and reports a count — fine when all succeed, misleading when two do not. Rows legitimately fail (already posted, already excluded, nothing to accept) and a partial success reported as a success is how a transaction quietly stays uncoded until year end. Deliberately **not atomic across rows**: eight good rows should not roll back because the ninth was posted. "Accept" applies a matching rule first (a human wrote it), then learned history (a human did it before) — never an invented account. |
| ✅ 1.8 | ~~**Attachments on bank transactions**~~ **Shipped 2026-08-03** | **S** | Migration 259, reusing migration 138's JSONB `{name,url}` convention rather than a table — there is no join, lifecycle or separate permission to express. **The link's scheme is an allow-list, not a sanitiser**: an attachment URL is rendered as a link a CA clicks, so a stored `javascript:` or `data:` URL is stored XSS delivered by whoever uploaded the "receipt". Only http/https are accepted. Names cannot contain path separators (the name is also what a download would be called). |

### Tier 2 — Reconciliation, to accountant standard  ·  ✅ COMPLETE, shipped 2026-08-02

| # | Item | Size | Notes |
|---|---|---|---|
| ✅ 2.1 | **Auto-populate opening balance** from the previous completed reconciliation's frozen snapshot | **S** | Snapshot already stored (`bank_reconciliation_service.py:301`) — just read it. Removes a whole class of silent error. |
| ✅ 2.2 | **Beginning-balance mismatch detection** — compare typed opening against derived book balance, warn before starting | **S** | |
| ✅ 2.3 | **Reconciliation Discrepancy Report** — reconciled lines whose journal was later reversed or whose amount no longer agrees with the frozen snapshot | **M** | Fits naturally as a new check inside `reconciliation_service.py` / Verify Books rather than a new subsystem. |
| ✅ 2.4 | **Live difference indicator** + filter/sort/search in the reconcile screen | **S** | |
| ✅ 2.5 | **Undo completed reconciliation** — permission-gated, reason required, fully audit-logged, snapshot retained | **M** | Deliberate escape hatch. Must not weaken `_require_mutable` for anyone else. |
| ✅ 2.6 | **PDF reconciliation report** (CSV exists) | **S** | |
| ✅ 2.7 | **Reconciliation history view** with access to every prior frozen report | **S** | |

### Tier 3 — Import breadth

| # | Item | Size | Notes |
|---|---|---|---|
| 3.1 | **MT940 / SWIFT** parser | **M** | What most Indian corporate net-banking actually exports. Bigger real-world win than OFX. |
| 3.2 | **Interactive column mapper** when no adapter matches — user maps columns once, mapping is saved per bank account | **M** | Removes the "unsupported bank" dead end and makes `_ADAPTERS` a fast path rather than a hard requirement. |
| 3.3 | **More bank adapters** — Kotak, Yes, IndusInd, IDFC First, Bank of Baroda, PNB, Canara, Union | **S each** | Purely additive; the architecture already isolates this to one dict. |
| 3.4 | **PDF statement import** (OCR) | **L** | Gemini vision path already exists for invoices. |
| 3.5 | **OFX / QFX** | **S** | Low priority in India; include for completeness. |

### Tier 4 — Strategic

| # | Item | Size | Notes |
|---|---|---|---|
| 4.1 | **Account Aggregator (RBI/Sahamati) bank feed** | **XL** | See Part 6. The real answer to "QBO has bank feeds". Needs an AA/FIU partner, consent flow, and a compliance review — a project, not a ticket. |
| 4.2 | **Receipts inbox** — forward-to-email + photo upload, OCR, auto-match to a bank line | **L** | Reuses `document_intelligence_v1.py`. |
| 4.3 | **Rule auto-add** — a high-confidence rule creates the **draft** journal without review | **M** | Hard constraint: auto-add may reach *draft* only. It must never post to the ledger without the existing approval click. Anything else breaks our posting model. |
| 4.4 | **Cash-flow forecast** from bank balance + open AR/AP | **L** | |

---

## Part 6 — India-specific opportunities QuickBooks structurally cannot match

Copying QBO gets us to parity. These are where we can be better for the actual user, and
several are cheap because the data is already in the narration.

1. **Account Aggregator feed (RBI framework).** The regulated, consent-based way to get
   bank data in India — no credential sharing, no scraping. QBO India never built this.
   It is the honest answer to the bank-feed gap and a genuine moat. *(Tier 4.1)*

2. ~~**UPI / NEFT / RTGS / IMPS narration parsing.**~~ ✅ **Shipped 2026-08-02.** Indian narrations are structured:
   `UPI/DR/412345678901/RAMESH K/HDFC/paym`. Extracting UTR, counterparty name, and
   payer VPA would raise match rates sharply. **Pure parsing work in a module we already
   own** (`normalizer.py`) — probably the best effort-to-value ratio on this entire
   document after Tier 0. *(Size: **M**)*

3. **TDS-aware receipt matching.** Covered in 2.3/0.3/0.4. QBO cannot express
   "invoice settled in full, cash short by the TDS" without a manual journal. We already
   have the settlement primitive — we just have not exposed it.

4. ~~**GST on bank charges.**~~ ✅ Done 2026-08-02. Bank charges carry GST, and it is
   input credit. A rule now codes the charge and books the GST split correctly
   (CGST/SGST vs IGST by the bank's place of supply, CGST Act §16) — a small,
   high-frequency win. *(Size: **S**, depended on 0.2)*

   The charge on a statement is tax-**inclusive**, so the taxable value is backed OUT of
   it (`domain/banking/charge_gst.split_inclusive_charge`): ₹590 at 18% is ₹500 + ₹90,
   not ₹590 + ₹106.20. The tax is taken as the *remainder*, which makes the split exact
   by construction — the journal balances with no rounding plug on a tax head. Place of
   supply (IGST Act §12(12)) is **stated, never inferred**: an IFSC does not encode a
   state, so the rule carries it (migration 254) and the CA confirms it in the drawer.

5. **Cheque return / bounce handling.** A returned cheque needs the original receipt
   reversed and bank charges booked. Today that is a manual journal. *(Size: **M**)*

6. **TDS deducted *by us* on vendor payments.** The mirror of #3 on the payables side —
   we remit less than the bill, and the balance goes to the TDS payable ledger. The
   engine already tracks TDS elsewhere; the bank path does not use it. *(Size: **M**)*

7. **GSTR-2B ⟷ bank cross-check.** Vendor payments that never produced an eligible ITC
   entry. We already have the GST return engine; joining it to the bank feed is a
   report, not a new subsystem. *(Size: **M**)*

---

## Recommended sequence

1. ~~**Tier 0 in full.**~~ ✅ Done 2026-08-02.
2. ~~**Then 2.1 + 2.2.**~~ ✅ Done 2026-08-02.
3. ~~**6.2 — UPI/NEFT narration parsing.**~~ ✅ Done 2026-08-02. Best differentiated win available,
   and it lands in a module we already control.
4. ~~**6.4 — GST on bank charges.**~~ ✅ Done 2026-08-02.
5. ~~**Tier 1.1 — the bank register.**~~ ✅ Done 2026-08-03.
6. ~~**Tier 1.2 — split across GL accounts.**~~ ✅ Done 2026-08-03.
7. ~~**Tier 1.3 + 1.4 — payee and learn-from-history.**~~ ✅ Done 2026-08-03.
8. ~~**Tier 1.5 — transfer auto-detection.**~~ ✅ Done 2026-08-03.
9. ~~**Tier 1.7 + 1.8 — batch actions and attachments.**~~ ✅ Done 2026-08-03.
10. ~~**Tier 1.6 — "find other matches" candidate picker.**~~ ✅ Done 2026-08-07.
   **Tier 1 is complete.** Tiers 0, 1 and 2 are now all done; what remains is Tier 3
   (import breadth — MT940/SWIFT, an interactive column mapper, eight more bank
   adapters, PDF/OCR, OFX/QFX), Tier 4 (Account Aggregator, receipts inbox, rule
   auto-add-to-draft, cash-flow forecast) and the three open India-specific items
   (cheque returns, TDS *we* withhold on vendor payments, GSTR-2B ⟷ bank cross-check).

   **Known follow-up from 1.2:** a split and a GST rate cannot currently be combined —
   both decide the non-bank legs, and doing them together needs a rate *per split*. The
   combination is refused with a clear message rather than silently applying one and
   dropping the other. Worth doing when a real case turns up; the pieces
   (`charge_gst.split_inclusive_charge`, `splits.build_split_lines`) already compose.

   **Found while building 1.6, fixed 2026-08-07 — client-assignment scope on the
   id-addressed banking endpoints.** `core.authz` makes only the **Partner**
   firm-wide (`_FIRMWIDE_ROLES`); Managers, Executives and Reviewers see only the
   clients in `user_client_assignments`. Endpoints taking a `client_id` parameter
   enforced that with `assert_client_access` / `_scope_rows`. Endpoints addressed
   by a row id did not — they checked `firm_id` and stopped, so a row id from
   another manager's client was accepted on reads **and on writes**: `POST …/post`
   wrote a journal into that client's books, and `…/suggestions` read out their
   open invoices and party names.

   The first count was 18 (`{txn_id}` only). The real number is **31** — the 19
   `{txn_id}` endpoints plus 12 on `{recon_id}`, which is just as client-scoped
   and had the identical hole. Fixing only the ones first noticed would have left
   the same defect in the same file.

   All 31 now call `_assert_txn_scope` / `_assert_recon_scope` — one firm-scoped
   `client_id` lookup, then `assert_client_access`, returning **404** for both
   "no such row" and "not your client" so the status code cannot be used as an
   oracle for which ids exist. The guard sits at the router because that is where
   every other client-scope check in the module lives; the copy 1.6 had put in
   `bank_candidate_search_service` was removed so there is one seam rather than
   two. `test_banking_client_scope.py` walks the **registered routes** and fails
   for any future row-addressed endpoint that skips the guard — a per-endpoint
   test alone would only cover the ones someone remembered.

   Side effect: `set_transaction_account` on a foreign-firm id used to surface a
   500-class error, because `_get_txn` assumed PostgREST's `.single()` returns
   empty on no-row when it actually raises. The guard now answers 404 first, so
   the error contract matches the intent (`test_e2e_banking.py` asserts it).

   **Also fixed 2026-08-07 — the three banking BATCH endpoints.** `batch-accept`,
   `batch-exclude` and `batch-include` name their rows in the request BODY, not
   the path, so the `{…_id}` sweep that found the other 31 matched none of them.
   They were caught by `tests/test_router_client_scope.py`, which walks the
   registered routes instead of pattern-matching URLs — the first thing that test
   did on being written was find three endpoints the manual sweep had missed.
   `_assert_txn_batch_scope` checks every distinct client in the batch in one
   read, before any row is touched.

   **Also fixed 2026-08-07 — `sales_invoices` (18 endpoints) and `purchase_bills`
   (10).** Worse than banking: neither router imported `core.authz` **at all**, so
   the client_id-parameterised endpoints were unguarded too and no id-guessing
   was needed. `GET /api/sales-invoices/?client_id=…` listed any client's
   invoices to any member of the firm; `POST /` created records in any client's
   books; `/{invoice_id}/issue`, `/cancel` and `/{bill_id}/receive` posted and
   reversed real journals (the last one also claiming input GST credit under
   CGST Act §16). All 28 now guarded: `assert_client_access` where the client is
   named directly, `_assert_invoice_scope` / `_assert_bill_scope` where it must be
   resolved from a row id, `filter_by_client` on the one firm-wide list view.

   Bulk create is refused **as a whole** if any row names a client the caller is
   not on. Not-atomic-across-rows is right for a VALIDATION failure (eight good
   invoices should not be lost to a ninth with a bad date) and wrong for an
   authorization one: checking per row lets every row before the foreign one
   land, and a bulk endpoint is exactly where one foreign client_id would be
   slipped in among fifty legitimate ones.

   **The ratchet.** `tests/test_router_client_scope.py` holds an `AUDITED`
   registry of router prefixes. A router goes in only once every endpoint under
   it has been looked at, and the test then walks the registered routes and fails
   for any endpoint — including a new one — that never consults the caller's
   client scope. Currently audited: `banking`, `sales_invoices`, `purchase_bills`,
   `engagement_letters`, `workflow_builder`, `knowledge`, `lifecycle`,
   `payroll`, `recurring_invoices`, `memory_intelligence`, `tasks` +
   `task_extras`, `task_recurring`, `tds_workspace` + `tds`,
   `gst_workspace` + `gst_portal` + `gst`, `mca_workspace`, `relationships`,
   `reconciliation`, `reminders`, `engagements`, `compliance_records`,
   `task_templates`, `customers`, `vendors`.

   **Also fixed 2026-08-07 — `engagement_letters` (19 endpoints).** This one had
   imported `core.authz` for years and used it in exactly one place
   (`create_engagement`), so every other endpoint took an engagement id from any
   client in the firm — including `/send` and `/resend` (email the letter to the
   client's own signatory), `/recipient` (**changes the address the signing link
   goes to**), `/signing-link`, `/pdf`, `/sign`, `/reject` and `/delete`.

   Two things here are deliberately NOT guarded, and both are pinned by tests
   rather than left as a comment:

   * **The five `/templates` endpoints.** `engagement_templates` has a `firm_id`
     and no `client_id` (migration 115) — a template is firm property, reused
     across every client. A client guard would have to invent a client to check.
     Over-guarding is a real failure mode, not a safe default.
   * **An engagement whose `client_id` is NULL.** That column is nullable because
     an engagement can be raised against a **lead**, before they are a client at
     all. `leads` carries only a `firm_id`, so there is no assignment to check
     against, and `assert_client_access(user, None)` reads it correctly as a
     firm-level resource. `filter_by_client` keeps rows with no client_id, which
     is what stops the firm-wide list narrowing from deleting the entire
     pre-client pipeline.

   **Follow-up this surfaced: leads have no assignment scope of their own.** Any
   member of a firm can see any lead and any lead-stage engagement. That may well
   be intended for a sales pipeline, but it is currently an accident of `leads`
   having no owner column rather than a decision. Worth deciding explicitly.

   The exemptions live in `EXEMPT` in `tests/test_router_client_scope.py`, each
   with its reason, and two tests keep them honest: one fails if an exemption
   names a route that no longer exists (a rename would otherwise move an endpoint
   quietly out of the sweep), and one fails if an exempt handler ever starts
   reading a `client_id` — at which point the stated reason has stopped being
   true.

   **Also fixed 2026-08-07 — `workflow_builder` (20 endpoints).** This is where
   *"does the table have a `client_id`?"* stops being a good enough question, and
   it is the most important lesson of the sweep so far.

   * `workflow_instances` has a `client_id` (nullable — a workflow can be a
     firm-level sweep belonging to no client). Guarded directly.
   * `workflow_executions`, `workflow_failures` and `workflow_approvals` have a
     `firm_id` and **no `client_id` at all** — but each has a NOT NULL
     `instance_id`, and that instance may name a client. They are **client data
     living in a table with no client column.** Scoping by column presence would
     have declared all three firm-level and left the audit trail, the failure
     list and the approval queue readable across every client in the firm. They
     are scoped THROUGH the parent instance, in one batch lookup per page rather
     than a query per row (`workflow_repo.client_ids_for_instances`).
   * `workflow_templates` and `workflow_schedules` genuinely are firm property —
     the DEFINITIONS, not the runs. Exempt, with the reason recorded.
   * `POST /templates/{id}/trigger` is under `/templates` but is **not** exempt:
     the template is firm property, and firing it CREATES an instance against the
     client named in the payload. That is the client-scoped act.

   Both mutating child endpoints (`/approvals/{id}/respond`,
   `/failures/{id}/resolve`) resolve their parent BEFORE the write —
   `respond_approval` writes and then resumes the workflow, which runs real steps
   against that client's data. `workflow_repo.get_failure` was added for exactly
   that ordering.

   **Method note for the routers still to come:** the column-presence heuristic
   used to pick guards in the first four routers would have MISSED three tables
   here. The question to ask of each table is not "does it have a client_id" but
   "can a row of it be traced to one" — and if so, guard through whatever traces
   it.

   **Also fixed 2026-08-07 — `knowledge` (12 endpoints).** The first router in
   the sweep that was already *mostly* right: it has its own client-scope model
   in `services/knowledge_service.py`, richer than `core.authz`'s — internal
   practice client (G1) separate from assignment, read separate from write. The
   guards live in the **service**, not the router, which is a shape the sweep
   had to learn to follow rather than a defect.

   Two things were wrong underneath it.

   * **`?scope=client` returned every client's articles.** `search_articles`
     checked the caller only on the `client_id` branch — `if client_id: assert …
     / elif scope: filter by scope / else: firm+department`. The middle branch
     had no check at all, so `GET /api/knowledge/articles?scope=client` handed
     any firm member with `knowledge.read` the client-scoped articles of every
     client in the firm. The function's own docstring claimed the opposite
     ("excludes client-scoped … unless a specific assigned client_id is
     requested"), so the intent was never in doubt — the branch simply escaped
     it. Now filtered per row, so the claim holds for every path in rather than
     for the two that were remembered.
   * **The mutating article paths checked the READ predicate.** edit / restore /
     archive called `_load_article_or_404(..., write=False)`.
     `can_view_client_content` admits Reviewer and Viewer;
     `can_write_instruction` deliberately does not. **Not reachable today** —
     RBAC gates `knowledge.write` to Partner and Manager, who pass both — so
     this is the two layers agreeing rather than a live hole, but it is one RBAC
     grant away from handing a read-only role an edit button.

   **Two flaws in the ratchet itself, found while adding this router.** Both
   made it pass on code with every check removed:

   * `_load_article_or_404` was listed as a name that counts as a check. It is a
     *loader* — it exists whether or not it checks anything. Only names that
     cannot exist without the check belong in `AUDITED`.
   * The sweep matched raw source, so a **docstring** mentioning
     `can_view_client_content` counted as calling it. It now strips comments and
     string literals before matching (`_code_only`), because prose is not
     enforcement. Verified by stripping all four checks from the service and
     confirming eight endpoints fail.

   **Also fixed 2026-08-07 — TWO CROSS-TENANT LEAKS, the most serious thing this
   sweep has found.** Two endpoints accepted a `firm_id` from the CALLER and
   preferred it over the one in the token (`firm_id or current_user["firm_id"]`):

   > `GET /api/lifecycle/onboarding/checklist/active?firm_id=<any firm>`
   > `GET /api/ai-insights/cross-client?firm_id=<any firm>`

   Any authenticated user of any firm could read another **firm's** data by
   supplying its id — client names in the first, and in the second an endpoint
   whose entire purpose is to aggregate across a firm's client base. That is a
   **tenant** boundary, not a client-assignment one: different firms are
   different customers, and every other control in this document sits inside a
   firm.

   Both parameters are **gone rather than validated**. There is no legitimate
   caller: a firm's own users get their firm from the token, and cross-firm
   access belongs to the platform-admin surface (`routers/platform.py`, gated by
   `require_platform_admin` — which is why its `/firms/{firm_id}` endpoints are
   correct and were left alone). A parameter only an attacker has a use for
   should not exist. An exhaustive check of every registered route confirms
   these were the only two; `models/ai_copilot.py` declares a `firm_id` on
   several request bodies, but no router reads it.

   **Also fixed 2026-08-07 — `lifecycle` (19 endpoints).** The lifecycle runs
   from before a client exists to after they renew, so what counts as client
   data differs per table: `onboarding_workflows` / `onboarding_checklists` /
   `renewals` carry a NOT NULL `client_id`; `proposals` a nullable one (a
   proposal can be made to a lead); `onboarding_tasks` and
   `onboarding_checklist_steps` carry a `workflow_id` and no client at all, so
   they are scoped through the parent — the same shape as workflow_builder's
   children. `leads` and the dashboard are exempt with reasons.

   **The exemption-honesty test caught a bad exemption of mine.** I had written
   off `POST /leads/{lead_id}/convert` as "converts a lead, so there is no client
   yet". True of one of its two paths: `LeadConvertIn.client_id` is optional, and
   when supplied it attaches the lead to an **existing** client — spawning
   onboarding workflows and lifecycle events against it. The test objected that
   an endpoint exempted for having no client was reading `client_id`, which was
   exactly right. It is now guarded; `assert_client_access(user, None)` is a
   no-op on the create-a-new-client path, which is the correct reading.

   **Also fixed 2026-08-07 — `payroll` (16 endpoints), the most sensitive
   surface reached so far.** It imported no authz at all, so any authenticated
   member of a firm could reach any client's individual salaries, PAN, PF/ESI
   numbers and employee bank details; a named person's payslip PDF; the salary
   register and statutory summary; and the endpoints that finalize, **disburse**
   and reverse a payroll run.

   `payroll_employees`, `payroll_runs` and `salary_structures` carry a NOT NULL
   `client_id` and are guarded directly. **`payroll_slips` carries a `run_id`
   and an `employee_id` and nothing else — no `client_id`, and no `firm_id`
   either.** One person's payslip lives in a table with no tenant column at all,
   so it is scoped through its run, which makes that hop load-bearing for BOTH
   boundaries. (Tenant scoping for the PDF already existed in
   `payslip_pdf_service`; what was missing was the client check on top.) A test
   asserts the two-hop shape explicitly, because a guard that stopped at the
   slip row would have had neither boundary.

   **Also fixed 2026-08-07 — `recurring_invoices` (11 endpoints).** Nine are the
   usual shape (resolve the template, check its client; narrow the firm-wide
   list). The tenth needed a different answer.

   `POST /api/recurring-invoices/run` is **not a list — it is a write across
   every client in the firm**, generating draft invoices. Narrowing its output
   would be the wrong shape entirely: the drafts would already exist by the time
   anything was filtered. So the RUN is confined instead. A Partner or Manager
   is firm-wide (`effective_client_ids` returns None) and gets the single
   firm-wide call exactly as before — the fix must not turn one query into N for
   the people who legitimately see everyone — while an Executive generates only
   for the clients they are assigned to. Results are merged so the response shape
   is identical for both, and no caller has to know which branch ran.

   An empty assignment set means **no** books to write into, which is worth
   stating because the unguarded `client_id=None` it replaces meant *all* of
   them.

   **Also fixed 2026-08-07 — `memory_intelligence` (14 endpoints), plus a
   whole-router break found while testing it.**

   **The router was dead.** All 14 endpoints called `api_response(data=...)`
   without the REQUIRED first argument `success`, so every one raised
   `TypeError` at runtime. `memory_intelligence` was the only file in the
   codebase doing it, and nothing exercised these handlers, so it had gone
   unnoticed. Fixed, with a test that drives every registered memory endpoint
   and asserts the `{success, data, error}` envelope other routers keep.

   On scope: an AI profile of any client — the firm's accumulated knowledge of
   how that client behaves and what they repeatedly get wrong — was readable by
   anyone in the firm, along with every trigger, anomaly and year-end readiness
   report. `client_profiles` and `year_end_reports` carry a NOT NULL client_id;
   `ai_memory_triggers` and `pattern_anomalies` a NULLABLE one, because a
   trigger can be firm-level ("three clients missed the same deadline") and must
   survive a narrowed list rather than vanish from it.

   **The first 403 in the sweep.** `POST /pipeline/run` and
   `POST /firm/profile/compute` are firm-WIDE computations — the pipeline loops
   every client in the firm and writes a profile, triggers, anomalies and a
   year-end report for each. There is no honest partial version: running it for
   a subset and reporting it as "the firm pipeline" would be worse than
   refusing. So they are limited to firm-wide roles with a **403, not the 404
   used everywhere else** — nothing is being hidden, a capability is being
   refused, and pretending the endpoint did not exist would be the misleading
   answer. The message names the per-client endpoint the caller can use instead.

   **Also fixed 2026-08-07 — the task routers (15 endpoints across TWO files).**
   `/api/tasks` is served by both `tasks.py` and `task_extras.py`. `tasks.py` had
   a guard on the list and on create; `task_extras.py` imported no authz at all,
   so the tags, dependencies and full timeline of **any** client's task were
   readable and writable by anyone in the firm. `tasks.client_id` is NOT NULL and
   every handler already loads its task firm-scoped, so the guard takes the row
   that is already on the desk and costs no extra query. `task_tags`,
   `task_dependencies` and `task_timeline_events` carry no client of their own —
   they are all reached through that task.

   Three of the fifteen needed a different answer:

   * **`POST /{task_id}/dependencies` names a SECOND task, in the body.** The
     response and the timeline event both echo `dep_task["title"]`, so checking
     only the task in the path hands over another client's task by name. Both
     ends are checked.
   * **`GET /tags/all` is autocomplete, not a record** — but a tag is free text
     somebody typed on a client's task, and "acme-gst-migration" names a client
     as surely as a client_id does. The vocabulary is resolved through its tasks
     and narrowed. `task_tags` has no foreign key to `tasks` (migration 063), so
     PostgREST cannot embed the join; it is two queries, not one per tag, and a
     firm-wide role keeps the single-query path it always had.
   * **The three `trigger-*` endpoints** (escalations, the daily automation
     batch, recurring generation) are firm-**wide** jobs, not rows. Same
     reasoning as the memory pipeline above: **403, not 404** — no id is
     involved and nothing is being hidden, so a "not found" would be a lie.

   `/api/tasks/summary/dashboard` is exempt: aggregate counts only — open tasks
   by status, overdue counts, a high-risk-client tally. No client is named and no
   per-client figure is returned.

   **Two things this phase turned up that were not scope bugs:**

   * **`_detect_cycle` read the entire `task_dependencies` table** — every firm's
     rows — to answer a question about two tasks in one firm, then did the graph
     walk in Python. The table has no `firm_id` of its own (migration 063 scopes
     it through `tasks`), so there is no filter to add; the fix is to bound the
     traversal, walking outward from the starting task one breadth-first level
     at a time so every edge read is one an ancestor already points at. It had
     no tests at all before this; it has six now, including one that fails on
     any unfiltered read.
   * **A refusal message had already drifted from the rule it describes.** Both
     `memory_intelligence` and the new task guard told a refused caller the
     endpoint was limited to "Partners and Managers" — but the M3 decision left
     only the **Partner** firm-wide (`_FIRMWIDE_ROLES`), so a Manager was reading
     a 403 saying they should have got in. `core.authz.firmwide_roles_label()`
     now derives the wording from `_FIRMWIDE_ROLES`, both call sites use it, and
     a test pins it. Checked the rest of the codebase for the same shape: the
     only other role sentence in a refusal is `year_end_reviews.py:333` ("Only
     Partner can lock an engagement"), which matches its literal
     `role != "Partner"` check and is correct post-migration 081.

   **Recorded, not fixed — the dashboard counts are firm-wide for everyone.**
   `/summary/dashboard` is exempt because it names no client, but an Executive
   assigned to two clients still sees the firm's total open-task and overdue
   counts. That is a cardinality signal, and arguably just wrong as a product
   behaviour rather than only as a scope one. Narrowing it touches
   `domain/task_service.py`, `client_repo` and `compliance_record_service`
   together, so it is stated here as a decision to take rather than folded into
   an authz commit. The lifecycle dashboard sits on exactly the same line.

   **Also fixed 2026-08-07 — `task_recurring` (9 endpoints).** A separate router
   on `/api/task-recurring`, so the `/api/tasks` prefix registered above does
   **not** cover it — the two read as one feature and are two registrations.

   This one is a different shape from the rest of the sweep, and a more
   misleading one. It *did* import `core.authz` and it *did* call
   `assert_client_access` — twice — on a caller-supplied `body.client_id` in
   `create_recurring` and `update_recurring`. Nothing checked the client of a
   config the caller named **by id**, so every stored config was open: edit it,
   delete it (which had no existence check at all), or rewrite the assignment
   rules that decide who in the firm ends up doing the work. A guard on the
   input and none on the record reads as "already handled" to anyone skimming.

   `_assert_config_scope` resolves the config within the firm and checks its
   client, returning the row so nothing is fetched twice. `update_recurring`
   now checks **both ends** — the config being edited and the client it is being
   moved to — because a destination-only check lets a config be lifted out of
   another client's book, and a source-only check lets it be pushed into one.
   `assignment_rules` (migration 045) carries a `firm_id` and a
   `recurring_config_id` and no client of its own, so all four rule endpoints
   are scoped through the config.

   `task_recurring_configs.client_id` is **nullable** (migration 063): a config
   with no client is a firm-level recurring task, not a hidden one. Both paths
   have to agree — `assert_client_access(user, None)` passes it and
   `filter_by_client` keeps it — and the tests drive the real `filter_by_client`
   rather than a stub, because a hand-written stub would encode one reading of
   the rule and then agree with itself.

   `POST /generate` is the same shape as the recurring-**invoice** run: a write
   across the firm, so the run is confined rather than the output narrowed. The
   service gained an `allowed_client_ids` parameter, filtered in Python rather
   than pushed into the query, because PostgREST's `in_` cannot match NULL and
   pushing it down would drop exactly the firm-level configs that must survive.
   A caller assigned to nothing still generates the firm's own recurring tasks
   and nothing else. The nightly cron passes nothing and keeps its single pass.

   **Recorded — this router has no frontend caller at all.** Nothing under
   `apps/web` references `/api/task-recurring`. Nine working endpoints, an
   assignment-rule engine and a generation service with no UI to reach them; the
   nightly job is the only thing that runs the generation. Second instance after
   `memory_intelligence` of a whole router the product cannot reach, which is
   why the coverage sweep below keeps being worth doing.

   **The pattern, swept.** "Guards the body, not the record" is checkable:
   routers that call `assert_client_access` on a `body.*` client_id while also
   exposing id-addressed routes. Twelve unaudited routers have that exact shape
   and are therefore *more* likely to look handled than an unguarded one —
   `tds_workspace`, `gst_workspace`, `mca_workspace`, `relationships` (3 body
   guards each), then `ai_copilot_v2`, `billing`, `compliance_records`,
   `customers`, `engagements`, `reconciliation`, `reminders`, `task_templates`.
   Worth taking before the routers with no guard at all, because the shape
   defeats a reviewer rather than merely failing to help one.
   **Eleven of the twelve are now taken — `reconciliation` and
   `compliance_records` needed no fix at all. One remains: `ai_copilot_v2`.
   `vendors` — found while auditing `customers`, not one of the original
   twelve — is done too, and so is `billing`, both below.**

   **Also fixed 2026-08-07 — the TWO TDS routers (20 endpoints).**
   `tds_workspace` on `/api/tds-workspace` (12) and `tds` on `/api/tds` (8) are
   one feature and two registrations. This is the "guards the body, not the
   record" shape named above, and it was the top of that list for a reason.

   `tds_workspace` imported `core.authz` and called `assert_client_access` four
   times — on the four POST bodies. Every endpoint that took its client from a
   **query parameter**, and every one addressed by a **row id**, was unguarded:
   any member of the firm could read any client's challans, filed returns, Form
   16/16A certificates and Form 26AS reconciliation, and could mark any client's
   statutory return **filed**, writing a PRN of their choosing onto the
   government proof-of-filing record (IT Act §200/§203). `tds.py` imported no
   authz at all; `/returns/{client_id}` and `/deductions/{client_id}` name a
   client directly in the path, and the two `/from-books` endpoints read a
   client's posted purchase bills or finalized payroll runs out of the ledger.

   **Two refusal shapes, because this router reports "not found" two ways.**
   Endpoints that NAME a client get the 404 every other audited router gives.
   Endpoints addressed by a row id report a missing row as a **200** carrying
   `{"success": false, "error": "Not found"}` — so a 404 refusal there would
   make the *status code* the oracle: 404 means the id is real and belongs to
   somebody else, 200 means it does not exist. Those go through
   `_visible_or_none`, which returns None and sends the refusal back down the
   router's own not-found path byte for byte. A test asserts the forbidden and
   the nonexistent responses are equal, rather than merely both unsuccessful.

   **The swallowing `try`.** Every handler in `tds_workspace` ends in a bare
   `except Exception: return api_response(False, None, str(e))`. A guard placed
   inside that block has its 404 caught and returned as a 200 — the guard
   silently downgraded to a log line. The query-param guards therefore sit
   **before** the `try`, and a test fails if one moves back inside; it is a
   distinct mutant from dropping the guard entirely, and both are killed.

   **The two `/compute` endpoints are guarded even though they do not need it
   today.** They are pure functions over caller-supplied rows and never read
   `req.client_id`. An exemption would be true right now and silently false the
   first time somebody uses the field the request model already requires — and
   the sweep's honesty tests check that an exempted ROUTE still exists, not that
   its REASON still holds. One line is cheaper than that trap.
   `/compute-amount` (no client_id in the model at all) and `/sections` (the
   statutory rate table from the IT Act) are exempt, and a test asserts
   `/sections` is *not* client-scoped, because over-guarding is a real failure
   mode.

   **A latent bug in the ratchet itself, found by this pair.** `/api/tds` is a
   string prefix of `/api/tds-workspace`, and `_routes()` attributed each route
   to the **first** matching `AUDITED` prefix — so declaration order decided
   which router's guard names a workspace route was checked against. It now
   takes the **longest** match, which makes the registry order-independent.
   Third flaw found in the sweep by using it; reverting it to first-match is a
   mutant the suite kills.

   **Also fixed 2026-08-07 — the THREE GST routers (25 endpoints).**
   `gst_workspace` on `/api/gst-workspace` (13), `gst_portal` on
   `/api/gst-portal` (5) and `gst` on `/api/gst` (7). One feature, three
   registrations — and `/api/gst` is a string prefix of the other two, which is
   exactly the shadowing the longest-match fix above was for.

   `gst_workspace` is the TDS shape again: `assert_client_access` on its four
   POST bodies (task #231) and nothing anywhere else. Every endpoint taking its
   client from a query parameter and every one addressed by a row id was open —
   any member of the firm could read any client's GSTR-1, GSTR-3B, GSTR-9 draft
   and GSTR-2B reconciliation. `gst.py` and `gst_portal.py` imported no authz at
   all.

   **The two status endpoints had no read at all.** `PATCH /gstr1/{id}/status`
   and its GSTR-3B twin fired the `UPDATE` and used whatever came back. There is
   no way to check a client from that — by the time the row is in hand the
   return has already moved to `submitted` (CGST §37/§39). A scoped read was
   added so the refusal happens first, and a test drives the real query path to
   prove the update never runs on a refusal.

   **`/sync-jobs/{job_id}/run` needed the same treatment one level down.**
   `run_sync_job` in `domain/gst/portal_service.py` reads `job["client_id"]`
   itself — but only after flipping the job to `running` and starting to write
   snapshots into that client's record. A `get_sync_job(firm_id, job_id)` lookup
   was added so the router can resolve and refuse before any of that, with the
   firm filter on the query rather than applied afterwards.

   **Five endpoints on `gst.py` are exempt, and this is a stronger exemption
   than the TDS `/compute` pair got.** `/classify`, `/gstr1/build`,
   `/gstr3b/compute` and the two `/validate` endpoints are pure functions over
   rows the caller supplied, and their request models carry **no `client_id` at
   all** — there is nothing to check, rather than a field that exists and
   happens to be unused. A test asserts `/validate/gstr1` is *not* client-scoped,
   because over-guarding is a real failure mode. The two `/from-books`
   endpoints, which read a client's posted invoices, credit notes and GL control
   accounts and resolve that client's own GSTIN, are guarded — and the guard was
   moved above `get_supabase()` so the refusal lands before the database is
   touched at all.

   **Also fixed 2026-08-08 — `mca_workspace` (13 endpoints).** The third router
   in a row with the same shape, and by now the shape is the finding rather than
   the individual bug: `assert_client_access` on the three POST bodies
   (`create_company` / `create_director` / `create_filing`) and nothing on the
   endpoints that take their client from a query parameter or address a row by
   id. Any member of the firm could read any client's company master, its
   directors and their DINs and PANs, and every MCA filing with its SRN.

   **Both PATCH endpoints had no read at all.** `PATCH /directors/{id}` and
   `PATCH /filings/{id}/status` fired the `UPDATE` and used whatever came back —
   the same defect as the two GST status endpoints, found the same way. By the
   time the row is in hand the director's KYC status or the filing's MCA21 SRN
   has already been written (Companies Act §92/§137/§139), so there is nothing
   left to refuse. A scoped read was added to each.

   `GET /calendar` is **guarded despite reading nothing** — the deadlines are
   pure arithmetic from the AGM date. Same reasoning as the TDS `/compute` pair:
   the `client_id` is required by the signature and echoed through the response,
   so an exemption would be true today and silently false the first time
   somebody reads stored data there.

   `PUT /filings/{id}/complete` is a one-line delegation to
   `update_filing_status` in the same module. Rather than force a second,
   meaningless check into the wrapper to satisfy the sweep, `/api/mca-workspace`
   was added to `FOLLOW` so the sweep follows the delegation — and a runtime
   test calls the wrapper directly, because a delegation that stopped delegating
   would be a hole the source-level check would not see.

   **Also fixed 2026-08-08 — `relationships` (19 endpoints), and it contained
   the sharpest row in the sweep so far.**

   This router's tables split in two, and the split IS the design.
   **Firm-level, no client column:** `entities` (a person or company the firm
   knows about), `entity_relationships` and `entity_to_entity_relationships`
   (migrations 059/156). They are deliberately shared across clients — that
   sharing is what makes cross-client match detection possible at all.
   **Client-bearing:** `entity_roles` (client_id NOT NULL — "X is a Director AT
   this client"), `loans`, `properties`, and `cross_client_matches`.

   **A cross-client match names TWO clients.** Its entire content is "this PAN
   appears at client A and at client B". Firm-scoping alone handed an Executive
   assigned to client A the existence of client B and a named person's link to
   it, along with that person's PAN as the `match_value`. Both ends are checked
   now — **not either**, because seeing the row with only one end authorised
   still discloses the other. Checking only the first end, only the second, and
   `or` instead of `and` are three separate mutants, all killed.

   **`POST /cross-client-matches/detect` is firm-wide** — it reads every
   `entity_role` in the firm and writes match rows pairing clients. There is no
   honest partial version: running it over one Executive's book and calling the
   result "the firm's cross-client matches" would be worse than refusing,
   because the gaps are invisible. 403, third one in the sweep after the memory
   pipeline and the task trigger jobs.

   `DELETE /roles/{role_id}` was firm-scoped only — deleting "X is a Shareholder
   at client C" is editing client C's record. Guarded.

   **The entity register itself stays firm-level, and that is a decision rather
   than an oversight.** `entities` has no client_id, so `assert_client_access`
   has nothing to check — but unlike a template it IS traceable to clients
   through `entity_roles`, which is the "can a row be traced to a client" test
   this sweep has applied everywhere else (task_tags, payroll_slips,
   workflow_executions were all scoped through a parent). Narrowing it would
   break the shared-entity model the cross-client feature depends on, and an
   entity can legitimately exist with no roles at all. What IS narrowed is the
   part that names clients: `GET /entities/{entity_id}` returns the entity's
   ROLES alongside it, and those are filtered. **Whether the register itself
   should be assignment-scoped is an open product question** — an Executive can
   currently see the name, PAN, date of birth and address of every director and
   beneficial owner the firm has recorded, across every client. Recorded here
   rather than decided in an authz commit.

   **A systematic gap in my own testing, found by the mutation pass.** Every
   endpoint in this router has TWO implementations — a mock branch and a real-DB
   branch, selected by `_db()` returning None. The first mutation run left
   **six** survivors and every one was on the live branch, because the tests
   only drove the mock path. Two of those mutants were a live `SELECT` dropping
   the very column the guard reads; since `can_access_client(user, None)` treats
   a missing client as "firm-level resource" and returns True, that is the guard
   failing **open**. Live-path tests were added with a fake that honours the
   column projection precisely so those cannot hide. Worth carrying forward: any
   router with a mock branch has this hazard, and mock-only tests will not show
   it.

   **Audited 2026-08-08 — `reconciliation` (4 endpoints): already correct, no
   fix needed.** All four already called `assert_client_access` — this is the
   "Verify Books" router built in task #244, guarded when it was written. The
   work here was backing that claim rather than assuming it.

   Two of the four guards had **no test at all**: `GET /runs/{run_id}` and
   `POST /findings/{finding_id}/resolve` resolve the client from the row, and
   the existing tests only covered "unknown id". Deleting either
   `assert_client_access` broke nothing in the suite. Fixed.

   **What those tests can and cannot show, stated rather than implied.**
   `rbac("accounting", "approve")` admits only the Partner — Manager, Executive
   and Reviewer are all False — and `is_firmwide` is True for exactly the
   Partner. So on this router `can_access_client` only ever exercises its
   TENANCY leg; the assignment leg is unreachable. The guards are defence in
   depth against a cross-firm row and against the RBAC gate later widening, and
   the tests pin them at that and no further. Claiming the assignment boundary
   was tested here would have been false.

   The `services/reconciliation_service.py` queries were swept too: every
   read is firm+client scoped, or scoped through a parent it already scoped
   (`bank_transactions` via `reconciliation_id`), or writes the pair it was
   handed. Nothing to fix.

   **A fidelity gap in the shared test harness, found by mutation-testing this
   router.** `tests/e2e_harness.py`'s `FakeDB.select()` ignored its column list
   and returned whole rows. That hides a real class of bug across every test
   using it: a guard reading `row["client_id"]` keeps passing after somebody
   narrows the `SELECT` to `"id"`, and only fails against a live database.
   `select()` now projects. Two things worth recording about the fix:

   * The first attempt projected **before** ordering, which broke one inventory
     test — correctly. PostgREST orders, ranges and limits server-side, so an
     `ORDER BY` column need not appear in the `SELECT` list. Projection belongs
     last. The suite caught my error, which is the harness earning its keep.
   * Embeds (`a(b,c)`), `*` and aliased selects are passed through untouched;
     this only narrows a plain column list.

   One mutant looked equivalent and was not, which is worth writing down
   because the reasoning generalises. Dropping the row-level `firm_id` filter
   from `get_run` appeared redundant with the client check, since
   `can_access_client` verifies the client belongs to the caller's firm (the F1
   fix). The two come apart on one shape: **another firm's row pointing at a
   client that IS in my firm.** The client check waves it through; only the
   query's firm filter stops it. Pathological, and exactly why the filter is
   there — now pinned by a test.

   **Also fixed 2026-08-08 — the small-router batch: `reminders` (3),
   `engagements` (7), `compliance_records` (6), `task_templates` (6).** The
   tail of the "guards the body, not the record" list, taken as one phase
   because each alone would have been ceremony. What each turned out to need:

   * **`reminders` — one gap.** `PATCH /{id}/sent` checked only the firm; the
     reminder names a client and marking it sent writes that client's record.
   * **`engagements` — five gaps, plus one more of the update-both-ends kind.**
     Every row-addressed endpoint (`GET`, `PATCH`, `DELETE`, `/transition`,
     `/generate-obligations`) was firm-only; the last of those writes draft
     statutory obligations into the client's compliance records. And
     `PATCH`'s destination check verified only firm membership, so an
     assigned-scope caller could move an engagement into any client's book.
     `fee_engagements.client_id` is NOT NULL (migration 014), so the guard
     reads the row already in hand.
   * **`compliance_records` — already fully guarded** (task #238). The
     list/get/create/update guards were already pinned in
     `test_audit_remediation_5_1a` and `test_r238`; the two router guards
     nothing pinned — `/firm/summary`'s narrowing and `/client/{id}/health` —
     are pinned now.
   * **`task_templates` — the firm-template pattern.** Five template routes
     exempt (`firm_id` nullable, no client_id — migration 063; NULL = shared
     system template), and `/instantiate`, the one route that names a client,
     was already guarded — before the template is even loaded, and a mutant
     that moves the check after the load is killed.

   **A refusal-message oracle, caught by this batch's own test.** The
   equal-404s test failed on its first run because a hidden reminder said
   `"Not found"` (assert_client_access's generic detail) while a missing one
   said `"Reminder not found"` — with matching status codes, the DETAIL still
   distinguished them. Both `reminders` and `engagements` now refuse with the
   router's own message via `can_access_client`, and the tests assert the
   details are equal, not just the codes. Worth a look-back some time: earlier
   phases asserted status-code equality only, so the same message-level oracle
   may exist wherever a router's own not-found detail is more specific than
   "Not found".

   **Also fixed 2026-08-08 — `customers` (10 endpoints), and it went beyond
   the "guards the body, not the record" shape.** `create_customer` and
   `bulk_create_customers` already checked the client on the way in (task
   #231). Every other endpoint — including `PATCH /{id}`, which can post a
   real opening-balance GL journal, a soft delete, and a **permanent** delete
   that CASCADEs across invoices/receipts/credit notes — checked only the
   firm. `customers.client_id` is required by `CustomerIn`, so it is never
   absent on a real row; nothing here is a firm-level resource in disguise.

   One shared helper, `_load_customer_or_404`, replaces every row-addressed
   lookup and **always selects the whole row**, not a narrowed column list —
   several call sites originally selected only `opening_balance_paise`, and a
   guard reading `client_id` off a row that never fetched it would silently
   pass (a missing client reads as "firm-level" and is let through — the exact
   `FakeDB` lesson from the reconciliation phase, this time in a real
   endpoint rather than in test infrastructure).

   **The mock branches were inconsistent with each other before this, too.**
   `list_customers`'s mock branch already filtered by `firm_id`.
   `get_customer`, `update_customer`, `get_customer_dependencies` and
   `delete_customer`'s did not — they matched on id alone, so in dev/mock mode
   any customer id from any firm was readable. Centralizing the lookup fixed
   that as the same change, not a separate one.

   **A message-oracle bug found while writing the equal-404s test, the same
   shape as the small-router batch's but the opposite direction.** This
   router's own convention echoes the id into its 404s
   (`f"Customer {id} not found"`), which is fine — the caller already knows
   the id they asked for. But the new guard's client-check branch was calling
   `assert_client_access`, which raises its own generic `"Not found"` — so a
   *hidden* customer got `"Not found"` while a *missing* one got
   `"Customer X not found"`. Same status code, different body: still an
   oracle. Fixed by using `can_access_client` (boolean) and raising the
   router's own message for both branches. The lesson from the small-router
   batch generalizes in both directions: whichever message a router's OWN
   convention uses, both refusal paths have to produce it identically.

   **Found while writing this phase, not fixed here (the bug-fixing rule):**
   `routers/vendors.py` is structurally the same file — `list_vendors`,
   `get_vendor`, `update_vendor`, `get_vendor_dependencies`, `delete_vendor`
   and `get_vendor_outstanding` show the identical shape, including the
   inconsistent-mock-firm-scoping detail (`list_vendors`'s mock branch filters
   `firm_id`; `get_vendor`'s does not). The vendor equivalent of every write
   fixed here — an opening-balance journal post, a soft delete, a permanent
   delete — is open the same way. Same size class as `customers`; next up.

   **Also fixed 2026-08-08 — `vendors` (10 endpoints), exactly as flagged in the
   previous phase.** Structurally the same file as `customers.py`
   (`VendorIn.client_id` is required, same as `CustomerIn`'s), so the same
   fix, applied the same way: `create_vendor` and `bulk_create_vendors`
   already checked the client on the way in; every other endpoint checked
   only the firm, including `PATCH /{id}` (can post a real opening-balance GL
   journal) and a permanent delete that CASCADEs across bills and payments.

   Two endpoints here have no `customers.py` counterpart. `ap_aging` and
   `vendor_statement` both take `client_id` as a query param and are guarded
   the same way as any other query-param endpoint. `vendor_statement` also
   takes `vendor_id` in the path — `vendor_statement_service._vendor` already
   ties `vendor_id` to `client_id` server-side (both columns must match one
   row), so the `client_id` check alone is sufficient. A test drives the real
   `_vendor` lookup with a vendor that belongs to a *different* client than
   the one named, rather than trusting the service's own docstring that this
   still holds.

   **`vendors` had no lifecycle test file at all.** `customers.py` has
   `test_customer_lifecycle.py`, driving `delete_customer`/`update_customer`
   through the real `FakeDB` (which honours `SELECT` column projection, per
   the reconciliation-phase fix) — that harness, not the client-scope unit
   tests, is what proved `_load_customer_or_404` fetches enough of the row
   for `opening_balance_paise` to survive a live query, and that a permanent
   delete's 409 uses the row's *real* balance rather than a stale default.
   `vendors.py` had no equivalent file, so both mutants — a narrowed live
   `SELECT`, and the permanent-delete branch silently reusing `0` regardless
   of the row's actual balance — survived the first mutation pass. Closed
   with two tests against the same `FakeDB` harness rather than a hand-rolled
   fake, since that is precisely the fidelity gap that matters here.

   **Also fixed 2026-08-08 — `billing` (16 endpoints), the last of the
   original twelve except `ai_copilot_v2`.** A different shape from every
   router so far: `PERMISSIONS["billing"]` (`core/permissions.py`) admits
   only Partner for both `read` and `write`, and Partner is the *sole*
   firm-wide role (`core/authz.py`'s `_FIRMWIDE_ROLES`). Every endpoint on
   this router requires it, so a Manager, Executive or Reviewer 403s at the
   RBAC dependency before any handler body runs — the M2 assignment-scope bug
   this whole sweep exists to close **cannot occur here by construction**.
   That was worth confirming by reading the permission matrix directly rather
   than assuming from the router's own docstring, which makes the same claim
   but is exactly the kind of comment that drifts (see `firmwide_roles_label`,
   added earlier in this sweep for the same reason).

   What was still real: `assert_client_access`'s *other* half. It composes a
   firm-boundary check (does `client_id` actually belong to the caller's
   firm?) with the assignment check, and only the second one is moot for a
   firm-wide caller — the first still matters, because a Partner in Firm B
   supplying Firm A's id should not reach Firm A's data. `create_schedule`
   already had this guard (a prior fix). Nothing else did:

   - `generate` (`POST /schedules/{schedule_id}/generate`) loads the schedule
     via `billing_service.get_schedule`, which does firm-scope its own query —
     but nothing asserted the invariant at the router, so a future edit to
     that query (e.g. someone "simplifying" it to drop the `firm_id` filter)
     would have nothing left to catch it. Same reasoning as every prior
     router in this sweep: guard the record, not just trust the query under
     it.
   - `run_customer_reminders` and `unbilled_work` both take an optional
     `client_id` **query parameter**. The services already `AND` it with
     `firm_id` (`collections_service._open_invoices`,
     `billing_service.unbilled_work`), so a foreign id was never a leak —
     just a silent empty result instead of an explicit refusal, which is
     still the wrong behavior for a caller-supplied id that names something
     real in another firm.
   - `record_fee_receipt` (`POST /fee-invoices/{invoice_id}/receipts`) is the
     one genuine gap with a real leak shape. `fee_invoices` is a **separate**
     table from the `billing_schedules` system above it in the same file
     (migration 172's Fee Billing system), and `fee_invoices.client_id` is
     `NOT NULL` (migration 014) — every invoice belongs to exactly one
     client. `services/fee_billing_service.record_receipt`'s only check was
     `invoice.get("firm_id") != firm_id`, and the repository call underneath
     it (`invoice_repo.find_by_id`) does not filter by firm **at all** — the
     manual Python comparison after the fetch was the only thing standing
     between a foreign firm's `invoice_id` and a receipt being posted against
     it. Fixed with a named resolver, `_assert_invoice_scope`, mirroring
     `sales_invoices.py`'s `_assert_invoice_scope` — not just for the
     sweep's own row-addressed-endpoint test (which requires a named
     resolver rather than a bare `assert_client_access` call on principle:
     see that test's docstring), but because the naming makes the
     resolve-then-assert discipline explicit at the call site.
   - `list_schedules` returns the firm's whole schedule catalogue with no
     `client_id` filter at all. Since `effective_client_ids` returns `None`
     for a firm-wide caller, narrowing it with `filter_by_client` is a
     no-op *today* — but it is the same real, load-bearing call used
     throughout the rest of the codebase for this exact shape, kept explicit
     so the invariant already holds if `"billing"` is ever opened to Manager
     or Executive (a plausible product direction, not a hypothetical one).

   The other eleven endpoints — `preview_run`, `run`, `ar_aging`,
   `collections_dashboard`, `run_overdue_sweep`, `send_reminders`, the
   reminder-settings GET/PUT, and the staff-cost-rate GET/PUT — are firm-wide
   aggregates or firm-level settings/HR data with no `client_id` in the
   request at all, and stay exempt with that reason (verified, not assumed,
   by the sweep's own honesty test that an exemption cannot cover a handler
   whose source mentions `client_id`).

   **Another message-oracle bug, same shape as `customers`' but caught before
   merge this time.** The first version of `_assert_invoice_scope` used
   `assert_client_access` for the client-check branch, which raises its own
   generic `"Not found"` — while the missing-row branch raised this router's
   own `f"Invoice {id} not found."`. A hidden invoice and a missing one would
   have produced the same status code with different bodies, the exact
   pattern the `reminders`/`customers` phases already found and fixed
   elsewhere. Caught by the equal-detail-text test for this router *before*
   the phase was called done, not after — the fix is the same one used
   everywhere else: `can_access_client` (boolean) plus the router's own
   message for both branches.

   **Found while writing this phase, not fixed here (the bug-fixing rule):**
   `routers/invoices.py` reads and writes the exact same `fee_invoices` table
   `record_fee_receipt` above guards, and it is *not* Partner-gated —
   `PERMISSIONS["invoice"]` is `_AT_LEAST_EXECUTIVE`, so Manager and Executive
   (both assignment-scoped under M3) can reach it directly. Every handler —
   `list_invoices`, `get_invoice`, `generate_from_engagement`,
   `generate_from_time_entries`, `download_invoice_pdf`,
   `change_invoice_status`, `delete_invoice` — checks only
   `invoice.get("firm_id") != firm_id` (or the equivalent for the
   engagement it is generated from), with no assignment check at all, and
   with `403` rather than the rest of the codebase's `404` convention. This
   is a live M2 gap, not a firm-boundary one: an Executive assigned to a
   single client can currently list, download, transition the status of, and
   **permanently delete** (Draft-only, but still) every other client's fee
   invoices firm-wide. Larger in blast radius than anything found in
   `billing` itself — promoted to the very next phase rather than left for
   later in the tail, the same way `vendors` followed `customers` immediately
   after being flagged.

   **Also fixed 2026-08-08 — `invoices` (8 endpoints), exactly as flagged in
   the previous phase.** Confirmed live, not just structurally suspicious:
   `PERMISSIONS["invoice"]` is `_AT_LEAST_EXECUTIVE`, so unlike `billing`
   both Manager and Executive — assignment-scoped roles under M3 — reach
   every handler directly. Every one of them checked only
   `invoice.get("firm_id") != firm_id` (or the equivalent for the engagement
   an invoice is generated from), with no assignment check, and refused with
   `403` rather than this codebase's `404` convention — a disclosure oracle
   in its own right, independent of the M2 gap: a missing `invoice_id`
   already got 404 while a wrong-firm one got 403, so the status code alone
   said whether the id was real. `fee_invoices.client_id` and
   `fee_engagements.client_id` are both `NOT NULL` (migration 014), so
   nothing here is a firm-level resource in disguise.

   Two named resolvers, `_assert_invoice_scope` and `_assert_engagement_scope`
   (the latter for the two generate-from-engagement endpoints), both use
   `can_access_client` and this router's own `"Invoice not found"` /
   `"Engagement not found"` for every branch — missing, wrong-firm, and
   wrong-client all raise byte-identical details, closing the pre-existing
   403/404 oracle at the same time as the M2 gap. Neither repository method
   underneath them (`invoice_repo.find_by_id`, `engagement_repo.find_by_id`)
   filters by firm at all, so the manual firm check inside each resolver is
   load-bearing, not redundant — confirmed by reading both repositories
   directly rather than assuming.

   **`run_overdue_check_endpoint` needed a different shape than every other
   fix in this sweep.** It is a WRITE across every Issued invoice in the
   firm (the daily Issued→Overdue transition), not a list — narrowing the
   *output* after the fact would be the wrong model, since the status
   transitions would already have happened to clients the caller cannot
   see. Confined the run itself instead, the same pattern already shipped in
   `recurring_invoices.py`'s `/run`: a firm-wide caller still runs once
   across the whole firm; an Executive or Reviewer now runs the check once
   per client they are actually assigned to, merging the results. Required
   a small service change — `invoice_lifecycle_service.run_overdue_check`
   gained an optional `client_id` param threaded into the existing
   `invoice_repo.find_all(client_id=...)` filter it already supported for
   other callers — verified the daily scheduler's call site
   (`jobs/scheduler.py`) still passes only `firm_id` by keyword, so its
   firm-wide behavior is unchanged.

   **25 new tests, all 7 mutants killed, full suite identical to baseline.**

   **Also fixed 2026-08-08 — `ai_copilot_v2` (17 endpoints), the last of the
   original twelve "guards the body, not the record" routers.** Three
   endpoints (`send_message`, `quick_chat`, `client_intelligence`) already
   guarded their `context_id`/`client_id` before this phase. Every other
   row-addressed or query-param endpoint that reaches client-scoped data did
   not: `create_conversation` accepted a caller-supplied `context_id` ("e.g.,
   client_id" per its own model comment) unchecked; `get_conversation` and
   `archive_conversation` were firm-scoped only, so any member of the firm
   could read or archive another's client-scoped AI chat history by id;
   `rate_message` was the same shape one hop further in — `ai_messages`
   carries no `context_id` of its own, only its parent conversation does, so
   the fix resolves message → conversation → context before allowing a
   rating; `list_recommendations` took an unchecked `client_id` query param
   and returned the firm's whole list unfiltered without one;
   `act_recommendation` and (when linked to one) `execute_ai_action` were
   row/body-addressed by `rec_id` with no check that `ai_recommendations.
   client_id` — nullable, since some recommendations are firm-wide — named a
   client the caller may access; `list_summaries` took the same unchecked
   pattern via `entity_id`.

   **Two named resolvers**, `_assert_conversation_scope` and
   `_assert_message_scope`, both use `can_access_client` and this router's
   own message for every branch, matching the message-oracle discipline
   from every prior phase. `list_conversations` and `list_recommendations`
   both got a real `filter_by_client` call rather than being exempted
   alongside their path-mates (`create_conversation`/`act_recommendation`'s
   siblings) — the same fix `billing.py`'s `list_schedules` needed for the
   identical shared-path reason: `EXEMPT` is keyed by path, not by method,
   so exempting `/conversations` would have hidden `create_conversation`'s
   real guard from the ratchet too.

   **Found and NOT fixed here — recorded as an open question, the same way
   the entity register and the task dashboard were in earlier phases.** Four
   endpoints — `compliance_intelligence`, `workflow_intelligence`,
   `relationship_intelligence`, `executive_dashboard` — aggregate across the
   whole firm with no per-client identifiers in their CURRENT output,
   confirmed by reading `domain/ai_copilot_service.py`'s actual
   implementations rather than the aspirational Pydantic response models in
   `models/ai_copilot.py` (which declare fields like `at_risk_clients` /
   `cross_client_conflicts` that the real functions do not populate). That
   is a real gap, not a non-issue: an Executive assigned to one client sees
   firm-wide compliance/workflow/relationship counts today. But a correct
   fix is bigger than a guard, for two different reasons:
     - `workflow_intelligence` pulls from `workflow_failures` and
       `workflow_approvals`, neither of which carries a `client_id` column
       — only `instance_id` (migration 068). Narrowing by client means
       joining through `workflow_instances`, which the repository does not
       currently expose a method for.
     - `compliance_intelligence` and `executive_dashboard` cache ONE
       firm-wide summary per firm (`ai_summaries`, `entity_id=None`) shared
       across every caller regardless of assignment. Narrowing the counts
       they compute without also changing the cache key would still serve
       a Manager's cached firm-wide response to the next Reviewer who asks —
       a cross-caller cache-poisoning shape distinct from every other fix
       in this sweep, and one that needs a caching-architecture decision
       (key by scope? skip the cache for scoped callers?) before it can be
       guarded correctly.
     - `relationship_intelligence`'s cross-client PAN/email matching is
       *computed over* the whole client list by design — the same tension
       already on record for `/api/relationships/entities`: narrowing the
       input set changes what the analysis IS, not just who can see it.

   **Also found, unrelated to M2 — `list_summaries` reads from the WRONG
   data source in live mode.** It always reads the in-process
   `MOCK_SUMMARIES` list directly, bypassing `_USE_MOCK` and the
   repository's `get_summary`/`upsert_summary` methods entirely (which
   correctly branch to the real `ai_summaries` table). In production this
   endpoint is effectively always empty — a "whole feature unreachable"
   bug in the same family as `memory_intelligence`'s from an earlier phase,
   not a client-scope one. Not fixed here (a data-source bug, not an
   authorization one); the `entity_id` guard was still added on the
   principle that the same risk exists whether or not it is reachable today.

   **29 new tests, all 9 mutants killed, full suite identical to baseline.**

   **Also fixed 2026-08-08 — `health` (13 endpoints), the first of the "long
   tail" routers (not one of the original twelve).** The best-guarded file
   found so far going in: `get_client_health`, `get_dimension_detail`,
   `list_scores`, `get_score`, `get_score_history` and `list_overrides` all
   already called `assert_client_access`/`filter_by_client` — R3.15, an
   earlier phase, had already closed a cross-TENANT `firm_id` query-param
   override on this router's reads and assignment-scoped every read
   endpoint. What R3.15 explicitly left alone was writes: `calculate_score`
   and `create_override` (row-addressed by `client_id`) had no guard at
   all; `deactivate_override` and `resolve_alert` (row-addressed by their
   own id) were firm-scoped only in live mode and not even that in mock
   mode (`health_overrides.client_id` / `health_alerts.client_id` are both
   `NOT NULL`, migration 059).

   **R3.15's own test suite caught a REAL conflict, not a false positive.**
   `test_calculate_score_still_works_for_a_non_assigned_executive` failed
   against the new guard — R3.15's module docstring explicitly documented
   "write endpoints remain firm-scoped-only (unchanged), matching the
   established compliance_records.py/compliance_ops.py precedent." That
   precedent no longer holds: task #238, earlier in *this* sweep, extended
   assignment-scope to compliance_records.py's own writes
   (`create_compliance_record`, `update_compliance_record`) — confirmed by
   rereading that file's fix comments directly rather than trusting the
   claim secondhand. R3.15 predates that evolution. Rather than revert the
   new guard to keep the old test green, the test was updated: renamed to
   `test_calculate_score_404s_for_unassigned_client` (mirroring the read
   pattern), with a new `test_calculate_score_still_works_for_an_assigned_
   executive` alongside it, and the module docstring records why. An
   unauthorized WRITE here — overwriting a client's health score, or
   creating an override that can mask a real Critical status — is at least
   as sensitive as an unauthorized read, not less, and every other write
   this sweep has guarded (`create_override`/`deactivate_override`/
   `resolve_alert` in this same file included) makes the same call.

   **`recalculate_all` needed the confine-the-run shape**, same as
   `invoices.py`'s `run_overdue_check_endpoint` and `recurring_invoices.py`'s
   `/run`: a firm-wide WRITE across every client's score, now confined via
   `effective_client_ids` — a Partner still runs once across the whole
   firm; a Manager (assignment-scoped under M3, and `rbac("client","write")`
   admits Manager, not just Partner) now runs it once per client they are
   actually assigned to.

   **`health_dashboard` was the most severe finding in this router** — worse
   than a leaked count, since `critical_clients`/`at_risk_clients` are NAMED
   rows (`client_id`, `client_name`, score), returned firm-wide with no
   narrowing at all, unlike `list_scores`/`list_alerts` two sections above
   it in the same file which already used `filter_by_client`. Fixed the
   same way. Its mock branch had a second, separate bug: no firm filter
   whatsoever on `_MOCK_SCORES` (every other endpoint in this file does
   filter mock data by firm) — a real cross-tenant gap in dev/mock mode,
   fixed alongside the M2 issue since it lives in the same three lines.
   `top_alerts` fetches a larger batch (50, not 10) before filtering and
   narrowing to 10 — filtering after a pre-limited fetch could otherwise
   under-fill an assignment-scoped caller's list even when more of their
   own clients' alerts exist further down the firm-wide order.

   **21 new tests, all 9 mutants killed on the second pass** — the first
   pass had one survivor (`health_dashboard`'s live-mode branch), because
   both dashboard tests forced mock mode via the shared `deny` fixture and
   never exercised the live-mode query path at all; closed with a dedicated
   live-mode test using a fake Supabase client. Full suite identical to
   baseline once the R3.15 test was reconciled.

   **Also fixed 2026-08-08 — `year_end_adjustments` (7 endpoints).** Every
   endpoint resolves an `engagement_id`, and `year_end_engagements` is the
   client-bearing table (`client_id` derived from it, never trusted from the
   request — an earlier F9 fix). Every WRITE already called a resolver
   (`_fetch_engagement_db` live / `_guard_locked_mock` mock) that checked
   the engagement belonged to the caller's firm and, live-only, that it
   wasn't locked — but neither ever checked the engagement's *client*
   against the caller's assignment. `list_adjustments` didn't call any
   resolver at all. `rbac("year_end", "read"/"write")` is
   `_AT_LEAST_EXECUTIVE` and `"approve"` is `_AT_LEAST_MANAGER` — both
   assignment-scoped roles under M3, so this was live on every endpoint.

   **A three-way shared-prefix collision, a new shape for this sweep.**
   `year_end.py`, `year_end_checklist.py` and `year_end_adjustments.py` all
   declare the identical router prefix (`"/year-end"`) and are mounted at
   `app.include_router(..., prefix="/api")` — three distinct, separately
   unaudited routers in one namespace, not a string-prefix-of-a-longer-one
   shape like `/api/gst`'s three-way split. Registering `/api/year-end`
   would have swept in the other two files' completely unaudited routes.
   Registered the literal path segment that actually distinguishes this
   router's routes instead —
   `/api/year-end/{engagement_id}/adjustments` — which doesn't
   string-prefix-collide with either sibling (`/engagements...` or
   `/{engagement_id}/checklist...`).

   **Two bugs found while testing the fix, neither one M2 — both fixed in
   the same file since they sit in the exact lines being touched.**
   Supabase's real `.single()` raises (`PGRST116`) rather than returning
   `None` when zero rows match, so a missing or wrong-firm `engagement_id`
   (or `adjustment_id`, in five more call sites in this same file) was
   crashing every one of these endpoints into a `500` instead of the `404`
   the `if not row` line was written to produce — caught by the e2e
   `FakeDB` harness, which mimics this real Postgrest behavior exactly. The
   same `.single()`-without-a-`try`/`except` shape also appears in
   `health.py`, `relationships.py`, `lifecycle.py`, `engagement_letters.py`,
   `fixed_assets.py` and `form_26as.py` — found, not fixed; a correctness
   question independent of client-scope and out of proportion for this
   phase to chase across six more files. Second: the client-check branch
   originally used `assert_client_access`, which raises its own generic
   `"Not found"`, while the missing-row branch raised this router's own
   `"Engagement not found"` — the same message-oracle shape fixed in three
   of the last four phases, closed the same way with `can_access_client`.

   **Unified the two write-time resolvers into one, `_assert_engagement_scope
   (db, engagement_id, current_user, *, require_unlocked=False)`,** rather
   than keeping a separate `_fetch_engagement_db`/`_load_engagement_or_404`
   split — partly for the obvious reason (one function, one place the
   client check can be forgotten from) and partly a mechanical constraint:
   `test_a_row_addressed_endpoint_is_not_satisfied_by_a_bare_client_check`
   requires a resolver named from a fixed list for any path matching
   `{engagement_id}` (among others), and `_assert_engagement_scope` is
   already that name in `invoices.py` — reusing it here, in a different
   module, is exactly the established per-router-local-helper convention
   the sweep has used everywhere else (`_assert_invoice_scope` also exists
   independently in both `billing.py` and `sales_invoices.py`).

   **27 new tests, all 7 mutants killed** on the second pass — the first had
   one survivor (`list_adjustments`'s live-mode branch, never exercised
   because both of its tests used mock mode), closed with two e2e tests via
   the same `FakeDB` harness used for the resolver itself. Full suite
   identical to baseline.

   **Still open — the same pattern in the remaining routers.** Counted rather
   than estimated this time (walk `app.routes`, keep `/api/*` paths with a path
   parameter, drop everything under an `AUDITED` prefix): **154** id-addressed
   routes have no client-scope check. Worst first: `itr_workspace` / `platform`
   at 6 each, and a long tail mostly in the
   3-5 range. That
   count is an upper bound — it includes
   genuinely firm-level resources (`/rules/{rule_id}`, branding, identity,
   platform) with no client to scope to. Each router needs the same judgement:
   which of its resources carry a `client_id`, then guard those and add the
   prefix to `AUDITED`. One router at a time — a blanket sweep would either
   over-guard firm-level endpoints or under-guard the ones whose client is named
   in a body rather than a path, which is precisely how the batch endpoints were
   missed the first time.

   **`itr_workspace.py` and `platform.py` — the two worst-first entries from
   above, taken together since one needed real fixes and the other needed
   none.** Not one of the original twelve; found next in the long tail.

   `itr_workspace.py` (17 endpoints, prefix `/api/itr`, no prefix collision):
   11 needed a guard. Five are query-param endpoints (`list_snapshots`,
   `list_filings`, `list_disallowances`, `list_deductions`, `list_bf_losses`)
   that took `client_id` straight from the caller and never checked it — the
   familiar shape. Six are row-addressed (`review_snapshot` by `snapshot_id`,
   `transition_filing`/`save_version`/`record_acknowledgement` by `filing_id`,
   `update_disallowance_status` by `disallowance_id`, `utilize_loss` by
   `loss_id`) and had no client check at all. `create_snapshot`,
   `create_filing`, `create_disallowance`, `auto_detect_40a3`,
   `create_deduction` and `create_bf_loss` were already guarded pre-phase
   (`client_id` is on the request body).

   This router delegates 100% to `domain/income_tax/computation_workspace.py`
   and `domain/income_tax/itr_workflow.py` rather than touching Supabase
   inline the way `billing.py`/`invoices.py`/`year_end_adjustments.py` do, so
   the four resolvers (`_assert_snapshot_scope`, `_assert_filing_scope`,
   `_assert_disallowance_scope`, `_assert_bf_loss_scope`) call new
   `get_snapshot`/`get_disallowance`/`get_bf_loss`/`get_filing` lookup
   functions added to those two domain modules instead of querying inline —
   matching the router's existing layering rather than breaking it for this
   one fix. `transition_filing`, `save_version` and `record_acknowledgement`
   share a single resolver, `_assert_filing_scope`, since all three act on the
   same `itr_filings` row via `filing_id` — three near-identical resolvers
   would have meant three places the check could drift apart. All four
   resolvers use `can_access_client` from the first line written, not
   `assert_client_access` — the message-oracle bug (a resolver's own 404 text
   differing from `assert_client_access`'s generic one at a matching status
   code) has now recurred often enough in this sweep to guard against by
   default rather than wait to find it.

   **Found, not fixed — the same `.single()`-raises-on-zero-rows bug, now in
   a seventh file.** While writing the new `get_bf_loss` lookup, its sibling
   `utilize_bf_loss` in the same module was reading a brought-forward-loss row
   with `.single()` and no `try`/`except` — a missing or wrong-firm `loss_id`
   crashes to `500` instead of the `404` the code was written to produce, the
   identical shape already found in `health.py`, `relationships.py`,
   `lifecycle.py`, `engagement_letters.py`, `fixed_assets.py` and
   `form_26as.py`. Not fixed this phase, same reasoning as those six: a
   correctness question independent of client-scope, out of proportion to
   chase down while the actual M2 gap in this file is the guard. Flagged with
   a comment on the new `get_bf_loss` function so the next reader sees it
   without re-discovering it.

   `platform.py` (9 endpoints, prefix `/api/platform`) needed **no code
   change** — read in full and confirmed genuinely exempt rather than
   assumed. It is the platform *owner's* cross-tenant admin surface, gated by
   `require_platform_admin`/`require_platform_admin_mfa` from
   `core.platform_auth`, a completely separate authorization system from
   `core.authz` — the router's own docstring says as much
   ("intentionally NOT part of firm RBAC"). It uses
   `get_service_supabase()` on purpose, to bypass firm RLS: suspending or
   purging a firm is the operator of the whole system acting, not a firm
   member reaching a client. Every endpoint reads or writes only
   `firms`/`users` rows — grepped for `client_id` across the whole file and
   found none. Registered with an empty guard-name tuple and all 9 endpoints
   (8 unique paths — GET and soft-DELETE share `/firms/{firm_id}`) in
   `EXEMPT` with the reason; deliberately **not** added to
   `test_every_audited_router_actually_imports_the_authz_engine`'s module
   list, since it correctly has no `core.authz` import to check for.

   **35 new tests** (`test_itr_workspace_client_scope.py`), all passing on
   first run. **15 mutants, all killed** — the 11 endpoint-level guard calls
   plus the internal `can_access_client` check inside each of the 4
   resolvers. Full suite identical to baseline (44 pre-existing
   environment-only failures, unchanged).

   **Still open, recounted the same way:** **142** id-addressed routes (down
   from 154 — the 6 `itr_workspace` and 6 `platform` routes that were the
   worst-first entries above are both now `AUDITED`). Worst first this time:
   `/api/year-end` (24, across `year_end.py`/`year_end_checklist.py`/
   `year_end_statements.py`/etc. — several distinct unaudited routers sharing
   the namespace, the same three-way-collision shape already seen with
   `year_end_adjustments.py`), then `/api/portal` (7), `/api/clients`,
   `/api/identity`, `/api/tally-migration`, `/api/debit-notes`,
   `/api/purchase-credit-notes`, `/api/settings` (5 each), and a long tail
   mostly in the 1-4 range.

   **`year_end.py` and `year_end_reviews.py`, the next of the `/api/year-end`
   siblings — audited together, and had to be.** `year_end.py` owns the root
   `year_end_engagements` table itself (create, list, get, PATCH status);
   `year_end_reviews.py` owns the review-and-approve workflow nested one
   segment deeper, under the SAME literal path
   (`/engagements/{engagement_id}/reviews/...`). Unlike
   `year_end_adjustments.py`'s clean split from its siblings (`/{engagement_id}
   /adjustments` shares no string prefix with `/engagements/...` or
   `/{engagement_id}/checklist`), there is no distinguishing segment here:
   every route `year_end_reviews.py` owns is a string-prefix EXTENSION of a
   route `year_end.py` owns, so the sweep's longest-prefix-match cannot
   register one without the other — registering just `year_end.py`'s routes
   would have swept `year_end_reviews.py`'s completely unaudited ones in
   under the same prefix by accident (or the reverse). Same shape as
   `/api/tasks` being shared by `tasks.py` and `task_extras.py`: one
   registration, `/api/year-end/engagements`, is a claim about both files —
   guarding the engagement record while leaving its approval-and-lock
   workflow open would be absurd anyway.

   **`year_end.py` (4 endpoints) had zero client-assignment checks —
   `core.authz` wasn't even imported.** `create_engagement` took `client_id`
   on the body and never checked it. `list_engagements` took an OPTIONAL
   `client_id`: checked when given, but when omitted the list was firm-wide
   with no per-row narrowing at all — fixed with `filter_by_client` in both
   branches, the same "unscoped list defaults to everything" shape found
   repeatedly this sweep. `get_engagement` and `update_engagement_status`
   are row-addressed by `engagement_id`, resolved by `firm_id` alone. A new
   `_assert_engagement_scope(current_user, engagement_id)` resolver
   (module-local to `year_end.py`, same name as the unrelated resolvers
   already in `year_end_adjustments.py` and `invoices.py` — the established
   per-file-local-helper convention) replaces both call sites and, as a
   side effect, closes the SAME `.single()`-raises-on-zero-rows bug already
   fixed in `year_end_adjustments.py` and found-not-fixed in six other files:
   `get_engagement`'s live-mode `.single()` call had no `try`/`except`.

   **`year_end_reviews.py` (5 endpoints) was the more serious gap: every one
   is a WRITE, and one of them is irreversible.** `submit_for_review`,
   `approve_review`, `request_revision`, `final_approve` and
   `get_review_state` each resolved their engagement with a local
   `_get_mock_engagement`/`_get_db_engagement` pair that checked `firm_id`
   only — this router never imported `core.authz` at all. `final_approve`
   transitions `approved` → `locked`, a terminal state with no outgoing
   transition in `_STATUS_TRANSITIONS`; a Manager or Executive could have
   locked another staff member's client's engagement permanently. Fixed by
   deleting both local resolvers and delegating to `year_end.py`'s
   `_assert_engagement_scope` by name (`from routers.year_end import
   _assert_engagement_scope`) rather than duplicating the check against the
   same table in a second file — one place the client-assignment logic
   lives, not two copies that could drift apart. `year_end_reviews.py`
   itself still imports no `core.authz` name directly (only the resolver,
   transitively), so it is deliberately NOT added to
   `test_every_audited_router_actually_imports_the_authz_engine`'s module
   list — same reasoning as `platform.py` and the `knowledge`/`mca_workspace`
   `FOLLOW` entries: the check that matters is the resolver-name check
   (`test_a_row_addressed_endpoint_is_not_satisfied_by_a_bare_client_check`)
   and the real runtime tests, not which file happens to hold the `import`
   line.

   **One test-fixture bug found and fixed, caused directly by the
   delegation:** `test_r3_8_year_end_review_workflow.py`'s `yer_app` fixture
   flipped `routers.year_end_reviews._USE_MOCK` to `False` for its e2e
   `FakeDB` tests but never touched `routers.year_end._USE_MOCK` — a
   separate module-level flag that `_assert_engagement_scope` now reads,
   since it lives in `year_end.py`. Every review-workflow e2e test failed
   (404 or `KeyError: 'data'`) because the resolver was reading the
   (test-empty) in-memory mock store instead of the seeded `FakeDB`. In
   production the two flags are always identical (both computed from
   `SUPABASE_URL` at import time) — this was purely a test-fixture gap
   exposed by the new cross-module call, fixed by flipping both flags in the
   fixture.

   **35 new tests** across two new files
   (`test_year_end_engagements_client_scope.py`,
   `test_year_end_reviews_client_scope.py`), covering mock mode, e2e
   `FakeDB` live mode for `year_end.py`'s two DB-touching paths
   (`_assert_engagement_scope`, `list_engagements`), and the missing/hidden
   message-oracle check. **14 mutants, all killed** on the second pass — the
   first had two live-mode survivors (`list_engagements`'s
   `filter_by_client` call and `_assert_engagement_scope`'s internal
   `can_access_client` check, neither exercised because every original test
   used mock mode), closed with the e2e `FakeDB` tests above, the same
   pattern as `year_end_adjustments.py`'s own first-pass survivor. Full
   suite identical to baseline.

   **Still open, recounted the same way:** **135** id-addressed routes (down
   from 142 — 7 of `year_end`/`year_end_reviews`'s 9 routes carry an
   `{engagement_id}`; the other 2, `POST`/`GET /engagements`, have no path
   parameter at all and were never in this count to begin with). Worst
   first: `/api/year-end` (17 — the remaining siblings:
   `year_end_checklist.py`, `year_end_statements.py`, `year_end_notes.py`,
   `year_end_exports.py`, `year_end_mappings.py`; `year_end_mappings.py` is
   the one genuinely disjoint from this collision, its own `/api/year-end/
   mappings` prefix shares no segment with `engagements` or the bare
   `{engagement_id}` branch), then `/api/portal` (7), `/api/clients`,
   `/api/identity`, `/api/tally-migration`, `/api/debit-notes`,
   `/api/purchase-credit-notes`, `/api/settings` (5 each), and a long tail
   mostly in the 1-4 range.

   **`year_end_checklist.py` — the first of the five remaining siblings,
   confirmed disjoint (its own `/checklist` segment doesn't string-prefix-
   collide with any other sibling) and audited alone.** Two endpoints,
   `list_checklist` and `update_checklist_item`, both addressed by
   `engagement_id`. The live branch resolved the engagement with a
   firm-only local helper (`_fetch_engagement_db`, now removed); the MOCK
   branch didn't check the engagement at all — `_MOCK_CHECKLIST` was keyed
   purely by `engagement_id` with no tenancy check whatsoever, not even a
   firm check, the "mock branch doesn't firm-scope even though the live
   branch does" shape this sweep has watched for since the start. Fixed the
   same way as `year_end_reviews.py`: delegates to `year_end.py`'s
   `_assert_engagement_scope` by name for both branches, rather than a
   third copy of the same check.

   **A pre-existing test fixture had the identical `_USE_MOCK` cross-module
   gap already found and fixed once this phase** —
   `test_year_end_tenancy.py`'s `checklist_app` fixture flipped
   `year_end_checklist._USE_MOCK` for its e2e tests but not
   `year_end._USE_MOCK`, the flag the newly-delegated resolver now reads.
   Same cause, same fix, same file class as `test_r3_8_year_end_review_
   workflow.py`'s `yer_app` fixture from the previous phase — flipped both
   flags.

   **8 new mock-mode tests plus 3 new e2e tests, all passing on first run;
   2 mutants, both killed** (the two resolver call sites — one per
   endpoint). Full suite identical to baseline.

   **Still open, recounted the same way:** **133** id-addressed routes
   (down from 135). Worst first: `/api/year-end` (15, across
   `year_end_statements.py`, `year_end_notes.py`, `year_end_exports.py`,
   `year_end_mappings.py`), then `/api/portal` (7), and the same long tail.

   **`year_end_statements.py` — the second of the four remaining siblings,
   confirmed disjoint (its two literal segments, `/financial-statements`
   and `/schedules`, string-prefix-collide with nothing else under
   `/api/year-end`) and audited alone.** The worst of the four so far: all
   5 endpoints had no client-assignment check, and two — `list_versions`
   and `get_version` — never resolved the engagement AT ALL. Both queried
   `financial_statement_versions` directly: live mode applied only an
   inline `firm_id` filter, mock mode (`_MOCK_VERSIONS`, keyed purely by
   `engagement_id`) had no tenancy check whatsoever, not even a firm one.
   The other three (`get_financial_statements`, `create_snapshot`,
   `get_schedule`) used a `_get_engagement`/`_mock_engagement_meta` pair —
   the live half checked `firm_id` only; the mock half was weaker still,
   checking only that the mock engagement existed, not even its firm.
   Fixed the same way as the last two phases: every endpoint now delegates
   to `year_end.py`'s `_assert_engagement_scope`, deleting both local
   helpers.

   **Found and fixed while touching `get_version`, not itself an M2
   issue:** its own `.single()` call on `financial_statement_versions` had
   the same raises-on-zero-rows shape as `_get_engagement`'s — a missing
   `version_id` crashed to `500` instead of the `404` the code intended.
   Wrapped in `try`/`except` since the fix sits in the exact lines already
   being touched for the guard, the same proportionality rule applied
   throughout this sweep (fix it where you're already working; don't go
   chase it into untouched files).

   **Registered as two `AUDITED` entries, not one** —
   `/api/year-end/{engagement_id}/financial-statements` (4 routes) and
   `/api/year-end/{engagement_id}/schedules` (1 route) — since they're
   genuinely separate literal path segments even though both live in the
   same file and share one resolver.

   **17 new mock-mode tests plus 6 new e2e tests, all passing on first run;
   6 mutants, all killed** (5 resolver call sites, one per endpoint, plus
   the `.single()` try/except). Full suite identical to baseline.

   **Still open, recounted the same way:** **128** id-addressed routes
   (down from 133). Worst first: `/api/year-end` (10, across
   `year_end_notes.py`, `year_end_exports.py`, `year_end_mappings.py`),
   then `/api/portal` (7), and the same long tail.

   **`year_end_notes.py` — the third of the four remaining siblings,
   confirmed disjoint (its `/notes` segment string-prefix-collides with no
   sibling) and audited alone.** All 5 endpoints had no client-assignment
   check; three of them — `list_notes`, `get_note`, `lock_note` — never
   resolved the engagement at all, the same "worse than the others" shape
   `year_end_statements.py` had in the previous phase: live mode applied
   only an inline `firm_id` filter directly on `year_end_notes`, mock mode
   (`_MOCK_NOTES`, keyed purely by `engagement_id`) had no tenancy check
   whatsoever. The other two (`generate_notes`, `update_note`) used a
   `_mock_engagement`/`_get_engagement_db` pair — live checked `firm_id`
   only; mock checked only that the engagement existed. Fixed the same way
   as the three siblings before it: every endpoint now delegates to
   `year_end.py`'s `_assert_engagement_scope`, deleting both local helpers.
   As a simplification made possible by the single shared resolver, the
   locked-engagement check in `generate_notes` and `update_note` — previously
   duplicated once per branch — now runs once, right after the guard.

   **15 new mock-mode tests plus 4 new e2e tests, all passing on first run;
   5 mutants, all killed** (one resolver call site per endpoint). Full
   suite identical to baseline.

   **Still open, recounted the same way:** **123** id-addressed routes
   (down from 128). Worst first: `/api/year-end` (5, `year_end_exports.py`
   only — the last entangled sibling; `year_end_mappings.py`'s 4 routes
   carry no `{id}` path parameter and were never in this id-addressed
   count), then `/api/portal` (7), and the same long tail.

   **`year_end_exports.py` and `year_end_mappings.py` — the last two of the
   eight-file year-end cluster this sweep started with
   `year_end_adjustments.py`, closed together.** `year_end_exports.py` is
   the last sibling entangled by the `/{engagement_id}/...` collision
   shape; `year_end_mappings.py` is the one genuinely disjoint file (its
   own top-level `/mappings` segment, not nested under `/{engagement_id}`)
   and needed **zero code changes**.

   `year_end_exports.py` (5 endpoints) had the same shape as
   `year_end_statements.py` and `year_end_notes.py` before it: all 5 had no
   client-assignment check, and two — `list_exports`, `get_download_url` —
   never resolved the engagement at all (live mode applied only an inline
   `firm_id` filter, mock mode had no tenancy check whatsoever). The other
   three (`export_financial_statements`, `export_notes`,
   `export_complete_pack`) used a `_mock_engagement`/`_get_engagement` pair
   — live checked `firm_id` only, mock checked only that the engagement
   existed. **`get_download_url` was the sharpest finding of this whole
   cluster**: it hands back a live, signed Supabase Storage URL, valid for
   an hour, to the export PDF — a client's complete financial-statements
   pack, its Notes to Accounts, or the full year-end pack. An unassigned
   caller reaching this endpoint wasn't a metadata leak, it was a real
   exfiltration path: a working download link to another client's filed
   financial statements. Fixed the same way as the other siblings —
   delegates to `year_end.py`'s `_assert_engagement_scope` — and, while
   touching `get_download_url` for the fix, its own `.single()` call (same
   raises-on-zero-rows shape found repeatedly this sweep) was wrapped in
   `try`/`except` too.

   `year_end_mappings.py` (4 endpoints) maps a firm's Chart of Accounts to
   Schedule III statutory line items. `account_group_mappings` has
   `firm_id` and, grepped across the whole file, no `client_id` anywhere —
   a firm's mapping of its own chart of accounts is firm-wide
   configuration, applied identically across every client, the same
   reasoning already established for `task-templates`/
   `engagement-templates`/`workflow-templates`. Registered EXEMPT with that
   reason, no code touched — the same "genuinely firm-level, verified by
   reading the whole file rather than assumed" treatment `platform.py` got
   two phases ago.

   **15 new mock-mode tests plus 6 new e2e tests for `year_end_exports.py`
   (one needed a small addition to the shared e2e harness pattern: `FakeDB`
   has no `.storage` mock, so the one test exercising the signed-URL path
   monkeypatches a minimal fake), all passing on first run; 6 mutants, all
   killed** (5 resolver call sites plus the `.single()` try/except). Full
   suite identical to baseline — for `year_end_mappings.py`, trivially so,
   since nothing in it changed.

   **Still open, recounted the same way:** **118** id-addressed routes
   (down from 123 — `/api/year-end` no longer appears among unaudited
   routers at all; the entire eight-file cluster is now `AUDITED` or
   `EXEMPT`). Worst first: `/api/portal` (7), `/api/clients`,
   `/api/identity`, `/api/tally-migration`, `/api/debit-notes`,
   `/api/purchase-credit-notes`, `/api/settings` (5 each), and a long tail
   mostly in the 1-4 range.

   **`portal.py` and `portal_access.py` — the worst-first entry above,
   both staff-facing CA management surfaces sharing the literal
   `/api/portal` prefix with two CLIENT-facing files that are genuinely out
   of scope.** `/api/portal` turned out to be FOUR router files sharing one
   literal prefix, not two: `portal.py`/`portal_access.py` are CA-side
   (`rbac("portal", ...)`, this sweep's usual model); `portal_self.py`/
   `portal_data.py` (the `/self/*`, `/me`, `/dashboard`, `/memberships`,
   `/accept-invite` routes) serve the **client's own** portal login via
   `get_current_portal_client`/`get_jwt_user` — a structurally different
   authorization model where a portal contact is bound to exactly one
   client_id at the identity layer, not scoped by a firm-staff assignment
   table. Left untouched this phase; not the same bug class this sweep
   exists for. The two staff-facing files were confirmed disjoint from
   each other and from the client-facing pair by literal path segment —
   `document-requests`/`messages`/`dues` (`portal.py`) vs `clients`/
   `contacts` (`portal_access.py`) vs `self`/`me`/`dashboard`/
   `memberships`/`accept-invite` (the client-facing pair) — so registered
   and fixed without touching the other two.

   `portal.py` (6 endpoints): `list_document_requests`,
   `create_document_request`, `list_messages`, `send_message` and
   `get_dues` all took `client_id` from the query or body and never
   checked it. `complete_document_request` is row-addressed by
   `request_id` and checked only `firm_id`. This endpoint already had an
   unusual, deliberate convention worth preserving rather than replacing:
   a refusal is a `200` with `{success: false, error: "Document request
   not found"}`, not a raised `HTTPException` — and the missing-row and
   wrong-firm cases already used byte-identical text. The new
   `_assert_doc_request_scope` resolver (added to `domain/portal_service.
   py` as a new non-mutating `get_document_request` lookup for the mock
   side) extends that exact convention to the client-assignment case
   rather than switching the endpoint to a different refusal shape.

   `portal_access.py` (4 endpoints): `list_portal_contacts` and
   `invite_portal_contact` are addressed directly by `client_id` and used
   a bespoke `_assert_client_in_firm` helper — a hand-rolled duplicate of
   half of `core.authz.assert_client_access` (the firm-boundary half only,
   never the assignment half) — now deleted and replaced with the real
   thing. `resend_portal_invite` and `deactivate_portal_contact` are
   row-addressed by `contact_id` and had no client check at all: the
   service layer's `get_contact()` filters by `firm_id` only. A new
   `_assert_contact_scope` resolver closes both, reusing `get_contact`'s
   own refusal text ("Portal contact not found.") so the message stays
   identical between the missing-row and hidden-row cases — the service's
   own subsequent 404 on the same text means there's no way for the two
   call sites to drift apart.

   **22 new tests, all passing on first run; 12 mutants, all killed** (6
   guard call sites in `portal.py`, one internal resolver check, 4 guard
   call sites in `portal_access.py`, one internal resolver check). Full
   suite identical to baseline.

   **Still open, recounted the same way:** **113** id-addressed routes
   (down from 118 — `/api/portal/clients/{client_id}/contacts` (2 routes)
   and the two `/api/portal/contacts/{contact_id}/...` routes plus
   `complete_document_request` account for the 5-route drop; the other
   `/api/portal` routes never carried a path parameter and were never in
   this count). Worst first: `/api/clients`, `/api/identity`,
   `/api/tally-migration`, `/api/debit-notes`, `/api/purchase-credit-notes`,
   `/api/settings` (5 each), and a long tail mostly in the 1-4 range.

   **Also fixed 2026-08-09 — `clients.py`, the root Client resource.**
   `get_client_workspace`, `update_client`, `archive_client` and
   `restore_client` all checked only `_assert_firm(client, firm_id)` — the
   firm boundary, not assignment. `PERMISSIONS["client"]` gates read at
   `_ALL_STAFF` and write at `_AT_LEAST_MANAGER`, so any Executive or
   Reviewer in the firm could pull the FULL workspace (compliance tasks,
   documents, AI insights, activity log) of any client in the firm, and
   any Manager could edit, archive or restore any client in the firm —
   not just their assigned book. Architecturally the sharpest finding of
   this cluster of phases: `clients.py` is the most central resource in
   the app, and every one of its four non-delete write/read endpoints was
   open. `delete_client` is gated `_PARTNER_ONLY`, the sole firm-wide
   role, so by RBAC construction the caller can never actually be denied
   there — it goes through the identical guard anyway for consistency
   rather than being carved out as a special case.

   `_assert_firm` now takes `current_user` instead of a bare `firm_id`,
   keeps the existing firm-mismatch raise, and adds
   `if not can_access_client(current_user, client.get("id")): raise
   HTTPException(404, "Client not found")` — the SAME text as the
   firm-mismatch branch, so a caller cannot use the message to tell
   "wrong firm" apart from "right firm, not your client" (message-oracle).
   `list_clients` already filtered correctly via `effective_client_ids`
   (pre-existing, marked `# M2: assignment scope` in the code) and needed
   no change; `create_client` has no existing client to scope against.

   GET and POST share the bare `/api/clients` path, and `EXEMPT` is keyed
   by path only — so that one path is EXEMPT with the reasoning written
   out (`create_client` has nothing to check; `list_clients`'s real
   `effective_client_ids` filtering just isn't visible to the path-level
   static check because POST shares the path). The row-addressed siblings
   (`{client_id}`, `{client_id}/archive`, `{client_id}/restore`) are NOT
   exempt — they're covered by `_assert_firm` in the `AUDITED` tuple like
   every other phase.

   **12 new tests, all passing on first run** (workspace/update/archive/
   restore/delete × hidden+allowed, one hidden-vs-missing message-oracle
   check, one cross-firm-short-circuits-before-assignment-check
   regression guard). **6 mutants, all killed** (the internal
   `can_access_client` check plus all 5 `_assert_firm` call sites). Full
   suite identical to the 44-failure baseline (`git stash -u` diff, byte
   for byte).

   **Still open, recounted the same way:** **108** id-addressed routes
   (down from 113 — `/api/clients/{client_id}` (GET/PATCH/DELETE, 3
   routes) plus `/archive` and `/restore` (1 each) account for the
   5-route drop). Worst first: `/api/credit-notes`, `/api/debit-notes`,
   `/api/purchase-credit-notes`, `/api/sales-debit-notes` (3 each),
   `/api/dsc`, `/api/firm-hsn-library`, `/api/service-catalogue`,
   `/api/settings/email-templates`, `/api/settings/invoice-templates`,
   `/api/time-entries` (2 each), and a long tail of 1-route paths
   (`/api/accounting`, `/api/approvals`, `/api/identity`,
   `/api/tally-migration`, `/api/xbrl`, `/api/fixed-assets`,
   `/api/receipts`, `/api/purchase-payments`, `/api/einvoice`,
   `/api/eway-bill`, `/api/form-26as`, and more — 94 unique paths, 108
   routes total).

   **Also fixed 2026-08-09 — the four GST note-type routers:
   `credit_notes.py`, `debit_notes.py`, `purchase_credit_notes.py`,
   `sales_debit_notes.py`.** None of the four imported `core.authz` at
   all — the exact same shape `sales_invoices.py`/`purchase_bills.py` had
   before their own fix earlier in this sweep. `list_*`/`create_*` took
   `client_id` from the query/body and never checked it; `get_*`/
   `update_*`/`issue_*`/`delete_*` (and `debit_notes.py`'s/
   `purchase_credit_notes.py`'s `upload`/`document-url` pair, which mints
   a live signed Storage URL to the note's attachment) are row-addressed
   and checked only `firm_id` — so any Executive/Reviewer/Manager in the
   firm could read, edit, issue or delete another staff member's assigned
   client's GST notes, not just their own book.

   Each router gets its own `_assert_*_scope(current_user, id) ->
   client_id` resolver — but rather than copying `sales_invoices.py`'s
   `_assert_invoice_scope` shape verbatim (permissive on a missing row in
   mock mode, and `assert_client_access`'s generic "Not found" for the
   denied branch vs. the handler's own id-embedded "X not found" for a
   genuinely missing row — two different message templates, a live
   message-oracle gap in that earlier fix this discovery surfaced), all
   four instead follow `year_end.py`'s more rigorous
   `_assert_engagement_scope` shape: `can_access_client` (not
   `assert_client_access`) with **one fixed, non-id-embedding message**
   covering every failure branch — missing, wrong firm, and right firm
   but unassigned all read identically — enforced in **both** mock and
   live mode, not just live. `sales_invoices.py`/`purchase_bills.py`'s
   older, looser shape is a real residual gap (status code still matches,
   only the message text differs) — left as-is for now since it's a
   message-level leak, not an M2 bypass, and out of scope for a
   worst-first pass; recorded here rather than silently carried forward.

   **59 new tests, all passing on first run** (deny/allow pairs for every
   endpoint across all four routers, four hidden-vs-missing message-oracle
   checks using the SAME id across both scenarios — the only valid way to
   test message parity once the message is id-parameterized — plus e2e
   `FakeDB` tests exercising each resolver's own SQL lookup with
   `can_access_client` still stubbed, mirroring
   `test_year_end_engagements_client_scope.py`'s e2e split). **32
   mutants, all killed** (the internal `can_access_client` check plus
   every guard call site, across all four routers). Full suite identical
   to the 44-failure baseline (`git stash -u` diff, byte for byte).

   **Still open, recounted the same way:** **90** id-addressed routes
   (down from 108 — 18 row-addressed routes across the four routers:
   4 on `/api/credit-notes` (get/update/issue/delete), 5 each on
   `/api/debit-notes` and `/api/purchase-credit-notes` (get/update/
   document-url/issue/delete), 4 on `/api/sales-debit-notes`). Worst
   first: `/api/dsc`, `/api/firm-hsn-library`, `/api/service-catalogue`,
   `/api/settings/email-templates`, `/api/settings/invoice-templates`,
   `/api/time-entries` (2 each), and a long tail of 1-route paths —
   `/api/accounting`, `/api/approvals`, `/api/identity`,
   `/api/tally-migration`, `/api/xbrl`, `/api/fixed-assets`,
   `/api/receipts`, `/api/purchase-payments`, `/api/einvoice`,
   `/api/eway-bill`, `/api/form-26as`, `/api/document-intelligence-v2`,
   and more (84 unique paths, 90 routes total).

   **Also fixed 2026-08-09 — the six worst-first routers from above:
   `dsc.py`, `firm_hsn_library.py`, `service_catalogue.py`, `branding.py`
   (`/api/settings/email-templates` + `/api/settings/invoice-templates`),
   `time_tracking.py`.** Three of the six turned out to be genuine EXEMPT
   findings, not gaps: `dsc_records` has a `firm_id` and NO `client_id`
   column at all (migration 014) — a Digital Signature Certificate belongs
   to the firm, not any client's book; `firm_hsn_library` likewise has no
   `client_id` (migration 179), firm-wide by design per its own module
   docstring ("shared across all of the firm's clients, even though the
   Product/Service referencing a code is client-owned"); `branding.py`
   (grepped the whole file) has no `client_id` anywhere — firm-level
   logo/invoice-numbering/template configuration, the same reasoning as
   task/engagement/workflow templates and year-end mappings, all already
   exempt. All three are registered in `AUDITED` with an empty check-tuple
   (the `/api/platform` pattern) plus a per-path `EXEMPT` entry and reason
   for every one of their routes, rather than left out of the sweep
   entirely — the claim "looked at, found no client to scope to" now holds
   and ratchets forward.

   `service_catalogue.py` was a real gap: CLIENT-owned by design (migration
   182 — "Client B must never inherit Client A's products") but the router
   never imported `core.authz` at all. `list_services`/`create_service`
   take `client_id` directly (query/body) and now call
   `assert_client_access`, the `sales_invoices.py` list/create shape.
   `bulk_create_services` checks every DISTINCT `client_id` in the batch up
   front via a new `_assert_batch_scope`, before any row is processed —
   same convention as `sales_invoices.py`'s own `_assert_batch_scope`, so a
   mixed batch with one foreign client_id among many of the caller's own
   fails the whole batch rather than silently landing the rows before the
   refusal. `update_service`/`delete_service`/`record_service_used` are
   row-addressed and previously checked only `firm_id`; a new
   `_assert_service_scope` resolver (`can_access_client`, not
   `assert_client_access`) raises the SAME "Service not found." text every
   one of these handlers already used for its own missing-row branch, so
   the fix introduces no second wording for the same condition (the
   message-oracle property established earlier in this sweep, for free
   here since the text pre-existed).

   `time_tracking.py`: `stop_timer`/`update_entry`/`delete_entry` are
   row-addressed and checked only `firm_id` (`list_entries` right above
   them already used `filter_by_client` — M2/M5, untouched); a new
   `_assert_entry_scope` resolver covers all three, raising the
   pre-existing "Time entry not found" text for both the missing-row and
   hidden-client branches. `create_manual_entry`/`start_timer` take an
   optional `client_id` and never checked it; `assert_client_access` is a
   no-op for `client_id=None` (internal/admin time entries carry none), so
   the fix does not regress that case. **Found beyond this router's
   original 2-route count in the worst-first list:** `export_entries` (GET
   `/export`) had NO assignment filtering at all — unlike `list_entries`
   immediately above it — so an Executive/Reviewer/Manager could export
   another staff member's unassigned client's billing data, or the whole
   firm's, via the `client_id` filter or by omitting it entirely. Fixed by
   threading `effective_client_ids` through to
   `time_export_service.export_time_entries`, which now drops any entry
   whose `client_id` falls outside it (a client-less entry is always kept)
   — the same filtering `list_entries` already applied, moved to the export
   layer. Two endpoints are EXEMPT, not gaps: `GET /summary/me` and `GET
   /running/me` are addressed by the caller's OWN `user_id`, not a client —
   they aggregate only time the caller logged themselves, never another
   staff member's assigned book, so there is no other caller's data for an
   assignment check to gate.

   **33 new tests, all passing on first run** (mock-mode deny/allow pairs
   for every real endpoint across both routers, hidden-vs-missing
   message-oracle checks using the SAME id across both scenarios, e2e
   `FakeDB` tests for `service_catalogue.py`'s resolver's own SQL branch,
   and dedicated coverage for `time_tracking.py`'s three new shapes: a
   client-less entry is never refused, the export's DB-level filtering
   drops out-of-scope rows while keeping client-less ones, and the export
   router-to-service wiring actually passes `effective_client_ids`
   through). **16 mutants, all killed** (every new `assert_client_access`/
   `can_access_client`/`_assert_service_scope`/`_assert_batch_scope`/
   `_assert_entry_scope` call site, plus the export filter itself, across
   both routers and the export service). Full suite identical to the
   44-failure baseline (`git stash -u` diff, byte for byte).

   **Still open, recounted the same way:** **73** id-addressed routes
   (down from 90 — the five routers above account for the 17-route drop:
   3 each on `/api/dsc` (get covers PATCH/DELETE `{dsc_id}` + POST
   `{dsc_id}/renew`), `/api/firm-hsn-library` (PATCH/DELETE `{library_id}`
   + DELETE `{library_id}/purge`), `/api/service-catalogue` (PATCH/DELETE
   `{service_id}` + POST `{service_id}/used`) and `/api/time-entries`
   (PATCH/DELETE `{entry_id}` + POST `{entry_id}/stop`), plus 5 on
   `/api/settings` (PATCH/DELETE on both `email-templates/{template_id}`
   and `invoice-templates/{template_id}`, plus the `set-default`
   sub-route) — all now either genuinely guarded or EXEMPT with a written
   reason rather than silently dropped). Worst first:
   `/api/identity`, `/api/tally-migration` (5 each), `/api/accounting`,
   `/api/approvals`, `/api/xbrl` (4 each), then a cluster of nine at 3
   each (`/api/ai-insights`, `/api/eway-bill`, `/api/inventory`,
   `/api/receipts`, `/api/compliance`, `/api/purchase-payments`,
   `/api/document-intelligence-v2`, `/api/payments`, `/api/public`), and a
   long tail mostly in the 1-2 range (30 unique top-level path groups, 73
   routes total).

   **Also fixed 2026-08-09 — the next worst-first pair: `identity.py`,
   `tally_migration.py`.** `identity.py` turned out EXEMPT, not a gap:
   `users` and `login_events` both have a `firm_id` and NO `client_id`
   column at all (migrations 003/085) — every one of its 11 routes manages
   STAFF accounts (invite, activate, suspend, role change, force-logout,
   login history), not client data. Registered `AUDITED` with an empty
   check-tuple plus a per-path `EXEMPT` entry and reason for all 10 unique
   paths, the same treatment as `dsc.py`/`firm_hsn_library.py`/
   `branding.py` last phase.

   `tally_migration.py` was a real gap, and a sharper one than most of this
   sweep: `tally_migration_jobs.client_id` is genuinely OPTIONAL (ledgers/
   journals can be a firm-level migration; customers/vendors need a target
   client — `domain/tally/migration_service.py`'s `_import_single_item`).
   `create_job` already checked a supplied `client_id` belonged to the
   caller's FIRM via a bespoke inline query — but never checked
   ASSIGNMENT, the familiar firm-boundary-only gap; replaced with
   `assert_client_access`, which checks both and deletes the bespoke query
   entirely. `list_jobs` returned EVERY job in the firm, completely
   unfiltered — an Executive/Reviewer/Manager could see which OTHER
   clients had a Tally migration in progress (file names, status) outside
   their own book; now narrowed with `filter_by_client`. `get_job`/
   `parse_xml`/`preview_import`/`execute_import`/`rollback_import` are all
   row-addressed by `job_id` and previously resolved the job by `firm_id`
   alone — meaning an unassigned caller could not just READ another
   client's migration, but actually **execute** it: `execute_import` with
   `is_dry_run=false` writes real `customers`/`vendors` rows into the
   target client's books via `_import_single_item`, and `rollback_import`
   deletes them again. A new `_assert_job_scope` resolver
   (`can_access_client`, ONE fixed `"Migration job not found"` message
   covering missing/wrong-firm/right-firm-but-unassigned alike) now guards
   all five — closing, as a side effect, a pre-existing message-oracle
   inconsistency where `get_job` said `"Migration job not found"` but
   `parse_xml` said `"Job not found"` for the identical condition.
   `can_access_client(user, None)` is always True throughout, so firm-level
   (client-less) jobs are unaffected by any of this.

   **36 new tests, all passing on first run** (mock-mode deny/allow pairs
   for every real endpoint, a firm-level-job-is-never-refused case, the
   `list_jobs` filtering, and a hidden-vs-missing message-oracle check
   using the SAME id across both scenarios). **8 mutants, all killed**
   (every new `assert_client_access`/`can_access_client`/
   `filter_by_client`/`_assert_job_scope` call site). Full suite identical
   to the 44-failure baseline (`git stash -u` diff, byte for byte).

   **Still open, recounted the same way:** **63** id-addressed routes
   (down from 73 — 5 each on `/api/identity` and `/api/tally-migration`
   account for the 10-route drop). Worst first: `/api/accounting`,
   `/api/approvals`, `/api/xbrl` (4 each), then a cluster of nine at 3
   each (`/api/ai-insights`, `/api/eway-bill`, `/api/inventory`,
   `/api/receipts`, `/api/compliance`, `/api/purchase-payments`,
   `/api/document-intelligence-v2`, `/api/payments`, `/api/public`), and a
   long tail mostly in the 1-2 range (28 unique top-level path groups, 63
   routes total).
11. **Tier 4.1 (Account Aggregator) needs a product decision before any engineering** —
   partner selection and compliance review gate the work.

---

## Appendix — file map

```
apps/api/domain/banking/
  normalizer.py      statement parsing, bank adapters        393 lines
  matcher.py         suggestion ranking (exact-amount gate)  103
  rules.py           rule evaluation engine                   45
  posting_map.py     category → journal mapping               82
  reconciliation.py  tie-out arithmetic                       61
  dedup.py           transaction + file hashing               45
  categories.py      controlled vocabulary (11 values)        27

apps/api/services/
  banking_service.py             import, accounts, ignore   360
  bank_matching_service.py       queue, categorize, match   363
  bank_posting_service.py        preview, post, settle      554
  bank_reconciliation_service.py sessions, tie-out, report  396

apps/api/routers/banking.py      33 endpoints               687

apps/web/app/clients/[id]/bank/page.tsx                    1764
apps/web/lib/api/index.ts:222-267   banking API client (no `rules`)

DB: bank_accounts, bank_statements, bank_transactions,
    bank_matching_rules, bank_reconciliations, bank_reconciliation_matches
```
