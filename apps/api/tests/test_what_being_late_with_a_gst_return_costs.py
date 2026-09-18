"""GST-21 — §50 interest and the §47 late fee.

Every late GSTR-3B the product prepared carried nil interest and nil late fee:
`gstr3b_computer` hardcoded Table 5.1 to zeros and `services/filing_demo/
gstr3b.py` said so in its own text. The CA computed both by hand.

What these pin is the split between what is COMPUTED and what is REFUSED. The
interest rates are in the Act; the late-fee rates are notifications this
environment cannot reach, and a fee written from memory is a number a CA would
pay over.
"""
from datetime import date

import pytest

import domain.gst.late_filing as lf

from domain.gst.late_filing import (
    DAYS_IN_YEAR, GAP_LATE_FEE_RATES_NOT_HELD, LATE_FEE_RATES, LateFeeRate,
    SECTION_47_1_STATUTORY_CAP_PAISE, SECTION_47_1_STATUTORY_PER_DAY_PAISE,
    SECTION_50_1_RATE_BPS, SECTION_50_3_CEILING_BPS,
    SECTION_50_3_NOTIFIED_RATE_BPS, GAP_SECTION_50_3_RATE_NOT_HELD,
    days_late, interest_on_late_return, interest_on_undeclared_tax,
    interest_on_wrongly_availed_credit, late_fee,
)


# ── the rates ────────────────────────────────────────────────────────────────

def test_section_50_1_is_18_and_section_50_3_is_24_at_its_own_ceiling():
    """§50(1) is 18%, notified by 13/2017-CT and unmoved since.

    §50(3) HAS BEEN CORRECTED THREE TIMES and the third correction is the only
    one made against the documents rather than about them. The module stated
    24%, then refused, then stated 18% on several secondary sources that agreed
    with one another. All three primary documents were then read:

      * Finance Act 2022 **s.111** substitutes §50(3) from 01-07-2017 and
        DELEGATES the rate — "at such rate not exceeding twenty-four per cent.
        as may be notified". No 18% appears in the Act.
      * **Notification 9/2022-CT** commences "clause (c) of section 110 and
        section 111" and nothing else. It does not reach s.116, carries no
        Schedule and states no percentage.
      * **Notification 13/2017-CT**, made under sub-sections (1) AND (3) of
        section 50, fixes §50(3) at 24%, and CBIC's amendment history for it
        records four amendments — all 2020/2021 COVID concessions — and none
        after July 2022.

    THE CEILING AND THE RATE ARE NOW THE SAME NUMBER, and this test asserts
    that deliberately where it used to assert the opposite. The earlier version
    said "collapsing them is how the module got it wrong the first time", which
    reasoned from the shape of the mistake rather than from the sub-section:
    a delegation that has never been exercised again leaves the notified rate
    sitting AT the ceiling, and there is nothing incoherent about that. An
    invariant inferred from a bug is not an invariant.

    VERIFIED is True, and that is a claim about PROVENANCE — a primary document
    was read — not about confidence."""
    assert SECTION_50_1_RATE_BPS == 1800
    assert SECTION_50_3_CEILING_BPS == 2400          # "not exceeding 24%"
    assert SECTION_50_3_NOTIFIED_RATE_BPS == 2400    # 13/2017-CT, never amended
    assert SECTION_50_3_NOTIFIED_RATE_BPS == SECTION_50_3_CEILING_BPS, (
        "the delegation has not been exercised since the substitution, so the "
        "notified rate sits at the Act's own ceiling"
    )
    assert lf.SECTION_50_3_RATE_VERIFIED is True, (
        "the Gazette text of s.111 and both notifications were read; False "
        "here would understate what is actually held"
    )
    for cite in ("s.111", "9/2022", "13/2017", "not exceeding twenty-four"):
        assert cite in lf.SECTION_50_3_RATE_SOURCE
    assert "Sixth Schedule" not in lf.SECTION_50_3_RATE_SOURCE, (
        "s.116 and the Sixth Schedule were the false link in the old chain — "
        "9/2022-CT commences s.110(c) and s.111 only"
    )
    assert DAYS_IN_YEAR == 365


