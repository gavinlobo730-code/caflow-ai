"""The copilot's firm context says what it could not read, and reads only keys its sources return (POST-A-281).

WHAT WAS WRONG
    `routers/ai_copilot.get_firm_context` read `firm_summary.get("filed", 0)`. `get_firm_summary` returns `filed_this_month` and
    has no `filed` key, so the figure was 0 whatever the books said. The panel's `tasks.due_this_week` was the same defect in a
    second place: it read `tasks_due_week` from a dashboard summary that returned no such key. And every read in both builders
    was wrapped `except Exception: x = {}` and then `.get(key, 0)`, so a read that FAILED was a zero too: the model was told
    "Overdue Compliance Records: 0" about a firm whose compliance read had raised, and a model asked what is due repeats a zero
    with confidence.

    A figure nobody has is not a 0. It is "not available" in the prompt (and the prompt tells the model what that means) and null
    in the panel; a genuine zero is still a zero, because "none are overdue" is a reading.

THE RULE, NOT TWO SPELLINGS OF IT
    Every `_figure(<source>, "<key>")` in the router must name a key the source function returns, found by reading the three
    functions' own return statements, so the next key read from a dict that never carries it fails here and not on a screen.
"""
from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import routers.ai_copilot as cp
from core.ist_clock import ist_today

API = Path(__file__).resolve().parents[1]
FIRM = "firm-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"}


# ── doubles ──────────────────────────────────────────────────────────────────────────────────────────

class _Dashboard:
    def __init__(self, **over):
        self.out = {"active_clients": 4, "tasks_due_today": 1, "tasks_due_week": 3, "overdue_tasks": 2,
                    "compliance_due_week": 5, "compliance_overdue": 6, "high_risk_clients": 1, **over}

    def get_dashboard_summary(self, firm_id=None, allowed_client_ids=None):
        return self.out


class _Summary:
    def __init__(self, out=None, raises=False):
        self.out, self.raises = out, raises

    def get_firm_summary(self, firm_id=None, allowed_client_ids=None):
        if self.raises:
            raise RuntimeError("compliance read failed")
        return self.out


SUMMARY = {"due_this_week": 5, "overdue": 6, "ready_for_review": 2, "ready_to_file": 3, "filed_this_month": 7, "high_risk_clients": 1}
RISKS = {"critical": 1, "high": 2, "medium": 3, "low": 4, "info": 0, "resolved": 5, "total_open": 10}


def _install(monkeypatch, *, dashboard=None, summary=None, risks=None, clients=None):
    """`None` for a source means its read raises; a value means it answers that."""
    import domain.compliance_record_service as comp_mod
    import domain.risk_engine as risk_mod
    import domain.task_service as task_mod
    import repositories.client_repository as client_mod

    monkeypatch.setattr(cp, "effective_client_ids", lambda user: None)
    monkeypatch.setattr(cp, "filter_by_client", lambda user, rows, key="client_id": list(rows))

    class _Boom:
        def __getattr__(self, _name):
            raise RuntimeError("read failed")

    monkeypatch.setattr(task_mod, "TaskDomainService", (lambda: dashboard) if dashboard is not None else (lambda: _Boom()))
    monkeypatch.setattr(comp_mod, "compliance_record_service", summary if summary is not None else _Summary(raises=True))
    monkeypatch.setattr(risk_mod, "get_risk_dashboard_stats",
                        (lambda **_k: risks) if risks is not None else (lambda **_k: (_ for _ in ()).throw(RuntimeError("read failed"))))

    class _Repo:
        def find_all(self, firm_id=None):
            if clients is None:
                raise RuntimeError("read failed")
            return list(clients)

    monkeypatch.setattr(client_mod, "client_repo", _Repo())


def _lines(ctx: str) -> dict:
    return {ln.split(":", 1)[0].strip(): ln.split(":", 1)[1].strip() for ln in ctx.splitlines() if ":" in ln}


CLIENTS = [{"id": "c1", "client_name": "A", "status": "active"}, {"id": "c2", "client_name": "B", "status": "active"}]


# ── a figure the source returns reaches the model and the panel ──────────────────────────────────────

def test_the_filed_count_is_this_months_and_reaches_both_the_prompt_and_the_panel(monkeypatch):
    _install(monkeypatch, dashboard=_Dashboard(), summary=_Summary(SUMMARY), risks=RISKS, clients=CLIENTS)
    lines = _lines(cp._build_firm_context(FIRM, USER))
    assert lines["Filed This Month"] == "7", lines
    panel = cp.get_firm_context(current_user=USER)["data"]
    assert panel["compliance"]["filed_this_month"] == 7
    assert "filed" not in panel["compliance"], "the key that was always 0 is gone, not kept beside the right one"


