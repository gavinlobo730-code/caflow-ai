"""An income-tax return becomes Filed by recording its acknowledgement, and recording it closes the ITR obligation (found while seeding the firm's ITR data).

WHAT WAS WRONG
    1. The state machine listed `filed` as the step after `ready_for_filing`, and the transition door took it like any other
       step. The filing screen offered it ("Move to Filed" sat beside the acknowledgement form), so a return could go
       terminal with NO acknowledgement number and NO filing date, and then the acknowledgement could never be recorded:
       a filed return is refused a second one. The only way back was the database.
    2. Recording an acknowledgement moved `itr_filings` and left the calendar's ITR obligation at Not Started, so a return
       filed on 24 July read Filed on the tax screen and Overdue on Deadlines, the Compliance tab and the dashboard (the
       GST workspace had the same split: POST-A-264).
    3. The acknowledgement's date was free text. A date that was not a date reached a DATE column and came back as a 500,
       and nothing asked whether a return for a year could have been filed before the year had ended.

WHAT IS HELD
    * a transition to `filed` is refused with a sentence that names the acknowledgement; the return stays where it was and
      the acknowledgement can still be recorded; a skip is still refused as the skip it is;
    * the acknowledgement is a real date, not in the future, not before the year the return declares has ended, with a number;
    * recording it closes the client's ITR obligation for that financial year, with the stated date and the acknowledgement
      number, through `mark_filed`, and nothing else on the calendar moves (another year, advance tax, the tax-audit
      report, another client);
    * only an ORIGINAL return closes it; a revised or an updated return corrects one already furnished;
    * an obligation already Filed keeps its own date and number; no obligation on the calendar, no compliance access, or a
      failure closing it never fails the recording and is said in the answer.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routers.itr_workspace as itr
from domain import compliance_record_service as crs
from domain.income_tax import itr_workflow as wf
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import itr_return_closes_obligation as closes
from services import obligation_closure

FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}
FY, AY = "2025-26", "2026-27"
STATED, ACK = "2026-07-24", "123456780240726"


@pytest.fixture
def world(monkeypatch):
    import services.audit_service as au
    import services.timeline_service as ts
    assert wf._USE_MOCK, "this file drives the workflow in its in-memory mode"
    MOCK_COMPLIANCE_RECORDS.clear()
    wf._MOCK_FILINGS.clear()
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(itr.timeline_service, "log", lambda *a, **k: None)
    monkeypatch.setattr(itr, "assert_client_access", lambda user, client_id: None)
    monkeypatch.setattr(itr, "can_access_client", lambda user, client_id: True)
    yield
    MOCK_COMPLIANCE_RECORDS.clear()
    wf._MOCK_FILINGS.clear()


def _obligation(otype="ITR", start="2025-04-01", end="2026-03-31", status="Not Started", client=CLIENT,
                ctype="Income Tax", **extra):
    return compliance_records_repo.create({
        "firm_id": FIRM, "client_id": client, "compliance_type": ctype, "obligation_type": otype,
        "period_label": f"{otype} {start}", "period_start": start, "period_end": end, "due_date": "2026-07-31",
        "status": status, **extra})


def _now(rec):
    return compliance_records_repo.find_by_id(rec["id"])


def _filing(*, form="ITR-3", return_type="original", fy=FY, ay=AY, client=CLIENT, upto="ready_for_filing", **extra):
    f = itr.create_filing(itr.CreateFilingRequest(
        client_id=client, financial_year=fy, assessment_year=ay, itr_form=form, return_type=return_type,
        **extra), current_user=USER)["data"]
    for step in ("review", "partner_review", "ready_for_filing"):
        itr.transition_filing(f["id"], itr.TransitionFilingRequest(new_status=step), current_user=USER)
        if step == upto:
            break
    return f


def _ack(filing, number=ACK, day=STATED):
    return itr.record_acknowledgement(
        filing["id"], itr.AcknowledgementRequest(acknowledgement_number=number, filing_date=day), current_user=USER)


# ── 1. filed is not a transition ────────────────────────────────────────────

def test_a_transition_to_filed_is_refused_and_names_the_acknowledgement(world):
    f = _filing()
    with pytest.raises(HTTPException) as refused:
        itr.transition_filing(f["id"], itr.TransitionFilingRequest(new_status="filed"), current_user=USER)
    assert refused.value.status_code == 400
    assert "acknowledgement" in refused.value.detail
    assert wf._MOCK_FILINGS[f["id"]]["status"] == "ready_for_filing"
    assert not wf._MOCK_FILINGS[f["id"]].get("acknowledgement_number")


def test_the_acknowledgement_can_still_be_recorded_after_the_refused_transition(world):
    """The regression: a return moved to filed by the transition door could never be given its acknowledgement."""
    f = _filing()
    with pytest.raises(HTTPException):
        itr.transition_filing(f["id"], itr.TransitionFilingRequest(new_status="filed"), current_user=USER)
    out = _ack(f)
    assert out["success"] is True
    assert out["data"]["status"] == "filed" and out["data"]["acknowledgement_number"] == ACK
    assert out["data"]["filing_date"] == STATED


def test_a_skip_to_filed_is_still_refused_as_a_skip(world):
    f = _filing(upto="review")
    with pytest.raises(HTTPException) as refused:
        itr.transition_filing(f["id"], itr.TransitionFilingRequest(new_status="filed"), current_user=USER)
    assert "Cannot transition" in refused.value.detail


def test_the_state_machine_still_leads_ready_for_filing_to_filed_for_the_acknowledgement_to_use():
    assert wf._TRANSITIONS["ready_for_filing"] == ["filed"]
    assert "ready_for_filing" in wf._MAY_BECOME_FILED


# ── 3. the acknowledgement's date and number ────────────────────────────────

@pytest.mark.parametrize("day", ["banana", "24/07/2026", "2026-13-40", "", "2026-7-24"])
def test_a_date_that_is_not_a_date_is_refused_before_it_reaches_the_database(day):
    with pytest.raises(ValidationError) as refused:
        itr.AcknowledgementRequest(acknowledgement_number=ACK, filing_date=day)
    assert "filing_date must be YYYY-MM-DD" in str(refused.value)
    assert "filed_date" not in str(refused.value).replace("filing_date", "")


def test_a_filing_date_in_the_future_is_refused():
    with pytest.raises(ValidationError) as refused:
        itr.AcknowledgementRequest(acknowledgement_number=ACK, filing_date="2999-01-01")
    assert "cannot be in the future" in str(refused.value)


@pytest.mark.parametrize("number", ["", "   "])
def test_an_empty_acknowledgement_number_is_refused(number):
    with pytest.raises(ValidationError):
        itr.AcknowledgementRequest(acknowledgement_number=number, filing_date=STATED)


def test_the_number_is_stored_trimmed():
    assert itr.AcknowledgementRequest(acknowledgement_number="  " + ACK + " ", filing_date=STATED) \
        .acknowledgement_number == ACK


def test_a_return_cannot_have_been_filed_before_its_year_ended(world):
    f = _filing()
    with pytest.raises(HTTPException) as refused:
        _ack(f, day="2026-03-30")
    assert refused.value.status_code == 400 and "before the year ended on 2026-03-31" in refused.value.detail
    assert wf._MOCK_FILINGS[f["id"]]["status"] == "ready_for_filing", "a refused date must not file the return"


def test_the_last_day_of_the_year_is_not_before_it_ended(world):
    out = _ack(_filing(), day="2026-03-31")
    assert out["success"] is True


# ── 2. the acknowledgement closes the obligation ────────────────────────────

def test_recording_the_acknowledgement_closes_the_obligation_with_the_stated_date_and_number(world):
    obligation = _obligation()
    out = _ack(_filing())
    assert out["success"] is True
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "closed" and answer["closed"] is True and answer["obligation_id"] == obligation["id"]
    now = _now(obligation)
    assert now["status"] == "Filed" and now["filed_date"] == STATED and now["acknowledgement_no"] == ACK
    assert out["data"]["status"] == "filed", "the answer is still the filing"


def test_nothing_else_on_the_calendar_moves(world):
    # Created BEFORE the target, so a match that ignored the year, the type or the client would pick one of them first.
    earlier_year = _obligation(start="2024-04-01", end="2025-03-31")
    advance_tax = _obligation("ADVANCE_TAX", start="2026-03-15", end="2026-03-15")
    tax_audit = _obligation("TAX_AUDIT")
    other_client = _obligation(client="client-2")
    other_type = _obligation(ctype="GST")
    target = _obligation()
    _ack(_filing())
    assert _now(target)["status"] == "Filed"
    for untouched in (earlier_year, advance_tax, tax_audit, other_client, other_type):
        assert _now(untouched)["status"] == "Not Started", (untouched["obligation_type"], untouched["period_start"])


def test_the_window_must_be_the_years_own_first_and_last_day(world):
    """A row that starts on 1 April but ends mid-year, or ends on 31 March but starts mid-year, is not this year's."""
    short_end = _obligation(start="2025-04-01", end="2025-09-30")
    late_start = _obligation(start="2025-10-01", end="2026-03-31")
    out = _ack(_filing())
    assert out["data"]["compliance_obligation"]["state"] == "not_on_the_calendar"
    assert _now(short_end)["status"] == "Not Started" and _now(late_start)["status"] == "Not Started"


