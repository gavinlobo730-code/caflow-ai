"""
Migration 282 — a statement built from the window must equal one built from the
whole history, exactly.

WHAT IS BEING PROVED
    customer_statement_service and its vendor mirror used to fetch a party's
    ENTIRE history to print one window of it, because the opening balance is the
    seed plus every movement before the window. public.party_opening_position
    answers that in the database, which lets the document fetches be bounded.

    So there are now two routes to the same statement, and this file asserts they
    produce the identical document — every transaction, every total, the opening
    and closing balances, and the per-currency closing split:

      A (unchanged)  full history fetched, opening replayed in Python
      B (new)        window fetched, opening from the SQL function

    Both run through generate(), not through a hand-assembled builder call, so
    what is compared is the code a CA's request actually executes.

WHY THE FUNCTION RETURNS A POSITION AND NOT A BALANCE
    scenario "foreign_only_before_the_window" is the reason, and it is the one to
    read if this file ever needs changing. attach_currency_outstanding splits the
    closing outstanding by currency and reconciles it to closing_balance_paise,
    which it can only do by accumulating every movement on or before the period
    end. A single opening number has summed the currency dimension away. Route B
    would then emit no split at all for a customer whose foreign invoices all
    predate the window — a silent difference in a document sent to that customer.

WHY A REAL DATABASE
    Only Postgres can prove what the function computes. The Python half runs
    against the FakeDB holding the identical rows.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="SQL/Python parity proof requires HARNESS_PG + psql",
)

from services.customer_statement_service import customer_statement_service as CS  # noqa: E402
from services.vendor_statement_service import vendor_statement_service as VS      # noqa: E402
from tests.e2e_harness import FakeDB, _apply_generated                            # noqa: E402

FIRM = "f8200000-0000-0000-0000-000000000001"
CLIENT = "c8200000-0000-0000-0000-000000000001"
CUST = "d8200000-0000-0000-0000-000000000001"
OTHER_CUST = "d8200000-0000-0000-0000-000000000002"
VEND = "e8200000-0000-0000-0000-000000000001"
OTHER_VEND = "e8200000-0000-0000-0000-000000000002"

START, END = "2026-04-01", "2027-03-31"
BEFORE = "2025-09-15"      # comfortably before the window
AFTER = "2027-06-01"       # comfortably after it


def _i(n: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"stmtparity.{n}"))


# ── document builders ────────────────────────────────────────────────────────

def inv(n, when, total, *, status="issued", deleted=False, cur="INR", txn_total=None,
        customer=CUST):
    return {"id": _i(n), "firm_id": FIRM, "client_id": CLIENT, "customer_id": customer,
            "invoice_no": f"INV-{n}", "invoice_date": when, "total_paise": total,
            "paid_paise": 0, "credited_paise": 0, "debit_note_paise": 0,
            "status": status, "deleted_at": "2026-01-01T00:00:00+00:00" if deleted else None,
            "txn_currency": cur, "exchange_rate": 83.5,
            "txn_total": txn_total if txn_total is not None else total, "paid_txn": 0}


def rcpt(n, when, amount, *, unallocated=0, reversed_=False, cur="INR", txn_amount=None,
         customer=CUST, tds=0):
    return {"id": _i(n), "firm_id": FIRM, "client_id": CLIENT, "customer_id": customer,
            "receipt_no": f"RCT-{n}", "receipt_date": when, "amount_paise": amount,
            "tds_paise": tds, "allocated_paise": 0, "unallocated_paise": unallocated,
            "is_reversed": reversed_, "txn_currency": cur, "exchange_rate": 83.5,
            "txn_amount": txn_amount}


def alloc(n, receipt_n, amount, *, voided=False, invoice_n=1):
    # sales_invoice_id is NOT NULL in the real schema, so an allocation always
    # points at an invoice the scenario actually seeded.
    return {"id": _i(n), "receipt_id": _i(receipt_n), "sales_invoice_id": _i(invoice_n),
            "allocated_paise": amount, "is_voided": voided, "allocated_txn": None}


def cnote(n, when, total, *, status="issued", deleted=False, customer=CUST):
    return {"id": _i(n), "firm_id": FIRM, "client_id": CLIENT, "customer_id": customer,
            "credit_note_no": f"CN-{n}", "credit_note_date": when, "total_paise": total,
            "status": status, "deleted_at": "2026-01-01T00:00:00+00:00" if deleted else None}


def sdnote(n, when, total, *, status="issued", customer=CUST):
    return {"id": _i(n), "firm_id": FIRM, "client_id": CLIENT, "customer_id": customer,
            "debit_note_no": f"SDN-{n}", "debit_note_date": when, "total_paise": total,
            "status": status, "deleted_at": None}


def bill(n, when, net, *, status="received", deleted=False, cur="INR", txn_net=None,
         vendor=VEND):
    return {"id": _i(n), "firm_id": FIRM, "client_id": CLIENT, "vendor_id": vendor,
            "bill_no": f"BILL-{n}", "bill_date": when, "net_payable_paise": net,
            "paid_paise": 0, "debited_paise": 0, "credit_note_paise": 0, "status": status,
            "deleted_at": "2026-01-01T00:00:00+00:00" if deleted else None,
            "txn_currency": cur, "exchange_rate": 83.5,
            "txn_net_payable": txn_net if txn_net is not None else net, "paid_txn": 0}


def pay(n, when, amount, *, reversed_=False, cur="INR", txn_amount=None, vendor=VEND):
    return {"id": _i(n), "firm_id": FIRM, "client_id": CLIENT, "vendor_id": vendor,
            "payment_no": f"PAY-{n}", "payment_date": when, "amount_paise": amount,
            "is_reversed": reversed_, "txn_currency": cur, "exchange_rate": 83.5,
            "txn_amount": txn_amount, "unallocated_paise": 0}


def fxadj(n, payment_n, delta):
    return {"id": _i(n), "firm_id": FIRM, "client_id": CLIENT, "kind": "realized",
            "document_type": "purchase_payment", "document_id": _i(payment_n),
            "currency": "USD", "original_rate": 83.0, "settlement_rate": 84.0,
            "closing_rate": None, "base_delta_paise": delta, "journal_entry_id": None,
            "rate_source": "settlement", "created_at": "2026-06-01T00:00:00+00:00",
            "created_by": None}


def pcnote(n, when, total, *, status="issued", vendor=VEND):
    return {"id": _i(n), "firm_id": FIRM, "client_id": CLIENT, "vendor_id": vendor,
            "credit_note_no": f"PCN-{n}", "credit_note_date": when, "total_paise": total,
            "status": status, "deleted_at": None}


def vdnote(n, when, total, *, status="issued", vendor=VEND):
    return {"id": _i(n), "firm_id": FIRM, "client_id": CLIENT, "vendor_id": vendor,
            "debit_note_no": f"VDN-{n}", "debit_note_date": when, "total_paise": total,
            "status": status, "deleted_at": None}


def _store(**kw) -> dict:
    base = {"client_sales_invoices": [], "receipts": [], "receipt_allocations": [],
            "credit_notes": [], "sales_debit_notes": [], "purchase_bills": [],
            "purchase_payments": [], "purchase_credit_notes": [], "debit_notes": [],
            "fx_adjustments": []}
    base.update(kw)
    return base


# ── scenarios ────────────────────────────────────────────────────────────────

def _customer_scenarios() -> list[tuple[str, dict, int]]:
    """(name, store, customer seed balance)."""
    out = []
    out.append(("nothing_at_all", _store(), 0))
    out.append(("seed_only", _store(), 250_000))

    out.append(("invoices_either_side_of_the_window", _store(
        client_sales_invoices=[inv(1, BEFORE, 100_000), inv(2, "2026-06-01", 200_000),
                               inv(3, AFTER, 400_000)]), 0))

    out.append(("seed_and_history", _store(
        client_sales_invoices=[inv(1, BEFORE, 100_000), inv(2, "2026-06-01", 200_000)]),
        75_000))

    out.append(("receipt_with_allocations_and_unallocated", _store(
        client_sales_invoices=[inv(1, BEFORE, 500_000)],
        receipts=[rcpt(10, BEFORE, 300_000, unallocated=20_000),
                  rcpt(11, "2026-07-01", 100_000)],
        receipt_allocations=[alloc(20, 10, 280_000), alloc(21, 11, 100_000)]), 0))

    out.append(("reversed_receipt_excluded", _store(
        client_sales_invoices=[inv(1, BEFORE, 500_000)],
        receipts=[rcpt(10, BEFORE, 300_000, reversed_=True),
                  rcpt(11, "2026-07-01", 100_000, reversed_=True)],
        receipt_allocations=[alloc(20, 10, 300_000), alloc(21, 11, 100_000)]), 0))

    # The Python does NOT filter receipt_allocations on is_voided, so neither may
    # the SQL. This scenario is what would catch it if either side started to.
    out.append(("voided_allocation_still_counted", _store(
        client_sales_invoices=[inv(1, BEFORE, 500_000)],
        receipts=[rcpt(10, BEFORE, 300_000)],
        receipt_allocations=[alloc(20, 10, 300_000, voided=True)]), 0))

    out.append(("draft_and_cancelled_invoices_excluded", _store(
        client_sales_invoices=[inv(1, BEFORE, 100_000, status="draft"),
                               inv(2, BEFORE, 100_000, status="cancelled"),
                               inv(3, BEFORE, 100_000),
                               inv(4, "2026-06-01", 50_000, status="draft")]), 0))

    out.append(("deleted_invoice_excluded", _store(
        client_sales_invoices=[inv(1, BEFORE, 100_000, deleted=True),
                               inv(2, BEFORE, 100_000)]), 0))

    out.append(("notes_on_both_sides", _store(
        client_sales_invoices=[inv(1, BEFORE, 500_000)],
        # 'draft', not 'cancelled': credit_notes_status_check allows only
        # draft/issued/applied, so the services' _DEAD set names a status the
        # schema cannot hold. draft is the reachable half of that set.
        credit_notes=[cnote(30, BEFORE, 40_000), cnote(31, "2026-08-01", 10_000),
                      cnote(32, BEFORE, 90_000, status="draft")],
        sales_debit_notes=[sdnote(40, BEFORE, 25_000), sdnote(41, "2026-09-01", 5_000)]), 0))

    out.append(("foreign_invoice_in_the_window", _store(
        client_sales_invoices=[inv(1, "2026-06-01", 835_000, cur="USD", txn_total=10_000)]),
        0))

    # THE scenario. Every foreign document predates the window, so route B sees
    # only INR events and would emit no currency split at all if the opening were
    # a bare number.
    out.append(("foreign_only_before_the_window", _store(
        client_sales_invoices=[inv(1, BEFORE, 835_000, cur="USD", txn_total=10_000),
                               inv(2, "2026-06-01", 200_000)],
        receipts=[rcpt(10, BEFORE, 417_500, cur="USD", txn_amount=5_000)],
        receipt_allocations=[alloc(20, 10, 417_500)]), 0))

    out.append(("foreign_before_and_inside", _store(
        client_sales_invoices=[inv(1, BEFORE, 835_000, cur="USD", txn_total=10_000),
                               inv(2, "2026-06-01", 900_000, cur="EUR", txn_total=9_500),
                               inv(3, "2026-07-01", 200_000)],
        receipts=[rcpt(10, BEFORE, 417_500, cur="USD", txn_amount=5_000)],
        receipt_allocations=[alloc(20, 10, 417_500)]), 40_000))

    out.append(("window_edges", _store(
        client_sales_invoices=[inv(1, "2026-03-31", 10_000), inv(2, START, 20_000),
                               inv(3, END, 40_000), inv(4, "2027-04-01", 80_000)]), 0))

    out.append(("another_customers_documents_excluded", _store(
        client_sales_invoices=[inv(1, BEFORE, 100_000),
                               inv(2, BEFORE, 999_000, customer=OTHER_CUST),
                               inv(3, "2026-06-01", 50_000, customer=OTHER_CUST)],
        receipts=[rcpt(10, BEFORE, 500_000, customer=OTHER_CUST)]), 0))

    out.append(("everything_at_once", _store(
        client_sales_invoices=[inv(1, BEFORE, 835_000, cur="USD", txn_total=10_000),
                               inv(2, BEFORE, 300_000), inv(3, "2026-06-01", 200_000),
                               inv(4, "2026-11-11", 150_000, status="cancelled"),
                               inv(5, AFTER, 700_000)],
        receipts=[rcpt(10, BEFORE, 100_000, unallocated=5_000),
                  rcpt(11, "2026-08-08", 60_000, tds=4_000),
                  rcpt(12, "2026-09-09", 20_000, reversed_=True)],
        receipt_allocations=[alloc(20, 10, 95_000), alloc(21, 11, 60_000)],
        credit_notes=[cnote(30, BEFORE, 25_000), cnote(31, "2026-10-10", 8_000)],
        sales_debit_notes=[sdnote(40, BEFORE, 12_000), sdnote(41, "2026-12-12", 3_000)]),
        60_000))
    return out


def _vendor_scenarios() -> list[tuple[str, dict, int]]:
    out = []
    out.append(("nothing_at_all", _store(), 0))
    out.append(("seed_only", _store(), 180_000))

    out.append(("bills_either_side_of_the_window", _store(
        purchase_bills=[bill(1, BEFORE, 100_000), bill(2, "2026-06-01", 200_000),
                        bill(3, AFTER, 400_000)]), 0))

    out.append(("payments_relieve_the_payable", _store(
        purchase_bills=[bill(1, BEFORE, 500_000)],
        purchase_payments=[pay(10, BEFORE, 200_000), pay(11, "2026-07-01", 50_000)]), 0))

    out.append(("reversed_payment_excluded", _store(
        purchase_bills=[bill(1, BEFORE, 500_000)],
        purchase_payments=[pay(10, BEFORE, 200_000, reversed_=True),
                           pay(11, "2026-07-01", 50_000, reversed_=True)]), 0))

    # ap_relief = amount + the booked/settlement delta, which is only ever
    # non-zero for a foreign payment.
    out.append(("foreign_payment_carries_the_fx_delta", _store(
        purchase_bills=[bill(1, BEFORE, 835_000, cur="USD", txn_net=10_000)],
        purchase_payments=[pay(10, BEFORE, 420_000, cur="USD", txn_amount=5_000)],
        fx_adjustments=[fxadj(50, 10, -2_500)]), 0))

    out.append(("draft_and_deleted_bills_excluded", _store(
        purchase_bills=[bill(1, BEFORE, 100_000, status="draft"),
                        bill(2, BEFORE, 100_000, deleted=True),
                        bill(3, BEFORE, 100_000)]), 0))

    out.append(("notes_on_both_sides", _store(
        purchase_bills=[bill(1, BEFORE, 500_000)],
        purchase_credit_notes=[pcnote(30, BEFORE, 30_000), pcnote(31, "2026-08-01", 7_000)],
        debit_notes=[vdnote(40, BEFORE, 20_000), vdnote(41, "2026-09-01", 4_000)]), 0))

    out.append(("foreign_only_before_the_window", _store(
        purchase_bills=[bill(1, BEFORE, 835_000, cur="USD", txn_net=10_000),
                        bill(2, "2026-06-01", 200_000)],
        purchase_payments=[pay(10, BEFORE, 417_500, cur="USD", txn_amount=5_000)]), 0))

    out.append(("window_edges", _store(
        purchase_bills=[bill(1, "2026-03-31", 10_000), bill(2, START, 20_000),
                        bill(3, END, 40_000), bill(4, "2027-04-01", 80_000)]), 0))

    out.append(("another_vendors_documents_excluded", _store(
        purchase_bills=[bill(1, BEFORE, 100_000),
                        bill(2, BEFORE, 999_000, vendor=OTHER_VEND)],
        purchase_payments=[pay(10, BEFORE, 500_000, vendor=OTHER_VEND)]), 0))

    out.append(("everything_at_once", _store(
        purchase_bills=[bill(1, BEFORE, 835_000, cur="USD", txn_net=10_000),
                        bill(2, BEFORE, 300_000), bill(3, "2026-06-01", 200_000),
                        bill(4, AFTER, 700_000)],
        purchase_payments=[pay(10, BEFORE, 120_000), pay(11, "2026-08-08", 60_000),
                           pay(12, "2026-09-09", 20_000, reversed_=True),
                           pay(13, BEFORE, 300_000, cur="USD", txn_amount=3_600)],
        fx_adjustments=[fxadj(50, 13, 1_500)],
        purchase_credit_notes=[pcnote(30, BEFORE, 15_000), pcnote(31, "2026-10-10", 6_000)],
        debit_notes=[vdnote(40, BEFORE, 9_000), vdnote(41, "2026-12-12", 2_000)]), 45_000))
    return out


CUSTOMER_SCENARIOS = _customer_scenarios()
VENDOR_SCENARIOS = _vendor_scenarios()


# ── the two routes ───────────────────────────────────────────────────────────

def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    # Via a file, not -c: one scenario seeds 300 invoices to prove the windowed
    # route reads less, and that command line exceeds the kernel's argv limit.
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as fh:
        fh.write(sql)
        path = fh.name
    try:
        return subprocess.run(args + ["-f", path], capture_output=True, text=True)
    finally:
        os.unlink(path)


def _q(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


_COLUMNS = {
    "client_sales_invoices": ["id", "firm_id", "client_id", "customer_id", "invoice_no",
                              "invoice_date", "total_paise", "paid_paise", "credited_paise",
                              "debit_note_paise", "status", "deleted_at", "txn_currency",
                              "exchange_rate", "txn_total", "paid_txn"],
    "receipts": ["id", "firm_id", "client_id", "customer_id", "receipt_no", "receipt_date",
                 "amount_paise", "tds_paise", "allocated_paise", "unallocated_paise",
                 "is_reversed", "txn_currency", "exchange_rate", "txn_amount"],
    "receipt_allocations": ["id", "receipt_id", "sales_invoice_id", "allocated_paise",
                            "is_voided"],
    "credit_notes": ["id", "firm_id", "client_id", "customer_id", "credit_note_no",
                     "credit_note_date", "total_paise", "status", "deleted_at"],
    "sales_debit_notes": ["id", "firm_id", "client_id", "customer_id", "debit_note_no",
                          "debit_note_date", "total_paise", "status", "deleted_at"],
    "purchase_bills": ["id", "firm_id", "client_id", "vendor_id", "bill_no", "bill_date",
                       "net_payable_paise", "paid_paise", "debited_paise",
                       "credit_note_paise", "status", "deleted_at", "txn_currency",
                       "exchange_rate", "txn_net_payable", "paid_txn"],
    "purchase_payments": ["id", "firm_id", "client_id", "vendor_id", "payment_no",
                          "payment_date", "amount_paise", "is_reversed", "txn_currency",
                          "exchange_rate", "txn_amount", "unallocated_paise"],
    "purchase_credit_notes": ["id", "firm_id", "client_id", "vendor_id", "credit_note_no",
                              "credit_note_date", "total_paise", "status", "deleted_at"],
    "debit_notes": ["id", "firm_id", "client_id", "vendor_id", "debit_note_no",
                    "debit_note_date", "total_paise", "status", "deleted_at"],
    "fx_adjustments": ["id", "firm_id", "client_id", "kind", "document_type", "document_id",
                       "currency", "original_rate", "settlement_rate", "closing_rate",
                       "base_delta_paise", "journal_entry_id", "rate_source", "created_at",
                       "created_by"],
}


def _seed_sql(store: dict, cust_seed: int, vend_seed: int) -> str:
    out = [f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'Stmt Parity', 's@parity.in');",
           "INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES "
           f"('{CLIENT}', '{FIRM}', 'Stmt Co', 'Proprietorship');"]
    for cid, seed in ((CUST, cust_seed), (OTHER_CUST, 0)):
        out.append("INSERT INTO customers (id, firm_id, client_id, name, opening_balance_paise) "
                   f"VALUES ('{cid}', '{FIRM}', '{CLIENT}', 'Cust {cid[:8]}', {seed});")
    for vid, seed in ((VEND, vend_seed), (OTHER_VEND, 0)):
        out.append("INSERT INTO vendors (id, firm_id, client_id, name, opening_balance_paise) "
                   f"VALUES ('{vid}', '{FIRM}', '{CLIENT}', 'Vend {vid[:8]}', {seed});")
    for table, cols in _COLUMNS.items():
        for row in store.get(table, []):
            vals = ", ".join(_q(row.get(c)) for c in cols)
            out.append(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({vals});")
    return "\n".join(out)


class _PgRpc:
    def __init__(self, dsn: str, fn: str, params: dict):
        self.dsn, self.fn, self.params = dsn, fn, params

    def execute(self):
        assert self.fn == "party_opening_position", self.fn
        args = ", ".join([
            f"p_firm => {_q(self.params['p_firm'])}::uuid",
            f"p_client => {_q(self.params['p_client'])}::uuid",
            f"p_party => {_q(self.params['p_party'])}::uuid",
            f"p_kind => {_q(self.params['p_kind'])}::text",
            f"p_before => {_q(self.params['p_before'])}::date",
        ])
        r = _psql(self.dsn, f"SELECT public.{self.fn}({args});", tuples=True)
        assert r.returncode == 0, f"party_opening_position failed: {r.stderr}"
        return type("R", (), {"data": json.loads(r.stdout.strip())})()


class _SqlRpcDB:
    """Route B's database: table reads from the FakeDB, .rpc() against Postgres."""

    def __init__(self, fake: FakeDB, dsn: str):
        self._fake, self._dsn = fake, dsn

    def table(self, name):
        return self._fake.table(name)

    def rpc(self, fn: str, params=None):
        return _PgRpc(self._dsn, fn, params or {})


