"""
Phase 5.2 final sprint — Compliance Cycle (integrated).

  Engagement → Obligation → Assignment → Filing → Completion

Drives the real engagement repo + compliance_obligation_service against the
shared DB: create a fee engagement, generate its statutory obligation(s),
reassign the preparer, then walk the obligation through the canonical status
machine to Filed and Completed. Idempotent generation + cross-firm isolation.
"""
import pytest
from fastapi import HTTPException

from core.exceptions import NotFoundError
from tests.e2e_harness import FakeDB, wire_e2e


FIRM = "FIRM-A"
ACTOR = {"auth_user_id": "u1", "email": "ca@firma.test"}


def _setup(monkeypatch):
    import repositories.engagement_repository as engrepo
    import repositories.compliance_records_repository as crepo
    import services.compliance_obligation_service as cos
    db = FakeDB()
    wire_e2e(monkeypatch, db, [])                     # patch get_supabase/get_service_supabase
    monkeypatch.setattr(engrepo, "_USE_MOCK", False)
    monkeypatch.setattr(crepo, "_USE_MOCK", False)
    monkeypatch.setattr(cos, "_USE_MOCK", False)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM})
    return engrepo.engagement_repo, cos, crepo.compliance_records_repo, db


def _engagement(eng_repo):
    return eng_repo.create({
        "firm_id": FIRM, "client_id": "CLI", "service_type": "Income Tax",
        "fee_paise": 5_000_000, "billing_cycle": "annual", "start_date": "2025-04-01",
        "status": "Active", "assigned_to": "exec1", "reviewer_id": "mgr1", "partner_id": "ptr1",
    })


def test_compliance_cycle_engagement_to_completion(monkeypatch):
    eng_repo, cos, rec_repo, db = _setup(monkeypatch)

    # 1) Engagement
    eng = _engagement(eng_repo)
    assert eng["id"] and eng["service_type"] == "Income Tax"

    # 2) Obligation generated from the engagement (Income Tax ⇒ one ITR obligation).
    res = cos.generate_for_engagement(FIRM, eng, "2025-26", actor=ACTOR)
    assert res["generated"] == 1 and res["skipped"] == 0
    rec_id = res["generated_ids"][0]
    rec = rec_repo.find_by_id(rec_id)
    assert rec["engagement_id"] == eng["id"]
    assert rec["status"] == "Not Started"
    assert rec["preparer_id"] == "exec1" and rec["approver_id"] == "ptr1"   # from engagement

    # 3) Assignment — reassign the preparer.
    upd = cos.assign(FIRM, rec_id, preparer_id="exec2", actor=ACTOR)
    assert upd["preparer_id"] == "exec2"

    # 4-5) Filing → Completion through the canonical state machine.
    for nxt in ("In Progress", "Ready For Review", "Ready To File", "Filed", "Completed"):
        out = cos.transition(FIRM, rec_id, nxt, actor=ACTOR)
        assert out["status"] == nxt
    final = rec_repo.find_by_id(rec_id)
    assert final["status"] == "Completed" and final["filed_date"]


def test_compliance_cycle_generation_is_idempotent(monkeypatch):
    eng_repo, cos, rec_repo, db = _setup(monkeypatch)
    eng = _engagement(eng_repo)
    first = cos.generate_for_engagement(FIRM, eng, "2025-26", actor=ACTOR)
    second = cos.generate_for_engagement(FIRM, eng, "2025-26", actor=ACTOR)
    assert first["generated"] == 1 and second["generated"] == 0 and second["skipped"] == 1
    # Only one obligation exists for this engagement/FY.
    recs = [r for r in db.rows("compliance_records") if r.get("engagement_id") == eng["id"]]
    assert len(recs) == 1


def test_compliance_cycle_invalid_transition_rejected(monkeypatch):
    eng_repo, cos, rec_repo, db = _setup(monkeypatch)
    eng = _engagement(eng_repo)
    rec_id = cos.generate_for_engagement(FIRM, eng, "2025-26", actor=ACTOR)["generated_ids"][0]
    with pytest.raises(Exception):                    # Not Started → Filed is not allowed
        cos.transition(FIRM, rec_id, "Filed", actor=ACTOR)
    assert rec_repo.find_by_id(rec_id)["status"] == "Not Started"


# --------------------------------------------------------------------------- #
#  Negative tenant-isolation legs
# --------------------------------------------------------------------------- #
def test_compliance_cycle_foreign_firm_cannot_assign_or_transition(monkeypatch):
    eng_repo, cos, rec_repo, db = _setup(monkeypatch)
    eng = _engagement(eng_repo)
    rec_id = cos.generate_for_engagement(FIRM, eng, "2025-26", actor=ACTOR)["generated_ids"][0]

    # assign() raises HTTPException(404); transition() delegates to the domain
    # service which raises NotFoundError (the router maps it to 404). Both deny
    # cross-firm access with no mutation.
    with pytest.raises(HTTPException) as e1:
        cos.assign("FIRM-B", rec_id, preparer_id="x", actor=ACTOR)
    assert e1.value.status_code == 404
    with pytest.raises(NotFoundError):
        cos.transition("FIRM-B", rec_id, "In Progress", actor=ACTOR)
    assert rec_repo.find_by_id(rec_id)["status"] == "Not Started"   # untouched
