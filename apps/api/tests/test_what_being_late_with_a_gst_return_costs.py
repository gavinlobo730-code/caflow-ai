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

def test_both_rates_are_18_percent_and_the_ceiling_is_not_the_rate():
    """§50(1) is 18%, notified by 13/2017-CT and unmoved since.

    §50(3) HAS BEEN CORRECTED TWICE. This module first stated 24% — what
    13/2017-CT notified against the ORIGINAL sub-section — then refused to
    state anything, because the Finance Act 2022 substituted §50(3)
    retrospectively from 01-07-2017 and the substituted text was believed to
    carry 18%. A third of the charge separates them and the error direction is
    NOT benign: this is a sum a CA pays over on a client's behalf, so
    over-stating takes money from somebody who does not owe it.

    It is now 18%, on s.111 (the substitution), s.116 with the Sixth Schedule
    (the rate, amended from 24% to 18%) and Notification 9/2022-CT (bringing
    them into force). `[S]`: corroborated across independent secondary sources,
    not read off the notification, which is why VERIFIED stays False and this
    test pins the figure exactly.

    THE CEILING IS NOT THE RATE and the two must stay different numbers — 24%
    is what the sub-section permits ("not exceeding twenty-four per cent") and
    18% is what is notified. Collapsing them is how the module got it wrong the
    first time."""
    assert SECTION_50_1_RATE_BPS == 1800
    assert SECTION_50_3_CEILING_BPS == 2400          # "not exceeding 24%"
    assert SECTION_50_3_NOTIFIED_RATE_BPS == 1800    # notified, [S]-graded
    assert SECTION_50_3_NOTIFIED_RATE_BPS != SECTION_50_3_CEILING_BPS
    assert lf.SECTION_50_3_RATE_VERIFIED is False, (
        "the figure is corroborated, not read off the notification — a True "
        "here would claim a primary source nobody has"
    )
    for cite in ("s.111", "s.116", "Sixth Schedule", "9/2022"):
        assert cite in lf.SECTION_50_3_RATE_SOURCE
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
    where 18% came from.

    The caveat travels ON the charge rather than living in a comment, because a
    CA is about to pay this over and a bare "18%" reads as a figure somebody
    read off a notification. Nobody here did."""
    c = interest_on_wrongly_availed_credit(
        utilised_on=date(2025, 5, 10), reversed_on=date(2025, 8, 10),
        utilised_paise=1_00_000_00)
    assert not isinstance(c, dict), "with the rate held this is a charge, not a refusal"
    assert c.rate_bps == 1800
    assert c.caveats, "an [S]-graded rate must not be presented bare"
    caveat = " ".join(c.caveats)
    assert "9/2022" in caveat and "secondary sources" in caveat
    assert "24%" in caveat, "the ceiling is named so the reader can sanity-check the rate"


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
    assert r.verified is False, (
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
    assert "not read off the notification" in joined
    assert "portal computes the fee itself" in joined, (
        "the portal is authoritative for this figure, and saying so is what "
        "makes it safe to state at all"
    )


def test_a_year_before_the_2021_ladder_still_REFUSES():
    """Notifications 4/2018 and 76/2018 govern earlier periods with different
    caps and no turnover bands. Charging those years at the 2021 figures is a
    rate that was not in force — the fork shape, not a migration."""
    out = late_fee(return_type="gstr3b", financial_year="2019-20",
                   due_date=date(2019, 7, 20), filed_on=date(2019, 9, 4))
    assert out["refused"] is True
    assert out["code"] == GAP_LATE_FEE_RATES_NOT_HELD
    assert out["days"] == 46
    for cite in ("4/2018", "76/2018", "19/2021", "20/2021"):
        assert cite in out["reason"], f"{cite} is a notification a CA has to read"
    assert "fee_paise" not in out


def test_the_statutory_figure_is_recorded_but_never_used_as_a_fallback():
    """₹200 a day is four times what a registered person has paid since 2018.
    It is held so nobody has to look up what the notifications reduced, and a
    refused year gets a REFUSAL rather than it."""
    assert SECTION_47_1_STATUTORY_PER_DAY_PAISE == 200_00
    assert SECTION_47_1_STATUTORY_CAP_PAISE == 10_000_00
    out = late_fee(return_type="gstr3b", financial_year="2019-20",
                   due_date=date(2019, 7, 20), filed_on=date(2019, 9, 4))
    assert "fee_paise" not in out
    assert str(SECTION_47_1_STATUTORY_PER_DAY_PAISE) not in str(out.get("fee_paise", ""))


def test_an_unknown_return_type_is_refused_rather_than_defaulted():
    """GSTR-9's own late fee is a different figure again, and nothing here
    holds it. Falling back to the 3B ladder would charge it anyway."""
    out = late_fee(return_type="gstr9", financial_year="2025-26",
                   due_date=date(2026, 12, 31), filed_on=date(2027, 1, 15))
    assert out["refused"] is True


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
