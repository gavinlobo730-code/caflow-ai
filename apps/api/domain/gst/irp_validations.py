"""
What the INVOICE REGISTRATION PORTAL will accept, which is not what the Act allows.

GST-32. CGST Rule 46 says what a tax invoice must CONTAIN and Rule 46(b) says
what its serial number may look like; the IRP is a piece of software with its
own, STRICTER acceptance rules, and a document that satisfies the Act and fails
them comes back as an error code with no explanation a CA can act on. Two
authorities, and this module is the second one.

THE ONE THAT PROVES IT IS THE DOCUMENT NUMBER, AND IT IS LIVE TODAY

    Rule 46(b) allows "alphabets or numerals or special characters hyphen or
    dash and slash ... and any combination thereof", up to sixteen characters.
    The IRP's own published expression is

        Document_Num   ^([a-zA-Z1-9]{1}[a-zA-Z0-9/-]{0,15})$

    and the first character class is NOT the second: a letter or a digit ONE TO
    NINE. Not `0`, not `-`, not `/`. So `0001`, `-INV-1` and `/2026/1` are legal
    invoice numbers that the IRP refuses.

    `0001` is not hypothetical. `invoice_settings` carries a prefix and a
    padding, and a firm with an empty prefix and the financial year switched off
    gets exactly `0001` from `sales_numbering_service.suggest` — offered to the
    CA, written on the document, and rejected at the portal on every invoice of
    the year.

IT REPORTS. IT NEVER REFUSES, AND IT IS ASKED OF THE RIGHT DOCUMENTS

    Rule 46(b) is the Act and `invoice_series.format_violation` refuses against
    it at every door. These rules reach only a supply that must carry an IRN —
    `domain/gst/irn_scope` decides which — and a client below the notified
    threshold may number their invoices `0001` for ever without breaking
    anything. Refusing here would refuse a lawful document over a portal this
    product does not even reach.

    So the answer is a list of findings, shown where an IRN is being prepared,
    and `invoice_series` is untouched.

THE PAYLOAD IS STILL REFUSED, AND THAT IS NOT INCONSISTENT

    GST-32's refusal stands: this product does not build the IRP or EWB JSON,
    because a misremembered field MEANING generates a real document with wrong
    figures while a wrong field NAME merely fails visibly at the portal. What
    this module does is narrower and checkable — it asks whether a VALUE this
    product already holds would be accepted in a field, and every rule is
    transcribed from a document committed in this repository.

PROVENANCE

    `docs/compliance/sources/e-invoice/field-regular-expressions.txt` (the
    GSTN-published expressions, Sr. 1.1, 3.1.1, 10.3, A.1.2.2) and
    `…/generate-irn-api-and-validations.txt` ("Validations on Items"). Both were
    fetched by hand on 18-09-2026 and read; every expression below is copied
    from them character for character and pinned by a test. That makes this the
    second place in the GST domain graded on PROVENANCE rather than on memory —
    `late_filing.SECTION_50_3_RATE_VERIFIED` is the first — and it is a claim
    about where the rule came from, not about how confident anyone is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

#: A primary document was read for every rule in this module.
VERIFIED = True

#: Sr. 1.1 Document_Num, and Sr. 3.1.1 Preceding_Document_Number — the same
#: expression, because a credit note's reference to its original is a document
#: number too. Copied exactly; the sixteen-character cap agrees with Rule 46(b)
#: and the FIRST CHARACTER CLASS does not appear in the rule at all.
DOCUMENT_NUMBER_RE = re.compile(r"^([a-zA-Z1-9]{1}[a-zA-Z0-9/-]{0,15})$")

#: Sr. 10.3 Trans_Doc_No. — DELIBERATELY DIFFERENT and not a typo to harmonise.
#: It admits a leading `0` and sets no length cap, because a transporter's
#: document is somebody else's numbering and the IRP does not govern it. A test
#: asserts the two expressions differ.
TRANSPORT_DOCUMENT_NUMBER_RE = re.compile(r"^[a-zA-Z0-9]{1}[a-zA-Z0-9-/]*$")

#: Sr. A.1.2.2 HSN_Code. `domain/gst/hsn_digits.is_a_code` is the reader and
#: states the same rule; this is where it comes from.
HSN_CODE_RE = re.compile(r"^[0-9]*$")

#: "Each item needs to have valid HSN code with at least 4 digits."
MINIMUM_HSN_DIGITS = 4


@dataclass(frozen=True)
class Finding:
    """One thing the IRP would refuse, and where the rule comes from.

    `field` is the IRP's own name for it, so a CA reading the portal's error
    beside this sentence can see they are about the same thing.
    """

    field: str
    value: str
    reason: str
    source: str


#: Why an IRN cannot be asked for at all, as against a value being wrong.
_NUMBER_FIRST_CHARACTER = (
    "The e-invoice portal accepts a document number beginning with a LETTER or "
    "a digit 1-9 only ({expr}), so a leading '{first}' is refused — although "
    "CGST Rule 46(b) permits it. Change the series prefix or the starting "
    "number; the invoice itself is lawful and only the IRN is blocked."
)

_SOURCE_REGEX = ("GSTN published field expressions, Sr. {sr} "
                 "(docs/compliance/sources/e-invoice/field-regular-expressions.txt)")
_SOURCE_ITEMS = ("Generate IRN API, \"Validations on Items\" "
                 "(docs/compliance/sources/e-invoice/generate-irn-api-and-validations.txt)")


def document_number_finding(number: Optional[str], *,
                            field: str = "DocDtls.No",
                            sr: str = "1.1") -> Optional[Finding]:
    """Why the IRP would refuse this document number, or None.

    Says WHICH limb failed rather than restating the expression, because the
    two that a legal Rule 46(b) number can fail are different things to go and
    fix: a first character is the numbering SERIES, a length is the prefix.
    """
    clean = (number or "").strip()
    if not clean:
        return Finding(field=field, value="",
                       reason=("No document number. The e-invoice portal requires "
                               "one, and CGST Rule 46(b) makes it a particular of "
                               "the invoice."),
                       source=_SOURCE_REGEX.format(sr=sr))
    if DOCUMENT_NUMBER_RE.match(clean):
        return None
    first = clean[0]
    if not re.match(r"[a-zA-Z1-9]", first):
        return Finding(
            field=field, value=clean,
            reason=_NUMBER_FIRST_CHARACTER.format(
                expr=DOCUMENT_NUMBER_RE.pattern, first=first),
            source=_SOURCE_REGEX.format(sr=sr))
    if len(clean) > 16:
        return Finding(
            field=field, value=clean,
            reason=(f"{len(clean)} characters; the e-invoice portal accepts "
                    f"sixteen, as does CGST Rule 46(b)."),
            source=_SOURCE_REGEX.format(sr=sr))
    bad = sorted({c for c in clean[1:] if not re.match(r"[a-zA-Z0-9/-]", c)})
    return Finding(
        field=field, value=clean,
        reason=(f"contains {', '.join(repr(c) for c in bad)}; the e-invoice "
                f"portal accepts letters, digits, '-' and '/' only, as does "
                f"CGST Rule 46(b)."),
        source=_SOURCE_REGEX.format(sr=sr))


def hsn_finding(code: Optional[str], *, line_no: int) -> Optional[Finding]:
    """Why the IRP would refuse this line's HSN, or None.

    TWO LIMBS AND THEY ARE NOT THE SAME AS THE NOTIFICATION'S. Notification
    78/2020 asks how many digits a RETURN must carry and lets a B2C supply
    carry none; the IRP asks for at least four on EVERY item of every document
    it registers. So a B2C-shaped line that owes no HSN under the notification
    still cannot be registered without one — and a document the IRP registers
    is never B2C anyway (Rule 48(4) reaches registered recipients, exports and
    SEZ), which is why the two rules can differ without contradicting.
    """
    clean = (code or "").strip()
    field = f"ItemList[{line_no}].HsnCd"
    if not clean:
        return Finding(field=field, value="",
                       reason=(f"no HSN or SAC code. The e-invoice portal requires "
                               f"one of at least {MINIMUM_HSN_DIGITS} digits on "
                               f"every item."),
                       source=_SOURCE_ITEMS)
    if not HSN_CODE_RE.match(clean):
        return Finding(field=field, value=clean,
                       reason=(f"is not a code — the e-invoice portal's own field "
                               f"rule is {HSN_CODE_RE.pattern}, digits only, and it "
                               f"refuses anything else as error 2176."),
                       source=_SOURCE_REGEX.format(sr="A.1.2.2"))
    if len(clean) < MINIMUM_HSN_DIGITS:
        return Finding(field=field, value=clean,
                       reason=(f"has {len(clean)} digits; the e-invoice portal "
                               f"requires at least {MINIMUM_HSN_DIGITS} on every "
                               f"item, whatever the return's own requirement is."),
                       source=_SOURCE_ITEMS)
    return None


#: "Quantity and Unit Quantity Code are mandatory for Goods and optional for
#: Services." Askable since migration 411 gave `client_sales_invoice_lines` an
#: `is_service`; before that the column did not exist, so a service line with
#: no unit and a goods line missing one were the same row.
#:
#: THE THIRD STATE IS NOT A FAILURE. `None` means nobody recorded what kind of
#: supply the line is, and both guesses are wrong in opposite directions —
#: reading it as goods demands a UQC on every professional's fee line, reading
#: it as a service waives a particular CGST Rule 46(h) asks for. So it is
#: reported as unrecorded, in its own sentence, and the CA decides.
_UNIT_RULE = (
    "the e-invoice portal makes quantity and Unit Quantity Code mandatory for "
    "a supply of GOODS and optional for services, and CGST Rule 46(h) asks for "
    "them on goods")


def goods_unit_finding(*, is_service: Optional[bool], unit: Optional[str],
                       line_no: int) -> Optional[Finding]:
    """Why the IRP would refuse this line's unit, or None.

    `is_service` is the RESOLVED answer from `domain/gst/goods_or_services`,
    not the stored column: a SAC is Chapter 99 of the tariff, so the code itself
    answers for almost every line and reading the column alone would report
    "nobody said" against `998313`. `None` is the third state — no recorded
    value AND no code that can say — which this reports rather than resolving.

    The quantity itself is not checked: it is `NUMERIC(10,3) NOT NULL DEFAULT 1`
    on every line table, so it is never absent, and `domain/quantity` already
    refuses a fourth decimal at six doors.
    """
    field = f"ItemList[{line_no}].Unit"
    clean = (unit or "").strip()
    if clean:
        return None
    if is_service is True:
        return None
    if is_service is False:
        return Finding(field=field, value="",
                       reason=(f"no unit of measure on a line recorded as GOODS — "
                               f"{_UNIT_RULE}."),
                       source=_SOURCE_ITEMS)
    return Finding(
        field=field, value="",
        reason=(f"no unit of measure, and this line does not say whether it is "
                f"a supply of goods or of services — {_UNIT_RULE}. Record which "
                f"it is on the line rather than leaving the portal to decide."),
        source=_SOURCE_ITEMS)


def assess(*, document_number: Optional[str],
           hsn_codes: Sequence[Optional[str]] = (),
           units: Sequence[Optional[str]] = (),
           is_service_flags: Sequence[Optional[bool]] = (),
           preceding_document_number: Optional[str] = None) -> list[Finding]:
    """Everything the IRP would refuse about the values this product holds.

    `hsn_codes` is one entry per line IN ORDER, so the field name carries the
    line's position the way the payload would — a CA given "one of your HSN
    codes is wrong" has to read all of them.

    A caller passing NO lines gets the document-level findings only, which is
    honest rather than clean: it means nobody supplied them.
    """
    out: list[Finding] = []
    found = document_number_finding(document_number)
    if found:
        out.append(found)
    if preceding_document_number is not None:
        found = document_number_finding(
            preceding_document_number, field="RefDtls.PrecDocDtls.InvNo", sr="3.1.1")
        if found:
            out.append(found)
    for i, code in enumerate(hsn_codes):
        found = hsn_finding(code, line_no=i)
        if found:
            out.append(found)
    # ZIPPED against `units` rather than indexed into it: a caller that knows
    # the HSN codes and not the units is answered about the codes only, which
    # is honest rather than reporting a missing unit on a line nobody described.
    for i, (unit, svc) in enumerate(zip(units, is_service_flags)):
        found = goods_unit_finding(is_service=svc, unit=unit, line_no=i)
        if found:
            out.append(found)
    return out


#: WHAT THIS MODULE DELIBERATELY DOES NOT HOLD, each with its own reason. A
#: rule with no reader is the `public.tds_section_limits` shape — a constant
#: whose name promises to be the authority, kept in step with nothing — so the
#: published expressions for amounts, dates, phones and e-mail addresses are
#: NOT transcribed here: they describe a payload GST-32 refuses to build, so
#: nothing would ask them.
NOT_HELD = {
    "the HSN master": (
        "Error 2176 is the portal checking the code against the GST master, "
        "not against a pattern. This product does not hold that master and a "
        "four-digit numeric code can still be one the portal has never heard "
        "of — so a clean answer here is not a promise of acceptance."),
    "IsServc against the HSN class": (
        "\"If Is Service is selected, then the HSN codes must belong to "
        "services\" — which needs the HSN master above. Migration 411 gave the "
        "line an `is_service` and `goods_unit_finding` uses it, so this is the "
        "half that is still refused, and it is refused on the MASTER rather "
        "than on the flag."),
    "the payload's own field expressions": (
        "Amounts, dates, phone numbers and e-mail addresses each have a "
        "published expression, and every one of them describes a field in a "
        "JSON document this product does not produce (GST-32). Holding them "
        "would be reference data with no reader."),
    "arithmetic the portal re-computes": (
        "The IRP recomputes each item's taxable value against quantity x rate "
        "and the document totals against the items, and returns its own error "
        "codes. This product computes both through `domain/sales/line_tax` "
        "and they agree by construction; a second implementation here would "
        "be a third answer to one question."),
}

#: The IRP's quantity expression is `^\\d+.?\\d{0,3}$` — three decimals, which
#: is the same bound `domain/quantity.quantity_violation` derives from the
#: `NUMERIC(10,3)` columns. Recorded rather than implemented: the column rule
#: already refuses a fourth decimal at six doors, so a second check here would
#: fire on nothing, and the corroboration is the useful half.
QUANTITY_DECIMALS_AGREE_WITH_THE_COLUMN = 3
