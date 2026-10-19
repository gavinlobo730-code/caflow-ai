"""A TDS statement is recorded as filed on a date the CA states, stays filed, and closes its quarterly obligation (found while
preparing to seed the firm's TDS data).

WHAT WAS WRONG, driven through the real door over a real database on 19-10-2026
    1. `PATCH /api/tds-workspace/returns/{id}/status` took `filing_date` as free text and stored it in `filed_at`:
       "2999-01-01" was recorded as the day a statement was filed, and "banana" came back as a generic failure. The screen's
       "Mark as Filed" modal sent no date at all, so `filed_at` was the instant the CA pressed the button, which is not the
       day they filed on the portal and is the date the late-filing fee and the calendar both turn on.
    2. A filed statement could be moved back to pending or prepared, leaving a PRN and a filing date on a statement the
       screen then called unfiled. `_revise_tds_return` already says a filed statement is final here ("a correction is a
       correction statement on TRACES"); the status door did not.
    3. An update that matched no row (the statement removed in the meantime, or the caller's row security refusing the
       change: PostgREST answers both with an empty list) was answered `{}` as a success, with the audit row and the
       timeline entry written for a change that never happened.
    4. Recording the PRN moved `tds_returns` and left the calendar's TDS24Q / TDS26Q / TDS27Q obligation at Not Started, so
       a quarter filed on 28 October read Filed on the TDS screen and Overdue on Deadlines, the Compliance tab and the
       dashboard. The GST workspace (POST-A-264) and the ITR workspace had the same split.

WHAT IS HELD
    * the date is required to mark a statement filed, is never defaulted, is a real date not in the future, and is not
      before the quarter the statement reports on has ended (unless the CA names the override, which skips that one check);
    * a filed statement's status cannot be changed through this door, and a second "filed" is still the duplicate it was;
    * an update that matched no row is a refusal and writes nothing;
    * recording the PRN closes the client's obligation for THAT statement and THAT quarter, with the stated date and the PRN,
      through `mark_filed`, and nothing else on the calendar moves (another quarter, the other statements, the monthly
      deposits, another client, another firm, another compliance type);
    * Form 27EQ has no obligation on the calendar and says so; an obligation already Filed keeps its own date and number; no
      obligation, no compliance access, or a failure closing it never fails the recording and is said in the answer.
"""
from __future__ import annotations

import pytest

import core.supabase_client as sc
import routers.tds_workspace as tw
from domain import compliance_record_service as crs
from domain.tds.section_rates import quarter_dates
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from routers.tds_workspace import (
    CreateReturnRequest, UpdateReturnStatusRequest, create_return, update_return_status,
)
from services import obligation_closure
from services import tds_return_closes_obligation as closes

FIRM, CLIENT = "firm-1", "client-1"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "a1", "email": "ca@f.test", "role": "Partner"}
FY = "2025-26"
STATED, PRN = "2025-10-28", "PRN2526Q2000042"


