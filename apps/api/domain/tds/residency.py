"""
Whether a payee is a resident, and what that changes — IT Act Chapter XVII-B.

WHY THIS IS NOT A LABEL

    tds_deductions.return_type was hardcoded '26Q'. The obvious reading is that
    a non-resident vendor needs the same row with '27Q' written on it instead.
    That reading is wrong, and acting on it would produce a return that looks
    right and is not.

    Almost every section this codebase computes says, in its own charging
    words, "to a RESIDENT". Section 194C(1) is "any person responsible for
    paying any sum to any resident ... for carrying out any work"; s.194J(1) is
    "to a resident any sum by way of fees for professional services"; 193, 194,
    194A, 194D, 194G, 194H, 194I, 194K, 194LA and 194Q all carry the same
    limitation. So for a NON-RESIDENT payee those sections do not merely file
    in a different form — THEY DO NOT APPLY AT ALL. Section 195 applies:

        "Any person responsible for paying to a non-resident, not being a
         company, or to a foreign company, any interest ... or any other sum
         chargeable under the provisions of this Act ... shall, at the time of
         credit ... or at the time of payment ... deduct income-tax thereon at
         THE RATES IN FORCE."

    Section 194B (winnings) is the single exception in the registry: it reads
    "to any person" and so reaches a non-resident too. It is listed separately
    rather than silently lumped in, because "every section is resident-only" is
    the kind of near-truth that stops being true when someone adds 194E or
    194LB and copies the pattern without reading it.

WHAT §195 CHANGES, ALL OF WHICH MAKES A NAIVE BRANCH DANGEROUS

    * NO THRESHOLD. The resident sections' Rs 30,000 / Rs 1,00,000 / Rs 50,000
      limits are creatures of their own sub-sections. s.195 has none — it bites
      on any sum chargeable to tax. Running a non-resident payment through
      resolve_tds() would find it "below_threshold" and deduct NOTHING.
    * RATES IN FORCE, not a section rate: Part II of the First Schedule to the
      Finance Act, by NATURE of the income (royalty, fees for technical
      services, interest, capital gains, other sums) — not by the kind of work
      done, which is what 194C/194J key on.
    * SURCHARGE AND CESS APPLY. Resident TDS under the 194 series is deducted
      at the bare section rate. s.195 is deducted at the rates in force
      INCLUDING surcharge and health-and-education cess, and the surcharge
      bands differ between a non-corporate payee and a foreign company.
    * THE TREATY MAY OVERRIDE IT. s.90(2) gives the assessee the more
      beneficial of the Act and the DTAA, conditional on a Tax Residency
      Certificate (s.90(4)), Form 10F (Rule 21AB) and, in practice, a no-PE
      declaration. India has treaties with over ninety countries, each with its
      own royalty/FTS/interest rates.
    * s.206AA's 20% floor has a carve-out that does not exist for residents.
      s.206AA(7) with Rule 37BC lifts it for a non-resident's interest,
      royalty, FTS and capital gains where they furnish name, email, phone,
      address, TRC and the TIN of their country. Applying a blanket 20% floor
      to a non-resident who has furnished all six over-deducts.
    * Rule 37BB requires Form 15CA, and 15CB from an accountant, BEFORE the
      remittance leaves.

WHERE THE RATE ITSELF LIVES

    This module routes and classifies. It does NOT compute the s.195 rate —
    domain/tds/section_195.py does, on the registry in section_195_rates.py,
    and those hold the Act side only. The treaty rate is recorded per vendor by
    the CA who read the agreement, because nature of income x ninety-odd
    treaties x surcharge band is exactly the shape of statutory data CLAUDE.md
    says must not be written from memory.

    This module's own refusal is narrower and is now a VENDOR-level check: a
    vendor recorded as a non-resident may not also carry a resident-only TDS
    section, because the two facts contradict each other. The bill routes by
    RESIDENCY rather than by the section string, so a stale s.194C on a
    non-resident vendor would otherwise be silently ignored rather than
    reported — models/parties.py enforces it where a human types it.

WHAT AN UNCLASSIFIED VENDOR MEANS, WHICH IS DIFFERENT FROM MSMED

    vendors.residential_status is NULL for every row that existed before
    migration 308, and NULL is treated as resident for computation. That is
    deliberate and it is NOT the msme_status rule, where an unclassified vendor
    is reported beside the table rather than inside it (see migration 303).

    The difference is what the default costs. An unclassified vendor called
    "Others" in the Schedule III payables note changes taxable income through
    s.43B(h), so there is no safe default and the code refuses. Here the
    default is 26Q at the section rate, which is correct for domestic vendors —
    which is very nearly all of them for the practices this serves — and
    blocking every bill for every client until somebody classifies every vendor
    would be a worse failure than the one being fixed.

    What is NOT acceptable is the silence. So the register reports the
    unclassified vendors it defaulted, and a CA can see which ones were assumed
    resident rather than known to be.
"""
from __future__ import annotations

