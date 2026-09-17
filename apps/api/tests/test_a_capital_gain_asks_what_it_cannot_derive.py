"""Two facts a capital-gains entry cannot derive (IT-28, and IT-19's second
half).

WHAT WAS WRONG

  1. `long_term_threshold_months` gave every bond twenty-four months, because
     `_EQUITY_LIKE` was the only route to the twelve-month limb. The proviso to
     s.2(42A) reaches "a security (other than a unit) listed in a recognised
     stock exchange in India", which is a listed DEBENTURE or BOND as much as a
     listed share. Probed against the previous code: a bond bought 01-01-2024
     and sold 02-06-2025 — seventeen months — came back `is_long_term=False`,
     30.0%, "Section 48", ₹1,50,000 of tax on a ₹5,00,000 gain, where s.112
     charges 12.5% and ₹62,500. The wrong classification was persisted into
     `gain_type` and `tax_rate_percent`.

  2. The engine computed gain = sale - cost and handed it to s.112A. s.55(2)(ac)
     deems the cost of a s.112A asset ACQUIRED BEFORE 01-02-2018 to be the
     higher of the actual cost and the lower of the 31-01-2018 fair market value
     and the sale value. Probed against the previous code: ₹1,00,000 of shares
     bought in 2012 and sold for ₹11,00,000 gave a ₹10,00,000 gain and ₹1,09,375
     of tax, where a 31-01-2018 value of ₹8,00,000 makes the gain ₹3,00,000 and
     the tax ₹21,875 — five times over-stated, on the commonest long-held
     holding an Indian practice sees.

WHAT IS PINNED HERE
    Both rules, both REFUSALS and the DIRECTION of each refusal, because the
    direction is the argument: an unrecorded listing takes the unlisted period
    (more tax, never less) and an unrecorded fair market value leaves the actual
    cost standing, which is limb (i)'s own floor and therefore an upper bound on
    the gain. Also that a value the section does not reach is NAMED rather than
    silently discarded, that `gaps` and `caveats` are different lists, and that
    the browser's copy of the two "when to ask" constants still says what the
    engine says.

⚠️ EVERY DATE AND PERIOD HERE IS `[S]`-GRADED. Direct egress is refused at this
    environment's proxy, incometax.gov.in included, so none of it was read
    against the bare Act. The constants are asserted EXACTLY below, so a
    correction is one edit and shows up as a deliberate change rather than a
    drift.
"""
from __future__ import annotations

import ast
import inspect
import re
from datetime import date
from pathlib import Path

import pytest

import routers.income_tax as it
import services.capital_gain_exemption_service as cgx
from domain.income_tax import capital_gains_engine as cg
from domain.income_tax.capital_gains_engine import (
    ASSESSEE_UNSPECIFIED,
    FINANCE_NO2_ACT_2024,
    SECTION_55_2_AC_ACQUIRED_BEFORE,
    SECTION_55_2_AC_FMV_DATE,
    compute_capital_gains,
    is_long_term,
    listing_gap,
    long_term_threshold_months,
    section_55_2_ac_cost,
)

_API = Path(__file__).resolve().parents[1]
_MIGRATIONS = _API / "migrations"
_WEB = Path(__file__).resolve().parents[3] / "apps" / "web"

L = 100_000 * 100

BEFORE_FORK = date(2024, 7, 22)
ON_OR_AFTER_FORK = date(2024, 7, 23)


# ══ s.2(42A) — the listed limb ═══════════════════════════════════════════════

def test_the_two_statutory_dates_are_exactly_these():
    """`[S]`, written from knowledge. Pinned exactly so a correction is
    deliberate."""
    assert SECTION_55_2_AC_FMV_DATE == date(2018, 1, 31)
    assert SECTION_55_2_AC_ACQUIRED_BEFORE == date(2018, 2, 1)
    assert FINANCE_NO2_ACT_2024 == date(2024, 7, 23)
    assert cg._LONG_TERM_MONTHS_LISTED == 12


@pytest.mark.parametrize("asset_type", ["bonds", "other"])
@pytest.mark.parametrize("sale_date", [BEFORE_FORK, ON_OR_AFTER_FORK])
def test_a_listed_security_is_twelve_months_on_both_sides_of_the_fork(asset_type, sale_date):
    """The proviso to s.2(42A) has said twelve months throughout the period
    this module covers, so the listed limb takes no date branch — unlike the
    unlisted one, which went 36 -> 24 on 23-07-2024."""
    assert long_term_threshold_months(asset_type, sale_date, True) == 12


