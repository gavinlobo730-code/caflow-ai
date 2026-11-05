"""The recurring templates' dates (found by the eleventh slice's drive of their forms, PRE-A-015).

WHAT WAS WRONG
    1. A recurring purchase bill template took both dates as bare strings. The form marks "First bill on" required, a cleared box reports no
       problem, and "" went to the server as `start_date`, where the date parser cannot read it: a 500. Any caller that is not the screen
       could do the same with any text.
    2. Clearing the optional stop date of an EXISTING template did nothing, on both recurring screens. The bill screen left the key out of
       its request (JSON drops `undefined`), and the journal service merged the request over the stored row dropping every None, so an
       explicit "no stop date" kept the old one while the screen said "Template updated".

WHAT IS HELD
    A start date that is not an ISO date is a 422 naming the field, a stop date that is not one is too, and a blank stop date means none. An
    update that sends a blank or null stop date clears it in both services, and an update that leaves the key out leaves it alone.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from routers.recurring_purchase_bills import RecurringBillLineIn, RecurringBillTemplateIn, RecurringBillTemplateUpdateIn


def _template(**over):
    line = RecurringBillLineIn.model_validate({
        "service_catalogue_id": "sc1", "description": "Rent", "quantity": 1, "rate_paise": 5_000_000, "gst_rate_percent": 18})
    base = dict(client_id="c1", vendor_id="v1", title="Rent", frequency="monthly", start_date="2026-11-01", lines=[line])
    base.update(over)
    return RecurringBillTemplateIn(**base)


@pytest.mark.parametrize("bad", ["", "   ", "01/11/2026", "2026-02-31", "soon"])
def test_a_template_start_date_that_is_not_an_iso_date_is_refused_naming_itself(bad):
    with pytest.raises(ValidationError) as caught:
        _template(start_date=bad)
    assert "start_date must be a date written YYYY-MM-DD." in str(caught.value)


@pytest.mark.parametrize("bad", ["01/11/2027", "2027-02-31", "later"])
def test_a_template_end_date_that_is_not_an_iso_date_is_refused_but_blank_means_none(bad):
    with pytest.raises(ValidationError) as caught:
        _template(end_date=bad)
    assert "end_date must be a date written YYYY-MM-DD." in str(caught.value)
    assert _template(end_date="").end_date is None
    assert _template(end_date=None).end_date is None
    assert _template(end_date="2027-10-31").end_date == "2027-10-31"


def test_an_update_refuses_a_blank_start_date_but_leaves_an_omitted_one_alone():
    assert RecurringBillTemplateUpdateIn().start_date is None
    assert RecurringBillTemplateUpdateIn(start_date="2026-12-01").start_date == "2026-12-01"
    with pytest.raises(ValidationError) as caught:
        RecurringBillTemplateUpdateIn(start_date="")
    assert "start_date must be a date written YYYY-MM-DD." in str(caught.value)


def test_an_update_models_stop_date_is_judged_as_the_create_models_is():
    for blank in ("", "   "):
        updated = RecurringBillTemplateUpdateIn(end_date=blank)
        assert updated.end_date is None
        # `exclude_unset` is how the route dumps it, and the key must survive as an explicit None: that is what the service reads as "clear".
        assert updated.model_dump(exclude_unset=True) == {"end_date": None}
    assert RecurringBillTemplateUpdateIn(end_date="2027-10-31").end_date == "2027-10-31"
    assert "end_date" not in RecurringBillTemplateUpdateIn().model_dump(exclude_unset=True)
    for bad in ("later", "31/10/2027", "2027-02-31"):
        with pytest.raises(ValidationError) as caught:
            RecurringBillTemplateUpdateIn(end_date=bad)
        assert "end_date must be a date written YYYY-MM-DD." in str(caught.value)


# ── A stop date cleared on an edit is cleared ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def _journals():
    from services import recurring_journal_service as svc
    svc.MOCK_JOURNAL_TEMPLATES.clear()
    yield svc
    svc.MOCK_JOURNAL_TEMPLATES.clear()


def _journal(svc, **over):
    lines = [{"account_id": "ACC-DR", "debit_paise": 500_000, "credit_paise": 0},
             {"account_id": "ACC-CR", "debit_paise": 0, "credit_paise": 500_000}]
    data = {"client_id": "C1", "name": "Monthly rent", "frequency": "monthly", "day_of_month": 1,
            "start_date": "2026-11-01", "end_date": "2027-10-31", "lines": lines}
    data.update(over)
    return svc.create_template("F1", data, created_by="u1")


@pytest.mark.parametrize("cleared", [None, "", "   "])
def test_a_journal_templates_stop_date_sent_empty_is_cleared(_journals, cleared):
    made = _journal(_journals)
    out = _journals.update_template("F1", made["id"], {"end_date": cleared})
    assert out["end_date"] is None
    assert _journals.get_template("F1", made["id"])["end_date"] is None


def test_a_journal_templates_stop_date_is_kept_when_the_edit_does_not_mention_it(_journals):
    made = _journal(_journals)
    out = _journals.update_template("F1", made["id"], {"name": "Rent, renamed"})
    assert (out["name"], out["end_date"]) == ("Rent, renamed", "2027-10-31")


def test_a_journal_templates_stop_date_can_be_changed_and_a_reversed_window_is_still_refused(_journals):
    from fastapi import HTTPException
    made = _journal(_journals)
    assert _journals.update_template("F1", made["id"], {"end_date": "2028-03-31"})["end_date"] == "2028-03-31"
    with pytest.raises(HTTPException) as caught:
        _journals.update_template("F1", made["id"], {"end_date": "2026-10-01"})
    assert caught.value.status_code == 422 and "cannot precede" in str(caught.value.detail)


def test_a_bill_templates_stop_date_rule_is_the_keys_presence_and_an_empty_value_stores_none():
    from services import recurring_purchase_bill_service as svc
    src = open(svc.__file__).read()
    # The service reads a database with no mock mode, so its rule is held where it is written, and the model test above holds the value that
    # reaches it: the key's PRESENCE decides, and an empty value stores none.
    assert '"end_date" in data' in src
    assert 'if data.get("end_date") else None' in src
