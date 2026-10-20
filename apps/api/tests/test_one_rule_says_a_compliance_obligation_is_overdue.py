"""A compliance obligation is OVERDUE by its date, in every backend reader, and the word in the column is nobody's evidence.

WHAT WAS WRONG (found by opening the seeded demo firm in a browser, 19-10-2026)
    `compliance_records.status` is the stored workflow state, and "Overdue" in it is a transition somebody makes by hand: nothing in
    `apps/api` sets it when a due date passes. The Deadlines screen derives it from the date (`apps/web/lib/compliance/overdue.ts`) and
    counted 220 overdue obligations on the seeded firm. Readers in seven backend modules asked for the stored word, so on the same firm
    the executive dashboard said 0 overdue filings, the client health score deducted nothing, the risk engine and the insight generator
    raised nothing, the client summary said 0 overdue, and the AI assistant was told "OVERDUE COMPLIANCE FILINGS: 0". The older readers
    also compared a status only with "Filed", so an obligation Completed (the terminal step after Filed) with a past date counted as
    late and as high-risk.

WHAT IS HELD
    * `domain/practice/compliance_overdue.is_overdue`: settled ("Filed", "Completed") is never overdue; the stored "Overdue" is; otherwise
      the due date is strictly before the CA's day (due today is not late until the day is out), a missing date is not late, and a
      datetime handed in by mistake is read as its day.
    * Each reader is driven with the stored word and the date DISAGREEING (a hand-set Overdue with a date ahead; a Completed record in
      the past), against classes of different sizes (late 2, settled-and-past 4, open and not late 1) so a reader that counts the wrong
      class cannot land on the right number, and with a late row that belongs to ANOTHER FIRM that no reader may count.
    * The clock is frozen at 31 March 2026 and every question put to the rule is recorded: after each test, every reader handed the rule
      exactly that day, as a `date`. Fixtures days from the boundary cannot tell a reader that asks yesterday (the UTC date, for five and
      a half hours of every night), a datetime or a day it worked out itself from one that asks the right clock.
    * A scan of the backend fails a comparison, a `status=` keyword or a PostgREST filter that hands a status the word "overdue" in any
      case, and any use of `STORED_OVERDUE` outside the rule's own module; the entities with their own "overdue" are named by FUNCTION,
      not exempted by file. Beside it an inventory of every literal "Overdue" in the backend by file, spelling-independent: a new one, in
      any role, fails until it has been looked at. Neither can see a word built from pieces or SQL; the reader tests above are the half
      that holds a reader with its own settled words.
"""
from __future__ import annotations

import ast
import asyncio
import json
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

import core.ist_clock as ist_clock
import domain.ai_copilot_service as copilot
import domain.compliance_record_service as crs
import domain.memory_pipeline as memory
from domain.practice import compliance_overdue as co

FIRM = "f1"
CLIENT = "c1"
#: The CA's day for every test in this module: 31 March 2026, 15:30 IST (10:00 UTC). It is frozen below, so a reader that asks any
#: other clock (the UTC date, yesterday, a datetime) is judging a different day from the one the fixtures are built on.
TODAY = date(2026, 3, 31)
FROZEN_UTC = datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc)

#: Tests that hand the rule a day of their own choosing (or a datetime on purpose), so the check below has nothing to say about them.
HANDS_ITS_OWN_DAY = {
    "test_an_obligation_is_overdue_when_unsettled_and_late_or_moved_there_by_hand",
    "test_an_obligation_due_today_is_not_late_until_the_day_is_out_and_a_missing_date_is_never_late",
    "test_a_datetime_handed_in_by_mistake_is_read_as_its_day",
    "test_the_rule_is_judged_against_the_day_it_is_handed",
    "test_the_health_score_is_judged_against_the_cas_day_when_none_is_given",
    "test_a_due_date_that_arrives_as_a_date_object_is_judged_as_its_day",
}


@pytest.fixture(autouse=True)
def the_cas_day(request, monkeypatch):
    """Freeze the shared IST clock (every reader asks it through `core.ist_clock`) and watch every question put to the rule.

    A reader that hands the rule the wrong day (yesterday, which is what the UTC date is for five and a half hours of every night, a
    datetime, or a day it computed itself) gives the same answer as the right one on any fixture that is days away from the boundary,
    so the day each reader PASSES is what is checked: after each test, every call the readers made to `is_overdue` carried exactly the
    frozen day, as a `date`."""
    fixed = FROZEN_UTC

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed

    monkeypatch.setattr(ist_clock, "datetime", _Frozen)
    seen: list = []
    real = co.is_overdue

    def spy(record, today):
        seen.append(today)
        return real(record, today)

    for module in list(sys.modules.values()):
        try:
            if getattr(module, "is_overdue", None) is real:
                monkeypatch.setattr(module, "is_overdue", spy)
        except Exception:   # a lazily loaded or proxied module that cannot be asked
            continue
    yield seen
    if request.node.originalname not in HANDS_ITS_OWN_DAY:
        wrong = [d for d in seen if type(d) is not date or d != TODAY]
        assert not wrong, f"a reader handed the rule {wrong[:3]!r} and not the CA's day {TODAY!r}"


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def rec(id_, status, due_in, **more):
    return {"id": id_, "firm_id": FIRM, "client_id": CLIENT, "status": status, "due_date": _iso(due_in),
            "compliance_type": "GST", "period_label": f"P-{id_}", "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00", **more}


