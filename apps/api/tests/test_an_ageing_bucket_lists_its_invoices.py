"""The practice's receivables ageing lists the invoices behind each bucket (POST-A-099).

WHAT WAS WRONG
    `/practice/ar` showed five ageing buckets as a total and a count, and nothing could say WHICH invoices made a bucket: the page sent
    the Partner to the practice's Sales tab to find them by hand, where the list is not ordered by how late each invoice is.

WHAT THIS HOLDS
    `GET /api/billing/ar-aging` lists each bucket's invoices from the same reading its totals are made of, most overdue first, so a bucket
    that is not cut adds up to its own total. A list cut at the cap says it was cut while the count and total stay the whole bucket's.
    A customer name that could not be read is unknown, never blank, and the dashboard (which reads the totals only) is unchanged.
"""
from __future__ import annotations

from datetime import date

import pytest

import routers.billing as billing
import routers.customers as customers
import services.collections_service as coll
import services.internal_client_service as ics
from routers.sales_invoices import MOCK_SALES_INVOICES

FIRM = "F1"
INT = "INT"
TODAY = date(2026, 6, 30)
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "role": "Partner", "email": "p@f.test"}


def _inv(iid, status, total, paid, due, customer="K1", invoice_date="2026-03-01"):
    return {"id": iid, "firm_id": FIRM, "client_id": INT, "customer_id": customer, "invoice_no": f"SINV-{iid}",
            "invoice_date": invoice_date, "due_date": due, "total_paise": total, "paid_paise": paid, "status": status}


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    # The module imported the name, so it is patched where it is read: the fee ledger is the internal client's, and the other
    # client's invoice below is what proves the filter runs.
    monkeypatch.setattr(ics, "get_internal_client_id", lambda firm_id: INT)
    monkeypatch.setattr(coll, "get_internal_client_id", lambda firm_id: INT)
    MOCK_SALES_INVOICES.clear()
    MOCK_SALES_INVOICES.extend([
        _inv("A", "issued", 118000, 0, "2026-06-20"),                         # 10 days -> 0-30
        _inv("A2", "issued", 20000, 0, "2026-06-25", customer="K2"),          # 5 days  -> 0-30
        _inv("B", "issued", 100000, 0, "2026-04-15"),                         # 76 days -> 61-90
        _inv("C", "issued", 50000, 0, "2026-07-10"),                          # future  -> not_due
        _inv("D", "partially_paid", 100000, 40000, "2026-01-01"),             # >90, 60000 owed
        _inv("E", "paid", 100000, 100000, "2026-01-01"),                      # settled: not listed
        _inv("F", "draft", 100000, 0, "2026-01-01"),                          # draft: not listed
        {**_inv("G", "issued", 30000, 0, None, invoice_date="2026-06-01"), "credit_days": 10},  # ages from 11 June -> 0-30
        {**_inv("X", "issued", 999999, 0, "2026-06-01"), "client_id": "SOME-CLIENT"},       # a client's own customer invoice: not the fee ledger
    ])
    customers.MOCK_CUSTOMERS.clear()
    customers.MOCK_CUSTOMERS.extend([{"id": "K1", "firm_id": FIRM, "name": "Mehta Traders"},
                                     {"id": "K2", "firm_id": FIRM, "name": "Rao & Sons"},
                                     {"id": "K1", "firm_id": "F2", "name": "Another firm's customer"}])
    yield
    MOCK_SALES_INVOICES.clear()
    customers.MOCK_CUSTOMERS.clear()


def test_each_bucket_lists_its_invoices_and_adds_up_to_its_total():
    aging = coll.ar_aging(FIRM, today=TODAY, with_invoices=True)
    listed = aging["invoices_by_bucket"]
    assert set(listed) == {"not_due", "0-30", "31-60", "61-90", "90+"}
    for bucket, b in aging["buckets"].items():
        rows = listed[bucket]["invoices"]
        assert listed[bucket]["truncated"] is False
        assert len(rows) == b["count"], bucket
        assert sum(r["outstanding_paise"] for r in rows) == b["paise"], bucket
    assert [r["invoice_no"] for r in listed["90+"]["invoices"]] == ["SINV-D"]
    assert "SINV-X" not in {r["invoice_no"] for b in listed.values() for r in b["invoices"]}, "a client's invoice is not the practice's"
    assert listed["90+"]["invoices"][0]["outstanding_paise"] == 60000
    assert listed["31-60"]["invoices"] == []


def test_a_bucket_is_most_overdue_first_and_says_where_the_ageing_runs_from():
    rows = coll.ar_aging(FIRM, today=TODAY, with_invoices=True)["invoices_by_bucket"]["0-30"]["invoices"]
    assert [r["invoice_no"] for r in rows] == ["SINV-G", "SINV-A", "SINV-A2"], "19, 10 and 5 days overdue"
    g = rows[0]
    assert g["ageing_from"] == "2026-06-11", "no due date: the invoice's date plus its own credit days"
    assert g["days_overdue"] == 19
    assert rows[1]["ageing_from"] == "2026-06-20" and rows[1]["invoice_date"] == "2026-03-01"


def test_the_customer_is_named_from_the_firms_own_customers():
    rows = coll.ar_aging(FIRM, today=TODAY, with_invoices=True)
    assert rows["customer_names_read"] is True
    by_no = {r["invoice_no"]: r for b in rows["invoices_by_bucket"].values() for r in b["invoices"]}
    assert by_no["SINV-A"]["customer_name"] == "Mehta Traders"
    assert by_no["SINV-A2"]["customer_name"] == "Rao & Sons"


def test_a_name_that_could_not_be_read_is_unknown_and_the_answer_says_so(monkeypatch):
    monkeypatch.setattr(coll, "_customer_names", lambda firm_id, ids: None)
    rows = coll.ar_aging(FIRM, today=TODAY, with_invoices=True)
    assert rows["customer_names_read"] is False
    assert {r["customer_name"] for b in rows["invoices_by_bucket"].values() for r in b["invoices"]} == {None}


def test_a_list_cut_at_the_cap_says_so_and_the_bucket_keeps_its_whole_count(monkeypatch):
    monkeypatch.setattr(coll, "BUCKET_LIST_CAP", 2)
    aging = coll.ar_aging(FIRM, today=TODAY, with_invoices=True)
    b = aging["invoices_by_bucket"]["0-30"]
    assert b["truncated"] is True and [r["invoice_no"] for r in b["invoices"]] == ["SINV-G", "SINV-A"], "the least late is what is cut"
    assert aging["buckets"]["0-30"] == {"paise": 168000, "count": 3}
    assert aging["list_cap"] == 2


def test_without_the_list_the_answer_is_the_totals_alone_as_before():
    aging = coll.ar_aging(FIRM, today=TODAY)
    assert set(aging) == {"buckets", "total_outstanding_paise", "overdue_paise", "overdue_count"}
    dash = coll.dashboard(FIRM, today=TODAY)
    assert "invoices_by_bucket" not in dash and "invoices_by_bucket" not in dash["aging"]


def test_the_route_serves_the_list():
    out = billing.ar_aging(current_user=PARTNER)
    assert out["success"] is True
    assert set(out["data"]["invoices_by_bucket"]) == {"not_due", "0-30", "31-60", "61-90", "90+"}
    assert out["data"]["customer_names_read"] is True