# ── §50(1) on a late return ──────────────────────────────────────────────────

def test_interest_runs_on_the_cash_payable_and_not_the_gross():
    """Rule 88B(1). A taxpayer whose credit ledger covered the whole liability
    owes NO interest however late the return is — which is why the base is
    `cash_payable_paise` and not the output tax."""
    c = interest_on_late_return(due_date=date(2025, 7, 20), filed_on=date(2025, 9, 4),
                                cash_payable_paise=0)
    assert c.interest_paise == 0
    assert c.days == 46


def test_the_arithmetic_is_days_over_365():
    # ₹1,00,000 × 18% × 46/365 = ₹2,268.49…
    c = interest_on_late_return(due_date=date(2025, 7, 20), filed_on=date(2025, 9, 4),
                                cash_payable_paise=1_00_000_00)
    assert c.days == 46
    assert c.interest_paise == 2_268_50   # rounded UP to the paise


def test_interest_rounds_up_because_the_taxpayer_owes_it():
    """Understating a sum somebody OWES leaves them short and a residual demand
    follows. ESI rounds up for the same reason; the GST discount floors,
    because there understating the DISCOUNT cannot under-declare tax. Each
    takes the direction that is safe for whoever carries the liability."""
    c = interest_on_late_return(due_date=date(2025, 7, 20), filed_on=date(2025, 7, 21),
                                cash_payable_paise=1_00_00)   # ₹100, one day
    # ₹100 × 18% × 1/365 = ₹0.0493… → 5 paise, not 4.
    assert c.interest_paise == 5


def test_a_return_filed_on_time_costs_nothing():
    c = interest_on_late_return(due_date=date(2025, 7, 20), filed_on=date(2025, 7, 20),
                                cash_payable_paise=1_00_000_00)
    assert c.days == 0 and c.interest_paise == 0


def test_a_return_filed_early_is_not_negative():
    c = interest_on_late_return(due_date=date(2025, 7, 20), filed_on=date(2025, 7, 10),
                                cash_payable_paise=1_00_000_00)
    assert c.days == 0 and c.interest_paise == 0


def test_one_day_late_is_one_day():
    """The portal counts days, not months. Getting this in months would be the
    §201(1A) arithmetic, which is a different section and thirty times wrong
    here — see domain/tds/interest.py."""
    assert days_late(date(2025, 7, 20), date(2025, 7, 21)) == 1


def test_the_basis_cites_rule_88b_1():
    c = interest_on_late_return(due_date=date(2025, 7, 20), filed_on=date(2025, 9, 4),
                                cash_payable_paise=1_00_000_00)
    assert "88B(1)" in c.basis and "cash" in c.basis.lower()


def test_a_2020_period_is_charged_at_18_percent_and_says_so():
    """The concessional-rate notifications of 2020 are not held. 18% over-states
    for a period they covered, which is the safe direction — and it is named
    rather than silently applied."""
    c = interest_on_late_return(due_date=date(2020, 5, 20), filed_on=date(2020, 9, 1),
                                cash_payable_paise=1_00_000_00,
                                period_start=date(2020, 4, 1))
    assert c.interest_paise > 0
    assert any("concessional" in g for g in c.caveats)


def test_an_ordinary_period_carries_no_such_caveat():
    c = interest_on_late_return(due_date=date(2025, 7, 20), filed_on=date(2025, 9, 4),
                                cash_payable_paise=1_00_000_00,
                                period_start=date(2025, 6, 1))
    assert c.caveats == []


# ── Rule 88B(2) — the other case ─────────────────────────────────────────────

def test_undeclared_tax_bears_interest_on_the_whole_amount():
    """Rule 88B(1)'s cash-only relief reaches tax DECLARED in a late return.
    Tax that comes out of a §73/§74 proceeding gets none of it."""
    c = interest_on_undeclared_tax(due_date=date(2025, 7, 20), paid_on=date(2025, 9, 4),
                                   tax_paise=1_00_000_00)
    assert c.interest_paise == 2_268_50
    assert "88B(2)" in c.basis and "WHOLE" in c.basis


