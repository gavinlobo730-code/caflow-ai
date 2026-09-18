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

def test_what_a_rule_may_propose_is_exactly_this():
    """A trusted rule posts with no click, so widening the PAYLOAD widens what
    happens with nobody watching.

    UPDATED DELIBERATELY ON 17-09-2026 for BANK-11 step 3, which the owner
    decided as option (a): a rule may tag the PARTY, and a TDS treatment stays
    out. The party is safe for a reason that has to hold for anything added
    here — it LABELS the transaction and is not a journal leg, so nothing in
    `posting_map.build_lines`, the settlement or the reversal reads it and no
    figure moves. The test below asserts that property rather than trusting
    this sentence.

    A general SPLIT LEG is still refused, and checking the decision's own
    premise is why: its worked example — "₹11,800 = ₹10,000 rent + ₹1,800 GST"
    — was ALREADY BUILT as `suggested_gst_rate_bps` and has posted unattended
    for months. What it does NOT settle is the shape of a split a rule could
    express in general: a rule cannot know a future amount, so fixed amounts
    fire only on identical totals and PERCENTAGES are the only form that
    generalises. That is a different feature from the one the decision
    describes, so it stays out and stays named."""
    from dataclasses import fields as dataclass_fields
    from domain.banking.rules import RuleSuggestion
    assert {f.name for f in dataclass_fields(RuleSuggestion)} == {
        "rule_id", "rule_name", "category", "account_id", "narration",
        "gst_rate_bps", "is_interstate", "payee_type", "payee_id",
    }


def test_a_tds_treatment_and_a_split_leg_are_still_refused():
    """The two halves of step 3 that were NOT taken. Asserted by NAME because
    each would go straight into the unattended path: a withholding decides a
    statutory liability under s.201 and belongs in front of a human however
    trusted the rule, and a split leg has no settled shape."""
    from dataclasses import fields as dataclass_fields
    from domain.banking.rules import RuleSuggestion
    names = {f.name for f in dataclass_fields(RuleSuggestion)}
    for forbidden in ("tds_section", "tds_rate_bps", "tds_applicable",
                      "splits", "split_legs", "split_percentages"):
        assert forbidden not in names, (
            f"{forbidden} would let a trusted rule decide it unattended")


def test_the_party_is_a_label_and_never_a_journal_leg():
    """The property that makes the party safe, asserted on the CODE rather than
    on the docstring: the posting map, the settlement builder and
    `coded_by_a_human` must not read it. If one ever does, the party stops
    being a label and this whole decision needs re-taking."""
    import pathlib as _p
    api = _p.Path(__file__).resolve().parents[1]
    for rel in ("domain/banking/posting_map.py",):
        src = (api / rel).read_text()
        assert "payee_type" not in src and "payee_id" not in src, rel
    entry = (api / "domain/banking/entry.py").read_text()
    body = entry[entry.index("def coded_by_a_human"):]
    body = body[:body.index("\n\n")]
    assert "payee" not in body, (
        "coded_by_a_human must not count a party — a tagged line with no ledger "
        "is still a line the CA has to code")


def test_the_party_kinds_match_both_migrations():
    """404's CHECK, 257's CHECK and the engine's tuple are three statements of
    one list. Read the files rather than restate them — `_validate_match_field`
    records the same reasoning for the match fields."""
    import pathlib as _p
    from domain.banking.rules import PAYEE_TYPES, PAYEE_TYPES_WITH_AN_ID
    mig = _p.Path(__file__).resolve().parents[1] / "migrations"
    for name in ("404_a_trusted_rule_may_tag_the_party.sql",
                 "257_bank_transaction_payee.sql"):
        sql = (mig / name).read_text()
        for t in PAYEE_TYPES:
            assert f"'{t}'" in sql, f"{t} missing from {name}"
    assert set(PAYEE_TYPES_WITH_AN_ID) < set(PAYEE_TYPES)
    assert "other" not in PAYEE_TYPES_WITH_AN_ID, (
        "'other' names a party this product does not hold, so there is nothing "
        "for an id to point into")


