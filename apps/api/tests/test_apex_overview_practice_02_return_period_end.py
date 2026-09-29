"""
apex-overview-practice-02: a RETURN cannot be marked Filed before its own
period has ended.

`domain/compliance_record_service.update_record` (and `mark_filed`, which
fast-forwards through it, and both router entry points that call them) used
to permit a transition to status "Filed" and stamp `filed_date=ist_today()`
with no check that the obligation's own `period_end` had passed — so a CA
(or a test script) could mark a GSTR-3B "Filed" for a period that had not
even ended yet.

`services.compliance_obligation_service.RETURN_OBLIGATION_TYPES` names which
obligation types this reaches. PMT-06 and the other PAYMENT types are the
negative control here: §208 and Rule 30(2) both charge those mid-period by
design, and marking one Filed before its own "period" ends (which for
PMT-06/ADVANCE_TAX *is* the due date — see `_advance_tax_obligations`) must
stay legal.
"""
from datetime import timedelta

import pytest
from fastapi import HTTPException

from core.exceptions import ValidationError
from core.ist_clock import ist_today
from domain.compliance_record_service import compliance_record_service
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo

FIRM = "FIRM-RETURN-PERIOD-TEST"
CLIENT = "CLIENT-RETURN-PERIOD-TEST"
ACTOR = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firm.test"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    MOCK_COMPLIANCE_RECORDS.clear()
    # Both real writers of audit_log/task_timeline are best-effort in
    # _audit_transition, but silence them anyway so an accidental import-time
    # side effect elsewhere in the suite cannot turn a real assertion failure
    # into a confusing one about logging.
    import services.audit_service as au
    import services.timeline_service as ts
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    yield
    MOCK_COMPLIANCE_RECORDS.clear()


def _make(obligation_type, period_end, status="Ready To File", compliance_type="GST"):
    return compliance_records_repo.create({
        "firm_id": FIRM, "client_id": CLIENT, "compliance_type": compliance_type,
        "obligation_type": obligation_type, "period_start": "2026-04-01",
        "period_end": period_end, "due_date": "2026-05-20", "status": status,
    })


# ── The refusal itself ───────────────────────────────────────────────────────

def test_a_return_cannot_be_filed_before_its_period_ends():
    future_end = (ist_today() + timedelta(days=5)).isoformat()
    rec = _make("GSTR3B", future_end)
    with pytest.raises(ValidationError):
        compliance_record_service.update_record(rec["id"], {"status": "Filed"}, firm_id=FIRM, actor=ACTOR)
    # And the record was NOT moved — the refusal happened before the write.
    reloaded = compliance_records_repo.find_by_id(rec["id"])
    assert reloaded["status"] == "Ready To File"
    assert not reloaded.get("filed_date")


@pytest.mark.parametrize("obligation_type", ["GSTR1", "GSTR3B", "GSTR9", "GSTR9C",
                                              "TDS24Q", "TDS26Q", "TDS27Q", "TDS27EQ",
                                              "ITR", "MCA_AOC4", "MCA_MGT7"])
def test_every_return_type_is_refused_when_its_period_has_not_ended(obligation_type):
    future_end = (ist_today() + timedelta(days=1)).isoformat()
    rec = _make(obligation_type, future_end)
    with pytest.raises(ValidationError) as ei:
        compliance_record_service.update_record(rec["id"], {"status": "Filed"}, firm_id=FIRM, actor=ACTOR)
    assert obligation_type in str(ei.value)


# ── NEGATIVE CONTROL 1: the identical obligation, once its period has ended ──

def test_the_same_return_type_files_fine_once_its_period_has_ended():
    past_end = (ist_today() - timedelta(days=1)).isoformat()
    rec = _make("GSTR3B", past_end)
    updated = compliance_record_service.update_record(rec["id"], {"status": "Filed"}, firm_id=FIRM, actor=ACTOR)
    assert updated["status"] == "Filed"
    assert updated["filed_date"]


def test_a_return_due_today_files_fine():
    # period_end == today is NOT "the period hasn't ended" — the boundary is
    # `ist_today() < period_end`, not `<=`.
    today = ist_today().isoformat()
    rec = _make("GSTR9", today)
    updated = compliance_record_service.update_record(rec["id"], {"status": "Filed"}, firm_id=FIRM, actor=ACTOR)
    assert updated["status"] == "Filed"


