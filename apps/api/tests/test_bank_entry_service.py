"""
bank_entry_service — redraft, counts, list, pass, pass-ready, trusted rules.

WHAT IS ASSERTED
    1. redraft writes each open line's best proposal WITH its grade and reason,
       writes only what changed, and never touches a passed or set-aside line.
    2. A rule outranks history; history alone is READY only when unanimous over
       three postings; a line nobody can propose for is left needs_you.
    3. counts are what the stored columns say, and to_do is the three open
       states summed.
    4. pass_entry applies the draft THROUGH the existing services (set_account,
       match, pair) and posts through bank_posting_service.post — the one
       posting path — with the draft's GST treatment.
    5. A refusal from the posting path is written onto the row as draft_error,
       demotes a machine draft to needs_you, and is NOT raised out of a bulk
       pass; the next chunk skips it.
    6. pass_ready passes only READY lines, in chunks, reporting `remaining`;
       a PROPOSED draft is never passed in bulk.
    7. only_trusted passes only lines a TRUSTED rule drafted, as that rule's
       trusted_by, stamping posted_by_rule_id; an untrusted rule's lines are
       left alone; un-trusting stops it.
    8. The pass of a transfer draft pairs the two lines and posts the PAYING
       side, whichever side was passed.

The posting engine is a recorder here: it has its own suite
(test_bank_posting.py), and what this file proves is that the entry service
calls it, with what, and never posts any other way. The FakeDB is
test_bank_matching's, which has no trigger — so entry_state is read through
the Python twin, exactly as the service does in mock mode.
"""
from __future__ import annotations

import re

import pytest
from fastapi import HTTPException

from domain.banking import entry as E
import services.bank_entry_service as bes
from services.bank_entry_service import bank_entry_service as svc
import services.bank_matching_service as bms
import services.banking_service as bsm
from tests.test_bank_matching import FakeDB, _Q, FIRM, CLIENT, _seed_txn

CHARGES, RENT = "acc-charges", "acc-rent"

# The trigger's twin, applied by the fake the way the database applies the
# trigger: after every insert or update of a bank line, entry_state is
# recomputed from the row, and a human's answer clears a standing error.
_ANSWER_COLS = ("account_id", "matched_entity_id", "category", "transfer_pair_id",
                "has_splits", "match_status")


class _TQ(_Q):
    def execute(self):
        payload = self._payload if self._op in ("insert", "update") else None
        res = super().execute()
        if self.table == "bank_transactions" and payload is not None:
            for r in (res.data if isinstance(res.data, list) else [res.data]):
                if not r:
                    continue
                if (self._op == "update" and r.get("draft_error")
                        and any(k in payload for k in _ANSWER_COLS)):
                    r["draft_error"] = None
                r["entry_state"] = E.entry_state(r)
        return res


class TriggeredDB(FakeDB):
    def table(self, name):
        return _TQ(self.store, name)


# ── a fake that refuses what postgrest refuses ───────────────────────────────
# supabase-py's builder has .select() on the TABLE only; once a select has been
# made, the query object has no .select at all. The lenient fake above accepts
# a second .select(), which is how a `.select("id", count="exact")` on a built
# query passed 9,000 tests and 500'd on the first production request after
# #395. This fake raises the same AttributeError postgrest does.
class _StrictQ(_TQ):
    def select(self, *a, **k):
        if getattr(self, "_selected", False):
            raise AttributeError("'SyncSelectRequestBuilder' object has no attribute 'select'")
        self._selected = True
        return super().select(*a, **k)


class StrictDB(TriggeredDB):
    def table(self, name):
        return _StrictQ(self.store, name)


# ── a fake that refuses what POSTGRES refuses ────────────────────────────────
# The one above models the client library's shape. This one models the column's
# TYPE: PostgREST hands a filter value straight to Postgres, which answers
# 22P02 `invalid input syntax for type uuid` for anything that is not a uuid.
# The shared fake compares strings, so it accepted the sentinel "-" that _base
# fell back to for an account with no statements — and production answered 500
# on every Entries read the moment a CA picked such an account.
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class _TypedQ(_TQ):
    def in_(self, k, vals):
        vals = list(vals)
        if k == "statement_id":
            for v in vals:
                if not _UUID.match(str(v)):
                    raise RuntimeError(f'invalid input syntax for type uuid: "{v}"')
        return super().in_(k, vals)


