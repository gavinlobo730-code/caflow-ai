"""
Phase 4.4 — Compliance & Engagement Management (application-layer tests, mock mode).

Covers the pure obligation-generation specs (GST/TDS/ITR/Advance Tax/ROC/Audit) and
their statutory due dates, the escalation tier math, dashboard aggregation, the
assignment chain, the lifecycle workflow (valid + invalid transitions, incl. the new
Filed→Completed step), idempotent generation, engagement lifecycle transitions, audit
hooks, and firm/client isolation. Reuses the existing mock-aware repos so no DB is
required; the canonical entity is compliance_records (Decision 1).
"""
from datetime import date

import pytest
from fastapi import HTTPException

import services.compliance_obligation_service as ob
from domain.compliance_record_service import VALID_TRANSITIONS, compliance_record_service
from repositories.compliance_records_repository import compliance_records_repo
from repositories.engagement_repository import engagement_repo
from routers.engagements import ENGAGEMENT_TRANSITIONS
from mock_data import MOCK_COMPLIANCE_RECORDS, MOCK_ENGAGEMENTS, ENGAGEMENT_INDEX
from routers.sales_invoices import MOCK_SALES_INVOICES

FIRM = "F1"
ACTOR = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f"}
FY = "2025-26"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    MOCK_COMPLIANCE_RECORDS.clear()
    MOCK_ENGAGEMENTS.clear()
    ENGAGEMENT_INDEX.clear()
    MOCK_SALES_INVOICES.clear()
    # Capture audit; silence timeline (both imported lazily inside the service).
    audit: list = []
    import services.audit_service as au
    import services.timeline_service as ts
    monkeypatch.setattr(au, "log_event", lambda *a, **k: audit.append((a, k)))
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    yield {"audit": audit}
    MOCK_COMPLIANCE_RECORDS.clear()
    MOCK_ENGAGEMENTS.clear()
    ENGAGEMENT_INDEX.clear()
    MOCK_SALES_INVOICES.clear()


def _engagement(service_type, firm=FIRM, client="CL-1", assigned_to="prep-1",
                reviewer_id="rev-1", partner_id="ptr-1", status="Active"):
    return engagement_repo.create({
        "firm_id": firm, "client_id": client, "service_type": service_type,
        "fee_paise": 500000, "billing_cycle": "Monthly", "start_date": "2025-04-01",
        "status": status, "assigned_to": assigned_to, "reviewer_id": reviewer_id,
        "partner_id": partner_id,
    })


# ── Pure: obligation specs + statutory due dates ─────────────────────────────

def test_fy_helpers():
    assert ob.fy_end_year("2025-26") == 2026
    months = ob.fy_months("2025-26")
    assert months[0] == (2025, 4) and months[-1] == (2026, 3) and len(months) == 12


def test_gst_obligations_count_and_due_dates():
    specs = ob.obligations_for_service("GST Compliance", FY)
    assert len(specs) == 25                      # 12 GSTR-1 + 12 GSTR-3B + 1 GSTR-9
    by = {(s["obligation_type"], s["period_label"]): s for s in specs}
    assert by[("GSTR1", "GSTR-1 May 2025")]["due_date"] == "2025-06-11"   # CGST §37
    assert by[("GSTR3B", "GSTR-3B May 2025")]["due_date"] == "2025-06-20"  # CGST §39
    g9 = next(s for s in specs if s["obligation_type"] == "GSTR9")
    assert g9["due_date"] == "2026-12-31" and g9["compliance_type"] == "GST"


def test_tds_itr_advance_roc_audit_obligations():
    tds = ob.obligations_for_service("TDS Compliance", FY)
    assert len(tds) == 4 and all(s["obligation_type"] == "TDS26Q" for s in tds)
    assert next(s for s in tds if "Q1" in s["period_label"])["due_date"] == "2025-07-31"

    itr = ob.obligations_for_service("Income Tax Return", FY)
    assert len(itr) == 1 and itr[0]["due_date"] == "2026-07-31" and itr[0]["compliance_type"] == "Income Tax"

    adv = ob.obligations_for_service("Advance Tax", FY)
    assert len(adv) == 4
    assert sorted(s["due_date"] for s in adv) == ["2025-06-15", "2025-09-15", "2025-12-15", "2026-03-15"]

    roc = ob.obligations_for_service("ROC Compliance", FY)
    assert {s["obligation_type"] for s in roc} == {"MCA_AOC4", "MCA_MGT7"}
    assert next(s for s in roc if s["obligation_type"] == "MCA_AOC4")["due_date"] == "2026-10-30"

    audit = ob.obligations_for_service("Statutory Audit", FY)
    assert len(audit) == 1 and audit[0]["obligation_type"] == "TAX_AUDIT" and audit[0]["due_date"] == "2026-10-31"


