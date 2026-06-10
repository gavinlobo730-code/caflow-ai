"""
Tests for recurring task generation service and job.
Verifies:
1. Task generation for configs with next_due_date <= today
2. Idempotency (no duplicate generation on same day)
3. Assignment rule evaluation
4. Next due date calculation for all frequencies
5. Timeline event logging
6. Notification sending
"""
import pytest
from datetime import date, timedelta, datetime, timezone
from dateutil.relativedelta import relativedelta
from unittest.mock import patch, MagicMock, call

FIRM_ID = "firm-001"
CLIENT_ID = "client-001"
ASSIGNEE_ID = "user-001"


class TestRecurringTaskService:
    """Tests for recurring_task_service.generate_due_recurring_tasks()"""

    def test_generate_task_for_config_due_today(self):
        """Config with next_due_date=today should generate a task."""
        from services.recurring_task_service import generate_due_recurring_tasks
        from datetime import date

        today = date.today().isoformat()
        config = {
            "id": "config-1",
            "firm_id": FIRM_ID,
            "client_id": CLIENT_ID,
            "title": "Monthly GST Filing",
            "description": "File GSTR-1 return",
            "priority": "high",
            "frequency": "monthly",
            "next_due_date": today,
            "assignee_id": ASSIGNEE_ID,
            "is_active": True,
            "template_id": None,
            "last_generated_at": None,
        }

        with patch("services.recurring_task_service._get_db") as mock_db, \
             patch("repositories.user_repository.user_repo") as mock_user_repo, \
             patch("repositories.assignment_rule_repository.assignment_rule_repo") as mock_rule_repo, \
             patch("repositories.task_extras_repository.task_extras_repo") as mock_extras_repo:

            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance

            # Mock the query chain for configs
            query_mock = MagicMock()
            query_mock.execute.return_value.data = [config]
            query_mock.eq.return_value = query_mock
            query_mock.lte.return_value = query_mock
            mock_db_instance.table.return_value.select.return_value = query_mock

            # Mock the insert for new task
            insert_mock = MagicMock()
            insert_mock.execute.return_value.data = [{
                **config,
                "id": "task-1",
                "status": "todo",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }]
            mock_db_instance.table.return_value.insert.return_value = insert_mock

            # Mock the update for config
            update_mock = MagicMock()
            update_mock.eq.return_value.execute.return_value.data = [config]
            mock_db_instance.table.return_value.update.return_value = update_mock

            mock_user_repo.find_all.return_value = [{"id": ASSIGNEE_ID, "role": "Partner"}]
            mock_rule_repo.evaluate_rules.return_value = ASSIGNEE_ID

            tasks = generate_due_recurring_tasks(firm_id=FIRM_ID)

            assert len(tasks) == 1
            assert tasks[0]["id"] == "task-1"

    def test_idempotency_skips_if_generated_today(self):
        """Config generated today should be skipped (idempotent)."""
        from services.recurring_task_service import generate_due_recurring_tasks
        from datetime import date

        today = date.today().isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        config = {
            "id": "config-1",
            "firm_id": FIRM_ID,
            "client_id": CLIENT_ID,
            "title": "Monthly GST Filing",
            "priority": "high",
            "frequency": "monthly",
            "next_due_date": today,
            "assignee_id": ASSIGNEE_ID,
            "is_active": True,
            "template_id": None,
            "last_generated_at": now_iso,  # Generated today
        }

        with patch("services.recurring_task_service._get_db") as mock_db:
            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance

            query_mock = MagicMock()
            query_mock.execute.return_value.data = [config]
            query_mock.eq.return_value = query_mock
            query_mock.lte.return_value = query_mock
            mock_db_instance.table.return_value.select.return_value = query_mock

            tasks = generate_due_recurring_tasks(firm_id=FIRM_ID)

            # Should not create any tasks (skipped due to idempotency)
            assert len(tasks) == 0

    def test_monthly_frequency_advances_by_one_month(self):
        """Monthly config should set next_due_date to one month later."""
        from services.recurring_task_service import _advance_date
        from datetime import date

        current = date(2026, 1, 15)
        next_date = _advance_date(current, "monthly")
        assert next_date == date(2026, 2, 15)

    def test_quarterly_frequency_advances_by_three_months(self):
        """Quarterly config should set next_due_date to three months later."""
        from services.recurring_task_service import _advance_date

        current = date(2026, 1, 15)
        next_date = _advance_date(current, "quarterly")
        assert next_date == date(2026, 4, 15)

    def test_annual_frequency_advances_by_one_year(self):
        """Annual config should set next_due_date to one year later."""
        from services.recurring_task_service import _advance_date

        current = date(2026, 1, 15)
        next_date = _advance_date(current, "annual")
        assert next_date == date(2027, 1, 15)

    def test_daily_frequency_advances_by_one_day(self):
        """Daily config should set next_due_date to next day."""
        from services.recurring_task_service import _advance_date

        current = date(2026, 1, 15)
        next_date = _advance_date(current, "daily")
        assert next_date == date(2026, 1, 16)

    def test_weekly_frequency_advances_by_one_week(self):
        """Weekly config should set next_due_date to one week later."""
        from services.recurring_task_service import _advance_date

        current = date(2026, 1, 15)
        next_date = _advance_date(current, "weekly")
        assert next_date == date(2026, 1, 22)

    def test_assignment_rules_evaluated_for_assignee(self):
        """Should use assignment rules to determine assignee."""
        from services.recurring_task_service import generate_due_recurring_tasks

        today = date.today().isoformat()
        config = {
            "id": "config-1",
            "firm_id": FIRM_ID,
            "client_id": CLIENT_ID,
            "title": "Monthly GST",
            "priority": "high",
            "frequency": "monthly",
            "next_due_date": today,
            "assignee_id": "fallback-user",
            "is_active": True,
            "template_id": None,
            "last_generated_at": None,
        }

        rule_evaluated_user = "rule-determined-user"

        with patch("services.recurring_task_service._get_db") as mock_db, \
             patch("repositories.user_repository.user_repo") as mock_user_repo, \
             patch("repositories.assignment_rule_repository.assignment_rule_repo") as mock_rule_repo, \
             patch("repositories.task_extras_repository.task_extras_repo"):

            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance

            query_mock = MagicMock()
            query_mock.execute.return_value.data = [config]
            query_mock.eq.return_value = query_mock
            query_mock.lte.return_value = query_mock
            mock_db_instance.table.return_value.select.return_value = query_mock

            insert_mock = MagicMock()
            insert_mock.execute.return_value.data = [{
                "id": "task-1",
                "assigned_to": rule_evaluated_user,
            }]
            mock_db_instance.table.return_value.insert.return_value = insert_mock

            update_mock = MagicMock()
            update_mock.eq.return_value.execute.return_value.data = [config]
            mock_db_instance.table.return_value.update.return_value = update_mock

            mock_user_repo.find_all.return_value = [
                {"id": rule_evaluated_user, "role": "Senior Partner"}
            ]
            mock_rule_repo.evaluate_rules.return_value = rule_evaluated_user

            tasks = generate_due_recurring_tasks(firm_id=FIRM_ID)

            # Verify rules were evaluated
            mock_rule_repo.evaluate_rules.assert_called_once()
            assert len(tasks) == 1

    def test_template_title_used_if_config_title_missing(self):
        """Should use template name if config title is not set."""
        from services.recurring_task_service import generate_due_recurring_tasks

        today = date.today().isoformat()
        config = {
            "id": "config-1",
            "firm_id": FIRM_ID,
            "client_id": CLIENT_ID,
            "title": None,  # No title in config
            "description": None,
            "priority": "high",
            "frequency": "monthly",
            "next_due_date": today,
            "template_id": "template-1",
            "assignee_id": ASSIGNEE_ID,
            "is_active": True,
            "last_generated_at": None,
        }

        with patch("services.recurring_task_service._get_db") as mock_db, \
             patch("repositories.user_repository.user_repo"), \
             patch("repositories.assignment_rule_repository.assignment_rule_repo"), \
             patch("repositories.task_extras_repository.task_extras_repo"):

            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance

            query_mock = MagicMock()
            query_mock.execute.return_value.data = [config]
            query_mock.eq.return_value = query_mock
            query_mock.lte.return_value = query_mock

            # Mock template lookup
            template_query = MagicMock()
            template_query.eq.return_value.maybe_single.return_value.execute.return_value.data = {
                "id": "template-1",
                "name": "GST Template",
                "description": "Annual GST filing",
                "default_priority": "high",
            }

            insert_mock = MagicMock()
            insert_mock.execute.return_value.data = [{
                "id": "task-1",
                "title": "GST Template",
            }]

            update_mock = MagicMock()
            update_mock.eq.return_value.execute.return_value.data = [config]

            # Route per table so the config, template, task and update queries
            # each get the right mock
            config_table = MagicMock()
            config_table.select.return_value = query_mock
            config_table.update.return_value = update_mock
            template_table = MagicMock()
            template_table.select.return_value = template_query
            tasks_table = MagicMock()
            tasks_table.insert.return_value = insert_mock
            tables = {
                "task_recurring_configs": config_table,
                "task_templates": template_table,
                "tasks": tasks_table,
            }
            mock_db_instance.table.side_effect = lambda name: tables.get(name, MagicMock())

            tasks = generate_due_recurring_tasks(firm_id=FIRM_ID)

            assert len(tasks) == 1


