"""
Does the period's GSTR-1, as the books build it, declare every invoice that carries a live IRN, and does each IRN record still name
the invoice it was obtained for (POST-A-066)?

WHAT WAS MISSING

    The e-invoice rail records an IRN that a person obtained on the IRP (`routers/einvoice.py`), and `irn_worklist` lists the
    invoices that owe one and have none. Nothing looked the other way: an IRN recorded as live for an invoice that the return does
    not declare, or a record whose invoice number or date is no longer the invoice's. Each is a disagreement between two records of
    one supply, and a CA preparing the month's return should see it before the return is filed rather than after.

WHAT THIS DECIDES, AND WHAT IT DOES NOT

    It takes the GSTR-1 payload the books build for the period, the live IRN records that belong to it (by their own invoice date, or
    their invoice's) and the invoices those records name (the one linked, or for an unlinked record the one carrying its number), and
    names each disagreement with its reason. The invoice's OWN state is asked first, because a number the return declares may be
    another invoice's (a deleted draft's number reused, or one that differs only in case):

        invoice_deleted     the invoice was deleted in the books (only a draft can be)
        invoice_cancelled   the invoice is cancelled in the books
        invoice_not_issued  the invoice is a draft, so no return declares it
        carried_over        the invoice is a carried-over opening document, which no return this product builds declares
        other_period        the invoice is dated outside this return's period
        declared_elsewhere  the return declares it as a large supply to an unregistered person (B2CL)
        not_declared        issued and in the period, and not declared by number as B2B, an export or B2CL: within a total
                            (B2C small; nil-rated, exempt, non-GST) or not in the return at all; this check cannot tell which
        no_invoice          the record names no invoice in the books, by link or by its number

    Apart from those: `differs`, a live record whose number or date is not its invoice's, and `duplicates`, more than one live record
    naming one invoice (this product keeps one per invoice, migration 518).

    It claims nothing about the IRP or the portal and mints, cancels and files nothing: the answer is a list of facts about the
    product's own records and the CA decides what to do. The converse, an invoice that owes an IRN and has none, is the missing-IRN
    list (`irn_worklist`), which the answer points to rather than repeats. Credit and debit notes are not compared: an IRN record links
    to a sales invoice only. The return is built again for the check, so the answer is about the books as they stand now.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from typing import Iterable, Optional

LIVE = "generated"

#: The invoice state in which no return declares an invoice: cancelled in the books (the schema allows draft, issued,
#: partially_paid, paid and cancelled).
CANCELLED_STATES = frozenset({"cancelled"})

REASONS = {
    "invoice_deleted": ("The invoice was deleted in the books (only a draft can be), while an IRN is recorded as live for it, so the "
                        "two records disagree."),
    "invoice_cancelled": ("The invoice is cancelled in the books while its IRN is recorded as live, so the two records disagree: if "
                          "the IRN was cancelled on the IRP, record that here; otherwise look at why the invoice was cancelled."),
    "invoice_not_issued": "The invoice is still a draft, so no return declares it, while an IRN is recorded as live for it.",
    "carried_over": ("The invoice is a carried-over opening document, which no return this product builds declares, while an IRN is "
                     "recorded as live for it."),
    "other_period": "The invoice is dated {invoice_date}, outside this return's period, so this return does not declare it.",
    "declared_elsewhere": ("This return declares the invoice as a large supply to an unregistered person (B2CL), not as a supply to "
                           "a registered person or an export, while an IRN is recorded as live for it. Check the recipient's GSTIN."),
    "not_declared": ("The invoice is issued and dated in this period, and this return does not declare it by number as a supply to a "
                     "registered person, an export or a large supply to an unregistered person: it is either within one of the "
                     "return's totals (small supplies to unregistered persons; nil-rated, exempt and non-GST supplies) or not in it "
                     "at all, while an IRN is recorded as live for it. Check the recipient's GSTIN and the invoice's type."),
    "no_invoice": "No invoice in the books carries the record's number {invoice_number}, and the record is linked to none.",
}

DIFFERS = "The IRN record says {record_number} of {record_date}; the invoice it names is {invoice_number} of {invoice_date}."

DUPLICATE = ("{count} live IRN records name invoice {invoice_number}; this product keeps one live IRN record per invoice, so one of "
             "them is a mistake to correct.")

CONVERSE = ("An invoice that owes an IRN and has none is on the missing-IRN list (E-invoice screen), which this check does not "
            "repeat.")

NOT_COMPARED = ("Credit and debit notes are not compared: an IRN record links to a sales invoice only. The return is built again "
                "from the books for the check, so it answers for the books as they stand now.")


def number_key(value) -> str:
    """An invoice number as the two records are compared on: the same text, case and outer spaces aside. Both records are this
    client's own, so a looser match (dropping separators or zeros) would pair two different invoices."""
    return str(value or "").strip().upper()


def _day(value) -> Optional[str]:
    text = str(value or "")[:10]
    return text or None


def _dmy(day: Optional[str], absent: str) -> str:
    """An ISO day as a sentence writes it, dd-mm-yyyy."""
    return f"{day[8:10]}-{day[5:7]}-{day[:4]}" if day and len(day) == 10 else absent


def _in(day: Optional[str], start: str, end: str) -> bool:
    return day is not None and start <= day <= end


def is_live(record: dict) -> bool:
    """A live IRN: a `generated` record that carries one (`irn_worklist.irn_state`'s reading)."""
    return str(record.get("status") or "").lower() == LIVE and bool(str(record.get("irn") or "").strip())