class TypedDB(TriggeredDB):
    def table(self, name):
        return _TypedQ(self.store, name)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(bms.timeline_service, "log", lambda *a, **k: None)
    yield


class _Poster:
    """Stands in for bank_posting_service.post. Records every call and marks
    the row posted the way the real one does; raises what it is told to."""
    def __init__(self, refuse: dict | None = None):
        self.calls: list[dict] = []
        self.refuse = refuse or {}

    def __call__(self, db, firm_id, txn_id, bank_account_id=None, account_id=None,
                 to_bank_account_id=None, actor_id=None, gst_rate_bps=None,
                 is_interstate=False, actor_auth_id=None):
        self.calls.append(dict(txn_id=txn_id, actor_id=actor_id, gst_rate_bps=gst_rate_bps,
                               is_interstate=is_interstate, actor_auth_id=actor_auth_id))
        if txn_id in self.refuse:
            raise HTTPException(status_code=422, detail=self.refuse[txn_id])
        je = f"je-{txn_id}"
        (db.table("bank_transactions").update(
            {"match_status": "posted", "posted_journal_id": je, "posted_by": actor_id})
         .eq("id", txn_id).eq("firm_id", firm_id).execute())
        return {"id": txn_id, "status": "posted", "match_status": "posted", "posted_journal_id": je}


@pytest.fixture
def poster(monkeypatch):
    p = _Poster()
    monkeypatch.setattr(bes.bank_posting_service, "post", p)
    return p


def _db(strict: bool = False):
    db = StrictDB() if strict else TriggeredDB()
    db.store["chart_of_accounts"] = [
        {"id": CHARGES, "firm_id": FIRM, "client_id": CLIENT, "account_name": "Bank Charges",
         "account_type": "Expense", "account_code": "5001", "is_active": True},
        {"id": RENT, "firm_id": FIRM, "client_id": CLIENT, "account_name": "Rent",
         "account_type": "Expense", "account_code": "5002", "is_active": True},
    ]
    db.store["bank_statements"] = [{"id": "s1", "firm_id": FIRM, "client_id": CLIENT,
                                    "bank_account_id": "ba-1"}]
    db.store["bank_accounts"] = [{"id": "ba-1", "firm_id": FIRM, "client_id": CLIENT,
                                  "bank_name": "HDFC", "account_no": "1234567890"}]
    db.store["bank_matching_rules"] = []
    return db


def _line(db, tid, descr, debit=59000, credit=0, **kw):
    base = dict(id=tid, description=descr, debit_paise=debit, credit_paise=credit,
                statement_id="s1", account_id=None, payee_name=None, payee_id=None,
                posted_journal_id=None, posted_at=None, transaction_date="2026-04-15",
                draft_source=None, draft_grade=None, drafted_at=None, draft_error=None)
    base.update(kw)
    row = _seed_txn(db, **base)
    # Seeding bypasses the fake's execute(), so the twin runs here as the
    # trigger would on INSERT. An explicit entry_state in the seed wins.
    row.setdefault("entry_state", E.entry_state(row))
    return row


def _rule(db, rid="r1", pattern="CHARGES", account=CHARGES, category="Expense", **kw):
    row = {"id": rid, "firm_id": FIRM, "client_id": CLIENT, "is_active": True,
           "rule_name": "Bank charges", "description_pattern": pattern,
           "amount_min_paise": None, "amount_max_paise": None, "txn_type": "any",
           "suggested_category": category, "suggested_account_id": account,
           "suggested_narration": None, "suggested_gst_rate_bps": None,
           "suggested_is_interstate": False, "created_at": "2026-01-01",
           "is_trusted": False, "trusted_by": None, "trusted_at": None}
    row.update(kw)
    db.store["bank_matching_rules"].append(row)
    return row


def _teach(db, n, account=RENT, payee="RAMESH KUMAR"):
    """n POSTED lines for one payee, coded to `account` — history's evidence."""
    for i in range(n):
        _line(db, f"teacher-{account}-{i}", f"UPI/DR/{i}/{payee}/HDFC", payee_name=payee,
              account_id=account, category="Expense", match_status="posted",
              posted_journal_id=f"je-t{i}", posted_at=f"2026-03-0{i + 1}T00:00:00Z")


def _row(db, tid):
    return next(r for r in db.store["bank_transactions"] if r["id"] == tid)


def _state(db, tid):
    return E.entry_state(_row(db, tid))