def test_an_unlisted_security_keeps_the_dated_thresholds():
    for asset_type in ("bonds", "other"):
        assert long_term_threshold_months(asset_type, BEFORE_FORK, False) == 36
        assert long_term_threshold_months(asset_type, ON_OR_AFTER_FORK, False) == 24


def test_the_seventeen_month_listed_bond_the_probe_found():
    """The finding's own case. Against the previous code this was short-term
    at a 30% slab estimate."""
    listed = compute_capital_gains(
        "bonds", date(2024, 1, 1), date(2025, 6, 2), 10 * L, 15 * L,
        is_listed_security=True)
    assert listed.holding_months == 17
    assert listed.is_long_term is True
    assert listed.tax_rate_percent == 12.5
    assert listed.tax_liability_paise == 5 * L * 125 // 1000   # 12.5% of Rs 5,00,000

    unlisted = compute_capital_gains(
        "bonds", date(2024, 1, 1), date(2025, 6, 2), 10 * L, 15 * L,
        is_listed_security=False)
    assert unlisted.is_long_term is False
    assert unlisted.tax_rate_percent == 30.0


def test_the_boundary_is_exceeded_not_reached_for_a_listed_security_too():
    """s.2(42A) runs to the day IMMEDIATELY PRECEDING the transfer, so twelve
    months exactly is still short-term. The listed limb must take the same
    `_add_months` comparison as every other, not a month count."""
    assert is_long_term("bonds", date(2024, 1, 1), date(2025, 1, 1), True) is False
    assert is_long_term("bonds", date(2024, 1, 1), date(2025, 1, 2), True) is True


def test_a_unit_is_outside_the_twelve_month_limb_however_it_is_listed():
    """The limb reaches a security "OTHER THAN A UNIT". Honouring the flag on a
    debt-fund unit would classify a real short-term gain as long-term, which
    UNDER-taxes — the direction that costs the client s.234B interest."""
    assert "debt_mf" not in cg._LISTING_IS_ASKED
    assert long_term_threshold_months("debt_mf", ON_OR_AFTER_FORK, True) == 24
    assert is_long_term("debt_mf", date(2024, 1, 1), date(2025, 6, 2), True) is False


def test_an_asset_type_that_already_answers_the_question_is_not_asked_again():
    """Each exclusion is its own decision, and `unlisted` is the sharp one: it
    answers the question in its own NAME, so honouring a contradictory flag
    would let a caller override the asset type the row was created with."""
    for settled in ("equity", "equity_shares", "mutual_funds", "property",
                    "gold", "vda", "unlisted", "debt_mf"):
        assert settled not in cg._LISTING_IS_ASKED, settled
    assert long_term_threshold_months("unlisted", ON_OR_AFTER_FORK, True) == 24
    # Equity was already on twelve months and stays there whatever is passed.
    for flag in (True, False, None):
        assert long_term_threshold_months("equity", ON_OR_AFTER_FORK, flag) == 12


# ══ the listing REFUSAL ══════════════════════════════════════════════════════

def test_an_unrecorded_listing_takes_the_unlisted_period_and_says_so():
    r = compute_capital_gains("bonds", date(2024, 1, 1), date(2025, 6, 2), 10 * L, 15 * L)
    assert r.is_long_term is False, "unrecorded must not claim the shorter period"
    assert len(r.gaps) == 1
    gap = r.gaps[0]
    assert "not recorded" in gap
    assert "2(42A)" in gap
    assert "12" in gap and "24" in gap
    assert "over-states" in gap


def test_the_gap_is_reported_only_where_the_answer_would_move_the_classification():
    """The `hsn_digits` discipline: a sentence telling a CA to record something
    that decides nothing is how these sentences come to be ignored."""
    # Six years — long-term either way.
    assert listing_gap("bonds", date(2019, 1, 1), date(2025, 6, 2), None) is None
    # Six months — short-term either way.
    assert listing_gap("bonds", date(2025, 1, 1), date(2025, 6, 2), None) is None
    # Seventeen months — the answer decides it.
    assert listing_gap("bonds", date(2024, 1, 1), date(2025, 6, 2), None) is not None


