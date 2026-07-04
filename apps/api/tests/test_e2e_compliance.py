"""
Phase 5.2 WS-1 — Compliance records E2E.

Drives the real router endpoints through the compliance lifecycle against the
shared DB (repository routed to the FakeDB):

  create → list → get → status transitions (Not Started → In Progress →
  Ready For Review → Ready To File → Filed)

Asserts the state machine (VALID_TRANSITIONS) is enforced, Filed stamps a
filed_date, risk scoring is integer, and the H2/F2 tenant isolation holds
(a foreign-firm caller gets 404 on get/update).
"""
import pytest
from fastapi import HTTPException

from routers.compliance_records import ComplianceRecordIn, ComplianceRecordUpdateIn
from tests.e2e_harness import FakeDB, wire_e2e


FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
OTHER = {"firm_id": "FIRM-B", "auth_user_id": "u2", "email": "ca@firmb.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.compliance_records as cr
    import repositories.compliance_records_repository as crepo
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cr])
    monkeypatch.setattr(crepo, "_USE_MOCK", False)       # route repo to the shared DB
    return cr, db


def _create(cr, status="Not Started", due="2026-12-20", ctype="GSTR-3B"):
    return cr.create_compliance_record(ComplianceRecordIn(
        client_id="CLI", compliance_type=ctype, due_date=due, status=status,
    ), CALLER)["data"]


def test_compliance_lifecycle_transitions(monkeypatch):
    cr, db = _setup(monkeypatch)

    rec = _create(cr)
    rid = rec["id"]
    assert rec["status"] == "Not Started"
    assert isinstance(rec["risk_score"], int)

    # Appears in the list and get. (status/compliance_type passed explicitly as
    # None — calling the endpoint directly bypasses FastAPI's Query() default
    # resolution, so the unset Query objects would otherwise become filters.)
    listed = cr.list_compliance_records(client_id="CLI", status=None,
                                        compliance_type=None, current_user=CALLER)["data"]
    assert any(r["id"] == rid for r in listed)
    assert cr.get_compliance_record(rid, CALLER)["data"]["id"] == rid

    # Walk the valid state machine through to Filed.
    for nxt in ("In Progress", "Ready For Review", "Ready To File", "Filed"):
        resp = cr.update_compliance_record(rid, ComplianceRecordUpdateIn(status=nxt), CALLER)
        assert resp["success"] is True, resp
        assert resp["data"]["status"] == nxt

    filed = cr.get_compliance_record(rid, CALLER)["data"]
    assert filed["status"] == "Filed"
    assert filed["filed_date"]                       # stamped on Filed
    assert filed["risk_score"] == 0                  # Filed ⇒ no risk


def test_compliance_invalid_transition_rejected(monkeypatch):
    cr, db = _setup(monkeypatch)
    rid = _create(cr)["id"]
    # Not Started → Filed is not allowed (must progress through the chain).
    with pytest.raises(HTTPException) as ei:
        cr.update_compliance_record(rid, ComplianceRecordUpdateIn(status="Filed"), CALLER)
    assert ei.value.status_code == 422
    assert cr.get_compliance_record(rid, CALLER)["data"]["status"] == "Not Started"


def test_compliance_create_sets_firm_from_user_not_body(monkeypatch):
    cr, db = _setup(monkeypatch)
    rec = _create(cr)
    # firm_id is taken from the authenticated user, never the request.
    stored = db.table("compliance_records").select("*").eq("id", rec["id"]).execute().data[0]
    assert stored["firm_id"] == FIRM


# --------------------------------------------------------------------------- #
#  Negative tenant-isolation legs
# --------------------------------------------------------------------------- #
def test_compliance_foreign_firm_cannot_get(monkeypatch):
    cr, db = _setup(monkeypatch)
    rid = _create(cr)["id"]
    with pytest.raises(HTTPException) as ei:
        cr.get_compliance_record(rid, OTHER)
    assert ei.value.status_code == 404


def test_compliance_foreign_firm_cannot_update(monkeypatch):
    cr, db = _setup(monkeypatch)
    rid = _create(cr)["id"]
    with pytest.raises(HTTPException) as ei:
        cr.update_compliance_record(rid, ComplianceRecordUpdateIn(status="In Progress"), OTHER)
    assert ei.value.status_code == 404
    # unchanged
    assert cr.get_compliance_record(rid, CALLER)["data"]["status"] == "Not Started"


# --------------------------------------------------------------------------- #
#  Manual-create dedup guard (compliance data-model consolidation gap-close)
# --------------------------------------------------------------------------- #
def test_compliance_manual_create_rejects_duplicate_period(monkeypatch):
    cr, db = _setup(monkeypatch)
    cr.create_compliance_record(ComplianceRecordIn(
        client_id="CLI", compliance_type="GST", due_date="2026-07-11",
        period_start="2026-06-01", period_end="2026-06-30"), CALLER)
    with pytest.raises(HTTPException) as ei:
        cr.create_compliance_record(ComplianceRecordIn(
            client_id="CLI", compliance_type="GST", due_date="2026-07-20",
            period_start="2026-06-01", period_end="2026-06-30"), CALLER)
    assert ei.value.status_code == 422


def test_compliance_manual_create_allows_distinct_periods(monkeypatch):
    cr, db = _setup(monkeypatch)
    r1 = cr.create_compliance_record(ComplianceRecordIn(
        client_id="CLI", compliance_type="GST", due_date="2026-07-11",
        period_start="2026-06-01"), CALLER)["data"]
    r2 = cr.create_compliance_record(ComplianceRecordIn(
        client_id="CLI", compliance_type="GST", due_date="2026-08-11",
        period_start="2026-07-01"), CALLER)["data"]
    assert r1["id"] != r2["id"]


def test_compliance_manual_create_without_period_never_dedups(monkeypatch):
    """No period supplied ⇒ nothing to dedup against; both creates succeed
    (matches the pre-existing behaviour for callers not yet passing periods)."""
    cr, db = _setup(monkeypatch)
    r1 = _create(cr)
    r2 = _create(cr)
    assert r1["id"] != r2["id"]
