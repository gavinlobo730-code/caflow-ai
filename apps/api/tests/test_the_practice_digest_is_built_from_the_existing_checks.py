"""The practice digest is built from the existing checks, and a model only words it (ai-25).

THE THREE CLAIMS THE ITEM MAKES, AND WHERE EACH IS HELD
    1. A scoped CA's digest names ONLY their clients — `test_a_scoped_callers_digest_*`
       asserts it by what the whole serialised answer CONTAINS and by what the
       model's prompt contains, not by reading source.
    2. Every count equals the count the underlying report returns —
       `test_every_count_is_what_its_engine_reports` asks each engine
       independently (the real compliance-risk engine, the overdue-task read, and
       the stored findings read by a code path that shares nothing with the
       service) and compares.
    3. With the model down the digest still appears, as plain text — the
       provider-failed, no-key and discarded-reply cases below.

THE ENGINES ARE REAL
    `compute_compliance_risk` runs for real against stand-in repositories, so a
    change to the engine's rule moves these tests; the digest is not compared with
    a copy of itself.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import authz
from core.ist_clock import ist_today
from domain.ai import groq_text
from domain.practice import digest as dg
from middleware import rate_limit
from services import digest_service as svc
from tests.e2e_harness import FakeDB

FIRM, OTHER_FIRM = "f1111111-1111-4111-8111-111111111111", "f2222222-2222-4222-8222-222222222222"
MINE_A, MINE_B = "c1111111-1111-4111-8111-111111111111", "c2222222-2222-4222-8222-222222222222"
THEIRS = "c9999999-9999-4999-8999-999999999999"
NAMES = {MINE_A: "Alpha Traders Pvt Ltd", MINE_B: "Bravo Exports LLP",
         THEIRS: "ZZ Secret Holdings"}

PARTNER = {"id": "u-partner", "auth_user_id": "a-1", "firm_id": FIRM,
           "email": "p@f.test", "role": "Partner"}
MANAGER = {"id": "u-mgr", "auth_user_id": "a-2", "firm_id": FIRM,
           "email": "m@f.test", "role": "Manager"}

TODAY = ist_today()


def _d(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _rec(client, offset, status="pending", ctype="GSTR-3B"):
    return {"id": f"r-{client[:2]}-{offset}-{ctype}", "client_id": client,
            "status": status, "due_date": _d(offset), "compliance_type": ctype}


def _task(client, owner=None, offset=-2):
    return {"id": f"t-{client}-{owner}-{offset}", "client_id": client, "assignee_id": owner,
            "status": "open", "due_date": _d(offset)}


# ── fixtures: real engines over stand-in repositories ────────────────────────

@pytest.fixture()
def world(monkeypatch):
    """One firm, three clients (two the Manager is assigned to), real engines."""
    import core.supabase_client as sc
    import repositories.client_repository as cr
    import repositories.compliance_records_repository as rr
    import repositories.task_repository as tr

    rate_limit.reset()
    svc.reset_narration_cache()
    state = {
        "clients": [{"id": cid, "client_name": n} for cid, n in NAMES.items()],
        "records": [
            _rec(MINE_A, -3), _rec(MINE_A, -10, ctype="TDS_NON_SALARY_DEPOSIT"),
            _rec(MINE_A, 3), _rec(MINE_B, 5), _rec(MINE_B, 20),
            _rec(MINE_B, -4, status="filed"),
            _rec(THEIRS, -1), _rec(THEIRS, -2), _rec(THEIRS, 2),
        ],
        "tasks": [_task(MINE_A, "u-mgr"), _task(MINE_A, None), _task(MINE_B, "u-other"),
                  _task(THEIRS, "u-other"), _task(None, "u-mgr")],
        "db": FakeDB(),
    }
    monkeypatch.setattr(cr.client_repo, "find_all", lambda **kw: state["clients"])
    monkeypatch.setattr(rr.compliance_records_repo, "find_all", lambda **kw: state["records"])
    monkeypatch.setattr(tr.task_repo, "find_overdue", lambda **kw: state["tasks"])
    monkeypatch.setattr(sc, "get_service_supabase", lambda: state["db"])
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    return state


@pytest.fixture()
def scoped_to_mine():
    """What `effective_client_ids` answers for a caller assigned to two clients.
    The ROUTE resolves it and hands it to the service, so the service tests pass
    it in; the route test below patches the resolver itself."""
    return {MINE_A, MINE_B}


class Model:
    """A stand-in for `groq_text.chat` that records what it was sent."""

    def __init__(self, reply="Alpha has trouble.", fail=None):
        self.reply, self.fail, self.calls = reply, fail, []

    async def __call__(self, messages, **kw):
        self.calls.append(messages)
        if self.fail:
            raise self.fail
        return self.reply, 5


@pytest.fixture()
def model(monkeypatch):
    m = Model()
    monkeypatch.setattr(groq_text, "chat", m)
    return m


def _seed_runs(db, *, client, started, status="completed", firm=FIRM, findings=()):
    run = db.seed("reconciliation_runs", {
        "firm_id": firm, "client_id": client, "status": status, "started_at": started})
    for severity, resolved in findings:
        db.seed("reconciliation_findings", {
            "firm_id": firm, "client_id": client, "run_id": run["id"],
            "severity": severity, "check_name": "x", "resolved_at": resolved})
    return run


def _hours_ago(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def _items(out):
    return {i["key"]: i for i in out["items"]}


async def _digest(user, allowed=None, **kw):
    return await svc.todays_digest(user, allowed, today=TODAY, **kw)


def run(coro):
    import asyncio
    return asyncio.run(coro)


# ── claim 2: every count is the engine's ─────────────────────────────────────

def test_every_count_is_what_its_engine_reports(world, model):
    from services.intelligence_service import compute_compliance_risk
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(5), findings=[
        ("critical", None), ("warning", None), ("warning", "2026-09-01T00:00:00Z")])
    _seed_runs(db, client=MINE_B, started=_hours_ago(5), findings=[("critical", None)])
    _seed_runs(db, client=THEIRS, started=_hours_ago(5), findings=[("warning", None)] * 2)

    out = run(_digest(PARTNER))
    items = _items(out)

    # The engine, asked on its own.
    engine = compute_compliance_risk(FIRM, None)["clients"]
    assert items["filings_overdue"]["count"] == sum(c["overdue_count"] for c in engine)
    assert items["filings_due_soon"]["count"] == sum(c["due_soon_count"] for c in engine)
    # By hand, so the engine is not the only witness: A has two overdue, THEIRS two,
    # B none (its past-due one is filed); due soon is one each for A, B and THEIRS.
    assert items["filings_overdue"]["count"] == 4
    assert items["filings_due_soon"]["count"] == 3

    # The task read, asked on its own.
    assert items["tasks_overdue"]["count"] == len(world["tasks"]) == 5
    assert items["tasks_overdue"]["facts"] == {"assigned_to_you": 0, "unassigned": 1}

    # The stored findings, counted by a path that shares nothing with the service:
    # unresolved rows of the latest completed run per client.
    unresolved = [r for r in db.rows("reconciliation_findings") if r["resolved_at"] is None]
    assert items["books_findings"]["count"] == len(unresolved) == 5
    assert items["books_findings"]["facts"]["critical"] == sum(
        1 for r in unresolved if r["severity"] == "critical") == 2


def test_the_headline_is_the_count_in_words_and_nothing_else(world, model):
    out = run(_digest(PARTNER))
    for it in out["items"]:
        if it["status"] == "attention" and it["key"] != "books_findings":
            assert str(it["count"]) in it["headline"], it["headline"]


def test_the_filing_window_is_the_engines_own_seven_days(world):
    """`DUE_SOON_DAYS` is named in the sentence and hardcoded in the engine, so the
    engine is asked where day 7 and day 8 fall."""
    from services.intelligence_service import compute_compliance_risk
    world["records"][:] = [_rec(MINE_A, dg.DUE_SOON_DAYS), _rec(MINE_A, dg.DUE_SOON_DAYS + 1)]
    row = next(c for c in compute_compliance_risk(FIRM, None)["clients"] if c["client_id"] == MINE_A)
    assert row["due_soon_count"] == 1


# ── claim 1: a scoped CA's digest names only their clients ───────────────────

def test_a_scoped_callers_digest_names_only_their_clients(world, scoped_to_mine, model):
    out = run(_digest(MANAGER, scoped_to_mine))
    blob = json.dumps(out)
    assert THEIRS not in blob and NAMES[THEIRS] not in blob
    assert out["scoped"] is True
    named = {c["client_id"] for i in out["items"] for c in i["clients"]}
    assert named and named <= {MINE_A, MINE_B}


def test_a_scoped_callers_counts_are_over_their_clients_only(world, scoped_to_mine, model):
    items = _items(run(_digest(MANAGER, scoped_to_mine)))
    # THEIRS has two overdue filings and a due-soon one; none is in this view.
    assert items["filings_overdue"]["count"] == 2           # MINE_A: -3 and -10
    assert items["filings_due_soon"]["count"] == 2          # MINE_A +3, MINE_B +5
    # Tasks: A x2, B x1 and the firm-level one with no client; THEIRS' task is out.
    assert items["tasks_overdue"]["count"] == 4
    assert items["tasks_overdue"]["facts"]["assigned_to_you"] == 2   # A's and the firm-level


def test_a_scoped_callers_prompt_carries_no_client_name_and_no_id(world, scoped_to_mine, model):
    run(_digest(MANAGER, scoped_to_mine))
    assert model.calls, "premise: something needs attention, so the model was asked"
    sent = json.dumps(model.calls)
    for name in NAMES.values():
        assert name not in sent
    for cid in NAMES:
        assert cid not in sent


def test_the_prompt_of_a_firm_wide_caller_carries_no_name_either(world, model):
    run(_digest(PARTNER))
    sent = json.dumps(model.calls)
    assert not any(n in sent for n in NAMES.values()) and not any(c in sent for c in NAMES)


def test_the_prompt_is_counts_and_labels(world, model):
    run(_digest(PARTNER))
    user_msg = model.calls[0][-1]["content"]
    assert "Overdue filings (needs attention):" in user_msg
    assert "As at" in user_msg


def test_a_client_outside_the_scope_is_not_in_the_books_section_either(world, scoped_to_mine, model):
    from core.permissions import can
    assert not can("Manager", "accounting", "approve"), "premise: a Manager cannot read books findings"
    db = world["db"]
    _seed_runs(db, client=THEIRS, started=_hours_ago(2), findings=[("critical", None)])
    out = run(_digest(MANAGER, scoped_to_mine))
    assert "books_findings" not in _items(out)
    assert any("Books-integrity findings is not shown to you" in g for g in out["gaps"])


def test_a_partner_scoped_to_some_clients_still_reads_only_those_runs(world, scoped_to_mine, model):
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(2), findings=[("critical", None)])
    _seed_runs(db, client=THEIRS, started=_hours_ago(2), findings=[("critical", None)] * 4)
    out = run(_digest(PARTNER, scoped_to_mine))
    assert _items(out)["books_findings"]["count"] == 1
    assert THEIRS not in json.dumps(out)


# ── the books section: latest run, window, three kinds of nil ───────────────

def test_only_the_latest_completed_run_of_a_client_counts(world, model):
    """The sweep never closes an old finding: counting every unresolved row would
    report a persistent problem once per night."""
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(50), findings=[("critical", None)] * 3)
    _seed_runs(db, client=MINE_A, started=_hours_ago(26), findings=[("critical", None)] * 3)
    _seed_runs(db, client=MINE_A, started=_hours_ago(2), findings=[("critical", None)])
    item = _items(run(_digest(PARTNER)))["books_findings"]
    assert item["count"] == 1 and item["facts"]["critical"] == 1


def test_a_failed_or_running_latest_run_does_not_replace_the_last_completed_one(world, model):
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(30), findings=[("warning", None)] * 2)
    _seed_runs(db, client=MINE_A, started=_hours_ago(2), status="failed", findings=[("critical", None)])
    _seed_runs(db, client=MINE_A, started=_hours_ago(1), status="running")
    item = _items(run(_digest(PARTNER)))["books_findings"]
    assert item["count"] == 2 and item["facts"]["other"] == 2


def test_a_resolved_finding_is_not_open(world, model):
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(2),
               findings=[("critical", "2026-09-30T00:00:00Z"), ("warning", None)])
    item = _items(run(_digest(PARTNER)))["books_findings"]
    assert item["count"] == 1 and item["facts"]["critical"] == 0


def test_another_firms_runs_and_findings_are_never_read(world, model):
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(2), firm=OTHER_FIRM,
               findings=[("critical", None)] * 9)
    item = _items(run(_digest(PARTNER)))["books_findings"]
    assert item["status"] == "unknown"


def test_no_recent_check_is_UNKNOWN_and_not_zero(world, model):
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(24 * (dg.RUN_WINDOW_DAYS + 2)),
               findings=[("critical", None)])
    item = _items(run(_digest(PARTNER)))["books_findings"]
    assert item["status"] == "unknown" and item["count"] is None
    assert "nothing to report" in item["headline"]


def test_a_check_that_found_nothing_is_CLEAR_and_says_how_many_it_covered(world, model):
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(2))
    _seed_runs(db, client=MINE_B, started=_hours_ago(3))
    item = _items(run(_digest(PARTNER)))["books_findings"]
    assert item["status"] == "clear" and item["count"] == 0
    assert "2 clients" in item["headline"]


def test_clients_with_no_recent_check_are_named_as_not_looked_at(world, model):
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(2), findings=[("critical", None)])
    out = run(_digest(PARTNER))
    assert any("2 clients had no completed books check" in g for g in out["gaps"]), out["gaps"]


# ── claim 3: with the model down it still appears, as plain text ─────────────

def test_with_the_provider_failing_the_digest_is_still_there(world, monkeypatch):
    monkeypatch.setattr(groq_text, "chat", Model(fail=groq_text.ProviderFailed("down", http_status=502)))
    out = run(_digest(PARTNER))
    assert out["summary_source"] == "rule-based" and out["model_used"] is None
    assert out["summary"].startswith("Needs attention:")
    assert out["items"], "the counts do not depend on a model"


def test_with_any_exception_from_the_model_the_digest_is_still_there(world, monkeypatch):
    monkeypatch.setattr(groq_text, "chat", Model(fail=RuntimeError("boom")))
    out = run(_digest(PARTNER))
    assert out["summary_source"] == "rule-based" and out["items"]


def test_with_no_key_no_model_is_called(world, model, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    out = run(_digest(PARTNER))
    assert not model.calls and out["summary_source"] == "rule-based"


def test_nothing_needing_attention_is_not_worth_a_model_call(world, model):
    world["records"][:] = []
    world["tasks"][:] = []
    out = run(_digest(PARTNER))
    assert not model.calls
    assert out["summary"].startswith("Nothing needs attention in what was checked.")


def test_a_reply_carrying_a_figure_no_engine_computed_is_discarded(world, monkeypatch):
    m = Model(reply="About a third of your book, 42 filings, is overdue.")
    monkeypatch.setattr(groq_text, "chat", m)
    out = run(_digest(PARTNER))
    assert m.calls and out["summary_source"] == "rule-based"
    assert "42" not in out["summary"] and out["model_used"] is None


def test_a_reply_using_only_the_engines_figures_is_kept_and_labelled_as_the_models(world, monkeypatch):
    m = Model(reply="4 filings are overdue, so start there. 5 tasks are overdue too.")
    monkeypatch.setattr(groq_text, "chat", m)
    out = run(_digest(PARTNER))
    assert out["summary_source"] == "model" and out["model_used"] == groq_text.text_model()
    assert out["summary"].startswith("4 filings are overdue")


def test_an_empty_reply_falls_back(world, monkeypatch):
    monkeypatch.setattr(groq_text, "chat", Model(reply="   "))
    assert run(_digest(PARTNER))["summary_source"] == "rule-based"


def test_the_numbers_beside_the_sentence_are_the_same_whether_or_not_a_model_spoke(world, monkeypatch):
    monkeypatch.setattr(groq_text, "chat", Model(fail=RuntimeError("x")))
    plain = run(_digest(PARTNER))
    svc.reset_narration_cache()
    monkeypatch.setattr(groq_text, "chat", Model(reply="4 filings are overdue."))
    worded = run(_digest(PARTNER))
    assert plain["items"] == worded["items"]


# ── the narration is cached by its facts; the counts never are ──────────────

def test_the_same_facts_are_one_model_call_and_changed_facts_are_another(world, model, monkeypatch):
    model.reply = "4 filings are overdue."
    run(_digest(PARTNER))
    run(_digest(PARTNER))
    assert len(model.calls) == 1, "an unchanged morning is one call"
    world["tasks"].append(_task(MINE_B, "u-other"))
    run(_digest(PARTNER))
    assert len(model.calls) == 2


def test_a_cached_wording_never_freezes_the_counts(world, model):
    model.reply = "4 filings are overdue."
    first = run(_digest(PARTNER))
    world["tasks"].append(_task(MINE_B, "u-other"))
    second = run(_digest(PARTNER))
    assert _items(second)["tasks_overdue"]["count"] == _items(first)["tasks_overdue"]["count"] + 1


def test_a_firms_cached_wording_is_not_served_to_another_firm(world, model):
    model.reply = "4 filings are overdue."
    run(_digest(PARTNER))
    other = {**PARTNER, "firm_id": OTHER_FIRM}
    run(_digest(other))
    assert len(model.calls) == 2


def test_a_discarded_or_failed_wording_is_not_cached(world, monkeypatch):
    bad = Model(reply="9999 filings")
    monkeypatch.setattr(groq_text, "chat", bad)
    run(_digest(PARTNER))
    good = Model(reply="4 filings are overdue.")
    monkeypatch.setattr(groq_text, "chat", good)
    assert run(_digest(PARTNER))["summary_source"] == "model" and len(good.calls) == 1


# ── sections: access, failure and what is deliberately absent ───────────────

def test_a_section_that_cannot_be_read_is_named_and_the_others_still_appear(world, model, monkeypatch):
    import repositories.task_repository as tr

    def boom(**kw):
        raise RuntimeError("tasks table gone")

    monkeypatch.setattr(tr.task_repo, "find_overdue", boom)
    out = run(_digest(PARTNER))
    assert "tasks_overdue" not in _items(out) and "filings_overdue" in _items(out)
    assert any("Overdue tasks could not be read" in g for g in out["gaps"])


def test_a_role_without_task_read_gets_no_task_section_and_is_told(world, model, monkeypatch):
    monkeypatch.setattr(svc, "can_user",
                        lambda user, res, act: not (res == "task" and act == "read"))
    out = run(_digest(PARTNER))
    assert "tasks_overdue" not in _items(out)
    assert any("Overdue tasks is not shown to you" in g for g in out["gaps"])


def test_the_engines_not_included_are_named_on_every_answer(world, model):
    out = run(_digest(PARTNER))
    text = " ".join(out["gaps"])
    for needle in ("GSTR-2B", "Rule 37A", "duplicate bills", "Recurring journal"):
        assert needle in text, needle


def test_the_items_use_exactly_the_keys_the_browser_routes_on(world, model):
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(2), findings=[("critical", None)])
    keys = [i["key"] for i in run(_digest(PARTNER))["items"]]
    assert sorted(keys) == sorted(dg.ITEM_KEYS)


def test_what_needs_attention_comes_first(world, model):
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(2))
    statuses = [i["status"] for i in run(_digest(PARTNER))["items"]]
    assert statuses == sorted(statuses, key={"attention": 0, "clear": 1, "unknown": 2}.get)


def test_the_digest_writes_nothing(world, model, monkeypatch):
    from tests import e2e_harness

    def forbidden(self, *a, **k):
        raise AssertionError("the digest wrote to the database")

    for verb in ("insert", "update", "upsert", "delete"):
        monkeypatch.setattr(e2e_harness._Query, verb, forbidden)
    run(_digest(PARTNER))


def test_a_list_cut_at_the_cap_says_how_many_clients_there_really_are():
    rows = [{"client_id": f"c{i}", "client_name": f"Client {i:02d}", "overdue_count": 1,
             "due_soon_count": 0} for i in range(dg.MAX_CLIENTS_LISTED + 4)]
    item = dg.compliance_items(rows)[0]
    assert len(item["clients"]) == dg.MAX_CLIENTS_LISTED
    assert item["clients_total"] == dg.MAX_CLIENTS_LISTED + 4
    assert item["count"] == dg.MAX_CLIENTS_LISTED + 4


# ── the plain sentence and the figures a narration may use ──────────────────

def test_the_plain_sentence_is_a_complete_account_not_a_stub(world, model):
    db = world["db"]
    _seed_runs(db, client=MINE_A, started=_hours_ago(2))
    world["records"][:] = [_rec(MINE_A, 3)]
    s = dg.plain_summary(run(_digest(PARTNER))["items"])
    assert "Needs attention:" in s and "Checked and clear:" in s


def test_every_figure_in_the_plain_sentence_is_one_the_engines_produced(world, model):
    items = run(_digest(PARTNER))["items"]
    from domain.ai import narration
    allowed = dg.allowed_figures(items, today_day=TODAY.day, today_year=TODAY.year)
    assert narration.is_grounded(dg.plain_summary(items), allowed)
    for it in items:
        assert narration.is_grounded(it["headline"], allowed), it["headline"]


def test_an_unknown_is_not_rendered_as_a_zero_in_the_sentence():
    unknown = dg.findings_item({}, [], {})
    s = dg.plain_summary([unknown])
    assert "Not known: books-integrity findings." in s and "0" not in s


# ── the route ────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(world, model):
    from core.auth import get_current_user
    from routers import intelligence

    app = FastAPI()
    app.include_router(intelligence.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False), app


def test_the_route_serves_the_digest_in_the_envelope(client):
    c, _ = client
    r = c.get("/api/intelligence/digest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["error"] is None
    assert {"items", "gaps", "summary", "summary_source", "scoped", "as_of"} <= set(body["data"])


def test_a_role_without_ai_read_is_refused_before_anything_is_spent(client, world, model):
    from core.auth import get_current_user
    c, app = client
    app.dependency_overrides[get_current_user] = lambda: {**PARTNER, "role": "Client"}
    for _ in range(30):
        assert c.get("/api/intelligence/digest").status_code == 403
    assert not model.calls
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    assert c.get("/api/intelligence/digest").status_code == 200, \
        "a refusal spent nothing from the limiter"


def test_the_scope_is_a_required_argument_so_it_cannot_be_forgotten():
    """A default of None would read firm-wide by OMISSION. None is spelled out at
    the one call site and means a firm-wide role."""
    import inspect
    p = inspect.signature(svc.todays_digest).parameters["allowed_client_ids"]
    assert p.default is inspect.Parameter.empty
    g = inspect.signature(svc.gather).parameters["allowed"]
    assert g.default is inspect.Parameter.empty


def test_the_route_resolves_the_callers_scope_and_the_whole_answer_is_narrowed(client, monkeypatch):
    """End to end through the real route: the resolver says this Manager has two
    clients, and nothing about the third appears anywhere in the response."""
    from core.auth import get_current_user
    from routers import intelligence
    c, app = client
    app.dependency_overrides[get_current_user] = lambda: MANAGER
    monkeypatch.setattr(intelligence, "effective_client_ids", lambda user: {MINE_A, MINE_B})
    r = c.get("/api/intelligence/digest")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["scoped"] is True
    assert THEIRS not in json.dumps(body) and NAMES[THEIRS] not in json.dumps(body)
    assert {i["key"]: i["count"] for i in body["items"]}["filings_overdue"] == 2


def test_a_firm_wide_caller_is_not_marked_scoped(client):
    c, _ = client
    assert c.get("/api/intelligence/digest").json()["data"]["scoped"] is False


def test_the_route_is_rate_limited_per_user(client):
    c, _ = client
    cap = rate_limit.user_limit(rate_limit.BUCKETS["intelligence"][0])
    for _ in range(cap):
        assert c.get("/api/intelligence/digest").status_code == 200
    r = c.get("/api/intelligence/digest")
    assert r.status_code == 429 and "Retry-After" in r.headers


# ── the browser's half, held from this side ──────────────────────────────────
#
# The key vocabulary is `digest.ITEM_KEYS`; the routes are `digestLinks.ts`. A guard
# written in apps/web would assert that map against a copy of itself and pass
# whenever both drifted together (the Schedule III caption lesson), so the check
# reads the browser's file from here.

import re
from pathlib import Path

_WEB = Path(__file__).resolve().parents[2] / "web"


def test_every_key_the_server_can_emit_is_routed_by_the_browser():
    src = (_WEB / "lib/insights/digestLinks.ts").read_text(encoding="utf-8")
    block = src[src.index("export const DIGEST_ROUTES"):src.index("export function digestClientHref")]
    assert set(re.findall(r"^\s{2}([a-z_]+):\s*\{", block, re.M)) == set(dg.ITEM_KEYS)


def test_each_route_names_a_screen_that_exists():
    app = _WEB / "app"
    assert (app / "deadlines/page.tsx").exists() and (app / "tasks/page.tsx").exists()
    for section in ("compliance", "tasks", "accounting"):
        assert (app / "clients/[id]" / section / "page.tsx").exists(), section
    accounting = (app / "clients/[id]/accounting/page.tsx").read_text(encoding="utf-8")
    assert 'id: "verify-books"' in accounting, "the books-findings link opens a tab that exists"


def test_the_digest_panel_is_mounted_on_the_insights_page():
    page = (_WEB / "app/insights/page.tsx").read_text(encoding="utf-8")
    assert "<DigestPanel />" in page