def test_non_statutory_services_generate_nothing():
    assert ob.obligations_for_service("Accounting Outsourcing", FY) == []
    assert ob.obligations_for_service("Payroll", FY) == []


def test_escalation_tier_thresholds():
    f = ob.escalation_tier
    assert f(-1) == "overdue"
    assert f(0) == "due_1" and f(1) == "due_1"
    assert f(2) == "due_3" and f(3) == "due_3"
    assert f(5) == "due_7" and f(7) == "due_7"
    assert f(8) is None


def test_dashboard_aggregation_pure():
    today = date(2026, 6, 1)
    recs = [
        {"status": "Not Started", "due_date": "2026-06-03", "preparer_id": "p1", "client_id": "c1"},  # due this week
        {"status": "In Progress", "due_date": "2026-06-20", "preparer_id": "p1", "client_id": "c1"},  # due this month
        {"status": "Not Started", "due_date": "2026-05-20", "preparer_id": "p2", "client_id": "c2"},  # overdue
        {"status": "Filed", "due_date": "2026-05-01", "preparer_id": "p1", "client_id": "c1"},        # closed (excluded)
    ]
    agg = ob.aggregate_dashboard(recs, today=today)
    assert agg["summary"] == {"total_obligations": 4, "open_obligations": 3,
                              "due_this_week": 1, "due_this_month": 2, "overdue": 1}
    p1 = next(s for s in agg["by_staff"] if s["key"] == "p1")
    assert p1["obligations"] == 2 and p1["overdue"] == 0
    c2 = next(s for s in agg["by_client"] if s["key"] == "c2")
    assert c2["overdue"] == 1


# ── Lifecycle transition map ─────────────────────────────────────────────────

def test_compliance_lifecycle_adds_completed():
    assert VALID_TRANSITIONS["Ready To File"] == ["Filed"]
    assert VALID_TRANSITIONS["Filed"] == ["Completed"]
    assert VALID_TRANSITIONS["Completed"] == []


def test_engagement_lifecycle_map():
    assert ENGAGEMENT_TRANSITIONS["Draft"] == ["Active", "Closed"]
    assert "Completed" in ENGAGEMENT_TRANSITIONS["Review"]
    assert ENGAGEMENT_TRANSITIONS["Closed"] == []


# ── Generation (idempotent) + traceability ───────────────────────────────────

def test_generate_for_engagement_creates_obligations_idempotently():
    eng = _engagement("GST Compliance")
    res = ob.generate_for_engagement(FIRM, eng, FY, actor=ACTOR)
    assert res["generated"] == 25 and res["skipped"] == 0
    recs = compliance_records_repo.find_all(firm_id=FIRM, client_id="CL-1")
    assert len(recs) == 25
    sample = recs[0]
    assert sample["engagement_id"] == eng["id"]
    assert sample["preparer_id"] == "prep-1" and sample["reviewer_id"] == "rev-1" and sample["approver_id"] == "ptr-1"
    assert sample["status"] == "Not Started" and sample["compliance_type"] == "GST"
    assert not sample.get("journal_entry_id")          # never an accounting event
    # idempotent re-run
    again = ob.generate_for_engagement(FIRM, eng, FY, actor=ACTOR)
    assert again["generated"] == 0 and again["skipped"] == 25
    assert len(compliance_records_repo.find_all(firm_id=FIRM, client_id="CL-1")) == 25


def test_generate_due_only_active_engagements():
    _engagement("GST Compliance", client="CL-1", status="Active")
    _engagement("TDS Compliance", client="CL-2", status="Draft")     # not active → skipped
    res = ob.generate_due(FIRM, financial_year=FY, actor=ACTOR)
    assert res["generated"] == 25                                     # GST only
    assert {r["client_id"] for r in compliance_records_repo.find_all(firm_id=FIRM)} == {"CL-1"}


def test_generation_has_no_accounting_side_effects():
    eng = _engagement("Income Tax Return")
    ob.generate_for_engagement(FIRM, eng, FY, actor=ACTOR)
    assert MOCK_SALES_INVOICES == []                                  # no invoices/journals created


# ── Assignment chain ─────────────────────────────────────────────────────────

