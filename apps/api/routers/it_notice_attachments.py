"""The files attached to an income-tax notice: the notice itself and the reply to it, under rbac() (POST-A-010).

The Notices page put each file in Storage from the browser (keyed on the file's own name, with `upsert` on, so a second
file of the same name replaced the first for every notice that shared it) and then wrote the path onto `it_notices`
straight over PostgREST. Both are routes here.

  * UPLOAD (`income_tax:compute`, the tier migration 261 gives `it_notices`): the same bounded, typed and renamed read
    every other upload goes through, a storage key the SERVER builds under the firm, the client and the notice, and a
    path written onto the notice or the file taken out again. A notice that already has a file in that slot is
    refused: the screen only offers an upload where there is none, and replacing silently would leave the earlier file in the bucket
    with nothing pointing at it.
  * LINK (`income_tax:read`): a signed link, minted now, for a notice in the caller's firm and clients.

A missing notice, another firm's and an unassigned client's answer the same words. The notice is read and written as the
caller, so row security is the second lock and the edit log names the person.
"""
from __future__ import annotations

import os
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from core import db_provider
from core.authz import assert_client_access, can_access_client
from core.observability import capture_soft_failure
from core.permissions import rbac
from core.storage_door import storage_folder
from core.uploads import accept_upload, safe_path_segment
from models.common import api_response
from services.audit_service import log_event

router = APIRouter(prefix="/api/income-tax/notices", tags=["income_tax"])

_USE_MOCK = not os.environ.get("SUPABASE_URL")

BUCKET = "Documents"
LINK_SECONDS = 300

#: What the screen calls the two slots, and the column each one fills. The route is the vocabulary: a free column name
#: from the browser would be a caller choosing which column of the row to write.
SLOTS = {"notice": "notice_storage_path", "response": "response_storage_path"}

#: What an attachment to a notice may be: a scan, a letter or a reply the CA drafted.
ALLOWED = ("pdf", "doc", "docx", "png", "jpg", "jpeg")

Slot = Literal["notice", "response"]

_MOCK_NOTICES: dict[str, dict] = {}


def _storage(firm_id: str, client_id: str, notice_id: str):
    """The bucket as the SERVER, bound to THIS notice's own folder, `{firm}/{client}/notices/{notice}/` (`core/storage_door`,
    POST-A-339): the route has asked who the caller is and whether they may touch the client, and the door will not store, sign
    or remove a key outside the notice's folder. The key columns are writable over PostgREST, so a row can be made to name
    somebody else's object, and that one is never signed."""
    return storage_folder(BUCKET, firm_id, client_id, "notices", notice_id)


def _db():
    return None if _USE_MOCK else db_provider.request_db()


def _take_out_again(path: str, firm_id: str, client_id: str, notice_id: str) -> None:
    """Remove a file this request stored and whose notice could not be updated. Through the same door (the server's client,
    bound to the notice's folder): migration 469's policy let only a Partner delete from the bucket and Storage answers a denied
    removal with an empty list and no error, so a clean-up through the caller's own client would have left an Executive's file
    in place without a word. Reports, and does not raise, if it cannot: the caller is already failing with the real reason."""
    try:
        gone = _storage(firm_id, client_id, notice_id).remove([path])
    except Exception as exc:  # noqa: BLE001 - the original failure is the one to report
        capture_soft_failure(exc, operation="it_notice.attach_cleanup", firm_id=firm_id)
        return
    if not gone:
        capture_soft_failure(RuntimeError(f"the file {path} was not removed"), operation="it_notice.attach_cleanup",
                             firm_id=firm_id)


def _notice(current_user: dict, notice_id: str) -> dict:
    """The notice, if it is in the caller's firm and the caller is assigned to its client; one fixed 404 otherwise."""
    db = _db()
    if db is None:
        row = _MOCK_NOTICES.get(notice_id)
    else:
        found = (db.table("it_notices").select("id, firm_id, client_id, notice_storage_path, response_storage_path")
                 .eq("id", notice_id).eq("firm_id", current_user["firm_id"]).execute().data or [])
        row = found[0] if found else None
    if not row or row.get("firm_id") != current_user["firm_id"] or not can_access_client(current_user, row.get("client_id")):
        raise HTTPException(status_code=404, detail="Notice not found")
    return row


