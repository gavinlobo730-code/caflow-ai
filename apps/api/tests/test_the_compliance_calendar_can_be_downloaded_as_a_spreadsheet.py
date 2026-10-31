"""POST-A-142 (the spreadsheet half): the compliance calendar can be downloaded as a CSV file.

WHAT WAS MISSING
    The calendar could be downloaded as an iCalendar file for a calendar application. A CA who wants the same deadlines in a
    spreadsheet, to sort by client, filter by status or send to a partner, had to retype them. The risks are the format (what a
    spreadsheet does with a cell) and a file that disagrees with the screen or with the iCalendar file about which obligations are in it.

WHAT IS HELD
    Format (`domain/practice/obligation_csv.py`, pure):
    * the file is UTF-8 with a byte-order mark, the first header says the date is a due date and not a filing date, and the rows are
      oldest due date first, then by client and obligation, so two downloads put them in one order;
    * a cell a spreadsheet would run as a formula (a client called `=HYPERLINK(...)`, or one starting + - @ tab or carriage return) is
      written as text, and a name with a comma, a quote or a line break is one cell;
    * a row with no usable due date is KEPT with an empty date, after the dated ones;
    * the "on the calendar" column is the bucket the calendar read put the row in, and the status is the stored word, unjudged.
    Route (`GET /api/compliance/obligations/calendar.csv`):
    * it serves `text/csv` as an attachment with the same window rules, overdue-always, filed-on-request, default window and assignment
      scope as the iCalendar file, and the two files hold the SAME obligations for the same request (one selection function).
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.compliance_ops as ops
from core.auth import get_current_user
from domain.practice import obligation_csv as oc
from mock_data import MOCK_COMPLIANCE_RECORDS
from services import compliance_obligation_service as ob

FIRM = "firm-csv-1"
MINE, THEIRS = "client-mine", "client-theirs"
PARTNER = {"id": "u-ptr", "firm_id": FIRM, "role": "Partner", "email": "p@f.in"}
TODAY = date(2026, 10, 10)


def _table(body: bytes) -> list[list[str]]:
    assert body.startswith(b"\xef\xbb\xbf"), "the file must start with a byte-order mark so Excel reads UTF-8"
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))


def _row(rid, due, client="c1", status="Not Started", title="GSTR-3B", kind="GST"):
    return {"id": rid, "client_id": client, "period_label": title, "compliance_type": kind, "due_date": due, "status": status}


# ── the format ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_header_names_the_date_and_the_rows_are_in_date_order():
    body = oc.from_rows([("upcoming", _row("b", "2026-11-20")), ("overdue", _row("a", "2026-09-20"))], {"c1": "Mine Traders"})
    table = _table(body)
    assert table[0] == list(oc.COLUMNS) and "not a filing date" in table[0][0]
    assert [r[0] for r in table[1:]] == ["2026-09-20", "2026-11-20"]
    assert table[1] == ["2026-09-20", "Mine Traders", "GSTR-3B", "GST", "Not Started", "Overdue"]


def test_the_bucket_is_the_calendars_and_the_status_is_the_stored_word():
    rows = [("overdue", _row("a", "2026-09-20", status="In Progress")), ("upcoming", _row("b", "2026-11-20")),
            ("completed", _row("c", "2026-10-02", status="Filed"))]
    table = _table(oc.from_rows(rows, {}))
    assert {r[0]: (r[4], r[5]) for r in table[1:]} == {"2026-09-20": ("In Progress", "Overdue"), "2026-11-20": ("Not Started", "Upcoming"),
                                                        "2026-10-02": ("Filed", "Filed")}


def test_order_is_stable_between_two_downloads_for_the_same_day():
    rows = [("upcoming", _row("2", "2026-11-20", client="c2", title="TDS")), ("upcoming", _row("1", "2026-11-20", client="c1", title="TDS"))]
    names = {"c1": "Alpha", "c2": "Beta"}
    first = oc.from_rows(rows, names)
    assert first == oc.from_rows(list(reversed(rows)), names)
    assert [r[1] for r in _table(first)[1:]] == ["Alpha", "Beta"]


@pytest.mark.parametrize("name", ["=HYPERLINK(\"http://evil\",\"x\")", "+1+1", "-2+3", "@SUM(A1)", "\t=1", "\r=1"])
def test_a_cell_a_spreadsheet_would_run_is_written_as_text(name):
    table = _table(oc.from_rows([("upcoming", _row("a", "2026-11-20"))], {"c1": name}))
    assert table[1][1] == "'" + name, "a client name that starts like a formula must not run when the CA opens the file"


def test_a_safe_name_is_not_changed_and_an_awkward_one_is_one_cell():
    names = {"c1": 'Rao, "Rao" & Sons\nTraders'}
    table = _table(oc.from_rows([("upcoming", _row("a", "2026-11-20"))], names))
    assert table[1][1] == 'Rao, "Rao" & Sons\nTraders' and len(table[1]) == len(oc.COLUMNS)
    assert oc.safe_cell("Mine Traders") == "Mine Traders" and oc.safe_cell(None) == "" and oc.safe_cell(5) == "5"


def test_a_devanagari_name_survives():
    table = _table(oc.from_rows([("upcoming", _row("a", "2026-11-20"))], {"c1": "राव एंड संस"}))
    assert table[1][1] == "राव एंड संस"


def test_a_row_with_no_due_date_is_kept_with_an_empty_date_after_the_dated_ones():
    rows = [("upcoming", _row("undated", None)), ("upcoming", _row("dated", "2026-11-20")), ("upcoming", _row("junk", "soon"))]
    table = _table(oc.from_rows(rows, {}))
    assert [r[0] for r in table[1:]] == ["2026-11-20", "", ""], "the dated row first and the two with no usable date kept, not dropped"


def test_a_row_with_no_title_still_says_what_it_is():
    table = _table(oc.from_rows([("upcoming", {"id": "x", "due_date": "2026-11-20"})], {}))
    assert table[1][2] == "Compliance obligation"


# ── the route ────────────────────────────────────────────────────────────────────────────────────────────────────────────
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


def _record(rid, due, status="Not Started", client=MINE, otype="GSTR3B"):
    MOCK_COMPLIANCE_RECORDS.append({
        "id": rid, "firm_id": FIRM, "client_id": client, "obligation_type": otype, "compliance_type": "GST", "period_label": f"{otype} {rid}",
        "period_start": due, "period_end": due, "due_date": due, "status": status,
        "created_at": "2026-04-01T00:00:00+00:00", "updated_at": "2026-04-01T00:00:00+00:00"})


def _get(path="calendar.csv", user=PARTNER, **params):
    app = FastAPI()
    app.include_router(ops.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app).get(f"/api/compliance/obligations/{path}", params=params)


def _ids(res):
    return sorted(r[2].split(" ")[-1] for r in _table(res.content)[1:])


def test_the_route_serves_a_spreadsheet_as_an_attachment():
    _record("up", "2026-11-12")
    res = _get()
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="compliance-calendar.csv"' in res.headers["content-disposition"]
    assert _table(res.content)[1] == ["2026-11-12", "Mine Traders", "GSTR3B up", "GST", "Not Started", "Upcoming"]


def test_overdue_is_always_in_and_filed_only_when_asked_for():
    _record("late", "2026-09-20")
    _record("soon", "2026-11-12")
    _record("done", "2026-11-02", status="Filed")
    assert _ids(_get()) == ["late", "soon"]
    assert _ids(_get(include_completed="true")) == ["done", "late", "soon"]
    rows = {r[2].split(" ")[-1]: r[5] for r in _table(_get(include_completed="true").content)[1:]}
    assert rows == {"late": "Overdue", "soon": "Upcoming", "done": "Filed"}


def test_the_default_window_a_bad_window_and_the_client_filter_are_the_screens():
    _record("in-year", (TODAY + timedelta(days=364)).isoformat())
    _record("beyond", (TODAY + timedelta(days=400)).isoformat())
    assert _ids(_get()) == ["in-year"]
    assert _get(date_from="2026-11-01").status_code == 422
    assert _get(date_from="2026-11-30", date_to="2026-11-01").status_code == 422
    _record("theirs", "2026-11-12", client=THEIRS)
    assert _ids(_get(client_id=THEIRS)) == ["theirs"]


def test_the_assignment_scope_is_the_screens(monkeypatch):
    _record("mine-up", "2026-11-12")
    _record("theirs-up", "2026-11-12", client=THEIRS)
    _record("theirs-late", "2026-09-12", client=THEIRS)
    monkeypatch.setattr(ops, "filter_by_client", lambda user, rows, key="client_id": [r for r in rows if r.get(key) == MINE])
    res = _get()
    assert _ids(res) == ["mine-up"] and b"Theirs" not in res.content


def test_the_spreadsheet_and_the_calendar_file_hold_the_same_obligations():
    for rid, due, status in (("late", "2026-09-20", "Not Started"), ("soon", "2026-11-12", "Not Started"), ("done", "2026-11-02", "Filed"),
                             ("far", (TODAY + timedelta(days=500)).isoformat(), "Not Started")):
        _record(rid, due, status=status)
    for params in ({}, {"include_completed": "true"}, {"date_from": "2026-11-01", "date_to": "2026-11-30"}):
        ics = sorted(line[4:].split("@")[0] for line in _get("calendar.ics", **params).text.replace("\r\n ", "").split("\r\n")
                     if line.startswith("UID:"))
        assert _ids(_get(**params)) == ics, f"the two files disagree for {params}"


def test_a_client_whose_name_cannot_be_read_still_has_its_obligation(monkeypatch):
    monkeypatch.setattr(ob, "_dashboard_names", lambda firm, clients, users: ({}, {}))
    _record("up", "2026-11-12")
    assert _table(_get().content)[1][:3] == ["2026-11-12", "", "GSTR3B up"]
