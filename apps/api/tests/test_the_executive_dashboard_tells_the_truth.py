"""The Executive Dashboard shows computed figures or says it does not know (ai-08).

WHAT WAS WRONG
    `get_executive_dashboard` hardcoded outstanding invoices, outstanding amount
    and average collection days to 0, computed "team utilisation" as
    `min(100, overdue * 5 + 50)`, defaulted the average health score to 75 when no
    client had one, attached Rs 5,000 / Rs 3,000 per head to two growth
    opportunities, labelled an overdue-TASK count "compliance failures", and
    stamped the Groq model's name on a summary that was a template sentence
    whenever the Groq call had failed inside `except Exception: pass`.

    The existing scope tests (test_the_executive_dashboard_is_scoped_to_the_caller)
    check WHOSE figures these are. This checks that they are figures.

HOW THESE ARE BUILT
    The revenue block is read through the REAL `collections_service` over its own
    mock-mode ledger (the in-memory lists the Collections screen runs on in
    development), so "equals the computed value" is a statement about the code
    that serves the Collections screen, not about a stub of it. Everything else
    is the same doubles the scope test uses.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

import domain.ai_copilot_service as mod
from domain.ai import narration
from domain.billing import collection_days as cd
from domain.practice import executive_dashboard as ed

FIRM = "f1"
TODAY = date(2026, 10, 1)


# ── the doubles ──────────────────────────────────────────────────────────────

class _Clients:
    def __init__(self, rows):
        self.rows = rows

    def find_all(self, **kw):
        return list(self.rows)


class _Tasks:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def find_overdue(self, **kw):
        return list(self.rows)


class _Compliance:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def find_all(self, **kw):
        return list(self.rows)


class _Workflows:
    def list_failures(self, firm_id, **kw):
        return []

    def list_approvals(self, firm_id, **kw):
        return []

    def list_templates(self, firm_id, **kw):
        return []

    def client_ids_for_instances(self, firm_id, ids):
        return {}


class _Repo:
    def __init__(self, cached=None):
        self.cached = cached
        self.stored: list[dict] = []

    def get_summary(self, *a, **k):
        return self.cached

    def upsert_summary(self, firm_id, kind, entity, row):
        self.stored.append(row)
        return row

    def list_recommendations(self, *a, **k):
        return []


def _world(monkeypatch, *, clients=(), tasks=(), records=(), cached=None, reply="ok"):
    svc = mod.ai_copilot_service
    repo = _Repo(cached)
    monkeypatch.setattr(mod, "_get_client_repo", lambda: _Clients(clients))
    monkeypatch.setattr(mod, "_get_task_repo", lambda: _Tasks(tasks))
    monkeypatch.setattr(mod, "_get_compliance_records_repo", lambda: _Compliance(records))
    monkeypatch.setattr(mod, "_get_workflow_repo", lambda: _Workflows())
    monkeypatch.setattr(svc, "_repo", repo)

    async def _model(messages, **kw):
        if isinstance(reply, Exception):
            raise reply
        return reply, 7
    monkeypatch.setattr(svc, "_call_groq", _model)
    return svc, repo


def _dash(svc, scope=None):
    return asyncio.run(svc.get_executive_dashboard(FIRM, allowed_client_ids=scope))


def _fee_ledger(monkeypatch):
    """A fee ledger with known answers.

    Invoice A: Rs 1,000 billed 1 Sep, Rs 400 paid.        -> Rs 600 open
    Invoice B: Rs 500 billed 1 Sep, nothing paid.         -> Rs 500 open
    Invoice C: Rs 2,000 billed 1 Aug, paid in full.       -> not open
    Receipt R1 settles Rs 400 of A, ten days after A was billed.
    Receipt R2 settles all of C, thirty days after C was billed.
    Weighted: (40,000 x 10 + 2,00,000 x 30) / 2,40,000 paise = 26.67 -> 27 days.
    """
    import routers.sales_invoices as si
    import services.receipt_service as rs

    def inv(i, total, paid, status, day):
        return {"id": i, "firm_id": FIRM, "client_id": "int", "status": status,
                "total_paise": total, "paid_paise": paid, "debit_note_paise": 0,
                "credited_paise": 0, "invoice_date": day, "due_date": day,
                "credit_days": 30}
    monkeypatch.setattr(si, "MOCK_SALES_INVOICES", [
        inv("A", 100_000, 40_000, "partially_paid", "2026-09-01"),
        inv("B", 50_000, 0, "issued", "2026-09-01"),
        inv("C", 200_000, 200_000, "paid", "2026-08-01"),
    ])
    monkeypatch.setattr(rs, "MOCK_RECEIPTS", [
        {"id": "R1", "firm_id": FIRM, "client_id": "int", "receipt_date": "2026-09-11"},
        {"id": "R2", "firm_id": FIRM, "client_id": "int", "receipt_date": "2026-08-31"},
    ])
    monkeypatch.setattr(rs, "MOCK_RECEIPT_ALLOCATIONS", [
        {"receipt_id": "R1", "sales_invoice_id": "A", "allocated_paise": 40_000},
        {"receipt_id": "R2", "sales_invoice_id": "C", "allocated_paise": 200_000},
    ])


# ── the three KPIs that were literal zeroes ──────────────────────────────────

def test_outstanding_invoices_and_collection_days_are_the_computed_values(monkeypatch):
    _fee_ledger(monkeypatch)
    svc, _ = _world(monkeypatch, clients=[
        {"id": "c1", "client_name": "One", "health_score": 90, "status": "active"}])
    rev = _dash(svc)["revenue_insights"]
    assert rev["available"] is True
    assert rev["outstanding_invoices"] == 2, "A and B are open; C is paid"
    assert rev["outstanding_amount_paise"] == 60_000 + 50_000
    assert rev["avg_collection_days"] == 27, "(40,000x10 + 2,00,000x30) / 2,40,000, half up"


def test_the_receivable_is_the_collections_screens_own_figure(monkeypatch):
    """One number by construction: the dashboard calls `ar_aging`, it does not
    restate it."""
    from services import collections_service
    _fee_ledger(monkeypatch)
    aging = collections_service.ar_aging(FIRM, TODAY)
    snap = collections_service.executive_snapshot(FIRM, TODAY)
    assert snap["outstanding_amount_paise"] == aging["total_outstanding_paise"]
    assert snap["overdue_amount_paise"] == aging["overdue_paise"]


def test_a_firm_that_has_collected_nothing_has_no_collection_days_not_zero(monkeypatch):
    import routers.sales_invoices as si
    import services.receipt_service as rs
    monkeypatch.setattr(si, "MOCK_SALES_INVOICES", [{
        "id": "A", "firm_id": FIRM, "client_id": "int", "status": "issued",
        "total_paise": 10_000, "paid_paise": 0, "debit_note_paise": 0,
        "credited_paise": 0, "invoice_date": "2026-09-01", "due_date": "2026-10-01"}])
    monkeypatch.setattr(rs, "MOCK_RECEIPTS", [])
    monkeypatch.setattr(rs, "MOCK_RECEIPT_ALLOCATIONS", [])
    svc, _ = _world(monkeypatch)
    rev = _dash(svc)["revenue_insights"]
    assert rev["outstanding_invoices"] == 1
    assert rev["avg_collection_days"] is None, "0 would claim everyone pays on the day"


def test_a_scoped_caller_is_not_handed_the_practices_fee_receivables(monkeypatch):
    """The fee ledger is Partner-only (G1) everywhere else; it is withheld for a
    caller narrowed to their own clients, with the reason, and never computed."""
    _fee_ledger(monkeypatch)
    svc, _ = _world(monkeypatch)
    rev = _dash(svc, scope={"c-mine"})["revenue_insights"]
    assert rev["available"] is False and rev["reason"]
    assert "outstanding_amount_paise" not in rev


def test_a_firm_with_no_fee_ledger_says_so_instead_of_reporting_nil(monkeypatch):
    from services import collections_service
    monkeypatch.setattr(collections_service, "fee_ledger_provisioned", lambda f: False)
    svc, _ = _world(monkeypatch)
    rev = _dash(svc)["revenue_insights"]
    assert rev["available"] is False
    assert "outstanding_invoices" not in rev


# ── an unknown is not 75 ─────────────────────────────────────────────────────

def _numbers(node):
    """Every int or float leaf in a nested answer (a bool is not a number)."""
    if isinstance(node, bool):
        return []
    if isinstance(node, (int, float)):
        return [node]
    if isinstance(node, dict):
        return [n for v in node.values() for n in _numbers(v)]
    if isinstance(node, (list, tuple)):
        return [n for v in node for n in _numbers(v)]
    return []


def test_an_empty_firm_has_no_score_rather_than_75(monkeypatch):
    svc, _ = _world(monkeypatch)
    out = _dash(svc)
    assert out["firm_health_summary"]["overall_score"] is None
    assert out["firm_health_summary"]["compliance_coverage"] is None
    assert out["analysed_client_count"] == 0
    # No NUMBER anywhere in the answer is 75. This used to assert the substring "75"
    # was absent from the serialised answer, which also carries a generated-at
    # timestamp, so it failed whenever the microseconds happened to contain it — a
    # flake on a required check. The defect it guards is a figure standing in for
    # an unknown, so it asks about values, not about characters.
    assert 75 not in _numbers(out)


def test_a_client_with_no_score_is_unscored_not_healthy(monkeypatch):
    svc, _ = _world(monkeypatch, clients=[
        {"id": "c1", "client_name": "A", "health_score": 95, "status": "active"},
        {"id": "c2", "client_name": "B", "health_score": None, "status": "active"},
        {"id": "c3", "client_name": "C", "status": "active"},          # key absent
    ])
    out = _dash(svc)
    risk = out["client_risk_insights"]
    assert (risk["healthy_clients"], risk["unscored_clients"]) == (1, 2)
    assert out["firm_health_summary"]["overall_score"] == 95, "the mean of the scores that EXIST"


def test_a_missing_score_does_not_crash_the_dashboard(monkeypatch):
    """`c.get("health_score", 100)` returned None for a present-but-null key and
    `None < 40` raised, taking the whole dashboard down."""
    svc, _ = _world(monkeypatch, clients=[
        {"id": "c1", "client_name": "A", "health_score": None, "status": "active"}])
    assert _dash(svc)["analysed_client_count"] == 1


# ── nothing is invented ──────────────────────────────────────────────────────

def test_no_growth_opportunity_carries_a_rupee_value(monkeypatch):
    svc, _ = _world(monkeypatch, clients=[
        {"id": "c1", "client_name": "A", "status": "inactive", "health_score": 80},
        {"id": "c2", "client_name": "B", "status": "active", "health_score": 80},
    ])
    out = _dash(svc)
    opps = out["growth_opportunities"]
    assert {o["type"] for o in opps} == {"reactivation", "advisory"}
    assert "estimated_value_paise" not in json.dumps(out)
    assert all(o["basis"].startswith("rule-based") for o in opps)
    assert all(isinstance(o["count"], int) for o in opps)


def test_team_utilisation_is_not_a_function_of_overdue_tasks(monkeypatch):
    """`min(100, overdue * 5 + 50)` rose when the team fell behind and had never
    seen a timesheet."""
    tasks = [{"id": f"t{i}", "client_id": "c1", "assigned_to": "u1" if i < 2 else None}
             for i in range(4)]
    svc, _ = _world(monkeypatch, tasks=tasks)
    cap = _dash(svc)["capacity_insights"]
    assert cap["utilisation_percent"] is None and cap["utilisation_note"]
    assert (cap["overdue_tasks"], cap["unassigned_overdue_tasks"],
            cap["staff_holding_overdue"]) == (4, 2, 1)
    assert "team_utilisation_percent" not in cap
    assert 70 not in cap.values(), "4 x 5 + 50 must not come back"


def test_compliance_failures_counts_overdue_filings_not_overdue_tasks(monkeypatch):
    tasks = [{"id": f"t{i}", "client_id": "c1"} for i in range(3)]
    records = [{"client_id": "c1", "status": "Overdue", "due_date": "2026-05-01"}]
    svc, _ = _world(monkeypatch, tasks=tasks, records=records,
                    clients=[{"id": "c1", "client_name": "A", "health_score": 80,
                              "status": "active"}])
    out = _dash(svc)
    assert out["client_risk_insights"]["compliance_failures"] == 1
    assert out["capacity_insights"]["overdue_tasks"] == 3


def test_compliance_coverage_is_filed_over_due_this_year():
    fy_start, today = "2026-04-01", "2026-10-01"
    records = [
        {"due_date": "2026-05-20", "status": "Filed"},
        {"due_date": "2026-06-20", "status": "Completed"},
        {"due_date": "2026-07-20", "status": "Overdue"},
        {"due_date": "2026-08-20", "status": "Not Started"},
        {"due_date": "2026-12-20", "status": "Not Started"},   # not yet due
        {"due_date": "2026-01-20", "status": "Overdue"},       # an earlier year
    ]
    cov = ed.compliance_coverage(records, fy_start, today)
    assert (cov["due"], cov["filed"], cov["percent"]) == (4, 2, 50)
    assert ed.compliance_coverage([], fy_start, today)["percent"] is None


# ── the summary says what wrote it ───────────────────────────────────────────

def test_a_failed_model_call_stores_no_model_name(monkeypatch):
    svc, repo = _world(monkeypatch, reply=RuntimeError("groq is down"),
                       clients=[{"id": "c1", "client_name": "A", "health_score": 30,
                                 "status": "active"}])
    out = _dash(svc)
    assert out["summary_source"] == "template" and out["model_used"] is None
    assert repo.stored[0]["model_used"] is None, "the stored row named a model that wrote nothing"
    assert "1 clients in view" in out["ai_summary"]


def test_a_model_summary_is_stamped_with_the_configured_model(monkeypatch):
    from domain.ai import groq_text
    svc, repo = _world(
        monkeypatch, reply="One client is in view and it is critical.",
        clients=[{"id": "c1", "client_name": "A", "health_score": 30, "status": "active"}])
    out = _dash(svc)
    assert out["summary_source"] == "model"
    assert out["model_used"] == groq_text.text_model() == repo.stored[0]["model_used"]


def test_a_summary_with_a_figure_nobody_computed_is_not_shown(monkeypatch):
    """"About 40% of clients" is a number no engine produced."""
    svc, repo = _world(
        monkeypatch, reply="Roughly 40% of the book is at risk.",
        clients=[{"id": "c1", "client_name": "A", "health_score": 30, "status": "active"}])
    out = _dash(svc)
    assert out["summary_source"] == "template" and out["model_used"] is None
    assert "40" not in out["ai_summary"]


def test_a_plain_sentence_is_cached_briefly_so_the_model_is_retried(monkeypatch):
    from datetime import datetime, timedelta, timezone
    svc, repo = _world(monkeypatch, reply=RuntimeError("down"))
    _dash(svc)
    expires = datetime.fromisoformat(repo.stored[0]["expires_at"])
    assert expires - datetime.now(timezone.utc) < timedelta(minutes=10)


def test_the_mock_mode_canned_paragraph_is_never_stored_as_the_summary(monkeypatch):
    """No key in mock mode: `_call_groq` used to answer with a canned paragraph
    chosen by keyword, which the dashboard then stored under the model's name."""
    svc = mod.ai_copilot_service
    monkeypatch.setattr(mod, "_GROQ_API_KEY", "")
    monkeypatch.setattr(mod, "_USE_MOCK", True)
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        asyncio.run(svc._call_groq([{"role": "user", "content": "gst"}], canned_ok=False))
    text, tokens = asyncio.run(svc._call_groq([{"role": "user", "content": "gst"}]))
    assert tokens == 0 and text, "the default is unchanged for the callers that want it"