@pytest.fixture(autouse=True)
def world(monkeypatch):
    assert tw._USE_MOCK, "this file drives the handlers in their in-memory mode"
    tw._MOCK_RETURNS.clear()
    MOCK_COMPLIANCE_RECORDS.clear()
    monkeypatch.setattr(tw, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(tw.timeline_service, "log_timeline_event", lambda *a, **k: None)
    import services.audit_service as au
    import services.timeline_service as ts
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    yield
    tw._MOCK_RETURNS.clear()
    MOCK_COMPLIANCE_RECORDS.clear()


def _obligation(kind="TDS26Q", quarter="Q2", fy=FY, status="Not Started", client=CLIENT, ctype="TDS", firm=FIRM, **extra):
    start, end, due = quarter_dates(fy, quarter)
    return compliance_records_repo.create({
        "firm_id": firm, "client_id": client, "compliance_type": ctype, "obligation_type": kind,
        "period_label": f"{kind} {quarter} {fy}", "period_start": start, "period_end": end, "due_date": due,
        "status": status, **extra})


def _now(rec):
    return compliance_records_repo.find_by_id(rec["id"])


def _statement(return_type="26Q", quarter="Q2", fy=FY, client=CLIENT):
    """A computed statement with one deductee, which is what the 'Compute from Books' save sends."""
    out = create_return(CreateReturnRequest(
        client_id=client, return_type=return_type, quarter=quarter, financial_year=fy,
        deductee_details=[{"deductee_pan": "ABCDE1234F", "section": "194C", "tds_paise": 20000}],
        total_deductions_paise=20000, total_deposits_paise=20000, deductee_count=1, validation_errors=[]), PARTNER)
    assert out["success"] is True, out
    return out["data"]


def _approve(row, **extra):
    out = update_return_status(row["id"], UpdateReturnStatusRequest(status="ca_approved", ca_approved=True, **extra), PARTNER)
    assert out["success"] is True, out


def _file(row, *, day=STATED, prn=PRN, approved=True, **extra):
    """Mark the statement filed, approving it first (a statement is filed from CA approved) unless told it already is."""
    if approved and tw._MOCK_RETURNS[row["id"]]["status"] in ("pending", "prepared"):
        _approve(row, acknowledge_incomplete=extra.get("acknowledge_incomplete", False))
    return update_return_status(row["id"], UpdateReturnStatusRequest(
        status="filed", ca_approved=True, prn=prn, ack_number="ACK-1", filing_date=day, **extra), PARTNER)


# ── 1. the date ─────────────────────────────────────────────────────────────

def test_the_request_model_takes_the_text_so_that_the_door_can_answer_it_in_its_own_way():
    """A validation error here would reach the screen as the framework's raw 422 shape, which carries no `error`, and the
    TDS screen would say only "Failed to mark as filed". The door judges the date and answers `success: false`."""
    body = UpdateReturnStatusRequest(status="filed", ca_approved=True, prn=PRN, filing_date="2999-01-01")
    assert body.filing_date == "2999-01-01"


@pytest.mark.parametrize("day", ["banana", "28/10/2025", "2025-13-40", "2025-10-2"])
def test_a_date_that_is_not_a_date_is_refused_in_the_doors_own_words_and_nothing_is_stored(day):
    row = _statement()
    obligation = _obligation()
    out = _file(row, day=day)
    assert out["success"] is False
    assert "filing_date must be YYYY-MM-DD" in out["error"] and "receipt" in out["error"]
    assert "filed_date" not in out["error"].replace("filing_date", "")
    stored = tw._MOCK_RETURNS[row["id"]]
    assert stored["status"] == "ca_approved" and not stored.get("prn") and not stored.get("filed_at")
    assert _now(obligation)["status"] == "Not Started"


def test_a_filing_date_in_the_future_is_refused_in_the_doors_own_words():
    row = _statement()
    out = _file(row, day="2999-01-01")
    assert out["success"] is False and "cannot be in the future" in out["error"]
    assert tw._MOCK_RETURNS[row["id"]]["status"] == "ca_approved"
    assert not tw._MOCK_RETURNS[row["id"]].get("filed_at")


def test_a_date_written_another_valid_way_is_stored_in_the_one_spelling():
    row = _statement()
    out = _file(row, day="20251028")
    assert out["success"] is True and str(out["data"]["filed_at"])[:10] == "2025-10-28"


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_blank_date_is_not_a_date_and_is_read_as_none_said(blank):
    assert UpdateReturnStatusRequest(status="prepared", filing_date=blank).filing_date is None


def test_the_prn_and_the_acknowledgement_number_are_stored_trimmed():
    body = UpdateReturnStatusRequest(status="filed", ca_approved=True, prn=f"  {PRN} ", ack_number="  ",
                                     filing_date=STATED)
    assert body.prn == PRN and body.ack_number is None


def test_marking_a_statement_filed_without_a_date_is_refused_and_nothing_is_filed():
    row = _statement()
    _approve(row)
    obligation = _obligation()
    out = update_return_status(row["id"], UpdateReturnStatusRequest(
        status="filed", ca_approved=True, prn=PRN), PARTNER)
    assert out["success"] is False
    assert "date the statement was filed" in out["error"] and "never defaulted" in out["error"]
    assert tw._MOCK_RETURNS[row["id"]]["status"] == "ca_approved" and not tw._MOCK_RETURNS[row["id"]].get("prn")
    assert _now(obligation)["status"] == "Not Started"


def test_a_date_is_not_needed_for_the_steps_before_filing():
    row = _statement()
    for step in ("prepared", "ca_approved"):
        out = update_return_status(row["id"], UpdateReturnStatusRequest(status=step, ca_approved=True), PARTNER)
        assert out["success"] is True and out["data"]["status"] == step
        assert "compliance_obligation" not in out["data"], "only a filing is answered with the calendar"


def test_the_stated_date_is_what_is_stored_not_the_day_it_was_recorded():
    row = _statement()
    out = _file(row, day="2025-10-28")
    assert out["success"] is True
    assert out["data"]["filed_at"] == "2025-10-28T00:00:00+00:00", (
        "the day the CA stated, as midnight UTC spelled out: 05:30 IST the same day, so the two calendars agree")


def test_a_statement_cannot_have_been_filed_before_its_quarter_ended():
    row = _statement()                                   # Q2 ends on 30 September 2025
    obligation = _obligation()
    out = _file(row, day="2025-09-29")
    assert out["success"] is False
    assert "before the quarter ended on 2025-09-30" in out["error"] and "Q2" in out["error"]
    assert tw._MOCK_RETURNS[row["id"]]["status"] == "ca_approved" and not tw._MOCK_RETURNS[row["id"]].get("prn")
    assert _now(obligation)["status"] == "Not Started"


def test_the_last_day_of_the_quarter_is_not_before_it_ended():
    assert _file(_statement(), day="2025-09-30")["success"] is True


def test_a_quarter_that_has_not_ended_is_still_refused_in_the_words_it_always_was():
    row = _statement(quarter="Q4", fy="2099-00")             # a quarter that cannot have ended yet
    _approve(row, acknowledge_incomplete=True)               # approving it needed the override too
    out = update_return_status(row["id"], UpdateReturnStatusRequest(
        status="filed", ca_approved=True, prn=PRN, filing_date="2025-10-28"), PARTNER)
    assert out["success"] is False and "has not ended yet" in out["error"]


def test_the_override_records_a_statement_the_product_would_hold_back_and_leaves_the_calendar_alone():
    """The override skips the date-against-quarter check; the calendar still refuses a period that has not ended, and the
    answer says so rather than the obligation being marked filed on a quarter nobody has finished."""
    row = _statement(quarter="Q4", fy="2098-99")
    obligation = _obligation(quarter="Q4", fy="2098-99")
    out = _file(row, day="2025-10-28", acknowledge_incomplete=True)
    assert out["success"] is True and out["data"]["status"] == "filed"
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_closed" and answer["closed"] is False
    assert _now(obligation)["status"] == "Not Started"


# ── 2. a statement is filed from CA approved, and stays filed ───────────────

@pytest.mark.parametrize("before", ["pending", "prepared"])
def test_a_statement_that_was_never_approved_cannot_be_marked_filed(before):
    row = _statement()
    if before == "prepared":
        update_return_status(row["id"], UpdateReturnStatusRequest(status="prepared"), PARTNER)
    obligation = _obligation()
    out = _file(row, approved=False)
    assert out["success"] is False
    assert "CA approved" in out["error"] and before in out["error"]
    stored = tw._MOCK_RETURNS[row["id"]]
    assert stored["status"] == before and not stored.get("prn") and not stored.get("ca_approved_by")
    assert _now(obligation)["status"] == "Not Started"


def test_a_filed_statement_always_carries_who_approved_it_and_when():
    row = _statement()
    assert _file(row)["success"] is True
    stored = tw._MOCK_RETURNS[row["id"]]
    assert stored["ca_approved_by"] == PARTNER["id"] and stored["ca_approved_at"]



@pytest.mark.parametrize("step", ["pending", "prepared", "ca_approved"])
def test_a_filed_statement_cannot_be_moved_back(step):
    row = _statement()
    assert _file(row)["success"] is True
    before = dict(tw._MOCK_RETURNS[row["id"]])
    out = update_return_status(row["id"], UpdateReturnStatusRequest(status=step, ca_approved=True,
                                                                    acknowledge_incomplete=True), PARTNER)
    assert out["success"] is False
    assert f"PRN {PRN}" in out["error"] and "correction statement on TRACES" in out["error"]
    assert tw._MOCK_RETURNS[row["id"]] == before


def test_a_second_filed_is_still_the_duplicate_it_was():
    row = _statement()
    _file(row)
    out = _file(row, prn="ANOTHER-PRN", day="2025-10-29")
    assert out["success"] is False and "already been filed" in out["error"]
    assert tw._MOCK_RETURNS[row["id"]]["prn"] == PRN


# ── 3. an update that matched no row ────────────────────────────────────────

class _Chain:
    def __init__(self, db, kind):
        self.db, self.kind = db, kind

    def select(self, columns="*", *a, **k):
        self.db.selected.append(columns)
        return self

    def eq(self, column, value):
        (self.db.update_filters if self.kind == "update" else self.db.read_filters).append((column, value))
        return self

    def limit(self, *a, **k): return self

    def update(self, payload):
        self.db.updates.append(payload)
        return _Chain(self.db, "update")

    def execute(self):
        class R: ...
        r = R()
        r.data = self.db.read_rows if self.kind == "select" else self.db.update_rows
        return r


class _OneStatementDatabase:
    """The slice of PostgREST the handler's database branch talks to, holding one statement."""

    def __init__(self, row, *, update_matches):
        self.read_rows = [row]
        self.update_rows = [{**row, "status": "filed", "prn": PRN}] if update_matches else []
        self.updates, self.selected, self.read_filters, self.update_filters = [], [], [], []

    def table(self, name):
        assert name == "tds_returns"
        return _Chain(self, "select")


def _against_a_database(monkeypatch, *, update_matches):
    row = {"id": "r-1", "client_id": CLIENT, "status": "ca_approved", "deductee_count": 1, "quarter_end": "2025-09-30",
           "return_type": "26Q", "quarter": "Q2", "financial_year": FY, "prn": None}
    db = _OneStatementDatabase(row, update_matches=update_matches)
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    return db


def test_an_update_that_matched_no_row_is_a_refusal_and_writes_nothing(monkeypatch):
    db = _against_a_database(monkeypatch, update_matches=False)
    written = []
    monkeypatch.setattr(tw, "log_event", lambda *a, **k: written.append(("audit", a)))
    monkeypatch.setattr(tw.timeline_service, "log_timeline_event", lambda *a, **k: written.append(("timeline", k)))
    obligation = _obligation()
    out = update_return_status("r-1", UpdateReturnStatusRequest(
        status="filed", ca_approved=True, prn=PRN, filing_date=STATED), PARTNER)
    assert out["success"] is False and "Nothing was changed" in out["error"]
    assert "changed by someone else" in out["error"]
    assert db.updates, "the update was attempted"
    assert written == [], "no audit row and no timeline entry for a change that never happened"
    assert _now(obligation)["status"] == "Not Started", "and the calendar is not closed on a statement that was not filed"


def test_an_update_that_matched_a_row_files_it_and_closes_the_obligation(monkeypatch):
    db = _against_a_database(monkeypatch, update_matches=True)
    obligation = _obligation()
    out = update_return_status("r-1", UpdateReturnStatusRequest(
        status="filed", ca_approved=True, prn=PRN, filing_date=STATED), PARTNER)
    assert out["success"] is True
    assert out["data"]["compliance_obligation"]["state"] == "closed"
    assert _now(obligation)["status"] == "Filed"
    assert db.updates[0]["filed_at"] == f"{STATED}T00:00:00+00:00" and db.updates[0]["prn"] == PRN


def test_the_live_update_is_conditional_on_the_status_that_was_read_so_a_double_click_cannot_overwrite_the_prn(monkeypatch):
    db = _against_a_database(monkeypatch, update_matches=True)
    update_return_status("r-1", UpdateReturnStatusRequest(
        status="filed", ca_approved=True, prn=PRN, filing_date=STATED), PARTNER)
    assert dict(db.update_filters) == {"id": "r-1", "firm_id": FIRM, "status": "ca_approved"}
    assert dict(db.read_filters) == {"id": "r-1", "firm_id": FIRM}


def test_the_live_read_asks_for_every_column_the_checks_and_the_closer_use(monkeypatch):
    """Dropping `quarter`, `financial_year`, `return_type` or `prn` from the select would not fail a mock-mode test: the
    sentence would read "A statement for None FY None" and the closer would match nothing, in production only."""
    db = _against_a_database(monkeypatch, update_matches=True)
    update_return_status("r-1", UpdateReturnStatusRequest(
        status="filed", ca_approved=True, prn=PRN, filing_date=STATED), PARTNER)
    asked = {c.strip() for c in db.selected[0].split(",")}
    assert {"status", "client_id", "deductee_count", "quarter_end", "return_type", "quarter", "financial_year",
            "prn"} <= asked


# ── 4. the PRN closes the obligation ────────────────────────────────────────

def test_recording_the_prn_closes_the_obligation_with_the_stated_date_and_the_prn():
    obligation = _obligation()
    out = _file(_statement())
    assert out["success"] is True and out["data"]["status"] == "filed"
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "closed" and answer["closed"] is True and answer["obligation_id"] == obligation["id"]
    now = _now(obligation)
    assert now["status"] == "Filed" and now["filed_date"] == STATED and now["acknowledgement_no"] == PRN


@pytest.mark.parametrize("statement, kind", [("24Q", "TDS24Q"), ("26Q", "TDS26Q"), ("27Q", "TDS27Q")])
def test_each_statement_closes_its_own_obligation_and_not_its_neighbours(statement, kind):
    # Created BEFORE the target, so a match that ignored the type, the quarter, the client, the firm or the compliance type
    # would pick one of them first.
    others = [_obligation(k) for k in ("TDS24Q", "TDS26Q", "TDS27Q") if k != kind]
    other_quarter = _obligation(kind, quarter="Q1")
    next_quarter = _obligation(kind, quarter="Q3")
    other_year = _obligation(kind, fy="2024-25")
    other_client = _obligation(kind, client="client-2")
    other_firm = _obligation(kind, firm="firm-2")
    other_type = _obligation(kind, ctype="GST")
    deposit = _obligation("TDS_NON_SALARY_DEPOSIT", quarter="Q2")
    target = _obligation(kind)
    out = _file(_statement(statement))
    assert out["data"]["compliance_obligation"]["obligation_id"] == target["id"]
    assert _now(target)["status"] == "Filed"
    for untouched in others + [other_quarter, next_quarter, other_year, other_client, other_firm, other_type, deposit]:
        assert _now(untouched)["status"] == "Not Started", (untouched["obligation_type"], untouched["period_start"])


def test_the_window_must_be_the_quarters_own_first_and_last_day():
    short_end = compliance_records_repo.create({
        "firm_id": FIRM, "client_id": CLIENT, "compliance_type": "TDS", "obligation_type": "TDS26Q",
        "period_label": "x", "period_start": "2025-07-01", "period_end": "2025-08-31", "due_date": "2025-10-31",
        "status": "Not Started"})
    late_start = compliance_records_repo.create({
        "firm_id": FIRM, "client_id": CLIENT, "compliance_type": "TDS", "obligation_type": "TDS26Q",
        "period_label": "y", "period_start": "2025-08-01", "period_end": "2025-09-30", "due_date": "2025-10-31",
        "status": "Not Started"})
    out = _file(_statement())
    assert out["data"]["compliance_obligation"]["state"] == "not_on_the_calendar"
    assert _now(short_end)["status"] == "Not Started" and _now(late_start)["status"] == "Not Started"


def test_form_27eq_has_no_obligation_on_the_calendar_and_says_so():
    untouched = _obligation("TDS26Q")
    out = _file(_statement("27EQ"))
    assert out["success"] is True and out["data"]["status"] == "filed"
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_on_the_calendar" and "27EQ" in answer["message"]
    assert _now(untouched)["status"] == "Not Started"


def test_an_obligation_already_filed_keeps_its_own_date_and_number():
    obligation = _obligation(status="Filed", filed_date="2025-10-20", acknowledgement_no="THE-CAS-OWN-NUMBER")
    out = _file(_statement())
    assert out["data"]["compliance_obligation"]["state"] == "already_filed"
    now = _now(obligation)
    assert now["filed_date"] == "2025-10-20" and now["acknowledgement_no"] == "THE-CAS-OWN-NUMBER"


def test_no_obligation_on_the_calendar_files_the_statement_and_says_so():
    out = _file(_statement())
    assert out["success"] is True and out["data"]["status"] == "filed" and out["data"]["prn"] == PRN
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_on_the_calendar" and "TDS 26Q Q2 FY 2025-26 obligation" in answer["message"]


@pytest.mark.parametrize("statement, form", [("24Q", "138"), ("26Q", "140"), ("27Q", "144")])
def test_a_sentence_names_the_form_the_periods_own_act_gives_it_as_the_calendar_does(statement, form):
    """From FY 2026-27 the calendar's title reads the Act's form number; a sentence about that obligation must too."""
    row = _statement(statement, quarter="Q1", fy="2026-27")
    out = _file(row, day="2026-07-20")
    assert out["success"] is True
    assert f"TDS {form} Q1 FY 2026-27 obligation" in out["data"]["compliance_obligation"]["message"]


def test_the_sentence_about_form_27eq_names_the_form_the_periods_own_act_gives_it():
    out = _file(_statement("27EQ", quarter="Q1", fy="2026-27"), day="2026-07-20")
    assert "Form 143" in out["data"]["compliance_obligation"]["message"]


def test_a_caller_without_compliance_access_files_and_the_obligation_stays_open(monkeypatch):
    monkeypatch.setattr(tw, "can_user", lambda user, resource, action: not (resource == "compliance" and action == "write"))
    obligation = _obligation()
    out = _file(_statement())
    assert out["success"] is True and out["data"]["status"] == "filed"
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_allowed" and "Compliance" in answer["message"]
    assert _now(obligation)["status"] == "Not Started"


def test_the_permission_asked_is_compliance_write_per_person(monkeypatch):
    asked = []
    monkeypatch.setattr(tw, "can_user", lambda user, resource, action: asked.append((resource, action)) or True)
    _obligation()
    _file(_statement())
    assert ("compliance", "write") in asked


def test_a_statement_that_names_no_client_or_firm_matches_nothing():
    """`find_all` drops an empty filter, which would read every client's calendar."""
    _obligation()
    for firm, client in (("", CLIENT), (FIRM, "")):
        answer = closes.close_for_filed_return(
            firm_id=firm, client_id=client, return_type="26Q", quarter="Q2", financial_year=FY, filed_date=STATED,
            prn=PRN, actor=PARTNER, may_write_compliance=True)
        assert answer["state"] == "not_closed" and answer["closed"] is False


@pytest.mark.parametrize("quarter, fy", [("Q9", FY), ("", FY), ("Q2", "not-a-year"), (None, None)])
def test_a_period_that_is_not_a_quarter_is_left_to_the_calendar(quarter, fy):
    answer = closes.close_for_filed_return(
        firm_id=FIRM, client_id=CLIENT, return_type="26Q", quarter=quarter, financial_year=fy, filed_date=STATED, prn=PRN,
        actor=PARTNER, may_write_compliance=True)
    assert answer["state"] == "not_closed" and "Compliance" in answer["message"]


def test_the_calendar_row_is_read_for_this_firm_and_client_only():
    mine = _obligation()
    theirs = _obligation(firm="firm-2")
    _file(_statement())
    assert _now(mine)["status"] == "Filed" and _now(theirs)["status"] == "Not Started"


# ── a failure never fails the recording ─────────────────────────────────────

def test_an_unexpected_failure_closing_the_obligation_does_not_fail_the_recording(monkeypatch):
    reported = []
    import core.observability as obs
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **kw: reported.append((str(exc), kw)))
    monkeypatch.setattr(closes, "close_for_filed_return",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("calendar read failed")))
    obligation = _obligation()
    out = _file(_statement())
    assert out["success"] is True and out["data"]["status"] == "filed" and out["data"]["prn"] == PRN
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_closed" and "Mark the obligation filed from Compliance" in answer["message"]
    assert reported and reported[0][1]["operation"] == "tds_workspace.close_the_obligation"
    assert _now(obligation)["status"] == "Not Started"


