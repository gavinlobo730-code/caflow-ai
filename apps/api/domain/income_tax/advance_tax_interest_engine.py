"""
Advance tax interest computation — IT Act 1961 Section 234C (interest for
deferment of advance tax) and Section 207/208 (advance-tax liability and
the four-instalment schedule).

R3.13a (fixes a live correctness bug): apps/web/app/income-tax/advance-tax/
page.tsx's compute234CInterest() computed interest as a function of the
*actual* number of days between an instalment's due date and whenever it
was actually paid — that is the Section 234B ("interest for default in
payment") shape, not Section 234C's. Section 234C instead prescribes a
FIXED interest period per instalment (3 months for instalments 1-3, 1
month for instalment 4) regardless of how late the payment actually was,
and additionally gives instalments 1 and 2 a "trigger" tolerance below
their headline cumulative requirement (12% vs. the 15% due by 15 Jun; 36%
vs. the 45% due by 15 Sep) under which no interest applies for that
instalment at all, even though the cumulative amount paid is technically
short of the full-year target. Neither the fixed-period structure nor the
trigger tolerance existed in the old client-side formula, which also used
today's date (not the instalment's own due date) for anything not yet
marked paid.

This module treats Section 234C's numeric structure (the 12/36/75/100
percent thresholds, the 3/3/3/1 month periods, and the 1%-per-month rate)
as settled, long-standing statutory text — not an annually-revised rate
table — and implements it directly, the same way capital_gains_engine.py
implements Section 111A/112A/50AA/115BBH's rates directly rather than
flagging them "pending verification" (that discipline is reserved for
empirical data that changes by government notification, like the CII table
or state Professional Tax slabs — see roadmap R3.1/R3.12).

THE §234C(1) PROVISO FOR INCOME NOBODY COULD HAVE FORESEEN IS APPLIED (IT-21).
This docstring used to record it as a KNOWN SIMPLIFICATION — "the engine has no
per-income-type breakdown to evaluate that proviso" — and a client with a
March sale was charged §234C interest on instalments that were not yet due on
that income. The breakdown is now an INPUT: `UnforeseenIncome` names the kind
(capital gain, winnings under §2(24)(ix), dividend), the date it arose and the
TAX it adds, and `compute_234c_interest(..., unforeseen=[...])` measures each
instalment against the tax due on the returned income LESS the tax on whatever
arose after that instalment's date. The default is the empty list, which is
exactly the behaviour this engine had: no figure moves for a caller that says
nothing. See `_apply_proviso` for the rule and for what it refuses to assume.

Integer paise throughout — never float in any stored or returned amount.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence


def _round_paise(numerator: int, denominator: int) -> int:
    """Integer round-half-up division — never a float intermediate."""
    if denominator == 0:
        return 0
    half = denominator // 2
    if numerator >= 0:
        return (numerator + half) // denominator
    return -((-numerator + half) // denominator)


@dataclass(frozen=True)
class InstallmentRule:
    number: int
    cumulative_required_percent: int  # % of estimated annual tax due by this date — Section 208
    trigger_percent: int              # % below which Section 234C interest applies for this instalment
    interest_months: int              # fixed period Section 234C charges, regardless of actual payment date


# Section 208 instalment schedule — applies to every assessee EXCEPT one under
# presumptive taxation u/s 44AD/44ADA, whose single instalment is below, since
# the Finance Act 2016 amendment aligned the corporate and non-corporate
# schedules onto the same 15/45/75/100 split.
#
# Section 234C(1)'s trigger tolerance: instalments 1 and 2 only need to
# clear 12%/36% (not the full 15%/45%) to avoid interest for THAT
# instalment; instalments 3 and 4 have no such tolerance — the trigger IS
# the full cumulative requirement.
INSTALLMENT_RULES: tuple[InstallmentRule, ...] = (
    InstallmentRule(number=1, cumulative_required_percent=15, trigger_percent=12, interest_months=3),
    InstallmentRule(number=2, cumulative_required_percent=45, trigger_percent=36, interest_months=3),
    InstallmentRule(number=3, cumulative_required_percent=75, trigger_percent=75, interest_months=3),
    InstallmentRule(number=4, cumulative_required_percent=100, trigger_percent=100, interest_months=1),
)

#: THE PRESUMPTIVE ASSESSEE HAS ONE INSTALMENT, NOT FOUR (IT-06).
#:
#: The PROVISO to §211(1) says it plainly: an eligible assessee in respect of an
#: eligible business under §44AD, or an eligible profession under §44ADA, "shall
#: pay the whole amount of such advance tax during each financial year on or
#: before the 15th day of March". There are no 15 June, 15 September or
#: 15 December instalments to defer, so there is nothing for §234C to charge on
#: those dates.
#:
#: §234C(1)(b) is the matching charging limb, and it is a different sentence
#: from §234C(1)(a): where the advance tax paid on or before 15 March is less
#: than the tax due on the returned income, interest runs at one per cent on the
#: shortfall — one month, no tolerance, one time.
#:
#: Applying the four-instalment schedule to such an assessee invents three
#: defaults. A ₹1,00,000 liability paid in full on 15 March — exactly as the
#: statute requires — was charged ₹450 + ₹1,350 + ₹2,250 = ₹4,050 of interest on
#: instalments that were never due.
PRESUMPTIVE_INSTALLMENT_RULES: tuple[InstallmentRule, ...] = (
    InstallmentRule(number=4, cumulative_required_percent=100,
                    trigger_percent=100, interest_months=1),
)

#: Why the single instalment keeps NUMBER 4 rather than 1: it is the same
#: 15 March date as the general schedule's fourth, and a stored
#: advance_tax_payments row is keyed on (client, FY, installment_number). Giving
#: it number 1 would make a presumptive client's 15 March payment collide with a
#: general client's 15 June slot in every query that reads the number, and would
#: silently re-label history if a client's basis ever changed.

_INTEREST_RATE_PERCENT_PER_MONTH = 1


def installment_rules(*, is_presumptive_44ad_44ada: bool = False) -> tuple[InstallmentRule, ...]:
    """Which schedule governs — §208's four, or §211(1)'s proviso's one."""
    return (PRESUMPTIVE_INSTALLMENT_RULES if is_presumptive_44ad_44ada
            else INSTALLMENT_RULES)