class _NoRpcDB:
    """Route A's database: the FakeDB with .rpc() removed, which is how the
    services detect "no database to ask" and replay the whole history."""

    def __init__(self, fake: FakeDB):
        self._fake = fake

    def table(self, name):
        return self._fake.table(name)


def _fake(store: dict, cust_seed: int, vend_seed: int) -> FakeDB:
    db = FakeDB()
    tables = {k: [dict(r) for r in v] for k, v in store.items()}
    tables["customers"] = [
        {"id": CUST, "firm_id": FIRM, "client_id": CLIENT, "name": f"Cust {CUST[:8]}",
         "opening_balance_paise": cust_seed},
        {"id": OTHER_CUST, "firm_id": FIRM, "client_id": CLIENT, "name": "Other",
         "opening_balance_paise": 0}]
    tables["vendors"] = [
        {"id": VEND, "firm_id": FIRM, "client_id": CLIENT, "name": f"Vend {VEND[:8]}",
         "opening_balance_paise": vend_seed},
        {"id": OTHER_VEND, "firm_id": FIRM, "client_id": CLIENT, "name": "Other",
         "opening_balance_paise": 0}]
    for name, rows in tables.items():
        _apply_generated(name, rows)
    db._tables.update(tables)
    return db


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"stpar_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{admin} dbname={name}"
    try:
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _routes(dsn: str, store: dict, cust_seed: int = 0, vend_seed: int = 0):
    seed = _psql(dsn, _seed_sql(store, cust_seed, vend_seed))
    assert seed.returncode == 0, f"seed failed: {seed.stderr}"
    a = _NoRpcDB(_fake(store, cust_seed, vend_seed))
    b = _SqlRpcDB(_fake(store, cust_seed, vend_seed), dsn)
    return a, b


