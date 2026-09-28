"""
sweep-accounting-hub-1-03 / sweep-tds-mca-11 — GET /api/health/clients/{id}
404'd on every single client-workspace page load for a client that has never
been calculated: ClientTopBar (apps/web/components/shell/ClientTopBar.tsx)
calls getLatestHealthScore on mount for EVERY client route, and
get_client_health raised 404 "Health score not found — run /calculate first"
whenever there was no health_scores row yet — which is every brand-new
client, and permanently true of the internal practice client, which
Guardrail G2 (calculate_score, recalculate_all) refuses to score at all. The
frontend caught the exception and rendered nothing, so nothing broke
visually, but the browser logged a failed request on every navigation.

"No score calculated yet" is not "not found": assert_client_access already
404s a client this caller cannot see (or that does not exist) before the
health_scores lookup ever runs, so a client that legitimately has no row
answers 200 with data: null instead.
"""
import pytest
from fastapi import HTTPException

import routers.health as health
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
PARTNER = {"firm_id": FIRM, "id": "ptr-a", "auth_user_id": "ptr-a", "role": "Partner"}


def _wire(monkeypatch, db: FakeDB):
    monkeypatch.setattr(health, "_db", lambda: db)


def test_a_client_with_no_row_yet_answers_200_with_null(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    # No health_scores row seeded for this client at all.

    resp = health.get_client_health("never-calculated", PARTNER)
    assert resp["success"] is True
    assert resp["data"] is None


def test_the_internal_practice_client_answers_200_with_null_too(monkeypatch):
    """Guardrail G2 (calculate_score, recalculate_all) never scores the
    internal practice client, so it can never have a health_scores row — this
    was the client that 404'd on literally every visit."""
    db = FakeDB()
    _wire(monkeypatch, db)
    db.seed("clients", {"id": "practice-books", "firm_id": FIRM,
                        "client_name": "Practice books", "is_internal": True})

    resp = health.get_client_health("practice-books", PARTNER)
    assert resp["success"] is True
    assert resp["data"] is None


def test_a_client_with_a_real_score_is_unaffected(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    db.seed("health_scores", {"client_id": "scored", "firm_id": FIRM, "overall_score": 80})

    resp = health.get_client_health("scored", PARTNER)
    assert resp["success"] is True
    assert resp["data"]["overall_score"] == 80


def test_a_client_the_caller_cannot_see_still_404s(monkeypatch):
    """The 404 that must survive is existence/access, decided by
    assert_client_access before the health_scores lookup ever runs — never
    "no score calculated yet"."""
    db = FakeDB()
    _wire(monkeypatch, db)
    monkeypatch.setattr(health, "assert_client_access",
                        lambda user, client_id: (_ for _ in ()).throw(
                            HTTPException(status_code=404, detail="Not found")))

    with pytest.raises(HTTPException) as ei:
        health.get_client_health("someone-elses-client", PARTNER)
    assert ei.value.status_code == 404