def test_an_obligation_already_filed_keeps_its_own_date_and_number(world):
    obligation = _obligation(status="Filed", filed_date="2026-07-20", acknowledgement_no="THE-CAS-OWN-NUMBER")
    out = _ack(_filing())
    assert out["data"]["compliance_obligation"]["state"] == "already_filed"
    now = _now(obligation)
    assert now["filed_date"] == "2026-07-20" and now["acknowledgement_no"] == "THE-CAS-OWN-NUMBER"


def test_no_obligation_on_the_calendar_files_the_return_and_says_so(world):
    out = _ack(_filing())
    assert out["success"] is True and out["data"]["status"] == "filed"
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_on_the_calendar" and "FY 2025-26" in answer["message"]


@pytest.mark.parametrize("kind", ["revised", "updated"])
def test_a_correction_closes_no_obligation_of_its_own(world, kind):
    obligation = _obligation()
    # The original was filed outside this product, so its receipt is typed; the obligation is still open.
    out = _ack(_filing(return_type=kind, original_acknowledgement_number="123456780240715",
                       original_filing_date="2026-07-15"), number="123456780250101")
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_the_original" and answer["closed"] is False
    assert kind in answer["message"] and "Compliance" in answer["message"]
    assert _now(obligation)["status"] == "Not Started"


