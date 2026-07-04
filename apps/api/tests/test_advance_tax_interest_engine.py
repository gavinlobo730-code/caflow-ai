"""
domain.income_tax.advance_tax_interest_engine — unit tests against
hand-worked Section 234C examples.

R3.13a: this replaces apps/web/app/income-tax/advance-tax/page.tsx's
compute234CInterest(), which computed interest as a function of actual
payment delay (the Section 234B shape) instead of Section 234C's fixed
3/3/3/1-month periods, and had no 12%/36% trigger tolerance at all.

Estimated tax used throughout: ₹10,00,000 (10L) so every percentage split
(12/15/36/45/75/100) lands on an exact paise amount with no rounding.
"""
from datetime import date

from domain.income_tax.advance_tax_interest_engine import (
    compute_234c_interest, installment_schedule, InstallmentPayment, INSTALLMENT_RULES,
)

L = 100_000 * 100
TAX = 10 * L  # estimated annual tax, paise
FY = "2024-25"


def _due(n: int) -> date:
    return dict(installment_schedule(FY))[n]


def _payment(n: int, amount_paise: int, paid_date) -> InstallmentPayment:
    return InstallmentPayment(installment_number=n, paid_amount_paise=amount_paise, paid_date=paid_date)


# ── Schedule ───────────────────────────────────────────────────────────────

def test_installment_schedule_due_dates():
    assert installment_schedule("2024-25") == [
        (1, date(2024, 6, 15)), (2, date(2024, 9, 15)),
        (3, date(2024, 12, 15)), (4, date(2025, 3, 15)),
    ]


def test_installment_rules_are_the_correct_section_234c_structure():
    by_number = {r.number: r for r in INSTALLMENT_RULES}
    assert (by_number[1].cumulative_required_percent, by_number[1].trigger_percent, by_number[1].interest_months) == (15, 12, 3)
    assert (by_number[2].cumulative_required_percent, by_number[2].trigger_percent, by_number[2].interest_months) == (45, 36, 3)
    assert (by_number[3].cumulative_required_percent, by_number[3].trigger_percent, by_number[3].interest_months) == (75, 75, 3)
    assert (by_number[4].cumulative_required_percent, by_number[4].trigger_percent, by_number[4].interest_months) == (100, 100, 1)


# ── No payments at all — full shortfall every instalment ───────────────────

def test_zero_paid_charges_interest_on_full_cumulative_shortfall_every_installment():
    payments = [_payment(n, 0, None) for n in (1, 2, 3, 4)]
    r = compute_234c_interest(FY, TAX, payments)
    by_n = {i.installment_number: i for i in r.installments}
    assert by_n[1].shortfall_paise == int(0.15 * TAX)  # 15% of 10L = 1.5L
    assert by_n[1].interest_paise == round(by_n[1].shortfall_paise * 1 * 3 / 100)
    assert by_n[2].shortfall_paise == int(0.45 * TAX)
    assert by_n[3].shortfall_paise == int(0.75 * TAX)
    assert by_n[4].shortfall_paise == TAX
    assert by_n[4].interest_months == 1
    assert r.total_interest_paise == sum(i.interest_paise for i in r.installments)


# ── Fully paid on time — zero interest throughout ──────────────────────────

def test_fully_paid_on_time_every_installment_has_zero_interest():
    payments = [
        _payment(1, int(0.15 * TAX), _due(1)),
        _payment(2, int(0.30 * TAX), _due(2)),  # + previous 15% = 45% cumulative
        _payment(3, int(0.30 * TAX), _due(3)),  # + previous 45% = 75% cumulative
        _payment(4, int(0.25 * TAX), _due(4)),  # + previous 75% = 100% cumulative
    ]
    r = compute_234c_interest(FY, TAX, payments)
    assert r.total_interest_paise == 0
    assert all(not i.is_short for i in r.installments)


# ── Trigger tolerance — the headline fix ────────────────────────────────────

def test_paying_exactly_the_12_percent_trigger_avoids_installment_1_interest():
    """Real Section 234C behaviour: 12% by 15 Jun is enough to avoid
    interest for instalment 1, even though it is short of the 15% cumulative
    target. The old frontend formula had no such tolerance at all."""
    payments = [_payment(1, int(0.12 * TAX), _due(1))] + [_payment(n, 0, None) for n in (2, 3, 4)]
    r = compute_234c_interest(FY, TAX, payments)
    inst1 = next(i for i in r.installments if i.installment_number == 1)
    assert inst1.is_short is False
    assert inst1.shortfall_paise == 0
    assert inst1.interest_paise == 0


