"""
R3.5b — proves repositories/compliance_records_repository.py's new
exclude_statuses/count_all support, used to bound
services/compliance_obligation_service.py's escalate() so it no longer
fetches every Filed/Completed record just to discard it in Python.
"""
from repositories.compliance_records_repository import compliance_records_repo
from mock_data import MOCK_COMPLIANCE_RECORDS

FIRM = "firm-r35b"


def _seed():
    return [
        compliance_records_repo.create({
            "firm_id": FIRM, "client_id": "c1", "compliance_type": "GST",
            "status": "Not Started", "due_date": "2026-06-01",
        }),
        compliance_records_repo.create({
            "firm_id": FIRM, "client_id": "c1", "compliance_type": "GST",
            "status": "Overdue", "due_date": "2026-05-01",
        }),
        compliance_records_repo.create({
            "firm_id": FIRM, "client_id": "c1", "compliance_type": "GST",
            "status": "Filed", "due_date": "2026-04-01",
        }),
        compliance_records_repo.create({
            "firm_id": FIRM, "client_id": "c1", "compliance_type": "GST",
            "status": "Completed", "due_date": "2026-03-01",
        }),
    ]


def _cleanup(created):
    ids = {r["id"] for r in created}
    MOCK_COMPLIANCE_RECORDS[:] = [r for r in MOCK_COMPLIANCE_RECORDS if r["id"] not in ids]


def test_exclude_statuses_filters_out_closed_records():
    created = _seed()
    try:
        open_only = compliance_records_repo.find_all(firm_id=FIRM, exclude_statuses=("Filed", "Completed"))
        assert {r["status"] for r in open_only} == {"Not Started", "Overdue"}
        assert len(open_only) == 2
    finally:
        _cleanup(created)


def test_exclude_statuses_is_a_pure_additive_filter():
    """Omitting exclude_statuses keeps the old fetch-everything behavior —
    backward compatible for any caller not yet migrated."""
    created = _seed()
    try:
        everything = compliance_records_repo.find_all(firm_id=FIRM)
        assert len(everything) == 4
    finally:
        _cleanup(created)


def test_count_all_matches_find_all_length():
    created = _seed()
    try:
        assert compliance_records_repo.count_all(firm_id=FIRM) == len(
            compliance_records_repo.find_all(firm_id=FIRM)
        ) == 4
    finally:
        _cleanup(created)


def test_escalate_no_longer_needs_closed_records_fetched():
    """services/compliance_obligation_service.py's escalate() now passes
    exclude_statuses=("Filed","Completed") — confirm it still correctly
    ignores closed obligations end-to-end (behavior-preserving, not just a
    query-shape change)."""
    import services.compliance_obligation_service as ob
    from datetime import date

    created = _seed()
    try:
        result = ob.escalate(FIRM, today=date(2026, 6, 1), actor={"auth_user_id": "u1", "email": "u1@test.in"})
        # Only the 2 open records (Not Started due 2026-06-01 -> due_1,
        # Overdue due 2026-05-01 -> overdue) can be escalated; the 2 closed
        # ones must never surface, whether or not their due_date would
        # otherwise have matched a tier.
        assert result["escalated"] == 2
    finally:
        _cleanup(created)
