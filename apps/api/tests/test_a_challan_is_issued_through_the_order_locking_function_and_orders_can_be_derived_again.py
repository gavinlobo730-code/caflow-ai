"""POST-A-421, parts (b) and (c), the API half: a challan is issued through `issue_delivery_challan_atomic` (migration 652), and an order the old rule left
`delivered` can be derived again by a person-run step.

The SQL itself (the rule's parity with `over_delivery`, the lock, the race) is `test_652_issue_delivery_challan_parity_pg.py`. Here, in mock mode over the
function's in-memory double: the door words each refusal of the function, the issue goes through it and not through a compare-and-set, the compare-and-set
survives only for a database without the function, and the re-derivation lists what differs, writes only when told, and leaves closed and cancelled orders alone.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent))

import services.delivery_challan_writes as writes
import services.sales_cycle_service as svc
import test_itc_04_is_derived_from_the_challans_already_entered as itc
from tests.e2e_harness import FakeDB

CONSIGNER = {"legal_name": "Mfg Co Pvt Ltd", "gstin": None, "address": "1 Mill Road, Pune"}


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(svc, "ist_today", lambda: date(2026, 10, 9))


@pytest.fixture
def db():
    x = FakeDB()
    x.seed("clients", {"id": itc.CLIENT, "firm_id": itc.FIRM, "client_name": "Mfg Co", "legal_name": "Mfg Co Pvt Ltd", "address_line1": "1 Mill Road", "city": "Pune"})
    return x


def _order(db, qty="10", status="confirmed"):
    order = db.seed("sales_orders", {"firm_id": itc.FIRM, "client_id": itc.CLIENT, "document_no": "SO/1", "status": status})
    line = db.seed("sales_order_lines", {"firm_id": itc.FIRM, "client_id": itc.CLIENT, "order_id": order["id"], "description": "Widget", "quantity": qty})
    return order, line


def _challan(db, order, line, qty, *, status="draft", no="DC/1"):
    c = itc._challan(db, no, "2026-06-01", reason="supply_invoice_to_follow", status=status, order_id=order["id"], goods_kind=None, gstin=None)
    c.update({"consignee_name": "Buyer", "consignee_address": "2 Lane"})
    itc._line(db, c, qty=qty, order_line_id=line["id"])
    return c


def _issue(db, c):
    return svc.issue_challan(db, itc.FIRM, c["id"], client_id=itc.CLIENT, consigner=CONSIGNER)


def test_an_issue_is_written_by_the_function_and_not_by_a_compare_and_set(db, monkeypatch):
    order, line = _order(db)
    c = _challan(db, order, line, "10")
    called = []
    real = writes.issue_in_one_transaction
    monkeypatch.setattr(writes, "issue_in_one_transaction", lambda *a, **k: called.append(a[3]) or real(*a, **k))
    assert _issue(db, c)["status"] == "issued" and called == [c["id"]]
    stored = next(r for r in db.rows("delivery_challans") if r["id"] == c["id"])
    assert stored["status"] == "issued" and stored["issued_at"]


def test_two_drafts_of_the_whole_order_the_second_issue_is_refused_in_words_and_writes_nothing(db):
    order, line = _order(db)
    first, second = _challan(db, order, line, "10", no="DC/1"), _challan(db, order, line, "10", no="DC/2")
    # both pass the API's own reading (both are drafts, nothing delivered yet); the function is the second asker
    _issue(db, first)
    with pytest.raises(HTTPException) as caught:
        _issue(db, second)
    assert caught.value.status_code == 422
    stored = next(r for r in db.rows("delivery_challans") if r["id"] == second["id"])
    assert stored["status"] == "draft" and not stored.get("issued_at")


def test_the_door_words_what_the_function_says_when_the_api_could_not_have_seen_it(db, monkeypatch):
    class Boom:
        def __init__(self, word): self.word = word
        def rpc(self, *_a, **_k): raise Exception(str({"message": self.word, "code": "P0001"}))
        def table(self, *_a, **_k): raise AssertionError("not read")
    monkeypatch.setattr(writes, "privileged_for", lambda d: d)
    for word, status in (("order_over_delivered", 422), ("order_line_not_of_order", 422), ("challan_not_draft", 409), ("challan_not_found", 404)):
        with pytest.raises(HTTPException) as caught:
            writes.issue_in_one_transaction(Boom(word), "f", "c", "x", "2026-01-01T00:00:00+00:00", document_no="DC/9")
        assert caught.value.status_code == status, word
    missing = Boom("Could not find the function public.issue_delivery_challan_atomic in the schema cache")
    assert writes.issue_in_one_transaction(missing, "f", "c", "x", "2026-01-01T00:00:00+00:00", document_no="DC/9") is None


def test_a_database_without_the_function_issues_with_the_compare_and_set_it_had(db, monkeypatch):
    order, line = _order(db)
    c = _challan(db, order, line, "10")
    monkeypatch.setattr(writes, "issue_in_one_transaction", lambda *a, **k: None)
    assert _issue(db, c)["status"] == "issued"
    assert next(r for r in db.rows("delivery_challans") if r["id"] == c["id"])["status"] == "issued"


def test_an_order_the_old_rule_left_delivered_is_derived_again_only_when_applied(db):
    order, line = _order(db, "10", status="delivered")
    _challan(db, order, line, "10", status="received_back")              # delivered nothing: its goods came back
    stuck, sline = _order(db, "5", status="partially_delivered")
    closed, cline = _order(db, "5", status="closed")
    cancelled, _ = _order(db, "5", status="cancelled")
    before = {r["id"]: r["status"] for r in db.rows("sales_orders")}
    listed = svc.orders_whose_status_would_change(db, itc.FIRM)
    assert {c["order_id"]: (c["from"], c["to"]) for c in listed} == {order["id"]: ("delivered", "confirmed"), stuck["id"]: ("partially_delivered", "confirmed")}
    assert {r["id"]: r["status"] for r in db.rows("sales_orders")} == before, "a dry run wrote"
    svc.orders_whose_status_would_change(db, itc.FIRM, apply=True)
    now = {r["id"]: r["status"] for r in db.rows("sales_orders")}
    assert now[order["id"]] == "confirmed" and now[stuck["id"]] == "confirmed" and now[closed["id"]] == "closed" and now[cancelled["id"]] == "cancelled"
    assert svc.orders_whose_status_would_change(db, itc.FIRM) == [], "a second run found more to change"


def test_the_script_is_a_dry_run_unless_told():
    src = (Path(__file__).resolve().parent.parent / "scripts" / "resettle_sales_orders.py").read_text(encoding="utf-8")
    assert 'action="store_true"' in src and "apply=args.apply" in src and "dry run" in src