# ── NEGATIVE CONTROL 2: PAYMENT types are never gated on this at all ────────

@pytest.mark.parametrize("obligation_type", ["PMT06", "TDS_NON_SALARY_DEPOSIT", "ADVANCE_TAX"])
def test_payment_types_are_never_refused_however_far_off_their_period_end_is(obligation_type):
    far_future_end = (ist_today() + timedelta(days=365)).isoformat()
    rec = _make(obligation_type, far_future_end, compliance_type="Income Tax")
    updated = compliance_record_service.update_record(rec["id"], {"status": "Filed"}, firm_id=FIRM, actor=ACTOR)
    assert updated["status"] == "Filed"


# ── NEGATIVE CONTROL 3: a manual record (no obligation_type) is untouched ───

def test_a_manual_record_with_no_obligation_type_is_never_gated():
    future_end = (ist_today() + timedelta(days=365)).isoformat()
    rec = compliance_records_repo.create({
        "firm_id": FIRM, "client_id": CLIENT, "compliance_type": "GSTR-3B",
        "period_start": "2026-04-01", "period_end": future_end,
        "due_date": "2026-05-20", "status": "Ready To File",
    })
    assert "obligation_type" not in rec or rec.get("obligation_type") is None
    updated = compliance_record_service.update_record(rec["id"], {"status": "Filed"}, firm_id=FIRM, actor=ACTOR)
    assert updated["status"] == "Filed"


# ── mark_filed fast-forwards through update_record, so it inherits the check ─

def test_mark_filed_is_refused_for_a_return_whose_period_has_not_ended():
    future_end = (ist_today() + timedelta(days=10)).isoformat()
    rec = _make("GSTR1", future_end, status="Not Started")
    with pytest.raises(ValidationError):
        compliance_record_service.mark_filed(rec["id"], firm_id=FIRM, actor=ACTOR)
    reloaded = compliance_records_repo.find_by_id(rec["id"])
    # The fast-forward stopped at the last step it could legally take —
    # Ready To File — rather than leaving the record wherever it started.
    assert reloaded["status"] != "Filed"


def test_mark_filed_still_works_for_a_return_whose_period_has_ended():
    past_end = (ist_today() - timedelta(days=10)).isoformat()
    rec = _make("GSTR3B", past_end, status="Not Started")
    updated = compliance_record_service.mark_filed(rec["id"], firm_id=FIRM, actor=ACTOR)
    assert updated["status"] == "Filed"


# ── Router entry points ──────────────────────────────────────────────────────

def test_compliance_records_router_surfaces_the_refusal_as_422():
    import routers.compliance_records as cr

    future_end = (ist_today() + timedelta(days=5)).isoformat()
    rec = _make("GSTR3B", future_end)
    with pytest.raises(HTTPException) as ei:
        cr.update_compliance_record(
            rec["id"], cr.ComplianceRecordUpdateIn(status="Filed"), ACTOR)
    assert ei.value.status_code == 422


def test_compliance_ops_transition_router_surfaces_the_refusal_as_422():
    import routers.compliance_ops as co

    future_end = (ist_today() + timedelta(days=5)).isoformat()
    rec = _make("GSTR3B", future_end)
    with pytest.raises(HTTPException) as ei:
        co.transition_obligation(rec["id"], co.TransitionBody(status="Filed"), ACTOR)
    assert ei.value.status_code == 422


def test_compliance_ops_mark_filed_router_surfaces_the_refusal_as_422():
    import routers.compliance_ops as co

    future_end = (ist_today() + timedelta(days=5)).isoformat()
    rec = _make("GSTR1", future_end, status="Not Started")
    with pytest.raises(HTTPException) as ei:
        co.mark_filed_obligation(rec["id"], co.MarkFiledBody(), ACTOR)
    assert ei.value.status_code == 422


def test_the_vocabulary_lives_where_the_obligation_type_vocabulary_already_lives():
    """Pins the constant's location, so a future move is deliberate rather
    than a second, drifting copy appearing beside it (the `public.
    tds_section_limits` shape CLAUDE.md warns about)."""
    from services.compliance_obligation_service import RETURN_OBLIGATION_TYPES
    assert "GSTR3B" in RETURN_OBLIGATION_TYPES
    assert "PMT06" not in RETURN_OBLIGATION_TYPES
    assert "ADVANCE_TAX" not in RETURN_OBLIGATION_TYPES