def test_a_recorded_listing_reports_no_gap_either_way():
    for flag in (True, False):
        assert listing_gap("bonds", date(2024, 1, 1), date(2025, 6, 2), flag) is None


def test_an_asset_that_is_never_asked_never_reports_the_listing_gap():
    assert listing_gap("property", date(2024, 1, 1), date(2025, 6, 2), None) is None
    assert listing_gap("equity", date(2024, 1, 1), date(2025, 6, 2), None) is None


def test_the_zero_coupon_bond_limb_is_named_rather_than_modelled():
    """s.2(42A) also reaches a notified zero coupon bond (s.2(48)) whatever its
    listing. That is a THIRD fact nobody holds, so it is named on the gap and
    the answer stays at the longer period — over-taxing, never under."""
    gap = listing_gap("bonds", date(2024, 1, 1), date(2025, 6, 2), None)
    assert gap is not None and "zero coupon bond" in gap and "2(48)" in gap


# ══ s.55(2)(ac) — the grandfathered cost ═════════════════════════════════════

def _gf(**kw):
    base = dict(asset_type="equity_shares", purchase_date=date(2012, 6, 1),
                sale_date=date(2025, 6, 1), purchase_cost_paise=1 * L,
                sale_value_paise=11 * L, fmv_31_01_2018_paise=8 * L)
    base.update(kw)
    return section_55_2_ac_cost(**base)


def test_the_deemed_cost_is_the_higher_of_the_actual_and_the_lower_of_two():
    r = _gf()
    assert r.applied is True
    # lower of FMV 8L and consideration 11L = 8L; higher of actual 1L and 8L = 8L
    assert r.cost_paise == 8 * L
    assert r.gaps == ()


def test_limb_two_b_caps_the_substitution_at_the_consideration():
    """Without the cap a scrip that fell since 2018 would be given a deemed cost
    above what it sold for and produce a NOTIONAL LOSS the section does not
    create."""
    r = _gf(sale_value_paise=5 * L, fmv_31_01_2018_paise=8 * L)
    assert r.cost_paise == 5 * L
    full = compute_capital_gains("equity_shares", date(2012, 6, 1), date(2025, 6, 1),
                                 1 * L, 5 * L, fmv_31_01_2018_paise=8 * L)
    assert full.gain_paise == 0


def test_limb_one_preserves_a_real_loss():
    """Bought at 10L, sold at 5L, worth 6L in January 2018. The actual cost wins
    and the real Rs 5,00,000 loss survives — limb (ii) would have made it
    Rs 0."""
    r = _gf(purchase_cost_paise=10 * L, sale_value_paise=5 * L,
            fmv_31_01_2018_paise=6 * L)
    assert r.cost_paise == 10 * L
    full = compute_capital_gains("equity_shares", date(2012, 6, 1), date(2025, 6, 1),
                                 10 * L, 5 * L, fmv_31_01_2018_paise=6 * L)
    assert full.gain_paise == -5 * L


def test_a_fair_market_value_below_the_actual_cost_changes_nothing():
    r = _gf(purchase_cost_paise=9 * L, fmv_31_01_2018_paise=3 * L)
    assert r.cost_paise == 9 * L


def test_the_whole_arithmetic_is_integer_paise_with_no_rounding():
    """Every limb is a max or a min of amounts already in paise — there is no
    division here to take a direction on, which is why this module states no
    rounding rule where `_round_paise`, the ESI contribution and the GST
    discount each have to."""
    r = _gf(purchase_cost_paise=1_23_456_79, sale_value_paise=9_87_654_31,
            fmv_31_01_2018_paise=4_56_789_13)
    assert isinstance(r.cost_paise, int)
    assert r.cost_paise == 4_56_789_13
    # Asserted on the SYNTAX rather than on a sample, so a division added later
    # fails here and has to state its own direction, as every other rounding in
    # this codebase does.
    body = ast.parse(inspect.getsource(section_55_2_ac_cost))
    divisions = [n for n in ast.walk(body)
                 if isinstance(n, ast.BinOp)
                 and isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mult))]
    assert divisions == [], (
        "s.55(2)(ac) is a max of a min — arithmetic here would need a stated "
        "rounding direction")


def test_the_section_reaches_only_a_pre_february_2018_acquisition():
    assert _gf(purchase_date=date(2018, 1, 31)).applied is True
    assert _gf(purchase_date=date(2018, 2, 1)).applied is False
    assert _gf(purchase_date=date(2018, 2, 2)).applied is False


