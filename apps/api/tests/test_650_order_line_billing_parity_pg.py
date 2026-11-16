"""Migration 650 on a real database: what the ISSUED invoices bill against a sales-order line is held by the database (POST-A-440).

WHAT ONLY POSTGRES CAN PROVE
    The API asks `order_cycle.over_billing` before it writes (`test_an_invoice_line_bills_the_order_line_it_names.py`), and two issues
    made at one moment could each pass that read. Here: the rule's SQL copy agrees with `over_billing` on every scenario (the parity
    half); an issue that would bill more than was ordered is refused and one within it is not; a draft, a cancelled and a deleted
    invoice bill nothing; a line written onto an issued invoice, and an order line whose quantity goes down, are asked too; TWO ISSUES
    IN FLIGHT AT ONCE cannot both land (the second waits for the first's lock and is refused); the functions are closed to the
    signed-in roles; the migration is idempotent; and after its rollback the same two issues both land (the negative control that the
    refusal is this migration's).

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from domain.sales import order_cycle as oc

API_ROOT = Path(__file__).resolve().parents[1]
_ADMIN = os.environ.get("HARNESS_PG")
MIGRATION = next(API_ROOT.glob("migrations/650_what_the_issued_invoices_bill_against_an_order_line_is_held_by_the_database.sql"))
ROLLBACK = next(API_ROOT.glob("migrations/650_*_rollback.sql"))

pytestmark = pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")

FIRM = "f6500000-0000-0000-0000-000000000001"
CLIENT = "c6500000-0000-0000-0000-000000000001"
CUSTOMER = "e6500000-0000-0000-0000-000000000001"
ORDER = "a6500000-0000-0000-0000-000000000001"
LINE = "b6500000-0000-0000-0000-000000000001"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"] + (["-tA"] if tuples else [])
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


def _ok(dsn: str, sql: str) -> None:
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr


def _val(dsn: str, sql: str) -> str:
    r = _psql(dsn, sql, tuples=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _run(dsn: str, path: Path) -> None:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"e650_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    d = f"{admin} dbname={name}"
    try:
        _ok(d, f"""
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship');
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Cust');
            INSERT INTO sales_orders (id, firm_id, client_id, customer_id, document_no, document_date, status) VALUES
                ('{ORDER}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'SO/1', '2026-04-01', 'confirmed');
            INSERT INTO sales_order_lines (id, firm_id, client_id, order_id, description, quantity) VALUES
                ('{LINE}', '{FIRM}', '{CLIENT}', '{ORDER}', 'Widget', 10);
        """)
        yield d
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _invoice(dsn: str, n: int, quantity: str, *, status: str = "draft", deleted: bool = False) -> str:
    """A draft invoice with one line billing the order line, then put in `status` (a draft written straight as another status would
    skip the trigger that watches the move; the move is what an issue is)."""
    inv = str(uuid.UUID(int=0x6500 + n))
    _ok(dsn, f"""
        INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date)
             VALUES ('{inv}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV-{n}', '2026-04-10');
        INSERT INTO client_sales_invoice_lines (id, sales_invoice_id, description, quantity, rate_paise, sales_order_line_id)
             VALUES ('{uuid.UUID(int=0x65000 + n)}', '{inv}', 'Widget', {quantity}, 100, '{LINE}');
    """)
    if status != "draft":
        r = _set_status(dsn, inv, status)
        assert r.returncode == 0, r.stderr
    if deleted:
        _ok(dsn, f"UPDATE client_sales_invoices SET deleted_at = now() WHERE id = '{inv}';")
    return inv


def _set_status(dsn: str, inv: str, status: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"UPDATE client_sales_invoices SET status = '{status}' WHERE id = '{inv}';")


# ── the parity half: the SQL copy and `over_billing` say the same of every scenario ─────────────────────────────────────────────────

SCENARIOS = [
    # (ordered, [(quantity, status, deleted)] of the other invoices, this invoice's quantity)
    ("10", [], "10"),
    ("10", [], "10.001"),
    ("10", [("6", "issued", False)], "4"),
    ("10", [("6", "issued", False)], "4.5"),
    ("10", [("6", "draft", False)], "6"),
    ("10", [("6", "cancelled", False)], "10"),
    ("10", [("6", "draft", True)], "10"),
    ("10", [("3", "issued", False), ("3", "paid", False)], "4"),
    ("10", [("3", "issued", False), ("3", "partially_paid", False)], "5"),
    ("2.001", [("1.001", "issued", False)], "1"),
    ("2.001", [("1.001", "issued", False)], "1.001"),
    ("10", [], "0"),
]


@pytest.mark.parametrize("ordered, others, mine", SCENARIOS)
def test_the_database_and_over_billing_agree(dsn, ordered, others, mine):
    _ok(dsn, f"UPDATE sales_order_lines SET quantity = {ordered} WHERE id = '{LINE}';")
    billed = Decimal(0)
    for n, (q, status, deleted) in enumerate(others, start=1):
        _invoice(dsn, n, q, status=status, deleted=deleted)
        if status not in ("draft", "cancelled") and not deleted:
            billed += Decimal(q)
    python_refuses = oc.over_billing(
        oc.OpenLine(order_line_id=LINE, description="Widget", ordered_qty=Decimal(ordered), delivered_qty=Decimal(0),
                    invoiced_qty=billed), Decimal(mine)) is not None
    mine_id = _invoice(dsn, 99, mine)
    r = _set_status(dsn, mine_id, "issued")
    assert (r.returncode != 0) == python_refuses, (ordered, others, mine, r.stderr)
    if python_refuses:
        assert "order_line_over_billed" in r.stderr or "unbilled" in r.stderr or "positive" in r.stderr, r.stderr


# ── each door that can make billing grow ────────────────────────────────────────────────────────────────────────────────────────

def test_an_issue_beyond_the_order_is_refused_and_one_within_it_lands(dsn):
    _invoice(dsn, 1, "6", status="issued")
    second = _invoice(dsn, 2, "6")
    r = _set_status(dsn, second, "issued")
    assert r.returncode != 0 and "more than its sales order line has unbilled" in r.stderr, r.stderr
    assert "12.000" in r.stderr and "10.000" in r.stderr
    assert _val(dsn, f"SELECT status FROM client_sales_invoices WHERE id = '{second}'") == "draft"
    _ok(dsn, f"UPDATE client_sales_invoice_lines SET quantity = 4 WHERE sales_invoice_id = '{second}';")
    assert _set_status(dsn, second, "issued").returncode == 0


def test_undeleting_or_un_cancelling_into_billing_is_asked_too(dsn):
    _invoice(dsn, 1, "8", status="issued")
    gone = _invoice(dsn, 2, "8", status="cancelled")
    r = _set_status(dsn, gone, "issued")
    assert r.returncode != 0 and "unbilled" in r.stderr


def test_a_line_written_onto_an_issued_invoice_and_an_order_line_reduced_are_asked(dsn):
    inv = _invoice(dsn, 1, "6", status="issued")
    r = _psql(dsn, f"""INSERT INTO client_sales_invoice_lines (id, sales_invoice_id, description, quantity, rate_paise, sales_order_line_id)
                       VALUES ('{uuid.UUID(int=0x777)}', '{inv}', 'Widget', 5, 100, '{LINE}');""")
    assert r.returncode != 0 and "unbilled" in r.stderr, r.stderr
    r = _psql(dsn, f"UPDATE client_sales_invoice_lines SET quantity = 11 WHERE sales_invoice_id = '{inv}';")
    assert r.returncode != 0 and "unbilled" in r.stderr, r.stderr
    r = _psql(dsn, f"UPDATE sales_order_lines SET quantity = 5 WHERE id = '{LINE}';")
    assert r.returncode != 0 and "unbilled" in r.stderr, r.stderr
    _ok(dsn, f"UPDATE sales_order_lines SET quantity = 6 WHERE id = '{LINE}';")


def test_a_draft_bills_nothing_so_its_lines_are_the_apis_to_judge(dsn):
    _invoice(dsn, 1, "10", status="issued")
    _invoice(dsn, 2, "10")                                  # a draft over the order is written; it is refused when it is issued
    assert _val(dsn, f"SELECT count(*) FROM client_sales_invoice_lines WHERE sales_order_line_id = '{LINE}'") == "2"


def test_the_functions_are_closed_to_the_signed_in_roles(dsn):
    for fn in ("public.order_lines_billed_beyond_what_was_ordered(uuid[])",
               "public.invoice_that_starts_to_bill_is_within_its_orders()",
               "public.invoice_lines_that_bill_are_within_their_orders()",
               "public.order_line_reduced_stays_above_what_is_billed()"):
        for role in ("anon", "authenticated"):
            assert _val(dsn, f"SELECT has_function_privilege('{role}', '{fn}', 'EXECUTE')") == "f", (fn, role)


# ── the race the migration exists for ───────────────────────────────────────────────────────────────────────────────────────────

def _wait_until_a_session_sleeps(dsn: str, timeout: float = 15.0) -> None:
    stop = time.time() + timeout
    while time.time() < stop:
        if _val(dsn, "SELECT count(*) FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND state = 'active' "
                     "AND query LIKE '%pg_sleep(2)%' AND query NOT LIKE '%pg_stat_activity%';") != "0":
            return
        time.sleep(0.05)
    raise AssertionError("the first session never reached its sleep")


def _two_issues_at_once(dsn: str) -> tuple[subprocess.CompletedProcess, float, str, str]:
    a, b = _invoice(dsn, 1, "6"), _invoice(dsn, 2, "6")
    first = subprocess.Popen(["psql", dsn, "-X", "-q", "-tA", "-v", "ON_ERROR_STOP=1", "-c",
                              f"BEGIN; UPDATE client_sales_invoices SET status = 'issued' WHERE id = '{a}'; SELECT pg_sleep(2); COMMIT;"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _wait_until_a_session_sleeps(dsn)
    started = time.time()
    second = _set_status(dsn, b, "issued")
    waited = time.time() - started
    first.communicate(timeout=30)
    assert first.returncode == 0
    return second, waited, a, b


def test_two_issues_in_flight_at_once_cannot_both_land(dsn):
    second, waited, _a, b = _two_issues_at_once(dsn)
    assert second.returncode != 0 and "unbilled" in second.stderr, second.stderr
    assert waited >= 0.5, f"the second issue did not wait for the first ({waited:.2f}s)"
    assert _val(dsn, f"SELECT status FROM client_sales_invoices WHERE id = '{b}'") == "draft"


def test_the_migration_is_idempotent_and_after_its_rollback_both_issues_land(dsn):
    _run(dsn, MIGRATION)
    _run(dsn, ROLLBACK)
    _run(dsn, ROLLBACK)
    assert _val(dsn, "SELECT count(*) FROM pg_proc WHERE proname = 'order_lines_billed_beyond_what_was_ordered'") == "0"
    # THE NEGATIVE CONTROL: without the migration the same race bills 12 against 10.
    second, _waited, _a, _b = _two_issues_at_once(dsn)
    assert second.returncode == 0, second.stderr
    assert _val(dsn, f"""SELECT sum(l.quantity) FROM client_sales_invoice_lines l JOIN client_sales_invoices i ON i.id = l.sales_invoice_id
                         WHERE l.sales_order_line_id = '{LINE}' AND i.status = 'issued'""") == "12.000"
