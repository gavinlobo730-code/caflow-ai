"""The money and statutory kernels hold for any input, not for the inputs somebody thought to type (engineering-23).

WHAT WAS MISSING
    Every arithmetic rule in this repository that CLAUDE.md calls load-bearing is pinned by examples: the parity
    vectors in shared/*.json, the worked cases in each module's own tests. An example proves the rule for the case
    its author could imagine. The rules that fail in production are the ones nobody imagined: a residue of one
    paisa that lands on the wrong line when an odd amount is split four ways, a CGST that is a paisa short of its
    SGST at a 0.25% rate, a split whose parts add to one paisa more than the whole only when two remainders tie.
    `grep -rl hypothesis` over the tests and the requirements returned nothing.

    This module states each rule as a PROPERTY and lets Hypothesis look for the counterexample. The inputs are
    generated, the settings are derandomized (tests/_property.py), and a failure prints the smallest input that
    breaks the rule, which is the whole value of the exercise: "a split loses a paisa" is useless to a person,
    "split 1 paisa over weights [1, 1]" is a bug report.

THE KERNELS, AND THE RULE EACH ONE IS HELD TO
    A. A SPLIT ADDS BACK TO ITS WHOLE: the five largest-remainder splitters in the tree (landed cost, the document
       discount, the report apportionment, stock ageing, the FIFO layer re-base) sum EXACTLY to the amount, are integers, are never more
       than a paisa from the exact share, give nothing to a nil weight, never give a heavier weight less than a
       lighter one, and where the amount equals the weights' total return the weights themselves.
    B. A DISCOUNTED INVOICE KEEPS ITS PAISA: gross = discounts + taxable, per line and over the invoice, whatever
       the percentages, and no line's taxable value goes negative.
    C. GST FOOTS: CGST + SGST is the floor of the exact tax and equals the IGST an identical inter-State supply
       would attract, SGST carries the odd paisa, and a bank charge's taxable value plus its tax is the gross the
       bank debited, to the paisa, at every rate the product allows.
    D. TDS: the bill that crosses a threshold carries the year's tax and every later bill credits it, so a payee's
       withholding over any run of bills equals the tax on the aggregate (CLAUDE.md, "A TDS threshold is a
       TRIGGER"). A challan deposit conserves: what is deposited plus what is short is what was deducted.
       NB: there is no largest-remainder split in TDS. `challan_mapping` was one and was replaced by FIFO, which is
       why its property is conservation and not apportionment.
    E. DOUBLE ENTRY: an unbalanced line set can never reach the database (the posting kernel refuses it before it
       touches `db`), a balanced one is stored with every line and exactly its totals, and the line builders of
       the banking module balance for every amount, rate and direction.
    F. INTEGER PAISE NEVER CROSSES A FLOAT: the kernels that are pure integer arithmetic stay exact and stay `int`
       far past 2^53 (about 9.0e15), where a float cannot hold every integer, and the statutory rupee boundary
       is exact over the range it can promise.

    The last section, NEGATIVE CONTROLS, is what makes the rest worth having. A property that cannot fail proves
    nothing, so each family is run against a deliberately broken copy (a split whose last share is one paisa too
    large, a charge whose tax is computed independently of its taxable value, a line tax that halves the rate
    instead of the tax, a TDS caller that forgets what was already withheld) and must be falsified, with a small
    counterexample. The real functions are not edited: the mutants wrap them.

WHAT THIS DOES NOT PROVE
    Hypothesis searches; it does not enumerate. A property that holds over 300 derandomized examples per run is
    evidence, and a counterexample is a certainty, so a failure here is a defect and a pass is not a proof. The
    amounts are bounded (tests/_property.py: PAISE_MAX is ₹10,000 crore) wherever a kernel divides in Decimal.
"""
from __future__ import annotations

import ast
import math
from itertools import pairwise
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from tests._property import HUGE_PAISE_MAX, PAISE_MAX, PROFILE, kernel, paise, rate_bps, weights
from hypothesis import assume, find, given
from hypothesis import strategies as st
from hypothesis.errors import NoSuchExample

from domain.banking import charge_gst, posting_map
from domain.gst import discount as gst_discount
from domain.gst import money as gst_money
from domain.inventory import costing, landed_cost
from domain.money_text import rupees_paise
from domain.reporting import model as report_model
from domain.reporting import stock_ageing
from domain.sales import line_tax
from domain.tds import challan_mapping
from domain.tds.section_rates import parent_of, tds_rates_for
from domain.tds.tds_computer import TDSComputer
from services.phase2_journal_service import Phase2JournalService
from tests.e2e_harness import FakeDB

TESTS = Path(__file__).resolve().parent


# ═══ A. A split adds back to its whole ═══════════════════════════════════════════════════════════════════════════

def check_apportionment(shares, amount, ws):
    """The rules every largest-remainder split in the tree promises. Raises AssertionError naming the one broken."""
    total = sum(ws)
    assert len(shares) == len(ws), f"{len(shares)} shares for {len(ws)} weights"
    assert all(type(s) is int for s in shares), f"a share is not an int: {shares!r}"
    assert all(s >= 0 for s in shares), f"a negative share: {shares!r}"
    assert sum(shares) == amount, f"{shares!r} sums to {sum(shares)}, not {amount}"
    for share, w in zip(shares, ws, strict=True):
        exact = Fraction(amount) * Fraction(w) / Fraction(total)
        assert abs(Fraction(share) - exact) < 1, f"{share} is a paisa or more from the exact share {float(exact)}"
        if w == 0:
            assert share == 0, f"a nil weight was given {share}"
    for i, wi in enumerate(ws):
        for j, wj in enumerate(ws):
            if wi > wj:
                assert shares[i] >= shares[j], f"weight {wi} got {shares[i]} but weight {wj} got {shares[j]}"


