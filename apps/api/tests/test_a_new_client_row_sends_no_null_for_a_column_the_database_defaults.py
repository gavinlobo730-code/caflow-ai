"""A client created through the API never sends a null for a column the database defaults.

WHAT WAS WRONG
    `ClientCreate.gst_registration_type` is None when a body does not state one, and `create_client` inserted
    `body.model_dump()`. The column is NOT NULL DEFAULT 'regular' (migration 420); PostgREST writes exactly the keys
    it is sent, so the null reached the column and the create answered 400 "A required value was missing". The real
    -Postgres proof is `test_the_client_door_accepts_a_minimal_body_pg.py`; this is the half the mock-mode job can
    run, and it states the RULE rather than the one field:

        every field of ClientCreate that defaults to None and whose clients column is NOT NULL with a default is
        left out of the insert when it is None.

    The column facts are read from the committed production snapshot (tests/fixtures/production_schema_*.json), so a
    field added to the model later, over a column like that, fails here instead of at a seeder run.
"""
from __future__ import annotations

import json
from pathlib import Path

from models.client import ClientCreate
from routers.clients import _OMITTED_WHEN_NOT_STATED, _new_client_row

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIRM = "FIRM-A"


def _clients_columns() -> dict:
    snapshots = sorted(p for p in FIXTURES.glob("production_schema_*.json")
                       if not p.name.endswith(".meta.json"))
    assert snapshots, "no production schema snapshot to read the clients columns from"
    return json.loads(snapshots[-1].read_text())["clients"]


def _minimal() -> ClientCreate:
    return ClientCreate(client_name="Minimal Traders", entity_type="Proprietorship", pan="ABCPD1234E")


def test_the_premise_a_column_with_a_default_is_not_null_in_the_snapshot():
    col = _clients_columns()["gst_registration_type"]
    assert col["nullable"] == "NO" and col["default"], col


def test_a_field_that_defaults_to_none_over_a_not_null_default_column_is_left_out():
    cols = _clients_columns()
    must_omit = {
        name for name, field in ClientCreate.model_fields.items()
        if field.default is None and name in cols
        and cols[name]["nullable"] == "NO" and cols[name]["default"] != ""
    }
    assert must_omit, "the rule found nothing to apply to -- the premise test above should have failed"
    assert must_omit <= set(_OMITTED_WHEN_NOT_STATED), (
        f"{sorted(must_omit - set(_OMITTED_WHEN_NOT_STATED))} default to None in ClientCreate over a column the "
        "database defaults: add them to _OMITTED_WHEN_NOT_STATED so the insert leaves the key out")


def test_the_minimal_body_builds_a_row_with_no_such_null():
    cols = _clients_columns()
    row = _new_client_row(_minimal(), FIRM)
    bad = [k for k, v in row.items()
           if v is None and k in cols and cols[k]["nullable"] == "NO"]
    assert bad == [], f"would be inserted as NULL into a NOT NULL column: {bad}"
    assert row["firm_id"] == FIRM


def test_a_stated_value_is_kept_and_only_the_not_stated_one_is_dropped():
    row = _new_client_row(
        ClientCreate(client_name="C", entity_type="Proprietorship", pan="ABCPD1234E",
                     gst_registration_type="Composition", composition_category="restaurant"),
        FIRM,
    )
    assert row["gst_registration_type"] == "composition", "the validator's own canonical form"
    assert row["composition_category"] == "restaurant"
    # A nullable column keeps its null: NULL there means "unrecorded", which is true.
    assert "gstin" in _new_client_row(_minimal(), FIRM)
