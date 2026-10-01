"""A DRAFT purchase bill from a GSTR-2B document the books have no bill for
(gst-13) — what may be drafted, from what, and what must be refused.

WHAT WAS MISSING
    For a `missing_in_books` row the screen said "chase the document" and
    stopped. The supplier has filed an invoice the client never entered, and the
    2B row already carries everything a bill needs that the supplier knows —
    GSTIN, number, date, the taxable value and the tax heads — so the CA was
    retyping from a screen that was holding the figures.

WHAT THIS MODULE IS, AND ISN'T
    It is the RULE: which 2B documents a bill may be drafted from, what the
    draft's lines are, and whether the books' own arithmetic then reproduces
    what the supplier filed. It reads nothing and writes nothing.
    `routers/purchase_bills.create_bill_from_2b` fetches the stored row and the
    kept file, calls this, and hands the result to the ONE bill engine
    (`_create_purchase_bill_core`), which computes the totals, the TDS and the
    locks exactly as it does for a typed bill. There is no second way to write a
    bill.

THE DRAFT NEVER POSTS AND NEVER CLAIMS
    A purchase bill becomes an accounting event when a CA RECEIVES it — that is
    what posts Dr Expense / Dr GST Input / Cr Trade Payables and puts the credit
    on Table 4(A). The bill engine's create path writes `status = 'draft'` and
    no journal, and `read_book_bills` counts only received bills, so the
    reconciliation does not see the draft either: the row stays
    `missing_in_books` until the CA has looked at it and received it, and the
    next reconciliation then matches it BY KEY (the supplier's GSTIN and number).

    THERE IS NO STORED LINK, AND THAT IS THE DESIGN. Writing `purchase_bill_id`
    onto the 2B row at draft time would make a bill nobody has received read as
    matched — to `status_for_bills`, and to `rule_36_4`, which reads exactly that
    column. The key does the linking: the draft carries the supplier's own
    number and the supplier's own GSTIN (through the vendor), so receiving it
    and running the reconciliation again turns the row `matched` by itself.

THE VENDOR'S NUMBER IS THEIRS. `bill_no` is taken from the 2B document exactly
    as the supplier wrote it — never folded, never padded, never replaced by a
    reference of ours — because it is half the key `itc_matching` matches on
    and a fact about the supplier's books.

THE RATE COMES FROM THE FILE, NOT FROM A DIVISION
    `gstr2a_records` stores the document's totals and nothing per rate, so a
    draft's lines are read from the file the CA uploaded (`RateLine`, one per
    `inv.items[]`), each at the rate the supplier charged. Dividing the tax by
    the taxable value would give one line at a rate the document never stated —
    11.5% for an invoice of a 5% line and an 18% line. The kept file must
    reproduce the stored row's totals to the paisa before it is used; if it does
    not, the draft is REFUSED with the sentence saying to upload the file again,
    because a draft built from a file the reconciliation did not read would
    disagree with the very row it is meant to resolve.

WHAT IS REFUSED, EACH WITH ITS OWN REASON
    * a reverse-charge document — whether §9(3)/(4) applies is the bill's own
      `is_reverse_charge` and the CA's answer (PUR-19), and booking it as an
      ordinary purchase would claim credit on tax the supplier never charged;
    * an amendment, a credit note, a debit note and an import — each has a
      different home (the original bill, a purchase credit / debit note, a Bill
      of Entry) and none is an ordinary bill;
    * a line with no rate, or a document with no lines — a rate nobody stated is
      not read as nil, the AI-01 rule.

WHAT IT DOES NOT DECIDE
    HSN, unit and product are not in GSTR-2B and are not invented; CGST §17(5)
    is a per-line judgement the draft leaves at its default (eligible) for the CA
    to set before receiving; and whether the supplier's State and the client's
    State make the supply inter-State is the bill engine's reading of the two
    registrations — `describe_agreement` reports it when the engine and the
    supplier disagree, rather than overriding either.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from domain.gst.gstr2b import GSTR2BDocument
from domain.money_text import rupees_paise

#: The only document a bill may be drafted from.
DRAFTABLE_SECTIONS = ("b2b",)
DRAFTABLE_TYPE = "invoice"

_HEADS = (("igst_paise", "IGST"), ("cgst_paise", "CGST"),
          ("sgst_paise", "SGST"), ("cess_paise", "cess"))


def refusal_for_kind(section: str, document_type: str) -> Optional[str]:
    """Why a bill cannot be drafted from this KIND of document, or None.

    Asked from the document's own section and type alone, so the screen can be
    told per row (`draft_bill_refusal`) without reading anything else — the
    browser holds no list of which kinds are draftable.
    """
    sec = (section or "").strip().lower()
    typ = (document_type or "").strip().lower()
    if sec == "b2ba":
        return ("This is an AMENDMENT of an invoice the supplier filed earlier. "
                "Book the original, or correct the bill already in the books — "
                "an amendment is not a second bill.")
    if typ == "credit_note":
        return ("This is a CREDIT NOTE. It reduces credit and belongs on a "
                "purchase debit note against the bill it reduces, not on a new "
                "bill.")
    if typ == "debit_note":
        return ("This is a DEBIT NOTE the supplier raised. It belongs on a "
                "purchase credit note against the bill it adds to, not on a "
                "new bill.")
    if typ == "bill_of_entry" or sec in ("impg", "impgsez"):
        return ("This is an import of goods, communicated against a Bill of "
                "Entry. Record it as a Bill of Entry — the tax was paid to "
                "customs, not to a supplier.")
    if sec in DRAFTABLE_SECTIONS and typ == DRAFTABLE_TYPE:
        return None
    return ("A bill can be drafted from an ordinary supplier invoice only; this "
            "document is not one.")


@dataclass(frozen=True)
class DraftPlan:
    """What may be handed to the bill engine, or why not."""
    refusal: Optional[str] = None
    lines: tuple[dict, ...] = ()
    notes: str = ""
    #: Said beside the draft, not refused: things the CA must still do or know.
    caveats: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.refusal is None


def _refuse(sentence: str) -> DraftPlan:
    return DraftPlan(refusal=sentence)


def _totals(doc: GSTR2BDocument) -> dict:
    return {"taxable_paise": doc.taxable_value_paise, "igst_paise": doc.igst_paise,
            "cgst_paise": doc.cgst_paise, "sgst_paise": doc.sgst_paise,
            "cess_paise": doc.cess_paise}


def plan(doc: GSTR2BDocument, stored: dict, *, period_label: str) -> DraftPlan:
    """The draft for one 2B document.

    `doc` is the document as parsed from the KEPT FILE (so it carries its rate
    lines) and `stored` is the `gstr2a_records` row the CA clicked on. The two
    must agree to the paisa — see the module docstring.
    """
    why = refusal_for_kind(doc.section, doc.document_type)
    if why:
        return _refuse(why)

    if doc.reverse_charge:
        return _refuse(
            "GSTR-2B marks this document as a REVERSE CHARGE supply. Whether "
            "§9(3)/(4) applies is your answer to give, and booking it as an "
            "ordinary purchase would claim credit on tax the supplier never "
            "charged. Enter the bill directly and mark it reverse charge.")

    if not doc.document_date:
        return _refuse(
            "The document's date could not be read from the file, and a bill "
            "needs the supplier's invoice date. Enter the bill directly.")

    on_record = {
        "taxable_paise": int(stored.get("taxable_value_paise") or 0),
        "igst_paise": int(stored.get("igst_paise") or 0),
        "cgst_paise": int(stored.get("cgst_paise") or 0),
        "sgst_paise": int(stored.get("sgst_paise") or 0),
        "cess_paise": int(stored.get("cess_paise") or 0),
    }
    if on_record != _totals(doc):
        return _refuse(
            "The copy of the GSTR-2B file kept for this month does not agree "
            "with the document stored from it, so a bill drafted from the file "
            "could disagree with the row it is meant to settle. Upload the "
            "file again, then create the draft.")

    if not doc.rate_lines:
        return _refuse(
            "The file carries this document with no rate lines, so there is "
            "nothing to draft the bill's lines from. Enter the bill directly.")

    lines: list[dict] = []
    has_cess = False
    for i, rl in enumerate(doc.rate_lines, start=1):
        if rl.rate_bps is None:
            return _refuse(
                f"Rate line {i} of this document states no GST rate, and a rate "
                f"nobody stated is not read as nil. Enter the bill directly.")
        if rl.taxable_paise <= 0:
            return _refuse(
                f"Rate line {i} of this document has no taxable value, so it "
                f"cannot be a bill line. Enter the bill directly.")
        line = {
            "description": (f"As per supplier invoice {doc.document_number}"
                            + (f" — rate line {i}" if len(doc.rate_lines) > 1 else "")),
            # Not in GSTR-2B and not invented: the CA adds them in the editor.
            "hsn_sac": None,
            "quantity": 1,
            "unit": None,
            "rate_paise": int(rl.taxable_paise),
            "gst_rate_percent": rl.rate_bps / 100.0,
            "service_catalogue_id": None,
        }
        if rl.cess_paise:
            # The file carries the cess as an AMOUNT, not the Schedule entry it
            # was charged under. On a quantity of one the per-unit figure IS the
            # amount, so the engine reproduces it exactly and no rate is made up.
            line["cess_specific_paise_per_unit"] = int(rl.cess_paise)
            has_cess = True
        lines.append(line)

    caveats = [
        "This is a DRAFT. Nothing is posted and no credit is claimed until you "
        "receive it. GSTR-2B carries no HSN, unit or product and no CGST §17(5) "
        "decision, so add them in the editor before receiving.",
    ]
    if has_cess:
        caveats.append(
            "The cess is recorded as a lump sum on a quantity of one, because "
            "GSTR-2B gives the amount and not the Schedule entry it was charged "
            "under. Replace it with the rate if you want the line to show one.")
    if (doc.itc_available or "").strip().upper() == "N":
        why_n = doc.itc_unavailable_reason or "no reason given"
        caveats.append(
            f"GSTR-2B itself marks this document's credit UNAVAILABLE ({why_n}). "
            f"Booking the bill does not make it claimable.")

    notes = (
        f"Drafted from GSTR-2B for {period_label}: "
        f"{doc.supplier_name or doc.supplier_gstin} invoice {doc.document_number} "
        f"dated {doc.document_date}. Not received — check the document and the "
        f"lines against the supplier's invoice, then receive it.")
    return DraftPlan(lines=tuple(lines), notes=notes, caveats=tuple(caveats))


def describe_agreement(bill: dict, doc: GSTR2BDocument) -> tuple[bool, list[str]]:
    """Does the BOOKS' arithmetic reproduce what the supplier filed?

    `bill` is what the bill engine computed from the draft's lines. The engine
    derives each head from the line's rate, floors it, and reads inter-State
    from the vendor's and the client's States; the supplier computed and
    rounded their own. They normally agree to the paisa and sometimes do not —
    a paisa where the supplier rounded half up, or a whole head where the
    vendor's recorded State disagrees with the one the invoice was issued from.
    Either is REPORTED, never corrected: overriding the engine to match the
    file would hide the thing the CA is there to look at, and the next
    reconciliation would say the same in a sentence they could not trace.
    """
    out: list[str] = []
    if int(bill.get("taxable_amount_paise") or 0) != doc.taxable_value_paise:
        out.append(
            f"Taxable value: the draft carries "
            f"₹{rupees_paise(int(bill.get('taxable_amount_paise') or 0))} and "
            f"GSTR-2B ₹{rupees_paise(doc.taxable_value_paise)}.")
    for key, label in _HEADS:
        got, filed = int(bill.get(key) or 0), int(getattr(doc, key) or 0)
        if got != filed:
            out.append(
                f"{label}: the draft computes ₹{rupees_paise(got)} and the "
                f"supplier filed ₹{rupees_paise(filed)}.")
    if out and ((int(bill.get("igst_paise") or 0) == 0) != (doc.igst_paise == 0)):
        out.append(
            "The supply is inter-State on one side and intra-State on the "
            "other: check the State recorded on the vendor against the "
            "supplier's GSTIN before receiving.")
    return (not out), out
