"""Section 234C(1)'s proviso for income nobody could have foreseen (IT-21).

WHAT WAS WRONG

    `advance_tax_interest_engine` computed the 12/36/75/100 triggers and the
    fixed 3/3/3/1-month periods and documented a KNOWN SIMPLIFICATION: the
    proviso that excuses the shortfall caused by capital gains, winnings or
    dividends arising AFTER an instalment fell due was not applied "because the
    input is not split by date of receipt". So a client with a ₹10 lakh sale in
    March was charged §234C interest on instalments that were not yet due on
    that income — interest they do not owe, on the strength of a sale that had
    not happened.

THE FIXTURE, WORKED BY HAND (FY 2025-26)

    Tax due on the returned income: ₹4,00,000, of which ₹1,00,000 is the tax on
    a ₹10 lakh long-term gain realised on 10 March. The regular tax is
    therefore ₹3,00,000, and the instalments are measured against that until
    the gain arose.

    Nothing paid until ₹1,00,000 on 12 March (the gain's own tax, in the
    instalment that remained):

        no proviso    15 Jun  ₹60,000 short  x 3%  =  1,800
                      15 Sep  ₹1,80,000      x 3%  =  5,400
                      15 Dec  ₹3,00,000      x 3%  =  9,000
                      15 Mar  ₹3,00,000      x 1%  =  3,000    = 19,200
        with proviso  15 Jun  ₹45,000        x 3%  =  1,350
                      15 Sep  ₹1,35,000      x 3%  =  4,050
                      15 Dec  ₹2,25,000      x 3%  =  6,750
                      15 Mar  ₹3,00,000      x 1%  =  3,000    = 15,150

    The three earlier instalments each measure ₹1,00,000 less tax — "no 234C on
    earlier instalments for that amount" — and the shortfall on the REST of the
    tax is still charged, which is what "still charges it on the rest" means.

WHAT IT REFUSES TO ASSUME

    The relief is conditional on the income's OWN tax being paid in the
    instalments that remain, or by 31 March where none does. A gain realised on
    20 March whose tax is paid on 5 April is not excused from the 15 March
    instalment, and that is the half of the proviso a "leave it out until it
    arises" gets wrong.

WHICH CLIENTS' FIGURES CHANGE

    None unless the caller sends the new `unforeseen` input. The default is the
    empty list and is exactly the engine's behaviour before the proviso was
    applied; every existing test of the engine passes unchanged.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routers.income_tax as it
from domain.income_tax import advance_tax_interest_engine as eng
from domain.income_tax.advance_tax_interest_engine import (
    InstallmentPayment, UnforeseenIncome, compute_234c_interest,
)

FY = "2025-26"


def rs(rupees: int) -> int:
    return rupees * 100


T = 4_00_000_00           # tax due on the returned income
U = 1_00_000_00           # the tax on the March gain, inside it


def _gain(arose=date(2026, 3, 10), tax=U, kind="capital_gain"):
    return UnforeseenIncome(kind=kind, arose_on=arose, tax_paise=tax,
                            description="Equity shares, ₹10 lakh LTCG")


def _pay(amount, on):
    return InstallmentPayment(installment_number=1, paid_amount_paise=amount, paid_date=on)


def _interest(result):
    return [i.interest_paise for i in result.installments]


# ── the default is the engine as it was ──────────────────────────────────────

def test_sending_nothing_is_exactly_what_the_engine_always_did():
    plain = compute_234c_interest(FY, T, [])
    explicit = compute_234c_interest(FY, T, [], unforeseen=[])
    assert _interest(plain) == _interest(explicit)
    # The figures, worked by hand: 15% x 4L x 3%, 45% x 4L x 3%, 75% x 4L x 3%,
    # 100% x 4L x 1%.
    assert _interest(plain) == [rs(1_800), rs(5_400), rs(9_000), rs(4_000)]
    assert plain.unforeseen_lines == () and plain.caveats == ()
    assert [i.unforeseen_excluded_paise for i in plain.installments] == [0, 0, 0, 0]
    assert [i.base_paise for i in plain.installments] == [T] * 4


# ── the finding's own fixture ────────────────────────────────────────────────

def test_a_march_gain_whose_tax_is_paid_in_march_is_excused_from_the_earlier_instalments():
    pays = [_pay(U, date(2026, 3, 12))]
    without = compute_234c_interest(FY, T, pays)
    with_it = compute_234c_interest(FY, T, pays, unforeseen=[_gain()])
    assert _interest(without) == [rs(1_800), rs(5_400), rs(9_000), rs(3_000)]
    assert _interest(with_it) == [rs(1_350), rs(4_050), rs(6_750), rs(3_000)]
    assert sum(_interest(with_it)) == rs(15_150)
    assert sum(_interest(without)) == rs(19_200)
    # The three earlier instalments each exclude the gain's tax; the fourth
    # (15 March, ON or AFTER the 10th) does not.
    assert [i.unforeseen_excluded_paise for i in with_it.installments] == [U, U, U, 0]
    assert [i.base_paise for i in with_it.installments] == [3_00_000_00] * 3 + [T]


def test_the_shortfall_on_the_rest_of_the_tax_is_still_charged():
    """"No 234C on earlier instalments for that amount AND still charges it on
    the rest": the interest with the proviso is not nil, and it is exactly the
    interest on the regular tax alone."""
    pays = [_pay(U, date(2026, 3, 12))]
    with_it = compute_234c_interest(FY, T, pays, unforeseen=[_gain()])
    regular_only = compute_234c_interest(FY, 3_00_000_00, [])
    assert sum(_interest(with_it)[:3]) == sum(_interest(regular_only)[:3]) > 0


def test_a_gain_after_the_last_instalment_is_excused_from_all_four_if_paid_by_31_march():
    """Realised on 20 March: no instalment remains, so 31 March is the date. The
    assessee paid the regular tax on time and the gain's ₹1,00,000 on 28 March."""
    regular = [_pay(45_000_00, date(2025, 6, 15)),
               _pay(90_000_00, date(2025, 9, 15)),      # cumulative 1.35L
               _pay(90_000_00, date(2025, 12, 15)),     # cumulative 2.25L
               _pay(75_000_00, date(2026, 3, 15))]      # cumulative 3.00L
    pays = regular + [_pay(U, date(2026, 3, 28))]
    gain = _gain(arose=date(2026, 3, 20))
    without = compute_234c_interest(FY, T, pays)
    with_it = compute_234c_interest(FY, T, pays, unforeseen=[gain])
    assert sum(_interest(without)) == rs(450 + 1_350 + 2_250 + 1_000)   # 5,050
    assert sum(_interest(with_it)) == 0
    assert [i.unforeseen_excluded_paise for i in with_it.installments] == [U] * 4
    (line,) = with_it.unforeseen_lines
    assert line.relief is True and line.settle_by == date(2026, 3, 31)


