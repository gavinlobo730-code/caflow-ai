"""
The GSTR-2B envelope, parsed — CGST Act §38 with Rule 60(7).

WHAT WAS WRONG
    The upload endpoint looked for `data.docDetails[]` keyed on `sgstin`.
    Neither exists. A GSTR-2B downloaded from the portal is

        {"data": {"gstin": ..., "rtnprd": "042025", "docdata": {
            "b2b":   [{"ctin", "trdnm", "supfildt", "inv": [{...}]}],
            "b2ba":  [...],  "cdnr": [{"ctin", "nt": [{...}]}],
            "cdnra": [...],  "impg": [{"boenum", ...}], "impgsez": [...]}}}

    so every genuine file parsed to an empty list, and the screen answered
    "Matched 0, Mismatched 0, Missing 0" — a clean result that means nothing.
    The books side was read out of the SAME pasted JSON (`raw["book_invoices"]`),
    which is to say from whatever the caller chose to put there.

THREE THINGS ABOUT THE REAL FILE THAT ARE EASY TO GET WRONG

  1. THE TAX IS NOT ON THE INVOICE. `inv.val` is the invoice VALUE — taxable
     plus tax plus cess. The taxable value and each tax head live per RATE LINE
     in `inv.items[]` as `txval`, `igst`, `cgst`, `sgst`, `cess`. Reading
     `val` as taxable value overstates the ITC being matched by the tax itself.

  2. `itcavl` IS PART OF THE DOCUMENT. GSTR-2B marks each document ITC
     available or not, with a reason code in `rsn` — "P" where the place of
     supply and the supplier's state are the same but the recipient is in
     another state (so the credit is not available to this recipient at all),
     "C" where the supplier filed after the annual cut-off (§16(4)). A
     reconciliation that matches an invoice and ignores `itcavl` tells a CA the
     credit is safe when the portal has already said it is not.

  3. A CREDIT NOTE REDUCES CREDIT. `cdnr` notes carry `typ` "C" or "D"; a
     credit note is a REVERSAL of ITC in the recipient's hands, so its amounts
     are signed negative here. Treating them as ordinary documents would have
     the reconciliation report more available credit than 2B allows.

WHAT THIS MODULE DOES NOT DO
    It does not match, read a book, or touch a database — it turns one JSON
    document into a list of rows. Matching is
    services/gst_2b_reconciliation_service, which reads the books server-side.

All amounts are integer paise. The portal sends rupees as JSON numbers, often
with a fractional part, so every conversion goes through Decimal(str(x)) —
never float(x) * 100, which is not guaranteed to round-trip through IEEE-754.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

#: The document sections this parser reads, and what each one is.
#:
#: b2ba and cdnra are AMENDMENTS — the portal reports the amended document in
#: its own section rather than restating the original — so they are parsed and
#: marked, not merged. Merging them would need the original's period, which the
#: amendment names (`oinum`/`ontnum` with the original period) and which this
#: client may not have downloaded.
SECTIONS = ("b2b", "b2ba", "cdnr", "cdnra", "impg", "impgsez")

#: §16(2)(aa) and Rule 36(4) turn on what 2B SAYS, and it says this.
ITC_UNAVAILABLE_REASONS = {
    "P": ("Place of supply and the supplier's State are the same, and the "
          "recipient is in another State — §16(2) with §12/§13, the credit is "
          "not available to this recipient at all."),
    "C": ("The supplier furnished the return after the §16(4) cut-off, so the "
          "credit for this document has lapsed."),
}


def paise(value: Any) -> int:
    """A portal rupee figure → integer paise, exactly.

    Decimal(str(x)) and never float(x) * 100: the portal sends 729248.16 as a
    JSON number, and the float route is not guaranteed to land on 72924816.
    """
    try:
        return int((Decimal(str(value or 0)) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        return 0


@dataclass(frozen=True)
class GSTR2BDocument:
    """One document out of GSTR-2B, in the shape gstr2a_records holds."""
    section: str                    # b2b / b2ba / cdnr / cdnra / impg / impgsez
    document_type: str              # invoice / credit_note / debit_note / bill_of_entry
    supplier_gstin: str             # "" for an import — there is no supplier GSTIN
    supplier_name: str
    document_number: str
    document_date: Optional[str]    # ISO, or None where the portal's date will not parse
    taxable_value_paise: int
    igst_paise: int
    cgst_paise: int
    sgst_paise: int
    cess_paise: int
    invoice_value_paise: int
    #: "Y", "N", or "" where the section does not carry the flag.
    itc_available: str
    itc_unavailable_reason_code: str
    itc_unavailable_reason: str
    supplier_filed_on: Optional[str]
    is_amendment: bool
    #: The document this one amends, where it is an amendment.
    amends_document_number: str = ""

    @property
    def total_tax_paise(self) -> int:
        return self.igst_paise + self.cgst_paise + self.sgst_paise + self.cess_paise


@dataclass
class GSTR2BFile:
    gstin: str
    return_period: str              # MMYYYY, as the portal writes it
    generated_on: str
    documents: list[GSTR2BDocument] = field(default_factory=list)
    #: Sections present in the file that this parser does not read, and
    #: sections it read but which were empty. Reported rather than dropped: a
    #: CA needs to know the file HAD an import section before concluding their
    #: client has no imports.
    sections_seen: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def _iso_date(value: Any) -> Optional[str]:
    """The portal writes DD-MM-YYYY. Returns ISO, or None rather than a guess.

    None rather than today's date, and rather than the string as-is: a date
    that will not parse must not become a date that sorts wrongly, and a
    reconciliation keyed partly on the date has to know it does not have one.
    """
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split("-")
    if len(parts) == 3 and len(parts[0]) == 2 and len(parts[2]) == 4:
        d, m, y = parts
        if d.isdigit() and m.isdigit() and y.isdigit():
            return f"{y}-{m}-{d}"
    # Already ISO?
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return None


def _sum_items(items: Any) -> tuple[int, int, int, int, int]:
    """(taxable, igst, cgst, sgst, cess) summed over the RATE LINES.

    The tax is per rate line, never on the invoice header — `inv.val` is the
    whole invoice value including tax, and reading it as taxable value
    overstates the credit being matched by the tax itself.
    """
    taxable = igst = cgst = sgst = cess = 0
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        taxable += paise(it.get("txval"))
        igst += paise(it.get("igst"))
        cgst += paise(it.get("cgst"))
        sgst += paise(it.get("sgst"))
        cess += paise(it.get("cess"))
    return taxable, igst, cgst, sgst, cess


def _reason(code: str) -> str:
    return ITC_UNAVAILABLE_REASONS.get(code, "")


def _document(*, section: str, document_type: str, supplier_gstin: str,
              supplier_name: str, number: str, date: Any, header: dict,
              items: Any, sign: int, is_amendment: bool,
              amends: str = "") -> GSTR2BDocument:
    taxable, igst, cgst, sgst, cess = _sum_items(items)
    itcavl = str(header.get("itcavl") or "").strip().upper()
    rsn = str(header.get("rsn") or "").strip().upper()
    return GSTR2BDocument(
        section=section,
        document_type=document_type,
        supplier_gstin=str(supplier_gstin or "").strip().upper(),
        supplier_name=str(supplier_name or "").strip(),
        document_number=str(number or "").strip(),
        document_date=_iso_date(date),
        taxable_value_paise=sign * taxable,
        igst_paise=sign * igst,
        cgst_paise=sign * cgst,
        sgst_paise=sign * sgst,
        cess_paise=sign * cess,
        invoice_value_paise=sign * paise(header.get("val")),
        itc_available=itcavl,
        itc_unavailable_reason_code=rsn,
        itc_unavailable_reason=_reason(rsn),
        supplier_filed_on=_iso_date(header.get("supfildt")),
        is_amendment=is_amendment,
        amends_document_number=str(amends or "").strip(),
    )


def parse_gstr2b(raw: Any) -> GSTR2BFile:
    """One GSTR-2B JSON → its documents. Never raises on a malformed file.

    A file this cannot read comes back with `problems` naming what was wrong
    and no documents, rather than an exception — the caller shows the CA the
    sentence, and an empty reconciliation that LOOKS clean is the failure this
    whole module exists to end.
    """
    out = GSTR2BFile(gstin="", return_period="", generated_on="")
    if not isinstance(raw, dict):
        out.problems.append("This is not a GSTR-2B file — the top level is not a JSON object.")
        return out

    data = raw.get("data")
    if not isinstance(data, dict):
        out.problems.append(
            "No `data` object. A GSTR-2B downloaded from the portal has "
            "`data.docdata` at its top level; a file without it is something else.")
        return out

    out.gstin = str(data.get("gstin") or "").strip().upper()
    out.return_period = str(data.get("rtnprd") or "").strip()
    out.generated_on = str(data.get("gendt") or "").strip()

    docdata = data.get("docdata")
    if not isinstance(docdata, dict):
        out.problems.append(
            "No `data.docdata`. Nothing in this file describes any document.")
        return out

    for section in SECTIONS:
        rows = docdata.get(section)
        if rows is None:
            continue
        if not isinstance(rows, list):
            out.problems.append(f"`{section}` is present but is not a list; it was ignored.")
            continue
        out.sections_seen[section] = len(rows)

    for unknown in sorted(set(docdata) - set(SECTIONS)):
        n = len(docdata[unknown]) if isinstance(docdata.get(unknown), list) else 0
        out.problems.append(
            f"`{unknown}` carries {n} row(s) and is not read by this version — "
            f"its documents are NOT in the reconciliation below.")

    # ── b2b and its amendments ────────────────────────────────────────────
    for section in ("b2b", "b2ba"):
        for supplier in (docdata.get(section) or []):
            if not isinstance(supplier, dict):
                continue
            ctin = supplier.get("ctin")
            trdnm = supplier.get("trdnm")
            for inv in (supplier.get("inv") or []):
                if not isinstance(inv, dict):
                    continue
                out.documents.append(_document(
                    section=section, document_type="invoice",
                    supplier_gstin=ctin, supplier_name=trdnm,
                    number=inv.get("inum"), date=inv.get("dt"),
                    header={**inv, "supfildt": supplier.get("supfildt")},
                    items=inv.get("items"), sign=1,
                    is_amendment=(section == "b2ba"),
                    amends=inv.get("oinum", "")))

    # ── credit and debit notes, and their amendments ──────────────────────
    #
    # A CREDIT note reduces the recipient's credit and a DEBIT note increases
    # it, so the sign follows `typ` rather than the section. Getting this
    # backwards would report more available credit than 2B allows, which is
    # the direction that draws a reversal notice under §42.
    for section in ("cdnr", "cdnra"):
        for supplier in (docdata.get(section) or []):
            if not isinstance(supplier, dict):
                continue
            ctin = supplier.get("ctin")
            trdnm = supplier.get("trdnm")
            for note in (supplier.get("nt") or []):
                if not isinstance(note, dict):
                    continue
                typ = str(note.get("typ") or "").strip().upper()
                is_credit = typ == "C"
                out.documents.append(_document(
                    section=section,
                    document_type="credit_note" if is_credit else "debit_note",
                    supplier_gstin=ctin, supplier_name=trdnm,
                    number=note.get("ntnum"), date=note.get("ntdt"),
                    header={**note, "supfildt": supplier.get("supfildt")},
                    items=note.get("itms"), sign=-1 if is_credit else 1,
                    is_amendment=(section == "cdnra"),
                    amends=note.get("ontnum", "")))

    # ── imports ───────────────────────────────────────────────────────────
    #
    # There is NO supplier GSTIN on an import: the document is a bill of entry
    # and the tax is IGST paid at the port. The taxable value and the tax are
    # on the row itself, not in an items list.
    for section in ("impg", "impgsez"):
        for row in (docdata.get(section) or []):
            if not isinstance(row, dict):
                continue
            out.documents.append(GSTR2BDocument(
                section=section, document_type="bill_of_entry",
                supplier_gstin=str(row.get("sgstin") or "").strip().upper(),
                supplier_name=str(row.get("tdname") or "").strip(),
                document_number=str(row.get("boenum") or "").strip(),
                document_date=_iso_date(row.get("boedt")),
                taxable_value_paise=paise(row.get("txval")),
                igst_paise=paise(row.get("igst")),
                cgst_paise=0, sgst_paise=0,
                cess_paise=paise(row.get("cess")),
                invoice_value_paise=paise(row.get("txval")) + paise(row.get("igst")),
                itc_available="", itc_unavailable_reason_code="",
                itc_unavailable_reason="",
                supplier_filed_on=None,
                is_amendment=bool(row.get("isamd") in ("Y", True)),
            ))

    if not out.documents and not out.problems:
        out.problems.append(
            "This file parsed, and it contains no documents at all. That is what "
            "an empty 2B looks like — but so does a file for the wrong period, so "
            "check the return period above against the one you are reconciling.")
    return out
