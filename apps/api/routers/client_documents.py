"""A client's documents (the vault, the Documents tab and the files shared with the client's portal), under rbac().

POST-A-010. Three screens read `client_documents` straight from PostgREST, put the file in Storage from the browser
and inserted or deleted the row themselves: the firm-wide Document Vault, a client's Documents tab, and the Client
Portal management page. The only control on that path was the database's row security, and the rules the API
applies everywhere else (the Documents permission a Partner sets on the Team screen, the bounds on an upload, the name
the file is stored under) were not asked at all: the browser chose the storage key from the file's own name and sent
whatever bytes it was given.

All four things those screens did are routes here: list, upload, a signed link, and delete.

WHAT EACH ROUTE ASKS
  * list and link: `document:read`, the client's assignment, and the firm. The rows are read in keyset pages of the
    server's own (`core.db_paging`), because PostgREST cuts a response at about a thousand rows without a word and
    the lists are newest first, so the cut took the oldest documents from the only list they can be opened from.
  * upload: `document:write` (Executive and above, the tier migration 261 gives the table), the same bounded,
    typed and renamed read every other upload goes through (`core.uploads.accept_upload`), a storage key the SERVER
    builds under the firm and the client, and a record that is written or the file is taken out again.
  * delete: `document:delete`, which is Partner only (migrations 261 and 469 ask `my_role_at_least('Partner')` of the
    row and of the file, and the two have to agree). The file goes first and the record second, as the browser did,
    so a deleted record never leaves the document's content behind; but the server FIRST asks whether anything still
    points at the record (a later version, a tax claim's evidence, a Form 26AS upload), because the browser learned
    that only after the file was gone and was left with an entry that would not open.

THE ROWS ARE THE CALLER'S. They are read and written through the caller's own database client, so row security is the
second lock and the audit trigger names the person. Storage is touched through the request's client
(`core.supabase_client.get_supabase`), as every other upload route does (`routers/documents.py`): under `USE_USER_JWT`
that is the caller's own token, so migration 469's Storage policies (the client's assignment, the write permission and
Partner-only delete) are asked of the file as well as the checks above.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from core import db_provider
from core.authz import assert_client_access, can_access_client
from core.db_paging import fetch_all
from core.ist_clock import ist_now
from core.observability import capture_soft_failure
from core.permissions import rbac
from core.uploads import MB, accept_upload, safe_path_segment
from models.common import api_response
from models.fy import OptionalFYLabel
from services.audit_service import log_event
from services.internal_client_service import assert_partner_for_internal_id

router = APIRouter(prefix="/api/client-documents", tags=["documents"])
_logger = logging.getLogger("caflow.client_documents")

_USE_MOCK = not os.environ.get("SUPABASE_URL")

BUCKET = "Documents"

#: What a client document may weigh. Over the 10 MB every attachment shares, because a scanned set of accounts is
#: often larger, and under the 32 MB the request body is capped at (`middleware/body_limit.py`). The screens said 50 MB
#: in the browser and nothing enforced it.
MAX_BYTES = 25 * MB

#: The categories the vault files a document under. `client_documents.doc_type` has no constraint of its own, so the
#: route is the vocabulary: a free string here is whatever a caller typed.
CATEGORIES = ("Identity", "GST", "Income Tax", "MCA", "Financials", "Other")

#: How long a signed link lives. One document opened now, and a whole list of links minted for a page that stays open.
LINK_SECONDS = 300
LIST_LINK_SECONDS = 3600

def _references(db, firm_id: str, doc_id: str):
    """What still points at a client document, as (what to call it, the query that finds one). A record something
    points at cannot be deleted (a foreign key refuses it), and the browser found that out after the file was gone.
    Each query is written out, with the firm on it, so the firm-scope guard can read every one of them."""
    return (
        ("a later version of it", db.table("client_documents").select("id")
         .eq("firm_id", firm_id).eq("parent_document_id", doc_id).limit(1)),
        ("a Form 26AS upload", db.table("form_26as_uploads").select("id")
         .eq("firm_id", firm_id).eq("document_id", doc_id).limit(1)),
        ("a tax deduction claim", db.table("tax_deduction_claims").select("id")
         .eq("firm_id", firm_id).eq("evidence_document_id", doc_id).limit(1)),
        ("a tax disallowance", db.table("tax_disallowances").select("id")
         .eq("firm_id", firm_id).eq("evidence_document_id", doc_id).limit(1)),
    )

_MOCK_ROWS: list[dict] = []


def _db():
    return None if _USE_MOCK else db_provider.request_db()


def _storage():
    from core.supabase_client import get_supabase
    return get_supabase().storage.from_(BUCKET)


def _server_storage():
    """The bucket as the SERVER, for the one thing the caller's own token cannot do: take away a file this request just
    stored. Migration 469 lets only a Partner delete from the bucket, and Storage answers a denied removal with an empty
    list and no error, so a clean-up through the caller's client would leave an Executive's orphaned file in place without
    a word. The key was built by the server under the caller's own firm and client a moment ago, so removing it is not an
    escalation."""
    from core.supabase_client import get_service_supabase
    return get_service_supabase().storage.from_(BUCKET)


def _take_out_again(path: str, *, operation: str) -> None:
    """Remove a file this request stored and whose record could not be written. Reports, and does not raise, if it
    cannot: the caller is already failing with the real reason."""
    try:
        gone = _server_storage().remove([path])
    except Exception as exc:  # noqa: BLE001 - the original failure is the one to report
        capture_soft_failure(exc, operation=operation)
        return
    if not gone:
        capture_soft_failure(RuntimeError(f"the file {path} was not removed"), operation=operation)


def _owns_path(firm_id: str, client_id: str, path: object) -> bool:
    """Whether a stored key sits under this firm and client. Every upload route builds `{firm}/{client}/...`, and the columns
    that hold a key are writable by an Executive over PostgREST, so a row can be made to name somebody else's object; a key
    outside the row's own firm and client is never signed and never removed from here."""
    return isinstance(path, str) and path.startswith(f"{firm_id}/{client_id}/") and ".." not in path


