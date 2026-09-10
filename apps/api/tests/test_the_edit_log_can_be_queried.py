"""ACC-07 — the Rule 3(1) edit log is written, and now it can be read.

WHAT WAS WRONG
    The proviso to Rule 3(1) of the Companies (Accounts) Rules 2014 requires
    books kept in electronic mode to carry an EDIT LOG. This product writes a
    thorough one — migration 111's triggers on every firm-scoped table,
    migration 266's on journal entries and lines, and services all over the
    backend — and almost none of it could be READ.

    GET /api/audit capped at 200 rows FIRM-WIDE with no date range and no
    paging, and its only caller fetched those 200 and filtered them IN THE
    BROWSER (apps/web/app/settings/audit-log/page.tsx). So "show me April"
    showed whatever fell inside the most recent 200 events, and there was no
    way to ask a different question.

    Per-entry history was impossible from any screen even though the trigger
    already keys a journal_line row to its PARENT entry id (migration 266) and
    the endpoint already accepted entity_id. A backend capability reachable
    from nothing.

THE TWO THINGS THIS PINS, BECAUSE BOTH ARE SILENT WHEN WRONG
    1. An IST date is not a UTC date. The column is timestamptz and a CA means
       IST, so a UTC-date filter moves the window five and a half hours and
       drops everything between midnight and 05:30 IST — the quiet hours a
       scheduled job runs in.
    2. now() is the TRANSACTION's timestamp, so every line of one journal edit
       shares an instant. A cursor of "created_at < last_seen" drops all of
       them but one, which is exactly the multi-line edit the history exists
       to show.
"""
from __future__ import annotations

import pathlib
import uuid

import pytest

from services import audit_query_service as aq

WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"

FIRM = "11111111-1111-1111-1111-111111111111"


# ── An IST date is not a UTC date ───────────────────────────────────────────

def test_a_day_runs_from_midnight_ist_not_midnight_utc():
    lo, hi = aq.ist_day_bounds("2026-09-10", "2026-09-10")
    # 00:00 IST on the 10th is 18:30 UTC on the 9th. A UTC-date filter would
    # start at 00:00Z and silently drop 00:00-05:30 IST.
    assert lo == "2026-09-10T00:00:00+05:30"
    # date_to is INCLUSIVE of its whole day, so the upper bound is the start of
    # the next IST day — an exclusive bound would drop a day's work.
    assert hi == "2026-09-11T00:00:00+05:30"


def test_a_single_day_window_is_exactly_twenty_four_hours():
    from datetime import datetime
    lo, hi = aq.ist_day_bounds("2026-04-01", "2026-04-01")
    span = datetime.fromisoformat(hi) - datetime.fromisoformat(lo)
    assert span.total_seconds() == 24 * 3600


def test_a_date_that_is_not_a_date_is_refused_with_the_shape():
    with pytest.raises(aq.AuditQueryRefused) as e:
        aq.ist_day_bounds("last tuesday", None)
    assert "2026-09-10" in str(e.value)


def test_a_backwards_window_is_refused():
    with pytest.raises(aq.AuditQueryRefused):
        aq.ist_day_bounds("2026-09-10", "2026-09-01")


def test_no_dates_means_no_window():
    assert aq.ist_day_bounds(None, None) == (None, None)


# ── The cursor breaks ties on the id ────────────────────────────────────────

def test_the_cursor_round_trips():
    row = {"created_at": "2026-09-10T04:30:00+00:00", "id": str(uuid.uuid4())}
    assert aq.decode_cursor(aq.encode_cursor(row)) == (row["created_at"], row["id"])


def test_the_cursor_names_both_halves_of_the_row_comparison():
    """Postgres would write (created_at, id) < (?, ?); PostgREST has no tuple
    comparison, so it is spelled out. Dropping the second limb loses every row
    sharing the last one's instant — which is every other line of one edit."""
    row_id = str(uuid.uuid4())
    clause = aq.cursor_clause(("2026-09-10T04:30:00+00:00", row_id))
    assert clause.startswith("created_at.lt.2026-09-10T04:30:00+00:00,")
    assert f"and(created_at.eq.2026-09-10T04:30:00+00:00,id.lt.{row_id})" in clause


def test_a_cursor_this_log_did_not_issue_is_refused():
    for bad in ("not-base64!!", aq.encode_cursor({"created_at": "x", "id": "abc"})):
        with pytest.raises(aq.AuditQueryRefused):
            aq.decode_cursor(bad)


def test_no_cursor_is_not_an_error():
    assert aq.decode_cursor(None) is None
    assert aq.decode_cursor("") is None


# ── The query itself ────────────────────────────────────────────────────────

class _Q:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def _rec(self, name, *a):
        self.calls.append((name, *a)); return self

    def select(self, *a): return self._rec("select", *a)
    def eq(self, k, v): return self._rec("eq", k, v)
    def in_(self, k, v): return self._rec("in_", k, list(v))
    def gte(self, k, v): return self._rec("gte", k, v)
    def lt(self, k, v): return self._rec("lt", k, v)
    def or_(self, expr): return self._rec("or_", expr)
    def order(self, k, desc=False): return self._rec("order", k, desc)
    def limit(self, n): self._rec("limit", n); self._limit = n; return self

    def execute(self):
        class _R:
            data = self.rows[:self._limit]
        return _R()