#: A: late and untouched (the common real case). B: filed, a past date. C: completed, a past date. D: due in two months. E: somebody moved
#: it to Overdue by hand, though its date is ahead. So the overdue ones are A and E, and only those.
A, B, C, D, E = (rec("A", "Not Started", -30), rec("B", "Filed", -30), rec("C", "Completed", -30),
                 rec("D", "Not Started", 60), rec("E", "Overdue", 60))
#: Two more settled ones, so the three classes have different sizes (late 2, settled-and-past 4, open and not late 1): a reader that
#: counts the wrong class cannot land on the right number by coincidence. And one late obligation that belongs to ANOTHER FIRM, which
#: no reader may count.
B2, C2 = rec("B2", "Filed", -90), rec("C2", "Completed", -90)
OTHER_FIRM = {**rec("X", "Not Started", -30), "firm_id": "other-firm"}
RECORDS = [A, B, C, D, E, B2, C2]


class _Records:
    """A compliance_records repository: `find_all` with the filters the readers use."""
    def __init__(self, rows):
        self.rows = list(rows) + [OTHER_FIRM]

    def find_all(self, firm_id=None, client_id=None, status=None, compliance_type=None, exclude_statuses=None, due_from=None, due_to=None):
        out = [r for r in self.rows if (client_id is None or r.get("client_id") == client_id)
               and (firm_id is None or r.get("firm_id") == firm_id)]
        if status:
            out = [r for r in out if r.get("status") == status]
        if exclude_statuses:
            out = [r for r in out if r.get("status") not in exclude_statuses]
        return out


# ── the rule ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,due_in,expected", [
    ("Not Started", -1, True), ("Awaiting Documents", -5, True), ("In Progress", -400, True), ("Ready For Review", -1, True),
    ("Ready To File", -1, True), ("Not Started", 0, False), ("Not Started", 1, False), ("Not Started", 365, False),
    ("Overdue", 30, True), ("Overdue", -3, True),
    ("Filed", -400, False), ("Completed", -400, False), ("Filed", 30, False), ("Completed", 0, False),
])
def test_an_obligation_is_overdue_when_unsettled_and_late_or_moved_there_by_hand(status, due_in, expected):
    assert co.is_overdue({"status": status, "due_date": _iso(due_in)}, TODAY) is expected


def test_an_obligation_due_today_is_not_late_until_the_day_is_out_and_a_missing_date_is_never_late():
    assert co.is_overdue({"status": "Not Started", "due_date": TODAY.isoformat()}, TODAY) is False
    assert co.is_overdue({"status": "Not Started", "due_date": (TODAY - timedelta(days=1)).isoformat()}, TODAY) is True
    for missing in (None, ""):
        assert co.is_overdue({"status": "Not Started", "due_date": missing}, TODAY) is False
    assert co.is_overdue({"status": "Not Started"}, TODAY) is False
    # A due date that arrives as a timestamp is judged as its date is
    assert co.is_overdue({"status": "Not Started", "due_date": f"{_iso(-1)}T18:30:00+00:00"}, TODAY) is True
    assert co.is_overdue({"status": "Not Started", "due_date": f"{TODAY.isoformat()}T00:00:00+00:00"}, TODAY) is False


def test_a_datetime_handed_in_by_mistake_is_read_as_its_day():
    """`datetime` is a subclass of `date`, and "2026-10-20" sorts before "2026-10-20T10:00:00": without the slice an obligation due
    today would read as late for anyone who passed `ist_now()`."""
    from datetime import datetime
    due_today = {"status": "Not Started", "due_date": TODAY.isoformat()}
    assert co.is_overdue(due_today, datetime(TODAY.year, TODAY.month, TODAY.day, 10, 0)) is False
    assert co.is_overdue({"status": "Not Started", "due_date": _iso(-1)}, datetime(TODAY.year, TODAY.month, TODAY.day, 10, 0)) is True


def test_a_due_date_that_arrives_as_a_date_object_is_judged_as_its_day():
    assert co.is_overdue({"status": "Not Started", "due_date": date(2026, 3, 30)}, TODAY) is True
    assert co.is_overdue({"status": "Not Started", "due_date": date(2026, 3, 31)}, TODAY) is False
    assert co.is_overdue({"status": "Not Started", "due_date": datetime(2026, 3, 31, 9, 30)}, TODAY) is False


def test_the_rule_is_judged_against_the_day_it_is_handed():
    due = {"status": "Not Started", "due_date": "2026-03-31"}
    assert co.is_overdue(due, date(2026, 3, 31)) is False and co.is_overdue(due, date(2026, 4, 1)) is True


def test_overdue_records_keeps_the_order_given_and_only_the_overdue():
    assert [r["id"] for r in co.overdue_records(RECORDS, TODAY)] == ["A", "E"]
    assert [r["id"] for r in co.overdue_records(reversed(RECORDS), TODAY)] == ["E", "A"]


# ── the health score and the risk score ──────────────────────────────────────────────

def _with_risk(rows):
    return [{**r, "risk_score": crs._compute_risk_score(r)} for r in rows]