def _own_row(current_user: dict, doc_id: str) -> dict:
    """The record, if it is in the caller's firm and the caller is assigned to its client.

    One fixed 404 covers a missing id, another firm's and an unassigned client's, so the answer is not an existence
    oracle (`routers/documents._assert_document_scope` says the same)."""
    db = _db()
    if db is None:
        row = next((r for r in _MOCK_ROWS if r["id"] == doc_id), None)
    else:
        # The columns a screen is given, plus the firm to check. They are spelled out in each query and not held in a
        # constant, so the column-existence guard can read every one of them against the real schema.
        res = (db.table("client_documents").select(
            "id, client_id, firm_id, file_name, description, doc_type, file_path, file_size, mime_type, expiry_date, "
            "financial_year, uploaded_by, version, parent_document_id, created_at")
            .eq("id", doc_id).eq("firm_id", current_user["firm_id"]).execute())
        row = (res.data or [None])[0]
    if not row or row.get("firm_id") != current_user["firm_id"] or not can_access_client(current_user, row.get("client_id")):
        raise HTTPException(status_code=404, detail="Document not found")
    return row


#: How many links one request to Storage asks for. A client can hold thousands of documents; the request body and the cost of
#: the per-object fallback below both stay bounded this way.
SIGN_BATCH = 200