def test_a_walk_that_stops_part_way_says_where_the_obligation_really_is(monkeypatch):
    reported = []
    monkeypatch.setattr(obligation_closure, "capture_soft_failure", lambda exc, **kw: reported.append(kw["operation"]))
    real = crs.compliance_record_service.update_record

    def fail_on_the_last_step(record_id, data, **kw):
        if data.get("status") == "Filed":
            raise RuntimeError("write failed")
        return real(record_id, data, **kw)
    monkeypatch.setattr(crs.compliance_record_service, "update_record", fail_on_the_last_step)
    obligation = _obligation()
    out = _file(_statement())
    assert out["success"] is True and out["data"]["status"] == "filed"
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_closed" and "Ready To File" in answer["message"] and "Compliance" in answer["message"]
    assert _now(obligation)["status"] == "Ready To File"
    assert reported == ["tds_return_closes_obligation.mark_filed"]


# ── the map is the generator's, not a copy of it ────────────────────────────

def test_the_obligation_codes_are_the_ones_the_calendar_generates():
    from services.compliance_obligation_service import _tds_obligations
    generated = {spec["obligation_type"] for spec in _tds_obligations(FY, has_non_resident_vendors=True)}
    assert set(closes.OBLIGATION_FOR_STATEMENT.values()) <= generated, (
        "a code renamed in the generator would leave the closer closing nothing")
    assert {spec["compliance_type"] for spec in _tds_obligations(FY, has_non_resident_vendors=True)} == {closes.COMPLIANCE_TYPE}


@pytest.mark.parametrize("quarter", ["Q1", "Q2", "Q3", "Q4"])
def test_the_quarters_are_the_generators_own_windows(quarter):
    from services.compliance_obligation_service import _tds_obligations
    start, end, _due = quarter_dates(FY, quarter)
    mine = [s for s in _tds_obligations(FY) if s["obligation_type"] == "TDS26Q"
            and str(s["period_start"])[:10] == start]
    assert len(mine) == 1 and str(mine[0]["period_end"])[:10] == end


def test_the_routing_keys_are_the_four_the_table_accepts():
    """`27EQ` is the one routing key with no obligation; the other three are the map."""
    import typing
    keys = set(typing.get_args(tw.ReturnTypeKey))
    assert keys == {"24Q", "26Q", "27Q", "27EQ"}
    assert set(closes.OBLIGATION_FOR_STATEMENT) == keys - {"27EQ"}
