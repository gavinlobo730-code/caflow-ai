"""A GSTR-1 or GSTR-3B recorded as filed in the GST workspace closes the compliance obligation it stands for (POST-A-254).

WHAT WAS WRONG
    The workspace's status door wrote the return row and the `filings` row (the period lock) and never touched
    `compliance_records`, which is what Deadlines, the client's Compliance tab and the firm dashboard read. A CA who filed
    eleven months in the workspace saw eleven Filed returns beside a calendar that called the same eleven overdue (on a
    seeded year: all 25 GST obligations of one client Not Started, 384 of 403 firm-wide overdue). The other door
    (`ComplianceRecordService.mark_filed`) already warned when the workspace return was not submitted; nothing went the
    other way.

WHAT IS HELD
    * submitting a return closes the client's obligation of that type whose period starts on the return's first day, with
      the CA's stated filed date and the ARN, through `mark_filed` (so the lifecycle, audit and the single `filings` row stay
      one path): one `filings` row, not two;
    * a QRMP quarter's return and obligation are both keyed by the quarter's first month and close together;
    * nothing else moves: another period, the other return's obligation, another client's, and an obligation already Filed
      (its own ARN and date are left alone);
    * the obligation is the one with the return's OWN window (type, first day AND last day): a quarter's return never
      closes a monthly row left behind by a change of frequency, and never writes a second, narrower `filings` row;
    * a client with two registrations keeps the obligation open until EVERY registration live in the window that files on
      the same cycle has this return recorded as filed, and says which is outstanding; a cancelled registration, or one
      that starts later, is not waited for; registrations on different cycles decline, with a sentence;
    * a caller without compliance access files the return and the obligation stays open with a sentence saying why;
    * no obligation on the calendar, or a failure closing it, never fails the filing and is reported in the answer, and a
      walk that stops part way says where the obligation really is;
    * approving (or any status but submitted) touches no obligation, and reopening a return does not reopen its obligation.
"""
from __future__ import annotations

import pytest

import routers.gst_workspace as gw
from domain import compliance_record_service as crs
from domain.gst import gstin as gstin_rules
from mock_data import MOCK_COMPLIANCE_RECORDS
from repositories.compliance_records_repository import compliance_records_repo
from services import gst_return_closes_obligation as closes
from services import obligation_closure
from tests.e2e_harness import FakeDB, wire_e2e

FIRM, CLIENT = "firm-1", "client-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}
GSTIN = "27AAPFU0939F1ZV"                                          # checksum-valid (tests/fixtures/gstin.json)
SECOND = "29AAPFU0939F1Z" + gstin_rules.checksum_char("29AAPFU0939F1Z")
JUNE = "062026"
STATED, ARN = "2026-07-11", "AA270626123456A"


