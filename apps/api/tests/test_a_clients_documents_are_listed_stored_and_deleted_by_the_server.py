"""POST-A-010, a client's documents: the vault, the Documents tab and the files shared to the client's portal.

THE FAULT. Three screens read `client_documents` over PostgREST, put the file in Storage from the browser, and inserted
or deleted the row themselves. The only control on that path was the database's row security, so the Documents
permission on the Team screen, the bounds every other upload meets, and the name the file is stored under were
all the browser's to choose.

WHAT THE ROUTES HAVE TO DO, each pinned here:

  * LIST every document of one client in the server's own pages (PostgREST cuts a response at about a thousand rows
    and says nothing), newest first, ties on the id, only this firm's and this client's, after the client assignment.
  * UPLOAD under a key the SERVER builds (`{firm}/{client}/{uuid}_{name}`), bounded, typed by its bytes, with the internal user as
    the uploader, a version the server numbers from the parent it read, and a record or no file.
  * LINK a document the caller may see, minted now.
  * DELETE (Partner only) the file and then the record, after asking whether anything still points at the record,
    and say in words what happened when the record is refused after the file went.
"""
from __future__ import annotations

import io

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

import routers.client_documents as cd

FIRM, OTHER_FIRM = "firm-001", "firm-002"
CLIENT, OTHER_CLIENT = "11111111-2222-3333-4444-555555555555", "99999999-2222-3333-4444-555555555555"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
# The internal id and the sign-in id are DIFFERENT strings on purpose: a test whose two were equal could not tell which one
# the route wrote.
USER = {"firm_id": FIRM, "id": "internal-user-id", "auth_user_id": "supabase-auth-id", "email": "ca@f.test", "role": "Partner"}


# ── doubles ──────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    CAP = 1000

    def __init__(self, db, table):
        self.db, self.table = db, table
        self.mode, self.payload = "select", None
        self.filters: list[tuple[str, object]] = []
        self.after = None
        self.limit_n = None
        self.ordered = False

    def select(self, cols="*", *_a, **_k): self.mode = "select"; return self
    def eq(self, col, v): self.filters.append((col, v)); return self
    def gt(self, col, v): self.after = (col, v); return self
    def order(self, col, desc=False): self.ordered = True; return self
    def limit(self, n): self.limit_n = n; return self
    def insert(self, row): self.mode, self.payload = "insert", row; return self
    def delete(self): self.mode = "delete"; return self

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        self.db.log.append((self.mode, self.table, list(self.filters)))
        self.db.timeline.append(("db", self.mode, self.table))
        if self.mode == "insert":
            if self.db.fail_insert:
                raise RuntimeError("insert refused")
            row = {"id": f"new-{len(rows) + 1}", "created_at": "2026-10-25T10:00:00+00:00", **self.payload}
            rows.append(row)
            return _Resp([row])
        match = [r for r in rows if all(r.get(c) == v for c, v in self.filters)]
        if self.mode == "delete":
            if self.db.fail_delete:
                raise RuntimeError("violates foreign key constraint")
            if self.db.hide_delete:
                return _Resp([])
            for r in match:
                rows.remove(r)
            return _Resp([{"id": r["id"]} for r in match])
        if self.after:
            col, v = self.after
            match = [r for r in match if str(r.get(col)) > str(v)]
        if self.ordered:
            match.sort(key=lambda r: str(r.get("id")))
        return _Resp(match[:min(self.limit_n or self.CAP, self.CAP)])


class _DB:
    def __init__(self, timeline=None, **tables):
        self.tables = {k: list(v) for k, v in tables.items()}
        self.log: list = []
        # ONE event log shared with the two storages, so a test can say which happened first
        self.timeline = timeline if timeline is not None else []
        self.fail_insert = self.fail_delete = self.hide_delete = False

    def table(self, name):
        return _Query(self, name)


