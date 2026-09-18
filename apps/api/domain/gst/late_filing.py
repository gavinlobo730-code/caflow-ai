"""What being late with a GST return costs — §50 interest and the §47 late fee.

GST-21. For any late GSTR-3B the product prepares, Table 5.1 came out as zeros
(`gstr3b_computer` hardcoded `intr_ltfee`) and `services/filing_demo/gstr3b.py`
said plainly in its own text that "PracticeSync does not compute §50 interest
or §47 late fee". The CA worked both out by hand. ClearTax, IRIS and Tally all
show them before filing.

WHAT IS COMPUTED HERE AND WHAT IS REFUSED

The INTEREST is computed. Its rates are in the Act itself — §50(1) "at such
rate not exceeding eighteen per cent as may be notified" (notified at 18% by
Notification 13/2017-Central Tax) and §50(3) at twenty-four per cent — and the
rule that decides the BASE is textual rather than numeric.

The LATE FEE is REFUSED, and that is the deliberate half. §47(1) sets a
statutory ₹100 per day per Act capped at ₹5,000, but no registered person has
paid that since 2018: Notifications 4/2018 and 76/2018 reduced it, and 19/2021
and 20/2021 capped it by turnover band. Those figures are not held, because
this environment's egress proxy refuses every `.gov.in` and a late fee written
from memory is a number a CA would pay. So `late_fee` returns a NAMED GAP
saying exactly which notification to read, the same shape as the state
professional-tax slabs and the ESIC reason codes. A CA fills the table once;
until they do, nothing wrong is shown.

RULE 88B IS THE PART THAT IS EASY TO GET WRONG, AND IT IS THE EXPENSIVE ONE

Interest under §50(1) is NOT charged on the gross output tax. Rule 88B(1) — the
proviso inserted by the Finance Act 2021 and made retrospective to 01-07-2017
by the Finance Act 2022 — charges it only on "that portion of the tax which is
paid by debiting the electronic cash ledger", where the supplies are declared
in a return furnished AFTER the due date and before any §73/§74 proceeding
begins. A taxpayer with enough credit in the ledger to cover the whole
liability owes NO interest on it however late the return is. Charging on the
gross would routinely demand several times what is due.

Rule 88B(2) is the other case — tax NOT declared in that return, found later —
and there the charge is on the whole tax from the date it fell due.

§50(3) with Rule 88B(3) is narrower still: 24% on input tax credit "wrongly
availed AND UTILISED", from the date of utilisation. Credit availed and never
utilised carries nothing, and this module refuses to guess the utilised portion
rather than charging the availed one.

TWO CONVENTIONS, BOTH STATED RATHER THAN ASSUMED

  • DAYS, not months. §50 charges "for the period for which the tax remains
    unpaid", and the portal counts days: due 20 July, paid 21 July is one day.
    That is `(paid - due).days`, and it is NOT the §201(1A) "month or part of a
    month" arithmetic — see domain/tds/interest.py, where getting it in months
    would be thirty times wrong in the other direction.
  • ROUNDED UP to the paise. Interest is a sum the taxpayer OWES, so
    understating it leaves them short and a residual demand follows; the ESI
    contribution rounds up for the same reason (see CLAUDE.md), while the GST
    discount floors because there understating the DISCOUNT cannot
    under-declare tax. Each takes the direction that is safe for whoever
    carries the liability.

⚠️ TWO THINGS ARE `[S]`-GRADED AND BOTH FAIL GENEROUS

  • The divisor is 365 even in a leap year, which is what the portal's own
    formula uses; if a leap year should divide by 366 this OVER-states by
    0.27%, which is the safe direction.
  • The COVID concessional rates (Notification 31/2020 and its siblings, which
    gave nil and 9% for specified 2020 periods) are NOT held. A period covered
    by them is charged at 18% here — over-stated, and named in the result's
    caveats rather than silently applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from domain.reporting.amount_words import indian_rupees

# §50(1), notified at 18% per annum by Notification 13/2017-Central Tax.
SECTION_50_1_RATE_BPS = 1800
# §50(3) as substituted by the Finance Act 2022 charges interest on input tax
# credit "wrongly availed and utilised" at "such rate not exceeding twenty-four
# per cent as may be notified". The CEILING is in the Act and is held here.
SECTION_50_3_CEILING_BPS = 2400
#
# ⚠️ THE NOTIFIED RATE IS 18%, `[S]`-GRADED, AND THIS IS THE SECOND CORRECTION.
#
# This module first stated 24%, on the strength of Notification 13/2017-Central
# Tax, which notified 24% against the ORIGINAL §50(3). It then refused to state
# any rate at all, because the Finance Act 2022 SUBSTITUTED §50(3) with
# retrospective effect from 01-07-2017 and the rate for the substituted
# sub-section was believed to be 18% — a THIRD of the charge apart, on a sum a
# CA pays over on a client's behalf, where over-stating takes money from
# somebody who does not owe it. A figure that might be a third too high is
# worse than a refusal naming the notifications to read, so it refused.
#
# The refusal is now lifted. The mechanism is:
#     * Finance Act 2022 **s.111** substituted §50(3) retrospectively from
#       01-07-2017;
#     * Finance Act 2022 **s.116 with the Sixth Schedule** retrospectively
#       amended the 28-06-2017 rate notifications from 24% to 18%;
#     * **Notification 9/2022-Central Tax, 05-07-2022** brought those
#       provisions into force.
#
# That corrects an earlier note in this repository which had 9/2022 itself
# notifying the rate. 9/2022 commenced the provisions; s.116 and the Sixth
# Schedule changed the figure.
#
# GRADE `[S]`, NOT `[P]`. Every `.gov.in` is refused at this environment's
# proxy, so this rests on several independent secondary sources that agree, and
# none of them argues for 24% after 2022. `VERIFIED` stays False and the figure
# is pinned exactly by a test, the discipline every other unfetchable statutory
# constant in this codebase follows.
#
# WHY IT IS NOW SAFE TO STATE WHERE IT WAS NOT BEFORE. The refusal existed
# because the DIRECTION of the doubt was unsafe. The evidence no longer
# supports the higher reading, so holding out keeps a working engine switched
# off over a doubt nothing argues for — and a refusal is not free either: a CA
# who gets no figure computes one by hand, and that is the outcome this module
# exists to replace. The Act's own 24% CEILING stays recorded above as the
# ceiling it is, so a later notification moving the rate has somewhere to land.
SECTION_50_3_NOTIFIED_RATE_BPS: Optional[int] = 1800
#: Where the 18% comes from, carried on every answer that uses it.
SECTION_50_3_RATE_SOURCE = (
    "Finance Act 2022 s.111 substituted s.50(3) retrospectively from "
    "01-07-2017; s.116 with the Sixth Schedule amended the 28-06-2017 rate "
    "notifications from 24% to 18%; Notification 9/2022-Central Tax "
    "(05-07-2022) brought them into force."
)
#: Corroborated across independent secondary sources, NOT read off the
#: notification — this environment's proxy refuses every .gov.in. Kept False so
#: the caveat travels with the figure rather than being remembered.
SECTION_50_3_RATE_VERIFIED = False
GAP_SECTION_50_3_RATE_NOT_HELD = "gst_section_50_3_rate_not_held"
# The portal's own divisor. See the leap-year caveat in the module docstring.
DAYS_IN_YEAR = 365

# The concessional-rate window nobody has transcribed. A return for a period
# inside it is charged at the full 18% and SAYS SO.
_COVID_RELIEF_FROM = date(2020, 2, 1)
_COVID_RELIEF_TO = date(2020, 8, 31)

GAP_LATE_FEE_RATES_NOT_HELD = "gst_late_fee_rates_not_held"


def _rupees(paise: int) -> str:
    return f"₹{indian_rupees(paise)}"


def _ceil_div(numerator: int, denominator: int) -> int:
    """Integer division rounding UP — see the module docstring on direction."""
    if denominator == 0:
        return 0
    return -(-numerator // denominator)


def days_late(due: date, paid: date) -> int:
    """Whole days of delay, never negative.

    `(paid - due).days`, which is what the portal counts: due 20 July and paid
    21 July is one day. Both are `date` objects, so there is no instant to be
    read back in the wrong zone — the trap the frontend's own day-count guard
    exists for.
    """
    return max(0, (paid - due).days)


@dataclass(frozen=True)
class InterestCharge:
    """One §50 charge, with the working a CA can check."""
    section: str
    base_paise: int
    rate_bps: int
    days: int
    interest_paise: int
    basis: str
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "section": self.section,
            "base_paise": self.base_paise,
            "rate_bps": self.rate_bps,
            "days": self.days,
            "interest_paise": self.interest_paise,
            "basis": self.basis,
            "caveats": self.caveats,
        }


def _charge(*, section: str, base_paise: int, rate_bps: int, days: int,
            basis: str, caveats: list[str]) -> InterestCharge:
    base = max(0, int(base_paise or 0))
    interest = _ceil_div(base * rate_bps * days, 10_000 * DAYS_IN_YEAR)
    return InterestCharge(section=section, base_paise=base, rate_bps=rate_bps,
                          days=days, interest_paise=interest, basis=basis,
                          caveats=caveats)


def interest_on_late_return(
    *,
    due_date: date,
    filed_on: date,
    cash_payable_paise: int,
    period_start: Optional[date] = None,
) -> InterestCharge:
    """§50(1) with Rule 88B(1) — on the CASH portion only.

    `cash_payable_paise` is what `gstr3b_computer` already computes as the
    challan figure: output tax less the credit the ledger can lawfully spend on
    it, plus reverse-charge tax, which §2(82) excludes from "output tax" so
    §49(4) can never pay it from credit. Passing the GROSS output tax here
    would charge interest a taxpayer with sufficient credit does not owe at
    all, which is the whole point of the proviso.
    """
    days = days_late(due_date, filed_on)
    caveats: list[str] = []
    if period_start and _COVID_RELIEF_FROM <= period_start <= _COVID_RELIEF_TO:
        caveats.append(
            "This period falls in the window the 2020 concessional-rate "
            "notifications covered (Notification 31/2020 and its siblings gave "
            "nil and 9% for specified months). Those rates are NOT held here, "
            "so 18% has been applied — the figure is an over-statement. Check "
            "the notification for this class of taxpayer and this month."
        )
    return _charge(
        section="50(1)", base_paise=cash_payable_paise,
        rate_bps=SECTION_50_1_RATE_BPS, days=days, caveats=caveats,
        basis=(
            "Section 50(1) with Rule 88B(1): where the supplies are declared in "
            "a return furnished after the due date, interest runs only on the "
            "portion of tax paid by debiting the electronic CASH ledger — not "
            "on the gross output tax. 18% per annum, notified by Notification "
            "13/2017-Central Tax."
        ),
    )


def interest_on_undeclared_tax(
    *,
    due_date: date,
    paid_on: date,
    tax_paise: int,
) -> InterestCharge:
    """§50(1) with Rule 88B(2) — the OTHER case, and the base is the whole tax.

    Rule 88B(1)'s cash-only relief reaches tax DECLARED in a return furnished
    late. Tax that was never declared and comes out of a §73/§74 proceeding
    gets no such relief: interest runs on the total, from the date it fell due.
    A caller that used the cash figure here would understate the charge.
    """
    return _charge(
        section="50(1)", base_paise=tax_paise,
        rate_bps=SECTION_50_1_RATE_BPS, days=days_late(due_date, paid_on),
        caveats=[],
        basis=(
            "Section 50(1) with Rule 88B(2): tax not declared in the return for "
            "the period bears interest on the WHOLE amount from the date it "
            "was due, with none of the cash-ledger relief a late-but-declared "
            "liability gets. 18% per annum."
        ),
    )


#: Notification 19/2022-Central Tax substituted the whole of Rule 37 with
#: effect from 01-10-2022, and sub-rule (3) — which stated the interest clock —
#: did not survive the substitution.
RULE_37_SUBSTITUTED_FROM = date(2022, 10, 1)

RULE_37_CLOCK_NOT_STATED = (
    "⚠️ Rule 37 no longer says when the interest clock STARTS. Until "
    "Notification 19/2022-Central Tax substituted the rule with effect from "
    "01-10-2022, sub-rule (3) ran it \"from the date of availing credit on "
    "such supplies till the date when the amount added to the output tax "
    "liability ... is paid\"; the substituted rule says only \"along with "
    "interest payable thereon under section 50\". Both readings are shown "
    "below — from the date the credit was availed, and from the day the 180 "
    "days expired — because picking one silently would understate or overstate "
    "a sum the client pays over. The RATE is not in doubt: §50(3) reaches "
    "credit wrongly availed AND utilised, which this is not — the credit was "
    "validly availed and has become repayable — so §50(1)'s 18% applies."
)


def interest_on_rule_37_reversal(
    *,
    reversal_paise: int,
    from_date: date,
    to_date: date,
    clock: str,
) -> InterestCharge:
    """§50(1) on a Rule 37 reversal, over a window the CALLER states.

    CGST Rule 37(1) with the second proviso to §16(2): where the recipient
    fails to pay the supplier within 180 days, they "shall pay an amount equal
    to the input tax credit availed in respect of such supply along with
    interest payable thereon under section 50".

    The rate is §50(1)'s 18% and that part is settled: §50(3) charges credit
    "wrongly availed AND UTILISED", and Rule 37 credit was validly availed —
    what changed is that the consideration went unpaid. The PERIOD is the open
    question, which is why this function takes it rather than deciding it; the
    caller shows both readings and names the substitution.
    """
    return _charge(
        section="50(1)", base_paise=reversal_paise,
        rate_bps=SECTION_50_1_RATE_BPS,
        days=days_late(from_date, to_date), caveats=[],
        basis=(
            f"Section 50(1) at 18% per annum (Notification 13/2017-Central "
            f"Tax), on the credit CGST Rule 37(1) requires to be paid back, "
            f"run {clock}."
        ),
    )


def interest_on_wrongly_availed_credit(
    *,
    utilised_on: Optional[date],
    reversed_on: Optional[date],
    utilised_paise: Optional[int],
    availed_paise: int = 0,
) -> InterestCharge | dict:
    """§50(3) with Rule 88B(3) — on the credit UTILISED, never the availed.

    THE RATE IS NOW HELD at 18%, `[S]`-graded — see
    SECTION_50_3_NOTIFIED_RATE_BPS above for the mechanism and why the earlier
    refusal was lifted. Every charge carries the source as a caveat rather than
    presenting the figure as read off the notification, because it was not.

    ONE REFUSAL REMAINS, and it is about the FACTS rather than the rate. Credit
    wrongly availed and NEVER UTILISED bears no interest at all — Rule
    88B(3)'s explanation is about the balance in the electronic credit ledger
    falling below the wrongly availed amount — so substituting the availed
    figure would charge a taxpayer who owes nothing. That one is not lifted by
    any notification; it is what the sub-section charges.
    """
    if SECTION_50_3_NOTIFIED_RATE_BPS is None:
        # Unreachable today and deliberately kept: the constant is typed
        # Optional so a later reader who finds the 18% wrong can set it back to
        # None and get a refusal rather than a wrong figure, which is the
        # behaviour this module had for good reason.
        return {
            "refused": True,
            "section": "50(3)",
            "gap": GAP_SECTION_50_3_RATE_NOT_HELD,
            "ceiling_bps": SECTION_50_3_CEILING_BPS,
            "reason": (
                "The rate notified for §50(3) is not held in this product. The "
                "sub-section's own ceiling is 24% (\"not exceeding twenty-four "
                "per cent\"), Notification 13/2017-Central Tax notified 24% "
                "against the ORIGINAL §50(3), and the Finance Act 2022 "
                "substituted the sub-section retrospectively from 01-07-2017 — "
                "for which Notification 09/2022-Central Tax appears to notify "
                "18%. A third of the charge separates the two readings, and "
                "this is a sum paid over on the client's behalf, so no figure "
                "is guessed. Read the notification in force for the period and "
                "record it in SECTION_50_3_NOTIFIED_RATE_BPS."
            ),
        }
    missing = []
    if utilised_paise is None:
        missing.append("how much of the credit was actually utilised")
    if utilised_on is None:
        missing.append("the date it was utilised")
    if reversed_on is None:
        missing.append("the date it was reversed or paid back")
    if missing:
        return {
            "refused": True,
            "section": "50(3)",
            "reason": (
                "Section 50(3) charges interest on input tax credit wrongly availed "
                "AND UTILISED, from the date of utilisation to the date of "
                "reversal (Rule 88B(3)). Credit availed and never utilised "
                "bears no interest, so this is not computed from the availed "
                f"amount of {_rupees(availed_paise)}. Record " + ", ".join(missing) + "."
            ),
        }
    return _charge(
        section="50(3)", base_paise=int(utilised_paise or 0),
        rate_bps=SECTION_50_3_NOTIFIED_RATE_BPS,
        days=days_late(utilised_on, reversed_on),
        # The caveat travels ON the charge rather than living in a comment: a
        # CA is about to pay this over, and "18%" presented bare reads as a
        # figure somebody read off a notification. Nobody here did.
        caveats=[
            f"The §50(3) rate of "
            f"{SECTION_50_3_NOTIFIED_RATE_BPS / 100:g}% is corroborated across "
            f"independent secondary sources, not read off the notification "
            f"(egress to .gov.in is refused in this environment). "
            f"{SECTION_50_3_RATE_SOURCE} The sub-section's own ceiling is "
            f"{SECTION_50_3_CEILING_BPS / 100:g}%; confirm against the "
            f"notification in force for the period before paying."
        ],
        basis=(
            f"Section 50(3) with Rule 88B(3): "
            f"{SECTION_50_3_NOTIFIED_RATE_BPS / 100:g}% per annum on input tax "
            f"credit wrongly availed AND utilised, running from the date of "
            f"utilisation to the date of reversal or payment."
        ),
    )


# ── The late fee ─────────────────────────────────────────────────────────────
#
# ⚠️ EVERY FIGURE BELOW IS `[S]`-GRADED, AND THIS TABLE WAS EMPTY UNTIL NOW.
#
# The refusal that stood here was right at the time and its ground was MEMORY:
# "a late fee written from memory is a number a CA would pay over". §47(1) is
# ₹100 a day per Act capped at ₹5,000 and no registered person has paid that
# since 2018, so the statutory figure is four times what is notified.
#
# What changed is the evidence, not the caution. The figures below are
# corroborated across independent secondary sources that agree with each other
# AND with what this module had already recorded as unverified belief —
# Notification **19/2021-Central Tax, 01-06-2021** (GSTR-3B) and **20/2021-CT**
# (GSTR-1), on the 43rd Council's recommendation. Still not read off the
# notification: this environment's proxy refuses every `.gov.in`. So
# `verified=False` travels on every rate, every answer carries the source, and
# a test pins each number exactly.
#
# WHY STATE THEM AT ALL, HAVING REFUSED. A CA who gets nothing computes the fee
# by hand from the same secondary sources, with no caveat attached and no test
# pinning it. And the PORTAL is authoritative here in a way it is not for
# §50(3) interest — the fee is computed by GSTN at filing, so this figure is a
# planning estimate the CA checks against the portal, not a sum they pay over
# on this product's say-so.
#
# ONLY FROM FY 2021-22. Notifications 4/2018 and 76/2018 govern earlier
# periods, with different caps and no turnover bands, and those were not
# corroborated to the same standard — so an earlier year still REFUSES rather
# than being charged at a rate that was not in force. The fork shape this
# codebase applies to the TDS vocabulary and the capital-gains rates.
@dataclass(frozen=True)
class TurnoverCap:
    """One band of Notification 19/2021's cap ladder.

    `upto_paise` is the band's upper bound, INCLUSIVE, and `None` means the
    band has no upper bound. Written as a ladder rather than as three named
    constants because the bands are the notification's own structure and a
    later one that moves a boundary should move a number here, not add a branch.
    """
    upto_paise: Optional[int]
    cap_paise: int


@dataclass(frozen=True)
class LateFeeRate:
    """What one day of delay costs, and where the ceiling is.

    Every figure is the COMBINED one (CGST + SGST), the way a portal shows it —
    §47 sets ₹100 a day capped at ₹5,000 under EACH Act, and every notification
    since has reduced both halves together.

    THE CAP DEPENDS ON THE TAXPAYER, THE PER-DAY RATE DOES NOT. That asymmetry
    is the whole reason this is not one number: ₹50 a day is charged to
    everyone, and the ceiling is ₹2,000, ₹5,000 or ₹10,000 by aggregate
    turnover. A nil return is its own rate AND its own cap, and is not banded.
    """
    per_day_paise: int
    nil_return_per_day_paise: int
    nil_cap_paise: int
    turnover_caps: tuple[TurnoverCap, ...]
    source: str
    #: False everywhere, and not a field anyone should set True without having
    #: read the notification itself.
    verified: bool = False

    def cap_for(self, aggregate_turnover_paise: Optional[int]) -> int:
        """The ceiling for this taxpayer, or the LOWEST band where none is known.

        An unrecorded turnover takes the SMALLEST cap deliberately. The three
        differ by 5x, so neither direction is harmless — but the portal computes
        the fee itself at filing, so an understatement is corrected there, while
        an overstatement is this product telling a CA to budget for money their
        client does not owe. `late_fee` names the assumption on the answer
        rather than leaving it to be inferred from the number.
        """
        if aggregate_turnover_paise is None:
            return min(c.cap_paise for c in self.turnover_caps)
        for band in self.turnover_caps:
            if band.upto_paise is None or aggregate_turnover_paise <= band.upto_paise:
                return band.cap_paise
        return self.turnover_caps[-1].cap_paise


_CRORE = 1_00_00_000_00  # one crore rupees, in paise

#: Notification 19/2021-CT (GSTR-3B) and 20/2021-CT (GSTR-1), from the June 2021
#: tax period. Identical ladders; both are held so neither is inferred from the
#: other.
_NOTIFIED_2021 = dict(
    per_day_paise=50_00,             # ₹25 CGST + ₹25 SGST
    nil_return_per_day_paise=20_00,  # ₹10 + ₹10
    nil_cap_paise=500_00,
    turnover_caps=(
        TurnoverCap(upto_paise=int(1.5 * _CRORE), cap_paise=2_000_00),
        TurnoverCap(upto_paise=5 * _CRORE,        cap_paise=5_000_00),
        TurnoverCap(upto_paise=None,              cap_paise=10_000_00),
    ),
)

LATE_FEE_RATES: dict[tuple[str, str], LateFeeRate] = {
    (rt, fy): LateFeeRate(
        **_NOTIFIED_2021,
        source=(
            f"Notification {'19' if rt == 'gstr3b' else '20'}/2021-Central Tax "
            f"(01-06-2021), 43rd GST Council. Corroborated across independent "
            f"secondary sources, not read off the notification."
        ),
    )
    for rt in ("gstr3b", "gstr1")
    for fy in ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26", "2026-27")
}

#: The first year the 2021 ladder is held for. An earlier period is REFUSED
#: rather than charged at a rate that was not in force — 4/2018 and 76/2018
#: govern those and carry different caps with no turnover bands.
LATE_FEE_FIRST_HELD_FY = "2021-22"

# The statutory figures, recorded so nobody has to look them up to know what
# the notifications REDUCED. Deliberately NOT used as a fallback: charging
# ₹200 a day where ₹50 is notified is four times the fee, on a figure a CA
# would pay.
SECTION_47_1_STATUTORY_PER_DAY_PAISE = 200_00
SECTION_47_1_STATUTORY_CAP_PAISE = 10_000_00


@dataclass(frozen=True)
class LateFee:
    return_type: str
    financial_year: str
    days: int
    is_nil_return: bool
    fee_paise: int
    capped: bool
    source: str
    #: The ceiling actually applied, so a reader can see WHICH band was used
    #: rather than inferring it from a capped figure.
    cap_paise: int = 0
    #: True where no aggregate turnover was supplied and the lowest band was
    #: assumed. The fee may be understated for a larger taxpayer, and the
    #: caveat says so — a capped figure with no such flag reads as the answer.
    turnover_band_assumed: bool = False
    #: Never empty. Every figure here is corroborated rather than read off the
    #: notification, and that travels with the number.
    caveats: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "return_type": self.return_type,
            "financial_year": self.financial_year,
            "days": self.days,
            "is_nil_return": self.is_nil_return,
            "fee_paise": self.fee_paise,
            "capped": self.capped,
            "cap_paise": self.cap_paise,
            "turnover_band_assumed": self.turnover_band_assumed,
            "caveats": list(self.caveats),
            "source": self.source,
        }


def late_fee(
    *,
    return_type: str,
    financial_year: str,
    due_date: date,
    filed_on: date,
    is_nil_return: bool = False,
    aggregate_turnover_paise: Optional[int] = None,
) -> LateFee | dict:
    """§47 — the notified fee where it is held, a named refusal where it is not.

    `aggregate_turnover_paise` is CGST §2(6) aggregate turnover, which decides
    the CAP and not the per-day rate. It is optional, and `None` is a real third
    state rather than "nil": the lowest band is assumed and the answer SAYS it
    was assumed. `client_gst_turnover` (migration 401) is where a caller gets
    it — the same store the HSN-digit requirement reads.

    AN EARLIER YEAR STILL REFUSES. Only the 2021 ladder is held; Notifications
    4/2018 and 76/2018 govern periods before it with different caps and no
    turnover bands, so charging those years at the 2021 figures would be a rate
    that was not in force.
    """
    days = days_late(due_date, filed_on)
    key = (return_type.strip().lower(), financial_year.strip())
    rate = LATE_FEE_RATES.get(key)
    if rate is None:
        return {
            "refused": True,
            "code": GAP_LATE_FEE_RATES_NOT_HELD,
            "return_type": return_type,
            "financial_year": financial_year,
            "days": days,
            "reason": (
                f"This return is {days} day(s) late and the section 47 late fee "
                f"for {return_type.upper()} in FY {financial_year} is not "
                f"recorded. The notified figures are held from FY "
                f"{LATE_FEE_FIRST_HELD_FY} (Notifications 19/2021 and 20/2021); "
                f"an earlier period is governed by Notifications 4/2018 and "
                f"76/2018, which carry different caps and no turnover bands. "
                f"The statutory figure is ₹100 a day under each Act capped at "
                f"₹5,000 (₹200 and ₹10,000 combined) and is deliberately NOT "
                f"used as a fallback, because charging four times the notified "
                f"fee is a number somebody would pay."
            ),
        }

    per_day = rate.nil_return_per_day_paise if is_nil_return else rate.per_day_paise
    # A nil return has its own cap and is NOT banded by turnover — a taxpayer
    # with nothing to declare has the same ₹500 ceiling whatever their size.
    cap = rate.nil_cap_paise if is_nil_return else rate.cap_for(aggregate_turnover_paise)
    raw = per_day * days
    fee = min(raw, cap)

    caveats = [
        f"Figures from {rate.source} They are corroborated across independent "
        f"secondary sources, not read off the notification (egress to .gov.in "
        f"is refused in this environment). The portal computes the fee itself "
        f"at filing — check this against it before paying."
    ]
    assumed = not is_nil_return and aggregate_turnover_paise is None
    if assumed:
        caveats.append(
            "No aggregate turnover is recorded for this client, so the LOWEST "
            "cap (₹2,000) was assumed. The ceiling is ₹5,000 above ₹1.5 crore "
            "and ₹10,000 above ₹5 crore, so this fee may be understated for a "
            "larger taxpayer. Record the turnover to remove the assumption."
        )

    return LateFee(return_type=return_type, financial_year=financial_year,
                   days=days, is_nil_return=is_nil_return, fee_paise=fee,
                   capped=fee < raw, cap_paise=cap,
                   turnover_band_assumed=assumed, caveats=tuple(caveats),
                   source=rate.source)
