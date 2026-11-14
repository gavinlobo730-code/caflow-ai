"""A ledger row naming a settlement or a year-end adjustment can be opened (POST-A-096).

WHAT WAS WRONG
    The ledger drill-through refused two sources because no screen could open them by the id the row carries. A settlement's journal
    names `payroll_settlements.id`, and the only screen near one, the leaver's drawer, computes a NEW settlement and shows none that was
    recorded. A year-end adjustment's journal names `year_end_adjustments.id`, and its screen lives under its ENGAGEMENT, which the row
    does not carry.

WHAT THIS HOLDS
    `GET /api/payroll/settlements/{id}` returns the settlement as it was stored, with its components in the order they were recorded,
    the employee it settled and the member who recorded it. `GET /api/year-end/adjustments/{id}/engagement` returns the engagement an
    adjustment belongs to. Both read under the firm AND the client the caller named, so a missing row, a row of another client and (for
    the adjustment) a row whose engagement the caller may not see answer the same words.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.payroll as payroll
import routers.year_end_adjustments as yea
from routers.year_end import _MOCK_ENGAGEMENTS
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
PARTNER = {"id": "u-int-1", "firm_id": FIRM, "auth_user_id": "auth-1", "role": "Partner", "email": "p@f.test"}


# ── The recorded settlement ──────────────────────────────────────────────────

@pytest.fixture
def settlements(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(payroll, "_db", lambda: db)
    db.seed("users", {"id": "u-int-1", "firm_id": FIRM, "full_name": "Asha Rao", "email": "asha@f.test"})
    db.seed("payroll_employees", {"id": "E1", "firm_id": FIRM, "client_id": MINE, "name": "Ravi Kumar",
                                  "employee_code": "EMP-7", "status": "resigned"})
    db.seed("payroll_settlements", {
        "id": "S1", "firm_id": FIRM, "client_id": MINE, "employee_id": "E1", "fy": "2026-27",
        "leaving_date": "2026-10-31", "gross_paise": 50_000_00, "exempt_paise": 20_000_00, "taxable_paise": 30_000_00,
        "deductions_paise": 5_000_00, "tds_paise": 1_500_00, "net_paid_paise": 43_500_00,
        "journal_entry_id": "J1", "created_by": "u-int-1", "created_at": "2026-11-02T06:00:00+00:00"})
    # Seeded out of order: the answer is in the order they were RECORDED.
    db.seed("payroll_settlement_components", {"id": "c3", "firm_id": FIRM, "settlement_id": "S1", "kind": "deduction",
                                              "label": "Notice pay recovered", "gross_paise": 5_000_00, "exempt_paise": 0,
                                              "tax_head": "17(1)", "exempt_section": "", "statute": "",
                                              "created_at": "2026-11-02T06:00:03+00:00"})
    db.seed("payroll_settlement_components", {"id": "c1", "firm_id": FIRM, "settlement_id": "S1", "kind": "earning",
                                              "label": "Salary to the last day", "gross_paise": 30_000_00, "exempt_paise": 0,
                                              "tax_head": "17(1)", "exempt_section": "", "statute": "",
                                              "created_at": "2026-11-02T06:00:01+00:00"})
    db.seed("payroll_settlement_components", {"id": "c2", "firm_id": FIRM, "settlement_id": "S1", "kind": "earning",
                                              "label": "Gratuity", "gross_paise": 20_000_00, "exempt_paise": 20_000_00,
                                              "tax_head": "17(3)", "exempt_section": "10(10)", "statute": "",
                                              "created_at": "2026-11-02T06:00:02+00:00"})
    # Another client's settlement in the same firm.
    db.seed("payroll_settlements", {"id": "S2", "firm_id": FIRM, "client_id": THEIRS, "employee_id": "E9", "fy": "2026-27",
                                    "leaving_date": "2026-09-30", "gross_paise": 1, "exempt_paise": 0, "taxable_paise": 1,
                                    "deductions_paise": 0, "tds_paise": 0, "net_paid_paise": 1, "journal_entry_id": None,
                                    "created_by": None, "created_at": "2026-10-01T06:00:00+00:00"})
    return db


def test_a_recorded_settlement_is_returned_as_it_was_stored(settlements):
    out = payroll.get_settlement("S1", client_id=MINE, current_user=PARTNER)
    assert out["success"] is True
    s = out["data"]
    assert s["settlement_id"] == "S1" and s["employee_id"] == "E1"
    assert s["employee"] == {"id": "E1", "name": "Ravi Kumar", "employee_code": "EMP-7", "status": "resigned"}
    assert (s["gross_paise"], s["exempt_paise"], s["taxable_paise"], s["deductions_paise"], s["tds_paise"], s["net_paid_paise"]) == (
        50_000_00, 20_000_00, 30_000_00, 5_000_00, 1_500_00, 43_500_00)
    assert s["financial_year"] == "2026-27" and s["leaving_date"] == "2026-10-31"
    assert s["journal_entry_id"] == "J1" and s["posted"] is True
    assert s["recorded_by"] == "Asha Rao"
    assert [c["label"] for c in s["components"]] == ["Salary to the last day", "Gratuity", "Notice pay recovered"]
    assert s["components"][1] == {"kind": "earning", "label": "Gratuity", "gross_paise": 20_000_00, "exempt_paise": 20_000_00,
                                  "tax_head": "17(3)", "exempt_section": "10(10)", "statute": ""}


def test_a_settlement_that_did_not_post_says_so_and_names_nobody_it_cannot(settlements):
    settlements.seed("payroll_settlements", {"id": "S3", "firm_id": FIRM, "client_id": MINE, "employee_id": "E-gone", "fy": "2026-27",
                                             "leaving_date": "2026-08-31", "gross_paise": 10, "exempt_paise": 0, "taxable_paise": 10,
                                             "deductions_paise": 0, "tds_paise": 0, "net_paid_paise": 10, "journal_entry_id": None,
                                             "created_by": "someone-not-in-the-firm", "created_at": "2026-09-01T06:00:00+00:00"})
    s = payroll.get_settlement("S3", client_id=MINE, current_user=PARTNER)["data"]
    assert s["posted"] is False and s["journal_entry_id"] is None
    assert s["employee"] is None, "an employee row that cannot be read under this client is unknown, never a blank name"
    assert s["recorded_by"] is None
    assert s["components"] == []


@pytest.mark.parametrize("settlement_id,client_id", [
    ("S2", MINE),        # another client's settlement, named under mine
    ("S404", MINE),      # no such settlement
])
def test_a_missing_settlement_and_another_clients_say_the_same_words(settlements, settlement_id, client_id):
    with pytest.raises(HTTPException) as e:
        payroll.get_settlement(settlement_id, client_id=client_id, current_user=PARTNER)
    assert (e.value.status_code, e.value.detail) == (404, "Settlement not found")


def test_the_caller_must_reach_the_client_before_anything_is_read(monkeypatch):
    """Not only a 404: the database is not touched at all, so moving the check below the reads fails here."""
    def refuse(user, client_id):
        raise HTTPException(status_code=404, detail="Not found")

    def untouchable():
        raise AssertionError("the database was asked before the client was")
    monkeypatch.setattr(payroll, "assert_client_access", refuse)
    monkeypatch.setattr(payroll, "_db", untouchable)
    with pytest.raises(HTTPException) as e:
        payroll.get_settlement("S1", client_id=MINE, current_user=PARTNER)
    assert e.value.status_code == 404


def test_mock_mode_records_no_settlement_so_there_is_none_to_open(monkeypatch):
    monkeypatch.setattr(payroll, "_db", lambda: None)
    with pytest.raises(HTTPException) as e:
        payroll.get_settlement("S1", client_id=MINE, current_user=PARTNER)
    assert (e.value.status_code, e.value.detail) == (404, "Settlement not found")


# ── The adjustment's engagement ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_mock_stores():
    yea._MOCK_ADJUSTMENTS.clear()
    _MOCK_ENGAGEMENTS.clear()
    yield
    yea._MOCK_ADJUSTMENTS.clear()
    _MOCK_ENGAGEMENTS.clear()


@pytest.fixture
def deny(monkeypatch):
    """The caller reaches every client but THEIRS."""
    monkeypatch.setattr(yea, "can_access_client", lambda user, client_id: client_id != THEIRS)


@pytest.fixture
def live(monkeypatch, deny):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [yea])
    db.seed("year_end_engagements", {"id": "ENG-MINE", "firm_id": FIRM, "client_id": MINE, "status": "locked"})
    db.seed("year_end_engagements", {"id": "ENG-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "status": "draft"})
    db.seed("year_end_adjustments", {"id": "A1", "engagement_id": "ENG-MINE", "firm_id": FIRM, "client_id": MINE, "status": "posted"})
    db.seed("year_end_adjustments", {"id": "A2", "engagement_id": "ENG-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "status": "posted"})
    # A row whose own client is mine but whose engagement is one the caller may not see: the engagement scope decides.
    db.seed("year_end_adjustments", {"id": "A3", "engagement_id": "ENG-THEIRS", "firm_id": FIRM, "client_id": MINE, "status": "posted"})
    db.seed("year_end_adjustments", {"id": "A4", "engagement_id": "ENG-X", "firm_id": "firm-2", "client_id": MINE, "status": "posted"})
    return db


def test_an_adjustment_answers_its_engagement_even_when_the_engagement_is_locked(live):
    out = yea.adjustment_engagement("A1", client_id=MINE, current_user=PARTNER)
    assert out["success"] is True
    assert out["data"] == {"adjustment_id": "A1", "engagement_id": "ENG-MINE", "status": "posted"}


@pytest.mark.parametrize("adjustment_id,client_id", [
    ("A2", MINE),        # another client's adjustment, named under mine
    ("A2", THEIRS),      # named under a client the caller cannot reach
    ("A3", MINE),        # mine, but its engagement is one the caller cannot see
    ("A4", MINE),        # another firm's
    ("A404", MINE),      # no such adjustment
])
def test_every_adjustment_the_caller_may_not_open_says_the_same_words(live, adjustment_id, client_id):
    with pytest.raises(HTTPException) as e:
        yea.adjustment_engagement(adjustment_id, client_id=client_id, current_user=PARTNER)
    assert (e.value.status_code, e.value.detail) == (404, "Adjustment not found")


def test_the_client_the_caller_named_is_asked_before_the_row_is_read(live, monkeypatch):
    """Only the up-front client check can refuse this one: the row is the named client's own and the engagement scope is made to pass."""
    live.seed("year_end_adjustments", {"id": "A5", "engagement_id": "ENG-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "status": "posted"})
    monkeypatch.setattr(yea, "_assert_engagement_scope", lambda *a, **k: {})
    with pytest.raises(HTTPException) as e:
        yea.adjustment_engagement("A5", client_id=THEIRS, current_user=PARTNER)
    assert (e.value.status_code, e.value.detail) == (404, "Adjustment not found")


def test_mock_mode_asks_the_client_before_the_store(deny):
    """A row of THEIRS in an engagement the mock store does not hold (so the engagement check has nothing to refuse): the up-front check alone."""
    yea._MOCK_ADJUSTMENTS["ENG-NOWHERE"] = [{"id": "A9", "client_id": THEIRS, "status": "draft"}]
    with pytest.raises(HTTPException) as e:
        yea.adjustment_engagement("A9", client_id=THEIRS, current_user=PARTNER)
    assert (e.value.status_code, e.value.detail) == (404, "Adjustment not found")


def test_the_year_end_lookup_asks_the_practice_guard_the_router_does_not():
    """The adjustments router is mounted without the client guard, so the route carries it: the firm's own practice is a Partner's (G1)."""
    from services.internal_client_service import require_client_access
    from main import app
    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/year-end/adjustments/{adjustment_id}/engagement")
    assert any(getattr(d, "dependency", None) is require_client_access for d in route.dependencies)


def test_mock_mode_answers_from_the_mock_store_and_asks_the_client_first(deny):
    _MOCK_ENGAGEMENTS["ENG-MINE"] = {"id": "ENG-MINE", "firm_id": FIRM, "client_id": MINE, "status": "draft"}
    yea._MOCK_ADJUSTMENTS["ENG-MINE"] = [{"id": "A1", "client_id": MINE, "status": "draft"}]
    assert yea.adjustment_engagement("A1", client_id=MINE, current_user=PARTNER)["data"]["engagement_id"] == "ENG-MINE"
    for adjustment_id, client_id in (("A1", THEIRS), ("A404", MINE)):
        with pytest.raises(HTTPException) as e:
            yea.adjustment_engagement(adjustment_id, client_id=client_id, current_user=PARTNER)
        assert (e.value.status_code, e.value.detail) == (404, "Adjustment not found")


# ── The routes are reachable at the paths the browser calls ──────────────────

@pytest.mark.parametrize("path,handler", [
    ("/api/payroll/settlements/S1", "get_settlement"),
    ("/api/year-end/adjustments/A1/engagement", "adjustment_engagement"),
])
def test_the_path_the_browser_calls_reaches_the_handler(path, handler):
    """No earlier route on the same prefix (`/year-end/{engagement_id}/...`) swallows the path."""
    from starlette.routing import Match
    from main import app
    scope = {"type": "http", "path": path, "method": "GET", "root_path": "", "query_string": b"", "headers": []}
    for route in app.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            assert getattr(route, "endpoint", None).__name__ == handler, f"{path} reaches {route.endpoint.__name__}"
            return
    pytest.fail(f"nothing answers GET {path}")
