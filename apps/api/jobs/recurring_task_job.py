"""
Background job for recurring task generation.
Runs once daily to generate tasks for configs where next_due_date is reached.
"""
import logging
from services.recurring_task_service import generate_due_recurring_tasks


logger = logging.getLogger("caflow.jobs")


def run_recurring_generation_job(firm_id: str = None) -> dict:
    """
    Run the recurring task generation job.

    Args:
        firm_id: Optional firm ID to limit generation to a specific firm.
                If None, generates for all firms with due configs.

    Returns:
        dict with 'count' of generated tasks and 'tasks' list
    """
    try:
        created_tasks = generate_due_recurring_tasks(firm_id=firm_id)
        logger.info(f"Recurring task job completed: {len(created_tasks)} tasks generated" + (f" for firm {firm_id}" if firm_id else ""))
        return {
            "success": True,
            "count": len(created_tasks),
            "tasks": created_tasks,
            "error": None,
        }
    except Exception as e:
        logger.error(f"Recurring task job failed: {str(e)}", exc_info=True)
        return {
            "success": False,
            "count": 0,
            "tasks": [],
            "error": str(e),
        }
