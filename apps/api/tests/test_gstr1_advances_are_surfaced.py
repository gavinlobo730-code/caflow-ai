"""Advances received against no invoice are named, and no tax is invented.

WHAT WAS WRONG
    GSTR-1 Tables 11A and 11B were absent from the payload, and nothing
    anywhere told a CA that. A client who took advances saw an empty Table 11
    and had no way to tell whether that meant "no advances" or "not computed".

WHY THIS REPORTS RATHER THAN COMPUTING
    An 11A row needs the place of supply, the inter/intra split, the RATE and
    the tax — every one of them a property of a supply that has not happened
    yet. `receipts` holds an amount, a customer and a date. A guessed rate on
    an advance is a guessed tax liability on a filed return, so this names the
    advances and stops.

    Even with a rate a blanket computation would be wrong. CGST Act §13(2)
    makes an advance for SERVICES taxable when received; Notification
    66/2017-Central Tax removed the charge for GOODS, where the liability
    arises at the invoice instead (§12(2) proviso). Two clients with identical
    receipts can owe different tax, and which is which is a fact about their
    business rather than about their ledger.
"""
import pytest

import routers.gst_workspace as gw
import services.gst_advance_service as svc
import services.gst_return_service as grs
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "FIRM-A", "CLI"
PERIOD = "062025"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw, grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT,
                         "name": "Acme", "gstin": "27BBBBB1111B1Z5",
                         "state_code": "27", "is_active": True})
    return d


def _receipt(db, no, date, amount, allocated):
    return db.seed("receipts", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
        "receipt_no": no, "receipt_date": date, "amount_paise": amount,
        "allocated_paise": allocated,
        "unallocated_paise": amount - allocated})


def _run(db, period=PERIOD):
    return svc.advances_report(db, FIRM, CLIENT, period)


# ── what it finds ────────────────────────────────────────────────────────────

def test_an_unallocated_receipt_is_reported_as_an_advance(db):
    _receipt(db, "RCT-1", "2025-06-10", 1_00_000, 0)
    out = _run(db)
    assert out["count"] == 1
    assert out["total_unadjusted_paise"] == 1_00_000
    a = out["unadjusted_advances"][0]
    assert a["receipt_no"] == "RCT-1"
    assert a["customer_name"] == "Acme"
    assert a["unadjusted_paise"] == 1_00_000


def test_a_partly_allocated_receipt_reports_only_what_is_left(db):
    _receipt(db, "RCT-1", "2025-06-10", 1_00_000, 40_000)
    out = _run(db)
    assert out["count"] == 1
    assert out["unadjusted_advances"][0]["unadjusted_paise"] == 60_000
    assert out["unadjusted_advances"][0]["amount_paise"] == 1_00_000


def test_a_fully_allocated_receipt_is_not_an_advance(db):
    """It paid an invoice. There is nothing outstanding to declare."""
    _receipt(db, "RCT-1", "2025-06-10", 1_00_000, 1_00_000)
    assert _run(db)["count"] == 0


def test_a_receipt_from_another_period_is_not_reported(db):
    _receipt(db, "RCT-1", "2025-05-31", 1_00_000, 0)
    _receipt(db, "RCT-2", "2025-07-01", 2_00_000, 0)
    _receipt(db, "RCT-3", "2025-06-15", 3_00_000, 0)
    out = _run(db)
    assert [a["receipt_no"] for a in out["unadjusted_advances"]] == ["RCT-3"]


def test_several_advances_are_totalled_and_ordered_by_date(db):
    _receipt(db, "RCT-B", "2025-06-20", 2_00_000, 0)
    _receipt(db, "RCT-A", "2025-06-05", 1_00_000, 0)
    out = _run(db)
    assert [a["receipt_no"] for a in out["unadjusted_advances"]] == ["RCT-A", "RCT-B"]
    assert out["total_unadjusted_paise"] == 3_00_000


def test_a_period_with_no_advances_says_so_plainly(db):
    out = _run(db)
    assert out["count"] == 0 and out["unadjusted_advances"] == []


# ── what it must NOT do ──────────────────────────────────────────────────────

def test_no_tax_figure_is_produced_anywhere(db):
    """The whole point. A rate cannot be derived from a receipt, so no tax
    field may appear — an invented one is an invented liability."""
    _receipt(db, "RCT-1", "2025-06-10", 1_00_000, 0)
    out = _run(db)
    forbidden = {"iamt", "camt", "samt", "csamt", "rt", "rate", "tax_paise",
                 "igst_paise", "cgst_paise", "sgst_paise", "pos",
                 "place_of_supply"}
    assert not (forbidden & set(out)), sorted(forbidden & set(out))
    for a in out["unadjusted_advances"]:
        assert not (forbidden & set(a)), sorted(forbidden & set(a))


