"""The firm's task, compliance and risk counts are the CALLER's counts (POST-A-054).

THE DEFECT
    `TaskDomainService.get_dashboard_summary` and `risk_engine.get_risk_dashboard_stats` took a firm and nothing else, so an
    Executive or Manager who is assigned seven of the firm's sixty clients was told the firm's overdue tasks, overdue
    compliance, high-risk clients and open risks. The AI copilot put those counts into the model's prompt (`/api/ai-copilot/chat`
    and `/api/ai-copilot/firm-context`), and `/api/risks/stats` and `/api/risks/firm/score` served them to the caller as they
    were (those two routes were retired on 22-11-2026, POST-A-548: no screen called them). No client is named in a count, and no screen reads these routes today, so the exposure was small: but the executive
    dashboard, the compliance summary and the client list beside them all answer for the caller's clients, and a figure that
    disagrees with the list next to it is a figure nobody can check.

WHAT IS HELD
    * with a client set, every figure counts only those clients (a row with no client is firm-level and stays); an EMPTY set is
      "no clients" and not "no filter"; `None` is unrestricted and is unchanged;
    * the copilot's two doors pass the caller's `effective_client_ids` to the count functions (behaviour), and a call site that
      forgets the keyword fails the scan (rule), with a negative control and a floor so the scan cannot go vacuous.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import domain.risk_engine as risk_engine
import domain.task_service as ts
from core.authz import within_client_scope

API = Path(__file__).resolve().parents[1]
FIRM = "firm-a"


# ── the narrowing itself ──────────────────────────────────────────────────────────────────────────────

ROWS = [{"id": 1, "client_id": "c1"}, {"id": 2, "client_id": "c2"}, {"id": 3, "client_id": None}, {"id": 4}]


def test_none_is_no_restriction():
    assert within_client_scope(ROWS, None) == ROWS


def test_a_set_keeps_its_clients_and_the_rows_that_have_none():
    assert [r["id"] for r in within_client_scope(ROWS, {"c1"})] == [1, 3, 4]


def test_an_empty_set_is_no_clients_and_not_no_filter():
    assert [r["id"] for r in within_client_scope(ROWS, set())] == [3, 4]


def test_the_key_can_be_named():
    clients = [{"id": "c1"}, {"id": "c2"}]
    assert within_client_scope(clients, {"c2"}, "id") == [{"id": "c2"}]


# ── the task / compliance summary ─────────────────────────────────────────────────────────────────────

TODAY = "2000-01-01"  # long past: every task with a due date is overdue


class _ClientRepo:
    def find_all(self, **_k):
        return [{"id": "c1", "status": "active"}, {"id": "c2", "status": "active"}, {"id": "c3", "status": "inactive"}]


class _TaskRepo:
    TASKS = [
        {"id": "t1", "client_id": "c1", "status": "open", "due_date": TODAY},
        {"id": "t2", "client_id": "c2", "status": "open", "due_date": TODAY},
        {"id": "t3", "client_id": "c2", "status": "waiting_client", "due_date": None},
        {"id": "t4", "client_id": None, "status": "open", "due_date": TODAY},  # the firm's own task
    ]

    def find_open(self, **_k):
        return list(self.TASKS)

    def find_overdue(self, **_k):
        return [t for t in self.TASKS if t["due_date"]]


class _Compliance:
    RECORDS = [
        {"client_id": "c1", "status": "Overdue", "due_date": "2000-01-01"},
        {"client_id": "c2", "status": "Overdue", "due_date": "2000-01-01"},
        {"client_id": "c2", "status": "Overdue", "due_date": "2000-01-01"},
    ]

    def list_records(self, **_k):
        return list(self.RECORDS)

    def score_from_records(self, records, today=None):
        return (10 if records else 100, None)  # a client with a record scores as high risk


@pytest.fixture
def summary(monkeypatch):
    import domain.compliance_record_service as crs
    monkeypatch.setattr(ts, "client_repo", _ClientRepo())
    monkeypatch.setattr(ts, "task_repo", _TaskRepo())
    monkeypatch.setattr(crs, "compliance_record_service", _Compliance())
    return lambda **kw: ts.TaskDomainService().get_dashboard_summary(firm_id=FIRM, **kw)


def test_the_unrestricted_summary_counts_the_firm(summary):
    out = summary()
    assert (out["active_clients"], out["overdue_tasks"], out["total_open_tasks"]) == (2, 3, 4)
    assert (out["compliance_overdue"], out["high_risk_clients"], out["waiting_client"]) == (3, 2, 1)


def test_a_scoped_summary_counts_the_callers_clients_and_the_firms_own_tasks(summary):
    out = summary(allowed_client_ids={"c1"})
    assert out["active_clients"] == 1
    assert out["overdue_tasks"] == 2          # t1 and the firm's own t4, not c2's t2
    assert out["total_open_tasks"] == 2       # t3 belongs to c2
    assert out["waiting_client"] == 0
    assert out["compliance_overdue"] == 1
    assert out["high_risk_clients"] == 1


def test_an_empty_scope_counts_no_clients(summary):
    out = summary(allowed_client_ids=set())
    assert out["active_clients"] == 0
    assert out["compliance_overdue"] == 0 and out["high_risk_clients"] == 0
    assert out["overdue_tasks"] == 1          # only the firm's own task has no client


# ── the risk tallies ──────────────────────────────────────────────────────────────────────────────────

RISKS = [
    {"id": "r1", "client_id": "c1", "severity": "critical"},
    {"id": "r2", "client_id": "c2", "severity": "critical"},
    {"id": "r3", "client_id": "c2", "severity": "high"},
]


@pytest.fixture
def risks(monkeypatch):
    monkeypatch.setattr(risk_engine, "get_all_risks", lambda firm_id=None, **k: list(RISKS))


def test_the_unrestricted_risk_stats_count_the_firm(risks):
    stats = risk_engine.get_risk_dashboard_stats(firm_id=FIRM)
    assert (stats["critical"], stats["high"], stats["total_open"], stats["resolved"]) == (2, 1, 3, 3)


def test_scoped_risk_stats_count_the_callers_clients(risks):
    stats = risk_engine.get_risk_dashboard_stats(firm_id=FIRM, allowed_client_ids={"c1"})
    assert (stats["critical"], stats["high"], stats["total_open"], stats["resolved"]) == (1, 0, 1, 1)
    assert risk_engine.get_risk_dashboard_stats(firm_id=FIRM, allowed_client_ids=set())["total_open"] == 0


# ── the doors ─────────────────────────────────────────────────────────────────────────────────────────

SCOPED_USER = {"id": "u1", "auth_user_id": "a1", "firm_id": FIRM, "role": "Executive", "email": "e@f"}
SCOPE = {"c1"}


# The two routes that served the document-risk counts and the firm's score (`/api/risks/stats`, `/api/risks/firm/score`) were
# RETIRED on 22-11-2026 with the score's function (POST-A-548): no screen called them and nothing records a document risk.
# The counts' one remaining door is the copilot's firm context, tried next, and the rule below still holds over every router.


def test_the_copilot_doors_pass_the_callers_clients(monkeypatch):
    import domain.compliance_record_service as crs
    import repositories.client_repository as crepo
    import routers.ai_copilot as mod
    seen = {}

    class _Tasks:
        def get_dashboard_summary(self, firm_id=None, allowed_client_ids="unset"):
            seen.setdefault("tasks", []).append(allowed_client_ids)
            return {}

    def _risk(firm_id=None, allowed_client_ids="unset"):
        seen.setdefault("risks", []).append(allowed_client_ids)
        return {}

    class _Comp:
        def get_firm_summary(self, firm_id=None, allowed_client_ids="unset"):
            seen.setdefault("compliance", []).append(allowed_client_ids)
            return {}

    class _Clients:
        def find_all(self, **_k):
            return []

    monkeypatch.setattr(mod, "effective_client_ids", lambda u: SCOPE)
    monkeypatch.setattr(ts, "TaskDomainService", _Tasks)
    monkeypatch.setattr(risk_engine, "get_risk_dashboard_stats", _risk)
    monkeypatch.setattr(crs, "compliance_record_service", _Comp())
    monkeypatch.setattr(crepo, "client_repo", _Clients())
    mod._build_firm_context(FIRM, SCOPED_USER)
    mod.get_firm_context(current_user=SCOPED_USER)
    assert seen == {"tasks": [SCOPE, SCOPE], "risks": [SCOPE, SCOPE], "compliance": [SCOPE, SCOPE]}


# ── the rule: no door asks for these counts without a scope ───────────────────────────────────────────

COUNT_FUNCTIONS = {"get_dashboard_summary", "get_risk_dashboard_stats"}


def _unscoped_calls(source: str) -> list[int]:
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        if name in COUNT_FUNCTIONS and not any(k.arg == "allowed_client_ids" for k in node.keywords):
            out.append(node.lineno)
    return out


def _router_sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted((API / "routers").glob("*.py"))}


def test_no_router_asks_for_a_count_without_naming_the_scope():
    offenders = {name: lines for name, src in _router_sources().items() if (lines := _unscoped_calls(src))}
    assert not offenders, (
        "a router calls a firm count function without `allowed_client_ids=`, so a scoped caller is told the firm's "
        f"figures (POST-A-054): {offenders}")


def test_the_scan_has_something_to_scan():
    total = sum(
        sum(1 for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call)
            and (getattr(n.func, "attr", None) or getattr(n.func, "id", None)) in COUNT_FUNCTIONS)
        for src in _router_sources().values())
    # Four since 22-11-2026 (POST-A-548): the two routes that served the risk counts and the score were retired, and the
    # copilot's two doors ask for the task counts and the risk counts each.
    assert total >= 4, f"expected the four router call sites, found {total}: the scan has gone vacuous"


def test_negative_control_a_call_without_the_scope_is_found():
    bad = "def f():\n    return get_risk_dashboard_stats(firm_id=x)\n"
    ok = "def f():\n    return get_risk_dashboard_stats(firm_id=x, allowed_client_ids=y)\n"
    assert _unscoped_calls(bad) == [2] and _unscoped_calls(ok) == []
