"""
CGST Rule 43 — input tax credit on CAPITAL GOODS used partly for exempt
supplies, apportioned monthly over a five-year life.

WHAT THE RULE DOES

    A business that makes both taxable and exempt supplies cannot keep the
    whole credit on a machine used for both. Rule 43 spreads that credit over
    SIXTY tax periods and, in each one, adds back the exempt-turnover share as
    output tax. The letters are the rule's own:

        A   the credit taken on one common capital good        43(1)(c)
        Tc  the aggregate of A over common capital goods       43(1)(d)
        Tm  a period's share of one good's credit, A ÷ 60      43(1)(e)
        Tr  Σ Tm over goods whose useful life REMAINS          43(1)(f)
        Te  (E ÷ F) × Tr — the amount added to output tax      43(1)(g)/(h)

        E   aggregate value of EXEMPT supplies in the period
        F   total turnover in the State in the period

    Rule 43(2) computes Te separately for IGST, CGST and SGST/UTGST, so this
    module carries three figures throughout and never a single total.

THE THREE USES, AND WHY AN UNCLASSIFIED ASSET IS REFUSED

    43(1)(a) exclusively for non-business or exempt supplies — NO credit.
    43(1)(b) exclusively for supplies other than exempt, zero-rated included —
             FULL credit, and no Te ever.
    43(1)(c) everything else — COMMON, and this rule applies.

    Only the CA knows which. Guessing is unsafe in BOTH directions, which is
    why `fixed_assets.rule_43_use` is nullable and a NULL is reported rather
    than assumed:

      * assuming COMMON reverses credit on a machine used only for taxable
        supplies — the business loses credit §16(1) gives it;
      * assuming EXCLUSIVELY TAXABLE leaves Te unpaid, and 43(1)(h) attaches
        interest to it, so the shortfall grows.

    Same shape as `vendors.msme_status` and `chart_of_accounts.unbilled_dues_side`:
    a fact about the world that no ledger holds, refused and named.

WHAT IS DELIBERATELY NOT MODELLED

  * **The (a)→(c) and (b)→(c) transitions.** Both provisos to 43(1)(c)/(d)
    reduce the input tax by five percentage points per quarter or part thereof
    before it joins Tc. A single `rule_43_use` column records only what an
    asset is NOW, not when it changed, so the reduction has nothing to compute
    from. Modelling it needs a history of the classification, which is a
    second table. `TRANSITION_NOT_MODELLED` says so on every answer.
  * **The Explanation to 43(1)(g)** excludes duties under entries 84 and 92A of
    List I and 51 and 54 of List II — central and state excise on petroleum,
    tobacco and alcohol — from both E and F. Nothing here separates them out of
    the non-GST bucket, so a client dealing in those needs the figures adjusted
    by hand, and the answer says so.
  * **Rule 42**, the inputs-and-input-services twin. Different inputs, monthly
    rather than sixty-monthly, and out of scope here.

WHAT IT DOES NOT DO EITHER: post anything. `services/itc_register_service`
records the deliberate choice that giving credit back is a real movement the CA
raises as a journal, and this module only says how much.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

#: Rule 43(1)(c) — "the useful life of such goods shall be taken as five years
#: from the date of the invoice".
USEFUL_LIFE_MONTHS = 60

#: `fixed_assets.rule_43_use`. NULL is a fourth state and is the default.
USE_COMMON = "common"
USE_EXCLUSIVELY_EXEMPT = "exclusively_exempt"
USE_EXCLUSIVELY_TAXABLE = "exclusively_taxable"
VALID_USES = (USE_COMMON, USE_EXCLUSIVELY_EXEMPT, USE_EXCLUSIVELY_TAXABLE)

HEADS = ("igst", "cgst", "sgst")

GAP_USE_NOT_CLASSIFIED = "rule_43_use_not_classified"
GAP_ITC_NOT_STATED = "rule_43_itc_eligibility_not_stated"
GAP_NO_INVOICE_DATE = "rule_43_no_invoice_date"
GAP_NO_TURNOVER = "rule_43_no_turnover_in_the_period"

TRANSITION_NOT_MODELLED = (
    "An asset that MOVED between the exclusive uses and common use is not "
    "handled. The provisos to Rule 43(1)(c) and (d) reduce its input tax by "
    "five percentage points per quarter or part thereof before it joins Tc, "
    "and this product records only what an asset is now, not when it changed. "
    "Adjust such an asset by hand."
)

EXCISE_EXCLUSION_NOT_MODELLED = (
    "The Explanation to Rule 43(1)(g) excludes duties under entries 84 and 92A "
    "of List I and 51 and 54 of List II — central and state excise on "
    "petroleum, tobacco and alcohol — from both E and F. Those are not "
    "separated out of the non-GST supply figure here, so a client dealing in "
    "them needs E and F adjusted before this figure is relied on."
)


@dataclass(frozen=True)
class CapitalGood:
    """One asset, as Rule 43 needs to see it."""
    asset_id: str
    asset_name: str
    #: Rule 43(1)(c): the five years run "from the date of the invoice".
    invoice_date: Optional[date]
    #: The tax on the acquisition, by head, in paise.
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    #: `fixed_assets.itc_eligible` — True credited, False blocked under §17(5)
    #: and capitalised, None not stated (an asset predating migration 343).
    itc_eligible: Optional[bool] = None
    #: `fixed_assets.rule_43_use` — one of VALID_USES, or None.
    use: Optional[str] = None

    def credit_paise(self, head: str) -> int:
        return max(0, int(getattr(self, f"{head}_paise") or 0))


@dataclass(frozen=True)
class Turnover:
    """E and F for the tax period, in paise, exclusive of tax.

    `exempt_paise` is §2(47)'s exempt supply, which INCLUDES a non-taxable
    supply (§2(78)) — so nil-rated, wholly exempt under §11, and non-GST
    together. Zero-rated supplies are deliberately NOT in it: §16(1) of the
    IGST Act allows credit on them and Rule 43(1)(b) names them expressly as
    supplies "other than exempted supplies".

    `total_paise` is turnover in the State under §2(112): taxable supplies,
    exempt supplies, exports and inter-State supplies, excluding tax itself and
    excluding inward supplies on reverse charge.
    """
    exempt_paise: int
    total_paise: int


@dataclass(frozen=True)
class AssetLine:
    """What one asset contributed, and why it contributed nothing."""
    asset_id: str
    asset_name: str
    use: Optional[str]
    #: Which of the sixty periods this is for the asset — 1-based. None where
    #: it does not participate.
    period_index: Optional[int]
    included: bool
    reason: str
    #: A ÷ 60 for this asset, per head, before the E/F share. Exact paise are
    #: not taken here — the division happens once, on the aggregate.
    credit_paise: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Rule43Result:
    """The period's answer, per head, with everything it rests on."""
    period: str
    #: Te — the amount to be added to output tax liability, per head.
    te_paise: dict
    #: Tr × 60, per head: the aggregate A over participating commons. Kept
    #: undivided so a reader can check the arithmetic without rounding.
    common_credit_paise: dict
    turnover: Optional[Turnover]
    lines: tuple
    #: Assets that could not be judged, one sentence each.
    gaps: tuple
    #: Things true of the whole answer.
    caveats: tuple
    #: True where Te could not be computed at all.
    refused: bool
    refusal: str = ""

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "te_paise": dict(self.te_paise),
            "te_total_paise": sum(self.te_paise.values()),
            "common_credit_paise": dict(self.common_credit_paise),
            "exempt_turnover_paise": self.turnover.exempt_paise if self.turnover else None,
            "total_turnover_paise": self.turnover.total_paise if self.turnover else None,
            "useful_life_months": USEFUL_LIFE_MONTHS,
            "assets": [
                {
                    "asset_id": ln.asset_id,
                    "asset_name": ln.asset_name,
                    "use": ln.use,
                    "period_index": ln.period_index,
                    "included": ln.included,
                    "reason": ln.reason,
                    "credit_paise": dict(ln.credit_paise),
                }
                for ln in self.lines
            ],
            "gaps": list(self.gaps),
            "caveats": list(self.caveats),
            "refused": self.refused,
            "refusal": self.refusal,
        }