def test_a_rule_that_names_only_a_party_proposes_nothing():
    """`is_empty` deliberately does not count the party, for gst_rate_bps'
    reason turned around: such a rule would win precedence over a later one
    that actually codes the line, and the CA would get a tagged transaction
    still sitting in the queue."""
    from domain.banking.rules import RuleSuggestion
    tag_only = RuleSuggestion(rule_id="r", rule_name="n", category=None,
                              account_id=None, narration=None,
                              payee_type="vendor", payee_id="v1")
    assert tag_only.is_empty()
    codes_and_tags = RuleSuggestion(rule_id="r", rule_name="n", category=None,
                                    account_id="a1", narration=None,
                                    payee_type="vendor", payee_id="v1")
    assert not codes_and_tags.is_empty()


def test_the_party_travels_on_the_draft_and_the_columns_agree():
    """A proposal is stored on the row like every other one, so the ordinary
    Pass applies it and the screen can show it before anybody clicks."""
    from domain.banking.entry import Draft, EMPTY_DRAFT_COLUMNS, from_rule
    from domain.banking.rules import RuleSuggestion
    d = Draft(source="rule", grade="ready", label="x", reason="y",
              payee_type="vendor", payee_id="v1")
    cols = d.as_columns()
    assert cols["draft_payee_type"] == "vendor" and cols["draft_payee_id"] == "v1"
    # EMPTY_DRAFT_COLUMNS is what CLEARS a draft. A key in one and not the
    # other leaves a stale proposal behind after a redraft.
    assert set(cols) == set(EMPTY_DRAFT_COLUMNS)
    carried = from_rule(RuleSuggestion(rule_id="r", rule_name="n", category=None,
                                       account_id="a1", narration=None,
                                       payee_type="customer", payee_id="c1"), "Sales")
    assert carried is not None
    assert carried.payee_type == "customer" and carried.payee_id == "c1"


def test_a_failed_pass_puts_the_party_back():
    """The rollback snapshot's own comment is the argument: "a pass that then
    fails would leave the machine's coding on the row looking like the CA's
    answer — and the next reader would trust it."

    That applies word for word to a party tag. Being a LABEL rather than a
    posting is what makes a trusted rule safe to APPLY it; it is not a reason
    to leave a wrong one behind. Asserted on `_CODING_COLS` and on the restore
    body, because the snapshot and the restore are two lists that have to
    agree — a column in one and not the other is a silent half-rollback."""
    import ast
    import pathlib as _p
    from services.bank_entry_service import _CODING_COLS

    party = ("payee_name", "payee_type", "payee_id")
    for col in party:
        assert col in _CODING_COLS, f"{col} is not snapshotted before a pass"

    src = (_p.Path(__file__).resolve().parents[1]
           / "services/bank_entry_service.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_unapply")
    restored = {k.value for n in ast.walk(fn) if isinstance(n, ast.Dict)
                for k in n.keys if isinstance(k, ast.Constant)}
    for col in party:
        assert col in restored, f"_unapply does not restore {col}"
    # And every OTHER snapshotted column is restored too — the property, not
    # just the three this test is about.
    for col in _CODING_COLS:
        assert col in restored, f"{col} is snapshotted and never put back"


def test_the_party_is_applied_through_the_human_door():
    """`bank_payee_service.set_payee` carries the firm-and-client check on a
    polymorphic `payee_id` — migration 257 records that it is the only thing
    between a typo and a bank line pointing at another client's customer. A
    second write path would be a second place to forget it, so the rule's tag
    delegates rather than updating the row."""
    import ast
    import pathlib as _p
    src = (_p.Path(__file__).resolve().parents[1]
           / "services/bank_payee_service.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "apply_rule_party")
    called = {n.func.attr for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "set_payee" in called
    assert "update" not in called, "apply_rule_party must not write the row itself"