def test_it_states_that_table_11_is_not_computed(db):
    """An empty Table 11 is ambiguous — no advances, or nothing computing it.
    The answer has to travel with the data, not live in a docstring."""
    out = _run(db)
    assert out["table_11_computed"] is False
    assert "66/2017" in out["why"], out["why"]
    assert "13(2)" in out["why"]
    assert out["ca_review_required"] is True


def test_another_firms_receipt_is_not_visible(db):
    r = _receipt(db, "RCT-X", "2025-06-10", 5_00_000, 0)
    db.table("receipts").update({"firm_id": "FIRM-B"}).eq("id", r["id"]).execute()
    assert _run(db)["count"] == 0


def test_another_clients_receipt_is_not_visible(db):
    r = _receipt(db, "RCT-Y", "2025-06-10", 5_00_000, 0)
    db.table("receipts").update({"client_id": "CLI-2"}).eq("id", r["id"]).execute()
    assert _run(db)["count"] == 0


# ── the route ────────────────────────────────────────────────────────────────

def test_the_route_is_registered():
    from main import app
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/api/gst-workspace/gstr1/advances" in paths


# ── Table 11A / 11B, once the client is marked as one whose advances bear tax ─

def _client(db, *, applicable):
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM,
                        "gstin": "27AAAAA0000A1Z5", "state_code": "27",
                        "financial_year_start": "2025-04-01",
                        "gst_advance_tax_applicable": applicable})


def _adv(db, no, date, amount, *, rate=1800, pos="27", interstate=False):
    return db.seed("receipts", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
        "receipt_no": no, "receipt_date": date, "amount_paise": amount,
        "allocated_paise": 0, "unallocated_paise": amount,
        "gst_rate_bps": rate, "place_of_supply": pos,
        "is_interstate": interstate})


def _allocate(db, receipt, paise, when):
    db.seed("receipt_allocations", {
        "receipt_id": receipt["id"], "sales_invoice_id": "inv-1",
        "allocated_paise": paise, "created_at": when})


def _t11(db, period=PERIOD):
    return svc.table_11_sections(db, FIRM, CLIENT, period)


def test_a_goods_client_gets_no_table_11_at_all(db):
    """The default. Notification 66/2017 removed the charge on advances for
    goods, so demanding a rate on every receipt would buy nothing."""
    _client(db, applicable=False)
    _adv(db, "RCT-1", "2025-06-10", 1_18_000)
    out = _t11(db)
    assert out == {"at": [], "txpd": [], "applicable": False}


def test_a_services_client_declares_the_advance_in_11a(db):
    _client(db, applicable=True)
    _adv(db, "RCT-1", "2025-06-10", 1_18_000)          # Rs 1,180 incl. 18%
    at = _t11(db)["at"]
    assert len(at) == 1
    assert at[0]["pos"] == "27" and at[0]["sply_ty"] == "INTRA"
    itm = at[0]["itms"][0]
    assert itm["rt"] == 18.0
    # The receipt is money the customer paid, so it INCLUDES the tax. ad_amt is
    # the taxable value backed out of it: 1,180 -> 1,000 + 90 + 90.
    assert itm["ad_amt"] == 1000.0
    assert itm["camt"] == 90.0 and itm["samt"] == 90.0
    assert "iamt" not in itm


def test_an_inter_state_advance_carries_the_whole_rate_as_igst(db):
    _client(db, applicable=True)
    _adv(db, "RCT-1", "2025-06-10", 1_18_000, pos="29", interstate=True)
    itm = _t11(db)["at"][0]["itms"][0]
    assert itm["ad_amt"] == 1000.0 and itm["iamt"] == 180.0
    assert "camt" not in itm and "samt" not in itm


def test_an_advance_with_no_rate_is_left_out_of_11a(db):
    """It is still listed by advances_report — visible, not silently dropped —
    but a guessed rate is a guessed liability."""
    _client(db, applicable=True)
    db.seed("receipts", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
        "receipt_no": "RCT-1", "receipt_date": "2025-06-10",
        "amount_paise": 1_18_000, "allocated_paise": 0,
        "unallocated_paise": 1_18_000, "gst_rate_bps": None,
        "place_of_supply": None, "is_interstate": None})
    assert _t11(db)["at"] == []
    assert _run(db)["count"] == 1


