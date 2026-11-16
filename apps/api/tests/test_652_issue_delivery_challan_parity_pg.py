"""Migration 652 on a real database: issuing a delivery challan locks the order it names and holds the over-delivery rule (POST-A-421, part b).

HELD HERE: the SQL rule and `order_cycle.over_delivery` agree on every scenario (the parity half); a refusal writes nothing; only the ISSUED
challans of an order deliver against it (a draft, a cancelled and a received-back challan do not); a line naming an order line of another order,
or an order line with no order, is refused; a challan of another client is not found; TWO DRAFTS OF THE WHOLE ORDER ISSUED IN THE SAME INSTANT
cannot both land (the second waits for the first's lock and is refused); the function is closed to the signed-in roles; the migration is
idempotent; and after its rollback the same race delivers the order twice (the negative control: the refusal is this migration's).

Runs only when HARNESS_PG is set + psql on PATH.
"""
from __future__ import annotations

import pathlib
import subprocess
import time
import uuid
from decimal import Decimal

import pytest

from domain.sales import order_cycle as oc
from tests.test_585_a_delivery_challan_is_written_in_one_transaction_and_says_when_it_was_issued_pg import (  # noqa: F401
    CLIENT, FIRM, OTHER_CLIENT, _ADMIN, _call, _psql, _rows, _run_file, _wait_until_a_session_sleeps, db,
)

pytestmark = pytest.mark.skipif(not _ADMIN, reason="needs HARNESS_PG")

_M = pathlib.Path(__file__).resolve().parent.parent / "migrations"
_UP = next(_M.glob("652_issuing_a_delivery_challan_locks_its_order_and_holds_the_over_delivery_rule.sql"))
_DOWN = next(_M.glob("652_*_rollback.sql"))
FN = "public.issue_delivery_challan_atomic"
CUSTOMER = str(uuid.uuid4())


def _world(dsn, ordered="10") -> tuple[str, str]:
    order, line = str(uuid.uuid4()), str(uuid.uuid4())
    _psql(dsn, f"""
        INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Cust') ON CONFLICT DO NOTHING;
        INSERT INTO sales_orders (id, firm_id, client_id, customer_id, document_no, document_date, status)
             VALUES ('{order}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'SO/{order[:4]}', '2026-04-01', 'confirmed');
        INSERT INTO sales_order_lines (id, firm_id, client_id, order_id, description, quantity)
             VALUES ('{line}', '{FIRM}', '{CLIENT}', '{order}', 'Widget', {ordered});""")
    return order, line


def _challan(dsn, order, line, qty, *, status="draft", no=None, order_line="same") -> str:
    cid = str(uuid.uuid4())
    named = line if order_line == "same" else order_line
    issued = ", issued_at" if status in ("issued", "received_back") else ""
    stamp = ", now()" if issued else ""
    ol = f"'{named}'" if named else "NULL"
    done = _psql(dsn, f"""
        INSERT INTO delivery_challans (id, firm_id, client_id, document_no, document_date, reason, status, order_id{issued})
             VALUES ('{cid}', '{FIRM}', '{CLIENT}', '{no or cid[:8]}', DATE '2026-05-10', 'supply_invoice_to_follow', '{status}', {"'" + order + "'" if order else "NULL"}{stamp});
        INSERT INTO delivery_challan_lines (id, firm_id, client_id, challan_id, line_order, description, quantity, unit, order_line_id)
             VALUES ('{uuid.uuid4()}', '{FIRM}', '{CLIENT}', '{cid}', 0, 'Widget', {qty}, 'NOS', {ol});""")
    assert done.returncode == 0, done.stderr
    return cid


def _issue(dsn, cid, client=CLIENT):
    return _call(dsn, f"SELECT {FN}('{FIRM}', '{client}', '{cid}', now());")


def _status(dsn, cid):
    return _rows(dsn, f"SELECT status || '|' || (issued_at IS NOT NULL)::text FROM delivery_challans WHERE id = '{cid}';")[0]


# (ordered, [(quantity, status) of the other challans], my quantity)
SCENARIOS = [
    ("10", [], "10"), ("10", [], "10.001"), ("10", [("6", "issued")], "4"), ("10", [("6", "issued")], "4.5"),
    ("10", [("6", "draft")], "10"), ("10", [("6", "cancelled")], "10"), ("10", [("6", "received_back")], "10"),
    ("10", [("3", "issued"), ("3", "issued")], "4"), ("10", [("3", "issued"), ("3", "issued")], "5"),
    ("2.001", [("1.001", "issued")], "1"), ("2.001", [("1.001", "issued")], "1.001"), ("10", [], "0"),
]


