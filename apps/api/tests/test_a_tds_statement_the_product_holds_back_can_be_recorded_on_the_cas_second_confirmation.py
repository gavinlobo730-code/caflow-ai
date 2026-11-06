"""
A TDS statement the product holds back can be recorded on the CA's own second confirmation (POST-A-402).

`update_return_status` refuses to record a statement as CA approved or filed when it holds no deductees or its quarter has not ended,
unless the request carries `acknowledge_incomplete`. The refusal used to end "Resubmit with acknowledge_incomplete=true to record it
anyway": an instruction no screen could follow, because nothing in the web app sent the flag. So a CA who had filed a statement on the
portal that this product held no deductees for (a shell made with "New Return", or a quarter whose books are kept elsewhere) could not
record that it was filed. The sentence is for a person now, the answer carries a marker the screen turns into "Record it anyway", and
the override is written to the audit log with what the statement was recorded over.
"""
from __future__ import annotations

import pytest

import routers.tds_workspace as tds_ws
from routers.tds_workspace import (
    CreateReturnRequest, UpdateReturnStatusRequest, _the_refusal, _what_is_incomplete, _why_this_status_cannot_be_recorded,
    create_return, update_return_status,
)

USER = {"firm_id": "firm-1", "id": "u1", "auth_user_id": "a1", "role": "partner"}
CLIENT = "client-1"
THE_FUTURE_QUARTER_END = "2099-06-30"


def _row(**over):
    base = {"status": "prepared", "deductee_count": 4, "quarter_end": "2025-06-30", "quarter": "Q1", "financial_year": "2025-26"}
    base.update(over)
    return base


def _ask(status="ca_approved", **over):
    return UpdateReturnStatusRequest(status=status, ca_approved=True, **over)


# ── the refusal, as a person reads it ───────────────────────────────────────

def test_a_statement_with_no_deductees_is_refused_in_words_that_name_no_flag():
    refusal = _the_refusal(_ask(), _row(deductee_count=0), None)
    assert refusal.sentence == "This return cannot be recorded as CA approved because it has no deductees recorded."
    assert "acknowledge_incomplete" not in refusal.sentence and "Resubmit" not in refusal.sentence
    assert refusal.marker() == {"can_record_anyway": True, "incomplete": ["it has no deductees recorded"]}


def test_both_reasons_are_joined_and_both_are_in_the_marker():
    refusal = _the_refusal(_ask(), _row(deductee_count=0, quarter_end=THE_FUTURE_QUARTER_END), None)
    assert refusal.sentence == ("This return cannot be recorded as CA approved because it has no deductees recorded and its "
                                f"quarter has not ended yet (ends {THE_FUTURE_QUARTER_END}).")
    assert refusal.marker()["incomplete"] == ["it has no deductees recorded",
                                              f"its quarter has not ended yet (ends {THE_FUTURE_QUARTER_END})"]


def test_the_word_for_filing_is_filed():
    refusal = _the_refusal(_ask("filed", prn="123456789012345", filing_date="2025-07-20"), _row(status="ca_approved", deductee_count=0), "2025-07-20")
    assert refusal.sentence == "This return cannot be recorded as filed because it has no deductees recorded."
    assert refusal.marker()["can_record_anyway"] is True


def test_the_wrapper_the_drive_test_reads_gives_the_same_sentence():
    body, row = _ask(), _row(deductee_count=0)
    assert _why_this_status_cannot_be_recorded(body, row, None) == _the_refusal(body, row, None).sentence


def test_a_complete_statement_is_not_refused():
    assert _the_refusal(_ask(), _row(), None) is None
    assert _what_is_incomplete(_row()) == []


def test_the_flag_lets_the_statement_through_and_the_other_checks_still_stand():
    assert _the_refusal(_ask(acknowledge_incomplete=True), _row(deductee_count=0, quarter_end=THE_FUTURE_QUARTER_END), None) is None
    # …but a statement that is already filed, or filed from the wrong state, is not something the flag records over
    already = _the_refusal(_ask("filed", prn="1", filing_date="2025-07-20", acknowledge_incomplete=True), _row(status="filed"), "2025-07-20")
    assert already.sentence == "This return has already been filed." and already.marker() is None
    from_prepared = _the_refusal(_ask("filed", prn="1", filing_date="2025-07-20", acknowledge_incomplete=True), _row(status="prepared"), "2025-07-20")
    assert "approve it first" in from_prepared.sentence and from_prepared.marker() is None


