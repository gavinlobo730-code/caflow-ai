"""Sharing a report to a client's portal, under rbac().

── THE DEFECT ───────────────────────────────────────────────────────────────
`shareToPortal` on the client accounting screen built the workbook, uploaded it
to Supabase Storage FROM THE BROWSER, and inserted into `shared_reports` over
PostgREST. `rbac()` ran on neither write, so the only control on publishing a
client's Profit & Loss, Balance Sheet or Trial Balance to that client's own
portal was RLS.

Both privileged writes move here. The workbook is still built in the browser and
posted, and that is deliberate: `lib/export/xlsx.ts` is FORMATTING of figures
the server already computed, which is not business logic — the reports
themselves come from `/api/accounting/{profit-loss,balance-sheet,trial-balance}`.
What the browser must not hold is the ability to write to somebody's storage
bucket and insert a row saying a client may read it.

The upload follows `routers/branding.py`'s logo path, which has done exactly
this since it was written — service client, explicit content type, mock branch
first.
"""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from core.authz import can_access_client
from core.observability import capture_soft_failure
from core.permissions import rbac
from domain.reporting.shared_report import BUCKET, ShareRefused, plan_share
from models.common import api_response
from models.fy import FYLabel
from services.audit_service import log_event

router = APIRouter(prefix="/api/accounting", tags=["accounting"])

_USE_MOCK = not os.environ.get("SUPABASE_URL")


@router.post("/shared-reports")
def share_report_to_portal(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    report_id: str = Form(...),
    report_label: str = Form(...),
    # Annotated[...] rather than `FYLabel = Form(...)`: with `Form()` in the
    # DEFAULT position FastAPI builds the field from it and DISCARDS the
    # Annotated metadata, so the validator never runs and the endpoint merely
    # reads as guarded. `2025-27` would then be stored and mean 2025-26.
    # `= ...` is Ellipsis, not a `Form()` instance: it only satisfies Python's
    # "non-default argument follows default argument", and FastAPI still reads
    # the Annotated metadata, so the label is validated.
    financial_year: Annotated[FYLabel, Form()] = ...,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Publish one statement to a client's portal.

    `report_id` is the SCREEN's id (pl / bs / trial). The column's vocabulary is
    resolved in the domain module, so the browser cannot write a value the CHECK
    refuses — which is what made the Trial Balance button fail silently for as
    long as it existed.
    """
    firm_id = current_user["firm_id"]

    # Assignment scope, not just tenancy. An Executive who cannot see this
    # client must not be able to publish that client's balance sheet, and the
    # message is the same either way so it cannot be used to probe which
    # clients exist.
    if not can_access_client(current_user, client_id):
        raise HTTPException(status_code=404, detail="Client not found")

    content = file.file.read()
    try:
        plan = plan_share(
            client_id=client_id,
            screen_report_id=report_id,
            file_name=file.filename or "report.xlsx",
            content_type=file.content_type,
            size_bytes=len(content),
        )
    except ShareRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # The mock branch's answer, and the shape the live INSERT below writes.
    # They are deliberately two literals — see the note on the insert.
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "report_type": plan.report_type,
        "report_label": report_label,
        "financial_year": financial_year,
        "storage_path": plan.storage_path,
        "file_name": plan.file_name,
        "file_size_bytes": len(content),
        "shared_by": current_user.get("id"),
    }

    if _USE_MOCK:
        return api_response(True, {"shared_report": row})

    from core.supabase_client import get_service_supabase

    svc = get_service_supabase()
    try:
        svc.storage.from_(BUCKET).upload(
            plan.storage_path,
            content,
            file_options={"content-type": plan.content_type, "upsert": "true"},
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the CA as one message
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc

    # THE ROW IS WRITTEN AFTER THE UPLOAD AND THE FAILURE IS CLEANED UP.
    # The browser did these in the same order and did NOT clean up, so every
    # refused insert — which is every Trial Balance share ever attempted — left
    # a file in storage that no row points at. A row without a file is a broken
    # link on the portal; a file without a row is invisible litter that nothing
    # will ever remove.
    # THE PAYLOAD IS SPELLED OUT RATHER THAN PASSED AS `row`, and the seven
    # duplicated keys are the price of schema coverage rather than an oversight.
    # `tests/test_backend_columns_exist_pg.py` checks every column this codebase
    # names against the real schema BY READING THE SOURCE, so an insert whose
    # payload is a NAME — `insert(row)` — is invisible to it and counts against
    # a budget with no headroom. Raising that budget is what the guard's own
    # message invites and is the wrong fix here: the coverage is recoverable, and
    # this is a door that writes a row saying a client may read their own
    # firm's statements. `test_the_two_payload_literals_do_not_drift` holds the
    # two in step.
    try:
        saved = svc.table("shared_reports").insert({
            "firm_id": firm_id,
            "client_id": client_id,
            "report_type": plan.report_type,
            "report_label": report_label,
            "financial_year": financial_year,
            "storage_path": plan.storage_path,
            "file_name": plan.file_name,
            "file_size_bytes": len(content),
            "shared_by": current_user.get("id"),
        }).execute().data
    except Exception as exc:  # noqa: BLE001
        try:
            svc.storage.from_(BUCKET).remove([plan.storage_path])
        except Exception as cleanup:  # noqa: BLE001
            # The insert failure is what the CA is told about; a cleanup that
            # ALSO fails leaves a file in the bucket that nothing points at and
            # nothing will ever remove, which is exactly the quiet kind of
            # failure capture_soft_failure exists for.
            capture_soft_failure(
                cleanup, operation="shared_report.cleanup_orphaned_upload",
                storage_path=plan.storage_path, firm_id=firm_id,
            )
        raise HTTPException(status_code=500, detail=f"Share failed: {exc}") from exc

    log_event(
        firm_id, "shared_report",
        (saved or [{}])[0].get("id") or plan.storage_path, "create",
        actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"),
        new_data=row,
    )
    return api_response(True, {"shared_report": (saved or [row])[0]})