class _DB:
    def __init__(self, rows):
        self.q = _Q(rows)

    def table(self, name):
        self.q.calls.append(("table", name))
        return self.q


def _rows(n, *, same_instant=False):
    return [{
        "id": f"{i:08d}-0000-0000-0000-000000000000",
        "firm_id": FIRM, "actor_id": None, "actor_email": "ca@f.test",
        "entity_type": "journal_line", "entity_id": "entry-1", "action": "update",
        "old_data": {}, "new_data": {}, "metadata": {},
        "created_at": ("2026-09-10T04:30:00+00:00" if same_instant
                       else f"2026-09-10T04:{59 - i:02d}:00+00:00"),
    } for i in range(n)]


def test_every_filter_is_applied_in_the_database():
    """The screen this replaced pulled 200 rows and filtered them in the
    browser, so a date range could only narrow the most recent 200 events."""
    db = _DB(_rows(3))
    aq.query(db, FIRM, entity_type="journal_entry", entity_id="e1",
             actor_id="u1", action="update",
             date_from="2026-09-01", date_to="2026-09-30", limit=10)
    calls = dict((c[1], c[2]) for c in db.q.calls if c[0] == "eq")
    assert calls["firm_id"] == FIRM
    assert calls["entity_type"] == "journal_entry"
    assert calls["entity_id"] == "e1"
    assert calls["actor_id"] == "u1"
    assert calls["action"] == "update"
    assert any(c[0] == "gte" and c[1] == "created_at" for c in db.q.calls)
    assert any(c[0] == "lt" and c[1] == "created_at" for c in db.q.calls)


def test_two_entity_types_are_one_question():
    """A journal entry's history that omits its lines omits the amounts."""
    db = _DB(_rows(2))
    aq.query(db, FIRM, entity_type="journal_entry,journal_line", entity_id="e1")
    ins = [c for c in db.q.calls if c[0] == "in_"]
    assert ins and ins[0][1] == "entity_type"
    assert set(ins[0][2]) == {"journal_entry", "journal_line"}


def test_the_page_is_ordered_by_instant_then_id_and_asks_for_one_extra():
    db = _DB(_rows(10))
    out = aq.query(db, FIRM, limit=5)
    orders = [(c[1], c[2]) for c in db.q.calls if c[0] == "order"]
    assert orders == [("created_at", True), ("id", True)]
    # One more than asked for, so "is there another page" needs no COUNT over
    # the whole log — which is the cost this endpoint exists to remove.
    assert ("limit", 6) in db.q.calls
    assert len(out["entries"]) == 5
    assert out["has_more"] is True
    assert out["next_cursor"]


def test_the_last_page_offers_no_cursor():
    db = _DB(_rows(3))
    out = aq.query(db, FIRM, limit=5)
    assert out["has_more"] is False
    assert out["next_cursor"] is None
    assert len(out["entries"]) == 3


def test_the_next_page_carries_both_halves_of_the_comparison():
    """The rows of one journal edit share a transaction timestamp, so the
    cursor must be able to distinguish them."""
    db = _DB(_rows(10, same_instant=True))
    first = aq.query(db, FIRM, limit=5)
    db2 = _DB(_rows(10, same_instant=True))
    aq.query(db2, FIRM, limit=5, cursor=first["next_cursor"])
    ors = [c[1] for c in db2.q.calls if c[0] == "or_"]
    assert ors, "the cursor did not reach the query"
    assert "created_at.lt." in ors[0] and "and(created_at.eq." in ors[0]


def test_a_page_cannot_be_larger_than_the_cap():
    assert aq.clamp_limit(100000) == aq.MAX_PAGE
    assert aq.clamp_limit(0) == 1
    assert aq.clamp_limit(None) == aq.DEFAULT_PAGE


def test_the_answer_carries_no_total():
    """A COUNT over the whole log to render one page is the cost removed."""
    out = aq.query(_DB(_rows(3)), FIRM)
    assert "total" not in out
    assert "has_more" in out


# ── The two modules stay apart ──────────────────────────────────────────────

def test_the_write_path_is_a_different_module():
    """services/audit_service.log_event appends and never raises, and its
    docstring carries the DPDP retention and redaction reasoning. One file
    doing both would put a query cursor next to an erasure rule."""
    from services.audit_service import log_event          # noqa: F401
    src = pathlib.Path(aq.__file__).read_text()
    assert "def log_event" not in src


# ── The screen asks the server ──────────────────────────────────────────────

def test_the_audit_screen_filters_on_the_server():
    page = (WEB / "app" / "settings" / "audit-log" / "page.tsx").read_text()
    assert "api.audit.list(" in page
    # The browser-side filter over a fixed 200-row fetch, gone.
    assert "FETCH_LIMIT" not in page
    for served in ("date_from", "date_to", "entity_type", "action"):
        assert served in page, f"{served} is not sent to the server"


def test_a_journal_entry_can_show_its_own_history():
    """The question an auditor actually asks."""
    src = "\n".join(
        p.read_text() for folder in ("app", "components", "lib")
        for p in (WEB / folder).rglob("*.ts*") if ".test." not in p.name)
    assert "api.audit.entityHistory(" in src
    assert "journal_entry,journal_line" in src
