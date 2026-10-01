"""A firm's monthly AI allowance, and the usage screen that reads what it used (ai-17).

WHAT WAS MISSING
    `check_rate_limit` was a per-minute, in-process window and nothing summed
    `ai_usage_events`, so one busy or misbehaving firm could run up the provider bill and
    nobody — the firm included — could see what the AI cost in tokens or pages.

WHAT THIS ASSERTS
    * the MONTH is the Indian one: a call at 23:30 UTC on 30 September is October's;
    * no limit is not zero, a limit of zero is refused where it is written, and a
      non-positive limit on a stored row never switches the AI off;
    * a token limit lets the call that crosses it finish and refuses the next; a page
      limit refuses a document that would take the firm past it BEFORE anything is sent;
    * a refusal reaches every caller as the `ProviderFailed` it already handles (429 and
      a sentence), leaves a usage row of its own, never reaches the provider's transport
      and is NOT noted as a provider failing;
    * the gate reads once a minute, counts a burst inside the process at once, fails OPEN
      (and remembers the failure for thirty seconds) and is never asked for the probe;
    * the screen's figures are folded from the database's grouped answers with the
      gateway's own outcome vocabulary, a grouped answer that reached PostgREST's row cap
      is reported as possibly cut, and the allowance is measured against the CURRENT
      month whichever month is being read;
    * the routes are Partner-only behind `mfa_guard`, the write validates strictly, is
      audited, and drops the firm's cached entry so it is felt at the next call.
"""
from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, mfa_guard
from core.ist_clock import IST
from domain.ai import budget, budget_gate, gateway, gemini_vision, groq_text
from services import ai_usage_service

FIRM = "firm-budget"
OTHER = "firm-other"
OCT = budget.month_of(dt.date(2026, 10, 15))
SEP = budget.month_of(dt.date(2026, 9, 15))