# ── 1-2. redraft ─────────────────────────────────────────────────────────────

def test_redraft_writes_the_rules_proposal_as_ready_with_its_reason():
    db = _db(); _rule(db); _line(db, "t1", "NEFT CHARGES APR2026")
    out = svc.redraft(db, FIRM, CLIENT)
    r = _row(db, "t1")
    assert out["drafted"] == 1 and out["changed"] == 1 and out["remaining"] == 0
    assert r["draft_source"] == "rule" and r["draft_grade"] == "ready"
    assert r["draft_account_id"] == CHARGES and r["draft_rule_id"] == "r1"
    assert r["draft_label"] == "Bank Charges" and "Bank charges" in r["draft_reason"]
    assert r["drafted_at"] and _state(db, "t1") == E.READY


def test_a_rule_outranks_history_for_the_same_line():
    db = _db(); _rule(db, pattern="RAMESH", account=CHARGES)
    _teach(db, 3)
    _line(db, "t1", "UPI/DR/9/RAMESH KUMAR/HDFC", payee_name="RAMESH KUMAR")
    svc.redraft(db, FIRM, CLIENT)
    r = _row(db, "t1")
    assert r["draft_source"] == "rule" and r["draft_account_id"] == CHARGES


def test_history_is_ready_only_when_unanimous_over_three():
    db = _db(); _teach(db, 3)
    _line(db, "t1", "UPI/DR/9/RAMESH KUMAR/HDFC", payee_name="RAMESH KUMAR")
    svc.redraft(db, FIRM, CLIENT)
    r = _row(db, "t1")
    assert r["draft_source"] == "history" and r["draft_grade"] == "ready"
    assert r["draft_account_id"] == RENT and r["draft_label"] == "Rent"
    assert "3" in r["draft_reason"]

    db2 = _db(); _teach(db2, 2)
    _line(db2, "t1", "UPI/DR/9/RAMESH KUMAR/HDFC", payee_name="RAMESH KUMAR")
    svc.redraft(db2, FIRM, CLIENT)
    assert _row(db2, "t1")["draft_grade"] == "proposed"
    assert _state(db2, "t1") == E.PROPOSED


def test_a_line_nobody_can_propose_for_is_drafted_empty_and_stays_needs_you():
    db = _db(); _line(db, "t1", "SOMETHING NOBODY HAS SEEN")
    out = svc.redraft(db, FIRM, CLIENT)
    r = _row(db, "t1")
    assert out["drafted"] == 1 and out["changed"] == 0
    assert r["draft_source"] is None and r["drafted_at"] is not None
    assert _state(db, "t1") == E.NEEDS_YOU


def test_redraft_leaves_passed_and_set_aside_lines_alone():
    db = _db(); _rule(db)
    _line(db, "done", "NEFT CHARGES", match_status="posted", posted_journal_id="je-1")
    _line(db, "aside", "NEFT CHARGES", match_status="ignored")
    out = svc.redraft(db, FIRM, CLIENT)
    assert out["drafted"] == 0
    assert _row(db, "done")["draft_source"] is None and _row(db, "aside")["drafted_at"] is None


def test_redraft_is_chunked_and_reports_what_remains():
    db = _db(); _rule(db)
    for i in range(5):
        _line(db, f"t{i}", "NEFT CHARGES", transaction_date=f"2026-04-1{i}")
    first = svc.redraft(db, FIRM, CLIENT, limit=2)
    assert first["drafted"] == 2 and first["remaining"] == 3
    second = svc.redraft(db, FIRM, CLIENT, limit=2)
    assert second["drafted"] == 2 and second["remaining"] == 1
    third = svc.redraft(db, FIRM, CLIENT, limit=2)
    assert third["drafted"] == 1 and third["remaining"] == 0
    assert svc.redraft(db, FIRM, CLIENT, limit=2)["drafted"] == 0


def test_a_second_redraft_of_a_drafted_line_writes_nothing():
    db = _db(); _rule(db); _line(db, "t1", "NEFT CHARGES")
    svc.redraft(db, FIRM, CLIENT)
    before = dict(_row(db, "t1"))
    out = svc.redraft(db, FIRM, CLIENT, stale_before="2999-01-01T00:00:00+00:00")
    after = _row(db, "t1")
    assert out["drafted"] == 1 and out["changed"] == 0
    assert {k: v for k, v in after.items() if k.startswith("draft_")} == \
           {k: v for k, v in before.items() if k.startswith("draft_")}