def test_a_completed_obligation_with_a_past_date_carries_no_risk_and_a_late_one_is_critical():
    assert crs._compute_risk_score(C) == 0 and crs._compute_risk_score(B) == 0
    assert crs._compute_risk_score(A) == 90 and crs._compute_risk_score(E) == 90


def test_an_obligation_is_critical_the_day_after_its_date_and_high_on_the_day_itself():
    """The strict boundary, through the risk score: due yesterday is late (90), due today is high (75) until the day is out, and the
    frozen clock is what makes these two rows the two sides of the line."""
    assert crs._compute_risk_score(rec("Q", "Not Started", -1)) == 90
    assert crs._compute_risk_score(rec("Q", "Not Started", 0)) == 75
    assert crs._compute_risk_score(rec("Q", "Not Started", 1)) == 75


def test_a_prepared_return_that_has_missed_its_date_is_critical_and_one_not_yet_due_stays_low():
    """"Ready To File" used to return its low score before the date was asked, so the health score counted such a return as late
    (it asks the one rule) while its own risk said 20, the lowest in the module."""
    assert crs._compute_risk_score(rec("R", "Ready To File", -5)) == 90
    assert crs._compute_risk_score(rec("R", "Ready To File", 20)) == 20
    assert crs._compute_risk_score(rec("R", "Ready To File", 2)) == 20, "inside the week it keeps its own answer, as before"


def test_the_health_score_deducts_twenty_for_each_obligation_that_is_late_by_its_date():
    score, breakdown = crs.compliance_record_service.score_from_records(_with_risk(RECORDS), TODAY)
    assert score == 100 - 20 - 20, "A and E are late; B and C are settled; D is far off"
    assert [b["deduction"] for b in breakdown] == [20, 20]
    only_settled = crs.compliance_record_service.score_from_records(_with_risk([B, C]), TODAY)
    assert only_settled[0] == 100, "a Filed and a Completed obligation, however old, cost nothing"


def test_the_health_score_is_judged_against_the_cas_day_when_none_is_given(monkeypatch):
    """The day comes from `ist_today`, so a fixed one is patched in: the real day would make a test of the CA's clock agree with any clock."""
    row = {"id": "Z", "status": "Not Started", "due_date": "2026-03-31", "risk_score": 0}
    monkeypatch.setattr(crs, "ist_today", lambda: date(2026, 3, 31))
    assert crs.compliance_record_service.score_from_records([row])[0] == 100, "due today is not late until the day is out"
    monkeypatch.setattr(crs, "ist_today", lambda: date(2026, 4, 1))
    assert crs.compliance_record_service.score_from_records([row])[0] == 80, "a day later it is"


class _Clients:
    def find_by_id(self, client_id):
        return {"id": client_id, "firm_id": FIRM, "client_name": "A client"}

    def find_all(self, **kw):
        return [{"id": CLIENT, "firm_id": FIRM, "client_name": "A client"}]


def _records_repo(monkeypatch, rows):
    repo = _Records(rows)
    monkeypatch.setattr(crs, "compliance_records_repo", repo)
    monkeypatch.setattr(crs, "client_repo", _Clients())
    return repo


def test_the_client_health_score_counts_the_overdue_records_by_date(monkeypatch):
    _records_repo(monkeypatch, RECORDS)
    got = crs.compliance_record_service.get_client_health_score(CLIENT, firm_id=FIRM)
    assert got["overdue_records"] == 2 and got["health_score"] == 60 and got["risk_level"] == "medium"


def test_the_firm_summary_counts_the_overdue_by_date_and_leaves_a_completed_one_out_of_due_this_week(monkeypatch):
    soon_open, soon_done = rec("F", "Not Started", 3), rec("G", "Completed", 3)
    _records_repo(monkeypatch, RECORDS + [soon_open, soon_done])
    got = crs.compliance_record_service.get_firm_summary(firm_id=FIRM)
    assert got["overdue"] == 2
    assert got["due_this_week"] == 1, "F is due in three days; G is Completed and owes nothing"


def test_a_filing_moved_on_to_completed_this_month_is_still_a_filing_this_month(monkeypatch):
    month = TODAY.replace(day=1).isoformat()
    _records_repo(monkeypatch, [rec("P", "Filed", -2, filed_date=month), rec("Q", "Completed", -2, filed_date=month),
                                rec("R", "In Progress", -2, filed_date=month)])
    assert crs.compliance_record_service.get_firm_summary(firm_id=FIRM)["filed_this_month"] == 2


# ── the executive dashboard ──────────────────────────────────────────────────────────

class _Tasks:
    def find_overdue(self, **kw):
        return []


class _Workflows:
    def list_failures(self, firm_id, **kw):
        return []

    def list_approvals(self, firm_id, **kw):
        return []

    def list_templates(self, firm_id, **kw):
        return []

    def client_ids_for_instances(self, firm_id, ids):
        return {}

    def list_recommendations(self, *a, **k):
        return []


class _SummaryStore:
    def get_summary(self, *a, **k):
        return None

    def upsert_summary(self, firm_id, kind, entity, row):
        return row


