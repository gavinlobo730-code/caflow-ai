"""
R3.5d — proves routers/analytics.py's fixes:

1. client_analytics/firm_analytics no longer fetch the firm's entire task
   history (every status, every FY) just to discard out-of-period
   completed tasks in Python — completed tasks are now fetched with
   status="completed" + a date range pushed to the query, matching the
   pattern team_analytics already used correctly. A completed task from
   last year must not appear in this period's completed count.
2. revenue_vs_effort no longer raises NameError (`client_repo =
   ClientRepository()` referenced a class that was never imported — only
   the client_repo singleton was, at module scope).
"""
from datetime import date

import routers.analytics as mod
import core.authz as authz_mod


def _today() -> str:
    return date.today().isoformat()


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, store, table, calls):
        self.s, self.t, self.calls = store, table, calls
        self.f = []

    def select(self, *a, **k):
        return self

    def eq(self, k, v):
        self.f.append(("eq", k, v)); return self

    def neq(self, k, v):
        self.f.append(("neq", k, v)); return self

    def gte(self, k, v):
        self.f.append(("gte", k, v)); return self

    def lte(self, k, v):
        self.f.append(("lte", k, v)); return self

    def execute(self):
        self.calls.append({"table": self.t, "filters": list(self.f)})
        rows = self.s.get(self.t, [])
        out = []
        for r in rows:
            ok = True
            for op, k, v in self.f:
                rv = r.get(k)
                if op == "eq" and rv != v:
                    ok = False; break
                if op == "neq" and rv == v:
                    ok = False; break
                if op == "gte" and (rv is None or str(rv) < str(v)):
                    ok = False; break
                if op == "lte" and (rv is None or str(rv) > str(v)):
                    ok = False; break
            if ok:
                out.append(r)
        return _Resp(out)


class FakeDB:
    def __init__(self):
        self.store = {}
        self.calls = []

    def table(self, name):
        return _Q(self.store, name, self.calls)


FIRM = "firm-r35d"


def _seed_tasks(db):
    db.store["tasks"] = [
        {"id": "t-old-completed", "client_id": "c1", "firm_id": FIRM,
         "status": "completed", "due_date": "2020-01-01", "updated_at": "2020-01-15"},
        {"id": "t-recent-completed", "client_id": "c1", "firm_id": FIRM,
         "status": "completed", "due_date": _today(), "updated_at": _today()},
        {"id": "t-open", "client_id": "c1", "firm_id": FIRM,
         "status": "open", "due_date": "2020-01-01", "updated_at": _today()},
    ]
    db.store["clients"] = [{"id": "c1", "client_name": "Client One", "firm_id": FIRM, "is_internal": False}]


def _patch_common(monkeypatch, db):
    monkeypatch.setattr(mod, "_get_db", lambda: db)
    monkeypatch.setattr(mod.time_tracking_analytics_repo, "get_hours_by_client", lambda *a, **k: {})
    monkeypatch.setattr(mod.time_tracking_analytics_repo, "get_firm_hours", lambda *a, **k: {"total_minutes": 0, "billable_minutes": 0})
    monkeypatch.setattr(authz_mod, "effective_client_ids", lambda user: None)


def test_client_analytics_excludes_old_completed_tasks_from_current_period(monkeypatch):
    db = FakeDB()
    _seed_tasks(db)
    _patch_common(monkeypatch, db)

    result = mod.client_analytics(period="month", current_user={"firm_id": FIRM, "id": "u1", "role": "Partner"})
    client_row = result["data"]["clients"][0]
    assert client_row["tasks_completed"] == 1  # only the in-period one
    assert client_row["tasks_active"] == 1

    # Confirm the completed-task query actually pushed status+date to the
    # query (bounded), rather than fetching the whole table unfiltered.
    task_calls = [c for c in db.calls if c["table"] == "tasks"]
    assert any(
        ("eq", "status", "completed") in c["filters"] and any(op == "gte" for op, *_ in c["filters"])
        for c in task_calls
    ), f"no bounded completed-tasks query found: {task_calls}"


def test_firm_analytics_excludes_old_completed_tasks_from_current_period(monkeypatch):
    db = FakeDB()
    _seed_tasks(db)
    _patch_common(monkeypatch, db)

    result = mod.firm_analytics(period="month", current_user={"firm_id": FIRM, "id": "u1", "role": "Partner"})
    assert result["data"]["tasks_completed"] == 1
    assert result["data"]["tasks_active"] == 1


def test_revenue_vs_effort_no_longer_raises_nameerror(monkeypatch):
    """Previously: `client_repo = ClientRepository()` — ClientRepository is
    never imported anywhere in this file, so this always raised NameError."""
    db = FakeDB()
    db.store["clients"] = []
    monkeypatch.setattr(mod, "_get_db", lambda: db)
    monkeypatch.setattr(mod.engagement_repo, "find_all", lambda **k: [])
    monkeypatch.setattr(mod.client_repo, "find_all", lambda **k: [])
    monkeypatch.setattr(mod.invoice_repo, "get_revenue_by_period", lambda **k: {})
    monkeypatch.setattr(mod.time_tracking_analytics_repo, "get_effort_by_engagement", lambda **k: {})

    result = mod.revenue_vs_effort(period="month", current_user={"firm_id": FIRM, "id": "u1", "role": "Partner"})
    assert result["success"] is True