# ── §50(3) — wrongly availed credit ──────────────────────────────────────────

def test_credit_availed_but_never_utilised_is_refused_not_charged(monkeypatch):
    """Rule 88B(3) charges on credit wrongly availed AND UTILISED. Substituting
    the availed figure would charge a taxpayer who owes nothing, at the higher
    of the two rates."""
    import domain.gst.late_filing as lf
    monkeypatch.setattr(lf, "SECTION_50_3_NOTIFIED_RATE_BPS", 1800)
    out = lf.interest_on_wrongly_availed_credit(
        utilised_on=None, reversed_on=None, utilised_paise=None,
        availed_paise=5_00_000_00)
    assert out["refused"] is True
    assert "utilised" in out["reason"].lower()
    assert "₹5,00,000" in out["reason"], "the refusal names the figure it did NOT charge"


def test_a_recorded_utilisation_is_now_CHARGED_and_carries_its_source():
    """Every fact §50(3) needs is stated, so it computes — and the answer says
    which notification produced the figure.

    The caveat travels ON the charge rather than living in a comment. That
    matters MORE now that the rate and the Act's ceiling are the same number:
    a bare "24%" cannot be told from somebody having quoted the ceiling by
    mistake, so the charge names 13/2017-CT and says the delegation has not
    been exercised since."""
    c = interest_on_wrongly_availed_credit(
        utilised_on=date(2025, 5, 10), reversed_on=date(2025, 8, 10),
        utilised_paise=1_00_000_00)
    assert not isinstance(c, dict), "with the rate held this is a charge, not a refusal"
    assert c.rate_bps == 2400
    assert c.caveats, "the source must not be dropped"
    caveat = " ".join(c.caveats)
    assert "13/2017" in caveat, "the notification that fixes the rate is named"
    assert "ceiling" in caveat, "the reader is told the rate sits at the ceiling"
    assert "concessional" in caveat, (
        "the 2020/2021 amendments to 13/2017 are not held, and a period they "
        "covered may be charged less — an over-statement the answer must own"
    )


def test_the_rate_can_be_withdrawn_again_and_the_refusal_still_works():
    """The constant stays Optional deliberately. A later reader who finds 18%
    wrong must be able to set it back to None and get a REFUSAL rather than a
    wrong figure — which is the behaviour this module had, for good reason, and
    which would rot unexercised if nothing tested it."""
    import domain.gst.late_filing as lf_
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(lf_, "SECTION_50_3_NOTIFIED_RATE_BPS", None)
        out = lf_.interest_on_wrongly_availed_credit(
            utilised_on=date(2025, 5, 10), reversed_on=date(2025, 8, 10),
            utilised_paise=1_00_000_00)
        assert out["refused"] is True
        assert out["gap"] == GAP_SECTION_50_3_RATE_NOT_HELD
        assert out["ceiling_bps"] == 2400
        # And the rate refusal still comes BEFORE the missing facts: with no
        # rate there is nothing to compute however complete the facts are, so
        # asking for a utilisation date first sends the CA to fetch something
        # that changes nothing.
        no_facts = lf_.interest_on_wrongly_availed_credit(
            utilised_on=None, reversed_on=None, utilised_paise=None,
            availed_paise=5_00_000_00)
        assert no_facts["gap"] == GAP_SECTION_50_3_RATE_NOT_HELD


def test_the_engine_works_the_moment_the_rate_is_written_in(monkeypatch):
    """The gap is data, not a missing implementation — the same property
    LATE_FEE_RATES has. At 18% the arithmetic is ₹1,00,000 × 18% × 92/365,
    rounded UP because interest is owed."""
    import domain.gst.late_filing as lf
    monkeypatch.setattr(lf, "SECTION_50_3_NOTIFIED_RATE_BPS", 1800)
    c = lf.interest_on_wrongly_availed_credit(
        utilised_on=date(2025, 5, 10), reversed_on=date(2025, 8, 10),
        utilised_paise=1_00_000_00)
    assert c.rate_bps == 1800
    assert c.days == 92
    assert c.interest_paise == 4_536_99
    assert "18% per annum" in c.basis, "the basis must state the rate it used"


