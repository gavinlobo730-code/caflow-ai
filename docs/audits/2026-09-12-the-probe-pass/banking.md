Read `CLAUDE.md`, the findings JSON, and probed each against current code. All fifteen are **open** — none stale. Several premises have holes.

---

**BANK-03 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/services/bank_posting_service.py:563` — `journal_entry_id = phase2_journal_service._create_journal(` … :566-569 pass `entry_type`, `lines`, `source_type="bank_transaction"` and no `txn_currency`/`exchange_rate`. `/home/user/caflow-ai/apps/api/services/banking_service.py:143` — `"reference_no": t.reference_no, "debit_paise": t.debit_paise,` — the row dict `import_normalized` builds carries no currency. `/home/user/caflow-ai/apps/api/routers/banking.py:483` — `_guard_foreign_bank_currency(db, firm_id, payload.get("client_id"), cur)` fires only in `create_bank_account`; `upload_statement` (:813-826) never reads the account's currency.
PREMISE: sound — with one correction. The finding says the post path has *no* currency plumbing anywhere. `match_and_settle_multi` does (bank_posting_service.py:933 `currency: Optional[str] = None, exchange_rate=None` → :1033-1036 / :1047-1050 pass them to `create_receipt_core`/`create_payment_core`). So the **multi-allocation** bank path is FX-capable already; the ordinary `post()`/`_plan()` path and the import are not. That matters for the fix: option (b) is not greenfield, it is making `post()` catch up with a sibling that already does it.
SHAPE: option (a) — one guard in `upload_statement`/`import_statement` reading `bank_accounts.currency`; no migration. Option (b) — `services/banking_service.py` (carry currency onto rows), `models/banking.py` (rate per statement/line), `services/bank_posting_service.py::_plan`/`post`, `routers/banking.py`; needs a migration if the rate is stored per statement line, and a decision on where the FX gain/loss leg lands so the journal still balances (`_plan` returns `lines` that `_create_journal` asserts balanced — an unbalanced FX leg is exactly the invariant that breaks).
SIZE: (a) hours. (b) multi-day.

---

**BANK-10 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/services/bank_matching_service.py:305` — `rows = (self._banded(q, "total_paise", bands, "invoice")`; :319 — `if not self._in_band(int(r.get("total_paise") or 0), amount):`; :334 — `amount_paise=total, entity_date=...`; :336 — `outstanding_paise=total - paid,`. `/home/user/caflow-ai/apps/api/domain/banking/matcher.py:176` — `difference = int(c.amount_paise) - int(txn_amount_paise)`; :46 `NEAR_MATCH_BAND_BPS = 2500`.
PREMISE: sound for invoices, and the bill side is **worse than described**. The finding says bills "do the same on `net_payable_paise`". They do — but `net_payable_paise` is total-minus-TDS, not total-minus-paid, and `_fetch_bill_pool` (:352) never even selects `paid_paise`, so bank_matching_service.py:385 sets `outstanding_paise=net_payable` — a bill 90% paid reports its full net payable as outstanding, and the `+15` "matches outstanding balance" bonus at matcher.py:215-216 can fire on a figure that is not outstanding. `_bills_from` (:373) also only skips `cancelled/paid/draft`, so `partially_paid` bills carry a wrong outstanding into scoring.
SHAPE: the finding's fix hides a cost it does not mention. `_banded` (:220-231) builds a **PostgREST filter on one named column** — `q.gte(col, lo).lte(col, hi)` / `or(and(col.gte…))`. "Outstanding" is not a column on either table, so you cannot band on it in SQL. Either add a generated/stored `outstanding_paise` (migration on `client_sales_invoices` and `purchase_bills`, kept in step with every settlement writer) or widen the SQL band to `total_paise` and filter to outstanding in Python — which breaks `_pool_limit`/`_warn_if_truncated` (:234-246), because the cap is applied by the DB before your Python filter runs. Files: `services/bank_matching_service.py`, `domain/banking/matcher.py`, `domain/banking/candidate_search.py`, plus every label that currently prints the total.
SIZE: day (Python-side filter) to multi-day (with the derived column + migration).

---

**BANK-11 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/domain/banking/rules.py:57` — `if pattern and pattern not in (narration or "").lower():` — that plus amount min/max (:59-63) and `txn_type` (:64-68) is the entire engine. `/home/user/caflow-ai/apps/api/routers/banking.py:2359` — `.order("created_at").execute())`; `services/bank_entry_service.py:396` orders the same way. `grep priority migrations/*.sql | grep bank_matching_rules` → no hits.
PREMISE: sound.
SHAPE: step 1 (priority) — one migration adding `priority INT`, two `.order()` changes (`routers/banking.py:2359`, `services/bank_entry_service.py:396`), the create/update models, and `RulesTab.tsx`. Steps 2 and 3 are new schema (a conditions child table or JSONB, and split legs) plus `domain/banking/rules.py`, `domain/banking/entry_state.py::from_rule`, and the trusted-rule CHECK from migration 322 — which is the invariant to watch: a *trusted* rule auto-posts (bank_entry_service.py:576 stamps `posted_by_rule_id`), so widening what a rule may propose widens what posts unattended.
SIZE: priority alone, hours. Full finding, multi-day.

---

**BANK-12 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/routers/banking.py:2456` — `current_user: dict = Depends(rbac("banking", "write")),`; :2458-2460 the docstring still claims "it has never written anything to the ledger"; :2466-2467 — `(db.table("bank_matching_rules").delete().eq("id", rule_id)...` with no `posted_by_rule_id` check and no `log_event`.
PREMISE: sound. `posted_by_rule_id` exists (`migrations/322_bank_entries_drafts_state_and_trusted_rules.sql:62`, `ON DELETE SET NULL`) and is stamped at `services/bank_entry_service.py:576`.
SHAPE: `routers/banking.py::delete_rule` only — one count query against `bank_transactions.posted_by_rule_id` (the partial index at migration 322:245 already exists), an rbac bump to `banking.approve` for trusted/ever-trusted rules, and an `audit_service.log_event` call. No migration.
SIZE: hours.

---

**BANK-13 — VERDICT: open**
EVIDENCE: `ls apps/api/services/ | grep exception` → `gst_exception_service.py` only. Repo-wide grep for `bank_exception|banking.exceptions` returns two hits: `/home/user/caflow-ai/apps/api/domain/banking/exceptions.py:22` (its own docstring naming the missing service) and `tests/test_bank_exception_rules.py:15`. `needs_review` is written only False: `services/bank_matching_service.py:816` `"match_status": "matched", "needs_review": False,`, `services/bank_posting_service.py:1067` `"needs_review": False,` (and `bank_entry_service.py:608` restores the prior value on undo). Yet `services/bank_register_service.py:150` — `if status == "needs_review" and not raw.get("needs_review"):` and `/home/user/caflow-ai/apps/web/components/banking/BankBook.tsx:83` — `{ id: "needs_review", label: "Needs review" },`.
PREMISE: sound, verbatim.
SHAPE: new `services/bank_exception_service.py` gathering payee/account/duplicate context, wiring into `redraft` or a per-page compute, plus a UI surface. No migration if computed per page; a migration if flags are stored. The cheap honest half — delete the option from `BankBook.tsx:83`, the `STATUS_FILTERS` tuple at `bank_register_service.py:60`, the filter at :150 and the route regex at `routers/banking.py:1346` — is an afternoon. Note `bank_matching_service.py:508-509` exposes the same dead filter on the Entries list.
SIZE: honest removal, hours. Real wiring, multi-day.

---

**BANK-14 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/domain/banking/normalizer.py:855` — `if rows:` / :856 `return rows` — sits *outside* the `for page in pdf.pages` loop, so any single ruled page short-circuits the whole document. :858-860 — `# No ruled table anywhere in the document — fall back to geometry.` then a second full-document loop. `_rows_by_position` at :923-925 — `header = next((ln for ln in lines if _looks_like_header(...)), None)` / `if header is None: return []`.
PREMISE: sound.
SHAPE: entirely inside `_pdf_rows` and `_rows_by_position` in `domain/banking/normalizer.py`. No migration. The invariant that has to survive: `domain/banking/tie_out.py` is the backstop and the tie-out currently *passes* on a truncated read only when the statement prints no totals — do not let a per-page merge change the row order feeding `_opening_closing_balance` (`services/banking_service.py`) or `balance_agreement`, or a correct parse starts failing its own arithmetic check. Carrying page-1's header forward also means the geometric column bounds from page 1 must be reused, not re-derived — that is the part that is not a one-liner.
SIZE: day.

---

**BANK-15 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/services/bank_transfer_service.py:29` — `SCAN_LIMIT = 1000`; :56-58 — `.order("transaction_date", desc=True)` / `.limit(SCAN_LIMIT).execute().data) or []`. `/home/user/caflow-ai/apps/api/services/bank_entry_service.py:402` — `pairs = self._pairs_by_txn(db, firm_id, client_id)` sits inside `redraft` (:376, `limit: int = REDRAFT_CHUNK`, :48 `REDRAFT_CHUNK = 100`), and `redraft` is driven in a chunk loop from `routers/banking.py:1056`, `routers/banking.py:1917` and `jobs/bank_trusted_rules_job.py:68`.
PREMISE: sound. `detect_pairs` already takes `txns: Optional[list[dict]] = None` (:49-51), so the pass-through the fix wants is genuinely already there.
SHAPE: `services/bank_entry_service.py` (hoist the index above the chunk loop — but the loop is in the *callers*, so either `redraft` grows a `pairs=` parameter and all three callers pass it, or the job owns the index) and `services/bank_transfer_service.py` (date window instead of the flat cap). No migration. Watch: `_pairs_by_txn` swallows all exceptions (:451-454) and returns `{}` — hoisting it means one failure now costs every chunk its transfer proposals instead of one.
SIZE: day.

---

**BANK-17 — VERDICT: open**
EVIDENCE: `grep -n reconciliation_id services/bank_posting_service.py services/bank_matching_service.py services/bank_entry_service.py` → **zero hits**. `/home/user/caflow-ai/apps/api/services/bank_posting_service.py:739-741` — the guards `undo` actually applies are `if txn.get("match_status") != "posted" or not journal_id:` and, at :750, `if je and je.get("source_type") not in (None, "bank_transaction"):`, plus the period check further down.
PREMISE: sound.
SHAPE: `services/bank_posting_service.py::undo` and `services/bank_matching_service.py::unmatch` (:840) — one read of `bank_transactions.reconciliation_id` joined to `bank_reconciliations.status`. No migration (column exists, `migrations/102_bank_reconciliation_b4.sql:28`). The invariant: if you take the "clear `reconciliation_id`" branch instead of refusing, the completed session's frozen snapshot (`bank_reconciliation_service.py:407-413`) no longer ties to the register's cleared set — pick refusal, or clear it *and* record the divergence, not silently.
SIZE: hours.

---

**BANK-21 — VERDICT: open, but the premise is half wrong**
EVIDENCE: `/home/user/caflow-ai/apps/api/migrations/054_v13_payroll_assets_banking.sql:101` — `CHECK (account_type IN ('Current', 'Savings', 'Cash Credit', 'Overdraft')),` and `/home/user/caflow-ai/apps/web/components/banking/AccountsPanel.tsx:481` — `{["Current","Savings","Cash Credit","Overdraft"].map((t) => <option key={t}>{t}</option>)}`.
PREMISE: FALSE in two of its three claims.
 (1) "The ledger creation path would in any case give a card an Asset ledger" — no longer true. `routers/banking.py:244-251`: `_OVERDRAWN_BANK_TYPES = frozenset({"Cash Credit", "Overdraft"})` / `def ledger_shape_for_bank(account_type)` returns `_OD_LEDGER` = `("Liability", "Bank Overdraft")`. Migration 342 built this. Adding `'Credit Card'` to that frozenset *is* the whole ledger side of the fix, and BANK-02 is already done.
 (2) "the posting map treats every statement line as money in or out of a bank asset" — also false. `domain/banking/posting_map.py:43-78` `build_lines` is purely directional: `if is_credit: [Dr bank, Cr counter] else [Dr counter, Cr bank]`. Against a liability ledger that already produces the right sign — a card spend (debit column) credits the card, a card payment debits it. No posting-map change is needed.
 What *is* true and unfixed: the CHECK, the picker, and the subtype. `'Bank Overdraft'` was chosen because `schedule_iii.bs_bucket()` substring-scans for the literal "overdraft" — a card mapped to that subtype would report under "loans repayable on demand from banks", which is wrong for a card. That is the real work the finding never names.
SHAPE: migration (CHECK on `bank_accounts.account_type` — and note migration 093 restates it, so both), `AccountsPanel.tsx:481`, `routers/banking.py:244` plus a subtype decision, and `domain/reporting/schedule_iii.py` so the card lands in trade payables / other current liabilities rather than short-term borrowings. Migration required.
SIZE: day.

---

**BANK-22 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/models/banking.py:105` — `bank_account_id: Optional[str] = None` on `StatementImportIn`; `/home/user/caflow-ai/apps/api/routers/banking.py:818` — `bank_account_id: Optional[str] = Form(None),`. `/home/user/caflow-ai/apps/api/services/bank_posting_service.py:107-109` — `return resolve_payment_account(db, firm_id=firm_id, client_id=txn["client_id"], find_account=phase2_journal_service._find_account).account_id`. No `bank_account_id` column on `bank_transactions`: `migrations/006_transactions_bank_compliance.sql:90-108` defines the table without it and nothing adds it (`grep 'ADD COLUMN.*bank_account_id' migrations/*.sql` hits `bank_accounts`-linked tables only).
PREMISE: sound, plus one thing the finding missed that argues the same way. `migrations/055_v131_hardening.sql:79` and `:100` create indexes `ON bank_transactions (client_id, bank_account_id, txn_date, ...)` — columns that **do not exist on that table** (`transaction_date`, not `txn_date`). Those two statements cannot have run against the live schema; either 055 was partially applied or those indexes silently do not exist. Worth confirming against the real DB before quoting index coverage anywhere.
SHAPE: making the field required is `models/banking.py`, `routers/banking.py` (two entry points) and `apps/web` callers — ownership validation already exists at `banking_service.py:176-181`. Making `_resolve_bank` refuse is one branch, but it changes behaviour for **already-imported** statements with a null `bank_account_id`, which will start 422-ing at post time; needs a backfill decision. Denormalising the column is a migration plus a backfill plus four read paths (`bank_entry_service.py:92`, `bank_transfer_service.py:41`, `bank_register_service.py:76`, `bank_reconciliation_service.py:55`).
SIZE: day for the guard; multi-day with the denormalisation and backfill.

---

**BANK-24 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/services/bank_posting_service.py:275-278` — `return build_inclusive_lines(split, bank_account_id=bank_id, counter_account_id=counter_id, is_credit=is_credit, cgst_account_id=cgst_id, ...)` — account ids and amounts only. Grep for `gstin|supplier|purchase_register` across `domain/banking/charge_gst.py` and `services/bank_posting_service.py` returns one hit, a prose comment at `charge_gst.py:26`.
PREMISE: sound, with one thing now different: `_charge_lines` has grown an **output-tax** branch (`:263-265`, `_gst_output_account` when `is_credit`), so a bank *credit* with a rate books output GST — that leg has the same missing-counterparty problem in the other direction, and any fix has to cover both or it will look like it worked while half of it did not.
SHAPE: this is the largest of the fifteen. Storing the bank's GSTIN/state means a migration on `bank_accounts` (or `bank_matching_rules`), stamping it onto the journal means a place to put it (`journal_entries` has `source_type`/`source_id`, not a party), and getting it into 2A/2B reconciliation means writing a purchase-register row from the bank path — which then has to *not* double-count: `services/itc_register_service.py` computes ITC from journal lines against GST Input, so if a new purchase-register row also carries the credit, the 3B figure foots twice. That coupling is the invariant the finding does not mention. The "at minimum, tag these journals" fallback avoids all of it.
SIZE: tagging only, day. Full 2B reconciliation, multi-day.

---

**BANK-25 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/services/banking_service.py:226` — `"row_count": len(new_rows), "import_status": "pending",`. Repo-wide grep for `import_status` across `apps/api` + `apps/web` returns exactly four hits: that line, the CHECK at `migrations/006_transactions_bank_compliance.sql:81`, one test fixture, and `/home/user/caflow-ai/apps/web/components/banking/AccountsPanel.tsx:282` rendering the chip against `STATUS_COLORS` (:161-165, `pending: "bg-amber-100 text-amber-700"`). Nothing writes it a second time.
PREMISE: sound, verbatim.
SHAPE: either a count-driven update in `services/banking_service.py` / `bank_entry_service.py` at state transitions (no migration — the CHECK already allows `reviewed`/`posted`), or drop the chip in `AccountsPanel.tsx` and compute "N of M passed" from the entry-state counts the Entries tab already fetches. The second is cheaper and is what the finding argues for.
SIZE: hours.

---

**BANK-26 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/domain/banking/normalizer.py:97` — `_ADAPTERS: dict[str, dict[str, Optional[int]]] = {` … seven keys through :125. `/home/user/caflow-ai/apps/api/services/bank_column_mapping_service.py:43-45` — `.eq("firm_id", firm_id)` / `.eq("bank_account_id", bank_account_id)` / `.eq("header_fingerprint", fingerprint)` — and :39 `if not db or not bank_account_id or not fingerprint: return None`, so with no account id there is no lookup at all.
PREMISE: mostly sound, the count is off. There are **seven** adapter keys, of which only four name a bank (`hdfc`, `sbi`, `icici`, `axis`); `generic_cheque`, `generic` and `generic_amount_drcr` are shape-based and between them cover a lot of co-op and PSU exports. "Six bank layouts auto-detected" overstates the bank coverage and understates the generic coverage.
SHAPE: cheaper than the finding implies. `bank_statement_column_mappings` already carries `firm_id` (`migrations/314_bank_statement_column_mappings.sql`), and the unique index at :66 is on `(bank_account_id, header_fingerprint)` — so a firm-scoped fallback read is a **read-only change** in `services/bank_column_mapping_service.py::find_mapping` plus the two call sites (`routers/banking.py:900-902`, `:1099-1101`). No migration. The Settings screen is separate frontend work. The invariant to keep: the fingerprint is what makes reuse safe, so the fallback must match on fingerprint exactly and must not fall back on bank *name*.
SIZE: firm-scoped fallback, hours. With the Settings screen, day.

---

**BANK-28 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/domain/banking/narration.py:105-116` — `class ParsedNarration:` with `raw, channel, utr, vpa, counterparty, ifsc, direction, tokens` and no cheque field; :51 — `("CHEQUE", r"\b(?:CHQ|CHEQUE|CLG|MICR)\b"),` recognises the channel; :81 lists `"CHQ", "CHEQUE", "CLG", "MICR", ...` as noise words.
PREMISE: sound.
SHAPE: `domain/banking/narration.py` (one field, one regex, one branch) and whoever should consume the fallback — `domain/banking/register.py:91` and `bank_reconciliation_service.py:609` read `reference_no` off the row, so "fall back to it when `reference_no` is empty" means either writing it onto the transaction at import (`services/banking_service.py`, and then it is a stored value that can disagree with the narration) or resolving it at read time in both places. No migration if read-time. Pick one; doing it at import makes it load-bearing for dedup, because `hash_rows` fingerprints `reference_no`.
SIZE: hours.

---

**BANK-29 — VERDICT: open**
EVIDENCE: `/home/user/caflow-ai/apps/api/domain/banking/normalizer.py:449-451` — `else:` / `debit_paise = abs(_to_paise(col("debit")))` / `credit_paise = abs(_to_paise(col("credit")))` — then :452 `out.append(NormalizedTxn(` unconditionally. The amount/drcr branch does guard, at :444 — `if amount == 0 or (not is_debit and not is_credit): continue`. Downstream refusal still stands: `services/bank_posting_service.py:305` — `raise HTTPException(status_code=422, detail="Transaction has zero amount.")`. No opening/closing-label filter exists — the only label regex is `_TOTAL_LABEL` at :75, which matches `totals?` only.
PREMISE: sound.
SHAPE: one `if` in the two-column branch of `_rows_to_txns`. No migration. One thing the finding does not flag: the skipped row's `balance_paise` currently feeds `_opening_closing_balance` in `services/banking_service.py`, and `domain/banking/tie_out.py` / `balance_agreement` walk the running balance across the stored rows. Dropping the opening row changes the first balance the tie-out sees, so the tie-out tests are the ones that will tell you whether the statement still foots — that is the invariant, and it is why this is not a one-line change you land unverified.
SIZE: hours.