def test_mark_stale_sends_open_lines_back_for_proposal_and_a_new_rule_wins():
    db = _db(); _teach(db, 3)
    _line(db, "t1", "UPI/DR/9/RAMESH KUMAR/HDFC", payee_name="RAMESH KUMAR")
    svc.redraft(db, FIRM, CLIENT)
    assert _row(db, "t1")["draft_source"] == "history"
    _rule(db, pattern="RAMESH", account=CHARGES)
    assert svc.mark_stale(db, FIRM, CLIENT) == 1
    assert svc.counts(db, FIRM, CLIENT)["undrafted"] == 1
    svc.redraft(db, FIRM, CLIENT)
    assert _row(db, "t1")["draft_source"] == "rule"


def test_redraft_clears_a_standing_error():
    db = _db(); _rule(db)
    _line(db, "t1", "NEFT CHARGES", draft_error="Period locked", draft_source="rule",
          draft_grade="ready", draft_account_id=CHARGES, draft_rule_id="r1",
          draft_label="Bank Charges", draft_reason="Rule “Bank charges”")
    svc.redraft(db, FIRM, CLIENT, txn_ids=["t1"])
    assert _row(db, "t1")["draft_error"] is None


# ── 3. counts and list ───────────────────────────────────────────────────────

def test_counts_read_the_stored_state_and_to_do_is_the_open_three():
    db = _db()
    _line(db, "a", "x", entry_state="needs_you")
    _line(db, "b", "x", entry_state="proposed")
    _line(db, "c", "x", entry_state="ready")
    _line(db, "d", "x", entry_state="ready", drafted_at="2026-04-15T00:00:00Z")
    _line(db, "e", "x", entry_state="passed", match_status="posted")
    _line(db, "f", "x", entry_state="set_aside", match_status="ignored")
    _line(db, "g", "x", entry_state="covered")
    c = svc.counts(db, FIRM, CLIENT)
    assert (c["needs_you"], c["proposed"], c["ready"], c["covered"], c["passed"], c["set_aside"]) \
        == (1, 1, 2, 1, 1, 1)
    assert c["to_do"] == 4 and c["undrafted"] == 3 and c["trusted_pending"] == 0


def test_list_filters_by_state_and_annotates_kind_and_narration():
    db = _db()
    _line(db, "a", "UPI/CR/1/ACME LTD/HDFC", debit=0, credit=5000, entry_state="ready")
    _line(db, "b", "NEFT CHARGES", entry_state="passed", match_status="posted")
    rows, total = svc.list_entries(db, FIRM, CLIENT, state="to_do")
    assert total == 1 and rows[0]["id"] == "a"
    assert rows[0]["kind"] == "receipt" and rows[0]["parsed"]["counterparty"]
    rows, total = svc.list_entries(db, FIRM, CLIENT, state="all")
    assert total == 2
    with pytest.raises(HTTPException):
        svc.list_entries(db, FIRM, CLIENT, state="everything")


def test_passed_lists_the_covered_side_of_a_contra_beside_its_paying_side():
    # The screen has three filters — To do · Passed · Set aside — so the
    # receiving side of a passed transfer must appear SOMEWHERE, and "done" is
    # where it is. Covered alone is still reachable by its own state.
    db = _db()
    _line(db, "a", "IMPS OWN ACCOUNT", debit=10000, credit=0, entry_state="passed", match_status="posted")
    _line(db, "b", "IMPS OWN ACCOUNT", debit=0, credit=10000, entry_state="covered")
    _line(db, "c", "NEFT CHARGES", entry_state="ready")
    rows, total = svc.list_entries(db, FIRM, CLIENT, state="passed")
    assert total == 2 and {r["id"] for r in rows} == {"a", "b"}
    rows, total = svc.list_entries(db, FIRM, CLIENT, state="covered")
    assert total == 1 and rows[0]["id"] == "b"
    rows, total = svc.list_entries(db, FIRM, CLIENT, state="to_do")
    assert total == 1 and rows[0]["id"] == "c"


# ── 4-5. pass_entry ──────────────────────────────────────────────────────────

