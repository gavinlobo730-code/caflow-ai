"""Recurring journals: templates the firm owns, DRAFT journals out (ACC-06).

WHAT WAS WRONG

`/accounting/recurring` kept every template a CA set up in
`localStorage["practicesync_recurring_templates"]`, worked out the next due
date in the browser, and POSTED NOTHING. The hub card said "Automate monthly,
quarterly & yearly entries" while nothing anywhere posted a due template, so a
CA had every reason to believe the firm's recurring journals were configured.

This is the last of ACC-06's three screens and the only genuine build among
them: the budget went onto `account_budgets` (migration 376) and the retainer
tracker onto `billing_schedules`, which was already built and had no caller.

THE TWO PROPERTIES THAT MATTER MOST

  * It produces a DRAFT and never a posted entry. This product acts unprompted
    in exactly one place — a bank rule a Manager has marked trusted — and that
    was a recorded owner decision, not a default to copy.
  * The generated entry is stamped `source_type = 'manual'`. Every guard reads
    that column, so any other value hands the CA a draft they are invited to
    review and forbidden to amend.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"


@pytest.fixture(autouse=True)
def _clean():
    from services import recurring_journal_service as svc
    svc.MOCK_JOURNAL_TEMPLATES.clear()
    svc.MOCK_JOURNAL_RUNS.clear()
    yield
    svc.MOCK_JOURNAL_TEMPLATES.clear()
    svc.MOCK_JOURNAL_RUNS.clear()


def _lines(amount=5_00_000):
    return [{"account_id": "ACC-DR", "debit_paise": amount, "credit_paise": 0},
            {"account_id": "ACC-CR", "debit_paise": 0, "credit_paise": amount}]


def _make(firm="F1", client="C1", **over):
    from services import recurring_journal_service as svc
    data = {"client_id": client, "name": "Monthly rent", "frequency": "monthly",
            "day_of_month": 1, "start_date": "2026-04-01",
            "narration": "Rent for the month", "lines": _lines()}
    data.update(over)
    return svc.create_template(firm, data, created_by="u1")


# ── the cadence engine is SHARED, not copied ────────────────────────────────

def test_the_cadence_engine_has_one_home():
    """CLAUDE.md: when a rule has to exist in two places, MOVE it. A cadence
    engine drifting means one feature posts in a month the other skips."""
    src = (API_ROOT / "services" / "recurring_invoice_service.py").read_text()
    assert "from domain.recurrence import" in src, (
        "the invoice service must import the shared cadence engine, not keep "
        "its own copy")
    assert "def occurrence(" not in src
    assert "def next_occurrence(" not in src


def test_a_month_end_clamps_against_the_original_day():
    """31 Jan monthly runs 31 Jan, 28 Feb, 31 MAR. Clamping each step against
    the PREVIOUS occurrence would walk the whole series back to the 28th after
    one February — a rent journal posting three days early for ever."""
    from domain.recurrence import preview_occurrences
    got = preview_occurrences(
        {"frequency": "monthly", "start_date": "2026-01-31",
         "next_run_date": "2026-01-31"}, count=4)
    assert got == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]


# ── validation, at save time ────────────────────────────────────────────────

def test_a_template_that_does_not_balance_is_refused():
    """Refused HERE rather than at the kernel: a CA saving a template needs to
    be told it does not balance while they are looking at it, and generation
    runs unattended."""
    from fastapi import HTTPException
    from services import recurring_journal_service as svc
    with pytest.raises(HTTPException) as e:
        svc.create_template("F1", {
            "client_id": "C1", "name": "x", "frequency": "monthly",
            "start_date": "2026-04-01",
            "lines": [{"account_id": "A", "debit_paise": 100, "credit_paise": 0},
                      {"account_id": "B", "debit_paise": 0, "credit_paise": 90}]})
    assert "does not balance" in str(e.value.detail)


def test_a_line_that_is_both_sides_is_refused():
    """BALANCED, deliberately. An unbalanced example would be caught by the
    balance check instead and this rule would go untested — which is what a
    negative control found: deleting the one-sided check passed the suite."""
    from fastapi import HTTPException
    from services import recurring_journal_service as svc
    with pytest.raises(HTTPException) as e:
        svc.create_template("F1", {
            "client_id": "C1", "name": "x", "frequency": "monthly",
            "start_date": "2026-04-01",
            "lines": [{"account_id": "A", "debit_paise": 100, "credit_paise": 100},
                      {"account_id": "B", "debit_paise": 100, "credit_paise": 0},
                      {"account_id": "C", "debit_paise": 0, "credit_paise": 100}]})
    assert "debit OR a credit" in str(e.value.detail)


def test_a_line_that_is_neither_side_is_refused():
    """Also balanced. A nil line is not a line — it is a row that says nothing
    and would reach `journal_lines` as noise."""
    from fastapi import HTTPException
    from services import recurring_journal_service as svc
    with pytest.raises(HTTPException) as e:
        svc.create_template("F1", {
            "client_id": "C1", "name": "x", "frequency": "monthly",
            "start_date": "2026-04-01",
            "lines": [{"account_id": "A", "debit_paise": 0, "credit_paise": 0},
                      {"account_id": "B", "debit_paise": 100, "credit_paise": 0},
                      {"account_id": "C", "debit_paise": 0, "credit_paise": 100}]})
    assert "debit OR a credit" in str(e.value.detail)


def test_a_day_of_month_that_does_not_exist_every_month_is_refused():
    """29, 30 and 31 do not exist in every month, and sliding to the 28th in
    February posts on a date nobody chose."""
    from fastapi import HTTPException
    from services import recurring_journal_service as svc
    for day in (0, 29, 31):
        with pytest.raises(HTTPException):
            svc.create_template("F1", {
                "client_id": "C1", "name": "x", "frequency": "monthly",
                "day_of_month": day, "start_date": "2026-04-01", "lines": _lines()})


def test_a_single_sided_template_is_refused():
    from fastapi import HTTPException
    from services import recurring_journal_service as svc
    with pytest.raises(HTTPException) as e:
        svc.create_template("F1", {
            "client_id": "C1", "name": "x", "frequency": "monthly",
            "start_date": "2026-04-01",
            "lines": [{"account_id": "A", "debit_paise": 100, "credit_paise": 0}]})
    assert "at least two lines" in str(e.value.detail)


def test_an_unknown_frequency_is_refused():
    from fastapi import HTTPException
    from services import recurring_journal_service as svc
    with pytest.raises(HTTPException):
        svc.create_template("F1", {
            "client_id": "C1", "name": "x", "frequency": "fortnightly",
            "start_date": "2026-04-01", "lines": _lines()})


# ── what is due ─────────────────────────────────────────────────────────────

def test_nothing_is_due_before_the_start_date():
    from services import recurring_journal_service as svc
    t = _make(start_date="2026-04-01")
    assert svc.due_occurrences(t, as_of="2026-03-31") == []


def test_a_dormant_template_catches_up_in_order():
    from services import recurring_journal_service as svc
    t = _make(start_date="2026-01-01")
    assert svc.due_occurrences(t, as_of="2026-04-15") == [
        "2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]


def test_catch_up_is_bounded():
    """A template dormant for years must not generate a thousand drafts on the
    morning somebody switches it on. Bounded rather than skipped: the rest
    generate on the next run."""
    from domain.recurrence import MAX_CATCHUP_PER_RUN
    from services import recurring_journal_service as svc
    t = _make(frequency="weekly", start_date="2000-01-01")
    assert len(svc.due_occurrences(t, as_of="2026-01-01")) == MAX_CATCHUP_PER_RUN


def test_a_paused_template_is_due_for_nothing():
    from services import recurring_journal_service as svc
    t = _make(start_date="2026-01-01", status="paused")
    assert svc.due_occurrences(t, as_of="2026-06-01") == []


def test_an_end_date_stops_the_series():
    from services import recurring_journal_service as svc
    t = _make(start_date="2026-01-01", end_date="2026-02-28")
    assert svc.due_occurrences(t, as_of="2026-06-01") == ["2026-01-01", "2026-02-01"]


# ── generation ──────────────────────────────────────────────────────────────

class _Journal:
    """A manual_journal_service double that records what it was asked for."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def create(self, db, firm_id, data, actor_id=None):
        self.calls.append(data)
        if self.fail:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=self.fail)
        return {"id": f"JE-{len(self.calls)}", "status": data.get("status"),
                "source_type": "manual"}


