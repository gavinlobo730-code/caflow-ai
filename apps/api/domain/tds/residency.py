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
GAP_RESIDENCY_NOT_CLASSIFIED = "vendor_residency_not_classified"
GAP_27Q_IDENTIFIERS_MISSING = "non_resident_identifiers_missing"
# Raised on a s.195 deduction whose year's rates nobody has confirmed against
# the Finance Act. Not a refusal — refusing every foreign payment until a human
# reads Part II would stop the work rather than inform it — but a CA about to
# pay a challan should be told the rate was reconciled and not verified.
GAP_195_RATES_UNVERIFIED = "section_195_rates_not_verified"
# The RESIDENT-SIDE twin, and it is the one that had no gap at all. Raised on
# any deduction whose year `domain/tds/section_rates.TDS_RATES_BY_FY` does not
# hold as verified — which includes every year BEFORE the registry starts, not
# only the years after it.
#
# That direction is the dangerous one. `tds_rates_for` substitutes
# LATEST_VERIFIED_TDS_FY for a year it does not have, and Finance Act 2025
# RAISED most thresholds — so a bill entered late for FY 2024-25 is measured
# against a bar the law had not yet lifted, and s.194J at Rs 40,000 comes back
# nil where Rs 4,000 was due. Under-deduction disallows 30% of the expenditure
# under s.40(a)(ia) and surfaces at assessment, long after the return.
#
# Not a refusal, for the same reason as the s.195 gap: a prior-year bill must
# still be bookable. The gap is how the CA learns which figure to re-read.
GAP_RESIDENT_RATES_UNVERIFIED = "resident_tds_rates_not_verified"
# Nil was withheld on a no-PE declaration nobody dated or attributed. s.201(1)
# makes a deductor who fails to deduct an assessee in default and s.201(1A)
# charges interest, so the consequence of a wrong nil sits with the DEDUCTOR —
# and "a box was ticked" answers neither who nor when.
GAP_NO_PE_DECLARATION_UNDATED = "no_pe_declaration_undated"
# Money left for a non-resident and no Form 15CA acknowledgement was recorded
# against the bill. Rule 37BB with s.195(6) wants it BEFORE the remittance.
GAP_FORM_15CA_NOT_RECORDED = "form_15ca_not_recorded"
# The deduction on this bill is the YEAR'S catch-up, not this bill's own rate
# applied to this bill's own value, so the deductee row's three money columns do
# not multiply out. Every one of them is individually right — Form 26Q's
# annexure asks for the amount paid on this date, the rate deducted under, and
# the tax deducted — but a reader checking rate x amount = tax will find it does
# not close, and a validator may say the same. The gap exists so that arrives as
# a sentence rather than as a surprise at the FVU.
GAP_TDS_IS_A_FY_CATCH_UP = "tds_is_a_fy_catch_up"
# A foreign-currency vendor payment left an unallocated remainder — an ADVANCE,
# and §194/§195 charge at credit or payment whichever is earlier — and nothing
# was withheld on it. The INR paths do withhold (migration 358); the realized-FX
# path deliberately does not, because the vendor is credited in a foreign
# currency and the tax is remitted in rupees, so the cash leg is not simply
# "amount less tax" and getting that wrong understates what the vendor was
# actually paid. Reported rather than guessed at, and rather than left silent:
# under-deducting under §195 disallows the WHOLE expenditure (§40(a)(i)).
GAP_FOREIGN_ADVANCE_NOT_WITHHELD = "foreign_advance_not_withheld"

