"""IT Act §43B(h) — a sum payable to a micro or small enterprise, paid late.

PUR-15. `/accounting/msme-tracker` asked the CA to type every bill in again
into `msme_payments` and then computed the whole statutory rule in TypeScript.
The figure was a re-keying of data the books already hold, it drifted the
moment a bill was corrected, `rbac()` never ran on the write, and the rule
lived in the browser.

These pin the RULE. The fetch is tested in
tests/test_the_43b_h_working_reads_the_purchase_ledger.py.

WHAT MATTERS MOST HERE, in order:

  * the limit is FIFTEEN days, not forty-five. Forty-five is the number every
    article quotes and it is the exception (the proviso to MSMED §15 caps a
    WRITTEN agreement); applying it by default gives a month's grace the Act
    does not and understates the disallowance;
  * the first proviso to §43B does not reach clause (h);
  * only MICRO and SMALL — a medium enterprise is registered under the MSMED
    Act and is still outside §15 (§2(n));
  * an unclassified vendor is NAMED, not assumed either way.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.income_tax import section_43b_h as rule
from domain.income_tax.section_43b_h import (
    APPOINTED_DAY_DAYS, Bill, MAX_AGREED_DAYS, Payment, compute, fy_of,
    limit_days,
)

FY = "2025-26"
MAY1 = date(2025, 5, 1)


def _bill(**kw):
    base = dict(bill_id="b1", bill_no="INV-1", vendor_id="v1",
                vendor_name="Acme Tools", msme_status="micro", bill_date=MAY1,
                total_paise=1_18_000, deductible_paise=1_00_000)
    base.update(kw)
    return Bill(**base)


# ── the time limit ───────────────────────────────────────────────────────────

def test_the_limit_is_fifteen_days_with_no_written_agreement():
    """MSMED §2(b): the appointed day is the day immediately following the
    expiry of FIFTEEN days from acceptance. Not forty-five."""
    days, why = limit_days(None)
    assert days == APPOINTED_DAY_DAYS == 15
    assert "§2(b)" in why and "no written agreement" in why


def test_a_written_agreement_sets_the_period():
    days, why = limit_days(30)
    assert days == 30
    assert "Written agreement" in why


def test_a_written_agreement_longer_than_forty_five_is_capped_AND_says_so():
    """The proviso to §15: 'in no case shall the period agreed upon ... exceed
    forty-five days'. A sixty-day contract is not void — it is ineffective
    past forty-five — so what is stored is what the contract says and the
    capping is stated rather than silently applied."""
    days, why = limit_days(60)
    assert days == MAX_AGREED_DAYS == 45
    assert "60 days" in why and "capped at 45" in why


def test_a_nonsense_period_falls_back_to_the_statutory_default():
    days, why = limit_days(0)
    assert days == 15
    assert "not a period" in why


def test_payment_on_the_last_day_of_the_limit_is_in_time():
    """§15 requires payment 'before the appointed day', and the appointed day
    is the day AFTER the fifteen expire — so day fifteen itself is in time."""
    r = compute([_bill(payments=(Payment(date(2025, 5, 16), 1_18_000),))],
                financial_year=FY)
    assert r.bills[0].due_by == "2025-05-16"
    assert r.disallowed_paise == 0


def test_payment_the_next_day_is_late():
    r = compute([_bill(payments=(Payment(date(2025, 5, 17), 1_18_000),))],
                financial_year=FY)
    assert r.disallowed_paise == 1_00_000


# ── who it reaches ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["micro", "small"])
def test_micro_and_small_are_reached(status):
    r = compute([_bill(msme_status=status, payments=())], financial_year=FY)
    assert r.disallowed_paise == 1_00_000
    assert r.bills[0].included is True


@pytest.mark.parametrize("status", ["medium", "not_registered"])
def test_medium_and_unregistered_are_not(status):
    """MSMED §2(n) makes a 'supplier' a micro or small enterprise. A MEDIUM
    enterprise is registered under the Act and is still outside §15 — the same
    line Schedule III's payables ageing draws for row (i)."""
    r = compute([_bill(msme_status=status, payments=())], financial_year=FY)
    assert r.disallowed_paise == 0
    assert r.bills[0].included is False
    assert "§2(n)" in r.bills[0].reason


def test_an_unclassified_vendor_is_named_and_left_out():
    """Whether a supplier is micro or small is a fact about their Udyam
    registration that no ledger holds. Guessing 'not MSME' would silently drop
    a disallowance; guessing 'micro' would add one that is not due."""
    r = compute([_bill(msme_status=None, payments=())], financial_year=FY)
    assert r.disallowed_paise == 0
    assert r.bills[0].reason == rule.GAP_MSME_STATUS_NOT_CLASSIFIED
    assert len(r.gaps) == 1
    assert "Udyam" in r.gaps[0]