@pytest.fixture
def world(monkeypatch):
    import services.audit_service as au
    import services.timeline_service as ts
    MOCK_COMPLIANCE_RECORDS.clear()
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    monkeypatch.setattr(gw, "_USE_MOCK", False)
    wire_e2e(monkeypatch, d, [gw])
    monkeypatch.setattr(crs, "_filing_db", lambda: d)
    monkeypatch.setattr(au, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(ts.timeline_service, "log", lambda *a, **k: None)
    d.seed("clients", {
        "id": CLIENT, "firm_id": FIRM, "client_name": "Acme Industries", "legal_name": "Acme Industries Private Limited",
        "gstin": GSTIN, "state_code": "27", "gst_filing_frequency": "monthly", "gst_registration_date": None,
        "gst_registration_type": None, "composition_category": None})
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    yield d
    MOCK_COMPLIANCE_RECORDS.clear()


def _obligation(otype="GSTR3B", start="2026-06-01", end="2026-06-30", status="Not Started", client=CLIENT, **extra):
    return compliance_records_repo.create({
        "firm_id": FIRM, "client_id": client, "compliance_type": "GST", "obligation_type": otype,
        "period_label": f"{otype} {start}", "period_start": start, "period_end": end, "due_date": "2026-07-20",
        "status": status, **extra})


def _now(rec):
    return compliance_records_repo.find_by_id(rec["id"])


def _save(kind, period=JUNE, gstin=GSTIN):
    if kind == "gstr1":
        return gw.save_gstr1(gw.SaveGSTR1Request(
            client_id=CLIENT, period=period, gstin=gstin, payload_json={"b2b": []}, summary_json={},
            total_taxable_paise=10_000_00), current_user=USER)["data"]
    return gw.save_gstr3b(gw.SaveGSTR3BRequest(
        client_id=CLIENT, period=period, gstin=gstin, payload_json={}, summary_json={}, tax_liability_paise=10_000_00,
        itc_claimed_paise=2_000_00, net_tax_paise=8_000_00), current_user=USER)["data"]


FNS = {"gstr1": gw.update_gstr1_status, "gstr3b": gw.update_gstr3b_status}
OTYPE = {"gstr1": "GSTR1", "gstr3b": "GSTR3B"}


def _submit(kind, return_id, filed_date=STATED, arn=ARN, status="submitted"):
    return FNS[kind](return_id, gw.UpdateStatusRequest(
        status=status, ca_approved=True, acknowledge_stale=True, arn=arn,
        **({"filed_date": filed_date} if status == "submitted" else {})), current_user=USER)


# ── the finding ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["gstr1", "gstr3b"])
def test_submitting_a_return_closes_the_obligation_with_the_stated_date_and_arn(world, kind):
    obligation = _obligation(OTYPE[kind])
    out = _submit(kind, _save(kind)["id"])

    assert out["success"] is True
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "closed" and answer["closed"] is True and answer["obligation_id"] == obligation["id"]
    now = _now(obligation)
    assert now["status"] == "Filed"
    assert now["filed_date"] == STATED and now["acknowledgement_no"] == ARN


@pytest.mark.parametrize("kind", ["gstr1", "gstr3b"])
def test_the_period_is_locked_by_one_filing_row_and_not_two(world, kind):
    """The workspace wrote the row first; `mark_filed` refreshes it (it is idempotent on its window)."""
    _obligation(OTYPE[kind])
    _submit(kind, _save(kind)["id"])
    rows = world.rows("filings")
    assert len(rows) == 1, rows
    assert rows[0]["filed_date"] == STATED and rows[0]["acknowledgement_number"] == ARN


def test_the_tax_the_workspace_recorded_on_the_filing_row_survives_the_obligation_refresh(world):
    _obligation("GSTR3B")
    _submit("gstr3b", _save("gstr3b")["id"])
    (row,) = world.rows("filings")
    assert row.get("tax_payable_paise") not in (None, 0), "mark_filed overwrote what the workspace recorded"


def test_nothing_else_on_the_calendar_moves(world):
    # The neighbours are created BEFORE the target, so a match that ignored the period, the type or the client would
    # pick one of them first.
    earlier = _obligation("GSTR3B", start="2026-05-01", end="2026-05-31")
    other_return = _obligation("GSTR1")
    other_client = _obligation("GSTR3B", client="client-2")
    target = _obligation("GSTR3B")
    later = _obligation("GSTR3B", start="2026-07-01", end="2026-07-31")
    _submit("gstr3b", _save("gstr3b")["id"])
    assert _now(target)["status"] == "Filed"
    for untouched in (earlier, later, other_return, other_client):
        assert _now(untouched)["status"] == "Not Started", (untouched["obligation_type"], untouched["period_start"])


def test_a_qrmp_quarter_closes_the_quarters_obligation(world):
    world.rows("clients")[0]["gst_filing_frequency"] = "quarterly"
    quarter = _obligation("GSTR1", start="2026-04-01", end="2026-06-30")
    next_quarter = _obligation("GSTR1", start="2026-07-01", end="2026-09-30")
    out = _submit("gstr1", _save("gstr1", period="042026")["id"], filed_date="2026-07-13")
    assert out["data"]["compliance_obligation"]["state"] == "closed"
    assert _now(quarter)["status"] == "Filed" and _now(next_quarter)["status"] == "Not Started"
    (row,) = world.rows("filings")
    assert (row["period_start"], row["period_end"]) == ("2026-04-01", "2026-06-30"), "the quarter, not its first month"


# ── what it leaves alone ────────────────────────────────────────────────────

def test_an_obligation_already_filed_is_left_as_it_is(world):
    obligation = _obligation("GSTR3B", status="Filed", filed_date="2026-07-09", acknowledgement_no="THE-CAS-OWN-ARN")
    out = _submit("gstr3b", _save("gstr3b")["id"])
    assert out["success"] is True
    assert out["data"]["compliance_obligation"]["state"] == "already_filed"
    now = _now(obligation)
    assert now["filed_date"] == "2026-07-09" and now["acknowledgement_no"] == "THE-CAS-OWN-ARN"


def test_no_obligation_on_the_calendar_files_the_return_and_says_so(world):
    out = _submit("gstr3b", _save("gstr3b")["id"])
    assert out["success"] is True
    assert out["data"]["compliance_obligation"]["state"] == "not_on_the_calendar"
    assert len(world.rows("filings")) == 1


def test_a_caller_without_compliance_access_files_the_return_and_the_obligation_stays_open(world, monkeypatch):
    real = gw.can_user
    monkeypatch.setattr(gw, "can_user", lambda u, r, a: False if (r, a) == ("compliance", "write") else real(u, r, a))
    obligation = _obligation("GSTR3B")
    out = _submit("gstr3b", _save("gstr3b")["id"])
    assert out["success"] is True
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_allowed" and "Compliance" in answer["message"]
    assert _now(obligation)["status"] == "Not Started"


@pytest.mark.parametrize("status", ["validated", "ca_approved"])
def test_a_status_that_files_nothing_touches_no_obligation(world, status):
    obligation = _obligation("GSTR3B")
    out = _submit("gstr3b", _save("gstr3b")["id"], status=status)
    assert out["success"] is True and "compliance_obligation" not in out["data"]
    assert _now(obligation)["status"] == "Not Started"


def test_reopening_a_return_does_not_reopen_its_obligation(world):
    """Decided, not forgotten: the period lock a filing leaves is not undone by reopening either, and un-filing a
    compliance obligation is the CA's act."""
    obligation = _obligation("GSTR3B")
    saved = _save("gstr3b")
    _submit("gstr3b", saved["id"])
    reopened = _submit("gstr3b", saved["id"], status="draft")
    assert reopened["success"] is True
    assert _now(obligation)["status"] == "Filed"


def test_mock_mode_has_no_calendar_to_close(world, monkeypatch):
    monkeypatch.setattr(gw, "_USE_MOCK", True)
    answer = gw._close_the_obligation(USER, "GSTR3B", {"client_id": CLIENT, "period": JUNE}, STATED, ARN)
    assert answer["closed"] is False and "no compliance calendar" in answer["message"]


# ── a client with two registrations ─────────────────────────────────────────

@pytest.fixture
def two_registrations(world):
    world.seed("client_gst_registrations", {
        "firm_id": FIRM, "client_id": CLIENT, "gstin": SECOND, "state_code": "29", "registration_type": "regular",
        "filing_frequency": "monthly", "deleted_at": None})
    return world


@pytest.mark.parametrize("kind", ["gstr1", "gstr3b"])
def test_the_obligation_waits_for_every_registration_and_closes_on_the_last(two_registrations, kind):
    obligation = _obligation(OTYPE[kind])
    first = _submit(kind, _save(kind, gstin=GSTIN)["id"])
    waiting = first["data"]["compliance_obligation"]
    assert waiting["state"] == "waiting_for_other_registrations" and SECOND in waiting["message"]
    assert _now(obligation)["status"] == "Not Started"

    last = _submit(kind, _save(kind, gstin=SECOND)["id"], filed_date="2026-07-12")
    assert last["data"]["compliance_obligation"]["state"] == "closed"
    assert _now(obligation)["status"] == "Filed"


def test_a_registration_that_does_not_file_gstr1_and_3b_is_not_waited_for(world):
    """A composition registration files CMP-08 and GSTR-4, not these two."""
    world.seed("client_gst_registrations", {
        "firm_id": FIRM, "client_id": CLIENT, "gstin": SECOND, "state_code": "29", "registration_type": "composition",
        "filing_frequency": "quarterly", "deleted_at": None})
    obligation = _obligation("GSTR3B")
    out = _submit("gstr3b", _save("gstr3b")["id"])
    assert out["data"]["compliance_obligation"]["state"] == "closed"
    assert _now(obligation)["status"] == "Filed"


# ── a failure is reported and never fails the filing ────────────────────────

def test_an_unexpected_failure_closing_the_obligation_does_not_fail_the_filing(world, monkeypatch):
    reported = []
    import core.observability as obs
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **kw: reported.append((str(exc), kw)))
    monkeypatch.setattr(closes, "close_for_filed_return",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("calendar read failed")))
    obligation = _obligation("GSTR3B")
    out = _submit("gstr3b", _save("gstr3b")["id"])
    assert out["success"] is True
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_closed" and "Mark the obligation filed from Compliance" in answer["message"]
    assert reported and reported[0][1]["operation"] == "gst_workspace.close_the_obligation"
    assert _now(obligation)["status"] == "Not Started"
    assert len(world.rows("filings")) == 1, "the period must still be locked"