OK_BODY = {"choices": [{"message": {"content": "an answer"}, "finish_reason": "stop"}],
           "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50}}
MSG = [{"role": "user", "content": "When is GSTR-3B due?"}]


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    """Every test lives in October 2026 unless it says otherwise."""
    monkeypatch.setattr(budget_gate, "ist_today", lambda: dt.date(2026, 10, 15))
    monkeypatch.setattr("services.ai_usage_service.ist_today", lambda: dt.date(2026, 10, 15))
    monkeypatch.setattr("routers.ai_status.ist_today", lambda: dt.date(2026, 10, 15))
    monkeypatch.setenv("GROQ_TEXT_MODEL", "groq-primary")
    monkeypatch.delenv("GROQ_TEXT_MODEL_FALLBACK", raising=False)
    monkeypatch.setenv("GEMINI_VISION_MODEL", "gem-primary")
    monkeypatch.delenv("GEMINI_VISION_MODEL_FALLBACK", raising=False)


def _limits(tokens=None, pages=None):
    return budget.Limits(tokens, pages)


def _firm_has(tokens=None, pages=None, used_tokens=0, used_pages=0):
    """Give FIRM an allowance and a running total; returns the list of reads made."""
    reads: list[str] = []

    def fetch(firm_id, month):
        reads.append(firm_id)
        if firm_id != FIRM:
            return budget.Limits(), budget.Used()
        return _limits(tokens, pages), budget.Used(used_tokens, used_pages)
    budget_gate.set_fetcher(fetch)
    budget_gate.reset()
    return reads


# ── the month ────────────────────────────────────────────────────────────────

def test_a_call_after_midnight_in_india_belongs_to_the_next_month():
    late_utc = dt.datetime(2026, 9, 30, 23, 30, tzinfo=dt.timezone.utc)      # 05:00 IST on 1 Oct
    assert budget.month_for(late_utc).key == "2026-10"
    assert budget.month_for(dt.datetime(2026, 9, 30, 18, 29, tzinfo=dt.timezone.utc)).key == "2026-09"


def test_a_month_is_a_half_open_ist_window_expressed_as_utc():
    assert OCT.start_utc == "2026-09-30T18:30:00+00:00"
    assert OCT.end_utc == "2026-10-31T18:30:00+00:00"
    assert budget.month_of(dt.date(2026, 12, 3)).end.date() == dt.date(2027, 1, 1)
    assert OCT.label == "October 2026" and OCT.as_dict()["ends_before"] == "2026-11-01"


def test_a_naive_instant_is_read_as_utc():
    assert budget.month_for(dt.datetime(2026, 9, 30, 20, 0)).key == "2026-10"


@pytest.mark.parametrize("raw,key", [(None, "2026-10"), ("", "2026-10"), ("2026-09", "2026-09"),
                                     ("2025-10", "2025-10")])
def test_a_month_that_may_be_read(raw, key):
    assert budget.parse_month(raw, dt.date(2026, 10, 15)).key == key


@pytest.mark.parametrize("raw", ["2026-13", "2026-1", "October", "2026-00", "26-10", "2026-10-01"])
def test_a_month_written_badly_is_refused_in_words(raw):
    with pytest.raises(budget.BudgetError) as e:
        budget.parse_month(raw, dt.date(2026, 10, 15))
    assert "year-month" in str(e.value)


def test_a_month_that_has_not_started_or_is_too_old_is_refused():
    with pytest.raises(budget.BudgetError, match="not started"):
        budget.parse_month("2026-11", dt.date(2026, 10, 15))
    with pytest.raises(budget.BudgetError, match="last 12 months"):
        budget.parse_month("2025-09", dt.date(2026, 10, 15))


def test_the_choices_offered_are_exactly_the_months_that_are_accepted():
    today = dt.date(2026, 10, 15)
    choices = ai_usage_service.month_choices(today)
    assert len(choices) == budget.MONTHS_BACK + 1 and choices[0]["key"] == "2026-10"
    assert choices[-1]["key"] == "2025-10"
    for c in choices:
        assert budget.parse_month(c["key"], today).key == c["key"]


# ── the limits ───────────────────────────────────────────────────────────────

def test_a_limit_is_a_whole_number_from_one_or_nothing():
    assert budget.validate_limit(None, name="x", maximum=10) is None
    assert budget.validate_limit(1, name="x", maximum=10) == 1
    assert budget.validate_limit(10, name="x", maximum=10) == 10


@pytest.mark.parametrize("bad", [0, -5, True, False, 1.5, "7"])
def test_a_limit_that_is_not_a_positive_whole_number_is_refused(bad):
    with pytest.raises(budget.BudgetError):
        budget.validate_limit(bad, name="The token limit", maximum=10)


def test_zero_is_refused_because_it_reads_as_both_off_and_unlimited():
    with pytest.raises(budget.BudgetError, match="zero is not accepted"):
        budget.validate_limit(0, name="The token limit", maximum=10)


def test_a_limit_above_the_ceiling_is_refused_with_the_ceiling_named():
    with pytest.raises(budget.BudgetError, match="cannot be more than 1,00,00,000"):
        budget.validate_limit(10**7 + 1, name="The page limit", maximum=budget.MAX_PAGE_LIMIT)


def test_a_non_positive_stored_limit_is_not_set_and_never_refuses_everything():
    assert not budget.Limits(0, -3).any_set
    assert budget.check(budget.Limits(0, 0), budget.Used(10**9, 10**9), month=OCT,
                        feature="assistant", pages_wanted=5).allowed


# ── the decision ─────────────────────────────────────────────────────────────

def test_no_limit_means_every_call_may_go_ahead():
    assert budget.check(_limits(), budget.Used(10**12, 10**9), month=OCT, feature="x",
                        pages_wanted=3).allowed


def test_the_call_that_crosses_a_token_limit_finishes_and_the_next_is_refused():
    lim = _limits(tokens=1000)
    assert budget.check(lim, budget.Used(999, 0), month=OCT, feature="assistant").allowed
    refused = budget.check(lim, budget.Used(1000, 0), month=OCT, feature="assistant")
    assert not refused.allowed and refused.reason == "tokens"


def test_a_document_that_would_take_the_firm_past_its_pages_is_refused_whole():
    lim = _limits(pages=10)
    assert budget.check(lim, budget.Used(0, 7), month=OCT, feature="x", pages_wanted=3).allowed
    refused = budget.check(lim, budget.Used(0, 8), month=OCT, feature="x", pages_wanted=3)
    assert not refused.allowed and refused.reason == "pages"
    assert "3-page document" in refused.sentence and "8 of 10 pages" in refused.sentence


def test_a_page_limit_does_not_refuse_a_call_that_sends_no_pages():
    assert budget.check(_limits(pages=1), budget.Used(0, 5), month=OCT, feature="assistant",
                        pages_wanted=0).allowed


def test_the_probe_is_never_refused_for_want_of_an_allowance():
    assert budget.check(_limits(tokens=1), budget.Used(10**6, 0), month=OCT, feature="probe").allowed


def test_the_refusal_says_the_month_the_figures_the_remedy_and_that_nothing_was_sent():
    s = budget.check(_limits(tokens=12_00_000), budget.Used(12_34_567, 0), month=OCT,
                     feature="assistant").sentence
    assert "October 2026" in s and "12,34,567 of 12,00,000 tokens" in s
    assert "counted from 1 October IST" in s
    assert "A Partner can raise or remove the limit" in s and "Nothing was sent" in s


def test_the_standing_reports_remaining_and_whether_a_limit_was_reached():
    s = budget.standing(_limits(tokens=100, pages=10), budget.Used(40, 10), month=OCT)
    assert s["tokens"] == {"limit": 100, "used": 40, "remaining": 60, "reached": False}
    assert s["pages"]["reached"] is True and s["reached"] is True
    assert "page allowance" in s["sentence"]
    nothing = budget.standing(_limits(), budget.Used(5, 5), month=OCT)
    assert nothing["tokens"]["limit"] is None and nothing["reached"] is False
    assert nothing["sentence"] is None


def test_the_standing_sentence_is_the_very_refusal_a_call_would_get():
    lim, used = _limits(tokens=100), budget.Used(100, 0)
    assert budget.standing(lim, used, month=OCT)["sentence"] == budget.check(
        lim, used, month=OCT, feature="assistant").sentence


# ── what the month's rows add up to ──────────────────────────────────────────

def _day(day, outcome, attempts, first, tokens=0, reasoning=0, pages=0):
    return {"day": day, "outcome": outcome, "attempts": attempts, "first_attempts": first,
            "tokens": tokens, "reasoning_tokens": reasoning, "pages": pages}


def _feat(provider, feature, model, outcome, attempts, first, tokens=0, reasoning=0, pages=0):
    return {"provider": provider, "feature": feature, "model": model, "outcome": outcome,
            "attempts": attempts, "first_attempts": first, "tokens": tokens,
            "reasoning_tokens": reasoning, "pages": pages}


def test_a_call_is_a_first_attempt_so_a_retry_is_not_a_second_call():
    out = budget.fold(
        [_day("2026-10-02", "provider_error", 1, 0), _day("2026-10-02", "ok", 1, 1, tokens=50)],
        [])
    t = out["totals"]
    assert (t["calls"], t["attempts"], t["answered"], t["failed"]) == (1, 2, 1, 1)


def test_the_gateways_own_vocabulary_decides_what_is_an_answer_a_failure_or_a_refusal():
    rows = [_day("2026-10-02", o, 1, 1) for o in
            ("ok", "truncated", "empty_reply", "model_gone", "param_rejected", "budget_exhausted")]
    t = budget.fold(rows, [])["totals"]
    assert t["answered"] == 2, "ok and truncated are answers"
    assert t["failed"] == 2, "the gateway's own retry-without-the-hint is not a failure"
    assert t["refused"] == 1


def test_the_months_figures_are_summed_by_day_and_by_feature():
    days = [_day("2026-10-02", "ok", 3, 3, tokens=300, reasoning=30, pages=0),
            _day("2026-10-01", "ok", 2, 2, tokens=100, pages=4)]
    feats = [_feat("groq", "assistant", "m1", "ok", 3, 3, tokens=300, reasoning=30),
             _feat("gemini", "invoice_extraction", "g1", "ok", 2, 2, tokens=100, pages=4),
             _feat("groq", "assistant", "m2", "ok", 1, 1, tokens=0)]
    out = budget.fold(days, feats)
    assert [d["day"] for d in out["by_day"]] == ["2026-10-01", "2026-10-02"]
    assert out["totals"]["tokens"] == 400 and out["totals"]["pages"] == 4
    assert out["totals"]["reasoning_tokens"] == 30
    top = out["by_feature"][0]
    assert (top["feature"], top["provider"], top["tokens"]) == ("assistant", "groq", 300)
    assert top["models"] == ["m1", "m2"], "two models behind one feature are listed, sorted"
    assert out["truncated"] is False


def test_a_grouped_answer_that_reached_the_row_cap_is_reported_as_possibly_cut():
    rows = [_day(f"2026-10-{(i % 28) + 1:02d}", f"o{i}", 1, 1) for i in range(budget.ROW_CAP)]
    assert budget.fold(rows, [])["truncated"] is True
    assert budget.fold(rows[:-1], [])["truncated"] is False
    assert budget.fold([], [_feat("g", "f", "m", f"o{i}", 1, 1) for i in range(budget.ROW_CAP)])[
        "truncated"] is True


def test_garbage_in_a_row_reads_as_zero_not_as_a_crash():
    out = budget.fold([{"day": None, "outcome": None, "attempts": "x", "tokens": None}], [])
    assert out["totals"]["attempts"] == 0


# ── the gate ─────────────────────────────────────────────────────────────────

def test_a_firm_with_no_allowance_is_never_refused_and_costs_one_read_a_minute():
    reads = _firm_has()
    for _ in range(5):
        budget_gate.enforce(FIRM, "assistant")
    assert reads == [FIRM]


def test_nothing_is_asked_for_a_call_with_no_firm_or_for_the_probe():
    reads = _firm_has(tokens=1, used_tokens=10**6)
    budget_gate.enforce(None, "assistant")
    budget_gate.enforce("", "assistant")
    budget_gate.enforce(FIRM, "probe")
    assert reads == []


def test_with_no_database_and_no_fetcher_no_allowance_can_exist(monkeypatch):
    budget_gate.set_fetcher(None)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    budget_gate.enforce(FIRM, "assistant")           # returns; there is nothing to read


def test_a_firm_over_its_token_limit_is_refused_with_the_classified_failure():
    _firm_has(tokens=1000, used_tokens=1000)
    with pytest.raises(gateway.ProviderFailed) as e:
        budget_gate.enforce(FIRM, "assistant")
    assert (e.value.kind, e.value.http_status) == (gateway.BUDGET, 429)
    assert "1,000 of 1,000 tokens" in e.value.sentence


def test_one_firms_allowance_is_not_anothers():
    _firm_has(tokens=1, used_tokens=10)
    budget_gate.enforce(OTHER, "assistant")          # no allowance for this firm: no refusal


def test_the_allowance_is_trusted_for_a_minute_and_then_read_again(monkeypatch):
    reads = _firm_has(tokens=10**6)
    now = [1000.0]
    monkeypatch.setattr(budget_gate, "_clock", lambda: now[0])
    budget_gate.enforce(FIRM, "assistant")
    now[0] += budget_gate.TTL_S - 1
    budget_gate.enforce(FIRM, "assistant")
    assert len(reads) == 1
    now[0] += 2
    budget_gate.enforce(FIRM, "assistant")
    assert len(reads) == 2


def test_a_new_month_reads_afresh_even_inside_the_minute(monkeypatch):
    reads = _firm_has(tokens=10**6)
    budget_gate.enforce(FIRM, "assistant")
    monkeypatch.setattr(budget_gate, "ist_today", lambda: dt.date(2026, 11, 1))
    budget_gate.enforce(FIRM, "assistant")
    assert len(reads) == 2


def test_a_burst_inside_the_process_is_counted_at_once_not_a_minute_late():
    reads = _firm_has(tokens=100)
    budget_gate.enforce(FIRM, "assistant")
    gateway.record(gateway.UsageEvent(
        firm_id=FIRM, user_id=None, feature="assistant", provider="groq", model="m",
        call_id="c", attempt=1, outcome="ok", latency_ms=1, total_tokens=60, input_units=None))
    budget_gate.enforce(FIRM, "assistant")           # 60 of 100: allowed
    gateway.record(gateway.UsageEvent(
        firm_id=FIRM, user_id=None, feature="assistant", provider="groq", model="m",
        call_id="c2", attempt=1, outcome="ok", latency_ms=1, total_tokens=60))
    with pytest.raises(gateway.ProviderFailed):
        budget_gate.enforce(FIRM, "assistant")        # 120 of 100, no re-read needed
    assert len(reads) == 1


def test_pages_are_counted_the_same_way():
    _firm_has(pages=5)
    budget_gate.enforce(FIRM, "invoice_extraction", pages_wanted=3)
    gateway.record(gateway.UsageEvent(
        firm_id=FIRM, user_id=None, feature="invoice_extraction", provider="gemini", model="g",
        call_id="c", attempt=1, outcome="ok", latency_ms=1, input_units=3))
    with pytest.raises(gateway.ProviderFailed) as e:
        budget_gate.enforce(FIRM, "invoice_extraction", pages_wanted=3)
    assert "3-page document" in e.value.sentence


def test_an_attempt_for_a_firm_that_is_not_cached_is_ignored():
    gateway.record(gateway.UsageEvent(
        firm_id=FIRM, user_id=None, feature="x", provider="groq", model="m", call_id="c",
        attempt=1, outcome="ok", latency_ms=1, total_tokens=10**9))
    reads = _firm_has(tokens=100)
    budget_gate.enforce(FIRM, "assistant")           # the first read sees the DATABASE's total
    assert len(reads) == 1


def test_an_unreadable_allowance_lets_the_call_through_and_is_remembered_for_thirty_seconds(
        monkeypatch, caplog):
    attempts: list[int] = []

    def broken(firm_id, month):
        attempts.append(1)
        raise RuntimeError("relation ai_firm_budgets does not exist")
    budget_gate.set_fetcher(broken)
    budget_gate.reset()
    now = [500.0]
    monkeypatch.setattr(budget_gate, "_clock", lambda: now[0])
    for _ in range(4):
        budget_gate.enforce(FIRM, "assistant")        # never raises
    assert len(attempts) == 1, "a database that is down is not asked again on every call"
    assert "could not read the allowance" in caplog.text
    now[0] += budget_gate.UNREADABLE_TTL_S + 1
    budget_gate.enforce(FIRM, "assistant")
    assert len(attempts) == 2


def test_dropping_a_firms_entry_makes_the_next_call_read_its_allowance_again():
    reads = _firm_has(tokens=10**6)
    budget_gate.enforce(FIRM, "assistant")
    budget_gate.invalidate(FIRM)
    budget_gate.enforce(FIRM, "assistant")
    assert len(reads) == 2


class _Db:
    """The two reads the gate makes, and what they were asked."""

    def __init__(self, budget_row=None, totals=None):
        self.budget_row, self.totals, self.calls = budget_row, totals, []

    class _Q:
        def __init__(self, db, name):
            self.db, self.name, self.filters = db, name, {}

        def select(self, cols="*", **_):
            self.db.calls.append(("select", self.name, cols))
            return self

        def eq(self, k, v):
            self.filters[k] = v
            return self

        def limit(self, n):
            return self

        def execute(self):
            rows = [self.db.budget_row] if (self.name == "ai_firm_budgets" and self.db.budget_row) else []
            return type("R", (), {"data": rows})()

    def table(self, name):
        return _Db._Q(self, name)

    def rpc(self, fn, params):
        self.calls.append(("rpc", fn, params))
        return type("X", (), {"execute": lambda s: type("R", (), {"data": self.totals or []})()})()


def test_the_default_read_is_one_table_read_for_a_firm_with_no_allowance_and_no_aggregate(monkeypatch):
    db = _Db()
    monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: db)
    limits, used = budget_gate.default_fetch(FIRM, OCT)
    assert not limits.any_set and used == budget.Used()
    assert [c[0] for c in db.calls] == ["select"], "no aggregate is read when there is nothing to measure against"