def installment_schedule(fy: str, *,
                         is_presumptive_44ad_44ada: bool = False) -> list[tuple[int, date]]:
    """Advance-tax due dates for a given FY string e.g. '2025-26'.

    Four under §208; ONE, on 15 March, for a §44AD/§44ADA assessee under the
    proviso to §211(1).
    """
    start_year = int(fy.split("-")[0])
    if is_presumptive_44ad_44ada:
        return [(4, date(start_year + 1, 3, 15))]
    return [
        (1, date(start_year, 6, 15)),
        (2, date(start_year, 9, 15)),
        (3, date(start_year, 12, 15)),
        (4, date(start_year + 1, 3, 15)),
    ]


@dataclass(frozen=True)
class InstallmentPayment:
    """One instalment's recorded payment. `paid_date=None` means not yet
    paid — it will not count toward any instalment's cumulative total."""
    installment_number: int
    paid_amount_paise: int
    paid_date: Optional[date] = None


#: What the proviso reaches (IT-21). §234C(1)'s own text names capital gains and
#: income of the nature in §2(24)(ix) — winnings from lotteries, crossword
#: puzzles, races, card games and betting — and the Finance Act 2020 added
#: dividend income when it abolished dividend distribution tax. A kind outside
#: this list is REFUSED rather than treated as one of them: "casual income" in
#: the loose sense is not §2(24)(ix), and widening the proviso is a way of
#: showing a client less interest than they owe.
UNFORESEEN_KINDS = ("capital_gain", "winnings", "dividend")

#: The words a screen shows for each, served so no screen spells them.
UNFORESEEN_KIND_LABELS = {
    "capital_gain": "Capital gain",
    "winnings": "Winnings — lottery, crossword, races, cards, betting (§2(24)(ix))",
    "dividend": "Dividend",
}

