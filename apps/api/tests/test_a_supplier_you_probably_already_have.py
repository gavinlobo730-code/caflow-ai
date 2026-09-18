"""PUR-32 — a party with a name you already have is REPORTED, never merged.

The GSTIN/PAN guard is unchanged and still refuses a second active party that
matches on either, because those identify the entity. This is the population it
cannot reach: an unregistered supplier below the CGST §22 threshold, whose PAN
a practice does not hold, entered twice.

Every assertion here is about a DIFFERENCE between two answers — merged vs
reported, same name vs same base name, active vs retired — because a single
answer that happens to be right proves nothing about a rule with two limbs.
"""
from __future__ import annotations

import pytest

from domain.party_duplicates import (
    SAME_NAME,
    SAME_NAME_DIFFERENT_FORM,
    EXPLANATIONS,
    normalise_party_name,
    possible_duplicates,
)


def _rows(*names: str) -> list[dict]:
    return [{"id": f"v{i}", "name": n, "is_active": True}
            for i, n in enumerate(names)]


# ── what folds, and what must not ────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("Sharma Traders", "sharma traders"),                 # case
    ("Sharma Traders", "  Sharma   Traders  "),           # whitespace
    ("Sharma Traders", "Sharma Traders."),                # punctuation
    ("Sharma Traders", "Sharma-Traders"),
    ("Sharma Traders", "M/s Sharma Traders"),             # the honorific
    ("Sharma Traders", "M/S. Sharma Traders"),
    ("Sharma & Co", "Sharma and Co"),                     # the ampersand
    ("Sharma Traders Pvt Ltd", "Sharma Traders Private Limited"),
    ("Sharma Traders Pvt. Ltd.", "Sharma Traders P Ltd"),
    ("Sharma Traders Ltd", "Sharma Traders Limited"),
])
def test_these_are_one_name(a, b):
    assert normalise_party_name(a).normalised == normalise_party_name(b).normalised
    assert [d.reason for d in possible_duplicates(a, _rows(b))] == [SAME_NAME]


def test_an_llp_is_not_the_company_of_the_same_name():
    """LLP Act 2008: a different legal person, its own PAN, its own return.
    Dropping the entity form altogether — the obvious simplification — would
    report these two as one party."""
    a = normalise_party_name("Sharma Traders LLP")
    b = normalise_party_name("Sharma Traders Pvt Ltd")
    assert a.normalised != b.normalised
    assert a.form == "llp" and b.form == "ltd"
    # They share a BASE, so the weaker limb still names them — which is the
    # honest answer: two real parties, often in one promoter group.
    assert [d.reason for d in possible_duplicates("Sharma Traders LLP",
                                                  _rows("Sharma Traders Pvt Ltd"))] \
        == [SAME_NAME_DIFFERENT_FORM]


def test_a_bare_name_and_a_company_are_the_weaker_limb():
    """The commonest real duplicate, and also a real pattern of its own: the
    proprietorship and the company that succeeded it."""
    found = possible_duplicates("Sharma Traders", _rows("Sharma Traders Pvt Ltd"))
    assert [d.reason for d in found] == [SAME_NAME_DIFFERENT_FORM]


@pytest.mark.parametrize("other", [
    "Sharma Trading Co",     # one word different — plausibly another business
    "Sharma Electronics",
    "Sharma",                # a substring is not a match
    "Verma Traders",
])
def test_these_are_not_reported(other):
    """Deliberately not an edit distance and not a substring: a warning that
    fires on most rows is a warning a CA stops reading. near_duplicate.py
    reached the same conclusion after its first draft used edit distance."""
    assert possible_duplicates("Sharma Traders", _rows(other)) == []


# ── what the two limbs mean, and the scope of the question ───────────────────