@pytest.fixture
def world(monkeypatch):
    repo = _Records(RECORDS)
    svc = copilot.ai_copilot_service
    monkeypatch.setattr(copilot, "_get_client_repo", lambda: _Clients())
    monkeypatch.setattr(copilot, "_get_task_repo", lambda: _Tasks())
    monkeypatch.setattr(copilot, "_get_compliance_records_repo", lambda: repo)
    monkeypatch.setattr(copilot, "_get_workflow_repo", lambda: _Workflows())
    monkeypatch.setattr(svc, "_repo", _SummaryStore())
    sent: list = []

    async def _model(messages, **kw):
        sent.append(messages)
        return "ok", 7
    monkeypatch.setattr(svc, "_call_groq", _model)
    return svc, repo, sent


def test_the_executive_dashboard_counts_the_late_filings_by_date(world):
    svc, _repo, _sent = world
    got = asyncio.run(svc.get_executive_dashboard(FIRM))
    assert got["client_risk_insights"]["compliance_failures"] == 2


def test_the_assistants_global_context_says_how_many_filings_are_late(world):
    svc, _repo, _sent = world
    context = svc._build_context(FIRM, "global", None, None)
    assert "OVERDUE COMPLIANCE FILINGS: 2" in context


def test_the_assistants_client_context_says_how_many_filings_are_late(world, monkeypatch):
    svc, _repo, _sent = world
    monkeypatch.setattr(copilot, "_get_client_repo", lambda: type("C", (), {
        "find_by_id": lambda self, cid, **kw: {"id": cid, "status": "active", "health_score": 71},
        "find_all": lambda self, **kw: [{"id": CLIENT}]})())
    context = svc._build_context(FIRM, "client", CLIENT, None)
    assert "CLIENT OVERDUE COMPLIANCE TASKS: 2" in context


def test_the_compliance_insight_prompt_is_told_the_late_filings_and_a_score_that_follows_them(world):
    svc, _repo, sent = world
    asyncio.run(svc.get_compliance_intelligence(FIRM))
    prompt = sent[-1][-1]["content"]
    assert "Overdue filings: 2 (affecting 1 clients)" in prompt
    assert "Estimated compliance health score: 90/100" in prompt


def test_the_client_report_prompt_is_told_the_late_filings(world, monkeypatch):
    svc, _repo, sent = world
    monkeypatch.setattr(copilot, "_get_client_repo", lambda: type("C", (), {
        "find_by_id": lambda self, cid, **kw: {"id": cid, "client_name": "X", "status": "active", "health_score": 71}})())
    asyncio.run(svc.get_client_intelligence(FIRM, CLIENT))
    assert "Overdue compliance tasks: 2" in sent[-1][-1]["content"]


# ── the readers outside the copilot ──────────────────────────────────────────────────

def _dashboard(monkeypatch, records):
    import domain.task_service as ts

    class _TaskRepo:
        def find_open(self, **kw):
            return []

        def find_overdue(self, **kw):
            return []

    monkeypatch.setattr(ts, "task_repo", _TaskRepo())
    monkeypatch.setattr(ts, "client_repo", type("C", (), {"find_all": lambda self, **kw: [
        {"id": CLIENT, "status": "active", "client_name": "X"}]})())
    monkeypatch.setattr(crs.compliance_record_service, "list_records", lambda **kw: _with_risk(records))
    return ts.TaskDomainService().get_dashboard_summary(firm_id=FIRM)


def test_the_practice_dashboard_counts_the_late_compliance_and_not_a_completed_one(monkeypatch):
    soon_open, soon_done = rec("F", "Not Started", 3), rec("G", "Completed", 3)
    got = _dashboard(monkeypatch, RECORDS + [soon_open, soon_done])
    assert got["compliance_overdue"] == 2
    assert got["compliance_due_week"] == 1, "F is open and due in three days; G is Completed"


def test_a_client_whose_filings_are_late_by_their_date_is_a_high_risk_client_and_one_whose_are_settled_is_not(monkeypatch):
    """Three late filings cost 60 and leave the score at 40, under 50. Under the old reading (the stored word, which nothing writes) the
    same client scored 100, so this is the figure that tells the two readings apart; a client with only settled, long-past filings is
    untouched."""
    late = [rec("L1", "Not Started", -30), rec("L2", "In Progress", -45), rec("L3", "Ready For Review", -20)]
    assert _dashboard(monkeypatch, late)["high_risk_clients"] == 1
    assert _dashboard(monkeypatch, [B, C])["high_risk_clients"] == 0


def test_the_risk_engine_raises_a_risk_for_a_late_obligation_by_its_date(monkeypatch):
    import domain.risk_engine as re_
    monkeypatch.setenv("SUPABASE_URL", "http://example.invalid")
    import repositories.compliance_records_repository as repo_module
    monkeypatch.setattr(repo_module, "compliance_records_repo", _Records(RECORDS))
    derived = re_._derive_compliance_risks(FIRM, CLIENT)
    assert sorted(d["id"] for d in derived) == ["risk-rec-A", "risk-rec-E"]


class _Insights:
    """An insights repository that remembers what it was given, like the real one: `find_all` returns what `create` wrote."""
    def __init__(self, existing=()):
        self.rows = list(existing)

    def find_all(self, firm_id=None, client_id=None, status=None, category=None):
        return [r for r in self.rows if r.get("client_id") == client_id]

    def create(self, row):
        self.rows.append(row)
        return row


