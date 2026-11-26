"""The compliance record doors answer a refusal in the refusal's own sentence (POST-A-392, item 2).

THE GAP
    `PATCH /api/compliance-records/{id}` and `POST /api/compliance-records` answered a `ValidationError` with `str(e)`, which is
    "Validation error on filed_date: <sentence>": a column name in front of the words a person reads. The obligation doors
    (`routers/compliance_ops`) had already stopped doing that and answered with `e.message`; these two had not. The create door also
    answered a missing key with `str(KeyError)`, which is the key in quotes and says nothing.

WHAT IS HELD
    * a refusal the service raises is the 422's detail word for word, with no "Validation error on" in front;
    * a missing key is a sentence that names it.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.compliance_records as door
from core.exceptions import ValidationError

USER = {"id": "u1", "firm_id": "F1", "role": "Partner"}
SENTENCE = "The date filed is not a date: write it as YYYY-MM-DD."


@pytest.fixture
def refused(monkeypatch):
    monkeypatch.setattr(door, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(door.compliance_record_service, "get_record", lambda *a, **k: {"id": "r1", "client_id": "c1"})

    def _refuse(*a, **k):
        raise ValidationError("filed_date", SENTENCE)
    monkeypatch.setattr(door.compliance_record_service, "update_record", _refuse)
    monkeypatch.setattr(door.compliance_record_service, "create_record", _refuse)


def test_an_edit_that_is_refused_is_answered_in_the_refusals_own_sentence(refused):
    with pytest.raises(HTTPException) as e:
        door.update_compliance_record("r1", door.ComplianceRecordUpdateIn(filed_date="2026-11-01"), current_user=USER)
    assert (e.value.status_code, e.value.detail) == (422, SENTENCE)


def test_a_create_that_is_refused_is_answered_in_the_refusals_own_sentence(refused):
    with pytest.raises(HTTPException) as e:
        door.create_compliance_record(door.ComplianceRecordIn(client_id="c1", compliance_type="GSTR-3B"), current_user=USER)
    assert (e.value.status_code, e.value.detail) == (422, SENTENCE)


def test_a_create_missing_a_field_names_the_field(monkeypatch):
    monkeypatch.setattr(door, "assert_client_access", lambda *a, **k: None)

    def _missing(*a, **k):
        raise KeyError("due_date")
    monkeypatch.setattr(door.compliance_record_service, "create_record", _missing)
    with pytest.raises(HTTPException) as e:
        door.create_compliance_record(door.ComplianceRecordIn(client_id="c1", compliance_type="GSTR-3B"), current_user=USER)
    assert (e.value.status_code, e.value.detail) == (422, "due_date is required.")