def test_the_panel_carries_every_figure_its_sources_return(monkeypatch):
    _install(monkeypatch, dashboard=_Dashboard(), summary=_Summary(SUMMARY), risks=RISKS, clients=CLIENTS)
    panel = cp.get_firm_context(current_user=USER)["data"]
    assert panel["tasks"] == {"overdue": 2, "due_today": 1, "due_this_week": 3}, "the tasks due this week are a count, not a 0"
    assert panel["compliance"] == {"overdue": 6, "due_this_week": 5, "ready_to_file": 3, "filed_this_month": 7}
    assert panel["risks"] == {"critical": 1, "high": 2, "medium": 3, "total_open": 10}
    assert panel["active_clients"] == 4 and len(panel["clients"]) == 2


def test_a_genuine_zero_is_still_a_zero(monkeypatch):
    _install(monkeypatch, dashboard=_Dashboard(overdue_tasks=0, compliance_overdue=0),
             summary=_Summary({**SUMMARY, "overdue": 0, "filed_this_month": 0}), risks={**RISKS, "critical": 0}, clients=CLIENTS)
    lines = _lines(cp._build_firm_context(FIRM, USER))
    assert lines["Overdue Compliance Records"] == "0" and lines["Filed This Month"] == "0" and lines["Overdue Tasks"] == "0"
    assert "Critical: 0" in cp._build_firm_context(FIRM, USER)


# ── a figure nobody has is not a 0 ───────────────────────────────────────────────────────────────────

def test_a_read_that_failed_is_not_available_in_the_prompt_and_null_in_the_panel(monkeypatch):
    _install(monkeypatch)                      # every read raises
    ctx = cp._build_firm_context(FIRM, USER)
    lines = _lines(ctx)
    for name in ("Active Clients", "Clients", "Overdue Tasks", "Tasks Due Today", "Compliance Overdue", "High-Risk Clients",
                 "Compliance Due This Week", "Overdue Compliance Records", "Ready to File", "Filed This Month", "Total Open Risks"):
        assert lines[name] == cp.NOT_AVAILABLE, (name, lines[name])
    assert "Critical: not available, High: not available, Medium: not available" in ctx
    panel = cp.get_firm_context(current_user=USER)["data"]
    assert panel["clients"] is None and panel["active_clients"] is None
    assert set(panel["tasks"].values()) == set(panel["compliance"].values()) == set(panel["risks"].values()) == {None}


def test_only_the_source_that_failed_is_not_available(monkeypatch):
    _install(monkeypatch, dashboard=_Dashboard(), summary=None, risks=RISKS, clients=CLIENTS)     # the compliance read raised
    lines = _lines(cp._build_firm_context(FIRM, USER))
    assert lines["Overdue Compliance Records"] == lines["Ready to File"] == lines["Filed This Month"] == cp.NOT_AVAILABLE
    assert lines["Overdue Tasks"] == "2" and lines["Total Open Risks"] == "10" and lines["Clients"] == "2"
    panel = cp.get_firm_context(current_user=USER)["data"]
    assert panel["compliance"]["overdue"] is None and panel["compliance"]["due_this_week"] == 5, "due this week comes from the dashboard"


def test_an_answer_that_lacks_a_key_is_not_available_for_that_figure_alone(monkeypatch):
    _install(monkeypatch, dashboard=_Dashboard(), summary=_Summary({"overdue": 6}), risks=RISKS, clients=CLIENTS)
    lines = _lines(cp._build_firm_context(FIRM, USER))
    assert lines["Overdue Compliance Records"] == "6" and lines["Filed This Month"] == cp.NOT_AVAILABLE


def test_the_panel_counts_active_clients_from_the_list_when_the_dashboard_did_not_say(monkeypatch):
    """A dashboard that returned no count is not a reason to say 0 active clients when the list the same panel carries has two."""
    _install(monkeypatch, dashboard=_Dashboard(active_clients=None), summary=_Summary(SUMMARY), risks=RISKS, clients=CLIENTS)
    assert cp.get_firm_context(current_user=USER)["data"]["active_clients"] == 2