def _sign_many(paths: list[str], seconds: int) -> dict[str, str]:
    """path -> signed link, in batches. A path that could not be signed is simply absent."""
    if not paths or _USE_MOCK:
        return {}
    store = _storage()
    links: dict[str, str] = {}
    for start in range(0, len(paths), SIGN_BATCH):
        batch = paths[start:start + SIGN_BATCH]
        try:
            out = store.create_signed_urls(batch, seconds)
        except Exception as exc:  # noqa: BLE001
            # The batch call raises for the WHOLE batch when Storage answers one path with a null link (an object that is
            # gone, or one the caller may not read), which would blank every other document's button. Sign that batch one at
            # a time, so the one that cannot be signed is the only one without a link.
            capture_soft_failure(exc, operation="client_documents.sign_many")
            links.update(_sign_each(store, batch, seconds))
            continue
        for item in out or []:
            path = item.get("path")
            url = item.get("signedURL") or item.get("signedUrl")
            if path and url:
                links[path] = url
    return links


def _sign_each(store, paths: list[str], seconds: int) -> dict[str, str]:
    links: dict[str, str] = {}
    for path in paths:
        try:
            signed = store.create_signed_url(path, expires_in=seconds)
        except Exception:  # noqa: BLE001 - this one has no link, which the answer counts
            continue
        url = signed.get("signedURL") if isinstance(signed, dict) else None
        if url:
            links[path] = url
    return links


@router.get("")
def list_client_documents(
    client_id: str = Query(...),
    with_links: bool = False,
    current_user: dict = Depends(rbac("document", "read")),
):
    """Every document of one client, newest first.

    `with_links` mints a signed link for each in one request (the vault shows them all at once); without it a link is
    asked for when somebody opens a document. A document whose link could not be minted has `download_url: null` and
    the answer says how many, so a page of dead buttons is not shown as a page of working ones."""
    assert_client_access(current_user, client_id)
    db = _db()
    if db is None:
        rows = [dict(r) for r in _MOCK_ROWS if r["client_id"] == client_id and r["firm_id"] == current_user["firm_id"]]
    else:
        firm_id = current_user["firm_id"]
        rows = fetch_all(
            lambda: db.table("client_documents").select(
                "id, client_id, file_name, description, doc_type, file_path, file_size, mime_type, expiry_date, "
                "financial_year, uploaded_by, version, parent_document_id, created_at")
            .eq("firm_id", firm_id).eq("client_id", client_id),
            "id", label="client_documents")
    rows = [_public(r) for r in rows]
    rows.sort(key=lambda r: str(r.get("id") or ""))
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    unlinked = 0
    if with_links:
        firm = current_user["firm_id"]
        links = _sign_many([r["file_path"] for r in rows if _owns_path(firm, client_id, r.get("file_path"))],
                           LIST_LINK_SECONDS)
        for r in rows:
            r["download_url"] = links.get(r.get("file_path"))
        unlinked = sum(1 for r in rows if not r["download_url"])
    return api_response(True, {"documents": rows, "returned": len(rows), "without_link": unlinked,
                               "categories": list(CATEGORIES),
                               # Served so the upload form states the real bound and the browser carries no copy of it.
                               "max_upload_bytes": MAX_BYTES})