def _generator(monkeypatch, records, existing=()):
    import domain.ai_insight_service as ai
    import repositories.ai_insights_repository as insights_module
    import repositories.client_repository as client_module
    store = _Insights(existing)
    monkeypatch.setattr(insights_module, "ai_insights_repo", store)
    monkeypatch.setattr(client_module, "client_repo", _Clients())
    _records_repo(monkeypatch, records)
    monkeypatch.setattr("domain.risk_engine.get_all_risks", lambda **kw: [])
    return ai, store


def test_the_insight_generator_raises_an_overdue_insight_for_a_late_obligation_by_its_date(monkeypatch):
    ai, store = _generator(monkeypatch, RECORDS)
    ai.generate_insights_for_client(CLIENT, firm_id=FIRM)
    titles = sorted(c["title"] for c in store.rows if c["title"].startswith("Overdue Filing"))
    assert titles == ["Overdue Filing: P-A", "Overdue Filing: P-E"]
    assert not any(c["title"].startswith("Deadline Approaching") for c in store.rows)
    assert {c["firm_id"] for c in store.rows} == {FIRM}, "every insight is written for the firm that asked"


def test_a_completed_obligation_due_in_three_days_raises_no_deadline_insight(monkeypatch):
    ai, store = _generator(monkeypatch, [rec("G", "Completed", 3), rec("F", "Not Started", 3)])
    ai.generate_insights_for_client(CLIENT, firm_id=FIRM)
    assert [c["title"] for c in store.rows if c["title"].startswith("Deadline Approaching")] == ["Deadline Approaching: P-F"]


def test_pressing_generate_twice_raises_nothing_the_second_time(monkeypatch):
    """With "overdue" read from the date a client with thirty late filings would have got thirty critical rows per press."""
    late = [rec(f"L{i}", "Not Started", -10 - i) for i in range(30)]
    ai, store = _generator(monkeypatch, late)
    first = ai.generate_insights_for_client(CLIENT, firm_id=FIRM)
    assert len([r for r in first if r["title"].startswith("Overdue Filing")]) == 30
    after_first = len(store.rows)
    assert ai.generate_insights_for_client(CLIENT, firm_id=FIRM) == []
    assert len(store.rows) == after_first, "the second press wrote rows the client already had"


def test_an_acknowledged_insight_is_not_raised_again_and_a_dismissed_one_is(monkeypatch):
    for status, raised_again in (("open", False), ("acknowledged", False), ("dismissed", True)):
        existing = [{"client_id": CLIENT, "title": "Overdue Filing: P-A", "status": status,
                     "description": "GST for P-A is overdue. Penalties may apply."}]
        ai, store = _generator(monkeypatch, [A], existing)
        got = ai.generate_insights_for_client(CLIENT, firm_id=FIRM)
        assert any(r["title"] == "Overdue Filing: P-A" for r in got) is raised_again, status


def test_two_obligations_of_one_period_are_two_insights_and_a_day_old_deadline_text_is_the_same_insight(monkeypatch):
    """The GSTR-1 and the TDS return of one month share a period label, so they share a title: the title alone cannot be the identity.
    And "due in 4 day(s)" yesterday is the same warning as "due in 3 day(s)" today."""
    two = [rec("G1", "Not Started", -10, compliance_type="GSTR1", period_label="April 2026"),
           rec("T1", "Not Started", -10, compliance_type="TDS", period_label="April 2026")]
    ai, store = _generator(monkeypatch, two)
    first = ai.generate_insights_for_client(CLIENT, firm_id=FIRM)
    assert sorted(r["description"][:4] for r in first if r["title"].startswith("Overdue Filing")) == ["GSTR", "TDS "]
    assert ai.generate_insights_for_client(CLIENT, firm_id=FIRM) == []
    yesterday = [{"client_id": CLIENT, "title": "Deadline Approaching: P-F", "status": "open",
                  "description": "GST due in 4 day(s). Current status: Not Started."}]
    ai, store = _generator(monkeypatch, [rec("F", "Not Started", 3, compliance_type="GST")], yesterday)
    assert not [r for r in ai.generate_insights_for_client(CLIENT, firm_id=FIRM) if r["title"].startswith("Deadline Approaching")]
    other_kind = [{**yesterday[0], "description": "TDS due in 4 day(s). Current status: Not Started."}]
    ai, store = _generator(monkeypatch, [rec("F", "Not Started", 3, compliance_type="GST")], other_kind)
    assert [r["title"] for r in ai.generate_insights_for_client(CLIENT, firm_id=FIRM)
            if r["title"].startswith("Deadline Approaching")] == ["Deadline Approaching: P-F"]


def test_the_same_obligation_twice_in_one_press_is_one_insight_and_a_different_insight_is_not_taken_for_it(monkeypatch):
    twice = [rec("A", "Not Started", -30), rec("A", "Not Started", -30)]
    ai, store = _generator(monkeypatch, twice)
    assert len([r for r in ai.generate_insights_for_client(CLIENT, firm_id=FIRM) if r["title"].startswith("Overdue Filing")]) == 1
    unrelated = [{"client_id": CLIENT, "title": "Something else", "status": "open",
                  "description": "GST for P-A is overdue. Penalties may apply."}]
    ai, store = _generator(monkeypatch, [A], unrelated)
    assert [r["title"] for r in ai.generate_insights_for_client(CLIENT, firm_id=FIRM)] == ["Overdue Filing: P-A"]


