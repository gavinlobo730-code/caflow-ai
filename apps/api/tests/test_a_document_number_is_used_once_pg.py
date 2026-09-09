"""
Two tabs cannot record the same document twice — and already could not.

THE INVESTIGATION THIS PINS
    "Two tabs" was carried as an open hole for a while: the screens now run one
    action at a time, which stops a double-click and a network retry but cannot
    stop two windows, because each has its own state and each correctly believes
    nothing is running.

    Closing it looked like it needed new UNIQUE indexes. It did not. Every
    document type below has carried one for a long time, in the migrations AND
    in production — checked against both rather than assumed. A first pass at
    this file added a second set, which would have meant redundant index writes
    on every document a client ever raises, to enforce a rule already enforced.

    So this file adds no constraint. It asserts the ones that exist still do
    what the product depends on, because they are load-bearing and nothing else
    checked them: a migration could drop one and every suite would stay green.

WHAT THE REAL RULES SAY, WHICH IS NOT WHAT YOU WOULD GUESS
    * A sales invoice number is unique per client across LIVE rows — DRAFTS
      INCLUDED. Deleting frees the number.
    * A purchase bill is unique per client and VENDOR, case-insensitively and
      ignoring surrounding spaces, and a cancelled bill releases its number.
      A supplier's number is not ours: two vendors may both send "INV-1".
    * Receipts and payments have no draft or cancelled state; every row counts.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

import pytest

_ADMIN = os.environ.get("HARNESS_PG", "")
pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql")


def _psql(dsn: str, statement: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q",
                           "-c", statement], capture_output=True, text=True)


@pytest.fixture(scope="module")
def seeded(pg_template):
    """A migrated database of our own, plus a firm, client, customer and vendor
    to hang documents from. `pg_template` (tests/conftest.py) applies the
    migration set once per session; this clones it in about a second."""
    name = f"dupdoc_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{_ADMIN.strip()} dbname=postgres"
    if _psql(admin_dsn,
             f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not clone the migrated template")
    dsn = f"{_ADMIN.strip()} dbname={name}"

    ids = {k: str(uuid.uuid4()) for k in ("firm", "client", "customer", "vendor")}
    r = _psql(dsn, f"""
        INSERT INTO firms (id, name, email)
          VALUES ('{ids["firm"]}', 'Dup Test Firm', 'dup@test.invalid');
        INSERT INTO clients (id, firm_id, client_name, entity_type)
          VALUES ('{ids["client"]}', '{ids["firm"]}', 'Dup Test Client',
                  'Proprietorship');
        INSERT INTO customers (id, firm_id, client_id, name)
          VALUES ('{ids["customer"]}', '{ids["firm"]}', '{ids["client"]}', 'Cust');
        INSERT INTO vendors (id, firm_id, client_id, name)
          VALUES ('{ids["vendor"]}', '{ids["firm"]}', '{ids["client"]}', 'Vend');
    """)
    if r.returncode != 0:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')
        pytest.fail(f"could not seed the fixture: {r.stderr.strip()[:300]}")
    ids["dsn"] = dsn
    try:
        yield ids
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def sql(ids, statement: str) -> subprocess.CompletedProcess:
    return _psql(ids["dsn"], statement)


def _invoice(ids, no, status):
    return sql(ids, f"""INSERT INTO client_sales_invoices
        (firm_id, client_id, customer_id, invoice_no, invoice_date, status)
        VALUES ('{ids["firm"]}','{ids["client"]}','{ids["customer"]}',
                '{no}', DATE '2026-04-01', '{status}')""")


def _bill(ids, no, status, vendor=None):
    return sql(ids, f"""INSERT INTO purchase_bills
        (firm_id, client_id, vendor_id, bill_no, bill_date, status)
        VALUES ('{ids["firm"]}','{ids["client"]}','{vendor or ids["vendor"]}',
                '{no}', DATE '2026-04-01', '{status}')""")


def test_a_second_tab_cannot_record_the_same_invoice(seeded):
    """THE TWO-TAB CASE. Both tabs believe nothing is running; the database
    knows better, and is the only thing that can."""
    assert _invoice(seeded, "INV-TAB-1", "issued").returncode == 0
    second = _invoice(seeded, "INV-TAB-1", "issued")
    assert second.returncode != 0, "the second tab recorded a duplicate invoice"
    assert "client_sales_invoices_firm_client_invoice_no_live_key" in second.stderr


def test_a_draft_holds_the_number_too(seeded):
    """Worth pinning because it is the opposite of what a partial-on-status rule
    would do: this index is partial on deleted_at ONLY, so a draft occupies the
    number as firmly as an issued invoice does."""
    assert _invoice(seeded, "INV-DRAFT", "draft").returncode == 0
    assert _invoice(seeded, "INV-DRAFT", "issued").returncode != 0


def test_deleting_an_invoice_releases_its_number(seeded):
    """The way out of a wrong number, and the reason the refusal message names
    it."""
    assert _invoice(seeded, "INV-DEL", "issued").returncode == 0
    assert sql(seeded, f"""UPDATE client_sales_invoices SET deleted_at = NOW()
        WHERE client_id = '{seeded["client"]}' AND invoice_no = 'INV-DEL'""").returncode == 0
    assert _invoice(seeded, "INV-DEL", "issued").returncode == 0


def test_a_bill_number_is_unique_per_VENDOR_not_per_client(seeded):
    """A supplier's number is not ours. Two vendors may both send "INV-1" in the
    same month and both are honest bookkeeping — keying per client alone would
    refuse the second."""
    other_vendor = str(uuid.uuid4())
    assert sql(seeded, f"""INSERT INTO vendors (id, firm_id, client_id, name)
        VALUES ('{other_vendor}','{seeded["firm"]}','{seeded["client"]}','Vend2')
    """).returncode == 0
    assert _bill(seeded, "SHARED-1", "received").returncode == 0
    assert _bill(seeded, "SHARED-1", "received", vendor=other_vendor).returncode == 0, \
        "a second VENDOR's identical bill number was refused"
    again = _bill(seeded, "SHARED-1", "received")
    assert again.returncode != 0, "the same vendor's bill was entered twice"


def test_a_bill_number_is_matched_ignoring_case_and_spaces(seeded):
    """The index keys on lower(btrim(bill_no)), which is the difference between
    catching a re-typed bill and only catching a copy-pasted one."""
    assert _bill(seeded, "Cipla-99", "received").returncode == 0
    assert _bill(seeded, "  CIPLA-99 ", "received").returncode != 0, \
        "the same bill re-typed in different case was accepted as a new one"


def test_a_cancelled_bill_releases_its_number(seeded):
    """Cancel and re-enter is how a wrong bill is corrected. Production holds
    four of exactly these pairs, and they are legitimate."""
    assert _bill(seeded, "BILL-CANC", "cancelled").returncode == 0
    assert _bill(seeded, "BILL-CANC", "received").returncode == 0


def test_a_bill_with_no_number_is_not_a_duplicate_of_another(seeded):
    """Blank and NULL are excluded rather than collapsed: two bills that arrived
    without a number are two bills, not one entered twice."""
    for day in ("2026-04-02", "2026-04-03"):
        assert sql(seeded, f"""INSERT INTO purchase_bills
            (firm_id, client_id, vendor_id, bill_date, status)
            VALUES ('{seeded["firm"]}','{seeded["client"]}','{seeded["vendor"]}',
                    DATE '{day}','received')""").returncode == 0


def test_a_receipt_number_is_used_once(seeded):
    """No draft state here: the money either moved or it did not."""
    stmt = f"""INSERT INTO receipts
        (firm_id, client_id, customer_id, receipt_no, receipt_date, amount_paise)
        VALUES ('{seeded["firm"]}','{seeded["client"]}','{seeded["customer"]}',
                'RCPT-1', DATE '2026-04-01', 10000)"""
    assert sql(seeded, stmt).returncode == 0
    assert sql(seeded, stmt).returncode != 0, "the same receipt was recorded twice"


def test_every_document_type_still_carries_its_guarantee(seeded):
    """The whole point of this file. These indexes are load-bearing and nothing
    else asserts them; one dropped by a later migration would leave a document
    type duplicable with every suite green."""
    r = sql(seeded, """SELECT indexname FROM pg_indexes
               WHERE schemaname='public' AND indexdef LIKE '%UNIQUE%'
               ORDER BY indexname""")
    assert r.returncode == 0, r.stderr
    for expected in ("client_sales_invoices_firm_client_invoice_no_live_key",
                     "credit_notes_firm_client_credit_note_no_key",
                     "debit_notes_firm_client_debit_note_no_key",
                     "purchase_payments_firm_payment_no_key",
                     "receipts_firm_client_receipt_no_key",
                     # Both PER CLIENT since migration 350. They were the last
                     # two per-FIRM keys, and that was not a stricter rule than
                     # the others — it was the launch blocker migration 151
                     # fixed for invoices and 159 for debit notes and receipts,
                     # re-introduced by 210: the router numbers per client, so
                     # the firm's SECOND client computed 0001, the per-firm key
                     # rejected it, and services/numbering.py recomputed the
                     # same 0001 on all six retries. Widening a unique key only
                     # relaxes it, so each client keeps its own continuous
                     # series and no document type became duplicable.
                     "sales_debit_notes_firm_client_debit_note_no_key",
                     # Never listed here at all, which is why nothing noticed
                     # it had the same defect as its sales-side twin.
                     "purchase_credit_notes_firm_client_credit_note_no_key",
                     "uq_purchase_bills_vendor_invoice"):
        assert expected in r.stdout, f"{expected} is gone — that document type is duplicable"
