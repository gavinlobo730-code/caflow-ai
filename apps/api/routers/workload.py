from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from datetime import date, timedelta

router = APIRouter(prefix="/api/workload", tags=["workload"])


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


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
    tasks_result = db.table("tasks").select("id, assigned_to, assignee_id, status, due_date, priority").eq("firm_id", firm_id).neq("status", "completed").execute()
    tasks = tasks_result.data or []

    # Single query for recently completed (this month)
    month_start = date.today().replace(day=1).isoformat()
    completed_result = db.table("tasks").select("id, assigned_to, assignee_id, updated_at").eq("firm_id", firm_id).eq("status", "completed").gte("updated_at", month_start).execute()
    completed_tasks = completed_result.data or []

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
        utilisation = min(100, round((active / 20) * 100))

        member = {
            "user_id": uid,
            "user_name": u.get("full_name") or u.get("email") or "Unknown",
            "user_email": u.get("email", ""),
            "role": u.get("role", ""),
            "active_tasks": active,
            "overdue_tasks": overdue,
            "due_this_week": due_week,
            "completed_this_week": completed_month,
            "utilisation_pct": utilisation,
            "is_overloaded": active > 15 or overdue > 3,
            "is_underutilised": active < 3,
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

    user_result = db.table("users").select("id, full_name, email, role").eq("id", user_id).maybe_single().execute()
    user = user_result.data

    tasks_result = db.table("tasks").select("*").eq("firm_id", firm_id).or_(f"assigned_to.eq.{user_id},assignee_id.eq.{user_id}").execute()
    tasks = tasks_result.data or []

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
