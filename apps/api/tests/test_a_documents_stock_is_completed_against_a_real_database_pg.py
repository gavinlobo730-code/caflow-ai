"""Completing a document whose stock effect was not all recorded, run against a real database, keeps the stock ledger and the
general ledger tied (POST-A-092, the retry the in-memory double alone had run).

WHAT WAS NOT VERIFIED
    The retry (`stock_effect_retry_service.retry` with `resume=True` on the four stock functions) had run only against the in-memory
    double of the database; the finder (migration 579) and the marks (620) had run against real Postgres. So the claim that a
    completed document leaves Inventory control equal to the stock it holds rested on a double that implements none of the database's
    own triggers (the monthly balances, the journal-line account guard, the posted-entry protections).

WHAT IS HELD, ON A MIGRATED DATABASE, AS THE ROLES PRODUCTION USES
    * a two-line sale whose second stock row was refused is found by the database's own finder, with no journal behind it;
    * the retry writes the second line only, posts ONE combined COGS entry through the real posting function for both lines' value,
      points both rows at it, and the finder stops listing the invoice;
    * afterwards the Inventory account's balance, read from the trigger-kept monthly balances, equals the sum of the stock rows'
      values for the client, and Cost of Goods Sold carries exactly the two lines' value;
    * a second retry writes nothing and says the stock is recorded in full.

HOW. `tests/_signed_in_postgrest.SignedInDb` runs each call in the real database as `service_role` (the privileged client the
retry and the stock functions use) or as an authenticated Partner (the request's own client the posting kernel reads with). Nothing
under test is replaced except which client the providers hand out, the audit writer, and the one stock-out call made to fail.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

from services.coa_seed_service import STANDARD_COA
from tests._signed_in_postgrest import SignedInDb

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the live-database proof requires HARNESS_PG + psql",
)

FIRM = "09201000-0000-0000-0000-000000000001"
CLIENT = "09201000-0000-0000-0000-0000000000a1"
CUSTOMER = "09201000-0000-0000-0000-0000000000c1"
PARTNER = {"id": "09201000-0000-0000-0000-00000000000a", "auth_user_id": "09201000-1111-0000-0000-000000000001",
           "role": "Partner", "firm_id": FIRM, "email": "partner@t.in"}
ITEM_A = "09201000-0000-0000-0000-0000000000f1"
ITEM_B = "09201000-0000-0000-0000-0000000000f2"
INVOICE = "09201000-0000-0000-0000-0000000000e1"


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql], capture_output=True, text=True)


def _rows(dsn: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-F", "\t", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return [line.split("\t") for line in r.stdout.splitlines() if line.strip()]


@pytest.fixture()
def world(pg_template, monkeypatch):
    admin = _ADMIN.strip()
    name = f"e092_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        chart = "\n".join(
            "INSERT INTO chart_of_accounts (firm_id, client_id, account_code, account_name, account_type, account_subtype, is_active) "
            f"VALUES ('{FIRM}', NULL, '{code}', '{n.replace(chr(39), chr(39) * 2)}', '{t}', "
            f"{'NULL' if sub is None else chr(39) + sub + chr(39)}, TRUE);"
            for code, n, t, sub in STANDARD_COA)
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES ('{PARTNER["auth_user_id"]}', 'partner@t.in');
            INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');
            INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES ('{CLIENT}', '{FIRM}', 'A', 'Proprietorship');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active)
                 VALUES ('{PARTNER["id"]}', '{FIRM}', '{PARTNER["auth_user_id"]}', 'partner@t.in', 'P', 'Partner', true);
            INSERT INTO customers (id, firm_id, client_id, name) VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT}', 'Buyer');
            INSERT INTO service_catalogue (id, firm_id, client_id, name, kind) VALUES
                ('{ITEM_A}', '{FIRM}', '{CLIENT}', 'Widget A', 'good'), ('{ITEM_B}', '{FIRM}', '{CLIENT}', 'Widget B', 'good');
            {chart}
        """)
        assert seed.returncode == 0, seed.stderr

        class World:
            pass

        w = World()
        w.dsn = dsn
        w.partner_db = SignedInDb(dsn, auth_user_id=PARTNER["auth_user_id"])
        w.service_db = SignedInDb(dsn, role="service_role")

        import core.authz
        import core.db_provider
        import core.supabase_client
        import services.phase2_journal_service

        monkeypatch.setenv("SUPABASE_URL", "test://db")
        monkeypatch.setattr(core.supabase_client, "get_supabase", lambda *a, **k: w.partner_db)
        monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: w.service_db)
        monkeypatch.setattr(services.phase2_journal_service, "_USE_MOCK", False)
        monkeypatch.setattr(core.authz, "_USE_MOCK", False)
        monkeypatch.setattr(core.authz, "_client_belongs_to_firm", lambda client_id, firm_id: True)
        monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None)
        yield w
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _stock_in(w, item, units, cost):
    import domain.inventory_service as inv
    inv.record_stock_in(w.service_db, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=item, movement_date="2026-04-01",
                        quantity=units, total_cost_paise=cost, movement_type="opening")


