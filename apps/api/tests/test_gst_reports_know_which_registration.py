"""GST-04 and GST-05 — a report or a return for ONE registration says so.

GST-04. The GSTR-1 exception report loaded the filed return with client, period
and `limit(1)` and no GSTIN. Migration 390 keyed `gstr1_returns` on (client,
period, gstin), so a client with two registrations has two rows for one period
and the report compared the books against whichever the database returned first.

GST-05. Returns can be built for any GSTIN a client holds, but invoices, bills
and notes carry no registration and are fetched by client alone. A return for a
second GSTIN is therefore assembled from the CLIENT-WIDE documents, including the
first state's, and renders as authoritatively as one built from a clean book.
The interim guard is a NAMED caveat on the return (a refusal would strand a saved
return that must stay readable); the durable fix is to attribute each document to
a registration (GST-16).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.gst_workspace as gw
import services.gst_exception_service as svc
import services.gst_return_service as grs
from domain.gst import registrations as reg
from domain.gst.gstr1_builder import GAP_RETURN_CAVEAT
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-R"
CLIENT = "CLI"
PRIMARY = "27AAAAA0000A1Z2"      # Maharashtra
SECOND = "29AAAAA0000A1Z5"       # Karnataka
PERIOD = "062025"


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw, grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": PRIMARY,
                       "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme",
                         "gstin": "27BBBBB1111B1ZN", "state_code": "27", "is_active": True})
    seed_standard_coa(d, FIRM, CLIENT)
    d.seed("client_sales_invoices", {
        "firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST",
        "invoice_no": "INV-1", "invoice_date": "2025-06-10", "status": "issued",
        "taxable_amount_paise": 100_000, "cgst_paise": 9_000, "sgst_paise": 9_000,
        "igst_paise": 0, "total_paise": 118_000, "is_interstate": False,
        "supply_state_code": "27", "supply_type": "taxable",
        "invoice_type": "Regular", "is_reverse_charge": False, "deleted_at": None})
    return d


def _second_registration(db, **over):
    row = {"firm_id": FIRM, "client_id": CLIENT, "gstin": SECOND,
           "state_code": "29", "registration_type": "regular",
           "filing_frequency": "monthly", "deleted_at": None}
    row.update(over)
    return db.seed("client_gst_registrations", row)


def _file(db, gstin, payload, arn):
    return db.seed("gstr1_returns", {
        "firm_id": FIRM, "client_id": CLIENT, "period": PERIOD, "gstin": gstin,
        "status": "submitted", "payload_json": payload,
        "submitted_at": "2025-07-11T10:00:00Z", "arn": arn})


def _books(db, gstin=PRIMARY):
    return grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD, gstin)["payload"]


# ── GST-04: the exception report is asked of ONE registration ────────────────

def test_each_registration_is_compared_against_its_own_filed_return(db):
    """THE test. Two registrations, two submitted returns for one period, with
    different frozen payloads — the primary's matches the books, the second's is
    empty. Each GSTIN has to get ITS OWN comparison."""
    _second_registration(db)
    _file(db, PRIMARY, _books(db), "ARN-PRIMARY")
    _file(db, SECOND, {"b2b": [], "b2cs": [], "hsn": {"data": []}}, "ARN-SECOND")

    primary = svc.gstr1_exceptions(db, FIRM, CLIENT, PERIOD, PRIMARY)
    second = svc.gstr1_exceptions(db, FIRM, CLIENT, PERIOD, SECOND)

    assert primary["arn"] == "ARN-PRIMARY" and primary["gstin"] == PRIMARY
    assert second["arn"] == "ARN-SECOND" and second["gstin"] == SECOND
    assert primary["clean"] is True
    assert second["clean"] is False, (
        "the second registration's return is empty, so the books' invoice is "
        "missing from it — that finding must not be answered by the primary's row")


def test_omitting_the_gstin_means_the_primary(db):
    _second_registration(db)
    _file(db, PRIMARY, _books(db), "ARN-PRIMARY")
    _file(db, SECOND, {"b2b": []}, "ARN-SECOND")
    out = svc.gstr1_exceptions(db, FIRM, CLIENT, PERIOD)
    assert out["arn"] == "ARN-PRIMARY" and out["gstin"] == PRIMARY


def test_the_row_order_does_not_decide_which_return_is_read(db):
    """The old read was `limit(1)` on (client, period): whichever row the
    database produced first. Seed them in the opposite order and the answer
    must not move."""
    _second_registration(db)
    _file(db, SECOND, {"b2b": []}, "ARN-SECOND")
    _file(db, PRIMARY, _books(db), "ARN-PRIMARY")
    assert svc.gstr1_exceptions(db, FIRM, CLIENT, PERIOD, PRIMARY)["arn"] == "ARN-PRIMARY"
    assert svc.gstr1_exceptions(db, FIRM, CLIENT, PERIOD, SECOND)["arn"] == "ARN-SECOND"


def test_a_registration_with_no_filed_return_is_not_filed_even_if_another_has_one(db):
    _second_registration(db)
    _file(db, PRIMARY, _books(db), "ARN-PRIMARY")
    out = svc.gstr1_exceptions(db, FIRM, CLIENT, PERIOD, SECOND)
    assert out["status"] == "not_filed"


def test_a_gstin_the_client_does_not_hold_is_refused_not_answered_as_the_primary(db):
    _file(db, PRIMARY, _books(db), "ARN-PRIMARY")
    with pytest.raises(HTTPException) as e:
        svc.gstr1_exceptions(db, FIRM, CLIENT, PERIOD, "07AAAAA0000A1Z5")
    assert e.value.status_code == 422
    assert "not a GST registration recorded for this client" in e.value.detail


def test_a_client_with_no_registration_at_all_has_simply_not_filed(db):
    db.table("clients").update({"gstin": None}).eq("id", CLIENT).execute()
    out = svc.gstr1_exceptions(db, FIRM, CLIENT, PERIOD)
    assert out["status"] == "not_filed"


def test_the_filed_return_read_requires_a_gstin():
    """No default: a read matching on (client, period) alone is one
    registration away from answering about somebody else's return."""
    import inspect
    param = inspect.signature(svc._filed_return).parameters["gstin"]
    assert param.default is inspect.Parameter.empty


