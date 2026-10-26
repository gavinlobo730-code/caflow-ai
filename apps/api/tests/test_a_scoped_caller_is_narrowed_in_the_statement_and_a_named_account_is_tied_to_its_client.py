"""What the privileged client lost, put back in the application: the caller's clients (POST-A-339, found by the independent review).

THE PREMISE
    Until the API read the bank, payroll and document tables with its privileged client, a caller who was not a Partner was
    narrowed to the clients assigned to them by the DATABASE's row policy, on every statement. The privileged client carries no row
    security, so the same narrowing has to be made by the application, and it has to be made where the statement is made. Three
    shapes were found missing:

    1. A ROUTE THAT NAMES AN ACCOUNT BUT LEAVES THE CLIENT OPTIONAL. `GET /api/banking/register?bank_account_id=` asked
       `assert_client_access` only `if client_id:`, and the service checked the client only `if client_id and ...`, so a caller
       assigned to client A who named client B's account and no client read B's whole register. The account's OWN client is what
       has to be asked. The rule below is over the route table: a banking route that takes an account and an optional client either
       asks the account row or is a list whose statement is narrowed.
    2. A LIST THAT CUTS ITS WINDOW BEFORE IT NARROWS. A scoped caller's list was read for the whole firm and filtered afterwards, so
       the row cap PostgREST carries (about a thousand, silently) or the `limit` of a window applied to the firm's rows and the
       caller's own could be crowded out, and `has_more` described the firm. `core.authz.scope_query_to_clients` puts the caller's
       clients INTO the statement; the filter after it stays as the second line.
    3. A LOOKUP BY ID THAT STOPS AT THE FIRM. A bank line's attachment named a document by id and asked only its firm; a document of
       a client the caller is not assigned to was attached, and the difference between a 404 and a 200 told whether such an id exists.

    Two more are held beside them because they were found in the same read: the split-replacement function is executable by the
    service role ALONE (migration 256, production's ACL read on 26-10-2026) and the splits route was calling it with the caller's own
    sign-in, and a statement's delete check read its lines unpaged, so a posted line past the thousandth was never seen.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

import routers.banking as rb
from core.authz import _NO_CLIENT, scope_query_to_clients

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "role": "Executive"}


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    """A recording PostgREST query: every verb is noted, the rows are those the equality filters keep."""

    def __init__(self, store, table, log):
        self.s, self.t, self.log = store, table, log
        self.eqs, self.ins, self.ops = [], [], []
        self.lim = None

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.eqs.append((k, v)); return self
    def in_(self, k, vs): self.ins.append((k, list(vs))); return self
    def is_(self, *_a): return self
    def order(self, *_a, **_k): return self
    def limit(self, n): self.lim = n; return self
    def gte(self, *_a): return self
    def lte(self, *_a): return self

    def execute(self):
        self.log.append({"table": self.t, "eq": dict(self.eqs), "in": dict(self.ins)})
        rows = [r for r in self.s.get(self.t, [])
                if all(r.get(k) == v for k, v in self.eqs) and all(r.get(k) in vs for k, vs in self.ins)]
        return _Resp(rows[: self.lim] if self.lim else rows)


class FakeDB:
    def __init__(self, store):
        self.store, self.log = store, []

    def table(self, name):
        return _Q(self.store, name, self.log)


# ── the helper ──────────────────────────────────────────────────────────────────────────────────────────────────────
class _Probe:
    def __init__(self):
        self.calls = []

    def in_(self, column, values):
        self.calls.append((column, values))
        return self


def test_none_is_no_restriction_and_the_query_comes_back_untouched():
    q = _Probe()
    assert scope_query_to_clients(q, None) is q and q.calls == []


def test_a_set_of_clients_is_put_into_the_statement_sorted():
    q = _Probe()
    scope_query_to_clients(q, {"b", "a", "c"})
    assert q.calls == [("client_id", ["a", "b", "c"])]


def test_an_empty_set_is_no_clients_and_never_no_filter():
    q = _Probe()
    scope_query_to_clients(q, set())
    assert q.calls == [("client_id", [_NO_CLIENT])], "an empty set must name a client nobody has, not skip the filter"


# ── the lists: the caller's clients go into the statement, and a named client wins ───────────────────────────────────────
ROWS = {
    "bank_statements": [{"id": "s1", "firm_id": FIRM, "client_id": MINE}, {"id": "s2", "firm_id": FIRM, "client_id": THEIRS}],
    "bank_transactions": [{"id": "t1", "firm_id": FIRM, "client_id": MINE, "statement_id": "s1"},
                          {"id": "t2", "firm_id": FIRM, "client_id": THEIRS, "statement_id": "s2"}],
    "bank_reconciliations": [{"id": "r1", "firm_id": FIRM, "client_id": MINE}, {"id": "r2", "firm_id": FIRM, "client_id": THEIRS}],
    "bank_statement_column_mappings": [{"id": "m1", "firm_id": FIRM, "client_id": MINE}, {"id": "m2", "firm_id": FIRM, "client_id": THEIRS}],
}


def _ids(rows):
    return sorted(r["id"] for r in rows)


def test_statements_for_a_scoped_caller_are_narrowed_in_the_statement():
    from services.banking_service import banking_service
    db = FakeDB(ROWS)
    out = banking_service.list_statements(db, FIRM, None, allowed_client_ids={MINE})
    assert _ids(out) == ["s1"] and db.log[0]["in"] == {"client_id": [MINE]}


def test_statements_for_a_partner_are_not_narrowed():
    from services.banking_service import banking_service
    db = FakeDB(ROWS)
    assert _ids(banking_service.list_statements(db, FIRM, None, allowed_client_ids=None)) == ["s1", "s2"] and db.log[0]["in"] == {}


def test_a_named_client_is_filtered_by_equality_and_the_set_is_not_added():
    from services.banking_service import banking_service
    db = FakeDB(ROWS)
    banking_service.list_statements(db, FIRM, MINE, allowed_client_ids={MINE, THEIRS})
    assert db.log[0]["eq"].get("client_id") == MINE and db.log[0]["in"] == {}


def test_transactions_for_a_scoped_caller_are_narrowed_in_the_statement():
    from services.banking_service import banking_service
    db = FakeDB(ROWS)
    out = banking_service.list_transactions(db, FIRM, allowed_client_ids={MINE})
    assert _ids(out) == ["t1"] and db.log[0]["in"] == {"client_id": [MINE]}


def test_a_caller_with_no_clients_reads_nothing():
    from services.banking_service import banking_service
    db = FakeDB(ROWS)
    assert banking_service.list_transactions(db, FIRM, allowed_client_ids=set()) == []


def test_reconciliations_for_a_scoped_caller_are_narrowed_in_the_statement():
    from services.bank_reconciliation_service import bank_reconciliation_service
    db = FakeDB({"bank_reconciliations": []})          # the statement is what is observed; a session row needs a dozen more columns
    bank_reconciliation_service.list_sessions(db, FIRM, None, None, allowed_client_ids={MINE})
    assert db.log[0]["in"] == {"client_id": [MINE]}
    db = FakeDB({"bank_reconciliations": []})
    bank_reconciliation_service.list_sessions(db, FIRM, MINE, None, allowed_client_ids={MINE, THEIRS})
    assert db.log[0]["eq"].get("client_id") == MINE and db.log[0]["in"] == {}


def test_column_mappings_are_narrowed_before_the_window_is_cut():
    from services import bank_column_mapping_service as cm
    db = FakeDB(ROWS)
    rows = cm.list_mappings(db, FIRM, None, None, limit=1, allowed_client_ids={MINE})
    assert _ids(rows) == ["m1"] and db.log[0]["in"] == {"client_id": [MINE]}


def test_documents_are_narrowed_in_the_statement(monkeypatch):
    """Mock mode answers from a module list, so the statement is observed through a fake client."""
    from repositories import document_repository as dr
    store = {"documents": [{"id": "d1", "firm_id": FIRM, "client_id": MINE}, {"id": "d2", "firm_id": FIRM, "client_id": THEIRS}]}
    db = FakeDB(store)
    monkeypatch.setattr(dr, "_USE_MOCK", False)
    monkeypatch.setattr(dr, "_get_db", lambda: db)
    monkeypatch.setattr(dr, "fetch_all", lambda build, *a, **kw: build().execute().data)
    out = dr.DocumentRepository().find_all(firm_id=FIRM, allowed_client_ids={MINE})
    assert [d["id"] for d in out] == ["d1"] and db.log[0]["in"] == {"client_id": [MINE]}


def test_the_routes_hand_the_callers_clients_to_the_lists(monkeypatch):
    """The service takes the set; the route has to send it. A scoped caller's clients come from `effective_client_ids`."""
    import inspect as _i
    for fn, needle in ((rb.list_statements, "list_statements"), (rb.list_transactions, "list_transactions"),
                       (rb.list_reconciliations, "list_sessions"), (rb.list_column_mappings, "list_mappings")):
        src = _i.getsource(fn)
        assert "allowed_client_ids=effective_client_ids(current_user)" in src, f"{fn.__name__} does not hand its caller's clients to {needle}"
    import routers.documents as docs
    assert "allowed_client_ids=" in inspect.getsource(docs.list_documents)


# ── a route that names an account ties the account to the caller's client ───────────────────────────────────────────────
def _optional(sig, name):
    p = sig.parameters.get(name)
    if p is None:
        return False
    d = p.default
    if d is inspect.Parameter.empty:
        return False
    return getattr(d, "default", d) is None


#: banking routes that name an account/statement, leave the client optional, and are LISTS: their statement is narrowed to the
#: caller's clients (above) and their rows are filtered after it, so there is no single row to tie.
LISTS = {
    ("GET", "/api/banking/statements/column-mappings"): "a list: narrowed in the statement, rows filtered after",
    ("GET", "/api/banking/transactions"): "a list: narrowed in the statement, rows filtered after",
    ("GET", "/api/banking/reconciliations"): "a list: narrowed in the statement, rows filtered after",
}

ROW_GUARDS = ("_assert_row_scope(", "_assert_txn_scope(", "_assert_statement_scope(", "_assert_recon_scope(")


def _routes_naming_an_account_with_an_optional_client():
    from main import app
    out = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api/banking"):
            continue
        sig = inspect.signature(r.endpoint)
        names = set(sig.parameters)
        if not (names & {"bank_account_id", "statement_id"}):
            continue
        if not _optional(sig, "client_id"):
            continue
        for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
            out.append((m, path, r.endpoint))
    return out