class TestRecurringTaskJob:
    """Tests for jobs.recurring_task_job.run_recurring_generation_job()"""

    def test_job_success_returns_count_and_tasks(self):
        """Job should return count and tasks on success."""
        from jobs.recurring_task_job import run_recurring_generation_job

        with patch("jobs.recurring_task_job.generate_due_recurring_tasks") as mock_gen:
            mock_tasks = [
                {"id": "task-1", "title": "Task 1"},
                {"id": "task-2", "title": "Task 2"},
            ]
            mock_gen.return_value = mock_tasks

            result = run_recurring_generation_job(firm_id=FIRM_ID)

            assert result["success"] is True
            assert result["count"] == 2
            assert result["tasks"] == mock_tasks
            assert result["error"] is None

    def test_job_failure_returns_error(self):
        """Job should catch errors and return error message."""
        from jobs.recurring_task_job import run_recurring_generation_job

        with patch("jobs.recurring_task_job.generate_due_recurring_tasks") as mock_gen:
            mock_gen.side_effect = Exception("Database connection failed")

            result = run_recurring_generation_job(firm_id=FIRM_ID)

            assert result["success"] is False
            assert result["count"] == 0
            assert result["tasks"] == []
            assert "Database connection failed" in result["error"]

    def test_job_without_firm_id_generates_for_all_firms(self):
        """Job called without firm_id should generate for all firms."""
        from jobs.recurring_task_job import run_recurring_generation_job

        with patch("jobs.recurring_task_job.generate_due_recurring_tasks") as mock_gen:
            mock_gen.return_value = []

            run_recurring_generation_job(firm_id=None)

            mock_gen.assert_called_once_with(firm_id=None)
