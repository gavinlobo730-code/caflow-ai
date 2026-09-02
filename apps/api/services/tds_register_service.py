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

    AND A NIL FOREIGN REMITTANCE GETS A ROW TOO. A s.195 bill that withheld
    nothing is still a payment to a non-resident, and Form 27Q reports it with
    a reason for non-deduction. A resident-section bill below its threshold
    does NOT get one, because 26Q reports deductions and that was not one. The
    asymmetry is the statute's.

WHAT THE AMOUNT IS
    payment_amount_paise is the TAXABLE amount, not the gross. Where GST is
    shown separately on the invoice, TDS is deducted on the amount excluding
    GST — CBDT Circular 23/2017 of 19 July 2017. That is also the base the bill
    itself computed the deduction on, so the register and the book agree by
    construction rather than by coincidence.

WHICH RETURN THE ROW BELONGS IN
    26Q for a resident payee, 27Q for a non-resident — Rule 31A(4). The vendor
    carries the fact (migration 308) and domain/tds/residency.py carries the
    rules; nothing is inferred here.

    A vendor NOBODY HAS CLASSIFIED is written as 26Q and REPORTED. That default
    is right for the domestic vendors this platform serves, and refusing every
    bill until every vendor is classified would be a worse failure than the one
    it prevents. What is not acceptable is doing it silently, so sync_for_bill
    returns the gap and a CA can see which deductions were filed on an
    assumption rather than a fact.

    A vendor who IS a non-resident cannot reach this function with a resident
    section on it at all: routers/purchase_bills.py refuses the bill's TDS
    computation first, because s.194C and its neighbours charge only payments
    "to a resident" and s.195 — which this codebase does not rate — is what
    applies instead. So a 27Q row here comes from a bill booked before the
    vendor was reclassified, or from a section that genuinely reaches a
    non-resident. Either way the row states what was true when the tax was
    deducted, which is why the country and TIN are COPIED onto it rather than
    joined at filing time.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from domain.tds.residency import (
    GAP_195_RATES_UNVERIFIED, GAP_27Q_IDENTIFIERS_MISSING,
    GAP_FORM_15CA_NOT_RECORDED, GAP_NO_PE_DECLARATION_UNDATED,
    GAP_RESIDENCY_NOT_CLASSIFIED, FORM_27Q,
    describe_gaps, is_classified, missing_27q_identifiers, return_type_for,
)
from domain.tds.section_195_rates import rates_are_verified

_logger = logging.getLogger("caflow.tds_register")

# A bill is "in the books" — the vendor's account has been credited — in these
# states. A draft has posted no journal entry; a cancelled bill's credit is
# undone. Transcribed from routers/purchase_bills.py's own status vocabulary.
IN_THE_BOOKS = frozenset({"received", "partially_paid", "paid", "overdue"})