def test_assign_sets_chain_and_audits(_isolate):
    rec = compliance_records_repo.create({
        "firm_id": FIRM, "client_id": "CL-1", "compliance_type": "GST", "obligation_type": "GSTR3B",
        "period_start": "2025-05-01", "due_date": "2026-06-20", "status": "Not Started"})
    out = ob.assign(FIRM, rec["id"], preparer_id="p9", reviewer_id="r9", approver_id="a9", actor=ACTOR)
    assert out["preparer_id"] == "p9" and out["reviewer_id"] == "r9" and out["approver_id"] == "a9"
    assert out.get("assigned_at")
    actions = [a[0][3] for a in _isolate["audit"]]
    assert "assignment_change" in actions
    # second assignment records reassigned_at
    out2 = ob.assign(FIRM, rec["id"], preparer_id="p10", actor=ACTOR)
    assert out2.get("reassigned_at")


def test_assign_404_other_firm():
    rec = compliance_records_repo.create({"firm_id": FIRM, "client_id": "CL-1", "compliance_type": "GST",
                                          "due_date": "2026-06-20", "status": "Not Started"})
    with pytest.raises(HTTPException) as ei:
        ob.assign("F2", rec["id"], preparer_id="x")
    assert ei.value.status_code == 404


# ── Workflow transitions ─────────────────────────────────────────────────────

def test_transition_valid_and_audited(_isolate):
    rec = compliance_records_repo.create({"firm_id": FIRM, "client_id": "CL-1", "compliance_type": "GST",
                                          "due_date": "2026-06-20", "status": "Not Started"})
    out = ob.transition(FIRM, rec["id"], "In Progress", actor=ACTOR)
    assert out["status"] == "In Progress"
    assert "status_change" in [a[0][3] for a in _isolate["audit"]]


def test_transition_rejects_invalid():
    from core.exceptions import ValidationError
    rec = compliance_records_repo.create({"firm_id": FIRM, "client_id": "CL-1", "compliance_type": "GST",
                                          "due_date": "2026-06-20", "status": "Not Started"})
    with pytest.raises(ValidationError):
        ob.transition(FIRM, rec["id"], "Filed", actor=ACTOR)        # Not Started -/-> Filed


def test_transition_filed_to_completed_sets_completed_at():
    rec = compliance_records_repo.create({"firm_id": FIRM, "client_id": "CL-1", "compliance_type": "GST",
                                          "due_date": "2026-06-20", "status": "Filed"})
    out = ob.transition(FIRM, rec["id"], "Completed", actor=ACTOR)
    assert out["status"] == "Completed" and out.get("completed_at")


# ── Escalations (internal, idempotent) ───────────────────────────────────────

def _obl(due, status="Not Started", **extra):
    return compliance_records_repo.create({"firm_id": FIRM, "client_id": "CL-1", "compliance_type": "GST",
                                           "obligation_type": "GSTR3B", "due_date": due, "status": status,
                                           "preparer_id": "p1", **extra})


def test_escalate_tiers_and_idempotent():
    today = date(2026, 6, 10)
    _obl("2026-06-15")    # +5 → due_7
    _obl("2026-06-12")    # +2 → due_3
    _obl("2026-06-11")    # +1 → due_1
    _obl("2026-06-09")    # -1 → overdue
    _obl("2026-07-30")    # +50 → none
    _obl("2026-06-01", status="Filed")  # closed → ignored
    res = ob.escalate(FIRM, today=today, actor=ACTOR)
    assert res == {"escalated": 4, "due_7": 1, "due_3": 1, "due_1": 1, "overdue": 1}
    # same-day re-run is suppressed (idempotent)
    assert ob.escalate(FIRM, today=today, actor=ACTOR)["escalated"] == 0


# ── Dashboard / calendar over the canonical entity ───────────────────────────

def test_dashboard_and_calendar_projection():
    eng = _engagement("GST Compliance")
    ob.generate_for_engagement(FIRM, eng, FY, actor=ACTOR)
    dash = ob.dashboard(FIRM)
    assert dash["summary"]["total_obligations"] == 25
    assert "queue" in dash and len(dash["queue"]) == 25
    cal = ob.calendar(FIRM)
    assert len(cal["upcoming"]) + len(cal["overdue"]) + len(cal["completed"]) == 25


# ── Isolation ────────────────────────────────────────────────────────────────

def test_firm_isolation():
    eng = _engagement("GST Compliance", firm="F1")
    ob.generate_for_engagement("F1", eng, FY, actor=ACTOR)
    assert compliance_records_repo.find_all(firm_id="F2") == []
    assert ob.dashboard("F2")["summary"]["total_obligations"] == 0
