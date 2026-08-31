"""
Statutory deposit dates arising from a month's payroll.

EPF Scheme 1952 para 38(1); ESI (General) Regulations 1950 reg. 31;
IT Act §192 with Rule 30(2).
"""
from datetime import date

from services.compliance_engine import (
    epf_deposit_due_date, esi_deposit_due_date, tds_deposit_due_date,
    payroll_deposit_due_dates,
)


def test_epf_is_fifteen_days_after_the_wage_month():
    """Para 38(1). Late deposit draws 12% under §7Q plus damages under §14B of
    up to 100% of the arrear."""
    assert epf_deposit_due_date(2026, 7) == date(2026, 8, 15)
    assert epf_deposit_due_date(2026, 12) == date(2027, 1, 15)


def test_esi_is_fifteen_days_not_the_pre_2017_twenty_one():
    """Regulation 31 as amended in 2017. A figure copied from older material is
    a week late."""
    assert esi_deposit_due_date(2026, 7) == date(2026, 8, 15)
    assert esi_deposit_due_date(2026, 7).day == 15


def test_tds_is_the_seventh_of_the_following_month():
    assert tds_deposit_due_date(2026, 7) == date(2026, 8, 7)
    assert tds_deposit_due_date(2026, 12) == date(2027, 1, 7)


def test_march_tds_is_due_on_30_april_not_7_april():
    """Rule 30(2)'s exception, and the one most often missed. §201(1A)(ii)
    charges 1.5% a month from the date of DEDUCTION, so being three weeks late
    on March costs two months of interest rather than one."""
    assert tds_deposit_due_date(2026, 3) == date(2026, 4, 30)
    assert tds_deposit_due_date(2026, 3) != date(2026, 4, 7)


def test_a_month_returns_all_three_soonest_first():
    dues = payroll_deposit_due_dates(2026, 7)
    assert [d["label"] for d in dues] == [
        "TDS on salary", "EPF contribution", "ESI contribution"]
    assert [d["due_date"] for d in dues] == sorted(d["due_date"] for d in dues)


def test_march_reorders_them_because_tds_moves_to_the_end():
    dues = payroll_deposit_due_dates(2026, 3)
    assert dues[-1]["label"] == "TDS on salary"
    assert dues[-1]["due_date"] == date(2026, 4, 30)


def test_every_entry_cites_its_statute():
    """A date with no authority behind it is something a CA has to go and
    verify anyway."""
    for d in payroll_deposit_due_dates(2026, 7):
        assert d["statute"].strip()
        assert d["authority"].strip()


def test_professional_tax_is_deliberately_absent():
    """Its due date is fixed by each state and there is no single rule.
    Inventing one would put a wrong date in a CA's calendar, which is worse
    than the date being missing — and this module models PT for four of the
    twenty-two states that levy it."""
    assert not any("rofessional" in d["label"]
                   for d in payroll_deposit_due_dates(2026, 7))
