"""A bank rule created through the API never sends a null for a column the database defaults.

The mock-mode half of `test_the_rule_door_accepts_a_minimal_body_pg.py`, stated as the RULE and read from the committed
production snapshot (tests/fixtures/production_schema_*.json): every field of `MatchingRuleIn` that defaults to None
whose `bank_matching_rules` column is NOT NULL with a default must be left out of the insert when it is None. The class
is the one `test_a_new_client_row_sends_no_null_for_a_column_the_database_defaults.py` states for clients: PostgREST
inserts exactly the keys it is sent, so a null reaches a NOT NULL column and the default never applies. A field added to
the model (or a column added by a migration) over a column like that fails here instead of at a seeder run.
"""
from __future__ import annotations

import json
from pathlib import Path

from models.banking import MatchingRuleIn
from routers.banking import _RULE_KEYS_OMITTED_WHEN_NOT_STATED, _rule_fields

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _rule_columns() -> dict:
    snapshots = sorted(p for p in FIXTURES.glob("production_schema_*.json")
                       if not p.name.endswith(".meta.json"))
    assert snapshots, "no production schema snapshot to read the bank_matching_rules columns from"
    return json.loads(snapshots[-1].read_text())["bank_matching_rules"]


def _minimal() -> MatchingRuleIn:
    return MatchingRuleIn(client_id="c", rule_name="Rent", description_pattern="Rent -", txn_type="debit",
                          suggested_narration="Rent paid")


def test_the_premise_the_flag_is_not_null_with_a_default_in_the_snapshot():
    col = _rule_columns()["flags_tds_decision"]
    assert col["nullable"] == "NO" and col["default"], col


def test_a_field_that_defaults_to_none_over_a_not_null_default_column_is_left_out():
    cols = _rule_columns()
    must_omit = {
        name for name, field in MatchingRuleIn.model_fields.items()
        if field.default is None and name in cols
        and cols[name]["nullable"] == "NO" and cols[name]["default"] != ""
    }
    assert must_omit, "the rule found nothing to apply to -- the premise test above should have failed"
    assert must_omit <= set(_RULE_KEYS_OMITTED_WHEN_NOT_STATED), (
        f"{sorted(must_omit - set(_RULE_KEYS_OMITTED_WHEN_NOT_STATED))} default to None in MatchingRuleIn over a "
        "column the database defaults: add them to _RULE_KEYS_OMITTED_WHEN_NOT_STATED")


def test_the_minimal_body_builds_a_row_with_no_such_null():
    cols = _rule_columns()
    fields = _rule_fields(_minimal())
    bad = [k for k, v in fields.items() if v is None and k in cols and cols[k]["nullable"] == "NO"]
    assert bad == [], f"would be inserted as NULL into a NOT NULL column: {bad}"


def test_a_stated_flag_is_kept_and_a_nullable_none_stays_a_null():
    for flag in (True, False):
        stated = MatchingRuleIn(client_id="c", rule_name="r", description_pattern="x",
                                suggested_narration="n", flags_tds_decision=flag)
        assert _rule_fields(stated)["flags_tds_decision"] is flag
    # A nullable column keeps its null: NULL there means "not set", which is true.
    assert "suggested_account_id" in _rule_fields(_minimal())
    assert _rule_fields(_minimal())["suggested_account_id"] is None