def test_the_same_gain_paid_on_5_april_is_not_excused():
    """THE HALF OF THE PROVISO THAT IS EASY TO MISS. The condition is on the
    income's own tax, and 5 April is outside the financial year."""
    regular = [_pay(45_000_00, date(2025, 6, 15)), _pay(90_000_00, date(2025, 9, 15)),
               _pay(90_000_00, date(2025, 12, 15)), _pay(75_000_00, date(2026, 3, 15))]
    pays = regular + [_pay(U, date(2026, 4, 5))]
    gain = _gain(arose=date(2026, 3, 20))
    without = compute_234c_interest(FY, T, pays)
    with_it = compute_234c_interest(FY, T, pays, unforeseen=[gain])
    assert _interest(with_it) == _interest(without), "no relief where the condition fails"
    (line,) = with_it.unforeseen_lines
    assert line.relief is False
    assert "31 March" in line.reason
    assert [i.unforeseen_excluded_paise for i in with_it.installments] == [0] * 4


def test_a_gain_not_paid_for_at_all_gets_no_relief():
    gain = _gain()
    with_it = compute_234c_interest(FY, T, [], unforeseen=[gain])
    assert _interest(with_it) == _interest(compute_234c_interest(FY, T, []))
    assert with_it.unforeseen_lines[0].relief is False


