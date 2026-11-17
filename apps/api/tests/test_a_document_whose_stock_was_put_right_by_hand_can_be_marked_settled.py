"""A document whose stock effect the CA put right by hand can be marked settled, and "Complete the stock" will not move its goods again (POST-A-092, the first LEFT item).

WHAT WAS WRONG
    `documents_with_unrecorded_stock` lists what the stock ROWS show, so a document the CA had already corrected with a stock adjustment stayed listed for ever, and
    "Complete the stock" would have moved its goods a second time. The button asked first and warned; nothing recorded that the document was dealt with, and a way to
    record it needed a decision on where the mark lives and who may set it. The decision (16-11-2026): a table of its own (`stock_effect_settlements`, migration 620),
    written and read by the API's privileged client only, set and taken back by anyone who may complete the stock (accounting write), with a reason the CA types.

WHAT IS HELD HERE (the database half is `test_620_..._pg.py`)
    * a listed document can be marked with a reason; the mark keeps the document's reference and date, the reason as typed (white space tidied), who and when;
    * a document that is not listed, one already marked, another client's, a draft, a cancelled one, a deleted one and an opening balance are each refused in words,
      and a blank reason or one over the table's length is a 422 with the sentence, before anything is read;
    * a list the finder could not give is "could not check" and marks nothing; a list cut at its limit that does not show the document still allows the mark;
    * a marked document is refused by the retry in the mark's words BEFORE any stock function runs; taking the mark off lets the retry run again;
    * the routes ask the right tier and the client first, a missing mark and another firm's are the same 404, each write is audited as the person, and the list of
      marks is a failure and never an empty list when it cannot be read;
    * the mark's read and writes name the firm and the client and go through the privileged client.
"""
from __future__ import annotations

import ast
import pathlib
import uuid

import pytest
from fastapi import HTTPException

import routers.inventory as inv_router
from domain.inventory import stock_settlement
from models.inventory import StockEffectSettleIn
from services import stock_effect_retry_service as svc
from tests.e2e_harness import FakeDB

API = pathlib.Path(__file__).resolve().parents[1]
FIRM, OTHER_FIRM = "firm-mark", "firm-other"
CLIENT, OTHER_CLIENT = "client-mark", "client-other"
CALLER = {"firm_id": FIRM, "id": "u-int", "auth_user_id": "auth-u", "email": "ca@f.test", "full_name": "Asha Rao", "role": "Partner"}


@pytest.fixture(autouse=True)
def _no_service_client(monkeypatch):
    monkeypatch.setattr("core.db_provider.service_db_or_none", lambda: None)


def _invoice(db, *, no="INV-7", status="issued", client=CLIENT, firm=FIRM, **extra):
    row = db.seed("client_sales_invoices", {"id": str(uuid.uuid4()), "firm_id": firm, "client_id": client, "invoice_no": no,
                                            "invoice_date": "2026-04-23", "status": status, **extra})
    return row["id"]


def _listed(*doc_ids, kind="sales_invoice", total=None):
    """What the finder answers: these documents, owing a line each."""
    docs = [{"kind": kind, "document_id": i, "reference": "x", "document_date": "2026-04-23", "owed_lines": 1, "moved_lines": 0, "unjournalled_rows": 0}
            for i in doc_ids]
    return {"total": len(docs) if total is None else total, "documents": docs}


@pytest.fixture
def listing(monkeypatch):
    """The finder's answer, set per test (the real one is the database function the pg test holds)."""
    answer = {"value": _listed()}
    monkeypatch.setattr(svc, "unrecorded_documents", lambda *a, **k: answer["value"])
    return answer


def _settle(db, doc_id, reason="Adjusted 4 units out on 12 April, ADJ-12", **kw):
    return svc.settle(db, firm_id=kw.pop("firm_id", FIRM), client_id=kw.pop("client_id", CLIENT), kind=kw.pop("kind", "sales_invoice"), document_id=doc_id,
                      reason=reason, settled_by="u-int", settled_by_name="Asha Rao")


# ── marking ──────────────────────────────────────────────────────────────────

