"""The one read behind GSTR-1 Table 13's coverage note: how many delivery challans the client issued in the window (POST-A-415).

A COUNT OF WHAT THE BOOKS HOLD, AND NOTHING THE RETURN IS BUILT FROM
    `tests/test_the_sales_cycle_before_the_tax_invoice.py::test_no_return_builder_reads_any_of_the_six_tables` keeps the GSTR-1 and GSTR-3B builders
    off the documents that do not declare a supply (a proforma invoice is the trap: it reads like an invoice and a return that picked one up would
    declare a supply that never happened). A delivery challan is not one of those traps in the way a proforma is, because it IS a statutory document
    that left (Rule 55), but this module is the reason the builders stay clean: it reads the challans to COUNT them for a sentence, it feeds no
    payload, and it is a separate module so the builders' own source never names the table. When the challans are declared in Table 13 (the rest of
    POST-A-415, waiting on owner list S30) the guard's list is to be revisited deliberately, not stepped round.
"""
from __future__ import annotations

from typing import Optional

from core.db_paging import fetch_all
from core.observability import capture_soft_failure
from domain.gst.itc_04 import SENT_STATUSES


def issued_challans_by_reason(db, firm_id: str, client_id: str, start: str, end: str) -> Optional[dict]:
    """Delivery challans the client issued in the window, counted by the reason each was issued for.

    "Issued" is a challan that left: issued or received back (`itc_04.SENT_STATUSES`), not a draft and not a cancelled one. A cancelled challan keeps its
    number and the status cannot tell issued-then-cancelled from cancelled-as-a-draft, so cancelled ones are not counted and the sentence says so. This says
    nothing about which Table 13 row a challan belongs in. A read that fails is None and not an empty count, so the return says it could not look rather
    than that nothing was issued.
    """
    try:
        rows = fetch_all(
            lambda: db.table("delivery_challans").select("id, reason")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("status", list(SENT_STATUSES))
                .gte("document_date", start).lte("document_date", end),
            key="id", label="gstr1.table_13.challans")
    except Exception as exc:  # noqa: BLE001 — a missing count is said, never a nil
        capture_soft_failure(exc, operation="gstr1.table_13_challans",
                             firm_id=firm_id, client_id=client_id)
        return None
    counts: dict[str, int] = {}
    for r in rows:
        reason = str(r.get("reason") or "")
        counts[reason] = counts.get(reason, 0) + 1
    return counts
