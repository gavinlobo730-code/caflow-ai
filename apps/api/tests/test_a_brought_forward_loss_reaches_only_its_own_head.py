"""IT-10 — a carried-forward loss now enters the computation, under its own section.

WHAT WAS WRONG
    brought_forward_losses has existed since migration 156. create_bf_loss and
    utilize_bf_loss write it, POST /api/itr/bf-losses records one, and the
    per-client computation screen SELECTS and displays them. ITRComputeRequest
    had no field for them at all, so ITREngine.compute never read one.

    A CA could record a carried-forward loss, see it listed on the screen with
    its remaining amount and its expiry year, and watch it change the computed
    tax by exactly nothing.

WHAT THIS PINS
    Not "the loss is deducted" — WHICH HEAD each section lets it reach. That is
    the whole of the difficulty, and the expensive direction is a loss relieving
    income the statute does not allow it to touch. §71(3) and §74 deny a capital
    loss any relief against salary, business or other income; the engine already
    floors each capital head at zero for that reason, and a brought-forward
    capital loss reaching salary would reopen the same hole from the other side.
"""
import pytest

from domain.income_tax.itr_engine import ITRComputeRequest, itr_engine, _assessment_year_for
from domain.income_tax.loss_set_off import (
    apply_brought_forward_losses, BroughtForwardLoss, KNOWN_LOSS_TYPES,
)
import routers.income_tax as it

L = 1_00_000_00        # one lakh, in paise
CALLER = {"firm_id": "F1", "id": "u1", "auth_user_id": "a1",
          "email": "ca@f.test", "role": "Partner"}


def _set_off(losses, **heads):
    base = dict(business_income_paise=0, house_property_income_paise=0,
                stcg_paise=0, ltcg_paise=0, ltcg_other_paise=0)
    base.update(heads)
    return apply_brought_forward_losses(losses=losses, **base)


# ─────────── the rule that costs the most to get wrong ───────────

def test_a_capital_loss_never_relieves_salary_or_business():
    """§71(3) with §74. The engine's own comment records the current-year
    version of this: a ₹5,00,000 short-term loss against a ₹20,00,000 salary
    cut the year's tax from ₹1,92,400 to ₹88,400, relief the section expressly
    denies. A brought-forward loss must not reopen it from the other side."""
    for kind in ("capital_short_term", "capital_long_term"):
        r = _set_off([BroughtForwardLoss(kind, 5 * L)], business_income_paise=20 * L)
        assert r.business_income_paise == 20 * L, kind
        assert r.total_set_off_paise == 0, kind

    res = itr_engine.compute(ITRComputeRequest(
        fy="2025-26", gross_salary_paise=20 * L,
        brought_forward_losses=[{"loss_type": "capital_short_term", "amount_paise": 5 * L}]))
    assert res.brought_forward_set_off_paise == 0
    assert res.gross_total_income_paise == 20 * L - 75_000_00      # std deduction only


def test_a_business_loss_reaches_business_income_and_not_salary():
    """§72 allows it against the profits and gains of business or profession
    and nothing else — and §71(2A) bars even the current year's against salary."""
    r = _set_off([BroughtForwardLoss("business", 4 * L)], business_income_paise=10 * L)
    assert r.business_income_paise == 6 * L
    assert r.lines[0].section == "§72"

    salary_only = itr_engine.compute(ITRComputeRequest(
        fy="2025-26", gross_salary_paise=20 * L,
        brought_forward_losses=[{"loss_type": "business", "amount_paise": 4 * L}]))
    assert salary_only.brought_forward_set_off_paise == 0


def test_a_house_property_loss_reaches_only_that_head():
    r = _set_off([BroughtForwardLoss("house_property", 3 * L)],
                 house_property_income_paise=5 * L, business_income_paise=9 * L)
    assert r.house_property_income_paise == 2 * L
    assert r.business_income_paise == 9 * L
    assert r.lines[0].section == "§71B"


# ─────────────────── §74's two limbs are different ───────────────────

def test_a_long_term_loss_cannot_touch_a_short_term_gain():
    """§74(1)(b) — long-term losses against LONG-TERM gains only."""
    r = _set_off([BroughtForwardLoss("capital_long_term", 4 * L)], stcg_paise=10 * L)
    assert r.stcg_paise == 10 * L
    assert r.total_set_off_paise == 0
    assert r.lines[0].section == "§74(1)(b)"


def test_a_short_term_loss_may_reach_either_kind_of_gain():
    """§74(1)(a) — against capital gains, short or long."""
    short = _set_off([BroughtForwardLoss("capital_short_term", 4 * L)], stcg_paise=10 * L)
    assert short.stcg_paise == 6 * L

    long_only = _set_off([BroughtForwardLoss("capital_short_term", 4 * L)], ltcg_paise=10 * L)
    assert long_only.ltcg_paise == 6 * L
    assert long_only.lines[0].section == "§74(1)(a)"


def test_the_long_term_loss_is_taken_first_so_it_is_not_stranded():
    """A long-term loss has ONE home; a short-term one has two. Taking the
    short-term loss first eats the long-term gain and strands the long-term
    loss for another year — the same relief, deferred, for no reason."""
    r = _set_off(
        [BroughtForwardLoss("capital_short_term", 5 * L),
         BroughtForwardLoss("capital_long_term", 5 * L)],
        stcg_paise=5 * L, ltcg_paise=5 * L)
    assert r.total_set_off_paise == 10 * L, "both losses should find a home"
    assert r.stcg_paise == 0 and r.ltcg_paise == 0