from typing import Optional

# The two values vendors.residential_status may hold. NULL means nobody has
# said, which is a third state and not a synonym for either.
RESIDENT = "resident"
NON_RESIDENT = "non_resident"
RESIDENTIAL_STATUSES = frozenset({RESIDENT, NON_RESIDENT})

# Quarterly statements under Rule 31A(4). 24Q is salary (Rule 31A(4)(a) reads
# with s.192) and 27EQ is TCS; neither is reachable from a purchase bill.
FORM_26Q = "26Q"   # non-salary payments to RESIDENTS      — Rule 31A(4)(a)
FORM_27Q = "27Q"   # payments to NON-RESIDENTS             — Rule 31A(4)(b)

# Sections whose charging words limit them to a resident payee. Each entry is
# the phrase the section itself uses, so a reader can check the claim without
# leaving the file. Transcribed from the Act, not inferred from the rate table.
RESIDENT_ONLY_SECTIONS: dict[str, str] = {
    "193":   "s.193 — 'to a resident any income by way of interest on securities'",
    "194":   "s.194 — 'to a shareholder, who is resident in India'",
    "194A":  "s.194A(1) — 'to a resident any income by way of interest other than "
             "income by way of interest on securities'",
    "194C":  "s.194C(1) — 'to any resident ... for carrying out any work'",
    "194D":  "s.194D — 'to a resident any income by way of remuneration or reward "
             "... for soliciting or procuring insurance business'",
    "194G":  "s.194G(1) — 'to any person, who is or has been stocking, distributing "
             "... lottery tickets' read with the resident limitation",
    "194H":  "s.194H — 'to a resident any income by way of commission or brokerage'",
    "194I":  "s.194I — 'to a resident any income by way of rent'",
    "194J":  "s.194J(1) — 'to a resident any sum by way of fees for professional services'",
    "194K":  "s.194K — 'to a resident any income in respect of units'",
    "194LA": "s.194LA — 'to a resident any sum ... compensation on compulsory acquisition'",
    "194Q":  "s.194Q(1) — 'to any resident ... for purchase of goods'",
}

# In the registry and NOT resident-only: s.194B charges "to any person", so a
# non-resident's winnings are within it. Kept explicit so that a future 194E
# (non-resident sportsmen) or 194LB is classified by reading it, not by
# inheriting whichever list it was pasted next to.
SECTIONS_REACHING_NON_RESIDENTS = frozenset({"194B"})

# The charging section for a payment to a non-resident.
SECTION_195 = "195"

# The named gap, in the shape domain/payroll uses: a machine-readable code, and
# a sentence written for the CA who has to act on it.
GAP_SECTION_195_RATE_NOT_MODELLED = "section_195_rate_not_modelled"
GAP_RESIDENCY_NOT_CLASSIFIED = "vendor_residency_not_classified"
GAP_27Q_IDENTIFIERS_MISSING = "non_resident_identifiers_missing"
# Raised on a s.195 deduction whose year's rates nobody has confirmed against
# the Finance Act. Not a refusal — refusing every foreign payment until a human
# reads Part II would stop the work rather than inform it — but a CA about to
# pay a challan should be told the rate was reconciled and not verified.
GAP_195_RATES_UNVERIFIED = "section_195_rates_not_verified"
# Nil was withheld on a no-PE declaration nobody dated or attributed. s.201(1)
# makes a deductor who fails to deduct an assessee in default and s.201(1A)
# charges interest, so the consequence of a wrong nil sits with the DEDUCTOR —
# and "a box was ticked" answers neither who nor when.
GAP_NO_PE_DECLARATION_UNDATED = "no_pe_declaration_undated"
# Money left for a non-resident and no Form 15CA acknowledgement was recorded
# against the bill. Rule 37BB with s.195(6) wants it BEFORE the remittance.
GAP_FORM_15CA_NOT_RECORDED = "form_15ca_not_recorded"


