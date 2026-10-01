"""Migration 476 on real PostgreSQL — a firm's optional monthly AI allowance and the three
aggregates the usage screen and the budget gate read (ai-17).

WHAT IS PROVEN HERE
    * `ai_firm_budgets` has exactly the columns the service reads and writes; one row per
      firm; a NULL limit is accepted (no limit — every firm's position today) and ZERO or a
      negative one is refused; deleting a firm takes its allowance with it;
    * RLS is on; a Partner reads their OWN firm's allowance and not another firm's; an
      Executive of the same firm reads none; and no signed-in session can write one (the API
      writes it as the service role, after rbac());
    * the three functions are NOT executable by `authenticated` (they take the firm as an
      argument, so granting them would let any signed-in user read any firm's usage by naming
      it) and are executable by `service_role`;
    * the day is the IST day (an attempt at 00:30 IST on the 1st lands on the 1st, not on
      the last day of the month before), the window is half-open, another firm's rows are
      never counted, `first_attempts` counts CALLS and not retries, and tokens and pages are
      summed over EVERY attempt including the failed ones;
    * the three functions agree with one another and with `budget.fold` (the Python fold
      of the two grouped answers gives the same totals as the SQL total);
    * the projections the service and the gate write are literals naming only columns the
      table has.

Runs only when HARNESS_PG is set + psql is on PATH, like every *_pg test; it cannot run in
the mock-mode job.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "47600000-0000-0000-0000-0000000000f1"
OTHER_FIRM = "47600000-0000-0000-0000-0000000000f2"
PARTNER_ID = "47600000-0000-0000-0000-00000000b001"
EXEC_ID = "47600000-0000-0000-0000-00000000b002"
OTHER_PARTNER_ID = "47600000-0000-0000-0000-00000000b003"
PARTNER_AUTH = "47600000-0000-0000-0000-00000000a001"
EXEC_AUTH = "47600000-0000-0000-0000-00000000a002"
OTHER_PARTNER_AUTH = "47600000-0000-0000-0000-00000000a003"

EXPECTED_COLUMNS = {"firm_id", "monthly_token_limit", "monthly_page_limit", "set_by", "updated_at"}
API = Path(__file__).resolve().parents[1]


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def _rows(dsn: str, sql: str) -> list[dict]:
    """The query's rows as dicts, through `jsonb_agg` (one line, unlike `json_agg`, which
    breaks between elements) so no column parsing is guessed at."""
    out = _scalar(dsn, f"SELECT COALESCE(jsonb_agg(to_jsonb(t)), '[]'::jsonb) FROM ({sql}) t;")
    return json.loads(out)


def _as(dsn: str, auth_uid: str, sql: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; "
                      f"SET ROLE authenticated; {sql}")


def _as_scalar(dsn: str, auth_uid: str, sql: str) -> str:
    return _scalar(dsn, f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; "
                        f"SET ROLE authenticated; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m476_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{PARTNER_AUTH}', 'p@t.in'), ('{EXEC_AUTH}', 'e@t.in'),
              ('{OTHER_PARTNER_AUTH}', 'op@t.in');
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}', 'F1', 'f1@t.in'), ('{OTHER_FIRM}', 'F2', 'f2@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
              ('{PARTNER_ID}', '{FIRM}', '{PARTNER_AUTH}', 'p@t.in', 'Partner', 'Partner', true),
              ('{EXEC_ID}', '{FIRM}', '{EXEC_AUTH}', 'e@t.in', 'Exec', 'Executive', true),
              ('{OTHER_PARTNER_ID}', '{OTHER_FIRM}', '{OTHER_PARTNER_AUTH}', 'op@t.in',
               'Other', 'Partner', true);
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _budget(firm: str = FIRM, tokens="NULL", pages="NULL") -> str:
    return (f"INSERT INTO public.ai_firm_budgets (firm_id, monthly_token_limit, monthly_page_limit) "
            f"VALUES ('{firm}', {tokens}, {pages});")


def _event(at: str, *, firm: str = FIRM, call: str = "c", attempt: int = 1,
           outcome: str = "ok", feature: str = "assistant", provider: str = "groq",
           model: str = "m1", tokens: int = 0, reasoning: int = 0, pages: int = 0) -> str:
    return (f"INSERT INTO public.ai_usage_events (firm_id, feature, provider, model, call_id, "
            f"attempt, outcome, latency_ms, total_tokens, reasoning_tokens, input_units, created_at) "
            f"VALUES ('{firm}', '{feature}', '{provider}', '{model}', '{call}', {attempt}, "
            f"'{outcome}', 10, {tokens}, {reasoning}, {pages}, '{at}');")


def _seed(db: str, *events: str) -> None:
    r = _psql(db, "\n".join(events))
    assert r.returncode == 0, r.stderr


FROM = "2026-09-30T18:30:00Z"      # 00:00 IST on 1 October
TO = "2026-10-31T18:30:00Z"        # 00:00 IST on 1 November


def _by_day(db: str, firm: str = FIRM, frm: str = FROM, to: str = TO) -> list[dict]:
    return _rows(db, f"SELECT * FROM public.ai_usage_by_day('{firm}', '{frm}', '{to}')")


def _by_feature(db: str, firm: str = FIRM, frm: str = FROM, to: str = TO) -> list[dict]:
    return _rows(db, f"SELECT * FROM public.ai_usage_by_feature('{firm}', '{frm}', '{to}')")


def _totals(db: str, firm: str = FIRM, frm: str = FROM, to: str = TO) -> dict:
    return _rows(db, f"SELECT * FROM public.ai_usage_totals('{firm}', '{frm}', '{to}')")[0]


# ── the table ────────────────────────────────────────────────────────────────

def test_the_table_has_exactly_the_columns_the_service_reads_and_writes(db):
    got = set(_scalar(db, "SELECT string_agg(column_name, ',') FROM information_schema.columns "
                          "WHERE table_schema='public' AND table_name='ai_firm_budgets';").split(","))
    assert got == EXPECTED_COLUMNS


def test_a_firm_with_no_limit_set_is_a_row_of_nulls_and_no_row_at_all_is_the_same_answer(db):
    """NULL is "no limit"; it is what every firm has until a Partner chooses otherwise, and
    there is no default value on either column."""
    assert _psql(db, _budget()).returncode == 0
    row = _rows(db, f"SELECT monthly_token_limit, monthly_page_limit FROM public.ai_firm_budgets "
                    f"WHERE firm_id = '{FIRM}'")[0]
    assert row == {"monthly_token_limit": None, "monthly_page_limit": None}
    defaults = _scalar(db, "SELECT count(*) FROM information_schema.columns "
                           "WHERE table_schema='public' AND table_name='ai_firm_budgets' "
                           "AND column_name IN ('monthly_token_limit','monthly_page_limit') "
                           "AND column_default IS NOT NULL;")
    assert defaults == "0"


def test_each_limit_can_be_set_alone_and_the_other_stays_unset(db):
    assert _psql(db, _budget(tokens="5000000")).returncode == 0
    assert _psql(db, _budget(OTHER_FIRM, pages="300")).returncode == 0
    mine = _rows(db, f"SELECT * FROM public.ai_firm_budgets WHERE firm_id = '{FIRM}'")[0]
    theirs = _rows(db, f"SELECT * FROM public.ai_firm_budgets WHERE firm_id = '{OTHER_FIRM}'")[0]
    assert (mine["monthly_token_limit"], mine["monthly_page_limit"]) == (5000000, None)
    assert (theirs["monthly_token_limit"], theirs["monthly_page_limit"]) == (None, 300)


@pytest.mark.parametrize("bad", [
    {"tokens": "0"}, {"tokens": "-1"}, {"pages": "0"}, {"pages": "-7"},
])
def test_a_zero_or_negative_limit_is_refused(db, bad):
    """Zero would mean "the AI is off" to one reader and "no limit" to another; the way to
    say no limit is NULL and the way to turn the AI off is not to set an allowance."""
    assert _psql(db, _budget(**bad)).returncode != 0


def test_a_firm_has_at_most_one_allowance(db):
    assert _psql(db, _budget(tokens="1000")).returncode == 0
    assert _psql(db, _budget(tokens="2000")).returncode != 0


def test_an_allowance_for_a_firm_that_does_not_exist_is_refused(db):
    assert _psql(db, _budget("47600000-0000-0000-0000-0000000000ff", tokens="1000")).returncode != 0


def test_deleting_a_firm_takes_its_allowance_with_it(db):
    assert _psql(db, _budget(OTHER_FIRM, tokens="1000")).returncode == 0
    # the firm's users hold a FK to it; a firm with no members is what a hard delete is for
    assert _psql(db, f"DELETE FROM users WHERE firm_id = '{OTHER_FIRM}'; "
                     f"DELETE FROM firms WHERE id = '{OTHER_FIRM}';").returncode == 0
    assert _scalar(db, f"SELECT count(*) FROM public.ai_firm_budgets "
                       f"WHERE firm_id = '{OTHER_FIRM}';") == "0"


def test_the_person_who_set_it_is_forgotten_not_the_allowance(db):
    r = _psql(db, f"INSERT INTO public.ai_firm_budgets (firm_id, monthly_token_limit, set_by) "
                  f"VALUES ('{FIRM}', 1000, '{PARTNER_ID}');")
    assert r.returncode == 0, r.stderr
    d = _psql(db, f"DELETE FROM users WHERE id = '{PARTNER_ID}';")
    assert d.returncode == 0, d.stderr
    row = _rows(db, f"SELECT monthly_token_limit, set_by FROM public.ai_firm_budgets "
                    f"WHERE firm_id = '{FIRM}'")[0]
    assert row == {"monthly_token_limit": 1000, "set_by": None}


# ── who can read and write it ────────────────────────────────────────────────

def test_rls_is_on(db):
    assert _scalar(db, "SELECT relrowsecurity FROM pg_class WHERE oid = "
                       "'public.ai_firm_budgets'::regclass;") == "t"


def test_a_partner_reads_their_own_firms_allowance_and_not_another_firms(db):
    assert _psql(db, _budget(FIRM, tokens="1000")).returncode == 0
    assert _psql(db, _budget(OTHER_FIRM, tokens="9999")).returncode == 0
    assert _as_scalar(db, PARTNER_AUTH, "SELECT count(*) FROM public.ai_firm_budgets;") == "1"
    assert _as_scalar(db, PARTNER_AUTH,
                      "SELECT monthly_token_limit FROM public.ai_firm_budgets;") == "1000"


def test_an_executive_of_the_same_firm_reads_none(db):
    """A firm's AI allowance is the Partner's to read, like the spend it limits."""
    assert _psql(db, _budget(FIRM, tokens="1000")).returncode == 0
    assert _as_scalar(db, EXEC_AUTH, "SELECT count(*) FROM public.ai_firm_budgets;") == "0"


@pytest.mark.parametrize("statement", [
    f"INSERT INTO public.ai_firm_budgets (firm_id, monthly_token_limit) VALUES ('{FIRM}', 1);",
    "UPDATE public.ai_firm_budgets SET monthly_token_limit = 1;",
    "DELETE FROM public.ai_firm_budgets;",
])
def test_no_signed_in_session_can_write_an_allowance(db, statement):
    """Not even a Partner's own: the allowance is set through the API, which asks rbac()
    and writes the audit row."""
    assert _psql(db, _budget(FIRM, tokens="1000")).returncode == 0
    r = _as(db, PARTNER_AUTH, statement)
    assert r.returncode != 0
    assert "permission denied" in r.stderr or "row-level security" in r.stderr
    assert _scalar(db, f"SELECT monthly_token_limit FROM public.ai_firm_budgets "
                       f"WHERE firm_id = '{FIRM}';") == "1000"


# ── the functions are the service role's ─────────────────────────────────────

FUNCTIONS = ("ai_usage_by_day", "ai_usage_by_feature", "ai_usage_totals")
SIGNATURE = "uuid, timestamptz, timestamptz"


@pytest.mark.parametrize("fn", FUNCTIONS)
def test_a_signed_in_user_cannot_run_the_aggregates(db, fn):
    """They take the firm as an argument: executable by `authenticated`, any signed-in user
    could read any firm's usage by naming it."""
    assert _scalar(db, f"SELECT has_function_privilege('authenticated', "
                       f"'public.{fn}({SIGNATURE})', 'EXECUTE');") == "f"
    assert _scalar(db, f"SELECT has_function_privilege('anon', "
                       f"'public.{fn}({SIGNATURE})', 'EXECUTE');") == "f"
    r = _as(db, PARTNER_AUTH, f"SELECT * FROM public.{fn}('{OTHER_FIRM}', '{FROM}', '{TO}');")
    assert r.returncode != 0
    assert "permission denied" in r.stderr