# What each code MEANS, for the CA who has to act on it. A bare
# "no_pe_declaration_undated" on a screen is a code, not a prompt: it says
# something is wrong without saying what to do, which is how a gap list stops
# being read. Every code above must appear here — a test enforces it.
GAP_MESSAGES: dict[str, str] = {
    GAP_RESIDENCY_NOT_CLASSIFIED:
        "Nobody has recorded whether this vendor is a resident. The deduction "
        "was reported on Form 26Q, which is right for a domestic supplier — "
        "set the residential status on the vendor to confirm it, or correct it "
        "to non-resident so the deduction moves to 27Q.",
    GAP_FOREIGN_ADVANCE_NOT_WITHHELD:
        "This payment left an unallocated advance in a foreign currency, and no "
        "tax was withheld on it. §194 and §195 both charge at credit or payment, "
        "whichever is earlier, so an advance is a deduction event — but this "
        "path pays the vendor in their own currency while the tax is remitted in "
        "rupees, and the software does not compute that split. Deduct and deposit "
        "it outside the software, or record the advance as an INR payment, which "
        "does withhold.",
    GAP_27Q_IDENTIFIERS_MISSING:
        "This deduction belongs on Form 27Q, which reports the payee's country "
        "and — where there is no PAN — its tax identification number. Add them "
        "to the vendor before the quarter is filed.",
    GAP_TDS_IS_A_FY_CATCH_UP:
        "The tax deducted on this bill is the whole financial year's liability "
        "on the aggregate paid to this payee, less what earlier bills already "
        "withheld — section 194C(5) and its neighbours charge on the aggregate, "
        "so the bill that crosses a threshold carries the year's tax. The "
        "deductee row's rate multiplied by its amount will NOT equal the tax "
        "deducted, and that is correct. Check the figure against the payee's "
        "year before filing the quarter.",
    GAP_195_RATES_UNVERIFIED:
        "The section 195 rates for this financial year were reconciled against "
        "s.115A and Part II of the First Schedule but have NOT been confirmed "
        "line by line against the Finance Act. Check the rate before paying the "
        "challan.",
    GAP_RESIDENT_RATES_UNVERIFIED:
        "The TDS rates and thresholds for this bill's financial year have not "
        "been confirmed against that year's Finance Act — for a year the "
        "registry does not hold at all, another year's figures were used. "
        "Finance Act 2025 RAISED most thresholds, so an earlier year is likely "
        "UNDER-deducted, and s.40(a)(ia) disallows 30% of the expenditure. "
        "Check this deduction against that year's own rates before the quarter "
        "is filed.",
    GAP_NO_PE_DECLARATION_UNDATED:
        "Nil was withheld on the payee having no permanent establishment in "
        "India, but the declaration has no date or nobody recorded who "
        "obtained it. s.201(1) makes a deductor who fails to deduct an assessee "
        "in default — record the date and the reference on the vendor.",
    GAP_FORM_15CA_NOT_RECORDED:
        "No Form 15CA acknowledgement is recorded against this remittance. "
        "Rule 37BB with s.195(6) wants it before the money leaves, and Part D "
        "covers a remittance that is not taxable. File it on the portal and "
        "record the acknowledgement number on the bill.",
}


def describe_gaps(codes) -> list[dict]:
    """Turn gap codes into something a CA can act on: {code, message} per gap.

    Unknown codes survive with an empty message rather than being dropped — a
    gap the caller cannot phrase is still a gap, and silently losing it would
    be the failure this whole mechanism exists to prevent.
    """
    return [{"code": c, "message": GAP_MESSAGES.get(c, "")} for c in (codes or [])]


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


#: The one section the registry holds a row for that a VENDOR may never carry.
#: section_rates.py's entry for it is `TDSSectionRule(0, 0, 0)` and that file's
#: own docstring calls it a sentinel, present so a lookup succeeds — salary is
#: slab-based and lives in domain/income_tax/statutory_rates.py. resolve_tds
#: therefore answers `applies=True, rate_bps=0, tds_paise=0` for it, which is a
#: SILENT NIL: the bill saves, the rate is stored as 0, the explanation reads
#: "s.192 at 0%", and tds_register_service writes no row and no gap because
#: nothing was deducted. A vendor bill is never salary.
SECTION_192_SALARY = "192"

#: Deductions made by a property BUYER, which this software cannot file. Kept
#: as a set rather than tested by name in the message, so adding s.194-IC or
#: s.194M later is a one-line change beside the reason rather than a new branch.
_PROPERTY_SECTIONS = frozenset({"194IA", "194-IA", "194IB", "194-IB"})

#: TCS, which is not a deduction and does not belong on a vendor.
#:
#: §206C is in the registry — its own comment says why, and says what it is:
#: "reference data only; do not assume TCS is an implemented feature because a
#: rate exists here". Nothing refused it at the vendor master, so a CA could
#: pick it off the supplier screen's section list (which is served straight
#: from the registry) and every bill from that vendor would withhold 0.1% of
#: the whole amount — the entry's threshold is ZERO, so it fires on the first
#: rupee — and the row would be stamped 26Q by `return_type_for`, which routes
#: on residency and never sees the section.
#:
#: Three things are wrong with that at once, and they are the same three the
#: docstring below already sets out for §194-IA:
#:
#:   * DIRECTION. §206C(1H) is collected BY A SELLER FROM A BUYER. A client
#:     paying a vendor collects nothing; if the VENDOR collects TCS from our
#:     client, it is the vendor's own liability and appears on the vendor's
#:     27EQ, never on ours.
#:   * STATEMENT. TCS is reported on 27EQ. `tds_deductions.return_type` CHECKs
#:     ('24Q','26Q','27Q','27EQ'), so 26Q is accepted and simply wrong — the
#:     one failure mode the CHECK cannot catch.
#:   * NOTHING COMPUTES IT. The registry entry is unread by any TCS path;
#:     there is no collection tracking and no 27EQ builder.
#:
#: Refused here rather than removed from the registry: the rate is real
#: HISTORIC reference data — §206C(1H) ceased to operate from 01-04-2025 and
#: the registry entry says so in its own `rate_gap` (SALES-32), but a belated
#: or revised 27EQ for FY 2024-25 is still filed at 0.1% — and
#: `domain/tds/vocabulary.py` maps 206C→394 for the 2026 Act. What is refused
#: is recording it against a payee.
SECTION_206C_TCS = "206C"


