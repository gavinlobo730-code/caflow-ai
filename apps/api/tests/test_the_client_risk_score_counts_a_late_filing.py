"""POST-A-261: the client risk score's "late filing history" reads the column the compliance table has.

`compute_compliance_risk` adds 20 points to a client's score when a filed compliance record was filed after its due date.
It decided that from `r["filed_at"]`; `compliance_records` has `filed_date` (a date) and `completed_at` (a timestamp) and no
`filed_at`, so the condition never held and the 20 points were never added to anyone. The insights screen already says the
score covers "whether they have filed late before" and prints `filed late N×` when the count is above zero, so the screen
was promising what the engine never did.
"""
from __future__ import annotations

import pytest

import services.intelligence_service as isvc

FIRM = "firm-1"
CLIENT, OTHER = "client-a", "client-b"
LONG_AGO = "2025-01-20"            # a due date well in the past: the record is filed, so it is not "overdue"


def _record(client, *, due=LONG_AGO, filed="2025-01-25", status="filed", **extra):
    return {"id": f"{client}-{due}-{filed}", "client_id": client, "compliance_type": "GSTR-3B",
            "due_date": due, "filed_date": filed, "status": status, **extra}


@pytest.fixture
def score(monkeypatch):
    import repositories.client_repository as cr
    import repositories.compliance_records_repository as rr
    monkeypatch.setattr(cr.client_repo, "find_all", lambda **kw: [
        {"id": CLIENT, "client_name": "A Ltd"}, {"id": OTHER, "client_name": "B Ltd"}])

    def run(records):
        monkeypatch.setattr(rr.compliance_records_repo, "find_all", lambda **kw: records)
        return {c["client_id"]: c for c in isvc.compute_compliance_risk(FIRM, None)["clients"]}
    return run


def test_a_record_filed_after_its_due_date_is_late_history_and_adds_twenty(score):
    late = score([_record(CLIENT, due="2025-01-20", filed="2025-01-25")])
    on_time = score([_record(CLIENT, due="2025-01-20", filed="2025-01-20")])
    assert late[CLIENT]["late_filing_history"] == 1 and on_time[CLIENT]["late_filing_history"] == 0
    assert late[CLIENT]["risk_score"] == on_time[CLIENT]["risk_score"] + 20


def test_filing_on_the_due_date_is_not_late(score):
    out = score([_record(CLIENT, due="2025-01-20", filed="2025-01-20")])
    assert out[CLIENT]["late_filing_history"] == 0 and out[CLIENT]["risk_score"] == 0


def test_a_filed_record_with_no_recorded_date_is_not_counted_late(score):
    """Absent evidence is not evidence of lateness: the count is of filings the CA recorded a date for."""
    out = score([_record(CLIENT, filed=None)])
    assert out[CLIENT]["late_filing_history"] == 0


def test_only_a_filed_record_can_be_late_history(score):
    """An open record past its due date is OVERDUE (25 points), not late history; a filed_date on it means nothing."""
    out = score([_record(CLIENT, status="pending", filed="2025-02-01")])
    assert out[CLIENT]["late_filing_history"] == 0
    assert out[CLIENT]["overdue_count"] == 1


def test_one_clients_late_filing_does_not_move_anothers_score(score):
    out = score([_record(CLIENT, filed="2025-03-01")])
    assert out[CLIENT]["late_filing_history"] == 1
    assert out[OTHER]["late_filing_history"] == 0 and out[OTHER]["risk_score"] == 0


def test_two_late_filings_add_the_twenty_once(score):
    out = score([_record(CLIENT, due="2025-01-20", filed="2025-01-25"),
                 _record(CLIENT, due="2025-02-20", filed="2025-02-28")])
    assert out[CLIENT]["late_filing_history"] == 2
    assert out[CLIENT]["risk_score"] == 20, "the rule is 'any history of late filing', +20 once"


def test_a_timestamp_shaped_filed_date_is_read_by_its_date(score):
    out = score([_record(CLIENT, due="2025-01-20", filed="2025-01-25T00:00:00+00:00")])
    assert out[CLIENT]["late_filing_history"] == 1


def test_the_engine_no_longer_reads_a_column_the_table_does_not_have():
    import inspect
    src = inspect.getsource(isvc.compute_compliance_risk)
    assert '"filed_at"' not in src
    assert '"filed_date"' in src
