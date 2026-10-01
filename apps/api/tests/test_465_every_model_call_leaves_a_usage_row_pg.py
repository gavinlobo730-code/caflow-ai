"""Migration 465 on real PostgreSQL — every model call leaves a usage row, and the
row holds no text (ai-04).

WHAT IS PROVEN HERE
    * `ai_usage_events` exists with exactly the columns the gateway writes — and
      none that could hold what was said: no prompt, no reply, no message, no
      client. A column added later that does is a decision this test makes loud;
    * a row with only the required columns inserts, with `fallback_used` false and
      a timestamp defaulted; two attempts of ONE call share a `call_id`;
    * `attempt` below 1, a negative latency and a negative token count are
      refused;
    * the gateway's own INSERT payload (read from `domain/ai/gateway._write_row`)
      names only columns the table has — the production writer and the schema
      cannot drift apart without this failing;
    * RLS is on; a Partner reads their OWN firm's rows and not another firm's; an
      Executive of the same firm reads none (a firm's AI spend is the Partner's);
      and no signed-in session can INSERT one.

Runs only when HARNESS_PG is set + psql is on PATH, like every *_pg test; it
cannot run in the mock-mode job.
"""
from __future__ import annotations

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

FIRM = "46500000-0000-0000-0000-0000000000f1"
OTHER_FIRM = "46500000-0000-0000-0000-0000000000f2"
PARTNER_ID = "46500000-0000-0000-0000-00000000b001"
EXEC_ID = "46500000-0000-0000-0000-00000000b002"
OTHER_PARTNER_ID = "46500000-0000-0000-0000-00000000b003"
PARTNER_AUTH = "46500000-0000-0000-0000-00000000a001"
EXEC_AUTH = "46500000-0000-0000-0000-00000000a002"
OTHER_PARTNER_AUTH = "46500000-0000-0000-0000-00000000a003"

#: Exactly what the gateway writes, plus the two the database supplies.
EXPECTED_COLUMNS = {
    "id", "firm_id", "user_id", "feature", "provider", "model", "call_id", "attempt",
    "outcome", "fallback_used", "http_status", "provider_code", "latency_ms",
    "prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens",
    "input_units", "created_at",
}


def _psql(dsn: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-c", sql],
                          capture_output=True, text=True)


def _scalar(dsn: str, sql: str) -> str:
    r = subprocess.run(["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-tA", "-c", sql],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def _as(dsn: str, auth_uid: str, sql: str) -> subprocess.CompletedProcess:
    return _psql(dsn, f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; "
                      f"SET ROLE authenticated; {sql}")


def _as_scalar(dsn: str, auth_uid: str, sql: str) -> str:
    return _scalar(dsn, f"SET request.jwt.claims = '{{\"sub\": \"{auth_uid}\"}}'; "
                        f"SET ROLE authenticated; {sql}")


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m465_{uuid.uuid4().hex[:12]}"
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


def _row(firm: str = FIRM, call_id: str = "c1", attempt: int = 1, **over) -> str:
    cols = {"firm_id": f"'{firm}'", "feature": "'assistant'", "provider": "'groq'",
            "model": "'openai/gpt-oss-120b'", "call_id": f"'{call_id}'",
            "attempt": str(attempt), "outcome": "'ok'", "latency_ms": "420"}
    cols.update({k: str(v) for k, v in over.items()})
    return (f"INSERT INTO public.ai_usage_events ({', '.join(cols)}) "
            f"VALUES ({', '.join(cols.values())});")


# ── the shape ────────────────────────────────────────────────────────────────

def test_the_table_has_exactly_the_columns_the_gateway_writes(db):
    got = set(_scalar(db, "SELECT string_agg(column_name, ',') FROM information_schema.columns "
                          "WHERE table_schema='public' AND table_name='ai_usage_events';").split(","))
    assert got == EXPECTED_COLUMNS


def test_the_only_free_text_columns_are_six_short_labels(db):
    """What could hold a sentence is what has type `text`. These six are a feature
    name, a provider name, a model name, an id, an outcome word and the
    provider's own short error code — none of them a message, a prompt or a
    reply. A seventh would have to be argued for here."""
    got = set(_scalar(db, "SELECT string_agg(column_name, ',') FROM information_schema.columns "
                          "WHERE table_schema='public' AND table_name='ai_usage_events' "
                          "AND data_type = 'text';").split(","))
    assert got == {"feature", "provider", "model", "call_id", "outcome", "provider_code"}


def test_the_gateways_insert_names_only_columns_the_table_has():
    """The writer is a literal in domain/ai/gateway._write_row; its keys are read
    from SOURCE so the production INSERT and this schema cannot drift apart."""
    src = (Path(__file__).resolve().parents[1] / "domain" / "ai" / "gateway.py").read_text()
    body = src[src.index('.table("ai_usage_events").insert({'):]
    body = body[:body.index("}).execute()")]
    written = set(re.findall(r'"([a-z_]+)":', body))
    assert written, "the scan found no keys — it would pass vacuously"
    assert written <= EXPECTED_COLUMNS, sorted(written - EXPECTED_COLUMNS)


# ── the constraints ──────────────────────────────────────────────────────────

def test_a_minimal_row_inserts_with_its_defaults(db):
    assert _psql(db, _row()).returncode == 0
    assert _scalar(db, "SELECT fallback_used FROM ai_usage_events;") == "f"
    assert _scalar(db, "SELECT created_at IS NOT NULL FROM ai_usage_events;") == "t"


def test_two_attempts_of_one_call_share_a_call_id(db):
    assert _psql(db, _row(call_id="abc", attempt=1, outcome="'provider_error'")).returncode == 0
    assert _psql(db, _row(call_id="abc", attempt=2, fallback_used="true")).returncode == 0
    assert _scalar(db, "SELECT count(*) FROM ai_usage_events WHERE call_id='abc';") == "2"


@pytest.mark.parametrize("bad", [
    {"attempt": 0}, {"latency_ms": -1}, {"prompt_tokens": -5}, {"total_tokens": -1},
    {"reasoning_tokens": -2}, {"input_units": -1},
])
def test_an_impossible_count_is_refused(db, bad):
    assert _psql(db, _row(**bad)).returncode != 0


# ── who can read it ──────────────────────────────────────────────────────────

def test_rls_is_on(db):
    assert _scalar(db, "SELECT relrowsecurity FROM pg_class WHERE oid = "
                       "'public.ai_usage_events'::regclass;") == "t"


def test_a_partner_reads_their_own_firms_rows_and_not_another_firms(db):
    assert _psql(db, _row(FIRM, "mine")).returncode == 0
    assert _psql(db, _row(OTHER_FIRM, "theirs")).returncode == 0
    assert _as_scalar(db, PARTNER_AUTH, "SELECT count(*) FROM public.ai_usage_events;") == "1"
    assert _as_scalar(db, PARTNER_AUTH,
                      "SELECT call_id FROM public.ai_usage_events;") == "mine"


def test_an_executive_of_the_same_firm_reads_none(db):
    """A firm's AI spend is the Partner's: the RESTRICTIVE policy narrows."""
    assert _psql(db, _row(FIRM, "mine")).returncode == 0
    assert _as_scalar(db, EXEC_AUTH, "SELECT count(*) FROM public.ai_usage_events;") == "0"


def test_no_signed_in_session_can_insert_a_row(db):
    r = _as(db, PARTNER_AUTH, _row(FIRM, "forged"))
    assert r.returncode != 0
    assert "permission denied" in r.stderr or "row-level security" in r.stderr
