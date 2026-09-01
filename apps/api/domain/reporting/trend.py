"""
The multi-year trend statement.

WHAT IT IS, AND WHAT IT IS NOT
    Schedule III requires ONE comparative — General Instructions para 5, the
    "corresponding amounts for the immediately preceding reporting period",
    which build_schedule_iii now carries. Five years side by side is NOT that,
    and this module says so on the document: it is a management and analytical
    view — what a CA puts in front of a client at the annual meeting, and what
    a bank asks for with a loan application.

    Presenting it as a statutory statement would be the mistake here. It has no
    prescribed form, no rounding rule of its own, and no audit status.

WHY IT REUSES EVERYTHING
    Every caption and every ratio here comes from ratios.components_from,
    which buckets through schedule_iii.bucket_amounts — the same function
    build_schedule_iii uses for the face of the statements. A trend whose "Revenue from Operations" is computed differently from
    the Revenue from Operations on the statement is worse than no trend: it
    invites a CA to explain a movement that is really a difference in method.

    So there is no new classification here at all, and nothing to hold in
    parity with anything: there is one implementation and this calls it.

WHY EMPTY LEADING YEARS ARE DROPPED
    A client onboarded two years ago has no 2022-23. Showing it as a column of
    zeros asserts the business had nil revenue and nil assets, which is a
    statement about the business rather than about the records. The document
    reports the window it actually found and says which years were asked for.
"""
from __future__ import annotations

from typing import Optional

from . import ratios as ratio_rules

# The captions to trend, in statement order. A deliberate subset of the full
# Schedule III caption list: a trend is read across, and twenty rows by five
# years is a wall of numbers nobody reads. These are the lines a CA actually
# looks at year on year.
#
# `higher_is_better` is presentation only — it decides which direction is
# green — and is None where the answer depends on the business (borrowings are
# not bad, inventory is not good).
PL_LINES: tuple[tuple[str, str, Optional[bool]], ...] = (
    ("Revenue from Operations", "revenue_from_operations", True),
    ("Other Income", "other_income", None),
    ("Cost of Materials Consumed", "cost_of_materials", None),
    ("Employee Benefit Expense", "employee_benefits", None),
    ("Finance Costs", "finance_costs", False),
    ("Depreciation & Amortisation", "depreciation", None),
    ("Other Expenses", "other_expenses", None),
    ("Profit Before Tax", "profit_before_tax", True),
    ("Tax Expense", "tax_expense", None),
    ("Profit After Tax", "profit_after_tax", True),
)

BS_LINES: tuple[tuple[str, str, Optional[bool]], ...] = (
    ("Share Capital", "share_capital", None),
    ("Reserves & Surplus", "reserves", True),
    ("Long Term Borrowings", "long_term_borrowings", None),
    ("Short Term Borrowings", "short_term_borrowings", None),
    ("Trade Payables", "trade_payables", None),
    ("Tangible Fixed Assets", "tangible", None),
    ("Inventories", "inventories", None),
    ("Trade Receivables", "trade_receivables", None),
    ("Cash & Cash Equivalents", "cash", True),
    ("Working Capital", "working_capital", True),
)

NOT_A_STATUTORY_STATEMENT = (
    "A management view, not a statutory statement. Schedule III General "
    "Instructions para 5 requires the corresponding amounts for the "
    "IMMEDIATELY PRECEDING period only — one comparative, which the balance "
    "sheet and statement of profit and loss carry. Nothing prescribes the form "
    "of a five-year trend, and this one is unaudited."
)

GAP_YEARS_DROPPED = (
    "years_without_records_dropped",
    "One or more of the years asked for has nothing recorded against it and has "
    "been left out rather than shown as zeros. A column of zeros would assert "
    "the business had nil revenue and nil assets that year, which is a claim "
    "about the business rather than about the records.",
)

# A DIFFERENT THING, AND IT MUST NOT BE FOLDED INTO THE ONE ABOVE.
# "Nothing is recorded against 2024-25" is a fact about the business. "2024-25
# could not be read" is a fact about this request — the books may be complete.
# Reporting the second as the first tells a CA their client had no trading year
# when the truth is that a fetch failed, and that is the kind of statement a CA
# repeats to a client.
GAP_YEARS_UNREADABLE = (
    "years_unreadable",
    "One or more of the years asked for could not be read and is missing from "
    "this trend. That is a failure of this request, NOT a finding about the "
    "books — those years may be complete. Reload before drawing any conclusion "
    "from the window that is shown.",
)


