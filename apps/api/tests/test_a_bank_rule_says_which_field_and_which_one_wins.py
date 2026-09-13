"""
A bank rule says WHICH FIELD it reads, HOW it compares, how many alternatives
it accepts, and WHICH RULE WINS. BANK-11 steps 1 and 2, migration 380.

WHAT WAS WRONG
    `domain/banking/rules.rule_matches` was one case-insensitive substring of
    the narration, an amount range and a direction — the whole engine. Two
    consequences a practice meets every month:

    PRECEDENCE WAS CREATION ORDER, with no way to change it. Three fetch sites
    ordered by `created_at` and `match_rule` takes the FIRST firing rule, so a
    broad rule written in April permanently shadowed the narrow one written in
    July. The only remedy available to a CA was to delete and re-create the
    broad rule — which loses its TRUSTED flag, and a trusted rule is the one
    place this product acts unprompted.

    ONE PATTERN, ONE FIELD. "NEFT from any of these three customers" was three
    rules. A UTR or cheque number in `bank_transactions.reference_no` — often
    the only stable part of a line whose narration the bank rewrites every
    month — could not be matched at all, though the column has been there
    throughout, and neither could the `payee_name` the normaliser extracts.

THE LINE THIS DOES NOT CROSS
    WHAT A RULE MAY PROPOSE IS UNCHANGED. A trusted rule passes its lines with
    no click (migration 322), so widening the PAYLOAD — split legs, a party, a
    TDS treatment, which are BANK-11's step 3 — widens what happens with nobody
    watching, and that is an owner decision rather than a side effect of better
    matching. Matching wider is different in kind: a CA types every pattern
    themselves, and the widest case has always been reachable anyway (an empty
    `description_pattern` matches every transaction).

WHAT EVERY DEFAULT DOES
    Reproduces today's behaviour exactly. `priority` defaults to 100 with
    `created_at` as the tiebreak, `match_field` to 'description',
    `match_operator` to 'contains', `description_patterns` to NULL — so no
    existing rule changes which transactions it fires on or which rule it
    beats. The migration's backfill is the DEFAULT; there is no UPDATE.
"""
from __future__ import annotations

import pytest

from domain.banking.rules import (
    MATCH_FIELDS, MATCH_OPERATORS, by_precedence, match_rule, rule_matches,
)
from models.banking import MatchingRuleIn, MatchingRuleUpdateIn


def _rule(**over):
    r = {"id": "R", "rule_name": "r", "is_active": True,
         "suggested_category": "Expense"}
    r.update(over)
    return r


# ── Nothing existing moves ───────────────────────────────────────────────────

def test_a_rule_with_none_of_the_new_columns_behaves_exactly_as_before():
    """The whole safety argument. A row written before migration 380 has NULL
    for all four, and NULL must read as the historic behaviour rather than as
    'no field to match against'."""
    r = _rule(description_pattern="bank charges")
    assert rule_matches(r, "HDFC BANK CHARGES JUL", 5000, True)
    assert not rule_matches(r, "NEFT ACME TRADERS", 5000, True)


def test_a_rule_with_no_pattern_still_matches_everything():
    """An amount-only or direction-only rule is legitimate and always has been."""
    assert rule_matches(_rule(txn_type="debit"), "anything at all", 1, True)


# ── Which field ──────────────────────────────────────────────────────────────

def test_the_field_map_is_the_one_the_database_check_allows():
    assert set(MATCH_FIELDS) == {"description", "reference_no", "payee_name", "any"}
    assert MATCH_OPERATORS == ("contains", "starts_with", "equals")


def test_a_reference_only_rule_ignores_the_narration():
    """The case the finding is about: the bank rewrites the narration monthly
    and the UTR is the stable part."""
    r = _rule(description_pattern="UTR123", match_field="reference_no")
    assert rule_matches(r, "SOMETHING ELSE ENTIRELY", 100, True, reference_no="utr123456")
    assert not rule_matches(r, "UTR123 IN THE NARRATION", 100, True, reference_no="")


def test_a_payee_rule_reads_the_payee():
    r = _rule(description_pattern="acme", match_field="payee_name")
    assert rule_matches(r, "", 100, True, payee_name="ACME Traders Pvt Ltd")
    assert not rule_matches(r, "ACME in the narration", 100, True, payee_name="Other")


def test_any_reads_all_three():
    r = _rule(description_pattern="acme", match_field="any")
    assert rule_matches(r, "NEFT ACME", 100, True)
    assert rule_matches(r, "", 100, True, reference_no="ACME/2026/1")
    assert rule_matches(r, "", 100, True, payee_name="Acme Traders")
    assert not rule_matches(r, "x", 100, True, reference_no="y", payee_name="z")


def test_a_rule_naming_a_field_the_caller_did_not_supply_simply_does_not_fire():
    """The safe direction, and it matters because a trusted rule posts
    unattended: failing to match costs a click, matching wrongly costs a
    journal."""
    r = _rule(description_pattern="utr1", match_field="reference_no")
    assert not rule_matches(r, "UTR1 EVERYWHERE", 100, True)


