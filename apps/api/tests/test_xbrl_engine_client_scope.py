"""
Client-assignment scope (M2) on xbrl_engine.py — MCA XBRL package generation.

xbrl_packages.client_id is NOT NULL (migration 156) — every package belongs
to exactly one client. create_package/list_packages took client_id from the
body/query and never checked it. update_package_data/validate_package/
generate_xml/review_package are row-addressed by package_id and checked only
firm_id — an unassigned Executive (year_end.write) or Manager (year_end.approve)
could read, edit, validate, generate XML for, or review another staff
member's assigned client's Balance Sheet and P&L data. _assert_package_scope
is the year_end.py-shaped resolver (can_access_client, ONE fixed "XBRL
package not found." message covering missing-row, wrong-firm and
right-firm-but-unassigned alike).

The router delegates entirely to domain/income_tax/xbrl_service.py's own
_MOCK_PACKAGES store (the tally_migration.py shape) — mock-mode-only tests
suffice; there is no separate live-mode branch in the ROUTER to exercise.
"""
import pytest
from fastapi import HTTPException

import routers.xbrl_engine as xe
import domain.income_tax.xbrl_service as xbrl_svc

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "e@f.test", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "email": "m@f.test", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(xe, "assert_client_access", _assert)
    monkeypatch.setattr(xe, "can_access_client", _can)
    # Pre-existing bug, unrelated to this sweep (found while writing this
    # file, recorded in the audit doc, not fixed here): validate_package's
    # success branch and review_package both call timeline_service.log(...,
    # action=..., metadata=...) — TimelineService.log() has neither
    # parameter (only its sibling log_timeline_event does), so every real
    # call on that success path 500s. Neutralised the same way
    # tests/e2e_harness.py's wire_e2e does for the same singleton, so this
    # file tests the AUTHZ guard, not that pre-existing crash.
    monkeypatch.setattr(xe.timeline_service, "log", lambda *a, **k: None)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_packages():
    xbrl_svc._MOCK_PACKAGES.clear()
    yield
    xbrl_svc._MOCK_PACKAGES.clear()


def _package(package_id, client_id, firm_id=FIRM, **extra):
    row = {
        "id": package_id, "firm_id": firm_id, "client_id": client_id,
        "financial_year": "2024-25", "taxonomy_version": "MCA_2023",
        "status": "draft", "balance_sheet_json": {}, "pnl_json": {},
        "notes_json": {}, **extra,
    }
    xbrl_svc._MOCK_PACKAGES[package_id] = row
    return row


# ══════════════════════════════════════════════════════════════════════════
# create_package — client_id is on the body
# ══════════════════════════════════════════════════════════════════════════

def test_creating_a_package_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        xe.create_package(
            xe.CreatePackageRequest(client_id=THEIRS, financial_year="2024-25"),
            current_user=EXEC_USER,
        )
    assert exc.value.status_code == 404
    assert xbrl_svc._MOCK_PACKAGES == {}


def test_creating_a_package_for_an_own_client_is_allowed(deny):
    resp = xe.create_package(
        xe.CreatePackageRequest(client_id=MINE, financial_year="2024-25"),
        current_user=EXEC_USER,
    )
    assert resp["success"] is True
    assert resp["data"]["client_id"] == MINE


# ══════════════════════════════════════════════════════════════════════════
# list_packages — client_id is a required query param
# ══════════════════════════════════════════════════════════════════════════

def test_listing_packages_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        xe.list_packages(client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_packages_for_an_own_client_is_allowed(deny):
    _package("P1", MINE)
    resp = xe.list_packages(client_id=MINE, current_user=EXEC_USER)
    assert [p["id"] for p in resp["data"]] == ["P1"]


# ══════════════════════════════════════════════════════════════════════════
# update_package_data / validate_package / generate_xml / review_package —
# all row-addressed by package_id via _assert_package_scope
# ══════════════════════════════════════════════════════════════════════════

def test_updating_a_hidden_clients_package_is_refused(deny):
    _package("P1", THEIRS)
    with pytest.raises(HTTPException) as exc:
        xe.update_package_data("P1", xe.UpdatePackageDataRequest(pnl_json={"x": 1}),
                               current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert xbrl_svc._MOCK_PACKAGES["P1"]["pnl_json"] == {}


def test_updating_an_own_clients_package_is_allowed(deny):
    _package("P1", MINE)
    resp = xe.update_package_data("P1", xe.UpdatePackageDataRequest(pnl_json={"x": 1}),
                                  current_user=EXEC_USER)
    assert resp["success"] is True
    assert resp["data"]["pnl_json"] == {"x": 1}


def test_validating_a_hidden_clients_package_is_refused(deny):
    _package("P1", THEIRS)
    with pytest.raises(HTTPException) as exc:
        xe.validate_package("P1", current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_validating_an_own_clients_package_is_allowed(deny):
    _package("P1", MINE)
    resp = xe.validate_package("P1", current_user=EXEC_USER)
    assert resp["success"] is True


def test_generating_xml_for_a_hidden_clients_package_is_refused(deny):
    _package("P1", THEIRS, status="validated")
    with pytest.raises(HTTPException) as exc:
        xe.generate_xml("P1", xe.GenerateXMLRequest(client_name="Acme", cin="U12345MH2020PTC000001"),
                        current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert xbrl_svc._MOCK_PACKAGES["P1"].get("xbrl_xml") is None


def test_generating_xml_for_an_own_clients_package_is_allowed(deny):
    _package("P1", MINE, status="validated")
    resp = xe.generate_xml("P1", xe.GenerateXMLRequest(client_name="Acme", cin="U12345MH2020PTC000001"),
                           current_user=MANAGER_USER)
    assert resp["success"] is True
    assert "xbrl_xml" in resp["data"]


def test_reviewing_a_hidden_clients_package_is_refused(deny):
    _package("P1", THEIRS, status="validated")
    with pytest.raises(HTTPException) as exc:
        xe.review_package("P1", current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert xbrl_svc._MOCK_PACKAGES["P1"]["status"] == "validated"


def test_reviewing_an_own_clients_package_is_allowed(deny):
    _package("P1", MINE, status="validated")
    resp = xe.review_package("P1", current_user=MANAGER_USER)
    assert resp["success"] is True
    assert xbrl_svc._MOCK_PACKAGES["P1"]["status"] == "reviewed"


def test_missing_and_hidden_package_errors_match(deny):
    _package("P1", THEIRS)
    with pytest.raises(HTTPException) as missing:
        xe.update_package_data("P-does-not-exist", xe.UpdatePackageDataRequest(),
                               current_user=EXEC_USER)
    with pytest.raises(HTTPException) as hidden:
        xe.update_package_data("P1", xe.UpdatePackageDataRequest(), current_user=EXEC_USER)
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "XBRL package not found."


# ══════════════════════════════════════════════════════════════════════════
# get_tag_mappings — the one EXEMPT route: no client_id anywhere
# ══════════════════════════════════════════════════════════════════════════

def test_tag_mappings_is_not_client_scoped(deny):
    """Over-guarding is a real failure mode too — this endpoint takes no
    client_id and must not require one."""
    resp = xe.get_tag_mappings(current_user=EXEC_USER)
    assert resp["success"] is True
    assert deny == []