def test_the_sweep_finds_the_route_the_review_found():
    found = {(m, p) for m, p, _e in _routes_naming_an_account_with_an_optional_client()}
    assert ("GET", "/api/banking/register") in found, found
    assert len(found) >= 4, found


@pytest.mark.parametrize("method,path,endpoint", [pytest.param(m, p, e, id=f"{m} {p}")
                                                  for m, p, e in _routes_naming_an_account_with_an_optional_client()])
def test_a_route_that_names_an_account_and_leaves_the_client_optional_asks_the_account_or_is_a_narrowed_list(method, path, endpoint):
    if (method, path) in LISTS:
        assert "allowed_client_ids=effective_client_ids(current_user)" in inspect.getsource(endpoint), \
            f"{method} {path} is a list but does not narrow its statement to the caller's clients"
        return
    src = inspect.getsource(endpoint)
    assert any(g in src for g in ROW_GUARDS), (
        f"{method} {path} names an account or a statement and leaves client_id optional, and never asks the row's own client. "
        "A caller assigned to one client could name another client's account and no client of their own.")


def test_the_register_refuses_an_account_of_a_client_the_caller_may_not_see_when_no_client_is_named(monkeypatch):
    db = FakeDB({"bank_accounts": [{"id": "acct-b", "firm_id": FIRM, "client_id": THEIRS}]})
    asked = []

    def deny(user, client_id, *, detail="Not found"):
        asked.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail=detail)

    reached = []
    monkeypatch.setattr(rb, "assert_client_access", deny)
    monkeypatch.setattr(rb, "_db", lambda: db)
    monkeypatch.setattr(rb.bank_register_service, "register", lambda *a, **k: reached.append(1) or {})
    with pytest.raises(HTTPException) as e:
        rb.bank_register(bank_account_id="acct-b", client_id=None, date_from=None, date_to=None, status="all", q=None,
                         sort="date", desc=False, limit=200, offset=0, current_user=USER)
    assert e.value.status_code == 404 and THEIRS in asked and not reached


