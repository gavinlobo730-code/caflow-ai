"""The bank exception rules finally have a reader, and it does not gate.

`domain/banking/exceptions.py` has been 315 lines of careful rules with no
importer but its own test since it was written, and its docstring named a
collaborator — `services/bank_exception_service.py` — that did not exist. So no
flag was ever raised and no partner ever saw one.

Two properties are worth a test more than any particular flag is, because both
are decisions somebody could undo with one line:

  * this service NEVER blocks or reverses a posting, and
  * the read is bounded by the PERIOD rather than by the ledger.

The rules themselves are already tested in test_bank_exceptions.py; nothing
here re-tests a threshold, which would be a second place they live.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date

import pytest

from domain.banking import exceptions as rules
from services import bank_exception_service as svc

API = pathlib.Path(__file__).resolve().parent.parent


# ── a fake that counts what it was asked for ─────────────────────────────────

class _Q:
    def __init__(self, table, store, log):
        self.table, self.store, self.log = table, store, log
        self.filters: list[tuple] = []

    def select(self, *_a, **_k):
        return self

    def _f(self, op, col, val):
        self.filters.append((op, col, val))
        return self

    def eq(self, c, v): return self._f("eq", c, v)
    def lt(self, c, v): return self._f("lt", c, v)
    def gt(self, c, v): return self._f("gt", c, v)
    def gte(self, c, v): return self._f("gte", c, v)
    def lte(self, c, v): return self._f("lte", c, v)
    def in_(self, c, v): return self._f("in", c, v)
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def range(self, *_a, **_k): return self

    def execute(self):
        self.log.append((self.table, tuple(self.filters)))
        rows = list(self.store.get(self.table, []))
        for op, col, val in self.filters:
            if op == "eq":
                rows = [r for r in rows if str(r.get(col)) == str(val)]
            elif op == "in":
                rows = [r for r in rows if str(r.get(col)) in {str(x) for x in val}]
            elif op == "gte":
                rows = [r for r in rows if str(r.get(col))[:10] >= val]
            elif op == "lte":
                rows = [r for r in rows if str(r.get(col))[:10] <= val]
            elif op == "lt":
                rows = [r for r in rows if str(r.get(col))[:10] < val]
            elif op == "gt":
                rows = [r for r in rows if str(r.get(col)) > str(val)]
        return type("R", (), {"data": rows})()


class _DB:
    def __init__(self, store):
        self.store, self.log = store, []

    def table(self, name):
        return _Q(name, self.store, self.log)


def _txn(tid, day, *, debit=0, credit=0, payee="Acme", desc="NEFT",
         status="posted", account_id="acct-1", **extra):
    row = {"id": tid, "firm_id": "firm-1", "client_id": "client-1",
           "transaction_date": f"2026-06-{day:02d}", "description": desc,
           "payee_name": payee, "debit_paise": debit, "credit_paise": credit,
           "account_id": account_id, "category": None, "match_status": status,
           "matched_entity_type": None, "matched_entity_id": None,
           "statement_id": "stmt-1"}
    row.update(extra)
    return row


def _run(txns, **kw):
    db = _DB({"bank_transactions": txns, **kw.pop("store", {})})
    out = svc.review_list(db, "firm-1", "client-1", from_date="2026-06-01",
                          to_date="2026-06-30", today=date(2026, 7, 1), **kw)
    return out, db


# ── it reports ───────────────────────────────────────────────────────────────

def test_it_flags_a_material_line_and_leaves_an_ordinary_one_alone():
    big = _txn("t1", 10, debit=20_000_000)          # ₹2,00,000, above materiality
    small = _txn("t2", 11, debit=5_000)             # ₹50
    # An earlier line, so the two history rules are answerable and the ordinary
    # line is genuinely ordinary. Without one this client's earliest period
    # would withhold them — see the test below, which is the point.
    earlier = dict(_txn("t0", 1, debit=1_000), transaction_date="2026-05-01")
    out, _ = _run([big, small, earlier])
    assert out["reviewed_count"] == 2
    assert [f["transaction_id"] for f in out["flagged"]] == ["t1"]
    assert out["flagged"][0]["exceptions"][0]["code"] == "above_materiality"


def test_the_earliest_period_withholds_the_two_history_rules():
    """FOUND BY WRITING THE TEST ABOVE. With no earlier lines every payee is a
    first payee and every account one not used before, so both rules fire on
    every row and the review list is the statement back again. True of
    everything is information about nothing."""
    out, _ = _run([_txn("t1", 10, debit=1_000, payee="A", account_id="x"),
                   _txn("t2", 11, debit=2_000, payee="B", account_id="y")])
    assert out["flagged"] == []
    assert [g["code"] for g in out["gaps"]] == [svc.GAP_HISTORY_EMPTY]


def test_an_empty_history_and_a_truncated_one_are_different_answers():
    """"There is nothing to have seen" is a different thing to tell a partner
    from "we could not tell" — the second sends them to widen a search."""
    empty = svc.GAP_SENTENCES[svc.GAP_HISTORY_EMPTY]
    truncated = svc.GAP_SENTENCES[svc.GAP_HISTORY_INCOMPLETE]
    assert empty != truncated
    assert "earliest period" in empty
    assert "could not be established" in truncated


def test_an_unposted_line_is_not_reviewed():
    """Risk-based review tests work that was DONE. What is still waiting is the
    Entries tab's job and already has a screen."""
    out, _ = _run([_txn("t1", 10, debit=20_000_000, status="matched")])
    assert out["reviewed_count"] == 0 and out["flagged"] == []


