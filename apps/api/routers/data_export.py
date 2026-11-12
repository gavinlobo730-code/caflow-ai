"""A Partner's export of one client's books as a ZIP of CSV files (POST-A-205, slice 1).

The build is `services/client_books_export_service`; this module decides only WHO may ask and HOW the file travels.

WHO. A Partner, asked twice: `firm:admin` (the role grid gives it to the Partner alone) AND the role itself. The second is not decoration: `rbac` honours a
per-person grant, a Partner may give `firm:admin` to anyone, and two-factor is required of the Partner and Manager roles only, so a granted Executive would
otherwise be handed a client's whole books at the lowest sign-in level. Behind the same two-factor guard as payroll, and a client the caller may reach. The file
holds a client's customers and vendors by name, PAN and GSTIN and every posting in the books: it is the most portable copy of a client the product can make, and
the guard is as heavy as the file.

THE AUDIT ROW COMES FIRST AND THE DOWNLOAD IS REFUSED WITHOUT IT. `audit_service.log_event` swallows its failures, which is right for a change that already
happened and wrong here: an export that left no account of who took it is the thing a firm's auditor asks about. The request is written to `audit_log` through the
service client before one row is read, and if that write fails the answer is a 503 that says nothing was exported. When the build finishes, a second row records
what it produced (the rows, the problems); when it is refused or stopped, a second row says so.

A FILE, NOT THE ENVELOPE. Like `routers/report_exports.py`, it returns the bytes with `Content-Disposition`, because a browser's download cannot read
`{success, data, error}`. What the build found wrong with itself travels in `X-Export-Problems`, as the bulk payslip zip's does, because a file cannot carry a message.
"""
from __future__ import annotations

import hashlib
import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from core import db_provider
from core.authz import assert_client_access, firmwide_roles_label, is_firmwide
from core.permissions import rbac
from domain.reporting.export_document import ExportRefused
from services import audit_service
from services import client_books_export_service as books

_logger = logging.getLogger("caflow.data_export")

router = APIRouter(prefix="/api/data-export", tags=["data-export"])

#: The privileged client, or None with no database (mock/dev). Every request the build makes names the firm and the client.
_prod_db = db_provider.service_db_or_none

#: The firms with an export running in this process. One at a time per firm: a build holds a worker thread, a page of rows and the finished file for up to ninety
#: seconds, and the button's disabled state is the browser's alone. In-process, which is right for the one worker this runs on.
_running: set[str] = set()
_running_lock = threading.Lock()


def _record_the_request_or_refuse(*, firm_id: str, client_id: str, actor: dict) -> None:
    """Write the audit row that says who asked for the export, or refuse. Not `audit_service.log_event`, which swallows its failures."""
    from core.supabase_client import get_service_supabase
    try:
        get_service_supabase().table("audit_log").insert({
            "firm_id": firm_id,
            "actor_id": actor.get("auth_user_id"),          # the AUTH id: that is the audit log's flavour of actor
            "actor_email": actor.get("email"),
            "entity_type": "client_books_export",
            "entity_id": client_id,
            "action": "export_requested",
            "old_data": None,
            "new_data": {"schema": books.SCHEMA},
            "metadata": {"client_id": client_id},
        }).execute()
    except Exception as exc:                                # noqa: BLE001
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="data_export.request_audit", firm_id=firm_id, client_id=client_id)
        raise HTTPException(
            status_code=503,
            detail="Nothing was exported, because the audit log could not be written just now and the audit log is the only account of who took a client's books. "
                   "Try again in a moment.") from exc


@router.get("/client-books")
def export_client_books(
    client_id: str = Query(..., min_length=1, description="Whose books: required"),
    current_user: dict = Depends(rbac("firm", "admin")),
):
    """Download one client's books as a ZIP of CSV files with a manifest (see `services/client_books_export_service` for what is and is not in it)."""
    if not is_firmwide(current_user):
        raise HTTPException(status_code=403, detail=f"A client's books can be exported by {firmwide_roles_label()} only.")
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    db = _prod_db()
    if db is None:
        raise HTTPException(status_code=503, detail="The export is built from the live books and is unavailable without the database.")
    with _running_lock:
        busy = firm_id in _running
        _running.add(firm_id)
    if busy:
        raise HTTPException(status_code=409, detail="An export for this firm is already being prepared. Wait for it to finish, then try again.")
    try:
        return _export(current_user, firm_id, client_id, db)
    finally:
        with _running_lock:
            _running.discard(firm_id)


def _export(current_user: dict, firm_id: str, client_id: str, db) -> Response:
    _record_the_request_or_refuse(firm_id=firm_id, client_id=client_id, actor=current_user)

    def say(action: str, detail: dict) -> None:
        audit_service.log_event(firm_id, "client_books_export", client_id, action, actor_id=current_user.get("auth_user_id"),
                                actor_email=current_user.get("email"), new_data=detail, metadata={"client_id": client_id})

    try:
        out = books.build(db, firm_id, client_id, exported_by=current_user.get("auth_user_id"))
    except books.ExportStopped as e:
        say("export_stopped", {"reason": str(e)})
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ExportRefused as e:
        # A refusal is the answer, in words: not an "Internal server error".
        say("export_refused", {"reason": str(e)})
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:                                  # noqa: BLE001
        _logger.error("client books export failed for firm=%s client=%s: %s", firm_id, client_id, e, exc_info=True)
        say("export_failed", {"reason": "the build raised"})
        raise HTTPException(status_code=500, detail="The export failed and nothing was downloaded. It has been logged; try again, and if it keeps failing tell support.") from e
    say("export_completed", {"files": len(out.manifest["files"]), "rows": sum(f["rows"] for f in out.manifest["files"]),
                             "problems": len(out.problems), "bytes": len(out.content),
                             "zip_sha256": hashlib.sha256(out.content).hexdigest()})
    headers = {"Content-Disposition": f'attachment; filename="{out.filename}"', "Cache-Control": "private, no-store"}
    if out.problems:
        # A header holds one line: the problems are counted here and listed in manifest.json and README.txt inside the file.
        headers["X-Export-Problems"] = f"{len(out.problems)} problem(s) found; see manifest.json inside the file"
    return Response(content=out.content, media_type="application/zip", headers=headers)