@pytest.mark.parametrize("fn", FUNCTIONS)
def test_the_service_role_can_run_the_aggregates(db, fn):
    assert _scalar(db, f"SELECT has_function_privilege('service_role', "
                       f"'public.{fn}({SIGNATURE})', 'EXECUTE');") == "t"


# ── what the aggregates say ──────────────────────────────────────────────────

def test_a_month_with_no_attempts_is_empty_for_the_grouped_answers_and_zero_for_the_total(db):
    assert _by_day(db) == []
    assert _by_feature(db) == []
    assert _totals(db) == {"tokens": 0, "pages": 0}


def test_the_day_is_the_ist_day_not_the_utc_day(db):
    """19:00 UTC on 30 September is 00:30 IST on 1 October. Grouped by the UTC date it would
    land on the last day of the month before and be missed by the window it belongs to."""
    _seed(db, _event("2026-09-30T19:00:00Z", call="a", tokens=10),
          _event("2026-10-01T18:00:00Z", call="b", tokens=20),    # 23:30 IST on the 1st
          _event("2026-10-01T18:45:00Z", call="c", tokens=40))    # 00:15 IST on the 2nd
    got = {r["day"]: r["tokens"] for r in _by_day(db)}
    assert got == {"2026-10-01": 30, "2026-10-02": 40}


