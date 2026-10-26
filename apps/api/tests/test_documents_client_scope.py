"""
Client-assignment scope on the documents router.

documents.client_id is NOT NULL (migration 001). upload_document and
parse_document were already guarded via _scope_client — multipart form fields
are invisible to main.py's mount-level client guard, so those two always had to
be explicit. The other three did not:

  * list_documents returned EVERY document in the firm when client_id was
    omitted, which is the default the UI uses.
  * get_download_url is row-addressed by doc_id and checked firm_id alone —
    and it mints a live signed Storage URL to the file itself, so an
    unassigned caller reaching it was a real exfiltration path, not just
    metadata (the same shape as the year_end_exports.py finding).
  * delete_document is row-addressed and checked firm_id alone.
"""
import pytest
from fastapi import HTTPException

import routers.documents as dc

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else. Patches assert_client_access/
    can_access_client on the router module, mirroring the other
    *_client_scope.py test files in this sweep."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(dc, "assert_client_access", _assert)
    monkeypatch.setattr(dc, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# list_documents
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_clients_documents_is_refused(deny, monkeypatch):
    called = []
    monkeypatch.setattr(dc.document_repo, "find_all", lambda **kw: called.append(kw) or [])
    with pytest.raises(HTTPException) as e:
        dc.list_documents(client_id=THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert not called


def test_omitting_client_id_no_longer_returns_the_whole_firms_documents(deny, monkeypatch):
    rows = [{"id": "D1", "client_id": MINE}, {"id": "D2", "client_id": THEIRS}]
    monkeypatch.setattr(dc.document_repo, "find_all", lambda **kw: rows)
    monkeypatch.setattr(dc, "filter_by_client",
                        lambda user, items, key="client_id":
                        [r for r in items if r.get(key) != THEIRS])
    out = dc.list_documents(client_id=None, current_user=USER)
    assert [r["id"] for r in out["data"]["documents"]] == ["D1"]
    assert out["data"]["total"] == 1


def test_listing_your_own_clients_documents_still_works(deny, monkeypatch):
    rows = [{"id": "D1", "client_id": MINE}]
    monkeypatch.setattr(dc.document_repo, "find_all", lambda **kw: rows)
    monkeypatch.setattr(dc, "filter_by_client", lambda user, items, key="client_id": items)
    out = dc.list_documents(client_id=MINE, current_user=USER)
    assert out["data"]["total"] == 1
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# _assert_document_scope
# ══════════════════════════════════════════════════════════════════════════════

def _seed(monkeypatch, row):
    monkeypatch.setattr(dc.document_repo, "get_or_raise", lambda did, **kw: row)


def test_the_repository_is_asked_under_the_callers_own_firm(deny, monkeypatch):
    """POST-A-339: the repository reads with the API's privileged client, which carries no row security, so the firm that row
    security used to apply is named by the router on every call. A read that names no firm reads nothing."""
    asked = {}
    monkeypatch.setattr(dc.document_repo, "get_or_raise", lambda did, **kw: asked.update(kw) or {"id": did, "firm_id": FIRM, "client_id": MINE})
    dc._assert_document_scope("D1", USER)
    assert asked == {"firm_id": FIRM}


def test_document_scope_refuses_another_clients_row(deny, monkeypatch):
    _seed(monkeypatch, {"id": "D1", "firm_id": FIRM, "client_id": THEIRS})
    with pytest.raises(HTTPException) as e:
        dc._assert_document_scope("D1", USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_document_scope_allows_your_own_row(deny, monkeypatch):
    row = {"id": "D1", "firm_id": FIRM, "client_id": MINE}
    _seed(monkeypatch, row)
    assert dc._assert_document_scope("D1", USER) == row
    assert deny == [MINE]


def test_document_scope_still_rejects_another_firm(deny, monkeypatch):
    """The pre-existing firm check must survive the added assignment check —
    including the NULL-firm_id case it was explicitly written to reject."""
    _seed(monkeypatch, {"id": "D1", "firm_id": "other-firm", "client_id": MINE})
    with pytest.raises(HTTPException) as e:
        dc._assert_document_scope("D1", USER)
    assert e.value.status_code == 404

    _seed(monkeypatch, {"id": "D1", "firm_id": None, "client_id": MINE})
    with pytest.raises(HTTPException):
        dc._assert_document_scope("D1", USER)


def test_wrong_firm_and_wrong_client_read_identically(deny, monkeypatch):
    """One fixed message for every failure branch — no existence oracle."""
    _seed(monkeypatch, {"id": "D1", "firm_id": "other-firm", "client_id": MINE})
    with pytest.raises(HTTPException) as wrong_firm:
        dc._assert_document_scope("D1", USER)

    _seed(monkeypatch, {"id": "D1", "firm_id": FIRM, "client_id": THEIRS})
    with pytest.raises(HTTPException) as wrong_client:
        dc._assert_document_scope("D1", USER)

    assert wrong_firm.value.status_code == wrong_client.value.status_code == 404
    assert wrong_firm.value.detail == wrong_client.value.detail == "Document not found"


# ══════════════════════════════════════════════════════════════════════════════
# get_download_url — the signed-URL exfiltration path
# ══════════════════════════════════════════════════════════════════════════════

def test_no_signed_url_is_minted_for_another_clients_document(deny, monkeypatch):
    _seed(monkeypatch, {"id": "D1", "firm_id": FIRM, "client_id": THEIRS,
                        "storage_path": "f/c/t/x.pdf"})
    monkeypatch.setattr(dc, "_USE_MOCK", False)
    with pytest.raises(HTTPException) as e:
        dc.get_download_url("D1", current_user=USER)
    assert e.value.status_code == 404
    # Refused before any Storage client was even constructed — if the guard
    # ran late, importing/creating the signed URL would have raised something
    # else here instead of a clean 404.


def test_downloading_your_own_document_still_works(deny, monkeypatch):
    _seed(monkeypatch, {"id": "D1", "firm_id": FIRM, "client_id": MINE,
                        "storage_path": "f/c/m/x.pdf"})
    monkeypatch.setattr(dc, "_USE_MOCK", True)
    out = dc.get_download_url("D1", current_user=USER)
    assert out["success"] is True


def _signing_world(monkeypatch):
    """The REAL door (`core/storage_door`) over a recording server client: what was asked to be signed, and nothing else."""
    signed: list = []
    bucket = type("B", (), {"create_signed_url": lambda self, path, expires_in=60: (
        signed.append(path) or {"signedURL": f"https://signed.example/{path}"})})()
    server = type("S", (), {"storage": type("St", (), {"from_": lambda self, name: bucket})()})()
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_service_supabase", lambda: server)
    monkeypatch.setattr(dc, "_USE_MOCK", False)
    return signed


def test_a_documents_link_is_signed_under_the_rows_own_firm_and_client(deny, monkeypatch):
    """The key is a column of the row, and the door is bound to the row's own `{firm}/{client}/`: a key under it is signed
    (so a door bound to any other folder would refuse the document's own file)."""
    signed = _signing_world(monkeypatch)
    key = f"{FIRM}/{MINE}/GST_INVOICE/abc_x.pdf"
    _seed(monkeypatch, {"id": "D1", "firm_id": FIRM, "client_id": MINE, "storage_path": key})
    out = dc.get_download_url("D1", current_user=USER)
    assert out["data"]["download_url"] == f"https://signed.example/{key}"
    assert signed == [key]


@pytest.mark.parametrize("key", [
    f"{FIRM}/{THEIRS}/GST_INVOICE/abc_x.pdf",      # another client of the same firm
    f"other-firm/{MINE}/GST_INVOICE/abc_x.pdf",    # another firm
    f"{FIRM}/{MINE}/../{THEIRS}/x.pdf",            # a climb out
])
def test_a_row_that_names_somebody_elses_object_is_a_404_and_signs_nothing(deny, monkeypatch, key):
    """`storage_path` is writable over PostgREST by an Executive, so the row can be made to name any object."""
    signed = _signing_world(monkeypatch)
    _seed(monkeypatch, {"id": "D1", "firm_id": FIRM, "client_id": MINE, "storage_path": key})
    with pytest.raises(HTTPException) as e:
        dc.get_download_url("D1", current_user=USER)
    assert e.value.status_code == 404 and e.value.detail == "Document not found"
    assert signed == []


# ══════════════════════════════════════════════════════════════════════════════
# delete_document
# ══════════════════════════════════════════════════════════════════════════════

def test_deleting_another_clients_document_is_refused(deny, monkeypatch):
    _seed(monkeypatch, {"id": "D1", "firm_id": FIRM, "client_id": THEIRS})
    deleted = []
    monkeypatch.setattr(dc.document_repo, "soft_delete",
                        lambda did, **kw: deleted.append(did))
    with pytest.raises(HTTPException) as e:
        dc.delete_document("D1", current_user=USER)
    assert e.value.status_code == 404
    assert not deleted


def test_deleting_your_own_document_still_works(deny, monkeypatch):
    _seed(monkeypatch, {"id": "D1", "firm_id": FIRM, "client_id": MINE,
                        "file_name": "x.pdf"})
    deleted = []
    monkeypatch.setattr(dc.document_repo, "soft_delete",
                        lambda did, **kw: deleted.append(did))
    monkeypatch.setattr(dc, "log_activity", lambda **kw: None)
    monkeypatch.setattr(dc, "log_event", lambda *a, **kw: None)
    out = dc.delete_document("D1", current_user=USER)
    assert out["data"]["deleted"] is True
    assert deleted == ["D1"]


# ══════════════════════════════════════════════════════════════════════════════
# _scope_client — pre-existing multipart guard, pinned so it cannot regress
# ══════════════════════════════════════════════════════════════════════════════

def test_multipart_writes_still_check_the_form_client_id(deny, monkeypatch):
    monkeypatch.setattr(dc, "assert_partner_for_internal_id", lambda cid, user: None)
    with pytest.raises(HTTPException):
        dc._scope_client(THEIRS, USER)
    dc._scope_client(MINE, USER)          # in scope — no raise
    dc._scope_client(None, USER)          # no client named — nothing to check
    assert deny == [THEIRS, MINE]