def test_a_refusal_from_the_compliance_door_is_an_answer_and_not_an_error(world, monkeypatch):
    from core.exceptions import ValidationError

    def refuse(*a, **k):
        raise ValidationError("filed_date", "A return cannot have been filed before the period it declares ended.")
    monkeypatch.setattr(crs.compliance_record_service, "mark_filed", refuse)
    obligation = _obligation("GSTR3B")
    out = _submit("gstr3b", _save("gstr3b")["id"])
    assert out["success"] is True
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_closed" and "before the period it declares ended" in answer["message"]
    assert not answer["message"].startswith("Validation error"), "the wrapper is not for the CA"
    assert _now(obligation)["status"] == "Not Started"


# ── the window the return covers is the window the obligation must have ─────

def test_the_message_names_the_period_so_a_run_of_back_recorded_months_can_be_told_apart(world):
    _obligation("GSTR3B")
    answer = _submit("gstr3b", _save("gstr3b")["id"])["data"]["compliance_obligation"]
    assert "June 2026" in answer["message"] and "GSTR-3B" in answer["message"]


def test_a_quarterly_return_does_not_close_a_monthly_row_left_behind_by_a_change_of_frequency(world):
    """The row starts on the same day as the quarter and ends a month later. It used to be matched on its first day alone,
    closed as Filed, and given a second, narrower `filings` row beside the quarter's."""
    world.rows("clients")[0]["gst_filing_frequency"] = "quarterly"
    stale_month = _obligation("GSTR1", start="2026-04-01", end="2026-04-30")
    quarter = _obligation("GSTR1", start="2026-04-01", end="2026-06-30")
    out = _submit("gstr1", _save("gstr1", period="042026")["id"], filed_date="2026-07-13")
    assert out["data"]["compliance_obligation"]["state"] == "closed"
    assert _now(quarter)["status"] == "Filed" and _now(stale_month)["status"] == "Not Started"
    assert [(r["period_start"], r["period_end"]) for r in world.rows("filings")] == [("2026-04-01", "2026-06-30")]


