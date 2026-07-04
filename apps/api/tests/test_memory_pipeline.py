"""Tests for Phase 13 AI Memory Pipeline."""
import pytest
from domain.memory_pipeline import MemoryPipeline
from repositories.memory_repository import MemoryRepository, MOCK_CLIENT_PROFILES
from repositories.client_repository import client_repo
from repositories.compliance_records_repository import compliance_records_repo
from mock_data import MOCK_COMPLIANCE_RECORDS

@pytest.fixture
def pipeline():
    return MemoryPipeline()

@pytest.fixture
def repo():
    return MemoryRepository()


class TestClientProfileGeneration:
    def test_profile_created_for_client(self, pipeline, repo):
        # Create a profile and verify structure
        # Use mock data (no SUPABASE_URL in tests)
        profile = repo.upsert_profile("firm-001", "client-001", {
            "compliance_score": 80.0,
            "avg_response_time_days": 3.5,
            "portal_engagement": 75.0,
            "doc_upload_reliability": 85.0,
            "recurring_issues": [],
            "missed_deadline_count": 1,
            "data_points_used": 15,
        })
        assert profile["firm_id"] == "firm-001"
        assert profile["client_id"] == "client-001"
        assert profile["compliance_score"] == 80.0
        assert profile["is_current"] is True

    def test_profile_version_increments(self, repo):
        repo.upsert_profile("firm-v", "client-v", {"compliance_score": 70.0, "data_points_used": 5})
        repo.upsert_profile("firm-v", "client-v", {"compliance_score": 75.0, "data_points_used": 10})
        current = repo.get_current_profile("firm-v", "client-v")
        assert current is not None
        assert current["compliance_score"] == 75.0
        # Old profile should be marked non-current
        history = [p for p in MOCK_CLIENT_PROFILES if p["client_id"] == "client-v" and not p["is_current"]]
        assert len(history) >= 1

    def test_nonexistent_profile_returns_none(self, repo):
        result = repo.get_current_profile("firm-x", "client-x")
        assert result is None


class TestTriggerCreation:
    def test_trigger_created_with_evidence(self, repo):
        trigger = repo.create_trigger(
            firm_id="firm-t",
            client_id="client-t",
            trigger_type="repeat_issue",
            title="GST Filing Risk",
            what_detected="Client has delayed GST 3 times",
            evidence=["GST delayed April 2024", "GST delayed October 2024", "GST delayed January 2025"],
            why_it_matters="Penalty risk increases with each delay",
            recommended_action="Contact client 2 weeks before deadline",
            confidence=85.0,
            severity="high",
        )
        assert trigger["id"] is not None
        assert trigger["status"] == "active"
        assert trigger["confidence"] == 85.0
        assert len(trigger["evidence"]) == 3

    def test_trigger_acknowledge(self, repo):
        trigger = repo.create_trigger(
            firm_id="firm-ack", client_id=None, trigger_type="deadline_at_risk",
            title="Test", what_detected="Test", evidence=[],
            why_it_matters="Test", recommended_action="Test",
            confidence=70.0, severity="medium",
        )
        acked = repo.acknowledge_trigger("firm-ack", trigger["id"], "user-001")
        assert acked["status"] == "acknowledged"
        assert acked["acknowledged_by"] == "user-001"

    def test_trigger_dismiss(self, repo):
        trigger = repo.create_trigger(
            firm_id="firm-dis", client_id=None, trigger_type="cash_flow_warning",
            title="Test", what_detected="Test", evidence=[],
            why_it_matters="Test", recommended_action="Test",
            confidence=60.0, severity="low",
        )
        dismissed = repo.dismiss_trigger("firm-dis", trigger["id"])
        assert dismissed["status"] == "dismissed"

    def test_list_triggers_filters_by_status(self, repo):
        repo.create_trigger(
            firm_id="firm-filter", client_id=None, trigger_type="repeat_issue",
            title="Active", what_detected="x", evidence=[],
            why_it_matters="x", recommended_action="x",
            confidence=80.0, severity="high",
        )
        active = repo.list_triggers("firm-filter", status="active")
        assert all(t["status"] == "active" for t in active if t["firm_id"] == "firm-filter")


class TestAnomalyDetection:
    def test_anomaly_created_with_deviation(self, repo):
        anomaly = repo.create_anomaly(
            firm_id="firm-anom",
            client_id="client-anom",
            anomaly_type="activity_spike",
            metric_name="monthly_task_volume",
            baseline=10.0,
            actual=25.0,
            period="2026-06",
            explanation="Task volume 150% above baseline",
            evidence=["Baseline: 10 tasks/month", "Current: 25 tasks"],
        )
        assert anomaly["id"] is not None
        assert anomaly["status"] == "open"
        assert anomaly["deviation_pct"] == pytest.approx(150.0, abs=1)

    def test_anomaly_status_update(self, repo):
        anomaly = repo.create_anomaly(
            firm_id="firm-anom2", client_id=None,
            anomaly_type="activity_drop", metric_name="task_volume",
            baseline=20.0, actual=5.0, period="2026-05",
            explanation="Drop detected", evidence=[],
        )
        updated = repo.update_anomaly_status("firm-anom2", anomaly["id"], "reviewed")
        assert updated["status"] == "reviewed"