def test_the_default_read_asks_the_aggregate_for_this_firm_and_this_months_window(monkeypatch):
    db = _Db({"monthly_token_limit": 5000, "monthly_page_limit": None},
             totals=[{"tokens": 1234, "pages": 7}])
    monkeypatch.setattr("core.supabase_client.get_service_supabase", lambda: db)
    limits, used = budget_gate.default_fetch(FIRM, OCT)
    assert limits.monthly_tokens == 5000 and limits.monthly_pages is None
    assert used == budget.Used(1234, 7)
    fn, params = db.calls[-1][1], db.calls[-1][2]
    assert fn == "ai_usage_totals"
    assert params == {"p_firm": FIRM, "p_from": OCT.start_utc, "p_to": OCT.end_utc}


# ── the doors ────────────────────────────────────────────────────────────────

def _transport():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)
    return httpx.MockTransport(handler), seen


def _ask(transport, **kw):
    import asyncio
    return asyncio.run(groq_text.chat(
        MSG, api_key="k", max_tokens=100, transport=transport,
        feature=kw.pop("feature", "assistant"), firm_id=kw.pop("firm_id", FIRM), **kw))


def test_a_refused_call_never_reaches_the_providers_transport(ai_usage_events):
    _firm_has(tokens=1000, used_tokens=1000)
    transport, seen = _transport()
    with pytest.raises(gateway.ProviderFailed) as e:
        _ask(transport, user_id="u-1")
    assert seen == [], "nothing was sent to the provider"
    assert (e.value.kind, e.value.http_status) == (gateway.BUDGET, 429)
    assert "Nothing was sent to the AI provider" in e.value.sentence