def test_with_only_the_stale_monthly_row_on_the_calendar_nothing_is_closed_and_the_lock_stays_the_quarters(world):
    world.rows("clients")[0]["gst_filing_frequency"] = "quarterly"
    stale_month = _obligation("GSTR1", start="2026-04-01", end="2026-04-30")
    out = _submit("gstr1", _save("gstr1", period="042026")["id"], filed_date="2026-07-13")
    assert out["data"]["compliance_obligation"]["state"] == "not_on_the_calendar"
    assert _now(stale_month)["status"] == "Not Started"
    assert [(r["period_start"], r["period_end"]) for r in world.rows("filings")] == [("2026-04-01", "2026-06-30")]


# ── which registrations are waited for ──────────────────────────────────────

@pytest.mark.parametrize("effective_from,effective_to", [
    (None, "2026-03-31"),            # cancelled before the period began
    ("2026-09-01", None),            # starts after the period ended
], ids=["cancelled-before", "starts-later"])
def test_a_registration_that_was_not_live_in_the_period_is_not_waited_for(world, effective_from, effective_to):
    world.seed("client_gst_registrations", {
        "firm_id": FIRM, "client_id": CLIENT, "gstin": SECOND, "state_code": "29", "registration_type": "regular",
        "filing_frequency": "monthly", "effective_from": effective_from, "effective_to": effective_to, "deleted_at": None})
    obligation = _obligation("GSTR3B")
    out = _submit("gstr3b", _save("gstr3b")["id"])
    assert out["data"]["compliance_obligation"]["state"] == "closed"
    assert _now(obligation)["status"] == "Filed"


