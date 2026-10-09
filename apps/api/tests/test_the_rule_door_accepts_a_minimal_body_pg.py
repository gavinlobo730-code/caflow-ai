"""POST /api/banking/rules accepts a body that does not state `flags_tds_decision`, against real PostgreSQL.

WHAT WAS WRONG
    Migration 413 made `bank_matching_rules.flags_tds_decision` NOT NULL DEFAULT false. `MatchingRuleIn` keeps it
    `Optional[bool] = None` (so PATCH can tell "leave it" from "set it") and `create_rule` inserted
    `data.model_dump()`. PostgREST inserts exactly the keys it is sent, so the JSON null was written as NULL, the
    default never applied, and every create that did not send the flag answered 400 "A required value was missing".
    The rules screen always sends it, which is why nothing noticed; every other caller does not -- found by driving the
    demo seeder over a real stack, where the first rule it wrote was refused. The same class as
    `test_the_client_door_accepts_a_minimal_body_pg.py` (a model default of None over a NOT NULL DEFAULT column).

WHAT THIS PROVES
    It builds the insert with the router's OWN `_rule_fields` and inserts the way PostgREST does: a column list of
    exactly the keys present. The first test shows the payload the door used to send IS refused by this schema, so the
    second cannot pass on a lenient insert.

Runs only when HARNESS_PG is set and psql is on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid

import pytest

from models.banking import MatchingRuleIn
from routers.banking import _rule_fields

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the rule door proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000413"
CLIENT = "bbbbbbbb-0000-0000-0000-000000000413"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"ruledoor_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert not [f for f in pg_template.failed if f.startswith("413_")], (
            "migration 413 did not apply -- the column under test would not exist")
        for sql in (
            f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');",
            f"INSERT INTO clients (id, firm_id, client_name, entity_type, pan) VALUES "
            f"('{CLIENT}', '{FIRM}', 'C', 'Private Limited', 'AAACA1234E');",
        ):
            r = _psql(dsn, sql)
            assert r.returncode == 0, r.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert_like_postgrest(dsn: str, row: dict) -> subprocess.CompletedProcess:
    """INSERT exactly the keys in `row`: an absent key takes its DEFAULT, a JSON null is inserted as NULL."""
    keys = list(row)
    cols = ", ".join(f'"{k}"' for k in keys)
    body = json.dumps(row, default=str).replace("'", "''")
    return _psql(
        dsn,
        f"INSERT INTO bank_matching_rules ({cols}) SELECT {cols} "
        f"FROM jsonb_populate_record(null::bank_matching_rules, '{body}'::jsonb);",
    )


def _minimal(**overrides) -> MatchingRuleIn:
    fields = dict(client_id=CLIENT, rule_name="Rent", description_pattern="Rent -", txn_type="debit",
                  suggested_narration="Rent paid")
    fields.update(overrides)
    return MatchingRuleIn(**fields)


def test_the_payload_the_door_used_to_send_is_refused_by_this_schema(dsn):
    """The premise. Without it the next test could pass against a schema that tolerated the null."""
    old = {"firm_id": FIRM, **_minimal().model_dump()}
    assert old["flags_tds_decision"] is None
    r = _insert_like_postgrest(dsn, old)
    assert r.returncode != 0
    assert "flags_tds_decision" in r.stderr and "not-null" in r.stderr


def test_a_rule_that_does_not_state_the_flag_inserts_and_takes_the_default(dsn):
    fields = _rule_fields(_minimal())
    assert "flags_tds_decision" not in fields
    r = _insert_like_postgrest(dsn, {"firm_id": FIRM, **fields})
    assert r.returncode == 0, r.stderr
    got = _psql(dsn, "SELECT flags_tds_decision, is_trusted, priority FROM bank_matching_rules "
                     "WHERE rule_name = 'Rent';", tuples=True)
    assert got.stdout.strip() == "f|f|100"


def test_a_flag_the_caller_states_is_kept_true_or_false(dsn):
    for flag, expected in ((True, "t"), (False, "f")):
        fields = _rule_fields(_minimal(rule_name=f"Flag {flag}", flags_tds_decision=flag))
        assert fields["flags_tds_decision"] is flag
        assert _insert_like_postgrest(dsn, {"firm_id": FIRM, **fields}).returncode == 0
        got = _psql(dsn, f"SELECT flags_tds_decision FROM bank_matching_rules WHERE rule_name = 'Flag {flag}';",
                    tuples=True)
        assert got.stdout.strip() == expected


def test_every_other_field_of_the_body_still_reaches_the_row(dsn):
    body = _minimal(rule_name="Courier", description_pattern="courier", suggested_narration="Courier charges",
                    priority=7, amount_max_paise=5_000_00)
    fields = _rule_fields(body)
    assert fields == {k: v for k, v in body.model_dump().items() if k != "flags_tds_decision"}
    assert _insert_like_postgrest(dsn, {"firm_id": FIRM, **fields}).returncode == 0
