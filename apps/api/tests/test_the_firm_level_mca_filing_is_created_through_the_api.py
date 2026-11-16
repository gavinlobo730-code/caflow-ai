"""The firm-level MCA Add Filing is created through the API, as the client tab's is (POST-A-442).

WHAT WAS WRONG
    `app/mca/page.tsx` inserted `mca_filings` over PostgREST while the client tab posted to `POST /api/mca-workspace/filings`. So a
    filing made on the firm-level page had no `category` (the client's Annual and Event tabs list by it, so it never showed there),
    wrote no audit event, and was never asked whether its company is its own client's. The API in turn did not take what the firm
    form sends: a typed CIN, an Overdue status, the client's name the firm-level list shows, and MGT-7A, which the form has always
    offered and `mca_filing_closes_obligation` already calls an annual form matched to no obligation.

WHAT IS HELD (through the real route over the shared in-memory database)
    * MGT-7A is created, as an annual filing, with no year asked of it (it closes no obligation, POST-C-209);
    * INC-20A, DIR-3 KYC and MSME-1 are still refused, and nothing is stored: which tab lists them and what rule dates them is not
      settled in this repository, so the API does not decide it and the firm-level form no longer offers them;
    * a CIN typed where no company is named is stored upper case in both CIN columns, a malformed one is refused in the Company
      Master's words and nothing is stored, and a named company's own CIN outranks a typed one;
    * the status is Not started or Overdue as the CA chose, and Filed is not a status a create can take;
    * the row carries the client's name, read under the firm;
    * the insert and the status update are made with the privileged client, and the update names the firm and the client.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

import routers.mca_workspace as mw
from tests import _privileged_write_sites as pw
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}
GOOD_CIN = "U17200MH2010PTC205678"


@pytest.fixture
def world(monkeypatch):
    import services.audit_service as au
    import services.timeline_service as ts
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    wire_e2e(monkeypatch, d, [mw])
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(mw, "can_access_client", lambda user, client_id: True)
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Acme Private Limited"})
    d.seed("clients", {"id": "client-other-firm", "firm_id": "firm-2", "client_name": "Someone Else"})
    yield d


def _create(**kw):
    body = {"client_id": CLIENT, "form_type": "AOC-4", "financial_year": "2025-26", "due_date": "2026-10-30", **kw}
    return mw.create_filing(mw.CreateFilingRequest(**body), current_user=USER)


def test_mgt_7a_is_created_as_an_annual_filing_with_no_year_asked(world):
    out = _create(form_type="MGT-7A", financial_year=None, cin=GOOD_CIN)
    assert out["success"] is True, out
    [row] = world.rows("mca_filings")
    assert row["form_type"] == "MGT-7A" and row["category"] == "annual"


@pytest.mark.parametrize("form", ["INC-20A", "DIR-3 KYC", "MSME-1"])
def test_the_three_forms_whose_list_is_not_settled_are_still_refused_and_nothing_is_stored(world, form):
    out = _create(form_type=form, financial_year=None, cin=GOOD_CIN)
    assert out["success"] is False and "Invalid form_type" in out["error"]
    assert world.rows("mca_filings") == []


def test_a_typed_cin_is_stored_upper_case_in_both_columns_when_no_company_is_named(world):
    out = _create(cin=f"  {GOOD_CIN.lower()} ")
    assert out["success"] is True, out
    [row] = world.rows("mca_filings")
    assert row["cin"] == row["company_cin"] == GOOD_CIN
    assert row["company_id"] is None


def test_a_malformed_typed_cin_is_refused_in_the_company_masters_words_and_nothing_is_stored(world):
    out = _create(cin="NOT-A-CIN")
    assert out["success"] is False and "CIN format is invalid" in out["error"]
    assert world.rows("mca_filings") == []


def test_a_named_companys_own_cin_outranks_a_typed_one(world):
    world.seed("mca_companies", {"id": "co-1", "firm_id": FIRM, "client_id": CLIENT, "is_active": True,
                                 "company_name": "Acme", "cin": "L17110MH1973PLC019786"})
    out = _create(company_id="co-1", cin=GOOD_CIN)
    assert out["success"] is True, out
    [row] = world.rows("mca_filings")
    assert row["cin"] == row["company_cin"] == "L17110MH1973PLC019786"


def test_a_named_company_with_no_cin_of_its_own_takes_the_typed_one(world):
    world.seed("mca_companies", {"id": "co-1", "firm_id": FIRM, "client_id": CLIENT, "is_active": True,
                                 "company_name": "Acme", "cin": None})
    out = _create(company_id="co-1", cin=GOOD_CIN)
    assert out["success"] is True, out
    [row] = world.rows("mca_filings")
    assert row["cin"] == GOOD_CIN and row["company_id"] == "co-1"


@pytest.mark.parametrize("status", ["not_started", "overdue"])
def test_the_status_is_the_one_the_ca_chose(world, status):
    assert _create(cin=GOOD_CIN, status=status)["success"] is True
    [row] = world.rows("mca_filings")
    assert row["status"] == status


@pytest.mark.parametrize("status", ["filed", "in_progress", "Filed"])
def test_a_create_cannot_take_any_other_status(status):
    with pytest.raises(ValidationError):
        mw.CreateFilingRequest(client_id=CLIENT, form_type="AOC-4", financial_year="2025-26", due_date="2026-10-30", status=status)


def test_the_row_carries_the_clients_name_read_under_the_firm(world):
    assert _create(cin=GOOD_CIN)["success"] is True
    [row] = world.rows("mca_filings")
    assert row["client_name"] == "Acme Private Limited"


def test_a_name_from_another_firm_is_never_written(world):
    assert mw._client_name(FIRM, "client-other-firm") is None


TABLES = frozenset({"mca_filings"})


def test_every_write_to_mca_filings_starts_at_the_privileged_client():
    bad = pw.unprivileged_writes(TABLES)
    assert not bad, "a write to mca_filings is made with the caller's own client:\n  " + "\n  ".join(bad)


def test_every_update_and_delete_of_mca_filings_names_the_firm_and_the_client():
    bad = pw.unscoped(TABLES)
    assert not bad, "an update or a delete of mca_filings does not name both the firm and the client:\n  " + "\n  ".join(bad)


def test_the_census_finds_the_three_writes_there_are():
    assert pw.census(TABLES) == {"mca_filings": 3}
