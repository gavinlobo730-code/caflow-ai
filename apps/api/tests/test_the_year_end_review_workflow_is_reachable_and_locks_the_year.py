"""
R3.8 — routers/year_end_reviews.py's review workflow is now actually
reachable from the frontend, and completing it locks the financial year.

Root cause found during the fresh Tier 3 re-scope: apps/web/lib/api/
yearEnd.ts called `/api/year-end/engagements/{id}/review/...` (singular
"review", and "submit" instead of "submit-for-review") while the router's
real routes were `/api/year-end/{id}/reviews/...` (no "engagements/"
segment at all, unlike every other year-end sub-resource router). Neither
side matched the other -- the year-end review workflow was completely
non-functional in production. Fixed by adding the missing "/engagements/"
segment to the router (matching every other year-end router's convention)
and correcting the frontend's paths to match.

Also: the FY-lock side effect that only routers/year_end.py's (unreachable)
generic PATCH endpoint had is now shared via
services/year_end_workflow_service.py and wired into final_approve too --
the transition users can actually reach.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.e2e_harness import FakeDB
from core.auth import get_current_user

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p1@f1.test", "auth_user_id": "auth-partner"}
MANAGER = {"id": "u2", "firm_id": "F1", "role": "Manager", "email": "m1@f1.test", "auth_user_id": "auth-manager"}


def _client_for(app: FastAPI, user: dict) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def yer_app(monkeypatch):
    import routers.year_end_reviews as mod
    import routers.year_end as year_end_mod
    db = FakeDB()
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    monkeypatch.setattr(mod, "log_event", lambda *a, **k: None)
    # _assert_engagement_scope lives in routers.year_end and is called by
    # name from routers.year_end_reviews (client-assignment scope fix) — its
    # own _USE_MOCK flag governs which branch it takes, independently of
    # year_end_reviews's, so it has to be flipped here too or the resolver
    # reads the (empty in this test) in-memory mock store instead of FakeDB.
    monkeypatch.setattr(year_end_mod, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    app = FastAPI()
    app.include_router(mod.router)
    return app, db


def _seed_engagement(db, **overrides) -> dict:
    row = {
        "id": "ENG1", "firm_id": "F1", "client_id": "C1",
        "financial_year": "2024-25", "status": "draft",
    }
    row.update(overrides)
    return db.seed("year_end_engagements", row)


class TestPathsAreReachable:
    """The actual bug: the frontend's paths must resolve to real endpoints."""

    def test_submit_for_review_is_reachable_at_the_engagements_path(self, yer_app):
        app, db = yer_app
        _seed_engagement(db)
        r = _client_for(app, MANAGER).post("/year-end/engagements/ENG1/reviews/submit-for-review", json={})
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "in_review"

    def test_approve_is_reachable_at_the_engagements_path(self, yer_app):
        app, db = yer_app
        _seed_engagement(db, status="in_review")
        r = _client_for(app, MANAGER).post("/year-end/engagements/ENG1/reviews/approve", json={})
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "approved"

    def test_final_approve_is_reachable_at_the_engagements_path(self, yer_app):
        app, db = yer_app
        _seed_engagement(db, status="approved")
        db.seed("firms", {"id": "F1", "locked_financial_years": [], "lock_pin": None})
        r = _client_for(app, PARTNER).post("/year-end/engagements/ENG1/reviews/final-approve", json={})
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "locked"


class TestFinalApproveLocksTheYear:
    """The FY-lock behaviour only the unreachable year_end.py endpoint had."""

    def test_final_approve_locks_the_financial_year_for_that_client(self, yer_app):
        """Final approval closes the engagement's own client's year.

        It used to lock firms.locked_financial_years — practice-wide, so every
        other client's posting in that year stopped too, behind the firm lock
        PIN. See migration 289."""
        app, db = yer_app
        _seed_engagement(db, status="approved")
        db.seed("firms", {"id": "F1", "locked_financial_years": [], "lock_pin": None})
        r = _client_for(app, PARTNER).post("/year-end/engagements/ENG1/reviews/final-approve", json={})
        assert r.status_code == 200

        locks = [row for row in db.rows("client_year_locks")
                 if row["firm_id"] == "F1" and row["financial_year"] == "2024-25"]
        assert len(locks) == 1
        assert locks[0]["client_id"] == "C1"

        firm = next(row for row in db.rows("firms") if row["id"] == "F1")
        assert "2024-25" not in (firm.get("locked_financial_years") or []), (
            "one client's year-end closed the whole firm's year"
        )


class TestReviewState:
    """The new GET endpoint apps/web/.../review/_page.tsx actually needs."""

    def test_fresh_draft_has_no_completed_steps_and_empty_history(self, yer_app):
        app, db = yer_app
        _seed_engagement(db)
        r = _client_for(app, MANAGER).get("/year-end/engagements/ENG1/reviews")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["history"] == []
        assert all(s["completed_at"] is None for s in data["steps"])

    def test_after_submit_the_prepared_step_is_completed_with_resolved_actor(self, yer_app):
        app, db = yer_app
        _seed_engagement(db)
        # Seeded with the INTERNAL id, matching MANAGER["id"]: the transitions
        # write public.users.id (it is what the FK points at) and the read
        # resolves by it. Seeding only auth_user_id, as this used to, matched
        # a lookup that was consistent with a write that could never succeed.
        db.seed("users", {"id": MANAGER["id"], "auth_user_id": "auth-manager",
                          "full_name": "Manager One", "role": "Manager"})
        _client_for(app, MANAGER).post("/year-end/engagements/ENG1/reviews/submit-for-review",
                                        json={"comment": "ready for review"})

        r = _client_for(app, MANAGER).get("/year-end/engagements/ENG1/reviews")
        data = r.json()["data"]
        prepared = next(s for s in data["steps"] if s["step"] == "prepared")
        assert prepared["completed_at"] is not None
        assert prepared["user_name"] == "Manager One"
        assert prepared["user_role"] == "Manager"

        assert len(data["history"]) == 1
        entry = data["history"][0]
        assert entry["action"] == "submitted_for_review"
        assert entry["performed_by"] == "Manager One"
        assert entry["comment"] == "ready for review"
        assert (entry["from_status"], entry["to_status"]) == ("draft", "in_review")

    def test_history_is_most_recent_first(self, yer_app):
        app, db = yer_app
        _seed_engagement(db)
        _client_for(app, MANAGER).post("/year-end/engagements/ENG1/reviews/submit-for-review", json={})
        _client_for(app, MANAGER).post("/year-end/engagements/ENG1/reviews/approve", json={})

        r = _client_for(app, MANAGER).get("/year-end/engagements/ENG1/reviews")
        history = r.json()["data"]["history"]
        assert len(history) == 2
        assert history[0]["action"] == "approved"
        assert history[1]["action"] == "submitted_for_review"