def test_a_listed_document_is_marked_with_its_reference_its_date_the_reason_and_who(listing):
    db = FakeDB()
    doc = _invoice(db)
    listing["value"] = _listed(doc)
    out = _settle(db, doc, reason="  Adjusted 4 units out\n on 12 April,   ADJ-12 ")
    rows = db.rows("stock_effect_settlements")
    assert len(rows) == 1
    row = rows[0]
    assert (row["firm_id"], row["client_id"], row["document_kind"], row["document_id"]) == (FIRM, CLIENT, "sales_invoice", doc)
    assert (row["reference"], row["document_date"]) == ("INV-7", "2026-04-23")
    assert row["reason"] == "Adjusted 4 units out on 12 April, ADJ-12", "white space tidied, the words as typed"
    assert (row["settled_by"], row["settled_by_name"]) == ("u-int", "Asha Rao") and row["settled_at"]
    assert out["message"] == stock_settlement.marked("Sales invoice INV-7") and "not touched" in out["message"]


def test_a_mark_moves_no_stock_and_posts_no_journal(listing):
    db = FakeDB()
    doc = _invoice(db)
    listing["value"] = _listed(doc)
    before = {t: len(db.rows(t)) for t in ("inventory_stock_ledger", "journal_entries", "journal_lines", "audit_log")}
    _settle(db, doc)
    assert {t: len(db.rows(t)) for t in before} == before


@pytest.mark.parametrize("reason, said", [("", stock_settlement.NO_REASON), ("   \n\t ", stock_settlement.NO_REASON),
                                          ("x" * 501, stock_settlement.REASON_TOO_LONG)])
def test_a_reason_that_says_nothing_or_too_much_is_refused_with_the_sentence_before_anything_is_read(listing, reason, said):
    db = FakeDB()
    with pytest.raises(ValueError, match=said[:20]):
        _settle(db, str(uuid.uuid4()), reason=reason)
    assert db.rows("stock_effect_settlements") == []
    assert stock_settlement.reason_problem(reason) == said
    assert stock_settlement.reason_problem("x" * 500) is None


def test_a_document_that_is_not_listed_is_refused_in_words(listing):
    db = FakeDB()
    doc = _invoice(db)
    listing["value"] = _listed()                      # the finder lists nothing: its stock is whole
    with pytest.raises(svc.Refused) as refused:
        _settle(db, doc)
    assert stock_settlement.not_listed("Sales invoice INV-7") == str(refused.value) and db.rows("stock_effect_settlements") == []


def test_a_list_cut_at_its_limit_that_does_not_show_the_document_still_allows_the_mark(listing):
    db = FakeDB()
    doc = _invoice(db)
    listing["value"] = _listed(str(uuid.uuid4()), total=201)        # one shown, 201 in all: the finder cannot say either way
    _settle(db, doc)
    assert len(db.rows("stock_effect_settlements")) == 1


def test_a_list_the_finder_could_not_give_marks_nothing(listing):
    db = FakeDB()
    doc = _invoice(db)
    listing["value"] = None
    with pytest.raises(svc.Refused) as refused:
        _settle(db, doc)
    assert str(refused.value) == stock_settlement.CANNOT_CHECK_THE_LIST and db.rows("stock_effect_settlements") == []


def test_a_second_mark_of_one_document_is_refused_in_words_and_changes_nothing(listing):
    db = FakeDB()
    doc = _invoice(db)
    listing["value"] = _listed(doc)
    _settle(db, doc)
    with pytest.raises(svc.Refused) as refused:
        _settle(db, doc, reason="Another reason")
    assert str(refused.value) == stock_settlement.already_marked("Sales invoice INV-7")
    assert [r["reason"] for r in db.rows("stock_effect_settlements")] == ["Adjusted 4 units out on 12 April, ADJ-12"]


def test_two_requests_that_both_pass_the_check_leave_one_mark_the_unique_key_says_so_in_words(listing, monkeypatch):
    """The check and the insert are two statements; the database's unique key is the second lock, and its refusal is said, not raised as a fault."""
    db = FakeDB()
    doc = _invoice(db)
    listing["value"] = _listed(doc)

    class _Duplicate(Exception):
        code = "23505"

    real = svc.privileged_for

    class _Raises:
        def __init__(self, inner): self.inner = inner
        def table(self, name):
            if name == "stock_effect_settlements":
                class _Q:
                    def insert(self, *_a, **_k): return self
                    def execute(self): raise _Duplicate("duplicate key value violates unique constraint")
                    def __getattr__(self, attr): return getattr(self.inner.table(name), attr)
                    inner = self.inner
                return _Q()
            return self.inner.table(name)
        def __getattr__(self, attr): return getattr(self.inner, attr)

    monkeypatch.setattr(svc, "privileged_for", lambda d: _Raises(real(d)))
    with pytest.raises(svc.Refused) as refused:
        _settle(db, doc)
    assert str(refused.value) == stock_settlement.already_marked("Sales invoice INV-7")


