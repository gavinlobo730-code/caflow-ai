"""A new MCA filing names the client's company and the year the calendar holds open (POST-A-291).

WHAT WAS WRONG
    The calendar's AOC-4 and MGT-7 obligations are one per client per year, and `mca_companies` allows several companies per
    client, so the closer (`services/mca_filing_closes_obligation`) closes the obligation only when every active company has
    filed, placing each filing by its `company_id` or its CIN. Neither screen offered a company: the client tab's Create
    Filing sent none and the API stored none, so with two companies no filing made there could ever close its obligation.
    The firm-level Add Filing asked for a CIN as typed text and defaulted its period to the CURRENT financial year, while a
    form filed in season is for the year that has just ended.

WHAT IS HELD (mock mode, through the real routes over the shared in-memory database and the in-memory calendar)
    * `GET /api/mca-workspace/filing-choices` answers the client's ACTIVE companies in name order (not an inactive one, not
      another client's or firm's), says a choice is required when there is more than one, and offers the financial years the
      calendar holds the form's obligation OPEN in, newest first, with each one's due date: not a year already Filed or
      Completed, not another form's, client's or firm's, not a window that is not a financial year's own;
    * no year is offered, and a sentence says why, for a form with no obligation on the calendar, for MGT-7A, for a caller
      whose access does not include Compliance, and when the calendar holds none open;
    * a filing created through the API with no company is refused in words when the client has several active companies
      and stores nothing; an inactive company does not count, and naming one is refused (the closer counts only active
      companies, so it could never be placed, or would close the obligation for the active one); a company that is not the
      client's is a 404 and stores nothing, in either mode; an id is matched without case, as Postgres matches a uuid; a
      company named stores its own CIN, upper case, in both CIN columns;
    * a filing of a form that stands for an obligation (AOC-4, MGT-7, ADT-1) with no year is refused in words, because it
      could never close it; an event form needs none; the answer says whether the form stands for one;
    * with two companies, a filing created for each through the API and recorded as filed closes the obligation on the
      second; with one company, a filing that names none still closes it, as before;
    * the route asks the MCA read permission and the client's access.
"""
from __future__ import annotations

import ast
import inspect

import pytest
from fastapi import HTTPException

import routers.mca_workspace as mw
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


@pytest.fixture
def world(monkeypatch):
    import services.audit_service as au
    import services.timeline_service as ts
    d = FakeDB()
    MOCK_COMPLIANCE_RECORDS.clear()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    wire_e2e(monkeypatch, d, [mw])
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(mw, "can_access_client", lambda user, client_id: True)
    yield d
    MOCK_COMPLIANCE_RECORDS.clear()


_N = {"n": 0}


def _company(db, name, *, active=True, client=CLIENT, firm=FIRM, cin=None):
    _N["n"] += 1
    return db.seed("mca_companies", {"id": f"co-{_N['n']}", "firm_id": firm, "client_id": client, "is_active": active,
                                     "company_name": name, "cin": cin or f"u00000mh2020ptc{_N['n']:06d}"})


def _obligation(otype="MCA_AOC4", start="2025-04-01", end="2026-03-31", status="Not Started", client=CLIENT, firm=FIRM,
                due="2026-10-30"):
    return compliance_records_repo.create({
        "firm_id": firm, "client_id": client, "compliance_type": "MCA", "obligation_type": otype,
        "period_label": f"{otype} {start}", "period_start": start, "period_end": end, "due_date": due, "status": status})


def _choices(form="AOC-4", client=CLIENT, user=USER):
    out = mw.filing_choices(client_id=client, form_type=form, current_user=user)
    assert out["success"] is True, out
    return out["data"]


def _create(company=None, form="AOC-4", fy="2025-26", client=CLIENT):
    return mw.create_filing(mw.CreateFilingRequest(client_id=client, company_id=company, form_type=form, financial_year=fy,
                                                   due_date="2026-10-30"), current_user=USER)


# ── what the screens are offered ────────────────────────────────────────────

def test_the_choices_are_the_clients_active_companies_in_name_order(world):
    _company(world, "Gamma Pvt Ltd")
    alpha = _company(world, "alpha Pvt Ltd")
    _company(world, "Beta Pvt Ltd", active=False)
    _company(world, "Not Ours Pvt Ltd", client="client-2")
    _company(world, "Another Firm's Pvt Ltd", firm="firm-2")
    got = _choices()
    assert [c["company_name"] for c in got["companies"]] == ["alpha Pvt Ltd", "Gamma Pvt Ltd"]
    assert got["companies"][0] == {"id": alpha["id"], "company_name": "alpha Pvt Ltd", "cin": alpha["cin"]}
    assert got["company_required"] is True


def test_one_active_company_needs_no_choice_and_none_needs_none(world):
    _company(world, "Alpha Pvt Ltd")
    _company(world, "Old Pvt Ltd", active=False)
    assert _choices()["company_required"] is False and len(_choices()["companies"]) == 1
    assert _choices(client="client-9") == {**_choices(client="client-9"), "companies": [], "company_required": False}


