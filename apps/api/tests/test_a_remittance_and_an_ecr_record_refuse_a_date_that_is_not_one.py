"""The two payroll records of "what I did at the portal" judge their dates before they are stored (found by the thirteenth slice's drive of the File tab, PRE-A-015).

WHAT WAS WRONG
    `RemittanceIn` (an ESI or professional-tax payment: submitted_on, paid_on, challan_date) and `ECRFiledIn` (an EPF return: submitted_on, approved_on)
    took every date as a bare `Optional[str]`. The services compared two of them as TEXT (`paid_on < submitted_on`), defaulted a missing `submitted_on`
    to today, and stored all of them in DATE columns. A caller that is not the screen (a script, a hand-made request) that sent "30/09/2026" or "soon"
    reached Postgres with it and got a 500 with no sentence, and a day ahead was stored as a payment already made. The screen now starts its date box
    empty, bounds it by today and asks for it in words; this is the same refusal for every other caller.

WHAT IS HELD
    A date that is not a real day is a 422 naming the field, in the one rule every model of this kind shares (`models/iso_date.a_real_date`); blank is the
    same as absent (the service then dates the record today, as it always did); a real one is stored in its canonical form. The dates of things already
    done (the filing, the payment, the approval) are refused when they have not come yet (IST), because both doors record what a person did at a portal
    and plan nothing. The challan's own date was judged as a day only here (nothing here knows when a challan may be dated, and a statutory reading is not
    assumed), and the seventeenth slice refuses a day after today for it too: the challan is what the portal gave once the thing was done, and the record
    is of what was done (`tests/test_the_day_goods_came_back_and_the_day_the_bank_took_the_tax_are_not_after_today.py`).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.auth import get_current_user
from core.ist_clock import ist_today
from routers.payroll import ECRFiledIn, RemittanceIn, router

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}
TOMORROW = ist_today().fromordinal(ist_today().toordinal() + 1).isoformat()
BAD_SHAPES = ["30/09/2026", "2026-02-30", "2026-9-1x", "soon"]

REMITTANCE_FIELDS = ["submitted_on", "paid_on", "challan_date"]
ECR_FIELDS = ["submitted_on", "approved_on"]


def _remittance(**over):
    base = dict(scheme="esic", wage_month="2026-09")
    base.update(over)
    return RemittanceIn(**base)


@pytest.mark.parametrize("bad", BAD_SHAPES)
@pytest.mark.parametrize("field", REMITTANCE_FIELDS)
def test_a_remittance_date_that_is_not_a_real_day_is_refused_naming_the_field(field, bad):
    with pytest.raises(ValidationError) as caught:
        _remittance(**{field: bad})
    assert f"{field} must be a date written YYYY-MM-DD." in str(caught.value)


@pytest.mark.parametrize("bad", BAD_SHAPES)
@pytest.mark.parametrize("field", ECR_FIELDS)
def test_an_ecr_date_that_is_not_a_real_day_is_refused_naming_the_field(field, bad):
    with pytest.raises(ValidationError) as caught:
        ECRFiledIn(**{field: bad})
    assert f"{field} must be a date written YYYY-MM-DD." in str(caught.value)


@pytest.mark.parametrize("field", ["submitted_on", "paid_on", "challan_date"])
def test_a_remittance_filed_or_paid_on_a_day_that_has_not_come_is_refused(field):
    with pytest.raises(ValidationError) as caught:
        _remittance(**{field: TOMORROW})
    assert f"{field} cannot be in the future" in str(caught.value)


@pytest.mark.parametrize("field", ECR_FIELDS)
def test_an_ecr_submitted_or_approved_on_a_day_that_has_not_come_is_refused(field):
    with pytest.raises(ValidationError) as caught:
        ECRFiledIn(**{field: TOMORROW})
    assert f"{field} cannot be in the future" in str(caught.value)


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_is_the_same_as_absent_so_the_service_still_dates_the_record_today(blank):
    r = _remittance(submitted_on=blank, paid_on=blank, challan_date=blank)
    assert (r.submitted_on, r.paid_on, r.challan_date) == (None, None, None)
    e = ECRFiledIn(submitted_on=blank, approved_on=blank)
    assert (e.submitted_on, e.approved_on) == (None, None)


def test_a_real_past_day_is_stored_in_its_canonical_form():
    r = _remittance(submitted_on=" 2026-10-07 ", paid_on="2026-10-07", challan_date="2026-10-07")
    assert (r.submitted_on, r.paid_on, r.challan_date) == ("2026-10-07", "2026-10-07", "2026-10-07")
    assert ECRFiledIn(submitted_on="2026-10-07", approved_on="2026-10-08").approved_on == "2026-10-08"
    assert ist_today().isoformat() == _remittance(paid_on=ist_today().isoformat()).paid_on


def test_a_day_is_not_the_same_as_a_compact_text_that_happens_to_parse():
    # `date.fromisoformat` reads 20261007; what is stored is the canonical text, so the services' text comparison stays a comparison of dates.
    assert _remittance(submitted_on="20261007").submitted_on == "2026-10-07"


# ── over HTTP: a 422 with the sentence at the door, not a 500 from the database ────────────────────────────────────────────────

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def test_the_remittance_door_answers_422_with_the_sentence(client):
    r = client.post("/api/payroll/clients/C1/remittances",
                    json={"scheme": "esic", "wage_month": "2026-09", "status": "paid", "paid_on": "30/09/2026"})
    assert r.status_code == 422, r.text
    assert "paid_on must be a date written YYYY-MM-DD." in r.text


def test_the_ecr_door_answers_422_with_the_sentence(client):
    r = client.post("/api/payroll/runs/run1/ecr/filed", json={"status": "approved", "submitted_on": TOMORROW})
    assert r.status_code == 422, r.text
    assert "submitted_on cannot be in the future" in r.text