# ── the amount ───────────────────────────────────────────────────────────────

def test_the_disallowance_is_the_DEDUCTION_not_the_gross_invoice():
    """§15 obliges payment of the whole invoice; §43B disallows a DEDUCTION.
    Creditable GST is input tax credit, not an expense, so it is not at risk."""
    r = compute([_bill(total_paise=1_18_000, deductible_paise=1_00_000,
                       payments=())], financial_year=FY)
    assert r.disallowed_paise == 1_00_000


def test_a_part_payment_in_time_saves_its_own_share():
    """§43B(h) reaches 'any sum payable ... beyond the time limit' — the part
    still owing at the limit, not the whole invoice."""
    r = compute([_bill(payments=(Payment(date(2025, 5, 10), 59_000),))],
                financial_year=FY)
    # Half the gross was in time, so half the deduction stands.
    assert r.disallowed_paise == 50_000
    assert r.bills[0].paid_in_time_paise == 59_000
    assert r.bills[0].unpaid_paise == 59_000


def test_tds_withheld_counts_as_paid_to_the_supplier():
    """The same interpretation domain/gst/itc_reversal.py applies to Rule 37:
    tax deducted is remitted to the government on the supplier's behalf and
    credited to them under §199, so the supply is settled even though less
    cash moved. Treating it as unpaid would disallow a sum in substance paid."""
    r = compute([_bill(tds_paise=18_000,
                       payments=(Payment(date(2025, 5, 10), 1_00_000),))],
                financial_year=FY)
    assert r.disallowed_paise == 0
    assert r.bills[0].unpaid_paise == 0


def test_without_the_tds_allowance_the_same_bill_would_be_disallowed():
    """Pins the size of the interpretation."""
    r = compute([_bill(tds_paise=0,
                       payments=(Payment(date(2025, 5, 10), 1_00_000),))],
                financial_year=FY)
    assert r.disallowed_paise > 0


def test_a_capitalised_bill_is_reported_and_disallows_nothing():
    """Nothing was deducted — the cost sits on the balance sheet and only the
    depreciation is claimed. The MSMED §15 obligation to pay is unaffected,
    which is why it is reported rather than dropped."""
    r = compute([_bill(capitalised=True, payments=())], financial_year=FY)
    assert r.disallowed_paise == 0
    assert "Capitalised" in r.bills[0].reason
    assert "§15 obligation to pay still stands" in r.bills[0].reason


# ── which year ───────────────────────────────────────────────────────────────

def test_a_bill_of_an_earlier_year_does_not_add_back_this_year():
    r = compute([_bill(bill_date=date(2024, 5, 1), payments=())],
                financial_year=FY)
    assert r.disallowed_paise == 0


def test_an_earlier_years_bill_paid_late_this_year_comes_BACK_this_year():
    """§43B allows the sum 'in computing the income of that previous year in
    which such sum is actually paid'."""
    r = compute([_bill(bill_date=date(2024, 5, 1),
                       payments=(Payment(date(2025, 9, 1), 1_18_000),))],
                financial_year=FY)
    assert r.disallowed_paise == 0
    assert r.allowed_on_payment_paise == 1_00_000


def test_paying_it_in_a_different_year_releases_nothing_here():
    r = compute([_bill(bill_date=date(2024, 5, 1),
                       payments=(Payment(date(2027, 9, 1), 1_18_000),))],
                financial_year=FY)
    assert r.allowed_on_payment_paise == 0


def test_this_years_bill_paid_late_is_disallowed_now_and_not_released_now():
    """Disallowed in the year of accrual; the release comes in the year of
    payment, which is a different year and a different return."""
    r = compute([_bill(bill_date=date(2025, 5, 1),
                       payments=(Payment(date(2025, 9, 1), 1_18_000),))],
                financial_year=FY)
    assert r.disallowed_paise == 1_00_000
    assert r.allowed_on_payment_paise == 0
    assert r.bills[0].paid_late_in_fys == ("2025-26",)


@pytest.mark.parametrize("d,fy", [
    (date(2025, 4, 1), "2025-26"), (date(2026, 3, 31), "2025-26"),
    (date(2025, 3, 31), "2024-25"), (date(2026, 4, 1), "2026-27"),
])
def test_the_financial_year_runs_april_to_march(d, fy):
    assert fy_of(d) == fy