# ── the rules inside the rule ────────────────────────────────────────────────

def test_a_payment_made_before_the_income_arose_does_not_count_as_paying_for_it():
    """It cannot have been paid 'in the remaining instalments' if it was paid
    before they remained. An assessee who prepaid in February gets no relief for
    a March sale from it — and the CA who knows the prepayment was for the gain
    enters the tax as paid after it arose."""
    pays = [_pay(U, date(2026, 2, 20))]
    with_it = compute_234c_interest(FY, T, pays, unforeseen=[_gain()])
    assert with_it.unforeseen_lines[0].relief is False


def test_a_payment_is_never_counted_against_two_incomes():
    """Two gains of ₹60,000 tax each, 10 and 12 March; only ₹1,00,000 paid
    between them. The earlier takes its ₹60,000 and is excused; the later is
    left with ₹40,000 and is not."""
    first = _gain(arose=date(2026, 3, 10), tax=60_000_00)
    second = _gain(arose=date(2026, 3, 12), tax=60_000_00)
    pays = [_pay(1_00_000_00, date(2026, 3, 14))]
    out = compute_234c_interest(FY, T, pays, unforeseen=[second, first])  # order given is irrelevant
    by_date = {ln.arose_on: ln for ln in out.unforeseen_lines}
    assert by_date[date(2026, 3, 10)].relief is True
    assert by_date[date(2026, 3, 12)].relief is False
    assert by_date[date(2026, 3, 12)].paid_toward_paise == 40_000_00
    # Only the excused one is left out, and only from the instalments before its date.
    assert [i.unforeseen_excluded_paise for i in out.installments] == [60_000_00] * 3 + [0]


def test_income_arising_on_the_due_date_itself_was_not_after_it():
    """'After' is strict. A gain on 15 September is not excused from the
    15 September instalment — only from 15 June."""
    gain = _gain(arose=date(2025, 9, 15))
    pays = [_pay(U, date(2025, 10, 1))]
    out = compute_234c_interest(FY, T, pays, unforeseen=[gain])
    assert out.unforeseen_lines[0].relief is True
    assert [i.unforeseen_excluded_paise for i in out.installments] == [U, 0, 0, 0]


def test_income_that_arose_before_the_first_instalment_changes_nothing_and_says_so():
    gain = _gain(arose=date(2025, 6, 10))
    out = compute_234c_interest(FY, T, [_pay(U, date(2025, 6, 12))], unforeseen=[gain])
    (line,) = out.unforeseen_lines
    assert line.relief is False
    assert "foreseeable at every instalment" in line.reason
    assert _interest(out) == _interest(compute_234c_interest(FY, T, [_pay(U, date(2025, 6, 12))]))


def test_a_presumptive_assessee_has_one_instalment_and_the_same_rule():
    """§211(1)'s proviso: the whole tax by 15 March. A gain realised on
    20 March is after that single date and is excused if its tax is paid by the
    31st."""
    gain = _gain(arose=date(2026, 3, 20))
    pays = [_pay(3_00_000_00, date(2026, 3, 15)), _pay(U, date(2026, 3, 30))]
    out = compute_234c_interest(FY, T, pays, is_presumptive_44ad_44ada=True, unforeseen=[gain])
    assert [i.installment_number for i in out.installments] == [4]
    assert out.installments[0].unforeseen_excluded_paise == U
    assert out.total_interest_paise == 0