def test_the_window_is_half_open(db):
    _seed(db, _event(FROM, call="first", tokens=1),               # in
          _event("2026-09-30T18:29:59Z", call="before", tokens=100),
          _event(TO, call="end", tokens=1000),                    # the next month's first instant
          _event("2026-10-31T18:29:59Z", call="last", tokens=10))
    assert _totals(db)["tokens"] == 11


def test_another_firms_attempts_are_never_counted(db):
    _seed(db, _event("2026-10-05T05:00:00Z", firm=FIRM, call="mine", tokens=7, pages=1),
          _event("2026-10-05T05:00:00Z", firm=OTHER_FIRM, call="theirs", tokens=700, pages=50))
    assert _totals(db) == {"tokens": 7, "pages": 1}
    assert _totals(db, OTHER_FIRM) == {"tokens": 700, "pages": 50}
    assert sum(r["tokens"] for r in _by_day(db)) == 7
    assert sum(r["tokens"] for r in _by_feature(db)) == 7


def test_first_attempts_counts_calls_and_not_retries(db):
    """One call retried once and then answered by a fallback is three attempts and one call."""
    _seed(db,
          _event("2026-10-05T05:00:00Z", call="x", attempt=1, outcome="provider_error", tokens=0),
          _event("2026-10-05T05:00:01Z", call="x", attempt=2, outcome="provider_error", tokens=0),
          _event("2026-10-05T05:00:02Z", call="x", attempt=3, outcome="ok", tokens=500),
          _event("2026-10-05T06:00:00Z", call="y", attempt=1, outcome="ok", tokens=200))
    rows = _by_feature(db)
    assert sum(r["attempts"] for r in rows) == 4
    assert sum(r["first_attempts"] for r in rows) == 2