def _rebase_as_a_split(amount, ws):
    """`costing.rebase` re-costs FIFO layers so they are worth exactly the carrying value. Layers weighted by their
    quantity ARE a split of that value, and its docstring promises largest remainder ('the parts sum to the whole
    EXACTLY'), so it is held to the same rules as the other four. The layers start worth nothing: only their
    quantities (the weights) and the target (the amount) go in."""
    layers = [costing.Layer(quantity=Decimal(w), value_paise=0) for w in ws]
    return [layer.value_paise for layer in costing.rebase(layers, amount)]


#: name -> (callable(amount, weights) -> shares, whether `amount` may not exceed the weights' total).
#: Every call goes through the MODULE, at call time, so a negative control can swap the function underneath.
SPLITTERS = {
    "landed_cost.split_pro_rata": (lambda a, ws: landed_cost.split_pro_rata(a, ws), False),
    "reporting.model.apportion": (lambda a, ws: report_model.apportion(a, ws), False),
    "stock_ageing._split_pro_rata": (
        lambda a, ws: stock_ageing._split_pro_rata(a, [Decimal(w) for w in ws]), False),
    "gst.discount.allocate": (lambda a, ws: gst_discount.allocate(a, ws), True),
    "costing.rebase": (_rebase_as_a_split, False),
}


@st.composite
def a_split(draw, capped: bool):
    """An amount and the weights to split it over. `capped` keeps the amount within the weights' total, which a
    discount may not exceed (it would be a negative value of supply)."""
    ws = draw(weights())
    amount = draw(paise(1, sum(ws) if capped else PAISE_MAX))
    return amount, ws


@pytest.mark.parametrize("name", sorted(SPLITTERS))
@kernel()
@given(data=st.data())
def test_a_split_sums_exactly_to_its_whole_and_is_fair(name, data):
    split, capped = SPLITTERS[name]
    amount, ws = data.draw(a_split(capped))
    check_apportionment(split(amount, ws), amount, ws)


@pytest.mark.parametrize("name", sorted(SPLITTERS))
@kernel()
@given(data=st.data(), k=st.integers(min_value=2, max_value=1000))
def test_a_split_depends_only_on_the_ratio_of_the_weights(name, data, k):
    """Weights in paise and weights in rupees are the same weights. Scaling them cannot change a figure."""
    split, capped = SPLITTERS[name]
    amount, ws = data.draw(a_split(capped))
    assert split(amount, [w * k for w in ws]) == split(amount, ws)


@pytest.mark.parametrize("name", sorted(SPLITTERS))
@kernel()
@given(ws=weights())
def test_a_split_of_exactly_the_weights_total_returns_the_weights(name, ws):
    """landed_cost.split_pro_rata's own stated contract: with nothing to round the answer IS the weights, which is
    what lets the receipt journal use it for the ordinary case with no branch."""
    split, _ = SPLITTERS[name]
    assert split(sum(ws), ws) == ws


@st.composite
def quantities(draw):
    """Line quantities, NUMERIC(10,3), at least one of them above nil (built, not filtered: see weights())."""
    rest = draw(st.lists(st.decimals(min_value=0, max_value=Decimal(10 ** 6), places=3), max_size=9))
    one = draw(st.decimals(min_value=Decimal("0.001"), max_value=Decimal(10 ** 6), places=3))
    at = draw(st.integers(min_value=0, max_value=len(rest)))
    return [*rest[:at], one, *rest[at:]]


@kernel()
@given(amount=paise(1), qtys=quantities())
def test_landed_cost_split_over_decimal_quantities_is_exact_too(amount, qtys):
    """The by-quantity basis weighs a line by its quantity, a NUMERIC(10,3) decimal, not by whole paise."""
    check_apportionment(landed_cost.split_pro_rata(amount, qtys), amount, qtys)


@pytest.mark.parametrize("name", sorted(SPLITTERS))
@kernel()
@given(amount=paise(-PAISE_MAX, 0), ws=weights())
def test_a_split_of_zero_or_a_negative_amount_is_all_zeros_except_stock_ageing_which_keeps_its_sign(name, amount, ws):
    """Zero and negative amounts: three splitters answer all zeros. Only stock ageing carries a sign, because an
    oversold item's carrying amount can be negative, and there the shares must still add to the whole."""
    split, capped = SPLITTERS[name]
    if capped:
        amount = max(amount, 0)           # a discount is never negative; discount.allocate refuses one
    if name == "costing.rebase":
        amount = max(amount, 0)           # the carrying value of units ON HAND; its own comment: "values are >= 0"
    shares = split(amount, ws)
    if name == "stock_ageing._split_pro_rata" and amount < 0:
        assert sum(shares) == amount and all(s <= 0 for s in shares)
    else:
        assert shares == [0] * len(ws)


@kernel()
@given(lines=st.lists(st.tuples(paise(0, 10 ** 8),
                                st.decimals(min_value=0, max_value=Decimal(10 ** 4), places=3)),
                      min_size=1, max_size=8),
       charge=paise(1, 10 ** 9), by_quantity=st.booleans())
def test_a_landed_cost_over_the_goods_lines_is_wholly_apportioned_or_wholly_reported(lines, charge, by_quantity):
    """AS-2 paragraph 6: a freight bill is in the cost of the goods or it is named as not placed. Never half."""
    goods = [landed_cost.Line(f"l{i}", f"i{i}", cost, qty) for i, (cost, qty) in enumerate(lines)]
    basis = landed_cost.BY_QUANTITY if by_quantity else landed_cost.BY_VALUE
    result = landed_cost.apportion(goods, charge, basis=basis)
    assert result.total_paise + result.unapportioned_paise == charge
    assert sum(result.by_line.values()) == result.total_paise
    assert all(type(v) is int and v > 0 for v in result.by_line.values())
    if result.unapportioned_paise:
        assert result.gaps, "an amount that could not be placed was not named"