#: `[S]`-GRADED, AND SAID SO ON THE CONSTANT. The proviso's shape — measure each
#: instalment against the tax due LESS the tax on income that arose after it,
#: and only where that tax is then paid in the remaining instalments or, where
#: none remains, by 31 March — is the section's own, but egress is refused in
#: this environment so neither §234C(1) nor the Finance Act 2020 amendment could
#: be opened. The dividend limb is the least certain of the three. Pinned by
#: tests/test_a_234c_proviso_excuses_the_shortfall_unforeseen_income_caused.py.
UNFORESEEN_PROVISO_VERIFIED = False

_DIVIDEND_CAVEAT = (
    "The dividend limb of the proviso reaches dividend income and not a deemed "
    "dividend under §2(22)(e); nothing recorded here can tell the two apart, so "
    "confirm the dividend is a real one.")
_PROVISO_CAVEAT = (
    "§234C(1)'s proviso is applied as written: each instalment is measured "
    "against the tax due on the returned income LESS the tax on income that "
    "arose AFTER that instalment's date, and only where the tax on that income "
    "is then paid in the instalments that remain — or, where none remains, by "
    "31 March. Payments are taken against each such income in the order it "
    "arose, from the day it arose. The figures behind it ([S]-graded) were not "
    "read against the Act in this environment.")


@dataclass(frozen=True)
class UnforeseenIncome:
    """One income that could not have been estimated when an instalment fell due.

    `tax_paise` is THE TAX THE INCOME ADDS to the year's tax due on the returned
    income — a figure from the computation, never derived here from an amount,
    because it depends on the rest of the return (the §112A exemption is annual,
    the basic exemption absorbs into special-rate gains, surcharge turns on the
    total). It is the caller's, and where the caller estimated it the answer
    says so.
    """
    kind: str
    arose_on: date
    tax_paise: int
    description: str = ""


@dataclass(frozen=True)
class UnforeseenLine:
    """What the proviso did with one income — the working a CA checks."""
    kind: str
    arose_on: date
    tax_paise: int
    description: str
    #: Whether the proviso's CONDITION is met. False means the income is treated
    #: as foreseeable at every instalment, and `reason` says why.
    relief: bool
    #: The last date its tax had to be paid by: the final instalment where one
    #: remained after it arose, 31 March where none did.
    settle_by: date
    paid_toward_paise: int
    reason: str


@dataclass(frozen=True)
class InstallmentInterestResult:
    installment_number: int
    due_date: date
    cumulative_required_percent: int
    trigger_percent: int
    required_cumulative_paise: int
    actual_cumulative_paid_paise: int  # only payments with paid_date <= this due date count
    is_short: bool                     # whether the trigger tolerance was breached
    shortfall_paise: int
    interest_months: int
    interest_paise: int
    #: The tax on income that arose AFTER this instalment's date and was
    #: therefore left out of what it is measured against (IT-21). Zero where
    #: nothing was supplied, which is the engine's behaviour before the proviso
    #: was applied.
    unforeseen_excluded_paise: int = 0
    #: The tax due on the returned income this instalment's percentages were
    #: taken of — the estimated tax less the figure above.
    base_paise: int = 0


@dataclass(frozen=True)
class AdvanceTaxInterestResult:
    installments: tuple[InstallmentInterestResult, ...]
    total_interest_paise: int
    #: Which schedule this was computed on. A caller that shows a presumptive
    #: computation without saying so shows one instalment where the CA expects
    #: four, and nothing on the screen explains the difference.
    is_presumptive_44ad_44ada: bool = False
    basis: str = ""
    #: One line per income handed to the proviso, with whether relief was
    #: granted and why not (IT-21). Empty where none was supplied.
    unforeseen_lines: tuple[UnforeseenLine, ...] = ()
    caveats: tuple[str, ...] = ()


_GENERAL_BASIS = (
    "IT Act §208 — four instalments (15%/45%/75%/100%), with §234C(1)(a)'s "
    "12%/36% tolerance on the first two and a fixed 3/3/3/1-month interest "
    "period.")
_PRESUMPTIVE_BASIS = (
    "IT Act §211(1) proviso — a §44AD/§44ADA assessee pays the whole advance "
    "tax by 15 March, so there is one instalment. §234C(1)(b) charges 1% on the "
    "shortfall from 100%, for one month, with no tolerance.")


