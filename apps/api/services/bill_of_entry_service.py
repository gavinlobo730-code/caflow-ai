"""Reads a Bill of Entry, and posts what customs assessed (PUR-18).

The domain rule is `domain/gst/bill_of_entry.py`; this file fetches its inputs
and writes. Nothing here decides which figure is credit and which is cost.

WHAT THE JOURNAL LOOKS LIKE AND WHY

    Dr GST Input Credit - IGST            the creditable integrated tax
    Dr Compensation Cess Input Credit     the creditable cess
    Dr <the duty account the CA names>    basic customs duty + surcharge +
                                          other levies + any blocked tax
        Cr <the account it was paid from> the whole assessment

    NO ACCOUNTS PAYABLE LEG. The supplier is not owed this money — customs is,
    and it is paid before the goods are cleared (Customs Act s.47). Debiting
    Trade Payables here would net the duty off what the supplier is owed, which
    is what putting the assessment on the purchase bill does wrong.

    The credit legs use the SAME system keys the purchase path uses, so an
    import's credit lands in the same ledger as every other input tax and
    `_gl_gst_movements` can see it. `gst_cess_input` rather than the GST input
    account for cess: the proviso to s.11(2) of the Compensation Act lets cess
    credit pay only cess, and migration 374 gave it its own ledger for exactly
    that reason.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from domain.accounting import journal_source
from domain.gst import bill_of_entry as boe

_logger = logging.getLogger("caflow.bill_of_entry")

#: Every column a read needs. Named once so a read that omits one cannot
#: silently hand the rule a zero — the shape INV-08 and PUR-19 both use.
COLUMNS = (
    "id, firm_id, client_id, be_number, be_date, port_code, vendor_id, "
    "purchase_bill_id, assessable_value_paise, basic_customs_duty_paise, "
    "social_welfare_surcharge_paise, other_duty_paise, igst_paise, cess_paise, "
    "ineligible_igst_paise, ineligible_cess_paise, is_sez, payment_account_id, "
    "duty_expense_account_id, status, journal_entry_id, notes, created_at, "
    "created_by, posted_at, posted_by, deleted_at"
)


def _first(rows) -> Optional[dict]:
    rows = rows or []
    return rows[0] if rows else None


def get(db, firm_id: str, be_id: str) -> dict:
    row = _first(db.table("bills_of_entry").select(
        "id, firm_id, client_id, be_number, be_date, port_code, vendor_id, "
        "purchase_bill_id, assessable_value_paise, basic_customs_duty_paise, "
        "social_welfare_surcharge_paise, other_duty_paise, igst_paise, "
        "cess_paise, ineligible_igst_paise, ineligible_cess_paise, is_sez, "
        "payment_account_id, duty_expense_account_id, status, "
        "journal_entry_id, notes, created_at, created_by, posted_at, "
        "posted_by, deleted_at")
        .eq("id", be_id).eq("firm_id", firm_id).limit(1).execute().data)
    if not row or row.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Bill of Entry not found.")
    return row


def listing(db, firm_id: str, client_id: str, *, start: Optional[str] = None,
            end: Optional[str] = None) -> list[dict]:
    """Every live Bill of Entry for a client, newest first, with the rule's
    own reading of each attached."""
    def _q():
        q = (db.table("bills_of_entry").select(
                "id, firm_id, client_id, be_number, be_date, port_code, "
                "vendor_id, purchase_bill_id, assessable_value_paise, "
                "basic_customs_duty_paise, social_welfare_surcharge_paise, "
                "other_duty_paise, igst_paise, cess_paise, "
                "ineligible_igst_paise, ineligible_cess_paise, is_sez, "
                "payment_account_id, duty_expense_account_id, status, "
                "journal_entry_id, notes, created_at, created_by, posted_at, "
                "posted_by, deleted_at")
             .eq("firm_id", firm_id).eq("client_id", client_id)
             .is_("deleted_at", "null"))
        if start:
            q = q.gte("be_date", start)
        if end:
            q = q.lte("be_date", end)
        return q

    rows = fetch_all(_q, key="id", label="bills_of_entry")
    out: list[dict] = []
    for r in rows:
        a = boe.assessment_of(r)
        ready = boe.readiness(r, a)
        out.append({
            **r,
            "total_paise": a.total_paise,
            "creditable_igst_paise": a.creditable_igst_paise,
            "creditable_cess_paise": a.creditable_cess_paise,
            "non_creditable_duty_paise": a.non_creditable_duty_paise,
            "gstr2b_section": boe.section_for(r),
            "can_post": ready.ok,
            "refusals": ready.refusals,
            "caveats": ready.caveats,
        })
    out.sort(key=lambda r: (str(r.get("be_date") or ""), str(r.get("id"))),
             reverse=True)
    return out


def for_period(db, firm_id: str, client_id: str, start: str, end: str) -> list[dict]:
    """POSTED bills of entry assessed in a period — what the return declares.

    Only posted ones. A draft has no journal behind it, and Table 4(A)(1)
    claiming credit the ledger does not carry is the books-vs-ledger difference
    this whole return exists to avoid.
    """
    return [r for r in listing(db, firm_id, client_id, start=start, end=end)
            if r.get("status") == "posted"]


def post(db, firm_id: str, be_id: str, *, actor_id: Optional[str] = None) -> dict:
    """Post the assessment to the ledger.

    # CA REVIEW REQUIRED — the CA confirms the figures before this is called.
    # Nothing here transmits anything to any portal.
    """
    row = get(db, firm_id, be_id)
    if row.get("status") == "posted":
        raise HTTPException(
            status_code=409,
            detail="This Bill of Entry is already posted. A correction is a "
                   "reversal, never a second posting.")

    assessment = boe.assessment_of(row)
    ready = boe.readiness(row, assessment)
    if not ready.ok:
        raise HTTPException(status_code=422, detail=" ".join(ready.refusals))

    client_id = row.get("client_id") or ""
    be_date = str(row.get("be_date"))

    # BOTH PERIOD QUESTIONS. `validate_posting_date` is the FIRM's financial-year
    # switch and takes no client_id, so it cannot know that this client's
    # GSTR-3B for the month is already filed — and a Bill of Entry IS a
    # document that feeds a return: its IGST is Table 4(A)(1).
    from services.period_validation_service import period_validation_service
    from services import period_lock_service
    period_validation_service.validate_posting_date(firm_id, be_date)
    period_lock_service.assert_open(db, firm_id, client_id, be_date)

    from services.phase2_journal_service import phase2_journal_service as pjs

    lines: list[dict] = []
    if assessment.creditable_igst_paise:
        lines.append({
            # The SAME resolution every other input-tax leg uses —
            # `%GST Input%` with system key `gst_input` — so an import's
            # credit lands in the ledger `_gl_gst_movements` already reads and
            # the books-vs-ledger reconciliation can see it. There is no
            # per-head input key in this chart; the head is in the narration.
            "account_id": pjs._find_account(db, firm_id, client_id,
                                            "%GST Input%",
                                            system_key="gst_input"),
            "debit_paise": assessment.creditable_igst_paise,
            "credit_paise": 0,
            # CGST Act s.2(62)(a) with Rule 36(1)(d).
            "narration": f"IGST on Bill of Entry {row.get('be_number')}",
        })
    if assessment.creditable_cess_paise:
        lines.append({
            # Its OWN ledger, never the GST input account: the proviso to
            # s.11(2) of the Compensation Act lets cess credit pay only cess,
            # and migration 374 gave it a name that avoids the "GST Input"
            # substring for exactly that reason.
            "account_id": pjs._find_account(db, firm_id, client_id,
                                            "%Compensation Cess Input Credit%",
                                            system_key="gst_cess_input"),
            "debit_paise": assessment.creditable_cess_paise,
            "credit_paise": 0,
            "narration": f"Compensation cess on Bill of Entry {row.get('be_number')}",
        })
    if assessment.non_creditable_duty_paise:
        lines.append({
            # The CA's own account. Not resolved by name: AS-2 paragraph 6 puts
            # this in the cost of purchase and which head that is depends on
            # what was imported.
            "account_id": row.get("duty_expense_account_id"),
            "debit_paise": assessment.non_creditable_duty_paise,
            "credit_paise": 0,
            "narration": "Customs duty and surcharge (not input tax)",
        })
    lines.append({
        "account_id": row.get("payment_account_id"),
        "debit_paise": 0,
        "credit_paise": assessment.total_paise,
        "narration": f"Paid to customs on Bill of Entry {row.get('be_number')}",
    })

    journal_id = pjs._create_journal(
        db, firm_id, client_id, be_date,
        reference_no=f"BOE-{row.get('be_number')}",
        narration=(f"Bill of Entry {row.get('be_number')} dated {be_date}"
                   + (f" at {row.get('port_code')}" if row.get("port_code") else "")),
        entry_type="Payment",
        lines=lines,
        source_type=journal_source.BILL_OF_ENTRY,
        source_id=be_id,
        created_by=actor_id,
    )

    from datetime import datetime, timezone
    updated = (db.table("bills_of_entry")
               .update({"status": "posted", "journal_entry_id": journal_id,
                        "posted_at": datetime.now(timezone.utc).isoformat(),
                        "posted_by": actor_id})
               .eq("id", be_id).eq("firm_id", firm_id).execute().data)
    return _first(updated) or {**row, "status": "posted",
                               "journal_entry_id": journal_id}
