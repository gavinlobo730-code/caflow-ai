"""
Resolving what to withhold on a payment to a non-resident — IT Act s.195.

THE ORDER OF THE QUESTIONS IS THE WHOLE THING

    1. IS IT CHARGEABLE AT ALL? s.195 reaches "any sum chargeable under the
       provisions of this Act", and GE India Technology Centre (P) Ltd v. CIT
       (2010) 327 ITR 456 held those words govern. An ordinary import, or a
       service that is not fees for technical services, is business profits of
       the non-resident and is not chargeable in India without a permanent
       establishment. The answer there is NIL, and 20% would take a fifth of a
       supplier's invoice for tax nobody owes.

    2. WHAT IS ITS NATURE? The Act rate keys on royalty / FTS / interest /
       capital gains / other sums, NOT on the kind of work — which is exactly
       where s.194C and s.194J key, and why routing a foreign payment through
       them was the original bug. Nothing here infers the nature from a bill
       line; a human records it.

    3. IS THERE A TREATY, AND IS IT BETTER? s.90(2) gives the assessee the more
       beneficial of the Act and the agreement, conditional on a Tax Residency
       Certificate under s.90(4) and, in practice, Form 10F and a no-PE
       declaration. The treaty position is read off the agreement by the CA and
       recorded per (country, nature) in dtaa_treaty_rates (migration 310);
       this module only compares two numbers.

       A treaty with NO ARTICLE for the nature — the UAE and Singapore have no
       fees-for-technical-services article — is an answer, not a missing rate:
       the income is Article 7 business profits and not taxable here without a
       PE. It therefore lands back on question 1 and needs the same evidence.

    4. IS THERE A PAN? s.206AA floors the rate at 20% without one — but
       s.206AA(7) with Rule 37BC lifts that floor for a non-resident's
       interest, royalty, FTS and capital gains where six particulars are held.
       A resident gets no such relief.

    5. SURCHARGE AND CESS. Resident TDS under the 194 series is deducted at the
       bare section rate. s.195 is deducted at the rates IN FORCE, which
       include surcharge under Part II of the First Schedule and the 4% health
       and education cess. Omitting them under-deducts on every foreign
       payment, and under-deduction disallows the WHOLE expenditure under
       s.40(a)(i).

WHERE IT REFUSES, AND WHY REFUSING IS THE SAFE DIRECTION

    A refusal stops a bill and makes a human decide. A wrong number is
    withheld, paid to the Government, reported on 27Q and discovered by the
    supplier. So this refuses on:

      * no nature recorded — there is no rate without one;
      * business profits claimed with no no-PE declaration held — the nil is
        the biggest claim in the module and needs its evidence;
      * a TRC on file but no treaty rate recorded — falling back to the Act
        rate here would over-deduct in precisely the case where somebody has
        already established that a treaty applies.

    It does NOT refuse for a missing TRC. No TRC means no treaty relief
    (s.90(4)), which is a complete answer: the Act rate applies.

Integer basis points and integer paise throughout. Never float.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.tds.section_195_rates import (
    NATURE_BUSINESS_PROFITS_NO_PE, RULE_37BC_NATURES, FY195Rates, rates_for,
)

# Refusal codes, so a caller can branch without matching on prose.
REFUSED_NO_NATURE = "section_195_nature_not_recorded"
REFUSED_NO_PE_DECLARATION = "section_195_no_pe_declaration_missing"
REFUSED_TREATY_RATE_UNKNOWN = "section_195_treaty_rate_not_recorded"
REFUSED_UNKNOWN_NATURE = "section_195_nature_not_priced"


@dataclass(frozen=True)
class Section195Resolution:
    """What to withhold, or why nothing could be resolved.

    `applies` False with `refusal` set means STOP — not "deduct nothing".
    Nil withholding is `applies` True with tds_paise 0, which is what a
    chargeability answer looks like and is a different fact from a refusal.
    """
    applies: bool
    tds_paise: int = 0
    # The three components, kept apart because 27Q reports them apart and a CA
    # reconciling a challan needs to see which moved.
    base_tax_paise: int = 0
    surcharge_paise: int = 0
    cess_paise: int = 0
    # bps of the BASE rate actually used, before surcharge and cess.
    rate_bps: int = 0
    effective_rate_bps: int = 0     # base + surcharge + cess, for display
    nature: Optional[str] = None
    basis: str = ""                 # "act" | "treaty" | "not_chargeable" | "206aa_floor"
    citation: str = ""
    refusal: Optional[str] = None
    refusal_detail: str = ""
    fy: str = ""
    rates_verified: bool = False


def _surcharge_percent(rates: FY195Rates, amount_paise: int, is_company: bool,
                       nature: str) -> int:
    """Part II First Schedule surcharge for this payee class and amount.

    Two ladders, and picking the wrong one is a large error: a foreign
    company's top band is 5%, a non-corporate payee's is 37%.
    """
    bands = (rates.surcharge_foreign_company if is_company
             else rates.surcharge_non_corporate)
    pct = 0
    for band in bands:
        if amount_paise > band.above_paise:
            pct = band.rate_percent
    # s.111A/112/112A surcharge is capped, as it is for a resident.
    if nature in ("stcg_111a", "ltcg_112", "ltcg_112a"):
        pct = min(pct, rates.capital_gains_surcharge_cap_percent)
    return pct


def resolve_section_195(
    *,
    amount_paise: int,
    nature: Optional[str],
    is_company: bool = False,
    has_pan: bool = True,
    trc_on_file: bool = False,
    form_10f_on_file: bool = False,
    no_pe_declaration_on_file: bool = False,
    treaty_rate_bps: Optional[int] = None,
    treaty_has_no_article: bool = False,
    rule_37bc_particulars_held: bool = False,
    fy: Optional[str] = None,
) -> Section195Resolution:
    """Withholding on one payment to a non-resident. See the module docstring
    for the order of the questions, which is the substance of this function.
    """
    rates = rates_for(fy)
    meta = {"fy": rates.fy, "rates_verified": rates.verified}
    key = (nature or "").strip().lower()

    if not key:
        return Section195Resolution(
            applies=False, refusal=REFUSED_NO_NATURE, **meta,
            refusal_detail=(
                "Section 195 deducts at the rates in force by the NATURE of the "
                "income — royalty, fees for technical services, interest, "
                "capital gains, or other sums chargeable. Record the nature on "
                "the vendor before booking a bill that withholds under s.195."))

    rule = rates.natures.get(key)
    if rule is None:
        return Section195Resolution(
            applies=False, refusal=REFUSED_UNKNOWN_NATURE, nature=key, **meta,
            refusal_detail=(
                f"'{key}' is not a nature of income this rate table prices. "
                f"Determine the rate in force and withhold outside this bill."))

    # 1. Chargeability. The nil is the largest claim here, so it needs its
    #    evidence: a no-PE declaration from the payee.
    if key == NATURE_BUSINESS_PROFITS_NO_PE:
        if not no_pe_declaration_on_file:
            return Section195Resolution(
                applies=False, refusal=REFUSED_NO_PE_DECLARATION, nature=key, **meta,
                refusal_detail=(
                    "Withholding nil on business profits rests on the payee "
                    "having no permanent establishment in India (GE India "
                    "Technology Centre v. CIT). Record a no-PE declaration "
                    "against the vendor, or record a different nature of "
                    "income."))
        return Section195Resolution(
            applies=True, tds_paise=0, nature=key, basis="not_chargeable",
            citation=rule.citation, **meta)

    act_bps = rule.company_rate_bps if (is_company and rule.company_rate_bps
                                        is not None) else rule.rate_bps

    # 2. s.90(2) — the more beneficial of the Act and the agreement.
    basis = "act"
    citation = rule.citation
    rate_bps = act_bps
    if trc_on_file:
        # THE AGREEMENT HAS NO ARTICLE FOR THIS NATURE, WHICH IS AN ANSWER.
        # Several — the UAE and Singapore among them — have no fees for
        # technical services article at all, so what the Act would tax as FTS
        # is business profits under Article 7 and not taxable in India without
        # a permanent establishment. That is the SAME question chargeability
        # asked above, arriving by a different route, so it needs the same
        # evidence rather than being waved through as a zero rate.
        if treaty_has_no_article:
            if not no_pe_declaration_on_file:
                return Section195Resolution(
                    applies=False, refusal=REFUSED_NO_PE_DECLARATION,
                    nature=key, **meta,
                    refusal_detail=(
                        "The treaty has no article for this nature of income, "
                        "so it is business profits under Article 7 and not "
                        "taxable in India without a permanent establishment — "
                        "but that is a claim about the payee's Indian presence. "
                        "Record a no-PE declaration against the vendor."))
            return Section195Resolution(
                applies=True, tds_paise=0, nature=key, basis="not_chargeable",
                citation=("s.90(2) — the agreement has no article for this "
                          "nature, so Article 7 business profits apply and "
                          "there is no permanent establishment"), **meta)
        if treaty_rate_bps is None:
            return Section195Resolution(
                applies=False, refusal=REFUSED_TREATY_RATE_UNKNOWN, nature=key, **meta,
                refusal_detail=(
                    "This vendor holds a Tax Residency Certificate, so s.90(2) "
                    "gives it whichever of the Act and the DTAA is more "
                    "beneficial — but no treaty rate has been recorded. This "
                    "software does not hold treaty rates: read the relevant "
                    "article of the agreement and record the rate on the "
                    "vendor. Falling back to the Act rate here would "
                    "over-deduct on a payment a treaty has already been "
                    "established for."))
        if not form_10f_on_file:
            # Not a refusal — Rule 21AB requires Form 10F, but the treaty rate
            # is still the operative one and a missing form is a document to
            # chase rather than a reason to withhold at a different rate. It
            # rides on the resolution so the caller can surface it.
            citation = (f"s.90(2) treaty rate — Form 10F NOT on file "
                        f"(Rule 21AB); {rule.citation} is the Act alternative")
        else:
            citation = f"s.90(2) treaty rate; {rule.citation} is the Act alternative"
        if treaty_rate_bps < act_bps:
            rate_bps = treaty_rate_bps
            basis = "treaty"

    # 3. s.206AA — the 20% floor, and the carve-out residents do not get.
    floor_applied = False
    if not has_pan:
        relieved = key in RULE_37BC_NATURES and rule_37bc_particulars_held
        if not relieved and rate_bps < rates.section_206aa_floor_bps:
            rate_bps = rates.section_206aa_floor_bps
            basis = "206aa_floor"
            floor_applied = True
            citation = ("s.206AA — no PAN on file. Rule 37BC relief needs the "
                        "payee's name, email, phone, address, TRC and country "
                        "TIN, and this nature to be interest, royalty, fees "
                        "for technical services or capital gains.")

    # 4. Surcharge and cess. s.195 withholds at the rates IN FORCE, which
    #    include both — unlike the resident 194 series, which does not.
    #
    #    APPLIED ON TOP OF THE s.206AA FLOOR TOO, and that is a decision rather
    #    than an oversight. There is authority that s.206AA prescribes a flat
    #    20% not to be grossed up by surcharge and cess. It is contested, and
    #    this module takes the conservative side for the reason section_rates.py
    #    already gives: the tool should over-flag rather than silently
    #    under-deduct, and a CA reviews every figure before the challan. A CA
    #    taking the other view lowers the withholding themselves.
    base_tax = amount_paise * rate_bps // 10000
    sur_pct = _surcharge_percent(rates, amount_paise, is_company, key)
    surcharge = base_tax * sur_pct // 100
    cess = (base_tax + surcharge) * rates.cess_percent // 100
    total = base_tax + surcharge + cess

    return Section195Resolution(
        applies=True,
        tds_paise=total,
        base_tax_paise=base_tax,
        surcharge_paise=surcharge,
        cess_paise=cess,
        rate_bps=rate_bps,
        # Integer bps of the whole withholding against the payment, so a CA can
        # read one number back against the invoice. Floor, never over-stated.
        effective_rate_bps=(total * 10000 // amount_paise) if amount_paise else 0,
        nature=key,
        basis=basis,
        citation=citation + (" (floor applied)" if floor_applied else ""),
        **meta,
    )