def _patched(monkeypatch, journal):
    import services.manual_journal_service as mjs
    monkeypatch.setattr(mjs, "manual_journal_service", journal)


def test_a_generated_entry_is_a_DRAFT(monkeypatch):
    """Never a posted one. This product acts unprompted in exactly one place —
    a trusted bank rule — and that was an owner decision, not a default."""
    from services import recurring_journal_service as svc
    j = _Journal()
    _patched(monkeypatch, j)
    t = _make()
    svc.generate_for_occurrence("F1", t, "2026-04-01")
    assert j.calls[0]["status"] == "draft"


def test_the_generated_entry_carries_the_templates_lines(monkeypatch):
    from services import recurring_journal_service as svc
    j = _Journal()
    _patched(monkeypatch, j)
    t = _make()
    svc.generate_for_occurrence("F1", t, "2026-04-01")
    lines = j.calls[0]["lines"]
    assert [(l["account_id"], l["debit_paise"], l["credit_paise"]) for l in lines] == [
        ("ACC-DR", 5_00_000, 0), ("ACC-CR", 0, 5_00_000)]
    assert j.calls[0]["entry_date"] == "2026-04-01"
    assert j.calls[0]["client_id"] == "C1"


def test_generating_the_same_occurrence_twice_makes_one_journal(monkeypatch):
    from services import recurring_journal_service as svc
    j = _Journal()
    _patched(monkeypatch, j)
    t = _make()
    first = svc.generate_for_occurrence("F1", t, "2026-04-01")
    second = svc.generate_for_occurrence("F1", t, "2026-04-01")
    assert first["created"] is True and second["created"] is False
    assert second["reason"] == "already generated"
    assert second["journal_entry_id"] == first["journal_entry_id"]
    assert len(j.calls) == 1