def test_an_advance_invoiced_in_the_same_period_reaches_neither_table(db):
    """Its tax was never declared in an 11A, so there is nothing to adjust."""
    _client(db, applicable=True)
    r = _adv(db, "RCT-1", "2025-06-05", 1_18_000)
    _allocate(db, r, 1_18_000, "2025-06-20T00:00:00Z")
    out = _t11(db)
    assert out["at"] == [] and out["txpd"] == []


def test_an_earlier_advance_adjusted_now_is_declared_in_11b(db):
    _client(db, applicable=True)
    r = _adv(db, "RCT-1", "2025-05-20", 1_18_000)
    _allocate(db, r, 1_18_000, "2025-06-15T00:00:00Z")
    out = _t11(db)
    assert out["at"] == [], "it was received in May, not June"
    assert len(out["txpd"]) == 1
    assert out["txpd"][0]["itms"][0]["ad_amt"] == 1000.0


def test_11a_asks_what_was_outstanding_at_the_PERIOD_END(db):
    """Not what is outstanding today. Reading unallocated_paise would answer a
    June question with today's facts and change a filed period every time an
    old advance is finally settled."""
    _client(db, applicable=True)
    r = _adv(db, "RCT-1", "2025-06-10", 1_18_000)
    _allocate(db, r, 1_18_000, "2025-09-01T00:00:00Z")   # settled much later
    assert _t11(db)["at"][0]["itms"][0]["ad_amt"] == 1000.0, (
        "a September allocation changed what June declared")


def test_a_partly_adjusted_advance_declares_only_the_balance(db):
    _client(db, applicable=True)
    r = _adv(db, "RCT-1", "2025-06-10", 1_18_000)
    _allocate(db, r, 59_000, "2025-06-25T00:00:00Z")
    assert _t11(db)["at"][0]["itms"][0]["ad_amt"] == 500.0


def test_advances_at_different_rates_are_separate_items(db):
    _client(db, applicable=True)
    _adv(db, "RCT-1", "2025-06-10", 1_18_000, rate=1800)
    _adv(db, "RCT-2", "2025-06-11", 1_05_000, rate=500)
    itms = _t11(db)["at"][0]["itms"]
    assert sorted(i["rt"] for i in itms) == [5.0, 18.0]


def test_advances_to_different_states_are_separate_rows(db):
    _client(db, applicable=True)
    _adv(db, "RCT-1", "2025-06-10", 1_18_000, pos="27")
    _adv(db, "RCT-2", "2025-06-11", 1_18_000, pos="29", interstate=True)
    at = _t11(db)["at"]
    assert {r["pos"] for r in at} == {"27", "29"}
    assert {r["sply_ty"] for r in at} == {"INTRA", "INTER"}


def test_the_split_is_exact_so_the_declaration_reconciles(db):
    """taxable + tax must equal the advance the customer actually paid — an
    awkward amount is where a naive percentage would leave a rounding hole."""
    _client(db, applicable=True)
    _adv(db, "RCT-1", "2025-06-10", 1_00_001)
    itm = _t11(db)["at"][0]["itms"][0]
    assert round(itm["ad_amt"] + itm["camt"] + itm["samt"], 2) == 1000.01


# ── and it has to reach the payload, not just the service ────────────────────

def test_table_11_reaches_the_gstr1_payload(db):
    """Every test above calls table_11_sections() directly, which proves the
    SERVICE computes and says nothing about whether gstr1_from_books merges it.
    Three times in this run of work a negative control passed because the tests
    sat one layer below the thing that was broken."""
    _client(db, applicable=True)
    _adv(db, "RCT-1", "2025-06-10", 1_18_000)
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT,
                          "name": "Acme", "gstin": None, "state_code": "27",
                          "is_active": True})

    payload = grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD,
                                   "27AAAAA0000A1Z5")["payload"]
    assert "at" in payload, (
        "Table 11A was computed and never merged into the file the CA uploads")
    assert payload["at"][0]["itms"][0]["ad_amt"] == 1000.0


def test_a_goods_client_gets_no_at_section_in_the_payload(db):
    """Omitted, not sent empty: the GSTN tool writes a section only when it has
    something to declare."""
    _client(db, applicable=False)
    _adv(db, "RCT-1", "2025-06-10", 1_18_000)
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT,
                          "name": "Acme", "gstin": None, "state_code": "27",
                          "is_active": True})

    payload = grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD,
                                   "27AAAAA0000A1Z5")["payload"]
    assert "at" not in payload and "txpd" not in payload
