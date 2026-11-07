"""A bank rule that tags a customer or a supplier names one of its own client's, asked when the rule is saved (POST-A-373).

WHAT WAS WRONG
    A bank rule may tag the party a line was with (migration 404): `payee_type` and `payee_id`. The create and update models checked the
    pair's SHAPE and the routes the pairing (`_refuse_an_unresolvable_party`) and nothing else, so a rule could be saved naming a customer or
    supplier of the firm's OTHER client, or an id that is nobody's, and it failed later: once for every line it was applied to, in
    `bank_payee_service.apply_rule_party`, where the failure is deliberately swallowed as a soft one (a tag is a label and must not stop a line
    being coded and posted). So the CA saw a rule that saved, and lines that never got the tag.

    The party's own check also told its refusals apart ("does not belong to this firm" for a party that is not there or is another firm's,
    "belongs to a different client" for a sibling's), which let a caller learn that an id was a real party of the firm's other client.

WHAT IS ASSERTED
    * THE SAVE ASKS. Creating a rule, or editing one to name a party, with a party of a sibling client, of another firm or of nobody answers
      404 "That customer was not found." (the words every named row gets) and writes nothing; the client's own party is saved.
    * AN EDIT THAT NAMES NO PARTY DOES NOT ASK. A rule whose stored party has since been deleted can still be renamed, switched off or given a
      ledger: only an edit that names a party is asked about it.
    * 'OTHER' IS UNTOUCHED. A name with no link has no id to ask about.
    * ONE SENTENCE. Setting a payee by hand answers an absent party, a sibling's and another firm's in one status and one sentence
      (`tests/test_bank_payee_service.py` holds the service half; this file holds that the rule door says the same).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.banking as bank
from models.banking import MatchingRuleIn, MatchingRuleUpdateIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
OTHER_FIRM = "99999999-9999-9999-9999-999999999999"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    for client, tag in ((A, "a"), (B, "b")):
        db.seed("clients", {"id": client, "firm_id": FIRM})
        db.seed("customers", {"id": f"customer-{tag}", "firm_id": FIRM, "client_id": client, "name": f"Customer {tag}"})
        db.seed("vendors", {"id": f"vendor-{tag}", "firm_id": FIRM, "client_id": client, "name": f"Vendor {tag}"})
    db.seed("customers", {"id": "customer-x", "firm_id": OTHER_FIRM, "client_id": A, "name": "Another firm's"})
    wire_e2e(monkeypatch, db, [bank])
    monkeypatch.setattr(bank, "_db", lambda: db)
    monkeypatch.setattr(bank, "privileged_for", lambda d: d)
    monkeypatch.setattr(bank.bank_entry_service, "mark_stale", lambda *a, **k: None)
    return db


def _new(**kw) -> MatchingRuleIn:
    return MatchingRuleIn(client_id=A, rule_name="Netflix", description_pattern="netflix", suggested_narration="Subscription", **kw)


# ── the save asks ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ptype,own", [("customer", "customer-a"), ("vendor", "vendor-a")])
def test_a_rule_naming_the_clients_own_party_is_saved(world, ptype, own):
    out = bank.create_rule(_new(payee_type=ptype, payee_id=own), PARTNER)
    assert out["success"] is True
    saved = world.rows("bank_matching_rules")
    assert len(saved) == 1 and saved[0]["payee_id"] == own and saved[0]["payee_type"] == ptype


@pytest.mark.parametrize("ptype,sibling,other_firm", [("customer", "customer-b", "customer-x"), ("vendor", "vendor-b", "vendor-x")])
def test_a_party_of_a_sibling_client_of_another_firm_and_an_invented_one_are_refused_in_the_same_words(world, ptype, sibling, other_firm):
    answers = set()
    for named in (sibling, other_firm, "no-such-party"):
        with pytest.raises(HTTPException) as e:
            bank.create_rule(_new(payee_type=ptype, payee_id=named), PARTNER)
        answers.add((e.value.status_code, e.value.detail))
    assert answers == {(404, f"That {ptype} was not found.")}
    assert world.rows("bank_matching_rules") == [], "a refused rule must write nothing"


def test_a_rule_that_tags_a_name_only_asks_about_no_party(world):
    out = bank.create_rule(_new(payee_type="other"), PARTNER)
    assert out["success"] is True and world.rows("bank_matching_rules")[0].get("payee_id") in (None, "")


def test_a_rule_that_tags_nobody_asks_about_no_party(world, monkeypatch):
    def never(*a, **k):
        raise AssertionError("a party was asked about although the rule names none")

    monkeypatch.setattr(bank, "customer_is_the_clients", never)
    monkeypatch.setattr(bank, "vendor_is_the_clients", never)
    assert bank.create_rule(_new(), PARTNER)["success"] is True


# ── the edit asks only when it names a party ─────────────────────────────────────────────────────────────
@pytest.fixture
def rule(world):
    world.seed("bank_matching_rules", {"id": "RULE-1", "firm_id": FIRM, "client_id": A, "rule_name": "Netflix", "description_pattern": "netflix",
                                       "payee_type": "vendor", "payee_id": "vendor-a", "is_active": True})
    return world


def test_an_edit_that_moves_a_rule_to_a_sibling_clients_party_is_refused_and_changes_nothing(rule):
    with pytest.raises(HTTPException) as e:
        bank.update_rule("RULE-1", MatchingRuleUpdateIn(payee_type="vendor", payee_id="vendor-b"), PARTNER)
    assert (e.value.status_code, e.value.detail) == (404, "That vendor was not found.")
    assert rule.rows("bank_matching_rules")[0]["payee_id"] == "vendor-a"


def test_an_edit_that_changes_only_the_type_is_asked_against_the_stored_id(rule):
    """A vendor's id under 'customer' is no customer of this client: the pair is judged merged, as the pairing rule is."""
    with pytest.raises(HTTPException) as e:
        bank.update_rule("RULE-1", MatchingRuleUpdateIn(payee_type="customer"), PARTNER)
    assert (e.value.status_code, e.value.detail) == (404, "That customer was not found.")
    assert rule.rows("bank_matching_rules")[0]["payee_type"] == "vendor"


def test_an_edit_to_the_clients_own_other_party_is_saved(rule):
    bank.update_rule("RULE-1", MatchingRuleUpdateIn(payee_type="customer", payee_id="customer-a"), PARTNER)
    assert rule.rows("bank_matching_rules")[0]["payee_id"] == "customer-a"


def test_a_rule_whose_stored_party_has_gone_can_still_be_renamed_and_switched_off(rule):
    """The party was deleted after the rule was saved. Asking about it on every edit would lock the rule; the edit names no party, so none is asked."""
    rule._tables["vendors"] = [r for r in rule.rows("vendors") if r["id"] != "vendor-a"]
    assert not any(r["id"] == "vendor-a" for r in rule.rows("vendors"))
    bank.update_rule("RULE-1", MatchingRuleUpdateIn(rule_name="Netflix India", is_active=False), PARTNER)
    saved = rule.rows("bank_matching_rules")[0]
    assert saved["rule_name"] == "Netflix India" and saved["is_active"] is False