@pytest.mark.parametrize("missing", ["utilised_paise", "utilised_on", "reversed_on"])
def test_each_missing_fact_is_named(missing, monkeypatch):
    kw = dict(utilised_on=date(2025, 5, 10), reversed_on=date(2025, 8, 10),
              utilised_paise=1_00_000_00)
    kw[missing] = None
    # With the rate held, the FACTS become the reason again.
    import domain.gst.late_filing as lf
    monkeypatch.setattr(lf, "SECTION_50_3_NOTIFIED_RATE_BPS", 1800)
    out = lf.interest_on_wrongly_availed_credit(**kw)
    assert out["refused"] is True
    assert "utilised" in out["reason"].lower()


# ── §47 — the notified fee, and what it still refuses ────────────────────────

def test_the_notified_ladder_is_held_exactly():
    """Every figure is `[S]`-graded — corroborated across independent secondary
    sources, not read off the notification, because this environment's proxy
    refuses every .gov.in. So each is pinned EXACTLY here, which is the only
    thing that makes a later silent edit visible."""
    r = LATE_FEE_RATES[("gstr3b", "2025-26")]
    assert r.per_day_paise == 50_00              # ₹25 CGST + ₹25 SGST
    assert r.nil_return_per_day_paise == 20_00   # ₹10 + ₹10
    assert r.nil_cap_paise == 500_00
    assert [(b.upto_paise, b.cap_paise) for b in r.turnover_caps] == [
        (1_50_00_000_00, 2_000_00),   # ≤ ₹1.5 crore
        (5_00_00_000_00, 5_000_00),   # ₹1.5 crore – ₹5 crore
        (None,          10_000_00),   # above ₹5 crore
    ]
    assert r.verified is True, (
        "a True here claims a primary source nobody has — the figures are "
        "corroborated, not read off the notification"
    )
    assert "19/2021" in r.source


def test_gstr1_has_its_own_row_rather_than_inheriting_gstr3b():
    """20/2021 is a different notification from 19/2021. They happen to carry
    the same ladder, and deriving one from the other would hide the day they
    stop doing so."""
    assert "20/2021" in LATE_FEE_RATES[("gstr1", "2025-26")].source
    assert "19/2021" in LATE_FEE_RATES[("gstr3b", "2025-26")].source


def test_the_cap_is_banded_by_turnover_and_the_per_day_rate_is_not():
    """The asymmetry is the reason this is not one number. ₹50 a day is charged
    to everyone; only the ceiling moves."""
    r = LATE_FEE_RATES[("gstr3b", "2025-26")]
    assert r.cap_for(1_00_00_000_00) == 2_000_00     # ₹1 crore
    assert r.cap_for(1_50_00_000_00) == 2_000_00     # exactly ₹1.5 crore — INCLUSIVE
    assert r.cap_for(1_50_00_000_01) == 5_000_00     # a paisa over
    assert r.cap_for(5_00_00_000_00) == 5_000_00     # exactly ₹5 crore — INCLUSIVE
    assert r.cap_for(5_00_00_000_01) == 10_000_00


def test_an_unrecorded_turnover_takes_the_LOWEST_cap_and_says_so():
    """Neither direction is harmless — the bands differ by 5x — but the PORTAL
    computes the fee at filing, so an understatement is corrected there while an
    overstatement is this product telling a CA to budget for money their client
    does not owe. The assumption is on the answer, not left to be inferred."""
    out = late_fee(return_type="gstr3b", financial_year="2025-26",
                   due_date=date(2025, 7, 20), filed_on=date(2025, 9, 4))
    assert out.fee_paise == 2_000_00           # 46 × ₹50 = ₹2,300, capped
    assert out.cap_paise == 2_000_00
    assert out.turnover_band_assumed is True
    assert any("LOWEST cap" in c for c in out.caveats)


def test_a_recorded_turnover_removes_the_assumption():
    out = late_fee(return_type="gstr3b", financial_year="2025-26",
                   due_date=date(2025, 7, 20), filed_on=date(2025, 9, 4),
                   aggregate_turnover_paise=9_00_00_000_00)
    assert out.fee_paise == 46 * 50_00         # ₹2,300, well under the ₹10,000 cap
    assert out.capped is False
    assert out.cap_paise == 10_000_00
    assert out.turnover_band_assumed is False


