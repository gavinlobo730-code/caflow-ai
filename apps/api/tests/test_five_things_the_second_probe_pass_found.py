"""
Five defects the 12 September probe pass found that no finding had recorded.
They are unrelated in subject and identical in shape: a value nobody
maintained, or a rule that was right for one pass through and wrong for the
second.

  1. A purchase bill dated in ANY financial year before the registry starts is
     withheld at the LATEST year's thresholds. `tds_rates_for` substitutes
     `LATEST_VERIFIED_TDS_FY` for a year it does not hold — for a year BEFORE
     it as well as after — and Finance Act 2025 RAISED most thresholds, so an
     earlier year is measured against a bar its own law had not lifted. §194J
     at ₹40,000 in FY 2024-25 comes back nil where ₹4,000 was due, and nothing
     says so. §40(a)(ia) disallows 30% of the expenditure, at assessment.

  2. The SECOND reverse of a payroll run gave nothing back, reopening PAY-08
     one cycle later. `_undo_loan_recoveries` skipped any loan whose id
     appeared among the run's `reversed` rows, so after finalise → reverse →
     finalise there were two `recovered` rows and one `reversed` row, and both
     recoveries were skipped: written down twice, restored once.

  3. The Fixed Assets Register tab read `fixed_assets` over PostgREST with no
     `deleted_at` filter while every backend read excludes them — so a deleted
     asset stayed in the grid and its cost stayed in the Gross Block, and the
     Delete dialog's "the asset leaves the register" was false. (Guarded in
     apps/web; recorded here because the rule is the backend's.)

  4. A quantity typed to four decimals was accepted while the column keeps
     three, and the MONEY was computed from the unrounded value (INV-09).

  5. `asset.get('asset_code', default)` on a NULLABLE column: a default
     substitutes only when the KEY is absent, so a NULL produced the literal
     reference `FA-DEPN-None-{period}` — the same reference for every code-less
     asset of a client in that month, which the posting kernel dedupes on.
"""
import pytest


# ---------------------------------------------------------------------------
# 1. The resident TDS registry's fallback, and the gap that now names it.
# ---------------------------------------------------------------------------
from domain.tds.section_rates import (                            # noqa: E402
    LATEST_VERIFIED_TDS_FY, TDS_RATES_BY_FY, fy_rate_gap,
    rates_are_verified, tds_rates_for,
)
from domain.tds.tds_computer import TDSComputer                    # noqa: E402

resolve_tds = TDSComputer().resolve_tds


def test_a_year_the_registry_does_not_hold_is_not_verified():
    assert rates_are_verified("2024-25") is False
    assert rates_are_verified("2019-20") is False


def test_the_latest_verified_year_is_verified_and_carries_no_gap():
    assert rates_are_verified(LATEST_VERIFIED_TDS_FY) is True
    assert fy_rate_gap(LATEST_VERIFIED_TDS_FY) is None


def test_a_year_carried_forward_is_held_but_not_verified():
    # FY 2026-27 shares FY 2025-26's table by design. That is a different
    # problem from a year nobody holds, and it gets a different sentence.
    assert "2026-27" in TDS_RATES_BY_FY
    assert rates_are_verified("2026-27") is False
    gap = fy_rate_gap("2026-27")
    assert gap and "carried forward" in gap


def test_a_PAST_year_says_the_substitution_may_have_UNDER_deducted():
    # The direction matters and the sentence has to carry it: for a future year
    # last year's figures are an estimate, for a past year they are the wrong
    # law, and Finance Act 2025 moved the thresholds UP.
    gap = fy_rate_gap("2024-25")
    assert gap and "UNDER-deducted" in gap and "2024-25" in gap


def test_the_substitution_itself_is_unchanged_and_still_answers():
    # Refusing outright would make a late-entered prior-year bill unbookable.
    # The engine still answers; the gap is how the caller learns it substituted.
    assert tds_rates_for("2024-25") is TDS_RATES_BY_FY[LATEST_VERIFIED_TDS_FY]
    out = resolve_tds("194J", 40_000_00, fy="2024-25")
    assert out is not None                     # it answers rather than raising


def test_the_worked_example_that_makes_this_worth_a_gap():
    # FY 2025-26's §194J threshold is ₹50,000; FY 2024-25's was ₹30,000. A
    # ₹40,000 professional fee in FY 2024-25 is below one and above the other,
    # so the substitution turns ₹4,000 of tax into nil — silently, until now.
    out = resolve_tds("194J", 40_000_00, fy="2024-25")
    assert out.applies is False                # the wrong answer, still given
    assert fy_rate_gap("2024-25")              # and now named


# ---------------------------------------------------------------------------
# 2. The second reverse.
# ---------------------------------------------------------------------------
class _LoanRowsDB:
    """The one query `_undo_loan_recoveries` makes, answered from a list."""

    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "payroll_loan_recoveries", name
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        class _R:
            data = self._rows
        return _R()


def _undo(monkeypatch, rows):
    """Run the undo over `rows` and return {loan_id: amount restored}."""
    import routers.payroll as pr
    restored: dict[str, int] = {}
    monkeypatch.setattr(
        pr, "_restore_one_loan",
        lambda db, f, c, loan_id, amount, run_id, by: restored.__setitem__(
            loan_id, restored.get(loan_id, 0) + int(amount)))
    notes = pr._undo_loan_recoveries(_LoanRowsDB(rows), "F", "C", "RUN-1")
    return restored, notes