def test_a_second_form_for_the_same_year_finds_the_obligation_already_filed(world):
    obligation = _obligation()
    _ack(_filing(form="ITR-3"))
    out = _ack(_filing(form="ITR-4"), number="123456780240727")
    assert out["data"]["compliance_obligation"]["state"] == "already_filed"
    assert _now(obligation)["acknowledgement_no"] == ACK, "the first acknowledgement stays"


def test_a_caller_without_compliance_access_files_and_the_obligation_stays_open(world, monkeypatch):
    monkeypatch.setattr(itr, "can_user", lambda user, resource, action: not (resource == "compliance" and action == "write"))
    obligation = _obligation()
    out = _ack(_filing())
    assert out["success"] is True and out["data"]["status"] == "filed"
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_allowed" and "Compliance" in answer["message"]
    assert _now(obligation)["status"] == "Not Started"


def test_the_permission_asked_is_compliance_write_per_person(world, monkeypatch):
    asked = []
    monkeypatch.setattr(itr, "can_user", lambda user, resource, action: asked.append((resource, action)) or True)
    _obligation()
    _ack(_filing())
    assert ("compliance", "write") in asked


# ── a failure never fails the recording ─────────────────────────────────────

def test_an_unexpected_failure_closing_the_obligation_does_not_fail_the_recording(world, monkeypatch):
    reported = []
    import core.observability as obs
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **kw: reported.append((str(exc), kw)))
    monkeypatch.setattr(closes, "close_for_filed_return",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("calendar read failed")))
    obligation = _obligation()
    out = _ack(_filing())
    assert out["success"] is True and out["data"]["status"] == "filed" and out["data"]["acknowledgement_number"] == ACK
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_closed" and "Mark the obligation filed from Compliance" in answer["message"]
    assert reported and reported[0][1]["operation"] == "itr_workspace.close_the_obligation"
    assert _now(obligation)["status"] == "Not Started"


def test_a_walk_that_stops_part_way_says_where_the_obligation_really_is(world, monkeypatch):
    reported = []
    monkeypatch.setattr(obligation_closure, "capture_soft_failure", lambda exc, **kw: reported.append(kw["operation"]))
    real = crs.compliance_record_service.update_record

    def fail_on_the_last_step(record_id, data, **kw):
        if data.get("status") == "Filed":
            raise RuntimeError("write failed")
        return real(record_id, data, **kw)
    monkeypatch.setattr(crs.compliance_record_service, "update_record", fail_on_the_last_step)
    obligation = _obligation()
    out = _ack(_filing())
    assert out["success"] is True and out["data"]["status"] == "filed"
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_closed" and "Ready To File" in answer["message"] and "Compliance" in answer["message"]
    assert _now(obligation)["status"] == "Ready To File"
    assert reported == ["itr_return_closes_obligation.mark_filed"]


