"""
Client-assignment scope on the year-end NOTES router (year_end_notes.py).

Every one of its 5 endpoints resolved its engagement by firm_id alone
(_get_engagement_db, live mode) or did not check its client at all
(_mock_engagement, mock mode). list_notes, get_note and lock_note were
worse still — they never resolved the engagement at all: live mode applied
only an inline firm_id filter directly on year_end_notes, and mock mode
(_MOCK_NOTES, keyed purely by engagement_id) had no tenancy check
whatsoever.

Fixed by delegating every endpoint to year_end.py's own
_assert_engagement_scope, the same pattern as the other year-end siblings
already fixed in this sweep.
"""
import pytest
from fastapi import HTTPException

import routers.year_end as ye
import routers.year_end_notes as yen
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow the rest. can_access_client is patched on
    routers.year_end (where _assert_engagement_scope actually calls it) —
    year_end_notes.py itself never imports core.authz directly."""
    seen = []

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(ye, "can_access_client", _can)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    ye._MOCK_ENGAGEMENTS.clear()
    yen._MOCK_NOTES.clear()


def _seed_engagement(engagement_id, client_id, firm_id=FIRM, **extra):
    row = {
        "id": engagement_id, "firm_id": firm_id, "client_id": client_id,
        "financial_year": "2024-25", "fy_start": "2024-04-01",
        "fy_end": "2025-03-31", "status": "draft", **extra,
    }
    ye._MOCK_ENGAGEMENTS[engagement_id] = row
    return row


# ══════════════════════════════════════════════════════════════════════════
# list_notes — never resolved the engagement at all before this fix
# ══════════════════════════════════════════════════════════════════════════

def test_listing_notes_for_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    yen._MOCK_NOTES["E-THEIRS"] = [{"id": "n1", "engagement_id": "E-THEIRS"}]
    with pytest.raises(HTTPException) as exc:
        yen.list_notes("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_notes_for_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    yen._MOCK_NOTES["E-MINE"] = [{"id": "n1", "engagement_id": "E-MINE"}]
    resp = yen.list_notes("E-MINE", current_user=EXEC_USER)
    assert len(resp["data"]) == 1


# ══════════════════════════════════════════════════════════════════════════
# generate_notes
# ══════════════════════════════════════════════════════════════════════════

def test_generating_notes_for_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc:
        yen.generate_notes("E-THEIRS", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert "E-THEIRS" not in yen._MOCK_NOTES


def test_generating_notes_for_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    resp = yen.generate_notes("E-MINE", current_user=MANAGER_USER)
    assert resp["success"] is True
    # This test is about client SCOPE, not about which notes exist, so it
    # asserts the full set rather than a bare count — a count breaks every
    # time a note is added, which says nothing about scoping.
    assert {n["note_type"] for n in resp["data"]} == yen._ALL_NOTE_TYPES


def test_generating_notes_on_a_hidden_clients_locked_engagement_is_404_not_403(deny):
    """The client check has to run before the locked check — an unassigned
    caller must learn nothing about the engagement's state."""
    _seed_engagement("E-THEIRS", THEIRS, status="locked")
    with pytest.raises(HTTPException) as exc:
        yen.generate_notes("E-THEIRS", current_user=MANAGER_USER)
    assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# get_note — never resolved the engagement at all before this fix
# ══════════════════════════════════════════════════════════════════════════

def test_getting_a_note_on_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    yen._MOCK_NOTES["E-THEIRS"] = [{"id": "n1", "engagement_id": "E-THEIRS"}]
    with pytest.raises(HTTPException) as exc:
        yen.get_note("E-THEIRS", "n1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_a_note_on_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    yen._MOCK_NOTES["E-MINE"] = [{"id": "n1", "engagement_id": "E-MINE"}]
    resp = yen.get_note("E-MINE", "n1", current_user=EXEC_USER)
    assert resp["data"]["id"] == "n1"


# ══════════════════════════════════════════════════════════════════════════
# update_note
# ══════════════════════════════════════════════════════════════════════════

def test_updating_a_note_on_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    yen._MOCK_NOTES["E-THEIRS"] = [{"id": "n1", "engagement_id": "E-THEIRS", "title": "old"}]
    with pytest.raises(HTTPException) as exc:
        yen.update_note("E-THEIRS", "n1", yen.NoteUpdateIn(title="new"),
                         current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert yen._MOCK_NOTES["E-THEIRS"][0]["title"] == "old"


def test_updating_a_note_on_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    yen._MOCK_NOTES["E-MINE"] = [{"id": "n1", "engagement_id": "E-MINE", "title": "old"}]
    resp = yen.update_note("E-MINE", "n1", yen.NoteUpdateIn(title="new"),
                            current_user=MANAGER_USER)
    assert resp["data"]["title"] == "new"


# ══════════════════════════════════════════════════════════════════════════
# lock_note — never resolved the engagement at all before this fix
# ══════════════════════════════════════════════════════════════════════════

def test_locking_a_note_on_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    yen._MOCK_NOTES["E-THEIRS"] = [{"id": "n1", "engagement_id": "E-THEIRS", "is_locked": False}]
    with pytest.raises(HTTPException) as exc:
        yen.lock_note("E-THEIRS", "n1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert yen._MOCK_NOTES["E-THEIRS"][0]["is_locked"] is False


def test_locking_a_note_on_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    yen._MOCK_NOTES["E-MINE"] = [{"id": "n1", "engagement_id": "E-MINE", "is_locked": False}]
    resp = yen.lock_note("E-MINE", "n1", current_user=MANAGER_USER)
    assert resp["data"]["is_locked"] is True


# ══════════════════════════════════════════════════════════════════════════
# Live mode (e2e FakeDB) — year_end_notes.py imports get_supabase per call
# rather than through a _db()-style indirection.
# ══════════════════════════════════════════════════════════════════════════

def _e2e_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ye, yen])
    return db


def test_live_list_notes_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    db.seed("year_end_notes", {"id": "n1", "engagement_id": "E-THEIRS", "firm_id": FIRM})
    with pytest.raises(HTTPException) as exc:
        yen.list_notes("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_live_list_notes_allows_an_own_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "draft"})
    db.seed("year_end_notes", {"id": "n1", "engagement_id": "E-MINE", "firm_id": FIRM})
    resp = yen.list_notes("E-MINE", current_user=EXEC_USER)
    assert len(resp["data"]) == 1


def test_live_get_note_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    note = db.seed("year_end_notes", {"engagement_id": "E-THEIRS", "firm_id": FIRM})
    with pytest.raises(HTTPException) as exc:
        yen.get_note("E-THEIRS", note["id"], current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_live_lock_note_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    note = db.seed("year_end_notes", {"engagement_id": "E-THEIRS", "firm_id": FIRM,
                                      "is_locked": False})
    with pytest.raises(HTTPException) as exc:
        yen.lock_note("E-THEIRS", note["id"], current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert db.rows("year_end_notes")[0]["is_locked"] is False