@kernel()
@given(lines=st.lists(st.tuples(paise(1, 10 ** 8), st.decimals(min_value=1, max_value=Decimal(1000), places=3)),
                      min_size=1, max_size=6),
       charges=st.lists(paise(1, 10 ** 8), min_size=1, max_size=4))
def test_several_charges_over_the_same_goods_add_up_to_what_was_charged(lines, charges):
    goods = [landed_cost.Line(f"l{i}", f"i{i}", cost, qty) for i, (cost, qty) in enumerate(lines)]
    many = landed_cost.apportion_many(goods, [(f"c{i}", c) for i, c in enumerate(charges)],
                                      basis=landed_cost.BY_VALUE)
    assert many.total_paise == sum(charges) and many.unapportioned_paise == 0
    assert sum(many.by_line.values()) == sum(charges)


# ═══ B. A discounted invoice keeps its paise ═════════════════════════════════════════════════════════════════════

@st.composite
def a_discounted_invoice(draw):
    """Lines carrying a percentage or a flat discount (never both beyond what the gross allows) and an optional
    document-level discount, every figure valid so the property is about the arithmetic and not the refusals."""
    lines = []
    for _ in range(draw(st.integers(min_value=1, max_value=8))):
        gross = draw(paise(0, 10 ** 10))
        kind = draw(st.sampled_from(["none", "percent", "flat"]))
        line = {"gross_paise": gross}
        if kind == "percent":
            line["discount_percent_bps"] = draw(st.integers(min_value=0, max_value=10_000))
        elif kind == "flat":
            line["discount_paise"] = draw(paise(0, gross))
        lines.append(line)
    nets = [l["gross_paise"] - gst_discount.discount_for(l["gross_paise"], l.get("discount_percent_bps"),
                                                         l.get("discount_paise")) for l in lines]
    doc = draw(st.sampled_from(["none", "percent", "flat"]))
    doc_pct = draw(st.integers(min_value=0, max_value=10_000)) if doc == "percent" else None
    doc_amt = draw(paise(0, sum(nets))) if doc == "flat" else None
    return lines, nets, doc_pct, doc_amt


@kernel()
@given(inv=a_discounted_invoice())
def test_every_paisa_of_gross_is_either_discount_or_taxable(inv):
    lines, nets, doc_pct, doc_amt = inv
    out = gst_discount.apply_to_lines(lines, document_percent_bps=doc_pct, document_amount_paise=doc_amt)
    assert len(out) == len(lines)
    for line, res in zip(lines, out, strict=True):
        assert type(res["taxable_paise"]) is int and type(res["discount_paise"]) is int
        assert 0 <= res["taxable_paise"] <= line["gross_paise"], "a line's taxable value left its own range"
        assert res["discount_paise"] + res["taxable_paise"] == line["gross_paise"], "a paisa was lost or made"
    if doc_pct is not None:
        doc_total = math.floor(Fraction(sum(nets) * doc_pct, 10_000))
    else:
        doc_total = doc_amt or 0
    assert sum(r["taxable_paise"] for r in out) == sum(nets) - doc_total, \
        "the document discount was not taken off exactly once"


@kernel()
@given(inv=a_discounted_invoice())
def test_a_hundred_percent_document_discount_leaves_nothing_to_tax(inv):
    lines, _, _, _ = inv
    out = gst_discount.apply_to_lines(lines, document_percent_bps=10_000)
    assert all(r["taxable_paise"] == 0 for r in out)


# ═══ C. GST foots ════════════════════════════════════════════════════════════════════════════════════════════════

def check_line_gst(taxable, rate):
    exact = Fraction(taxable * rate, 10_000)
    full = math.floor(exact)
    intra = line_tax.compute_line_gst(taxable, rate, False)
    inter = line_tax.compute_line_gst(taxable, rate, True)
    assert all(type(x) is int for x in (*intra, *inter)), f"a head is not an int: {intra!r} {inter!r}"
    cgst, sgst, igst = intra
    assert igst == 0 and cgst + sgst == full, f"CGST {cgst} + SGST {sgst} is not the floor {full} of the exact tax"
    assert 0 <= sgst - cgst <= 1, "the odd paisa is not SGST's, or the halves differ by more than one"
    assert inter == (0, 0, full), f"the inter-State supply is not IGST of the same {full}: {inter!r}"
    assert exact - 1 < full <= exact, "the tax is more than the exact tax, or short by a paisa or more"


@kernel()
@given(taxable=paise(), rate=rate_bps)
def test_a_lines_tax_is_the_floor_of_the_exact_tax_and_both_halves_agree_with_igst(taxable, rate):
    check_line_gst(taxable, rate)


@kernel()
@given(taxable=paise(0, HUGE_PAISE_MAX), rate=rate_bps)
def test_a_lines_tax_stays_exact_and_integer_past_two_to_the_fifty_third(taxable, rate):
    """F. A float cannot hold every integer above 2^53, so an implementation that crossed one would break here
    and nowhere in the range a person would type."""
    check_line_gst(taxable, rate)


@st.composite
def an_invoice_of_quantities_and_rates(draw):
    return draw(st.lists(
        st.tuples(st.decimals(min_value=0, max_value=Decimal(10 ** 6), places=3),   # quantity, NUMERIC(10,3)
                  paise(0, 10 ** 9),                                                # rate per unit, paise
                  rate_bps),
        min_size=1, max_size=8))


@kernel()
@given(lines=an_invoice_of_quantities_and_rates(), interstate=st.booleans(),
       doc_pct=st.one_of(st.none(), st.integers(min_value=0, max_value=10_000)))