def test_the_section_reaches_only_a_long_term_s112a_asset():
    assert _gf(asset_type="property").applied is False
    assert _gf(asset_type="bonds").applied is False
    # Short-term equity: s.111A charges it on the actual cost.
    assert _gf(purchase_date=date(2025, 1, 1)).applied is False


# ══ the fair-market-value REFUSAL ════════════════════════════════════════════

def test_an_absent_fair_market_value_leaves_the_actual_cost_and_names_it():
    r = _gf(fmv_31_01_2018_paise=None)
    assert r.applied is False
    assert r.cost_paise == 1 * L
    assert len(r.gaps) == 1
    gap = r.gaps[0]
    assert "55(2)(ac)" in gap
    assert "31-01-2018" in gap
    assert "LARGEST" in gap
    assert "WHOLE holding" in gap, "a per-share figure here is a hundredfold error"


def test_the_absent_value_gives_an_upper_bound_rather_than_a_guess():
    """Limb (i) makes the actual cost a FLOOR on the deemed cost, so the gain
    reported without the substitution is the largest the section can produce.
    That is what makes refusing safe rather than merely cautious."""
    without = compute_capital_gains("equity_shares", date(2012, 6, 1), date(2025, 6, 1),
                                    1 * L, 11 * L)
    for fmv in (0, 1 * L, 5 * L, 8 * L, 20 * L):
        with_fmv = compute_capital_gains("equity_shares", date(2012, 6, 1),
                                         date(2025, 6, 1), 1 * L, 11 * L,
                                         fmv_31_01_2018_paise=fmv)
        assert with_fmv.gain_paise <= without.gain_paise


def test_a_supplied_value_the_section_cannot_use_is_named_not_discarded():
    """The `SalesInvoiceIn` lesson: a caller who fills in a field and has it
    silently dropped believes it was honoured. Each reason is its own
    sentence, because what the CA should do about it differs."""
    reasons = set()
    for kw in (dict(asset_type="property"),
               dict(purchase_date=date(2025, 1, 1)),
               dict(purchase_date=date(2020, 1, 1))):
        r = _gf(**kw)
        assert r.applied is False
        assert len(r.caveats) == 1
        assert "has NOT been used" in r.caveats[0]
        reasons.add(r.caveats[0])
    assert len(reasons) == 3, "three different situations must read differently"


def test_nothing_is_said_where_no_value_was_supplied_and_none_was_wanted():
    r = _gf(asset_type="property", fmv_31_01_2018_paise=None)
    assert r.gaps == () and r.caveats == ()


# ══ what the result carries ══════════════════════════════════════════════════

def test_the_result_reports_the_cost_the_gain_was_measured_against():
    r = compute_capital_gains("equity_shares", date(2012, 6, 1), date(2025, 6, 1),
                              1 * L, 11 * L, fmv_31_01_2018_paise=8 * L)
    assert r.cost_of_acquisition_paise == 8 * L
    assert r.grandfathered_cost_is_applied is True
    assert r.gain_paise == 11 * L - 8 * L
    assert r.tax_liability_paise == (3 * L - 125_000_00) * 125 // 1000
    assert len(r.grandfathering_working) == 2


def test_the_result_reports_the_actual_cost_where_nothing_was_substituted():
    r = compute_capital_gains("property", date(2012, 6, 1), date(2025, 6, 1),
                              1 * L, 11 * L)
    assert r.cost_of_acquisition_paise == 1 * L
    assert r.grandfathered_cost_is_applied is False


def test_improvement_cost_stays_outside_the_substituted_cost():
    """s.55(2)(ac) substitutes the cost of ACQUISITION. The cost of improvement
    is a separate limb of s.48 and is deducted on top of it."""
    r = compute_capital_gains("equity_shares", date(2012, 6, 1), date(2025, 6, 1),
                              1 * L, 11 * L, improvement_cost_paise=1 * L,
                              fmv_31_01_2018_paise=8 * L)
    assert r.cost_of_acquisition_paise == 8 * L
    assert r.gain_paise == 11 * L - 8 * L - 1 * L


