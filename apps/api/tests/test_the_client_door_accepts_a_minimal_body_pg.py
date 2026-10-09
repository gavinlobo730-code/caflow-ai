"""POST /api/clients accepts a body that does not state a GST registration type, against real PostgreSQL.

WHAT WAS WRONG
    `ClientCreate.gst_registration_type` defaults to None ("not stated") and `create_client` sent
    `body.model_dump()` as the insert. Migration 420 made `clients.gst_registration_type` NOT NULL DEFAULT
    'regular'. PostgREST inserts exactly the keys it is sent, so the JSON null was written as NULL, the default
    never applied, and the column refused it: HTTP 400 "A required value was missing" for every create that did
    not name a registration type. Found by driving the demo seeder (`scripts/seed_demo_firm.py`) over a real
    stack; its first client fails. The web inserts clients over PostgREST and never meets this door, which is
    why nothing else noticed: only the API client and the seeder call it.

WHAT THIS PROVES, AND HOW IT KEEPS FROM BEING VACUOUS
    It builds the row with the router's OWN `_new_client_row` (not a copy of what the router does) and inserts it
    the way PostgREST does: a column list of exactly the keys present, values from the JSON. An omitted key takes
    the column default; a null key is written as NULL. The first test shows that the payload the door used to
    send IS refused by this schema, so the second cannot pass just because the insert is lenient.

Runs only when HARNESS_PG is set and psql is on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid

import pytest

from models.client import ClientCreate
from routers.clients import _new_client_row

_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None,
    reason="the client door proof requires HARNESS_PG + psql",
)

FIRM = "aaaaaaaa-0000-0000-0000-000000000c05"


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    return subprocess.run(args + ["-c", sql], capture_output=True, text=True)


@pytest.fixture()
def dsn(pg_template):
    admin = _ADMIN.strip()
    name = f"clientdoor_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{name}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={name}"
    try:
        assert "420_a_clients_own_registration_can_be_composition_too.sql" not in pg_template.failed, (
            "migration 420 did not apply -- the column under test would not exist")
        r = _psql(dsn, f"INSERT INTO firms (id, name, email) VALUES ('{FIRM}', 'F', 'f@t.in');")
        assert r.returncode == 0, r.stderr
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def _insert_like_postgrest(dsn: str, row: dict) -> subprocess.CompletedProcess:
    """INSERT exactly the keys in `row`, values taken from its JSON.

    PostgREST builds ``INSERT INTO t (<keys>) SELECT <keys> FROM json_populate_record(null::t, $body)``: a key
    that is absent is not in the column list and so takes its DEFAULT, while a key present with a JSON null is
    inserted as NULL. That difference is the whole defect.
    """
    keys = list(row)
    cols = ", ".join(f'"{k}"' for k in keys)
    body = json.dumps(row, default=str).replace("'", "''")
    return _psql(
        dsn,
        f"INSERT INTO clients ({cols}) SELECT {cols} "
        f"FROM jsonb_populate_record(null::clients, '{body}'::jsonb);",
    )


def _minimal(**overrides) -> ClientCreate:
    fields = dict(client_name="Minimal Traders", entity_type="Proprietorship", pan="ABCPD1234E")
    fields.update(overrides)
    return ClientCreate(**fields)


def test_the_payload_the_door_used_to_send_is_refused_by_this_schema(dsn):
    """The premise. Without it the next test could pass against a schema that tolerated the null."""
    old = {**_minimal().model_dump(), "firm_id": FIRM}
    assert old["gst_registration_type"] is None
    r = _insert_like_postgrest(dsn, old)
    assert r.returncode != 0
    assert "gst_registration_type" in r.stderr and "not-null" in r.stderr


def test_a_body_that_names_no_registration_type_inserts_and_takes_the_default(dsn):
    row = _new_client_row(_minimal(), FIRM)
    assert "gst_registration_type" not in row
    r = _insert_like_postgrest(dsn, row)
    assert r.returncode == 0, r.stderr
    got = _psql(dsn, "SELECT gst_registration_type FROM clients WHERE client_name = 'Minimal Traders';", tuples=True)
    assert got.stdout.strip() == "regular"


def test_a_registration_type_the_caller_states_is_kept(dsn):
    row = _new_client_row(
        _minimal(client_name="Composition Co", gst_registration_type="composition",
                 composition_category="restaurant"),
        FIRM,
    )
    assert row["gst_registration_type"] == "composition"
    r = _insert_like_postgrest(dsn, row)
    assert r.returncode == 0, r.stderr
    got = _psql(dsn, "SELECT gst_registration_type, composition_category FROM clients "
                     "WHERE client_name = 'Composition Co';", tuples=True)
    assert got.stdout.strip() == "composition|restaurant"


def test_every_other_field_of_the_body_still_reaches_the_row(dsn):
    """Only the not-stated key is dropped: the rest of the dump is what the door always sent."""
    body = _minimal(gstin=None, mobile="9999999999", email="a@b.in", city="Pune", state="Maharashtra",
                    state_code="27", notes="seeded")
    row = _new_client_row(body, FIRM)
    assert {k: v for k, v in row.items() if k != "gst_registration_type"} == {
        **{k: v for k, v in body.model_dump().items() if k != "gst_registration_type"}, "firm_id": FIRM}
    assert _insert_like_postgrest(dsn, row).returncode == 0