def test_another_clients_insight_does_not_stand_in_for_this_ones(monkeypatch):
    existing = [{"client_id": "other", "title": "Overdue Filing: P-A", "status": "open",
                 "description": "GST for P-A is overdue. Penalties may apply."}]
    ai, store = _generator(monkeypatch, [A], existing)
    assert [r["title"] for r in ai.generate_insights_for_client(CLIENT, firm_id=FIRM)] == ["Overdue Filing: P-A"]


def test_the_memory_profile_counts_the_missed_deadlines_by_date_and_names_a_type_that_repeats(monkeypatch):
    late = [rec("A1", "Not Started", -30, compliance_type="GST"), rec("A2", "In Progress", -60, compliance_type="GST"),
            rec("A3", "Not Started", -10, compliance_type="TDS"), rec("OK", "Filed", -90, compliance_type="GST"),
            rec("DONE", "Completed", -90, compliance_type="GST")]
    monkeypatch.setattr(memory, "_get_client_repo", lambda: type("C", (), {"find_by_id": lambda self, cid: {"id": cid}})())
    monkeypatch.setattr(memory, "_get_task_repo", lambda: type("T", (), {"find_all": lambda self, **kw: []})())
    monkeypatch.setattr(memory, "_get_compliance_records_repo", lambda: _Records(late))
    monkeypatch.setattr(memory, "_get_memory_repo", lambda: type("M", (), {"upsert_profile": lambda self, f, c, data: data})())
    profile = memory.MemoryPipeline().compute_client_profile(FIRM, CLIENT)
    assert profile["missed_deadline_count"] == 3
    assert profile["recurring_issues"] == [{"type": "GST", "count": 2, "issue": "Recurring GST delays"}]
    assert profile["compliance_score"] == max(0, round(100 - (3 / 5 * 50), 1))


def test_the_client_workspace_summary_counts_the_late_obligations_by_date(monkeypatch):
    import routers.clients as rc
    monkeypatch.setattr(rc, "client_repo", type("C", (), {"find_by_id": lambda self, cid, fid=None: {"id": cid, "firm_id": FIRM}})())
    monkeypatch.setattr(rc, "_assert_firm", lambda client, user: None)
    monkeypatch.setattr(rc, "assert_can_view_client", lambda client, user: None)
    monkeypatch.setattr(rc, "compliance_records_repo", _Records(RECORDS))
    empty = type("E", (), {"find_all": lambda self, **kw: []})()
    monkeypatch.setattr(rc, "document_repo", empty)
    monkeypatch.setattr(rc, "ai_insights_repo", empty)
    monkeypatch.setattr(rc, "task_repo", empty)
    monkeypatch.setattr(rc, "engagement_repo", empty, raising=False)
    monkeypatch.setattr(rc, "invoice_repo", empty, raising=False)
    out = rc.get_client_workspace(client_id=CLIENT, current_user={"id": "u", "firm_id": FIRM, "role": "Partner"})
    summary = out["data"]["summary"] if isinstance(out, dict) else json.loads(out.body)["data"]["summary"]
    assert summary["overdue_count"] == 2 and summary["pending_count"] == 2 and summary["filed_count"] == 4


# ── the compliance-risk engine, the dashboard cache and the last readers ─────────────

def test_the_compliance_risk_engine_counts_a_completed_obligation_as_settled_and_a_late_one_as_late(monkeypatch):
    """`compute_compliance_risk` carried its own settled words ("filed", "not_applicable"), so a Completed obligation with a past date
    counted as late and one due within the week as a predicted miss: the digest and the recommendations repeated it."""
    import repositories.client_repository as client_module
    import repositories.compliance_records_repository as repo_module
    import services.intelligence_service as intelligence
    rows = [rec("A", "Not Started", -30),                                   # late
            rec("C", "Completed", -30, filed_date=_iso(-31)),               # settled, on time
            rec("H", "Completed", -60, filed_date=_iso(-50)),               # settled, filed ten days after its date
            rec("S", "Completed", 3),                                       # settled, due inside the week
            rec("F", "Not Started", 3)]                                     # due inside the week and open
    monkeypatch.setattr(client_module, "client_repo", _Clients())
    monkeypatch.setattr(repo_module, "compliance_records_repo", _Records(rows))
    (client,) = intelligence.compute_compliance_risk(FIRM)["clients"]
    assert client["overdue_count"] == 1, "only A is late"
    assert client["due_soon_count"] == 1, "only F is open and due inside the week"
    assert client["late_filing_history"] == 1, "H was filed late; a Completed record counts as a filing"
    assert client["risk_score"] == 25 + 10 + 20
    assert [m["record_id"] for m in client["predicted_misses"]] == ["F"]


def test_a_dashboard_cached_before_the_overdue_rule_is_not_served():
    """The executive dashboard is cached for an hour; a row written by the old code carries `compliance_failures` 0 for every firm."""
    from domain.practice import executive_dashboard as ed
    assert ed.DASHBOARD_VERSION >= 3, "version 2 payloads carried the count of a status nothing writes"


