"""§140A self-assessment tax — what is payable, and how a short challan lands.

WHAT WAS MISSING (IT-13)

    IT Act §140A(1): where any tax is payable on the basis of a return, after
    taking into account the tax already deducted or collected, advance tax
    paid, relief under §90, §90A or §91, and credit under §115JAA or §115JD,
    the assessee "shall be liable to pay such tax together with interest and
    fee payable ... before furnishing the return and the return shall be
    accompanied by proof of payment of such tax, interest and fee".

    That proof is a Challan 280, and this product held no record of one. The
    ITR keying sheet printed `self_assessment_tax` as nil on every return and
    said why; Schedule IT asks for each challan's BSR code, date, serial number
    and amount, and a CA had them on a bank receipt and nowhere else.

THE RULE THAT MAKES THIS MORE THAN STORAGE

    §140A(1)'s own Explanation appropriates a SHORT payment in a fixed order:

        "where the amount paid ... falls short of the aggregate of the tax,
         interest and fee, the amount so paid shall first be adjusted towards
         the fee payable and thereafter towards the interest payable and the
         balance, if any, shall be adjusted towards the tax payable."

    So a challan for less than what was due is not "part paid" pro rata. It
    settles the §234F fee first, then the §234A/B/C interest, and only what is
    left reduces the TAX — which is the figure §234A and §234B keep charging
    interest on. Splitting a shortfall proportionally would under-state the tax
    still outstanding and therefore the interest still running.

    `appropriate` is that order, and it is the only arithmetic in this module.

THE CHALLAN'S OWN SPLIT DOES NOT BIND THE APPROPRIATION

    A Challan 280 carries five boxes — tax, surcharge, cess, interest, fee —
    and they are recorded because they are what the DOCUMENT says. They are
    NOT what `appropriate` reads. The Explanation's order runs off what is
    DUE, so a short payment tendered with ₹12,000 typed into the interest box
    still settles the §234F fee first where a fee is due: the provision exists
    precisely to override the payer's own labelling.

    Reading the split instead would give a taxpayer who mis-typed a box a
    different outstanding TAX, and therefore different §234A and §234B
    interest, from one who did not — on the same money, paid on the same day.
    `test_the_challans_own_split_does_not_bind_the_appropriation` pins it.

WHAT IS REFUSED RATHER THAN GUESSED

  * **The INTEREST and FEE are inputs, not derived here.** §234A, §234B and
    §234C are computed by `advance_tax_interest_engine` and shown on the
    Advance Tax screen, which asks the four facts a return cannot supply — the
    §139(1) due date, the date of furnishing, the TDS credit and any
    §89/90/91 relief. §234F is not modelled at all. Re-deriving either here
    would be a second engine that agrees with the first until it does not.
  * **§140A(3) is NAMED, not scored.** Failing to pay makes the assessee "an
    assessee in default" and §221 attaches a penalty "as the Assessing Officer
    may direct" — a discretion, not a formula, and this product does not
    invent one.
  * **Nothing is posted.** A payment of the client's OWN income tax is not a
    transaction of the books this product keeps for them unless the CA raises
    it; the challan is a record of what was paid, not a journal.
  * **The CREDIT is not netted against a later year.** §140A settles one
    return; a refund or a carry-forward is the assessment's business.

⚠️ `[S]`-graded on its CITATION rather than its effect: egress is refused at
this environment's proxy, so the Explanation's wording above is recorded from
knowledge. The ORDER it states — fee, then interest, then tax — is what the
module implements and is pinned by
`tests/test_a_short_self_assessment_challan_lands_fee_first.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: Not confirmed against the Act's text from this environment.
VERIFIED = False

UNVERIFIED_NOTE = (
    "§140A(1)'s appropriation order is recorded from knowledge, not read off "
    "the Act — this environment refuses outbound requests. It is pinned by a "
    "test. Check it before relying on the split of a short payment."
)

SECTION_140A_3_DEFAULT = (
    "§140A(3): where the tax, interest or fee is not paid in accordance with "
    "§140A(1), the assessee is deemed to be an assessee in default and §221 "
    "attaches a penalty the Assessing Officer directs. The amount is a "
    "discretion, not a formula, and is not computed here."
)

INTEREST_IS_NOT_DERIVED_HERE = (
    "The §234A, §234B and §234C figures are the Advance Tax screen's — it asks "
    "the four facts a return cannot supply, and re-deriving them here would be "
    "a second engine. §234F is not modelled at all, so a fee is whatever was "
    "recorded on the challan."
)

#: Challan 280's minor heads. 300 is self-assessment tax and is what §140A
#: pays; the other two exist because a challan records what somebody actually
#: paid under, and a CA correcting a mis-headed payment needs to say so.
SPLIT_DOES_NOT_FOOT = (
    "challan {serial}: its tax, surcharge, cess, interest and fee add up to "
    "{split}, and its total is {total}. Both figures are recorded as given — "
    "the total is what Schedule IT declares and what §140A(1) appropriates, so "
    "nothing here changes; check the entry against the bank receipt."
)

MINOR_HEAD_ADVANCE_TAX = "100"
MINOR_HEAD_SELF_ASSESSMENT = "300"
MINOR_HEAD_REGULAR_ASSESSMENT = "400"
MINOR_HEADS = (MINOR_HEAD_ADVANCE_TAX, MINOR_HEAD_SELF_ASSESSMENT,
               MINOR_HEAD_REGULAR_ASSESSMENT)

#: 0020 is a company, 0021 anybody else.
MAJOR_HEAD_COMPANY = "0020"
MAJOR_HEAD_OTHER = "0021"
MAJOR_HEADS = (MAJOR_HEAD_COMPANY, MAJOR_HEAD_OTHER)


@dataclass(frozen=True)
class Appropriation:
    """How a payment landed across §140A(1)'s three heads, in its own order."""
    towards_fee_paise: int
    towards_interest_paise: int
    towards_tax_paise: int
    #: What each head still owes after this payment.
    fee_outstanding_paise: int
    interest_outstanding_paise: int
    tax_outstanding_paise: int

    @property
    def total_applied_paise(self) -> int:
        return (self.towards_fee_paise + self.towards_interest_paise
                + self.towards_tax_paise)

    @property
    def is_fully_paid(self) -> bool:
        return (self.fee_outstanding_paise == 0
                and self.interest_outstanding_paise == 0
                and self.tax_outstanding_paise == 0)

    def to_dict(self) -> dict:
        return {
            "towards_fee_paise": self.towards_fee_paise,
            "towards_interest_paise": self.towards_interest_paise,
            "towards_tax_paise": self.towards_tax_paise,
            "fee_outstanding_paise": self.fee_outstanding_paise,
            "interest_outstanding_paise": self.interest_outstanding_paise,
            "tax_outstanding_paise": self.tax_outstanding_paise,
            "total_applied_paise": self.total_applied_paise,
            "is_fully_paid": self.is_fully_paid,
        }


