"""
apex-overview-practice-06: `escalate()` re-notifies an OVERDUE obligation
every single day it stays open, because "overdue" is a TERMINAL tier — once a
record crosses its due date, every subsequent day is still tier "overdue" but
a DIFFERENT calendar day, so the (tier, day) idempotency check
(`last_escalated_on == today AND last_escalated_tier == tier`) never matches
again and the notification fires daily for as long as the obligation stays
open (observed: one Apex record escalated 41 days in a row).

Fix: once already escalated at "overdue", re-notify at most WEEKLY (7 days)
rather than every day (or never again).

Also covers the message-wording half of the same finding: the redundant
`obligation_type` prefix (duplicating what `period_label` already names) and
the raw ISO due date.
"""
from datetime import date

import pytest

import services.compliance_obligation_service as ob
from repositories.compliance_records_repository import compliance_records_repo
from mock_data import MOCK_COMPLIANCE_RECORDS

FIRM = "FIRM-ESCALATION-SPAM-TEST"
ACTOR = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firm.test"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    MOCK_COMPLIANCE_RECORDS.clear()
    monkeypatch.setattr("services.timeline_service.timeline_service.log", lambda *a, **k: None)
    monkeypatch.setattr("services.audit_service.log_event", lambda *a, **k: None)
    yield
    MOCK_COMPLIANCE_RECORDS.clear()


def _overdue_record(due_date="2026-06-01"):
    return compliance_records_repo.create({
        "firm_id": FIRM, "client_id": "CL-1", "compliance_type": "GST",
        "obligation_type": "GSTR3B", "period_label": "GSTR-3B May 2026",
        "due_date": due_date, "status": "Not Started", "preparer_id": "p1",
    })


# ── The bug itself: no daily re-notification once overdue ──────────────────

def test_an_overdue_record_is_not_re_escalated_the_next_day():
    rec = _overdue_record()
    day1 = date(2026, 6, 10)
    res1 = ob.escalate(FIRM, today=day1, actor=ACTOR)
    assert res1["overdue"] == 1

    day2 = date(2026, 6, 11)
    res2 = ob.escalate(FIRM, today=day2, actor=ACTOR)
    assert res2["overdue"] == 0, (
        "an obligation already escalated as overdue yesterday must not "
        "re-notify again today — that is the 41-days-in-a-row bug")


def test_an_overdue_record_is_not_re_escalated_for_six_more_days():
    rec = _overdue_record()
    ob.escalate(FIRM, today=date(2026, 6, 10), actor=ACTOR)
    for offset in range(1, 7):  # days 11..16 — still inside the 7-day window
        day = date(2026, 6, 10 + offset)
        res = ob.escalate(FIRM, today=day, actor=ACTOR)
        assert res["overdue"] == 0, f"re-escalated on day +{offset}, inside the 7-day window"


def test_an_overdue_record_is_re_escalated_after_a_full_week():
    rec = _overdue_record()
    ob.escalate(FIRM, today=date(2026, 6, 10), actor=ACTOR)
    # exactly 7 days later
    res = ob.escalate(FIRM, today=date(2026, 6, 17), actor=ACTOR)
    assert res["overdue"] == 1, "a week has passed — the weekly cadence should have fired"
    # and the clock resets: escalating again the next day does not double-fire
    res_next_day = ob.escalate(FIRM, today=date(2026, 6, 18), actor=ACTOR)
    assert res_next_day["overdue"] == 0


def test_forty_one_consecutive_days_escalates_at_most_seven_times_not_forty_one():
    """The exact scenario CLAUDE.md/the finding describes — one Apex record,
    escalated once a day for 41 days in a row under the old code."""
    rec = _overdue_record(due_date="2025-12-01")   # already overdue before the walk starts
    total = 0
    start = date(2026, 1, 1)
    for offset in range(41):
        day = date.fromordinal(start.toordinal() + offset)
        total += ob.escalate(FIRM, today=day, actor=ACTOR)["overdue"]
    # Day 0 fires; the next fire is not until day 7, then day 14, 21, 28, 35 —
    # six fires across 41 days, not forty-one.
    assert total <= 7, f"escalated {total} times over 41 days — the daily-spam bug is back"
    assert total >= 5, "the weekly cadence should still fire periodically, not go silent forever"


def test_due_7_due_3_and_due_1_tiers_are_unaffected_by_the_overdue_cadence_change():
    """Negative control on SCOPE: the fix must not touch the escalating-IN
    tiers, which already change tier as the days count down and so were never
    part of this bug."""
    rec = _overdue_record(due_date="2026-06-17")   # +7 on day1
    day1 = date(2026, 6, 10)
    res1 = ob.escalate(FIRM, today=day1, actor=ACTOR)
    assert res1 == {"escalated": 1, "due_7": 1, "due_3": 0, "due_1": 0, "overdue": 0}

    day2 = date(2026, 6, 11)   # +6 — still due_7, same day count check as before
    res2 = ob.escalate(FIRM, today=day2, actor=ACTOR)
    assert res2["due_7"] == 1, "due_7 on a NEW day must still fire (unaffected by the overdue fix)"

    day3 = date(2026, 6, 14)   # +3 — now due_3, a real tier change
    res3 = ob.escalate(FIRM, today=day3, actor=ACTOR)
    assert res3["due_3"] == 1


# ── The message wording half of the same finding ────────────────────────────

def test_the_escalation_message_drops_the_redundant_obligation_type_prefix(monkeypatch):
    calls = []
    monkeypatch.setattr("services.timeline_service.timeline_service.log",
                        lambda *a, **k: calls.append(a))
    rec = _overdue_record()
    ob.escalate(FIRM, today=date(2026, 6, 10), actor=ACTOR)
    assert len(calls) == 1
    description = calls[0][3]
    assert not description.startswith("GSTR3B "), (
        f"the description still opens with the obligation_type code, "
        f"duplicating what the period_label already names: {description!r}")
    assert description.startswith("GSTR-3B May 2026"), description


def test_the_escalation_message_formats_the_due_date_as_dd_mon_yyyy(monkeypatch):
    calls = []
    monkeypatch.setattr("services.timeline_service.timeline_service.log",
                        lambda *a, **k: calls.append(a))
    rec = _overdue_record(due_date="2026-06-01")
    ob.escalate(FIRM, today=date(2026, 6, 10), actor=ACTOR)
    description = calls[0][3]
    assert "2026-06-01" not in description, (
        f"the raw ISO date is still in the message: {description!r}")
    assert "01 Jun 2026" in description, description


def test_the_in_app_notification_body_also_uses_the_pretty_date(monkeypatch):
    from repositories.notifications_repository import notifications_repo
    created = []
    monkeypatch.setattr(notifications_repo, "create", lambda payload: created.append(payload))
    rec = _overdue_record(due_date="2026-06-01")
    ob.escalate(FIRM, today=date(2026, 6, 10), actor=ACTOR)
    assert created, "no in-app notification was created for the preparer"
    body = created[0]["body"]
    assert "2026-06-01" not in body
    assert "01 Jun 2026" in body