def test_indexation_still_runs_on_the_actual_cost():
    """s.112A allows no indexation, so the two never meet; taking the deemed
    cost here would put a figure on a line this transfer never reads."""
    plain = compute_capital_gains("equity_shares", date(2012, 6, 1), date(2025, 6, 1),
                                  1 * L, 11 * L)
    substituted = compute_capital_gains("equity_shares", date(2012, 6, 1),
                                        date(2025, 6, 1), 1 * L, 11 * L,
                                        fmv_31_01_2018_paise=8 * L)
    assert substituted.indexed_cost_paise == plain.indexed_cost_paise


def test_gaps_and_caveats_are_different_lists_and_both_can_be_empty():
    clean = compute_capital_gains("equity_shares", date(2020, 6, 1), date(2025, 6, 1),
                                  1 * L, 11 * L)
    assert clean.gaps == () and clean.caveats == ()
    both = compute_capital_gains("bonds", date(2024, 1, 1), date(2025, 6, 2),
                                 10 * L, 15 * L, fmv_31_01_2018_paise=1 * L)
    assert len(both.gaps) == 1 and len(both.caveats) == 1
    assert both.gaps[0] != both.caveats[0]


def test_neither_new_fact_disturbs_a_transfer_that_carries_neither():
    """The regression that matters: every existing register entry passes None
    for both, so nothing already computed may move."""
    for asset_type in ("equity_shares", "mutual_funds", "property", "bonds",
                       "other", "unlisted", "gold", "vda", "debt_mf"):
        for sale in (BEFORE_FORK, ON_OR_AFTER_FORK, date(2025, 6, 1)):
            r = compute_capital_gains(asset_type, date(2019, 1, 1), sale, 1 * L, 5 * L,
                                      assessee_type=ASSESSEE_UNSPECIFIED)
            baseline = cg._compute_capital_gains(
                asset_type, date(2019, 1, 1), sale, 1 * L, 5 * L, 0,
                ASSESSEE_UNSPECIFIED)
            assert r.gain_paise == baseline.gain_paise
            assert r.is_long_term == baseline.is_long_term
            assert r.tax_liability_paise == baseline.tax_liability_paise


# ══ the register's own reader ════════════════════════════════════════════════

def test_the_exemption_service_classifies_with_the_same_listing_fact():
    """`exemption_for_entry` falls back to the classifier when the row carries
    no `gain_type`. Reading the row without `is_listed_security` would give
    that path a different answer from the one stored on every row that has
    one — and s.54EC/54F gate on `is_long_term`."""
    entry = {"sale_value_paise": 15 * L, "purchase_cost_paise": 10 * L,
             "improvement_cost_paise": 0, "asset_type": "bonds",
             "purchase_date": "2024-01-01", "sale_date": "2025-06-02",
             "is_listed_security": True}
    r = cgx.exemption_for_entry(entry, [], client_id="C1")
    assert not any("short-term" in g for g in r.gaps)
    unlisted = cgx.exemption_for_entry({**entry, "is_listed_security": False},
                                       [], client_id="C1")
    assert r.gain_paise == unlisted.gain_paise


# ══ the API boundary ═════════════════════════════════════════════════════════

CALLER = {"firm_id": "F1", "id": "u1", "role": "Partner", "email": "p@f.test"}


def test_both_facts_cross_the_compute_endpoint():
    body = it.compute_capital_gains_endpoint(
        it.ComputeCapitalGainsRequest(
            asset_type="bonds", purchase_date=date(2024, 1, 1),
            sale_date=date(2025, 6, 2), purchase_cost_paise=10 * L,
            sale_value_paise=15 * L, is_listed_security=True),
        current_user=CALLER)
    assert body["success"] is True
    assert body["data"]["gain_type"] == "LTCG"
    assert body["data"]["tax_rate_percent"] == 12.5


def test_the_response_carries_the_cost_the_working_and_both_lists():
    body = it.compute_capital_gains_endpoint(
        it.ComputeCapitalGainsRequest(
            asset_type="equity_shares", purchase_date=date(2012, 6, 1),
            sale_date=date(2025, 6, 1), purchase_cost_paise=1 * L,
            sale_value_paise=11 * L, fmv_31_01_2018_paise=8 * L),
        current_user=CALLER)
    data = body["data"]
    assert data["cost_of_acquisition_paise"] == 8 * L
    assert data["grandfathered_cost_is_applied"] is True
    assert len(data["grandfathering_working"]) == 2
    assert data["gaps"] == [] and data["caveats"] == []


