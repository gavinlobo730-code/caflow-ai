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

from domain.gst.late_filing import (
    DAYS_IN_YEAR, GAP_LATE_FEE_RATES_NOT_HELD, LATE_FEE_RATES, LateFeeRate,
    SECTION_47_1_STATUTORY_CAP_PAISE, SECTION_47_1_STATUTORY_PER_DAY_PAISE,
    SECTION_50_1_RATE_BPS, SECTION_50_3_RATE_BPS,
    days_late, interest_on_late_return, interest_on_undeclared_tax,
    interest_on_wrongly_availed_credit, late_fee,
)


# ── the rates ────────────────────────────────────────────────────────────────

def test_the_two_statutory_rates():
    assert SECTION_50_1_RATE_BPS == 1800     # §50(1), Notification 13/2017-CT
    assert SECTION_50_3_RATE_BPS == 2400     # §50(3) as substituted
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

def test_credit_availed_but_never_utilised_is_refused_not_charged():
    """Rule 88B(3) charges on credit wrongly availed AND UTILISED. Substituting
    the availed figure would charge a taxpayer who owes nothing, at the higher
    of the two rates."""
    out = interest_on_wrongly_availed_credit(
        utilised_on=None, reversed_on=None, utilised_paise=None,
        availed_paise=5_00_000_00)
    assert out["refused"] is True
    assert "utilised" in out["reason"].lower()
    assert "₹5,00,000" in out["reason"], "the refusal names the figure it did NOT charge"


def test_a_recorded_utilisation_is_charged_at_24_percent():
    c = interest_on_wrongly_availed_credit(
        utilised_on=date(2025, 5, 10), reversed_on=date(2025, 8, 10),
        utilised_paise=1_00_000_00)
    assert c.rate_bps == 2400
    assert c.days == 92
    # ₹1,00,000 × 24% × 92/365 = ₹6,049.31…
    assert c.interest_paise == 6_049_32


@pytest.mark.parametrize("missing", ["utilised_paise", "utilised_on", "reversed_on"])
def test_each_missing_fact_is_named(missing):
    kw = dict(utilised_on=date(2025, 5, 10), reversed_on=date(2025, 8, 10),
              utilised_paise=1_00_000_00)
    kw[missing] = None
    out = interest_on_wrongly_availed_credit(**kw)
    assert out["refused"] is True


# ── §47 — the refusal ────────────────────────────────────────────────────────

def test_the_late_fee_is_refused_with_the_notification_to_read():
    out = late_fee(return_type="gstr3b", financial_year="2025-26",
                   due_date=date(2025, 7, 20), filed_on=date(2025, 9, 4))
    assert out["refused"] is True
    assert out["code"] == GAP_LATE_FEE_RATES_NOT_HELD
    assert out["days"] == 46
    for cite in ("4/2018", "76/2018", "19/2021", "20/2021"):
        assert cite in out["reason"], f"{cite} is the notification a CA has to read"


def test_the_statutory_figure_is_recorded_but_never_used_as_a_fallback():
    """₹200 a day is four times what a registered person has paid since 2018.
    It is held so nobody has to look up what the notifications reduced, and it
    is deliberately not a default."""
    assert SECTION_47_1_STATUTORY_PER_DAY_PAISE == 200_00
    assert SECTION_47_1_STATUTORY_CAP_PAISE == 10_000_00
    out = late_fee(return_type="gstr3b", financial_year="2025-26",
                   due_date=date(2025, 7, 20), filed_on=date(2025, 9, 4))
    assert "fee_paise" not in out


def test_the_rate_table_is_empty_and_that_is_the_state_of_the_world():
    assert LATE_FEE_RATES == {}, (
        "adding a row is a human step — read the notification in force for that "
        "year and that turnover band, like the state professional-tax slabs")


def test_a_recorded_rate_is_applied_and_capped(monkeypatch):
    """The engine works the moment somebody fills the table in."""
    monkeypatch.setitem(LATE_FEE_RATES, ("gstr3b", "2025-26"),
                        LateFeeRate(per_day_paise=50_00, nil_return_per_day_paise=20_00,
                                    cap_paise=2_000_00, source="Notification 19/2021-CT"))
    out = late_fee(return_type="gstr3b", financial_year="2025-26",
                   due_date=date(2025, 7, 20), filed_on=date(2025, 9, 4))
    assert out.days == 46
    assert out.fee_paise == 2_000_00        # 46 × ₹50 = ₹2,300, capped at ₹2,000
    assert out.capped is True
    assert out.source == "Notification 19/2021-CT"


def test_a_nil_return_takes_its_own_lower_rate(monkeypatch):
    monkeypatch.setitem(LATE_FEE_RATES, ("gstr3b", "2025-26"),
                        LateFeeRate(per_day_paise=50_00, nil_return_per_day_paise=20_00,
                                    cap_paise=5_000_00, source="x"))
    out = late_fee(return_type="gstr3b", financial_year="2025-26",
                   due_date=date(2025, 7, 20), filed_on=date(2025, 8, 4),
                   is_nil_return=True)
    assert out.fee_paise == 15 * 20_00 and out.capped is False


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
    assert out["late_fee"]["refused"] is True


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