def test_a_refusal_leaves_a_usage_row_of_its_own(ai_usage_events):
    _firm_has(tokens=1000, used_tokens=1000)
    transport, _ = _transport()
    with pytest.raises(gateway.ProviderFailed):
        _ask(transport, user_id="u-1")
    row = ai_usage_events[-1]
    assert (row.firm_id, row.user_id, row.feature, row.provider, row.model) == (
        FIRM, "u-1", "assistant", "groq", "groq-primary")
    assert (row.outcome, row.attempt, row.latency_ms, row.http_status) == ("budget_exhausted", 1, 0, 429)
    assert row.total_tokens is None and row.input_units is None


def test_a_refusal_does_not_make_the_provider_look_like_it_is_failing(ai_usage_events):
    _firm_has(tokens=1000, used_tokens=1000)
    transport, _ = _transport()
    with pytest.raises(gateway.ProviderFailed):
        _ask(transport)
    assert gateway.last_attempt("groq") is None
    assert gateway.provider_status("groq", configured=True) == gateway.STATUS_UNVERIFIED


def test_a_call_inside_the_allowance_goes_ahead_and_adds_to_the_running_total(ai_usage_events):
    _firm_has(tokens=100, used_tokens=0)
    transport, seen = _transport()
    _ask(transport)                       # 50 tokens
    _ask(transport)                       # 100: the call that reaches it still finished
    assert len(seen) == 2
    with pytest.raises(gateway.ProviderFailed):
        _ask(transport)
    assert len(seen) == 2