def _months_between(earlier: date, later: date) -> int:
    """Whole calendar months from `earlier`'s month to `later`'s month.

    Month arithmetic, not day arithmetic, and deliberately so: Rule 43 spreads
    a credit over sixty TAX PERIODS, and a tax period is a month. An asset
    invoiced on the 28th and one invoiced on the 2nd of the same month take
    their first instalment in the same return.
    """
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def period_index(invoice_date: date, period_start: date) -> int:
    """Which of the sixty instalments this tax period is — 1-based.

    Returns 0 or less for a period BEFORE the asset was acquired, and 61 or
    more once the life has run out.

    WHY 1-BASED AND WHY EXACTLY SIXTY. Rule 43(1)(c) gives a useful life of
    "five years from the date of the invoice" and (e) divides by sixty, so the
    credit is designed to come back in sixty equal instalments. Counting the
    month of the invoice as the first makes them sixty exactly, and settles
    the "useful life remains DURING the tax period" question in the month the
    five years expire without any part-of-a-month arithmetic.
    """
    return _months_between(invoice_date, period_start) + 1


def _ceil_div(numerator: int, denominator: int) -> int:
    """Round UP.

    Te is added to the output tax liability and Rule 43(1)(h) attaches "the
    applicable interest" to it, so an understated figure is a shortfall that
    grows. Rounding up is the direction that cannot create one — the same
    reasoning as the §50 interest and the ESI contribution, and the opposite of
    the GST discount, which floors because there understating cannot
    under-declare tax.
    """
    if denominator <= 0:
        raise ZeroDivisionError("denominator must be positive")
    return -(-numerator // denominator)


def compute(
    goods: Iterable[CapitalGood],
    *,
    period: str,
    period_start: date,
    turnover: Optional[Turnover],
) -> Rule43Result:
    """Te for one tax period, per head.

    `period` is the label the caller uses (this module never parses it);
    `period_start` is the first day of the tax period and is what the sixty
    instalments are counted against.
    """
    lines: list[AssetLine] = []
    gaps: list[str] = []
    caveats: list[str] = [TRANSITION_NOT_MODELLED, EXCISE_EXCLUSION_NOT_MODELLED]

    # Σ A over the commons whose useful life remains, per head. Kept as a
    # running integer so the ÷60 and the ×E/F happen ONCE, at the end — a
    # per-asset division would round sixty times and drift.
    common: dict = {h: 0 for h in HEADS}

    for g in goods:
        credit = {h: g.credit_paise(h) for h in HEADS}

        if g.use is None:
            gaps.append(
                f"{g.asset_name}: no Rule 43 use recorded. Mark it as used "
                f"exclusively for exempt supplies (43(1)(a), no credit), "
                f"exclusively for taxable or zero-rated supplies (43(1)(b), "
                f"full credit), or COMMON (43(1)(c), this reversal). It is "
                f"left out until then — assuming either way is wrong in a "
                f"direction that costs somebody money."
            )
            lines.append(AssetLine(g.asset_id, g.asset_name, None, None, False,
                                   GAP_USE_NOT_CLASSIFIED, credit))
            continue

        if g.use == USE_EXCLUSIVELY_EXEMPT:
            lines.append(AssetLine(
                g.asset_id, g.asset_name, g.use, None, False,
                "Rule 43(1)(a) — used exclusively for exempt or non-business "
                "supplies, so no credit was available and there is nothing to "
                "reverse.", credit))
            continue

        if g.use == USE_EXCLUSIVELY_TAXABLE:
            lines.append(AssetLine(
                g.asset_id, g.asset_name, g.use, None, False,
                "Rule 43(1)(b) — used exclusively for supplies other than "
                "exempt ones, zero-rated included, so the whole credit stands "
                "and Rule 43 never reaches it.", credit))
            continue

        # ── common (43(1)(c)) from here ──────────────────────────────────────
        if g.itc_eligible is None:
            gaps.append(
                f"{g.asset_name}: whether the tax on this acquisition was "
                f"CLAIMED as credit is not recorded (it predates the column). "
                f"Rule 43 apportions credit actually taken, so it is left out."
            )
            lines.append(AssetLine(g.asset_id, g.asset_name, g.use, None, False,
                                   GAP_ITC_NOT_STATED, credit))
            continue

        if g.itc_eligible is False:
            lines.append(AssetLine(
                g.asset_id, g.asset_name, g.use, None, False,
                "No credit was taken — the tax is blocked under §17(5) and was "
                "capitalised into the cost, so there is nothing to apportion.",
                credit))
            continue

        if g.invoice_date is None:
            gaps.append(
                f"{g.asset_name}: no acquisition date, so the five years Rule "
                f"43(1)(c) counts "
                f"\"from the date of the invoice\" cannot be measured."
            )
            lines.append(AssetLine(g.asset_id, g.asset_name, g.use, None, False,
                                   GAP_NO_INVOICE_DATE, credit))
            continue

        idx = period_index(g.invoice_date, period_start)
        if idx < 1:
            lines.append(AssetLine(
                g.asset_id, g.asset_name, g.use, idx, False,
                "Acquired after this tax period.", credit))
            continue
        if idx > USEFUL_LIFE_MONTHS:
            lines.append(AssetLine(
                g.asset_id, g.asset_name, g.use, idx, False,
                f"The five-year useful life ran out — this would be instalment "
                f"{idx} of {USEFUL_LIFE_MONTHS}.", credit))
            continue

        if not any(credit.values()):
            lines.append(AssetLine(
                g.asset_id, g.asset_name, g.use, idx, False,
                "No GST recorded on the acquisition, so there is no credit to "
                "apportion.", credit))
            continue

        for h in HEADS:
            common[h] += credit[h]
        lines.append(AssetLine(
            g.asset_id, g.asset_name, g.use, idx, True,
            f"Common capital good, instalment {idx} of {USEFUL_LIFE_MONTHS}.",
            credit))

    zero = {h: 0 for h in HEADS}

    if turnover is None or turnover.total_paise <= 0:
        # The proviso to Rule 43(1)(g): where there is no turnover in the
        # period, or the information is not available, E and F are taken from
        # the LAST period for which they are — which is a different period's
        # figures and cannot be invented here.
        return Rule43Result(
            period=period, te_paise=zero, common_credit_paise=common,
            turnover=turnover, lines=tuple(lines), gaps=tuple(gaps),
            caveats=tuple(caveats), refused=True,
            refusal=(
                "Total turnover (F) for this period is nil or unknown, so E ÷ F "
                "has no value. The proviso to Rule 43(1)(g) says to take E and "
                "F from the last tax period for which they are available — "
                "those are a different period's figures and are not "
                "substituted automatically."
            ),
        )

    if turnover.exempt_paise <= 0:
        caveats.append(
            "No exempt supplies in this period, so E is nil and Te is nil "
            "however much common credit is running. The instalment still "
            "counts against the sixty."
        )

    # Te = (E ÷ F) × (Σ A ÷ 60), computed as one integer division per head so
    # the rounding happens once rather than three times.
    te = {
        h: _ceil_div(common[h] * max(0, turnover.exempt_paise),
                     USEFUL_LIFE_MONTHS * turnover.total_paise)
        for h in HEADS
    }

    if not any(ln.included for ln in lines):
        caveats.append(
            "No common capital good is inside its five-year life this period, "
            "so there is nothing to apportion."
        )

    return Rule43Result(
        period=period, te_paise=te, common_credit_paise=common,
        turnover=turnover, lines=tuple(lines), gaps=tuple(gaps),
        caveats=tuple(caveats), refused=False,
    )
