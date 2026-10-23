"""A customer's or vendor's permanent delete is refused for every table that would be wiped with it, or the table is on a list that says so.

WHY THIS EXISTS
    `routers/customers._DEPENDENCY_TABLES` and `routers/vendors._VENDOR_DEPENDENCY_TABLES` are the application's refusal to hard-delete a
    party that has accounting history (CGST Act s.35/36, IT Act s.44AA: the books are kept). The reason is written beside the lists:
    every foreign key that references `customers` is ON DELETE CASCADE, so a raw delete silently removes the rows. The lists were
    written by hand from the tables that existed, and nothing asked the database which tables cascade, so a table added later was
    never put on them: `sales_debit_notes` (a section 34(3) document, migration 210) cascades from `customers` and was not on the
    customer list, so a customer whose only record was an issued debit note could be deleted and the document would go with it.

WHAT THIS HOLDS
    The tables that REFERENCE `customers` or `vendors` with ON DELETE CASCADE are read from the catalogue of a database built from the
    migrations, and each one is either named by the router's list or on the list below, which says why it is not and which ledger line
    holds the decision. The list below only shrinks: a table that stops cascading, or that the router starts to name, must come off it,
    and a table that appears must be put on the router's list or here with a reason.

WHAT IT DOES NOT HOLD
    That the not-yet-guarded tables SHOULD be guarded. That is POST-A-334, an open decision about which of them are records and which are
    working data; this file only keeps the list from growing by accident. A table that names a party with no foreign key at all
    (`debit_notes`, `purchase_credit_notes` on the vendor side) is not found by a catalogue query and is on the router's list by name.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("HARNESS_PG") or shutil.which("psql") is None,
    reason="real-Postgres harness requires HARNESS_PG + psql")

# table -> why it is not on the router's list (shrinks only; each is POST-A-334)
CUSTOMER_NOT_YET_GUARDED = {
    "client_firm_customer_links": "the link that ties a customer to a client of the practice; no accounting date",
    "customer_statement_deliveries": "a mail log of statements sent",
    "late_interest_charges": "an interest figure prepared as a draft, never posted on its own",
    "post_dated_cheques": "a memorandum of a cheque held, until it is converted to a receipt",
}
VENDOR_NOT_YET_GUARDED = {
    "post_dated_cheques": "a memorandum of a cheque issued, until it is converted to a payment",
    "tds_lower_deduction_certificates": "a section 197 certificate held on a payee; carries its own validity dates",
}

_QUERY = """
SELECT c.conrelid::regclass::text
FROM pg_constraint c
WHERE c.contype = 'f' AND c.confdeltype = 'c' AND c.confrelid = 'public.{party}'::regclass
ORDER BY 1
"""


def _cascading(pg_template, party: str) -> set[str]:
    admin = os.environ["HARNESS_PG"].strip()
    done = subprocess.run(["psql", f"{admin} dbname={pg_template.name}", "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", _QUERY.format(party=party)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return {line.removeprefix("public.") for line in done.stdout.split() if line}


def test_every_table_that_cascades_from_a_customer_is_on_the_delete_guard_or_says_why_not(pg_template):
    from routers.customers import _DEPENDENCY_TABLES

    guarded = {table for _label, table, _date in _DEPENDENCY_TABLES}
    cascading = _cascading(pg_template, "customers")
    assert cascading, "the query found nothing: the catalogue read is wrong"
    unexplained = cascading - guarded - set(CUSTOMER_NOT_YET_GUARDED)
    assert not unexplained, (
        f"{sorted(unexplained)} cascade from customers and are neither on _DEPENDENCY_TABLES nor named here: a permanent delete of a "
        f"customer would remove their rows without a word")
    assert not (set(CUSTOMER_NOT_YET_GUARDED) & guarded), "a table is both guarded and on the not-yet list: take it off the list"
    assert set(CUSTOMER_NOT_YET_GUARDED) <= cascading, "a listed table no longer cascades from customers: take it off the list"


def test_every_table_that_cascades_from_a_vendor_is_on_the_delete_guard_or_says_why_not(pg_template):
    from routers.vendors import _VENDOR_DEPENDENCY_TABLES

    guarded = {table for _label, table, _date in _VENDOR_DEPENDENCY_TABLES}
    cascading = _cascading(pg_template, "vendors")
    assert cascading, "the query found nothing: the catalogue read is wrong"
    unexplained = cascading - guarded - set(VENDOR_NOT_YET_GUARDED)
    assert not unexplained, (
        f"{sorted(unexplained)} cascade from vendors and are neither on _VENDOR_DEPENDENCY_TABLES nor named here: a permanent delete of "
        f"a vendor would remove their rows without a word")
    assert not (set(VENDOR_NOT_YET_GUARDED) & guarded), "a table is both guarded and on the not-yet list: take it off the list"
    assert set(VENDOR_NOT_YET_GUARDED) <= cascading, "a listed table no longer cascades from vendors: take it off the list"


def test_the_two_party_lists_name_the_documents_that_matter_most():
    """The documents a return is built from. A shorter list than this is the defect the file exists to catch."""
    from routers.customers import _DEPENDENCY_TABLES
    from routers.vendors import _VENDOR_DEPENDENCY_TABLES

    customer = {table for _l, table, _d in _DEPENDENCY_TABLES}
    vendor = {table for _l, table, _d in _VENDOR_DEPENDENCY_TABLES}
    assert {"client_sales_invoices", "receipts", "credit_notes", "sales_debit_notes"} <= customer
    assert {"purchase_bills", "purchase_payments", "debit_notes", "purchase_credit_notes", "recurring_purchase_bill_templates"} <= vendor