def test_an_unknown_field_or_operator_falls_back_to_the_historic_behaviour():
    """A CHECK stops these reaching the database, but a hand-written row or a
    later value must not turn a narrow rule into one that matches nothing —
    or, worse, everything."""
    r = _rule(description_pattern="charges", match_field="nonsense",
              match_operator="regex")
    assert rule_matches(r, "BANK CHARGES", 100, True)


# ── How it compares ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("operator,narration,expected", [
    ("contains", "HDFC BANK CHARGES", True),
    # The same narration under the two operators, which is the whole point of
    # having them: 'contains' finds the pattern anywhere, 'starts_with' only at
    # the head. A bank that prefixes its own name is the everyday case.
    ("contains", "SBI HDFC BANK CHARGES", True),
    ("starts_with", "hdfc bank charges", True),
    ("starts_with", "SBI HDFC BANK CHARGES", False),
    ("equals", "hdfc bank charges", True),
    ("equals", "hdfc bank charges jul", False),
])
def test_the_operator_decides(operator, narration, expected):
    r = _rule(description_pattern="hdfc bank charges", match_operator=operator)
    assert rule_matches(r, narration, 100, True) is expected


# ── Alternatives ─────────────────────────────────────────────────────────────

def test_three_customers_are_one_rule():
    r = _rule(description_pattern="acme traders",
              description_patterns=["acme exports", "acme pvt ltd"])
    for name in ("NEFT ACME TRADERS", "RTGS ACME EXPORTS", "IMPS ACME PVT LTD"):
        assert rule_matches(r, name, 100, False), name
    assert not rule_matches(r, "NEFT BETA CORP", 100, False)


def test_the_alternatives_use_the_same_field_and_operator():
    r = _rule(description_pattern="a/1", description_patterns=["b/2"],
              match_field="reference_no", match_operator="equals")
    assert rule_matches(r, "", 100, True, reference_no="B/2")
    assert not rule_matches(r, "", 100, True, reference_no="xb/2")
    assert not rule_matches(r, "b/2", 100, True)


def test_a_blank_alternative_is_dropped_rather_than_matching_everything():
    """An empty pattern matches every transaction, so one stray blank row on
    the form would turn a narrow rule into a catch-all — and if that rule is
    trusted it posts them. Dropped in the model, and ignored by the engine
    even if one somehow reaches it."""
    cleaned = MatchingRuleIn(client_id="c", rule_name="r",
                             description_pattern="acme",
                             description_patterns=["", "  ", "beta"],
                             suggested_category="Expense")
    assert cleaned.description_patterns == ["beta"]
    r = _rule(description_pattern="acme", description_patterns=["", "  "])
    assert not rule_matches(r, "NEFT BETA", 100, True)


def test_an_alternatives_only_rule_is_a_real_rule():
    """It has a condition, so the model's 'a rule needs at least one condition'
    check must not refuse it — and the ENGINE must read it as a condition too.

    The engine side is the one that bites. `description_pattern` is blank on
    such a rule, and a blank pattern is contained in every string, so an engine
    that kept it beside the alternatives would fire on every transaction while
    reading, on the screen, as a rule about one customer.
    """
    m = MatchingRuleIn(client_id="c", rule_name="r",
                       description_patterns=["acme"], suggested_category="Expense")
    assert m.description_patterns == ["acme"]

    r = _rule(description_pattern=None, description_patterns=["acme"])
    assert rule_matches(r, "NEFT ACME TRADERS", 100, False)
    assert not rule_matches(r, "NEFT BETA CORP", 100, False)


# ── Which rule wins ──────────────────────────────────────────────────────────

def test_precedence_is_priority_then_creation_order():
    broad = _rule(id="broad", priority=100, created_at="2026-04-01",
                  description_pattern="neft", suggested_category="Expense")
    narrow = _rule(id="narrow", priority=10, created_at="2026-07-01",
                   description_pattern="neft acme", suggested_category="Income")
    assert [r["id"] for r in by_precedence([broad, narrow])] == ["narrow", "broad"]
    hit = match_rule("NEFT ACME TRADERS", 100, False, [broad, narrow])
    assert hit is not None and hit.rule_id == "narrow", (
        "the narrow rule was written later and would have been shadowed for ever")


def test_at_the_default_priority_the_order_is_exactly_creation_order():
    """What makes the migration safe: every existing rule keeps winning what
    it wins today."""
    first = _rule(id="first", created_at="2026-04-01", description_pattern="neft")
    second = _rule(id="second", created_at="2026-07-01", description_pattern="neft")
    assert [r["id"] for r in by_precedence([second, first])] == ["first", "second"]
    hit = match_rule("NEFT X", 100, False, [second, first])
    assert hit is not None and hit.rule_id == "first"


def test_a_rule_with_no_priority_at_all_sorts_with_the_defaults():
    """A row read back before the column existed, or a test double."""
    old = _rule(id="old", created_at="2026-01-01", description_pattern="x")
    new = _rule(id="new", priority=100, created_at="2026-02-01", description_pattern="x")
    assert [r["id"] for r in by_precedence([new, old])] == ["old", "new"]