def test_tokens_and_pages_are_summed_over_every_attempt_failed_ones_included(db):
    """A reasoning model that burned its allowance and sent back nothing was still billed, and
    a retry sends the same pages again."""
    _seed(db,
          _event("2026-10-05T05:00:00Z", call="z", attempt=1, outcome="empty_reply",
                 tokens=4096, reasoning=4096, pages=3, feature="invoice_vision", provider="gemini"),
          _event("2026-10-05T05:00:05Z", call="z", attempt=2, outcome="ok",
                 tokens=900, reasoning=100, pages=3, feature="invoice_vision", provider="gemini"))
    t = _totals(db)
    assert t == {"tokens": 4996, "pages": 6}
    day = _by_day(db)
    assert {(r["outcome"], r["tokens"], r["reasoning_tokens"], r["pages"]) for r in day} == {
        ("empty_reply", 4096, 4096, 3), ("ok", 900, 100, 3)}


def test_null_counts_are_zero_and_never_poison_a_sum(db):
    """A refused call (the budget's own refusal, or an auth failure) carries no usage; the
    column is NULL and the sum is still a number."""
    r = _psql(db, f"INSERT INTO public.ai_usage_events (firm_id, feature, provider, model, call_id, "
                  f"attempt, outcome, latency_ms, created_at) VALUES ('{FIRM}', 'assistant', 'groq', "
                  f"'m1', 'n', 1, 'budget_exhausted', 0, '2026-10-05T05:00:00Z');")
    assert r.returncode == 0, r.stderr
    assert _totals(db) == {"tokens": 0, "pages": 0}
    row = _by_day(db)[0]
    assert (row["attempts"], row["tokens"], row["pages"]) == (1, 0, 0)


