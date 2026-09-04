"""
Per-client payroll enablement — the cost brake.

WHY THERE IS A SWITCH
    Payroll is bundled into the subscription rather than priced per employee, so
    what bounds a firm's cost has to be a decision somebody made rather than how
    many clients happen to exist. docs/architecture/10-payroll.md calls it "the
    cost brake, in place of a price". It also keeps payroll off the screen for
    the clients that have none, which is most of them.

THE THREE THINGS THIS PROVES
    1. WRITES are refused for a client payroll is not switched on for, and READS
       are not. A client whose payroll the firm has stopped running still has
       Form 16s to issue and an ECR history somebody may be asked about; a
       switch that lost those is one nobody would dare use.
    2. A FAILED READ IS NOT "SWITCHED OFF". _payroll_settings swallows a failed
       read into {}, and reporting that as a settled decision would send a CA
       looking for a Partner to switch on something already on. The gate reads
       directly and answers 503.
    3. NO ROW MEANS NOT ENABLED. client_payroll_settings is sparse — migration
       326 created it for the input cut-off, which most clients never set — so
       absence is the ordinary state and it is the same answer as false.
       Migration 332 backfills a true row for every client that already has an
       employee or a run, which is why this cannot switch off a live payroll.

NEGATIVE CONTROL
    Remove the assert_payroll_enabled calls from routers/payroll.py and the
    refusal tests fail — every write goes through for a client nobody enabled.
    Make the gate treat a failed read as "not enabled" and
    test_a_failed_read_is_not_a_decision fails.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.payroll as payroll_mod
from core.permissions import PERMISSIONS, Role
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-ENABLE"
PARTNER = {"firm_id": FIRM, "id": "u-1", "auth_user_id": "a-1",
           "email": "partner@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [payroll_mod])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("clients", {"id": "CLI", "firm_id": FIRM,
                       "financial_year_start": "2026-04-01"})
    # Deliberately NO client_payroll_settings row: absence is the ordinary
    # state for a client nobody has switched payroll on for.
    return d


def _enable(d, enabled: bool = True):
    from models.payroll import PayrollEnablementIn
    return payroll_mod.put_payroll_enablement(
        PayrollEnablementIn(client_id="CLI", enabled=enabled), PARTNER)


def _employee(**kw):
    from models.payroll import EmployeeIn
    return EmployeeIn(client_id="CLI", name="Asha", basic_paise=3_000_000, **kw)


# ─── 1. it is Partner-only, and that is a different permission from write ────

def test_enabling_is_partner_only():
    """A Manager agreeing an input cut-off is doing their job. A Manager adding
    a payroll client is making a commercial commitment."""
    assert PERMISSIONS["payroll"]["enable"] == {Role.PARTNER}
    assert Role.MANAGER not in PERMISSIONS["payroll"]["enable"]
    assert Role.MANAGER in PERMISSIONS["payroll"]["write"]


# ─── 2. writes are refused, reads are not ───────────────────────────────────

def test_creating_an_employee_is_refused_for_a_client_nobody_enabled(db):
    with pytest.raises(HTTPException) as e:
        payroll_mod.create_employee(_employee(), PARTNER)
    assert e.value.status_code == 403
    assert "not switched on" in str(e.value.detail)


def test_creating_a_run_is_refused_for_a_client_nobody_enabled(db):
    from models.payroll import PayrollRunIn
    with pytest.raises(HTTPException) as e:
        payroll_mod.create_run(PayrollRunIn(client_id="CLI", month="2026-08"), PARTNER)
    assert e.value.status_code == 403


def test_recording_attendance_is_refused(db):
    from models.payroll import AttendanceIn
    with pytest.raises(HTTPException) as e:
        payroll_mod.put_attendance(
            AttendanceIn(client_id="CLI", month="2026-08", rows=[]), PARTNER)
    assert e.value.status_code == 403


def test_recording_a_one_time_earning_is_refused(db):
    from models.payroll import OneTimeEarningsIn
    with pytest.raises(HTTPException) as e:
        payroll_mod.put_one_time_earnings(
            OneTimeEarningsIn(client_id="CLI", month="2026-08", rows=[]), PARTNER)
    assert e.value.status_code == 403


def test_recording_the_statutory_identity_is_refused(db):
    from models.payroll import StatutoryIdentityIn
    with pytest.raises(HTTPException) as e:
        payroll_mod.put_statutory_identity(
            StatutoryIdentityIn(client_id="CLI", tan="MUMA12345B"), PARTNER)
    assert e.value.status_code == 403


def test_reading_stays_open_for_a_client_that_is_switched_off(db):
    """The asymmetry is the whole design. Switching payroll off is
    administrative; it must not delete anybody's Form 16."""
    _enable(db, True)
    payroll_mod.create_employee(_employee(), PARTNER)
    _enable(db, False)

    # The write is now refused …
    with pytest.raises(HTTPException) as e:
        payroll_mod.create_employee(_employee(), PARTNER)
    assert e.value.status_code == 403

    # … and the employee is still there to read.
    listed = payroll_mod.list_employees(client_id="CLI", current_user=PARTNER)
    assert len(listed["data"]) == 1


# ─── 3. switching on, and what the row records ──────────────────────────────

def test_switching_on_lets_the_write_through(db):
    _enable(db, True)
    out = payroll_mod.create_employee(_employee(), PARTNER)
    assert out["success"] is True


def test_the_row_records_who_switched_it_and_when(db):
    res = _enable(db, True)
    assert res["data"]["payroll_enabled"] is True
    assert res["data"]["payroll_enabled_by"] == "u-1"
    assert res["data"]["payroll_enabled_on"]


def test_switching_off_is_recorded_as_a_decision_not_a_deletion(db):
    _enable(db, True)
    res = _enable(db, False)
    assert res["data"]["payroll_enabled"] is False
    rows = [r for r in db.rows("client_payroll_settings") if r["client_id"] == "CLI"]
    assert len(rows) == 1, "one row per client, amended rather than replaced"


def test_the_attendance_screen_says_whether_payroll_is_on(db):
    """A client payroll is switched off for still answers every read, so the
    screen would look ordinary right up until Save is refused."""
    before = payroll_mod.get_attendance(client_id="CLI", month="2026-08",
                                        current_user=PARTNER)
    assert before["data"]["payroll_enabled"] is False
    _enable(db, True)
    after = payroll_mod.get_attendance(client_id="CLI", month="2026-08",
                                       current_user=PARTNER)
    assert after["data"]["payroll_enabled"] is True


# ─── 4. a failed read is not a decision ─────────────────────────────────────

def test_a_failed_read_is_not_a_decision(db, monkeypatch):
    """_payroll_settings swallows a failed read into {}. Reporting that as
    "payroll is switched off" would send a CA looking for a Partner to switch on
    something that is already on. 503, not 403."""
    real_table = db.table

    def _boom(name):
        if name == "client_payroll_settings":
            raise Exception("connection reset by peer")
        return real_table(name)

    monkeypatch.setattr(db, "table", _boom)
    with pytest.raises(HTTPException) as e:
        payroll_mod.assert_payroll_enabled(db, FIRM, "CLI")
    assert e.value.status_code == 503
    assert "nothing was written" in str(e.value.detail)


def test_mock_mode_is_not_gated():
    """No database means no settings and no decision to read. The guard is a
    no-op there, the same way assert_not_internal_for_payroll's lookup is."""
    payroll_mod.assert_payroll_enabled(None, FIRM, "CLI")