def test_the_clause_does_not_reach_a_year_before_2023_24():
    """Inserted by the Finance Act 2023 with effect from AY 2024-25."""
    r = compute([_bill(payments=())], financial_year="2022-23")
    assert r.applicable is False
    assert r.disallowed_paise == 0
    assert any("Finance Act 2023" in c for c in r.caveats)


# ── what every answer says ───────────────────────────────────────────────────

def test_every_answer_says_the_first_proviso_does_not_apply():
    """The single commonest mistake with this clause: every other §43B item is
    saved by paying before the §139(1) return date, and (h) is not."""
    r = compute([], financial_year=FY)
    assert rule.FIRST_PROVISO_DOES_NOT_APPLY in r.caveats
    assert "does NOT reach clause (h)" in rule.FIRST_PROVISO_DOES_NOT_APPLY


def test_the_proxy_caveat_appears_only_on_a_bill_THAT_USED_THE_PROXY():
    """§15 runs from the day of acceptance or deemed acceptance, and until
    PUR-25 the books held only the bill date — so this caveat was on EVERY
    answer, including an empty one.

    Migration 393's goods receipt supplies the real date, so the caveat is now
    emitted only for the bills that actually fell back. A caveat that appears
    whether or not it applies is one a reader learns to skip, and this one has
    to be read: the proxy gives the EARLIEST due date and therefore the
    LARGEST disallowance.
    """
    assert "ACCEPTANCE" in rule.ACCEPTANCE_DATE_NOT_HELD
    # Nothing to speak for.
    assert rule.ACCEPTANCE_DATE_NOT_HELD not in compute(
        [], financial_year=FY).caveats
    # A bill with no goods receipt behind it.
    proxied = compute([_bill(payments=())], financial_year=FY)
    assert rule.ACCEPTANCE_DATE_NOT_HELD in proxied.caveats
    # And one with a real acceptance date does not raise it.
    accepted = compute(
        [_bill(payments=(), acceptance_date=date(2025, 5, 20))],
        financial_year=FY)
    assert rule.ACCEPTANCE_DATE_NOT_HELD not in accepted.caveats


def test_the_clock_runs_from_the_ACCEPTANCE_date_where_one_is_held():
    """MSMED §2(b), Explanation: the day of acceptance is the day of ACTUAL
    DELIVERY. Goods arrive after the invoice as often as before, so the real
    date is usually LATER than the bill date — which lengthens the period and
    can only REMOVE a disallowance the proxy manufactured, never create one."""
    bill_date = date(2025, 5, 1)
    delivered = date(2025, 5, 20)
    paid = date(2025, 6, 2)          # 32 days after the bill, 13 after delivery
    # The WHOLE gross, so nothing is left unpaid to disallow proportionally —
    # the only thing under test here is which date the fifteen days run from.
    settled = (rule.Payment(paid, 1_18_000),)
    # On the proxy that is late; §15's fifteen days ran out on 16 May.
    on_proxy = compute([_bill(bill_date=bill_date, payments=settled)],
                       financial_year=FY)
    assert on_proxy.disallowed_paise > 0
    # On the real acceptance date it is in time — 4 June was the limit.
    on_acceptance = compute([_bill(bill_date=bill_date,
                                   acceptance_date=delivered,
                                   payments=settled)],
                            financial_year=FY)
    assert on_acceptance.disallowed_paise == 0
    outcome = on_acceptance.bills[0]
    assert outcome.due_by == "2025-06-04"
    assert "day of acceptance" in outcome.limit_source


def test_the_YEAR_of_the_add_back_is_still_the_BILL_s():
    """§43B(h) disallows a deduction claimed in the previous year the expense
    ACCRUED in, and the expense accrues with the bill. Only the fifteen-day
    CLOCK moves to the acceptance date — a March bill received in April must
    not silently move its disallowance into the next year's computation."""
    march = date(2026, 3, 20)
    april = date(2026, 4, 5)
    r = compute([_bill(bill_date=march, acceptance_date=april, payments=())],
                financial_year=FY)
    assert r.disallowed_paise == 1_00_000, (
        "the add-back left FY 2025-26 because the goods arrived in April")


def test_a_bill_with_no_date_is_a_gap_not_a_disallowance():
    r = compute([_bill(bill_date=None, payments=())], financial_year=FY)
    assert r.disallowed_paise == 0
    assert any("no date" in g for g in r.gaps)


def test_to_dict_carries_both_directions():
    d = compute([_bill(payments=())], financial_year=FY).to_dict()
    assert d["disallowed_paise"] == 1_00_000
    assert d["allowed_on_payment_paise"] == 0
    assert d["financial_year"] == FY
    assert d["bills"][0]["limit_days"] == 15
    assert d["bills"][0]["due_by"] == "2025-05-16"
