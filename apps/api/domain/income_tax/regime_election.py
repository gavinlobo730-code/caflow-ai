"""
Choosing between the tax regimes — IT Act 1961, §115BAC(6) and Rule 21AGA.

Since AY 2024-25 the §115BAC regime is the DEFAULT. A taxpayer who wants the
old regime must opt out, and how they do that — and whether they may ever do it
again — depends entirely on one thing: whether they have income from business
or profession.

§115BAC(6) has two clauses, and they are not variations of one rule.

    CLAUSE (i) — a person WITH income from business or profession.
        The option is exercised in FORM 10-IEA (Rule 21AGA), on or before the
        due date under §139(1). Filed late, or not filed, the new regime
        applies whatever the return says.

        It "once exercised for any previous year can be withdrawn only once for
        a previous year other than the year in which it was exercised and
        thereafter, the person shall never be eligible to exercise the option
        under this sub-section" — except where they cease to have business or
        professional income, when clause (ii) becomes available instead.

        So a business taxpayer has, in effect, one return journey. Opting out,
        then going back to the new regime, closes the old regime to them for
        the rest of their working life.

    CLAUSE (ii) — a person WITHOUT such income.
        The option is exercised in the RETURN itself under §139(1). No form, no
        deadline beyond the return's own, and no lock-out: they may choose
        afresh every year.

WHY THIS IS MODELLED RATHER THAN LEFT TO THE CA

The consequence of getting clause (i) wrong is not a rounding difference. A
missed Form 10-IEA taxes a client on the new regime for a year they planned
around the old one, and it cannot be cured after the due date. A withdrawal
made without realising it is final closes an option worth lakhs over a career.
Neither failure is visible in the return — it computes cleanly either way.

WHAT THIS DOES NOT KNOW

Prior-year elections. The product holds no filing history, so the lock-out
cannot be derived; it is an INPUT (`prior_elections`) the CA supplies, and when
nothing is supplied the result says the history is unknown rather than assuming
the option is available. Assuming availability is the dangerous direction: it
would tell a CA the old regime is open when the client spent it years ago.

All monetary values elsewhere in this package are integer paise; this module
deals in dates and elections only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

# What a taxpayer did in one earlier year, as the CA reports it.
#   "opted_out"  — exercised the clause (i) option and used the old regime
#   "withdrew"   — withdrew that option and returned to the new regime
ElectionAction = Literal["opted_out", "withdrew"]

# How the election must be made.
ElectionRoute = Literal["form_10iea", "in_the_return"]


@dataclass(frozen=True)
class PriorElection:
    fy: str
    action: ElectionAction


@dataclass(frozen=True)
class RegimeElectionResult:
    regime: Literal["old", "new"]
    route: ElectionRoute
    form_10iea_required: bool
    due_date: Optional[date]
    # False when the old regime cannot be chosen at all — the option is spent,
    # or the form was filed late.
    election_is_available: bool
    # True when the product cannot tell, because prior-year history was not
    # supplied. Distinct from "unavailable": one is a fact, the other is a gap.
    history_unknown: bool
    reasons: tuple[str, ...]


def election_route(has_business_income: bool) -> ElectionRoute:
    """Which limb of §115BAC(6) applies. The whole shape of the election —
    form, deadline, and whether it can ever be made again — follows from this
    one fact."""
    return "form_10iea" if has_business_income else "in_the_return"


def form_10iea_due_date(
    financial_year_end: int,
    *,
    is_audit: bool = False,
    has_transfer_pricing_report: bool = False,
) -> date:
    """Rule 21AGA ties Form 10-IEA to the §139(1) due date, so this defers to
    services.compliance_engine.itr_due_date rather than restating it.

    CLAUDE.md names compliance_engine as the single source for every due date
    in the product; a second copy here would be the thing that drifts when a
    year's dates are extended by circular.
    """
    from services.compliance_engine import itr_due_date
    return itr_due_date(financial_year_end, is_audit=is_audit,
                        has_transfer_pricing_report=has_transfer_pricing_report)


def _option_is_spent(prior: list[PriorElection]) -> bool:
    """Whether clause (i)'s single withdrawal has already been used.

    The proviso bars a further election only after a WITHDRAWAL. Opting out
    repeatedly across years is not a withdrawal — the option stays exercised —
    so only "withdrew" consumes it.
    """
    return any(p.action == "withdrew" for p in prior)


def evaluate_election(
    *,
    wants_old_regime: bool,
    has_business_income: bool,
    financial_year_end: int,
    form_10iea_filed_on: Optional[date] = None,
    is_audit: bool = False,
    has_transfer_pricing_report: bool = False,
    prior_elections: Optional[list[PriorElection]] = None,
    business_income_ceased: bool = False,
) -> RegimeElectionResult:
    """What regime actually applies, and what the CA must do to get there.

    `form_10iea_filed_on` is the date the form was ACTUALLY filed; None means
    it has not been. A date after the due date does not merely warn — under
    clause (i) the option is exercised by filing on or before that date, so a
    late form is no election and the new regime applies.
    """
    reasons: list[str] = []
    route = election_route(has_business_income)
    due = (form_10iea_due_date(financial_year_end, is_audit=is_audit,
                               has_transfer_pricing_report=has_transfer_pricing_report)
           if route == "form_10iea" else None)

    # The default. Everything below is about whether it can be displaced.
    if not wants_old_regime:
        reasons.append(
            "The §115BAC regime is the default since AY 2024-25; no election "
            "is needed to remain in it."
        )
        return RegimeElectionResult(
            regime="new", route=route, form_10iea_required=False,
            due_date=due, election_is_available=True, history_unknown=False,
            reasons=tuple(reasons),
        )

    # ── Clause (ii): no business income — choose in the return, every year ───
    if route == "in_the_return":
        reasons.append(
            "With no income from business or profession, §115BAC(6)(ii) allows "
            "the old regime to be chosen in the return itself under §139(1). "
            "Form 10-IEA is not required, and the choice may be made afresh "
            "each year."
        )
        return RegimeElectionResult(
            regime="old", route=route, form_10iea_required=False,
            due_date=None, election_is_available=True, history_unknown=False,
            reasons=tuple(reasons),
        )

    # ── Clause (i): business income — Form 10-IEA, once, on time ────────────
    prior = prior_elections if prior_elections is not None else []
    history_unknown = prior_elections is None

    if history_unknown:
        reasons.append(
            "Prior-year elections were not supplied, so whether this client "
            "has already withdrawn the §115BAC(6) option — which would close "
            "the old regime to them permanently — cannot be determined here. "
            "Confirm before relying on this."
        )

    spent = _option_is_spent(prior)
    if spent and not business_income_ceased:
        reasons.append(
            "The §115BAC(6) option has already been withdrawn once. The "
            "proviso bars exercising it again, so the old regime is not "
            "available while the client has income from business or "
            "profession."
        )
        return RegimeElectionResult(
            regime="new", route=route, form_10iea_required=False,
            due_date=due, election_is_available=False,
            history_unknown=history_unknown, reasons=tuple(reasons),
        )
    if spent and business_income_ceased:
        reasons.append(
            "The option was withdrawn once, but the client no longer has "
            "income from business or profession — the proviso's exception "
            "applies and the choice reverts to §115BAC(6)(ii), made in the "
            "return each year."
        )
        return RegimeElectionResult(
            regime="old", route="in_the_return", form_10iea_required=False,
            due_date=None, election_is_available=True,
            history_unknown=history_unknown, reasons=tuple(reasons),
        )

    if form_10iea_filed_on is None:
        reasons.append(
            f"Form 10-IEA has not been filed. Under §115BAC(6)(i) read with "
            f"Rule 21AGA it must be filed on or before {due.isoformat()} for "
            f"the old regime to apply; without it the new regime applies "
            f"whatever the return says."
        )
        return RegimeElectionResult(
            regime="new", route=route, form_10iea_required=True,
            due_date=due, election_is_available=True,
            history_unknown=history_unknown, reasons=tuple(reasons),
        )

    if form_10iea_filed_on > due:
        reasons.append(
            f"Form 10-IEA was filed on {form_10iea_filed_on.isoformat()}, "
            f"after the §139(1) due date of {due.isoformat()}. The option is "
            f"exercised by filing on or before that date, so this is no "
            f"election and the new regime applies. It cannot be cured now."
        )
        return RegimeElectionResult(
            regime="new", route=route, form_10iea_required=True,
            due_date=due, election_is_available=False,
            history_unknown=history_unknown, reasons=tuple(reasons),
        )

    reasons.append(
        f"Form 10-IEA filed on {form_10iea_filed_on.isoformat()}, on or before "
        f"the due date of {due.isoformat()}, so the old regime applies."
    )
    reasons.append(
        "Note for later years: this option may be withdrawn only ONCE, and "
        "after that withdrawal the old regime is closed permanently while the "
        "client has business or professional income."
    )
    return RegimeElectionResult(
        regime="old", route=route, form_10iea_required=True,
        due_date=due, election_is_available=True,
        history_unknown=history_unknown, reasons=tuple(reasons),
    )
