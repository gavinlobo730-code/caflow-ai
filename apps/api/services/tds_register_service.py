"""
The TDS deduction register, kept in step with the bills that make the deductions.

WHY THIS EXISTS
    TDS was computed correctly on a purchase bill and went nowhere. The figure
    landed on purchase_bills.tds_paise, was netted off what the vendor is paid,
    and never reached tds_deductions — which nothing in the codebase had ever
    written to. So the deduction was real in the books and invisible to
    compliance: no challan to pay by the 7th (Rule 30), nothing to assemble
    26Q from (Rule 31A), and GET /api/tds/deductions/{client_id} returning an
    empty list.

WHEN A ROW EXISTS, WHICH IS A STATUTORY QUESTION AND NOT A UI ONE
    Section 194C(3), 194J(1) and their neighbours all say the same thing: the
    deduction falls due at the time of CREDIT to the payee's account or of
    PAYMENT, whichever is EARLIER. Booking the bill is the credit.

    A DRAFT bill is not a credit — it posts no journal entry, so nothing has
    been credited to the vendor and no liability has arisen. A cancelled bill
    is a credit undone. So the register carries a row exactly while the bill is
    in the books, and sync_for_bill() is called on every transition rather than
    only on create: an edited bill updates its row, a cancelled one loses it.

WHAT THE AMOUNT IS
    payment_amount_paise is the TAXABLE amount, not the gross. Where GST is
    shown separately on the invoice, TDS is deducted on the amount excluding
    GST — CBDT Circular 23/2017 of 19 July 2017. That is also the base the bill
    itself computed the deduction on, so the register and the book agree by
    construction rather than by coincidence.

WHAT IS NOT MODELLED, SAID PLAINLY
    return_type is always '26Q'. 26Q is the correct quarterly statement for
    non-salary payments to RESIDENTS; a payment to a non-resident belongs in
    27Q under Rule 31A(4)(b). Nothing in this schema records a vendor's
    residency — there is no such column on `vendors` — so residency cannot be
    derived, and guessing it would put a foreign remittance in the wrong return.
    Adding it is a human step, like the MSMED classification: a residency flag
    on the vendor, then a branch here. Until then every deduction is reported
    as 26Q, which is right for the domestic vendors this platform is built for
    and wrong for a non-resident nobody has told it about.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

_logger = logging.getLogger("caflow.tds_register")

# A bill is "in the books" — the vendor's account has been credited — in these
# states. A draft has posted no journal entry; a cancelled bill's credit is
# undone. Transcribed from routers/purchase_bills.py's own status vocabulary.
IN_THE_BOOKS = frozenset({"received", "partially_paid", "paid", "overdue"})


def fy_quarter(on: date) -> str:
    """'Q3 2025-26' — the Indian financial year and the quarter within it.

    Q1 Apr-Jun, Q2 Jul-Sep, Q3 Oct-Dec, Q4 Jan-Mar, because the FY runs 1 April
    to 31 March. The format matches the column's own comment in migration 014.
    """
    fy_start = on.year if on.month >= 4 else on.year - 1
    quarter = ((on.month - 4) % 12) // 3 + 1
    return f"Q{quarter} {fy_start}-{str(fy_start + 1)[2:]}"


def _as_date(v) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except (ValueError, TypeError):
        return None


def sync_for_bill(db, firm_id: str, client_id: str, bill: dict,
                  vendor: Optional[dict] = None) -> dict:
    """Make the register agree with one bill. Returns what it did.

    Never raises into the caller's path: a bill that posted correctly must not
    be rolled back because its register row could not be written. A failure is
    logged loudly and reported in the return value, because a silently missing
    deduction is a missed challan and an under-reported 26Q.
    """
    bill_id = bill.get("id")
    if db is None or not bill_id:
        return {"synced": False, "reason": "no database"}

    deducted = int(bill.get("tds_paise") or 0)
    status = (bill.get("status") or "").lower()
    live = status in IN_THE_BOOKS and deducted > 0 and not bill.get("deleted_at")

    try:
        if not live:
            # Draft, cancelled, deleted, or nothing was deducted — no row.
            db.table("tds_deductions").delete().eq(
                "purchase_bill_id", bill_id).eq("firm_id", firm_id).execute()
            return {"synced": True, "action": "removed", "reason": status or "no tds"}

        when = _as_date(bill.get("bill_date")) or date.today()
        # bps -> percent for a NUMERIC(5,2) column: 2000 bps is 20.00%.
        rate_pct = round(int(bill.get("tds_rate_bps") or 0) / 100, 2)
        v = vendor or {}
        # Payload written INLINE with literal keys — tests/test_backend_columns_
        # exist_pg.py can only read a query whose table name and payload keys
        # are both string constants.
        db.table("tds_deductions").upsert({
            "firm_id": firm_id,
            "client_id": client_id,
            "purchase_bill_id": bill_id,
            "deductee_name": (v.get("name") or "(vendor not found)"),
            "deductee_pan": (v.get("pan") or None),
            "section": (bill.get("tds_section") or ""),
            "transaction_date": when.isoformat(),
            # Excluding GST — CBDT Circular 23/2017.
            "payment_amount_paise": int(bill.get("taxable_amount_paise") or 0),
            "tds_rate_pct": rate_pct,
            "tds_paise": deducted,
            "quarter": fy_quarter(when),
            "return_type": "26Q",
        }, on_conflict="purchase_bill_id").execute()
        return {"synced": True, "action": "recorded", "tds_paise": deducted,
                "quarter": fy_quarter(when)}
    except Exception as e:                                      # noqa: BLE001
        _logger.error(
            "TDS register out of step with bill %s (firm=%s client=%s, %s paise "
            "deducted under %s): %s — the deduction is in the books but will be "
            "missing from the challan and from 26Q until this is repaired.",
            bill_id, firm_id, client_id, deducted, bill.get("tds_section"), e)
        return {"synced": False, "reason": str(e)}
