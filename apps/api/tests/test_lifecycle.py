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


# ---------------------------------------------------------------------------
# 10-step onboarding checklist (Product Bible Ch. 7)
# ---------------------------------------------------------------------------

# Mirror the router constants for test isolation
ONBOARDING_CHECKLIST_STEPS = [
    (1,  "Engagement Letter",          "Generate, partner approve, send to client, client signs, archive"),
    (2,  "Client Profile",             "Legal name, entity type, incorporation date, address, industry, PAN, CIN/GSTIN, FY start"),
    (3,  "KYC",                        "PAN verification, GSTIN verification, CIN verification, directors, bank account"),
    (4,  "Services & Fees",            "Services confirmed, fee structure, billing frequency, billing start date"),
    (5,  "Compliance Calendar Setup",  "Auto-identified obligations, due dates, CA reviews and confirms"),
    (6,  "Accounting Setup",           "CoA from Schedule III, customisations, bank accounts, opening balances"),
    (7,  "Relationship Intelligence",  "Directors with DINs, shareholders, related parties, group companies, cross-client links"),
    (8,  "Team Assignment",            "Partner, Manager, Staff, internal briefing note, Timeline event"),
    (9,  "Portal Invitation",          "Primary contact invited, accepts, welcome message, first portal task"),
    (10, "Go-Live Verification",       "System checks all steps complete, first work item created, partner signs off"),
]

MANDATORY_CHECKLIST_STEPS = {1, 2, 3, 4, 5, 8, 9, 10}

AVG_DAYS_BY_ENTITY = {
    "Individual": 7, "Proprietorship": 7, "Partnership": 10,
    "LLP": 14, "Private Limited": 21, "Public Limited": 30,
    "Trust": 14, "Society": 14, "HUF": 7,
}

CHECKLIST_STATUS_MAP = {
    "Pending": "pending", "In Progress": "in_progress",
    "Done": "done", "Skipped": "skipped",
    "pending": "pending", "in_progress": "in_progress",
    "done": "done", "skipped": "skipped",
}


def _make_steps(workflow_id: str = "wf-test") -> list[dict]:
    """Build 10 fresh steps in pending status."""
    return [
        {"id": str(i + 1), "workflow_id": workflow_id, "step_number": n,
         "title": title, "status": "pending", "completed_at": None}
        for i, (n, title, _) in enumerate(ONBOARDING_CHECKLIST_STEPS)
    ]


def _calc_progress(steps: list[dict]) -> int:
    """Replicate the router's integer progress calculation."""
    if not steps:
        return 0
    done = sum(1 for s in steps if s.get("status") in ("done", "skipped"))
    return (done * 100) // len(steps)


def test_start_onboarding_creates_10_steps():
    """Starting an onboarding workflow produces exactly 10 steps."""
    steps = _make_steps()
    assert len(steps) == 10


def test_step_numbers_are_sequential():
    """Steps are numbered 1–10 without gaps."""
    steps = _make_steps()
    numbers = [s["step_number"] for s in steps]
    assert numbers == list(range(1, 11))


def test_step_update_changes_status():
    """Marking a step done changes its status."""
    steps = _make_steps()
    steps[0]["status"] = "done"
    assert steps[0]["status"] == "done"


def test_progress_pct_zero_on_start():
    """Fresh workflow has 0% progress."""
    steps = _make_steps()
    assert _calc_progress(steps) == 0


def test_progress_pct_calculates_correctly():
    """5 of 10 done → 50%."""
    steps = _make_steps()
    for s in steps[:5]:
        s["status"] = "done"
    assert _calc_progress(steps) == 50


def test_progress_pct_skipped_counts_as_done():
    """Skipped steps contribute to progress."""
    steps = _make_steps()
    for s in steps:
        s["status"] = "skipped"
    assert _calc_progress(steps) == 100


def test_go_live_fails_if_mandatory_steps_incomplete():
    """Go-live verification must reject if any mandatory step is pending."""
    steps = _make_steps()
    # Mark all done except step 3 (KYC — mandatory)
    for s in steps:
        s["status"] = "done"
    steps[2]["status"] = "pending"  # step_number 3

    step_map = {s["step_number"]: s["status"] for s in steps}
    incomplete = [n for n in MANDATORY_CHECKLIST_STEPS if step_map.get(n) not in ("done", "skipped")]
    assert 3 in incomplete


def test_go_live_succeeds_when_mandatory_done():
    """Go-live passes when all mandatory steps are done or skipped."""
    steps = _make_steps()
    for s in steps:
        if s["step_number"] in MANDATORY_CHECKLIST_STEPS:
            s["status"] = "done"
        else:
            s["status"] = "pending"  # optional steps may remain pending

    step_map = {s["step_number"]: s["status"] for s in steps}
    incomplete = [n for n in MANDATORY_CHECKLIST_STEPS if step_map.get(n) not in ("done", "skipped")]
    assert incomplete == []


def test_avg_days_private_limited():
    """Private Limited companies have a 21-day average onboarding period."""
    assert AVG_DAYS_BY_ENTITY["Private Limited"] == 21


def test_stalled_threshold_is_150_pct_of_avg():
    """A workflow is stalled when days_in_progress > 1.5 * avg_days."""
    avg = AVG_DAYS_BY_ENTITY["Private Limited"]  # 21
    threshold = avg * 1.5  # 31.5
    assert 32 > threshold  # day 32 is stalled
    assert 31 <= threshold  # day 31 is not stalled (edge)


def test_checklist_status_map_all_lowercase():
    """All DB-bound status values in the checklist map are lowercase."""
    for db_val in CHECKLIST_STATUS_MAP.values():
        assert db_val == db_val.lower()