def test_the_probe_goes_through_even_when_the_firm_is_over_its_allowance():
    _firm_has(tokens=1, used_tokens=10**6)
    transport, seen = _transport()
    _ask(transport, feature="probe")
    assert len(seen) == 1


def test_a_call_with_no_firm_is_not_limited():
    _firm_has(tokens=1, used_tokens=10**6)
    transport, seen = _transport()
    import asyncio
    asyncio.run(groq_text.chat(MSG, api_key="k", max_tokens=100, transport=transport,
                               feature="assistant", firm_id=None))
    assert len(seen) == 1


def test_a_gate_that_blows_up_never_takes_the_ai_down(monkeypatch, caplog):
    def boom(*_a, **_k):
        raise RuntimeError("a bug in the gate")
    monkeypatch.setattr(budget_gate, "enforce", boom)
    transport, seen = _transport()
    _ask(transport)
    assert len(seen) == 1 and "the gate failed" in caplog.text


class _GemResp:
    def __init__(self):
        self.text = "read it"
        self.usage_metadata = type("U", (), dict(
            prompt_token_count=8, candidates_token_count=2,
            thoughts_token_count=0, total_token_count=10))()


@pytest.fixture
def gemini(monkeypatch):
    made: list[int] = []

    class _Models:
        def generate_content(self, **kwargs):
            return _GemResp()

    class _Client:
        def __init__(self, **kw):
            made.append(1)
            self.models = _Models()

    monkeypatch.setattr("google.genai.Client", _Client)
    return made