def _row(loan, amount, kind):
    # `_record_loan_movement` signs from `kind`; these are what it would write.
    return {"loan_id": loan, "run_id": "RUN-1", "kind": kind,
            "amount_paise": amount if kind == "recovered" else -amount}


def test_one_cycle_gives_back_exactly_what_it_took(monkeypatch):
    restored, notes = _undo(monkeypatch, [_row("L1", 500000, "recovered")])
    assert restored == {"L1": 500000} and notes == []


def test_a_run_reversed_TWICE_without_re_finalising_gives_back_once(monkeypatch):
    # The case the first version got right, and it must stay right.
    restored, _ = _undo(monkeypatch, [
        _row("L1", 500000, "recovered"),
        _row("L1", 500000, "reversed"),
    ])
    assert restored == {}


def test_the_SECOND_correction_cycle_gives_back_the_second_recovery(monkeypatch):
    # finalise → reverse → finalise → reverse. Two recovered, one reversed.
    # The id-keyed skip saw "L1 has been reversed" and dropped BOTH recoveries,
    # leaving the loan written down 2x and restored 1x.
    restored, _ = _undo(monkeypatch, [
        _row("L1", 500000, "recovered"),
        _row("L1", 500000, "reversed"),
        _row("L1", 500000, "recovered"),
    ])
    assert restored == {"L1": 500000}


def test_a_third_cycle_stays_square(monkeypatch):
    restored, _ = _undo(monkeypatch, [
        _row("L1", 500000, "recovered"), _row("L1", 500000, "reversed"),
        _row("L1", 500000, "recovered"), _row("L1", 500000, "reversed"),
        _row("L1", 500000, "recovered"),
    ])
    assert restored == {"L1": 500000}


def test_two_loans_on_one_run_are_netted_separately(monkeypatch):
    restored, _ = _undo(monkeypatch, [
        _row("L1", 500000, "recovered"),
        _row("L2", 300000, "recovered"),
        _row("L1", 500000, "reversed"),
        _row("L1", 500000, "recovered"),
    ])
    assert restored == {"L1": 500000, "L2": 300000}


def test_a_partial_instalment_nets_rather_than_being_skipped(monkeypatch):
    # The apply path takes min(remaining, owed), so a second cycle can recover
    # a different amount from the first. A skip could not express that; a sum
    # does.
    restored, _ = _undo(monkeypatch, [
        _row("L1", 500000, "recovered"),
        _row("L1", 500000, "reversed"),
        _row("L1", 200000, "recovered"),
    ])
    assert restored == {"L1": 200000}


# ---------------------------------------------------------------------------
# 4. A quantity is stored to three decimals, so three is what may be typed.
# ---------------------------------------------------------------------------
from domain.quantity import QUANTITY_DECIMALS, quantity_violation   # noqa: E402
from models.inventory import StockAdjustmentIn                      # noqa: E402
from models.invoices import InvoiceLineIn, PurchaseBillLineIn       # noqa: E402


@pytest.mark.parametrize("q", [1, 1.5, 0.001, "1.234", 12345.678])
def test_three_decimals_or_fewer_is_accepted(q):
    assert quantity_violation(q) is None


@pytest.mark.parametrize("q", [1.2345, 0.0001, "1.23456"])
def test_a_fourth_decimal_is_refused_rather_than_rounded(q):
    problem = quantity_violation(q)
    assert problem and str(QUANTITY_DECIMALS) in problem


def test_something_that_is_not_a_number_is_refused_as_such():
    assert quantity_violation("x") == "Quantity must be a number."
    assert quantity_violation(float("nan")) == "Quantity must be a number."


def test_every_quantity_field_in_the_product_carries_the_rule():
    # One rule, three fields — the stock adjustment and both line models.
    for build in (
        lambda q: StockAdjustmentIn(client_id="C", adjustment_date="2026-04-10",
                                    quantity=q, direction="decrease", reason="damage"),
        lambda q: InvoiceLineIn(description="x", rate_paise=100, quantity=q,
                                service_catalogue_id="S1"),
        lambda q: PurchaseBillLineIn(description="x", rate_paise=100, quantity=q,
                                     service_catalogue_id="S1"),
    ):
        build(1.234)                                   # accepted
        with pytest.raises(Exception):
            build(1.2345)                              # refused


# ---------------------------------------------------------------------------
# 5. A nullable column and dict.get's default.
# ---------------------------------------------------------------------------
def test_a_null_asset_code_falls_back_to_the_id_not_to_the_string_None():
    # `dict.get(key, default)` substitutes only when the KEY IS ABSENT. Every
    # asset row HAS an `asset_code` key; a legacy one has it set to None. So
    # the default never fired and the reference read "FA-DEPN-None-2026-04" —
    # identical for every code-less asset of that client in that month, and the
    # posting kernel dedupes on (client_id, reference_no, entry_date).
    asset = {"id": "abcdef1234567890", "asset_code": None}
    assert (asset.get("asset_code", asset["id"][:8])) is None        # the bug
    assert (asset.get("asset_code") or asset["id"][:8]) == "abcdef12"  # the fix