def test_the_grouping_keys_are_what_the_service_and_the_screen_show(db):
    _seed(db,
          _event("2026-10-05T05:00:00Z", call="a", feature="assistant", provider="groq", model="m1", tokens=1),
          _event("2026-10-05T05:00:01Z", call="b", feature="assistant", provider="groq", model="m2", tokens=2),
          _event("2026-10-05T05:00:02Z", call="c", feature="invoice_vision", provider="gemini", model="g1", tokens=4),
          _event("2026-10-05T05:00:03Z", call="d", feature="assistant", provider="groq", model="m1",
                 outcome="timeout", tokens=0))
    keys = {(r["provider"], r["feature"], r["model"], r["outcome"]): r["tokens"] for r in _by_feature(db)}
    assert keys == {("groq", "assistant", "m1", "ok"): 1, ("groq", "assistant", "m2", "ok"): 2,
                    ("gemini", "invoice_vision", "g1", "ok"): 4, ("groq", "assistant", "m1", "timeout"): 0}


def test_the_three_functions_agree_with_one_another_and_with_the_python_fold(db):
    """The fold in `domain/ai/budget` is what the screen shows and the SQL total is what the
    gate enforces; for the same month they must be the same number."""
    from domain.ai import budget
    _seed(db,
          _event("2026-10-02T05:00:00Z", call="a", tokens=1000, reasoning=300, pages=2,
                 feature="invoice_vision", provider="gemini", model="g1"),
          _event("2026-10-09T05:00:00Z", call="b", attempt=1, outcome="rate_limited", tokens=0),
          _event("2026-10-09T05:00:03Z", call="b", attempt=2, tokens=250),
          _event("2026-10-31T17:00:00Z", call="c", tokens=70),
          _event("2026-10-31T18:00:00Z", call="d", tokens=5, outcome="timeout"))
    by_day, by_feature, total = _by_day(db), _by_feature(db), _totals(db)
    assert sum(r["tokens"] for r in by_day) == sum(r["tokens"] for r in by_feature) == total["tokens"] == 1325
    assert sum(r["pages"] for r in by_day) == sum(r["pages"] for r in by_feature) == total["pages"] == 2
    folded = budget.fold(by_day, by_feature)
    assert folded["totals"]["tokens"] == total["tokens"]
    assert folded["totals"]["pages"] == total["pages"]
    assert folded["truncated"] is False


def test_the_months_the_python_rule_names_are_the_bounds_the_sql_is_given(db):
    """`budget.month_of` produces the strings handed to the functions; an attempt in the first
    IST minute of the month is in it and one in the last IST minute of the month before is
    not."""
    from domain.ai import budget
    month = budget.month_of(dt.date(2026, 10, 15))
    _seed(db, _event("2026-09-30T18:29:00Z", call="prev", tokens=900),    # 23:59 IST on 30 Sep
          _event("2026-09-30T18:31:00Z", call="this", tokens=9))          # 00:01 IST on 1 Oct
    got = _rows(db, f"SELECT * FROM public.ai_usage_totals('{FIRM}', '{month.start_utc}', '{month.end_utc}')")[0]
    assert got["tokens"] == 9


# ── the source reads only columns the table has ──────────────────────────────

def _selects(path: str) -> list[str]:
    src = (API / path).read_text()
    return re.findall(r'\.table\("ai_firm_budgets"\)\s*\.select\("([^"]+)"\)', src)


@pytest.mark.parametrize("path", ["services/ai_usage_service.py", "domain/ai/budget_gate.py"])
def test_the_projections_name_only_columns_the_table_has(path):
    found = _selects(path)
    assert found, f"{path} has no literal projection of ai_firm_budgets; the scan would pass vacuously"
    for projection in found:
        named = {c.strip() for c in projection.split(",")}
        assert named <= EXPECTED_COLUMNS, sorted(named - EXPECTED_COLUMNS)


def test_the_upsert_writes_only_columns_the_table_has():
    src = (API / "services" / "ai_usage_service.py").read_text()
    body = src[src.index('.table("ai_firm_budgets").upsert({'):]
    body = body[:body.index("}, on_conflict")]
    written = set(re.findall(r'"([a-z_]+)":', body))
    assert written, "the scan found no keys — it would pass vacuously"
    assert written <= EXPECTED_COLUMNS, sorted(written - EXPECTED_COLUMNS)