def _see(pages, **kw):
    return gemini_vision.generate(api_key="k", images=[b"p"] * pages, mime="image/png",
                                  prompt="read it", feature="invoice_extraction",
                                  firm_id=kw.pop("firm_id", FIRM), **kw)


def test_a_document_past_the_page_allowance_is_refused_before_a_client_is_even_built(
        gemini, ai_usage_events):
    _firm_has(pages=10, used_pages=8)
    with pytest.raises(gateway.ProviderFailed) as e:
        _see(3)
    assert gemini == [], "nothing was sent: a document is refused whole, never read in part"
    assert e.value.kind == gateway.BUDGET and "3-page document" in e.value.sentence
    row = ai_usage_events[-1]
    assert (row.provider, row.model, row.outcome) == ("gemini", "gem-primary", "budget_exhausted")


def test_a_document_that_fits_goes_ahead_and_its_pages_are_counted(gemini, ai_usage_events):
    _firm_has(pages=10, used_pages=0)
    assert _see(2) == "read it"
    assert ai_usage_events[-1].input_units == 2
    assert _see(2) == "read it" and _see(2) == "read it"       # 6 of 10
    with pytest.raises(gateway.ProviderFailed):
        _see(5)                                                  # 6 + 5 > 10
    assert _see(4) == "read it"                                  # 6 + 4 == 10 fits exactly


# ── the service ──────────────────────────────────────────────────────────────

class _Reader:
    """The reads the usage section makes."""

    def __init__(self, by_day=None, by_feature=None, totals=None, budget_row=None,
                 first="2026-10-01T05:00:00+00:00", fail=False):
        self.by_day, self.by_feature, self.totals = by_day or [], by_feature or [], totals or []
        self.budget_row, self.first, self.fail, self.rpcs, self.upserts = budget_row, first, fail, [], []

    class _Q:
        def __init__(self, db, name):
            self.db, self.name, self.payload = db, name, None

        def select(self, *_a, **_k): return self
        def eq(self, *_a): return self
        def order(self, *_a, **_k): return self
        def limit(self, *_a): return self

        def upsert(self, payload, **kw):
            self.db.upserts.append((self.name, payload, kw))
            self.payload = payload
            return self

        def execute(self):
            if self.db.fail:
                raise RuntimeError("down")
            if self.name == "ai_firm_budgets":
                return type("R", (), {"data": [self.db.budget_row] if self.db.budget_row else []})()
            if self.name == "ai_usage_events":
                return type("R", (), {"data": [{"created_at": self.db.first}] if self.db.first else []})()
            return type("R", (), {"data": []})()

    def table(self, name):
        return _Reader._Q(self, name)

    def rpc(self, fn, params):
        self.rpcs.append((fn, params))
        data = {"ai_usage_by_day": self.by_day, "ai_usage_by_feature": self.by_feature,
                "ai_usage_totals": self.totals}[fn]
        if self.fail:
            raise RuntimeError("down")
        return type("X", (), {"execute": lambda s: type("R", (), {"data": data})()})()