def test_a_nil_return_has_its_own_rate_AND_its_own_cap_and_is_not_banded():
    """A taxpayer with nothing to declare has the same ₹500 ceiling whatever
    their size, so a nil return must not be reported as having assumed a band."""
    for turnover in (None, 9_00_00_000_00):
        out = late_fee(return_type="gstr3b", financial_year="2025-26",
                       due_date=date(2025, 7, 20), filed_on=date(2025, 9, 4),
                       is_nil_return=True, aggregate_turnover_paise=turnover)
        assert out.fee_paise == 500_00         # 46 × ₹20 = ₹920, capped at ₹500
        assert out.cap_paise == 500_00
        assert out.turnover_band_assumed is False


def test_every_answer_carries_the_source_and_the_grading():
    out = late_fee(return_type="gstr3b", financial_year="2025-26",
                   due_date=date(2025, 7, 20), filed_on=date(2025, 9, 4),
                   aggregate_turnover_paise=1_00_00_000_00)
    assert out.caveats, "an [S]-graded figure must never be presented bare"
    joined = " ".join(out.caveats)
    assert "read off the notification" in joined, (
        "the source travels on the answer — and it says READ OFF now, which is "
        "a claim about provenance rather than about confidence"
    )
    assert "portal computes the fee itself" in joined, (
        "the portal is authoritative for this figure, and saying so is what "
        "makes it safe to state at all"
    )


def test_a_year_before_the_2021_ladder_IS_NOW_COMPUTED_at_the_2018_figures():
    """This asserted a REFUSAL until 18-09-2026 and now asserts a figure.

    The refusal was right for as long as 4/2018 and 76/2018 had not been read:
    they govern the earlier periods, they carry different caps, and charging
    those years at the 2021 ladder would be a rate that was not in force. Both
    are now committed under docs/compliance/sources/, and what they say is that
    the PER-DAY RATE NEVER MOVED — ₹25 central tax, ₹10 for a nil return, the
    same figures 2021 kept. What 2021 added was the turnover-banded ceiling and
    the ₹500 nil cap.

    So the fork is entirely in the CAP, and an earlier year takes §47(1)'s own
    ₹5,000 under each Act because neither 2018 notification sets one."""
    out = late_fee(return_type="gstr3b", financial_year="2019-20",
                   due_date=date(2019, 7, 20), filed_on=date(2019, 9, 4))
    assert not isinstance(out, dict), "the 2018 ladder is held; this computes"
    assert out.days == 46
    assert out.fee_paise == 46 * 50_00
    assert out.cap_paise == 10_000_00, (
        "neither 4/2018 nor 76/2018 notifies a cap, so §47(1)'s own applies — "
        "NOT the 2021 ladder's ₹2,000, which did not exist yet"
    )
    assert out.turnover_band_assumed is False, (
        "there are no bands before 2021, so nothing was assumed about turnover"
    )
    assert "76/2018" in out.source


def test_a_nil_return_before_2021_has_no_five_hundred_rupee_cap():
    """The ₹500 nil ceiling is 19/2021's. Reading it back onto 2019 would cap a
    fee at a twentieth of what was chargeable."""
    out = late_fee(return_type="gstr3b", financial_year="2019-20",
                   due_date=date(2019, 7, 20), filed_on=date(2021, 1, 1),
                   is_nil_return=True)
    assert out.cap_paise == 10_000_00
    assert out.fee_paise == 10_000_00, "530 days at ₹20 is well past the cap"


