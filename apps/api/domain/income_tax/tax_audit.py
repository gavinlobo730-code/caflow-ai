"""
IT Act 1961, §44AB — whether a tax audit applies, and on which limb.

WHY THIS MODULE EXISTS
    The Tax Audit tracker decided this in the browser, from the turnover
    figure alone:

        turnover >= 1 crore  -> "tax audit mandatory (business)"
        turnover >= 50 lakh  -> "tax audit mandatory (profession)"
        otherwise            -> "below threshold"

    That reads the NATURE OF THE ACTIVITY off the AMOUNT, which is backwards.
    §44AB(a) reaches a person carrying on BUSINESS and §44AB(b) a person
    carrying on a PROFESSION; they are different clauses with different
    figures, and which one applies is a fact about the client, not about how
    much they turned over. So a trader with 60 lakh of turnover — who needs no
    audit at all under (a) — was told "tax audit mandatory (profession)", and
    a professional with 1.2 crore of gross receipts was told they were a
    business. Both statements are wrong, and one of them is wrong in the
    direction that matters: §271B charges 0.5% of turnover, capped at
    1,50,000, for failing to get the accounts audited.

    It also silently ignored the proviso to §44AB(a). Its own module comment
    said so — "that cash-percentage test is not modeled here; callers always
    apply the base threshold" — so a client with 4 crore of turnover and 2% of
    it in cash was told an audit was mandatory when the proviso lifts the
    figure to 10 crore.

WHAT IS DECIDED AND WHAT IS REFUSED
    Clauses (a) and (b) are DECIDED, because the CA supplies the two figures
    they turn on. Clauses (c), (d) and (e) are NOT tested and are NAMED: each
    of them compares the profit actually DECLARED against a figure deemed by
    §44AE / §44BB / §44BBB / §44ADA / §44AD(4), and nothing in a turnover box
    says what was declared. Naming them is the point — a bare "no audit
    required" would read as an answer to the whole section.

    The proviso's 10 crore limb is applied only where the caller states BOTH
    cash aggregates and the payments denominator. Absent any of them the base
    figure stands and the answer says which fact would move it. That direction
    is deliberate: assuming the cash test is met is the assumption that
    produces a missed audit.

THE FIGURES ARE `[S]`-GRADED
    Egress is refused at this environment's proxy, so none of them was read
    off the Act or a Finance Act. They are written from knowledge and
    reconciled against `domain/income_tax/presumptive.py`, which holds the
    same 5% cash test for §44AD/§44ADA's enhanced limits. Every year is
    therefore `verified=False` — the same contract as
    `domain/tds/section_195_rates.py`, which is reconciled rather than
    confirmed line by line.

    One reconciliation is worth stating because it is the easy mistake: the
    Finance Act 2023 raised §44ADA's PRESUMPTIVE receipts limit from 50 lakh
    to 75 lakh, which `presumptive.py` holds. It did NOT move §44AB(b)'s
    AUDIT threshold, which is a different section.
    `apps/web/lib/income-tax/taxAuditThresholds.ts` said otherwise in its own
    comment; this module is the authority and that file is deleted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CRORE_PAISE = 1_00_00_000_00
LAKH_PAISE = 1_00_000_00

#: The activity a §44AB test is run against. A client may carry on both, in
#: which case both clauses are tested separately and either can trigger it.
BUSINESS = "business"
PROFESSION = "profession"
NATURES = (BUSINESS, PROFESSION)


@dataclass(frozen=True)
class TaxAuditThresholds:
    """The §44AB figures for one financial year."""
    fy: str
    verified: bool
    #: §44AB(a) — sales, turnover or gross receipts of a BUSINESS.
    business_limit_paise: int
    #: The proviso to §44AB(a) — the same clause read with "ten crore rupees"
    #: where the cash test below is met on BOTH sides.
    business_enhanced_limit_paise: int
    #: §44AB(b) — gross receipts of a PROFESSION. No cash-based enhancement:
    #: the proviso sits on clause (a) and names clause (a)'s words.
    profession_limit_paise: int
    #: The proviso's ceiling, as a percentage of the respective aggregate.
    enhanced_limit_cash_percent: int


_FY_2025_26 = TaxAuditThresholds(
    fy="2025-26",
    verified=False,
    business_limit_paise=1 * CRORE_PAISE,
    business_enhanced_limit_paise=10 * CRORE_PAISE,
    profession_limit_paise=50 * LAKH_PAISE,
    enhanced_limit_cash_percent=5,
)

# Carried forward, not guessed — the same convention as presumptive.py.
_FY_2026_27 = TaxAuditThresholds(**{**_FY_2025_26.__dict__, "fy": "2026-27"})

THRESHOLDS_BY_FY: dict[str, TaxAuditThresholds] = {
    "2025-26": _FY_2025_26,
    "2026-27": _FY_2026_27,
}

#: No year has been confirmed against a Finance Act — see the module docstring.
#: Named rather than omitted so the annual sweep in CLAUDE.md has something to
#: move once somebody reads one.
LATEST_VERIFIED_FY: Optional[str] = None

_FALLBACK_FY = "2025-26"


def thresholds_for(fy: Optional[str] = None) -> TaxAuditThresholds:
    """Thresholds for `fy`, falling back to the earliest seeded year.

    The fallback carries the same hazard every registry in this codebase
    carries and CLAUDE.md records: a year that is not held comes back with
    another year's figures and no warning. `answer()` states the FY it used
    and caveats an unheld year, so the warning travels with the answer rather
    than living only here.
    """
    from domain.income_tax.statutory_rates import current_fy
    fy = fy or current_fy()
    return THRESHOLDS_BY_FY.get(fy, THRESHOLDS_BY_FY[_FALLBACK_FY])


#: The limbs this module does not test, and what each would need. Emitted with
#: every answer, including a "not required" one — §44AB is not exhausted by
#: clauses (a) and (b), and an answer that reads as if it were is the one a CA
#: would rely on.
LIMBS_NOT_TESTED: tuple[str, ...] = (
    "§44AB(c) — profits claimed LOWER than the figure deemed by §44AE, §44BB "
    "or §44BBB. Needs the profit actually declared, which no turnover figure "
    "carries.",
    "§44AB(d) — profits claimed lower than §44ADA's deemed 50% AND total "
    "income above the basic exemption limit. Needs both figures.",
    "§44AB(e) — §44AD(4) applies (the scheme was opted out of within five "
    "years) AND total income is above the basic exemption limit. Needs the "
    "client's §44AD history.",
)


@dataclass(frozen=True)
class TaxAuditAnswer:
    """Whether §44AB requires an audit, and the whole reasoning."""
    financial_year: str
    #: Whether the clause tested requires an audit on the facts stated.
    required: bool
    #: The clause tested — "44AB(a)" or "44AB(b)".
    clause: str
    #: The figure the turnover was measured against, in paise.
    threshold_applied_paise: int
    #: Whether the proviso's higher figure was the one applied.
    enhanced_limit_applied: bool
    #: One sentence stating the decision and why.
    basis: str
    #: Everything the CA must still confirm before relying on the answer.
    caveats: tuple[str, ...]
    #: The limbs of §44AB this module does not reach.
    limbs_not_tested: tuple[str, ...]
    #: Which report form applies, where an audit is required.
    form_type: Optional[str]

    def to_dict(self) -> dict:
        return {
            "financial_year": self.financial_year,
            "required": self.required,
            "clause": self.clause,
            "threshold_applied_paise": self.threshold_applied_paise,
            "enhanced_limit_applied": self.enhanced_limit_applied,
            "basis": self.basis,
            "caveats": list(self.caveats),
            "limbs_not_tested": list(self.limbs_not_tested),
            "form_type": self.form_type,
        }


def _within_cash_ceiling(cash_paise: int, total_paise: int, percent: int) -> bool:
    """Whether `cash_paise` is within `percent` of `total_paise`.

    Cross-multiplied rather than divided, for the reason presumptive.py gives:
    a turnover of 10,00,00,000 with exactly 50,00,000 in cash is 5.000% and
    must qualify, and a percentage computed by division can round it out.
    """
    if total_paise <= 0:
        return True
    return cash_paise * 100 <= total_paise * percent


def _rupees(paise: int) -> str:
    """Indian-grouped rupees, for a sentence a CA reads."""
    from domain.reporting.amount_words import indian_rupees
    return f"₹{indian_rupees(paise)}"


def answer(
    *,
    nature: str,
    turnover_paise: int,
    financial_year: Optional[str] = None,
    cash_receipts_paise: Optional[int] = None,
    cash_payments_paise: Optional[int] = None,
    total_payments_paise: Optional[int] = None,
    is_company: bool = False,
) -> TaxAuditAnswer:
    """Decide §44AB(a) or (b) on the facts stated.

    `nature` is the ACTIVITY — "business" or "profession" — and is required.
    It is never inferred from `turnover_paise`; inferring it is the defect
    this module replaces.

    The proviso to §44AB(a) needs FOUR figures, not two: cash receipts against
    total receipts, and cash payments against total payments. `turnover_paise`
    serves as the receipts denominator (the clause's own words are "amounts
    received including amount received for sales, turnover or gross
    receipts"), but the payments side has its own denominator and there is no
    way to derive it from turnover. Where `total_payments_paise` is absent the
    proviso is NOT applied and the answer says so.
    """
    n = (nature or "").strip().lower()
    if n not in NATURES:
        raise ValueError(
            f"nature must be one of {NATURES}; got {nature!r}. §44AB(a) and (b) "
            f"are different clauses and which applies is a fact about the "
            f"client, not about the turnover."
        )
    if turnover_paise < 0:
        raise ValueError("turnover_paise cannot be negative")

    t = thresholds_for(financial_year)
    caveats: list[str] = []
    if not t.verified:
        caveats.append(
            f"The FY {t.fy} §44AB figures in this product have not been confirmed "
            f"against that year's Finance Act. Confirm the limits before relying "
            f"on a borderline answer."
        )
    if financial_year and financial_year not in THRESHOLDS_BY_FY:
        caveats.append(
            f"No §44AB figures are held for FY {financial_year}; FY {t.fy}'s were "
            f"used. Add the year before filing on it."
        )

    if n == PROFESSION:
        clause = "44AB(b)"
        limit = t.profession_limit_paise
        enhanced = False
        caveats.append(
            "§44AB(b) has no cash-based higher limit. The 75 lakh figure that "
            "appears alongside it is §44ADA's PRESUMPTIVE receipts limit "
            "(Finance Act 2023), which is a different section and does not "
            "move the audit threshold."
        )
    else:
        clause = "44AB(a)"
        limit = t.business_limit_paise
        enhanced = False
        # Only worth testing the proviso where the base limit is exceeded;
        # below it the clause does not charge either way, and a caveat about
        # a limb that changes nothing is noise on the answer.
        if turnover_paise > t.business_limit_paise:
            missing = []
            if cash_receipts_paise is None:
                missing.append("cash receipts")
            if cash_payments_paise is None:
                missing.append("cash payments")
            if total_payments_paise is None:
                missing.append("total payments")
            if missing:
                caveats.append(
                    f"The proviso to §44AB(a) reads the clause as "
                    f"{_rupees(t.business_enhanced_limit_paise)} where cash "
                    f"receipts AND cash payments are each within "
                    f"{t.enhanced_limit_cash_percent}% of their own aggregate. "
                    f"It was NOT applied: {', '.join(missing)} not stated. The "
                    f"base figure is the safe direction — assuming the cash "
                    f"test is met is what produces a missed audit and §271B."
                )
            else:
                receipts_ok = _within_cash_ceiling(
                    int(cash_receipts_paise), turnover_paise,
                    t.enhanced_limit_cash_percent)
                payments_ok = _within_cash_ceiling(
                    int(cash_payments_paise), int(total_payments_paise),
                    t.enhanced_limit_cash_percent)
                if receipts_ok and payments_ok:
                    limit = t.business_enhanced_limit_paise
                    enhanced = True
                    caveats.append(
                        f"The proviso to §44AB(a) was applied: cash receipts and "
                        f"cash payments are each within "
                        f"{t.enhanced_limit_cash_percent}% of their own "
                        f"aggregate, so the clause reads "
                        f"{_rupees(t.business_enhanced_limit_paise)}. A payment "
                        f"or receipt by a cheque or bank draft that is NOT "
                        f"account payee counts as cash for this test — confirm "
                        f"both figures were computed on that basis."
                    )
                else:
                    failed = []
                    if not receipts_ok:
                        failed.append("cash receipts")
                    if not payments_ok:
                        failed.append("cash payments")
                    caveats.append(
                        f"The proviso to §44AB(a) does not apply: "
                        f"{' and '.join(failed)} exceed "
                        f"{t.enhanced_limit_cash_percent}% of the respective "
                        f"aggregate, so the clause keeps its "
                        f"{_rupees(t.business_limit_paise)} figure. The test is "
                        f"conjunctive — both sides must be within the ceiling."
                    )

    # §44AB charges where the figure EXCEEDS the limit, not where it reaches
    # it: "exceed one crore rupees". A turnover of exactly the limit is out.
    required = turnover_paise > limit
    label = "gross receipts" if n == PROFESSION else "sales, turnover or gross receipts"

    if required:
        basis = (
            f"§{clause} — {label} of {_rupees(turnover_paise)} exceed "
            f"{_rupees(limit)}"
            + (" (the proviso's higher figure)" if enhanced else "")
            + f" for FY {t.fy}, so the accounts are required to be audited."
        )
        # The proviso to §44AB: where the accounts are already required to be
        # audited under any other law, that audit plus a FURTHER report by an
        # accountant is sufficient compliance. The further report is Form 3CA;
        # a person audited under no other law files 3CB. 3CD is the statement
        # of particulars either way.
        form_type = "3CA-3CD" if is_company else "3CB-3CD"
        if is_company:
            caveats.append(
                "A company's accounts are audited under Companies Act 2013 §139 "
                "with §143 in any event, so §44AB is satisfied by that audit "
                "plus the further report — Form 3CA with 3CD."
            )
    else:
        basis = (
            f"§{clause} — {label} of {_rupees(turnover_paise)} do not exceed "
            f"{_rupees(limit)}"
            + (" (the proviso's higher figure)" if enhanced else "")
            + f" for FY {t.fy}, so this clause does not require an audit."
        )
        form_type = None

    return TaxAuditAnswer(
        financial_year=t.fy,
        required=required,
        clause=clause,
        threshold_applied_paise=limit,
        enhanced_limit_applied=enhanced,
        basis=basis,
        caveats=tuple(caveats),
        limbs_not_tested=LIMBS_NOT_TESTED,
        form_type=form_type,
    )