def test_the_usage_is_folded_from_the_two_grouped_answers_and_measured_against_the_allowance():
    db = _Reader(by_day=[_day("2026-10-02", "ok", 2, 2, tokens=900)],
                 by_feature=[_feat("groq", "assistant", "m", "ok", 2, 2, tokens=900)],
                 budget_row={"monthly_token_limit": 1000, "monthly_page_limit": None,
                             "updated_at": "2026-10-01T06:00:00+00:00"})
    out = ai_usage_service.usage(db, FIRM, OCT)
    assert out["usage"]["totals"]["tokens"] == 900
    assert out["allowance"]["limits"] == {"monthly_tokens": 1000, "monthly_pages": None}
    assert out["allowance"]["standing"]["tokens"]["remaining"] == 100
    assert out["unread"] is None and out["first_recorded_at"] == "2026-10-01T05:00:00+00:00"
    assert [fn for fn, _ in db.rpcs] == ["ai_usage_by_day", "ai_usage_by_feature"], (
        "reading the current month needs no third read")
    for _, params in db.rpcs:
        assert params == {"p_firm": FIRM, "p_from": OCT.start_utc, "p_to": OCT.end_utc}


def test_reading_an_earlier_month_still_measures_the_allowance_against_this_month():
    db = _Reader(by_day=[_day("2026-09-10", "ok", 1, 1, tokens=999_999)],
                 totals=[{"tokens": 50, "pages": 0}],
                 budget_row={"monthly_token_limit": 100, "monthly_page_limit": None, "updated_at": None})
    out = ai_usage_service.usage(db, FIRM, SEP)
    assert out["usage"]["totals"]["tokens"] == 999_999            # September's own figures
    assert out["allowance"]["standing"]["tokens"]["used"] == 50   # October's against the limit
    assert out["allowance"]["standing"]["reached"] is False
    totals_call = next(p for fn, p in db.rpcs if fn == "ai_usage_totals")
    assert totals_call["p_from"] == OCT.start_utc and out["current_month"]["key"] == "2026-10"


def test_with_no_database_the_usage_is_unread_and_says_so_not_an_empty_month():
    out = ai_usage_service.usage(None, FIRM, OCT)
    assert out["usage"] is None and out["allowance"] is None
    assert out["unread"] == ai_usage_service.NO_DATABASE


def test_a_failed_read_is_said_so_and_does_not_raise():
    out = ai_usage_service.usage(_Reader(fail=True), FIRM, OCT)
    assert out["usage"] is None and "could not be read" in out["unread"]


def test_what_the_screen_does_not_cover_is_on_every_answer():
    for out in (ai_usage_service.usage(None, FIRM, OCT), ai_usage_service.usage(_Reader(), FIRM, OCT)):
        text = " ".join(out["not_covered"])
        assert "No rupee figure" in text and "usage record began" in text and "Check now" in text


def test_setting_the_allowance_writes_both_limits_for_this_firm_and_drops_its_cached_entry():
    reads = _firm_has(tokens=10**6)
    budget_gate.enforce(FIRM, "assistant")
    assert len(reads) == 1
    db = _Reader(budget_row={"monthly_token_limit": 7, "monthly_page_limit": 3, "updated_at": None})
    previous = ai_usage_service.set_limits(db, FIRM, "user-1", budget.Limits(500, None))
    name, payload, kw = db.upserts[0]
    assert name == "ai_firm_budgets" and kw == {"on_conflict": "firm_id"}
    assert (payload["firm_id"], payload["monthly_token_limit"], payload["monthly_page_limit"],
            payload["set_by"]) == (FIRM, 500, None, "user-1")
    assert previous == budget.Limits(7, 3)
    budget_gate.enforce(FIRM, "assistant")
    assert len(reads) == 2, "the change is felt at the next call, not a minute later"


# ── the routes ───────────────────────────────────────────────────────────────

def _user(role, uid="u1"):
    return {"id": uid, "firm_id": FIRM, "role": role, "email": f"{uid}@f.test",
            "auth_user_id": f"auth-{uid}"}