def test_a_return_that_names_no_client_or_firm_matches_nothing(world):
    """`find_all` drops an empty filter, which would read every client's calendar."""
    _obligation()
    for firm, client in (("", CLIENT), (FIRM, "")):
        answer = closes.close_for_filed_return(
            firm_id=firm, client_id=client, financial_year=FY, return_type="original", filed_date=STATED,
            acknowledgement_number=ACK, actor=USER, may_write_compliance=True)
        assert answer["state"] == "not_closed" and answer["closed"] is False


def test_a_label_that_is_not_a_year_is_left_to_the_calendar(world):
    answer = closes.close_for_filed_return(
        firm_id=FIRM, client_id=CLIENT, financial_year="not-a-year", return_type="original", filed_date=STATED,
        acknowledgement_number=ACK, actor=USER, may_write_compliance=True)
    assert answer["state"] == "not_closed" and "Compliance" in answer["message"]


def test_the_calendar_row_is_read_for_this_firm_and_client_only(world):
    mine = _obligation()
    theirs = compliance_records_repo.create({
        "firm_id": "firm-2", "client_id": CLIENT, "compliance_type": "Income Tax", "obligation_type": "ITR",
        "period_label": "ITR", "period_start": "2025-04-01", "period_end": "2026-03-31", "due_date": "2026-07-31",
        "status": "Not Started"})
    _ack(_filing())
    assert _now(mine)["status"] == "Filed" and _now(theirs)["status"] == "Not Started"


# ── an update that matched no row is a refusal, not a success ───────────────

class _OneFilingDatabase:
    """The slice of PostgREST the workflow's database branch talks to, holding one filing. Reads find it; an update
    "matches no row" (the filing was removed in the meantime, or row security refused the change), which PostgREST
    answers with an empty list."""

    def __init__(self, row):
        self.row, self.updates = row, 0

    def table(self, name):
        assert name == "itr_filings"
        return _Chain(self)


class _Chain:
    def __init__(self, db):
        self.db, self.op = db, "read"

    def select(self, *a, **k):
        return self

    def update(self, *a, **k):
        self.op = "update"
        self.db.updates += 1
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        self.one = True
        return self

    maybe_single = single

    def execute(self):
        from types import SimpleNamespace
        if self.op == "update":
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=self.db.row if getattr(self, "one", False) else [self.db.row])


@pytest.fixture
def vanishing_filing(world, monkeypatch):
    row = {"id": "f-1", "firm_id": FIRM, "client_id": CLIENT, "financial_year": FY, "assessment_year": AY,
           "itr_form": "ITR-3", "status": "ready_for_filing", "return_type": "original",
           "computation_snapshot_id": None, "acknowledgement_number": None}
    db = _OneFilingDatabase(row)
    monkeypatch.setattr(wf, "_USE_MOCK", False)
    monkeypatch.setattr(wf, "_supabase", lambda: db)
    return db


def test_an_acknowledgement_whose_update_matched_no_row_is_refused_and_closes_nothing(vanishing_filing):
    obligation = _obligation()
    with pytest.raises(HTTPException) as refused:
        itr.record_acknowledgement(
            "f-1", itr.AcknowledgementRequest(acknowledgement_number=ACK, filing_date=STATED), current_user=USER)
    assert refused.value.status_code == 400
    assert "Nothing was changed" in refused.value.detail and "record the acknowledgement" in refused.value.detail
    assert vanishing_filing.updates == 1, "the update was attempted once and matched nothing"
    assert _now(obligation)["status"] == "Not Started", "the calendar must not be closed for a return that was not filed"


def test_a_transition_whose_update_matched_no_row_is_refused(vanishing_filing):
    vanishing_filing.row["status"] = "partner_review"
    with pytest.raises(HTTPException) as refused:
        itr.transition_filing("f-1", itr.TransitionFilingRequest(new_status="ready_for_filing"), current_user=USER)
    assert refused.value.status_code == 400 and "Nothing was changed" in refused.value.detail


def test_the_refusal_text_is_one_helper_and_not_two_copies():
    import inspect
    src = inspect.getsource(wf)
    assert src.count("def _the_updated_row(") == 1
    assert "return res.data[0] if res.data else {}" not in src, "an update that matched nothing is answered as a success again"


def test_the_transition_door_does_not_advertise_filed_and_logs_no_filed_event():
    import inspect
    assert "filed" not in itr.TransitionFilingRequest.model_fields["new_status"].description.replace("ready_for_filing", "")
    handler = inspect.getsource(itr.transition_filing)
    assert '"filed": ("ITR filed"' not in handler

