"""POST-A-368 (first slice) — a return recorded as filed without a saved computation can be pinned to one, and its loss records updated.

WHAT WAS WRONG
    The write of a filed return's use of each brought-forward loss (POST-A-073) runs once, when the acknowledgement is recorded, and reads the
    computation the filing pinned. A return created without one, or whose write was refused (the caller could not change loss records, the
    database did not answer), had no way to be written afterwards, and every answer that said so could only say "there is no screen".

WHAT THIS PINS
    PIN       a return with no pinned computation can be pinned to this client's own computation for its year, once; a computation of another
              client or year, one that does not exist, and a return that already has a pin are refused in words and change nothing.
    RE-RUN    a return recorded as filed can have its loss records updated again (the same idempotent write the acknowledgement makes, audited);
              a return that is not filed is refused and writes nothing, so a draft's what-if computation cannot consume a client's loss.
"""
import pytest
from fastapi import HTTPException

import routers.itr_workspace as itr
from domain.income_tax.computation_workspace import _MOCK_LOSSES, _MOCK_SNAPSHOTS
from domain.income_tax.itr_workflow import _MOCK_FILINGS
from services import bf_loss_service as svc

L = 1_00_000_00
FIRM = "F1"
MINE, OTHER = "client-mine", "client-other"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "email": "ca@example.in", "role": "Partner"}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for store in (_MOCK_LOSSES, _MOCK_SNAPSHOTS, _MOCK_FILINGS):
        store.clear()
    monkeypatch.setattr(itr, "can_access_client", lambda user, client_id: True)
    monkeypatch.setattr(itr, "assert_client_access", lambda user, client_id: None)
    monkeypatch.setattr(itr.timeline_service, "log", lambda **k: None)
    monkeypatch.setattr(svc, "can_access_client", lambda user, client_id: True)
    yield
    for store in (_MOCK_LOSSES, _MOCK_SNAPSHOTS, _MOCK_FILINGS):
        store.clear()


@pytest.fixture
def audit(monkeypatch):
    events = []
    import services.audit_service as audit_service
    monkeypatch.setattr(audit_service, "log_event", lambda *a, **k: events.append((a, k)))
    return events


def loss(loss_id="L1", client=MINE, original=10 * L):
    _MOCK_LOSSES[loss_id] = {
        "id": loss_id, "firm_id": FIRM, "client_id": client, "loss_type": "business", "assessment_year": "2024-25",
        "original_amount_paise": original, "utilized_amount_paise": 0, "remaining_amount_paise": original,
        "expiry_assessment_year": "2032-33", "source_itr_ack": "ACK", "utilisations": {},
    }


def snapshot(snapshot_id="S1", client=MINE, fy="2025-26", used=4 * L):
    _MOCK_SNAPSHOTS[snapshot_id] = {
        "id": snapshot_id, "firm_id": FIRM, "client_id": client, "financial_year": fy,
        "computation_json": {"brought_forward": {"set_off_paise": used, "lines": [
            {"loss_id": "L1", "loss_type": "business", "section": "§72", "set_off_paise": used}]}},
    }


def filing(filing_id="F1", status="filed", snapshot_id=None, client=MINE, fy="2025-26"):
    _MOCK_FILINGS[filing_id] = {
        "id": filing_id, "firm_id": FIRM, "client_id": client, "financial_year": fy, "assessment_year": "2026-27",
        "return_type": "original", "status": status, "computation_snapshot_id": snapshot_id, "itr_form": "ITR-3",
    }


def pin(filing_id, snapshot_id):
    return itr.pin_filing_computation(filing_id, itr.PinComputationRequest(computation_snapshot_id=snapshot_id), USER)


# ───────────────────────────── PIN ─────────────────────────────

def test_a_return_with_no_pin_is_pinned_to_this_clients_computation_for_its_year():
    snapshot("S1")
    filing("F1")
    out = pin("F1", "S1")
    assert out["success"] is True and out["data"]["computation_snapshot_id"] == "S1"
    assert _MOCK_FILINGS["F1"]["computation_snapshot_id"] == "S1"


@pytest.mark.parametrize("make", [
    lambda: snapshot("S1", client=OTHER),
    lambda: snapshot("S1", fy="2024-25"),
])
def test_another_clients_or_another_years_computation_is_refused_and_nothing_changes(make):
    make()
    filing("F1")
    with pytest.raises(HTTPException) as e:
        pin("F1", "S1")
    assert e.value.status_code == 400 and "not one of this client's for FY 2025-26" in e.value.detail
    assert _MOCK_FILINGS["F1"]["computation_snapshot_id"] is None
    with pytest.raises(HTTPException):
        pin("F1", "no-such-snapshot")


def test_a_return_that_already_has_a_pin_keeps_it():
    snapshot("S1")
    snapshot("S2")
    filing("F1", snapshot_id="S1")
    with pytest.raises(HTTPException) as e:
        pin("F1", "S2")
    assert e.value.status_code == 409 and "already built on a saved computation" in e.value.detail
    assert _MOCK_FILINGS["F1"]["computation_snapshot_id"] == "S1"


def test_a_filing_the_caller_may_not_reach_is_not_found(monkeypatch):
    snapshot("S1")
    filing("F1")
    monkeypatch.setattr(itr, "can_access_client", lambda user, client_id: False)
    with pytest.raises(HTTPException) as e:
        pin("F1", "S1")
    assert e.value.status_code == 404


# ───────────────────────────── RE-RUN ─────────────────────────────

def test_a_filed_return_pinned_afterwards_has_its_loss_records_updated(audit):
    loss()
    snapshot("S1")
    filing("F1")                                                  # filed, and created without a computation
    first = svc.write_back_filing(USER, _MOCK_FILINGS["F1"])
    assert first["state"] == svc.NOT_WRITTEN and "Choose the saved computation on the return" in first["message"]
    pin("F1", "S1")
    out = itr.update_loss_records_from_a_filed_return("F1", USER)["data"]["brought_forward_losses"]
    assert out["state"] == svc.WRITTEN
    assert _MOCK_LOSSES["L1"]["remaining_amount_paise"] == 6 * L
    [(args, kwargs)] = audit
    assert args[:4] == (FIRM, "brought_forward_loss", "L1", "update") and kwargs["actor_id"] == "a1"


def test_running_it_again_changes_nothing_and_audits_nothing(audit):
    loss()
    snapshot("S1")
    filing("F1", snapshot_id="S1")
    itr.update_loss_records_from_a_filed_return("F1", USER)
    audit.clear()
    again = itr.update_loss_records_from_a_filed_return("F1", USER)["data"]["brought_forward_losses"]
    assert again["state"] == svc.UNCHANGED and audit == []
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 4 * L


@pytest.mark.parametrize("status", ["draft", "review", "partner_review", "ready_for_filing"])
def test_a_return_that_is_not_filed_writes_nothing(status, audit):
    loss()
    snapshot("S1")
    filing("F1", status=status, snapshot_id="S1")
    with pytest.raises(HTTPException) as e:
        itr.update_loss_records_from_a_filed_return("F1", USER)
    assert e.value.status_code == 409 and "recorded as filed" in e.value.detail
    assert _MOCK_LOSSES["L1"]["utilized_amount_paise"] == 0 and audit == []


def test_another_firms_filing_is_not_found():
    loss()
    filing("F1", snapshot_id=None)
    _MOCK_FILINGS["F1"]["firm_id"] = "F2"
    with pytest.raises(HTTPException) as e:
        itr.update_loss_records_from_a_filed_return("F1", USER)
    assert e.value.status_code == 404