@pytest.mark.parametrize("make, words", [
    (lambda db: _invoice(db, status="draft"), "is still a draft"),
    (lambda db: _invoice(db, status="cancelled"), "was cancelled"),
    (lambda db: _invoice(db, deleted_at="2026-05-01T00:00:00+00:00"), "was deleted"),
    (lambda db: _invoice(db, is_opening=True), "opening balance"),
])
def test_a_document_that_has_no_stock_effect_to_settle_is_refused_as_a_retry_refuses_it(listing, make, words):
    db = FakeDB()
    doc = make(db)
    listing["value"] = _listed(doc)
    with pytest.raises(svc.Refused, match=words):
        _settle(db, doc)
    assert db.rows("stock_effect_settlements") == []


def test_another_clients_document_and_an_absent_one_are_the_same_not_found(listing):
    db = FakeDB()
    theirs = _invoice(db, client=OTHER_CLIENT)
    other_firm = _invoice(db, firm=OTHER_FIRM)
    for doc in (theirs, other_firm, str(uuid.uuid4())):
        listing["value"] = _listed(doc)
        with pytest.raises(svc.NotFound):
            _settle(db, doc)
    assert db.rows("stock_effect_settlements") == []


# ── the retry believes the mark ──────────────────────────────────────────────

def test_a_marked_document_is_refused_by_the_retry_before_any_stock_function_runs(listing, monkeypatch):
    db = FakeDB()
    doc = _invoice(db)
    listing["value"] = _listed(doc)
    _settle(db, doc)

    def must_not_run(*a, **k):
        raise AssertionError("a document the CA marked as settled had its goods moved again")

    monkeypatch.setattr("domain.inventory_service.apply_sale_to_inventory", must_not_run)
    with pytest.raises(svc.Refused) as refused:
        svc.retry(db, firm_id=FIRM, client_id=CLIENT, kind="sales_invoice", document_id=doc, created_by=None)
    said = str(refused.value)
    assert said == stock_settlement.settled_refusal("Sales invoice INV-7", "Adjusted 4 units out on 12 April, ADJ-12")
    assert "Take the mark off first" in said


def test_taking_the_mark_off_lets_the_retry_run_again(listing, monkeypatch):
    from domain.inventory.stock_effect import StockEffect
    db = FakeDB()
    doc = _invoice(db)
    listing["value"] = _listed(doc)
    mark = _settle(db, doc)
    ran = []

    def stock_function(*a, **k):
        ran.append(1)
        return StockEffect(kind="sales_invoice")

    monkeypatch.setattr("domain.inventory_service.apply_sale_to_inventory", stock_function)
    with pytest.raises(svc.Refused):
        svc.retry(db, firm_id=FIRM, client_id=CLIENT, kind="sales_invoice", document_id=doc, created_by=None)
    assert ran == []
    svc.remove(db, firm_id=FIRM, client_id=CLIENT, settlement_id=mark["id"])
    assert db.rows("stock_effect_settlements") == []
    svc.retry(db, firm_id=FIRM, client_id=CLIENT, kind="sales_invoice", document_id=doc, created_by=None)
    assert ran == [1], "the mark is gone, so the stock function runs"


def test_a_mark_of_another_client_does_not_refuse_this_clients_retry(listing):
    db = FakeDB()
    doc = _invoice(db)
    db.seed("stock_effect_settlements", {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": OTHER_CLIENT, "document_kind": "sales_invoice",
                                         "document_id": doc, "reason": "theirs"})
    assert svc._mark_of(db, firm_id=FIRM, client_id=CLIENT, kind="sales_invoice", document_id=doc) is None
    assert svc._mark_of(db, firm_id=FIRM, client_id=OTHER_CLIENT, kind="sales_invoice", document_id=doc)["reason"] == "theirs"
    assert svc._mark_of(db, firm_id=OTHER_FIRM, client_id=OTHER_CLIENT, kind="sales_invoice", document_id=doc) is None


