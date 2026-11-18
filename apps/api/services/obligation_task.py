"""A compliance obligation worked as a task on the preparer's list (POST-A-206, the second slice).

WHAT WAS MISSING
    My Work listed the obligations a person is named on beside their tasks, and nothing joined the two: an obligation could not be
    put on anybody's task list, and nothing on a task said which return or deposit it was for. `tasks.compliance_record_id`
    (migration 003) has carried the link since the beginning and nothing wrote it.

WHAT THIS DOES
    * `work_as_task` makes ONE task for an open obligation, linked by `compliance_record_id`: titled from the obligation's own
      label, due on the obligation's own due date (a date the calendar already holds, not a new one), for the obligation's
      client, assigned to its preparer when one is named and can open the client. An obligation that already has an open task
      answers that task and makes no second one; a settled obligation (Filed, Completed, Not Required) has no work left and is
      refused in words. Nothing on the obligation itself changes.
    * `after_task_completed` is asked when a linked task is completed: the obligation moves to Ready For Review through the
      obligation's own transition door (each step validated, audited and on the timeline), from Not Started, Awaiting Documents,
      Overdue or In Progress, by way of In Progress. An obligation already at Ready For Review or beyond is left and said; a
      person without compliance write access is told and nothing moves; a failure never fails the task's own change.
    * `linked_open_tasks` is what My Obligations reads so that an obligation the person is working as their own task is shown
      once, as the task.

WHAT IT DOES NOT DO
    There is no stage checklist on the task (collect data, reconcile, prepare, review, file): that needs the task checklists of
    POST-A-199. No hours are attached: an estimate is the firm's own figure. Nothing is filed: the obligation stops at Ready For
    Review and a person records the filing as before.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from core.exceptions import ValidationError
from core.observability import capture_soft_failure
from domain.practice.compliance_overdue import is_settled
from repositories.task_repository import task_repo

#: Where completing the task takes the obligation, and the steps on the way from each status the obligation can be worked from.
READY_FOR_REVIEW = "Ready For Review"
_PATH_TO_REVIEW: dict[str, tuple[str, ...]] = {
    "Not Started": ("In Progress", READY_FOR_REVIEW),
    "Awaiting Documents": ("In Progress", READY_FOR_REVIEW),
    "Overdue": ("In Progress", READY_FOR_REVIEW),
    "In Progress": (READY_FOR_REVIEW,),
}

#: The answer's `state` after a linked task is completed. Only MOVED means this call moved the obligation.
MOVED = "moved_to_review"
ALREADY_PAST = "already_at_review_or_beyond"
NOT_ALLOWED = "not_allowed"
NOT_MOVED = "not_moved"


def _answer(state: str, message: str, obligation_id: Optional[str]) -> dict[str, Any]:
    return {"state": state, "moved": state == MOVED, "obligation_id": obligation_id, "message": message}


def open_task_for(firm_id: str, record_id: str) -> Optional[dict]:
    """The open task already working this obligation, or None."""
    return next((t for t in task_repo.find_open_linked_to_obligations(firm_id)
                 if str(t.get("compliance_record_id")) == str(record_id)), None)


def linked_open_tasks(firm_id: str) -> dict[str, dict]:
    """Obligation id -> the open task working it, for the firm."""
    out: dict[str, dict] = {}
    for t in task_repo.find_open_linked_to_obligations(firm_id):
        out.setdefault(str(t.get("compliance_record_id")), t)
    return out


def _preparer_who_can_open(firm_id: str, record: dict) -> Optional[str]:
    """The obligation's preparer, when one is named and they can still open its client; None otherwise (the task is then unassigned
    rather than given to somebody who cannot open the work)."""
    preparer = record.get("preparer_id") or record.get("assigned_to")
    if not preparer:
        return None
    try:
        from repositories.user_repository import user_repo
        from core.authz import member_reaches_client
        person = user_repo.find_by_id(str(preparer), firm_id=firm_id)
        if person and person.get("firm_id") == firm_id and member_reaches_client(person, record.get("client_id"), firm_id):
            return str(preparer)
    except Exception as exc:                                    # noqa: BLE001
        capture_soft_failure(exc, operation="obligation_task.preparer", firm_id=firm_id)
    return None


def work_as_task(firm_id: str, record_id: str, actor: Optional[dict] = None) -> dict[str, Any]:
    """Make the one task that works this obligation, or answer the one that already does. Returns `{task, created, message}`."""
    from domain.compliance_record_service import compliance_record_service
    record = compliance_record_service.get_record(record_id, firm_id=firm_id)
    label = record.get("period_label") or record.get("obligation_type") or "this obligation"
    if is_settled(record.get("status")):
        raise ValidationError("status", f"{label} is {record.get('status')}, so there is no work left to put on a task.")
    if not record.get("client_id"):
        raise ValidationError("client_id", f"{label} names no client, and a task belongs to a client.")
    existing = open_task_for(firm_id, record_id)
    if existing:
        return {"task": existing, "created": False,
                "message": f"{label} is already being worked as a task, so no second one was made."}
    assignee = _preparer_who_can_open(firm_id, record)
    now = datetime.now(timezone.utc).isoformat()
    fields: dict[str, Any] = {
        "firm_id": firm_id, "client_id": record["client_id"], "compliance_record_id": record_id,
        "title": f"Prepare {label}",
        "description": f"Worked from the compliance obligation {label}. Completing this task moves the obligation to "
                       f"{READY_FOR_REVIEW}; recording it as filed is still done on the obligation.",
        "status": "todo", "priority": "medium", "due_date": str(record.get("due_date") or "")[:10] or None,
        "completed_at": None, "created_at": now, "updated_at": now,
    }
    if assignee:
        fields["assigned_to"] = assignee
        fields["assignee_id"] = assignee
    task = task_repo.create(fields)
    actor = actor or {}
    try:
        from services.audit_service import log_event
        log_event(firm_id, "task", task["id"], "create", actor_id=actor.get("auth_user_id"), actor_email=actor.get("email"),
                  new_data={"title": task.get("title"), "status": task.get("status"), "assigned_to": assignee,
                            "compliance_record_id": record_id})
    except Exception as exc:                                    # noqa: BLE001
        capture_soft_failure(exc, operation="obligation_task.audit", firm_id=firm_id, task_id=task.get("id"))
    try:
        from repositories.task_extras_repository import task_extras_repo
        task_extras_repo.log_event(task_id=task["id"], event_type="created", firm_id=firm_id, actor_id=actor.get("id"),
                                   actor_name=actor.get("full_name") or actor.get("email"),
                                   new_value={"title": task.get("title"), "compliance_record_id": record_id})
    except Exception as exc:                                    # noqa: BLE001
        capture_soft_failure(exc, operation="obligation_task.timeline", firm_id=firm_id, task_id=task.get("id"))
    who = "its preparer" if assignee else "nobody yet (no preparer who can open the client is named on it)"
    return {"task": task, "created": True,
            "message": f"{label} is now a task, due {fields['due_date'] or 'with no date'}, assigned to {who}. Completing the "
                       f"task moves the obligation to {READY_FOR_REVIEW}."}


def after_task_completed(task: dict, actor: Optional[dict], may_write_compliance: bool) -> Optional[dict[str, Any]]:
    """Move the obligation a just-completed task worked to Ready For Review, and say what became of it; None for a task that works
    no obligation. Never raises: the task IS completed."""
    record_id = task.get("compliance_record_id")
    if not record_id:
        return None
    firm_id = str(task.get("firm_id") or (actor or {}).get("firm_id") or "")
    try:
        from domain.compliance_record_service import compliance_record_service
        from services import compliance_obligation_service as obligations
        record = compliance_record_service.get_record(str(record_id), firm_id=firm_id)
        label = record.get("period_label") or "The obligation"
        path = _PATH_TO_REVIEW.get(str(record.get("status") or ""))
        if path is None:
            return _answer(ALREADY_PAST, f"{label} is {record.get('status')}, so it was left as it is.", record.get("id"))
        if not may_write_compliance:
            return _answer(NOT_ALLOWED, f"{label} was left at {record.get('status')}: moving it needs Compliance access, which "
                                        "yours does not include. Someone who has it can move it to review on Deadlines.",
                           record.get("id"))
        for step in path:
            obligations.transition(firm_id, str(record_id), step, actor=actor)
        return _answer(MOVED, f"{label} is now {READY_FOR_REVIEW}.", record.get("id"))
    except ValidationError as refusal:
        return _answer(NOT_MOVED, f"The obligation was not moved: {getattr(refusal, 'message', None) or refusal}",
                       str(record_id))
    except Exception as exc:                                    # noqa: BLE001
        capture_soft_failure(exc, operation="obligation_task.after_completed", firm_id=firm_id, task_id=task.get("id"))
        return _answer(NOT_MOVED, "The task is completed, but its obligation could not be moved just now. Move it to review on "
                                  "Deadlines.", str(record_id))