def test_a_failure_is_recorded_and_the_template_does_not_advance(monkeypatch):
    """A template that cannot post needs a CA, not another attempt at 06:00
    tomorrow — and advancing past a failure would skip the occurrence for
    ever, which is worse than a visible error."""
    from services import recurring_journal_service as svc
    _patched(monkeypatch, _Journal(fail="Financial year is locked."))
    t = _make(start_date="2026-04-01")
    out = svc.run_due("F1", as_of="2026-04-02")
    assert out["failed_count"] == 1
    assert "locked" in out["failed"][0]["error"]
    assert t["next_run_date"] == "2026-04-01"   # unmoved
    runs = svc.history("F1", t["id"])
    assert runs and runs[0]["status"] == "failed"


def test_run_due_advances_past_what_it_generated(monkeypatch):
    from services import recurring_journal_service as svc
    _patched(monkeypatch, _Journal())
    t = _make(start_date="2026-01-01")
    out = svc.run_due("F1", as_of="2026-03-15")
    assert [g["occurrence"] for g in out["generated"]] == [
        "2026-01-01", "2026-02-01", "2026-03-01"]
    assert t["next_run_date"] == "2026-04-01"


def test_running_twice_generates_nothing_the_second_time(monkeypatch):
    from services import recurring_journal_service as svc
    j = _Journal()
    _patched(monkeypatch, j)
    _make(start_date="2026-01-01")
    svc.run_due("F1", as_of="2026-03-15")
    again = svc.run_due("F1", as_of="2026-03-15")
    assert again["generated_count"] == 0
    assert len(j.calls) == 3


def test_a_template_past_its_end_date_is_archived(monkeypatch):
    from services import recurring_journal_service as svc
    _patched(monkeypatch, _Journal())
    t = _make(start_date="2026-01-01", end_date="2026-02-28")
    svc.run_due("F1", as_of="2026-06-01")
    assert t["status"] == "archived"