def _issued_invoice(w):
    seed = _psql(w.dsn, f"""
        INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date, status)
             VALUES ('{INVOICE}', '{FIRM}', '{CLIENT}', '{CUSTOMER}', 'INV-092', '2026-04-20', 'issued');
        INSERT INTO client_sales_invoice_lines (sales_invoice_id, description, quantity, service_catalogue_id)
             VALUES ('{INVOICE}', 'Widget A', 2, '{ITEM_A}'), ('{INVOICE}', 'Widget B', 3, '{ITEM_B}');
    """)
    assert seed.returncode == 0, seed.stderr


def _the_invoice(w) -> dict:
    return w.service_db.table("client_sales_invoices").select("*").eq("id", INVOICE).eq("firm_id", FIRM).execute().data[0]


def _first_issue_that_stops_after_line_one(w, monkeypatch):
    """The first issue's stock: line one is moved, line two's stock row is refused, so the combined journal is not posted."""
    import domain.inventory_service as inv
    real = inv.record_stock_out
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("a refused ledger row")
        return real(*args, **kwargs)

    monkeypatch.setattr(inv, "record_stock_out", flaky)
    effect = inv.apply_sale_to_inventory(w.service_db, firm_id=FIRM, client_id=CLIENT, invoice=_the_invoice(w))
    monkeypatch.setattr(inv, "record_stock_out", real)
    return effect


def _sale_rows(w) -> list[list[str]]:
    return _rows(w.dsn, f"SELECT service_catalogue_id, value_delta_paise, COALESCE(journal_entry_id::text, '') FROM inventory_stock_ledger "
                        f"WHERE source_type = 'sales_invoice' AND source_id = '{INVOICE}' ORDER BY service_catalogue_id")


def _listed(w) -> bool:
    from services import stock_effect_retry_service as svc
    found = svc.unrecorded_documents(w.service_db, firm_id=FIRM, client_id=CLIENT)
    assert found is not None, "the finder answered"
    return INVOICE in str(found)


def _balance(w, account_name: str) -> int:
    rows = _rows(w.dsn, f"""
        SELECT COALESCE(SUM(b.debit_paise - b.credit_paise), 0) FROM account_period_balances b
          JOIN chart_of_accounts c ON c.id = b.account_id
         WHERE b.client_id = '{CLIENT}' AND c.firm_id = '{FIRM}' AND c.account_name = '{account_name}'""")
    return int(rows[0][0])


def _stock_value(w) -> int:
    return int(_rows(w.dsn, f"SELECT COALESCE(SUM(value_delta_paise), 0) FROM inventory_stock_ledger WHERE client_id = '{CLIENT}'")[0][0])


def test_a_sale_stopped_after_line_one_is_completed_and_the_two_ledgers_tie(world, monkeypatch):
    from services import stock_effect_retry_service as svc
    _stock_in(world, ITEM_A, 10, 1_000_00)            # ₹100.00 each
    _stock_in(world, ITEM_B, 10, 2_000_00)            # ₹200.00 each
    _issued_invoice(world)
    opening_stock = _stock_value(world)

    first = _first_issue_that_stops_after_line_one(world, monkeypatch)
    assert (first.moved_lines, first.goods_lines, first.recorded) == (1, 2, False)
    rows = _sale_rows(world)
    assert len(rows) == 1 and rows[0][2] == "", "line one moved, with no journal behind it"
    assert _listed(world), "the database's own finder lists the half-recorded invoice"

    answer = svc.retry(world.service_db, firm_id=FIRM, client_id=CLIENT, kind="sales_invoice", document_id=INVOICE,
                       created_by=PARTNER["id"])
    assert answer["recorded"] is True, answer

    rows = _sale_rows(world)
    assert sorted(r[0] for r in rows) == sorted([ITEM_A, ITEM_B]), "line one is not taken out a second time"
    journals = {r[2] for r in rows}
    assert len(journals) == 1 and "" not in journals, "both rows point at ONE combined entry"
    sold_value = -sum(int(r[1]) for r in rows)
    assert sold_value == 2 * 100_00 + 3 * 200_00

    entry = journals.pop()
    debit, credit = _rows(world.dsn, f"SELECT SUM(debit_paise), SUM(credit_paise) FROM journal_lines WHERE journal_entry_id = '{entry}'")[0]
    assert int(debit) == int(credit) == sold_value, "the entry carries both lines' value, balanced"
    assert not _listed(world), "the finder stops listing the invoice"

    # THE TIE: what the books say the stock is worth equals what the stock rows say, through the database's own monthly balances.
    assert _stock_value(world) == opening_stock - sold_value
    assert _balance(world, "Cost of Goods Sold") == sold_value
    assert _balance(world, "Inventory") == -sold_value, (
        "the opening rows were recorded outside the ledger here, so Inventory moved by exactly the COGS entry")