def test_the_compliance_dashboard_counts_a_hand_set_overdue_and_says_which_queue_rows_are_late(monkeypatch):
    """The Practice → Compliance tile asked the date alone, so an obligation somebody moved to "Overdue" with a date ahead was open and
    late nowhere. And the queue it serves carried no answer of its own: the screen's Overdue filter compared the stored status, so it
    listed only those hand-set rows while the tile beside it said 220."""
    import services.compliance_obligation_service as cos
    agg = cos.aggregate_dashboard(RECORDS, TODAY)
    assert agg["summary"]["overdue"] == 2 and agg["summary"]["open_obligations"] == 3
    assert {s["key"]: s["overdue"] for s in agg["by_client"]} == {CLIENT: 2}
    monkeypatch.setattr(cos, "_records_for", lambda firm_id, client_id=None: list(RECORDS))
    monkeypatch.setattr(cos, "_dashboard_names", lambda *a, **k: ({}, {}))
    expected = {"A": True, "B": False, "C": False, "D": False, "E": True, "B2": False, "C2": False}
    assert {r["id"]: r["overdue"] for r in cos.dashboard(FIRM, TODAY)["queue"]} == expected
    assert {r["id"]: r["overdue"] for r in cos.dashboard(FIRM)["queue"]} == expected, "the route calls it without a day: the CA's day"


# ── the rule, over the whole backend ─────────────────────────────────────────────────

#: Places where the word "overdue" is the status of something that is NOT a `compliance_records` row, so the stored word is evidence
#: there. Named by (file, function) and not by file: the first version of this guard exempted three whole files, and one of them also
#: held a compliance reader with its own settled words. An entry that no longer matches anything fails, so the list cannot go stale.
OTHER_ENTITIES = {
    ("services/intelligence_service.py", "_relationship_rows"): "invoices: a job writes 'Overdue' onto an invoice",
    ("domain/portal_service.py", "compute_dues_summary"): "invoice dues",
    ("domain/memory_pipeline.py", "compute_client_profile"): "tasks (their lowercase vocabulary, not this table's)",
    ("repositories/compliance_repository.py", "find_overdue"): "System B compliance_tasks, retired; nothing calls it",
    ("services/risk_register_service.py", "build_register"): "loans",
}