def test_the_excluded_tax_is_capped_at_the_estimate_and_says_so():
    big = _gain(tax=T + 50_000_00)
    pays = [_pay(T + 50_000_00, date(2026, 3, 12))]
    out = compute_234c_interest(FY, T, pays, unforeseen=[big])
    assert all(i.base_paise >= 0 for i in out.installments)
    assert out.installments[0].unforeseen_excluded_paise == T
    assert any("exceeds the estimated tax" in c for c in out.caveats)


# ── what it refuses ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad,match", [
    (UnforeseenIncome("casual_income", date(2026, 3, 10), 1), "not an income"),
    (UnforeseenIncome("capital_gain", date(2024, 12, 1), 1), "is not income of FY 2025-26"),
    (UnforeseenIncome("capital_gain", date(2026, 4, 1), 1), "is not income of FY 2025-26"),
    (UnforeseenIncome("capital_gain", date(2026, 3, 10), -1), "not negative"),
])
def test_an_income_the_proviso_cannot_reach_is_refused_not_clamped(bad, match):
    """A misdated gain moves the whole answer, so it is raised and not nudged
    into the year."""
    with pytest.raises(ValueError, match=match):
        compute_234c_interest(FY, T, [], unforeseen=[bad])


def test_dividends_carry_their_own_caveat():
    div = UnforeseenIncome("dividend", date(2026, 3, 10), U, "Dividend")
    out = compute_234c_interest(FY, T, [_pay(U, date(2026, 3, 12))], unforeseen=[div])
    assert any("2(22)(e)" in c for c in out.caveats)
    plain = compute_234c_interest(FY, T, [_pay(U, date(2026, 3, 12))], unforeseen=[_gain()])
    assert not any("2(22)(e)" in c for c in plain.caveats)


def test_the_proviso_is_graded_as_unconfirmed_and_says_so_on_every_answer():
    assert eng.UNFORESEEN_PROVISO_VERIFIED is False
    out = compute_234c_interest(FY, T, [_pay(U, date(2026, 3, 12))], unforeseen=[_gain()])
    assert any("[S]" in c for c in out.caveats)
    assert eng.UNFORESEEN_KINDS == ("capital_gain", "winnings", "dividend")


# ── the endpoint ─────────────────────────────────────────────────────────────

def _req(**over):
    base = dict(
        fy=FY, estimated_tax_paise=T,
        installments=[it.AdvanceTaxInstallmentInput(
            installment_number=1, paid_amount_paise=U, paid_date=date(2026, 3, 12))],
        unforeseen_income=[it.UnforeseenIncomeInput(
            kind="capital_gain", arose_on=date(2026, 3, 10), tax_paise=U,
            description="Equity shares")])
    base.update(over)
    return it.ComputeAdvanceTaxRequest(**base)


def test_the_endpoint_serves_the_working_beside_the_figure():
    out = it.compute_advance_tax_interest(_req(), current_user={"firm_id": "F"})
    data = out["data"]
    assert data["total_interest_paise"] == rs(15_150)
    assert [i["unforeseen_excluded_paise"] for i in data["installments"]] == [U, U, U, 0]
    (line,) = data["unforeseen_income"]
    assert line["relief"] is True and line["settle_by"] == "2026-03-15"
    assert data["caveats"], "the [S] caveat travels with every answer that used the proviso"


def test_the_endpoint_without_the_input_answers_exactly_as_before():
    out = it.compute_advance_tax_interest(_req(unforeseen_income=[]),
                                          current_user={"firm_id": "F"})
    assert out["data"]["total_interest_paise"] == rs(19_200)
    assert out["data"]["unforeseen_income"] == [] and out["data"]["caveats"] == []


