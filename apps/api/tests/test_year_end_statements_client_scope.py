"""
Client-assignment scope on the year-end FINANCIAL STATEMENTS router
(year_end_statements.py).

Every one of its 5 endpoints resolved its engagement by firm_id alone
(_get_engagement, live mode) or not at all (_mock_engagement_meta, mock
mode — checked existence only, not even firm_id). list_versions and
get_version were worse: neither ever resolved the engagement at all —
live mode applied only an inline firm_id filter directly on
financial_statement_versions, and mock mode had no tenancy check
whatsoever (_MOCK_VERSIONS keyed purely by engagement_id).

Fixed by delegating every endpoint to year_end.py's own
_assert_engagement_scope, the same pattern as year_end_reviews.py and
year_end_checklist.py.
"""
import pytest
from fastapi import HTTPException

import routers.year_end as ye
import routers.year_end_statements as yes
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow the rest. can_access_client is patched on
    routers.year_end (where _assert_engagement_scope actually calls it) —
    year_end_statements.py itself never imports core.authz directly."""
    seen = []

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(ye, "can_access_client", _can)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    ye._MOCK_ENGAGEMENTS.clear()
    yes._MOCK_VERSIONS.clear()


def _seed_engagement(engagement_id, client_id, firm_id=FIRM, **extra):
    row = {
        "id": engagement_id, "firm_id": firm_id, "client_id": client_id,
        "financial_year": "2024-25", "fy_start": "2024-04-01",
        "fy_end": "2025-03-31", "status": "draft", **extra,
    }
    ye._MOCK_ENGAGEMENTS[engagement_id] = row
    return row


# ══════════════════════════════════════════════════════════════════════════
# get_financial_statements
# ══════════════════════════════════════════════════════════════════════════

def test_getting_statements_for_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc:
        yes.get_financial_statements("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_statements_for_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    resp = yes.get_financial_statements("E-MINE", current_user=EXEC_USER)
    assert resp["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# create_snapshot
# ══════════════════════════════════════════════════════════════════════════

def test_snapshotting_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc:
        yes.create_snapshot("E-THEIRS", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert "E-THEIRS" not in yes._MOCK_VERSIONS


def test_snapshotting_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    resp = yes.create_snapshot("E-MINE", current_user=MANAGER_USER)
    assert resp["data"]["engagement_id"] == "E-MINE"


# ══════════════════════════════════════════════════════════════════════════
# list_versions — never resolved the engagement at all before this fix
# ══════════════════════════════════════════════════════════════════════════

def test_listing_versions_for_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    yes._MOCK_VERSIONS["E-THEIRS"] = [{"id": "v1", "engagement_id": "E-THEIRS"}]
    with pytest.raises(HTTPException) as exc:
        yes.list_versions("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_versions_for_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    yes._MOCK_VERSIONS["E-MINE"] = [{"id": "v1", "engagement_id": "E-MINE"}]
    resp = yes.list_versions("E-MINE", current_user=EXEC_USER)
    assert len(resp["data"]) == 1


# ══════════════════════════════════════════════════════════════════════════
# get_version — never resolved the engagement at all before this fix
# ══════════════════════════════════════════════════════════════════════════

def test_getting_a_version_on_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    yes._MOCK_VERSIONS["E-THEIRS"] = [{"id": "v1", "engagement_id": "E-THEIRS"}]
    with pytest.raises(HTTPException) as exc:
        yes.get_version("E-THEIRS", "v1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_a_version_on_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    yes._MOCK_VERSIONS["E-MINE"] = [{"id": "v1", "engagement_id": "E-MINE"}]
    resp = yes.get_version("E-MINE", "v1", current_user=EXEC_USER)
    assert resp["data"]["id"] == "v1"


def test_getting_a_missing_engagements_version_matches_the_hidden_message(deny):
    with pytest.raises(HTTPException) as exc_missing:
        yes.get_version("E-NOPE", "v1", current_user=EXEC_USER)
    _seed_engagement("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc_hidden:
        yes.get_version("E-THEIRS", "v1", current_user=EXEC_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail


# ══════════════════════════════════════════════════════════════════════════
# get_schedule
# ══════════════════════════════════════════════════════════════════════════

def test_getting_a_schedule_for_a_hidden_clients_engagement_is_refused(deny):
    _seed_engagement("E-THEIRS", THEIRS)
    with pytest.raises(HTTPException) as exc:
        yes.get_schedule("E-THEIRS", "cash_bank", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_a_schedule_for_an_own_clients_engagement_is_allowed(deny):
    _seed_engagement("E-MINE", MINE)
    resp = yes.get_schedule("E-MINE", "cash_bank", current_user=EXEC_USER)
    assert resp["data"]["schedule_type"] == "cash_bank"


def test_invalid_schedule_type_is_rejected_before_the_client_check(deny):
    """422 on a bad schedule_type, not a 404 that would leak whether the
    engagement exists — validation runs first, matching the router's
    existing order."""
    with pytest.raises(HTTPException) as exc:
        yes.get_schedule("E-ANYTHING", "not_a_real_type", current_user=EXEC_USER)
    assert exc.value.status_code == 422
    assert deny == []


# ══════════════════════════════════════════════════════════════════════════
# Live mode (e2e FakeDB) — year_end_statements.py imports get_supabase per
# call rather than through a _db()-style indirection.
# ══════════════════════════════════════════════════════════════════════════

def _e2e_setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ye, yes])
    return db


def test_live_list_versions_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    db.seed("financial_statement_versions", {"id": "v1", "engagement_id": "E-THEIRS",
                                             "firm_id": FIRM, "version_number": 1})
    with pytest.raises(HTTPException) as exc:
        yes.list_versions("E-THEIRS", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_live_list_versions_allows_an_own_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "draft"})
    db.seed("financial_statement_versions", {"id": "v1", "engagement_id": "E-MINE",
                                             "firm_id": FIRM, "version_number": 1})
    resp = yes.list_versions("E-MINE", current_user=EXEC_USER)
    assert len(resp["data"]) == 1


def test_live_get_version_refuses_another_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-THEIRS", "firm_id": FIRM,
                                     "client_id": THEIRS, "status": "draft"})
    ver = db.seed("financial_statement_versions", {"engagement_id": "E-THEIRS",
                                                    "firm_id": FIRM, "version_number": 1})
    with pytest.raises(HTTPException) as exc:
        yes.get_version("E-THEIRS", ver["id"], current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_live_get_version_allows_an_own_clients_engagement(deny, monkeypatch):
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "draft"})
    ver = db.seed("financial_statement_versions", {"engagement_id": "E-MINE",
                                                    "firm_id": FIRM, "version_number": 1})
    resp = yes.get_version("E-MINE", ver["id"], current_user=EXEC_USER)
    assert resp["data"]["id"] == ver["id"]


def test_live_get_version_missing_version_id_is_404_not_500(deny, monkeypatch):
    """The .single()-raises-on-zero-rows bug this phase also closed: a
    missing version_id must 404, not crash to an unhandled 500."""
    db = _e2e_setup(monkeypatch)
    db.seed("year_end_engagements", {"id": "E-MINE", "firm_id": FIRM,
                                     "client_id": MINE, "status": "draft"})
    with pytest.raises(HTTPException) as exc:
        yes.get_version("E-MINE", "no-such-version", current_user=EXEC_USER)
    assert exc.value.status_code == 404