# ── the endpoint ────────────────────────────────────────────────────────────

def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    import routers.recurring_journals as mod

    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "firm_id": "F1", "role": "Partner",
        "email": "p@f1.test", "auth_user_id": "auth-partner"}
    return TestClient(app, raise_server_exceptions=False)


def test_the_endpoint_creates_lists_and_previews():
    c = _client()
    res = c.post("/api/recurring-journals", json={
        "client_id": "client-001", "name": "Monthly rent", "frequency": "monthly",
        "start_date": "2026-04-01", "lines": _lines()})
    assert res.status_code == 200, res.text
    tid = res.json()["data"]["id"]

    listed = c.get("/api/recurring-journals")
    assert listed.status_code == 200
    assert [t["id"] for t in listed.json()["data"]] == [tid]

    prev = c.get(f"/api/recurring-journals/{tid}/preview?count=3")
    assert prev.json()["data"]["occurrences"] == [
        "2026-04-01", "2026-05-01", "2026-06-01"]


def test_the_endpoint_404s_on_someone_elses_template():
    assert _client().get("/api/recurring-journals/nope").status_code == 404


def test_the_patch_body_cannot_move_a_template_to_another_client():
    """Its generated journals would still point at the first client, and the
    runs ledger is keyed (template, occurrence) with no client in it."""
    from routers.recurring_journals import TemplateUpdateIn
    assert "client_id" not in TemplateUpdateIn.model_fields


def test_an_unbalanced_template_is_refused_by_the_endpoint():
    res = _client().post("/api/recurring-journals", json={
        "client_id": "client-001", "name": "x", "frequency": "monthly",
        "start_date": "2026-04-01",
        "lines": [{"account_id": "A", "debit_paise": 100, "credit_paise": 0},
                  {"account_id": "B", "debit_paise": 0, "credit_paise": 90}]})
    assert res.status_code == 422, res.text


# ── nothing posts unprompted ────────────────────────────────────────────────

def test_no_path_in_this_feature_can_post(monkeypatch):
    """The whole feature, asserted as a rule rather than per call site: every
    journal it creates is a draft."""
    from services import recurring_journal_service as svc
    j = _Journal()
    _patched(monkeypatch, j)
    _make(start_date="2026-01-01")
    svc.run_due("F1", as_of="2026-04-01")
    assert j.calls, "nothing was generated, so this proves nothing"
    assert all(call["status"] == "draft" for call in j.calls)


def test_the_service_never_names_the_posted_status():
    """A rule about the SOURCE, not one call site: nothing in the module may
    ask for a posted entry."""
    src = (API_ROOT / "services" / "recurring_journal_service.py").read_text()
    code = re.sub(r'"""[\s\S]*?"""', " ", src)
    code = re.sub(r"^\s*#.*$", " ", code, flags=re.M)
    assert '"posted"' not in code and "'posted'" not in code


def test_the_entry_stays_manual_so_the_CA_can_still_amend_it():
    """`manual_journal_service._is_manual` is `(source_type or "") == "manual"`
    and migrations 275/338 refuse the edit and discard paths on anything else.
    Stamping the template's own source_type would hand the CA a draft they are
    invited to review and forbidden to change."""
    src = (API_ROOT / "services" / "recurring_journal_service.py").read_text()
    code = re.sub(r'"""[\s\S]*?"""', " ", src)
    code = re.sub(r"^\s*#.*$", " ", code, flags=re.M)
    assert "source_type" not in code, (
        "the generated entry must not be stamped with a source_type — the "
        "trace lives on recurring_template_id, which no guard reads")
    assert "recurring_template_id" in code


# ── the browser no longer owns any of this ──────────────────────────────────

