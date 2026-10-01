from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from core.authz import filter_by_client
from domain.practice import task_estimate
from repositories.capacity_repository import capacity_repo, DEFAULT_WEEKLY_HOURS, DEFAULT_MAX_TASKS
from services import capacity_risk_service

from datetime import date, timedelta
from core.ist_clock import ist_today

router = APIRouter(prefix="/api/workload", tags=["workload"])

#: How many of a person's open tasks ride on their card, and how many unassigned
#: ones ride on the page. The COUNTS are always the whole truth; the lists are
#: what a person can act on from one screen, so the payload is proportional to
#: the answer and not to the size of the firm's task history.
OPEN_TASKS_SHOWN_PER_MEMBER = 8
UNASSIGNED_TASKS_SHOWN = 50

_OPEN_TASK_FIELDS = ("id", "title", "client_id", "due_date", "priority", "status",
                     "estimated_minutes")


def _open_task_row(t: dict) -> dict:
    """The part of an open task a person allocating work needs to see."""
    return {k: t.get(k) for k in _OPEN_TASK_FIELDS}


def _by_urgency(tasks: list[dict]) -> list[dict]:
    """Earliest due first, undated last, id as the tie-break so the same list
    comes back in the same order on every read."""
    return sorted(tasks, key=lambda t: (t.get("due_date") is None,
                                        t.get("due_date") or "", str(t.get("id") or "")))


def _get_db():
    # sweep-team-hub-04: this router reads `public.users` to build the firm's
    # roster (get_team_workload, get_user_workload). Under USE_USER_JWT,
    # get_supabase() returns the CALLER's own JWT client, and `users`' RLS
    # SELECT policy (`users_own_row_select`) shows a caller exactly one row —
    # itself — the same defect `repositories/user_repository.py`'s header
    # documents for the identity router. The service role bypasses that, and
    # every query here already carries its own `.eq("firm_id", …)` (plus
    # filter_by_client on the task rows), which is the tenant boundary per
    # CLAUDE.md's "Tenancy and access" — so this is not a widening of scope.
    from core.supabase_client import get_service_supabase
    return get_service_supabase()


class CapacityUpdate(BaseModel):
    user_id: str
    weekly_capacity_hours: int = Field(DEFAULT_WEEKLY_HOURS, ge=1, le=100)
    max_concurrent_tasks: int = Field(DEFAULT_MAX_TASKS, ge=1, le=100)


@router.get("/capacity")
def list_capacity(current_user: dict = Depends(rbac("workload", "read"))):
    """List configured capacity for all firm users (defaults applied client-side)."""
    firm_id = current_user.get("firm_id")
    rows = capacity_repo.find_all(firm_id=firm_id)
    return api_response(True, {
        "capacities": rows,
        "defaults": {
            "weekly_capacity_hours": DEFAULT_WEEKLY_HOURS,
            "max_concurrent_tasks": DEFAULT_MAX_TASKS,
        },
    })


@router.put("/capacity")
def set_capacity(body: CapacityUpdate, current_user: dict = Depends(rbac("workload", "write"))):
    """Set a user's weekly capacity (Manager+)."""
    firm_id = current_user.get("firm_id")
    record = capacity_repo.upsert(firm_id, body.user_id, {
        "weekly_capacity_hours": body.weekly_capacity_hours,
        "max_concurrent_tasks": body.max_concurrent_tasks,
        "updated_by": current_user.get("id"),
    })
    return api_response(True, {"capacity": record})


def _minutes_logged_this_week(db, firm_id: str) -> dict[str, int]:
    """Minutes logged per user since Monday of the current week."""
    today = ist_today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    try:
        result = (
            db.table("time_entries").select("user_id, duration_minutes")
            .eq("firm_id", firm_id).gte("started_at", week_start).execute()
        )
        minutes: dict[str, int] = {}
        for e in result.data or []:
            if e.get("duration_minutes"):
                minutes[e["user_id"]] = minutes.get(e["user_id"], 0) + e["duration_minutes"]
        return minutes
    except Exception:
        return {}


