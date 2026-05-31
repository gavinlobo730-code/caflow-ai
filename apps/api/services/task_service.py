"""
Task management service.
Handles task lifecycle, status transitions, and workload calculations.
"""
from datetime import date, datetime, timezone
from typing import Optional


VALID_TRANSITIONS: dict[str, list[str]] = {
    "todo":             ["in_progress", "waiting_client"],
    "in_progress":      ["todo", "waiting_client", "review_required", "completed"],
    "waiting_client":   ["in_progress", "todo"],
    "review_required":  ["in_progress", "completed"],
    "completed":        [],
}


def is_valid_transition(current: str, next_status: str) -> bool:
    return next_status in VALID_TRANSITIONS.get(current, [])


def compute_task_urgency(due_date_str: Optional[str], status: str) -> str:
    if status == "completed":
        return "none"
    if not due_date_str:
        return "low"
    due = date.fromisoformat(due_date_str)
    days = (due - date.today()).days
    if days < 0:
        return "overdue"
    if days <= 1:
        return "critical"
    if days <= 3:
        return "high"
    if days <= 7:
        return "medium"
    return "low"


def group_tasks_by_status(tasks: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {
        "todo": [],
        "in_progress": [],
        "waiting_client": [],
        "review_required": [],
        "completed": [],
    }
    for task in tasks:
        s = task.get("status", "todo")
        if s in groups:
            groups[s].append(task)
    return groups


def compute_team_workload(tasks: list[dict], team_members: list[dict]) -> list[dict]:
    """
    Compute workload percentage per team member.
    Workload % = open tasks assigned / total open tasks * 100
    """
    open_tasks = [t for t in tasks if t["status"] != "completed"]
    total = len(open_tasks)
    result = []
    for member in team_members:
        assigned = [t for t in open_tasks if t.get("assigned_to") == member["id"]]
        completed = [t for t in tasks if t.get("assigned_to") == member["id"] and t["status"] == "completed"]
        result.append({
            **member,
            "assigned_open_tasks": len(assigned),
            "completed_tasks": len(completed),
            "workload_pct": round((len(assigned) / total * 100) if total > 0 else 0, 1),
        })
    return result