def test_the_flag_does_not_waive_a_filing_date_before_a_quarter_that_has_ended():
    """Found by the independent read: the date rule sat inside `not acknowledge_incomplete`, so two presses on a statement with no deductees recorded a
    filing dated before its quarter ended (which cannot be moved back). The flag is the CA's confirmation of what the product held back, not of a date."""
    early = _ask("filed", prn="123456789012345", filing_date="2025-06-15", acknowledge_incomplete=True)
    refusal = _the_refusal(early, _row(status="ca_approved", deductee_count=0), "2025-06-15")
    assert refusal.sentence == ("A statement for Q1 FY 2025-26 cannot have been filed before the quarter ended on 2025-06-30. "
                                "Check the date on the receipt.")
    assert refusal.marker() is None, "the date is refused outright: there is no second confirmation for it"


def test_the_date_is_asked_before_the_question_so_the_cas_confirmation_is_for_the_right_statement():
    no_flag_early = _the_refusal(_ask("filed", prn="1", filing_date="2025-06-15"), _row(status="ca_approved", deductee_count=0), "2025-06-15")
    assert "cannot have been filed before the quarter ended" in no_flag_early.sentence and no_flag_early.marker() is None
    # with a date that can be right, the first press is the question and the second records it
    no_flag_good = _the_refusal(_ask("filed", prn="1", filing_date="2025-07-20"), _row(status="ca_approved", deductee_count=0), "2025-07-20")
    assert no_flag_good.marker() == {"can_record_anyway": True, "incomplete": ["it has no deductees recorded"]}
    assert _the_refusal(_ask("filed", prn="1", filing_date="2025-07-20", acknowledge_incomplete=True),
                        _row(status="ca_approved", deductee_count=0), "2025-07-20") is None
    # a complete statement is refused the early date as it always was
    complete_early = _the_refusal(_ask("filed", prn="1", filing_date="2025-06-15"), _row(status="ca_approved"), "2025-06-15")
    assert "cannot have been filed before the quarter ended" in complete_early.sentence


def test_a_quarter_that_has_not_ended_is_recorded_over_by_the_flag_whatever_the_date():
    """Every date is before the end of a quarter that has not ended: that is what the CA was told and confirmed, so the date rule is not asked."""
    future = _row(status="ca_approved", quarter_end=THE_FUTURE_QUARTER_END)
    flagged = _ask("filed", prn="1", filing_date="2026-10-07", acknowledge_incomplete=True)
    assert _the_refusal(flagged, future, "2026-10-07") is None
    asked = _the_refusal(_ask("filed", prn="1", filing_date="2026-10-07"), future, "2026-10-07")
    assert asked.marker()["incomplete"] == [f"its quarter has not ended yet (ends {THE_FUTURE_QUARTER_END})"]


def test_a_refusal_nothing_may_be_recorded_over_offers_no_second_confirmation():
    furnished = _the_refusal(_ask(), _row(status="filed", prn="777"), None)
    assert "cannot be changed here" in furnished.sentence and furnished.marker() is None
    before_quarter_end = _the_refusal(_ask("filed", prn="1", filing_date="2025-06-01"), _row(status="ca_approved"), "2025-06-01")
    assert "cannot have been filed before the quarter ended" in before_quarter_end.sentence and before_quarter_end.marker() is None


# ── the door ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_store(monkeypatch):
    tds_ws._MOCK_RETURNS.clear()
    monkeypatch.setattr(tds_ws, "_USE_MOCK", True)
    calls = []
    monkeypatch.setattr(tds_ws, "log_event", lambda *a, **k: calls.append((a, k)))
    yield calls
    tds_ws._MOCK_RETURNS.clear()


def _status_changes(calls):
    """The audit rows of status changes (creating the shell wrote one of its own)."""
    return [c for c in calls if c[0][3] == "status_change"]


