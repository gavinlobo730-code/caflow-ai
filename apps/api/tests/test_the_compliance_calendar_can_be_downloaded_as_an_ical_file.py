"""POST-A-142 (the export half): the compliance calendar can be downloaded as an iCalendar file.

WHAT WAS MISSING
    A CA who wanted the client deadlines in Outlook, Google Calendar or a phone had to retype them: there was no VCALENDAR anywhere
    in the product. The file is a different consumer of the SAME rows the calendar screen shows, so the risk is not the format (a
    small, well-known one) but a file that disagrees with the screen: an obligation in it the caller may not see, an overdue one
    missing, a filed one shown as pending, or an obligation silently left out because it has no due date.

WHAT IS HELD
    Format (`domain/practice/ical.py`, pure):
    * every line ends in CRLF and no content line is longer than 75 OCTETS; a fold never splits a UTF-8 sequence (a Devanagari
      name is three bytes a character) and unfolding gives the original back;
    * TEXT is escaped: a client called "Rao, Rao & Sons; Traders" is one value, a line break is the two characters backslash-n;
    * an obligation is an ALL-DAY event: a DATE and not an instant, and its end is the NEXT day (exclusive), including across a
      month and a year boundary; no time zone is written;
    * the UID is the obligation's id and nothing else, so the same download twice is the same events (only DTSTAMP moves);
    * every event says it is not a filing, and the workflow word is printed as it is stored and never as CANCELLED;
    * a row with no usable due date is not placed and the calendar's own description says how many were left out.
    The route (`GET /api/compliance/obligations/calendar.ics`):
    * it serves `text/calendar` as an attachment, with the same window rules as the screen's read (half a window, a backwards
      one and a too-wide one are refused);
    * OVERDUE obligations are always in it, a filed one only when asked for, and with no window the file covers today and a year;
    * the assignment scope is the screen's: an obligation of a client the caller is not assigned to is not in the file;
    * client names are looked up and put in the title, and an id with no name is a title without one, not an error.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.compliance_ops as ops
from core.auth import get_current_user
from domain.practice import ical
from mock_data import MOCK_COMPLIANCE_RECORDS
from services import compliance_obligation_service as ob

NOW = datetime(2026, 10, 10, 9, 30, tzinfo=timezone.utc)
FIRM = "firm-ics-1"
MINE, THEIRS = "client-mine", "client-theirs"
PARTNER = {"id": "u-ptr", "firm_id": FIRM, "role": "Partner", "email": "p@f.in"}
TODAY = date(2026, 10, 10)


def _unfold(text: str) -> str:
    return text.replace("\r\n ", "")


def _lines(text: str) -> list[str]:
    return _unfold(text).split("\r\n")


# ── the format ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_text_is_escaped_so_a_clients_name_is_one_value():
    assert ical.escape_text("Rao, Rao & Sons; Traders") == "Rao\\, Rao & Sons\\; Traders"
    assert ical.escape_text("a\\b") == "a\\\\b"
    assert ical.escape_text("one\ntwo\r\nthree") == "one\\ntwo\\nthree"


def test_a_long_line_is_folded_at_75_octets_and_unfolds_to_the_original():
    line = "DESCRIPTION:" + "x" * 300
    folded = ical.fold(line)
    parts = folded.split("\r\n")
    assert all(len(p.encode("utf-8")) <= 75 for p in parts) and len(parts) > 1
    assert all(p.startswith(" ") for p in parts[1:])
    assert folded.replace("\r\n ", "") == line


def test_a_fold_never_splits_a_multibyte_character():
    name = "आनंद टेक्सटाइल्स " * 12
    line = "SUMMARY:" + name
    folded = ical.fold(line)
    for part in folded.split("\r\n"):
        assert len(part.encode("utf-8")) <= 75
        part.encode("utf-8").decode("utf-8")                    # a split sequence would not decode
    assert folded.replace("\r\n ", "") == line


def test_a_short_line_is_not_folded():
    assert ical.fold("SUMMARY:GSTR-3B") == "SUMMARY:GSTR-3B"


def _file(*obligations, description=None):
    return ical.build_calendar(obligations, now=NOW, description=description)


def test_the_file_is_crlf_throughout_and_has_the_calendar_envelope():
    text = _file(ical.Obligation(id="r1", day=date(2026, 10, 20), title="GSTR-3B"))
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    lines = text.split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR" and lines[1] == "VERSION:2.0" and lines[-2] == "END:VCALENDAR"
    assert "PRODID:-//PracticeSync//Compliance calendar//EN" in lines and "METHOD:PUBLISH" in lines


def test_an_obligation_is_an_all_day_event_that_ends_the_next_day():
    text = _file(ical.Obligation(id="r1", day=date(2026, 10, 20), title="GSTR-3B"))
    assert "DTSTART;VALUE=DATE:20261020" in text and "DTEND;VALUE=DATE:20261021" in text
    assert "TZID" not in text and "T000000" not in text, "an all-day obligation carries no time and no zone"


def test_the_day_after_a_month_end_and_a_year_end_is_right():
    text = _file(ical.Obligation(id="a", day=date(2026, 10, 31), title="A"), ical.Obligation(id="b", day=date(2026, 12, 31), title="B"),
                 ical.Obligation(id="c", day=date(2028, 2, 28), title="C"))
    assert "DTEND;VALUE=DATE:20261101" in text and "DTEND;VALUE=DATE:20270101" in text and "DTEND;VALUE=DATE:20280229" in text


def test_the_uid_is_the_obligation_and_only_dtstamp_moves_between_downloads():
    o = ical.Obligation(id="rec-42", day=date(2026, 10, 20), title="GSTR-3B")
    first = ical.build_calendar([o], now=NOW)
    later = ical.build_calendar([o], now=NOW + timedelta(days=3))
    assert "UID:rec-42@obligation.practicesync" in first
    assert first.replace("20261010T093000Z", "") == later.replace("20261013T093000Z", "")


def test_the_dtstamp_is_utc_whatever_zone_the_instant_carries():
    ist = datetime(2026, 10, 10, 15, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert "DTSTAMP:20261010T093000Z" in ical.build_calendar([ical.Obligation(id="r", day=date(2026, 10, 20), title="T")], now=ist)


def test_every_event_says_it_is_not_a_filing_and_a_filed_obligation_is_not_cancelled():
    text = _file(ical.Obligation(id="r1", day=date(2026, 10, 20), title="GSTR-3B", status="Filed", client_name="Acme"))
    body = _unfold(text)
    assert "This is not a filing and nothing has been submitted." in body
    assert "Status: Filed" in body and "STATUS:CONFIRMED" in body and "CANCELLED" not in body


def test_the_title_carries_the_client_and_a_comma_in_it_does_not_split_the_property():
    text = _file(ical.Obligation(id="r1", day=date(2026, 10, 20), title="GSTR-3B", client_name="Rao, Rao & Sons; Traders"))
    summary = [l for l in _lines(text) if l.startswith("SUMMARY:")]
    assert summary == ["SUMMARY:GSTR-3B – Rao\\, Rao & Sons\\; Traders"]


def test_a_row_with_no_due_date_is_left_out_and_the_calendar_says_how_many():
    rows = [{"id": "r1", "due_date": "2026-10-20", "period_label": "GSTR-3B", "client_id": "c1"},
            {"id": "r2", "due_date": "", "period_label": "TDS"}, {"id": "r3", "due_date": None}]
    text = ical.from_rows(rows, {"c1": "Acme"}, now=NOW)
    assert text.count("BEGIN:VEVENT") == 1
    assert "X-WR-CALDESC:2 obligations with no due date are not in this file." in _unfold(text)
    one = ical.from_rows(rows[:2], {}, now=NOW)
    assert "X-WR-CALDESC:1 obligation with no due date is not in this file." in _unfold(one)
    assert "X-WR-CALDESC" not in ical.from_rows(rows[:1], {}, now=NOW)


def test_events_are_in_date_order():
    rows = [{"id": "b", "due_date": "2026-11-20", "period_label": "B"}, {"id": "a", "due_date": "2026-10-20", "period_label": "A"}]
    uids = [l for l in _lines(ical.from_rows(rows, {}, now=NOW)) if l.startswith("UID:")]
    assert uids == ["UID:a@obligation.practicesync", "UID:b@obligation.practicesync"]


# ── the route ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def records(monkeypatch):
    saved = list(MOCK_COMPLIANCE_RECORDS)
    MOCK_COMPLIANCE_RECORDS.clear()
    monkeypatch.setattr(ob, "ist_today", lambda: TODAY)
    monkeypatch.setattr(ops, "ist_today", lambda: TODAY)
    monkeypatch.setattr(ob, "_dashboard_names", lambda firm, clients, users: ({MINE: "Mine Traders", THEIRS: "Theirs Ltd"}, {}))
    yield MOCK_COMPLIANCE_RECORDS
    MOCK_COMPLIANCE_RECORDS.clear()
    MOCK_COMPLIANCE_RECORDS.extend(saved)


def _row(rid, due, status="Not Started", client=MINE, otype="GSTR3B"):
    row = {"id": rid, "firm_id": FIRM, "client_id": client, "obligation_type": otype, "compliance_type": "GST",
           "period_label": f"{otype} {rid}", "period_start": due, "period_end": due, "due_date": due, "status": status,
           "created_at": "2026-04-01T00:00:00+00:00", "updated_at": "2026-04-01T00:00:00+00:00"}
    MOCK_COMPLIANCE_RECORDS.append(row)
    return row


def _get(user=PARTNER, **params):
    app = FastAPI()
    app.include_router(ops.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app).get("/api/compliance/obligations/calendar.ics", params=params)


def _uids(res):
    return sorted(l[4:].split("@")[0] for l in _lines(res.text) if l.startswith("UID:"))


def test_the_route_serves_a_calendar_file_as_an_attachment():
    _row("up", "2026-11-12")
    res = _get()
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/calendar")
    assert 'attachment; filename="compliance-calendar.ics"' in res.headers["content-disposition"]
    assert res.text.startswith("BEGIN:VCALENDAR\r\n") and res.text.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:GSTR3B up – Mine Traders" in _unfold(res.text)


def test_overdue_is_always_in_and_filed_only_when_asked_for():
    _row("late", "2026-09-20")
    _row("soon", "2026-11-12")
    _row("done", "2026-11-02", status="Filed")
    assert _uids(_get()) == ["late", "soon"]
    assert _uids(_get(include_completed="true")) == ["done", "late", "soon"]


def test_with_no_window_the_file_covers_a_year_ahead_and_not_beyond():
    _row("in-year", (TODAY + timedelta(days=364)).isoformat())
    _row("beyond", (TODAY + timedelta(days=400)).isoformat())
    assert _uids(_get()) == ["in-year"]


def test_a_window_is_read_like_the_screens_and_a_bad_one_is_refused():
    _row("nov", "2026-11-12")
    _row("dec", "2026-12-12")
    assert _uids(_get(date_from="2026-11-01", date_to="2026-11-30")) == ["nov"]
    assert _get(date_from="2026-11-01").status_code == 422
    assert _get(date_from="2026-11-30", date_to="2026-11-01").status_code == 422
    assert _get(date_from="2025-01-01", date_to="2026-11-01").status_code == 422


def test_the_assignment_scope_is_the_screens(monkeypatch):
    _row("mine-up", "2026-11-12")
    _row("theirs-up", "2026-11-12", client=THEIRS)
    _row("mine-late", "2026-09-12")
    _row("theirs-late", "2026-09-12", client=THEIRS)
    monkeypatch.setattr(ops, "filter_by_client", lambda user, rows, key="client_id": [r for r in rows if r.get(key) == MINE])
    res = _get()
    assert _uids(res) == ["mine-late", "mine-up"] and "Theirs" not in res.text


def test_the_client_filter_narrows_the_file():
    _row("mine", "2026-11-12")
    _row("theirs", "2026-11-12", client=THEIRS)
    assert _uids(_get(client_id=THEIRS)) == ["theirs"]


def test_a_client_whose_name_cannot_be_read_still_has_its_obligation(monkeypatch):
    monkeypatch.setattr(ob, "_dashboard_names", lambda firm, clients, users: ({}, {}))
    _row("up", "2026-11-12")
    res = _get()
    assert _uids(res) == ["up"] and "SUMMARY:GSTR3B up\r\n" in res.text
