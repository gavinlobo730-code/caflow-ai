"""The delivery log of emailed customer statements is a window a CA can read (POST-A-105).

WHAT WAS WRONG
    `GET /api/customer-statements/deliveries` has been written to by the send path since the statements shipped and read by no
    screen, so a CA who emailed a customer's statement could not see whether it had gone out; it sat on the frozen list of
    computed answers nobody can open. The read itself returned EVERY delivery of the customer with every column (the mail
    service's own message id included), unbounded.

WHAT IS HELD
    * the route answers a window of the newest deliveries, newest first, with `has_more` taken from the read (one row more than
      the window is asked for and is never returned), `limit` and the server's ceiling;
    * a tie on `created_at` is broken by `id`, so a row is on exactly one window;
    * only this firm's, this client's and this customer's rows come back, and no column the screen has no use for (the
      provider's message id, the firm, client and customer keys);
    * the client-scope check is made before the read, and the no-database branch answers the same shape;
    * `limit` is bounded at the door (1 .. the server's ceiling);
    * the screen reads it: the endpoint left the frozen list of unreached answers and the per-prefix budget.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI

import routers.customer_statements as cs
from core.list_window import MAX_LIST_LIMIT
from tests.e2e_harness import FakeDB

FIRM, CLIENT, CUST = "firm-1", "client-1", "cust-1"
USER = {"id": "u1", "firm_id": FIRM, "role": "partner"}


def _row(n, *, firm=FIRM, client=CLIENT, cust=CUST, created=None, **over):
    row = {"id": f"d{n:02d}", "firm_id": firm, "client_id": client, "customer_id": cust,
           "period_start": "2026-04-01", "period_end": "2026-04-30", "sent_to": "ap@acme.test",
           "sent_by_id": "u1", "sent_by_email": "ca@firm.test", "status": "sent", "provider_message_id": f"msg-{n}",
           "error_message": None, "sent_at": f"2026-05-{n:02d}T10:00:00Z", "created_at": created or f"2026-05-{n:02d}T10:00:00Z"}
    row.update(over)
    return row


@pytest.fixture
def served(monkeypatch):
    db = FakeDB()
    checked = []
    monkeypatch.setattr(cs, "_db", lambda: db)
    monkeypatch.setattr(cs, "assert_client_access", lambda user, client_id: checked.append(client_id))
    return db, checked


def _ask(limit=50, client=CLIENT, cust=CUST):
    return cs.list_deliveries(client_id=client, customer_id=cust, limit=limit, current_user=USER)["data"]


def test_the_newest_come_first_and_the_window_says_older_ones_exist(served):
    db, _ = served
    for n in (1, 2, 3):
        db.seed("customer_statement_deliveries", _row(n))
    out = _ask(limit=2)
    assert [r["id"] for r in out["deliveries"]] == ["d03", "d02"]
    assert out["returned"] == 2 and out["has_more"] is True and out["limit"] == 2 and out["max_limit"] == MAX_LIST_LIMIT


def test_a_window_that_holds_everything_says_so(served):
    db, _ = served
    for n in (1, 2, 3):
        db.seed("customer_statement_deliveries", _row(n))
    out = _ask(limit=3)
    assert [r["id"] for r in out["deliveries"]] == ["d03", "d02", "d01"] and out["has_more"] is False
    assert _ask(limit=50)["has_more"] is False


def test_a_tie_on_the_timestamp_is_broken_by_id_so_a_row_is_on_one_window_only(served):
    db, _ = served
    same = "2026-05-09T10:00:00Z"
    for n in (4, 5, 6):
        db.seed("customer_statement_deliveries", _row(n, created=same))
    first = [r["id"] for r in _ask(limit=2)["deliveries"]]
    everything = [r["id"] for r in _ask(limit=3)["deliveries"]]
    assert first == everything[:2] == ["d06", "d05"]


def test_only_this_firms_clients_and_customers_rows_come_back(served):
    db, _ = served
    db.seed("customer_statement_deliveries", _row(1))
    db.seed("customer_statement_deliveries", _row(2, cust="cust-2"))
    db.seed("customer_statement_deliveries", _row(3, client="client-2"))
    db.seed("customer_statement_deliveries", _row(4, firm="firm-2"))
    assert [r["id"] for r in _ask()["deliveries"]] == ["d01"]


def test_no_column_the_screen_has_no_use_for_is_sent(served):
    db, _ = served
    db.seed("customer_statement_deliveries", _row(1))
    [row] = _ask()["deliveries"]
    assert set(row) == {"id", "period_start", "period_end", "sent_to", "sent_by_email", "status", "error_message", "sent_at", "created_at"}
    assert "provider_message_id" not in row and "firm_id" not in row


def test_the_scope_check_is_made_and_the_no_database_branch_answers_the_same_shape(monkeypatch, served):
    _, checked = served
    _ask()
    assert checked == [CLIENT]
    monkeypatch.setattr(cs, "_db", lambda: None)
    out = _ask(limit=10)
    assert out == {"deliveries": [], "returned": 0, "has_more": False, "limit": 10, "max_limit": MAX_LIST_LIMIT}
    assert checked == [CLIENT, CLIENT]


def test_limit_is_bounded_at_the_door():
    app = FastAPI()
    app.include_router(cs.router)
    params = {p["name"]: p for p in app.openapi()["paths"]["/api/customer-statements/deliveries"]["get"]["parameters"]}
    schema = params["limit"]["schema"]
    assert schema["minimum"] == 1 and schema["maximum"] == MAX_LIST_LIMIT and schema["default"] == cs.DELIVERY_LIST_LIMIT


def test_the_endpoint_left_the_frozen_list_of_unreached_answers():
    """The two ratchets hold the rest: the equality list would fail on a stale entry and the per-prefix budget on a stale count."""
    from tests import test_a_computed_answer_nobody_can_open_is_named as frozen
    assert "/api/customer-statements/deliveries" not in frozen.UNREACHED_COMPUTED_ANSWERS
