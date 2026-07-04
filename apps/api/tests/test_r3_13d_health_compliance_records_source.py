"""
R3.13d — routers/health.py's compliance-driven checks (the ITR hard-override
trigger, the compliance_health dimension's overdue/late-filing penalties, and
its dimension-detail factors) now read compliance_records (System A) instead
of compliance_tasks (System B, being retired).

This closes a real, live bug, not just a data-source swap: the old queries
referenced a task_type column and "Pending"/"Filed" status values that never
existed on compliance_tasks (the real columns/values are compliance_type and
lowercase pending/filed) — the ITR-overdue-6-months hard override and the
compliance_health dimension's overdue-return penalty have never actually
fired in any real deployment. Proven here against the real router functions
via the FakeDB e2e harness (routers/health.py has no module-level _USE_MOCK
flag, so _db is patched directly rather than via wire_e2e's usual mechanism).
"""
from datetime import date, timedelta

import routers.health as health
from tests.e2e_harness import FakeDB

FIRM = "FIRM-A"
CLIENT = "CLI-1"


def _seed_record(db, **overrides):
    row = {
        "id": overrides.pop("id", "cr-1"),
        "firm_id": FIRM, "client_id": CLIENT,
        "compliance_type": "Income Tax", "obligation_type": "ITR",
        "period_label": "ITR FY 2025-26", "status": "Not Started",
        "due_date": date.today().isoformat(),
    }
    row.update(overrides)
    return db.seed("compliance_records", row)


def test_itr_hard_override_fires_when_overdue_past_six_months():
    db = FakeDB()
    seven_months_ago = (date.today() - timedelta(days=210)).isoformat()
    _seed_record(db, obligation_type="ITR", status="Not Started", due_date=seven_months_ago)

    result = health._detect_hard_override_db(db, CLIENT, FIRM)
    assert result == "itr_overdue_6months"


def test_itr_hard_override_does_not_fire_when_recently_overdue():
    db = FakeDB()
    one_month_ago = (date.today() - timedelta(days=30)).isoformat()
    _seed_record(db, obligation_type="ITR", status="Not Started", due_date=one_month_ago)

    result = health._detect_hard_override_db(db, CLIENT, FIRM)
    assert result is None


def test_itr_hard_override_does_not_fire_when_filed():
    db = FakeDB()
    seven_months_ago = (date.today() - timedelta(days=210)).isoformat()
    _seed_record(db, obligation_type="ITR", status="Filed", due_date=seven_months_ago)

    result = health._detect_hard_override_db(db, CLIENT, FIRM)
    assert result is None


def test_compliance_health_dimension_penalizes_overdue_return():
    db = FakeDB()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _seed_record(db, status="Not Started", due_date=yesterday)

    score = health._dim_compliance_health_db(db, CLIENT, FIRM)
    assert score == 75   # 100 - 25 for the one overdue return


def test_compliance_health_dimension_penalizes_late_filing():
    db = FakeDB()
    due = (date.today() - timedelta(days=30)).isoformat()
    filed_late = (date.today() - timedelta(days=10)).isoformat()
    _seed_record(db, status="Filed", due_date=due, filed_date=filed_late)

    score = health._dim_compliance_health_db(db, CLIENT, FIRM)
    assert score == 92   # 100 - 8 for the one late filing


def test_compliance_health_dimension_no_penalty_for_on_time_filing():
    db = FakeDB()
    due = (date.today() + timedelta(days=10)).isoformat()
    filed_on_time = (date.today() - timedelta(days=1)).isoformat()
    _seed_record(db, status="Filed", due_date=due, filed_date=filed_on_time)

    score = health._dim_compliance_health_db(db, CLIENT, FIRM)
    assert score == 100


def test_dimension_detail_reports_overdue_return_with_period_label():
    db = FakeDB()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _seed_record(db, status="Not Started", due_date=yesterday, period_label="GSTR-3B Jun 2026")

    factors = health._dimension_detail_db(db, CLIENT, FIRM, "compliance_health")
    assert any("GSTR-3B Jun 2026" in f["label"] for f in factors)
    assert all(f["impact"] == -25 for f in factors if "overdue since" in f["label"])