def _client(user):
    from routers import ai_status
    app = FastAPI()
    app.include_router(ai_status.router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def db_present(monkeypatch):
    import routers.ai_status as mod
    db = _Reader()
    monkeypatch.setattr(mod, "_db", lambda: db)
    audit: list = []
    monkeypatch.setattr(mod, "log_event", lambda *a, **k: audit.append((a, k)))
    return type("S", (), {"db": db, "audit": audit})


@pytest.mark.parametrize("role", ["Manager", "Executive", "Reviewer"])
def test_nobody_below_a_partner_reads_the_usage_or_sets_the_allowance(role, db_present):
    c = _client(_user(role))
    assert c.get("/api/ai-status/usage").status_code == 403
    assert c.put("/api/ai-status/budget",
                 json={"monthly_token_limit": 5, "monthly_page_limit": None}).status_code == 403
    assert db_present.db.upserts == [] and db_present.audit == []


def test_a_partner_reads_the_usage_for_the_current_month_by_default(db_present):
    res = _client(_user("Partner")).get("/api/ai-status/usage")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["month"]["key"] == "2026-10" and data["usage"]["totals"]["calls"] == 0
    assert len(data["choices"]) == 13


def test_a_partner_reads_an_earlier_month(db_present):
    data = _client(_user("Partner")).get("/api/ai-status/usage?month=2026-09").json()["data"]
    assert data["month"]["key"] == "2026-09" and data["current_month"]["key"] == "2026-10"


@pytest.mark.parametrize("month", ["2026-13", "nonsense", "2026-11", "2024-01"])
def test_a_month_that_cannot_be_read_is_a_422_in_words(month, db_present):
    res = _client(_user("Partner")).get(f"/api/ai-status/usage?month={month}")
    assert res.status_code == 422 and res.json()["detail"]


def test_with_no_database_the_usage_route_answers_unread_not_an_error(monkeypatch):
    import routers.ai_status as mod
    monkeypatch.setattr(mod, "_db", lambda: None)
    data = _client(_user("Partner")).get("/api/ai-status/usage").json()["data"]
    assert data["usage"] is None and data["unread"] == ai_usage_service.NO_DATABASE


def test_setting_the_allowance_without_a_database_is_a_503_in_words(monkeypatch):
    import routers.ai_status as mod
    monkeypatch.setattr(mod, "_db", lambda: None)
    res = _client(_user("Partner")).put(
        "/api/ai-status/budget", json={"monthly_token_limit": 5, "monthly_page_limit": None})
    assert res.status_code == 503 and "no database" in res.json()["detail"]


def test_a_partner_sets_the_allowance_and_it_is_audited(db_present):
    res = _client(_user("Partner", "p1")).put(
        "/api/ai-status/budget",
        json={"monthly_token_limit": 12_00_000, "monthly_page_limit": 400})
    assert res.status_code == 200
    assert db_present.db.upserts[0][1]["monthly_token_limit"] == 12_00_000
    (args, kwargs), = db_present.audit
    assert args[:4] == (FIRM, "ai_firm_budget", FIRM, "update")
    assert kwargs["actor_id"] == "auth-p1", "the audit log takes the AUTH id"
    assert kwargs["new_data"] == {"monthly_tokens": 12_00_000, "monthly_pages": 400}
    assert kwargs["old_data"] == {"monthly_tokens": None, "monthly_pages": None}
    assert res.json()["data"]["month"]["key"] == "2026-10"


def test_null_clears_a_limit(db_present):
    res = _client(_user("Partner")).put(
        "/api/ai-status/budget", json={"monthly_token_limit": None, "monthly_page_limit": None})
    assert res.status_code == 200
    assert db_present.db.upserts[0][1]["monthly_token_limit"] is None


@pytest.mark.parametrize("body", [
    {"monthly_token_limit": 0, "monthly_page_limit": None},
    {"monthly_token_limit": -1, "monthly_page_limit": None},
    {"monthly_token_limit": None, "monthly_page_limit": 0},
    {"monthly_token_limit": True, "monthly_page_limit": None},
    {"monthly_token_limit": "5", "monthly_page_limit": None},
    {"monthly_token_limit": 1.5, "monthly_page_limit": None},
    {"monthly_token_limit": 10**12 + 1, "monthly_page_limit": None},
    {"monthly_token_limit": None, "monthly_page_limit": 10**7 + 1},
    {"monthly_token_limit": 5},
    {},
])
def test_a_limit_that_is_not_a_positive_whole_number_is_refused_and_nothing_is_written(body, db_present):
    res = _client(_user("Partner")).put("/api/ai-status/budget", json=body)
    assert res.status_code == 422
    assert db_present.db.upserts == [] and db_present.audit == []


def test_both_new_routes_sit_behind_the_mfa_guard():
    import routers.ai_status as mod
    wanted = {"/api/ai-status/usage", "/api/ai-status/budget"}
    found = set()
    for route in mod.router.routes:
        if route.path in wanted:
            found.add(route.path)
            assert any(d.dependency is mfa_guard for d in route.dependencies), route.path
    assert found == wanted


def test_the_budget_route_is_not_one_the_model_route_scan_wants_limited():
    """Reading and setting an allowance makes no model call; the probe is the one route
    in this router that does, and it is limited."""
    import inspect
    import routers.ai_status as mod
    from tests.test_every_route_that_reaches_a_model_is_rate_limited import MODEL_MARKERS
    for fn in (mod.ai_usage, mod.set_ai_budget):
        code = inspect.getsource(fn)
        assert not any(m in code for m in MODEL_MARKERS)


def test_the_budget_outcome_is_a_named_outcome_with_a_decision():
    assert gateway.BUDGET in gateway.OUTCOMES
    assert gateway.decide(gateway.BUDGET, 1) == gateway.STOP
    assert gateway.BUDGET in gateway.NOT_ABOUT_THE_PROVIDER