def _is_the_word(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.lower() == "overdue"


def _holds_the_word(node) -> bool:
    if _is_the_word(node):
        return True
    return isinstance(node, (ast.Tuple, ast.List, ast.Set)) and any(_is_the_word(e) for e in node.elts)


def _asks_the_stored_word(tree: ast.AST, *, rel: str = "") -> list[tuple[str, int, str]]:
    """Every place a status is compared with, filtered on, or handed the word "overdue", in any case: a comparison (`==`, `in`),
    a `status=` keyword (how the old assistant helper asked the repository), a PostgREST `.eq("status", ...)` / `.in_("status", [...])`,
    and any use of `STORED_OVERDUE` outside the rule's own module. Returned as (enclosing function, line, text)."""
    found: list[tuple[str, int, str]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.stack: list[str] = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def add(self, node, text=None):
            found.append((self.stack[-1] if self.stack else "<module>", node.lineno, (text or ast.unparse(node))[:110]))

        def visit_Compare(self, node):
            if any(_holds_the_word(c) for c in [node.left, *node.comparators]) and "status" in ast.unparse(node).lower():
                self.add(node)
            self.generic_visit(node)

        def visit_keyword(self, node):
            if node.arg == "status" and _holds_the_word(node.value):
                self.add(node.value, f"status={ast.unparse(node.value)}")
            self.generic_visit(node)

        def visit_Call(self, node):
            for position, argument in enumerate(node.args[:-1]):
                if isinstance(argument, ast.Constant) and argument.value == "status" and _holds_the_word(node.args[position + 1]):
                    self.add(node)
            self.generic_visit(node)

        def visit_Name(self, node):
            if node.id == "STORED_OVERDUE" and not rel.endswith("domain/practice/compliance_overdue.py"):
                self.add(node)

        def visit_Attribute(self, node):
            if node.attr == "STORED_OVERDUE" and not rel.endswith("domain/practice/compliance_overdue.py"):
                self.add(node)
            self.generic_visit(node)

    Visitor().visit(tree)
    return found


#: Every literal "Overdue" in the backend's source (docstrings aside), by file, and what it is. A SECOND guard beside the structural scan
#: above, because that one holds only the spellings it knows (a comparison, a `status=` keyword, a PostgREST filter) and the original
#: defect had a spelling nobody listed. This one is spelling-independent: ANY new literal of the word, in any role (a comparison, a
#: constant a comparison reads, a dict, a `match` case, a lambda), fails until somebody has looked at it and added it here with what it
#: is. A literal that decides whether a compliance obligation is late does not belong here: it asks `domain/practice/compliance_overdue`.
#: What it cannot see, said plainly: a word built from pieces, a lowercase `overdue`, and anything in SQL.
LITERAL_INVENTORY = {
    "domain/compliance_record_service.py": (4, "the stored status vocabulary and VALID_TRANSITIONS: a transition somebody makes by hand"),
    "domain/hub/worklist.py": (1, "a column heading"),
    "domain/practice/compliance_overdue.py": (1, "STORED_OVERDUE, the rule's own word"),
    "mock_data.py": (2, "mock compliance records whose status was set by hand"),
    "routers/invoices.py": (1, "the invoice statuses, where a job writes it"),
    "routers/lifecycle.py": (1, "a legacy engagement status mapped to another"),
    "services/hub_service.py": (1, "the compliance_records CHECK vocabulary, for the outstanding count"),
    "services/intelligence_service.py": (3, "invoices (a job writes 'Overdue' onto an invoice)"),
    "services/invoice_lifecycle_service.py": (1, "the job that writes it onto an invoice"),
    "services/practice_mail_service.py": (3, "headings in a mail"),
}


def _literals_of_the_word(tree: ast.AST) -> int:
    documented = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                documented.add(id(body[0].value))
    return sum(1 for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value == "Overdue" and id(node) not in documented)


def _backend_sources():
    root = pathlib.Path(__file__).resolve().parents[1]
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", "migrations/", "scripts/", "venv/", ".venv/")) or "/__pycache__/" in rel:
            continue
        try:
            yield rel, ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue


def test_every_literal_overdue_in_the_backend_is_accounted_for():
    counts, scanned = {}, 0
    for rel, tree in _backend_sources():
        scanned += 1
        found = _literals_of_the_word(tree)
        if found:
            counts[rel] = found
    assert scanned > 700, f"the scan read {scanned} modules"
    expected = {rel: n for rel, (n, _why) in LITERAL_INVENTORY.items()}
    assert counts == expected, (
        "the literal 'Overdue' appears somewhere it was not reviewed. If it decides whether a compliance obligation is late, ask "
        "domain/practice/compliance_overdue instead; if it is a heading or another entity's status, add it to LITERAL_INVENTORY "
        f"with what it is.\n  found:    {dict(sorted(counts.items()))}\n  reviewed: {dict(sorted(expected.items()))}")


def test_the_inventory_counts_a_literal_in_any_role_and_leaves_a_docstring_alone():
    for source in ('WORD = "Overdue"', 'x = {"Overdue": 1}', 'lambda s: s == "Overdue"', 'match s:\n    case "Overdue": pass',
                   'counts.get("Overdue")', 'LATE = ("Filed", "Overdue")'):
        assert _literals_of_the_word(ast.parse(source)) == 1, source
    assert _literals_of_the_word(ast.parse('"""A status of Overdue is set by hand."""\nx = 1\ndef f():\n    "Overdue"\n')) == 0
    assert _literals_of_the_word(ast.parse('x = "overdue"')) == 0, "the lowercase word is another entity's (tasks, loans) and is not counted"


def _backend_findings() -> tuple[int, dict[tuple[str, str], list[str]]]:
    root = pathlib.Path(__file__).resolve().parents[1]
    scanned = 0
    where: dict[tuple[str, str], list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", "migrations/", "scripts/", "venv/", ".venv/")) or rel == "mock_data.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        scanned += 1
        for function, line, text in _asks_the_stored_word(tree, rel=rel):
            where.setdefault((rel, function), []).append(f"{rel}:{line}: {text}")
    return scanned, where


def test_no_backend_module_asks_the_stored_word_overdue_of_a_compliance_record():
    """The rule, not the spelling of the sites that had it: any comparison, keyword or PostgREST filter that hands a status the word
    "overdue" (in any case) in `apps/api`, outside the named places that are about another entity, fails. Compliance obligations go
    through `domain/practice/compliance_overdue`. What this CANNOT see, said plainly: a status read into a variable first, a word
    built from pieces, SQL, and a reader that derives lateness from the date with its own settled words (that is the other half of
    the rule, held by the reader tests above, which put Completed and a hand-set Overdue through each one)."""
    scanned, where = _backend_findings()
    assert scanned > 400, f"the scan read {scanned} modules"
    offenders = [line for key, lines in where.items() if key not in OTHER_ENTITIES for line in lines]
    assert not offenders, "a status is compared with, filtered on or handed the word 'overdue':\n" + "\n".join(offenders)
    stale = sorted(set(OTHER_ENTITIES) - set(where))
    assert not stale, f"these named places no longer ask for the word, so remove them from OTHER_ENTITIES: {stale}"


def test_the_scan_would_catch_a_reader_that_asks_the_word():
    for source in ('r.get("status") == "Overdue"', 'r["status"] == "Overdue"', 'status in ("Filed", "Overdue")',
                   '"Overdue" == t.get("status")', 'x.status != "Overdue"', 'r.get("status") == "overdue"',
                   'status in ("overdue",)', 'repo.find_all(firm_id=f, status="Overdue")',
                   'db.table("compliance_records").eq("status", "Overdue")',
                   'db.table("compliance_records").in_("status", ["Overdue", "x"])',
                   'r["status"] == co.STORED_OVERDUE', 'status == STORED_OVERDUE'):
        assert _asks_the_stored_word(ast.parse(source)), source
    for source in ('r.get("status") == "Filed"', 'invoice_kind == "Overdue"', 'repo.find_all(firm_id=f, status="Filed")',
                   'db.table("t").eq("status", "Filed")', 'x = {"label": "Overdue"}'):
        assert not _asks_the_stored_word(ast.parse(source)), source
    assert not _asks_the_stored_word(ast.parse("STORED_OVERDUE = 'Overdue'"), rel="domain/practice/compliance_overdue.py")