def test_a_retry_that_cannot_read_the_marks_stops_and_never_moves_the_goods(listing, monkeypatch):
    db = FakeDB()
    doc = _invoice(db)

    def boom(*a, **k):
        raise RuntimeError("read failed")

    monkeypatch.setattr(svc, "_mark_of", boom)
    monkeypatch.setattr("domain.inventory_service.apply_sale_to_inventory",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("goods moved with the marks unread")))
    with pytest.raises(RuntimeError):
        svc.retry(db, firm_id=FIRM, client_id=CLIENT, kind="sales_invoice", document_id=doc, created_by=None)


# ── the list of marks ────────────────────────────────────────────────────────

def test_the_marks_are_listed_newest_first_and_only_for_the_firm_and_the_client():
    db = FakeDB()
    for n, (at, firm, client) in enumerate([("2026-05-01T10:00:00+00:00", FIRM, CLIENT), ("2026-06-01T10:00:00+00:00", FIRM, CLIENT),
                                            ("2026-07-01T10:00:00+00:00", FIRM, OTHER_CLIENT), ("2026-08-01T10:00:00+00:00", OTHER_FIRM, CLIENT)]):
        db.seed("stock_effect_settlements", {"id": f"m{n}", "firm_id": firm, "client_id": client, "document_kind": "sales_invoice",
                                             "document_id": str(uuid.uuid4()), "reason": f"r{n}", "settled_at": at})
    assert [r["id"] for r in svc.settlements(db, firm_id=FIRM, client_id=CLIENT)] == ["m1", "m0"]


# ── the routes ───────────────────────────────────────────────────────────────