def test_the_register_still_serves_the_callers_own_account(monkeypatch):
    db = FakeDB({"bank_accounts": [{"id": "acct-a", "firm_id": FIRM, "client_id": MINE}]})
    monkeypatch.setattr(rb, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(rb, "_db", lambda: db)
    monkeypatch.setattr(rb.bank_register_service, "register", lambda *a, **k: {"lines": []})
    out = rb.bank_register(bank_account_id="acct-a", client_id=None, date_from=None, date_to=None, status="all", q=None,
                           sort="date", desc=False, limit=200, offset=0, current_user=USER)
    assert out["success"] is True


# ── an attachment names a document of the bank line's own client ────────────────────────────────────────────────────────
def test_a_document_of_another_client_cannot_be_attached_to_a_bank_line():
    from services.bank_batch_service import bank_batch_service
    db = FakeDB({"documents": [{"id": "doc-b", "firm_id": FIRM, "client_id": THEIRS}, {"id": "doc-a", "firm_id": FIRM, "client_id": MINE}]})
    with pytest.raises(HTTPException) as e:
        bank_batch_service._assert_document_in_firm(db, FIRM, "doc-b", client_id=MINE)
    assert e.value.status_code == 404
    bank_batch_service._assert_document_in_firm(db, FIRM, "doc-a", client_id=MINE)       # the line's own client: allowed


def test_add_attachment_hands_the_lines_client_to_the_document_check(monkeypatch):
    from services.bank_batch_service import bank_batch_service
    db = FakeDB({"bank_transactions": [{"id": "t1", "firm_id": FIRM, "client_id": MINE, "attachments": []}],
                 "documents": [{"id": "doc-b", "firm_id": FIRM, "client_id": THEIRS}]})
    with pytest.raises(HTTPException) as e:
        bank_batch_service.add_attachment(db, FIRM, "t1", "x.pdf", document_id="doc-b")
    assert e.value.status_code == 404


# ── the split replacement is made with the privileged client ─────────────────────────────────────────────────────────────
def test_the_split_replacement_is_called_through_the_privileged_client(monkeypatch):
    """The function is executable by the service role ALONE; on the caller's own sign-in the database refuses it."""
    from services import bank_split_service as bs

    called = []

    class _Rpc:
        def execute(self):
            return _Resp(None)

    class _Priv:
        def rpc(self, name, params):
            called.append(name)
            return _Rpc()

    svc = bs.BankSplitService()
    monkeypatch.setattr(svc, "_get_txn", lambda *a, **k: {"id": "t1", "client_id": MINE, "debit_paise": 0, "credit_paise": 0})
    monkeypatch.setattr(bs, "privileged_for", lambda db: _Priv())

    class _Boom:
        def rpc(self, *a, **k):
            raise AssertionError("the caller's own client was used for the split replacement")

    monkeypatch.setattr(svc, "get", lambda *a, **k: {})
    svc.replace(_Boom(), FIRM, "t1", [])
    assert called == ["replace_bank_transaction_splits"]


# ── a statement is deleted only after EVERY one of its lines has been read ──────────────────────────────────────────────
def test_a_posted_line_past_the_thousandth_stops_the_deletion_of_its_statement(monkeypatch):
    lines = [{"id": f"t{i:05d}", "match_status": "unmatched", "posted_journal_id": None} for i in range(1500)]
    lines.append({"id": "t99999", "match_status": "posted", "posted_journal_id": "j1"})
    seen = {}

    def fake_fetch_all(build, **kw):
        seen.update(kw)
        return lines

    class _Statement(FakeDB):
        pass

    db = FakeDB({"bank_statements": [{"id": "s1", "firm_id": FIRM, "client_id": MINE}]})
    deleted = []
    monkeypatch.setattr(rb, "_db", lambda: db)
    monkeypatch.setattr(rb, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(rb, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(rb, "log_event", lambda *a, **k: deleted.append("logged"))
    with pytest.raises(HTTPException) as e:
        rb.delete_statement(statement_id="s1", current_user=USER)
    assert e.value.status_code == 422 and "already posted" in e.value.detail
    assert deleted == [] and seen.get("key") == "id"


def test_the_delete_check_reads_the_lines_through_the_pager():
    src = inspect.getsource(rb.delete_statement)
    assert "fetch_all(" in src and '.table("bank_transactions").select("*")' in src
