"""POST-A-010, the Documents page and the Client Portal's document requests.

WHAT MOVED. The Documents page listed `documents` straight from PostgREST, uploaded to Storage from the browser and
inserted the row itself, and opened a file with a link it signed in the browser. The Client Portal page listed and
deleted `document_requests` the same way. Each now asks the server, so the Documents permission, the Portal
permission and the client assignment are asked once, in the route.

WHAT THE SERVER HAD TO LEARN FIRST, each pinned here:

  * THE LIST IS EVERY DOCUMENT. `document_repo.find_all` read one PostgREST response, which is cut at about a thousand
    rows without a word; the page it replaces paged. A firm with more documents than that would have been shown the
    first thousand as if they were all of them.
  * THE UPLOAD TAKES THE FINANCIAL YEAR the page asks for and lists, as the same validated label every other route takes.
  * A RECORD THAT CANNOT BE WRITTEN LEAVES NO FILE BEHIND. The browser handler removed the file it had just stored when
    the insert failed; the route did not.
  * A REQUEST CAN BE WITHDRAWN. `DELETE /api/portal/document-requests/{id}` at the tier the database asks (Executive and
    above), scoped as the complete route is, and `success: false` when no row went.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from tests._capped_postgrest import DB_MAX_ROWS, CappedDB

FIRM = "firm-001"
CLIENT = "11111111-2222-3333-4444-555555555555"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


# ── the list reads every row ─────────────────────────────────────────────────────────────────────────────────────────

def _docs(n: int, *, firm: str = FIRM, deleted: int = 0) -> list[dict]:
    rows = []
    for i in range(n):
        rows.append({
            "id": f"d{i:06d}", "firm_id": firm, "client_id": CLIENT, "document_type": "OTHER",
            "file_name": f"f{i}.pdf", "deleted_at": None,
            # three documents share a day, so the order has to break ties and not rely on the stored order
            "created_at": f"2026-09-{(i // 3) % 28 + 1:02d}T10:00:00+00:00",
        })
    for j in range(deleted):
        rows.append({**rows[j], "id": f"x{j:06d}", "deleted_at": "2026-10-01T00:00:00+00:00"})
    return rows


@pytest.fixture
def repo(monkeypatch):
    import repositories.document_repository as dr

    def use(rows):
        db = CappedDB({"documents": rows})
        monkeypatch.setattr(dr, "_USE_MOCK", False)
        monkeypatch.setattr(dr, "_get_db", lambda: db)
        return dr.document_repo, db

    return use


def test_a_firm_with_more_documents_than_the_row_cap_lists_all_of_them(repo):
    rows = _docs(2300)
    document_repo, db = repo(rows)
    got = document_repo.find_all(firm_id=FIRM)
    assert len(got) == 2300 and len({d["id"] for d in got}) == 2300
    # the cap is what made the old read stop at DB_MAX_ROWS; this read took three requests
    assert 2300 > DB_MAX_ROWS and len(db.requests["documents"]) == 3


def test_the_list_is_newest_first_and_ties_break_on_the_id(repo):
    rows = _docs(40)
    rows.reverse()  # stored in no helpful order
    document_repo, _ = repo(rows)
    got = document_repo.find_all(firm_id=FIRM)
    assert len(got) == 40
    for earlier, later in zip(got, got[1:], strict=False):
        assert (earlier["created_at"] > later["created_at"]
                or (earlier["created_at"] == later["created_at"] and earlier["id"] < later["id"])), (earlier, later)
    assert len({d["created_at"] for d in got}) < 40, "the fixture must contain ties or the tie-break is untested"


def test_a_deleted_document_is_not_listed_and_another_firms_is_not_either(repo):
    rows = _docs(10, deleted=4) + _docs(5, firm="other-firm")
    document_repo, _ = repo(rows)
    got = document_repo.find_all(firm_id=FIRM)
    assert len(got) == 10
    assert all(d["firm_id"] == FIRM and d["deleted_at"] is None for d in got)


# ── the upload takes the financial year, and leaves no file behind ───────────────────────────────────────────────────

@pytest.fixture
def upload(monkeypatch, dev_header_auth):
    import routers.documents as docs
    from main import app

    repo = MagicMock()
    repo.create.side_effect = lambda row: {"id": "doc-1", **row}
    monkeypatch.setattr(docs, "document_repo", repo)
    monkeypatch.setattr(docs, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(docs, "log_activity", lambda *a, **k: None)
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"X-User-Role": "Partner", "X-Firm-Id": FIRM, "X-User-Id": "user-1"}

    def post(**data):
        return client.post(
            "/api/documents/upload", headers=headers,
            files={"file": ("receipt.pdf", io.BytesIO(PDF), "application/pdf")},
            data={"document_type": "OTHER", "client_id": CLIENT, **data})

    return post, repo, docs


def test_the_financial_year_is_stored_as_the_canonical_label(upload):
    post, repo, _ = upload
    r = post(financial_year="2026-2027")
    assert r.status_code == 200, r.text
    assert repo.create.call_args.args[0]["financial_year"] == "2026-27"


@pytest.mark.parametrize("bad", ["2026-28", "2026", "garbage"])
def test_a_financial_year_that_is_not_one_is_a_422_and_nothing_is_stored(upload, bad):
    post, repo, _ = upload
    r = post(financial_year=bad)
    assert r.status_code == 422, r.text
    repo.create.assert_not_called()


@pytest.mark.parametrize("data", [{}, {"financial_year": ""}])
def test_no_financial_year_stores_none_and_the_upload_still_works(upload, data):
    post, repo, _ = upload
    r = post(**data)
    assert r.status_code == 200, r.text
    assert "financial_year" not in repo.create.call_args.args[0]


class _Bucket:
    """One bucket, recording what was done to it. `who` says whose client it belongs to."""

    def __init__(self, who, log, *, sign_fail=False, remove_result=None):
        self.who, self.log = who, log
        self.sign_fail = sign_fail
        self.remove_result = [{"name": "x"}] if remove_result is None else remove_result

    def upload(self, path=None, file=None, file_options=None, **kw):
        self.log.append((self.who, "upload", path))
        return {"path": path}

    def remove(self, paths):
        self.log.append((self.who, "remove", list(paths)))
        return self.remove_result

    def create_signed_url(self, path, expires_in=60):
        self.log.append((self.who, "sign", path))
        if self.sign_fail:
            raise RuntimeError("storage down")
        return {"signedURL": f"https://signed.example/{path}"}


def _storage_world(monkeypatch, docs, *, sign_fail=False, server_remove=None):
    """The caller's Storage client and the server's, as two objects sharing ONE event log."""
    log: list = []

    def client(who, **kw):
        bucket = _Bucket(who, log, **kw)
        return type("S", (), {"storage": type("St", (), {"from_": staticmethod(lambda _b: bucket)})})()

    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: client("caller", sign_fail=sign_fail))
    monkeypatch.setattr(sc, "get_service_supabase", lambda: client("server", remove_result=server_remove))
    monkeypatch.setattr(docs, "_USE_MOCK", False)
    return log


def test_a_record_that_cannot_be_written_removes_the_file_it_just_stored(monkeypatch, upload):
    post, repo, docs = upload
    log = _storage_world(monkeypatch, docs)
    repo.create.side_effect = RuntimeError("insert refused")
    r = post()
    assert r.status_code == 500, r.text
    [(_, _, stored)] = [e for e in log if e[1] == "upload"]
    assert stored.startswith(f"{FIRM}/{CLIENT}/OTHER/")
    # taken out through the SERVER's client: only a Partner may delete from the bucket (migration 469) and a denied removal
    # answers an empty list and no error, so the caller's own token would leave an Executive's file in place without a word
    assert [e for e in log if e[1] == "remove"] == [("server", "remove", [stored])]


def test_a_clean_up_that_removed_nothing_is_reported_and_the_real_failure_still_reaches_the_caller(monkeypatch, upload):
    post, repo, docs = upload
    _storage_world(monkeypatch, docs, server_remove=[])
    reported: list = []
    monkeypatch.setattr(docs, "capture_soft_failure", lambda exc, **kw: reported.append((str(exc), kw)))
    repo.create.side_effect = RuntimeError("insert refused")
    assert post().status_code == 500
    [(message, kw)] = reported
    assert "was not removed" in message and kw["operation"] == "documents.upload_cleanup"


def test_a_stored_record_keeps_the_file(monkeypatch, upload):
    post, repo, docs = upload
    log = _storage_world(monkeypatch, docs)
    r = post(financial_year="2025-26")
    assert r.status_code == 200, r.text
    assert not [e for e in log if e[1] == "remove"]
    assert r.json()["data"]["document"]["financial_year"] == "2025-26"
    assert r.json()["data"]["download_url"].startswith("https://signed.example/")


def test_a_link_that_cannot_be_signed_after_the_upload_does_not_turn_it_into_a_failure(monkeypatch, upload):
    """The record and the file are both there; a 500 here would invite a second upload of the same document."""
    post, repo, docs = upload
    log = _storage_world(monkeypatch, docs, sign_fail=True)
    r = post()
    assert r.status_code == 200, r.text
    assert r.json()["data"]["download_url"] is None
    assert not [e for e in log if e[1] == "remove"]


def test_the_mime_type_of_the_stored_file_is_recorded_on_the_row(upload):
    post, repo, _ = upload
    assert post().status_code == 200
    assert repo.create.call_args.args[0]["mime_type"] == "application/pdf"


# ── an id that is not there is a 404 and never a 500 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("method, path", [("get", "/api/documents/{id}/download-url"), ("delete", "/api/documents/{id}")])
def test_a_document_that_is_gone_is_a_404_with_the_one_fixed_sentence(monkeypatch, dev_header_auth, method, path):
    """A second tab pressing Download on a document the first tab deleted used to escape as an unhandled NotFoundError."""
    import routers.documents as docs
    from core.exceptions import NotFoundError
    from main import app

    repo = MagicMock()
    repo.get_or_raise.side_effect = NotFoundError("Document", "gone")
    monkeypatch.setattr(docs, "document_repo", repo)
    r = getattr(TestClient(app, raise_server_exceptions=False), method)(
        path.format(id="gone"), headers={"X-User-Role": "Partner", "X-Firm-Id": FIRM, "X-User-Id": "user-1"})
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Document not found"
    repo.soft_delete.assert_not_called()


# ── a document request can be withdrawn ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def requests_store(dev_header_auth):
    import domain.portal_service as ps
    ps._MOCK_DOC_REQUESTS.clear()
    yield ps
    ps._MOCK_DOC_REQUESTS.clear()


def _h(role: str, firm: str = FIRM) -> dict:
    return {"X-User-Role": role, "X-Firm-Id": firm, "X-User-Id": f"{role}-1"}


def _client() -> TestClient:
    from main import app
    return TestClient(app, raise_server_exceptions=False)


def test_a_request_is_withdrawn_by_the_firm_that_made_it(requests_store):
    rec = requests_store.create_document_request(FIRM, CLIENT, "Bank statements")
    r = _client().delete(f"/api/portal/document-requests/{rec['id']}", headers=_h("Executive"))
    assert r.status_code == 200, r.text
    assert r.json() == {"success": True, "data": {"deleted": True}, "error": None}
    assert requests_store.get_document_request(rec["id"]) is None


def test_the_answer_says_no_when_no_row_went(requests_store):
    c = _client()
    gone = c.delete("/api/portal/document-requests/never-existed", headers=_h("Partner"))
    assert gone.status_code == 200 and gone.json()["success"] is False
    assert gone.json()["error"] == "Document request not found"


def test_another_firms_request_is_not_withdrawn_and_reads_as_missing(requests_store):
    rec = requests_store.create_document_request("other-firm", CLIENT, "Their request")
    r = _client().delete(f"/api/portal/document-requests/{rec['id']}", headers=_h("Partner"))
    assert r.json()["success"] is False and r.json()["error"] == "Document request not found"
    assert requests_store.get_document_request(rec["id"]) is not None


def test_a_reviewer_may_not_withdraw_a_request(requests_store):
    """The database's own tier for a document request is Executive; the route asks portal:write, which is the same."""
    rec = requests_store.create_document_request(FIRM, CLIENT, "Bank statements")
    r = _client().delete(f"/api/portal/document-requests/{rec['id']}", headers=_h("Reviewer"))
    assert r.status_code == 403, r.text
    assert requests_store.get_document_request(rec["id"]) is not None


def test_the_in_memory_twin_reports_whether_a_row_went(requests_store):
    rec = requests_store.create_document_request(FIRM, CLIENT, "x")
    assert requests_store.delete_document_request(rec["id"]) is True
    assert requests_store.delete_document_request(rec["id"]) is False
