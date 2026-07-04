"""
R3.15 — routers/health.py access-control hardening.

Found while scoping the compliance data-model consolidation's health-score
gap (adjacent to R3.14's schema-drift fix, same file): every one of
routers/health.py's read endpoints was missing the assignment-scoping
(M2/M5, filter_by_client/assert_client_access) pattern already applied
consistently in compliance_ops.py/compliance_records.py — a non-firm-wide
role (Executive, Reviewer) could see health data for ANY client in the
firm, not just their assigned ones. Separately, and more severely,
get_client_health()/get_dimension_detail() accepted a caller-supplied
`firm_id` query parameter that silently overrode the authenticated caller's
own firm scope — any authenticated user could read another FIRM's client
health data by passing `?firm_id=<other-firm-id>`, a genuine cross-tenant
leak (not just cross-client-within-firm), independent of the schema-drift
bug R3.14 fixed in the same file.

Covers, against the real router functions (not the mocked-out unit style):
  * the removed firm_id query-param override (cross-tenant leak)
  * assignment-scope enforcement on every read endpoint
  * write endpoints remain firm-scoped-only (unchanged), matching the
    established compliance_records.py/compliance_ops.py precedent
"""
import inspect

import pytest
from fastapi import HTTPException

import core.authz as authz
import routers.health as health
from tests.e2e_harness import FakeDB


FIRM_A = "FIRM-A"
FIRM_B = "FIRM-B"
PARTNER_A = {"firm_id": FIRM_A, "id": "ptr-a", "auth_user_id": "ptr-a", "role": "Partner"}
EXEC_A = {"firm_id": FIRM_A, "id": "exec-a", "auth_user_id": "exec-a", "role": "Executive"}


def _wire(monkeypatch, db: FakeDB):
    monkeypatch.setattr(health, "_db", lambda: db)
    monkeypatch.setattr(health.timeline_service, "log", lambda *a, **k: None)


def _scope_exec_to(monkeypatch, allowed: set[str]):
    """Simulates real (non-mock) assignment scoping the way
    test_compliance_engagement.py does — Partner (firm-wide) sees
    everything; Executive is restricted to `allowed`."""
    monkeypatch.setattr(
        authz, "effective_client_ids",
        lambda u: None if u.get("role") == "Partner" else set(allowed))
    monkeypatch.setattr(
        authz, "can_access_client",
        lambda u, cid: True if u.get("role") == "Partner" else (cid in allowed))


# --------------------------------------------------------------------------- #
#  The removed firm_id query-param override (cross-tenant leak)
# --------------------------------------------------------------------------- #
def test_get_client_health_signature_no_longer_accepts_a_firm_id_override():
    """Positive proof the attack surface is gone: the parameter doesn't
    exist at all, so there is no query string a caller can send that
    changes which firm's data gets queried."""
    assert "firm_id" not in inspect.signature(health.get_client_health).parameters
    assert "firm_id" not in inspect.signature(health.get_dimension_detail).parameters


def test_get_client_health_always_scoped_to_the_callers_own_firm(monkeypatch):
    """Even with a client_id that happens to collide across firms, a caller
    only ever sees their OWN firm's row — the scope comes from current_user,
    not anything caller-suppliable."""
    db = FakeDB()
    _wire(monkeypatch, db)
    db.seed("health_scores", {"client_id": "SHARED", "firm_id": FIRM_A, "overall_score": 90})
    db.seed("health_scores", {"client_id": "SHARED", "firm_id": FIRM_B, "overall_score": 10})

    resp = health.get_client_health("SHARED", PARTNER_A)
    assert resp["data"]["overall_score"] == 90                 # Firm A's row, never Firm B's


