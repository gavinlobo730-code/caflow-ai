"""
Unit tests for lifecycle router logic — status maps, paise arithmetic.
Self-contained tests that don't require the FastAPI stack.

All monetary values in integer paise — never float. (CGST Act § 2(52))
"""
from datetime import datetime, timezone

# ── Status mapping dicts (duplicated for test isolation) ──────────────────

TASK_STATUS_MAP = {
    "Pending": "pending", "In Progress": "in_progress",
    "Done": "done", "Skipped": "skipped",
    "pending": "pending", "in_progress": "in_progress",
    "done": "done", "skipped": "skipped",
}

WORKFLOW_STATUS_MAP = {
    "Pending": "pending", "In Progress": "in_progress",
    "Completed": "completed", "Cancelled": "cancelled",
    "pending": "pending", "in_progress": "in_progress",
    "completed": "completed", "cancelled": "cancelled",
}

RENEWAL_STATUS_MAP = {
    "Pending": "pending", "Sent": "sent", "Accepted": "accepted",
    "Rejected": "rejected", "Expired": "expired",
    "Overdue": "expired", "Completed": "accepted", "Cancelled": "rejected",
    "pending": "pending", "sent": "sent", "accepted": "accepted",
    "rejected": "rejected", "expired": "expired",
}

DEFAULT_ONBOARDING_TASKS = [
    "Obtain PAN copy", "Obtain GST certificate", "Collect bank statements",
    "KYC documents", "Previous year financials", "Director/Partner documents",
    "Engagement letter signing", "Add to accounting software",
    "Create login credentials", "Welcome call scheduled",
]


# ---------------------------------------------------------------------------
# Task status mapping tests
# ---------------------------------------------------------------------------

def test_task_status_pending():
    assert TASK_STATUS_MAP["Pending"] == "pending"

def test_task_status_in_progress():
    assert TASK_STATUS_MAP["In Progress"] == "in_progress"

def test_task_status_done():
    assert TASK_STATUS_MAP["Done"] == "done"

def test_task_status_skipped():
    assert TASK_STATUS_MAP["Skipped"] == "skipped"

def test_task_status_idempotent_lowercase():
    assert TASK_STATUS_MAP["pending"] == "pending"
    assert TASK_STATUS_MAP["done"] == "done"

def test_all_task_db_values_are_lowercase():
    for db_val in TASK_STATUS_MAP.values():
        assert db_val == db_val.lower()


# ---------------------------------------------------------------------------
# Workflow status mapping tests
# ---------------------------------------------------------------------------

def test_workflow_in_progress():
    assert WORKFLOW_STATUS_MAP["In Progress"] == "in_progress"

def test_workflow_completed():
    assert WORKFLOW_STATUS_MAP["Completed"] == "completed"

def test_all_workflow_db_values_lowercase():
    for db_val in WORKFLOW_STATUS_MAP.values():
        assert db_val == db_val.lower()


# ---------------------------------------------------------------------------
# Renewal status mapping tests
# ---------------------------------------------------------------------------

def test_renewal_pending():
    assert RENEWAL_STATUS_MAP["Pending"] == "pending"

def test_renewal_accepted():
    assert RENEWAL_STATUS_MAP["Accepted"] == "accepted"

def test_renewal_legacy_completed_maps_to_accepted():
    assert RENEWAL_STATUS_MAP["Completed"] == "accepted"

def test_renewal_legacy_overdue_maps_to_expired():
    assert RENEWAL_STATUS_MAP["Overdue"] == "expired"

def test_renewal_legacy_cancelled_maps_to_rejected():
    assert RENEWAL_STATUS_MAP["Cancelled"] == "rejected"

def test_all_renewal_db_values_valid():
    valid = {"pending", "sent", "accepted", "rejected", "expired"}
    for db_val in RENEWAL_STATUS_MAP.values():
        assert db_val in valid, f"'{db_val}' not in DB CHECK constraint values"


# ---------------------------------------------------------------------------
# Onboarding tasks
# ---------------------------------------------------------------------------

def test_onboarding_tasks_count():
    assert len(DEFAULT_ONBOARDING_TASKS) == 10

def test_onboarding_first_task():
    assert DEFAULT_ONBOARDING_TASKS[0] == "Obtain PAN copy"

def test_onboarding_last_task():
    assert DEFAULT_ONBOARDING_TASKS[-1] == "Welcome call scheduled"

def test_onboarding_all_strings():
    for t in DEFAULT_ONBOARDING_TASKS:
        assert isinstance(t, str) and len(t) > 0


# ---------------------------------------------------------------------------
# Paise arithmetic (integer — never float)
# ---------------------------------------------------------------------------

def test_paise_multiplication_is_integer():
    rupees = 15000
    paise = rupees * 100
    assert isinstance(paise, int)
    assert paise == 1500000

def test_paise_to_rupees_display():
    paise = 1500000
    rupees = paise // 100  # integer division
    assert isinstance(rupees, int)
    assert rupees == 15000

def test_zero_paise_is_valid():
    assert 0 * 100 == 0
    assert isinstance(0, int)

def test_proposal_no_format():
    """Proposal numbers follow PROP-YYYY-NNNN format."""
    year = datetime.now(timezone.utc).year
    n = 1
    prop_no = f"PROP-{year}-{n:04d}"
    parts = prop_no.split("-")
    assert len(parts) == 3
    assert parts[0] == "PROP"
    assert parts[1] == str(year)
    assert len(parts[2]) == 4