def test_passing_a_rule_draft_codes_the_line_then_posts_with_the_rules_gst(poster):
    db = _db(); _rule(db, suggested_gst_rate_bps=1800, suggested_is_interstate=True)
    _line(db, "t1", "NEFT CHARGES")
    svc.redraft(db, FIRM, CLIENT)
    out = svc.pass_entry(db, FIRM, "t1", actor_id="u-1", actor_auth_id="auth-1")
    assert out["status"] == "passed" and out["posted_journal_id"] == "je-t1"
    r = _row(db, "t1")
    assert r["account_id"] == CHARGES and r["category"] == "Expense"   # through set_account/categorize
    assert poster.calls == [dict(txn_id="t1", actor_id="u-1", gst_rate_bps=1800,
                                 is_interstate=True, actor_auth_id="auth-1")]
    assert _state(db, "t1") == E.PASSED


def test_a_line_the_ca_coded_posts_what_they_chose_and_ignores_the_draft(poster):
    db = _db(); _rule(db)
    _line(db, "t1", "NEFT CHARGES", account_id=RENT, category="Expense",
          draft_source="rule", draft_grade="ready", draft_account_id=CHARGES,
          draft_gst_rate_bps=1800)
    out = svc.pass_entry(db, FIRM, "t1", actor_id="u-1")
    assert out["status"] == "passed"
    assert _row(db, "t1")["account_id"] == RENT
    assert poster.calls[0]["gst_rate_bps"] is None


def test_a_line_the_ca_coded_passes_with_the_gst_they_chose(poster):
    db = _db()
    _line(db, "t1", "NEFT CHARGES", account_id=CHARGES, category="Expense")
    out = svc.pass_entry(db, FIRM, "t1", actor_id="u-1", gst_rate_bps=1800, is_interstate=True)
    assert out["status"] == "passed"
    assert poster.calls[0]["gst_rate_bps"] == 1800 and poster.calls[0]["is_interstate"] is True


def test_a_refusal_lands_on_the_row_and_demotes_the_draft(monkeypatch):
    p = _Poster(refuse={"t1": "Financial year 2026-27 is locked."})
    monkeypatch.setattr(bes.bank_posting_service, "post", p)
    db = _db(); _rule(db); _line(db, "t1", "NEFT CHARGES")
    svc.redraft(db, FIRM, CLIENT)
    out = svc.pass_entry(db, FIRM, "t1", actor_id="u-1")
    assert out["status"] == "failed" and "locked" in out["reason"]
    r = _row(db, "t1")
    assert r["draft_error"] == "Financial year 2026-27 is locked."
    assert _state(db, "t1") == E.NEEDS_YOU
    # Nothing of the draft is left on the row as if a human had coded it.
    assert r["account_id"] is None and r["category"] is None and r["match_status"] == "unmatched"
    assert r["draft_source"] == "rule" and r["draft_account_id"] == CHARGES   # the proposal survives


def test_passing_a_line_with_nothing_on_it_is_refused_without_posting(poster):
    db = _db(); _line(db, "t1", "UNKNOWN", drafted_at="2026-04-15T00:00:00Z")
    out = svc.pass_entry(db, FIRM, "t1", actor_id="u-1")
    assert out["status"] == "failed" and "choose a ledger" in out["reason"]
    assert poster.calls == []


def test_a_short_document_draft_is_refused_and_sent_to_the_line(poster):
    db = _db()
    _line(db, "t1", "NEFT ACME", debit=0, credit=90000, draft_source="document",
          draft_grade="proposed", draft_entity_type="sales_invoice", draft_entity_id="inv-1",
          draft_reason="short by ₹10,000.00 — TDS at 10%?")
    out = svc.pass_entry(db, FIRM, "t1", actor_id="u-1")
    assert out["status"] == "failed" and "settle it from the line" in out["reason"]
    assert poster.calls == []


def test_passing_a_ready_document_draft_matches_then_posts(poster):
    db = _db()
    db.store["client_sales_invoices"] = [{"id": "inv-1", "firm_id": FIRM, "client_id": CLIENT}]
    _line(db, "t1", "NEFT ACME", debit=0, credit=100000, draft_source="document",
          draft_grade="ready", draft_entity_type="sales_invoice", draft_entity_id="inv-1")
    out = svc.pass_entry(db, FIRM, "t1", actor_id="u-1")
    assert out["status"] == "passed"
    r = _row(db, "t1")
    assert r["matched_entity_id"] == "inv-1" and r["category"] == "Customer Payment"
    assert poster.calls[0]["txn_id"] == "t1"


