from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from core.authz import filter_by_client
from repositories.capacity_repository import capacity_repo, DEFAULT_WEEKLY_HOURS, DEFAULT_MAX_TASKS

from datetime import date, timedelta

router = APIRouter(prefix="/api/workload", tags=["workload"])


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


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
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
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


@router.get("")
def get_team_workload(current_user: dict = Depends(rbac("workload", "read"))):
    firm_id = current_user.get("firm_id")
    db = _get_db()
    today = date.today().isoformat()
    week_end = (date.today() + timedelta(days=7)).isoformat()

    # Single query for all firm users
    users_result = db.table("users").select("id, full_name, email, role, is_active").eq("firm_id", firm_id).execute()
    users = [u for u in (users_result.data or []) if u.get("is_active") is not False]

    # Single query for all open tasks for the firm
    # M2: client_id is selected purely so these firm-wide reads can be narrowed
    # to the caller's assigned book — every figure below (active/overdue/
    # due-this-week/utilisation, per named colleague) is otherwise computed
    # over every client in the firm. tasks.client_id is NOT NULL (migration 002).
    tasks_result = db.table("tasks").select("id, assigned_to, assignee_id, status, due_date, priority, client_id").eq("firm_id", firm_id).neq("status", "completed").execute()
    tasks = filter_by_client(current_user, tasks_result.data or [])

    # Single query for recently completed (this month)
    month_start = date.today().replace(day=1).isoformat()
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
            "utilisation_pct": utilisation,
            "is_overloaded": is_overloaded,
            "is_underutilised": is_underutilised,
        }
        members.append(member)
        if member["is_overloaded"]:
            overloaded.append(member)
        if member["is_underutilised"]:
            underutilised.append(member)

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
    })


@router.get("/{user_id}")
def get_user_workload(user_id: str, current_user: dict = Depends(rbac("workload", "read"))):
    firm_id = current_user.get("firm_id")
    db = _get_db()
    today = date.today().isoformat()
    week_end = (date.today() + timedelta(days=7)).isoformat()

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
