"""
Fetches what `domain/practice/capacity_risk` needs, and decides none of it.

THREE READS, EACH BOUNDED BY THE WINDOW. Open tasks with a due date inside the
next quarter, unfiled compliance obligations in the same window, and the firm's
own capacity rows — none of them proportional to transaction volume, and the
tasks read carries `workflow_step_id` so the one effort estimate this product
actually records can be resolved without a fourth query per task.

THE EFFORT ESTIMATE IS A JOIN THAT MAY FIND NOTHING, AND THAT IS THE POINT.
`tasks` has no estimate column (migrations 002 / 063 put one on
`workflow_steps` and `task_templates` instead), so a task generated from a
workflow step has one and everything else does not. The estimates are looked up
for the steps actually referenced — a bounded `.in_` over the distinct ids, not
one read per task — and a task with no step simply carries None, which the
domain module counts rather than averages over.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from core.authz import filter_by_client
from core.db_paging import fetch_all
from core.ist_clock import ist_today
from domain.practice import capacity_risk as rule
from repositories.capacity_repository import DEFAULT_WEEKLY_HOURS

#: Statuses that mean the work is done. Everything else is outstanding —
#: written this way round rather than as a list of live statuses, because
#: migration 002's CHECK carries five and a sixth added later must default to
#: "still to do" rather than silently vanishing from the forecast.
_TASK_DONE = frozenset({"completed", "cancelled"})

#: `compliance_calendar.filing_status` values that mean nothing is owed.
#: 'na' is the CA saying the obligation does not apply to this client, which is
#: a decision and not a gap.
_COMPLIANCE_SETTLED = frozenset({"filed", "na"})


def _effort_by_step(db, step_ids: list[str]) -> dict[str, float]:
    """`workflow_steps.estimated_hours` for the steps some task references."""
    out: dict[str, float] = {}
    for i in range(0, len(step_ids), 200):
        rows = (db.table("workflow_steps")
                .select("id, estimated_hours")
                .in_("id", step_ids[i:i + 200])
                .execute().data) or []
        for r in rows:
            if r.get("estimated_hours") is not None:
                out[str(r["id"])] = float(r["estimated_hours"])
    return out


def capacity_risk(db, current_user: dict, *,
                  weeks_ahead: int = rule.DEFAULT_WEEKS_AHEAD,
                  today: Optional[date] = None) -> dict:
    firm_id = current_user.get("firm_id")
    today = today or ist_today()
    window_end = (rule.monday_of(today) + timedelta(weeks=weeks_ahead)).isoformat()

    # ── tasks ────────────────────────────────────────────────────────────────
    # PAGED: a firm's open task list crosses PostgREST's ~1000-row cap on any
    # real book, and a truncated read reports a quiet quarter. `id` is in the
    # projection because it is fetch_all's cursor; `client_id` because
    # filter_by_client narrows this firm-wide read to the caller's own book.
    tasks = fetch_all(
        lambda: db.table("tasks")
        .select("id, due_date, status, client_id, workflow_step_id, title")
        .eq("firm_id", firm_id)
        .lt("due_date", window_end),
        label="capacity_risk_service.tasks")
    tasks = [t for t in filter_by_client(current_user, tasks)
             if (t.get("status") or "") not in _TASK_DONE]

    step_ids = sorted({str(t["workflow_step_id"]) for t in tasks
                       if t.get("workflow_step_id")})
    effort = _effort_by_step(db, step_ids) if step_ids else {}

    # ── the undated backlog, which the window read CANNOT see ────────────────
    # `.lt("due_date", ...)` excludes NULLs, so a task nobody dated is absent
    # from the fetch above — and `CapacityRisk.undated_items` would be a
    # structural zero reading as "everything is dated", the `capital_wip`
    # shape. Its own bounded read, `is null`, rather than dropping the filter
    # above and narrowing in Python: that would make the main read
    # proportional to the whole task history.
    undated = fetch_all(
        lambda: db.table("tasks")
        .select("id, status, client_id")
        .eq("firm_id", firm_id)
        .is_("due_date", "null"),
        label="capacity_risk_service.undated")
    undated_count = sum(1 for t in filter_by_client(current_user, undated)
                        if (t.get("status") or "") not in _TASK_DONE)

    items: list[rule.DueItem] = []
    task_ids: set[str] = set()
    for t in tasks:
        task_ids.add(str(t["id"]))
        step = t.get("workflow_step_id")
        items.append(rule.DueItem(
            due_date=t.get("due_date") or "",
            source="task",
            effort_hours=effort.get(str(step)) if step else None,
            label=t.get("title"),
        ))

    # ── compliance obligations ───────────────────────────────────────────────
    obligations = fetch_all(
        lambda: db.table("compliance_calendar")
        .select("id, due_date, filing_status, client_id, compliance_type, task_id")
        .eq("firm_id", firm_id)
        .lt("due_date", window_end),
        label="capacity_risk_service.compliance")
    obligations = [o for o in filter_by_client(current_user, obligations)
                   if (o.get("filing_status") or "") not in _COMPLIANCE_SETTLED]

    # ONE PIECE OF WORK, NOT TWO. `compliance_calendar.task_id` (migration 006)
    # means this obligation is already being worked as a task that is in the
    # list above — counting both would double every GSTR-1 in the forecast,
    # which is the biggest population in that table. The fold is COUNTED, not
    # silent: a partner comparing this with the deadline list would otherwise
    # read the difference as the forecast being short.
    folded = 0
    for o in obligations:
        linked = o.get("task_id")
        if linked and str(linked) in task_ids:
            folded += 1
            continue
        items.append(rule.DueItem(
            due_date=o.get("due_date") or "",
            source="compliance",
            effort_hours=None,       # nothing records how long a filing takes
            label=o.get("compliance_type"),
        ))

    # ── the team ─────────────────────────────────────────────────────────────
    users = (db.table("users").select("id, is_active")
             .eq("firm_id", firm_id).execute().data) or []
    active = [u for u in users if u.get("is_active") is not False]
    caps = (db.table("user_capacity").select("user_id, weekly_capacity_hours")
            .eq("firm_id", firm_id).execute().data) or []
    hours_by_user = {str(c["user_id"]): int(c.get("weekly_capacity_hours")
                                            or DEFAULT_WEEKLY_HOURS)
                     for c in caps}

    # The undated tasks are handed in as items with no date; the rule counts
    # them and places none, which is where that decision belongs.
    items.extend(rule.DueItem(due_date="", source="task")
                 for _ in range(undated_count))

    answer = rule.forecast(
        items,
        today=today,
        people=len(active),
        # A member with no capacity row takes the same default the workload
        # screen already applies to them, so the two figures agree.
        configured_weekly_hours=sum(
            hours_by_user.get(str(u["id"]), DEFAULT_WEEKLY_HOURS) for u in active),
        obligations_folded_into_tasks=folded,
        weeks_ahead=weeks_ahead,
    )
    return as_payload(answer)


def as_payload(answer: rule.CapacityRisk) -> dict:
    return {
        "weeks": [
            {
                "week_start": w.week_start,
                "items_due": w.items_due,
                "tasks_due": w.tasks_due,
                "compliance_due": w.compliance_due,
                "estimated_hours": w.estimated_hours,
                "items_without_an_estimate": w.items_without_an_estimate,
                "vs_median_pct": w.vs_median_pct,
                "is_peak": w.is_peak,
            }
            for w in answer.weeks
        ],
        "overdue_items": answer.overdue_items,
        "undated_items": answer.undated_items,
        "obligations_folded_into_tasks": answer.obligations_folded_into_tasks,
        "median_week_items": answer.median_week_items,
        "peak_weeks": list(answer.peak_weeks),
        "people": answer.people,
        "configured_weekly_hours": answer.configured_weekly_hours,
        "peak_multiple": rule.PEAK_MULTIPLE,
        "not_forecast": list(answer.not_forecast),
    }
