"""
Client-assignment scope (M2) on tally_migration.py.

tally_migration_jobs.client_id is OPTIONAL (ledgers/journals can be a
firm-level migration; customers/vendors need a target client — see
domain/tally/migration_service.py's _import_single_item). create_job already
checked a supplied client_id belonged to the caller's FIRM (a bespoke inline
query), but never checked ASSIGNMENT — the same firm-boundary-only gap found
across this sweep. Replaced with assert_client_access, which checks both.

get_job/parse_xml/preview_import/execute_import/rollback_import are all
row-addressed by job_id and previously resolved the job by firm_id alone
(get_migration_job) — an Executive/Reviewer/Manager could reach, parse,
preview, actually IMPORT (writing real customers/vendors into the target
client's books via execute_import) or roll back another staff member's
assigned client's Tally migration. A new _assert_job_scope resolver
(can_access_client, ONE fixed "Migration job not found" message covering
missing-row, wrong-firm and right-firm-but-unassigned alike) now guards all
five. can_access_client(user, None) is always True, so a client-less
(firm-level) job is unaffected by any of this.
"""
import pytest
from fastapi import HTTPException

import routers.tally_migration as tm
import domain.tally.migration_service as svc

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "e@f.test", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "email": "m@f.test", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow the rest (including client_id=None)."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    def _filter(user, rows, key="client_id"):
        return [r for r in rows if not r.get(key) or r.get(key) != THEIRS]

    monkeypatch.setattr(tm, "assert_client_access", _assert)
    monkeypatch.setattr(tm, "can_access_client", _can)
    monkeypatch.setattr(tm, "filter_by_client", _filter)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_store():
    svc._MOCK_JOBS.clear()
    svc._MOCK_ITEMS.clear()


def _job(client_id, job_id, **extra):
    row = {
        "id": job_id, "firm_id": FIRM, "client_id": client_id,
        "import_types": ["ledgers"], "status": "uploaded", **extra,
    }
    svc._MOCK_JOBS[job_id] = row
    svc._MOCK_ITEMS[job_id] = []
    return row


def _create_req(**overrides):
    body = {
        "name": "Import", "source_file_name": "data.xml",
        "target_financial_year": "2025-26",
    }
    body.update(overrides)
    return tm.CreateJobRequest(**body)


# ══════════════════════════════════════════════════════════════════════════
# create_job (client_id known up front, optional)
# ══════════════════════════════════════════════════════════════════════════

def test_creating_a_job_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        tm.create_job(_create_req(client_id=THEIRS), current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert svc._MOCK_JOBS == {}


def test_creating_a_job_for_an_own_client_is_allowed(deny):
    resp = tm.create_job(_create_req(client_id=MINE), current_user=EXEC_USER)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == MINE


def test_creating_a_firm_level_job_with_no_client_is_allowed(deny):
    """ledgers/journals migrations need no target client at all."""
    resp = tm.create_job(_create_req(), current_user=EXEC_USER)
    assert resp["success"] is True
    assert resp["data"]["client_id"] is None
    assert deny == [None]


def test_listing_jobs_drops_the_hidden_clients_rows(deny):
    _job(MINE, "J-MINE")
    _job(THEIRS, "J-THEIRS")
    _job(None, "J-FIRM")
    resp = tm.list_jobs(current_user=EXEC_USER)
    assert resp["success"] is True
    ids = {j["id"] for j in resp["data"]}
    assert ids == {"J-MINE", "J-FIRM"}


# ══════════════════════════════════════════════════════════════════════════
# get_job / parse_xml / preview_import / execute_import / rollback_import
# (row-addressed by job_id)
# ══════════════════════════════════════════════════════════════════════════

def test_getting_a_hidden_clients_job_is_refused(deny):
    _job(THEIRS, "J1")
    with pytest.raises(HTTPException) as exc:
        tm.get_job("J1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_an_own_clients_job_is_allowed(deny):
    _job(MINE, "J1")
    resp = tm.get_job("J1", current_user=EXEC_USER)
    assert resp["success"] is True


def test_getting_a_firm_level_job_is_allowed(deny):
    _job(None, "J1")
    resp = tm.get_job("J1", current_user=EXEC_USER)
    assert resp["success"] is True


def test_parsing_xml_for_a_hidden_clients_job_is_refused(deny):
    _job(THEIRS, "J1")
    with pytest.raises(HTTPException) as exc:
        tm.parse_xml("J1", tm.ParseXMLRequest(xml_content="<ENVELOPE></ENVELOPE>"), current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert svc._MOCK_ITEMS["J1"] == []


def test_parsing_xml_for_an_own_clients_job_is_allowed(deny):
    _job(MINE, "J1")
    resp = tm.parse_xml("J1", tm.ParseXMLRequest(xml_content="<ENVELOPE></ENVELOPE>"), current_user=MANAGER_USER)
    assert resp["success"] is True


def test_previewing_a_hidden_clients_job_is_refused(deny):
    _job(THEIRS, "J1")
    with pytest.raises(HTTPException) as exc:
        tm.preview_import("J1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_previewing_an_own_clients_job_is_allowed(deny):
    _job(MINE, "J1")
    resp = tm.preview_import("J1", current_user=EXEC_USER)
    assert resp["success"] is True


def test_importing_a_hidden_clients_job_is_refused(deny):
    _job(THEIRS, "J1")
    with pytest.raises(HTTPException) as exc:
        tm.execute_import("J1", tm.ExecuteImportRequest(), current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    # Refused before the domain layer ever ran — status untouched.
    assert svc._MOCK_JOBS["J1"]["status"] == "uploaded"


def test_importing_an_own_clients_job_is_allowed(deny):
    _job(MINE, "J1")
    resp = tm.execute_import("J1", tm.ExecuteImportRequest(), current_user=MANAGER_USER)
    assert resp["success"] is True


def test_rolling_back_a_hidden_clients_job_is_refused(deny):
    _job(THEIRS, "J1")
    with pytest.raises(HTTPException) as exc:
        tm.rollback_import("J1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert svc._MOCK_JOBS["J1"]["status"] == "uploaded"


def test_rolling_back_an_own_clients_job_is_allowed(deny):
    _job(MINE, "J1")
    resp = tm.rollback_import("J1", current_user=MANAGER_USER)
    assert resp["success"] is True
    assert svc._MOCK_JOBS["J1"]["status"] == "rolled_back"


def test_hidden_and_missing_job_errors_match(deny):
    # Same id in both scenarios — absent from the store, then present but
    # belonging to another client — so the message can only differ if the
    # wording itself differs between the two branches.
    with pytest.raises(HTTPException) as exc_missing:
        tm.get_job("J1", current_user=EXEC_USER)
    _job(THEIRS, "J1")
    with pytest.raises(HTTPException) as exc_hidden:
        tm.get_job("J1", current_user=EXEC_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail
