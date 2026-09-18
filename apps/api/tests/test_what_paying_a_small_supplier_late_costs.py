"""MSMED §16 — the DEBT a late payment creates, which is not the disallowance.

WHY THIS IS A SEPARATE NUMBER (PUR-15's remaining half)
    `domain/income_tax/section_43b_h.py` answers what §43B(h) does to the
    buyer's own taxable income: it defers a deduction to the year of payment.
    §16 answers something else entirely -- the buyer is LIABLE TO THE SUPPLIER
    for compound interest with monthly rests at three times the RBI Bank Rate,
    "notwithstanding anything contained in any agreement", and §23 then
    disallows that interest outright so paying it never releases it.

    A working that reports only the add-back reports the smaller of the two.

⚠️ EVERY CONSTANT AND EVERY SECTION IS `[S]`-GRADED -- egress is refused at
this environment's proxy -- so each is pinned EXACTLY here. A later correction
is then a deliberate edit with a failing test in front of it, never a drift.

NEGATIVE CONTROLS
  * Make `compound_interest_paise` simple interest (drop the exponent) and
    `test_monthly_rests_are_not_simple_interest` fails: at a 6.75% Bank Rate
    over a year the gap is 198 rupees on a 10,000 rupee principal, and it
    widens with the delay.
  * Return a rate instead of None from `interest_refusal` and
    `test_the_bank_rate_is_refused_and_never_guessed` fails -- which is the
    whole design, because a guessed rate is wrong BY A FACTOR OF THREE in
    whichever direction it is wrong.
  * Round the charge DOWN and the rounding test fails.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.income_tax import msmed_interest as m
from domain.income_tax import section_43b_h as h


# ── The two figures §16 actually names ───────────────────────────────────────

def test_the_multiplier_is_three_and_the_rests_are_monthly():
    """Pinned exactly: §16 says "three times of the bank rate" and "monthly
    rests". Both are the section's own words and neither is a convention."""
    assert m.BANK_RATE_MULTIPLE == 3
    assert m.RESTS_PER_YEAR == 12


def test_the_charged_rate_is_three_times_the_bank_rate():
    assert m.charged_rate_bps(675) == 2025
    assert m.charged_rate_bps(600) == 1800
    assert m.charged_rate_bps(0) == 0


def test_the_bank_rate_is_refused_and_never_guessed():
    """The rate moves by RBI notification partway through a year, and a delay
    spanning a change is governed by more than one. Guessing is unsafe in BOTH
    directions and by a multiple of three."""
    assert m.interest_refusal(None) == m.BANK_RATE_IS_NOT_HELD
    assert m.interest_refusal(675) is None
    # And the refusal names what to go and look up, rather than only saying no.
    assert "Bank Rate" in m.BANK_RATE_IS_NOT_HELD
    assert "three times" in m.BANK_RATE_IS_NOT_HELD.lower()
    assert "repo rate" in m.BANK_RATE_IS_NOT_HELD


def test_no_bank_rate_is_stored_anywhere_in_the_module():
    """A registry entry would be a figure nobody here read off a notification.

    Stated as a property rather than as a spelling: no module-level constant
    holds a plausible rate. `BANK_RATE_MULTIPLE` and `RESTS_PER_YEAR` are the
    section's own integers and are allowlisted by name.
    """
    allowed = {"BANK_RATE_MULTIPLE", "RESTS_PER_YEAR"}
    numeric = {
        k: v for k, v in vars(m).items()
        if k.isupper() and isinstance(v, (int, float)) and k not in allowed
    }
    assert numeric == {}, f"a rate crept into the module: {numeric}"


# ── Compounding, which is the thing simple interest gets wrong ───────────────

def test_monthly_rests_are_not_simple_interest():
    """At a 6.75% Bank Rate the charged rate is 20.25% nominal; compounded
    monthly it is about 22.24%. The gap grows with the delay, so it is worst
    exactly where the exposure matters."""
    principal = 1_000_000          # Rs 10,000.00
    charged = m.charged_rate_bps(675)
    compound = m.compound_interest_paise(principal, charged, 12)
    simple = principal * charged // 10_000
    assert compound == 222_393
    assert simple == 202_500
    assert compound > simple