def test_the_years_offered_are_the_open_obligations_of_this_form_newest_first(world):
    _obligation(start="2024-04-01", end="2025-03-31", due="2025-10-30")
    _obligation(start="2025-04-01", end="2026-03-31", due="2026-10-30")
    _obligation(start="2023-04-01", end="2024-03-31", status="Filed")
    _obligation(start="2022-04-01", end="2023-03-31", status="Completed")
    _obligation(otype="MCA_MGT7", start="2021-04-01", end="2022-03-31")
    _obligation(start="2020-04-01", end="2021-03-31", client="client-2")
    _obligation(start="2019-04-01", end="2020-03-31", firm="firm-2")
    _obligation(start="2018-04-01", end="2018-09-30")                     # not a financial year's own window
    got = _choices()
    assert got["periods"] == [
        {"financial_year": "2025-26", "due_date": "2026-10-30", "status": "Not Started"},
        {"financial_year": "2024-25", "due_date": "2025-10-30", "status": "Not Started"},
    ]
    assert got["periods_note"] is None
    assert [p["financial_year"] for p in _choices("MGT-7")["periods"]] == ["2021-22"]


@pytest.mark.parametrize("form, says", [
    ("CHG-1", "holds no obligation for CHG-1"),
    ("MGT-7A", "holds no obligation for MGT-7A"),
    ("INC-20A", "holds no obligation for INC-20A"),
])
def test_a_form_with_no_obligation_on_the_calendar_offers_no_year_and_says_so(world, form, says):
    _obligation()
    got = _choices(form)
    assert got["periods"] is None and says in got["periods_note"] and "Type the year" in got["periods_note"]
    assert got["has_obligation"] is False


def test_the_answer_says_whether_the_form_stands_for_an_obligation(world):
    assert [_choices(form)["has_obligation"] for form in ("AOC-4", "MGT-7", "ADT-1", "DIR-12", "MGT-7A")] == [
        True, True, True, False, False]


def test_no_open_obligation_offers_an_empty_list_and_says_so(world):
    _obligation(status="Filed")
    got = _choices()
    assert got["periods"] == [] and "holds no open AOC-4 for this client" in got["periods_note"]


def test_a_caller_without_compliance_access_is_offered_no_year_and_told_why(world, monkeypatch):
    _obligation()
    real = mw.can_user
    monkeypatch.setattr(mw, "can_user", lambda user, resource, action: False if resource == "compliance" else real(user, resource, action))
    got = _choices()
    assert got["periods"] is None and "does not include Compliance" in got["periods_note"]


def test_the_route_asks_the_mca_read_permission_and_the_clients_access():
    source = inspect.getsource(mw.filing_choices)
    tree = ast.parse(source.lstrip())
    fn = tree.body[0]
    assert "rbac('mca', 'read')" in ast.unparse(fn.args)
    assert any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "assert_client_access"
               and [ast.unparse(a) for a in n.args] == ["current_user", "client_id"] for n in ast.walk(fn))


# ── what the API stores ─────────────────────────────────────────────────────

def test_a_filing_naming_no_company_is_refused_when_the_client_has_several_and_nothing_is_stored(world):
    _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    out = _create(company=None)
    assert out["success"] is False
    assert out["error"] == "This client has 2 active companies. Choose the company this filing is for."
    assert world.rows("mca_filings") == []


def test_an_inactive_company_does_not_count_and_one_active_company_needs_no_choice(world):
    _company(world, "Alpha Pvt Ltd"), _company(world, "Old Pvt Ltd", active=False)
    out = _create(company=None)
    assert out["success"] is True and out["data"]["company_id"] is None and out["data"]["company_cin"] is None


def test_a_company_that_is_not_the_clients_is_a_404_and_nothing_is_stored(world):
    _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    theirs = _company(world, "Not Ours Pvt Ltd", client="client-2")
    with pytest.raises(HTTPException) as exc:
        _create(company=theirs["id"])
    assert exc.value.status_code == 404 and exc.value.detail == "That company was not found."
    assert world.rows("mca_filings") == []


def test_naming_an_inactive_company_is_refused_in_words_and_nothing_is_stored(world):
    _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    gone = _company(world, "Old Pvt Ltd", active=False)
    out = _create(company=gone["id"])
    assert out["success"] is False
    assert out["error"] == "Old Pvt Ltd is not an active company of this client. Choose one of its active companies."
    assert world.rows("mca_filings") == []


@pytest.mark.parametrize("form", ["AOC-4", "MGT-7", "ADT-1"])
def test_a_filing_of_a_form_that_stands_for_an_obligation_needs_a_year(world, form):
    out = _create(form=form, fy=None)
    assert out["success"] is False
    assert out["error"] == (f"{form}: say the financial year this filing is for. Without a year it can never close its "
                            "obligation on the compliance calendar.")
    assert world.rows("mca_filings") == []


def test_an_event_form_needs_no_year(world):
    assert _create(form="DIR-12", fy=None)["success"] is True


