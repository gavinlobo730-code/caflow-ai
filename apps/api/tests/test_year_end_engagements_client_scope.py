"""
Client-assignment scope on the year-end ENGAGEMENTS router (year_end.py) —
the root `year_end_engagements` table. year_end_adjustments.py's own
`_assert_engagement_scope` resolver already read from this same table
correctly (fixed in an earlier phase of this sweep), but this router — the
one that actually owns creating, listing, reading and transitioning an
engagement — never checked assignment scope at all, only `firm_id`.

create_engagement took `client_id` from the body and never checked it.
list_engagements took an OPTIONAL client_id: when supplied it was never
checked, and when omitted the list was firm-wide with no per-row narrowing —
an Executive assigned to one client could list every client's engagements.
get_engagement and update_engagement_status are row-addressed by
engagement_id and resolved the row by firm_id alone; a Manager or Executive
could read or transition (write to) another staff member's client's
engagement, including locking it (irreversible — `locked` has no outgoing
transition).
"""
import pytest
from fastapi import HTTPException

import routers.year_end as ye
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else — closer to a real assignment
    boundary than refusing everything, and it catches a guard that resolves
    the wrong id. Wires all three of assert_client_access/can_access_client/
    filter_by_client to the same boundary so no endpoint can pass by using
    the "wrong" one of the three."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    def _filter(user, rows, key="client_id"):
        return [r for r in rows if r.get(key) != THEIRS]

    monkeypatch.setattr(ye, "assert_client_access", _assert)
    monkeypatch.setattr(ye, "can_access_client", _can)
    monkeypatch.setattr(ye, "filter_by_client", _filter)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_store():
    ye._MOCK_ENGAGEMENTS.clear()


def _seed(engagement_id, client_id, firm_id=FIRM, **extra):
    row = {
        "id": engagement_id, "firm_id": firm_id, "client_id": client_id,
        "financial_year": "2024-25", "status": "draft", **extra,
    }
    ye._MOCK_ENGAGEMENTS[engagement_id] = row
    return row


# ══════════════════════════════════════════════════════════════════════════
# create_engagement — client_id is on the body
# ══════════════════════════════════════════════════════════════════════════

def test_creating_an_engagement_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        ye.create_engagement(
            ye.EngagementCreateIn(client_id=THEIRS, financial_year="2024-25"),
            current_user=EXEC_USER,
        )
    assert exc.value.status_code == 404
    assert THEIRS in deny


def test_creating_an_engagement_for_an_own_client_is_allowed(deny):
    resp = ye.create_engagement(
        ye.EngagementCreateIn(client_id=MINE, financial_year="2024-25"),
        current_user=EXEC_USER,
    )
    assert resp["success"] is True
    assert resp["data"]["client_id"] == MINE
    assert MINE in deny


# ══════════════════════════════════════════════════════════════════════════
# list_engagements — optional client_id query param, else firm-wide
# ══════════════════════════════════════════════════════════════════════════