def test_an_unrecorded_fact_reaches_the_screen_as_a_gap():
    body = it.compute_capital_gains_endpoint(
        it.ComputeCapitalGainsRequest(
            asset_type="bonds", purchase_date=date(2024, 1, 1),
            sale_date=date(2025, 6, 2), purchase_cost_paise=10 * L,
            sale_value_paise=15 * L),
        current_user=CALLER)
    assert len(body["data"]["gaps"]) == 1


def test_the_create_path_persists_both_facts_and_neither_is_defaulted():
    payload = it.create_capital_gains(
        it.CreateCapitalGainsRequest(
            client_id="C1", asset_description="8.5% NCD 2029",
            asset_type="bonds", purchase_date=date(2024, 1, 1),
            sale_date=date(2025, 6, 2), purchase_cost_paise=10 * L,
            sale_value_paise=15 * L, is_listed_security=True),
        current_user=CALLER)["data"]
    assert payload["is_listed_security"] is True
    assert payload["fmv_31_01_2018_paise"] is None
    assert payload["gain_type"] == "LTCG"

    omitted = it.create_capital_gains(
        it.CreateCapitalGainsRequest(
            client_id="C1", asset_description="8.5% NCD 2029",
            asset_type="bonds", purchase_date=date(2024, 1, 1),
            sale_date=date(2025, 6, 2), purchase_cost_paise=10 * L,
            sale_value_paise=15 * L),
        current_user=CALLER)["data"]
    assert omitted["is_listed_security"] is None
    assert omitted["gain_type"] == "STCG"


def test_a_negative_fair_market_value_is_refused_at_the_model():
    with pytest.raises(Exception):
        it.ComputeCapitalGainsRequest(
            asset_type="equity_shares", purchase_date=date(2012, 6, 1),
            sale_date=date(2025, 6, 1), purchase_cost_paise=1 * L,
            sale_value_paise=11 * L, fmv_31_01_2018_paise=-1)


# ══ the migration ════════════════════════════════════════════════════════════

def _migration_adding(column: str) -> tuple[Path, str]:
    """Resolve the migration BY WHAT IT DOES, not by its filename. A guard that
    names a path breaks on a rename that does not break its rule."""
    hits = [p for p in sorted(_MIGRATIONS.glob("*.sql"))
            if not p.name.endswith("_rollback.sql")
            and re.search(rf"ADD COLUMN IF NOT EXISTS\s+{column}\b",
                          p.read_text(encoding="utf-8"))]
    assert len(hits) == 1, f"expected exactly one migration adding {column}: {hits}"
    return hits[0], hits[0].read_text(encoding="utf-8")


def _statements(sql: str) -> str:
    """The migration with its `--` prose stripped: every assertion below is
    about what the STATEMENTS do, and the header deliberately discusses the
    guesses it did NOT make."""
    return "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))


@pytest.mark.parametrize("column", ["is_listed_security", "fmv_31_01_2018_paise"])
def test_the_column_is_nullable_with_no_default_and_no_backfill(column):
    """Nullable and undefaulted is the whole design — NULL is NOT RECORDED, and
    guessing is unsafe in both directions. A backfill would assert a fact about
    every row already in the register."""
    path, sql = _migration_adding(column)
    body = _statements(sql)
    line = next(l for l in body.splitlines() if f"ADD COLUMN IF NOT EXISTS {column}" in l)
    assert "NOT NULL" not in line and "DEFAULT" not in line, line
    assert not re.search(rf"UPDATE\s+public\.capital_gains[\s\S]*{column}", body), (
        f"{path.name} must not back-fill {column}")


def test_the_two_columns_are_added_by_the_same_migration():
    """They are one decision — two facts the same entry cannot derive — and
    splitting them would let one land in production without the other."""
    assert _migration_adding("is_listed_security")[0] == \
        _migration_adding("fmv_31_01_2018_paise")[0]


def test_the_fair_market_value_cannot_be_negative():
    _, sql = _migration_adding("fmv_31_01_2018_paise")
    body = _statements(sql)
    assert "fmv_31_01_2018_paise IS NULL OR fmv_31_01_2018_paise >= 0" in body


def test_no_deemed_cost_and_no_classification_is_stored():
    """The caps and the limbs move by Finance Act, so the deemed cost is
    derived on every read — migration 278's reasoning, and the same reason
    migration 385 stores no exemption amount."""
    _, sql = _migration_adding("is_listed_security")
    body = _statements(sql)
    for forbidden in ("deemed_cost", "grandfathered_cost", "holding_months"):
        assert forbidden not in body