def compute_234c_interest(
    fy: str,
    estimated_tax_paise: int,
    payments: list[InstallmentPayment],
    *,
    is_presumptive_44ad_44ada: bool = False,
    unforeseen: Sequence[UnforeseenIncome] = (),
) -> AdvanceTaxInterestResult:
    """Section 234C interest for deferment of advance tax.

    A payment's `paid_date` counts toward an instalment's cumulative total
    only if it is on or before THAT instalment's own due date — a lump
    payment recorded late against instalment N's slot still correctly
    counts toward instalment N+1 (and later)'s cumulative-by-due-date
    total, since by then it has genuinely been paid.

    `is_presumptive_44ad_44ada` selects §211(1)'s proviso instead of §208: one
    instalment on 15 March, §234C(1)(b), no tolerance. It is a FACT ABOUT THE
    ASSESSEE that this engine cannot derive — whether §44AD or §44ADA is opted
    into is the CA's determination and no turnover figure here decides it — so
    it is supplied, not inferred, and the answer carries `basis` saying which
    branch was taken.

    `unforeseen` is §234C(1)'s OTHER proviso (IT-21): income that arose after an
    instalment fell due is left out of what that instalment is measured
    against, on the condition the proviso states. Empty — the default — is
    exactly the behaviour before it was applied.
    """
    if estimated_tax_paise <= 0:
        return AdvanceTaxInterestResult(
            installments=tuple(), total_interest_paise=0,
            is_presumptive_44ad_44ada=is_presumptive_44ad_44ada,
            basis=_PRESUMPTIVE_BASIS if is_presumptive_44ad_44ada else _GENERAL_BASIS)

    due_dates = dict(installment_schedule(
        fy, is_presumptive_44ad_44ada=is_presumptive_44ad_44ada))
    lines, caveats = _apply_proviso(fy, due_dates, payments, list(unforeseen))
    results = []
    total = 0
    for rule in installment_rules(is_presumptive_44ad_44ada=is_presumptive_44ad_44ada):
        due_date = due_dates[rule.number]
        actual_cumulative = sum(
            p.paid_amount_paise for p in payments
            if p.paid_date is not None and p.paid_date <= due_date
        )
        # What arose AFTER this date and met the proviso's condition is not part
        # of what this instalment is measured against. Capped at the whole
        # estimate: the figures are the caller's, and a total that exceeds the
        # tax it is a part of is a sign of an input error that must not turn
        # the base negative.
        excluded = min(estimated_tax_paise, sum(
            ln.tax_paise for ln in lines if ln.relief and ln.arose_on > due_date))
        base = estimated_tax_paise - excluded
        required_cumulative = _round_paise(base * rule.cumulative_required_percent, 100)
        trigger_amount = _round_paise(base * rule.trigger_percent, 100)
        is_short = actual_cumulative < trigger_amount
        shortfall = max(0, required_cumulative - actual_cumulative) if is_short else 0
        interest = _round_paise(shortfall * _INTEREST_RATE_PERCENT_PER_MONTH * rule.interest_months, 100)
        results.append(InstallmentInterestResult(
            installment_number=rule.number,
            due_date=due_date,
            cumulative_required_percent=rule.cumulative_required_percent,
            trigger_percent=rule.trigger_percent,
            required_cumulative_paise=required_cumulative,
            actual_cumulative_paid_paise=actual_cumulative,
            is_short=is_short,
            shortfall_paise=shortfall,
            interest_months=rule.interest_months,
            interest_paise=interest,
            unforeseen_excluded_paise=excluded,
            base_paise=base,
        ))
        total += interest

    if sum(ln.tax_paise for ln in lines if ln.relief) > estimated_tax_paise:
        caveats = caveats + (
            "The tax on the income handed to the proviso exceeds the estimated "
            "tax it is part of, so what each instalment excluded was capped at "
            "the estimate. Check the two figures against each other.",)

    return AdvanceTaxInterestResult(
        installments=tuple(results), total_interest_paise=total,
        is_presumptive_44ad_44ada=is_presumptive_44ad_44ada,
        basis=_PRESUMPTIVE_BASIS if is_presumptive_44ad_44ada else _GENERAL_BASIS,
        unforeseen_lines=lines, caveats=caveats)