def test_the_two_reasons_are_different_sentences():
    """A shared sentence would make the weaker limb assert the stronger one's
    claim. Asserted on the ANSWERS, so moving a reason cannot make it vacuous."""
    assert EXPLANATIONS[SAME_NAME] != EXPLANATIONS[SAME_NAME_DIFFERENT_FORM]
    assert "two parties" in EXPLANATIONS[SAME_NAME_DIFFERENT_FORM]
    assert "not merged" in EXPLANATIONS[SAME_NAME]


def test_a_retired_namesake_is_not_reported():
    rows = [{"id": "v1", "name": "Sharma Traders", "is_active": False}]
    assert possible_duplicates("Sharma Traders", rows) == []


def test_a_row_never_reports_itself():
    rows = _rows("Sharma Traders")
    assert possible_duplicates("Sharma Traders", rows, exclude_id="v0") == []


def test_an_empty_name_asks_nothing():
    """A party with no name is the required-field check's problem. Answering
    here would report every unnamed row against every other."""
    assert possible_duplicates("", _rows("Sharma Traders")) == []
    assert possible_duplicates("   ", _rows("Sharma Traders")) == []
    # And a candidate with no name is skipped rather than matching the blank.
    assert possible_duplicates("Sharma Traders", [{"id": "v1", "name": "", "is_active": True}]) == []


def test_a_name_that_is_only_an_entity_form_matches_nothing():
    """`Ltd` normalises to a form with no base. Comparing on the form alone
    would report every company against every other."""
    assert normalise_party_name("Ltd").base == ""
    assert possible_duplicates("Ltd", _rows("Sharma Traders Ltd")) == []


def test_the_exact_match_is_listed_first():
    found = possible_duplicates(
        "Sharma Traders",
        _rows("Sharma Traders Pvt Ltd", "M/s SHARMA TRADERS"))
    assert [d.reason for d in found] == [SAME_NAME, SAME_NAME_DIFFERENT_FORM]


def test_it_carries_the_identifiers_so_the_screen_can_tell_them_apart():
    """Two genuine `Sharma Traders` in two cities are told apart by GSTIN or
    PAN, which is exactly what the CA needs to see beside the warning."""
    rows = [{"id": "v1", "name": "Sharma Traders", "is_active": True,
             "gstin": "27AABCU9603R1ZX", "pan": "AABCU9603R"}]
    d = possible_duplicates("SHARMA TRADERS", rows)[0].as_dict()
    assert d["gstin"] == "27AABCU9603R1ZX" and d["pan"] == "AABCU9603R"
    assert d["explanation"] == EXPLANATIONS[SAME_NAME]


# ── the doors ────────────────────────────────────────────────────────────────

def test_both_create_doors_report_and_neither_refuses():
    """A validator on one door only is one PATCH from being none, and these
    two create paths have mirrored each other since they were written."""
    import uuid as _uuid
    from routers.vendors import create_vendor, MOCK_VENDORS
    from routers.customers import create_customer, MOCK_CUSTOMERS
    from models.parties import VendorIn, CustomerIn

    client_id, firm_id = str(_uuid.uuid4()), "firm-dup"
    user = {"id": "u1", "firm_id": firm_id, "role": "Partner",
            "auth_user_id": "a1", "email": "p@example.com"}

    for door, model, store, key in (
        (create_vendor, VendorIn, MOCK_VENDORS, "vendor"),
        (create_customer, CustomerIn, MOCK_CUSTOMERS, "customer"),
    ):
        first = door(model(client_id=client_id, name="Sharma Traders"), current_user=user)
        assert first["success"] and first["data"]["possible_duplicates"] == [], key

        second = door(model(client_id=client_id, name="M/s SHARMA TRADERS."),
                      current_user=user)
        # CREATED, not refused and not merged: a new id, and the store grew.
        assert second["success"], key
        assert second["data"]["id"] != first["data"]["id"], key
        assert second["data"].get("duplicate") is not True, key
        assert [d["reason"] for d in second["data"]["possible_duplicates"]] == [SAME_NAME], key
        assert sum(1 for r in store if r.get("client_id") == client_id) == 2, key