def test_no_second_assignment_scope_policy_is_written_over_the_table():
    """`public.capital_gains` predates migration 084, so it already carries that
    migration's RESTRICTIVE policy. A table created SINCE has to declare one
    inline (385); writing a second one over this table would be a different
    bug."""
    _, sql = _migration_adding("is_listed_security")
    body = _statements(sql)
    assert "CREATE POLICY" not in body
    assert "GRANT" not in body
    assert "ENABLE ROW LEVEL SECURITY" not in body


def test_the_rollback_undoes_both_columns_and_the_check():
    path, _ = _migration_adding("is_listed_security")
    back = path.with_name(path.stem + "_rollback.sql").read_text(encoding="utf-8")
    assert "DROP COLUMN IF EXISTS is_listed_security" in back
    assert "DROP COLUMN IF EXISTS fmv_31_01_2018_paise" in back
    assert "DROP CONSTRAINT IF EXISTS capital_gains_fmv_31_01_2018_paise_check" in back


def test_both_columns_are_commented_with_what_null_means():
    _, sql = _migration_adding("is_listed_security")
    body = _statements(sql)
    for column in ("is_listed_security", "fmv_31_01_2018_paise"):
        # Up to the NEXT statement of this kind, not to the next semicolon —
        # these comments are prose and contain their own punctuation.
        comment = re.search(
            rf"COMMENT ON COLUMN public\.capital_gains\.{column} IS"
            r"([\s\S]*?)(?=COMMENT ON |\Z)", body)
        assert comment, column
        assert "NOT RECORDED" in comment.group(1), column


# ══ the browser's copy of "when to ask" ══════════════════════════════════════

_FACTS = _WEB / "lib" / "income-tax" / "capitalGainsFacts.ts"


def _ts_string_array(name: str) -> list[str]:
    src = _FACTS.read_text(encoding="utf-8")
    m = re.search(rf"export const {name}[^=]*=\s*(\[[^\]]*\])", src)
    assert m, f"{name} not found in {_FACTS}"
    return [s for s in re.findall(r'"([^"]+)"', m.group(1))]


def test_the_browser_asks_the_listing_question_of_exactly_these_asset_types():
    """Pinned from the PYTHON side deliberately — a guard in `apps/web` would
    assert the browser against a copy of itself and pass whenever both drifted
    together. The Schedule III caption lesson."""
    assert set(_ts_string_array("LISTING_IS_ASKED")) == set(cg._LISTING_IS_ASKED)


def test_the_browser_offers_the_fair_market_value_for_exactly_the_s112a_types():
    assert set(_ts_string_array("GRANDFATHERING_ASSET_TYPES")) == set(cg._EQUITY_LIKE)


def test_the_browser_holds_the_same_acquisition_cut_off():
    src = _FACTS.read_text(encoding="utf-8")
    m = re.search(r'SECTION_55_2_AC_ACQUIRED_BEFORE\s*=\s*"([\d-]+)"', src)
    assert m, "the cut-off date is not in the browser's copy"
    assert m.group(1) == SECTION_55_2_AC_ACQUIRED_BEFORE.isoformat()


def test_the_screen_records_both_facts_rather_than_only_computing_them():
    """A figure the engine gets right and no screen can supply is not a fixed
    bug. Both doors — the calculator and the register's create form — must send
    both fields."""
    page = (_WEB / "app" / "income-tax" / "capital-gains" / "page.tsx").read_text(
        encoding="utf-8")
    assert page.count("is_listed_security:") >= 2, "calculator AND register"
    assert page.count("fmv_31_01_2018_paise:") >= 2
    # And the two lists must be rendered, or the refusals reach nobody.
    assert "gaps" in page and "caveats" in page


def test_the_screen_holds_no_second_copy_of_either_rule():
    """The browser may hold WHEN TO ASK; it may not hold the periods or the
    limbs. Those are the engine's."""
    page = (_WEB / "app" / "income-tax" / "capital-gains" / "page.tsx").read_text(
        encoding="utf-8")
    for rule in ("holding_months >", "> 12 ? ", "Math.max(", "Math.min("):
        assert rule not in page, f"{rule!r} looks like the engine's rule restated"
