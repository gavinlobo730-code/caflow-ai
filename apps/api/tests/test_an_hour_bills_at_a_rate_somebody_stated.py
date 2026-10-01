"""practice_management-11 — recorded time says which engagement it belongs to and
what an hour of it bills at, and unbilled work says which time has NO rate.

WHAT WAS WRONG
    The timer's body had no engagement and no rate, the Time screen sent only the
    client, and nothing gave a staff member a billing rate at all. So
    `billable_rate_paise` was NULL on every timer-started row, and the one place
    that totalled unbilled work read a NULL rate as ZERO — "this work is worth
    nothing", for what is really "nobody said what it is worth".

WHAT IS ASSERTED
    * the rate is the entry's own, then the engagement's, then the person's, then
      NOTHING; a stated 0 is a rate and an absent one is not;
    * a timer started for a client with ONE active engagement stores that
      engagement and the resolved rate on the row; with SEVERAL none is chosen
      for you and the answer says why; an engagement that is not the client's is
      refused before anything is written; non-billable work carries no rate;
    * stopping re-resolves a rate that is STILL missing and never replaces one the
      entry already carries;
    * the unbilled-work value is exactly minutes x rate / 60 summed over entries,
      and an entry with no rate is LISTED as such and adds nothing to it;
    * both rates are set by the right role, validated as whole non-negative paise,
      and clearable.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.billing as billing_router
import routers.engagements as engagements_router
import routers.time_tracking as tt
import services.billing_service as billing
import services.time_rates_service as rates
from core.auth import get_current_user
from domain.billing import time_rate as rule

FIRM, OTHER_FIRM = "firm-time-1", "firm-time-2"
CLIENT, OTHER_CLIENT = "client-time-1", "client-time-2"
USER_ID = "u-prep"
PARTNER = {"id": "u-ptr", "firm_id": FIRM, "role": "Partner", "email": "p@f.in"}
PREPARER = {"id": USER_ID, "firm_id": FIRM, "role": "Executive", "email": "e@f.in"}


# ══════════════════════════════════════════════════════════════════════════════
# the rule
# ══════════════════════════════════════════════════════════════════════════════

def test_the_entrys_own_rate_wins_then_the_engagement_then_the_person_then_nothing():
    r = rule.resolve_rate(entry_rate_paise=300000, engagement_rate_paise=200000, user_rate_paise=100000)
    assert (r.rate_paise, r.source) == (300000, "entry")
    r = rule.resolve_rate(engagement_rate_paise=200000, user_rate_paise=100000)
    assert (r.rate_paise, r.source) == (200000, "engagement")
    r = rule.resolve_rate(user_rate_paise=100000)
    assert (r.rate_paise, r.source) == (100000, "user")
    r = rule.resolve_rate()
    assert (r.rate_paise, r.source, r.has_rate) == (None, None, False)


def test_a_stated_zero_is_a_rate_and_an_absent_one_is_not():
    """`if rate:` is how the code this replaces confused them: a retainer's hours
    bill at nothing BY DECISION, which is not the same as nobody having decided."""
    r = rule.resolve_rate(engagement_rate_paise=0, user_rate_paise=100000)
    assert (r.rate_paise, r.source) == (0, "engagement"), "a stated zero is honoured, not skipped"
    assert rule.resolve_rate(engagement_rate_paise=None, user_rate_paise=100000).rate_paise == 100000


@pytest.mark.parametrize("junk", [-1, 1.5, "12.5", "1e3", "abc", True, False, [], {}])
def test_a_value_that_is_not_whole_non_negative_paise_is_not_a_rate(junk):
    assert rule.resolve_rate(user_rate_paise=junk).rate_paise is None


def test_a_bigint_that_came_back_as_text_is_read():
    assert rule.resolve_rate(user_rate_paise="250000").rate_paise == 250000


def test_value_is_minutes_times_rate_over_sixty_floored_and_none_without_a_rate():
    assert rule.value_paise(60, 100000) == 100000
    assert rule.value_paise(90, 100000) == 150000
    assert rule.value_paise(50, 100000) == 83333, "floored, never rounded up"
    assert rule.value_paise(60, None) is None, "no rate is not zero"
    assert rule.value_paise(60, 0) == 0, "a stated zero is"


def test_the_default_engagement_is_the_single_active_one():
    rows = [{"id": "e1", "status": "Active"}, {"id": "e2", "status": "Closed"},
            {"id": "e3", "status": "Draft"}]
    choice = rule.default_engagement(rows)
    assert choice.engagement_id == "e1" and choice.reason is None


def test_several_active_engagements_are_never_resolved_by_taking_the_first():
    rows = [{"id": "e1", "status": "Active"}, {"id": "e2", "status": "In Progress"}]
    choice = rule.default_engagement(rows)
    assert choice.engagement_id is None
    assert "2 active engagements" in choice.reason and len(choice.active) == 2


def test_no_active_engagement_is_a_reason_not_a_guess():
    choice = rule.default_engagement([{"id": "e1", "status": "Closed"}])
    assert choice.engagement_id is None and "no active engagement" in choice.reason


def test_the_active_set_is_the_one_the_obligation_generator_uses():
    from services import compliance_obligation_service as ob
    assert tuple(ob._ACTIVE_ENGAGEMENT_STATUSES) == rule.ACTIVE_ENGAGEMENT_STATUSES


# ── the unbilled total ───────────────────────────────────────────────────────

def _entry(minutes, billable=None, hourly=None, client="C1", task="T1", **kw):
    return {"id": f"e{minutes}-{billable}-{hourly}", "client_id": client, "task_id": task,
            "duration_minutes": minutes, "is_billable": True, "billed_invoice_id": None,
            "billable_rate_paise": billable, "hourly_rate_paise": hourly, "user_id": "u1", **kw}


def test_the_unbilled_value_is_minutes_times_rate_over_sixty_summed_across_users():
    entries = [_entry(60, 100000, user_id="a") | {"user_id": "a", "id": "1"},
               _entry(90, 200000) | {"user_id": "b", "id": "2"},
               _entry(50, None, 120000) | {"user_id": "c", "id": "3"}]   # the legacy fallback
    g = billing.group_unbilled(entries)
    expected = (60 * 100000) // 60 + (90 * 200000) // 60 + (50 * 120000) // 60
    assert g["total_value_paise"] == expected == 100000 + 300000 + 100000
    assert g["total_minutes"] == 200 and g["no_rate"]["count"] == 0


def test_an_entry_with_no_rate_is_listed_as_no_rate_and_adds_nothing():
    entries = [_entry(60, 100000) | {"id": "priced"},
               _entry(120) | {"id": "unrated", "description": "Audit fieldwork"}]
    g = billing.group_unbilled(entries)
    assert g["total_value_paise"] == 100000, "the unrated two hours are NOT counted as zero rupees"
    assert g["priced_minutes"] == 60 and g["total_minutes"] == 180
    nr = g["no_rate"]
    assert nr["count"] == 1 and nr["minutes"] == 120
    assert [e["id"] for e in nr["entries"]] == ["unrated"]
    assert nr["entries"][0]["description"] == "Audit fieldwork"
    assert nr["by_client"] == {"C1": {"minutes": 120, "count": 1}}
    assert g["by_client"]["C1"] == {"minutes": 60, "value_paise": 100000, "count": 1}, (
        "the priced slot keeps the shape it always had")


def test_a_stated_zero_rate_is_priced_at_nothing_and_is_not_on_the_no_rate_list():
    g = billing.group_unbilled([_entry(60, 0)])
    assert g["no_rate"]["count"] == 0 and g["total_value_paise"] == 0
    assert g["by_client"]["C1"]["count"] == 1


def test_billed_non_billable_and_zero_minute_entries_are_not_unbilled_work():
    g = billing.group_unbilled([
        _entry(60, 100000) | {"billed_invoice_id": "INV1"},
        _entry(60, 100000) | {"is_billable": False},
        _entry(0, 100000)])
    assert g["total_minutes"] == 0 and g["no_rate"]["count"] == 0


def test_the_no_rate_list_is_bounded_and_the_count_is_not():
    many = [_entry(10) | {"id": f"x{i}"} for i in range(rule.NO_RATE_LIST_LIMIT + 25)]
    g = billing.group_unbilled(many)
    assert g["no_rate"]["count"] == rule.NO_RATE_LIST_LIMIT + 25
    assert len(g["no_rate"]["entries"]) == rule.NO_RATE_LIST_LIMIT


def test_the_database_path_reads_the_aggregate_and_lists_the_unrated(monkeypatch):
    """`unbilled_work` asks the SQL function for the totals — never `select("*")`
    over every unbilled entry — and fetches only the bounded list of unrated rows."""
    calls = {"rpc": [], "select": []}

    class _Q:
        def __init__(self, table): self.table = table
        def select(self, expr): calls["select"].append((self.table, expr)); return self
        def eq(self, *a): return self
        def is_(self, *a): return self
        def gt(self, *a): return self
        def order(self, *a, **k): return self
        def limit(self, n): calls["limit"] = n; return self
        def in_(self, *a): return self
        def execute(self):
            class R: pass
            r = R()
            r.data = ([{"id": "x1", "user_id": "u1", "client_id": "C1", "task_id": None,
                        "description": "d", "started_at": "2026-10-01T00:00:00Z",
                        "duration_minutes": 30, "engagement_id": None}]
                      if self.table == "time_entries" else
                      [{"id": "u1", "full_name": "Priya", "email": "p@f.in"}])
            return r

    class _Rpc:
        def __init__(self, fn, params): calls["rpc"].append((fn, params))
        def execute(self):
            class R: pass
            r = R()
            r.data = [{"client_id": "C1", "task_id": "T1", "priced": True, "minutes": 60,
                       "value_paise": 100000, "entries": 1},
                      {"client_id": "C1", "task_id": None, "priced": False, "minutes": 30,
                       "value_paise": 0, "entries": 1}]
            return r

    class _DB:
        def rpc(self, fn, params): return _Rpc(fn, params)
        def table(self, name): return _Q(name)

    monkeypatch.setattr(billing, "_USE_MOCK", False)
    monkeypatch.setattr(billing, "_db", lambda: _DB())
    monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: _DB())
    out = billing.unbilled_work(FIRM)
    assert calls["rpc"] == [("unbilled_time_summary", {"p_firm_id": FIRM})]
    assert out["total_value_paise"] == 100000
    assert out["no_rate"]["count"] == 1 and out["no_rate"]["minutes"] == 30
    assert out["no_rate"]["entries"][0]["user_name"] == "Priya"
    assert all(expr != "*" for _, expr in calls["select"]), "never select * over unbilled time"
    assert calls["limit"] == rule.NO_RATE_LIST_LIMIT


# ══════════════════════════════════════════════════════════════════════════════
# the timer and the manual entry, through the real router
# ══════════════════════════════════════════════════════════════════════════════

class _Repo:
    """time_tracking_repo, in memory."""
    def __init__(self): self.rows: list[dict] = []
    def find_running(self, firm_id, user_id): return None
    def create(self, data):
        row = {**data, "id": f"te{len(self.rows) + 1}"}
        self.rows.append(row)
        return row
    def find_by_id(self, id, firm_id=None): return next((r for r in self.rows if r["id"] == id), None)
    def update(self, id, data, firm_id=None):
        row = self.find_by_id(id)
        row.update(data)
        return row
    def find_all(self, **k): return list(self.rows)


@pytest.fixture
def world(monkeypatch):
    rates.reset_mock_stores()
    repo = _Repo()
    monkeypatch.setattr(tt, "time_tracking_repo", repo)
    monkeypatch.setattr("routers.time_tracking._now", lambda: "2026-10-01T10:00:00+00:00")
    rates.MOCK_USER_RATES[USER_ID] = 200000
    rates.MOCK_ENGAGEMENTS.extend([
        {"id": "eng-1", "firm_id": FIRM, "client_id": CLIENT, "service_type": "GST Filing",
         "status": "Active", "billable_rate_paise": None},
        {"id": "eng-other", "firm_id": FIRM, "client_id": OTHER_CLIENT, "service_type": "Audit",
         "status": "Active", "billable_rate_paise": 900000}])
    yield repo
    rates.reset_mock_stores()


def _client(user=PREPARER, *routers):
    app = FastAPI()
    for r in routers or (tt,):
        app.include_router(r.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def test_a_timer_for_a_client_with_one_active_engagement_stores_the_engagement_and_a_rate(world):
    res = _client().post("/api/time-entries/start", json={"client_id": CLIENT, "description": "GSTR-3B"})
    assert res.status_code == 200, res.text
    row = world.rows[0]
    assert row["engagement_id"] == "eng-1", "the client's single active engagement is the default"
    assert row["billable_rate_paise"] == 200000, "no override, so the person's default"
    assert res.json()["data"]["rate"] == {"source": "user", "notes": []}


def test_the_engagements_override_beats_the_persons_default(world):
    rates.MOCK_ENGAGEMENTS[0]["billable_rate_paise"] = 350000
    _client().post("/api/time-entries/start", json={"client_id": CLIENT})
    assert world.rows[0]["billable_rate_paise"] == 350000


def test_a_stated_zero_override_makes_the_engagements_hours_bill_at_nothing(world):
    rates.MOCK_ENGAGEMENTS[0]["billable_rate_paise"] = 0
    _client().post("/api/time-entries/start", json={"client_id": CLIENT})
    assert world.rows[0]["billable_rate_paise"] == 0


def test_two_active_engagements_choose_none_and_the_answer_says_why(world):
    rates.MOCK_ENGAGEMENTS.append({"id": "eng-2", "firm_id": FIRM, "client_id": CLIENT,
                                   "service_type": "ITR", "status": "In Progress",
                                   "billable_rate_paise": 500000})
    res = _client().post("/api/time-entries/start", json={"client_id": CLIENT})
    row = world.rows[0]
    assert row["engagement_id"] is None, "which one an hour belongs to is a fact about the work"
    assert row["billable_rate_paise"] == 200000, "the person's rate; no override was chosen"
    assert "2 active engagements" in res.json()["data"]["rate"]["notes"][0]


def test_a_named_engagement_is_used_and_prices_the_hour(world):
    rates.MOCK_ENGAGEMENTS.append({"id": "eng-2", "firm_id": FIRM, "client_id": CLIENT,
                                   "service_type": "ITR", "status": "In Progress",
                                   "billable_rate_paise": 500000})
    _client().post("/api/time-entries/start", json={"client_id": CLIENT, "engagement_id": "eng-2"})
    assert world.rows[0]["engagement_id"] == "eng-2"
    assert world.rows[0]["billable_rate_paise"] == 500000


def test_an_engagement_that_is_not_the_clients_is_refused_before_anything_is_written(world):
    res = _client().post("/api/time-entries/start",
                         json={"client_id": CLIENT, "engagement_id": "eng-other"})
    assert res.status_code == 422 and "not one of this client's" in res.json()["detail"]
    assert world.rows == [], "pricing an hour under another client's override is a wrong invoice with no error"


def test_an_engagement_with_no_client_is_refused(world):
    res = _client().post("/api/time-entries/start", json={"engagement_id": "eng-1"})
    assert res.status_code == 422


def test_non_billable_time_carries_no_rate(world):
    _client().post("/api/time-entries/start", json={"client_id": CLIENT, "is_billable": False})
    assert world.rows[0]["billable_rate_paise"] is None
    assert world.rows[0]["engagement_id"] == "eng-1", "the engagement is still recorded"


def test_with_no_rate_anywhere_the_row_says_none_and_the_answer_says_it_will_be_listed_as_no_rate(world):
    rates.MOCK_USER_RATES.clear()
    res = _client().post("/api/time-entries/start", json={"client_id": CLIENT})
    assert world.rows[0]["billable_rate_paise"] is None
    assert "no rate" in res.json()["data"]["rate"]["notes"][-1]


def test_stopping_looks_again_for_a_rate_that_is_still_missing(world):
    rates.MOCK_USER_RATES.clear()
    c = _client()
    c.post("/api/time-entries/start", json={"client_id": CLIENT})
    assert world.rows[0]["billable_rate_paise"] is None
    rates.MOCK_USER_RATES[USER_ID] = 150000          # a partner records it while the timer runs
    world.rows[0]["user_id"] = USER_ID
    res = c.post("/api/time-entries/te1/stop")
    assert res.status_code == 200, res.text
    assert world.rows[0]["billable_rate_paise"] == 150000
    assert world.rows[0]["ended_at"]


def test_stopping_never_replaces_a_rate_the_entry_already_carries(world):
    c = _client()
    c.post("/api/time-entries/start", json={"client_id": CLIENT})
    assert world.rows[0]["billable_rate_paise"] == 200000
    rates.MOCK_USER_RATES[USER_ID] = 999999          # the rate changes while the timer runs
    world.rows[0]["user_id"] = USER_ID
    c.post("/api/time-entries/te1/stop")
    assert world.rows[0]["billable_rate_paise"] == 200000, (
        "the price the work was started at is the price; re-pricing logged work is what "
        "storing the rate on the row exists to prevent")


def test_a_manual_entry_with_a_typed_rate_uses_it(world):
    _client().post("/api/time-entries", json={
        "client_id": CLIENT, "started_at": "2026-10-01T09:00:00+00:00",
        "ended_at": "2026-10-01T10:00:00+00:00", "billable_rate_paise": 420000})
    assert world.rows[0]["billable_rate_paise"] == 420000


def test_the_screens_rate_box_posts_hourly_rate_and_that_is_the_entrys_own_rate(world):
    _client().post("/api/time-entries", json={
        "client_id": CLIENT, "started_at": "2026-10-01T09:00:00+00:00",
        "ended_at": "2026-10-01T10:00:00+00:00", "hourly_rate_paise": 330000})
    row = world.rows[0]
    assert row["billable_rate_paise"] == 330000
    assert row["hourly_rate_paise"] == 330000, "still stored where the analytics read it"


def test_a_manual_entry_with_no_typed_rate_resolves_one(world):
    _client().post("/api/time-entries", json={
        "client_id": CLIENT, "started_at": "2026-10-01T09:00:00+00:00",
        "ended_at": "2026-10-01T10:00:00+00:00"})
    assert world.rows[0]["billable_rate_paise"] == 200000
    assert world.rows[0]["engagement_id"] == "eng-1"


def test_the_entries_list_says_no_rate_rather_than_zero(world):
    world.rows.extend([
        {"id": "a", "firm_id": FIRM, "client_id": CLIENT, "is_billable": True, "ended_at": "x",
         "duration_minutes": 90, "billable_rate_paise": 100000, "hourly_rate_paise": None},
        {"id": "b", "firm_id": FIRM, "client_id": CLIENT, "is_billable": True, "ended_at": "x",
         "duration_minutes": 90, "billable_rate_paise": None, "hourly_rate_paise": None},
        {"id": "c", "firm_id": FIRM, "client_id": CLIENT, "is_billable": False, "ended_at": "x",
         "duration_minutes": 90, "billable_rate_paise": None, "hourly_rate_paise": None}])
    got = {e["id"]: e for e in _client().get("/api/time-entries").json()["data"]["entries"]}
    assert got["a"]["value_paise"] == 150000 and got["a"]["rate_paise"] == 100000
    assert got["b"]["value_paise"] is None and got["b"]["rate_paise"] is None, "not 0"
    assert got["c"]["value_paise"] is None, "non-billable time has no value"


def test_the_engagement_picker_is_served_without_the_fee_economics(world):
    rates.MOCK_ENGAGEMENTS[0]["billable_rate_paise"] = 350000
    data = _client().get(f"/api/time-entries/engagement-choices?client_id={CLIENT}").json()["data"]
    assert data["default_engagement_id"] == "eng-1"
    assert [e["id"] for e in data["engagements"]] == ["eng-1"]
    assert "billable_rate_paise" not in data["engagements"][0], (
        "the override is fee economics (billing:write); a person picking an engagement "
        "does not need it")


# ══════════════════════════════════════════════════════════════════════════════
# setting the two rates
# ══════════════════════════════════════════════════════════════════════════════

def test_a_partner_sets_and_clears_a_persons_default_rate(world):
    c = _client(PARTNER, billing_router)
    assert c.put(f"/api/billing/staff-billable-rates/{USER_ID}",
                 json={"default_billable_rate_paise": 275000}).status_code == 200
    assert rates.MOCK_USER_RATES[USER_ID] == 275000
    assert c.put(f"/api/billing/staff-billable-rates/{USER_ID}",
                 json={"default_billable_rate_paise": None}).status_code == 200
    assert rates.MOCK_USER_RATES[USER_ID] is None, "NULL clears it; it is not stored as 0"


@pytest.mark.parametrize("bad", [-5, 12.5])
def test_a_rate_is_whole_non_negative_paise(world, bad):
    """Refused, and nothing is stored. A NEGATIVE rate is the service's refusal and
    says why; a FRACTION never reaches the service, because the body's own type
    (`Optional[int]`) refuses it first with the framework's 422 — either way the
    rate the person typed is not stored as something else."""
    res = _client(PARTNER, billing_router).put(
        f"/api/billing/staff-billable-rates/{USER_ID}", json={"default_billable_rate_paise": bad})
    assert res.status_code == 422
    if bad < 0:
        assert "whole number of paise" in res.json()["detail"]
    assert rates.MOCK_USER_RATES[USER_ID] == 200000, "a refused rate must change nothing"


def test_only_a_partner_may_set_what_an_hour_bills_at(world):
    res = _client(PREPARER, billing_router).put(
        f"/api/billing/staff-billable-rates/{USER_ID}", json={"default_billable_rate_paise": 1})
    assert res.status_code == 403
    assert _client(PREPARER, billing_router).get("/api/billing/staff-billable-rates").status_code == 403


def test_a_partner_sets_and_clears_an_engagement_override(world, monkeypatch):
    monkeypatch.setattr(engagements_router.engagement_repo, "find_by_id",
                        lambda eid: next((e for e in rates.MOCK_ENGAGEMENTS if e["id"] == eid), None))
    c = _client(PARTNER, engagements_router)
    assert c.put("/api/engagements/eng-1/billable-rate", json={"billable_rate_paise": 450000}).status_code == 200
    assert rates.MOCK_ENGAGEMENTS[0]["billable_rate_paise"] == 450000
    assert c.put("/api/engagements/eng-1/billable-rate", json={"billable_rate_paise": None}).status_code == 200
    assert rates.MOCK_ENGAGEMENTS[0]["billable_rate_paise"] is None, (
        "its own door, because PATCH drops every null and an override set once could never come off")


def test_another_firms_engagement_cannot_be_priced(world, monkeypatch):
    monkeypatch.setattr(engagements_router.engagement_repo, "find_by_id",
                        lambda eid: {"id": eid, "firm_id": OTHER_FIRM, "client_id": CLIENT})
    res = _client(PARTNER, engagements_router).put(
        "/api/engagements/x/billable-rate", json={"billable_rate_paise": 1})
    assert res.status_code == 404


def test_no_computation_reads_the_cost_rate():
    """What an hour costs the firm is not what it bills — `cost_rate_paise` is
    capture-only and must stay that way."""
    import inspect
    for mod in (rule, rates):
        assert "cost_rate" not in inspect.getsource(mod).replace("cost_rate_paise` is", "")\
            .replace("cost_rate_paise`, which", "").replace("`cost_rate_paise`", "")\
            .replace("cost_rate_paise", "")  # mentions in prose are fine; a read is `cost_rate` + more


# ── a rate set on an entry (how a "no rate" hour gets one) ───────────────────

def _unpriced(world, **kw):
    row = {"id": "te-fix", "firm_id": FIRM, "user_id": USER_ID, "client_id": CLIENT,
           "is_billable": True, "duration_minutes": 60, "billable_rate_paise": None,
           "hourly_rate_paise": None, "billed_invoice_id": None, **kw}
    world.rows.append(row)
    return row


def test_a_rate_set_on_an_unpriced_entry_is_stored(world):
    row = _unpriced(world)
    res = _client(PARTNER).patch("/api/time-entries/te-fix", json={"billable_rate_paise": 123400})
    assert res.status_code == 200, res.text
    assert row["billable_rate_paise"] == 123400


@pytest.mark.parametrize("field", ["billable_rate_paise", "hourly_rate_paise"])
def test_a_negative_rate_on_an_entry_is_refused_and_stores_nothing(world, field):
    """`time_entries` carries no CHECK on either rate column, so this is the only
    thing between a typo and a negative figure in an unbilled-work total."""
    row = _unpriced(world)
    res = _client(PARTNER).patch("/api/time-entries/te-fix", json={field: -100})
    assert res.status_code == 422 and "whole number of paise" in res.json()["detail"]
    assert row["billable_rate_paise"] is None and row["hourly_rate_paise"] is None


@pytest.mark.parametrize("field", ["billable_rate_paise", "hourly_rate_paise"])
def test_the_rate_of_time_already_on_an_invoice_cannot_be_changed(world, field):
    row = _unpriced(world, billed_invoice_id="inv-1", billable_rate_paise=100000)
    res = _client(PARTNER).patch("/api/time-entries/te-fix", json={field: 999999})
    assert res.status_code == 409 and "already on an invoice" in res.json()["detail"]
    assert row["billable_rate_paise"] == 100000


def test_other_fields_of_billed_time_are_not_made_stricter_by_this(world):
    """The refusal is about the RATE: a description can still be corrected."""
    row = _unpriced(world, billed_invoice_id="inv-1")
    res = _client(PARTNER).patch("/api/time-entries/te-fix", json={"description": "fixed typo"})
    assert res.status_code == 200 and row["description"] == "fixed typo"
