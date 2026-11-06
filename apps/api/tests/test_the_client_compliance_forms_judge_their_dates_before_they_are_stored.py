"""The records a client's MCA and TDS tabs create judge their dates (and the fields a challan is known by) before they are stored (found by the fourteenth slice's drive, PRE-A-015).

WHAT WAS WRONG
    `CreateCompanyRequest.incorporation_date`, `CreateFilingRequest.due_date`, `UpdateDirectorRequest.date_of_cessation` and `CreateChallanRequest.challan_date`
    took their dates as bare strings and handed them to a DATE column (or to `validate_posting_date`, which raises a ValueError for text that is not a day).
    The client's MCA tab sends "" for a box left empty and the TDS tab sent whatever was typed; the insert failed, the handler's broad `except` answered
    "Unable to complete MCA operation" (or the TDS door's own "Could not record the TDS challan"), and both screens ignored the answer and closed the form
    as though the record was saved. A company or a filing typed with no date, and a challan with a mistyped one, was NOT created and nothing said so.
    The screens now read the answer; this is the same refusal, with a sentence naming the field, for every other caller.

    The reviewers of that fix found two things it had wrong or left. A filing's due date is not optional: `mca_filings.due_date` is `DATE NOT NULL`
    (migration 012, unchanged since), so the null the fix first sent for a blank box was refused by the database exactly as the "" had been; the date is
    REQUIRED, at the screen and here. And a challan's BSR code, serial number and section could be left blank and were stored as empty text (the columns are
    NOT NULL, which a blank satisfies), a challan nobody can match to the bank's record.

WHAT IS HELD
    A date that is not a real day is a 422 naming the field (`models/iso_date.a_real_date`); the one OPTIONAL date left (the company's incorporation date,
    `mca_companies.incorp_date` is nullable) left blank is the same as absent; a real one is stored in its canonical form. An incorporation date is refused when it
    has not come yet (IST), because it records a thing already done: a company that has a CIN has been incorporated. A due date and a cessation date are plans and
    may be any day. The challan's date is a real day, and from the seventeenth slice it is not after today in India either: a challan is recorded from the bank's counterfoil,
    whose BSR code and serial number exist only once the bank has taken the tax (how far back it may go is the period lock's, and no statutory reading is assumed here; this file
    first held it to being a day only). A blank cessation date on the PATCH is refused, not read as absent, because the route drops what was not sent and would
    have reported a success for a change it never made.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.auth import get_current_user
from core.ist_clock import ist_today
from routers.mca_workspace import CreateCompanyRequest, CreateFilingRequest, UpdateDirectorRequest, router as mca_router
from routers.tds_workspace import CreateChallanRequest, router as tds_router

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}
TOMORROW = ist_today().fromordinal(ist_today().toordinal() + 1).isoformat()
BAD_SHAPES = ["30/09/2026", "2026-02-30", "2026-9-1x", "soon"]
CIN = "U74999MH2020PTC123456"


def _company(**over):
    return CreateCompanyRequest(**{"client_id": "C1", "cin": CIN, "company_name": "Acme Traders Pvt Ltd", **over})


def _filing(**over):
    return CreateFilingRequest(**{"client_id": "C1", "form_type": "AOC-4", "due_date": "2026-10-30", **over})


def _challan(**over):
    base = dict(client_id="C1", bsr_code="0510308", challan_date="2026-10-07", amount_paise=1234500, challan_no="00123",
                section="194C", financial_year="2026-27", quarter="Q2")
    base.update(over)
    return CreateChallanRequest(**base)


# ── the company's incorporation date ───────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", BAD_SHAPES)
def test_an_incorporation_date_that_is_not_a_real_day_is_refused_naming_the_field(bad):
    with pytest.raises(ValidationError) as caught:
        _company(incorporation_date=bad)
    assert "incorporation_date must be a date written YYYY-MM-DD." in str(caught.value)


def test_a_company_cannot_have_been_incorporated_on_a_day_that_has_not_come():
    with pytest.raises(ValidationError) as caught:
        _company(incorporation_date=TOMORROW)
    assert "incorporation_date cannot be in the future" in str(caught.value)


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_blank_incorporation_date_is_no_date(blank):
    assert _company(incorporation_date=blank).incorporation_date is None


def test_a_real_past_incorporation_date_is_stored_in_its_canonical_form():
    assert _company(incorporation_date=" 2019-06-12 ").incorporation_date == "2019-06-12"
    assert _company(incorporation_date="20190612").incorporation_date == "2019-06-12"
    assert _company(incorporation_date=ist_today().isoformat()).incorporation_date == ist_today().isoformat()


# ── the filing's due date: REQUIRED, because the column is NOT NULL ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", BAD_SHAPES + ["", "   "])
def test_a_due_date_that_is_not_a_real_day_or_is_blank_is_refused_naming_the_field(bad):
    with pytest.raises(ValidationError) as caught:
        _filing(due_date=bad)
    assert "due_date must be a date written YYYY-MM-DD." in str(caught.value)


def test_a_filing_without_a_due_date_is_refused_as_a_missing_field():
    with pytest.raises(ValidationError) as caught:
        CreateFilingRequest(client_id="C1", form_type="AOC-4")
    assert "due_date" in str(caught.value) and "Field required" in str(caught.value)


def test_a_due_date_is_a_plan_and_may_be_any_day():
    assert _filing(due_date=TOMORROW).due_date == TOMORROW
    assert _filing(due_date="2019-06-12").due_date == "2019-06-12"
    assert _filing(due_date="20261030").due_date == "2026-10-30"


# ── a director's cessation date (a PATCH body) ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", BAD_SHAPES + ["", "   "])
def test_a_cessation_date_that_is_not_a_real_day_or_is_blank_is_refused_naming_the_field(bad):
    with pytest.raises(ValidationError) as caught:
        UpdateDirectorRequest(date_of_cessation=bad)
    assert "date_of_cessation must be a date written YYYY-MM-DD." in str(caught.value)


def test_an_omitted_cessation_date_stays_omitted_and_one_ahead_is_a_resignation_effective_later():
    assert UpdateDirectorRequest(kyc_status="active").date_of_cessation is None
    assert UpdateDirectorRequest(date_of_cessation=TOMORROW).date_of_cessation == TOMORROW


# ── the challan: its date, and the three fields it is known by ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", BAD_SHAPES + ["", "   "])
def test_a_challan_date_that_is_not_a_real_day_is_refused_naming_the_field(bad):
    with pytest.raises(ValidationError) as caught:
        _challan(challan_date=bad)
    assert "challan_date must be a date written YYYY-MM-DD." in str(caught.value)


def test_a_challan_dated_after_today_is_refused_and_today_is_allowed():
    """The seventeenth slice reversed this file's earlier stance (a day only): the bank has taken the tax by the day the challan is dated. The rule's own tests are in
    test_the_day_goods_came_back_and_the_day_the_bank_took_the_tax_are_not_after_today.py; this holds the sentence at the door that the rest of this file drives."""
    with pytest.raises(ValidationError) as caught:
        _challan(challan_date=TOMORROW)
    assert "The challan date cannot be after today's date in India." in str(caught.value)
    assert _challan(challan_date=ist_today().isoformat()).challan_date == ist_today().isoformat()


def test_a_challan_date_is_stored_in_its_canonical_form():
    # `date.fromisoformat` reads 20261007; what is stored is the canonical text.
    assert _challan(challan_date="20261007").challan_date == "2026-10-07"


@pytest.mark.parametrize("field", ["bsr_code", "challan_no", "section"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_a_challan_is_not_stored_without_the_fields_it_is_known_by(field, blank):
    with pytest.raises(ValidationError) as caught:
        _challan(**{field: blank})
    assert f"{field} is required." in str(caught.value)


def test_a_challans_identifying_text_is_stored_trimmed_and_no_format_is_assumed():
    c = _challan(bsr_code=" 0510308 ", challan_no=" 00123 ", section=" 194C ")
    assert (c.bsr_code, c.challan_no, c.section) == ("0510308", "00123", "194C")
    # Nothing here knows what a BSR code or a serial number must look like: a short one is the bank's business, not a reading this door assumes.
    assert _challan(bsr_code="12").bsr_code == "12"


# ── over HTTP: a sentence at the door, not a database refusal swallowed into "try again" ────────────────────────────────────────

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(mca_router)
    app.include_router(tds_router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def test_a_filing_is_created_with_the_due_date_it_was_given_in_its_canonical_form(client):
    r = client.post("/api/mca-workspace/filings", json={"client_id": "C1", "form_type": "AOC-4", "financial_year": "2025-26", "due_date": "20261030"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True, body
    assert body["data"]["due_date"] == "2026-10-30"


@pytest.mark.parametrize("sent", [{"due_date": ""}, {"due_date": "31/03/2027"}, {}])
def test_a_filing_without_a_usable_due_date_is_a_422_that_names_the_field(client, sent):
    r = client.post("/api/mca-workspace/filings", json={"client_id": "C1", "form_type": "AOC-4", **sent})
    assert r.status_code == 422, r.text
    assert "due_date" in r.text


def test_a_company_with_no_incorporation_date_is_created_with_no_date(client):
    r = client.post("/api/mca-workspace/companies", json={"client_id": "C1", "cin": CIN, "company_name": "Acme Traders Pvt Ltd", "incorporation_date": ""})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True, body
    assert body["data"]["incorp_date"] is None


def test_a_company_incorporated_on_a_day_that_has_not_come_is_a_422_with_the_sentence(client):
    r = client.post("/api/mca-workspace/companies", json={"client_id": "C1", "cin": CIN, "company_name": "Acme Traders Pvt Ltd", "incorporation_date": TOMORROW})
    assert r.status_code == 422, r.text
    assert "incorporation_date cannot be in the future" in r.text


@pytest.mark.parametrize("bad", ["", "30/09/2026"])
def test_a_challan_with_a_date_that_is_not_a_day_is_a_422_with_the_sentence(client, bad):
    r = client.post("/api/tds-workspace/challans", json={
        "client_id": "C1", "bsr_code": "0510308", "challan_date": bad, "amount_paise": 1234500, "challan_no": "00123",
        "section": "194C", "financial_year": "2026-27", "quarter": "Q2"})
    assert r.status_code == 422, r.text
    assert "challan_date must be a date written YYYY-MM-DD." in r.text


def test_a_nameless_challan_is_a_422_with_the_sentence(client):
    r = client.post("/api/tds-workspace/challans", json={
        "client_id": "C1", "bsr_code": "", "challan_date": "2026-10-07", "amount_paise": 1234500, "challan_no": "00123",
        "section": "194C", "financial_year": "2026-27", "quarter": "Q2"})
    assert r.status_code == 422, r.text
    assert "bsr_code is required." in r.text


def test_the_tds_door_names_the_action_the_drive_expects_when_it_cannot_say_more():
    """The drive's stub speaks `_could_not(…, "record the TDS challan")`'s sentence; the door must still ask for exactly that action."""
    from routers.tds_workspace import create_challan
    assert '_could_not(e, "record the TDS challan")' in inspect.getsource(create_challan)