def test_an_invoice_foots_for_any_quantity_rate_and_discount(lines, interstate, doc_pct):
    """quantity x rate -> discount -> tax per line, exactly as routers/sales_invoices.create_invoice calls them."""
    gross = [int(Decimal(str(q)) * r) for q, r, _ in lines]
    resolved = gst_discount.apply_to_lines([{"gross_paise": g} for g in gross], document_percent_bps=doc_pct)
    heads = [line_tax.compute_line_gst(res["taxable_paise"], bps, interstate)
             for res, (_, _, bps) in zip(resolved, lines, strict=True)]
    taxable = sum(res["taxable_paise"] for res in resolved)
    discount = sum(res["discount_paise"] for res in resolved)
    tax = sum(sum(h) for h in heads)
    assert taxable + discount == sum(gross), "gross is not discount plus taxable over the invoice"
    # The invoice total is what the customer is asked for, and it is the sum of its lines' totals.
    assert taxable + tax == sum(res["taxable_paise"] + sum(h) for res, h in zip(resolved, heads, strict=True))
    # The same invoice made inter-State declares exactly the tax the intra-State one split between CGST and SGST.
    intra = [line_tax.compute_line_gst(res["taxable_paise"], bps, False)
             for res, (_, _, bps) in zip(resolved, lines, strict=True)]
    inter = [line_tax.compute_line_gst(res["taxable_paise"], bps, True)
             for res, (_, _, bps) in zip(resolved, lines, strict=True)]
    assert sum(c + s for c, s, _ in intra) == sum(i for _, _, i in inter)
    # Flooring per line loses less than a paisa per line and never over-declares.
    exact = sum(Fraction(res["taxable_paise"] * bps, 10_000) for res, (_, _, bps) in zip(resolved, lines, strict=True))
    assert exact - len(lines) < tax <= exact


@kernel()
@given(gross=paise(1), rate=st.sampled_from(charge_gst.ALLOWED_RATES_BPS), interstate=st.booleans())
def test_a_tax_inclusive_charge_reassembles_to_the_gross_the_bank_debited(gross, rate, interstate):
    split = charge_gst.split_inclusive_charge(gross, rate, interstate)
    assert split.taxable_paise + split.cgst_paise + split.sgst_paise + split.igst_paise == gross
    assert split.tax_paise == gross - split.taxable_paise
    assert split.taxable_paise == math.floor(Fraction(gross * 10_000, 10_000 + rate))
    assert 0 <= split.taxable_paise <= gross
    assert all(type(x) is int for x in (split.taxable_paise, split.cgst_paise, split.sgst_paise, split.igst_paise))
    if interstate:
        assert split.cgst_paise == split.sgst_paise == 0
    else:
        assert split.igst_paise == 0 and 0 <= split.sgst_paise - split.cgst_paise <= 1
    # Backing the tax out and charging it forward again must land on the gross within a paisa of rounding.
    assert abs(split.tax_paise - Fraction(gross * rate, 10_000 + rate)) <= 1


@kernel()
@given(gross=paise(1, HUGE_PAISE_MAX), rate=st.sampled_from(charge_gst.ALLOWED_RATES_BPS), interstate=st.booleans())
def test_a_tax_inclusive_charge_stays_exact_past_two_to_the_fifty_third(gross, rate, interstate):
    split = charge_gst.split_inclusive_charge(gross, rate, interstate)
    assert split.taxable_paise + split.tax_paise == gross
    assert split.taxable_paise == math.floor(Fraction(gross * 10_000, 10_000 + rate))


# ═══ D. TDS ══════════════════════════════════════════════════════════════════════════════════════════════════════

_FY = "2025-26"
#: Sections whose threshold has an aggregate limb and charges the whole aggregate: the ones the telescoping rule is
#: about. Derived from the registry, so a section added next year is covered without an edit here.
_AGGREGATE_SECTIONS = sorted(
    key for key, rule in tds_rates_for(_FY).sections.items()
    if rule.aggregate_threshold_paise is not None and not rule.charge_on_excess_only
    and rule.single_threshold_paise >= 1)


def withhold_in_sequence(section, bills, *, is_company, has_pan, credit_prior_tds=True):
    """What each bill withholds when a payee is billed `bills` in order, the way the purchase-bill path calls the
    engine: the running taxable and the running tax already withheld, both."""
    engine = TDSComputer()
    prior_taxable = prior_tds = 0
    out, rate_bps_used = [], 0
    for bill in bills:
        res = engine.resolve_tds(section, bill, fy_prior_taxable_paise=prior_taxable,
                                 fy_prior_tds_paise=prior_tds if credit_prior_tds else 0,
                                 is_company=is_company, fy=_FY, has_pan=has_pan)
        out.append(res.tds_paise)
        rate_bps_used = res.rate_bps
        prior_taxable += bill
        prior_tds += res.tds_paise
    return out, rate_bps_used