# ── the parity proof ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,store,seed", CUSTOMER_SCENARIOS,
                         ids=[s[0] for s in CUSTOMER_SCENARIOS])
def test_customer_statement_windowed_matches_full_replay(db, name, store, seed):
    a, b = _routes(db, store, cust_seed=seed)
    assert CS.generate(b, FIRM, CLIENT, CUST, START, END) == \
           CS.generate(a, FIRM, CLIENT, CUST, START, END), name


@pytest.mark.parametrize("name,store,seed", VENDOR_SCENARIOS,
                         ids=[s[0] for s in VENDOR_SCENARIOS])
def test_vendor_statement_windowed_matches_full_replay(db, name, store, seed):
    a, b = _routes(db, store, vend_seed=seed)
    assert VS.generate(b, FIRM, CLIENT, VEND, START, END) == \
           VS.generate(a, FIRM, CLIENT, VEND, START, END), name


def test_the_windowed_route_really_is_reading_less(db):
    """The guard. Every comparison above would also pass if route B quietly fell
    back to the full fetch — a broken function, a typo in the rpc name — and would
    then be comparing the old path with itself. This counts the rows each route
    pulled, over a party with a long history and a short window."""
    store = _store(client_sales_invoices=(
        [inv(1000 + i, BEFORE, 10_000) for i in range(300)]
        + [inv(1, "2026-06-01", 20_000)]))
    a, b = _routes(db, store)

    def rows(target) -> int:
        counted = {"n": 0}
        real = target.table

        def table(nm):
            q = real(nm)
            inner = q.execute

            def execute():
                res = inner()
                counted["n"] += len(res.data or [])
                return res

            q.execute = execute      # type: ignore[method-assign]
            return q

        target.table = table         # type: ignore[method-assign]
        CS.generate(target, FIRM, CLIENT, CUST, START, END)
        return counted["n"]

    full, windowed = rows(a), rows(b)
    assert full >= 300, full
    assert windowed < 20, (
        f"the windowed route read {windowed} rows against the full route's {full} — "
        f"it is not using the opening position")