def test_a_registration_live_for_only_part_of_the_period_is_still_waited_for(world):
    world.seed("client_gst_registrations", {
        "firm_id": FIRM, "client_id": CLIENT, "gstin": SECOND, "state_code": "29", "registration_type": "regular",
        "filing_frequency": "monthly", "effective_from": "2026-06-15", "effective_to": None, "deleted_at": None})
    obligation = _obligation("GSTR3B")
    out = _submit("gstr3b", _save("gstr3b")["id"])
    assert out["data"]["compliance_obligation"]["state"] == "waiting_for_other_registrations"
    assert _now(obligation)["status"] == "Not Started"


def test_the_waiting_message_says_how_to_finish_by_hand(two_registrations):
    _obligation("GSTR3B")
    message = _submit("gstr3b", _save("gstr3b")["id"])["data"]["compliance_obligation"]["message"]
    assert "Compliance" in message and SECOND in message


@pytest.mark.parametrize("client_frequency,second_frequency", [("quarterly", "monthly"), ("monthly", "quarterly")],
                         ids=["quarterly-client-monthly-second", "monthly-client-quarterly-second"])
def test_registrations_on_different_cycles_decline_instead_of_guessing(world, client_frequency, second_frequency):
    """One obligation cannot stand for a monthly registration's three returns AND a quarterly one's single return: closing
    it on the first quarterly filing locked May and June for the monthly registration while its returns were unfiled."""
    world.rows("clients")[0]["gst_filing_frequency"] = client_frequency
    world.seed("client_gst_registrations", {
        "firm_id": FIRM, "client_id": CLIENT, "gstin": SECOND, "state_code": "29", "registration_type": "regular",
        "filing_frequency": second_frequency, "deleted_at": None})
    quarterly = client_frequency == "quarterly"
    obligation = (_obligation("GSTR1", start="2026-04-01", end="2026-06-30") if quarterly
                  else _obligation("GSTR1", start="2026-04-01", end="2026-04-30"))
    out = _submit("gstr1", _save("gstr1", period="042026")["id"], filed_date="2026-07-13")
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "registrations_on_different_cycles" and "Compliance" in answer["message"]
    assert _now(obligation)["status"] == "Not Started"


# ── a walk that stops part way, a race, and what the answer says ────────────

