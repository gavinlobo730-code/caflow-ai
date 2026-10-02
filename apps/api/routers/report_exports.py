"""Server-made PDF and Excel of the live reports (accounting-16).

A thin wrapper over `services/report_export_service`, which calls the very
report function each screen calls — see its header for why that is the whole
design. This module decides only WHO may ask and HOW the file travels.

A SEPARATE ROUTER, AND NOT `/api/accounting/...`. Its routes return a FILE, not
the `{success, data, error}` envelope the rest of that prefix returns, and
`routers/accounting.py` is already 1,500 lines of report endpoints that a CA's
screen reads as JSON. Putting a binary download among them would make the next
reader assume the contract still holds — the reasoning that kept the FX
revaluation POST out of `routers/fx_reports.py` and CWIP off
`/api/fixed-assets`.

`client_id` IS REQUIRED. A PDF is headed by whose books it is, and a firm-wide
ledger would add together the books of unrelated businesses — which is not a
figure that means anything (the same reasoning `/api/accounting/cash-book`
records). It is checked against the caller's client scope, and the report
itself is built from `routers.accounting._reporting_service(current_user)` so
the caller's assignment scope is the screen's.
"""
from __future__ import annotations

import logging
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from core.authz import assert_client_access
from core.permissions import rbac
from domain.reporting.export_document import ExportRefused
from services import report_export_service as exports
from core import db_provider

_logger = logging.getLogger("caflow.report_exports")

router = APIRouter(prefix="/api/report-exports", tags=["accounting"])

#: A date the reports will read. The existing report endpoints take a bare
#: string; a malformed one here would be formatted into a filename and a PDF
#: header, so it is refused at the door.
_DATE = r"^\d{4}-\d{2}-\d{2}$"

ReportName = Literal["ledger", "trial-balance", "cash-flow", "ar-ageing", "ap-ageing"]


# The privileged client, or None with no database (mock/dev).
#
# Every route here is rbac()-gated and reads only; this is the same choice
# `routers/accounting._prod_db` makes for the reports it serves.
_prod_db = db_provider.service_db_or_none


@router.get("/{report}")
def export_report(
    report: ReportName,
    client_id: str = Query(..., description="Whose books — required"),
    format: Literal["pdf", "xlsx"] = Query("pdf"),
    account_id: Optional[str] = Query(None, description="Ledger only"),
    start_date: Annotated[Optional[str], Query(pattern=_DATE)] = None,
    end_date: Annotated[Optional[str], Query(pattern=_DATE)] = None,
    as_of_date: Annotated[Optional[str], Query(pattern=_DATE)] = None,
    as_of: Annotated[Optional[str], Query(pattern=_DATE)] = None,
    basis: str = Query("accrual", pattern="^(accrual|cash)$"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Download one report as a PDF (or, for the ledger and cash flow, a
    spreadsheet). The parameters are the screen's own: `start_date`/`end_date`
    for the ledger and cash flow, `as_of_date` (+ optional `start_date`) for the
    trial balance, `as_of` for the two ageing reports."""
    assert_client_access(current_user, client_id)
    db = _prod_db()
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Exports are built from the live books and are unavailable "
                   "without the database.")
    from routers.accounting import _reporting_service
    try:
        out = exports.export_report(
            report, format, svc=_reporting_service(current_user), db=db,
            firm_id=current_user["firm_id"], client_id=client_id,
            params={"account_id": account_id, "start_date": start_date,
                    "end_date": end_date, "as_of_date": as_of_date, "as_of": as_of,
                    "basis": basis})
    except ExportRefused as e:
        # A refusal is the answer, in words — not an "Internal server error".
        raise HTTPException(status_code=422, detail=str(e))
    return Response(
        content=out.content, media_type=out.media_type,
        headers={"Content-Disposition": f'attachment; filename="{out.filename}"'})