def test_the_recurring_screen_keeps_nothing_in_the_browser():
    page = WEB_ROOT / "app" / "accounting" / "recurring" / "page.tsx"
    src = re.sub(r"/\*[\s\S]*?\*/", " ", page.read_text())
    src = re.sub(r"^\s*//.*$", " ", src, flags=re.M)
    assert not re.search(r"localStorage\.(getItem|setItem)", src), (
        "recurring templates are rows in recurring_journal_templates now")
    assert "api.recurringJournals" in src, (
        "the screen must read and write through the API")
    assert "nextDueDate" not in src, (
        "the next due date is domain/recurrence.py's answer, not the browser's")


def test_every_updatable_field_is_a_column_the_create_path_writes():
    """The other end of the schema chain.

    `tests/test_backend_columns_exist_pg.py` checks a write's columns against
    the real schema only when they are written as a dict LITERAL, and a
    PATCH's key set is variable, so `update_template`'s `.update(fields)`
    cannot be one — it costs a unit of that test's budget and its columns go
    unchecked.

    So `create_template`'s INSERT is a literal (checked against Postgres) and
    this asserts the update's field set is a SUBSET of those names. Add a
    field the table has no column for and this fails, in mock mode, with no
    database needed — which is how the `description` / `due_date` gap on
    `billing_schedules` was found.
    """
    import ast, inspect, pathlib as _p
    from services import recurring_journal_service as svc

    tree = ast.parse(_p.Path(inspect.getfile(svc)).read_text())

    def _fn(name):
        return next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == name)

    # `fields = {k: merged[k] for k in (...) if k in merged}`
    updatable = next(
        {e.value for e in n.value.generators[0].iter.elts}
        for n in ast.walk(_fn("update_template"))
        if isinstance(n, ast.Assign)
        and getattr(n.targets[0], "id", None) == "fields"
        and isinstance(n.value, ast.DictComp))

    insert_keys = next(
        {k.value for k in call.args[0].keys}
        for call in ast.walk(_fn("create_template"))
        if isinstance(call, ast.Call)
        and getattr(call.func, "attr", None) == "insert"
        and call.args and isinstance(call.args[0], ast.Dict))

    assert updatable - insert_keys == set(), (
        f"update_template can write {sorted(updatable - insert_keys)}, which "
        f"create_template does not — either it is not a column of "
        f"recurring_journal_templates, or the create path is missing it")


def test_the_line_insert_names_its_columns_where_the_schema_check_can_read_them():
    """`.insert(_line_rows(...))` is a CALL and invisible to the schema check,
    so a wrong column there would never be caught. `_insert_lines` restates
    the names in a comprehension over dict literals, once, for both callers."""
    import inspect
    from services import recurring_journal_service as svc
    src = inspect.getsource(svc._insert_lines)
    for col in ("template_id", "account_id", "debit_paise", "credit_paise",
                "narration", "sort_order"):
        assert f'"{col}"' in src, col


def test_the_routers_scope_helper_actually_asks(monkeypatch):
    """`_scoped` is named in `test_router_client_scope`'s AUDITED tuple, and
    that test's own comment warns about exactly this: a loader "exists whether
    or not it checks anything", so naming one lets the sweep pass while the
    check is gone. A negative control proved it — deleting the
    `assert_client_access` call inside `_scoped` failed nothing.

    So the ratchet says every endpoint goes through `_scoped`, and this says
    `_scoped` asks.
    """
    import routers.recurring_journals as mod

    asked: list = []
    monkeypatch.setattr(mod, "assert_client_access",
                        lambda user, cid: asked.append(cid))
    monkeypatch.setattr(mod.svc, "get_template",
                        lambda firm_id, tid: {"id": tid, "client_id": "C9"})
    mod._scoped({"firm_id": "F1"}, "T1")
    assert asked == ["C9"], "_scoped must assert the caller may reach the client"


def test_the_routers_scope_helper_404s_on_a_missing_template(monkeypatch):
    import pytest as _pytest
    from fastapi import HTTPException
    import routers.recurring_journals as mod
    monkeypatch.setattr(mod.svc, "get_template", lambda firm_id, tid: None)
    with _pytest.raises(HTTPException) as e:
        mod._scoped({"firm_id": "F1"}, "T1")
    assert e.value.status_code == 404