@pytest.mark.parametrize("ordered, others, mine", SCENARIOS)
def test_the_database_and_over_delivery_agree(db, ordered, others, mine):
    order, line = _world(db, ordered)
    delivered = Decimal(0)
    for q, status in others:
        _challan(db, order, line, q, status=status)
        if status == "issued":
            delivered += Decimal(q)
    python_refuses = oc.over_delivery(oc.OpenLine(order_line_id=line, description="Widget", ordered_qty=Decimal(ordered),
                                                  delivered_qty=delivered, invoiced_qty=Decimal(0)), Decimal(mine)) is not None
    cid = _challan(db, order, line, mine)
    done = _issue(db, cid)
    assert (done.returncode != 0) == python_refuses, (ordered, others, mine, done.stderr)
    assert _status(db, cid) == ("draft|false" if python_refuses else "issued|true")
    if python_refuses:
        assert "order_over_delivered" in done.stderr


def test_a_challan_with_no_order_is_issued_and_one_naming_an_order_line_it_has_no_order_for_is_refused(db):
    plain = _challan(db, None, None, "5", order_line=None)
    assert _issue(db, plain).returncode == 0 and _status(db, plain) == "issued|true"
    order, line = _world(db)
    stray = _challan(db, None, line, "5")
    assert "order_line_not_of_order" in _issue(db, stray).stderr and _status(db, stray) == "draft|false"
    other_order, other_line = _world(db)
    cross = _challan(db, order, other_line, "5")
    assert "order_line_not_of_order" in _issue(db, cross).stderr and _status(db, cross) == "draft|false"


def test_only_a_draft_of_this_client_is_issued_and_nothing_is_written_otherwise(db):
    order, line = _world(db)
    cid = _challan(db, order, line, "1")
    assert "challan_not_found" in _issue(db, cid, client=OTHER_CLIENT).stderr and _status(db, cid) == "draft|false"
    assert _issue(db, cid).returncode == 0
    again = _issue(db, cid)
    assert again.returncode != 0 and "challan_not_draft" in again.stderr


def test_the_function_is_closed_to_signed_in_roles(db):
    fn = f"{FN}(uuid, uuid, uuid, timestamptz)"
    for role in ("anon", "authenticated", "public"):
        assert _rows(db, f"SELECT has_function_privilege('{role}', '{fn}', 'EXECUTE');") == ["f"]
    assert _rows(db, f"SELECT has_function_privilege('service_role', '{fn}', 'EXECUTE');") == ["t"]


def _two_issues_at_once(dsn):
    order, line = _world(dsn, "10")
    a, b = _challan(dsn, order, line, "10"), _challan(dsn, order, line, "10")
    first = subprocess.Popen(["psql", dsn, "-X", "-q", "-tA", "-c",
                              f"SET ROLE service_role; BEGIN; SELECT {FN}('{FIRM}', '{CLIENT}', '{a}', now()); SELECT pg_sleep(2); COMMIT;"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _wait_until_a_session_sleeps(dsn)
    started = time.time()
    second = _issue(dsn, b)
    waited = time.time() - started
    first.communicate(timeout=30)
    assert first.returncode == 0
    return second, waited, a, b


def test_two_drafts_of_the_whole_order_issued_at_once_cannot_both_land(db):
    second, waited, a, b = _two_issues_at_once(db)
    assert second.returncode != 0 and "order_over_delivered" in second.stderr, second.stderr
    assert waited >= 0.5, f"the second issue did not wait for the first ({waited:.2f}s)"
    assert (_status(db, a), _status(db, b)) == ("issued|true", "draft|false")


def test_the_migration_is_idempotent_and_after_its_rollback_the_same_race_delivers_the_order_twice(db):
    assert _run_file(db, _UP).returncode == 0
    assert _run_file(db, _DOWN).returncode == 0 and _run_file(db, _DOWN).returncode == 0
    assert _rows(db, "SELECT count(*) FROM pg_proc WHERE proname = 'issue_delivery_challan_atomic';") == ["0"]
    # NEGATIVE CONTROL: the compare-and-set the API had issues both, each on its own row.
    order, line = _world(db)
    a, b = _challan(db, order, line, "10"), _challan(db, order, line, "10")
    for cid in (a, b):
        assert _psql(db, f"UPDATE delivery_challans SET status = 'issued', issued_at = now() WHERE id = '{cid}' AND status = 'draft';").returncode == 0
    assert _rows(db, f"SELECT sum(l.quantity) FROM delivery_challan_lines l JOIN delivery_challans c ON c.id = l.challan_id WHERE l.order_line_id = '{line}' AND c.status = 'issued';") == ["20.000"]