def _apply_proviso(
    fy: str,
    due_dates: dict[int, date],
    payments: list[InstallmentPayment],
    items: list[UnforeseenIncome],
) -> tuple[tuple[UnforeseenLine, ...], tuple[str, ...]]:
    """Decide, for each income handed in, whether §234C(1)'s proviso applies.

    THE CONDITION IS ON THE INCOME ITSELF, and it is the half of the proviso a
    simple "leave it out until it arises" gets wrong. The relief is available
    only where the assessee has paid the whole of the tax on that income in the
    instalments that remain after it arose — or, where none remains because it
    arose after the last one, by 31 March. So an income realised on 20 March is
    excused from the 15 March instalment only if its tax is then paid by the
    31st; paid on 5 April it is not, and the 15 March shortfall is charged as if
    it had been foreseen.

    PAYMENTS ARE TAKEN AGAINST EACH INCOME IN THE ORDER IT AROSE, from the day it
    arose to its settlement date, and a rupee is never counted against two of
    them. A payment made BEFORE an income arose cannot have been made "in the
    remaining instalments", which is why an assessee who prepaid generously in
    June gets no relief for a March sale from it. Where an earlier payment is in
    fact what covered the tax, the CA says so by entering the income's tax as
    already paid — which is not a thing this engine can know.

    An income that arose on or before the FIRST instalment date was foreseeable
    at every date and changes nothing; it is returned with `relief=False` and
    that reason, so it appears on the working rather than vanishing from it.

    REFUSES an income outside the financial year (it is not this year's income),
    a kind the proviso does not name, a negative tax and a date that is not a
    date. Raised, never clamped: a misdated gain moves the whole answer.
    """
    if not items:
        return (), ()

    start_year = int(fy.split("-")[0])
    fy_start, fy_end = date(start_year, 4, 1), date(start_year + 1, 3, 31)
    for it in items:
        if it.kind not in UNFORESEEN_KINDS:
            raise ValueError(
                f"'{it.kind}' is not an income §234C(1)'s proviso reaches. It names "
                f"capital gains, winnings under §2(24)(ix) and dividend income: "
                f"{', '.join(UNFORESEEN_KINDS)}.")
        if not isinstance(it.arose_on, date):
            raise ValueError("The date an unforeseen income arose must be a date.")
        if not (fy_start <= it.arose_on <= fy_end):
            raise ValueError(
                f"An income that arose on {it.arose_on.isoformat()} is not income of "
                f"FY {fy} ({fy_start.isoformat()} to {fy_end.isoformat()}), so the "
                f"proviso has nothing to say about it.")
        if not isinstance(it.tax_paise, int) or isinstance(it.tax_paise, bool) or it.tax_paise < 0:
            raise ValueError("The tax on an unforeseen income is integer paise, and not negative.")

    first_due = min(due_dates.values())
    last_due = max(due_dates.values())
    pool = [[p.paid_date, p.paid_amount_paise] for p in payments
            if p.paid_date is not None and p.paid_amount_paise > 0]
    pool.sort(key=lambda row: row[0])

    out: list[UnforeseenLine] = []
    for it in sorted(items, key=lambda i: (i.arose_on, i.kind)):
        remaining = [d for d in due_dates.values() if d >= it.arose_on]
        settle_by = last_due if remaining else fy_end
        needed = it.tax_paise
        got = 0
        taken: list[tuple[int, int]] = []
        for idx, (paid_on, amount) in enumerate(pool):
            if amount <= 0 or paid_on < it.arose_on or paid_on > settle_by:
                continue
            take = min(amount, needed - got)
            if take <= 0:
                break
            taken.append((idx, take))
            got += take
            if got >= needed:
                break

        if it.arose_on <= first_due:
            relief, reason = False, (
                f"It arose on or before the first instalment date "
                f"({first_due.isoformat()}), so it was foreseeable at every instalment "
                f"and the proviso has nothing to excuse.")
        elif needed == 0:
            relief, reason = False, "No tax was supplied for it, so there is nothing to leave out."
        elif got >= needed:
            relief, reason = True, (
                f"Its tax was paid in full between {it.arose_on.isoformat()} and "
                f"{settle_by.isoformat()}, so the shortfall it caused at every earlier "
                f"instalment is excused.")
            for idx, take in taken:
                pool[idx][1] -= take
        else:
            where = ("the instalments that remain" if remaining
                     else "31 March, there being no instalment left")
            relief, reason = False, (
                f"Only {got} of the {needed} paise of tax on it was paid in {where} "
                f"(by {settle_by.isoformat()}), so the proviso's condition is not met and "
                f"it is treated as foreseeable at every instalment.")

        out.append(UnforeseenLine(
            kind=it.kind, arose_on=it.arose_on, tax_paise=it.tax_paise,
            description=it.description, relief=relief, settle_by=settle_by,
            paid_toward_paise=got, reason=reason))

    caveats = [_PROVISO_CAVEAT]
    if any(i.kind == "dividend" for i in items):
        caveats.append(_DIVIDEND_CAVEAT)
    return tuple(out), tuple(caveats)


