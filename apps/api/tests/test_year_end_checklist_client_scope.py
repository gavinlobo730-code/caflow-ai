"""
Client-assignment scope on the year-end CHECKLIST router
(year_end_checklist.py).

test_year_end_tenancy.py already covers the FIRM boundary (a cross-firm
caller is refused). This covers the layer above it: a same-firm caller not
ASSIGNED to the engagement's client. Before this fix, list_checklist and
update_checklist_item resolved the engagement by firm_id alone in live mode
(_fetch_engagement_db, now removed) and did not check it AT ALL in mock
mode (_MOCK_CHECKLIST was keyed purely by engagement_id, no tenancy check
whatsoever) — a Manager or Executive could read or complete another staff
member's client's year-end checklist.

Fixed by delegating to year_end.py's own _assert_engagement_scope, same
pattern as year_end_reviews.py.
"""
import pytest
from fastapi import HTTPException

import routers.year_end as ye
import routers.year_end_checklist as yec
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow the rest. can_access_client is patched on
    routers.year_end (where _assert_engagement_scope actually calls it) —
    year_end_checklist.py itself never imports core.authz directly."""
    seen = []

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(ye, "can_access_client", _can)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    ye._MOCK_ENGAGEMENTS.clear()
    yec._MOCK_CHECKLIST.clear()


def _seed_engagement(engagement_id, client_id, firm_id=FIRM, **extra):
    row = {
        "id": engagement_id, "firm_id": firm_id, "client_id": client_id,
        "financial_year": "2024-25", "status": "draft", **extra,
    }
    ye._MOCK_ENGAGEMENTS[engagement_id] = row
    return row


# ══════════════════════════════════════════════════════════════════════════
# list_checklist — mock mode
# ══════════════════════════════════════════════════════════════════════════

def test_listing_a_hidden_clients_checklist_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc:
        yec.list_checklist("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert "E-THEIRS" not in yec._MOCK_CHECKLIST  # never auto-initialized


def test_listing_an_own_clients_checklist_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    resp = yec.list_checklist("E-MINE", current_user=EXEC_USER)
    assert len(resp["data"]) == 12


def test_listing_a_missing_engagements_checklist_matches_the_hidden_message(deny):
    with pytest.raises(HTTPException) as exc_missing:
        yec.list_checklist("E-NOPE", current_user=EXEC_USER)
    _seed_engagement("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc_hidden:
        yec.list_checklist("E-THEIRS", current_user=EXEC_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail


# ══════════════════════════════════════════════════════════════════════════
# update_checklist_item — mock mode
# ══════════════════════════════════════════════════════════════════════════

def test_updating_a_hidden_clients_checklist_item_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    yec._MOCK_CHECKLIST["E-THEIRS"] = yec._init_checklist_items("E-THEIRS")
    item_id = yec._MOCK_CHECKLIST["E-THEIRS"][0]["id"]
    with pytest.raises(HTTPException) as exc:
        yec.update_checklist_item(
            "E-THEIRS", item_id, yec.ChecklistItemUpdateIn(status="complete"),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    assert yec._MOCK_CHECKLIST["E-THEIRS"][0]["status"] == "pending"


def test_updating_an_own_clients_checklist_item_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    yec._MOCK_CHECKLIST["E-MINE"] = yec._init_checklist_items("E-MINE")
    item_id = yec._MOCK_CHECKLIST["E-MINE"][0]["id"]
    resp = yec.update_checklist_item(
        "E-MINE", item_id, yec.ChecklistItemUpdateIn(status="complete"),
        current_user=MANAGER_USER,
    )
    assert resp["data"]["status"] == "complete"


# ══════════════════════════════════════════════════════════════════════════
# Live mode (e2e FakeDB) — year_end_checklist.py imports get_supabase per
# call rather than through a _db()-style indirection.
# ══════════════════════════════════════════════════════════════════════════

def _e2e_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ye, yec])
    return db


def test_live_list_checklist_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    with pytest.raises(HTTPException) as exc:
        yec.list_checklist("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert db.rows("year_end_checklist_items") == []


def test_live_list_checklist_allows_an_own_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "draft"})
    resp = yec.list_checklist("E-MINE", current_user=EXEC_USER)
    assert len(resp["data"]) == 12


def test_live_update_checklist_item_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    item = db.seed("year_end_checklist_items", {"engagement_id": "E-THEIRS",
                                                "firm_id": FIRM, "status": "pending"})
    with pytest.raises(HTTPException) as exc:
        yec.update_checklist_item(
            "E-THEIRS", item["id"], yec.ChecklistItemUpdateIn(status="complete"),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    assert db.rows("year_end_checklist_items")[0]["status"] == "pending"
