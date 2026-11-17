"""The tax each capital-gains register transfer adds, offered as a candidate for §234C(1)'s proviso (POST-A-075).

The register's per-transfer figure (`compute_capital_gains`) is the statutory rate on ONE gain with the §112A exemption taken off that
one gain. Two things make that wrong for a year with more than one transfer or a large gain, and both are read here from the
FY-versioned rate registry (`statutory_rates`) and from nothing else:

* **The §112A exemption is annual.** Income-tax Act §112A exempts the first slice of the assessee's aggregate LTCG on listed equity
  for the year, not of each transfer. The transfers are taken in the order they arose, against the running total of the year's
  §112A gains and losses: each gain carries what the running total's tax reaches above the highest the earlier gains already
  reached, never above the tax on the year's net total. So the exemption is used once, by the first gains, a loss in the section
  nets in its place, a gain that only makes good an earlier loss carries nothing, and the amounts add up to the tax on the year's
  net §112A gain exactly (a running difference that is allowed to fall on a loss would offer the same tax twice). It attaches the
  tax to the EARLIEST gains, which excuses the fewest instalments under §234C(1)'s proviso. (Set-off against other heads, and
  losses brought forward, are not known to the register and are not applied.)
* **Surcharge.** For a gain taxed under §111A, §112A or §112 the surcharge is capped at the registry's
  `capital_gains_surcharge_cap_percent` whatever the assessee's bracket; the bracket is decided by the year's TOTAL income, which
  the register does not hold. It is applied only where the caller states that income, from the registry's own brackets and cap, and
  never from marginal relief (not modelled and said). The registry's brackets are the slab path's (`itr_engine` charges them to the
  four `assessee.SLAB_KINDS`), so a firm, an LLP, a company or a client whose tax basis is not known is offered NO surcharge and
  the sentence says why. A gain taxed at the assessee's own slab (§50AA, §115BBH, a slab estimate) has a surcharge that depends on
  the regime, which is not known, so none is offered for it.

A year the registry does not hold is NOT filled with another year's figure: the figure stays the register's own (as before) and the
sentence from `statutory_rates.fy_rate_gap` says what was not applied. A year it holds but has not verified is applied and says so.
Prepare-only: every candidate is the CA's to include, edit or reject.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.income_tax import statutory_rates as sr
from domain.income_tax.assessee import SLAB_KINDS, is_entity

# Sections whose surcharge the registry caps (the registry's own comment on `capital_gains_surcharge_cap_percent`).
_CAPPED = ("Section 111A", "Section 112A", "Section 112")
_S112A = "Section 112A"


@dataclass(frozen=True)
class Transfer:
    register_id: Optional[str]
    sale_date: str                    # ISO date
    section_ref: str                  # CapitalGainsResult.section_ref
    gain_paise: int                   # may be negative: a loss nets against the section's running total
    engine_tax_paise: int             # the register's own tax on this transfer alone, before cess


@dataclass(frozen=True)
class Offer:
    register_id: Optional[str]
    tax_before_surcharge_paise: int
    surcharge_paise: int
    tax_paise: int                    # including cess
    surcharge_rate_percent: Optional[int]


def _round_half_up(numerator: int, denominator: int) -> int:
    return (numerator * 2 + denominator) // (2 * denominator)


def offer(transfers: list[Transfer], fy: str, total_income_paise: Optional[int], *,
          assessee_kind: Optional[str]) -> tuple[list[Offer], list[str]]:
    """(one Offer per transfer, in the order given, and the sentences saying what was and was not applied).

    `assessee_kind` is `assessee.assessee_kind_for_entity_type`'s answer for the client (None where it has no tax basis recorded),
    and has no default: the surcharge ladder held here is the slab path's, and a caller that forgot to say whose gains these are
    must not be given an individual's."""
    notes: list[str] = []
    ladder_applies = assessee_kind in SLAB_KINDS
    held = sr.RATES_BY_FY.get(fy)
    gap = sr.fy_rate_gap(fy)
    if gap:
        notes.append(gap)
    rates = held if held is not None else sr.rates_for(fy)      # cess only, for a year the registry lacks (the gap above says so)

    before: dict[int, int] = {}
    if held is None:
        notes.append(
            f"The registry holds no rates for FY {fy}, so the annual §112A exemption and the surcharge are NOT applied and each "
            "gain is shown at the register's own per-transfer figure; the §112A exemption in it is taken once per transfer, "
            "which overstates the exemption for a year with several.")
        for i, t in enumerate(transfers):
            before[i] = t.engine_tax_paise
    else:
        order = sorted((i for i, t in enumerate(transfers) if t.section_ref == _S112A),
                       key=lambda i: (transfers[i].sale_date, str(transfers[i].register_id)))

        def tax_on(total: int) -> int:
            return _round_half_up(max(0, total - held.ltcg_112a_exemption_paise) * held.ltcg_112a_rate_bps, 10_000)

        # A high-water mark capped at the year's own figure: what a gain carries is what the running total's tax reaches above the
        # most already offered. A running DIFFERENCE fell with a loss and so offered the same tax again on the next gain.
        year_tax = tax_on(sum(transfers[i].gain_paise for i in order))
        running = offered = 0
        for i in order:
            running += transfers[i].gain_paise
            reached = min(tax_on(running), year_tax)
            before[i] = max(0, reached - offered)
            offered = max(offered, reached)
        if order:
            notes.append(
                "The ₹1,25,000 §112A exemption is annual: it is used once, by the first listed-equity long-term gains of the year "
                "in date order, and a §112A loss nets against them in its place, so the amounts add up to the tax on the year's "
                "net §112A gain and a gain that only makes good an earlier loss carries nothing. Set-off of other losses and "
                "brought-forward losses is not known to the register and is not applied.")
        for i, t in enumerate(transfers):
            before.setdefault(i, t.engine_tax_paise)

    out: list[Offer] = []
    for i, t in enumerate(transfers):
        tax = max(0, before[i])
        rate: Optional[int] = None
        surcharge = 0
        if held is not None and ladder_applies and total_income_paise is not None and t.section_ref in _CAPPED:
            rate, _ = sr.resolve_surcharge_bracket(total_income_paise, held.surcharge_brackets, held.capital_gains_surcharge_cap_percent)
            surcharge = tax * rate // 100
        out.append(Offer(t.register_id, tax, surcharge, tax + surcharge + sr.cess_paise(tax + surcharge, rates), rate))

    if any(t.section_ref in _CAPPED for t in transfers) and not (assessee_kind is not None and is_entity(assessee_kind)):
        notes.append(
            "It leaves out any basic exemption the slab income did not use, so the tax shown can be higher than the computation's.")
    if held is not None:
        if not ladder_applies:
            notes.append(
                "Surcharge is NOT included: the registry's surcharge brackets are the ones the computation charges an individual, a "
                "HUF, an AOP or a BOI, and this client is a firm, an LLP or a company, or has no entity type this software can tax. "
                "Take the surcharge from the computation.")
        elif total_income_paise is None:
            notes.append(
                "Surcharge is NOT included: its bracket depends on the year's total income, which the register does not hold. "
                "Give the year's total income to include it.")
        else:
            notes.append(
                "Surcharge is included at the registry's bracket for the total income given, capped for §111A, §112A and §112 "
                "gains; marginal relief is not modelled.")
            if any(t.section_ref not in _CAPPED for t in transfers):
                notes.append(
                    "A gain taxed at the assessee's own slab carries no surcharge here: it depends on the regime, which is not known.")
    return out, notes