def test_april_and_may_2021_are_inside_the_year_and_outside_the_notification():
    """19/2021 and 20/2021 run from the tax period JUNE 2021, and the rate table
    is keyed on a FINANCIAL year — so two months of FY 2021-22 belong to the
    earlier ladder. This is the one place the key is coarser than the
    notification, and the module says so rather than quietly rounding.

    A caller who names the period gets the right answer; one who does not gets
    the banded cap and a caveat naming the two months. The direction is
    deliberate: the banded cap is the SMALLER for every taxpayer below ₹5 crore,
    so the assumption understates, and the portal corrects at filing."""
    stated = late_fee(return_type="gstr3b", financial_year="2021-22",
                      due_date=date(2021, 5, 20), filed_on=date(2022, 1, 1),
                      tax_period_start=date(2021, 4, 1))
    assert stated.cap_paise == 10_000_00, "April 2021 is the 2018 ladder"

    assumed = late_fee(return_type="gstr3b", financial_year="2021-22",
                       due_date=date(2021, 5, 20), filed_on=date(2022, 1, 1))
    assert assumed.cap_paise == 2_000_00, "no period stated, so banded"
    assert any("April and May 2021" in c for c in assumed.caveats), (
        "a key coarser than the notification's must be named on the answer"
    )

    june = late_fee(return_type="gstr3b", financial_year="2021-22",
                    due_date=date(2021, 7, 20), filed_on=date(2022, 1, 1),
                    tax_period_start=date(2021, 6, 1))
    assert june.cap_paise == 2_000_00, "June 2021 is the first banded period"


def test_the_statutory_figure_is_recorded_and_used_only_where_it_governs():
    """§47(1)'s ₹200 a day is still never a fallback — every monthly year from
    2017-18 is now held, so there is nothing to fall back FROM.

    §47(2)'s is different and IS used: 7/2023's table stops at ₹20 crore of
    aggregate turnover, so a taxpayer above it was never given a reduction and
    the statute is simply what applies to them. Using the statutory figure
    where the statute governs is not the same thing as using it where a
    notification exists and has not been read."""
    assert SECTION_47_1_STATUTORY_PER_DAY_PAISE == 200_00
    assert SECTION_47_1_STATUTORY_CAP_PAISE == 10_000_00
    assert lf.SECTION_47_2_STATUTORY_PER_DAY_PAISE == 200_00
    assert lf.SECTION_47_2_STATUTORY_CAP_BPS == 50

    top = lf.GSTR9_FEE_BANDS[-1]
    assert top.upto_aggregate_paise is None
    assert top.per_day_paise == lf.SECTION_47_2_STATUTORY_PER_DAY_PAISE
    assert top.cap_bps_of_state_turnover == lf.SECTION_47_2_STATUTORY_CAP_BPS


def test_the_monthly_ladder_now_covers_every_year_the_fee_has_existed():
    """There is no monthly year left to refuse. GSTR-1 and GSTR-3B did not
    exist before July 2017 and neither did §47's charge on them."""
    for rt in ("gstr1", "gstr3b"):
        for fy in ("2017-18", "2018-19", "2019-20", "2020-21",
                   "2021-22", "2026-27"):
            assert (rt, fy) in lf.LATE_FEE_RATES, f"{rt} {fy} is not held"
    assert lf.LATE_FEE_FIRST_HELD_FY == "2017-18"
    assert lf.LATE_FEE_BANDED_FROM_FY == "2021-22"


def test_the_annual_fee_is_its_own_sub_section_with_its_own_shape():
    """§47(2) is not a fourth row of the monthly table and could not be.

    Its ceiling is a PERCENTAGE of turnover in the State, so there is no
    cap_paise to write down without a figure about the taxpayer — and it is a
    DIFFERENT turnover from the one that picks the band, which is CGST §2(6)
    aggregate turnover, PAN-level and all-India. `client_gst_turnover` holds
    the second and nothing holds the first."""
    out = late_fee(return_type="gstr9", financial_year="2025-26",
                   due_date=date(2026, 12, 31), filed_on=date(2027, 1, 15),
                   aggregate_turnover_paise=2 * lf._CRORE)
    assert not isinstance(out, dict)
    assert out.days == 15
    assert out.fee_paise == 15 * 50_00, "₹25 + ₹25 a day up to ₹5 crore"
    assert out.capped is False
    assert out.cap_gap == lf.GAP_STATE_TURNOVER_NOT_HELD, (
        "with no State turnover there is no ceiling to report, and a zero cap "
        "would read as 'no cap was reached'"
    )
    assert any("turnover in THIS STATE" in c for c in out.caveats)
    assert any("overstated" in c for c in out.caveats), (
        "this is the one answer in the module that errs HIGH, and it owns it"
    )