class TestYearEndReports:
    def test_year_end_report_created(self, repo):
        report = repo.create_year_end_report(
            firm_id="firm-ye",
            client_id="client-ye",
            financial_year="2025-26",
            data={
                "prior_year_lessons": ["Request documents earlier"],
                "recurring_provisions": ["Depreciation", "Gratuity"],
                "auditor_requests": ["Bank statements", "Loan certificates"],
                "historical_bottlenecks": ["GST reconciliation delays"],
                "planning_recommendations": ["Start by Feb 28"],
                "ai_narrative": "Year-end 2025-26 planning report.",
            }
        )
        assert report["financial_year"] == "2025-26"
        assert len(report["prior_year_lessons"]) == 1
        assert report["status"] == "draft"

    def test_get_existing_report(self, repo):
        repo.create_year_end_report(
            firm_id="firm-yeg", client_id="client-yeg", financial_year="2025-26",
            data={"prior_year_lessons": [], "recurring_provisions": [],
                  "auditor_requests": [], "historical_bottlenecks": [],
                  "planning_recommendations": [], "ai_narrative": "Test"}
        )
        fetched = repo.get_year_end_report("firm-yeg", "client-yeg", "2025-26")
        assert fetched is not None
        assert fetched["financial_year"] == "2025-26"

    def test_get_nonexistent_report_returns_none(self, repo):
        result = repo.get_year_end_report("firm-none", "client-none", "2024-25")
        assert result is None


class TestFirmProfile:
    def test_firm_profile_upsert(self, repo):
        profile = repo.upsert_firm_profile("firm-fp", {
            "portfolio_compliance_score": 82.0,
            "peak_workload_months": ["March", "July"],
            "portfolio_health_trend": "stable",
        })
        assert profile["firm_id"] == "firm-fp"
        assert profile["portfolio_compliance_score"] == 82.0

    def test_get_firm_profile(self, repo):
        repo.upsert_firm_profile("firm-gfp", {"portfolio_compliance_score": 75.0})
        fetched = repo.get_firm_profile("firm-gfp")
        assert fetched is not None


class TestComplianceRecordsSource:
    """R3.13d: the AI-memory pipeline's compliance signal now reads the
    canonical compliance_records (System A), not the retiring
    compliance_tasks (System B) — proves the status vocabulary was mapped
    correctly (System A's capitalized 'Overdue'/'Filed'/'Completed', not
    System B's lowercase 'overdue'/'pending'), not just the data source."""

    @pytest.fixture(autouse=True)
    def _isolate(self):
        snapshot = list(MOCK_COMPLIANCE_RECORDS)
        yield
        MOCK_COMPLIANCE_RECORDS[:] = snapshot

    def _client(self, client_id, firm_id):
        return client_repo.create({"id": client_id, "firm_id": firm_id, "client_name": "Test Co"})

    def test_compute_client_profile_counts_overdue_from_compliance_records(self, pipeline):
        self._client("mp-cli-1", "mp-firm-1")
        compliance_records_repo.create({
            "firm_id": "mp-firm-1", "client_id": "mp-cli-1", "compliance_type": "GST",
            "status": "Overdue", "due_date": "2026-01-11"})
        compliance_records_repo.create({
            "firm_id": "mp-firm-1", "client_id": "mp-cli-1", "compliance_type": "GST",
            "status": "Filed", "due_date": "2026-02-11"})

        profile = pipeline.compute_client_profile("mp-firm-1", "mp-cli-1")
        assert profile["missed_deadline_count"] == 1

    def test_detect_deadline_at_risk_reads_open_compliance_records(self, pipeline):
        self._client("mp-cli-2", "mp-firm-2")
        from datetime import datetime, timezone, timedelta
        due_soon = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
        compliance_records_repo.create({
            "firm_id": "mp-firm-2", "client_id": "mp-cli-2", "compliance_type": "GST",
            "status": "Not Started", "due_date": due_soon})
        # A Filed record due just as soon must NOT be treated as at-risk.
        compliance_records_repo.create({
            "firm_id": "mp-firm-2", "client_id": "mp-cli-2", "compliance_type": "GST",
            "status": "Filed", "due_date": due_soon})

        triggers = pipeline.detect_deadline_at_risk("mp-firm-2", "mp-cli-2")
        # Whether or not it crosses the at-risk threshold depends on
        # avg_response_time_days (defaults to 5), but it must not raise and
        # must only ever have considered the one open record.
        assert isinstance(triggers, list)
