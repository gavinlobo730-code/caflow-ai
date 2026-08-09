"""
Client-assignment scope on the workload and team routers — the two places
that aggregate the WHOLE FIRM's tasks per named colleague.

Neither router carries main.py's mount-level client guard, and neither takes a
client_id in any request, so nothing was ever going to check one for them.
tasks.client_id is NOT NULL (migration 002).

  * workload.get_user_workload is the sharpest: it selects "*" and returns
    FULL task rows (title, description, due_date, client_id) under
    overdue_tasks/due_today — the substance of a colleague's work on clients
    outside the caller's own book, not just counts.
  * workload.get_team_workload computed every named colleague's active/
    overdue/due-this-week/utilisation figures over every client in the firm.
  * team.list_team fed task_repo.find_all(firm_id=...) straight into
    compute_team_workload — aggregate counts only, so lower severity, but the
    same underlying firm-wide read.
"""
import pytest

import routers.team as tm
import routers.workload as wl

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


def _only_mine(user, rows, key="client_id"):
    """Stand-in for core.authz.filter_by_client with {MINE} as the book."""
    return [r for r in rows if not r.get(key) or r.get(key) == MINE]


# ══════════════════════════════════════════════════════════════════════════════
# workload.get_user_workload — raw task rows
# ══════════════════════════════════════════════════════════════════════════════

class _Result:
    def __init__(self, data):
        self.data = data


class _TasksQuery:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def neq(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def or_(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return _Result(self.rows)


class _Db:
    def __init__(self, users, tasks):
        self._users, self._tasks = users, tasks

    def table(self, name):
        if name == "users":
            return _TasksQuery(self._users)
        if name == "tasks":
            return _TasksQuery(self._tasks)
        return _TasksQuery([])


def test_a_colleagues_task_rows_outside_your_book_are_not_returned(monkeypatch):
    tasks = [
        {"id": "T1", "status": "open", "due_date": "2000-01-01", "client_id": MINE,
         "title": "mine"},
        {"id": "T2", "status": "open", "due_date": "2000-01-01", "client_id": THEIRS,
         "title": "SECRET client work"},
    ]
    monkeypatch.setattr(wl, "_get_db", lambda: _Db({"id": "u2", "full_name": "Colleague"}, tasks))
    monkeypatch.setattr(wl, "filter_by_client", _only_mine)

    out = wl.get_user_workload("u2", current_user=USER)
    assert out["data"]["summary"]["total_open"] == 1
    assert [t["id"] for t in out["data"]["overdue_tasks"]] == ["T1"]
    assert "SECRET client work" not in str(out)


def test_your_own_clients_task_rows_still_come_back(monkeypatch):
    tasks = [{"id": "T1", "status": "open", "due_date": "2000-01-01",
              "client_id": MINE, "title": "mine"}]
    monkeypatch.setattr(wl, "_get_db", lambda: _Db({"id": "u2"}, tasks))
    monkeypatch.setattr(wl, "filter_by_client", _only_mine)
    out = wl.get_user_workload("u2", current_user=USER)
    assert out["data"]["overdue_tasks"][0]["title"] == "mine"


# ══════════════════════════════════════════════════════════════════════════════
# workload.get_team_workload — per-colleague counts
# ══════════════════════════════════════════════════════════════════════════════

def test_team_workload_counts_only_tasks_in_your_book(monkeypatch):
    users = [{"id": "u2", "full_name": "Colleague", "email": "c@f", "role": "Executive"}]
    tasks = [
        {"id": "T1", "assignee_id": "u2", "status": "open", "client_id": MINE},
        {"id": "T2", "assignee_id": "u2", "status": "open", "client_id": THEIRS},
        {"id": "T3", "assignee_id": "u2", "status": "open", "client_id": THEIRS},
    ]
    monkeypatch.setattr(wl, "_get_db", lambda: _Db(users, tasks))
    monkeypatch.setattr(wl, "filter_by_client", _only_mine)
    monkeypatch.setattr(wl.capacity_repo, "capacity_map", lambda firm_id: {})
    monkeypatch.setattr(wl, "_minutes_logged_this_week", lambda db, firm_id: {})

    out = wl.get_team_workload(current_user=USER)
    member = out["data"]["members"][0]
    assert member["active_tasks"] == 1          # not 3
    assert out["data"]["total_active_tasks"] == 1


def test_the_client_id_column_is_actually_selected(monkeypatch):
    """The narrowing is only possible because client_id is in the SELECT list —
    without it every row would have client_id=None and survive the filter.
    Pinned because it is easy to 'tidy' an unused-looking column away."""
    import inspect
    src = inspect.getsource(wl.get_team_workload)
    selects = [line for line in src.splitlines() if '.table("tasks").select(' in line]
    assert selects, "task selects not found — did the query shape change?"
    for line in selects:
        assert "client_id" in line, f"client_id missing from: {line.strip()}"


# ══════════════════════════════════════════════════════════════════════════════
# team.list_team
# ══════════════════════════════════════════════════════════════════════════════

def test_team_roster_workload_counts_only_tasks_in_your_book(monkeypatch):
    members = [{"id": "u2", "full_name": "Colleague"}]
    tasks = [{"id": "T1", "client_id": MINE}, {"id": "T2", "client_id": THEIRS}]
    monkeypatch.setattr(tm.user_repo, "find_all", lambda **kw: members)
    monkeypatch.setattr(tm.task_repo, "find_all", lambda **kw: tasks)
    monkeypatch.setattr(tm, "filter_by_client", _only_mine)

    seen = {}
    monkeypatch.setattr(tm, "compute_team_workload",
                        lambda tasks_, members_: seen.setdefault("tasks", tasks_) or [])
    tm.list_team(current_user=USER)
    assert [t["id"] for t in seen["tasks"]] == ["T1"]


def test_team_roster_still_returns_the_members(monkeypatch):
    """A narrowing of TASKS, not of the roster — every colleague still shows."""
    members = [{"id": "u2"}, {"id": "u3"}]
    monkeypatch.setattr(tm.user_repo, "find_all", lambda **kw: members)
    monkeypatch.setattr(tm.task_repo, "find_all", lambda **kw: [])
    monkeypatch.setattr(tm, "filter_by_client", _only_mine)
    monkeypatch.setattr(tm, "compute_team_workload",
                        lambda tasks_, members_: [{"user_id": m["id"]} for m in members_])
    out = tm.list_team(current_user=USER)
    assert out["data"]["total"] == 2