def test_the_annual_cap_applies_once_the_state_turnover_is_given():
    """0.02 per cent under each Act — 4 basis points combined."""
    out = late_fee(return_type="gstr9", financial_year="2025-26",
                   due_date=date(2026, 12, 31), filed_on=date(2027, 12, 31),
                   aggregate_turnover_paise=2 * lf._CRORE,
                   state_turnover_paise=1 * lf._CRORE)
    assert out.cap_paise == 4_000_00, "0.04% of ₹1 crore"
    assert out.fee_paise == 4_000_00
    assert out.capped is True
    assert out.cap_gap is None


def test_the_annual_bands_are_the_notifications_own_ladder():
    """₹25 a day to ₹5 crore, ₹50 a day to ₹20 crore, and above that the
    notification gives no reduction at all."""
    def fee(agg):
        return late_fee(return_type="gstr9", financial_year="2025-26",
                        due_date=date(2026, 12, 31), filed_on=date(2027, 1, 1),
                        aggregate_turnover_paise=agg).fee_paise
    assert fee(5 * lf._CRORE) == 1 * 50_00, "the band is INCLUSIVE at ₹5 crore"
    assert fee(6 * lf._CRORE) == 1 * 100_00
    assert fee(25 * lf._CRORE) == 1 * 200_00


def test_an_annual_year_before_the_notification_still_REFUSES():
    """7/2023 says nothing about FY 2021-22 and earlier except through its own
    amnesty proviso, so a year before it is refused rather than charged at a
    ladder that did not reach it."""
    out = late_fee(return_type="gstr9", financial_year="2021-22",
                   due_date=date(2022, 12, 31), filed_on=date(2024, 1, 15))
    assert out["refused"] is True
    assert out["code"] == GAP_LATE_FEE_RATES_NOT_HELD
    assert "7/2023" in out["reason"]
    assert "fee_paise" not in out


def test_the_2023_amnesty_window_is_honoured_and_has_closed():
    """The proviso caps FY 2017-18 to 2021-22 at ₹10,000 under each Act if the
    return was FURNISHED between 1 April and 30 June 2023. It is asked before
    the bands because it REPLACES them, and it needs no turnover at all."""
    inside = late_fee(return_type="gstr9", financial_year="2019-20",
                      due_date=date(2021, 3, 31), filed_on=date(2023, 5, 1))
    assert inside.fee_paise == 20_000_00
    assert inside.capped is True
    assert any("1 April and 30 June 2023" in c for c in inside.caveats)

    outside = late_fee(return_type="gstr9", financial_year="2019-20",
                       due_date=date(2021, 3, 31), filed_on=date(2023, 7, 1))
    assert outside["refused"] is True, "a day past the window and it is gone"


def test_an_unknown_return_type_is_still_refused_rather_than_defaulted():
    """GSTR-4, GSTR-7 and GSTR-8 each carry their own fee and none is held.
    Falling back to the 3B ladder would charge one anyway."""
    for rt in ("gstr4", "gstr7", "gstr8", "cmp08"):
        out = late_fee(return_type=rt, financial_year="2025-26",
                       due_date=date(2026, 12, 31), filed_on=date(2027, 1, 15))
        assert isinstance(out, dict) and out["refused"] is True, rt


# ── the wiring: Table 5.1 and the service ────────────────────────────────────

def _result():
    """One intra-state sale AND a purchase, so the CASH payable is strictly
    less than the gross output tax.

    The purchase is what makes these tests able to see the Rule 88B(1)
    distinction at all. A first draft had no purchases, so
    `cash_payable_cgst == outward_taxable_cgst` and the mutation that charges
    interest on the GROSS passed every assertion — the negative control caught
    the test, not the code.
    """
    from domain.gst.gstr3b_computer import (
        compute_gstr3b, PurchaseTransaction, SalesTransaction,
    )
    sale = SalesTransaction(transaction_type="sales_invoice",
                            taxable_amount_paise=20_00_000_00,
                            cgst_paise=1_80_000_00, sgst_paise=1_80_000_00,
                            igst_paise=0, cess_paise=0,
                            supply_type="taxable", is_reverse_charge=False)
    purchase = PurchaseTransaction(taxable_amount_paise=10_00_000_00,
                                   cgst_paise=90_000_00, sgst_paise=90_000_00,
                                   igst_paise=0, cess_paise=0,
                                   is_reverse_charge=False)
    return compute_gstr3b([sale], [purchase], [])