@st.composite
def bills_that_cross_the_aggregate(draw):
    """A payee billed in amounts none of which reaches the single-payment limit, until the year's total passes the
    aggregate one. Only the aggregate limb can trigger, which is the case the telescoping rule is about (a bill that
    is itself over the single limit is taxable on its own and is a different, correct, answer)."""
    section = draw(st.sampled_from(_AGGREGATE_SECTIONS))
    rule = tds_rates_for(_FY).sections[section]
    single, aggregate = rule.single_threshold_paise, rule.aggregate_threshold_paise
    bills, total = [], 0
    for _ in range(80):
        bill = draw(st.one_of(st.integers(min_value=1, max_value=single),
                              st.integers(min_value=max(1, single // 2), max_value=single)))
        bills.append(bill)
        total += bill
        if total > aggregate:
            break
    assume(total > aggregate)
    for _ in range(draw(st.integers(min_value=0, max_value=3))):
        bills.append(draw(st.integers(min_value=1, max_value=single)))
    return section, bills


def check_withholding_telescopes(section, bills, is_company, has_pan, credit_prior_tds=True):
    withheld, rate = withhold_in_sequence(section, bills, is_company=is_company, has_pan=has_pan,
                                          credit_prior_tds=credit_prior_tds)
    aggregate_tax = sum(bills) * rate // 10_000
    assert all(t >= 0 for t in withheld)
    assert sum(withheld) == aggregate_tax, (
        f"{section}: withheld {sum(withheld)} over {len(bills)} bills but the aggregate {sum(bills)} at "
        f"{rate} bps is {aggregate_tax}")
    one_shot = TDSComputer().resolve_tds(section, sum(bills), is_company=is_company, fy=_FY, has_pan=has_pan)
    assert sum(withheld) == one_shot.tds_paise


def test_the_registry_has_aggregate_sections_to_check():
    """Vacuity guard: the property below draws its section from the registry, and a registry that no longer
    qualified any would make it pass over nothing."""
    assert len(_AGGREGATE_SECTIONS) >= 3, _AGGREGATE_SECTIONS


@kernel()
@given(case=bills_that_cross_the_aggregate(), is_company=st.booleans(), has_pan=st.booleans())
def test_a_payees_withholding_over_a_year_of_bills_equals_the_tax_on_the_aggregate(case, is_company, has_pan):
    section, bills = case
    check_withholding_telescopes(section, bills, is_company, has_pan)


_SECTION_KEYS = ["194C", "194J", "194J(A)", "194J(B)", "194I", "194H"]


@st.composite
def deductions_and_challans(draw):
    start = date(2025, 4, 1)
    deductions = [{"id": f"d{i}", "section": draw(st.sampled_from(_SECTION_KEYS)),
                   "on_date": (start + timedelta(days=draw(st.integers(0, 80)))).isoformat(),
                   "doc_no": f"B{i}", "tds_paise": draw(paise(0, 10 ** 9))}
                  for i in range(draw(st.integers(min_value=0, max_value=10)))]
    challans = [{"id": f"c{i}", "section": draw(st.sampled_from(_SECTION_KEYS)),
                 "payment_date": (start + timedelta(days=draw(st.integers(0, 80)))).isoformat(),
                 "challan_no": f"{i:05d}", "tds_paise": draw(paise(0, 10 ** 9))}
                for i in range(draw(st.integers(min_value=0, max_value=6)))]
    return deductions, challans


@kernel()
@given(case=deductions_and_challans())
def test_a_challan_deposit_conserves_what_was_deducted(case):
    """What is deposited plus what is short is what was deducted, and what is deposited plus what is left over is
    what the challans carry: per parent section, in whatever order the rows come, with no paisa created."""
    deductions, challans = case
    mapping = challan_mapping.assign(deductions, challans)
    for parent in {parent_of(r["section"]) for r in (*deductions, *challans)}:
        mine = [d for d in deductions if parent_of(d["section"]) == parent]
        owed = sum(d["tds_paise"] for d in mine)
        carried = sum(c["tds_paise"] for c in challans if parent_of(c["section"]) == parent)
        deposited = [mapping.for_deduction(d["id"]).deposited_paise for d in mine]
        assert sum(deposited) == min(owed, carried)
        assert all(0 <= got <= d["tds_paise"] for got, d in zip(deposited, mine, strict=True))
        shortfall = sum(g["shortfall_paise"] for g in mapping.gaps
                        if g["code"] == challan_mapping.GAP_DEDUCTIONS_NOT_DEPOSITED and g["section"] == parent)
        surplus = sum(g["surplus_paise"] for g in mapping.gaps
                      if g["code"] == challan_mapping.GAP_CHALLAN_EXCEEDS_DEDUCTIONS and g["section"] == parent)
        assert shortfall == max(0, owed - carried) and surplus == max(0, carried - owed)
        # FIFO: once a deduction is only partly covered, every later one in the section gets nothing.
        ordered = sorted(mine, key=lambda d: (d["on_date"], d["doc_no"], d["id"]))
        gone_short = False
        for d in ordered:
            got = mapping.for_deduction(d["id"]).deposited_paise
            if gone_short:
                assert got == 0, "a later deduction was covered while an earlier one was left short"
            if got < d["tds_paise"]:
                gone_short = True


# ═══ E. Double entry ═════════════════════════════════════════════════════════════════════════════════════════════

class _NoDatabase:
    """A `db` that fails the test the moment anything touches it."""

    def __getattr__(self, name):
        raise AssertionError(f"the posting kernel reached the database ({name}) before refusing")


def _post(db, lines, entry_date="2025-06-01"):
    return Phase2JournalService()._create_journal(
        db, firm_id="F", client_id="C", entry_date=entry_date, reference_no="PROP-1", narration="n",
        entry_type="Journal", lines=lines)


@st.composite
def a_line_set(draw):
    """Debit lines and credit lines, each line one-sided, each amount positive; NOT necessarily balanced."""
    debits = draw(st.lists(paise(1, 10 ** 10), min_size=0, max_size=6))
    credits = draw(st.lists(paise(1, 10 ** 10), min_size=0, max_size=6))
    return ([{"account_id": f"dr{i}", "debit_paise": d, "credit_paise": 0} for i, d in enumerate(debits)]
            + [{"account_id": f"cr{i}", "debit_paise": 0, "credit_paise": c} for i, c in enumerate(credits)])


@kernel()
@given(lines=a_line_set())
def test_an_unbalanced_line_set_is_refused_before_it_can_touch_the_database(lines):
    debit = sum(l["debit_paise"] for l in lines)
    credit = sum(l["credit_paise"] for l in lines)
    if debit != credit:
        with pytest.raises(ValueError, match="imbalance"):
            _post(_NoDatabase(), lines)
    elif debit == 0:
        with pytest.raises(ValueError, match="zero-value"):
            _post(_NoDatabase(), lines)
    else:
        # Balanced and non-zero passes the first two gates and is stopped by the third, an unreadable date,
        # still before any database access: so the balance check is not what refused it.
        with pytest.raises(ValueError, match="not a posting date"):
            _post(_NoDatabase(), lines, entry_date="not-a-date")


@st.composite
def a_balanced_line_set(draw):
    debits = draw(st.lists(paise(1, 10 ** 10), min_size=1, max_size=6))
    total = sum(debits)
    # The credits are the debits' total cut at up to five points, so the set balances by construction.
    cuts = sorted(draw(st.lists(st.integers(min_value=1, max_value=max(1, total - 1)), unique=True, max_size=5)))
    edges = [0, *[c for c in cuts if c < total], total]
    credits = [b - a for a, b in pairwise(edges)]
    return ([{"account_id": f"dr{i}", "debit_paise": d, "credit_paise": 0} for i, d in enumerate(debits)]
            + [{"account_id": f"cr{i}", "debit_paise": 0, "credit_paise": c} for i, c in enumerate(credits)])


@kernel()
@given(lines=a_balanced_line_set())
def test_a_balanced_line_set_is_stored_whole_with_debits_equal_to_credits(lines):
    db = FakeDB()
    entry_id = _post(db, lines)
    stored = [r for r in db.rows("journal_lines") if r["journal_entry_id"] == entry_id]
    debit = sum(r["debit_paise"] for r in stored)
    credit = sum(r["credit_paise"] for r in stored)
    assert debit == credit == sum(l["debit_paise"] for l in lines)
    assert sorted((r["account_id"], r["debit_paise"], r["credit_paise"]) for r in stored) == \
        sorted((l["account_id"], l["debit_paise"], l["credit_paise"]) for l in lines), "a line was lost or altered"


def check_lines_balance(lines, gross):
    debit = sum(l["debit_paise"] for l in lines)
    credit = sum(l["credit_paise"] for l in lines)
    assert all(type(l["debit_paise"]) is int and type(l["credit_paise"]) is int for l in lines)
    assert debit == credit == gross, f"debit {debit} credit {credit} for a gross of {gross}"
    assert all(l["debit_paise"] == 0 or l["credit_paise"] == 0 for l in lines), "a line is on both sides"


@kernel()
@given(amount=paise(1), is_credit=st.booleans())
def test_the_bank_posting_builders_balance_for_every_amount_and_direction(amount, is_credit):
    check_lines_balance(posting_map.build_lines(amount, is_credit, "bank", "counter"), amount)
    check_lines_balance(posting_map.build_transfer_lines(amount, is_credit, "bank", "other"), amount)


@kernel()
@given(gross=paise(1), rate=st.sampled_from(charge_gst.ALLOWED_RATES_BPS), interstate=st.booleans(),
       is_credit=st.booleans())
def test_a_tax_inclusive_bank_entry_balances_at_every_rate_in_both_directions(gross, rate, interstate, is_credit):
    split = charge_gst.split_inclusive_charge(gross, rate, interstate)
    lines = charge_gst.build_inclusive_lines(
        split, bank_account_id="bank", counter_account_id="counter", is_credit=is_credit,
        cgst_account_id="cgst", sgst_account_id="sgst", igst_account_id="igst")
    check_lines_balance(lines, gross)


# ═══ F. Integer paise never crosses a float ══════════════════════════════════════════════════════════════════════

@kernel()
@given(p=paise(0, HUGE_PAISE_MAX))
def test_gstr3b_whole_rupees_round_half_up_exactly_at_any_magnitude(p):
    """CGST Act §170: nearest rupee, half up. Integer arithmetic, so past 2^53 it must not drift."""
    got = gst_money.paise_to_rupees_whole(p)
    assert type(got) is int
    assert got == math.floor(Fraction(p, 100) + Fraction(1, 2))


@kernel()
@given(p=paise(0, 10 ** 15))
def test_gstr1_rupees_are_exact_over_the_range_the_float_can_promise(p):
    """The statutory boundary is a float (`round(paise / 100, 2)`). It is exact while the paise figure has at most
    15 significant digits, so up to ₹10 trillion; above about ₹100 trillion it is not (measured: with 10^16 paise
    a fifth of all values fail), which no practice's books reach. The bound is part of the test on purpose: raise it
    and this fails, which is the information."""
    assert Decimal(str(gst_money.paise_to_rupees_2dp(p))) * 100 == p


@kernel()
@given(p=paise(-HUGE_PAISE_MAX, HUGE_PAISE_MAX))
def test_rupees_text_reads_back_to_the_same_paise_whatever_the_sign_or_size(p):
    """`f"{p // 100}.{p % 100:02d}"` prints -1 paise as -1.99 (floor division). This one must not, and must group
    the Indian way."""
    text = rupees_paise(p)
    assert Decimal(text.replace(",", "")) * 100 == p, f"{p} printed as {text}"
    whole = text.lstrip("-").split(".")[0]
    groups = whole.split(",")
    assert all(len(g) == 2 for g in groups[1:-1]) and (len(groups) == 1 or len(groups[-1]) == 3)


# ═══ Negative controls: the properties above must be able to FAIL ════════════════════════════════════════════════
#
# Each mutant is a wrapper around the real function with ONE paisa of error, or one realistic mistake, introduced.
# `find` returns the smallest input a condition holds for and raises NoSuchExample when there is none, so the real
# function is shown to have no counterexample and the mutant is shown to have a SMALL one.

def _counterexample(strategy, fails):
    return find(strategy, fails, settings=kernel(max_examples=500))


def _violates(check, *args):
    try:
        check(*args)
    except AssertionError:
        return True
    return False


def _one_paisa_too_many(fn):
    def mutant(*args, **kwargs):
        out = list(fn(*args, **kwargs))
        if out and sum(out) > 0:
            out[-1] += 1
        return out
    return mutant


def _drops_the_residue(fn):
    """The classic: floor every share and forget to hand the remainder out."""
    def mutant(amount, ws):
        total = sum(ws)
        return [int(Fraction(amount) * Fraction(w) / Fraction(total)) for w in ws] if total > 0 and amount > 0 \
            else fn(amount, ws)
    return mutant


_SPLIT_TARGETS = {
    "landed_cost.split_pro_rata": (landed_cost, "split_pro_rata"),
    "reporting.model.apportion": (report_model, "apportion"),
    "stock_ageing._split_pro_rata": (stock_ageing, "_split_pro_rata"),
    "gst.discount.allocate": (gst_discount, "allocate"),
}


#: `costing.rebase` takes (layers, value), not (amount, weights), so the two generic mutants cannot wrap it as they
#: stand. It has its own mutants below, and this says so: a splitter nobody wrote a control for would pass vacuously.
_SPLITTERS_WITH_THEIR_OWN_CONTROL = {"costing.rebase"}


def test_every_splitter_has_a_negative_control():
    assert set(SPLITTERS) == set(_SPLIT_TARGETS) | _SPLITTERS_WITH_THEIR_OWN_CONTROL


@pytest.mark.parametrize("name", sorted(_SPLIT_TARGETS))
@pytest.mark.parametrize("mutation", [_one_paisa_too_many, _drops_the_residue], ids=["one-paisa-over", "no-residue"])
def test_a_split_with_a_paisa_wrong_fails_the_property_with_a_small_counterexample(monkeypatch, name, mutation):
    split, capped = SPLITTERS[name]
    strategy = a_split(capped)
    module, attribute = _SPLIT_TARGETS[name]
    monkeypatch.setattr(module, attribute, mutation(getattr(module, attribute)))
    amount, ws = _counterexample(strategy, lambda case: _violates(
        lambda: check_apportionment(split(case[0], case[1]), case[0], case[1])))
    # Whatever the minimal input is, it is a person-sized one: a handful of paise over at most three weights.
    assert amount <= 100 and len(ws) <= 3 and max(ws) <= 100, (amount, ws)


def _rebase_one_paisa_too_many(real):
    def mutant(layers, to_value_paise):
        out = list(real(layers, to_value_paise))
        if out and sum(layer.value_paise for layer in out) > 0:
            last = out[-1]
            out[-1] = costing.Layer(quantity=last.quantity, value_paise=last.value_paise + 1)
        return tuple(out)
    return mutant


def _rebase_drops_the_residue(real):
    def mutant(layers, to_value_paise):
        layers = tuple(layers)
        total = sum((layer.quantity for layer in layers), Decimal(0))
        if total <= 0 or to_value_paise <= 0:
            return real(layers, to_value_paise)
        return tuple(costing.Layer(quantity=layer.quantity,
                                   value_paise=int(Fraction(to_value_paise) * Fraction(layer.quantity) / Fraction(total)))
                     for layer in layers)
    return mutant


@pytest.mark.parametrize("mutation", [_rebase_one_paisa_too_many, _rebase_drops_the_residue],
                         ids=["one-paisa-over", "no-residue"])
def test_a_rebase_with_a_paisa_wrong_fails_the_property_with_a_small_counterexample(monkeypatch, mutation):
    """The same control the four other splitters get, written against `rebase`'s own (layers, value) signature."""
    monkeypatch.setattr(costing, "rebase", mutation(costing.rebase))
    amount, ws = _counterexample(a_split(False), lambda case: _violates(
        lambda: check_apportionment(_rebase_as_a_split(case[0], case[1]), case[0], case[1])))
    assert amount <= 100 and len(ws) <= 3 and max(ws) <= 100, (amount, ws)


def test_a_charge_whose_tax_is_computed_apart_from_its_taxable_value_fails_with_a_small_counterexample(monkeypatch):
    """charge_gst's own docstring: computing both independently leaves a one-paisa hole about half the time."""
    real = charge_gst.split_inclusive_charge

    def independent(gross, rate, interstate=False):
        base = real(gross, rate, interstate)
        tax = math.floor(Fraction(gross * rate, 10_000 + rate) + Fraction(1, 2))      # rounded, not the remainder
        return charge_gst.ChargeSplit(gross, base.taxable_paise, 0, 0, tax, rate, True) if interstate else \
            charge_gst.ChargeSplit(gross, base.taxable_paise, tax // 2, tax - tax // 2, 0, rate, False)

    def reassembles(gross, rate, interstate):
        s = charge_gst.split_inclusive_charge(gross, rate, interstate)
        return s.taxable_paise + s.cgst_paise + s.sgst_paise + s.igst_paise == gross

    case = st.tuples(paise(1), st.sampled_from(charge_gst.ALLOWED_RATES_BPS), st.booleans())
    with pytest.raises(NoSuchExample):
        _counterexample(case, lambda c: not reassembles(*c))
    monkeypatch.setattr(charge_gst, "split_inclusive_charge", independent)
    gross, rate, _ = _counterexample(case, lambda c: not reassembles(*c))
    assert gross <= 100 and rate in charge_gst.ALLOWED_RATES_BPS, (gross, rate)


def test_a_line_tax_that_halves_the_rate_instead_of_the_tax_fails_with_a_small_counterexample(monkeypatch):
    """compute_line_gst's docstring: splitting the rate and flooring each half loses a paisa whenever the full tax
    is odd, so CGST + SGST falls short of the IGST of an identical inter-State supply."""
    real = line_tax.compute_line_gst

    def halves_the_rate(taxable, rate, interstate):
        if interstate:
            return real(taxable, rate, True)
        half = taxable * (rate // 2) // 10_000
        return half, half, 0

    case = st.tuples(paise(), rate_bps)
    with pytest.raises(NoSuchExample):
        _counterexample(case, lambda c: _violates(check_line_gst, *c))
    monkeypatch.setattr(line_tax, "compute_line_gst", halves_the_rate)
    taxable, rate = _counterexample(case, lambda c: _violates(check_line_gst, *c))
    assert taxable <= 10_000 and rate <= 4000, (taxable, rate)


def test_a_tds_caller_that_forgets_what_was_already_withheld_fails_with_a_small_counterexample():
    """The defect CLAUDE.md records: a caller that passes the running taxable but not the tax already withheld
    charges the growing aggregate again on every later bill."""
    case = st.tuples(bills_that_cross_the_aggregate(), st.booleans(), st.booleans())

    def broken(c, credit):
        (section, bills), is_company, has_pan = c
        return _violates(check_withholding_telescopes, section, bills, is_company, has_pan, credit)

    with pytest.raises(NoSuchExample):
        _counterexample(case, lambda c: broken(c, True))
    (section, bills), _, _ = _counterexample(case, lambda c: broken(c, False))
    rule = tds_rates_for(_FY).sections[section]
    fewest_to_cross = rule.aggregate_threshold_paise // rule.single_threshold_paise + 1
    # The least that can show the defect is the bills that cross the aggregate and one after; the generator may add
    # up to three more, so a shrunk example is within a handful of bills of that floor.
    assert len(bills) <= fewest_to_cross + 4, (section, bills)


def test_a_bank_builder_that_is_a_paisa_out_fails_with_a_small_counterexample(monkeypatch):
    real = posting_map.build_lines

    def a_paisa_out(amount, is_credit, bank, counter):
        lines = real(amount, is_credit, bank, counter)
        lines[-1] = {**lines[-1], "credit_paise": lines[-1]["credit_paise"] + (0 if is_credit else 1),
                     "debit_paise": lines[-1]["debit_paise"] + (1 if is_credit else 0)}
        return lines

    case = st.tuples(paise(1), st.booleans())
    with pytest.raises(NoSuchExample):
        _counterexample(case, lambda c: _violates(
            lambda: check_lines_balance(posting_map.build_lines(c[0], c[1], "b", "c"), c[0])))
    monkeypatch.setattr(posting_map, "build_lines", a_paisa_out)
    amount, _ = _counterexample(case, lambda c: _violates(
        lambda: check_lines_balance(posting_map.build_lines(c[0], c[1], "b", "c"), c[0])))
    assert amount <= 10, amount


def test_a_float_in_the_line_tax_is_found_by_the_large_magnitude_generator_and_not_by_a_realistic_one(monkeypatch):
    """F. The reason the magnitude tests exist: a version that went through a float is exact over every amount a
    person would type (here, up to ₹1 crore) and wrong once the product of amount and rate outgrows 2^53, so only a
    generator that goes there can catch it."""
    def through_a_float(taxable, rate, interstate):
        full = int(float(taxable) * rate / 10_000)
        if interstate:
            return 0, 0, full
        return full // 2, full - full // 2, 0

    realistic_ceiling = PAISE_MAX // 1000
    monkeypatch.setattr(line_tax, "compute_line_gst", through_a_float)
    with pytest.raises(NoSuchExample):                  # a human-sized test of the float version passes
        _counterexample(st.tuples(paise(0, realistic_ceiling), rate_bps), lambda c: _violates(check_line_gst, *c))
    taxable, rate = _counterexample(st.tuples(paise(0, HUGE_PAISE_MAX), rate_bps),
                                    lambda c: _violates(check_line_gst, *c))
    assert taxable > realistic_ceiling and taxable * rate > 2 ** 53, (taxable, rate)


# ═══ The settings are the rule, not each test's spelling of it ═══════════════════════════════════════════════════

def test_the_profile_is_deterministic_has_no_replay_database_and_a_deadline_that_will_not_flake():
    assert PROFILE.derandomize is True, "a property test that draws fresh entropy is a flaky test"
    assert PROFILE.database is None, "no example database, so no replay of another machine's failures"
    assert PROFILE.deadline is not None and PROFILE.deadline >= timedelta(seconds=1), \
        "the default 200 ms deadline has failed healthy code on loaded runners"
    assert PROFILE.max_examples >= 100


def _imports_hypothesis(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "hypothesis":
            return True
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "hypothesis" for a in node.names):
            return True
    return False


def _modules_using_hypothesis():
    for path in sorted(TESTS.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if "hypothesis" not in text:          # cheap prefilter: parsing 1,100 files costs seconds
            continue
        tree = ast.parse(text)
        if _imports_hypothesis(tree):
            yield path, tree


def _decorator_names(fn):
    names = set()
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        names.add(target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", ""))
    return names


def test_every_generated_test_in_the_tree_carries_the_shared_settings():
    """THE RULE, NOT A LIST OF MODULES. A `@given` with Hypothesis's default settings draws fresh entropy and has a
    200 ms deadline: a test that passes today and fails one run in fifty. Every test that generates inputs, in any
    module that imports hypothesis, takes `@kernel(...)` or `@settings(...)` too."""
    found, bare = 0, []
    for path, tree in _modules_using_hypothesis():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "given" in _decorator_names(node):
                found += 1
                if not _decorator_names(node) & {"kernel", "settings"}:
                    bare.append(f"{path.name}::{node.name}")
    assert found >= 20, f"only {found} generated tests found: the scan stopped seeing them"
    assert not bare, f"generated tests with default settings (use @kernel()): {bare}"