@router.post("/upload")
def upload_client_document(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    # The name the person gives it ("PAN card"). Required by the screens that list by it; the file's own name is the fallback.
    description: Annotated[Optional[str], Form()] = None,
    # Left out, a new version takes its parent's category (so it stays in the same vault tab) and anything else is "Other".
    doc_type: Annotated[Optional[str], Form()] = None,
    expiry_date: Annotated[Optional[str], Form()] = None,
    financial_year: Annotated[OptionalFYLabel, Form()] = None,
    parent_document_id: Annotated[Optional[str], Form()] = None,
    current_user: dict = Depends(rbac("document", "write")),
):
    """Store one file against one client and write its record, or neither.

    A new version names `parent_document_id`: the server reads the parent (it must be this client's) and numbers the
    version itself, so the number is not whatever the browser counted."""
    assert_partner_for_internal_id(client_id, current_user)
    assert_client_access(current_user, client_id)
    if doc_type is not None and doc_type not in CATEGORIES:
        raise HTTPException(status_code=422, detail=f"doc_type must be one of: {', '.join(CATEGORIES)}.")
    expiry = _expiry(expiry_date)
    label = (description or "").strip() or None
    firm_id = current_user["firm_id"]

    version, parent_id = 1, None
    if parent_document_id:
        parent = _own_row(current_user, parent_document_id)
        if parent.get("client_id") != client_id:
            raise HTTPException(status_code=422, detail="That earlier version belongs to a different client.")
        version, parent_id = int(parent.get("version") or 1) + 1, parent["id"]
        if doc_type is None and parent.get("doc_type") in CATEGORIES:
            doc_type = parent["doc_type"]
    doc_type = doc_type or "Other"

    accepted = accept_upload(file, max_bytes=MAX_BYTES)
    storage_path = (f"{firm_id}/{safe_path_segment(client_id, field='client_id')}/"
                    f"{uuid.uuid4()}_{accepted.storage_name}")
    db = _db()
    if db is None:
        # The mock branch's row, and the shape the live INSERT below writes. They are deliberately two literals, as in
        # routers/shared_reports.py: `tests/test_backend_columns_exist_pg.py` reads the source for the columns it names, an
        # insert whose payload is a NAME is invisible to it, and `test_the_two_payload_literals_do_not_drift` holds them
        # in step.
        row = {
            "id": str(uuid.uuid4()), "created_at": ist_now().isoformat(),
            "firm_id": firm_id, "client_id": client_id, "file_name": accepted.display_name, "description": label,
            "doc_type": doc_type, "file_path": storage_path, "file_size": len(accepted.content),
            "mime_type": accepted.content_type, "expiry_date": expiry, "version": version,
            "parent_document_id": parent_id, "uploaded_by": current_user.get("id"),
            "financial_year": financial_year or None,
        }
        _MOCK_ROWS.append(row)
        return api_response(True, {"document": _public(row)})

    store = _storage()
    stored = store.upload(
        path=storage_path, file=accepted.content,
        # OUR content type, from the validated extension: never the caller's header.
        file_options={"content-type": accepted.content_type})
    if getattr(stored, "error", None):
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {stored.error}")
    try:
        written = db.table("client_documents").insert({
            "firm_id": firm_id,
            "client_id": client_id,
            "file_name": accepted.display_name,
            "description": label,
            "doc_type": doc_type,
            "file_path": storage_path,
            "file_size": len(accepted.content),
            "mime_type": accepted.content_type,
            "expiry_date": expiry,
            "version": version,
            "parent_document_id": parent_id,
            # The INTERNAL id (public.users), never the sign-in id: the column is a foreign key to users.
            "uploaded_by": current_user.get("id"),
            "financial_year": financial_year or None,
        }).execute()
    except Exception:
        # The file is stored and the record is not: take the file out again, so nothing is left in the bucket that
        # nothing points at, and let the failure reach the caller as the failure it is.
        _take_out_again(storage_path, operation="client_documents.upload_cleanup")
        raise
    row = (written.data or [{}])[0]
    _audit(current_user, row.get("id"), "upload", new={"file_name": accepted.display_name, "client_id": client_id,
                                                         "doc_type": doc_type, "version": version})
    return api_response(True, {"document": _public(row)})


@router.get("/{doc_id}/download-url")
def client_document_link(
    doc_id: str,
    current_user: dict = Depends(rbac("document", "read")),
):
    """A signed link to one document, minted now. Stored links expire, so nothing keeps one."""
    row = _own_row(current_user, doc_id)
    if _USE_MOCK:
        return api_response(True, {"download_url": None})
    if not _owns_path(current_user["firm_id"], row["client_id"], row.get("file_path")):
        raise HTTPException(status_code=502, detail="The link to this document could not be made. Please try again.")
    links = _sign_many([row["file_path"]], LINK_SECONDS)
    url = links.get(row["file_path"])
    if not url:
        raise HTTPException(status_code=502, detail="The link to this document could not be made. Please try again.")
    return api_response(True, {"download_url": url, "expires_in_seconds": LINK_SECONDS})