def test_the_charge_rounds_up():
    """A sum the BUYER owes. Understating it leaves a residual debt to a small
    supplier the Act exists to protect -- the same direction ESI takes, and the
    opposite of the GST discount, which floors because flooring there cannot
    under-declare tax."""
    # One rest on 1 paisa at any positive rate is a fraction of a paisa.
    assert m.compound_interest_paise(1, 2025, 1) == 1


@pytest.mark.parametrize("principal, rate, months", [
    (0, 2025, 12), (-500, 2025, 12), (1_000_000, 2025, 0), (1_000_000, 0, 12),
])
def test_nothing_is_charged_where_there_is_nothing_to_charge(principal, rate, months):
    assert m.compound_interest_paise(principal, rate, months) == 0


# ── A rest is a month that has FALLEN DUE ────────────────────────────────────

@pytest.mark.parametrize("start, end, months, part_days", [
    # Exactly one month is one rest.
    (date(2026, 1, 1), date(2026, 2, 1), 1, 0),
    # 45 days is one rest and part of a second that has not arrived.
    (date(2026, 1, 1), date(2026, 2, 15), 1, 14),
    # A day short of the first rest is no rest at all.
    (date(2026, 1, 1), date(2026, 1, 31), 0, 30),
    # Month-end clamps: 31 January plus one month is 28 February.
    (date(2026, 1, 31), date(2026, 2, 28), 1, 0),
    (date(2026, 1, 31), date(2026, 2, 27), 0, 27),
    # A full year.
    (date(2025, 4, 1), date(2026, 4, 1), 12, 0),
    # Backwards or same day is nothing.
    (date(2026, 5, 1), date(2026, 5, 1), 0, 0),
    (date(2026, 5, 1), date(2026, 4, 1), 0, 0),
])
def test_whole_months_are_counted_on_the_calendar(start, end, months, part_days):
    assert m.whole_months_between(start, end) == (months, part_days)


def test_a_month_end_clamps_against_the_original_day_not_the_previous_one():
    """`domain/recurrence.py` records the trap: clamping each step against its
    predecessor walks a 31st series permanently back to the 28th after one
    February. Twelve months from 31 January is 31 January, not 28 January."""
    assert m.whole_months_between(date(2026, 1, 31), date(2027, 1, 31)) == (12, 0)
    assert m.whole_months_between(date(2026, 1, 31), date(2026, 3, 31)) == (2, 0)


def test_a_february_anniversary_falls_on_the_28th_in_a_common_year():
    """Counted anniversary to anniversary, so a leap year cannot make the
    answer disagree with itself -- and the clamp is what makes that true in
    both directions.

    31 January's one-month anniversary is 29 February in a leap year; 29
    February's twelve-month anniversary is 28 February in the next, because
    that is the day a month has passed on. Reading it the other way would say
    a full year of rests had not fallen due on 28 February 2025, which is
    plainly wrong, and would then charge them all at once a day later.

    (The first draft of this test asserted 11 rests. The CODE was right and the
    expectation was not -- recorded because the intuition that a 29 February
    start "has no anniversary" is the tempting one.)
    """
    assert m.whole_months_between(date(2024, 1, 31), date(2024, 2, 29)) == (1, 0)
    assert m.whole_months_between(date(2024, 2, 29), date(2025, 2, 28)) == (12, 0)
    assert m.whole_months_between(date(2024, 2, 29), date(2025, 2, 27)) == (11, 29)


# ── The clock starts the day AFTER the appointed day ─────────────────────────

def _amount(**kw):
    base = dict(bill_id="B1", bill_no="INV/1", vendor_name="Sharma Traders",
                principal_paise=1_000_000, due_by=date(2026, 1, 1),
                settled_on=None)
    base.update(kw)
    return m.LateAmount(**base)


def test_interest_runs_from_the_day_immediately_following():
    """§16's own words. The day the payment became late is not itself a day of
    delay, so a bill due 1 January starts its clock on 2 January."""
    r = m.compute([_amount(settled_on=date(2026, 2, 1))],
                  financial_year="2025-26", bank_rate_bps=675)
    row = r.amounts[0]
    assert row.from_date == "2026-01-02"
    # 2 Jan to 1 Feb is 30 days -- one day short of a rest.
    assert row.months == 0
    assert row.interest_paise == 0


def test_an_unpaid_amount_is_still_accruing_and_says_so():
    r = m.compute([_amount()], financial_year="2025-26", bank_rate_bps=675,
                  as_at=date(2026, 7, 2))
    row = r.amounts[0]
    assert row.still_running is True
    assert row.to_date == "2026-07-02"
    assert row.months == 6
    assert row.interest_paise == m.compound_interest_paise(1_000_000, 2025, 6)
    assert "still accruing" in row.reason


def test_a_settled_amount_stops_at_the_payment_date():
    r = m.compute([_amount(settled_on=date(2026, 4, 2))],
                  financial_year="2025-26", bank_rate_bps=675,
                  as_at=date(2026, 12, 31))
    row = r.amounts[0]
    assert row.still_running is False
    assert row.to_date == "2026-04-02"
    assert row.months == 3


# ── A refused rate still produces the working ────────────────────────────────

def test_without_a_rate_the_working_survives_and_the_charge_is_named():
    """A screen that shows nothing until a rate is recorded teaches the CA the
    feature is broken. Which bills are accruing, and since when, is useful
    before anybody looks anything up."""
    r = m.compute([_amount()], financial_year="2025-26", as_at=date(2026, 7, 2))
    assert r.interest_paise is None
    assert r.charged_rate_bps is None
    row = r.amounts[0]
    assert row.interest_paise is None
    assert row.months == 6                      # the working is intact
    assert m.BANK_RATE_IS_NOT_HELD in r.gaps
    assert r.gaps[0] == m.BANK_RATE_IS_NOT_HELD, "the refusal comes first"


def test_an_amount_with_no_appointed_day_is_named_never_run_from_the_bill_date():
    r = m.compute([_amount(due_by=None)], financial_year="2025-26",
                  bank_rate_bps=675)
    row = r.amounts[0]
    assert row.interest_paise is None
    assert row.from_date is None
    assert any("appointed day" in g for g in r.gaps)


# ── §23 and §22, which are the parts a CA can miss ───────────────────────────

def test_every_answer_carries_section_23_and_section_22():
    r = m.compute([], financial_year="2025-26", bank_rate_bps=675)
    assert m.SECTION_23_DISALLOWS_IT in r.caveats
    assert m.SECTION_22_DISCLOSURE in r.caveats
    assert m.NOTHING_IS_POSTED in r.caveats


def test_section_23_says_paying_it_never_releases_it():
    """That is the whole difference from §43B(h), and it is the reason the two
    add-backs are independent rather than one net figure."""
    assert "NEVER RELEASES" in m.SECTION_23_DISALLOWS_IT
    assert "§43B(h)" in m.SECTION_23_DISALLOWS_IT


def test_the_three_caveats_say_different_things():
    """A caveat that restates its neighbour trains a reader to skip all of
    them -- the `deduction_section_refusal` discipline."""
    assert len({m.SECTION_23_DISALLOWS_IT, m.SECTION_22_DISCLOSURE,
                m.NOTHING_IS_POSTED}) == 3


# ── It reads §43B(h)'s answer rather than restating §15 ──────────────────────

def _bill(**kw):
    base = dict(bill_id="B1", bill_no="INV/1", vendor_id="V1",
                vendor_name="Sharma Traders", msme_status="small",
                bill_date=date(2025, 6, 1), total_paise=1_180_000,
                deductible_paise=1_000_000)
    base.update(kw)
    return h.Bill(**base)


def test_late_amounts_take_the_appointed_day_from_the_43bh_outcome():
    """One definition of when a payment became late, used by both rules."""
    bill = _bill(payments=(h.Payment(paid_on=date(2025, 12, 1),
                                     amount_paise=1_180_000),))
    res = h.compute([bill], financial_year="2025-26")
    outcome = res.bills[0]
    amounts = m.late_amounts(bill, outcome)
    assert len(amounts) == 1
    assert amounts[0].due_by.isoformat() == outcome.due_by
    assert amounts[0].settled_on == date(2025, 12, 1)


def test_each_late_tranche_runs_its_own_clock():
    """§16 charges "on that amount ... from the appointed day", so a bill
    part-paid one month late and cleared six months late owes two periods --
    treating it as one principal over the longer one over-charges."""
    bill = _bill(payments=(
        h.Payment(paid_on=date(2025, 7, 20), amount_paise=500_000),
        h.Payment(paid_on=date(2025, 12, 20), amount_paise=680_000),
    ))
    res = h.compute([bill], financial_year="2025-26")
    amounts = m.late_amounts(bill, res.bills[0])
    assert [a.principal_paise for a in amounts] == [500_000, 680_000]
    assert [a.settled_on for a in amounts] == [date(2025, 7, 20), date(2025, 12, 20)]


def test_an_unpaid_balance_becomes_its_own_still_running_amount():
    bill = _bill(payments=(h.Payment(paid_on=date(2025, 7, 20),
                                     amount_paise=500_000),))
    res = h.compute([bill], financial_year="2025-26")
    amounts = m.late_amounts(bill, res.bills[0])
    unpaid = [a for a in amounts if a.settled_on is None]
    assert len(unpaid) == 1
    assert unpaid[0].principal_paise == res.bills[0].unpaid_paise > 0


def test_a_payment_made_in_time_owes_nothing():
    bill = _bill(payments=(h.Payment(paid_on=date(2025, 6, 10),
                                     amount_paise=1_180_000),))
    res = h.compute([bill], financial_year="2025-26")
    assert m.late_amounts(bill, res.bills[0]) == []


@pytest.mark.parametrize("status", ["medium", "large", None])
def test_a_vendor_section_15_does_not_reach_owes_no_section_16_either(status):
    """§16 charges for failing to pay "as required under section 15", and §15
    protects a "supplier", which §2(n) makes a micro or small enterprise. So
    the same population answers both, and it is read off the §43B(h) outcome
    rather than re-tested here."""
    bill = _bill(msme_status=status,
                 payments=(h.Payment(paid_on=date(2025, 12, 1),
                                     amount_paise=1_180_000),))
    res = h.compute([bill], financial_year="2025-26")
    assert m.late_amounts(bill, res.bills[0]) == []


def test_this_module_reads_nothing_and_posts_nothing():
    """A rule module is a rule: no database handle, no journal.

    The charge is a liability to the SUPPLIER and the journal raising it is the
    CA's -- `itc_register_service`'s judgement about Rule 37, applied here.

    STATED AS THE RULE, NOT A SPELLING. The first draft banned the bare word
    `insert`, which caught `gaps.insert(0, refusal)` -- a list operation that
    has nothing to do with a database. What actually matters is what the module
    IMPORTS (nothing that can reach Postgres) and the two posting functions by
    name.
    """
    import ast
    import inspect
    from tests._python_source import blank_python_docstrings

    tree = ast.parse(blank_python_docstrings(inspect.getsource(m)))

    imported: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            imported.add(n.module or "")
        elif isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
    for mod in imported:
        assert not mod.startswith(("services.", "core.supabase", "repositories.")), (
            f"a rule module imported {mod}; it must take its inputs, not fetch them")

    called = {getattr(n.func, "attr", getattr(n.func, "id", ""))
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for forbidden in ("_create_journal", "post_journal_atomic", "get_supabase"):
        assert forbidden not in called, f"{forbidden} reached from a rule module"
    assert "compound_interest_paise" in called, "vacuity floor: it still computes"