@router.get("/capacity-risk")
def capacity_risk_forecast(
    weeks_ahead: int = Query(13, ge=4, le=26),
    current_user: dict = Depends(rbac("workload", "read")),
):
    """Which of the next weeks the practice is about to be short-staffed for.

    THE FORWARD-LOOKING HALF OF THIS ROUTER. `GET /api/workload` and
    `compute_workload_insights` both describe TODAY — who has too many tasks
    open right now. Neither can tell a partner that the week of 8 December is
    four times an ordinary week because sixty clients' GSTR-3B and a quarterly
    TDS statement land in it together, which is the only version of this
    question they can still act on.

    `domain/practice/capacity_risk` is the rule and refuses two temptations it
    would be easy to give in to: it never averages an effort estimate over the
    tasks that carry none, and it never treats `max_concurrent_tasks` as a
    weekly throughput. Load is measured against the practice's own median week.

    Assignment-scoped through `filter_by_client`, like every other firm-wide
    read here, so a Manager sees the risk in their own book.

    Uses the SAME service-role client as the rest of this router (see
    `_get_db`'s docstring) — `capacity_risk_service.capacity_risk` reads
    `users` for the roster alongside `tasks`/`compliance_calendar`/
    `user_capacity`, and a caller-JWT client would silently under-report the
    team to "1 person" the same way `get_team_workload` did."""
    try:
        return api_response(True, capacity_risk_service.capacity_risk(
            _get_db(), current_user, weeks_ahead=weeks_ahead))
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("")
def get_team_workload(current_user: dict = Depends(rbac("workload", "read"))):
    firm_id = current_user.get("firm_id")
    db = _get_db()
    today = ist_today().isoformat()
    week_end = (ist_today() + timedelta(days=7)).isoformat()

    # Single query for all firm users
    users_result = db.table("users").select("id, full_name, email, role, is_active").eq("firm_id", firm_id).execute()
    users = [u for u in (users_result.data or []) if u.get("is_active") is not False]

    # Single query for all open tasks for the firm
    # M2: client_id is selected purely so these firm-wide reads can be narrowed
    # to the caller's assigned book — every figure below (active/overdue/
    # due-this-week/utilisation, per named colleague) is otherwise computed
    # over every client in the firm. tasks.client_id is NOT NULL (migration 002).
    # `title` and `estimated_minutes` are selected so the SAME read that counts
    # each person's open work can say what it is and how long it is expected to
    # take — the screen that used to answer "who is loaded" from a task count and
    # a per-role constant is retired (practice_management-24), and this is the one
    # model it is merged into.
    tasks_result = db.table("tasks").select("id, title, assigned_to, assignee_id, status, due_date, priority, client_id, estimated_minutes").eq("firm_id", firm_id).neq("status", "completed").execute()
    tasks = filter_by_client(current_user, tasks_result.data or [])

    # Single query for recently completed (this month)
    month_start = ist_today().replace(day=1).isoformat()
    completed_result = db.table("tasks").select("id, assigned_to, assignee_id, updated_at, client_id").eq("firm_id", firm_id).eq("status", "completed").gte("updated_at", month_start).execute()
    completed_tasks = filter_by_client(current_user, completed_result.data or [])

    # Aggregate per user in Python — avoids N+1
    def get_uid(t: dict) -> str:
        return t.get("assignee_id") or t.get("assigned_to") or ""

    user_tasks: dict[str, list] = {u["id"]: [] for u in users}
    for t in tasks:
        uid = get_uid(t)
        if uid in user_tasks:
            user_tasks[uid].append(t)

    user_completed: dict[str, int] = {u["id"]: 0 for u in users}
    for t in completed_tasks:
        uid = get_uid(t)
        if uid in user_completed:
            user_completed[uid] += 1

    # Capacity configuration + actual time logged this week
    capacity_map = capacity_repo.capacity_map(firm_id)
    minutes_logged = _minutes_logged_this_week(db, firm_id)

    members = []
    overloaded = []
    underutilised = []

    for u in users:
        uid = u["id"]
        utasks = user_tasks.get(uid, [])
        active = len(utasks)
        overdue = sum(1 for t in utasks if t.get("due_date") and t["due_date"] < today)
        due_week = sum(1 for t in utasks if t.get("due_date") and today <= t["due_date"] <= week_end)
        completed_month = user_completed.get(uid, 0)

        # What this person's open work is EXPECTED to take, where anybody said:
        # the recorded minutes are totalled and the tasks that carry none are
        # counted beside them, never averaged over (`domain/practice/task_estimate`).
        expected = task_estimate.summarise(t.get("estimated_minutes") for t in utasks)

        cap = capacity_map.get(uid, {})
        weekly_hours = cap.get("weekly_capacity_hours", DEFAULT_WEEKLY_HOURS)
        max_tasks = cap.get("max_concurrent_tasks", DEFAULT_MAX_TASKS)
        logged_min = minutes_logged.get(uid, 0)

        # Utilisation = time logged this week vs configured weekly capacity.
        # Falls back to task-count utilisation when no time has been logged.
        if logged_min > 0:
            utilisation = round((logged_min / (weekly_hours * 60)) * 100)
        else:
            utilisation = min(100, round((active / max(max_tasks, 1)) * 100))

        is_overloaded = utilisation > 100 or active > max_tasks or overdue > 3
        is_underutilised = utilisation < 40 and active < 3

        member = {
            "user_id": uid,
            "user_name": u.get("full_name") or u.get("email") or "Unknown",
            "user_email": u.get("email", ""),
            "role": u.get("role", ""),
            "active_tasks": active,
            "overdue_tasks": overdue,
            "due_this_week": due_week,
            "completed_this_week": completed_month,
            "weekly_capacity_hours": weekly_hours,
            "max_concurrent_tasks": max_tasks,
            "minutes_logged_this_week": logged_min,
            "estimated_open_minutes": expected.minutes,
            "open_tasks_without_estimate": expected.without_estimate,
            "open_tasks": [_open_task_row(t) for t in
                           _by_urgency(utasks)[:OPEN_TASKS_SHOWN_PER_MEMBER]],
            "utilisation_pct": utilisation,
            "is_overloaded": is_overloaded,
            "is_underutilised": is_underutilised,
        }
        members.append(member)
        if member["is_overloaded"]:
            overloaded.append(member)
        if member["is_underutilised"]:
            underutilised.append(member)

    # The population no member card shows: an open task with nobody on it. It is
    # in no person's count and no utilisation figure, so it is the work most
    # likely to go missing — and it is what the retired Work Allocation screen
    # was the only place to see.
    unassigned_tasks = [t for t in tasks if not get_uid(t)]
    unassigned_expected = task_estimate.summarise(
        t.get("estimated_minutes") for t in unassigned_tasks)

    total_active = sum(m["active_tasks"] for m in members)
    total_overdue = sum(m["overdue_tasks"] for m in members)
    avg_util = round(sum(m["utilisation_pct"] for m in members) / len(members)) if members else 0

    members.sort(key=lambda m: m["active_tasks"], reverse=True)

    return api_response(True, {
        "members": members,
        "total_active_tasks": total_active,
        "total_overdue_tasks": total_overdue,
        "overloaded_count": len(overloaded),
        "underutilised_count": len(underutilised),
        "avg_utilisation_pct": avg_util,
        "unassigned": {
            "count": len(unassigned_tasks),
            "estimated_minutes": unassigned_expected.minutes,
            "without_estimate": unassigned_expected.without_estimate,
            "tasks": [_open_task_row(t) for t in
                      _by_urgency(unassigned_tasks)[:UNASSIGNED_TASKS_SHOWN]],
        },
    })