# ── Sections 234A and 234B ───────────────────────────────────────────────────
#
# The module above implements Section 234C. These two complete the trio, and
# the reason they are here rather than in a module of their own is that all
# three share one rate and one rounding convention — 1% per month or part of a
# month, on integer paise — and splitting them would be the first step to those
# drifting apart.
#
# What must NOT be shared is the shape. The three sections charge different
# amounts over different periods, and conflating them is the mistake this
# module's own header records the frontend having made: it computed 234C as a
# function of actual delay, which is 234B's shape, not 234C's.
#
#   234A  LATE FILING. From the day after the Section 139(1) due date to the
#         date the return is actually furnished. Base: tax on total income less
#         TDS/TCS, advance tax paid and reliefs.
#   234B  ADVANCE-TAX SHORTFALL. From 1 April of the ASSESSMENT year to the
#         date of assessment. Base: the shortfall. Charged ONLY where advance
#         tax plus TDS is BELOW 90% of assessed tax.
#   234C  DEFERMENT of individual instalments. Fixed 3/3/3/1-month periods,
#         regardless of when payment was actually made.

# Section 234B(1) — the gate. Interest arises only where advance tax paid is
# LESS THAN this percentage of assessed tax. At exactly 90% no interest arises
# at all, which is the part most easily missed: a taxpayer who has paid 90.0%
# is fully compliant, not marginally in default.
_S234B_COMPLIANCE_THRESHOLD_PERCENT = 90


def _months_or_part(from_date: date, to_date: date) -> int:
    """Whole months between two dates, counting any PART of a month as a whole
    one — the convention all three sections use ("every month or part of a
    month").

    A period ending on the same day of a later month is that many whole
    months; one day beyond adds another. Nil where to_date is not after
    from_date, so a return filed early cannot earn negative interest.
    """
    if to_date <= from_date:
        return 0
    months = (to_date.year - from_date.year) * 12 + (to_date.month - from_date.month)
    if to_date.day > from_date.day:
        months += 1
    return max(1, months)


@dataclass(frozen=True)
class SectionInterestResult:
    section: str
    applies: bool
    base_paise: int
    months: int
    interest_paise: int
    from_date: date | None
    to_date: date | None
    reasons: tuple[str, ...]