def _numbers(payload: dict, *tables: str) -> set[str]:
    out: set[str] = set()
    for table in tables:
        for group in payload.get(table) or []:
            out.update(number_key(inv.get("inum")) for inv in group.get("inv") or [])
    out.discard("")
    return out


def declared_numbers(payload: dict) -> set[str]:
    """The invoice numbers a GSTR-1 payload declares as a supply to a registered person (B2B, which carries SEZ and deemed exports)
    or as an export."""
    return _numbers(payload, "b2b", "exp")


def _resolve(record: dict, invoices: dict[str, dict]) -> Optional[dict]:
    """The invoice a record names: the one it is linked to, or, unlinked, the one carrying its number (exactly, then case aside where
    only one does). A linked id that is not among the invoices read resolves to nothing."""
    if record.get("sales_invoice_id"):
        return invoices.get(str(record["sales_invoice_id"]))
    wanted = str(record.get("invoice_number") or "").strip()
    if not wanted:
        return None
    exact = [i for i in invoices.values() if str(i.get("invoice_no") or "").strip() == wanted]
    if len(exact) == 1:
        return exact[0]
    loose = [i for i in invoices.values() if number_key(i.get("invoice_no")) == number_key(wanted)]
    return loose[0] if len(exact) == 0 and len(loose) == 1 else None


def _reason(invoice: Optional[dict], declared: set[str], b2cl: set[str], start: str, end: str) -> Optional[str]:
    """Why the return does not declare the invoice a live record names, or None where it does. The invoice's own state is asked
    FIRST: a number declared in the return may be another invoice's (a deleted draft's number reused, or one differing by case)."""
    if invoice is None:
        return "no_invoice"
    status = str(invoice.get("status") or "").lower()
    if invoice.get("deleted_at"):
        return "invoice_deleted"
    if status in CANCELLED_STATES:
        return "invoice_cancelled"
    if status == "draft":
        return "invoice_not_issued"
    if invoice.get("is_opening"):
        return "carried_over"
    if not _in(_day(invoice.get("invoice_date")), start, end):
        return "other_period"
    key = number_key(invoice.get("invoice_no"))
    if key in declared:
        return None
    return "declared_elsewhere" if key in b2cl else "not_declared"


def compare(payload: dict, records: Iterable[dict], invoices: dict[str, dict], start: str, end: str) -> dict:
    """The disagreements between a period's live IRN records and the GSTR-1 the books build for it.

    `records` are the client's e-invoice records; only live ones whose own invoice date, or whose invoice's date, falls in
    [start, end] are compared. `invoices` maps a sales invoice id to its row (`invoice_no`, `invoice_date`, `status`, `deleted_at`,
    `is_opening`) for every invoice a record may name: those linked, those dated in the window and those carrying an unlinked
    record's number."""
    declared, b2cl = declared_numbers(payload), _numbers(payload, "b2cl")
    not_declared, differs, compared = [], [], 0
    by_invoice: dict[str, list[dict]] = {}
    ordered = sorted(records, key=lambda r: (str(r.get("invoice_date") or ""), number_key(r.get("invoice_number")), str(r.get("id"))))
    for rec in ordered:
        if not is_live(rec):
            continue
        invoice = _resolve(rec, invoices)
        if not (_in(_day(rec.get("invoice_date")), start, end)
                or (invoice is not None and _in(_day(invoice.get("invoice_date")), start, end))):
            continue
        compared += 1
        base = {"record_id": rec.get("id"), "irn": rec.get("irn"), "sales_invoice_id": rec.get("sales_invoice_id"),
                "record_number": rec.get("invoice_number"), "record_date": _day(rec.get("invoice_date")),
                "linked": bool(rec.get("sales_invoice_id"))}
        by_invoice.setdefault(str(invoice["id"]) if invoice else f"number:{number_key(rec.get('invoice_number'))}", []).append(base)
        reason = _reason(invoice, declared, b2cl, start, end)
        if reason:
            not_declared.append({**base, "reason": reason, "sentence": REASONS[reason].format(
                invoice_date=_dmy(_day((invoice or {}).get("invoice_date")), "an unrecorded date"),
                invoice_number=rec.get("invoice_number") or "(none recorded)")})
        if invoice is not None and (number_key(rec.get("invoice_number")) != number_key(invoice.get("invoice_no"))
                                    or _day(rec.get("invoice_date")) != _day(invoice.get("invoice_date"))):
            differs.append({**base, "invoice_number": invoice.get("invoice_no"),
                            "invoice_date": _day(invoice.get("invoice_date")),
                            "sentence": DIFFERS.format(
                                record_number=rec.get("invoice_number") or "(no number)",
                                record_date=_dmy(_day(rec.get("invoice_date")), "no date"),
                                invoice_number=invoice.get("invoice_no") or "(no number)",
                                invoice_date=_dmy(_day(invoice.get("invoice_date")), "no date"))})
    duplicates = [{"record_ids": [r["record_id"] for r in rows], "invoice_number": rows[0]["record_number"],
                   "sentence": DUPLICATE.format(count=len(rows), invoice_number=rows[0]["record_number"] or "(no number)")}
                  for rows in by_invoice.values() if len(rows) > 1]
    return {"live_irns_compared": compared, "declared_invoices": len(declared), "not_declared": not_declared,
            "differs": differs, "duplicates": duplicates, "converse": CONVERSE, "not_compared": NOT_COMPARED}
