"""
Client-assignment scope on the eway_bill router — CGST Act §68/Rule 138.

create_eway_bill already called assert_client_access before this phase.
list_eway_bills took client_id from the query string and never checked it.
record_ewb_generated/extend_ewb/cancel_ewb are row-addressed by record_id
with NO client_id in the request body at all and checked only firm_id — an
unassigned staff member with gst.approve could record/extend/cancel another
client's E-Way Bill just by guessing or observing a record_id. New
get_eway_bill lookup + _assert_ewb_scope resolver closes that gap.
"""
import pytest
from fastapi import HTTPException

import routers.eway_bill as ewb
import domain.income_tax.eway_service as eway_service

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else. Patches assert_client_access/
    can_access_client on the router module, mirroring the other
    *_client_scope.py test files in this sweep."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(ewb, "assert_client_access", _assert)
    monkeypatch.setattr(ewb, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# list_eway_bills — client_id from the query string
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_clients_eway_bills_is_refused(deny, monkeypatch):
    monkeypatch.setattr(eway_service, "list_eway_bills", lambda *a, **kw: [])
    with pytest.raises(HTTPException) as e:
        ewb.list_eway_bills(client_id=THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_listing_your_own_clients_eway_bills_still_works(deny, monkeypatch):
    monkeypatch.setattr(eway_service, "list_eway_bills", lambda *a, **kw: [{"id": "e1"}])
    out = ewb.list_eway_bills(client_id=MINE, current_user=USER)
    assert out["data"] == [{"id": "e1"}]
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# _assert_ewb_scope + record_ewb_generated/extend_ewb/cancel_ewb — row-addressed
# ══════════════════════════════════════════════════════════════════════════════

def test_ewb_scope_refuses_another_clients_record(deny, monkeypatch):
    monkeypatch.setattr(eway_service, "get_eway_bill", lambda firm_id, record_id: {"id": record_id, "client_id": THEIRS})
    with pytest.raises(HTTPException) as e:
        ewb._assert_ewb_scope(USER, "EWB-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_ewb_scope_allows_your_own_record(deny, monkeypatch):
    row = {"id": "EWB-MINE", "client_id": MINE}
    monkeypatch.setattr(eway_service, "get_eway_bill", lambda firm_id, record_id: row)
    assert ewb._assert_ewb_scope(USER, "EWB-MINE") == row
    assert deny == [MINE]


def test_missing_and_hidden_ewb_records_use_the_identical_message(deny, monkeypatch):
    monkeypatch.setattr(eway_service, "get_eway_bill", lambda firm_id, record_id: None)
    with pytest.raises(HTTPException) as missing:
        ewb._assert_ewb_scope(USER, "EWB-NOPE")

    monkeypatch.setattr(eway_service, "get_eway_bill", lambda firm_id, record_id: {"id": record_id, "client_id": THEIRS})
    with pytest.raises(HTTPException) as hidden:
        ewb._assert_ewb_scope(USER, "EWB-THEIRS")

    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "E-Way Bill record not found"


def test_recording_ewb_generated_for_another_clients_record_is_refused(deny, monkeypatch):
    monkeypatch.setattr(eway_service, "get_eway_bill", lambda firm_id, record_id: {"id": record_id, "client_id": THEIRS})
    called = []
    monkeypatch.setattr(eway_service, "record_ewb_generated", lambda **kw: called.append(kw))
    with pytest.raises(HTTPException):
        ewb.record_ewb_generated(
            "EWB-THEIRS",
            ewb.RecordEWBGeneratedRequest(ewb_number="1", ewb_date="2026-01-01", ewb_valid_upto="2026-01-05"),
            current_user=USER,
        )
    assert not called   # refused before the domain mutation ever ran


def test_extending_another_clients_ewb_is_refused(deny, monkeypatch):
    monkeypatch.setattr(eway_service, "get_eway_bill", lambda firm_id, record_id: {"id": record_id, "client_id": THEIRS})
    called = []
    monkeypatch.setattr(eway_service, "record_ewb_extended", lambda *a, **kw: called.append((a, kw)))
    with pytest.raises(HTTPException):
        ewb.extend_ewb(
            "EWB-THEIRS", ewb.ExtendEWBRequest(new_valid_upto="2026-02-01", extension_reason="delay"),
            current_user=USER,
        )
    assert not called


def test_cancelling_another_clients_ewb_is_refused(deny, monkeypatch):
    monkeypatch.setattr(eway_service, "get_eway_bill", lambda firm_id, record_id: {"id": record_id, "client_id": THEIRS})
    called = []
    monkeypatch.setattr(eway_service, "record_ewb_cancelled", lambda *a, **kw: called.append((a, kw)))
    with pytest.raises(HTTPException):
        ewb.cancel_ewb("EWB-THEIRS", ewb.CancelEWBRequest(cancellation_reason="wrong vehicle"), current_user=USER)
    assert not called


# ══════════════════════════════════════════════════════════════════════════════
# get_eway_bill (domain/income_tax/eway_service.py) — the resolve half
# ══════════════════════════════════════════════════════════════════════════════

def test_get_eway_bill_mock_mode_scopes_by_firm(monkeypatch):
    monkeypatch.setattr(eway_service, "_USE_MOCK", True)
    eway_service._MOCK_RECORDS.clear()
    eway_service._MOCK_RECORDS["rec-1"] = {"id": "rec-1", "firm_id": "firm-a", "client_id": "c1"}
    assert eway_service.get_eway_bill("firm-a", "rec-1") is not None
    assert eway_service.get_eway_bill("firm-b", "rec-1") is None   # different firm — not visible
    eway_service._MOCK_RECORDS.clear()