def test_the_answer_says_what_it_was_measured_against():
    """Materiality is a judgement. A list that does not carry its thresholds
    cannot be argued with — the domain module's own point."""
    out, _ = _run([_txn("t1", 10, debit=1)])
    assert out["policy"]["materiality_paise"] == rules.ExceptionPolicy().materiality_paise
    assert out["policy"]["duplicate_window_days"] == rules.ExceptionPolicy().duplicate_window_days


def test_worst_first_and_stable_under_it():
    rows = [_txn("t2", 20, debit=20_000_000, payee="Acme"),
            _txn("t1", 10, debit=20_000_000, payee="Beta"),
            _txn("t3", 15, debit=6_000_000, desc="ATM CASH WDL", payee="Self")]
    out, _ = _run(rows)
    sev = [f["exceptions"][0]["severity"] for f in out["flagged"]]
    assert sev == sorted(sev, key=lambda s: rules.SEVERITY_ORDER[s])
    highs = [f["transaction_id"] for f in out["flagged"]
             if f["exceptions"][0]["severity"] == "high"]
    assert highs == sorted(highs, key=lambda i: {"t3": "15", "t1": "10", "t2": "20"}[i])


# ── the margin is for siblings only ──────────────────────────────────────────

def test_a_line_outside_the_period_is_a_sibling_and_never_a_subject():
    """The duplicate rule compares each line with its neighbours, so the fetch
    reaches either side of the period. If the margin also supplied SUBJECTS,
    asking about June would report May's lines back."""
    inside = _txn("t1", 2, debit=100_000, payee="Landlord")
    outside = dict(_txn("t9", 1, debit=100_000, payee="Landlord"),
                   transaction_date="2026-05-30")
    out, _ = _run([inside, outside])
    assert out["reviewed_count"] == 1
    ids = [f["transaction_id"] for f in out["flagged"]]
    assert ids == ["t1"], "the May line must not be reviewed"
    # ...and it WAS used as a sibling, which is the reason it was fetched.
    assert any(e["code"] == "duplicate_suspect"
               for f in out["flagged"] for e in f["exceptions"])


# ── what it could not ask, it says ───────────────────────────────────────────

def test_an_unreadable_history_withholds_the_two_rules_that_need_it():
    """Running them on a partial history would report payees as "first time in
    this client's bank history" that are not — a false sentence on a list whose
    whole value is that the few rows in it can be trusted."""
    def boom(*_a, **_k):
        raise RuntimeError("history unavailable")

    earlier = dict(_txn("t0", 1, debit=1_000, payee="Someone Else",
                        account_id="used-before"), transaction_date="2026-05-01")
    original = svc._seen_before
    svc._seen_before = boom
    try:
        out, _ = _run([_txn("t1", 10, debit=1_000, payee="Brand New Payee",
                            account_id="never-used"), earlier])
    finally:
        svc._seen_before = original

    assert [g["code"] for g in out["gaps"]] == [svc.GAP_HISTORY_INCOMPLETE]
    codes = {e["code"] for f in out["flagged"] for e in f["exceptions"]}
    assert "new_payee" not in codes and "unusual_account" not in codes


def test_a_complete_history_does_answer_them():
    """The negative half: withholding must be caused by the GAP, not by the
    rules being unreachable from here."""
    earlier = dict(_txn("t0", 1, debit=1_000, payee="Someone Else",
                        account_id="used-before"), transaction_date="2026-05-01")
    out, _ = _run([_txn("t1", 10, debit=1_000, payee="Brand New Payee",
                        account_id="never-used"), earlier])
    assert out["gaps"] == []
    codes = {e["code"] for f in out["flagged"] for e in f["exceptions"]}
    assert "new_payee" in codes and "unusual_account" in codes


