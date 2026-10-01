"""Migration 451 on real PostgreSQL — a time entry knows its engagement and what
an hour of it is worth (practice_management-11).

WHAT IS PROVEN HERE
    * `users.default_billable_rate_paise` and `fee_engagements.billable_rate_paise`
      exist, are NULLABLE with NO DEFAULT (NULL is "nobody said", not 0), accept 0
      and refuse a negative;
    * a signed-in browser session cannot write a person's billing rate — the
      `users` column grants name `full_name` and nothing else, so the new column is
      the API's to set, with `rbac("billing", "write")` in front of it;
    * `public.unbilled_time_summary` agrees with its Python twin
      (`domain/billing/time_rate.fold_unbilled`) over one fixture that has a row
      for every way an entry can be left out or priced: a rate of its own, the
      legacy `hourly_rate_paise` only, a stated ZERO, NO rate at all, non-billable,
      already billed, no minutes, another firm's, no client and no task;
    * a stated ZERO is PRICED (worth nothing, and not on the "no rate" list) and a
      missing rate is not (listed, adding nothing) — the two the old total ran
      together;
    * value is floored PER ENTRY, so two entries of 7 minutes at 100 paise an hour
      are 22 paise and not the 23 a floor on the sum would give;
    * the function is not executable by `anon`.

Runs only when HARNESS_PG is set + psql is on PATH, like every *_pg test; it
cannot run in the mock-mode job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid

import pytest

from domain.billing import time_rate

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or not shutil.which("psql"),
    reason="needs HARNESS_PG and psql on PATH",
)

FIRM = "51000000-0000-0000-0000-0000000000f1"
OTHER_FIRM = "51000000-0000-0000-0000-0000000000f2"
CLIENT_A = "51000000-0000-0000-0000-0000000000c1"
CLIENT_B = "51000000-0000-0000-0000-0000000000c2"
OTHER_CLIENT = "51000000-0000-0000-0000-0000000000c3"
PARTNER_ID = "51000000-0000-0000-0000-00000000b001"
PREPARER_ID = "51000000-0000-0000-0000-00000000b002"
PARTNER_AUTH = "51000000-0000-0000-0000-00000000a001"
PREPARER_AUTH = "51000000-0000-0000-0000-00000000a002"
TASK_1 = "51000000-0000-0000-0000-0000000000a1"
TASK_2 = "51000000-0000-0000-0000-0000000000a2"
ENGAGEMENT = "51000000-0000-0000-0000-0000000000e1"
INVOICE = "51000000-0000-0000-0000-0000000000d1"
CUSTOMER = "51000000-0000-0000-0000-0000000000d2"


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


@pytest.fixture()
def db(pg_template):
    admin = _ADMIN.strip()
    name = f"m451_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        seed = _psql(dsn, f"""
            INSERT INTO auth.users (id, email) VALUES
              ('{PARTNER_AUTH}', 'p@t.in'), ('{PREPARER_AUTH}', 'e@t.in');
            INSERT INTO firms (id, name, email) VALUES
              ('{FIRM}', 'F1', 'f1@t.in'), ('{OTHER_FIRM}', 'F2', 'f2@t.in');
            INSERT INTO users (id, firm_id, auth_user_id, email, full_name, role, is_active) VALUES
              ('{PARTNER_ID}', '{FIRM}', '{PARTNER_AUTH}', 'p@t.in', 'Partner', 'Partner', true),
              ('{PREPARER_ID}', '{FIRM}', '{PREPARER_AUTH}', 'e@t.in', 'Preparer', 'Executive', true);
            INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES
              ('{CLIENT_A}', '{FIRM}', 'A', 'Private Limited', 'AAACA1234A'),
              ('{CLIENT_B}', '{FIRM}', 'B', 'Private Limited', 'AAACB1234B'),
              ('{OTHER_CLIENT}', '{OTHER_FIRM}', 'C', 'Private Limited', 'AAACC1234C');
            INSERT INTO fee_engagements (id, firm_id, client_id, service_type)
              VALUES ('{ENGAGEMENT}', '{FIRM}', '{CLIENT_A}', 'GST Filing');
        """)
        assert seed.returncode == 0, seed.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


# ── the two columns ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("table,column", [("users", "default_billable_rate_paise"),
                                          ("fee_engagements", "billable_rate_paise")])
def test_a_rate_column_is_nullable_with_no_default(db, table, column):
    row = _scalar(db, f"SELECT is_nullable || '|' || coalesce(column_default, 'none') "
                      f"FROM information_schema.columns "
                      f"WHERE table_schema='public' AND table_name='{table}' AND column_name='{column}'")
    assert row == "YES|none", ("NULL is 'nobody has said', which is not 0; a default would make "
                               f"every existing row look like a decision. Got {row!r}")


@pytest.mark.parametrize("table,column,where", [
    ("users", "default_billable_rate_paise", f"id = '{PREPARER_ID}'"),
    ("fee_engagements", "billable_rate_paise", f"id = '{ENGAGEMENT}'"),
])
def test_a_rate_may_be_nothing_or_zero_and_never_negative(db, table, column, where):
    assert _psql(db, f"UPDATE {table} SET {column} = NULL WHERE {where};").returncode == 0
    assert _psql(db, f"UPDATE {table} SET {column} = 0 WHERE {where};").returncode == 0
    assert _scalar(db, f"SELECT {column} FROM {table} WHERE {where}") == "0", \
        "a stated zero is stored as zero, not turned back into NULL"
    r = _psql(db, f"UPDATE {table} SET {column} = -1 WHERE {where};")
    assert r.returncode != 0 and "check" in r.stderr.lower()


def test_a_browser_session_cannot_write_a_persons_billing_rate(db):
    """`users` grants `authenticated` UPDATE on full_name only (migration 153), so
    a Partner's own browser cannot set a colleague's — or their own — rate over
    PostgREST, past `rbac("billing", "write")`."""
    r = _as(db, PARTNER_AUTH,
            f"UPDATE users SET default_billable_rate_paise = 1 WHERE id = '{PREPARER_ID}';")
    assert r.returncode != 0 and "permission denied" in r.stderr.lower(), r.stderr
    assert _scalar(db, f"SELECT coalesce(default_billable_rate_paise::text, 'null') FROM users "
                       f"WHERE id = '{PREPARER_ID}'") == "null"


# ── the unbilled-work summary and its Python twin ────────────────────────────

# (label, firm, client, task, minutes, billable, billed, billable_rate, hourly_rate)
_ENTRIES = [
    ("own rate",            FIRM, CLIENT_A, TASK_1, 90, True,  False, 250000, None),
    ("legacy rate only",    FIRM, CLIENT_A, TASK_1, 30, True,  False, None,   120000),
    ("own rate wins",       FIRM, CLIENT_A, TASK_2, 60, True,  False, 100000, 999999),
    ("stated zero",         FIRM, CLIENT_A, TASK_2, 45, True,  False, 0,      None),
    ("no rate at all",      FIRM, CLIENT_A, TASK_1, 50, True,  False, None,   None),
    ("no rate, B",          FIRM, CLIENT_B, None,   20, True,  False, None,   None),
    ("priced B no task",    FIRM, CLIENT_B, None,   10, True,  False, 300000, None),
    ("no client",           FIRM, None,     None,   15, True,  False, 50000,  None),
    ("floor 1",             FIRM, CLIENT_B, TASK_1, 7,  True,  False, 100,    None),
    ("floor 2",             FIRM, CLIENT_B, TASK_1, 7,  True,  False, 100,    None),
    ("not billable",        FIRM, CLIENT_A, TASK_1, 60, False, False, 250000, None),
    ("already billed",      FIRM, CLIENT_A, TASK_1, 60, True,  True,  250000, None),
    ("no minutes",          FIRM, CLIENT_A, TASK_1, 0,  True,  False, 250000, None),
    ("running (null mins)", FIRM, CLIENT_A, TASK_1, None, True, False, 250000, None),
    ("other firm",          OTHER_FIRM, OTHER_CLIENT, None, 600, True, False, 900000, None),
]


def _q(v) -> str:
    return "NULL" if v is None else (f"'{v}'" if isinstance(v, str) else str(v))


def _seed_entries(dsn: str) -> list[dict]:
    """Insert the fixture and return the SAME rows as dicts for the Python twin."""
    # `time_entries.billed_invoice_id` is an FK to `client_sales_invoices`.
    inv = _psql(dsn, f"INSERT INTO customers (id, firm_id, client_id, name) "
                     f"VALUES ('{CUSTOMER}', '{FIRM}', '{CLIENT_A}', 'Buyer'); "
                     f"INSERT INTO client_sales_invoices (id, firm_id, client_id, customer_id, invoice_no, invoice_date) "
                     f"VALUES ('{INVOICE}', '{FIRM}', '{CLIENT_A}', '{CUSTOMER}', 'T-1', CURRENT_DATE);")
    assert inv.returncode == 0, inv.stderr
    entries: list[dict] = []
    for label, firm, client, task, mins, billable, billed, brate, hrate in _ENTRIES:
        user = PARTNER_ID
        sql = (f"INSERT INTO time_entries (firm_id, user_id, client_id, task_id, description, "
               f"started_at, duration_minutes, is_billable, billed_invoice_id, "
               f"billable_rate_paise, hourly_rate_paise) VALUES ("
               f"{_q(firm)}, '{user}', {_q(client)}, {_q(task)}, '{label}', now(), "
               f"{_q(mins)}, {str(billable).lower()}, {_q(INVOICE if billed else None)}, "
               f"{_q(brate)}, {_q(hrate)});")
        r = _psql(dsn, sql)
        assert r.returncode == 0, (label, r.stderr)
        if firm == FIRM:
            entries.append({"client_id": client, "task_id": task, "duration_minutes": mins,
                            "is_billable": billable, "billed_invoice_id": INVOICE if billed else None,
                            "billable_rate_paise": brate, "hourly_rate_paise": hrate})
    return entries


def _sql_answer(dsn: str, client: str | None = None) -> dict:
    args = f"'{FIRM}'" + (f", '{client}'" if client else "")
    raw = _scalar(dsn, f"SELECT coalesce(jsonb_agg(t), '[]'::jsonb) FROM "
                       f"public.unbilled_time_summary({args}) t")
    return time_rate.fold_unbilled(json.loads(raw))


def _strip(answer: dict) -> dict:
    """The comparable part: the entries list is fetched separately, not aggregated."""
    return {**answer, "no_rate": {k: v for k, v in answer["no_rate"].items() if k != "entries"}}


def test_the_sql_summary_and_its_python_twin_are_one_answer(db):
    entries = _seed_entries(db)
    sql = _strip(_sql_answer(db))
    py = _strip(time_rate.fold_unbilled(time_rate.group_unbilled_entries(entries)))
    assert sql == py


def test_the_answer_is_the_one_the_fixture_was_built_to_make(db):
    """The parity above would pass if BOTH sides were wrong the same way, so the
    figures are also pinned by hand."""
    _seed_entries(db)
    a = _sql_answer(db)
    # priced: 90m@250000=375000, 30m@120000=60000, 60m@100000=100000, 45m@0=0,
    #         10m@300000=50000, 15m@50000=12500, 7m@100=11 twice
    assert a["total_value_paise"] == 375000 + 60000 + 100000 + 0 + 50000 + 12500 + 11 + 11
    # two 7-minute entries at 100 paise: 700 // 60 = 11 EACH (22), not 1400 // 60 = 23
    assert a["by_client"][CLIENT_B]["value_paise"] == 50000 + 22
    # 50 + 20 minutes carry no rate; the stated zero (45) is NOT among them
    assert a["no_rate"]["count"] == 2 and a["no_rate"]["minutes"] == 70
    assert a["by_client"][CLIENT_A]["count"] == 4 and a["by_client"][CLIENT_A]["minutes"] == 90 + 30 + 60 + 45
    assert a["total_minutes"] == a["priced_minutes"] + 70


def test_a_missing_rate_is_listed_and_a_stated_zero_is_not(db):
    _seed_entries(db)
    a = _sql_answer(db)
    assert a["no_rate"]["by_client"][CLIENT_A] == {"minutes": 50, "count": 1}
    assert a["no_rate"]["by_client"][CLIENT_B] == {"minutes": 20, "count": 1}
    # the stated zero is work somebody priced at nothing: counted, worth nothing
    assert a["by_work_item"][TASK_2] == {"minutes": 105, "value_paise": 100000, "count": 2}


def test_the_client_filter_is_the_same_rule_on_fewer_rows(db):
    entries = _seed_entries(db)
    only_a = [e for e in entries if e["client_id"] == CLIENT_A]
    sql = _strip(_sql_answer(db, CLIENT_A))
    py = _strip(time_rate.fold_unbilled(time_rate.group_unbilled_entries(only_a)))
    assert sql == py and CLIENT_B not in sql["by_client"]


def test_another_firms_time_is_never_in_the_answer(db):
    _seed_entries(db)
    a = _sql_answer(db)
    assert OTHER_CLIENT not in a["by_client"] and a["total_value_paise"] < 900000 * 10


def test_the_summary_is_not_executable_by_anon(db):
    r = _psql(db, f"SET ROLE anon; SELECT * FROM public.unbilled_time_summary('{FIRM}');")
    assert r.returncode != 0 and "permission denied" in r.stderr.lower(), r.stderr


def test_the_migration_applies_twice(db):
    """Additive and idempotent: re-running the file changes nothing and errors on nothing."""
    path = os.path.join(os.path.dirname(__file__), "..", "migrations",
                        "451_a_time_entry_knows_its_engagement_and_what_an_hour_of_it_is_worth.sql")
    r = subprocess.run(["psql", db, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", path],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