def test_the_position_itself_is_what_the_replay_would_have_computed(db):
    """One direct assertion on the function, so a failure above can be localised
    to the position rather than to statement assembly."""
    store = _store(
        client_sales_invoices=[inv(1, BEFORE, 835_000, cur="USD", txn_total=10_000),
                               inv(2, BEFORE, 300_000)],
        receipts=[rcpt(10, BEFORE, 100_000, unallocated=5_000)],
        receipt_allocations=[alloc(20, 10, 95_000)],
        credit_notes=[cnote(30, BEFORE, 25_000)],
        sales_debit_notes=[sdnote(40, BEFORE, 12_000)])
    _, b = _routes(db, store, cust_seed=60_000)
    pos = b.rpc("party_opening_position", {
        "p_firm": FIRM, "p_client": CLIENT, "p_party": CUST,
        "p_kind": "customer", "p_before": START}).execute().data

    # 60,000 seed + 835,000 + 300,000 invoiced + 12,000 debit note
    #          − 100,000 receipt relief (95,000 allocated + 5,000 unallocated)
    #          − 25,000 credit note
    assert pos["opening_balance_paise"] == 1_082_000, pos
    by = {r["currency"]: r for r in pos["by_currency"]}
    assert by["USD"]["base_paise"] == 835_000 and by["USD"]["foreign_minor"] == 10_000, pos
    # INR slot: seed + 300,000 + 12,000 − 100,000 − 25,000
    assert by["INR"]["base_paise"] == 247_000, pos
    assert sum(r["base_paise"] for r in pos["by_currency"]) == pos["opening_balance_paise"]