def test_the_fixture_can_tell_cash_from_gross():
    """The assertion that makes the two below mean something."""
    r = _result()
    assert r.cash_payable_cgst == 90_000_00
    assert r.outward_taxable_cgst == 1_80_000_00


def test_table_5_1_stays_zeros_without_a_filing_date():
    """A return being PREPARED has no filing date, and computing against today
    would give the form a figure that changes every day it is not filed."""
    p = _result().as_gstn_payload("27AAAAA0000A1Z2", "062026")
    assert p["intr_ltfee"]["intr_details"] == {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0}


def test_table_5_1_carries_interest_once_the_date_is_known():
    from datetime import date as _d
    p = _result().as_gstn_payload("27AAAAA0000A1Z2", "062026", filed_on=_d(2026, 9, 4))
    intr = p["intr_ltfee"]["intr_details"]
    # Due 20 July 2026, filed 4 September 2026 = 46 days, on ₹90,000 each side.
    assert intr["camt"] == 2_042 and intr["samt"] == 2_042
    assert intr["iamt"] == 0, "no IGST liability, so no IGST interest"


def test_the_late_fee_cell_stays_zero_whatever_is_passed():
    """§47's notified rates are not held. The refusal is reported beside the
    payload, because a GSTN payload has nowhere to carry a sentence."""
    from datetime import date as _d
    p = _result().as_gstn_payload("27AAAAA0000A1Z2", "062026", filed_on=_d(2026, 9, 4))
    assert p["intr_ltfee"]["fee_details"] == {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0}


def test_the_service_block_is_absent_until_a_date_is_given():
    from services.gst_return_service import _late_filing_block
    out = _late_filing_block(_result(), "062026", None)
    assert out["available"] is False and "filing date" in out["reason"]


def test_the_service_block_names_the_due_date_and_the_days():
    from datetime import date as _d
    from services.gst_return_service import _late_filing_block
    out = _late_filing_block(_result(), "062026", _d(2026, 9, 4))
    assert out["available"] is True
    assert out["due_date"] == "2026-07-20"     # 20th of the following month
    assert out["days_late"] == 46
    # ₹90,000 × 18% × 46/365 = ₹2,041.64…, rounded UP to ₹2,041.65 per head.
    # Table 5.1 shows ₹2,042 because the FORM is in whole rupees (§170, half up)
    # — the paise figure here is the one the working is checked against.
    assert out["interest_total_paise"] == 2 * 2_041_65
    # FY 2026-27 is inside the held ladder, so the fee is now COMPUTED. It was
    # a refusal until the notified figures were written in.
    assert out["late_fee"].get("refused") is not True
    assert out["late_fee"]["fee_paise"] == 2_000_00   # 46 x Rs50, capped
    assert out["late_fee"]["turnover_band_assumed"] is True


def test_the_late_fee_is_keyed_on_the_return_periods_own_financial_year():
    """March 2026's 3B is due on 20 April 2026, which falls in FY 2026-27 — so
    keying off the DUE date would look up the wrong year's notification on
    every March return, the one month a firm files late most often."""
    from datetime import date as _d
    from services.gst_return_service import _late_filing_block
    out = _late_filing_block(_result(), "032026", _d(2026, 6, 15))
    assert out["due_date"] == "2026-04-20"
    assert out["late_fee"]["financial_year"] == "2025-26"


def test_a_malformed_period_does_not_raise():
    from datetime import date as _d
    from services.gst_return_service import _late_filing_block
    assert _late_filing_block(_result(), "not-a-period", _d(2026, 9, 4))["available"] is False