def components_of(pl: dict, bs: dict) -> ratio_rules.Components:
    """One year's amounts. Delegates so the trend, the ratio note and the
    statements read one set of numbers."""
    return ratio_rules.components_from(pl, bs)


def has_records(c: ratio_rules.Components) -> bool:
    """Whether a year has anything in it at all."""
    return any((c.total_revenue, c.total_expenses, c.current_assets,
                c.current_liabilities, c.shareholders_funds,
                c.tangible, c.intangible))


def _series(label: str, attr: str, higher_is_better: Optional[bool],
            years: list[ratio_rules.Components]) -> dict:
    values = [getattr(c, attr) for c in years]
    return {
        "label": label,
        "key": attr,
        "higher_is_better": higher_is_better,
        "values_paise": values,
        # One shorter than `values`: the first year has nothing to move from.
        # Absolute AND percentage, because neither alone is readable — a ₹4 lakh
        # rise means nothing without the base, and +300% means nothing without
        # the amount.
        "movement_paise": [values[i] - values[i - 1] for i in range(1, len(values))],
        "movement_bps": [ratio_rules.pct_change_bps(values[i], values[i - 1])
                         for i in range(1, len(values))],
    }


def build(years: list[tuple[str, dict, dict]], requested_fys: list[str],
          unreadable_fys: list[str] | None = None) -> dict:
    """The trend document.

    `years` is [(fy_label, profit_loss, balance_sheet)] in chronological order,
    already filtered to the years that have records. `requested_fys` is what was
    asked for, so the document can say what it dropped. `unreadable_fys` are the
    years that FAILED rather than the years that were empty — see
    GAP_YEARS_UNREADABLE for why the two are never merged.
    """
    labels = [fy for fy, _pl, _bs in years]
    components = [components_of(pl, bs) for _fy, pl, bs in years]

    # The ratios, per year, from ratios.build itself — so a ratio here cannot be
    # defined differently from the same ratio on the clause (Q) note. Each year
    # is built with no preceding year: the 25% test belongs to that note, and a
    # trend shows the movement across the whole window instead.
    per_year_ratios = [ratio_rules.build(c) for c in components]
    ratio_series = []
    for i, spec in enumerate(per_year_ratios[0]["ratios"] if per_year_ratios else []):
        values = [doc["ratios"][i]["value_bps"] for doc in per_year_ratios]
        ratio_series.append({
            "key": spec["key"], "label": spec["label"], "unit": spec["unit"],
            "clause": spec["clause"],
            "values_bps": values,
            "movement_bps": [ratio_rules.pct_change_bps(values[j], values[j - 1])
                             for j in range(1, len(values))],
            "unavailable_reason": spec["unavailable_reason"],
        })

    unreadable = list(unreadable_fys or [])
    dropped = [fy for fy in requested_fys if fy not in labels and fy not in unreadable]
    gaps = [{"code": c, "message": m} for c, m in
            (([GAP_YEARS_DROPPED] if dropped else [])
             + ([GAP_YEARS_UNREADABLE] if unreadable else []))]
    # Whatever the ratios themselves could not compute, said once rather than
    # once per year.
    for gap in (per_year_ratios[-1]["gaps"] if per_year_ratios else []):
        if gap["code"] != "no_preceding_year":       # the trend IS the comparison
            gaps.append(gap)

    return {
        "fys": labels,
        "requested_fys": requested_fys,
        "dropped_fys": dropped,
        "unreadable_fys": unreadable,
        "basis": NOT_A_STATUTORY_STATEMENT,
        "profit_and_loss": [_series(lbl, attr, hib, components)
                            for lbl, attr, hib in PL_LINES],
        "balance_sheet": [_series(lbl, attr, hib, components)
                          for lbl, attr, hib in BS_LINES],
        "ratios": ratio_series,
        "gaps": gaps,
    }