def test_the_route_passes_the_registration_through(db):
    _second_registration(db)
    _file(db, PRIMARY, _books(db), "ARN-PRIMARY")
    _file(db, SECOND, {"b2b": []}, "ARN-SECOND")
    user = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth",
            "email": "ca@f.test", "role": "Partner"}
    resp = gw.gstr1_exception_report(client_id=CLIENT, period=PERIOD,
                                     gstin=SECOND, current_user=user)
    assert resp["data"]["arn"] == "ARN-SECOND"


# ── GST-05: a return says when its documents are not split by registration ───

def _gaps(result):
    return [g for g in result["payload_gaps"]
            if "registrations that file GSTR-1" in (g.get("reason") or "")]


def test_a_return_for_a_second_registration_carries_the_caveat(db):
    _second_registration(db)
    out = grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD, SECOND)
    [gap] = _gaps(out)
    assert gap["kind"] == GAP_RETURN_CAVEAT
    assert SECOND in gap["reason"] and PRIMARY in gap["reason"]
    assert "a second registration" in gap["reason"]
    assert gap["withheld"] is False, "a caveat about the whole return, not a document held out"


def test_the_primary_of_a_multi_registration_client_carries_it_too(db):
    """The primary's return is built from the same client-wide documents, so it
    over-declares exactly as much."""
    _second_registration(db)
    [gap] = _gaps(grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD, PRIMARY))
    assert "the primary registration" in gap["reason"]


def test_a_client_with_one_registration_carries_nothing(db):
    assert _gaps(grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD, PRIMARY)) == []
    assert grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD, PRIMARY)["payload_gaps"] is not None


def test_a_registration_that_files_neither_return_does_not_count(db):
    """A composition dealer files CMP-08 and GSTR-4 from its own tables, so a
    second registration of that kind does not contaminate a GSTR-1."""
    _second_registration(db, registration_type="composition", composition_category="trader")
    assert _gaps(grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD, PRIMARY)) == []


def test_a_deleted_registration_does_not_count(db):
    _second_registration(db, deleted_at="2025-01-01T00:00:00Z")
    assert _gaps(grs.gstr1_from_books(db, FIRM, CLIENT, PERIOD, PRIMARY)) == []


def test_gstr3b_carries_the_caveat_and_always_carries_the_key(db):
    one = grs.gstr3b_from_books(db, FIRM, CLIENT, PERIOD, PRIMARY)
    assert "registration_caveat" in one and one["registration_caveat"] is None
    _second_registration(db)
    two = grs.gstr3b_from_books(db, FIRM, CLIENT, PERIOD, SECOND)
    assert SECOND in two["registration_caveat"] and PRIMARY in two["registration_caveat"]


def test_the_exception_report_says_the_books_side_is_not_split(db):
    _second_registration(db)
    _file(db, PRIMARY, _books(db), "ARN-PRIMARY")
    out = svc.gstr1_exceptions(db, FIRM, CLIENT, PERIOD, PRIMARY)
    assert out["registration_caveat"] and PRIMARY in out["registration_caveat"]


# ── the rule itself ──────────────────────────────────────────────────────────

def _r(gstin, primary=False, kind=reg.REGULAR):
    return reg.Registration(gstin=gstin, state_code=gstin[:2], registration_type=kind,
                            filing_frequency=reg.MONTHLY, is_primary=primary)


def test_the_rule_is_silent_for_one_filer():
    assert reg.documents_not_split_caveat([_r(PRIMARY, True)], PRIMARY) is None


def test_the_rule_is_silent_when_the_chosen_gstin_is_not_a_filer():
    assert reg.documents_not_split_caveat(
        [_r(PRIMARY, True), _r(SECOND)], "07AAAAA0000A1Z5") is None


def test_the_rule_names_every_other_registration():
    third = "33AAAAA0000A1Z5"
    text = reg.documents_not_split_caveat([_r(PRIMARY, True), _r(SECOND), _r(third)], SECOND)
    assert PRIMARY in text and third in text and "3 registrations" in text
