"""The two database functions that write the ledger ask the closure and the pairs the posting routes ask (migration 533, POST-A-316).

The behaviour is proven on real Postgres in `test_a_posting_into_a_closed_year_is_refused_by_the_two_ledger_functions_pg.py`.
This file holds what the mock-mode job (a required check) can hold, in four parts:

  1. THE ORDER IN THE MIGRATION: in each wrapper the caller check comes first, then the closure, then the call to the
     unguarded original, and the closure is `period_closure_reason` (the CLOSURES, not the filed-return branch the kernel
     deliberately does not ask).
  2. THE PAIR LIST IS A UNION THAT REFUSES NO POSTING ROUTE: every (resource, action) pair in `post_journal_atomic`'s list is a
     real pair of `core.permissions` with the third element equal to the lowest role that holds it, and every router that
     posts has at least one non-read pair in the list, so the database's second lock never refuses a route the first lock
     admits. A new posting router whose pairs are all outside the list fails here, with the router named.
  3. THE RECEIPT'S OWN REFUSAL: the plain rupee receipt asks `closure_reason` before it takes a number or writes a row, with
     the closure's sentence and a 422; the foreign receipt asks it too; a mock-mode receipt (no database) is untouched.
  4. `assert_not_closed` is the closures only.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from core.permissions import PERMISSIONS, ROLE_HIERARCHY
from services import period_lock_service, receipt_service

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next(p for p in (API_ROOT / "migrations").glob("533_a_posting_into_a_closed_year_is_refused_by_the_two_ledger_functions*.sql")
                 if not p.name.endswith("_rollback.sql"))
ROLLBACK = next((API_ROOT / "migrations").glob("533_a_posting_into_a_closed_year_is_refused_by_the_two_ledger_functions*_rollback.sql"))
SQL = MIGRATION.read_text()


def _function(name: str, text: str = SQL) -> str:
    m = re.search(rf"CREATE (?:OR REPLACE )?FUNCTION public\.{name}\(.*?\n\$fn\$;\n", text, re.S)
    assert m, f"533 does not define {name}"
    return m.group(0)


def _code(sql: str) -> str:
    """The function without its comments, so a word in prose cannot satisfy a check on code."""
    return re.sub(r"--[^\n]*", "", sql)


# ── 1. THE ORDER ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,raw", [("post_journal_atomic", "post_journal_atomic__unguarded"),
                                      ("settle_receipt_atomic", "settle_receipt_atomic__unguarded")])
def test_each_wrapper_checks_the_caller_then_the_closure_then_calls_the_original(name, raw):
    body = _code(_function(name))
    caller = body.index("assert_caller_acts_for")
    closure = body.index("period_closure_reason")
    call = body.index(f"RETURN public.{raw}(")
    assert caller < closure < call, (name, caller, closure, call)
    assert body.count(f"public.{raw}(") == 1 and body.count("period_closure_reason") == 1


def test_the_closure_asked_is_the_closures_and_not_the_filed_return_branch():
    """The kernel deliberately does not ask the filed-return branch (June's bank work happens after June's returns are filed;
    migration 361's header): `period_lock_reason` and `journal_period_lock_reason` here would stop every June receipt from the
    11th of July."""
    code = _code(SQL)
    assert "period_closure_reason" in code
    assert "period_lock_reason" not in code and "journal_period_lock_reason" not in code and "is_fy_locked" not in code


def test_the_unguarded_originals_are_the_service_roles_alone_and_the_wrappers_are_not_anons():
    code = _code(SQL)
    for raw, args in (("post_journal_atomic__unguarded", "jsonb, jsonb"), ("settle_receipt_atomic__unguarded", None)):
        if args is None:
            continue
        assert f"REVOKE ALL ON FUNCTION public.{raw}({args}) FROM PUBLIC, anon, authenticated;" in code
        assert f"GRANT EXECUTE ON FUNCTION public.{raw}({args}) TO service_role;" in code
    assert "REVOKE ALL ON FUNCTION public.post_journal_atomic(jsonb, jsonb) FROM PUBLIC, anon;" in code
    assert "GRANT EXECUTE ON FUNCTION public.post_journal_atomic(jsonb, jsonb) TO authenticated, service_role;" in code


def test_the_rollback_renames_the_original_back_and_restores_486s_wrapper_from_486():
    rb = _code(ROLLBACK.read_text())
    assert "ALTER FUNCTION public.post_journal_atomic__unguarded(jsonb, jsonb) RENAME TO post_journal_atomic;" in rb
    m486 = next(p for p in (API_ROOT / "migrations").glob("486_*.sql") if not p.name.endswith("_rollback.sql")).read_text()
    wrapper486 = re.search(r"CREATE FUNCTION public\.settle_receipt_atomic\(.*?\n\$fn\$;\n", m486, re.S).group(0)
    assert _code(wrapper486).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1) in rb


# ── 2. THE PAIRS ────────────────────────────────────────────────────────────────

def _pairs() -> list[tuple[str, str, str]]:
    body = _function("post_journal_atomic")
    m = re.search(r"assert_caller_acts_for\('post_journal_atomic',.*?'(\[\[.*?\]\])'::jsonb\)", body, re.S)
    assert m, "the pair list was not found"
    return [tuple(p) for p in json.loads(m.group(1))]


def _lowest_role(resource: str, action: str) -> str:
    roles = PERMISSIONS[resource][action]
    return next(r.value for r in ROLE_HIERARCHY if r in roles)


def test_every_pair_in_the_list_is_a_real_pair_with_its_real_lowest_role():
    pairs = _pairs()
    assert len(pairs) == 6 and len(set(pairs)) == len(pairs)
    for resource, action, minimum in pairs:
        assert resource in PERMISSIONS and action in PERMISSIONS[resource], (resource, action)
        assert minimum == _lowest_role(resource, action), (resource, action, minimum, _lowest_role(resource, action))


def test_the_list_is_ordered_lowest_tier_first_so_the_usual_caller_is_admitted_by_the_first_pair():
    order = [r.value for r in ROLE_HIERARCHY]
    ranks = [order.index(minimum) for _, _, minimum in _pairs()]
    assert ranks == sorted(ranks), ranks
    assert _pairs()[0] == ("banking", "write", "Executive")


def test_no_pair_in_the_list_is_open_to_a_reviewer_or_a_client():
    """The whole point of the second lock: a Reviewer and a Client-role member hold none of them."""
    for resource, action, _ in _pairs():
        roles = {r.value for r in PERMISSIONS[resource][action]}
        assert not roles & {"Reviewer", "Client"}, (resource, action, roles)


def test_the_pairs_that_guard_something_else_are_not_in_the_list():
    """The first reading over-collected: invoice:write guards SENDING a document, year_end:write drafting an adjustment,
    payroll:write the payroll masters, billing:write the practice's fee billing (which never touches the ledger) and
    banking:approve a reconciliation adjustment that posts nothing. A person denied the pairs a posting route asks, but
    holding one of these, must not be able to post."""
    pairs = {(r, a) for r, a, _ in _pairs()}
    for wrong in (("invoice", "write"), ("year_end", "write"), ("payroll", "write"), ("billing", "write"), ("banking", "approve")):
        assert wrong not in pairs, wrong


POSTING_PRIMITIVES = re.compile(r"\b(_create_journal|reverse_entry|post_journal_atomic|settle_receipt_atomic|journal_for_[a-z_]+"
                                r"|post_opening_balances|bank_posting_service|post_draft)\b")

#: A router that reaches a posting module (it mentions a posting primitive, or imports a service or domain module that does)
#: and none of whose write pairs is in the list, each with the reason it posts nothing through the caller's own sign-in.
#: Read route by route by the independent review of migration 533 (22-10-2026). A NEW router that reaches a posting module
#: has to have one of the listed pairs or be added here with its reason, so the second lock cannot refuse a route nobody
#: classified. Only shrinks.
REVIEWED_NOT_POSTING: dict[str, str] = {
    "billing": "fee invoices and receipts: record_fee_receipt_atomic never touches the ledger",
    "customer_statements": "e-mails a statement; posts nothing",
    "einvoice": "IRN records and the missing-IRN list; prepare-only",
    "gst": "GST return preparation; posts nothing",
    "gst_workspace": "GST return preparation and the filing record; posts nothing",
    "gstr4_annual": "the composition annual return; prepares only",
    "itr_workspace": "return preparation and the keying sheets; Part A reads the chart account an asset category is booked to, by the "
                     "posting kernel's own lookup so that it is the same account, and posts nothing",
    "portal": "portal-contact invitations",
    "portal_data": "the client's own view; the online payment is posted by the gateway's webhook as the backend, with no JWT",
    "report_exports": "reads",
    "reports": "reads",
    "sales_cycle": "quotations, orders and delivery challans; it does not import the posting kernel and a test asserts that",
    "scheduler_status": "triggers the scheduler, which runs as the service role",
    "scheduler_trigger": "triggers the scheduler, which runs as the service role",
    "tasks": "task management; the scheduler it imports runs as the service role",
    "tds": "TDS statements and the deposit worksheet; posts nothing",
    "year_end": "engagement, checklist and statements; the adjustments that post are year_end_adjustments (year_end:approve)",
}


def _imports(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
            out.update(f"{n.module}.{a.name}" for a in n.names)
        elif isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
    return out


def _non_read_pairs(tree: ast.AST) -> set[tuple[str, str]]:
    return {(c.args[0].value, c.args[1].value) for c in ast.walk(tree)
            if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "rbac" and len(c.args) >= 2
            and all(isinstance(a, ast.Constant) for a in c.args[:2]) and c.args[1].value != "read"}


def _posting_modules() -> set[str]:
    mods: dict[str, str] = {}
    for base in ("services", "domain"):
        for path in (API_ROOT / base).rglob("*.py"):
            mods[".".join(path.relative_to(API_ROOT).with_suffix("").parts)] = path.read_text()
    first = {m for m, text in mods.items() if POSTING_PRIMITIVES.search(text)}
    return first | {m for m, text in mods.items() if _imports(ast.parse(text)) & first}


def test_every_router_that_reaches_a_posting_module_has_a_pair_the_database_admits_or_is_reviewed_as_posting_nothing():
    union = {(r, a) for r, a, _ in _pairs()}
    posting = _posting_modules()
    reaching, unclassified = 0, []
    for path in sorted((API_ROOT / "routers").glob("*.py")):
        text = path.read_text()
        tree = ast.parse(text)
        if not (POSTING_PRIMITIVES.search(text) or _imports(tree) & posting):
            continue
        reaching += 1
        if _non_read_pairs(tree) & union:
            assert path.stem not in REVIEWED_NOT_POSTING, f"{path.stem} has a pair in the list: delete it from REVIEWED_NOT_POSTING"
        elif path.stem not in REVIEWED_NOT_POSTING:
            unclassified.append((path.stem, sorted(_non_read_pairs(tree))))
    assert reaching >= 40, f"only {reaching} routers reach a posting module: the scan stopped seeing them"
    assert not unclassified, (
        f"these routers reach a posting module and none of their write pairs is one post_journal_atomic asks: {unclassified}. "
        "Their callers would be admitted by rbac() and refused by the database if they post. Add the pair to migration 533's "
        "list in a new migration (re-derived from it), or record the router in REVIEWED_NOT_POSTING with the reason it posts "
        "nothing through the caller's sign-in.")


def test_a_router_reviewed_as_posting_nothing_does_not_name_a_posting_primitive_itself():
    for name in REVIEWED_NOT_POSTING:
        text = (API_ROOT / "routers" / f"{name}.py").read_text()
        assert not POSTING_PRIMITIVES.search(text), f"routers/{name}.py now names a posting primitive: review it again"


def test_the_posting_routers_this_audit_was_made_from_are_all_still_covered():
    """The routers the pair list was read off (22-10-2026), by name, so renaming or splitting one is noticed."""
    named = {"accounting", "credit_notes", "cwip", "debit_notes", "fixed_assets", "payroll", "purchase_bills",
             "purchase_credit_notes", "purchase_payments", "receipts", "recurring_journals", "sales_debit_notes",
             "sales_invoices", "year_end_adjustments", "banking", "customers", "vendors"}
    union = {(r, a) for r, a, _ in _pairs()}
    for name in sorted(named):
        pairs = _non_read_pairs(ast.parse((API_ROOT / "routers" / f"{name}.py").read_text()))
        assert pairs & union, name


# ── 3. THE RECEIPT'S OWN REFUSAL ────────────────────────────────────────────────

CLOSED = ("FY 2024-25 is closed for this client — its year-end has been finalised. Reopen the year before posting to it.")


class _Rpc:
    def __init__(self, data):
        self._data = data

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self._data
        return r


class _Customers:
    """The one read the receipt makes before its date checks (the customer belongs to the client and is active)."""

    def select(self, *a, **k):
        return self

    eq = limit = select

    def execute(self):
        return _Rpc([{"is_active": True}]).execute()


class _Db:
    """A source with an `rpc` (so the real SQL function is the question) that answers the closure and fails on anything else:
    a refusal must come before any other read or any write."""

    def __init__(self, closure=None):
        self.closure = closure
        self.rpcs: list[str] = []
        self.tables: list[str] = []

    def rpc(self, fn, params=None):
        self.rpcs.append(fn)
        assert fn == "period_closure_reason", f"{fn} was called: the refusal must come before any other call"
        return _Rpc(self.closure)

    def table(self, name):
        self.tables.append(name)
        assert name == "customers", f"table({name!r}) was read or written before the refusal"
        return _Customers()


@pytest.fixture()
def no_firm_lock(monkeypatch):
    monkeypatch.setattr(receipt_service.period_validation_service, "validate_posting_date", lambda *a, **k: None)


def _receipt(day="2024-09-30"):
    return {"client_id": "c1", "customer_id": "cu1", "receipt_date": day, "amount_paise": 10000, "allocations": []}


def test_the_plain_receipt_in_a_finalised_year_is_refused_with_the_closures_sentence_before_anything_is_read(no_firm_lock):
    db = _Db(CLOSED)
    with pytest.raises(HTTPException) as e:
        receipt_service.create_receipt_core("f1", _receipt(), {"auth_user_id": "a", "email": "e"}, db)
    assert e.value.status_code == 422 and e.value.detail == CLOSED
    assert db.rpcs == ["period_closure_reason"] and db.tables == ["customers"]


def test_the_foreign_receipt_in_a_finalised_year_is_refused_the_same_way(no_firm_lock):
    db = _Db(CLOSED)
    data = {**_receipt(), "currency": "USD"}
    with pytest.raises(HTTPException) as e:
        receipt_service.create_foreign_receipt("f1", data, {"auth_user_id": "a", "email": "e"}, db)
    assert e.value.status_code == 422 and e.value.detail == CLOSED
    assert db.rpcs == ["period_closure_reason"]


def test_a_source_that_cannot_answer_is_a_refusal_not_an_open_year(no_firm_lock):
    class Down(_Db):
        def rpc(self, fn, params=None):
            raise RuntimeError("connection reset")

    with pytest.raises(HTTPException) as e:
        receipt_service.create_receipt_core("f1", _receipt(), {"auth_user_id": "a", "email": "e"}, Down())
    assert e.value.status_code == 422 and e.value.detail == period_lock_service.UNVERIFIABLE


def test_the_check_comes_before_the_number_is_taken_and_before_the_atomic_call():
    """Structure, so a later edit that moves it below the sequence (a number consumed for a refused receipt) or removes it
    from either path fails here."""
    src = (API_ROOT / "services" / "receipt_service.py").read_text()
    for fn, nxt in (("create_receipt_core", "_next_receipt_seq(db"), ("create_foreign_receipt", "currency_service.get_currency(")):
        start = src.index(f"def {fn}(")
        body = src[start:src.index("\ndef ", start + 10)] if "\ndef " in src[start + 10:] else src[start:]
        assert "_assert_open_where_a_receipt_feeds_a_return(db," in body, fn
        assert body.index("_assert_open_where_a_receipt_feeds_a_return(db,") < body.index(nxt), fn


def test_a_mock_mode_receipt_is_untouched(no_firm_lock):
    out = receipt_service.create_receipt_core("f1", _receipt(), {"auth_user_id": "a", "email": "e"}, None)
    assert out["receipt_no"].startswith("RCPT-")


def test_a_refusal_the_database_gives_reaches_the_person_as_the_sentence_and_a_422(monkeypatch):
    """The function asks the same question the door asked; when it is the one that speaks (a year closed between the two) the
    receipt answers 422 with the closure's sentence and not a generic failure."""
    class Raises:
        def rpc(self, fn, params=None):
            assert fn == "settle_receipt_atomic"

            class R:
                def execute(self_inner):
                    raise RuntimeError("{'message': '%s', 'code': 'P0001'}" % CLOSED)
            return R()

    receipt = {"id": "r1", "firm_id": "f1", "client_id": "c1", "customer_id": "cu1", "receipt_no": "RCPT-1",
               "receipt_date": "2024-09-30", "amount_paise": 100, "tds_paise": 0, "unallocated_paise": 100}
    from services import phase2_journal_service as p2
    monkeypatch.setattr(p2.phase2_journal_service, "receipt_journal_lines", lambda *a, **k: [
        {"account_id": "a1", "debit_paise": 100, "credit_paise": 0}, {"account_id": "a2", "debit_paise": 0, "credit_paise": 100}])
    with pytest.raises(HTTPException) as e:
        receipt_service._settle_receipt_via_atomic_rpc(Raises(), "f1", "c1", receipt, [], {"auth_user_id": "a", "email": "e"})
    assert e.value.status_code == 422 and e.value.detail == CLOSED


def test_the_recogniser_knows_both_sentences_and_nothing_else():
    from services.period_lock_service import _CLIENT_YEAR_CLOSED, _FIRM_YEAR_LOCKED, closure_sentence_in
    for template in (_FIRM_YEAR_LOCKED, _CLIENT_YEAR_CLOSED):
        sentence = template.format(fy="2024-25")
        assert closure_sentence_in(sentence) == sentence
        assert closure_sentence_in(f"{{'message': '{sentence}', 'code': 'P0001'}}") == sentence
    for other in ("", None, "connection reset", "duplicate key value violates unique constraint",
                  "FY 2024-25 is open", "Financial year soon is locked."):
        assert closure_sentence_in(other) is None, other


# ── 4. assert_not_closed ────────────────────────────────────────────────────────

def test_assert_not_closed_is_the_closures_only_and_raises_422_with_the_reason():
    class OnlyClosure:
        def rpc(self, fn, params=None):
            assert fn == "period_closure_reason", fn           # never period_lock_reason: a filed return is not a closure
            return _Rpc(None)

    period_lock_service.assert_not_closed(OnlyClosure(), "f1", "c1", "2024-09-30")
    with pytest.raises(HTTPException) as e:
        period_lock_service.assert_not_closed(_Db(CLOSED), "f1", "c1", "2024-09-30")
    assert e.value.status_code == 422 and e.value.detail == CLOSED


def test_assert_not_closed_asks_nothing_when_there_is_nothing_to_ask():
    period_lock_service.assert_not_closed(None, "", "c1", "2024-09-30")
    period_lock_service.assert_not_closed(_Db(CLOSED), "f1", None, "2024-09-30")
    period_lock_service.assert_not_closed(_Db(CLOSED), "f1", "c1", "")