def test_a_second_retry_writes_nothing(world, monkeypatch):
    from services import stock_effect_retry_service as svc
    _stock_in(world, ITEM_A, 10, 1_000_00)
    _stock_in(world, ITEM_B, 10, 2_000_00)
    _issued_invoice(world)
    _first_issue_that_stops_after_line_one(world, monkeypatch)
    svc.retry(world.service_db, firm_id=FIRM, client_id=CLIENT, kind="sales_invoice", document_id=INVOICE, created_by=PARTNER["id"])
    before = (_sale_rows(world), _rows(world.dsn, "SELECT count(*) FROM journal_entries")[0][0])

    again = svc.retry(world.service_db, firm_id=FIRM, client_id=CLIENT, kind="sales_invoice", document_id=INVOICE,
                      created_by=PARTNER["id"])
    assert again["recorded"] is True and "recorded in full" in again["message"]
    assert (_sale_rows(world), _rows(world.dsn, "SELECT count(*) FROM journal_entries")[0][0]) == before


BILL = "09201000-0000-0000-0000-0000000000b1"
VENDOR = "09201000-0000-0000-0000-0000000000d1"


def test_a_purchase_stopped_after_line_one_is_completed_with_one_receipt_entry_and_the_ledgers_tie(world, monkeypatch):
    """The other direction of stock: goods coming in. Line two's stock row is refused at the first issue; the retry receives it and
    journals both lines' cost in one entry, and Inventory control equals the stock rows' value."""
    import domain.inventory_service as inv
    from services import stock_effect_retry_service as svc
    seed = _psql(world.dsn, f"""
        INSERT INTO vendors (id, firm_id, client_id, name) VALUES ('{VENDOR}', '{FIRM}', '{CLIENT}', 'Supplier');
        INSERT INTO purchase_bills (id, firm_id, client_id, vendor_id, bill_no, bill_date, status)
             VALUES ('{BILL}', '{FIRM}', '{CLIENT}', '{VENDOR}', 'B-092', '2026-04-05', 'received');
        INSERT INTO purchase_bill_lines (bill_id, description, quantity, taxable_amount_paise, service_catalogue_id)
             VALUES ('{BILL}', 'Widget A', 4, 40000, '{ITEM_A}'), ('{BILL}', 'Widget B', 5, 75000, '{ITEM_B}');
    """)
    assert seed.returncode == 0, seed.stderr
    bill = world.service_db.table("purchase_bills").select("*").eq("id", BILL).eq("firm_id", FIRM).execute().data[0]
    real = inv.record_stock_in
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("a refused ledger row")
        return real(*args, **kwargs)

    monkeypatch.setattr(inv, "record_stock_in", flaky)
    first = inv.apply_purchase_to_inventory(world.service_db, firm_id=FIRM, client_id=CLIENT, bill=bill)
    monkeypatch.setattr(inv, "record_stock_in", real)
    assert (first.moved_lines, first.goods_lines, first.recorded) == (1, 2, False)
    assert _listed_document(world, BILL)

    answer = svc.retry(world.service_db, firm_id=FIRM, client_id=CLIENT, kind="purchase_bill", document_id=BILL,
                       created_by=PARTNER["id"])
    assert answer["recorded"] is True, answer
    rows = _rows(world.dsn, f"SELECT service_catalogue_id, value_delta_paise, COALESCE(journal_entry_id::text, '') "
                            f"FROM inventory_stock_ledger WHERE source_type = 'purchase_bill' AND source_id = '{BILL}'")
    assert sorted(r[0] for r in rows) == sorted([ITEM_A, ITEM_B])
    entries = {r[2] for r in rows}
    assert len(entries) == 1 and "" not in entries
    received = sum(int(r[1]) for r in rows)
    assert received == 40000 + 75000
    debit, credit = _rows(world.dsn, f"SELECT SUM(debit_paise), SUM(credit_paise) FROM journal_lines "
                                     f"WHERE journal_entry_id = '{entries.pop()}'")[0]
    assert int(debit) == int(credit) == received
    assert not _listed_document(world, BILL)
    assert _balance(world, "Inventory") == _stock_value(world) == received, "Inventory control equals the stock rows' value"


def _listed_document(w, document_id: str) -> bool:
    from services import stock_effect_retry_service as svc
    found = svc.unrecorded_documents(w.service_db, firm_id=FIRM, client_id=CLIENT)
    assert found is not None
    return document_id in str(found)