def appropriate(
    *,
    paid_paise: int,
    tax_due_paise: int,
    interest_due_paise: int = 0,
    fee_due_paise: int = 0,
) -> Appropriation:
    """§140A(1)'s Explanation: fee first, then interest, then tax.

    NOT PRO RATA, and that is the whole point of the function. A challan for
    less than the aggregate settles the fee in full before a rupee reaches the
    interest, and the interest in full before a rupee reaches the tax — so what
    is still outstanding as TAX is larger than a proportional split would make
    it, and §234A and §234B go on charging interest on that larger figure.

    An OVERPAYMENT is not spread and not refused: every head goes to nil and
    the excess simply does not appear, because where it goes is the
    assessment's business rather than this return's.
    """
    remaining = max(0, int(paid_paise))
    fee_due = max(0, int(fee_due_paise))
    interest_due = max(0, int(interest_due_paise))
    tax_due = max(0, int(tax_due_paise))

    to_fee = min(remaining, fee_due)
    remaining -= to_fee
    to_interest = min(remaining, interest_due)
    remaining -= to_interest
    to_tax = min(remaining, tax_due)

    return Appropriation(
        towards_fee_paise=to_fee,
        towards_interest_paise=to_interest,
        towards_tax_paise=to_tax,
        fee_outstanding_paise=fee_due - to_fee,
        interest_outstanding_paise=interest_due - to_interest,
        tax_outstanding_paise=tax_due - to_tax,
    )


def total_paise_of(challans) -> int:
    """What a set of challans has paid towards §140A.

    THE WHOLE CHALLAN — tax, surcharge, cess, interest and fee — and not
    `tax_paise` alone, because Schedule IT's Amount column is what left the
    bank account and that is the sum §140A(1) appropriates. How it is
    appropriated ACROSS the heads is the Explanation's business and is
    `appropriate`'s, not this one's.

    It takes already-fetched ROWS rather than a database handle, so the
    keying-sheet endpoint can total the challans it has just read without a
    second Singapore-to-Mumbai round trip — and, more to the point, without a
    second definition of what "paid" means.
    """
    return sum(int(c.get("total_paise") or 0) for c in challans)