# ── the cache ────────────────────────────────────────────────────────────────

def test_a_cached_row_from_before_this_change_is_not_served(monkeypatch):
    """It carries the invented figures; serving it would put them back for an hour."""
    stale = {"metadata": {"revenue_insights": {"outstanding_invoices": 0},
                          "firm_health_summary": {"overall_score": 75}}}
    svc, repo = _world(monkeypatch, cached=stale)
    out = _dash(svc)
    assert out["dashboard_version"] == ed.DASHBOARD_VERSION
    assert out["firm_health_summary"]["overall_score"] is None
    assert repo.stored, "and a fresh answer replaced it"


def test_a_current_cached_row_is_served_as_the_payload_itself(monkeypatch):
    payload = {"dashboard_version": ed.DASHBOARD_VERSION, "marker": "cached"}
    svc, repo = _world(monkeypatch, cached={"id": "row", "metadata": payload})
    assert _dash(svc) == payload and not repo.stored


# ── the pure rules ───────────────────────────────────────────────────────────

def test_collection_days_weights_by_paise_not_by_invoice():
    rows = [
        {"allocated_paise": 500, "receipt_date": "2026-01-02", "invoice_date": "2026-01-01"},
        {"allocated_paise": 500_000, "receipt_date": "2026-04-01", "invoice_date": "2026-01-01"},
    ]
    got = cd.average_days_to_collect(rows)
    assert got.days == 90, "a Rs 5 invoice paid in a day does not cancel a Rs 5,000 one paid in 90"
    assert got.allocations == 2 and got.settled_paise == 500_500