def test_the_order_is_deterministic_when_priority_and_time_tie():
    """An unordered fetch made 'first' depend on whatever Postgres returned,
    which is the defect the created_at ordering was added for. The id is the
    last tiebreak so the answer never depends on list order."""
    a = _rule(id="aaa", priority=1, created_at="2026-01-01", description_pattern="x")
    b = _rule(id="bbb", priority=1, created_at="2026-01-01", description_pattern="x")
    assert [r["id"] for r in by_precedence([b, a])] == ["aaa", "bbb"]
    assert [r["id"] for r in by_precedence([a, b])] == ["aaa", "bbb"]


# ── The screen is shown the same order the engine evaluates in ───────────────

def test_the_rules_screen_lists_them_in_precedence_order(monkeypatch):
    """The list endpoint's ordering is not decoration.

    `by_precedence` re-sorts in Python, so matching is right whatever order the
    rows arrive in — which is exactly why this needs its own test. What the
    ordering decides is whether a CA can SEE which rule wins. A screen listing
    them by creation date while the engine evaluates by priority teaches the
    opposite of the truth, and the remedy a CA reaches for then is to delete
    and re-create a rule, which loses its TRUSTED flag.
    """
    import core.authz as authz
    import routers.banking as banking_router
    from tests.test_bank_matching import FakeDB, FIRM, CLIENT

    db = FakeDB()
    monkeypatch.setattr(banking_router, "_db", lambda: db)
    monkeypatch.setattr(authz, "_USE_MOCK", True)
    rows = db.store.setdefault("bank_matching_rules", [])
    for rid, priority, created in (("broad", 100, "2026-04-01"),
                                   ("narrow", 10, "2026-07-01"),
                                   ("later", 100, "2026-08-01")):
        rows.append({"id": rid, "firm_id": FIRM, "client_id": CLIENT,
                     "rule_name": rid, "is_active": True,
                     "description_pattern": "neft",
                     "suggested_category": "Other",
                     "priority": priority, "created_at": created})

    listed = banking_router.list_rules(
        client_id=CLIENT,
        current_user={"firm_id": FIRM, "role": "Partner",
                      "auth_user_id": "p1", "id": "u1"})["data"]
    assert [r["id"] for r in listed] == ["narrow", "broad", "later"]
    # And it is the SAME order the engine will evaluate them in.
    assert [r["id"] for r in by_precedence(rows)] == ["narrow", "broad", "later"]


# ── The boundary values are validated at BOTH doors ──────────────────────────

@pytest.mark.parametrize("field", sorted(MATCH_FIELDS))
def test_every_allowed_field_is_accepted(field):
    assert MatchingRuleIn(client_id="c", rule_name="r", description_pattern="x",
                          match_field=field,
                          suggested_category="Expense").match_field == field


def test_an_unknown_field_is_refused_at_create_and_at_edit():
    """A validator only at the create door is one PATCH from being none."""
    with pytest.raises(Exception):
        MatchingRuleIn(client_id="c", rule_name="r", description_pattern="x",
                       match_field="account_number", suggested_category="Expense")
    with pytest.raises(Exception):
        MatchingRuleUpdateIn(match_field="account_number")


def test_an_unknown_operator_is_refused_at_create_and_at_edit():
    with pytest.raises(Exception):
        MatchingRuleIn(client_id="c", rule_name="r", description_pattern="x",
                       match_operator="regex", suggested_category="Expense")
    with pytest.raises(Exception):
        MatchingRuleUpdateIn(match_operator="regex")


def test_the_model_reads_the_engines_own_map_rather_than_a_third_list():
    """Two lists drift; the CHECK in migration 380 is the third and cannot be
    imported, so it is pinned by the migration test below."""
    import inspect
    import models.banking as mb
    src = inspect.getsource(mb)
    assert "from domain.banking.rules import MATCH_FIELDS" in src
    assert "from domain.banking.rules import MATCH_OPERATORS" in src


def test_the_database_check_allows_exactly_what_the_engine_knows():
    """The migration's CHECK is the third statement of the same list. Read the
    file rather than restate it, so a value added to one and not the other
    fails here instead of at INSERT time on production."""
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parents[1]
           / "migrations/380_a_bank_rule_says_which_field_and_which_one_wins.sql").read_text()
    for f in MATCH_FIELDS:
        assert f"'{f}'" in sql, f
    for o in MATCH_OPERATORS:
        assert f"'{o}'" in sql, o


# ── What a rule may PROPOSE is untouched ─────────────────────────────────────

def test_this_change_added_nothing_to_what_a_rule_can_propose():
    """A trusted rule posts with no click. Split legs, a party and a TDS
    treatment are BANK-11's step 3 and are an owner decision — a guard, because
    the obvious next commit is to add one to `RuleSuggestion` and it would go
    straight into the unattended path."""
    from dataclasses import fields as dataclass_fields
    from domain.banking.rules import RuleSuggestion
    assert {f.name for f in dataclass_fields(RuleSuggestion)} == {
        "rule_id", "rule_name", "category", "account_id", "narration",
        "gst_rate_bps", "is_interstate",
    }
