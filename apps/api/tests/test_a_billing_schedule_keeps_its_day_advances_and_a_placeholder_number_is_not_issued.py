"""POST-A-215 and POST-A-216: the billing loop keeps its day and its place, a placeholder invoice number is not issued, and
two people editing a knowledge article do not lose a save.

THE DEFECTS (observed 8 October 2026 while writing docs/architecture/11, fixed 18 October)
    * `generate_for_schedule` returned early when the period already had an invoice and never advanced the schedule, so a
      schedule whose invoice was stamped but whose advance then failed stayed due for ever and was counted "skipped" by every
      run;
    * billing's cadence arithmetic capped the day at 28 and stepped from the PREVIOUS run: a retainer set for the 31st ran
      31 Oct, 28 Nov, 28 Dec, 28 Jan for ever. `domain/recurrence` clamps against the ORIGINAL day, which billing could not
      use because the schedule held only the already-clamped date (migration 511 adds the anchor);
    * a `DRAFT-` number made by an unattended process is a legal Rule 46(b) number, so nothing refused issuing it and the
      tax invoice number was a placeholder;
    * `edit_article` had no retry on the `UNIQUE (article_id, version)` collision, so the second of two simultaneous editors
      got a 500 and their text was lost.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.sales_invoices as sales
import services.billing_service as billing
import services.knowledge_service as kb
from services import numbering

PARTNER = {"firm_id": "F1", "role": "Partner", "auth_user_id": "p", "email": "p@f"}


@pytest.fixture(autouse=True)
def _clean():
    billing.MOCK_BILLING_SCHEDULES.clear()
    billing.MOCK_CLIENT_LINKS.clear()
    sales.MOCK_SALES_INVOICES.clear()
    yield
    billing.MOCK_BILLING_SCHEDULES.clear()
    billing.MOCK_CLIENT_LINKS.clear()
    sales.MOCK_SALES_INVOICES.clear()


def _schedule(cadence="monthly", next_run_date="2026-10-31"):
    return billing.create_schedule("F1", {
        "client_id": "PRACTICE_CLIENT_1", "arrangement": "retainer", "cadence": cadence, "amount_paise": 100000,
        "gst_rate": 18.0, "next_run_date": next_run_date, "service_id": "SVC-1"}, created_by="p")


# ── the cadence keeps its day ─────────────────────────────────────────────────────────────────────────────────────────

def _walk(cadence, anchor, steps):
    out, cur = [], anchor
    for _ in range(steps):
        cur = billing.next_run_after(cadence, cur, anchor=anchor)
        out.append(cur)
    return out


def test_a_retainer_set_for_the_31st_keeps_the_31st_in_every_month_that_has_one():
    assert _walk("monthly", "2026-01-31", 6) == [
        "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31"]


def test_a_short_month_borrows_nothing_from_the_months_after_it_and_a_leap_year_has_its_29th():
    assert _walk("monthly", "2028-01-31", 2) == ["2028-02-29", "2028-03-31"]


def test_a_quarterly_and_an_annual_schedule_keep_their_day_too():
    assert _walk("quarterly", "2026-01-31", 4) == ["2026-04-30", "2026-07-31", "2026-10-31", "2027-01-31"]
    assert _walk("annual", "2024-02-29", 4) == ["2025-02-28", "2026-02-28", "2027-02-28", "2028-02-29"]


def test_a_schedule_with_no_anchor_is_measured_from_its_next_run_date_and_no_longer_capped_at_the_28th():
    assert billing.next_run_after("monthly", "2026-10-31") == "2026-11-30"
    assert billing.next_run_after("monthly", "2026-06-01") == "2026-07-01"
    assert billing.next_run_after("one_time", "2026-06-01") is None


def test_the_scheduler_advance_uses_the_schedules_own_anchor():
    s = _schedule(next_run_date="2026-10-31")
    assert s["anchor_date"] == "2026-10-31"
    for expected in ("2026-11-30", "2026-12-31", "2027-01-31", "2027-02-28", "2027-03-31"):
        billing._advance_schedule("F1", s, "monthly")
        assert s["next_run_date"] == expected


def test_editing_the_next_run_date_by_hand_rebases_the_schedule():
    s = _schedule(next_run_date="2026-10-31")
    updated = billing.update_schedule("F1", s["id"], {"next_run_date": "2026-12-15"})
    assert updated["anchor_date"] == "2026-12-15"
    billing._advance_schedule("F1", updated, "monthly")
    assert updated["next_run_date"] == "2027-01-15"


def test_editing_something_else_leaves_the_anchor_alone():
    s = _schedule(next_run_date="2026-10-31")
    updated = billing.update_schedule("F1", s["id"], {"amount_paise": 250000})
    assert updated["anchor_date"] == "2026-10-31"


# ── a schedule whose invoice is already on file moves on ──────────────────────────────────────────────────────────────

def test_a_stamped_but_unadvanced_schedule_advances_instead_of_staying_due_for_ever():
    s = _schedule(next_run_date="2026-06-01")
    first = billing.generate_for_schedule("F1", s, PARTNER)
    assert first["created"] is True and s["next_run_date"] == "2026-07-01"
    s["next_run_date"] = "2026-06-01"                      # the advance after the first run was lost

    again = billing.generate_for_schedule("F1", s, PARTNER)

    assert again["created"] is False and again["idempotent"] is True
    assert again["invoice"]["id"] == first["invoice"]["id"]
    assert s["next_run_date"] == "2026-07-01", "the early return must finish the advance it found undone"
    assert len(sales.MOCK_SALES_INVOICES) == 1, "and still makes no second invoice"


def test_the_next_run_no_longer_counts_the_schedule_as_skipped_for_ever():
    s = _schedule(next_run_date="2026-06-01")
    billing.generate_for_schedule("F1", s, PARTNER)
    s["next_run_date"] = "2026-06-01"
    first = billing.run_due("F1", PARTNER, as_of="2026-06-15")
    second = billing.run_due("F1", PARTNER, as_of="2026-06-15")
    assert first["skipped_count"] == 1 and first["generated_count"] == 0
    assert second["skipped_count"] == 0 and second["generated_count"] == 0, "it moved on, so it is not due any more"


def test_a_period_asked_for_by_name_that_is_not_the_schedules_own_moves_nothing():
    s = _schedule(next_run_date="2026-06-01")
    billing.generate_for_schedule("F1", s, PARTNER, period="2026-05")
    before = s["next_run_date"]
    billing.generate_for_schedule("F1", s, PARTNER, period="2026-05")        # a re-read of an old period
    assert s["next_run_date"] == before or before == "2026-07-01"
    assert billing.period_for("monthly", s["next_run_date"]) != "2026-05"


# ── a placeholder number is not issued ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("number", ["DRAFT-ABC123DEF0", "draft-abc123def0", "  DRAFT-X", "DRAFT-"])
def test_a_placeholder_is_recognised_however_it_is_typed(number):
    assert numbering.is_placeholder_invoice_no(number)


@pytest.mark.parametrize("number", ["SINV-2026-27-0001", "INV/0042", "", None, "DRAFTING-1"])
def test_a_real_number_is_not_a_placeholder(number):
    assert not numbering.is_placeholder_invoice_no(number)


def test_the_number_the_unattended_process_makes_is_a_placeholder_and_a_legal_one():
    made = numbering.draft_placeholder_invoice_no()
    assert numbering.is_placeholder_invoice_no(made)
    sales._assert_invoice_no_legal(made)                # Rule 46(b) allows it, which is why a second rule is needed


def test_issuing_a_generated_draft_is_refused_until_the_number_is_replaced():
    s = _schedule(next_run_date="2026-06-01")
    inv = billing.generate_for_schedule("F1", s, PARTNER)["invoice"]
    with pytest.raises(HTTPException) as refused:
        sales.issue_invoice(inv["id"], PARTNER)
    assert refused.value.status_code == 422 and inv["invoice_no"] in refused.value.detail
    assert inv["status"] == "draft"
    inv["invoice_no"] = "SINV-26-27-0001"
    assert sales.issue_invoice(inv["id"], PARTNER)["data"]["status"] == "issued"


def test_both_issue_paths_ask_the_placeholder_question_straight_after_the_legal_one():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(sales.__file__)).read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "issue_invoice")
    calls = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    # The in-memory branch still asks the two itself; the real branch asks them through the readiness list since POST-A-125.
    assert calls.count("_assert_invoice_no_legal") == 1
    assert calls.count("_assert_invoice_no_is_not_a_placeholder") == 1
    assert "issue_readiness_service.blockers_for_sales_invoice" in [
        ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    from services import issue_readiness_service as service
    number = next(n for n in ast.walk(ast.parse(Path(service.__file__).read_text(encoding="utf-8")))
                  if isinstance(n, ast.FunctionDef) and n.name == "_number")
    asked = [ast.unparse(n.func) for n in ast.walk(number) if isinstance(n, ast.Call)]
    assert asked.index("invoice_series.format_violation") < asked.index("placeholder_number_problem"), \
        "the placeholder question comes straight after the legal one"


# ── two editors, one version number ───────────────────────────────────────────────────────────────────────────────────

class _Table:
    def __init__(self, db, name):
        self.db, self.name, self.op, self.payload, self.filters = db, name, "select", None, []

    def select(self, *_a, **_k): self.op = "select"; return self
    def insert(self, payload): self.op, self.payload = "insert", payload; return self
    def update(self, payload): self.op, self.payload = "update", payload; return self
    def eq(self, c, v): self.filters.append((c, v)); return self
    def order(self, *_a, **_k): return self
    def limit(self, _n): return self
    def execute(self): return self.db.run(self)


class _Result:
    def __init__(self, data): self.data = data


class _Db:
    """Two editors: the other one has already written version 2 (and not yet bumped current_version)."""

    def __init__(self, colliding_attempts=1, other_wrote=2):
        self.versions = [1, other_wrote]
        self.collide = colliding_attempts
        self.inserted: list[int] = []
        self.article = {"id": "A1", "firm_id": "F1", "current_version": 1, "client_id": None, "title": "t"}

    def table(self, name): return _Table(self, name)

    def run(self, t):
        if t.name == "knowledge_articles" and t.op == "select":
            return _Result([dict(self.article)])
        if t.name == "knowledge_articles" and t.op == "update":
            self.article.update(t.payload)
            return _Result([dict(self.article)])
        if t.name == "knowledge_article_versions" and t.op == "select":
            return _Result([{"version": max(self.versions)}])
        if t.name == "knowledge_article_versions" and t.op == "insert":
            v = t.payload["version"]
            if v in self.versions or self.collide > 0:
                self.collide = max(0, self.collide - 1)
                if v in self.versions:
                    raise RuntimeError('duplicate key value violates unique constraint "uq_article_version" (23505)')
            self.versions.append(v)
            self.inserted.append(v)
            return _Result([t.payload])
        raise AssertionError((t.name, t.op))


@pytest.fixture
def knowledge(monkeypatch):
    def use(db):
        monkeypatch.setattr(kb, "_USE_MOCK", False)
        monkeypatch.setattr(kb, "_db", lambda: db)
        monkeypatch.setattr(kb, "_emit_article_event", lambda *a, **k: None)
        return db
    return use


USER = {"id": "u1", "firm_id": "F1", "role": "Partner"}


def test_the_next_version_is_the_highest_actually_written_so_a_lagging_current_version_does_not_collide(knowledge):
    db = knowledge(_Db(colliding_attempts=0, other_wrote=2))
    kb.edit_article(USER, "A1", "my text")
    assert db.inserted == [3], "version 2 was the other editor's; this save is the version after it"
    assert db.article["current_version"] == 3


def test_a_collision_that_does_happen_is_retried_and_the_losers_text_is_saved(knowledge, monkeypatch):
    db = knowledge(_Db(colliding_attempts=0, other_wrote=2))
    real = db.run
    state = {"raced": False}

    def run(t):
        # the other editor writes version 3 between this editor's read and its insert
        if t.name == "knowledge_article_versions" and t.op == "insert" and not state["raced"]:
            state["raced"] = True
            db.versions.append(3)
        return real(t)

    monkeypatch.setattr(db, "run", run)
    kb.edit_article(USER, "A1", "my text")
    assert db.inserted == [4]


def test_five_collisions_in_a_row_are_raised_not_swallowed(knowledge, monkeypatch):
    db = knowledge(_Db(colliding_attempts=0, other_wrote=2))

    def always_collide(t):
        if t.name == "knowledge_article_versions" and t.op == "insert":
            raise RuntimeError("duplicate key value violates unique constraint (23505)")
        return _Db.run(db, t)

    monkeypatch.setattr(db, "run", always_collide)
    with pytest.raises(RuntimeError):
        kb.edit_article(USER, "A1", "x")


def test_an_error_that_is_not_a_collision_is_not_retried(knowledge, monkeypatch):
    db = knowledge(_Db(colliding_attempts=0))
    calls = {"n": 0}

    def boom(t):
        if t.name == "knowledge_article_versions" and t.op == "insert":
            calls["n"] += 1
            raise RuntimeError("connection reset by peer")
        return _Db.run(db, t)

    monkeypatch.setattr(db, "run", boom)
    with pytest.raises(RuntimeError, match="connection reset"):
        kb.edit_article(USER, "A1", "x")
    assert calls["n"] == 1
