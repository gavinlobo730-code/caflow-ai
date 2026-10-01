from datetime import date, datetime, timezone
from typing import Optional
from repositories.escalation_rule_repository import escalation_rule_repo
from repositories.task_repository import task_repo
from repositories.user_repository import user_repo
from repositories.notifications_repository import notifications_repo
from repositories.task_extras_repository import task_extras_repo
from core.ist_clock import ist_today


class EscalationService:
    """Service for managing task escalations based on configurable rules."""

    def escalate_due_soon_tasks(self, firm_id: str, mail_items: Optional[list] = None) -> int:
        """
        Find tasks due soon and create notifications based on escalation rules.

        `mail_items`, when given, collects what each recipient is to be MAILED
        about so `run_all_escalations` can send one mail per person for the
        whole sweep (practice_management-03); the notification above it is
        unchanged.

        Returns:
            Count of escalated tasks
        """
        # Find all non-completed tasks
        tasks = task_repo.find_all(firm_id=firm_id, status=None)
        non_completed = [t for t in tasks if t.get("status") != "completed"]

        escalated_count = 0

        for task in non_completed:
            # Get applicable escalation rules for this task
            applicable_rules = escalation_rule_repo.get_applicable_escalations(firm_id, task)

            # Filter for due_soon rules only
            due_soon_rules = [r for r in applicable_rules if r.get("rule_type") == "due_soon"]

            for rule in due_soon_rules:
                # Create notification
                escalate_to_role = rule.get("escalate_to_role")
                notification = self._create_escalation_notification(
                    firm_id=firm_id,
                    task=task,
                    escalation_type="due_soon",
                    escalate_to_role=escalate_to_role,
                    days_threshold=rule.get("days_threshold")
                )

                if notification:
                    if mail_items is not None:
                        mail_items.append({
                            "recipient_id": notification.get("user_id"),
                            "kind": "due_soon", "task": task,
                            "days_threshold": rule.get("days_threshold"),
                        })
                    # Log to task_escalations table
                    self._log_task_escalation(task["id"], rule["id"], "due_soon")
                    escalated_count += 1

        return escalated_count

    def escalate_overdue_tasks(self, firm_id: str, mail_items: Optional[list] = None) -> int:
        """
        Find overdue tasks and execute escalation actions (reassignment, notifications).

        `mail_items` is the same collector `escalate_due_soon_tasks` fills.

        Returns:
            Count of escalated tasks
        """
        # Find all non-completed tasks
        tasks = task_repo.find_all(firm_id=firm_id, status=None)
        non_completed = [t for t in tasks if t.get("status") != "completed"]

        escalated_count = 0

        for task in non_completed:
            # Get applicable escalation rules for this task
            applicable_rules = escalation_rule_repo.get_applicable_escalations(firm_id, task)

            for rule in applicable_rules:
                rule_type = rule.get("rule_type")

                if rule_type == "reassign_overdue":
                    # Reassign to role with least busy user
                    reassign_to_role = rule.get("reassign_to_role")
                    if reassign_to_role:
                        new_assignee = self._find_least_busy_user(firm_id, reassign_to_role)
                        if new_assignee:
                            old_assignee = task.get("assigned_to")
                            task_repo.update(task["id"], {"assigned_to": new_assignee["id"]})

                            # Log timeline event
                            task_extras_repo.log_event(
                                task_id=task["id"],
                                event_type="escalated_reassigned",
                                firm_id=firm_id,
                                actor_id="system",
                                actor_name="Escalation Engine",
                                old_value={"assigned_to": old_assignee},
                                new_value={"assigned_to": new_assignee["id"]},
                            )

                            # The person the task was just handed to is MAILED too:
                            # a system reassignment is still an assignment, and
                            # this is the one door where nobody was told at all
                            # (no in-app notification exists for them either —
                            # left as it is). No actor: the engine did it.
                            try:
                                from services import practice_mail_service
                                practice_mail_service.task_assigned(
                                    {**task, "assigned_to": new_assignee["id"],
                                     "assignee_id": new_assignee["id"], "firm_id": firm_id},
                                    new_assignee, None)
                            except Exception:  # noqa: BLE001 - mail is best-effort
                                pass

                            # Notify manager
                            manager = self._find_manager_for_task(firm_id, task)
                            if manager and mail_items is not None:
                                mail_items.append({
                                    "recipient_id": manager["id"], "kind": "reassigned",
                                    "task": {**task, "assigned_to": new_assignee["id"],
                                             "assignee_id": new_assignee["id"]},
                                })
                            if manager:
                                notifications_repo.create({
                                    "firm_id": firm_id,
                                    "user_id": manager["id"],
                                    "type": "task_overdue",
                                    "title": f"Task Escalated: {task['title']}",
                                    "body": f"Task '{task['title']}' was overdue and has been reassigned to {new_assignee.get('full_name', 'Unknown')}.",
                                    "severity": "high",
                                    "metadata": {
                                        "task_id": task["id"],
                                        "escalation_rule_id": rule["id"],
                                        "old_assignee_id": old_assignee,
                                        "new_assignee_id": new_assignee["id"],
                                    }
                                })

                            # Log to task_escalations table
                            self._log_task_escalation(task["id"], rule["id"], "reassigned")
                            escalated_count += 1

                elif rule_type == "manager_notify":
                    # Notify manager about overdue task
                    manager = self._find_manager_for_task(firm_id, task)
                    if manager and mail_items is not None:
                        mail_items.append({
                            "recipient_id": manager["id"], "kind": "overdue", "task": task,
                        })
                    if manager:
                        notifications_repo.create({
                            "firm_id": firm_id,
                            "user_id": manager["id"],
                            "type": "task_overdue",
                            "title": f"Overdue Task: {task['title']}",
                            "body": f"Task '{task['title']}' is overdue and assigned to {task.get('assigned_to', 'Unassigned')}.",
                            "severity": "high",
                            "metadata": {
                                "task_id": task["id"],
                                "escalation_rule_id": rule["id"],
                                "days_overdue": (ist_today() - (
                                    datetime.fromisoformat(task["due_date"]).date()
                                    if isinstance(task["due_date"], str)
                                    else task["due_date"]
                                )).days,
                            }
                        })

                        # Log to task_escalations table
                        self._log_task_escalation(task["id"], rule["id"], "overdue")
                        escalated_count += 1

        return escalated_count

    def run_all_escalations(self, firm_id: str) -> dict:
        """
        Run all escalation checks for a firm.

        Returns:
            Dict with counts of escalated tasks by type
        """
        mail_items: list = []
        due_soon_count = self.escalate_due_soon_tasks(firm_id, mail_items)
        overdue_count = self.escalate_overdue_tasks(firm_id, mail_items)

        # THE MAILS (practice_management-03). One per manager for what the
        # escalation rules sent them, and one per ASSIGNEE for their own overdue
        # tasks — weekly after the first, never daily. Both are idempotent
        # against practice_email_log, which matters here more than anywhere:
        # POST /api/tasks/trigger-escalations runs this with no once-a-day flag,
        # and the in-app notifications above are NOT deduplicated, so a second
        # run sent a second notification and (unguarded) would have sent a
        # second mail. Mail never fails the sweep, and the shape returned is
        # unchanged.
        try:
            from services import practice_mail_service
            practice_mail_service.send_escalation_mails(firm_id, mail_items)
            open_tasks = task_repo.find_all(firm_id=firm_id, status=None)
            # A task this very sweep reassigned already told its new owner it was
            # theirs; saying "and it is overdue" in the same minute is two mails
            # about one thing.
            just_handed_over = {str(i["task"]["id"]) for i in mail_items
                                if i.get("kind") == "reassigned"}
            practice_mail_service.send_overdue_task_mails(
                firm_id, [t for t in open_tasks if str(t.get("id")) not in just_handed_over])
        except Exception:  # noqa: BLE001 - mail is best-effort
            pass

        return {
            "due_soon_escalations": due_soon_count,
            "overdue_escalations": overdue_count,
            "total_escalations": due_soon_count + overdue_count,
        }

    def _find_least_busy_user(self, firm_id: str, role: str) -> Optional[dict]:
        """
        Find the least busy user with a given role in the firm.

        Returns:
            User dict or None
        """
        users = user_repo.find_all(firm_id=firm_id, role=role)
        if not users:
            return None

        # For now, return the first user with the role
        # In production, could count assigned tasks per user
        return users[0]

    def _find_manager_for_task(self, firm_id: str, task: dict) -> Optional[dict]:
        """
        Find the manager to notify about task escalation.

        Returns:
            User dict (manager) or None
        """
        # If task is assigned, find their manager
        if task.get("assigned_to"):
            assignee = user_repo.find_by_id(task["assigned_to"], firm_id=firm_id)
            if assignee:
                # Find manager with explicit lookup
                managers = user_repo.find_all(firm_id=firm_id, role="Manager")
                if managers:
                    return managers[0]

        # Otherwise, find any manager in the firm
        managers = user_repo.find_all(firm_id=firm_id, role="Manager")
        if managers:
            return managers[0]

        # Fall back to Partner
        partners = user_repo.find_all(firm_id=firm_id, role="Partner")
        if partners:
            return partners[0]

        return None

    def _create_escalation_notification(
        self,
        firm_id: str,
        task: dict,
        escalation_type: str,
        escalate_to_role: Optional[str] = None,
        days_threshold: int = 0,
    ) -> Optional[dict]:
        """
        Create a notification for task escalation.

        Args:
            firm_id: Firm ID
            task: Task dict
            escalation_type: Type of escalation
            escalate_to_role: Role to notify (Manager, Partner, etc.)
            days_threshold: Days before due date

        Returns:
            Created notification dict or None
        """
        if not escalate_to_role:
            return None

        # Find user with the role to notify
        users = user_repo.find_all(firm_id=firm_id, role=escalate_to_role)
        if not users:
            return None

        # Notify the first user with the role
        user = users[0]

        notification = notifications_repo.create({
            "firm_id": firm_id,
            "user_id": user["id"],
            "type": "due_soon",
            "title": f"Task Due Soon: {task['title']}",
            "body": f"Task '{task['title']}' is due in {days_threshold} day(s).",
            "severity": "medium",
            "metadata": {
                "task_id": task["id"],
                "escalation_type": escalation_type,
                "days_threshold": days_threshold,
            }
        })

        return notification

    def _log_task_escalation(self, task_id: str, escalation_rule_id: str, escalation_type: str) -> dict:
        """
        Log an escalation event to the task_escalations table.

        Args:
            task_id: Task ID
            escalation_rule_id: Escalation rule ID
            escalation_type: Type of escalation

        Returns:
            Created escalation record
        """
        db = _get_db()
        result = db.table("task_escalations").insert({
            "task_id": task_id,
            "escalation_rule_id": escalation_rule_id,
            "escalation_type": escalation_type,
            "escalated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return result.data[0] if result.data else {}


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


escalation_service = EscalationService()