def test_a_payee_seen_earlier_is_not_new():
    earlier = dict(_txn("t0", 1, debit=1_000, payee="Acme"),
                   transaction_date="2025-01-05")
    out, _ = _run([_txn("t1", 10, debit=1_000, payee="Acme"), earlier])
    codes = {e["code"] for f in out["flagged"] for e in f["exceptions"]}
    assert "new_payee" not in codes


def test_the_gap_sentences_are_different_and_name_what_was_not_asked():
    a = svc.GAP_SENTENCES[svc.GAP_HISTORY_INCOMPLETE]
    b = svc.GAP_SENTENCES[svc.GAP_DOCUMENTS_UNREAD]
    assert a != b
    assert "were NOT applied" in a and "were not applied" in b


# ── the two properties that are decisions, not details ───────────────────────

def test_nothing_here_gates_a_posting():
    """`blocking` is computed by the rules and consumed by nobody. Asserted on
    the SOURCE as well as the answer: a gate is one line somebody could add,
    and the whole feature's safety argument is that it advises."""
    # Asserted on the AST rather than on the text: this module's own docstring
    # NAMES blocks_posting to explain why it is not called, and a substring
    # check would fail on the explanation. The rule is "never calls it", not
    # "never mentions it" — the guard-names-a-spelling trap, again.
    src = (API / "services" / "bank_exception_service.py").read_text()
    tree = ast.parse(src)
    called = {n.func.attr if isinstance(n.func, ast.Attribute) else
              getattr(n.func, "id", "")
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "blocks_posting" not in called
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                for a in n.names}
    assert "blocks_posting" not in imported
    for verb in ("update", "insert", "upsert", "delete", "rpc"):
        assert verb not in called, f"the review list must not {verb} anything"

    router = ast.parse((API / "routers" / "banking.py").read_text())
    fn = next(n for n in ast.walk(router)
              if isinstance(n, ast.FunctionDef) and n.name == "worth_a_look")
    router_calls = {c.func.attr if isinstance(c.func, ast.Attribute) else
                    getattr(c.func, "id", "")
                    for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "blocks_posting" not in router_calls
    # It still SHOWS the rules' own judgement, which is the point of keeping it.
    out, _ = _run([_txn("t1", 10, debit=20_000_000)])
    assert out["flagged"][0]["exceptions"][0]["blocking"] is True


def test_the_period_is_required_and_keyword_only():
    """An optional period is how a report comes to read the whole ledger — the
    BANK-07 shape. Asserted on the SIGNATURE so a default added later fails."""
    import inspect
    sig = inspect.signature(svc.review_list)
    for name in ("from_date", "to_date"):
        p = sig.parameters[name]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, name
        assert p.default is inspect.Parameter.empty, f"{name} must have no default"
    with pytest.raises(TypeError):
        svc.review_list(_DB({}), "firm-1", "client-1")     # type: ignore[call-arg]


def test_every_read_is_bounded_by_the_period_or_by_a_small_set():
    """The fetch must not be proportional to the ledger. Every read of
    `bank_transactions` here either carries a date bound or is the history
    probe, which is `.in_()` over the PERIOD's own payees and accounts."""
    out, db = _run([_txn(f"t{i}", 10, debit=1_000, payee=f"P{i}") for i in range(5)])
    assert out["reviewed_count"] == 5
    reads = [f for (t, f) in db.log if t == "bank_transactions"]
    assert reads, "no read was made at all — the fake is not being exercised"
    for filters in reads:
        ops = {(op, col) for op, col, _ in filters}
        dated = any(op in ("gte", "lte", "lt") and col == "transaction_date"
                    for op, col in ops)
        probed = any(op == "in" and col in ("payee_name", "account_id")
                     for op, col in ops)
        assert dated or probed, f"an unbounded read of bank_transactions: {filters}"


def test_every_read_carries_the_firm_filter():
    """The service-role key bypasses RLS, so the app-layer filter is the
    primary isolation control (CLAUDE.md)."""
    _run([_txn("t1", 10, debit=1_000)])
    _, db = _run([_txn("t1", 10, debit=1_000)])
    for table, filters in db.log:
        assert any(op == "eq" and col == "firm_id" for op, col, _ in filters), \
            f"{table} was read without a firm_id filter"