def test_passed_set_aside_and_covered_lines_are_skipped_not_failed(poster):
    db = _db()
    _line(db, "p", "x", match_status="posted", posted_journal_id="je")
    _line(db, "s", "x", match_status="ignored")
    _line(db, "c", "x", transfer_pair_id="p", transfer_is_primary=False)
    for tid in ("p", "s", "c"):
        assert svc.pass_entry(db, FIRM, tid, actor_id="u-1")["status"] == "skipped"
    assert poster.calls == []


# ── 8. transfers ─────────────────────────────────────────────────────────────

def test_passing_either_side_of_a_transfer_pairs_them_and_posts_the_paying_side(poster, monkeypatch):
    paired = []

    def fake_pair(db, firm_id, primary_id, counterpart_id, actor_id=None):
        paired.append((primary_id, counterpart_id))
        for tid, prim in ((primary_id, True), (counterpart_id, False)):
            other = counterpart_id if prim else primary_id
            (db.table("bank_transactions").update(
                {"transfer_pair_id": other, "transfer_is_primary": prim, "category": "Transfer"})
             .eq("id", tid).execute())
        return {}
    monkeypatch.setattr(bes.bank_transfer_service, "pair", fake_pair)

    db = _db()
    _line(db, "out", "TRF TO COSMOS", debit=10000, credit=0, draft_source="transfer",
          draft_grade="ready", draft_entity_type="bank_transaction", draft_entity_id="in")
    _line(db, "in", "TRF FROM HDFC", debit=0, credit=10000, draft_source="transfer",
          draft_grade="ready", draft_entity_type="bank_transaction", draft_entity_id="out")
    out = svc.pass_entry(db, FIRM, "in", actor_id="u-1")       # the RECEIVING side was clicked
    assert out["status"] == "passed" and out["posted_transaction_id"] == "out"
    assert paired == [("out", "in")]
    assert poster.calls[0]["txn_id"] == "out"
    assert _state(db, "in") == E.COVERED


# ── 6-7. pass_ready ──────────────────────────────────────────────────────────

def test_pass_ready_passes_only_ready_lines_in_chunks_and_never_a_proposed_one(poster):
    db = _db(); _rule(db)
    for i in range(3):
        _line(db, f"r{i}", "NEFT CHARGES", transaction_date=f"2026-04-1{i}")
    _teach(db, 2)
    _line(db, "prop", "UPI/DR/9/RAMESH KUMAR/HDFC", payee_name="RAMESH KUMAR")
    svc.redraft(db, FIRM, CLIENT)
    assert _state(db, "prop") == E.PROPOSED
    first = svc.pass_ready(db, FIRM, CLIENT, limit=2, actor_id="u-1")
    assert first["passed"] == 2 and first["remaining"] == 1
    second = svc.pass_ready(db, FIRM, CLIENT, limit=2, actor_id="u-1")
    assert second["passed"] == 1 and second["remaining"] == 0
    assert [c["txn_id"] for c in poster.calls] == ["r0", "r1", "r2"]
    assert _state(db, "prop") == E.PROPOSED


def test_a_failed_line_is_not_retried_by_the_next_chunk(monkeypatch):
    p = _Poster(refuse={"r0": "Financial year is locked."})
    monkeypatch.setattr(bes.bank_posting_service, "post", p)
    db = _db(); _rule(db)
    _line(db, "r0", "NEFT CHARGES", transaction_date="2026-04-10")
    _line(db, "r1", "NEFT CHARGES", transaction_date="2026-04-11")
    svc.redraft(db, FIRM, CLIENT)
    out = svc.pass_ready(db, FIRM, CLIENT, limit=1, actor_id="u-1")
    assert out["failed"] == 1 and out["remaining"] == 1
    out = svc.pass_ready(db, FIRM, CLIENT, limit=1, actor_id="u-1")
    assert out["passed"] == 1 and out["remaining"] == 0
    assert [c["txn_id"] for c in p.calls] == ["r0", "r1"]


