"""
Notification service for task lifecycle events.
Handles auto-notification creation on task assignment, reassignment, due soon, overdue, and recurring task generation.
"""
from typing import Optional
from repositories.notifications_repository import notifications_repo
from repositories.user_repository import user_repo
from repositories.client_repository import client_repo


def _mail_new_assignee(task: dict, assignee: dict, assigned_by: Optional[dict]) -> None:
    """One mail to a task's new assignee. Never raises and never blocks the
    assignment — `practice_mail_service.task_assigned` owns the rules (the
    person's own preference, a self-assignment, the record of the send)."""
    try:
        from services import practice_mail_service
        practice_mail_service.task_assigned(task, assignee, assigned_by)
    except Exception:                                           # noqa: BLE001
        import logging
        logging.getLogger("caflow").warning("task-assigned mail failed", exc_info=True)


class NotificationService:
    """Helper class to manage task lifecycle notifications."""

    @staticmethod
    def notify_task_assigned(task: dict, assignee_user: dict, created_by_user: dict) -> Optional[dict]:
        """
        Create notification when task is assigned.
        Type: 'task_assigned'
        Severity: 'info'
        """
        notification = None
        try:
            client = client_repo.find_by_id(task.get("client_id"))
            client_name = client.get("client_name", "Unknown Client") if client else "Unknown Client"
            due_date = task.get("due_date", "Not set")

            notification = notifications_repo.create({
                "firm_id": task.get("firm_id"),
                "user_id": assignee_user.get("id"),
                "type": "task_assigned",
                "title": f"New task assigned: {task.get('title')}",
                "body": f"Client: {client_name}, Due: {due_date}",
                "severity": "info",
                "client_id": task.get("client_id"),
                "metadata": {
                    "task_id": task.get("id"),
                    "assigned_by": created_by_user.get("full_name") or created_by_user.get("email"),
                },
                "is_read": False,
                "is_archived": False,
            })
        except Exception as e:
            import logging
            logging.getLogger("caflow").error(f"Failed to create task_assigned notification: {e}")
        # The mail is the SAME event as the in-app notification and is attempted
        # whether or not that write worked, so a failed notification does not
        # also silence the one channel the assignee reads away from the screen
        # (practice_management-03). `task_assigned` never raises.
        _mail_new_assignee(task, assignee_user, created_by_user)
        return notification

    @staticmethod
    def notify_task_reassigned(task: dict, old_assignee: dict, new_assignee: dict, reason: str,
                               reassigned_by: Optional[dict] = None) -> list[dict]:
        """
        Create notifications when task is reassigned.
        Two notifications: one to old assignee (reassigned away), one to new assignee (reassigned to).
        Severity: 'info'

        The NEW assignee is also mailed — to them a reassignment is an assignment
        (practice_management-03) — unless they are the person who did it.
        """
        notifications = []
        try:
            client = client_repo.find_by_id(task.get("client_id"))
            client_name = client.get("client_name", "Unknown Client") if client else "Unknown Client"

            # Notification to old assignee
            try:
                old_notif = notifications_repo.create({
                    "firm_id": task.get("firm_id"),
                    "user_id": old_assignee.get("id"),
                    "type": "task_reassigned",
                    "title": f"Task reassigned from you: {task.get('title')}",
                    "body": f"Task reassigned to {new_assignee.get('full_name')} due to: {reason}",
                    "severity": "info",
                    "client_id": task.get("client_id"),
                    "metadata": {
                        "task_id": task.get("id"),
                        "old_assignee_id": old_assignee.get("id"),
                        "new_assignee_id": new_assignee.get("id"),
                        "reason": reason,
                    },
                    "is_read": False,
                    "is_archived": False,
                })
                notifications.append(old_notif)
            except Exception as e:
                import logging
                logging.getLogger("caflow").error(f"Failed to create reassignment notification for old assignee: {e}")

            # Notification to new assignee
            try:
                new_notif = notifications_repo.create({
                    "firm_id": task.get("firm_id"),
                    "user_id": new_assignee.get("id"),
                    "type": "task_reassigned",
                    "title": f"Task reassigned to you: {task.get('title')}",
                    "body": f"Client: {client_name}, Due: {task.get('due_date', 'Not set')}. Reason: {reason}",
                    "severity": "info",
                    "client_id": task.get("client_id"),
                    "metadata": {
                        "task_id": task.get("id"),
                        "old_assignee_id": old_assignee.get("id"),
                        "new_assignee_id": new_assignee.get("id"),
                        "reason": reason,
                    },
                    "is_read": False,
                    "is_archived": False,
                })
                notifications.append(new_notif)
            except Exception as e:
                import logging
                logging.getLogger("caflow").error(f"Failed to create reassignment notification for new assignee: {e}")

            return notifications
        except Exception as e:
            import logging
            logging.getLogger("caflow").error(f"Failed to create task_reassigned notifications: {e}")
            return []
        finally:
            # Attempted whether or not the in-app notifications above worked —
            # see notify_task_assigned.
            _mail_new_assignee(task, new_assignee, reassigned_by)

    @staticmethod
    def notify_due_soon(task: dict, assignee_user: dict) -> Optional[dict]:
        """
        Create notification when task is due in 3 days.
        Type: 'due_soon'
        Severity: 'warning'
        """
        try:
            client = client_repo.find_by_id(task.get("client_id"))
            client_name = client.get("client_name", "Unknown Client") if client else "Unknown Client"

            notification = notifications_repo.create({
                "firm_id": task.get("firm_id"),
                "user_id": assignee_user.get("id"),
                "type": "due_soon",
                "title": f"Task due in 3 days: {task.get('title')}",
                "body": f"Client: {client_name}, Due date: {task.get('due_date', 'Not set')}",
                "severity": "medium",
                "client_id": task.get("client_id"),
                "metadata": {
                    "task_id": task.get("id"),
                },
                "is_read": False,
                "is_archived": False,
            })
            return notification
        except Exception as e:
            import logging
            logging.getLogger("caflow").error(f"Failed to create due_soon notification: {e}")
            return None

    @staticmethod
    def notify_overdue(task: dict, assignee_user: dict, manager_user: Optional[dict] = None) -> list[dict]:
        """
        Create notifications when task is overdue.
        Notification to assignee: "Task overdue: {task.title}"
        Notification to manager: "Team member task overdue: {assignee.name} - {task.title}"
        Severity: 'critical'
        """
        notifications = []
        try:
            client = client_repo.find_by_id(task.get("client_id"))
            client_name = client.get("client_name", "Unknown Client") if client else "Unknown Client"

            # Notification to assignee
            try:
                assignee_notif = notifications_repo.create({
                    "firm_id": task.get("firm_id"),
                    "user_id": assignee_user.get("id"),
                    "type": "overdue",
                    "title": f"Task overdue: {task.get('title')}",
                    "body": f"Client: {client_name}, Was due: {task.get('due_date', 'Not set')}. Please prioritize this task.",
                    "severity": "critical",
                    "client_id": task.get("client_id"),
                    "metadata": {
                        "task_id": task.get("id"),
                    },
                    "is_read": False,
                    "is_archived": False,
                })
                notifications.append(assignee_notif)
            except Exception as e:
                import logging
                logging.getLogger("caflow").error(f"Failed to create overdue notification for assignee: {e}")

            # Notification to manager if provided
            if manager_user:
                try:
                    manager_notif = notifications_repo.create({
                        "firm_id": task.get("firm_id"),
                        "user_id": manager_user.get("id"),
                        "type": "overdue",
                        "title": f"Team member task overdue: {assignee_user.get('full_name')}",
                        "body": f"{assignee_user.get('full_name')} has overdue task '{task.get('title')}' (Client: {client_name}, Was due: {task.get('due_date', 'Not set')})",
                        "severity": "critical",
                        "client_id": task.get("client_id"),
                        "metadata": {
                            "task_id": task.get("id"),
                            "assignee_id": assignee_user.get("id"),
                        },
                        "is_read": False,
                        "is_archived": False,
                    })
                    notifications.append(manager_notif)
                except Exception as e:
                    import logging
                    logging.getLogger("caflow").error(f"Failed to create overdue notification for manager: {e}")

            return notifications
        except Exception as e:
            import logging
            logging.getLogger("caflow").error(f"Failed to create overdue notifications: {e}")
            return []

    @staticmethod
    def notify_recurring_generated(task: dict, assignee_user: dict, template_name: str) -> Optional[dict]:
        """
        Create notification when recurring task is generated.
        Type: 'recurring_generated'
        Severity: 'info'
        """
        try:
            client = client_repo.find_by_id(task.get("client_id"))
            client_name = client.get("client_name", "Unknown Client") if client else "Unknown Client"

            notification = notifications_repo.create({
                "firm_id": task.get("firm_id"),
                "user_id": assignee_user.get("id"),
                "type": "recurring_generated",
                "title": f"New {template_name} task created",
                "body": f"Client: {client_name}, Due: {task.get('due_date', 'Not set')}",
                "severity": "info",
                "client_id": task.get("client_id"),
                "metadata": {
                    "task_id": task.get("id"),
                    "template_name": template_name,
                    "source": "recurring",
                },
                "is_read": False,
                "is_archived": False,
            })
            return notification
        except Exception as e:
            import logging
            logging.getLogger("caflow").error(f"Failed to create recurring_generated notification: {e}")
            return None


notification_service = NotificationService()