@router.post("/{notice_id}/attachment")
def attach_to_notice(
    notice_id: str,
    file: UploadFile = File(...),
    slot: Annotated[Slot, Form()] = "notice",
    current_user: dict = Depends(rbac("income_tax", "compute")),
):
    """File the notice's own document, or the reply to it, against the notice."""
    notice = _notice(current_user, notice_id)
    assert_client_access(current_user, notice["client_id"])
    column = SLOTS[slot]
    if notice.get(column):
        raise HTTPException(status_code=409, detail=f"This notice already has its {slot} document.")
    accepted = accept_upload(file, allowed=ALLOWED)
    path = (f"{current_user['firm_id']}/{safe_path_segment(notice['client_id'], field='client_id')}/notices/"
            f"{safe_path_segment(notice_id, field='notice_id')}/{uuid.uuid4()}_{accepted.storage_name}")

    db = _db()
    if db is None:
        _MOCK_NOTICES[notice_id][column] = path
        return api_response(True, {"slot": slot, "storage_path": path})

    store = _storage(current_user["firm_id"], notice["client_id"], notice_id)
    stored = store.upload(path, accepted.content, accepted.content_type)
    if getattr(stored, "error", None):
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {stored.error}")
    try:
        # Only a slot that is still empty is filled, so two people attaching at once cannot overwrite each other. The two
        # columns are written out, one branch each, so the column-existence guard reads both against the real schema.
        if slot == "notice":
            updated = (db.table("it_notices").update({"notice_storage_path": path})
                       .eq("id", notice_id).eq("firm_id", current_user["firm_id"])
                       .is_("notice_storage_path", "null").execute().data or [])
        else:
            updated = (db.table("it_notices").update({"response_storage_path": path})
                       .eq("id", notice_id).eq("firm_id", current_user["firm_id"])
                       .is_("response_storage_path", "null").execute().data or [])
        if not updated:
            raise HTTPException(status_code=409, detail=f"This notice already has its {slot} document.")
    except Exception:
        # The file is stored and the notice does not point at it: take it out again, and let the failure reach the caller.
        _take_out_again(path, current_user["firm_id"], notice["client_id"], notice_id)
        raise
    log_event(current_user["firm_id"], "it_notice", notice_id, "attach",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              new_data={"slot": slot, "file_name": accepted.display_name})
    return api_response(True, {"slot": slot, "storage_path": path})


@router.get("/{notice_id}/attachment-url")
def notice_attachment_link(
    notice_id: str,
    slot: Slot = Query("notice"),
    current_user: dict = Depends(rbac("income_tax", "read")),
):
    """A signed link to the notice's document or the reply, minted now."""
    notice = _notice(current_user, notice_id)
    assert_client_access(current_user, notice["client_id"])
    path = notice.get(SLOTS[slot])
    if not path:
        raise HTTPException(status_code=404, detail=f"This notice has no {slot} document.")
    if _USE_MOCK:
        return api_response(True, {"download_url": None})
    # The column is writable over PostgREST, so the key is only signed if it sits under this notice's own folder.
    if not (isinstance(path, str) and ".." not in path
            and path.startswith(f"{current_user['firm_id']}/{notice['client_id']}/notices/{notice_id}/")):
        raise HTTPException(status_code=502, detail="The link to this document could not be made. Please try again.")
    try:
        signed = _storage(current_user["firm_id"], notice["client_id"], notice_id).create_signed_url(path, LINK_SECONDS)
    except Exception as exc:  # noqa: BLE001 - said to the caller as one sentence
        capture_soft_failure(exc, operation="it_notice.sign", firm_id=current_user["firm_id"])
        signed = None
    url = signed.get("signedURL") if isinstance(signed, dict) else None
    if not url:
        raise HTTPException(status_code=502, detail="The link to this document could not be made. Please try again.")
    return api_response(True, {"download_url": url, "expires_in_seconds": LINK_SECONDS})