def compute_234a_interest(
    *,
    tax_on_total_income_paise: int,
    tds_tcs_paise: int = 0,
    advance_tax_paid_paise: int = 0,
    relief_paise: int = 0,
    due_date: date,
    return_furnished_on: date | None,
    assessment_date: date | None = None,
) -> SectionInterestResult:
    """Section 234A — interest for defaulting in furnishing the return.

    1% per month or part, from the day AFTER the Section 139(1) due date until
    the return is furnished, on the tax on total income reduced by TDS/TCS,
    advance tax paid and any relief.

    A return NOT YET furnished still accrues: `return_furnished_on=None` runs
    the period to `assessment_date` where one is supplied. Reporting nil for an
    unfiled return would tell a CA the cheapest moment to file is never.
    """
    reasons: list[str] = []
    net = max(0, tax_on_total_income_paise - tds_tcs_paise
              - advance_tax_paid_paise - relief_paise)

    end = return_furnished_on or assessment_date
    if end is None:
        return SectionInterestResult(
            section="234A", applies=False, base_paise=net, months=0,
            interest_paise=0, from_date=due_date, to_date=None,
            reasons=("The return has not been furnished and no assessment date "
                     "was supplied, so the period cannot be closed. Interest is "
                     "still running.",),
        )

    if end <= due_date:
        return SectionInterestResult(
            section="234A", applies=False, base_paise=net, months=0,
            interest_paise=0, from_date=due_date, to_date=end,
            reasons=("The return was furnished on or before the §139(1) due "
                     "date, so no §234A interest arises.",),
        )

    if net <= 0:
        return SectionInterestResult(
            section="234A", applies=False, base_paise=0,
            months=_months_or_part(due_date, end), interest_paise=0,
            from_date=due_date, to_date=end,
            reasons=("Tax on total income is fully covered by TDS, advance tax "
                     "and reliefs, so there is no amount for §234A to charge "
                     "interest on — the delay itself is not what is taxed.",),
        )

    months = _months_or_part(due_date, end)
    interest = net * _INTEREST_RATE_PERCENT_PER_MONTH * months // 100
    reasons.append(
        f"§234A charges {_INTEREST_RATE_PERCENT_PER_MONTH}% per month or part "
        f"for {months} month(s) from the day after {due_date.isoformat()} to "
        f"{end.isoformat()}, on {net} paise of tax net of TDS, advance tax and "
        f"relief."
    )
    return SectionInterestResult(
        section="234A", applies=True, base_paise=net, months=months,
        interest_paise=interest, from_date=due_date, to_date=end,
        reasons=tuple(reasons),
    )


def compute_234b_interest(
    *,
    assessed_tax_paise: int,
    advance_tax_paid_paise: int = 0,
    tds_tcs_paise: int = 0,
    assessment_year_start: date,
    assessment_date: date,
) -> SectionInterestResult:
    """Section 234B — interest for default in payment of advance tax.

    Charged ONLY where advance tax plus TDS falls BELOW 90% of assessed tax.
    At exactly 90% nothing arises: a taxpayer who has paid 90.0% is compliant,
    not marginally in default, and treating the threshold as a floor to clear
    rather than a line not to fall below charges interest to people who owe
    none.

    The period runs from 1 APRIL OF THE ASSESSMENT YEAR — not from the end of
    the financial year, and not from any instalment date — to the date of
    assessment. `assessment_year_start` is that 1 April.

    Unlike §234C, which charges fixed notional periods per instalment, §234B
    charges the actual elapsed months. That difference is the whole reason the
    two are separate sections.
    """
    assessed = max(0, assessed_tax_paise)
    paid = max(0, advance_tax_paid_paise) + max(0, tds_tcs_paise)

    # Compared by cross-multiplication so no division rounds a taxpayer across
    # the 90% line.
    compliant = paid * 100 >= assessed * _S234B_COMPLIANCE_THRESHOLD_PERCENT
    if assessed <= 0 or compliant:
        return SectionInterestResult(
            section="234B", applies=False, base_paise=0, months=0,
            interest_paise=0, from_date=assessment_year_start,
            to_date=assessment_date,
            reasons=(f"Advance tax and TDS of {paid} paise is at least "
                     f"{_S234B_COMPLIANCE_THRESHOLD_PERCENT}% of assessed tax "
                     f"of {assessed} paise, so no §234B interest arises.",),
        )

    shortfall = assessed - paid
    months = _months_or_part(assessment_year_start, assessment_date)
    interest = shortfall * _INTEREST_RATE_PERCENT_PER_MONTH * months // 100
    return SectionInterestResult(
        section="234B", applies=True, base_paise=shortfall, months=months,
        interest_paise=interest, from_date=assessment_year_start,
        to_date=assessment_date,
        reasons=(
            f"Advance tax and TDS of {paid} paise is below "
            f"{_S234B_COMPLIANCE_THRESHOLD_PERCENT}% of assessed tax of "
            f"{assessed} paise, so §234B charges "
            f"{_INTEREST_RATE_PERCENT_PER_MONTH}% per month or part on the "
            f"shortfall of {shortfall} paise for {months} month(s) from "
            f"{assessment_year_start.isoformat()}.",
        ),
    )