def test_a_failure_part_way_says_where_the_obligation_really_is(world, monkeypatch):
    import core.observability as obs
    reported = []
    monkeypatch.setattr(obs, "capture_soft_failure", lambda exc, **kw: reported.append(kw["operation"]))
    monkeypatch.setattr(obligation_closure, "capture_soft_failure", lambda exc, **kw: reported.append(kw["operation"]))
    monkeypatch.setattr(crs, "_close_the_period",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("filings write failed")))
    obligation = _obligation("GSTR3B")
    out = _submit("gstr3b", _save("gstr3b")["id"])
    assert out["success"] is True
    answer = out["data"]["compliance_obligation"]
    assert answer["state"] == "not_closed" and answer["closed"] is False
    assert "Ready To File" in answer["message"], "the answer must name the status the walk stopped at"
    assert "Compliance" in answer["message"]
    assert _now(obligation)["status"] == "Ready To File"
    assert "gst_return_closes_obligation.mark_filed" in reported
    # ...and the walk resumes from there: marking it filed again finishes the job.
    monkeypatch.undo()
    crs.compliance_record_service.mark_filed(obligation["id"], firm_id=FIRM, actor=USER, filed_date=STATED)
    assert _now(obligation)["status"] == "Filed"


def test_an_obligation_filed_by_someone_else_a_moment_ago_is_reported_as_filed(world, monkeypatch):
    _obligation("GSTR3B")

    def lose_the_race(record_id, **kw):
        compliance_records_repo.update(record_id, {"status": "Filed", "filed_date": "2026-07-09"})
        from core.exceptions import ValidationError
        raise ValidationError("status", "Cannot transition from 'Filed' to 'In Progress'.")
    monkeypatch.setattr(crs.compliance_record_service, "mark_filed", lose_the_race)
    answer = _submit("gstr3b", _save("gstr3b")["id"])["data"]["compliance_obligation"]
    assert answer["state"] == "already_filed" and "just now" in answer["message"]


def test_an_obligation_that_cannot_be_updated_is_not_said_to_have_been_removed(world, monkeypatch):
    from core.exceptions import NotFoundError
    monkeypatch.setattr(crs.compliance_record_service, "mark_filed",
                        lambda *a, **k: (_ for _ in ()).throw(NotFoundError("ComplianceRecord", "x")))
    _obligation("GSTR3B")
    answer = _submit("gstr3b", _save("gstr3b")["id"])["data"]["compliance_obligation"]
    assert answer["state"] == "not_on_the_calendar"
    assert "removed" not in answer["message"] and "could not be found to update" in answer["message"]


@pytest.mark.parametrize("firm,client", [("", CLIENT), (FIRM, "")])
def test_a_return_that_names_no_client_or_firm_matches_nothing(world, firm, client):
    """`find_all` drops an empty filter, which would read every client's calendar."""
    _obligation("GSTR3B")
    answer = closes.close_for_filed_return(
        world, firm_id=firm, client_id=client, obligation_type="GSTR3B", period=JUNE, frequency="monthly",
        filed_date=STATED, arn=ARN, actor=USER, may_write_compliance=True)
    assert answer["state"] == "not_closed" and answer["closed"] is False


def test_the_status_re_read_after_a_failure_is_scoped_to_the_firm_and_the_client(world):
    """The id came from a scoped listing, and the re-read goes through the same one: another firm's or another client's
    calendar can never be what a status is read from (the firm-scope guard also holds the by-id spelling out)."""
    rec = _obligation("GSTR3B", status="In Progress")
    assert obligation_closure.status_now(FIRM, CLIENT, "GST", rec["id"]) == "In Progress"
    assert obligation_closure.status_now("firm-2", CLIENT, "GST", rec["id"]) is None
    assert obligation_closure.status_now(FIRM, "client-2", "GST", rec["id"]) is None


def test_a_status_that_cannot_be_read_is_none_and_does_not_raise(world, monkeypatch):
    rec = _obligation("GSTR3B")
    monkeypatch.setattr(compliance_records_repo, "find_all",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("PostgREST is unreachable")))
    assert obligation_closure.status_now(FIRM, CLIENT, "GST", rec["id"]) is None
