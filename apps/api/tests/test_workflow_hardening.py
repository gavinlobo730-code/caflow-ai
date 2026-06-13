"""
Tests for Phase 10B production hardening:
- Branch execution with jump logic
- Cycle detection
- Max-step guard
- Approval pause and resume
- Retry behaviour (via mock patching)
- Scheduler helpers
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from domain.workflow_engine_v2 import WorkflowEngineV2, _ApprovalPause
from repositories.workflow_repository import WorkflowRepository


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    return WorkflowEngineV2()


@pytest.fixture
def repo():
    return WorkflowRepository()


def _make_template(repo, firm_id, name, **extra):
    """Helper: create a template with is_active=True."""
    return repo.create_template(firm_id, {
        "name": name,
        "category": "general",
        "trigger_type": "client_created",
        "trigger_config": {},
        "is_active": True,
        **extra,
    })


def _make_instance(repo, firm_id, template_id):
    """Helper: create a running instance."""
    return repo.create_instance(firm_id, template_id, "client_created", {})


# ── Branch Execution Tests ────────────────────────────────────────────────────

class TestBranchExecution:
    def test_branch_takes_true_path(self, engine, repo):
        """When branch condition is true, branch_taken == 'true' in the action log."""
        template = _make_template(repo, "firm-brt", "Branch True Test")
        step_true = repo._create_step(template["id"], {
            "step_order": 3, "step_type": "action", "name": "True Path",
            "config": {"action_type": "notification", "message": "true"},
            "next_step_id": None,
        })
        step_false = repo._create_step(template["id"], {
            "step_order": 4, "step_type": "action", "name": "False Path",
            "config": {"action_type": "notification", "message": "false"},
            "next_step_id": None,
        })
        repo._create_step(template["id"], {
            "step_order": 1, "step_type": "branch", "name": "Health Check",
            "config": {"condition": {"logic": "AND", "rules": [
                {"field": "health_score", "operator": ">", "value": "50", "value_type": "number"},
            ], "groups": []}},
            "true_branch_step_id": step_true["id"],
            "false_branch_step_id": step_false["id"],
            "next_step_id": None,
        })

        instance = _make_instance(repo, "firm-brt", template["id"])
        result = engine._execute_steps(template, instance, {"health_score": 80}, "firm-brt")

        assert result["status"] in ("completed", "waiting_approval", "failed")
        logs = repo.list_action_logs(instance["id"])
        branch_log = next((l for l in logs if l.get("step_name") == "Health Check"), None)
        assert branch_log is not None
        assert branch_log.get("result_data", {}).get("branch_taken") == "true"

    def test_branch_takes_false_path(self, engine, repo):
        """When branch condition is false, branch_taken == 'false' in the action log."""
        template = _make_template(repo, "firm-brf", "Branch False Test")
        step_false = repo._create_step(template["id"], {
            "step_order": 2, "step_type": "action", "name": "False Path",
            "config": {"action_type": "notification", "message": "false"},
            "next_step_id": None,
        })
        repo._create_step(template["id"], {
            "step_order": 1, "step_type": "branch", "name": "Score Check",
            "config": {"condition": {"logic": "AND", "rules": [
                {"field": "score", "operator": ">", "value": "90", "value_type": "number"},
            ], "groups": []}},
            "true_branch_step_id": None,
            "false_branch_step_id": step_false["id"],
            "next_step_id": None,
        })

        instance = _make_instance(repo, "firm-brf", template["id"])
        result = engine._execute_steps(template, instance, {"score": 40}, "firm-brf")

        logs = repo.list_action_logs(instance["id"])
        branch_log = next((l for l in logs if l.get("step_name") == "Score Check"), None)
        assert branch_log is not None
        assert branch_log.get("result_data", {}).get("branch_taken") == "false"


# ── Cycle Detection Tests ─────────────────────────────────────────────────────

class TestCycleDetection:
    def test_cycle_detected_and_fails_instance(self, engine, repo):
        """A self-referencing step is detected by the visited-set and stops as failed."""
        template = _make_template(repo, "firm-cyc", "Cycle Test")
        step = repo._create_step(template["id"], {
            "step_order": 1, "step_type": "action", "name": "Loop Step",
            "config": {"action_type": "notification", "message": "looping"},
            "next_step_id": None,
        })
        # Create a circular reference — step points back to itself
        repo._update_step(step["id"], {"next_step_id": step["id"]})

        instance = _make_instance(repo, "firm-cyc", template["id"])
        result = engine._execute_steps(template, instance, {}, "firm-cyc")

        assert result["status"] == "failed"
        assert "cycle" in result.get("error", "").lower()

    def test_max_steps_exceeded_fails_instance(self, engine, repo):
        """A chain longer than MAX_STEPS is halted with status=failed."""
        from domain.workflow_engine_v2 import MAX_STEPS
        template = _make_template(repo, "firm-mxs", "Max Steps Test")

        # Build chain of MAX_STEPS + 5 steps, all unique (no cycles)
        steps = []
        for i in range(MAX_STEPS + 5):
            s = repo._create_step(template["id"], {
                "step_order": i + 1, "step_type": "action", "name": f"Step {i}",
                "config": {"action_type": "notification", "message": f"step {i}"},
                "next_step_id": None,
            })
            steps.append(s)
        for i in range(len(steps) - 1):
            repo._update_step(steps[i]["id"], {"next_step_id": steps[i + 1]["id"]})

        instance = _make_instance(repo, "firm-mxs", template["id"])
        result = engine._execute_steps(template, instance, {}, "firm-mxs")

        assert result["status"] == "failed"
        assert "max_steps" in result.get("error", "").lower()


# ── Idempotency / Repeated Firing Tests ──────────────────────────────────────

class TestFireTriggerIdempotency:
    def test_fire_trigger_matches_active_template(self, engine, repo):
        """fire_trigger returns results for a matching active template."""
        template = _make_template(repo, "firm-ftm", "Fire Test")
        results = engine.fire_trigger("firm-ftm", "client_created", {"client_id": "c-001"})
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_fire_trigger_does_not_match_inactive_template(self, engine, repo):
        """fire_trigger skips templates with is_active=False."""
        repo.create_template("firm-fti", {
            "name": "Inactive Template",
            "category": "general",
            "trigger_type": "client_created",
            "trigger_config": {},
            "is_active": False,
        })
        results = engine.fire_trigger("firm-fti", "client_created", {"client_id": "c-999"})
        # No active templates → no results for this firm
        assert all(r.get("firm_id") != "firm-fti" for r in results) or results == []

    def test_different_trigger_data_fires_independently(self, engine, repo):
        """Two distinct trigger payloads each create an instance."""
        template = _make_template(repo, "firm-ftt", "Two Fire Test")
        engine.fire_trigger("firm-ftt", "client_created", {"client_id": "c-A"})
        engine.fire_trigger("firm-ftt", "client_created", {"client_id": "c-B"})
        instances = repo.list_instances("firm-ftt")
        assert len(instances) >= 2


# ── Approval Pause / Resume Tests ─────────────────────────────────────────────

class TestApprovalWorkflow:
    def test_approval_step_pauses_workflow(self, engine, repo):
        """Workflow with an approval step returns waiting_approval status."""
        template = _make_template(repo, "firm-apr", "Approval Test")
        repo._create_step(template["id"], {
            "step_order": 1, "step_type": "approval", "name": "Partner Approval",
            "config": {
                "approver_role": "Partner",
                "title": "Review client onboarding",
                "description": "Please review and approve",
                "due_hours": 24,
            },
            "next_step_id": None,
        })

        instance = _make_instance(repo, "firm-apr", template["id"])
        result = engine._execute_steps(template, instance, {}, "firm-apr")

        assert result["status"] == "waiting_approval"
        assert "approval_id" in result

        # Instance status should be waiting_approval
        updated = repo.get_instance("firm-apr", instance["id"])
        assert updated["status"] == "waiting_approval"

        # Approval record should be created
        approvals = repo.list_approvals("firm-apr", status="pending")
        assert any(a["instance_id"] == instance["id"] for a in approvals)

    def test_approval_resume_approved_completes_workflow(self, engine, repo):
        """Approving an instance resumes execution and reaches completion."""
        template = _make_template(repo, "firm-rsr", "Resume Test")
        step_post = repo._create_step(template["id"], {
            "step_order": 2, "step_type": "action", "name": "Post Approval",
            "config": {"action_type": "notification", "message": "Approved!"},
            "next_step_id": None,
        })
        repo._create_step(template["id"], {
            "step_order": 1, "step_type": "approval", "name": "Approval Step",
            "config": {
                "approver_role": "Partner", "title": "Approve",
                "description": "", "due_hours": 24,
            },
            "next_step_id": step_post["id"],
        })

        instance = _make_instance(repo, "firm-rsr", template["id"])
        engine._execute_steps(template, instance, {}, "firm-rsr")

        resumed = engine.resume_after_approval("firm-rsr", instance["id"], approved=True, user_id="user-001")
        assert resumed is not None

        updated = repo.get_instance("firm-rsr", instance["id"])
        assert updated["status"] == "completed"

    def test_approval_rejected_cancels_workflow(self, engine, repo):
        """Rejecting an approval transitions instance to cancelled."""
        template = _make_template(repo, "firm-rej", "Reject Test")
        repo._create_step(template["id"], {
            "step_order": 1, "step_type": "approval", "name": "Approval Step",
            "config": {
                "approver_role": "Partner", "title": "Approve",
                "description": "", "due_hours": 24,
            },
            "next_step_id": None,
        })

        instance = _make_instance(repo, "firm-rej", template["id"])
        engine._execute_steps(template, instance, {}, "firm-rej")

        engine.resume_after_approval("firm-rej", instance["id"], approved=False, user_id="user-002")

        updated = repo.get_instance("firm-rej", instance["id"])
        assert updated["status"] == "cancelled"


# ── Retry / Resilience Tests ──────────────────────────────────────────────────

class TestRetryResilience:
    def test_step_failure_returns_failed_status(self, engine, repo):
        """When a step permanently fails, _execute_steps returns status=failed."""
        template = _make_template(repo, "firm-sfail", "Fail Test")
        repo._create_step(template["id"], {
            "step_order": 1, "step_type": "action", "name": "Flaky Step",
            "config": {"action_type": "notification", "message": "test"},
            "next_step_id": None,
        })

        instance = _make_instance(repo, "firm-sfail", template["id"])

        with patch.object(engine, "_execute_step", side_effect=RuntimeError("permanent failure")):
            result = engine._execute_steps(template, instance, {}, "firm-sfail")

        assert result["status"] == "failed"
        assert result.get("error") is not None

    def test_step_failure_transitions_instance_to_failed(self, engine, repo):
        """Instance status is set to failed after a step error."""
        template = _make_template(repo, "firm-sinst", "Instance Fail Test")
        repo._create_step(template["id"], {
            "step_order": 1, "step_type": "action", "name": "Error Step",
            "config": {"action_type": "notification", "message": "boom"},
            "next_step_id": None,
        })

        instance = _make_instance(repo, "firm-sinst", template["id"])

        with patch.object(engine, "_execute_step", side_effect=ValueError("bad config")):
            engine._execute_steps(template, instance, {}, "firm-sinst")

        updated = repo.get_instance("firm-sinst", instance["id"])
        assert updated["status"] == "failed"

    def test_step_failure_creates_failure_log(self, engine, repo):
        """Failed step creates a failure record queryable via list_failures."""
        template = _make_template(repo, "firm-flog", "Fail Log Test")
        repo._create_step(template["id"], {
            "step_order": 1, "step_type": "action", "name": "Error Step",
            "config": {"action_type": "notification", "message": "boom"},
            "next_step_id": None,
        })

        instance = _make_instance(repo, "firm-flog", template["id"])

        with patch.object(engine, "_execute_step", side_effect=ValueError("bad config")):
            engine._execute_steps(template, instance, {}, "firm-flog")

        failures = repo.list_failures("firm-flog", resolved=False)
        assert any(f["instance_id"] == instance["id"] for f in failures)

    def test_retry_executes_step_multiple_times_before_success(self, engine, repo):
        """_execute_step_with_retry retries a failing step."""
        template = _make_template(repo, "firm-retry", "Retry Test")
        repo._create_step(template["id"], {
            "step_order": 1, "step_type": "action", "name": "Flaky Step",
            "config": {"action_type": "notification", "message": "test"},
            "next_step_id": None,
        })

        instance = _make_instance(repo, "firm-retry", template["id"])
        call_count = [0]
        original = engine._execute_step

        def flaky(step, inst, ctx, fid):
            call_count[0] += 1
            if call_count[0] < 3:
                raise RuntimeError("Transient error")
            return original(step, inst, ctx, fid)

        with patch.object(engine, "_execute_step", side_effect=flaky):
            result = engine._execute_steps(template, instance, {}, "firm-retry")

        # Should have retried — called 3+ times (2 failures + 1 success)
        assert call_count[0] >= 3
        assert result["status"] == "completed"


# ── Scheduler Tests ───────────────────────────────────────────────────────────

class TestScheduler:
    def test_compute_next_run_returns_future_iso_string(self):
        """compute_next_run returns a UTC ISO 8601 string in the future."""
        from jobs.scheduler import compute_next_run
        next_run = compute_next_run("0 9 * * *", "Asia/Kolkata")
        assert next_run is not None
        assert "T" in next_run  # ISO format has T separator
        now = datetime.now(timezone.utc).isoformat()
        assert next_run > now

    def test_compute_next_run_invalid_cron_returns_fallback(self):
        """Invalid cron expression falls back to 1 day from now."""
        from jobs.scheduler import compute_next_run
        next_run = compute_next_run("not a valid cron", "Asia/Kolkata")
        assert next_run is not None
        assert "T" in next_run

    def test_run_due_schedules_no_due_does_not_raise(self):
        """run_due_schedules with no due schedules completes without error."""
        from jobs.scheduler import run_due_schedules
        run_due_schedules()  # must not raise

    def test_run_due_schedules_fires_and_updates_metadata(self, repo):
        """A schedule with next_run_at in the past is fired and last_run_at is set."""
        from jobs.scheduler import run_due_schedules
        from repositories.workflow_repository import MOCK_SCHEDULES

        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        schedule = repo.create_schedule(
            "firm-sched-fire", None, "Due Schedule", "0 9 * * *",
        )
        for s in MOCK_SCHEDULES:
            if s["id"] == schedule["id"]:
                s["next_run_at"] = past
                s["is_active"] = True
                break

        run_due_schedules()

        schedules = repo.list_schedules("firm-sched-fire")
        updated = next((s for s in schedules if s["id"] == schedule["id"]), None)
        assert updated is not None
        assert updated.get("last_run_at") is not None

    def test_update_schedule_run_sets_metadata(self, repo):
        """update_schedule_run sets last_run_status, next_run_at, increments run_count."""
        schedule = repo.create_schedule(
            "firm-sr-update", None, "Update Test", "0 0 * * *",
        )
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        updated = repo.update_schedule_run(schedule["id"], "success", future)

        assert updated is not None
        assert updated["last_run_status"] == "success"
        assert updated["next_run_at"] == future
        assert updated["run_count"] == 1
        assert updated["last_run_at"] is not None

    def test_list_schedules_due_filters_by_next_run_at(self, repo):
        """list_schedules_due returns only active schedules past their due time."""
        from repositories.workflow_repository import MOCK_SCHEDULES

        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        due_sched = repo.create_schedule("firm-lsd", None, "Due", "0 9 * * *")
        not_due_sched = repo.create_schedule("firm-lsd", None, "Not Due Yet", "0 9 * * *")

        for s in MOCK_SCHEDULES:
            if s["id"] == due_sched["id"]:
                s["next_run_at"] = past
                s["is_active"] = True
            elif s["id"] == not_due_sched["id"]:
                s["next_run_at"] = future
                s["is_active"] = True

        due = repo.list_schedules_due(now_iso)
        due_ids = {s["id"] for s in due}

        assert due_sched["id"] in due_ids
        assert not_due_sched["id"] not in due_ids

    def test_inactive_schedule_not_returned_as_due(self, repo):
        """Inactive schedules with past next_run_at are not returned by list_schedules_due."""
        from repositories.workflow_repository import MOCK_SCHEDULES

        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        inactive = repo.create_schedule("firm-lsd-inactive", None, "Inactive", "0 9 * * *")
        for s in MOCK_SCHEDULES:
            if s["id"] == inactive["id"]:
                s["next_run_at"] = past
                s["is_active"] = False
                break

        due = repo.list_schedules_due(now_iso)
        assert inactive["id"] not in {s["id"] for s in due}
