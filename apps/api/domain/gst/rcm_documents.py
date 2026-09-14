"""The two documents a reverse-charge purchase owes, and they are not one rule
(PUR-19).

WHAT WAS MISSING
    The reverse-charge ACCOUNTING is complete. `_compute_bill_lines_and_totals`
    keeps the tax out of what the vendor is owed, `phase2_journal_service`
    self-accounts the output liability per head, and GSTR-3B declares it at
    3.1(d) with the credit at Table 4(A)(3) or 4(A)(5). What the product never
    produced is the two DOCUMENTS the CGST Act makes the RECIPIENT issue — and
    on an inward supply from an unregistered person the self-invoice IS the
    document the credit rests on (Rule 36(1)(b) with s.16(2)(a)), so the
    product claimed a credit it could not evidence.

THE TWO ARE DIFFERENT RULES AND THE DIFFERENCE IS THE WHOLE MODULE
    s.31(3)(f) — the SELF-INVOICE — is limited by its own words to a supply
    received "from the supplier who is NOT REGISTERED on the date of receipt of
    goods or services or both". A registered goods transport agency or advocate
    issues their own tax invoice marked payable on reverse charge; a
    self-invoice against it would be a second document for one supply.

    s.31(3)(g) — the PAYMENT VOUCHER — carries no such limb. It is due "at the
    time of making payment to the supplier" on every s.9(3)/(4) liability,
    registered supplier or not.

    So the self-invoice is a fact about the BILL and asks whether the vendor is
    registered; the payment voucher is a fact about the PAYMENT and does not.
    One "RCM document" answering both would be wrong about one of them, and
    that is the defect this module exists to make unwritable.

THE REGISTRATION QUESTION HAS THREE ANSWERS
    A GSTIN recorded and well-formed IS the registration — s.25 issues one on
    registration, and that is exactly what s.31(3)(f) asks about. A GSTIN
    ABSENT means only that nobody recorded one, which is not the same as having
    established that the supplier is unregistered;
    `vendors.gst_registration_status` (migration 388, nullable, no default) is
    where that is recorded, and a NULL is a NAMED GAP rather than either guess.
    Guessing "unregistered" mints a document the Act does not ask for; guessing
    "registered" withholds the one the credit rests on.

    A GSTIN recorded but MALFORMED is also the gap, not a registration. GST-29
    refuses a malformed GSTIN at every door a human types one, so a malformed
    value in the table is legacy data — somebody's typo, and a typo is evidence
    of nothing. Naming it is also the actionable answer: the vendor screen
    validates now, so the fix is one edit.

    NOT MODELLED, and said rather than hidden: a registration CANCELLED before
    the date of receipt. s.31(3)(f) asks whether the supplier was registered ON
    THAT DATE, and cancellation is a fact about the portal that no ledger here
    holds.

WHAT IS NOT DECIDED HERE
    WHETHER s.9(3) or s.9(4) applies. `purchase_bills.is_reverse_charge` is the
    CA's own answer and this module reads it. s.9(4) has bound only notified
    classes of registered person since 01-02-2019, which is a fact about the
    client's business rather than about the bill.

    [S] The consolidated month-end self-invoice the old proviso to s.31(3)(f)
    allowed for small-value s.9(4) supplies is NOT built. It was tied to the
    withdrawn Notification 8/2017-Central Tax (Rate) exemption and could not be
    confirmed from this environment, whose proxy refuses every .gov.in. One
    document per bill is never wrong; a consolidated one is only sometimes
    allowed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ── The two kinds ────────────────────────────────────────────────────────────

KIND_SELF_INVOICE = "self_invoice"
KIND_PAYMENT_VOUCHER = "payment_voucher"
KINDS = (KIND_SELF_INVOICE, KIND_PAYMENT_VOUCHER)

#: The charging provision each kind answers to, quoted where the document is
#: rendered so a reader can check it against the Act rather than trust a label.
SECTION_FOR_KIND = {
    KIND_SELF_INVOICE: "CGST Act s.31(3)(f)",
    KIND_PAYMENT_VOUCHER: "CGST Act s.31(3)(g)",
}
#: The rule prescribing the particulars. Rule 52(b)'s serial-number limb is
#: worded identically to Rule 46(b), which is why one module answers both.
RULE_FOR_KIND = {
    KIND_SELF_INVOICE: "CGST Rule 46",
    KIND_PAYMENT_VOUCHER: "CGST Rule 52",
}

#: The default series head for each kind. Each kind is its OWN series — Rule
#: 46(b) expressly allows "one or multiple series", and putting a self-invoice
#: number into the outward sales sequence would place a number in the GSTR-1
#: series that no outward supply carries.
DEFAULT_PREFIX_FOR_KIND = {
    KIND_SELF_INVOICE: "RCM-SI/",
    KIND_PAYMENT_VOUCHER: "RCM-PV/",
}

# ── The registration question ────────────────────────────────────────────────

REGISTERED = "registered"
UNREGISTERED = "unregistered"
#: Nobody has recorded it. A THIRD STATE, never collapsed into either answer.
UNRECORDED = "unrecorded"
REGISTRATION_STATES = (REGISTERED, UNREGISTERED, UNRECORDED)


def registration_of(vendor: dict[str, Any]) -> tuple[str, Optional[str]]:
    """(state, why) — is this supplier registered, and if unknown, why not.

    `why` is None for a settled answer and a sentence for `UNRECORDED`, because
    the two unknown cases have different remedies: record the status, or
    correct a GSTIN that was typed before the validator existed.
    """
    from domain.gst.gstin import problem_with

    who = (vendor.get("name") or "this vendor").strip() or "this vendor"
    raw = (vendor.get("gstin") or "").strip()
    if raw:
        problem = problem_with(raw)
        if problem is None:
            return REGISTERED, None
        return UNRECORDED, (
            f"The GSTIN recorded for {who} is not a valid GSTIN ({problem}), so "
            f"it cannot be read as a registration. Correct it on the vendor, or "
            f"record the registration status."
        )

    status = (vendor.get("gst_registration_status") or "").strip().lower()
    if status in (REGISTERED, UNREGISTERED):
        return status, None
    return UNRECORDED, (
        f"Whether {who} is registered under GST has not been recorded. CGST Act "
        f"s.31(3)(f) requires a self-invoice only for a supply from a supplier "
        f"who is NOT registered, so it cannot be decided from the books. Record "
        f"it on the vendor."
    )


# ── Is a document due? ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class Decision:
    """Whether one kind of document is due, and what stands in the way.

    `due` is False in two very different situations and a caller must not
    conflate them: `reasons` means the Act does not ask for this document, and
    `gaps` means nobody can yet tell. A screen shows the first as settled and
    the second as something to go and record.
    """
    kind: str
    due: bool
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def undecided(self) -> bool:
        return bool(self.gaps) and not self.due


def self_invoice_due(bill: dict[str, Any], vendor: dict[str, Any]) -> Decision:
    """CGST Act s.31(3)(f) — due only on an RCM bill from an UNREGISTERED
    supplier."""
    reasons: list[str] = []
    gaps: list[str] = []

    if not bill.get("is_reverse_charge"):
        reasons.append(
            "This bill does not carry a reverse-charge liability, so CGST Act "
            "s.31(3)(f) does not reach it — the supplier's own invoice is the "
            "document."
        )
        return Decision(KIND_SELF_INVOICE, False, reasons, gaps)

    state, why = registration_of(vendor)
    if state == REGISTERED:
        reasons.append(
            "The supplier is registered, and s.31(3)(f) reaches only a supply "
            "received from a supplier who is NOT registered. Their own tax "
            "invoice, marked payable on reverse charge, is the document."
        )
        return Decision(KIND_SELF_INVOICE, False, reasons, gaps)
    if state == UNRECORDED:
        gaps.append(why or "The supplier's registration status is not recorded.")
        return Decision(KIND_SELF_INVOICE, False, reasons, gaps)

    return Decision(KIND_SELF_INVOICE, True, reasons, gaps)


def payment_voucher_due(payment: dict[str, Any],
                        settled: list[dict[str, Any]]) -> Decision:
    """CGST Act s.31(3)(g) — due at the time of payment on EVERY s.9(3)/(4)
    liability, registered supplier or not.

    `settled` is `[{"bill": <row>, "settled_paise": int}]` — what this payment
    actually cleared, in whichever of the two shapes PUR-22 records. The caller
    resolves that, because which shape a payment is written in is a fact about
    `purchase_payments.purchase_bill_id` being set or NULL and not something a
    pure rule can read.

    THE REGISTRATION IS NOT ASKED, and that is the point. A payment to a
    REGISTERED goods transport agency owes a voucher exactly as much as one to
    an unregistered supplier does; asking here would import s.31(3)(f)'s limb
    into a section that does not carry it.
    """
    reasons: list[str] = []
    gaps: list[str] = []

    if not settled:
        gaps.append(
            "This payment is not recorded against any bill, so what it paid for "
            "— and therefore whether CGST Act s.31(3)(g) reaches it — cannot be "
            "read. Allocate it to the bills it settled."
        )
        return Decision(KIND_PAYMENT_VOUCHER, False, reasons, gaps)

    rcm = [s for s in settled if (s.get("bill") or {}).get("is_reverse_charge")]
    if not rcm:
        reasons.append(
            "None of the bills this payment settled carries a reverse-charge "
            "liability, so there is no s.9(3)/(4) tax for a payment voucher to "
            "state."
        )
        return Decision(KIND_PAYMENT_VOUCHER, False, reasons, gaps)

    return Decision(KIND_PAYMENT_VOUCHER, True, reasons, gaps)


# ── The particulars ──────────────────────────────────────────────────────────
#
# Rule 46 for the self-invoice, Rule 52 for the payment voucher. Both are built
# here rather than in the PDF, so the JSON the endpoint serves and the document
# the CA prints are the same object — a PDF that assembled its own figures
# would be a second implementation of the rule, and this file exists because one
# of those is enough.


@dataclass(frozen=True)
class Party:
    """A name, an address and — where there is one — a GSTIN.

    `gstin` is Optional and NOT defaulted to the empty string: Rule 52(a) asks
    for the supplier's GSTIN "if registered", so an absent one is part of the
    document's meaning rather than a blank to be filled.
    """
    name: str
    address: str = ""
    gstin: Optional[str] = None
    state_code: Optional[str] = None


@dataclass(frozen=True)
class TaxHead:
    """One head of tax and its amount. Integer paise, like every other document."""
    head: str                       # CGST | SGST | IGST | CESS
    amount_paise: int


@dataclass(frozen=True)
class DocumentLine:
    description: str
    hsn_sac: Optional[str] = None
    quantity: Optional[str] = None
    unit: Optional[str] = None
    taxable_paise: int = 0


@dataclass(frozen=True)
class Particulars:
    """What the document says.

    One shape for both kinds, because Rule 46 and Rule 52 ask for the same
    fields under different names — and where they differ the difference is an
    ABSENCE (a payment voucher has no HSN and no line table) rather than a
    different field.
    """
    kind: str
    section: str
    rule: str
    document_no: str
    document_date: str
    supplier: Party
    recipient: Party
    lines: list[DocumentLine] = field(default_factory=list)
    taxable_paise: int = 0
    amount_paid_paise: int = 0
    taxes: list[TaxHead] = field(default_factory=list)
    place_of_supply: tuple[str, str] = ("", "")
    #: Rule 46(p) / Rule 52(j). Always true here, since neither document exists
    #: except on a s.9(3)/(4) supply — but it is a PARTICULAR of the document
    #: and is printed, not implied.
    tax_payable_on_reverse_charge: bool = True
    gaps: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def total_tax_paise(self) -> int:
        return sum(t.amount_paise for t in self.taxes)


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _heads_of(row: dict[str, Any]) -> list[TaxHead]:
    """The heads that carry tax, in the order a GST document prints them.

    A head with NO tax is OMITTED rather than printed as nil: an IGST line of
    zero on an intra-state document tells the reader the supply was inter-state
    and nothing was charged, which is the opposite of what happened.
    """
    out: list[TaxHead] = []
    for head, key in (("CGST", "cgst_paise"), ("SGST", "sgst_paise"),
                      ("IGST", "igst_paise"), ("CESS", "cess_paise")):
        amount = _int(row.get(key))
        if amount:
            out.append(TaxHead(head=head, amount_paise=amount))
    return out


def _place_of_supply(recipient: Party, charged_igst: bool,
                     rule_clause: str, gaps: list[str]) -> tuple[str, str]:
    """Rule 46(n) / Rule 52(i) — stated where the supply is inter-state.

    On an INWARD supply the recipient is the client, so the client's own state
    is the place of supply (IGST Act s.12(2)(a), a supply to a registered
    person). Absent on an intra-state document, because the rule asks for it
    only "in the case of a supply in the course of inter-State trade".
    """
    if not charged_igst:
        return ("", "")
    if recipient.state_code:
        return (recipient.state_code, "")
    gaps.append(
        f"This is an inter-state supply and {rule_clause} requires the place of "
        f"supply on the document, but no state is recorded against the client."
    )
    return ("", "")


def self_invoice_particulars(
    *, bill: dict[str, Any], bill_lines: list[dict[str, Any]],
    supplier: Party, recipient: Party,
    document_no: str, document_date: str,
) -> Particulars:
    """Rule 46, for a s.31(3)(f) self-invoice.

    THE HEADS THE BILL ACTUALLY CARRIES DECIDE WHETHER THE SUPPLY IS
    INTER-STATE, not `purchase_bills.is_interstate`. The tax is what the return
    declares and what the ledger posted; the flag is a stored answer that can
    disagree with it. Where they do disagree the document is built from the TAX
    and the disagreement is a CAVEAT — silently preferring either would put a
    place of supply on the document that its own tax contradicts.
    """
    taxes = _heads_of(bill)
    caveats: list[str] = []
    gaps: list[str] = []

    charged_igst = any(t.head == "IGST" for t in taxes)
    charged_local = any(t.head in ("CGST", "SGST") for t in taxes)
    stored_interstate = bool(bill.get("is_interstate"))
    if charged_igst and charged_local:
        caveats.append(
            "This bill carries IGST and CGST/SGST at once. A supply is one or "
            "the other, so the document states both and the bill needs a look."
        )
    elif charged_igst and not stored_interstate:
        caveats.append(
            "The bill is recorded as intra-state but carries IGST. The document "
            "follows the tax."
        )
    elif charged_local and stored_interstate:
        caveats.append(
            "The bill is recorded as inter-state but carries CGST and SGST. The "
            "document follows the tax."
        )

    pos = _place_of_supply(recipient, charged_igst, "CGST Rule 46(n)", gaps)

    lines = [
        DocumentLine(
            description=(l.get("description") or l.get("item_name") or "").strip(),
            hsn_sac=((l.get("hsn_sac") or "").strip() or None),
            quantity=(None if l.get("quantity") is None else str(l.get("quantity"))),
            unit=((l.get("unit") or "").strip() or None),
            taxable_paise=_int(l.get("taxable_amount_paise")
                               if l.get("taxable_amount_paise") is not None
                               else l.get("taxable_paise")),
        )
        for l in bill_lines
    ]
    if not lines:
        gaps.append(
            "The bill has no lines, so CGST Rule 46(g) — the description of the "
            "goods or services — cannot be stated."
        )

    return Particulars(
        kind=KIND_SELF_INVOICE,
        section=SECTION_FOR_KIND[KIND_SELF_INVOICE],
        rule=RULE_FOR_KIND[KIND_SELF_INVOICE],
        document_no=document_no,
        document_date=document_date,
        supplier=supplier,
        recipient=recipient,
        lines=lines,
        taxable_paise=_int(bill.get("taxable_amount_paise")),
        amount_paid_paise=0,
        taxes=taxes,
        place_of_supply=pos,
        gaps=gaps,
        caveats=caveats,
    )


def payment_voucher_particulars(
    *, payment: dict[str, Any], settled: list[dict[str, Any]],
    supplier: Party, recipient: Party,
    document_no: str, document_date: str,
) -> Particulars:
    """Rule 52, for a s.31(3)(g) payment voucher.

    TWO FIGURES, AND THEY ARE NOT THE SAME ONE. Rule 52(f) is the AMOUNT PAID,
    which is the whole payment. Rule 52(h) is the tax payable on the supply,
    which is the reverse-charge tax of the bills this payment settled. Where the
    payment also cleared ordinary bills the two cannot be reconciled from the
    document alone, so the non-reverse-charge part is NAMED in a caveat rather
    than folded into either figure or quietly dropped.

    THE TAX IS APPORTIONED BY WHAT WAS SETTLED, not taken whole. A part payment
    discharges part of the consideration, and stating a bill's whole tax on a
    voucher for half of it would overstate what this payment carries. The
    apportionment FLOORS: a voucher may not state more tax than the payment
    supports, and the remainder rides on the next one.
    """
    caveats: list[str] = []
    gaps: list[str] = []

    paid = _int(payment.get("amount_paise"))
    rcm = [s for s in settled if (s.get("bill") or {}).get("is_reverse_charge")]
    other = [s for s in settled if not (s.get("bill") or {}).get("is_reverse_charge")]

    if other:
        caveats.append(
            f"This payment also settled {len(other)} bill(s) carrying no "
            f"reverse-charge liability. CGST Rule 52(f) states the whole amount "
            f"paid, so the tax below is less than that figure and its rate would "
            f"otherwise suggest."
        )

    totals: dict[str, int] = {}
    taxable = 0
    for s in rcm:
        bill = s.get("bill") or {}
        bill_total = _int(bill.get("total_paise"))
        part = _int(s.get("settled_paise"))
        whole_bill = part >= bill_total or bill_total <= 0
        for head, key in (("CGST", "cgst_paise"), ("SGST", "sgst_paise"),
                          ("IGST", "igst_paise"), ("CESS", "cess_paise")):
            amount = _int(bill.get(key))
            if not amount:
                continue
            # Floor — see the docstring: never more tax than the payment carries.
            share = amount if whole_bill else (amount * part) // bill_total
            if share:
                totals[head] = totals.get(head, 0) + share
        bill_taxable = _int(bill.get("taxable_amount_paise"))
        taxable += (bill_taxable if whole_bill
                    else (bill_taxable * part) // bill_total)

    taxes = [TaxHead(head=h, amount_paise=totals[h])
             for h in ("CGST", "SGST", "IGST", "CESS") if totals.get(h)]

    pos = _place_of_supply(recipient, any(t.head == "IGST" for t in taxes),
                           "CGST Rule 52(i)", gaps)

    return Particulars(
        kind=KIND_PAYMENT_VOUCHER,
        section=SECTION_FOR_KIND[KIND_PAYMENT_VOUCHER],
        rule=RULE_FOR_KIND[KIND_PAYMENT_VOUCHER],
        document_no=document_no,
        document_date=document_date,
        supplier=supplier,
        recipient=recipient,
        lines=[],          # Rule 52 asks for a description, not a line table.
        taxable_paise=taxable,
        amount_paid_paise=paid,
        taxes=taxes,
        place_of_supply=pos,
        gaps=gaps,
        caveats=caveats,
    )


def as_dict(p: Particulars) -> dict[str, Any]:
    """The particulars as JSON — what the endpoint serves AND what is stored.

    One serialiser, because a stored copy that differs from the served one is
    two records of the same document.
    """
    return {
        "kind": p.kind,
        "section": p.section,
        "rule": p.rule,
        "document_no": p.document_no,
        "document_date": p.document_date,
        "supplier": {"name": p.supplier.name, "address": p.supplier.address,
                     "gstin": p.supplier.gstin, "state_code": p.supplier.state_code},
        "recipient": {"name": p.recipient.name, "address": p.recipient.address,
                      "gstin": p.recipient.gstin, "state_code": p.recipient.state_code},
        "lines": [{"description": l.description, "hsn_sac": l.hsn_sac,
                   "quantity": l.quantity, "unit": l.unit,
                   "taxable_paise": l.taxable_paise} for l in p.lines],
        "taxable_paise": p.taxable_paise,
        "amount_paid_paise": p.amount_paid_paise,
        "taxes": [{"head": t.head, "amount_paise": t.amount_paise} for t in p.taxes],
        "total_tax_paise": p.total_tax_paise,
        "place_of_supply": list(p.place_of_supply),
        "tax_payable_on_reverse_charge": p.tax_payable_on_reverse_charge,
        "gaps": list(p.gaps),
        "caveats": list(p.caveats),
    }