def test_only_trusted_passes_a_trusted_rules_lines_as_the_person_who_trusted_it(poster):
    db = _db()
    _rule(db, rid="trusted", pattern="CHARGES", is_trusted=True, trusted_by="mgr-1",
          trusted_at="2026-09-03T00:00:00Z")
    _rule(db, rid="plain", pattern="RENT", account=RENT)
    _line(db, "chg", "NEFT CHARGES")
    _line(db, "rent", "NEFT RENT")
    svc.redraft(db, FIRM, CLIENT)
    assert svc.counts(db, FIRM, CLIENT)["trusted_pending"] == 1
    out = svc.pass_ready(db, FIRM, CLIENT, only_trusted=True, actor_id="exec-1")
    assert out["passed"] == 1 and out["remaining"] == 0
    assert poster.calls == [dict(txn_id="chg", actor_id="mgr-1", gst_rate_bps=None,
                                 is_interstate=False, actor_auth_id=None)]
    assert _row(db, "chg")["posted_by_rule_id"] == "trusted"
    assert _state(db, "rent") == E.READY and _row(db, "rent").get("posted_by_rule_id") is None


def test_untrusting_a_rule_stops_the_sweep_at_once(poster):
    db = _db()
    rule = _rule(db, is_trusted=True, trusted_by="mgr-1", trusted_at="2026-09-03T00:00:00Z")
    _line(db, "chg", "NEFT CHARGES")
    svc.redraft(db, FIRM, CLIENT)
    rule["is_trusted"] = False
    out = svc.pass_ready(db, FIRM, CLIENT, only_trusted=True)
    assert out == {"passed": 0, "failed": 0, "skipped": 0, "remaining": 0, "results": []}
    assert poster.calls == []


def test_a_click_pass_of_a_trusted_rules_line_is_the_clicker_not_the_rule(poster):
    db = _db()
    _rule(db, is_trusted=True, trusted_by="mgr-1", trusted_at="2026-09-03T00:00:00Z")
    _line(db, "chg", "NEFT CHARGES")
    svc.redraft(db, FIRM, CLIENT)
    svc.pass_ready(db, FIRM, CLIENT, actor_id="exec-1")
    assert poster.calls[0]["actor_id"] == "exec-1"
    assert _row(db, "chg").get("posted_by_rule_id") is None


# ── every read the screen makes, against the postgrest-faithful fake ─────────

def test_counts_list_redraft_and_pass_ready_never_select_twice(poster):
    """The regression behind the first production 500 after #395. Each of
    these went through _count(), which called .select() on a built query.
    Against the strict fake the old code raises AttributeError here."""
    db = _db(strict=True); _rule(db)
    _line(db, "t1", "NEFT CHARGES"); _line(db, "t2", "NOBODY KNOWS")
    out = svc.redraft(db, FIRM, CLIENT)
    assert out["drafted"] == 2 and out["remaining"] == 0
    c = svc.counts(db, FIRM, CLIENT)
    assert c["ready"] == 1 and c["needs_you"] == 1 and c["undrafted"] == 0
    rows, total = svc.list_entries(db, FIRM, CLIENT, state="to_do")
    assert total == 2 and len(rows) == 2
    rows, total = svc.list_entries(db, FIRM, CLIENT, state="ready", bank_account_id="ba-1")
    assert total == 1
    p = svc.pass_ready(db, FIRM, CLIENT, actor_id="u-1")
    assert p["passed"] == 1 and p["remaining"] == 0
    assert svc.redraft(db, FIRM, CLIENT, stale_before="2000-01-01T00:00:00+00:00")["remaining"] == 0


# ── the account filter, against a database that enforces the column's type ───

