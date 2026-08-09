"""
Client-assignment scope on the year-end EXPORTS router (year_end_exports.py).

Every one of its 5 endpoints resolved its engagement by firm_id alone
(_get_engagement, live mode) or did not check its client at all
(_mock_engagement, mock mode). list_exports and get_download_url never
resolved the engagement at all: live mode applied only an inline firm_id
filter directly on year_end_exports, mock mode (_MOCK_EXPORTS, keyed
purely by engagement_id) had no tenancy check whatsoever.

get_download_url is the sharpest one — it hands back a live, signed
download URL to the export PDF (a client's complete financial-statements
pack, notes, or the full year-end pack), so an unassigned caller reaching
it was a real exfiltration path, not just a metadata leak.

Fixed by delegating every endpoint to year_end.py's own
_assert_engagement_scope, the same pattern as the other year-end siblings
already fixed in this sweep.
"""
import pytest
from fastapi import HTTPException

import routers.year_end as ye
import routers.year_end_exports as yee
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow the rest. can_access_client is patched on
    routers.year_end (where _assert_engagement_scope actually calls it) —
    year_end_exports.py itself never imports core.authz directly."""
    seen = []

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(ye, "can_access_client", _can)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    ye._MOCK_ENGAGEMENTS.clear()
    yee._MOCK_EXPORTS.clear()


def _seed_engagement(engagement_id, client_id, firm_id=FIRM, **extra):
    row = {
        "id": engagement_id, "firm_id": firm_id, "client_id": client_id,
        "financial_year": "2024-25", "fy_start": "2024-04-01",
        "fy_end": "2025-03-31", "status": "approved", **extra,
    }
    ye._MOCK_ENGAGEMENTS[engagement_id] = row
    return row


# ══════════════════════════════════════════════════════════════════════════
# export_financial_statements
# ══════════════════════════════════════════════════════════════════════════

def test_exporting_statements_for_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc:
        yee.export_financial_statements("E-THEIRS", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert "E-THEIRS" not in yee._MOCK_EXPORTS


def test_exporting_statements_for_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    resp = yee.export_financial_statements("E-MINE", current_user=MANAGER_USER)
    assert resp["data"]["export_type"] == "financial_statements"


# ══════════════════════════════════════════════════════════════════════════
# export_notes
# ══════════════════════════════════════════════════════════════════════════

def test_exporting_notes_for_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc:
        yee.export_notes("E-THEIRS", current_user=MANAGER_USER)
    assert exc.value.status_code == 404


def test_exporting_notes_for_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    resp = yee.export_notes("E-MINE", current_user=MANAGER_USER)
    assert resp["data"]["export_type"] == "notes"


# ══════════════════════════════════════════════════════════════════════════
# export_complete_pack
# ══════════════════════════════════════════════════════════════════════════

def test_exporting_complete_pack_for_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc:
        yee.export_complete_pack("E-THEIRS", current_user=MANAGER_USER)
    assert exc.value.status_code == 404


def test_exporting_complete_pack_for_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    resp = yee.export_complete_pack("E-MINE", current_user=MANAGER_USER)
    assert resp["data"]["export_type"] == "complete_pack"


# ══════════════════════════════════════════════════════════════════════════
# list_exports — never resolved the engagement at all before this fix
# ══════════════════════════════════════════════════════════════════════════

def test_listing_exports_for_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    yee._MOCK_EXPORTS["E-THEIRS"] = [{"id": "x1", "engagement_id": "E-THEIRS"}]
    with pytest.raises(HTTPException) as exc:
        yee.list_exports("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_exports_for_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    yee._MOCK_EXPORTS["E-MINE"] = [{"id": "x1", "engagement_id": "E-MINE"}]
    resp = yee.list_exports("E-MINE", current_user=EXEC_USER)
    assert len(resp["data"]) == 1


# ══════════════════════════════════════════════════════════════════════════
# get_download_url — the sharpest gap: hands back a live signed URL
# ══════════════════════════════════════════════════════════════════════════

def test_downloading_an_export_on_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    yee._MOCK_EXPORTS["E-THEIRS"] = [{"id": "x1", "engagement_id": "E-THEIRS"}]
    with pytest.raises(HTTPException) as exc:
        yee.get_download_url("E-THEIRS", "x1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_downloading_an_export_on_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    yee._MOCK_EXPORTS["E-MINE"] = [{"id": "x1", "engagement_id": "E-MINE"}]
    resp = yee.get_download_url("E-MINE", "x1", current_user=EXEC_USER)
    assert resp["data"]["download_url"]


def test_downloading_a_missing_engagements_export_matches_the_hidden_message(deny):
    with pytest.raises(HTTPException) as exc_missing:
        yee.get_download_url("E-NOPE", "x1", current_user=EXEC_USER)
    _seed_engagement("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc_hidden:
        yee.get_download_url("E-THEIRS", "x1", current_user=EXEC_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail


# ══════════════════════════════════════════════════════════════════════════
# Live mode (e2e FakeDB) — year_end_exports.py imports get_supabase per
# call rather than through a _db()-style indirection.
# ══════════════════════════════════════════════════════════════════════════

def _e2e_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ye, yee])
    return db


def test_live_list_exports_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "approved"})
    db.seed("year_end_exports", {"id": "x1", "engagement_id": "E-THEIRS", "firm_id": FIRM})
    with pytest.raises(HTTPException) as exc:
        yee.list_exports("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_live_get_download_url_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "approved"})
    export = db.seed("year_end_exports", {"engagement_id": "E-THEIRS", "firm_id": FIRM,
                                          "storage_path": "F1/C-THEIRS/2024-25/pack.pdf"})
    with pytest.raises(HTTPException) as exc:
        yee.get_download_url("E-THEIRS", export["id"], current_user=EXEC_USER)
    assert exc.value.status_code == 404


class _FakeStorageBucket:
    def create_signed_url(self, path, expires_in):
        return {"signedURL": f"https://fake-storage.test/{path}?expires={expires_in}"}


class _FakeStorage:
    def from_(self, bucket):
        return _FakeStorageBucket()


def test_live_get_download_url_allows_an_own_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    monkeypatch.setattr(db, "storage", _FakeStorage(), raising=False)
    db.seed("year_end_engagements", {"id": "E-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "approved"})
    export = db.seed("year_end_exports", {"engagement_id": "E-MINE", "firm_id": FIRM,
                                          "storage_path": "F1/C-MINE/2024-25/pack.pdf"})
    resp = yee.get_download_url("E-MINE", export["id"], current_user=EXEC_USER)
    assert resp["data"]["export_id"] == export["id"]
    assert "fake-storage.test" in resp["data"]["download_url"]


def test_live_get_download_url_missing_export_id_is_404_not_500(deny, monkeypatch):
    """The .single()-raises-on-zero-rows bug this phase also closed: a
    missing export_id must 404, not crash to an unhandled 500."""
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "approved"})
    with pytest.raises(HTTPException) as exc:
        yee.get_download_url("E-MINE", "no-such-export", current_user=EXEC_USER)
    assert exc.value.status_code == 404