def test_the_endpoint_refuses_an_unknown_kind_and_an_income_outside_the_year():
    with pytest.raises(ValidationError, match="kind must be one of"):
        it.UnforeseenIncomeInput(kind="gift", arose_on=date(2026, 3, 10), tax_paise=1)
    with pytest.raises(HTTPException) as e:
        it.compute_advance_tax_interest(
            _req(unforeseen_income=[it.UnforeseenIncomeInput(
                kind="winnings", arose_on=date(2027, 1, 1), tax_paise=1)]),
            current_user={"firm_id": "F"})
    assert e.value.status_code == 422 and "FY 2025-26" in e.value.detail


# ── the register's candidates ────────────────────────────────────────────────

@pytest.fixture
def register(monkeypatch):
    from tests.e2e_harness import FakeDB
    db = FakeDB()
    monkeypatch.setattr(it, "_db", lambda: db)
    monkeypatch.setattr(it, "assert_client_access", lambda u, c: None)
    base = {"firm_id": "F", "client_id": "C", "asset_type": "equity_shares",
            "improvement_cost_paise": 0, "is_listed_security": True}
    # A long-term equity gain in the year, one outside it, and a loss.
    db.seed("capital_gains", {**base, "id": "G1", "asset_description": "Infosys",
                              "purchase_date": "2021-01-10", "sale_date": "2026-03-10",
                              "purchase_cost_paise": 2_00_000_00, "sale_value_paise": 12_00_000_00})
    db.seed("capital_gains", {**base, "id": "G2", "asset_description": "Old sale",
                              "purchase_date": "2019-01-10", "sale_date": "2025-02-10",
                              "purchase_cost_paise": 2_00_000_00, "sale_value_paise": 12_00_000_00})
    db.seed("capital_gains", {**base, "id": "G3", "asset_description": "A loss",
                              "purchase_date": "2021-01-10", "sale_date": "2025-11-10",
                              "purchase_cost_paise": 12_00_000_00, "sale_value_paise": 2_00_000_00})
    return db


def test_the_register_offers_only_this_years_gains_with_tax_on_them(register):
    out = it.advance_tax_unforeseen_income(
        client_id="C", fy=FY, current_user={"firm_id": "F"})["data"]
    assert [c["register_id"] for c in out["candidates"]] == ["G1"]
    c = out["candidates"][0]
    assert c["arose_on"] == "2026-03-10" and c["kind"] == "capital_gain"
    assert c["tax_paise"] > 0 and c["is_estimate"] is True
    assert any("ESTIMATE" in cv for cv in out["caveats"])


def test_the_kinds_are_served_with_the_candidates_and_the_browser_fallback_matches(register):
    """The screen spells neither the three kinds nor the words for them: they
    ride on the candidates answer. The browser keeps a fallback for the
    redeploy window, pinned HERE from the side that owns the vocabulary — a guard
    in apps/web would assert the browser against a copy of itself."""
    import re
    from pathlib import Path

    served = it.advance_tax_unforeseen_income(
        client_id="C", fy=FY, current_user={"firm_id": "F"})["data"]["kinds"]
    assert [k["key"] for k in served] == list(eng.UNFORESEEN_KINDS)
    assert {k["key"]: k["label"] for k in served} == eng.UNFORESEEN_KIND_LABELS

    panel = (Path(__file__).resolve().parents[2] / "web" / "components" / "tax"
             / "UnforeseenIncomePanel.tsx").read_text(encoding="utf-8")
    fallback = panel.split("UNFORESEEN_KINDS_FALLBACK = [", 1)[1].split("];", 1)[0]
    assert tuple(re.findall(r'key: "([a-z_]+)"', fallback)) == eng.UNFORESEEN_KINDS


def test_a_candidate_nobody_includes_changes_no_figure(register):
    """Prepare-only: the endpoint reads; the compute endpoint is not told."""
    offered = it.advance_tax_unforeseen_income(
        client_id="C", fy=FY, current_user={"firm_id": "F"})["data"]
    assert offered["candidates"]
    out = it.compute_advance_tax_interest(_req(unforeseen_income=[]),
                                          current_user={"firm_id": "F"})
    assert out["data"]["unforeseen_income"] == []