def tax_payable_on_return(
    *,
    tax_on_total_income_paise: int,
    tds_tcs_paise: int = 0,
    advance_tax_paid_paise: int = 0,
    relief_paise: int = 0,
    mat_amt_credit_paise: int = 0,
) -> int:
    """§140A(1)'s own figure: the tax payable on the basis of the return.

    The section says the tax is payable "after taking into account" the amount
    already paid under any provision (TDS and TCS), any advance tax paid, any
    relief under §90, §90A or §91, and any credit under §115JAA or §115JD. So
    this is a SUBTRACTION the statute spells out, not a computation of tax —
    the tax itself is `itr_engine`'s and is passed in.

    IT IS DELIBERATELY NOT READ OFF §234A's BASE. Explanation 1 to §234A lists
    the same reductions and the two figures coincide, but they are different
    provisions charging different things, and a later amendment to one is not
    an amendment to the other. One stated rule per section.

    FLOORED AT NIL. A return showing more credit than tax is a REFUND, and a
    refund is the assessment's business (§143(1)) — a negative "tax payable"
    would appropriate a payment against it and report a credit as settled.
    """
    return max(0, int(tax_on_total_income_paise) - int(tds_tcs_paise)
               - int(advance_tax_paid_paise) - int(relief_paise)
               - int(mat_amt_credit_paise))


@dataclass(frozen=True)
class ChallanIdentity:
    """Schedule IT's own three particulars, which together ARE the payment."""
    bsr_code: str
    deposit_date: str
    challan_serial_no: str

    def key(self) -> tuple:
        return (self.bsr_code.strip(), self.deposit_date,
                self.challan_serial_no.strip())


@dataclass
class SelfAssessmentPosition:
    """What one client-year has paid under §140A, and what is left.

    `challans` is every payment in the order it was made, because Schedule IT
    has a row for each and the order is what the appropriation walks.
    """
    financial_year: str
    challans: list = field(default_factory=list)
    total_paid_paise: int = 0
    appropriation: Optional[Appropriation] = None
    gaps: list = field(default_factory=list)
    caveats: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "financial_year": self.financial_year,
            "challans": list(self.challans),
            "total_paid_paise": self.total_paid_paise,
            "appropriation": (self.appropriation.to_dict()
                              if self.appropriation else None),
            "gaps": list(self.gaps),
            "caveats": list(self.caveats),
            "verified": VERIFIED,
        }


def position(
    *,
    financial_year: str,
    challans: list,
    tax_due_paise: Optional[int] = None,
    interest_due_paise: Optional[int] = None,
    fee_due_paise: Optional[int] = None,
) -> SelfAssessmentPosition:
    """The year's challans, their total, and — where the dues are known — how
    the aggregate lands under §140A(1).

    THE DUES ARE OPTIONAL AND THEIR ABSENCE IS NAMED. A CA may record a challan
    before the computation is finished, and refusing to list it until the tax
    is known would make the screen useless at exactly the moment it is used.
    Where no `tax_due_paise` is given the payments are reported and NOTHING is
    appropriated — an appropriation against an unknown liability would invent
    an outstanding figure.
    """
    out = SelfAssessmentPosition(financial_year=financial_year,
                                 challans=list(challans))
    out.total_paid_paise = total_paise_of(challans)
    out.caveats.append(UNVERIFIED_NOTE)

    # A challan whose five boxes do not add up to its own total. REPORTED and
    # never corrected: both figures came off a bank receipt, and silently
    # replacing one with the other would hide a keying error on the exact
    # document the return has to be accompanied by. A challan that records the
    # total alone — every box nil — is not a mismatch; it is a receipt that
    # showed only what left the account, which is the case the table's own
    # header says must stay recordable.
    for c in challans:
        split = (int(c.get("tax_paise") or 0) + int(c.get("surcharge_paise") or 0)
                 + int(c.get("cess_paise") or 0) + int(c.get("interest_paise") or 0)
                 + int(c.get("fee_paise") or 0))
        total = int(c.get("total_paise") or 0)
        if split and split != total:
            out.gaps.append(SPLIT_DOES_NOT_FOOT.format(
                serial=str(c.get("challan_serial_no") or "?"),
                split=split, total=total))

    mis_headed = [c for c in challans
                  if str(c.get("minor_head") or MINOR_HEAD_SELF_ASSESSMENT)
                  != MINOR_HEAD_SELF_ASSESSMENT]
    if mis_headed:
        out.gaps.append(
            f"{len(mis_headed)} challan(s) here carry a minor head other than "
            f"300. Minor head 300 is self-assessment tax; 100 is advance tax "
            f"and 400 is tax on regular assessment, and a payment made under "
            f"the wrong head is credited to the wrong demand until it is "
            f"corrected with the assessing officer.")

    if tax_due_paise is None:
        out.gaps.append(
            "No tax due is stated, so nothing is appropriated. §140A(1) "
            "settles the fee, then the interest, then the tax — an order that "
            "cannot be applied to a liability nobody has computed. Compute the "
            "return first.")
        return out

    out.caveats.append(INTEREST_IS_NOT_DERIVED_HERE)
    out.appropriation = appropriate(
        paid_paise=out.total_paid_paise,
        tax_due_paise=tax_due_paise,
        interest_due_paise=interest_due_paise or 0,
        fee_due_paise=fee_due_paise or 0)
    if not out.appropriation.is_fully_paid:
        out.gaps.append(SECTION_140A_3_DEFAULT)
    return out