# ─────────────────────── refusals that are answers ───────────────────────

def test_a_speculation_loss_is_carried_forward_rather_than_misapplied():
    """§73(1) allows it only against another SPECULATION business. This engine
    holds no such head, so setting it against ordinary business income is the
    very thing the section prevents."""
    r = _set_off([BroughtForwardLoss("speculation", 4 * L)], business_income_paise=10 * L)
    assert r.business_income_paise == 10 * L
    assert r.lines[0].set_off_paise == 0
    assert r.lines[0].carried_forward_paise == 4 * L
    assert any("speculation" in w for w in r.warnings)


def test_a_loss_whose_head_is_not_identified_is_not_guessed_at():
    r = _set_off([BroughtForwardLoss("other", 4 * L)], business_income_paise=10 * L)
    assert r.total_set_off_paise == 0
    assert r.warnings


def test_an_expired_loss_is_not_available():
    flagged = _set_off([BroughtForwardLoss("business", 4 * L, is_expired=True)],
                       business_income_paise=10 * L)
    assert flagged.total_set_off_paise == 0

    by_year = _set_off(
        [BroughtForwardLoss("business", 4 * L, expiry_assessment_year="2025-26")],
        business_income_paise=10 * L, )
    assert by_year.total_set_off_paise == 4 * L, "no AY given — the flag decides"

    ran_out = apply_brought_forward_losses(
        losses=[BroughtForwardLoss("business", 4 * L, expiry_assessment_year="2025-26")],
        business_income_paise=10 * L, house_property_income_paise=0,
        stcg_paise=0, ltcg_paise=0, ltcg_other_paise=0,
        assessment_year="2026-27")
    assert ran_out.total_set_off_paise == 0
    assert "2025-26" in ran_out.lines[0].reasons[0]


def test_a_loss_with_no_acknowledgement_is_set_off_and_warned_about():
    """§139(3) with §80 allows a carry-forward only where the loss year's
    return was furnished on time. The CA knows that; the software does not.
    Refusing on absence would deny relief that is very often due."""
    r = _set_off([BroughtForwardLoss("business", 4 * L)], business_income_paise=10 * L)
    assert r.total_set_off_paise == 4 * L
    assert any("139(3)" in w for w in r.warnings)

    filed = _set_off([BroughtForwardLoss("business", 4 * L, source_itr_ack="ACK123")],
                     business_income_paise=10 * L)
    assert not filed.warnings


# ───────────────────────── never below zero ─────────────────────────

def test_a_loss_larger_than_the_head_does_not_make_it_negative():
    r = _set_off([BroughtForwardLoss("business", 20 * L)], business_income_paise=6 * L)
    assert r.business_income_paise == 0
    assert r.lines[0].set_off_paise == 6 * L
    assert r.lines[0].carried_forward_paise == 14 * L


def test_a_head_that_is_already_a_loss_is_left_alone():
    """There is no income under the head for §71B to reach, so the
    brought-forward loss stays carried forward rather than deepening a loss."""
    res = itr_engine.compute(ITRComputeRequest(
        fy="2025-26", gross_salary_paise=20 * L, use_new_regime=False,
        house_property_income_paise=-1 * L,
        brought_forward_losses=[{"loss_type": "house_property", "amount_paise": 3 * L}]))
    assert res.brought_forward_set_off_paise == 0


# ─────────────────────────── through the API ───────────────────────────

def test_the_endpoint_carries_the_losses_and_shows_the_working():
    res = it.compute_itr(it.ComputeITRRequest(
        fy="2025-26", business_income_paise=10 * L,
        brought_forward_losses=[{"loss_type": "business", "amount_paise": 4 * L}]), CALLER)
    bf = res["data"]["brought_forward"]
    assert bf["set_off_paise"] == 4 * L
    line = bf["lines"][0]
    assert line["section"] == "§72"
    assert line["against"] == ["business"]
    assert line["reasons"], "a total with no working is not checkable"


def test_the_endpoint_refuses_a_loss_type_with_no_rule():
    with pytest.raises(Exception):
        it.ComputeITRRequest(fy="2025-26", brought_forward_losses=[
            {"loss_type": "capital", "amount_paise": 1 * L}])


def test_every_stored_loss_type_has_a_rule():
    """The vocabulary comes from brought_forward_losses_loss_type_check. A type
    added to the CHECK without a rule here must fail loudly, not fall through
    to being silently ignored."""
    assert KNOWN_LOSS_TYPES == {"business", "speculation", "capital_short_term",
                                "capital_long_term", "house_property", "other"}
    for kind in KNOWN_LOSS_TYPES:
        r = _set_off([BroughtForwardLoss(kind, 1 * L)],
                     business_income_paise=5 * L, house_property_income_paise=5 * L,
                     stcg_paise=5 * L, ltcg_paise=5 * L)
        assert r.lines and r.lines[0].reasons, f"{kind} produced no reasoning"


def test_the_assessment_year_is_the_one_after_the_financial_year():
    assert _assessment_year_for("2025-26") == "2026-27"
    assert _assessment_year_for("") is None