# --------------------------------------------------------------------------- #
#  Assignment-scope enforcement (M2/M5 pattern) on every read endpoint
# --------------------------------------------------------------------------- #
def test_get_client_health_404s_for_unassigned_client(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    _scope_exec_to(monkeypatch, {"CL-A"})
    db.seed("health_scores", {"client_id": "CL-B", "firm_id": FIRM_A, "overall_score": 80})

    with pytest.raises(HTTPException) as ei:
        health.get_client_health("CL-B", EXEC_A)
    assert ei.value.status_code == 404


def test_get_client_health_allowed_for_assigned_client(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    _scope_exec_to(monkeypatch, {"CL-A"})
    db.seed("health_scores", {"client_id": "CL-A", "firm_id": FIRM_A, "overall_score": 80})

    resp = health.get_client_health("CL-A", EXEC_A)
    assert resp["data"]["overall_score"] == 80


def test_get_dimension_detail_404s_for_unassigned_client(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    _scope_exec_to(monkeypatch, {"CL-A"})

    with pytest.raises(HTTPException) as ei:
        health.get_dimension_detail("CL-B", dimension="compliance_health", current_user=EXEC_A)
    assert ei.value.status_code == 404


def test_get_score_404s_for_unassigned_client(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    _scope_exec_to(monkeypatch, {"CL-A"})
    db.seed("health_scores", {"client_id": "CL-B", "firm_id": FIRM_A, "overall_score": 80})

    with pytest.raises(HTTPException) as ei:
        health.get_score("CL-B", EXEC_A)
    assert ei.value.status_code == 404


def test_get_score_history_404s_for_unassigned_client(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    _scope_exec_to(monkeypatch, {"CL-A"})

    with pytest.raises(HTTPException) as ei:
        health.get_score_history("CL-B", limit=20, current_user=EXEC_A)
    assert ei.value.status_code == 404


def test_list_overrides_404s_for_unassigned_client(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    _scope_exec_to(monkeypatch, {"CL-A"})

    with pytest.raises(HTTPException) as ei:
        health.list_overrides(client_id="CL-B", current_user=EXEC_A)
    assert ei.value.status_code == 404


def test_list_scores_filters_to_assigned_clients_only(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    _scope_exec_to(monkeypatch, {"CL-A"})
    db.seed("health_scores", {"client_id": "CL-A", "firm_id": FIRM_A, "overall_score": 80})
    db.seed("health_scores", {"client_id": "CL-B", "firm_id": FIRM_A, "overall_score": 40})

    resp = health.list_scores(is_critical=None, is_at_risk=None, current_user=EXEC_A)
    assert {r["client_id"] for r in resp["data"]} == {"CL-A"}

    resp_partner = health.list_scores(is_critical=None, is_at_risk=None, current_user=PARTNER_A)
    assert {r["client_id"] for r in resp_partner["data"]} == {"CL-A", "CL-B"}


def test_list_alerts_filters_to_assigned_clients_only(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    _scope_exec_to(monkeypatch, {"CL-A"})
    db.seed("health_alerts", {"client_id": "CL-A", "firm_id": FIRM_A, "is_resolved": False, "severity": "critical"})
    db.seed("health_alerts", {"client_id": "CL-B", "firm_id": FIRM_A, "is_resolved": False, "severity": "critical"})

    resp = health.list_alerts(client_id=None, severity=None, current_user=EXEC_A)
    assert {a["client_id"] for a in resp["data"]} == {"CL-A"}


def test_list_alerts_with_explicit_unassigned_client_id_404s(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    _scope_exec_to(monkeypatch, {"CL-A"})

    with pytest.raises(HTTPException) as ei:
        health.list_alerts(client_id="CL-B", severity=None, current_user=EXEC_A)
    assert ei.value.status_code == 404


# --------------------------------------------------------------------------- #
#  Write endpoints remain firm-scoped only (unchanged) — matches the
#  established compliance_records.py/compliance_ops.py precedent, where
#  reads are assignment-scoped but writes are not.
# --------------------------------------------------------------------------- #
def test_calculate_score_still_works_for_a_non_assigned_executive(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    _scope_exec_to(monkeypatch, {"CL-A"})       # exec is NOT assigned to CL-B
    db.seed("clients", {"id": "CL-B", "firm_id": FIRM_A, "client_name": "B Co", "is_internal": False})
    monkeypatch.setattr(health, "_calculate_scores_db",
                        lambda db, cid, fid: {"overall_score": 90, "grade": "Healthy",
                                              "health_grade": "Healthy", "trend": "+0",
                                              "hard_override": None, "hard_override_reason": None,
                                              "is_critical": False, "is_at_risk": False})
    resp = health.calculate_score("CL-B", EXEC_A)
    assert resp["success"] is True
