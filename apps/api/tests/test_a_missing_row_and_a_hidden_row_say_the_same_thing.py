"""A row that is not there and a row in somebody else's client answer with the SAME words (POST-A-017).

WHY THIS FILE EXISTS
    Both answers were already a 404, chosen so that the status code is not an oracle for which ids exist. But a handler that
    looked a row up by id said "Invoice <id> not found" for a missing row and let `assert_client_access` say its generic
    "Not found" for a row in a client the caller is not assigned to. Same status, different body: a caller who knows an id
    (they leak, in URLs, exports and support threads) could tell a real one from an invented one by the wording alone.

THE RULE, AND WHY IT IS THIS SHAPE
    In a route handler, a function that raises a 404 with its own wording for a looked-up row, and THEN calls
    `assert_client_access` on that row's client, must give the call the same wording (`detail=`). The comparison is by
    position: an assertion placed BEFORE any such lookup runs on a client the caller supplied, so it says nothing about a row's
    existence and is not an oracle.

    The check is derived from every router's own source, so a new handler is held to it without being listed. Two functions are
    exempt and each exemption says why; the negative control proves the rule still fires.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi import HTTPException

ROUTERS = pathlib.Path(__file__).resolve().parent.parent / "routers"

# (module, function): why this one asserts after a differently-worded 404 and is still not an oracle.
EXEMPT = {
    ("ai_copilot_v2.py", "send_message"): (
        "the 404 is for the CALLER's own conversation (the lookup is filtered by the caller's user id), and the assertion that "
        "follows is on the client the caller named in the payload; neither wording says anything about another person's row"
    ),
    ("workflow_builder.py", "manually_trigger"): (
        "the assertion is on the client in the request payload, not on the template that was looked up, so the template's "
        "wording is not compared with a hidden-client answer"
    ),
}


def _call_name(call: ast.Call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def _not_found_detail(node: ast.AST):
    """The `detail` expression of a `raise HTTPException(404, ...)`, or the sentinel False when the node is not one."""
    if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
        return False
    c = node.exc
    if _call_name(c) != "HTTPException":
        return False
    kw = {k.arg: k.value for k in c.keywords}
    status = kw.get("status_code") or (c.args[0] if c.args else None)
    if not (isinstance(status, ast.Constant) and status.value == 404):
        return False
    return kw.get("detail") or (c.args[1] if len(c.args) > 1 else None)


def offenders(source: str, filename: str = "<src>") -> list[tuple[str, int]]:
    """(function, line of the assertion) for every assertion that follows a differently worded 404 and does not repeat it."""
    out = []
    for fn in ast.walk(ast.parse(source, filename)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        raises = []
        asserts = []
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and _call_name(n) == "assert_client_access":
                asserts.append(n)
            elif isinstance(n, ast.Raise):
                d = _not_found_detail(n)
                if d is not False and d is not None:
                    raises.append((n.lineno, d))
        for call in asserts:
            given = {k.arg: k.value for k in call.keywords}.get("detail")
            earlier = [d for line, d in raises if line < call.lineno
                       and not (isinstance(d, ast.Constant) and d.value == "Not found")]
            if not earlier:
                continue
            if given is not None and any(ast.dump(given) == ast.dump(d) for d in earlier):
                continue
            out.append((fn.name, call.lineno))
    return out


def test_every_router_says_the_same_words_for_a_missing_row_and_a_hidden_one():
    found = []
    for path in sorted(ROUTERS.glob("*.py")):
        for name, line in offenders(path.read_text(), str(path)):
            if (path.name, name) not in EXEMPT:
                found.append(f"{path.name}:{line} {name}")
    assert not found, (
        "a handler answers a missing row in one sentence and a row in an unassigned client in another; pass the same text to "
        "assert_client_access(detail=...): " + ", ".join(found)
    )


def test_the_rule_is_not_vacuous_it_sees_the_helpers_that_were_fixed():
    # The rule only means something if it has looked at handlers that carry both a custom 404 and an assertion.
    seen = 0
    for path in ROUTERS.glob("*.py"):
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                has_assert = any(isinstance(n, ast.Call) and _call_name(n) == "assert_client_access"
                                 and any(k.arg == "detail" for k in n.keywords) for n in ast.walk(fn))
                if has_assert:
                    seen += 1
    assert seen >= 20, f"only {seen} handlers pass detail= to assert_client_access; the sweep fixed more than that"


def test_the_exemptions_still_exist_and_still_need_exempting():
    flagged = set()
    for path in sorted(ROUTERS.glob("*.py")):
        for name, _ in offenders(path.read_text(), str(path)):
            flagged.add((path.name, name))
    assert flagged == set(EXEMPT), (
        "an exemption that no longer fires should be deleted, and one that fires should be fixed or justified; "
        f"flagged={sorted(flagged)}"
    )


NEGATIVE_CONTROL = '''
def lookup(current_user, row_id):
    row = find(row_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Row {row_id} not found")
    assert_client_access(current_user, row["client_id"])
'''


def test_negative_control_the_old_shape_is_caught():
    assert offenders(NEGATIVE_CONTROL) == [("lookup", 6)]


def test_negative_control_the_same_words_pass():
    fixed = NEGATIVE_CONTROL.replace('row["client_id"])', 'row["client_id"], detail=f"Row {row_id} not found")')
    assert offenders(fixed) == []


def test_an_assertion_placed_before_any_lookup_is_not_an_oracle():
    src = '''
def handler(current_user, client_id, row_id):
    assert_client_access(current_user, client_id)
    row = find(row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Row not found")
'''
    assert offenders(src) == []


# ── behavioural: the three helpers the finding named, driven for real ─────────────────────────────────────────────────

@pytest.fixture()
def as_a_scoped_manager(monkeypatch):
    from core import authz
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "_client_belongs_to_firm", lambda client_id, firm_id: True)
    monkeypatch.setattr(authz, "assigned_client_ids", lambda user: {"C-MINE"})
    return {"role": "Manager", "firm_id": "F1", "id": "u1"}


def _detail_of(call):
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == 404
    return caught.value.detail


def test_an_invoice_that_is_missing_and_one_in_an_unassigned_client_say_the_same(as_a_scoped_manager, monkeypatch):
    from routers import sales_invoices as si
    monkeypatch.setattr(si, "_USE_MOCK", False)
    monkeypatch.setattr(si, "_invoice_owner", lambda user, invoice_id: (False, None))
    missing = _detail_of(lambda: si._assert_invoice_scope(as_a_scoped_manager, "INV-1"))
    monkeypatch.setattr(si, "_invoice_owner", lambda user, invoice_id: (True, "C-OTHER"))
    hidden = _detail_of(lambda: si._assert_invoice_scope(as_a_scoped_manager, "INV-1"))
    assert missing == hidden == "Invoice INV-1 not found"


def test_a_bill_that_is_missing_and_one_in_an_unassigned_client_say_the_same(as_a_scoped_manager, monkeypatch):
    from routers import purchase_bills as pb
    monkeypatch.setattr(pb, "_USE_MOCK", False)
    monkeypatch.setattr(pb, "_bill_owner", lambda user, bill_id: (False, None))
    missing = _detail_of(lambda: pb._assert_bill_scope(as_a_scoped_manager, "B-1"))
    monkeypatch.setattr(pb, "_bill_owner", lambda user, bill_id: (True, "C-OTHER"))
    hidden = _detail_of(lambda: pb._assert_bill_scope(as_a_scoped_manager, "B-1"))
    assert missing == hidden == "Purchase bill B-1 not found"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return self

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self._rows
        return r


def test_a_bank_row_that_is_missing_and_one_in_an_unassigned_client_say_the_same(as_a_scoped_manager):
    from routers import banking
    missing = _detail_of(lambda: banking._assert_row_scope(_Rows([]), as_a_scoped_manager, "bank_transactions", "T-1", "Bank transaction"))
    hidden = _detail_of(lambda: banking._assert_row_scope(
        _Rows([{"client_id": "C-OTHER"}]), as_a_scoped_manager, "bank_transactions", "T-1", "Bank transaction"))
    assert missing == hidden == "Bank transaction not found."


def test_an_assigned_clients_row_is_still_reachable(as_a_scoped_manager):
    from routers import banking
    got = banking._assert_row_scope(_Rows([{"client_id": "C-MINE"}]), as_a_scoped_manager, "bank_transactions", "T-1", "Bank transaction")
    assert got == "C-MINE"


def test_the_default_wording_is_unchanged_for_a_caller_that_does_not_name_one(as_a_scoped_manager):
    from core import authz
    assert _detail_of(lambda: authz.assert_client_access(as_a_scoped_manager, "C-OTHER")) == "Not found"
    assert _detail_of(lambda: authz.assert_client_access(as_a_scoped_manager, "C-OTHER", detail="Gone")) == "Gone"
