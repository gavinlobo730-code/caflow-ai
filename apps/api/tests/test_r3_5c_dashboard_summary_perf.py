"""
R3.5c — proves domain/task_service.py get_dashboard_summary()'s fixes:
open-tasks fetch pushed server-side (exclude_statuses instead of fetching
every task ever and discarding completed ones in Python), and the N+1
per-client health-score loop replaced with one grouped pass over
compliance_records already fetched for the compliance_due_week/overdue
metrics.
"""
from unittest.mock import patch

from domain.task_service import task_domain_service

FIRM = "firm-r35c"


def test_high_risk_clients_computed_without_per_client_repo_calls():
    """get_client_health_score() (2 DB round trips per client: a client
    lookup + its own compliance_records fetch) must never be called from
    get_dashboard_summary() — score_from_records() (pure, no I/O) is used
    instead, fed by the compliance_records already fetched once for the
    whole firm."""
    clients = [
        {"id": "c1", "status": "active"},
        {"id": "c2", "status": "active"},
    ]
    records = [
        # c1: one Overdue -> 100 - 20 = 80 (not high-risk)
        {"client_id": "c1", "status": "Overdue", "risk_score": 10, "due_date": "2020-01-01"},
        # c2: three Overdue -> 100 - 60 = 40 (high-risk, < 50)
        {"client_id": "c2", "status": "Overdue", "risk_score": 10, "due_date": "2020-01-01"},
        {"client_id": "c2", "status": "Overdue", "risk_score": 10, "due_date": "2020-01-01"},
        {"client_id": "c2", "status": "Overdue", "risk_score": 10, "due_date": "2020-01-01"},
    ]

    with patch("domain.task_service.client_repo") as mock_clients, \
         patch("domain.task_service.task_repo") as mock_tasks, \
         patch("domain.compliance_record_service.compliance_record_service") as mock_records:
        mock_clients.find_all.return_value = clients
        mock_tasks.find_all.return_value = []
        mock_tasks.find_overdue.return_value = []
        mock_records.list_records.return_value = records
        # Real (unmocked) pure scoring math — proves the batched call site
        # produces the same numbers get_client_health_score() would have.
        from domain.compliance_record_service import ComplianceRecordService
        mock_records.score_from_records.side_effect = ComplianceRecordService.score_from_records

        result = task_domain_service.get_dashboard_summary(firm_id=FIRM)

        assert result["high_risk_clients"] == 1  # only c2
        mock_records.get_client_health_score.assert_not_called()
        mock_records.list_records.assert_called_once()  # one firm-wide fetch, not one per client


def test_open_tasks_excludes_completed_server_side():
    """find_all() must be called with exclude_statuses=["completed"] rather
    than fetching every task and filtering completed ones out in Python."""
    with patch("domain.task_service.client_repo") as mock_clients, \
         patch("domain.task_service.task_repo") as mock_tasks, \
         patch("domain.compliance_record_service.compliance_record_service") as mock_records:
        mock_clients.find_all.return_value = []
        mock_tasks.find_all.return_value = []
        mock_tasks.find_overdue.return_value = []
        mock_records.list_records.return_value = []

        task_domain_service.get_dashboard_summary(firm_id=FIRM)

        mock_tasks.find_all.assert_called_once_with(firm_id=FIRM, exclude_statuses=["completed"])