def test_an_account_with_no_statements_reads_empty_rather_than_refusing():
    """The Entries account filter, for a bank account nothing has been imported
    against yet.

    A bank line knows its statement, not its account, so an account filter is a
    statement filter — and an account with no statements yields no statement
    ids. What goes into that filter then still has to be a value a uuid column
    can hold: production answered 500 on every read (list, counts and
    pass-ready alike) for a client whose second bank account had been added but
    never imported from, because the fallback was the string "-".
    """
    firm = "11111111-1111-4111-8111-111111111111"
    client = "22222222-2222-4222-8222-222222222222"
    imported = "33333333-3333-4333-8333-333333333333"      # the account with a statement
    added_only = "44444444-4444-4444-8444-444444444444"    # the account with none
    stmt = "55555555-5555-4555-8555-555555555555"
    line = "66666666-6666-4666-8666-666666666666"

    db = TypedDB()
    db.store["chart_of_accounts"] = []
    db.store["bank_matching_rules"] = []
    db.store["bank_accounts"] = [
        {"id": imported, "firm_id": firm, "client_id": client, "bank_name": "HDFC Bank",
         "account_no": "50100234567890"},
        {"id": added_only, "firm_id": firm, "client_id": client, "bank_name": "Cosmos Bank",
         "account_no": "1234567899"},
    ]
    db.store["bank_statements"] = [
        {"id": stmt, "firm_id": firm, "client_id": client, "bank_account_id": imported},
    ]
    row = {"id": line, "firm_id": firm, "client_id": client, "statement_id": stmt,
           "description": "NEFT CHARGES", "transaction_date": "2026-04-15",
           "debit_paise": 59000, "credit_paise": 0, "match_status": "pending",
           "account_id": None, "category": None, "matched_entity_id": None,
           "matched_entity_type": None, "posted_journal_id": None, "posted_at": None,
           "draft_source": "rule", "draft_grade": "ready", "draft_account_id": CHARGES,
           "draft_label": "Bank Charges", "draft_error": None, "drafted_at": "2026-04-15T00:00:00Z"}
    row["entry_state"] = E.entry_state(row)
    db.store["bank_transactions"] = [row]

    # The account that HAS a statement reads its line, so the filter works.
    rows, total = svc.list_entries(db, firm, client, state="to_do", bank_account_id=imported)
    assert total == 1 and rows[0]["id"] == line

    # The one with none reads EMPTY — and builds no filter the database refuses.
    assert svc.list_entries(db, firm, client, state="to_do", bank_account_id=added_only) == ([], 0)
    c = svc.counts(db, firm, client, bank_account_id=added_only)
    assert (c["to_do"], c["ready"], c["undrafted"]) == (0, 0, 0)
    out = svc.pass_ready(db, firm, client, bank_account_id=added_only)
    assert (out["passed"], out["remaining"]) == (0, 0)


# ── the matched document's number ────────────────────────────────────────────

def test_a_matched_line_carries_the_document_number_a_ca_knows_it_by():
    """"against an invoice" is the same sentence for every matched line on the
    page. The document's own number is what distinguishes them, and what lets
    a CA check a match without opening it."""
    db = _db()
    db.store["client_sales_invoices"] = [
        {"id": "inv-1", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "APEX/25-26/0042"},
        {"id": "inv-2", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": "APEX/25-26/0043"},
    ]
    db.store["purchase_bills"] = [
        {"id": "bill-1", "firm_id": FIRM, "client_id": CLIENT, "bill_no": "OM/2026/117"},
    ]
    _line(db, "a", "NEFT CR SILVER OAK", debit=0, credit=142543,
          match_status="matched", matched_entity_type="sales_invoice", matched_entity_id="inv-1")
    _line(db, "b", "NEFT CR URBAN EDGE", debit=0, credit=52363,
          match_status="matched", matched_entity_type="sales_invoice", matched_entity_id="inv-2")
    _line(db, "c", "NEFT DR OM STATIONERS",
          match_status="matched", matched_entity_type="purchase_bill", matched_entity_id="bill-1")
    _line(db, "d", "NEFT CHARGES")                       # nothing matched
    _line(db, "e", "ADJUSTMENT", match_status="matched",  # a match with no document
          matched_entity_type="manual", matched_entity_id="whatever")

    rows, _ = svc.list_entries(db, FIRM, CLIENT, state="all")
    got = {r["id"]: r["matched_document_no"] for r in rows}
    assert got == {"a": "APEX/25-26/0042", "b": "APEX/25-26/0043", "c": "OM/2026/117",
                   "d": None, "e": None}


def test_the_document_numbers_are_one_query_per_type_not_one_per_row():
    """Fifty matched lines on a page must not be fifty round trips to read
    fifty short strings — the same bargain _attach_splits makes."""
    db = _db()
    db.store["client_sales_invoices"] = [
        {"id": f"inv-{i}", "firm_id": FIRM, "client_id": CLIENT, "invoice_no": f"INV-{i}"}
        for i in range(8)
    ]
    for i in range(8):
        _line(db, f"t{i}", f"RECEIPT {i}", debit=0, credit=1000 + i, match_status="matched",
              matched_entity_type="sales_invoice", matched_entity_id=f"inv-{i}")

    reads: list[str] = []
    original = db.table

    def counting(name):
        reads.append(name)
        return original(name)

    db.table = counting
    rows, _ = svc.list_entries(db, FIRM, CLIENT, state="all")
    db.table = original

    assert [r["matched_document_no"] for r in rows] == [f"INV-{i}" for i in range(8)]
    assert reads.count("client_sales_invoices") == 1, \
        f"read the invoice table {reads.count('client_sales_invoices')} times for 8 rows"
