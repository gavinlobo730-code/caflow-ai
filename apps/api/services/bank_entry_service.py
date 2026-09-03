"""
Bank entries — the draft on the row, and passing it.

The design is docs/architecture/09-bank-entries.md; the pure half is
domain/banking/entry.py. This service is the database half:

    redraft     write each open line's best proposal onto it, chunked
    counts      how many lines are in each state — a SQL count, not a scan
    list        one page of lines in a state, from stored columns
    pass_entry  apply the draft (through the existing services) and post it
                through the ONE posting path, bank_posting_service.post
    pass_ready  "Pass N ready": every ready line, chunked and resumable, or
                only the ones a TRUSTED rule drafted, on that rule's authority

WHAT THIS SERVICE NEVER DOES
    Post through anything but bank_posting_service.post. Invent a ledger.
    Pass a PROPOSED draft in bulk. Learn from a line that is not posted.
    Write entry_state — the trigger owns it (the Python twin is for reads in
    mock mode only).

WHY EVERYTHING IS CHUNKED
    A client can have three thousand open lines. Drafting one is a few
    dictionary lookups, but writing it is a Mumbai round trip from Singapore,
    and posting one is several. Neither fits in one request under lib/api's
    45-second abort, so both take a `limit` and return `remaining`; the screen
    keeps calling until it is zero and shows the progress. No job table, no
    background thread, and every chunk is idempotent.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from domain.banking import entry as E
from domain.banking import match_rule, parse_narration, describe_narration
from domain.banking import posting_map as pmap
from services.bank_matching_service import bank_matching_service
from services.bank_payee_service import bank_payee_service
from services.bank_transfer_service import bank_transfer_service
from services.bank_posting_service import bank_posting_service
from services.banking_service import banking_service

_logger = logging.getLogger("caflow.bank_entries")

REDRAFT_CHUNK = 100
PASS_CHUNK = 50
MAX_CHUNK = 200
# What goes on the row when a pass fails. Long enough for the posting
# engine's sentences, short enough to sit in a table cell.
_ERROR_MAX = 300

_TRANSFER_TYPE = "bank_transaction"
# The columns _apply_draft can write through set_account / categorize / match.
_CODING_COLS = ("account_id", "category", "match_status", "matched_entity_type",
                "matched_entity_id", "matched_by", "matched_at", "needs_review")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _outcome(txn_id: str, status: str, reason: str, **extra) -> dict:
    return {"transaction_id": txn_id, "status": status, "reason": reason, **extra}


class BankEntryService:

    # ── reads ────────────────────────────────────────────────────────────────

    def _get_txn(self, db, firm_id: str, txn_id: str) -> dict:
        rows = (db.table("bank_transactions").select("*")
                .eq("id", txn_id).eq("firm_id", firm_id).limit(1).execute().data or [])
        if not rows:
            raise HTTPException(status_code=404, detail="Bank transaction not found.")
        return rows[0]

    @staticmethod
    def _statement_ids(db, firm_id: str, client_id: str, bank_account_id: str) -> list[str]:
        """The statements of one account. A bank line knows its statement, not
        its account, so an account filter is a statement filter."""
        rows = (db.table("bank_statements").select("id")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("bank_account_id", bank_account_id).execute().data or [])
        return [r["id"] for r in rows]

    def _base(self, db, firm_id: str, client_id: str, bank_account_id: Optional[str] = None):
        q = (db.table("bank_transactions").select("*")
             .eq("firm_id", firm_id).eq("client_id", client_id))
        if bank_account_id:
            ids = self._statement_ids(db, firm_id, client_id, bank_account_id)
            q = q.in_("statement_id", ids or ["-"])
        return q

    def _count(self, make_query) -> int:
        """A count with no rows behind it. PostgREST answers from the header;
        the FakeDB from len()."""
        res = make_query().select("id", count="exact").range(0, 0).execute()
        n = getattr(res, "count", None)
        return int(n) if n is not None else len(res.data or [])

    def counts(self, db, firm_id: str, client_id: str,
               bank_account_id: Optional[str] = None) -> dict:
        """One number per state, plus the two the screen acts on: `undrafted`
        (open lines nobody has proposed for yet — the screen redrafts while it
        is non-zero) and `trusted_pending` (ready drafts a trusted rule wrote,
        which the screen passes with a progress bar)."""
        base = lambda: self._base(db, firm_id, client_id, bank_account_id)  # noqa: E731
        out: dict = {}
        for state in E.STATES:
            out[state] = self._count(lambda s=state: base().eq("entry_state", s))
        out["to_do"] = sum(out[s] for s in E.OPEN_STATES)
        out["undrafted"] = self._count(
            lambda: base().in_("entry_state", list(E.OPEN_STATES)).is_("drafted_at", "null"))
        trusted = self._trusted_rules(db, firm_id, client_id)
        out["trusted_pending"] = (
            self._count(lambda: base().eq("entry_state", E.READY).is_("draft_error", "null")
                        .in_("draft_rule_id", list(trusted)))
            if trusted else 0)
        return out

    _LIST_STATES = frozenset(E.STATES) | {"to_do", "all"}

    def list_entries(self, db, firm_id: str, client_id: str, *, state: str = "to_do",
                     limit: int = 50, offset: int = 0, q_text: Optional[str] = None,
                     bank_account_id: Optional[str] = None) -> tuple[list[dict], int]:
        """One page, from stored columns. No pools are read here: the draft is
        on the row, and the detail (get_entry) fetches live candidates for the
        one line that is open."""
        if state not in self._LIST_STATES:
            raise HTTPException(status_code=422, detail="Invalid entry state.")

        def make():
            q = self._base(db, firm_id, client_id, bank_account_id)
            if state == "to_do":
                q = q.in_("entry_state", list(E.OPEN_STATES))
            elif state != "all":
                q = q.eq("entry_state", state)
            return bank_matching_service._search_filter(q, q_text)

        total = self._count(make)
        start = max(int(offset), 0)
        rows = (make().order("transaction_date").order("id")
                .range(start, start + max(int(limit), 1) - 1).execute().data or [])
        self._annotate(db, firm_id, rows)
        return rows, total

    def get_entry(self, db, firm_id: str, txn_id: str) -> dict:
        """The one line the CA opened: the row, plus what only the detail
        needs — live document candidates, the payee's history with its
        evidence, and any transfer counterpart the matcher can see."""
        txn = self._get_txn(db, firm_id, txn_id)
        self._annotate(db, firm_id, [txn])
        client_id = txn["client_id"]
        live = not (txn.get("match_status") in ("posted", "ignored") or txn.get("matched_entity_id"))
        txn["suggestions"] = (
            bank_matching_service.suggestions_for_many(db, firm_id, client_id, [txn]).get(str(txn_id), [])
            if live else [])
        index = bank_payee_service.history_index(db, firm_id, client_id)
        txn["history"] = bank_payee_service.as_dict(bank_payee_service.suggest_for(txn, index))
        txn["suggested_payee"] = bank_payee_service.suggest_payee(
            db, firm_id, client_id, txn, parties=bank_payee_service.parties(db, firm_id, client_id))
        pairs = self._pairs_by_txn(db, firm_id, client_id)
        txn["transfer_candidate"] = pairs.get(str(txn_id))
        return txn

    def _annotate(self, db, firm_id: str, rows: list[dict]) -> None:
        """What every reader of a line needs and no column holds: the kind,
        the parsed narration, the state in mock mode, GST eligibility and the
        splits. Cheap — one query for the splits, none for the rest."""
        for t in rows:
            t["kind"] = E.kind_for(t)
            n = parse_narration(t.get("description"))
            t["parsed"] = {"channel": n.channel, "utr": n.utr, "vpa": n.vpa,
                           "counterparty": n.counterparty, "ifsc": n.ifsc,
                           "summary": describe_narration(n)}
            # The trigger wrote entry_state on a real database. A fake has no
            # trigger, so the twin fills it in — and on a real row the two agree,
            # which is what the parity test proves.
            if not t.get("entry_state"):
                t["entry_state"] = E.entry_state(t)
        bank_matching_service._attach_splits(db, firm_id, rows)
        bank_matching_service._mark_gst_eligibility(rows)

    # ── redraft ──────────────────────────────────────────────────────────────

    def mark_stale(self, db, firm_id: str, client_id: str) -> int:
        """After a rule changes: every open line is re-proposed for on the next
        redraft. Writes drafted_at = NULL rather than recomputing here, so a
        rule edit costs one UPDATE and the redraft happens in chunks, with
        progress, when the screen next asks."""
        rows = (db.table("bank_transactions").update({"drafted_at": None})
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("entry_state", list(E.OPEN_STATES)).execute().data or [])
        return len(rows)

    def _pick_for_redraft(self, db, firm_id, client_id, *, limit, stale_before, txn_ids):
        if txn_ids:
            return (self._base(db, firm_id, client_id).in_("id", list(txn_ids))
                    .in_("entry_state", list(E.OPEN_STATES))
                    .order("transaction_date").order("id").limit(limit).execute().data or [])
        rows = (self._base(db, firm_id, client_id).in_("entry_state", list(E.OPEN_STATES))
                .is_("drafted_at", "null")
                .order("transaction_date").order("id").limit(limit).execute().data or [])
        if stale_before and len(rows) < limit:
            # A forced refresh: lines drafted before the refresh began. Two
            # queries rather than an OR, so the fake and PostgREST read alike.
            more = (self._base(db, firm_id, client_id).in_("entry_state", list(E.OPEN_STATES))
                    .lte("drafted_at", stale_before)
                    .order("transaction_date").order("id").limit(limit - len(rows))
                    .execute().data or [])
            seen = {r["id"] for r in rows}
            rows += [r for r in more if r["id"] not in seen]
        return rows

    def _remaining_for_redraft(self, db, firm_id, client_id, stale_before) -> int:
        base = lambda: self._base(db, firm_id, client_id).in_("entry_state", list(E.OPEN_STATES))  # noqa: E731
        n = self._count(lambda: base().is_("drafted_at", "null"))
        if stale_before:
            n += self._count(lambda: base().lte("drafted_at", stale_before))
        return n

    def redraft(self, db, firm_id: str, client_id: str, *, limit: int = REDRAFT_CHUNK,
                stale_before: Optional[str] = None, txn_ids: Optional[list[str]] = None) -> dict:
        """Propose for up to `limit` open lines and write what changed.

        Which lines: those never drafted (drafted_at IS NULL) — that is what
        an import leaves, and what mark_stale produces — or, when
        `stale_before` is given, also those drafted before that instant. The
        caller passes the instant back on every chunk so the walk ends.

        The sources are built ONCE for the chunk — the client's rules, the
        payee history, the candidate pools, the transfer pairs — never per
        row. That is the whole reason this is a service and not a loop over
        the per-row endpoints.
        """
        limit = max(1, min(int(limit), MAX_CHUNK))
        rows = self._pick_for_redraft(db, firm_id, client_id, limit=limit,
                                      stale_before=stale_before, txn_ids=txn_ids)
        changed = 0
        if rows:
            rules = (db.table("bank_matching_rules").select("*")
                     .eq("firm_id", firm_id).eq("client_id", client_id).eq("is_active", True)
                     .order("created_at").execute().data or [])
            index = bank_payee_service.history_index(db, firm_id, client_id)
            candidates = bank_matching_service.suggestions_for_many(
                db, firm_id, client_id,
                [t for t in rows if not t.get("matched_entity_id")])
            pairs = self._pairs_by_txn(db, firm_id, client_id)
            bank_names = self._bank_account_names(db, firm_id, client_id)
            account_names = self._account_names(db, firm_id, rules, index)
            now = _now()
            for t in rows:
                draft = self._draft_for(t, rules, index, candidates, pairs, bank_names, account_names)
                # Column names written out at the call, not spread from a dict:
                # tests/test_backend_columns_exist_pg.py reads literal keys and
                # counts anything else as a blind spot.
                if E.draft_changed(t, draft):
                    c = draft.as_columns() if draft else E.EMPTY_DRAFT_COLUMNS
                    changed += 1
                    (db.table("bank_transactions").update({
                        "drafted_at": now, "draft_error": None,
                        "draft_source": c["draft_source"], "draft_grade": c["draft_grade"],
                        "draft_label": c["draft_label"], "draft_reason": c["draft_reason"],
                        "draft_account_id": c["draft_account_id"], "draft_category": c["draft_category"],
                        "draft_entity_type": c["draft_entity_type"], "draft_entity_id": c["draft_entity_id"],
                        "draft_rule_id": c["draft_rule_id"], "draft_gst_rate_bps": c["draft_gst_rate_bps"],
                        "draft_is_interstate": c["draft_is_interstate"],
                    }).eq("id", t["id"]).eq("firm_id", firm_id).execute())
                else:
                    (db.table("bank_transactions").update({"drafted_at": now, "draft_error": None})
                     .eq("id", t["id"]).eq("firm_id", firm_id).execute())
        remaining = self._remaining_for_redraft(db, firm_id, client_id, stale_before) if not txn_ids else 0
        return {"drafted": len(rows), "changed": changed, "remaining": remaining,
                "stale_before": stale_before}

    def _draft_for(self, t, rules, index, candidates, pairs, bank_names, account_names) -> Optional[E.Draft]:
        amount = max(int(t.get("debit_paise") or 0), int(t.get("credit_paise") or 0))
        is_debit = int(t.get("credit_paise") or 0) == 0
        hit = match_rule(t.get("description"), amount, is_debit, rules)
        rule_d = E.from_rule(hit, account_names.get(hit.account_id) if hit else None)
        doc_d = E.from_documents(candidates.get(str(t.get("id")), []))
        learned = bank_payee_service.suggest_for(t, index)
        hist_d = E.from_history(learned, account_names.get(learned.account_id) if learned else None)
        pair = pairs.get(str(t.get("id")))
        other_name = None
        if pair:
            other_acct = (pair.get("counterpart_account_id") if pair.get("primary_id") == t.get("id")
                          else pair.get("primary_account_id"))
            other_name = bank_names.get(other_acct)
        tr_d = E.from_transfer(pair, str(t.get("id")), other_name)
        return E.choose(rule_d, doc_d, tr_d, hist_d)

    def _pairs_by_txn(self, db, firm_id, client_id) -> dict:
        """Each open line's candidate counterpart, keyed by BOTH ids. Never
        fatal: a scan that fails costs the lines a transfer proposal, not the
        redraft."""
        try:
            pairs = bank_transfer_service.detect_pairs(db, firm_id, client_id)
        except Exception as e:  # pragma: no cover - best effort, as the endpoint is
            _logger.warning("transfer detection failed for client %s: %s", client_id, e)
            return {}
        out: dict = {}
        for p in pairs:
            d = bank_transfer_service.as_dict(p)
            out[str(d["primary_id"])] = d
            out[str(d["counterpart_id"])] = d
        return out

    @staticmethod
    def _bank_account_names(db, firm_id, client_id) -> dict:
        rows = (db.table("bank_accounts").select("id, bank_name, account_no")
                .eq("firm_id", firm_id).eq("client_id", client_id).execute().data or [])
        out = {}
        for r in rows:
            tail = str(r.get("account_no") or "")[-4:]
            out[r["id"]] = f"{r.get('bank_name') or 'Bank'}{' ·' + tail if tail else ''}"
        return out

    @staticmethod
    def _account_names(db, firm_id, rules, index) -> dict:
        """Names for exactly the ledgers a draft could name — the rules' and
        the history's — in one query. The chart is not read whole."""
        ids = {r.get("suggested_account_id") for r in rules if r.get("suggested_account_id")}
        for rows in index.values():
            for r in rows:
                if r.get("account_id"):
                    ids.add(r["account_id"])
        if not ids:
            return {}
        rows = (db.table("chart_of_accounts").select("id, account_name")
                .eq("firm_id", firm_id).in_("id", list(ids)).execute().data or [])
        return {r["id"]: r.get("account_name") for r in rows}

    # ── passing ──────────────────────────────────────────────────────────────

    def pass_entry(self, db, firm_id: str, txn_id: str, *, actor_id: Optional[str],
                   actor_auth_id: Optional[str] = None, by_rule: Optional[dict] = None,
                   gst_rate_bps: Optional[int] = None, is_interstate: bool = False) -> dict:
        """Apply the draft, then post — through the services that already own
        each step, so nothing here is a second way to code a line.

        A line the CA coded themselves posts what they chose; the draft is
        not consulted. Otherwise the draft is applied: a rule's or history's
        ledger through set_account, a document through match, a transfer
        through pair (and then the PAYING side is what posts). A short
        document match is refused — it needs the settlement modal, where
        someone says what the shortfall was.

        A refusal is written onto the row as draft_error and reported; it is
        never raised out of a bulk pass, because one locked line must not
        stop the other forty-nine.
        """
        txn = self._get_txn(db, firm_id, txn_id)
        state = txn.get("entry_state") or E.entry_state(txn)
        if state == E.PASSED:
            return _outcome(txn_id, "skipped", "Already passed.")
        if state == E.SET_ASIDE:
            return _outcome(txn_id, "skipped", "Set aside — restore it first.")
        if state == E.COVERED:
            return _outcome(txn_id, "skipped", "Passes with its paying side.")

        post_id = txn_id
        # The GST treatment for a line the CA coded themselves comes from the
        # detail, the way it did from the old drawer; a draft carries its own.
        gst_rate, interstate = gst_rate_bps, bool(is_interstate)
        # What the row said before the draft touched it. A draft is applied
        # through the same services a human uses, so a pass that then fails
        # would leave the machine's coding on the row looking like the CA's
        # answer — and the next reader would trust it. Put it back.
        before = {k: txn.get(k) for k in _CODING_COLS}
        applied = False
        try:
            if not E.coded_by_a_human(txn):
                post_id, draft_gst, draft_inter = self._apply_draft(db, firm_id, txn, actor_id)
                applied = True
                # The draft's GST treatment unless the CA said otherwise from
                # the detail — a person's choice outranks a rule's proposal.
                if gst_rate_bps is None:
                    gst_rate, interstate = draft_gst, draft_inter
            result = bank_posting_service.post(
                db, firm_id, post_id, gst_rate_bps=gst_rate, is_interstate=interstate,
                actor_id=actor_id, actor_auth_id=actor_auth_id)
        except HTTPException as e:
            detail = str(e.detail)[:_ERROR_MAX]
            if applied:
                self._unapply(db, firm_id, txn, before)
            # A separate write, AFTER the restore: the trigger clears
            # draft_error when the coding columns change, and they just did.
            (db.table("bank_transactions").update({"draft_error": detail, "updated_at": _now()})
             .eq("id", txn_id).eq("firm_id", firm_id).execute())
            return _outcome(txn_id, "failed", detail)

        if by_rule:
            (db.table("bank_transactions")
             .update({"posted_by_rule_id": by_rule.get("id"), "updated_at": _now()})
             .eq("id", post_id).eq("firm_id", firm_id).execute())
            try:
                from services.audit_service import log_event
                log_event(firm_id, "bank_transaction", post_id, "status_change",
                          actor_id=actor_id,
                          new_data={"posted_journal_id": result.get("posted_journal_id"),
                                    "rule_id": by_rule.get("id"), "rule_name": by_rule.get("rule_name"),
                                    "trusted_by": by_rule.get("trusted_by")},
                          metadata={"source": "bank_trusted_rule", "stage": "posted"})
            except Exception as e:  # pragma: no cover - audit must never block the post
                from core.observability import capture_soft_failure
                capture_soft_failure(e, operation="bank_entries.trusted_rule_audit",
                                     transaction_id=post_id, rule_id=by_rule.get("id"))
        return _outcome(txn_id, "passed", f"Passed as a {E.kind_for(txn)}.",
                        posted_journal_id=result.get("posted_journal_id"),
                        posted_transaction_id=post_id)

    def _unapply(self, db, firm_id, txn, before: dict) -> None:
        """Undo what _apply_draft wrote, best effort. A transfer was paired
        through the RPC and is unpaired through its twin; everything else is
        the row's own coding columns, restored from the snapshot."""
        try:
            if txn.get("draft_source") == E.SOURCE_TRANSFER:
                bank_transfer_service.unpair(db, firm_id, txn["id"])
            else:
                (db.table("bank_transactions").update({
                    "account_id": before["account_id"], "category": before["category"],
                    "match_status": before["match_status"],
                    "matched_entity_type": before["matched_entity_type"],
                    "matched_entity_id": before["matched_entity_id"],
                    "matched_by": before["matched_by"], "matched_at": before["matched_at"],
                    "needs_review": before["needs_review"], "updated_at": _now(),
                }).eq("id", txn["id"]).eq("firm_id", firm_id).execute())
        except Exception as e:  # pragma: no cover - the refusal is still reported
            _logger.warning("could not restore bank line %s after a failed pass: %s", txn["id"], e)

    def _apply_draft(self, db, firm_id, txn, actor_id) -> tuple[str, Optional[int], bool]:
        """Returns (the id to post, gst_rate_bps, is_interstate)."""
        source = txn.get("draft_source")
        txn_id = txn["id"]
        if not source:
            raise HTTPException(status_code=422,
                                detail="Nothing to pass — choose a ledger or a document first.")
        if source in (E.SOURCE_RULE, E.SOURCE_HISTORY):
            account_id = txn.get("draft_account_id")
            category = txn.get("draft_category")
            if category:
                bank_matching_service.categorize(db, firm_id, txn_id, category)
            if account_id:
                banking_service.set_account(db, firm_id, txn_id, account_id,
                                            derive_category=not category)
            elif not category:
                raise HTTPException(status_code=422, detail="The proposal names no ledger.")
            return txn_id, txn.get("draft_gst_rate_bps"), bool(txn.get("draft_is_interstate"))
        if source == E.SOURCE_DOCUMENT:
            if txn.get("draft_grade") != E.GRADE_READY:
                raise HTTPException(
                    status_code=422,
                    detail=f"{txn.get('draft_reason') or 'Needs a decision'} — settle it from the line.")
            bank_matching_service.match(db, firm_id, txn_id, txn.get("draft_entity_type"),
                                        txn.get("draft_entity_id"), actor_id=actor_id)
            return txn_id, None, False
        if source == E.SOURCE_TRANSFER:
            other = txn.get("draft_entity_id")
            if not other:
                raise HTTPException(status_code=422, detail="The transfer names no counterpart.")
            is_out = int(txn.get("credit_paise") or 0) == 0
            primary, counter = (txn_id, other) if is_out else (other, txn_id)
            bank_transfer_service.pair(db, firm_id, primary, counter, actor_id=actor_id)
            return primary, None, False
        raise HTTPException(status_code=422, detail=f"Unknown proposal source '{source}'.")

    def _trusted_rules(self, db, firm_id, client_id) -> dict:
        rows = (db.table("bank_matching_rules").select("*")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("is_active", True).eq("is_trusted", True).execute().data or [])
        return {r["id"]: r for r in rows}

    def pass_ready(self, db, firm_id: str, client_id: str, *, limit: int = PASS_CHUNK,
                   only_trusted: bool = False, actor_id: Optional[str] = None,
                   actor_auth_id: Optional[str] = None, bank_account_id: Optional[str] = None,
                   txn_ids: Optional[list[str]] = None) -> dict:
        """One chunk of "Pass N ready".

        Only READY lines with no standing error are picked — a line whose last
        pass failed waits for a human or a redraft rather than failing again
        on every chunk. With only_trusted, only lines a trusted rule drafted,
        each passed as that rule's trusted_by; the flag is read from the rule
        NOW, so un-trusting stops the sweep at once. Deliberately not atomic
        across lines: forty-nine good lines must not roll back for the fiftieth.
        """
        limit = max(1, min(int(limit), MAX_CHUNK))
        trusted = self._trusted_rules(db, firm_id, client_id) if only_trusted else {}
        if only_trusted and not trusted:
            return {"passed": 0, "failed": 0, "skipped": 0, "remaining": 0, "results": []}

        def make():
            q = (self._base(db, firm_id, client_id, bank_account_id)
                 .eq("entry_state", E.READY).is_("draft_error", "null"))
            if txn_ids:
                q = q.in_("id", list(txn_ids))
            if only_trusted:
                q = q.in_("draft_rule_id", list(trusted))
            return q

        rows = make().order("transaction_date").order("id").limit(limit).execute().data or []
        results = []
        for t in rows:
            rule = trusted.get(t.get("draft_rule_id")) if only_trusted else None
            actor = rule.get("trusted_by") if rule else actor_id
            results.append(self.pass_entry(db, firm_id, t["id"], actor_id=actor,
                                           actor_auth_id=None if rule else actor_auth_id,
                                           by_rule=rule))
        remaining = self._count(make)
        summary = {s: sum(1 for r in results if r["status"] == s)
                   for s in ("passed", "failed", "skipped")}
        return {**summary, "remaining": remaining, "results": results}


bank_entry_service = BankEntryService()