class _Storage:
    def __init__(self, who="caller", timeline=None):
        self.who = who
        self.timeline = timeline if timeline is not None else []
        self.calls: list[tuple] = []
        self.upload_error = None
        self.removed_result: list = [{"name": "x"}]
        self.remove_error = None
        self.sign_fail = False
        self.single_sign_missing: set[str] = set()

    def upload(self, path=None, file=None, file_options=None, **kw):
        self.timeline.append((self.who, "upload", path))
        self.calls.append(("upload", path, len(file), (file_options or {}).get("content-type")))
        if self.upload_error:
            return type("R", (), {"error": self.upload_error})()
        return {"path": path}

    def remove(self, paths):
        self.timeline.append((self.who, "remove", list(paths)))
        self.calls.append(("remove", list(paths)))
        if self.remove_error:
            raise RuntimeError(self.remove_error)
        return self.removed_result

    def create_signed_urls(self, paths, expires_in=60):
        seconds = expires_in
        self.calls.append(("sign", list(paths), seconds))
        if self.sign_fail:
            raise RuntimeError("storage down")
        if self.single_sign_missing & set(paths):
            # what Storage does: the batch call fails for the WHOLE list when one object is gone
            raise RuntimeError("object not found")
        return [{"path": p, "signedURL": f"https://signed.example/{p}"} for p in paths]

    def create_signed_url(self, path, expires_in=60):
        self.calls.append(("sign_one", path, expires_in))
        if self.sign_fail or path in self.single_sign_missing:
            raise RuntimeError("object not found")
        return {"signedURL": f"https://signed.example/{path}"}


def _row(i, *, firm=FIRM, client=CLIENT, **over):
    return {"id": f"d{i:06d}", "firm_id": firm, "client_id": client, "file_name": f"f{i}.pdf", "description": f"doc {i}",
            "doc_type": "Other", "file_path": f"{firm}/{client}/f{i}.pdf", "file_size": 10, "mime_type": "application/pdf",
            "expiry_date": None, "financial_year": None, "uploaded_by": None, "version": 1, "parent_document_id": None,
            "created_at": f"2026-09-{(i // 3) % 28 + 1:02d}T10:00:00+00:00", **over}