def test_listing_with_an_explicit_hidden_client_id_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        ye.list_engagements(client_id=THEIRS, financial_year=None, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_with_an_explicit_own_client_id_is_allowed(deny):
    _seed("E-MINE", MINE)
    resp = ye.list_engagements(client_id=MINE, financial_year=None, current_user=EXEC_USER)
    assert [r["id"] for r in resp["data"]] == ["E-MINE"]


def test_listing_without_a_client_id_narrows_to_assigned_clients(deny):
    _seed("E-MINE", MINE)
    _seed("E-THEIRS", THEIRS)
    resp = ye.list_engagements(client_id=None, financial_year=None, current_user=EXEC_USER)
    ids = {r["id"] for r in resp["data"]}
    assert ids == {"E-MINE"}


# ══════════════════════════════════════════════════════════════════════════
# get_engagement — row-addressed by engagement_id
# ══════════════════════════════════════════════════════════════════════════

def test_getting_a_hidden_clients_engagement_is_refused(deny):
    _seed("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc:
        ye.get_engagement("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_an_own_clients_engagement_is_allowed(deny):
    _seed("E-MINE", MINE)
    resp = ye.get_engagement("E-MINE", current_user=EXEC_USER)
    assert resp["data"]["id"] == "E-MINE"
    assert resp["data"]["checklist_completion_pct"] == 0
    assert resp["data"]["adjustment_count"] == 0


def test_getting_a_missing_engagement_matches_the_hidden_message(deny):
    """The status code AND detail text must be identical for "no such row"
    and "not your client" — otherwise the message becomes an oracle for
    which engagement ids exist even though both return 404."""
    with pytest.raises(HTTPException) as exc_missing:
        ye.get_engagement("does-not-exist", current_user=EXEC_USER)
    _seed("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc_hidden:
        ye.get_engagement("E-THEIRS", current_user=EXEC_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail


def test_getting_a_wrong_firm_engagement_is_refused_before_the_client_check(deny):
    _seed("E-OTHERFIRM", MINE, firm_id="firm-2")
    with pytest.raises(HTTPException) as exc:
        ye.get_engagement("E-OTHERFIRM", current_user=EXEC_USER)
    assert exc.value.status_code == 404
    # firm_id short-circuits before can_access_client is ever consulted.
    assert MINE not in deny


# ══════════════════════════════════════════════════════════════════════════
# update_engagement_status — row-addressed by engagement_id, a WRITE
# ══════════════════════════════════════════════════════════════════════════

def test_transitioning_a_hidden_clients_engagement_is_refused(deny):
    _seed("E-THEIRS", THEIRS, status="draft")
    with pytest.raises(HTTPException) as exc:
        ye.update_engagement_status(
            "E-THEIRS", ye.EngagementStatusIn(status="in_review"),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    assert ye._MOCK_ENGAGEMENTS["E-THEIRS"]["status"] == "draft"


def test_transitioning_an_own_clients_engagement_is_allowed(deny):
    _seed("E-MINE", MINE, status="draft")
    resp = ye.update_engagement_status(
        "E-MINE", ye.EngagementStatusIn(status="in_review"),
        current_user=MANAGER_USER,
    )
    assert resp["data"]["status"] == "in_review"


def test_transitioning_a_missing_engagement_matches_the_hidden_message(deny):
    with pytest.raises(HTTPException) as exc_missing:
        ye.update_engagement_status(
            "does-not-exist", ye.EngagementStatusIn(status="in_review"),
            current_user=MANAGER_USER,
        )
    _seed("E-THEIRS", THEIRS, status="draft")
    with pytest.raises(HTTPException) as exc_hidden:
        ye.update_engagement_status(
            "E-THEIRS", ye.EngagementStatusIn(status="in_review"),
            current_user=MANAGER_USER,
        )
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail


def test_the_client_check_runs_before_the_locked_check(deny):
    """An unassigned caller must learn nothing about the engagement's state,
    not even that it is locked — the client check has to run first."""
    _seed("E-THEIRS", THEIRS, status="locked")
    with pytest.raises(HTTPException) as exc:
        ye.update_engagement_status(
            "E-THEIRS", ye.EngagementStatusIn(status="in_review"),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "Engagement not found"


# ══════════════════════════════════════════════════════════════════════════
# Live mode (e2e FakeDB) — year_end.py imports get_supabase per call rather
# than through a _db()-style indirection, so mock-mode tests above never
# exercise this branch.
# ══════════════════════════════════════════════════════════════════════════

def _e2e_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ye])
    return db


def test_live_scope_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    with pytest.raises(HTTPException) as exc:
        ye._assert_engagement_scope(EXEC_USER, "E-THEIRS")
    assert exc.value.status_code == 404
    assert deny == [THEIRS]


def test_live_scope_returns_your_own_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "draft"})
    row = ye._assert_engagement_scope(EXEC_USER, "E-MINE")
    assert row["id"] == "E-MINE"
    assert deny == [MINE]


def test_live_scope_refuses_another_firms_engagement_before_the_client_check(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-ALIEN", "firm_id": "firm-2",
                                     "client_id": "c-x", "status": "draft"})
    with pytest.raises(HTTPException) as exc:
        ye._assert_engagement_scope(EXEC_USER, "E-ALIEN")
    assert exc.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


def test_live_missing_and_hidden_engagements_use_the_identical_message(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    with pytest.raises(HTTPException) as missing:
        ye._assert_engagement_scope(EXEC_USER, "E-NOPE")
    with pytest.raises(HTTPException) as hidden:
        ye._assert_engagement_scope(EXEC_USER, "E-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Engagement not found"


def test_live_get_engagement_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    with pytest.raises(HTTPException) as exc:
        ye.get_engagement("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_live_get_engagement_returns_your_own_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "draft"})
    resp = ye.get_engagement("E-MINE", current_user=EXEC_USER)
    assert resp["data"]["id"] == "E-MINE"
    assert resp["data"]["checklist_completion_pct"] == 0
    assert resp["data"]["adjustment_count"] == 0


def test_live_list_engagements_without_a_client_id_narrows_to_assigned_clients(deny, monkeypatch):
    """The mutant this closes: live-mode list_engagements dropped
    filter_by_client and returned every firm engagement unnarrowed when no
    client_id was supplied."""
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "draft"})
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    resp = ye.list_engagements(client_id=None, financial_year=None, current_user=EXEC_USER)
    ids = {r["id"] for r in resp["data"]}
    assert ids == {"E-MINE"}


def test_live_list_engagements_with_an_explicit_hidden_client_id_is_refused(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        ye.list_engagements(client_id=THEIRS, financial_year=None, current_user=EXEC_USER)
    assert exc.value.status_code == 404
