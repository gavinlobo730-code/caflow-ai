"""
CGST Rule 59(2) — the Invoice Furnishing Facility, for months 1 and 2 of a
QRMP quarter.

WHY IT EXISTS, IN ONE PARAGRAPH

    A QRMP taxpayer — the proviso to CGST §39(1) with Rule 61A, which is a
    large share of a small practice's book — furnishes GSTR-1 once a quarter.
    Their customer's input tax credit rests on §16(2)(aa): the SUPPLIER's
    furnished invoice, communicated to the recipient in GSTR-2B. So a January
    invoice from a quarterly filer reaches the buyer's 2B in April, and the
    buyer finances the tax for three months. Rule 59(2) is the way out — for
    the FIRST and SECOND months of a quarter the supplier may furnish the
    documents to a REGISTERED person alone, between the 1st and the 13th of
    the following month, and the credit arrives on time.

    `return_period.IFF_NOT_BUILT` said this product did not produce it, on
    every quarterly GSTR-1, which was true and is what this module ends. The
    facility is OPTIONAL in the strict sense — nothing is owed if it is not
    used — so nothing here refuses a return or raises a deadline. What is lost
    by not using it is the CUSTOMER's working capital, which is why B2B
    clients ask their accountant for it by name.

WHAT IS IN IT, DERIVED FROM THE RULE'S OWN WORDS

    The sub-rule reaches "the details of such outward supplies of goods or
    services or both **to a registered person**". That sentence, and not a
    remembered list of portal tiles, is what decides every section here:

      * B2B — Tables 4A, 4B, 4C and, inside the same GSTN `b2b` section,
        6B (SEZ) and 6C (deemed export). An SEZ unit and a deemed-export
        recipient are both REGISTERED persons, so the rule reaches them, and
        they need no special case because `B2B_SECTION_CATEGORIES` already
        groups them.
      * CDNR — a credit or debit note to a registered person, Table 9B.

    and what it does NOT reach:

      * B2CS and B2CL, because an unregistered recipient claims no credit and
        the rule does not name them;
      * CDNUR, for the same reason — a note to an unregistered person. The
        finding's own suggested fix named `cdnur` among the sections to emit,
        and the rule's words are against it: nothing is furnished early for a
        recipient who has nothing to furnish it for;
      * EXP, because an export is a supply to a person outside India, who is
        not a registered person under this Act;
      * NIL, HSN (Table 12) and DOC_ISSUE (Table 13), which are PERIOD
        summaries of everything the period contained. A summary of a
        two-thirds-omitted period is not a smaller summary, it is a wrong one,
        and each belongs to the quarterly return that actually covers the
        period.

    Every one of those is NAMED in `SECTIONS_NOT_IN_IFF` rather than silently
    absent, because a CA comparing this against their sales register has to
    know an export is missing on purpose.

WHAT IS REFUSED RATHER THAN GUESSED

    * AMENDMENTS. The portal shows amended-B2B and amended-CDNR tiles inside
      the facility, and whether the facility accepts them could not be checked
      from this environment — every `.gov.in` is refused at the egress proxy.
      The direction of the error decides it: an amendment left out of an IFF
      is furnished in the quarterly return a few weeks later, which is slow;
      an amendment section the facility does not carry is an upload that fails
      or, worse, is accepted against the wrong period. So amendments are
      NAMED, not emitted. `domain/gst/amendments` remains the one place a
      §37(3) amendment is built.
    * THE PAYLOAD'S OWN ENVELOPE. GST-32's refusal, unchanged and for its own
      reason: a wrong field NAME fails visibly at the portal, while a
      misremembered field MEANING produces a real document with wrong figures.
      What this builds is the SECTIONS, reusing `gstr1_builder`'s own
      builders, so the field names and meanings are the ones the GSTR-1 path
      is already tested on. Nothing is transmitted.

⚠️ `VERIFIED` is False. The window, the cap and the two-month scope are
written from the notifications named here rather than read off them. A test
pins each one exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from domain.gst.classifier import GSTInvoiceCategory, B2B_SECTION_CATEGORIES
from domain.gst.gstr1_builder import (
    InvoiceForGSTR1, _build_b2b, _build_cdnr, _paise_to_rupees,
)

#: Every figure and window below is written from knowledge. Egress is refused
#: at this environment's proxy, so none could be read off the rule.
VERIFIED = False

#: Rule 59(2): "up to a cumulative value of fifty lakh rupees in each month".
#: ₹50,00,000 in paise. [S]
CUMULATIVE_CAP_PAISE = 50_00_000 * 100

#: The 1st to the 13th of the month succeeding the month furnished for. The
#: DUE DATE itself is `compliance_engine.iff_due_date`, which is the authority
#: and is deliberately not restated here — this is the opening day, which that
#: function has no reason to carry.
WINDOW_OPENS_DAY = 1
WINDOW_CLOSES_DAY = 13

#: Only the first two months of a quarter. The third month's documents are in
#: the quarterly GSTR-1 itself, so furnishing them here would declare them
#: twice.
MONTHS_IN_QUARTER_WITH_IFF = (1, 2)

#: What the facility carries, in the GSTN section names `gstr1_builder` emits.
SECTIONS_IN_IFF = ("b2b", "cdnr")

#: What it does not, each with the reason, so a CA comparing this against the
#: sales register knows the absence is the rule's and not a defect. Keyed on
#: the GSTN section name.
SECTIONS_NOT_IN_IFF = {
    "b2cs": "Rule 59(2) reaches supplies to a REGISTERED person. A supply to "
            "an unregistered person claims no input tax credit, so there is "
            "nothing for early furnishing to release; it is declared in the "
            "quarterly GSTR-1.",
    "b2cl": "Rule 59(2) reaches supplies to a REGISTERED person. A large "
            "inter-state supply to an unregistered person is declared in the "
            "quarterly GSTR-1.",
    "cdnur": "A credit or debit note to an UNREGISTERED person. The rule "
             "reaches documents to a registered person only.",
    "exp": "An export is a supply to a person outside India, who is not a "
           "registered person under this Act. Table 6A is filed with the "
           "quarterly GSTR-1, and a refund under Rule 96(1) is matched "
           "against the shipping bill rather than against this facility.",
    "nil": "Table 8 is a summary of the whole period's nil-rated, exempt and "
           "non-GST supplies. A summary covering one month of a quarter is "
           "not a smaller summary, it is a wrong one.",
    "hsn": "Table 12 is a period summary (Notification 78/2020-Central Tax), "
           "and is filed with the return that covers the period.",
    "doc_issue": "Table 13 declares the serial RANGES issued in the period. A "
                 "range covering one month of a quarter would leave gaps that "
                 "are not gaps.",
}

#: Amendments — refused, with the direction of the error stated. See the module
#: header.
AMENDMENTS_NOT_BUILT = (
    "Amendments to a document already furnished are not produced here. "
    "Whether this facility accepts an amendment section could not be verified "
    "from this environment, and the safe direction is to leave it out: an "
    "amendment omitted is furnished a few weeks later in the quarterly "
    "GSTR-1, while a section the facility does not carry fails at upload or "
    "is accepted against the wrong period."
)

#: What the cap is measured on, said out loud because two readings exist and
#: the rule does not spell one out here. [S]
CAP_BASIS = (
    "The cumulative value is measured on each document's own INVOICE VALUE — "
    "taxable value plus tax plus cess — which is the figure the `val` field "
    "of the furnished document carries. Rule 59(2) says 'cumulative value' "
    "without defining it in the sub-rule; the taxable value alone is the other "
    "reading, and it is SMALLER, so measuring on the invoice value is the "
    "reading that cannot silently let a month through."
)

#: The facility is optional, so nothing refuses on the cap. Said on every
#: answer that carries one.
CAP_EXCEEDED_NOTE = (
    "Rule 59(2) allows the facility to be used 'as he may consider necessary' "
    "— the supplier chooses WHICH documents to furnish — so the excess is "
    "reported and nothing is dropped. Selecting a subset that fits is the "
    "CA's decision; furnishing a set this product had silently trimmed would "
    "not match the sales register and there would be nothing on screen saying "
    "what was left out."
)


def month_has_iff(month_in_quarter: int) -> bool:
    """Is this month of a quarter one the facility reaches?

    Takes the POSITION in the quarter (1, 2 or 3), which
    `compliance_engine.gst_period_month_in_quarter` answers — not a calendar
    month, because which calendar months make a quarter is a fact about the
    financial year that `core.ist_clock.fy_quarters` already owns and that
    nothing here should restate.
    """
    return month_in_quarter in MONTHS_IN_QUARTER_WITH_IFF


def document_value_paise(inv: InvoiceForGSTR1) -> int:
    """One document's value for the cap — see CAP_BASIS.

    Round-off is included because it is part of the printed total and of the
    `val` this document is furnished with; leaving it out would make the cap
    measured on a figure that appears nowhere.
    """
    return (inv.taxable_amount_paise + inv.cgst_paise + inv.sgst_paise
            + inv.igst_paise + inv.cess_paise + inv.round_off_paise)


@dataclass
class IFFPayload:
    """One month's Invoice Furnishing Facility.

    `payload` carries only the sections Rule 59(2) reaches. `not_carried` is
    the rest of the GSTR-1 named with its reason — a CA reconciling this
    against the register must be able to tell a deliberate absence from a
    dropped document, which is what `gaps` is for on the GSTR-1 side and what
    this is for here.
    """
    gstin: str
    period: str                      # MMYYYY of the month furnished FOR
    payload: dict
    summary: dict
    document_count: int
    cumulative_value_paise: int
    cap_paise: int
    cap_exceeded: bool
    excess_paise: int
    not_carried: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def build_iff(
    invoices: Sequence[InvoiceForGSTR1],
    gstin: str,
    period: str,
    month_in_quarter: Optional[int] = None,
) -> IFFPayload:
    """Build one month's IFF from the same classified documents GSTR-1 is built
    from.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT

    `month_in_quarter` is the position (1, 2 or 3) this month holds in its
    quarter. It is a PARAMETER rather than derived here because the answer
    depends on the financial year's own quarters, which `core.ist_clock` owns;
    passing None means the caller has not established it, and the build goes
    ahead with a note rather than refusing — a CA may legitimately want to see
    what a month would furnish before deciding.

    A month the facility does NOT reach — the third of a quarter — is refused,
    because furnishing it would declare the same documents twice: once here
    and once in the quarterly GSTR-1 that already covers it.
    """
    if month_in_quarter is not None and not month_has_iff(month_in_quarter):
        raise ValueError(
            "The third month of a quarter has no Invoice Furnishing Facility "
            "(CGST Rule 59(2)). Its documents are declared in the quarterly "
            "GSTR-1 itself, so furnishing them here would declare them twice."
        )

    # The SAME grouping the quarterly return uses. Restating either predicate
    # would be a second answer to "is this a supply to a registered person",
    # and the two would disagree the first time a category was added.
    b2b_invoices = [i for i in invoices
                    if i.gst_invoice_category in B2B_SECTION_CATEGORIES]
    cdnr_invoices = [i for i in invoices
                     if i.gst_invoice_category == GSTInvoiceCategory.CDNR]

    # An SEZ or deemed-export document with no recipient GSTIN cannot be
    # declared — `ctin` is what the recipient's own return matches on — and is
    # held out here exactly as `build_gstr1` holds it out, with the same test.
    declarable_b2b = [i for i in b2b_invoices
                      if i.party_gstin
                      or i.gst_invoice_category is GSTInvoiceCategory.B2B]

    payload: dict = {"gstin": gstin, "fp": period}
    b2b = _build_b2b(declarable_b2b)
    if b2b:
        payload["b2b"] = b2b
    cdnr = _build_cdnr(cdnr_invoices)
    if cdnr:
        payload["cdnr"] = cdnr

    furnished = declarable_b2b + cdnr_invoices
    cumulative = sum(document_value_paise(i) for i in furnished)
    exceeded = cumulative > CUMULATIVE_CAP_PAISE

    not_carried: list[dict] = []
    for section, reason in SECTIONS_NOT_IN_IFF.items():
        not_carried.append({"section": section, "reason": reason})

    notes = [AMENDMENTS_NOT_BUILT, CAP_BASIS]
    if month_in_quarter is None:
        notes.append(
            "Which month of its quarter this is was not established, so "
            "whether the facility is available for it has not been checked. "
            "The third month of a quarter has none.")
    if exceeded:
        notes.append(CAP_EXCEEDED_NOTE)

    # A document held out of the b2b section for want of a recipient GSTIN is
    # NAMED, the `gaps` discipline: it is a real supply to a registered person
    # that this facility cannot carry, and silence would read as "there were
    # none".
    for inv in b2b_invoices:
        if inv in declarable_b2b:
            continue
        not_carried.append({
            "section": "b2b",
            "reference_no": inv.reference_no,
            "reason": (
                "A supply to an SEZ or a deemed export is declared against the "
                "RECIPIENT's GSTIN, and none is recorded on this document. "
                "Record it, or the supply waits for the quarterly return."),
        })

    summary = {
        "period": period,
        "gstin": gstin,
        "counts": {
            "b2b": sum(len(g["inv"]) for g in b2b),
            "credit_notes_registered": len(cdnr_invoices),
        },
        "cumulative_value_rupees": _paise_to_rupees(cumulative),
        "cap_rupees": _paise_to_rupees(CUMULATIVE_CAP_PAISE),
    }

    return IFFPayload(
        gstin=gstin,
        period=period,
        payload=payload,
        summary=summary,
        document_count=len(furnished),
        cumulative_value_paise=cumulative,
        cap_paise=CUMULATIVE_CAP_PAISE,
        cap_exceeded=exceeded,
        excess_paise=max(0, cumulative - CUMULATIVE_CAP_PAISE),
        not_carried=not_carried,
        notes=notes,
    )