def is_non_resident(residential_status: Optional[str]) -> bool:
    """True only when somebody has actually said 'non_resident'.

    NULL and any unrecognised value are NOT non-resident: an unclassified
    vendor is treated as resident for computation (see the header), and the
    caller reports the gap separately rather than guessing the other way.
    """
    return (residential_status or "").strip().lower() == NON_RESIDENT


def is_classified(residential_status: Optional[str]) -> bool:
    """Whether a human has recorded this vendor's residential status at all."""
    return (residential_status or "").strip().lower() in RESIDENTIAL_STATUSES


def return_type_for(residential_status: Optional[str]) -> str:
    """The quarterly statement this deduction belongs in — Rule 31A(4).

    27Q for a payee recorded as non-resident, 26Q otherwise. 'Otherwise'
    includes unclassified, which is why is_classified() exists and why the
    caller raises GAP_RESIDENCY_NOT_CLASSIFIED beside this.
    """
    return FORM_27Q if is_non_resident(residential_status) else FORM_26Q


def section_refusal(section: Optional[str],
                    residential_status: Optional[str]) -> Optional[str]:
    """Why this section cannot be recorded against this payee, or None.

    One refusal: a RESIDENT-ONLY section on a payee recorded as a non-resident.
    s.194C and its neighbours do not reach a non-resident at all; s.195 does.

    s.195 itself is NOT refused here any more. It was, while nothing could rate
    it; domain/tds/section_195.py now does, and that module raises its own
    refusals — no nature recorded, no no-PE declaration behind a nil, a TRC
    with no treaty rate — which are about the payment rather than the section.

    Returns a sentence for a CA, not a code: it goes into a 422 verbatim.
    """
    code = (section or "").upper().strip()
    if not code or code == SECTION_195:
        return None

    if not is_non_resident(residential_status):
        return None

    citation = RESIDENT_ONLY_SECTIONS.get(code)
    if citation is None:
        # Either s.194B, which genuinely reaches a non-resident, or a section
        # nobody has classified. Silence here is deliberate: refusing a section
        # this module has not read would be guessing in the other direction.
        return None

    return (
        f"This vendor is recorded as a NON-RESIDENT, and section {code} applies "
        f"only to a resident payee ({citation}). A payment to a non-resident is "
        f"deducted under section 195 at the rates in force, which this software "
        f"does not compute — see the section 195 message for what that needs. "
        f"Either correct the vendor's residential status, or turn TDS off on "
        f"this vendor and deduct under section 195 outside the bill."
    )


def missing_27q_identifiers(vendor: Optional[dict]) -> list[str]:
    """Which 27Q deductee identifiers this vendor is missing.

    Form 27Q's deductee annexure needs more than 26Q's does. Where the payee
    has no PAN, Rule 37BC's relief from the s.206AA floor is conditional on the
    deductor holding the payee's name, email, phone, address, Tax Residency
    Certificate and the TIN of the country of residence — so the country and
    the TIN are not decoration, they are what makes the lower rate defensible.

    Returns field names, empty when nothing is missing. A vendor WITH a PAN is
    still asked for its country: 27Q reports it either way.
    """
    v = vendor or {}
    missing: list[str] = []
    if not (v.get("country_of_residence") or "").strip():
        missing.append("country_of_residence")
    has_pan = bool((v.get("pan") or "").strip())
    if not has_pan and not (v.get("tax_identification_number") or "").strip():
        # Only demanded in the no-PAN case, which is the one Rule 37BC governs.
        missing.append("tax_identification_number")
    return missing