def deduction_section_refusal(section: Optional[str],
                              fy: Optional[str] = None) -> Optional[str]:
    """Why the engine cannot withhold under this section at all, or None.

    A COMPANION TO section_refusal ABOVE, AND A DIFFERENT QUESTION. That one
    asks whether the section fits the PAYEE; this asks whether the engine can
    answer for the section at all, for anybody. Both belong here because both
    are "this section must not be recorded", and both return a sentence a CA
    reads rather than a code.

    WHY IT REFUSES RATHER THAN COMPUTING. Two cases, and the second is the one
    that was doing damage:

      * A section the registry does not hold. resolve_tds already raises
        ValueError for it (tds_computer.py), which reaches the CA as the bare
        string "Unknown TDS section '194IA'" at the FIRST BILL — long after the
        vendor was created, with no statute, no reason and no next step. The
        vendor master accepted it silently: VendorIn.tds_section is a bare
        Optional[str], so s.194IA, s.194R, s.194T and s.194M all save fine over
        the API, the bulk import, or any row predating the screen that stopped
        offering them.

      * s.192. Not missing from the registry — present as a sentinel, and
        therefore WORSE than missing: it computes a nil instead of raising, so
        nothing anywhere says the withholding did not happen.

    WHY NOT JUST ADD THE MISSING SECTIONS TO THE REGISTRY. For s.194IA in
    particular, a rate alone would make the engine confidently wrong in three
    directions at once: the base is the consideration OR the stamp-duty value,
    whichever is higher, and no column here holds a stamp-duty value; the
    deduction is made without a TAN, which the whole challan model assumes; and
    return_type_for() picks a statement by RESIDENCY alone, so the row would be
    stamped 26Q — reporting a property deduction on a statement it does not
    belong on, by a deductor who is not filing 26Q at all. tds_deductions.
    return_type CHECKs ('24Q','26Q','27Q','27EQ') (migration 014), so there is
    nowhere correct to put it. A 422 stops a CA; a 26Q row that looks right
    does not.

    The same call was already made one module over, on the same section:
    routers/tds_workspace.py refuses to name a form for 16B/16C because "a
    wrong form number is worse than an unchanged one".
    """
    from domain.tds.section_rates import tds_rates_for

    code = (section or "").upper().strip()
    if not code:
        return None                      # TDS off, or not recorded yet

    if code == SECTION_195:
        return None                      # s.195 has its own module and its own refusals

    if code == SECTION_192_SALARY:
        return (
            "Section 192 is salary withholding, and it cannot be recorded "
            "against a vendor. It is charged on the year's estimated salary at "
            "the slab rates, not at a flat section rate, so a bill for this "
            "vendor would deduct NOTHING and say nothing about it. Run salary "
            "through Payroll, which computes section 192 properly, and give "
            "this vendor the section that fits what they actually supply."
        )

    if code == SECTION_206C_TCS:
        return (
            "Section 206C is tax COLLECTED at source, and it cannot be "
            "recorded against a vendor. It is collected by a seller from a "
            "buyer and reported on Form 27EQ — so on a bill you are paying "
            "there is nothing to collect, and a figure withheld here would be "
            "0.1% of every rupee (the section carries no threshold) reported "
            "on Form 26Q, which is not where TCS goes. If your client COLLECTS "
            "tax on its sales, that is a separate obligation this software "
            "does not yet compute."
        )

    if code in tds_rates_for(fy).sections:
        return None

    # s.192 and s.206C are excluded from the suggestion for the same reason
    # they are refused above: offering either would answer one refusal with
    # another. s.192's failure is silent and s.206C's is on the wrong return.
    known = ", ".join(sorted(set(tds_rates_for(fy).sections)
                             - {SECTION_192_SALARY, SECTION_206C_TCS}))
    why = (
        f"This software holds no rate or threshold for section {code}, so it "
        f"cannot work out what to withhold on a bill for this vendor. The "
        f"sections it can compute are: {known}. "
    )
    if code in _PROPERTY_SECTIONS:
        # Named, because these two are the ones a CA reaches for first and a
        # rate alone would not fix them. Only what this repository proves is
        # asserted: the certificate side already refuses to name their form
        # (routers/tds_workspace.py's _CERTIFICATE_KIND deliberately omits 16B
        # and 16C), and return_type_for() picks a statement by RESIDENCY alone
        # while tds_deductions.return_type CHECKs ('24Q','26Q','27Q','27EQ') —
        # so a computed row here would be stamped 26Q, which is not where a
        # property deduction is reported.
        why += (
            f"Section {code} is also not simply a missing rate: this software "
            f"has no way to file it. Every deduction it records is routed to "
            f"24Q, 26Q, 27Q or 27EQ, and a property deduction belongs on none "
            f"of them, so a figure computed here would be reported on the "
            f"wrong return. "
        )
    return why + (
        f"Either record the section this payment actually falls under, or turn "
        f"TDS off on this vendor and deduct under section {code} outside the "
        f"bill."
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