def fy_label(on: date) -> str:
    """'2025-26' — the Indian financial year a date falls in, 1 Apr to 31 Mar."""
    start = on.year if on.month >= 4 else on.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def fy_quarter(on: date) -> str:
    """'Q3 2025-26' — the Indian financial year and the quarter within it.

    Q1 Apr-Jun, Q2 Jul-Sep, Q3 Oct-Dec, Q4 Jan-Mar, because the FY runs 1 April
    to 31 March. The format matches the column's own comment in migration 014.
    """
    quarter = ((on.month - 4) % 12) // 3 + 1
    return f"Q{quarter} {fy_label(on)}"


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
    # A FOREIGN REMITTANCE THAT WITHHELD NOTHING IS STILL A REMITTANCE.
    #
    # This used to require deducted > 0, so a payment to a non-resident that
    # withheld NIL — business profits with no permanent establishment, or a
    # treaty with no article for the nature — left no row at all. Those are the
    # two an assessing officer is most likely to ask about: both rest on a
    # CLAIM, and the register 27Q is assembled from had no record the payment
    # happened. It also put the missing-15CA and undated-declaration checks
    # beyond reach, since they sit after this line.
    #
    # A resident-section bill below its threshold still gets NO row: 26Q
    # reports deductions, and a payment that never crossed s.194C's limit is
    # not one. The asymmetry is the statute's, not an inconsistency.
    is_195 = (bill.get("tds_section") or "").strip() == "195"
    on_books = status in IN_THE_BOOKS and not bill.get("deleted_at")
    live = on_books and (deducted > 0 or is_195)

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
        status = v.get("residential_status")
        return_type = return_type_for(status)          # Rule 31A(4)
        # Country and TIN are reported on 27Q and are meaningless on 26Q, which
        # has no field for either — so they go on the row only when the row is
        # a 27Q one. Writing them on a 26Q row would put a value in a column the
        # return never reads, which reads later as "somebody meant something by
        # this".
        is_27q = return_type == FORM_27Q
        # Why nothing was withheld, where nothing was. The engine's own
        # sentence, not an FVU remark code: those are a published list and
        # guessing one would put a wrong code in a filed return, so mapping
        # this to a code is a human step (migration 312).
        non_deduction_reason = None
        if deducted == 0 and is_195:
            non_deduction_reason = (
                bill.get("_tds_citation")
                or f"Nil withheld under section 195 — basis "
                   f"'{bill.get('tds_basis') or 'not recorded'}'.")
        gaps: list[str] = []
        if not is_classified(status):
            gaps.append(GAP_RESIDENCY_NOT_CLASSIFIED)
        elif is_27q:
            missing = missing_27q_identifiers(v)
            if missing:
                gaps.append(GAP_27Q_IDENTIFIERS_MISSING)
        # A s.195 withholding computed on a year nobody has confirmed against
        # the Finance Act. Asked of the year the BILL falls in, not today's:
        # a bill entered late for a prior year was withheld at that year's law.
        is_195 = (bill.get("tds_section") or "").strip() == "195"
        if is_195 and not rates_are_verified(fy_label(when)):
            gaps.append(GAP_195_RATES_UNVERIFIED)
        # A nil resting on a declaration nobody dated or attributed. Reported
        # only where the nil was actually RELIED ON — a vendor that holds a
        # declaration and is withheld at a rate anyway has not used it.
        if (is_195 and v.get("no_pe_declaration_on_file")
                and not (v.get("no_pe_declaration_on")
                         and v.get("no_pe_declaration_by"))):
            gaps.append(GAP_NO_PE_DECLARATION_UNDATED)
        # Rule 37BB with s.195(6) wants Form 15CA before the remittance. This
        # cannot block the bill — the form is filed on a portal, and CLAUDE.md
        # forbids submitting to one from here — but the gap between money
        # leaving and the form existing should not be invisible.
        if is_195 and not (bill.get("form_15ca_ack_no") or "").strip():
            gaps.append(GAP_FORM_15CA_NOT_RECORDED)
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
            # 27Q needs to say what the remittance was FOR. nature_of_payment
            # has existed since migration 037 and nothing ever wrote it.
            "nature_of_payment": (bill.get("tds_nature_of_income") or None),
            "transaction_date": when.isoformat(),
            # Excluding GST — CBDT Circular 23/2017.
            "payment_amount_paise": int(bill.get("taxable_amount_paise") or 0),
            "tds_rate_pct": rate_pct,
            "tds_paise": deducted,
            # Form 27Q reports tax, surcharge and cess in separate columns of
            # the deductee annexure, so the split has to survive from the bill
            # to the register. Always 0 on a resident-section bill, which
            # deducts at the bare section rate and carries neither.
            "surcharge_paise": int(bill.get("tds_surcharge_paise") or 0),
            "cess_paise": int(bill.get("tds_cess_paise") or 0),
            "quarter": fy_quarter(when),
            "return_type": return_type,
            "country_of_residence": (v.get("country_of_residence") or None) if is_27q else None,
            "deductee_tin": (v.get("tax_identification_number") or None) if is_27q else None,
            "non_deduction_reason": non_deduction_reason,
        }, on_conflict="purchase_bill_id").execute()
        out = {"synced": True, "action": "recorded", "tds_paise": deducted,
               "quarter": fy_quarter(when), "return_type": return_type}
        if gaps:
            # Named, machine-readable, and beside the vendor it is about — the
            # same shape payroll's statutory_gaps uses. A gap that only exists
            # in a log is the failure this whole module was written to fix.
            out["statutory_gaps"] = gaps
            # The codes AND what they mean. A caller that only had codes would
            # have to re-implement the wording, which is how two screens end up
            # describing the same gap differently.
            out["gap_details"] = describe_gaps(gaps)
            out["vendor_id"] = v.get("id")
            out["vendor_name"] = v.get("name")
        return out
    except Exception as e:                                      # noqa: BLE001
        _logger.error(
            "TDS register out of step with bill %s (firm=%s client=%s, %s paise "
            "deducted under %s): %s — the deduction is in the books but will be "
            "missing from the challan and from 26Q until this is repaired.",
            bill_id, firm_id, client_id, deducted, bill.get("tds_section"), e)
        return {"synced": False, "reason": str(e)}
