"""
Recurring task generation service.
Scans active recurring configs and generates tasks for those due today or past due.
Ensures idempotency by checking last_generated_at.
"""
import logging
from datetime import date, timedelta, datetime, timezone
from dateutil.relativedelta import relativedelta
from typing import Optional


logger = logging.getLogger("caflow.services")


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _advance_date(current: date, frequency: str) -> date:
    """
    Calculate the next due date based on frequency.
    """
    if frequency == "daily":
        return current + timedelta(days=1)
    if frequency == "weekly":
        return current + timedelta(weeks=1)
    if frequency == "monthly":
        return current + relativedelta(months=1)
    if frequency == "quarterly":
        return current + relativedelta(months=3)
    if frequency == "annual":
        return current + relativedelta(years=1)
    return current + timedelta(days=1)


def _is_already_generated_today(config: dict) -> bool:
    """
    Check if a task was already generated today for this config.
    Ensures idempotency.
    """
    last_generated = config.get("last_generated_at")
    if not last_generated:
        return False

    try:
        last_gen_date = datetime.fromisoformat(last_generated.replace('Z', '+00:00')).date()
        today = date.today()
        return last_gen_date == today
    except Exception:
        return False


def generate_due_recurring_tasks(firm_id: Optional[str] = None) -> list[dict]:
    """
    Generate tasks for all active recurring configs where next_due_date <= today.
    Uses assignment rules to determine assignee. Falls back to config.assignee_id if no rules match.
    Updates next_due_date after each generation.
    Idempotent: skips configs that were already generated today.

    Args:
        firm_id: Optional firm ID to limit generation to a specific firm.

    Returns:
        list[dict] - List of created task objects.
    """
    from repositories.task_extras_repository import task_extras_repo
    from repositories.assignment_rule_repository import assignment_rule_repo
    from repositories.user_repository import user_repo

    db = _get_db()
    today = date.today()
    created_tasks = []

    # Query all active configs with next_due_date <= today
    query = db.table("task_recurring_configs").select("*").eq("is_active", True).lte("next_due_date", today.isoformat())
    if firm_id:
        query = query.eq("firm_id", firm_id)
    result = query.execute()
    configs = result.data or []

    for config in configs:
        try:
            # Idempotency check: skip if already generated today
            if _is_already_generated_today(config):
                logger.info(f"Skipping config {config['id']} - already generated today")
                continue

            # Get title and description from config or template
            title = config.get("title")
            description = config.get("description")
            priority = config.get("priority", "medium")

            if config.get("template_id"):
                try:
                    tpl_result = db.table("task_templates").select("name, description, default_priority").eq("id", config["template_id"]).maybe_single().execute()
                    if tpl_result.data:
                        tpl = tpl_result.data
                        title = title or tpl.get("name")
                        description = description or tpl.get("description")
                        priority = priority or tpl.get("default_priority", "medium")
                except Exception as e:
                    logger.warning(f"Failed to load template {config.get('template_id')}: {str(e)}")

            if not title:
                logger.warning(f"Skipping config {config['id']} - no title found")
                continue

            now = datetime.now(timezone.utc).isoformat()
            due_date = config["next_due_date"]

            # Determine assignee using assignment rules, fallback to config.assignee_id
            assignee_id = config.get("assignee_id")

            # Try to evaluate assignment rules
            try:
                available_users = user_repo.find_all(firm_id=config["firm_id"])
                if available_users:
                    evaluated_assignee = assignment_rule_repo.evaluate_rules(
                        firm_id=config["firm_id"],
                        recurring_config_id=config["id"],
                        available_users=available_users
                    )
                    if evaluated_assignee:
                        assignee_id = evaluated_assignee
            except Exception as e:
                logger.warning(f"Failed to evaluate rules for config {config['id']}: {str(e)}")
                # Use fallback assignee_id from config

            # Create the task
            task_data = {
                "firm_id": config["firm_id"],
                "client_id": config.get("client_id"),
                "title": title,
                "description": description,
                "status": "todo",
                "priority": priority,
                "assigned_to": assignee_id,
                "assignee_id": assignee_id,
                "due_date": due_date,
                "completed_at": None,
                "created_at": now,
                "updated_at": now,
            }

            task_result = db.table("tasks").insert(task_data).execute()
            if task_result.data:
                created_task = task_result.data[0]
                created_tasks.append(created_task)
                logger.info(f"Created recurring task {created_task['id']} from config {config['id']}")

                # Log timeline event
                try:
                    task_extras_repo.log_event(
                        task_id=created_task["id"],
                        event_type="created",
                        firm_id=config["firm_id"],
                        actor_name="Recurring Engine",
                        new_value={
                            "source": "recurring",
                            "config_id": config["id"],
                            "frequency": config["frequency"],
                            "title": title,
                        },
                    )
                except Exception as e:
                    logger.warning(f"Failed to log timeline event for task {created_task['id']}: {str(e)}")

                # Send notification to assignee if assigned
                if assignee_id:
                    try:
                        from services.notification_service import notification_service
                        assignee = user_repo.find_by_id(assignee_id)
                        if assignee:
                            template_name = config.get("title") or title
                            notification_service.notify_recurring_generated(
                                task=created_task,
                                assignee_user=assignee,
                                template_name=template_name,
                            )
                    except Exception as e:
                        logger.warning(f"Failed to create notification for task {created_task['id']}: {str(e)}")

            # Calculate next due date and update config
            try:
                next_date = _advance_date(date.fromisoformat(config["next_due_date"]), config["frequency"])
                db.table("task_recurring_configs").update({
                    "next_due_date": next_date.isoformat(),
                    "last_generated_at": now,
                }).eq("id", config["id"]).execute()
                logger.info(f"Updated config {config['id']}: next_due_date = {next_date.isoformat()}")
            except Exception as e:
                logger.error(f"Failed to update config {config['id']}: {str(e)}")

        except Exception as e:
            logger.error(f"Error processing config {config.get('id')}: {str(e)}", exc_info=True)
            # Continue with next config despite error

    logger.info(f"Recurring task generation completed: {len(created_tasks)} tasks created" + (f" for firm {firm_id}" if firm_id else ""))
    return created_tasks