def _handler(name):
    tree = ast.parse((API / "routers" / "inventory.py").read_text())
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def test_the_routes_ask_the_tier_and_prove_the_clients_access_first():
    def asked(name):
        return [ast.unparse(d) for d in _handler(name).args.defaults]

    assert "Depends(rbac('accounting', 'write'))" in asked("settle_stock_effect")
    assert "Depends(rbac('accounting', 'write'))" in asked("take_back_a_stock_settlement")
    assert "Depends(rbac('accounting', 'read'))" in asked("documents_marked_settled")
    for name in ("settle_stock_effect", "documents_marked_settled"):
        body = [n for n in _handler(name).body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        first = [ast.unparse(n) for n in body if ast.unparse(n).startswith("assert_client_access(") or "assert_client_access(" in ast.unparse(n)][0]
        assert first.startswith("assert_client_access(current_user, ") and first.endswith("client_id)"), first


@pytest.fixture
def routes(monkeypatch):
    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    monkeypatch.setattr(inv_router, "_USE_MOCK", False)
    monkeypatch.setattr(inv_router, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    events = []
    monkeypatch.setattr(inv_router, "log_event", lambda *a, **k: events.append((a, k)))
    return db, events


def test_a_mark_through_the_route_is_audited_as_the_person_and_returns_the_servers_sentence(routes, listing):
    db, events = routes
    doc = _invoice(db)
    listing["value"] = _listed(doc)
    out = inv_router.settle_stock_effect(StockEffectSettleIn(client_id=CLIENT, kind="sales_invoice", document_id=doc, reason="Adjusted by hand, ADJ-12"), CALLER)
    assert out["success"] is True and out["data"]["message"] == stock_settlement.marked("Sales invoice INV-7")
    assert db.rows("stock_effect_settlements")[0]["settled_by"] == "u-int", "users.id, the internal id, as for every *_by column"
    assert db.rows("stock_effect_settlements")[0]["settled_by_name"] == "Asha Rao"
    (args, kwargs), = events
    assert args[1:4] == ("stock_effect", doc, "settle") and kwargs["actor_id"] == "auth-u" and kwargs["new_data"]["reason"] == "Adjusted by hand, ADJ-12"


def test_the_route_answers_a_blank_reason_with_a_422_and_the_sentence_and_writes_nothing(routes, listing):
    db, events = routes
    with pytest.raises(HTTPException) as e:
        inv_router.settle_stock_effect(StockEffectSettleIn(client_id=CLIENT, kind="sales_invoice", document_id=str(uuid.uuid4()), reason="   "), CALLER)
    assert e.value.status_code == 422 and e.value.detail == stock_settlement.NO_REASON
    assert db.rows("stock_effect_settlements") == [] and events == []


def test_a_missing_document_is_404_and_a_refusal_is_409_with_the_sentence(routes, listing):
    db, _ = routes
    with pytest.raises(HTTPException) as gone:
        inv_router.settle_stock_effect(StockEffectSettleIn(client_id=CLIENT, kind="sales_invoice", document_id=str(uuid.uuid4()), reason="done"), CALLER)
    assert gone.value.status_code == 404 and gone.value.detail == "Document not found."
    doc = _invoice(db, status="cancelled")
    with pytest.raises(HTTPException) as no:
        inv_router.settle_stock_effect(StockEffectSettleIn(client_id=CLIENT, kind="sales_invoice", document_id=doc, reason="done"), CALLER)
    assert no.value.status_code == 409 and "was cancelled" in no.value.detail


def test_a_mark_is_listed_and_taken_back_through_the_routes_and_the_take_back_is_audited(routes, listing):
    db, events = routes
    doc = _invoice(db)
    listing["value"] = _listed(doc)
    mark = inv_router.settle_stock_effect(StockEffectSettleIn(client_id=CLIENT, kind="sales_invoice", document_id=doc, reason="done by hand"), CALLER)["data"]
    listed = inv_router.documents_marked_settled(CLIENT, CALLER)
    assert listed["success"] is True and [m["id"] for m in listed["data"]["settlements"]] == [mark["id"]]
    assert listed["data"]["settlements"][0]["reason"] == "done by hand"
    back = inv_router.take_back_a_stock_settlement(mark["id"], CALLER)
    assert back["success"] is True and back["data"]["message"] == stock_settlement.TAKEN_BACK
    assert db.rows("stock_effect_settlements") == []
    assert events[-1][0][1:4] == ("stock_effect", doc, "unsettle")


def test_a_missing_mark_another_firms_and_an_id_that_is_not_one_are_the_same_404(routes):
    db, _ = routes
    theirs = db.seed("stock_effect_settlements", {"id": str(uuid.uuid4()), "firm_id": OTHER_FIRM, "client_id": CLIENT, "document_kind": "sales_invoice",
                                                  "document_id": str(uuid.uuid4()), "reason": "x"})
    for bad in (theirs["id"], str(uuid.uuid4()), "not-an-id"):
        with pytest.raises(HTTPException) as e:
            inv_router.take_back_a_stock_settlement(bad, CALLER)
        assert e.value.status_code == 404 and e.value.detail == "Mark not found."
    assert len(db.rows("stock_effect_settlements")) == 1, "another firm's mark was not touched"


def test_the_take_back_proves_the_access_of_the_marks_own_client(routes, monkeypatch):
    db, _ = routes
    mark = db.seed("stock_effect_settlements", {"id": str(uuid.uuid4()), "firm_id": FIRM, "client_id": OTHER_CLIENT, "document_kind": "sales_invoice",
                                                "document_id": str(uuid.uuid4()), "reason": "x"})
    asked = []

    def refuse(user, client_id, **_k):
        asked.append(client_id)
        raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(inv_router, "assert_client_access", refuse)
    with pytest.raises(HTTPException):
        inv_router.take_back_a_stock_settlement(mark["id"], CALLER)
    assert asked == [OTHER_CLIENT] and len(db.rows("stock_effect_settlements")) == 1


def test_a_list_of_marks_that_cannot_be_read_is_a_failure_and_never_an_empty_list(routes, monkeypatch):
    monkeypatch.setattr(svc, "settlements", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("read failed")))
    res = inv_router.documents_marked_settled(CLIENT, CALLER)
    assert res["success"] is False and res["data"] is None and "not the same as there being none" in res["error"]


# ── where the table is read and written ──────────────────────────────────────

def test_every_statement_on_the_marks_names_the_firm_and_goes_through_the_privileged_client():
    tree = ast.parse((API / "services" / "stock_effect_retry_service.py").read_text())
    text = (API / "services" / "stock_effect_retry_service.py").read_text()
    uses = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == "stock_effect_settlements"]
    assert len(uses) >= 5, "the module no longer reads and writes the table the migration makes"
    assert text.count('privileged_for(db).table("stock_effect_settlements")') >= 4, "the four statements on the table go through the privileged client"
    assert 'db.table("stock_effect_settlements")' not in text.replace('privileged_for(db).table("stock_effect_settlements")', "")
    for fn in ("_mark_of", "settlements", "get_settlement", "remove"):
        src = ast.unparse(next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn))
        assert ".eq('firm_id', firm_id)" in src, fn


def test_the_table_is_on_the_list_of_tables_nothing_signed_in_writes():
    listed = (API / "tests" / "fixtures" / "tables_the_signed_in_role_cannot_write.txt").read_text().split("\n")
    assert "stock_effect_settlements" in listed