def test_a_failed_read_is_logged_and_the_model_is_told_what_not_available_means(monkeypatch, caplog):
    _install(monkeypatch)
    with caplog.at_level("WARNING", logger="caflow.ai_copilot"):
        cp._build_firm_context(FIRM, USER)
    assert {r.getMessage() for r in caplog.records if "firm_context_read_failed" in r.getMessage()} == {
        "caflow.ai_copilot.firm_context_read_failed which=dashboard",
        "caflow.ai_copilot.firm_context_read_failed which=compliance_summary",
        "caflow.ai_copilot.firm_context_read_failed which=risks",
        "caflow.ai_copilot.firm_context_read_failed which=clients"}
    assert 'A figure shown as "not available" could not be read' in cp.COPILOT_SYSTEM_PROMPT
    assert "never treat it as zero" in cp.COPILOT_SYSTEM_PROMPT


# ── the rule: a key read is a key returned ───────────────────────────────────────────────────────────

def _returned_keys(path: str, function: str) -> set[str]:
    tree = ast.parse((API / path).read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == function:
            keys: set[str] = set()
            for ret in (n for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)):
                keys |= {k.value for k in ret.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            assert keys, f"{function} no longer returns a dict literal this guard can read"
            return keys
    raise AssertionError(f"{function} not found in {path}")


SOURCES = {
    "dashboard": ("domain/task_service.py", "get_dashboard_summary"),
    "firm_summary": ("domain/compliance_record_service.py", "get_firm_summary"),
    "risk_stats": ("domain/risk_engine.py", "get_risk_dashboard_stats"),
}


def test_every_figure_the_router_reads_is_a_key_its_source_returns():
    tree = ast.parse((API / "routers/ai_copilot.py").read_text(encoding="utf-8"))
    reads: list[tuple[str, str]] = []
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_figure"):
        source, key = call.args[0], call.args[1]
        assert isinstance(source, ast.Name) and isinstance(key, ast.Constant), "a _figure read this guard cannot follow"
        reads.append((source.id, key.value))
    assert len(reads) >= 20, f"the scan found {len(reads)} reads; it stopped seeing them"
    assert {s for s, _ in reads} == set(SOURCES), "a source is read that this guard does not know the function of"
    returned = {name: _returned_keys(*where) for name, where in SOURCES.items()}
    missing = sorted(f"{s}.{k}" for s, k in reads if k not in returned[s])
    assert not missing, f"the router reads keys that its source never returns, so they are always unavailable: {missing}"


def test_the_guard_would_catch_the_old_key():
    assert "filed" not in _returned_keys(*SOURCES["firm_summary"]) and "filed_this_month" in _returned_keys(*SOURCES["firm_summary"])
    assert "tasks_due_week" in _returned_keys(*SOURCES["dashboard"])


# ── tasks_due_week is a real count ───────────────────────────────────────────────────────────────────

def test_tasks_due_week_counts_open_tasks_due_today_or_within_seven_days(monkeypatch):
    import domain.compliance_record_service as crs
    import domain.task_service as ts

    today = ist_today()
    day = lambda n: (today + timedelta(days=n)).isoformat()      # noqa: E731

    class _Tasks:
        OPEN = [
            {"id": "today", "client_id": "c1", "due_date": day(0)},
            {"id": "d3", "client_id": "c1", "due_date": day(3)},
            {"id": "d7", "client_id": "c1", "due_date": day(7)},                       # the last day of the window
            {"id": "d8", "client_id": "c1", "due_date": day(8)},                       # outside it
            {"id": "late", "client_id": "c1", "due_date": day(-2)},                    # overdue: counted as overdue, not here
            {"id": "none", "client_id": "c1", "due_date": None},
            {"id": "stamp", "client_id": "c1", "due_date": day(2) + "T00:00:00+00:00"},  # a timestamp column's value
            {"id": "stamp7", "client_id": "c1", "due_date": day(7) + "T10:00:00+00:00"},  # ... on the last day: its DAY is in the window
        ]

        def find_open(self, **_k):
            return list(self.OPEN)

        def find_overdue(self, **_k):
            return [t for t in self.OPEN if t["due_date"] and str(t["due_date"])[:10] < day(0)]

    class _Clients:
        def find_all(self, **_k):
            return [{"id": "c1", "status": "active"}]

    class _Records:
        def list_records(self, **_k):
            return []

        def score_from_records(self, records, today=None):
            return (100, None)

    monkeypatch.setattr(ts, "task_repo", _Tasks())
    monkeypatch.setattr(ts, "client_repo", _Clients())
    monkeypatch.setattr(crs, "compliance_record_service", _Records())
    out = ts.TaskDomainService().get_dashboard_summary(firm_id=FIRM)
    assert out["tasks_due_week"] == 5, out    # today, d3, d7 and the two stamped ones: not d8, not the overdue one, not the undated
    assert out["tasks_due_today"] == 1 and out["overdue_tasks"] == 1
