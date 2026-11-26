"""POST-A-399, the bank matching rule: an emptied box on the rule form clears the stored value, and a clear never leaves a rule the create
door would refuse.

The rule form has always sent an emptied box as null (a narration phrase, an amount bound, the proposed ledger, category, narration and
GST rate), and the route read its body with `exclude_none`, so only the GST rate could be taken away (by a hand-written exception) and the
screen said "Rule saved" over every other. The route reads through `models.clearable.patch_dict` now, and the merged rule is judged by the
create door's own shape after a clear.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from models.banking import MatchingRuleUpdateIn
from tests.test_bank_charge_gst_posting import PARTNER, rules_db  # noqa: F401  (the fixture)


def _stored(db):
    return db.store["bank_matching_rules"][0]


@pytest.mark.parametrize("field, before", [
    ("suggested_narration", "Bank charges for the month"),
    ("suggested_category", "Expense"),
    ("amount_min_paise", 10_000),
    ("amount_max_paise", 90_000),
    ("suggested_gst_rate_bps", 1800),
])
def test_a_soft_box_sent_as_null_is_cleared_and_reads_back_null(rules_db, field, before):  # noqa: F811
    db, router = rules_db
    _stored(db)[field] = before
    router.update_rule("r1", MatchingRuleUpdateIn(**{field: None}), current_user=PARTNER)
    assert _stored(db)[field] is None


def test_a_blank_narration_phrase_is_a_clear_when_another_condition_remains(rules_db):  # noqa: F811
    db, router = rules_db
    _stored(db).update(description_pattern="BANK CHARGES", txn_type="debit")
    router.update_rule("r1", MatchingRuleUpdateIn(description_pattern="  "), current_user=PARTNER)
    assert _stored(db)["description_pattern"] is None


def test_a_field_not_sent_is_left_alone_and_a_null_for_a_field_that_is_not_clearable_is_not_sent(rules_db):  # noqa: F811
    db, router = rules_db
    _stored(db)["suggested_narration"] = "kept"
    router.update_rule("r1", MatchingRuleUpdateIn(rule_name="Renamed", txn_type=None, priority=None), current_user=PARTNER)
    assert _stored(db)["suggested_narration"] == "kept" and _stored(db)["rule_name"] == "Renamed"
    assert "txn_type" not in _stored(db) or _stored(db)["txn_type"] is not None


def test_clearing_the_only_condition_is_refused_in_the_create_door_s_words(rules_db):  # noqa: F811
    db, router = rules_db
    with pytest.raises(HTTPException) as e:
        router.update_rule("r1", MatchingRuleUpdateIn(description_pattern=None), current_user=PARTNER)
    assert e.value.status_code == 422 and "at least one condition" in e.value.detail
    assert _stored(db)["description_pattern"] == "BANK CHARGES"


def test_clearing_everything_the_rule_proposes_is_refused(rules_db):  # noqa: F811
    db, router = rules_db
    with pytest.raises(HTTPException) as e:
        router.update_rule("r1", MatchingRuleUpdateIn(suggested_category=None, suggested_account_id=None), current_user=PARTNER)
    assert e.value.status_code == 422 and "at least one suggestion" in e.value.detail
    assert _stored(db)["suggested_account_id"] == "acc-charges"


def test_clearing_the_ledger_under_a_gst_rate_is_refused(rules_db):  # noqa: F811
    db, router = rules_db
    _stored(db)["suggested_gst_rate_bps"] = 1800
    with pytest.raises(HTTPException) as e:
        router.update_rule("r1", MatchingRuleUpdateIn(suggested_account_id=None), current_user=PARTNER)
    assert e.value.status_code == 422 and "GST rate needs a ledger" in e.value.detail


def test_clearing_the_ledger_of_a_trusted_rule_is_refused(rules_db):  # noqa: F811
    db, router = rules_db
    _stored(db).update(is_trusted=True, trusted_by="u1")
    with pytest.raises(HTTPException) as e:
        router.update_rule("r1", MatchingRuleUpdateIn(suggested_account_id=None), current_user=PARTNER)
    assert e.value.status_code == 422 and "trusted rule must name a ledger" in e.value.detail
    assert _stored(db)["suggested_account_id"] == "acc-charges"


def test_an_edit_that_clears_nothing_is_not_judged_again(rules_db):  # noqa: F811
    """A rule stored before a check existed stays editable: its name can be changed without the shape being asked."""
    db, router = rules_db
    _stored(db).update(description_pattern=None, suggested_category=None)
    router.update_rule("r1", MatchingRuleUpdateIn(rule_name="Old rule"), current_user=PARTNER)
    assert _stored(db)["rule_name"] == "Old rule"


def test_the_mock_mode_branch_clears_too(monkeypatch):
    import routers.banking as banking_router
    monkeypatch.setattr(banking_router, "_db", lambda: None)
    out = banking_router.update_rule("r1", MatchingRuleUpdateIn(suggested_narration=None, txn_type=None), current_user=PARTNER)
    assert out["data"] == {"id": "r1", "suggested_narration": None}


# ── what the independent review found: a condition CHANGED, not cleared, can leave a rule with nothing to fire on ──────────

def test_emptying_the_list_of_patterns_on_a_rule_whose_only_condition_it_is_is_refused(rules_db):  # noqa: F811
    db, router = rules_db
    _stored(db).update(description_pattern=None, description_patterns=["BANK CHARGES"], txn_type="any",
                       amount_min_paise=None, amount_max_paise=None)
    with pytest.raises(HTTPException) as e:
        router.update_rule("r1", MatchingRuleUpdateIn(description_patterns=[]), current_user=PARTNER)
    assert e.value.status_code == 422 and "at least one condition" in e.value.detail
    assert _stored(db)["description_patterns"] == ["BANK CHARGES"]


def test_setting_the_type_back_to_any_on_a_rule_whose_only_condition_is_debit_is_refused(rules_db):  # noqa: F811
    db, router = rules_db
    _stored(db).update(description_pattern=None, description_patterns=None, txn_type="debit",
                       amount_min_paise=None, amount_max_paise=None)
    with pytest.raises(HTTPException) as e:
        router.update_rule("r1", MatchingRuleUpdateIn(txn_type="any"), current_user=PARTNER)
    assert e.value.status_code == 422 and "at least one condition" in e.value.detail
    assert _stored(db)["txn_type"] == "debit"


def test_changing_a_condition_to_another_condition_is_still_allowed(rules_db):  # noqa: F811
    db, router = rules_db
    router.update_rule("r1", MatchingRuleUpdateIn(description_pattern="NEFT"), current_user=PARTNER)
    assert _stored(db)["description_pattern"] == "NEFT"