@router.delete("/{doc_id}")
def delete_client_document(
    doc_id: str,
    current_user: dict = Depends(rbac("document", "delete")),
):
    """Delete a document: its file, then its record. Partner only.

    Refused with the reason when something still points at the record, BEFORE the file is touched. If the record is
    refused after all (something was added a moment ago), the file has already gone and the answer says so."""
    row = _own_row(current_user, doc_id)
    db = _db()
    if db is None:
        _MOCK_ROWS[:] = [r for r in _MOCK_ROWS if r["id"] != doc_id]
        return api_response(True, {"deleted": True})

    for what, query in _references(db, current_user["firm_id"], doc_id):
        try:
            held = query.execute().data or []
        except Exception as exc:  # noqa: BLE001
            # A check that cannot be made is not a check that passed: going on would remove the file and leave a record
            # that refuses to go, which is the state this pre-check exists to prevent. Refuse, say why, and let them retry.
            capture_soft_failure(exc, operation="client_documents.reference_check")
            raise HTTPException(
                status_code=503,
                detail="This document was not deleted because the check that nothing still points at it could not be "
                       "made. Please try again.") from exc
        if held:
            raise HTTPException(
                status_code=409,
                detail=f"This document cannot be deleted because {what} still points at it. Remove that first.")

    if not _owns_path(current_user["firm_id"], row["client_id"], row.get("file_path")):
        raise HTTPException(
            status_code=409,
            detail="This document was not deleted: its stored file is not under this client's folder, so it is left alone. "
                   "Ask support to look at it.")

    try:
        removed = _storage().remove([row["file_path"]])
    except Exception as exc:  # noqa: BLE001 - nothing was deleted, and the record is still there to try again
        capture_soft_failure(exc, operation="client_documents.delete_file")
        raise HTTPException(
            status_code=502,
            detail="This document was not deleted because its file could not be removed. Please try again.") from exc
    file_went = bool(removed)
    try:
        gone = db.table("client_documents").delete().eq("id", doc_id).eq("firm_id", current_user["firm_id"]).execute()
    except Exception as exc:  # noqa: BLE001 - say what happened to the file, in our own words; the database's go to the log
        capture_soft_failure(exc, operation="client_documents.delete_record")
        raise HTTPException(
            status_code=409,
            detail=("The file was removed but its record could not be, so this entry will not open. Reload to see what is there now."
                    if file_went else "The record could not be deleted. Reload to see what is there now.")) from exc
    if not (gone.data or []):
        raise HTTPException(
            status_code=409,
            detail=("The file was removed but its record could not be, so this entry will not open. Reload to see what is there now."
                    if file_went else
                    "This document was not deleted: it may already have been removed by someone else. Reload to see what is there now."))
    _audit(current_user, doc_id, "delete", old={"file_name": row.get("file_name"), "client_id": row.get("client_id")})
    return api_response(True, {"deleted": True})


# ── small helpers ────────────────────────────────────────────────────────────

def _expiry(value: Optional[str]) -> Optional[str]:
    """An expiry date as the calendar date it names, or None for none; a value that is not one is a 422."""
    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="expiry_date must be a calendar date (YYYY-MM-DD).") from exc


def _public(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "firm_id"}


def _audit(current_user: dict, doc_id, action: str, *, new: dict | None = None, old: dict | None = None) -> None:
    """The edit log, naming the person by their AUTH id (`audit_log.actor_id` takes that one). `log_event` never raises:
    the record is already written, and a failure to log it is reported by the logger and does not fail the request."""
    log_event(current_user["firm_id"], "client_document", doc_id, action,
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              new_data=new, old_data=old)