def _shell(deductee_count=0):
    out = create_return(CreateReturnRequest(client_id=CLIENT, return_type="26Q", quarter="Q1", financial_year="2025-26",
                                            deductee_count=deductee_count), USER)
    assert out["success"] is True, out
    return out["data"]["id"]


def test_the_door_answers_the_refusal_with_the_marker_and_changes_nothing(mock_store):
    rid = _shell()
    tds_ws._MOCK_RETURNS[rid]["status"] = "prepared"
    out = update_return_status(rid, _ask(), USER)
    assert out["success"] is False
    assert out["error"] == "This return cannot be recorded as CA approved because it has no deductees recorded."
    assert out["data"] == {"can_record_anyway": True, "incomplete": ["it has no deductees recorded"]}
    assert tds_ws._MOCK_RETURNS[rid]["status"] == "prepared"
    assert _status_changes(mock_store) == [], "a refused change leaves no audit row"


def test_a_refusal_with_no_way_on_answers_no_marker():
    rid = _shell(deductee_count=2)
    out = update_return_status(rid, UpdateReturnStatusRequest(status="filed", ca_approved=True, prn="123456789012345",
                                                              filing_date="2025-07-20"), USER)
    assert out["success"] is False and out["data"] is None and "approve it first" in out["error"]


def test_the_second_confirmation_records_it_and_the_audit_row_says_what_it_was_recorded_over(mock_store):
    rid = _shell()
    tds_ws._MOCK_RETURNS[rid]["status"] = "prepared"
    out = update_return_status(rid, _ask(acknowledge_incomplete=True), USER)
    assert out["success"] is True and out["data"]["status"] == "ca_approved"
    (args, kwargs), = _status_changes(mock_store)
    assert args[:4] == ("firm-1", "tds_return", rid, "status_change")
    assert kwargs["new_data"] == {"status": "ca_approved", "recorded_over": ["it has no deductees recorded"]}


def test_a_complete_statement_recorded_with_the_flag_leaves_no_recorded_over(mock_store):
    """The flag is a confirmation of what was incomplete. Where nothing was, the row says nothing was recorded over."""
    rid = _shell(deductee_count=3)
    tds_ws._MOCK_RETURNS[rid]["status"] = "prepared"
    out = update_return_status(rid, _ask(acknowledge_incomplete=True), USER)
    assert out["success"] is True
    (_, kwargs), = _status_changes(mock_store)
    assert kwargs["new_data"] == {"status": "ca_approved"}


def test_a_complete_statement_recorded_without_the_flag_is_audited_as_before(mock_store):
    rid = _shell(deductee_count=3)
    tds_ws._MOCK_RETURNS[rid]["status"] = "prepared"
    assert update_return_status(rid, _ask(), USER)["success"] is True
    (_, kwargs), = _status_changes(mock_store)
    assert kwargs["new_data"] == {"status": "ca_approved"}


# ── who may record over it ──────────────────────────────────────────────────

def _person(role, **overrides):
    return {"firm_id": "firm-1", "id": f"{role}-1", "auth_user_id": f"auth-{role}", "role": role, "permission_overrides": overrides}


def _prepared_shell():
    rid = _shell()
    tds_ws._MOCK_RETURNS[rid]["status"] = "prepared"
    return rid


@pytest.mark.parametrize("who", [_person("Executive"), _person("Reviewer"), _person("Manager", **{"tds:approve": False})])
def test_nobody_without_the_approval_of_tds_records_over_the_refusal(who):
    """The gate asks the PERSON (a per-person row wins, the role decides where there is none), so a Manager whose approval of TDS the Team grid
    switched off no longer records over a refusal, and neither does anyone below Manager."""
    rid = _prepared_shell()
    out = update_return_status(rid, _ask(acknowledge_incomplete=True), who)
    assert out["success"] is False and out["error"] == "Only Manager or above can approve or file a TDS return."
    assert tds_ws._MOCK_RETURNS[rid]["status"] == "prepared"


def test_a_member_the_grid_has_given_the_approval_of_tds_can():
    rid = _prepared_shell()
    out = update_return_status(rid, _ask(acknowledge_incomplete=True), _person("Executive", **{"tds:approve": True}))
    assert out["success"] is True and out["data"]["status"] == "ca_approved"