@router.get("/{user_id}")
def get_user_workload(user_id: str, current_user: dict = Depends(rbac("workload", "read"))):
    firm_id = current_user.get("firm_id")
    db = _get_db()
    today = ist_today().isoformat()
    week_end = (ist_today() + timedelta(days=7)).isoformat()

    # H1 fix: scope the user lookup to the caller's firm so a cross-firm user_id
    # cannot disclose another firm's user PII. 404 (not 403) — existence hidden.
    user_result = db.table("users").select("id, full_name, email, role").eq("id", user_id).eq("firm_id", firm_id).maybe_single().execute()
    user = user_result.data
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # M2: this returns FULL task rows (title, description, due_date, client_id)
    # in overdue_tasks/due_today, not just counts — so without narrowing, any
    # Executive could read the substance of a colleague's work on clients
    # outside their own assigned book.
    tasks_result = db.table("tasks").select("*").eq("firm_id", firm_id).or_(f"assigned_to.eq.{user_id},assignee_id.eq.{user_id}").execute()
    tasks = filter_by_client(current_user, tasks_result.data or [])

    open_tasks = [t for t in tasks if t["status"] != "completed"]
    overdue = [t for t in open_tasks if t.get("due_date") and t["due_date"] < today]
    due_today = [t for t in open_tasks if t.get("due_date") == today]
    due_week = [t for t in open_tasks if t.get("due_date") and today < t["due_date"] <= week_end]
    completed = [t for t in tasks if t["status"] == "completed"]

    by_status: dict[str, list] = {}
    for t in open_tasks:
        s = t.get("status", "unknown")
        if s not in by_status:
            by_status[s] = []
        by_status[s].append(t)

    return api_response(True, {
        "user": user,
        "summary": {
            "total_open": len(open_tasks),
            "overdue": len(overdue),
            "due_today": len(due_today),
            "due_this_week": len(due_week),
            "completed_total": len(completed),
        },
        "by_status": by_status,
        "overdue_tasks": overdue,
        "due_today": due_today,
    })