def test_collection_days_rules():
    f = cd.average_days_to_collect
    assert f([]).days is None
    assert f([{"allocated_paise": 100, "is_voided": True,
               "receipt_date": "2026-02-01", "invoice_date": "2026-01-01"}]).days is None
    advance = f([{"allocated_paise": 100, "receipt_date": "2026-01-01",
                  "invoice_date": "2026-01-10"}])
    assert advance.days == 0, "an advance is 0 days, never negative"
    unreadable = f([
        {"allocated_paise": 100, "receipt_date": None, "invoice_date": "2026-01-01"},
        {"allocated_paise": 100, "receipt_date": "2026-01-11", "invoice_date": "2026-01-01"},
    ])
    assert (unreadable.days, unreadable.skipped, unreadable.allocations) == (10, 1, 1)
    assert f([{"allocated_paise": 3, "receipt_date": "2026-01-02",
               "invoice_date": "2026-01-01"},
              {"allocated_paise": 1, "receipt_date": "2026-01-03",
               "invoice_date": "2026-01-01"}]).days == 1, "(3x1 + 1x2)/4 = 1.25 -> 1"
    assert f([{"allocated_paise": 1, "receipt_date": "2026-01-02",
               "invoice_date": "2026-01-01"},
              {"allocated_paise": 1, "receipt_date": "2026-01-03",
               "invoice_date": "2026-01-01"}]).days == 2, "1.5 rounds half up"


def test_narration_reads_standalone_figures_only():
    assert narration.numbers_in("12 filings, Rs 1,25,000, 4.50 days") == {"12", "125000", "4.5"}
    assert narration.numbers_in("GSTR-3B on the 20th, Form 26Q, s.194J") == set()
    assert narration.numbers_in("due on the 20th") == set()
    assert narration.numbers_in("GSTR-3B and 26Q and 194J") == set()
    assert narration.is_grounded("12 filings overdue", [12])
    assert not narration.is_grounded("12 filings, about 40% of clients", [12])
    assert narration.ungrounded_numbers("3 of 7", [3]) == ["7"]
