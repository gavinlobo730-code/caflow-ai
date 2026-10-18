"""A leave allotment and a client-timeline event are written through the server, as the signed-in person (POST-A-235, POST-A-228).

WHAT WAS WRONG
    The attendance screen upserted `leave_balances` straight over PostgREST, where the only rule was the ROLE (a Manager the
    Team screen had blocked from payroll:write could still change an employee's allotment), and four screens inserted into
    `client_timeline_events` themselves, choosing the actor, so a staff member could write an entry in a client's activity feed
    naming someone else. Both now go through the API; migration 515 takes the signed-in write away (proved against a real
    database in test_515_..._pg.py).

WHAT IS HELD HERE (no database)
    * the browser writes neither table any more (the feed's pin button is an UPDATE of `is_pinned` and is the one exception);
    * the leave door: refuses a row of three empty boxes, refuses a fractional or negative day, resolves the employee to the
      caller's own firm and clients (a stranger's employee answers exactly as a missing one), writes the firm the CALLER
      belongs to, and records what it replaced in the audit log;
    * the timeline door: has no field for the firm or the actor, sets both from the signed-in person, ignores one the browser
      sends anyway, accepts only a path inside the product as a link, answers a client the caller may not act on exactly as a
      missing one, and says so (503) when the event was not written;
    * the server's own timeline events are written with the privileged client and never with the caller's session, and the
      two ways of writing differ only in whether a failure is swallowed;
    * the Team screen's sentence says the database refuses a leave write.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_direct_write_tables_are_role_guarded import WEB, _chains, _strip_comments  # noqa: E402

API = Path(__file__).resolve().parents[1]

FIRM = "firm-1"
USER = {"role": "Manager", "firm_id": FIRM, "id": "u-1", "auth_user_id": "auth-1", "email": "m@firm.in", "full_name": "Maya"}


# ── the browser ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _web_chain_verbs(table: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in WEB.rglob("*.ts*"):
        if set(path.parts) & {"node_modules", ".next", "out", ".vercel"}:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, tail in _chains(_strip_comments(src)):
            if name != table:
                continue
            for verb in re.findall(r"\.\s*(insert|upsert|update|delete)\s*\(", tail):
                found.setdefault(verb, set()).add(path.relative_to(WEB).as_posix())
    return found


@pytest.mark.skipif(not WEB.is_dir(), reason="frontend not in this checkout")
def test_the_browser_no_longer_writes_the_leave_allotments():
    assert _web_chain_verbs("leave_balances") == {}


@pytest.mark.skipif(not WEB.is_dir(), reason="frontend not in this checkout")
def test_the_browser_only_pins_an_event_it_never_inserts_one():
    verbs = _web_chain_verbs("client_timeline_events")
    assert set(verbs) == {"update"}, verbs
    assert verbs["update"] == {"components/ClientTimeline.tsx"}, verbs


@pytest.mark.skipif(not WEB.is_dir(), reason="frontend not in this checkout")
def test_the_screens_that_write_these_go_through_the_api_client():
    attendance = (WEB / "app/payroll/attendance/page.tsx").read_text(encoding="utf-8")
    assert "api.payroll.saveLeaveBalance" in attendance
    timeline = (WEB / "lib/services/timeline.ts").read_text(encoding="utf-8")
    assert "api.timeline.write" in timeline
    # the browser type for what it may SAY has no firm and no actor to choose
    sent = timeline.split("export interface TimelineEventInput", 1)[1].split("}", 1)[0]
    for forbidden in ("firm_id", "actor_id", "actor_name", "actor_type", "is_pinned"):
        assert forbidden not in sent, forbidden


# ── the leave door ───────────────────────────────────────────────────────────────────────────────────────────────────

class _Query:
    def __init__(self, db, table):
        self.db, self.table, self._filters = db, table, {}
        self._upsert = None

    def select(self, *_a, **_k):
        return self

    def eq(self, key, value):
        self._filters[key] = value
        return self

    def limit(self, *_a):
        return self

    def upsert(self, row, on_conflict=None):
        self._upsert = (row, on_conflict)
        return self

    def execute(self):
        if self._upsert is not None:
            self.db.upserts.append((self.table, *self._upsert))
            return type("R", (), {"data": [{"id": "lb-1", **self._upsert[0]}]})()
        self.db.reads.append((self.table, dict(self._filters)))
        return type("R", (), {"data": list(self.db.rows.get(self.table, []))})()


class _Db:
    def __init__(self, **rows):
        self.rows = rows
        self.reads, self.upserts = [], []

    def table(self, name):
        return _Query(self, name)


@pytest.fixture()
def leave(monkeypatch):
    from routers import payroll
    from core import authz
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "_client_belongs_to_firm", lambda client_id, firm_id: True)
    monkeypatch.setattr(authz, "assigned_client_ids", lambda user: {"C-MINE"})
    audit = []
    import services.audit_service as audit_service
    monkeypatch.setattr(audit_service, "log_event", lambda *a, **k: audit.append((a, k)))
    return payroll, audit


def _body(**kw):
    from models.payroll import LeaveBalanceIn
    return LeaveBalanceIn(**{"employee_id": "E1", "year": 2026, "casual_leave_balance": 12, **kw})


def test_a_row_of_three_empty_boxes_is_refused(leave):
    payroll, _ = leave
    body = _body(casual_leave_balance=None)
    with pytest.raises(HTTPException) as e:
        payroll.put_leave_balance(body, USER)
    assert e.value.status_code == 422 and "at least one" in e.value.detail


@pytest.mark.parametrize("bad", [{"casual_leave_balance": -1}, {"sick_leave_balance": 12.5}, {"earned_leave_balance": 400},
                                 {"year": 1999}, {"year": 2101}])
def test_a_negative_fractional_or_absurd_value_never_reaches_the_database(bad):
    with pytest.raises(ValidationError):
        _body(**bad)


def test_an_employee_of_another_client_answers_as_a_missing_one(leave, monkeypatch):
    payroll, _ = leave
    monkeypatch.setattr(payroll, "_db", lambda: _Db(payroll_employees=[]))
    missing = _detail(lambda: payroll.put_leave_balance(_body(), USER))
    monkeypatch.setattr(payroll, "_db", lambda: _Db(payroll_employees=[{"client_id": "C-OTHER"}]))
    hidden = _detail(lambda: payroll.put_leave_balance(_body(), USER))
    assert missing == hidden == (404, "Employee not found")


def _detail(call):
    with pytest.raises(HTTPException) as e:
        call()
    return e.value.status_code, e.value.detail


def test_a_new_allotment_is_written_for_the_callers_firm_and_audited(leave, monkeypatch):
    payroll, audit = leave
    db = _Db(payroll_employees=[{"client_id": "C-MINE"}], leave_balances=[])
    monkeypatch.setattr(payroll, "_db", lambda: db)
    res = payroll.put_leave_balance(_body(sick_leave_balance=None, earned_leave_balance=15), USER)
    assert res["success"] is True
    [(table, row, conflict)] = db.upserts
    assert table == "leave_balances" and conflict == "employee_id,year"
    assert row == {"firm_id": FIRM, "employee_id": "E1", "year": 2026, "casual_leave_balance": 12,
                   "sick_leave_balance": None, "earned_leave_balance": 15}
    [(args, kwargs)] = audit
    assert args[:4] == (FIRM, "leave_balance", "lb-1", "create")
    assert kwargs["actor_id"] == "auth-1" and kwargs["old_data"] is None and kwargs["new_data"]["casual_leave_balance"] == 12


def test_a_changed_allotment_records_what_it_replaced(leave, monkeypatch):
    payroll, audit = leave
    before = {"id": "lb-1", "casual_leave_balance": 10, "sick_leave_balance": 10, "earned_leave_balance": 10}
    db = _Db(payroll_employees=[{"client_id": "C-MINE"}], leave_balances=[before])
    monkeypatch.setattr(payroll, "_db", lambda: db)
    payroll.put_leave_balance(_body(casual_leave_balance=14), USER)
    [(args, kwargs)] = audit
    assert args[3] == "update"
    assert kwargs["old_data"] == {"casual_leave_balance": 10, "sick_leave_balance": 10, "earned_leave_balance": 10}
    # the read that found the old value was for THIS firm's row
    assert any(t == "leave_balances" and f.get("firm_id") == FIRM for t, f in db.reads)


def test_the_route_asks_payroll_write():
    from routers import payroll
    route = next(r for r in payroll.router.routes if getattr(r, "path", "") == "/api/payroll/leave-balance")
    assert route.methods == {"PUT"}
    fn = next(n for n in ast.walk(ast.parse((API / "routers" / "payroll.py").read_text(encoding="utf-8")))
              if isinstance(n, ast.FunctionDef) and n.name == "put_leave_balance")
    defaults = {a.arg: d for a, d in zip(fn.args.args[-len(fn.args.defaults):], fn.args.defaults, strict=True)}
    assert ast.unparse(defaults["current_user"]) == "Depends(rbac('payroll', 'write'))"


# ── the timeline door ────────────────────────────────────────────────────────────────────────────────────────────────

def _event(**kw):
    from routers.timeline import TimelineEventIn
    return TimelineEventIn(**{"client_id": "C-MINE", "financial_year": "2026-27", "category": "document",
                              "event_type": "document_uploaded", "title": "Document uploaded: PAN", **kw})


@pytest.fixture()
def feed(monkeypatch):
    from core import authz
    import services.timeline_service as ts
    from repositories.client_repository import client_repo
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "_client_belongs_to_firm", lambda client_id, firm_id: True)
    monkeypatch.setattr(authz, "assigned_client_ids", lambda user: {"C-MINE"})
    monkeypatch.setattr(client_repo, "find_by_id", lambda cid, firm_id=None: {"id": cid} if cid == "C-MINE" else None)
    monkeypatch.setattr(ts, "_USE_MOCK", True)
    ts.MOCK_TIMELINE_EVENTS.clear()
    yield ts
    ts.MOCK_TIMELINE_EVENTS.clear()


def test_the_event_names_the_signed_in_person_and_the_callers_firm(feed):
    from routers import timeline
    res = timeline.write_timeline_event(_event(), USER)
    event = res["data"]
    assert event["firm_id"] == FIRM and event["actor_type"] == "user"
    assert event["actor_id"] == "auth-1" and event["actor_name"] == "Maya"
    assert event["is_pinned"] is False and feed.MOCK_TIMELINE_EVENTS == [event]


def test_the_name_falls_back_to_the_email(feed):
    from routers import timeline
    event = timeline.write_timeline_event(_event(), USER | {"full_name": None})["data"]
    assert event["actor_name"] == "m@firm.in"


def test_a_firm_or_an_actor_the_browser_sends_is_ignored(feed):
    from routers import timeline
    body = _event(firm_id="firm-evil", actor_name="The Partner", actor_id="x", actor_type="system", is_pinned=True)
    assert not hasattr(body, "firm_id") and not hasattr(body, "actor_name")
    event = timeline.write_timeline_event(body, USER)["data"]
    assert event["firm_id"] == FIRM and event["actor_name"] == "Maya" and event["is_pinned"] is False


def test_a_client_the_caller_may_not_act_on_answers_as_a_missing_one(feed):
    from routers import timeline
    unassigned = _detail(lambda: timeline.write_timeline_event(_event(client_id="C-OTHER"), USER))
    missing = _detail(lambda: timeline.write_timeline_event(_event(client_id="C-NONE"), USER))
    assert unassigned == missing == (404, "Client not found")
    assert feed.MOCK_TIMELINE_EVENTS == []


@pytest.mark.parametrize("url,ok", [("/clients/1/documents", True), ("/", True), ("//evil.example", False),
                                    ("https://evil.example/x", False), ("/a b", False), ("javascript:alert(1)", False)])
def test_a_link_is_a_path_inside_the_product(url, ok):
    if ok:
        assert _event(action_url=url).action_url == url
    else:
        with pytest.raises(ValidationError):
            _event(action_url=url)


@pytest.mark.parametrize("bad", [{"category": "secrets"}, {"severity": "fatal"}, {"visibility": "everyone"},
                                 {"event_type": "Has Spaces"}, {"title": ""}, {"financial_year": "2026-28"},
                                 {"amount_paise": -1}])
def test_an_event_outside_the_vocabulary_is_refused(bad):
    with pytest.raises(ValidationError):
        _event(**bad)


def test_an_event_that_could_not_be_written_says_so(feed, monkeypatch):
    from routers import timeline

    def boom(**_k):
        raise RuntimeError("db down")
    monkeypatch.setattr(feed.timeline_service, "record_event", boom)
    status, detail = _detail(lambda: timeline.write_timeline_event(_event(), USER))
    assert status == 503 and "could not be recorded" in detail


# ── the service ──────────────────────────────────────────────────────────────────────────────────────────────────────

class _Insert:
    def __init__(self, sink, fail):
        self.sink, self.fail = sink, fail

    def table(self, name):
        assert name == "client_timeline_events"
        return self

    def insert(self, row):
        self.row = row
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("refused")
        self.sink.append(self.row)
        return type("R", (), {"data": [self.row]})()


def _service(monkeypatch, fail=False):
    import services.timeline_service as ts
    sink: list = []
    monkeypatch.setattr(ts, "_USE_MOCK", False)
    monkeypatch.setattr(ts, "_write_db", lambda: _Insert(sink, fail))
    return ts.timeline_service, sink


def test_the_servers_own_events_are_written_with_the_privileged_client(monkeypatch):
    svc, sink = _service(monkeypatch)
    svc.log("C-1", "work", "Attendance Entered", "5 employees", firm_id=FIRM, actor_id="auth-1")
    [row] = sink
    assert row["firm_id"] == FIRM and row["actor_id"] == "auth-1" and row["event_type"] == "attendance_entered"
    # an optional column left unset is OMITTED, not sent as NULL (the table's own defaults apply)
    assert "entity_id" not in row and "action_url" not in row and "amount_paise" not in row


def test_every_key_a_timeline_row_can_carry_is_a_column_of_the_table():
    """The compensating control for two unreadable references (tests/test_backend_columns_exist_pg.py): the insert payload is
    assembled from `_row`, so the column-existence scan cannot read it. The keys `_row` can produce are asserted against the
    production snapshot here, so a key added to it that the table does not have fails in the mock-mode job."""
    import json
    import services.timeline_service as ts
    snapshot = json.loads((API / "tests" / "fixtures" / "production_schema_2026-09-03.json").read_text(encoding="utf-8"))
    columns = set(snapshot["client_timeline_events"])
    row = ts.TimelineService._row(client_id="c", firm_id="f", financial_year="2026-27", category="work", event_type="x",
                                  title="T")
    assert set(row) <= columns, sorted(set(row) - columns)
    # and the stored form is a subset of the row, with the optional columns dropped when unset
    assert set(ts.TimelineService._stored(row)) <= set(row)


def test_the_service_never_asks_for_the_callers_session():
    src = (API / "services" / "timeline_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "get_supabase" not in names and "request_db" not in names
    assert "service_db" in names


def test_a_server_log_swallows_a_failure_and_a_requested_record_does_not(monkeypatch):
    svc, sink = _service(monkeypatch, fail=True)
    svc.log("C-1", "work", "Something", firm_id=FIRM)            # non-fatal, by design
    assert sink == []
    with pytest.raises(RuntimeError):
        svc.record_event(client_id="C-1", firm_id=FIRM, financial_year="2026-27", category="work",
                         event_type="x", title="T")


def test_nothing_else_in_the_api_inserts_into_the_feed():
    """The privileged write has one door. A second would be a second place to forget the firm."""
    offenders = []
    for path in API.rglob("*.py"):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", "migrations/", "scripts/")) or rel == "services/timeline_service.py":
            continue
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r'client_timeline_events"\s*\)([^;]*)', src):
            if re.search(r"\.\s*(insert|upsert)\s*\(", m.group(1)[:200]):
                offenders.append(rel)
    assert not offenders, offenders


# ── the Team screen's sentence ───────────────────────────────────────────────────────────────────────────────────────

def test_the_team_screens_sentence_says_the_database_refuses_a_leave_write():
    from services.user_permission_service import DENIAL_REACH_NOTICE as notice
    text = " ".join(notice.split())
    assert "any write to employees, runs, payslips, attendance, leave balances" in text
    assert "Leave balances and tax declarations can still be saved" not in text
    assert "An employee's own tax declaration can still be saved from the browser" in text