def test_a_company_named_stores_its_own_cin_in_both_columns(world):
    alpha = _company(world, "Alpha Pvt Ltd", cin=" u17200mh2010ptc205678 ")
    _company(world, "Beta Pvt Ltd")
    out = _create(company=alpha["id"])
    assert out["success"] is True
    [row] = world.rows("mca_filings")
    assert (row["company_id"], row["company_cin"], row["cin"]) == (alpha["id"], "U17200MH2010PTC205678", "U17200MH2010PTC205678")


# ── the verification the ledger asked for ───────────────────────────────────

def _file(filing_id, day="2026-06-15", srn="T12345678"):
    return mw.update_filing_status(filing_id, mw.UpdateFilingStatusRequest(status="filed", ca_approved=True, srn=srn,
                                                                           filing_date=day), current_user=USER)


def test_with_two_companies_filing_the_form_for_each_from_the_api_closes_the_obligation_on_the_second(world):
    alpha, beta = _company(world, "Alpha Pvt Ltd"), _company(world, "Beta Pvt Ltd")
    obligation = _obligation()
    first = _create(company=alpha["id"])["data"]
    second = _create(company=beta["id"])["data"]
    assert _file(first["id"])["data"]["compliance_obligation"]["state"] == "waiting_for_other_companies"
    assert compliance_records_repo.find_by_id(obligation["id"])["status"] == "Not Started"
    assert _file(second["id"], day="2026-06-16")["data"]["compliance_obligation"]["state"] == "closed"
    assert compliance_records_repo.find_by_id(obligation["id"])["status"] == "Filed"


def test_with_one_company_a_filing_that_names_none_still_closes_the_obligation(world):
    _company(world, "Alpha Pvt Ltd")
    obligation = _obligation()
    made = _create(company=None)["data"]
    assert _file(made["id"])["data"]["compliance_obligation"]["state"] == "closed"
    assert compliance_records_repo.find_by_id(obligation["id"])["status"] == "Filed"


# ── mock mode reads its own store ───────────────────────────────────────────

@pytest.fixture
def in_memory(world, monkeypatch):
    monkeypatch.setattr(mw, "_USE_MOCK", True)
    mw._MOCK_COMPANIES.clear()
    mw._MOCK_FILINGS.clear()
    yield
    mw._MOCK_COMPANIES.clear()
    mw._MOCK_FILINGS.clear()


def test_mock_mode_offers_the_active_companies_of_this_client_and_refuses_a_filing_naming_none_among_two(in_memory):
    for cid, name, client, active in (("m1", "Beta", CLIENT, True), ("m2", "Alpha", CLIENT, True),
                                      ("m3", "Gone", CLIENT, False), ("m4", "Theirs", "client-2", True)):
        mw._MOCK_COMPANIES[cid] = {"id": cid, "firm_id": FIRM, "client_id": client, "company_name": name, "cin": f"C{cid}",
                                   "is_active": active}
    assert [c["id"] for c in _choices()["companies"]] == ["m2", "m1"]
    assert _create(company=None)["success"] is False and mw._MOCK_FILINGS == {}
    made = _create(company="m1")["data"]
    assert made["company_cin"] == "CM1" and mw._MOCK_FILINGS[made["id"]]["company_id"] == "m1"
    with pytest.raises(HTTPException) as exc:                 # another client's company: mock mode asks the same question
        _create(company="m4")
    assert exc.value.status_code == 404 and exc.value.detail == "That company was not found."
    assert _create(company="m3")["success"] is False           # an inactive one


def test_mock_mode_reads_only_this_firms_companies_and_reads_a_missing_flag_as_active(in_memory):
    mw._MOCK_COMPANIES["n1"] = {"id": "n1", "client_id": CLIENT, "company_name": "No firm on the row"}
    mw._MOCK_COMPANIES["n2"] = {"id": "n2", "firm_id": FIRM, "client_id": CLIENT, "company_name": "No flag"}
    mw._MOCK_COMPANIES["n3"] = {"id": "n3", "firm_id": FIRM, "client_id": CLIENT, "company_name": "Flag none", "is_active": None}
    assert [c["id"] for c in _choices()["companies"]] == ["n2"]


def test_a_company_id_is_matched_without_case_as_postgres_matches_a_uuid(in_memory):
    """The database's ownership check compares a uuid without case, so this one must too (the in-memory double's `.eq` does not,
    which is why this is asked in mock mode, where only this check runs)."""
    uid = "5c1d2e3f-0000-4000-8000-00000000abcd"
    mw._MOCK_COMPANIES[uid] = {"id": uid, "firm_id": FIRM, "client_id": CLIENT, "company_name": "Alpha", "cin": "c1"}
    mw._MOCK_COMPANIES["b"] = {"id": "b", "firm_id": FIRM, "client_id": CLIENT, "company_name": "Beta", "cin": "c2"}
    out = _create(company=uid.upper())
    assert out["success"] is True and out["data"]["company_cin"] == "C1" and out["data"]["company_id"] == uid