@pytest.fixture
def world(monkeypatch):
    timeline: list[tuple] = []
    db = _DB(timeline, client_documents=[])
    # ONE storage, the server's: every verb on a file goes through `core/storage_door` (POST-A-339), bound to the folder the route
    # names. `server_storage` stays as a second name for the same object so the clean-up tests read as they always did.
    storage = server_storage = _Storage("server", timeline)
    events: list[tuple] = []
    monkeypatch.setattr(cd, "_USE_MOCK", False)
    monkeypatch.setattr(cd, "_db", lambda: db)
    # The REAL door runs (`core/storage_door`), over a server client whose bucket is the recorder below: so the folder rule is
    # exercised by every test here and not stubbed out.
    import core.supabase_client as sc
    buckets: list[str] = []
    server = type("S", (), {"storage": type("St", (), {"from_": staticmethod(lambda b: (buckets.append(b), storage)[1])})})()
    monkeypatch.setattr(sc, "get_service_supabase", lambda: server)
    monkeypatch.setattr(cd, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(cd, "assert_partner_for_internal_id", lambda *a, **k: None)
    monkeypatch.setattr(cd, "can_access_client", lambda user, client: client != "unassigned")
    monkeypatch.setattr(cd, "log_event", lambda *a, **k: events.append((a, k)))
    return type("W", (), {"db": db, "storage": storage, "server_storage": server_storage, "events": events,
                          "timeline": timeline, "buckets": buckets})


def _file(name="pan.pdf", data=PDF):
    return UploadFile(filename=name, file=io.BytesIO(data))


def _upload(**over):
    kw = dict(file=_file(), client_id=CLIENT, description="PAN card", doc_type="Identity", expiry_date=None,
              financial_year=None, parent_document_id=None, current_user=USER)
    kw.update(over)
    return cd.upload_client_document(**kw)


def _refused(status, fn, *a, **k):
    with pytest.raises(HTTPException) as caught:
        fn(*a, **k)
    assert caught.value.status_code == status, (caught.value.status_code, caught.value.detail)
    return caught.value.detail


# ── list ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_client_with_more_documents_than_the_row_cap_lists_all_of_them(world):
    world.db.tables["client_documents"] = [_row(i) for i in range(2300)]
    body = cd.list_client_documents(client_id=CLIENT, with_links=False, current_user=USER)["data"]
    assert body["returned"] == 2300 == len({d["id"] for d in body["documents"]})
    selects = [e for e in world.db.log if e[0] == "select"]
    assert len(selects) == 3, "2,300 rows are three pages of at most 1,000"


def test_the_list_is_newest_first_with_ties_on_the_id_and_holds_only_this_clients_documents_of_this_firm(world):
    rows = [_row(i) for i in range(30)] + [_row(100, client=OTHER_CLIENT), _row(101, firm=OTHER_FIRM)]
    rows.reverse()
    world.db.tables["client_documents"] = rows
    docs = cd.list_client_documents(client_id=CLIENT, with_links=False, current_user=USER)["data"]["documents"]
    assert len(docs) == 30 and all(d["client_id"] == CLIENT for d in docs)
    for earlier, later in zip(docs, docs[1:], strict=False):
        assert (earlier["created_at"] > later["created_at"]
                or (earlier["created_at"] == later["created_at"] and earlier["id"] < later["id"]))
    assert len({d["created_at"] for d in docs}) < 30, "the fixture must contain ties"


def test_the_list_carries_no_firm_id_and_names_the_bound_it_enforces(world):
    world.db.tables["client_documents"] = [_row(1)]
    body = cd.list_client_documents(client_id=CLIENT, with_links=False, current_user=USER)["data"]
    assert "firm_id" not in body["documents"][0]
    assert body["max_upload_bytes"] == cd.MAX_BYTES == 25 * 1024 * 1024
    assert body["categories"] == list(cd.CATEGORIES)


def test_links_are_signed_in_one_request_and_a_document_without_one_is_counted(world):
    world.db.tables["client_documents"] = [_row(1), _row(2)]
    body = cd.list_client_documents(client_id=CLIENT, with_links=True, current_user=USER)["data"]
    signs = [c for c in world.storage.calls if c[0] == "sign"]
    assert len(signs) == 1 and signs[0][2] == cd.LIST_LINK_SECONDS
    assert all(d["download_url"].startswith("https://signed.example/") for d in body["documents"])
    assert body["without_link"] == 0

    world.storage.sign_fail = True
    broken = cd.list_client_documents(client_id=CLIENT, with_links=True, current_user=USER)["data"]
    assert broken["returned"] == 2 and broken["without_link"] == 2
    assert all(d["download_url"] is None for d in broken["documents"])


def test_without_with_links_nothing_is_signed(world):
    world.db.tables["client_documents"] = [_row(1)]
    cd.list_client_documents(client_id=CLIENT, with_links=False, current_user=USER)
    assert world.storage.calls == []


# ── upload ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_upload_is_stored_under_a_key_the_server_builds_and_recorded(world):
    out = _upload(file=_file("My PAN card (final).pdf"), expiry_date="2027-03-31", financial_year="2026-27")["data"]["document"]
    [(_, path, size, content_type)] = [c for c in world.storage.calls if c[0] == "upload"]
    assert path.startswith(f"{FIRM}/{CLIENT}/") and path.count("/") == 2
    assert path.endswith(".pdf") and " " not in path and "(" not in path
    assert size == len(PDF) and content_type == "application/pdf"
    [row] = world.db.tables["client_documents"]
    assert row["file_path"] == path and row["firm_id"] == FIRM and row["client_id"] == CLIENT
    assert row["description"] == "PAN card" and row["doc_type"] == "Identity"
    assert row["expiry_date"] == "2027-03-31" and row["financial_year"] == "2026-27"
    assert row["mime_type"] == "application/pdf" and row["file_size"] == len(PDF)
    assert row["version"] == 1 and row["parent_document_id"] is None
    assert "firm_id" not in out and out["id"] == "new-1"


def test_the_uploader_is_the_internal_user_not_the_sign_in_id(world):
    _upload()
    [row] = world.db.tables["client_documents"]
    assert row["uploaded_by"] == USER["id"] and row["uploaded_by"] != USER["auth_user_id"]
    [(args, kwargs)] = world.events
    assert args[1:4] == ("client_document", "new-1", "upload") and kwargs["actor_id"] == USER["auth_user_id"]


def test_two_uploads_of_one_name_are_two_files_and_not_one_overwritten(world):
    _upload(file=_file("pan.pdf"))
    _upload(file=_file("pan.pdf"))
    paths = [c[1] for c in world.storage.calls if c[0] == "upload"]
    assert len(paths) == 2 and paths[0] != paths[1]


def test_the_upload_is_bounded_and_read_at_most_the_bound_plus_one(world):
    class Spy(io.BytesIO):
        requested: list[int] = []
        def read(self, n=-1):
            self.requested.append(n)
            return super().read(n)

    big = Spy(PDF + b"x" * (cd.MAX_BYTES + 5))
    big.requested = []
    detail = _refused(413, _upload, file=UploadFile(filename="big.pdf", file=big))
    assert "25 MB" in detail and big.requested == [cd.MAX_BYTES + 1]
    assert world.storage.calls == [] and world.db.tables["client_documents"] == []


def test_a_file_whose_bytes_are_not_its_type_is_refused_before_anything_is_stored(world):
    _refused(415, _upload, file=_file("fake.pdf", b"MZ\x90\x00 this is not a pdf"))
    _refused(415, _upload, file=_file("run.exe", b"MZ\x90\x00"))
    assert world.storage.calls == [] and world.db.tables["client_documents"] == []


@pytest.mark.parametrize("over", [{"doc_type": "Secret"}, {"expiry_date": "31-03-2027"}, {"expiry_date": "2027-02-30"}])
def test_an_unknown_category_or_a_date_that_is_not_one_is_a_422_and_nothing_is_stored(world, over):
    _refused(422, _upload, **over)
    assert world.storage.calls == [] and world.db.tables["client_documents"] == []


def test_a_blank_description_and_a_blank_expiry_store_none(world):
    _upload(description="   ", expiry_date="")
    [row] = world.db.tables["client_documents"]
    assert row["description"] is None and row["expiry_date"] is None


def test_a_new_version_is_numbered_by_the_server_from_the_parent_it_read(world):
    world.db.tables["client_documents"] = [_row(1, version=3)]
    _upload(parent_document_id="d000001")
    row = world.db.tables["client_documents"][-1]
    assert row["version"] == 4 and row["parent_document_id"] == "d000001"


def test_a_parent_in_another_client_another_firm_or_an_unassigned_client_is_refused(world):
    world.db.tables["client_documents"] = [
        _row(1, client=OTHER_CLIENT), _row(2, firm=OTHER_FIRM), _row(3, client="unassigned")]
    assert "different client" in _refused(422, _upload, parent_document_id="d000001")
    assert _refused(404, _upload, parent_document_id="d000002") == "Document not found"
    assert _refused(404, _upload, parent_document_id="d000003") == "Document not found"
    assert _refused(404, _upload, parent_document_id="nope") == "Document not found"
    assert world.storage.calls == []


def test_a_record_that_cannot_be_written_removes_the_file_and_the_failure_still_reaches_the_caller(world):
    world.db.fail_insert = True
    with pytest.raises(RuntimeError, match="insert refused"):
        _upload()
    [up] = [c for c in world.storage.calls if c[0] == "upload"]
    # taken out through the SERVER's client (the only one there is): the old policy let only a Partner delete from the bucket and
    # a denied removal answered an empty list and no error, so the caller's own client would have left an Executive's file in place
    assert ("remove", [up[1]]) in world.server_storage.calls
    assert [c[0] for c in world.storage.calls] == ["upload", "remove"]
    # and both calls were made on the Documents bucket, for a key under THIS firm's and THIS client's folder
    assert set(world.buckets) == {"Documents"}
    assert all(c[1].startswith(f"{FIRM}/{CLIENT}/") if c[0] == "upload" else all(p.startswith(f"{FIRM}/{CLIENT}/") for p in c[1])
               for c in world.storage.calls)
    assert world.events == []


def test_a_clean_up_that_removed_nothing_is_reported_and_the_real_failure_still_reaches_the_caller(world, monkeypatch):
    reported: list = []
    monkeypatch.setattr(cd, "capture_soft_failure", lambda exc, **kw: reported.append((str(exc), kw)))
    world.server_storage.removed_result = []
    world.db.fail_insert = True
    with pytest.raises(RuntimeError, match="insert refused"):
        _upload()
    [(message, kw)] = reported
    assert "was not removed" in message and kw["operation"] == "client_documents.upload_cleanup"


def test_a_clean_up_that_raises_is_reported_and_the_real_failure_still_reaches_the_caller(world, monkeypatch):
    reported: list = []
    monkeypatch.setattr(cd, "capture_soft_failure", lambda exc, **kw: reported.append((str(exc), kw)))
    world.server_storage.remove_error = "storage down"
    world.db.fail_insert = True
    with pytest.raises(RuntimeError, match="insert refused"):
        _upload()
    assert [m for m, _ in reported] == ["storage down"]


def test_a_storage_failure_writes_no_record(world):
    world.storage.upload_error = "bucket unavailable"
    detail = _refused(500, _upload)
    assert "bucket unavailable" in detail and world.db.tables["client_documents"] == []


# ── a link ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_link_is_minted_for_a_document_the_caller_may_see(world):
    world.db.tables["client_documents"] = [_row(1)]
    out = cd.client_document_link("d000001", current_user=USER)["data"]
    assert out["download_url"] == f"https://signed.example/{FIRM}/{CLIENT}/f1.pdf"
    assert out["expires_in_seconds"] == cd.LINK_SECONDS


def test_a_link_for_another_firms_an_unassigned_or_a_missing_document_says_the_same_thing(world):
    world.db.tables["client_documents"] = [_row(1, firm=OTHER_FIRM), _row(2, client="unassigned")]
    for doc_id in ("d000001", "d000002", "missing"):
        assert _refused(404, cd.client_document_link, doc_id, current_user=USER) == "Document not found"
    assert world.storage.calls == []


def test_a_link_that_could_not_be_made_is_an_error_not_an_empty_answer(world):
    world.db.tables["client_documents"] = [_row(1)]
    world.storage.sign_fail = True
    _refused(502, cd.client_document_link, "d000001", current_user=USER)


# ── delete ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_delete_removes_the_file_first_and_the_record_second_and_logs_it(world):
    world.db.tables["client_documents"] = [_row(1)]
    assert cd.delete_client_document("d000001", current_user=USER)["data"] == {"deleted": True}
    assert world.db.tables["client_documents"] == []
    assert ("remove", [f"{FIRM}/{CLIENT}/f1.pdf"]) in world.storage.calls
    kinds = [e[0] for e in world.db.log]
    assert kinds.index("delete") > max(i for i, e in enumerate(world.db.log) if e[0] == "select")
    # ONE log for the database and the bucket: the file goes before the record, and the reference checks come before both
    order = world.timeline
    removed_at = order.index(("server", "remove", [f"{FIRM}/{CLIENT}/f1.pdf"]))
    deleted_at = order.index(("db", "delete", "client_documents"))
    last_check = max(i for i, e in enumerate(order) if e[:2] == ("db", "select"))
    assert last_check < removed_at < deleted_at
    [(args, kwargs)] = world.events
    assert args[1:4] == ("client_document", "d000001", "delete") and kwargs["old_data"]["client_id"] == CLIENT


@pytest.mark.parametrize("table, column, words", [
    ("client_documents", "parent_document_id", "a later version"),
    ("form_26as_uploads", "document_id", "Form 26AS"),
    ("tax_deduction_claims", "evidence_document_id", "tax deduction claim"),
    ("tax_disallowances", "evidence_document_id", "tax disallowance"),
])
def test_a_record_something_points_at_is_refused_before_the_file_is_touched(world, table, column, words):
    world.db.tables["client_documents"] = [_row(1)]
    if table == "client_documents":
        world.db.tables["client_documents"].append(_row(2, parent_document_id="d000001"))
    else:
        world.db.tables[table] = [{"id": "ref-1", "firm_id": FIRM, column: "d000001"}]
    detail = _refused(409, cd.delete_client_document, "d000001", current_user=USER)
    assert words in detail
    assert world.storage.calls == [], "the file must still be there"
    assert any(r["id"] == "d000001" for r in world.db.tables["client_documents"])


@pytest.mark.parametrize("table, column", [
    ("client_documents", "parent_document_id"), ("form_26as_uploads", "document_id"),
    ("tax_deduction_claims", "evidence_document_id"), ("tax_disallowances", "evidence_document_id")])
def test_a_reference_in_another_firm_does_not_block_this_firms_delete(world, table, column):
    """Every reference check carries the firm, so another firm's row cannot decide whether this firm may delete."""
    world.db.tables["client_documents"] = [_row(1)]
    world.db.tables.setdefault(table, []).append({"id": "ref-1", "firm_id": OTHER_FIRM, column: "d000001"})
    assert cd.delete_client_document("d000001", current_user=USER)["data"] == {"deleted": True}


def test_a_record_refused_after_the_file_went_says_the_file_is_gone(world):
    world.db.tables["client_documents"] = [_row(1)]
    world.db.fail_delete = True
    detail = _refused(409, cd.delete_client_document, "d000001", current_user=USER)
    assert "file was removed but its record could not be" in detail
    assert "violates foreign key" not in detail, "the database's own words go to the log, never to the screen"


def test_a_delete_the_database_hid_is_never_reported_as_done(world):
    world.db.tables["client_documents"] = [_row(1)]
    world.db.hide_delete = True
    detail = _refused(409, cd.delete_client_document, "d000001", current_user=USER)
    assert "file was removed but its record could not be" in detail
    world.storage.removed_result = []
    detail = _refused(409, cd.delete_client_document, "d000001", current_user=USER)
    assert "was not deleted" in detail and "already have been removed" in detail
    assert "file was removed" not in detail, "no file went, so the answer must not say one did"
    assert world.events == []


def test_another_firms_an_unassigned_or_a_missing_document_is_not_deleted_and_says_the_same_thing(world):
    world.db.tables["client_documents"] = [_row(1, firm=OTHER_FIRM), _row(2, client="unassigned")]
    for doc_id in ("d000001", "d000002", "missing"):
        assert _refused(404, cd.delete_client_document, doc_id, current_user=USER) == "Document not found"
    assert world.storage.calls == [] and len(world.db.tables["client_documents"]) == 2


# ── the reviewer's cases ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_reference_check_that_cannot_be_made_refuses_the_delete_and_leaves_the_file(world, monkeypatch):
    """A check that failed is not a check that passed: going on would remove the file and leave a record that refuses to go."""
    world.db.tables["client_documents"] = [_row(1)]
    real = _Query.execute

    def execute(self):
        if self.table == "tax_deduction_claims":
            raise RuntimeError("relation unavailable")
        return real(self)

    monkeypatch.setattr(_Query, "execute", execute)
    detail = _refused(503, cd.delete_client_document, "d000001", current_user=USER)
    assert "check that nothing still points at it could not be made" in detail and "relation" not in detail
    assert world.storage.calls == [] and any(r["id"] == "d000001" for r in world.db.tables["client_documents"])


def test_a_file_that_cannot_be_removed_leaves_the_record_and_says_so(world):
    world.db.tables["client_documents"] = [_row(1)]
    world.storage.remove_error = "storage down"
    detail = _refused(502, cd.delete_client_document, "d000001", current_user=USER)
    assert "was not deleted" in detail and "storage down" not in detail
    assert not any(e[:2] == ("db", "delete") for e in world.timeline)
    assert len(world.db.tables["client_documents"]) == 1


@pytest.mark.parametrize("path", [
    "firm-002/someone-else/f.pdf",               # another firm's object
    f"{FIRM}/{OTHER_CLIENT}/f.pdf",              # another client's object in this firm
    f"{FIRM}/{CLIENT}/../{OTHER_CLIENT}/f.pdf",  # climbs out
    None,
])
def test_a_row_whose_stored_key_is_not_under_its_own_firm_and_client_is_never_signed_or_removed(world, path):
    """`file_path` is writable over PostgREST by an Executive, so a row can be made to name somebody else's object."""
    world.db.tables["client_documents"] = [_row(1, file_path=path)]
    assert world.db.tables["client_documents"]
    _refused(502, cd.client_document_link, "d000001", current_user=USER)
    delete_detail = _refused(409, cd.delete_client_document, "d000001", current_user=USER)
    assert "not under this client's folder" in delete_detail
    assert world.storage.calls == [] and world.server_storage.calls == []
    assert len(world.db.tables["client_documents"]) == 1


def test_the_list_signs_only_keys_under_the_clients_own_folder(world):
    world.db.tables["client_documents"] = [_row(1), _row(2, file_path="firm-002/x/secret.pdf")]
    body = cd.list_client_documents(client_id=CLIENT, with_links=True, current_user=USER)["data"]
    [(_, signed, _s)] = [c for c in world.storage.calls if c[0] == "sign"]
    assert signed == [f"{FIRM}/{CLIENT}/f1.pdf"]
    by_id = {d["id"]: d for d in body["documents"]}
    assert by_id["d000001"]["download_url"] and by_id["d000002"]["download_url"] is None
    assert body["without_link"] == 1


def test_one_object_that_is_gone_blanks_only_its_own_link(world):
    """Storage fails the batch call for the whole list when one path has no object; the others keep their links."""
    world.db.tables["client_documents"] = [_row(1), _row(2), _row(3)]
    world.storage.single_sign_missing = {f"{FIRM}/{CLIENT}/f2.pdf"}
    body = cd.list_client_documents(client_id=CLIENT, with_links=True, current_user=USER)["data"]
    by_id = {d["id"]: d for d in body["documents"]}
    assert by_id["d000001"]["download_url"] and by_id["d000003"]["download_url"]
    assert by_id["d000002"]["download_url"] is None and body["without_link"] == 1 and body["returned"] == 3


def test_a_long_list_is_signed_in_batches_and_a_missing_object_costs_only_its_own_batch(world):
    world.db.tables["client_documents"] = [_row(i) for i in range(450)]
    world.storage.single_sign_missing = {f"{FIRM}/{CLIENT}/f7.pdf"}
    body = cd.list_client_documents(client_id=CLIENT, with_links=True, current_user=USER)["data"]
    batches = [c for c in world.storage.calls if c[0] == "sign"]
    singles = [c for c in world.storage.calls if c[0] == "sign_one"]
    assert all(len(c[1]) <= cd.SIGN_BATCH for c in batches)
    assert len(batches) == 3, "450 documents are three batches of at most 200"
    # the batch that held the missing object fell back to one request per path; the other two did not
    assert 0 < len(singles) <= cd.SIGN_BATCH
    assert body["returned"] == 450 and body["without_link"] == 1


def test_a_new_version_with_no_category_takes_its_parents_and_an_explicit_one_wins(world):
    world.db.tables["client_documents"] = [_row(1, doc_type="GST"), _row(2, doc_type="Weird legacy value")]
    _upload(parent_document_id="d000001", doc_type=None)
    assert world.db.tables["client_documents"][-1]["doc_type"] == "GST"
    _upload(parent_document_id="d000001", doc_type="MCA")
    assert world.db.tables["client_documents"][-1]["doc_type"] == "MCA"
    # a parent whose stored category is not one of the vault's falls back to Other, never to the stray value
    _upload(parent_document_id="d000002", doc_type=None)
    assert world.db.tables["client_documents"][-1]["doc_type"] == "Other"
    _upload(doc_type=None)
    assert world.db.tables["client_documents"][-1]["doc_type"] == "Other"


# ── the two payload literals ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_two_payload_literals_do_not_drift():
    """The mock branch's row and the live INSERT are two literals on purpose (the column guard reads the source for the
    columns a query names, and an insert of a NAME is invisible to it). They must carry the same columns, or the in-memory
    twin stops being a picture of what the database receives."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(cd.upload_client_document)))
    literals = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)
                and any(isinstance(k, ast.Constant) and k.value == "uploaded_by" for k in n.keys)]
    assert len(literals) == 2, "the upload route must hold exactly the mock row and the insert payload"
    keys = [{k.value for k in lit.keys if isinstance(k, ast.Constant)} for lit in literals]
    assert keys[0] - {"id", "created_at"} == keys[1] - {"id", "created_at"}
    assert {"firm_id", "client_id", "file_path", "uploaded_by", "version", "financial_year"} <= keys[1]


# ── in front of the app: who may do what ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def app_world(monkeypatch, dev_header_auth, world):
    from main import app
    monkeypatch.setattr(cd, "can_access_client", lambda user, client: True)
    return TestClient(app, raise_server_exceptions=False), world


def _h(role, firm=FIRM):
    return {"X-User-Role": role, "X-Firm-Id": firm, "X-User-Id": f"{role}-1"}


@pytest.mark.parametrize("role, status", [("Partner", 200), ("Manager", 403), ("Executive", 403), ("Reviewer", 403)])
def test_only_a_partner_deletes(app_world, role, status):
    client, w = app_world
    w.db.tables["client_documents"] = [_row(1)]
    r = client.delete("/api/client-documents/d000001", headers=_h(role))
    assert r.status_code == status, r.text
    assert (w.db.tables["client_documents"] == []) is (status == 200)


@pytest.mark.parametrize("role, status", [("Partner", 200), ("Manager", 200), ("Executive", 200), ("Reviewer", 403)])
def test_an_executive_and_above_uploads_and_a_reviewer_does_not(app_world, role, status):
    client, w = app_world
    r = client.post("/api/client-documents/upload", headers=_h(role),
                    files={"file": ("pan.pdf", io.BytesIO(PDF), "application/pdf")},
                    data={"client_id": CLIENT, "description": "PAN"})
    assert r.status_code == status, r.text
    assert len(w.db.tables["client_documents"]) == (1 if status == 200 else 0)


def test_a_financial_year_is_canonicalised_at_the_door(app_world):
    client, w = app_world
    r = client.post("/api/client-documents/upload", headers=_h("Partner"),
                    files={"file": ("pan.pdf", io.BytesIO(PDF), "application/pdf")},
                    data={"client_id": CLIENT, "financial_year": "2026-2027"})
    assert r.status_code == 200, r.text
    assert w.db.tables["client_documents"][0]["financial_year"] == "2026-27"


def test_every_staff_role_reads_and_a_financial_year_that_is_not_one_is_a_422(app_world):
    client, w = app_world
    w.db.tables["client_documents"] = [_row(1)]
    for role in ("Partner", "Manager", "Executive", "Reviewer"):
        r = client.get("/api/client-documents", params={"client_id": CLIENT}, headers=_h(role))
        assert r.status_code == 200 and r.json()["data"]["returned"] == 1
    bad = client.post("/api/client-documents/upload", headers=_h("Partner"),
                      files={"file": ("pan.pdf", io.BytesIO(PDF), "application/pdf")},
                      data={"client_id": CLIENT, "financial_year": "2026-28"})
    assert bad.status_code == 422, bad.text
