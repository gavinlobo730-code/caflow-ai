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
from repositories.client_repository import client_repo
from routers.engagements import ENGAGEMENT_TRANSITIONS
from mock_data import MOCK_COMPLIANCE_RECORDS, MOCK_ENGAGEMENTS, ENGAGEMENT_INDEX, MOCK_CLIENTS, CLIENT_INDEX
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
    clients_snapshot = list(MOCK_CLIENTS)
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
    MOCK_CLIENTS[:] = clients_snapshot
    CLIENT_INDEX.clear()
    CLIENT_INDEX.update({c["id"]: c for c in MOCK_CLIENTS})


def _client(client_id, firm=FIRM):
    return client_repo.create({"id": client_id, "firm_id": firm, "client_name": f"Client {client_id}"})


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


# ── No-engagement fallback ────────────────────────────────────────────────────
# A client with zero ACTIVE engagements previously got nothing generated at all —
# a regression risk once the frontend's unconditional seedComplianceCalendar()
# (which needed no engagement concept) is repointed at this generator. These
# prove the fallback restores that "every client gets baseline GST coverage"
# behaviour without overriding a client whose active engagement already scoped
# obligations deliberately (e.g. an ITR-only engagement should not also receive
# GST obligations as an unrequested side effect).

def test_generate_due_client_scoped_fallback_seeds_gst_only():
    _client("CL-NOENG")
    res = ob.generate_due(FIRM, client_id="CL-NOENG", financial_year=FY, actor=ACTOR)
    assert res["generated"] == 25 and res["skipped"] == 0
    recs = compliance_records_repo.find_all(firm_id=FIRM, client_id="CL-NOENG")
    assert len(recs) == 25
    assert {r["obligation_type"] for r in recs} == {"GSTR1", "GSTR3B", "GSTR9"}
    assert all(r.get("engagement_id") is None for r in recs)
    # idempotent re-run
    again = ob.generate_due(FIRM, client_id="CL-NOENG", financial_year=FY, actor=ACTOR)
    assert again["generated"] == 0 and again["skipped"] == 25


def test_generate_due_active_engagement_client_excluded_from_fallback():
    """An ITR-only active engagement must not gain GST obligations as a side
    effect of the fallback — the fallback applies only to clients with zero
    active engagements, never on top of a deliberately-scoped one."""
    eng = _engagement("Income Tax Return", client="CL-ITR")
    res = ob.generate_due(FIRM, client_id="CL-ITR", financial_year=FY, actor=ACTOR)
    assert res["generated"] == 1                                     # ITR only, no GST fallback
    recs = compliance_records_repo.find_all(firm_id=FIRM, client_id="CL-ITR")
    assert {r["obligation_type"] for r in recs} == {"ITR"}
    assert recs[0]["engagement_id"] == eng["id"]


def test_generate_due_firm_wide_applies_fallback_to_uncovered_clients_only():
    _engagement("GST Compliance", client="CL-WITH-ENG")   # active → covered, no fallback
    _client("CL-WITH-ENG")
    _client("CL-NO-ENG-A")
    _client("CL-NO-ENG-B")
    res = ob.generate_due(FIRM, financial_year=FY, actor=ACTOR)
    assert res["generated"] == 75                                    # 25 x 3 clients
    by_client = {}
    for r in compliance_records_repo.find_all(firm_id=FIRM):
        by_client.setdefault(r["client_id"], []).append(r)
    assert set(by_client) == {"CL-WITH-ENG", "CL-NO-ENG-A", "CL-NO-ENG-B"}
    assert all(r.get("engagement_id") for r in by_client["CL-WITH-ENG"])
    assert all(r.get("engagement_id") is None for r in by_client["CL-NO-ENG-A"])
    assert all(r.get("engagement_id") is None for r in by_client["CL-NO-ENG-B"])


def test_generate_default_for_client_direct_call_is_pure_gst():
    _client("CL-DIRECT")
    res = ob.generate_default_for_client(FIRM, "CL-DIRECT", FY, actor=ACTOR)
    assert res["generated"] == 25
    recs = compliance_records_repo.find_all(firm_id=FIRM, client_id="CL-DIRECT")
    assert all(r["compliance_type"] == "GST" for r in recs)


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


# ── Assignment isolation (M2/M5) on the read endpoints ───────────────────────
# Mock mode is permissive by design (no assignments table), so we stub the exact
# seam filter_by_client() uses — effective_client_ids — to simulate real scope.

EXEC_A = {"firm_id": FIRM, "role": "Executive", "id": "exec-A", "auth_user_id": "exec-A"}
PARTNER = {"firm_id": FIRM, "role": "Partner", "id": "ptr", "auth_user_id": "ptr"}


def _seed_obl(client_id, obligation_type="GSTR3B", due="2026-06-20", status="Not Started"):
    return compliance_records_repo.create({
        "firm_id": FIRM, "client_id": client_id, "compliance_type": "GST",
        "obligation_type": obligation_type, "period_start": "2025-05-01",
        "due_date": due, "status": status})


def _scope_exec_to_client_a(monkeypatch):
    import core.authz as authz
    # Partner / firm-wide → None (all); everyone else → only CL-A.
    monkeypatch.setattr(authz, "effective_client_ids",
                        lambda u: None if u.get("role") == "Partner" else {"CL-A"})


def test_obligations_list_assignment_scope(monkeypatch):
    _scope_exec_to_client_a(monkeypatch)
    _seed_obl("CL-A", "GSTR1"); _seed_obl("CL-A", "GSTR3B"); _seed_obl("CL-B", "GSTR1")
    from routers.compliance_ops import list_obligations
    # Positive (sees Client A) + Negative (cannot see Client B)
    res = list_obligations(client_id=None, status=None, compliance_type=None, current_user=EXEC_A)
    obs = res["data"]["obligations"]
    assert {o["client_id"] for o in obs} == {"CL-A"} and len(obs) == 2
    # Partner still sees all firm obligations
    resp = list_obligations(client_id=None, status=None, compliance_type=None, current_user=PARTNER)
    assert len(resp["data"]["obligations"]) == 3


def test_calendar_assignment_scope(monkeypatch):
    _scope_exec_to_client_a(monkeypatch)
    _seed_obl("CL-A", "GSTR1", "2026-06-20"); _seed_obl("CL-B", "GSTR1", "2026-06-20")
    from routers.compliance_ops import obligations_calendar
    res = obligations_calendar(client_id=None, current_user=EXEC_A)
    cal = res["data"]
    rows = cal["upcoming"] + cal["overdue"] + cal["completed"]
    assert {o["client_id"] for o in rows} == {"CL-A"}        # calendar obeys assignment scope
    resp = obligations_calendar(client_id=None, current_user=PARTNER)
    calp = resp["data"]
    rowsp = calp["upcoming"] + calp["overdue"] + calp["completed"]
    assert {o["client_id"] for o in rowsp} == {"CL-A", "CL-B"}  # Partner sees all