def test_paying_just_below_the_12_percent_trigger_charges_interest_on_the_15_percent_shortfall():
    payments = [_payment(1, int(0.11 * TAX), _due(1))] + [_payment(n, 0, None) for n in (2, 3, 4)]
    r = compute_234c_interest(FY, TAX, payments)
    inst1 = next(i for i in r.installments if i.installment_number == 1)
    assert inst1.is_short is True
    assert inst1.shortfall_paise == int(0.15 * TAX) - int(0.11 * TAX)
    assert inst1.interest_paise == round(inst1.shortfall_paise * 3 / 100)


def test_installment_3_and_4_have_no_tolerance_below_their_own_cumulative_target():
    """Unlike instalments 1/2, paying anything less than the full 75%/100%
    cumulative target charges interest — there is no lower trigger."""
    payments = [
        _payment(1, int(0.15 * TAX), _due(1)),
        _payment(2, int(0.30 * TAX), _due(2)),
        _payment(3, int(0.30 * TAX) - 1, _due(3)),  # 1 paise short of 75% cumulative
        _payment(4, 0, None),
    ]
    r = compute_234c_interest(FY, TAX, payments)
    inst3 = next(i for i in r.installments if i.installment_number == 3)
    assert inst3.is_short is True
    assert inst3.shortfall_paise == 1


# ── Fixed period regardless of actual payment delay (the core bug fix) ────

def test_interest_period_is_fixed_per_installment_not_based_on_actual_delay():
    """The old buggy formula computed months-elapsed between due date and
    paid date (or today, if unpaid) -- e.g. an instalment paid a year late
    would accrue ~12 months of interest. Section 234C instead always
    charges exactly 3 months (instalments 1-3) or 1 month (instalment 4),
    however late the actual payment was."""
    on_time = [_payment(1, 0, _due(1))] + [_payment(n, 0, None) for n in (2, 3, 4)]
    a_year_late = [_payment(1, 0, date(2025, 6, 20))] + [_payment(n, 0, None) for n in (2, 3, 4)]
    r_on_time = compute_234c_interest(FY, TAX, on_time)
    r_late = compute_234c_interest(FY, TAX, a_year_late)
    inst1_on_time = next(i for i in r_on_time.installments if i.installment_number == 1)
    inst1_late = next(i for i in r_late.installments if i.installment_number == 1)
    assert inst1_on_time.interest_months == inst1_late.interest_months == 3
    assert inst1_on_time.interest_paise == inst1_late.interest_paise


# ── Cascading late payment — recorded against an earlier slot but counts later ─

def test_late_lump_payment_recorded_against_an_earlier_slot_still_counts_for_later_installments():
    """A CA might record a full-year lump payment against instalment 1's
    row with a paid_date after instalment 1's own due date (paid late for
    Q1) but before instalment 2's due date. It must NOT count for
    instalment 1 (correctly still short) but MUST count for instalment 2
    onward (genuinely paid in full by then)."""
    lump_paid_date = date(2024, 6, 20)  # after 15 Jun (inst 1 due), before 15 Sep (inst 2 due)
    payments = [_payment(1, TAX, lump_paid_date)] + [_payment(n, 0, None) for n in (2, 3, 4)]
    r = compute_234c_interest(FY, TAX, payments)
    by_n = {i.installment_number: i for i in r.installments}
    assert by_n[1].actual_cumulative_paid_paise == 0
    assert by_n[1].is_short is True
    assert by_n[2].actual_cumulative_paid_paise == TAX
    assert by_n[2].is_short is False
    assert by_n[3].is_short is False
    assert by_n[4].is_short is False
    assert r.total_interest_paise == by_n[1].interest_paise


# ── Non-positive estimated tax — no liability, no interest ─────────────────

def test_zero_or_negative_estimated_tax_has_no_installments_and_no_interest():
    for bad in (0, -100):
        r = compute_234c_interest(FY, bad, [])
        assert r.installments == tuple()
        assert r.total_interest_paise == 0


# ── Integer-only arithmetic ──────────────────────────────────────────────────

def test_all_paise_amounts_are_integers():
    payments = [_payment(n, 0, None) for n in (1, 2, 3, 4)]
    r = compute_234c_interest(FY, 333_333_333, payments)
    for i in r.installments:
        assert isinstance(i.required_cumulative_paise, int)
        assert isinstance(i.actual_cumulative_paid_paise, int)
        assert isinstance(i.shortfall_paise, int)
        assert isinstance(i.interest_paise, int)
    assert isinstance(r.total_interest_paise, int)
