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
| 1.3 | **Payee on `bank_transactions`** + customer/vendor lookup + auto-fill from history | **M** | Unlocks 1.4 and much better matching. |
| 1.4 | **Learn-from-history suggestions** — "last time this narration was coded to X" | **M** | Depends on 1.3. Cheap once payee + history exist. |
| 1.5 | **Transfer auto-detection** — pair opposite-sign, same-amount lines within N days across two of the client's own accounts | **M** | Prevents double-counted cash. Pure logic over data we already store. |
| 1.6 | **"Find other matches"** — searchable candidate picker with date/amount/party filters, not a fixed top-5 | **M** | |
| 1.7 | **Batch accept / batch exclude** alongside the existing bulk categorize | **S** | |
| 1.8 | **Attachments on bank transactions** | **S** | Storage + RLS already exist for documents. |

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
7. **Then the rest of Tier 1.** 1.3 (payee) and 1.4 (learn-from-history) are a pair —
   1.4 is cheap only once payee and history exist. 1.7 and 1.8 are both **S** and
   independent of everything else.

   **Known follow-up from 1.2:** a split and a GST rate cannot currently be combined —
   both decide the non-bank legs, and doing them together needs a rate *per split*. The
   combination is refused with a clear message rather than silently applying one and
   dropping the other. Worth doing when a real case turns up; the pieces
   (`charge_gst.split_inclusive_charge`, `splits.build_split_lines`) already compose.
8. **Tier 4.1 (Account Aggregator) needs a product decision before any engineering** —
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
