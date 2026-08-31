"""
Salary arrears, §89(1) relief, and Form 10E.

THE PROBLEM THE SECTION SOLVES

Salary is taxed in the year of RECEIPT (§15). So a pay revision agreed in 2026
but backdated to 2023 lands three years' arrears in one year's income, pushing
the employee through slabs they would never have reached had they been paid on
time. §89(1) relieves that: the tax is compared with what would have been paid
had each instalment fallen in the year it related to, and the excess is
relieved.

  §89(1)   Where salary is received "in arrears or in advance" and the
           assessee's tax is thereby higher, the Assessing Officer "shall grant
           such relief as may be prescribed".

  Rule 21A(2) prescribes the method for salary arrears, and it is a comparison
           of two totals, not a re-assessment of the earlier years:

             A = tax on the year of receipt INCLUDING the arrears
                 minus tax on that year EXCLUDING them
             B = for each earlier year, tax on that year's income INCLUDING the
                 part of the arrears relating to it, minus tax on that year's
                 income as it was
             relief = A - B, and only where A exceeds B

           The earlier years are NOT reopened, no return is revised, and the
           earlier years' own tax is not refunded. Only the current year's
           liability falls.

  §89 proviso (inserted by Finance Act 2021, w.e.f. 01-04-2021) and Rule 21AA:
           relief "shall not be granted" unless FORM 10E has been filed on the
           e-filing portal BEFORE the return. This is not paperwork. A return
           claiming §89 relief without a Form 10E on record draws an intimation
           under §143(1) disallowing the relief in full, and the assessee then
           has to file the form and rectify. It is one of the commonest §143(1)
           adjustments there is.

WHAT THIS MODULE DOES AND DOES NOT DO

It computes A, B and the relief, using the FY-versioned rate registry so an
earlier year is taxed at ITS OWN rates — the whole point of the exercise
collapses if 2023-24's slice is taxed at 2026-27's slabs.

It does not file Form 10E, and it does not let the relief be applied without
one. `form_10e_acknowledgement` is required for the relief to be reported as
available; absent it, the relief is computed and reported as BLOCKED, with the
reason. Computing it silently and letting a CA apply it is how the §143(1)
notice happens.

It also does not decide which earlier year an instalment relates to. That comes
from the revision order or the award, and is an input.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from dataclasses import dataclass, field

from domain.income_tax.itr_engine import ITRComputeRequest, ITREngine
from domain.income_tax.statutory_rates import RATES_BY_FY


@dataclass
class ArrearSlice:
    """The part of an arrear that relates to one earlier financial year."""
    fy: str
    amount_paise: int
    # The employee's TOTAL INCOME as originally assessed for that year. Rule
    # 21A(2) adds the slice to what the year actually was, so this is needed —
    # and it is the employee's, from their own return, not something payroll
    # holds.
    total_income_that_year_paise: int | None = None


@dataclass
class ReliefResult:
    relief_paise: int = 0
    tax_on_receipt_year_with_arrears_paise: int = 0
    tax_on_receipt_year_without_arrears_paise: int = 0
    difference_a_paise: int = 0
    difference_b_paise: int = 0

    available: bool = False
    blocked_reason: str = ""
    gaps: list[str] = field(default_factory=list)
    per_year: list[dict] = field(default_factory=list)


def rates_exist_for(fy: str) -> bool:
    """Whether the registry actually holds this year, rather than falling back.

    THIS CHECK IS THE DIFFERENCE BETWEEN A RELIEF AND A FICTION. `rates_for()`
    returns LATEST_VERIFIED_FY's figures for a year it does not hold — the
    documented convention across every registry here (CLAUDE.md) — so asking it
    for 2023-24 today returns 2025-26's slabs and rebate without saying so.

    §89 relief is a comparison of years at THEIR OWN rates. Computed against a
    silent fallback, every earlier year is taxed at the current year's slabs,
    B collapses towards A, and the relief comes out wrong in whichever direction
    the two years' rates happen to differ. It looks perfectly reasonable.

    Caught in development on exactly that: a ₹12,00,000 earlier year came back
    with nil tax, because FY 2025-26's §87A rebate reaches ₹12,00,000 and FY
    2023-24's did not.
    """
    return fy in RATES_BY_FY


def _tax(income_paise: int, fy: str, use_new_regime: bool) -> int:
    """Tax on a total income for one financial year, at THAT year's rates.

    Taxing an earlier year's slice at the current year's slabs would defeat the
    exercise: the relief exists precisely because the years differ.
    """
    return ITREngine().compute(ITRComputeRequest(
        # Passed as other_income rather than salary so the §16(ia) standard
        # deduction is not applied a second time — these are TOTAL INCOME
        # figures, already net of it.
        other_income_paise=max(0, income_paise),
        fy=fy,
        use_new_regime=use_new_regime,
    )).total_tax_paise


def compute_relief(
    *,
    receipt_fy: str,
    total_income_receipt_year_paise: int,
    arrears: list[ArrearSlice],
    use_new_regime: bool = True,
    form_10e_acknowledgement: str | None = None,
) -> ReliefResult:
    """§89(1) relief on salary arrears, per Rule 21A(2).

    `total_income_receipt_year_paise` INCLUDES the arrears — it is the year's
    income as it actually is.
    """
    out = ReliefResult()
    total_arrears = sum(max(0, a.amount_paise) for a in arrears)

    if total_arrears <= 0:
        out.blocked_reason = "No arrears, so there is nothing to relieve."
        return out

    if not rates_exist_for(receipt_fy):
        out.blocked_reason = (
            f"The statutory rate registry holds no entry for {receipt_fy}, the "
            f"year of receipt, so the tax on it would be computed at another "
            f"year's slabs. Add it from that year's Finance Act first."
        )
        out.gaps.append(out.blocked_reason)
        return out

    # ── A: the receipt year, with and without the arrears ────────────────────
    with_arrears = _tax(total_income_receipt_year_paise, receipt_fy, use_new_regime)
    without = _tax(max(0, total_income_receipt_year_paise - total_arrears),
                   receipt_fy, use_new_regime)
    out.tax_on_receipt_year_with_arrears_paise = with_arrears
    out.tax_on_receipt_year_without_arrears_paise = without
    out.difference_a_paise = max(0, with_arrears - without)

    # ── B: each earlier year, with and without its slice ─────────────────────
    b_total = 0
    for slice_ in arrears:
        if not rates_exist_for(slice_.fy):
            out.gaps.append(
                f"{slice_.fy}: the statutory rate registry holds no entry for that "
                f"year, and asking for one returns the latest verified year's "
                f"slabs instead. §89 compares years at THEIR OWN rates, so relief "
                f"computed on a substitute is not relief — it is a plausible wrong "
                f"number. Add {slice_.fy} to domain/income_tax/statutory_rates.py "
                f"from that year's Finance Act before claiming this."
            )
            continue
        if slice_.total_income_that_year_paise is None:
            out.gaps.append(
                f"{slice_.fy}: the employee's total income for that year is not "
                f"recorded, so Rule 21A(2)'s second half cannot be computed. It "
                f"comes from their own return for {slice_.fy}, not from payroll. "
                f"Without it the relief cannot be quantified."
            )
            continue
        base = max(0, slice_.total_income_that_year_paise)
        # Each earlier year at ITS OWN rates.
        before = _tax(base, slice_.fy, use_new_regime)
        after = _tax(base + max(0, slice_.amount_paise), slice_.fy, use_new_regime)
        delta = max(0, after - before)
        b_total += delta
        out.per_year.append({
            "fy": slice_.fy,
            "arrear_paise": max(0, slice_.amount_paise),
            "tax_before_paise": before,
            "tax_after_paise": after,
            "additional_tax_paise": delta,
        })

    out.difference_b_paise = b_total

    if out.gaps:
        out.blocked_reason = (
            "Relief cannot be quantified — see the gaps. Each earlier year needs "
            "both its own statutory rates and the employee's total income as "
            "originally assessed."
        )
        return out

    # Rule 21A(2): relief is A - B, and only where A exceeds B.
    out.relief_paise = max(0, out.difference_a_paise - out.difference_b_paise)

    # ── Form 10E: the proviso to §89 ─────────────────────────────────────────
    if not (form_10e_acknowledgement or "").strip():
        out.available = False
        out.blocked_reason = (
            "Relief of ₹{:,.2f} is computed but NOT AVAILABLE: the proviso to §89, "
            "read with Rule 21AA, bars relief unless Form 10E has been filed on "
            "the e-filing portal BEFORE the return. A return claiming §89 without "
            "a Form 10E on record draws a §143(1) intimation disallowing the "
            "relief in full."
        ).format(out.relief_paise / 100)
        return out

    out.available = True
    return out
