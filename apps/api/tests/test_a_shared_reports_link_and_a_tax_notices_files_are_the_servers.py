"""POST-A-010, the last Storage calls in the browser: a shared report's link and a tax notice's two documents.

THE FAULT. The Client Portal page and the client Accounting tab signed a shared report's link in the browser from the
row's `storage_path`; the Notices page put a notice's document and its reply in the bucket from the browser, keyed on the
file's own name with `upsert` on, and wrote the path onto `it_notices` itself. None of it met `rbac()`, the bounds an
upload meets elsewhere, or a check that the notice belonged to the caller's firm and clients.

WHAT THE ROUTES DO, each pinned here:

  * A SHARED REPORT'S LINK is minted for a report in the caller's firm and clients, and a missing id, another firm's
    and an unassigned client's say the same words.
  * A NOTICE'S DOCUMENT is bounded, typed by its bytes, stored under a key the SERVER builds (firm / client / notice /
    uuid_name), written onto the notice only into an EMPTY slot, and taken out again if the notice cannot be updated.
  * THE SLOT IS THE SERVER'S VOCABULARY: "notice" or "response", never a column name the browser chose.
"""
from __future__ import annotations

import io

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

import routers.it_notice_attachments as na
import routers.shared_reports as sr

FIRM, OTHER_FIRM = "firm-001", "firm-002"
CLIENT = "11111111-2222-3333-4444-555555555555"
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
USER = {"firm_id": FIRM, "id": "internal-user-id", "auth_user_id": "supabase-auth-id", "email": "ca@f.test", "role": "Partner"}


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.mode, self.payload = db, table, "select", None
        self.filters: list[tuple[str, str, object]] = []

    def select(self, *_a, **_k): self.mode = "select"; return self
    def eq(self, col, v): self.filters.append(("eq", col, v)); return self
    def is_(self, col, v): self.filters.append(("is", col, None if v == "null" else v)); return self
    def update(self, payload): self.mode, self.payload = "update", payload; return self

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        match = [r for r in rows if all(r.get(c) == v for _, c, v in self.filters)]
        if self.mode == "update":
            if self.db.fail_update:
                raise RuntimeError("update refused")
            for r in match:
                r.update(self.payload)
            return _Resp([dict(r) for r in match])
        # a read hands back a SNAPSHOT, as a database does: a row changed afterwards is not seen through it
        return _Resp([dict(r) for r in match])


class _DB:
    def __init__(self, **tables):
        self.tables = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.fail_update = False
        # the caller's own Storage client and the server's are two objects, so a test can say WHICH one did a thing
        self.storage = _Storage()
        self.service_storage = _Storage()

    def table(self, name):
        return _Query(self, name)


class _Storage:
    def __init__(self):
        self.calls: list[tuple] = []
        self.sign_fail = False
        self.upload_error = None

    def from_(self, _bucket):
        return self

    def upload(self, path=None, file=None, file_options=None, **kw):
        self.calls.append(("upload", path, len(file), (file_options or {}).get("content-type")))
        if self.upload_error:
            return type("R", (), {"error": self.upload_error})()
        return {"path": path}

    def remove(self, paths):
        self.calls.append(("remove", list(paths)))
        return [{"name": p} for p in paths]

    def create_signed_url(self, path, expires_in=60):
        self.calls.append(("sign", path, expires_in))
        if self.sign_fail:
            raise RuntimeError("storage down")
        return {"signedURL": f"https://signed.example/{path}"}


def _refused(status, fn, *a, **k):
    with pytest.raises(HTTPException) as caught:
        fn(*a, **k)
    assert caught.value.status_code == status, (caught.value.status_code, caught.value.detail)
    return caught.value.detail


# ── a shared report's link ───────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def reports(monkeypatch):
    # A shared report is stored by the share route's service client at `shared_reports/{client_id}/{name}`.
    db = _DB(shared_reports=[
        {"id": "r1", "firm_id": FIRM, "client_id": CLIENT, "storage_path": f"shared_reports/{CLIENT}/pl.xlsx"},
        {"id": "r2", "firm_id": OTHER_FIRM, "client_id": CLIENT, "storage_path": f"shared_reports/{CLIENT}/other.xlsx"},
        {"id": "r3", "firm_id": FIRM, "client_id": "unassigned", "storage_path": "shared_reports/unassigned/pl.xlsx"},
        # a row whose path points outside this client's folder (the column is writable over PostgREST)
        {"id": "r4", "firm_id": FIRM, "client_id": CLIENT, "storage_path": f"{FIRM}/someone-else/secret.pdf"},
        {"id": "r5", "firm_id": FIRM, "client_id": CLIENT, "storage_path": f"shared_reports/{CLIENT}/../other/x.xlsx"},
        {"id": "r6", "firm_id": FIRM, "client_id": CLIENT, "storage_path": None},
    ])
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: type("S", (), {"table": db.table, "storage": db.storage})())
    monkeypatch.setattr(sc, "get_service_supabase", lambda: type("S", (), {"storage": db.service_storage})())
    monkeypatch.setattr(sr, "_USE_MOCK", False)
    monkeypatch.setattr(sr, "can_access_client", lambda user, client: client != "unassigned")
    return db


def test_a_report_in_the_callers_firm_and_clients_gets_a_link_minted_now(reports):
    out = sr.shared_report_link("r1", current_user=USER)["data"]
    assert out["download_url"] == f"https://signed.example/shared_reports/{CLIENT}/pl.xlsx"
    assert out["expires_in_seconds"] == sr.LINK_SECONDS == 300
    assert ("sign", f"shared_reports/{CLIENT}/pl.xlsx", 300) in reports.service_storage.calls


def test_the_link_is_signed_by_the_servers_client_because_the_callers_cannot_open_that_folder(reports):
    """Migration 469 lets a signed-in session open `{firm}/{client}/...` only; the share route stores a report under
    `shared_reports/{client}/...` with the service client, so a link signed with the caller's own client would not open."""
    sr.shared_report_link("r1", current_user=USER)
    assert reports.storage.calls == [] and [c[0] for c in reports.service_storage.calls] == ["sign"]


def test_another_firms_an_unassigned_and_a_missing_report_say_the_same_words_and_sign_nothing(reports):
    for report_id in ("r2", "r3", "missing"):
        assert _refused(404, sr.shared_report_link, report_id, current_user=USER) == "Report not found"
    assert reports.storage.calls == [] and reports.service_storage.calls == []


@pytest.mark.parametrize("report_id", ["r4", "r5", "r6"])
def test_a_row_whose_path_leaves_the_clients_folder_is_never_signed(reports, report_id):
    """`storage_path` is writable over PostgREST, so a path that is not under this client's own shared-reports folder, one
    that climbs out of it and a row with no path at all are each an error and mint nothing."""
    _refused(502, sr.shared_report_link, report_id, current_user=USER)
    assert reports.storage.calls == [] and reports.service_storage.calls == []


def test_a_link_that_could_not_be_made_is_an_error_and_not_an_empty_answer(reports):
    reports.service_storage.sign_fail = True
    _refused(502, sr.shared_report_link, "r1", current_user=USER)


# ── a tax notice's documents ─────────────────────────────────────────────────────────────────────────────────────────

NOTICE = {"id": "n1", "firm_id": FIRM, "client_id": CLIENT, "notice_storage_path": None, "response_storage_path": None}


@pytest.fixture
def notices(monkeypatch):
    db = _DB(it_notices=[
        dict(NOTICE),
        {**NOTICE, "id": "n2", "firm_id": OTHER_FIRM},
        {**NOTICE, "id": "n3", "client_id": "unassigned"},
        {**NOTICE, "id": "n4", "notice_storage_path": f"{FIRM}/{CLIENT}/notices/n4/old.pdf"},
    ])
    monkeypatch.setattr(na, "_USE_MOCK", False)
    monkeypatch.setattr(na, "_db", lambda: db)
    # The REAL door runs (`core/storage_door`, POST-A-339) over the server's client, whose bucket is the one recorder below. The
    # caller's own Storage client is not reachable any more: `service_storage` is a second name for the same recorder, so the
    # clean-up tests still read "the server removed it".
    import core.supabase_client as sc
    db.service_storage = db.storage
    monkeypatch.setattr(sc, "get_service_supabase", lambda: type("S", (), {"storage": db.storage})())
    monkeypatch.setattr(na, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(na, "can_access_client", lambda user, client: client != "unassigned")
    events: list = []
    monkeypatch.setattr(na, "log_event", lambda *a, **k: events.append((a, k)))
    db.events = events
    return db


def _attach(notice_id="n1", slot="notice", name="notice.pdf", data=PDF, user=USER):
    return na.attach_to_notice(notice_id, file=UploadFile(filename=name, file=io.BytesIO(data)), slot=slot, current_user=user)


def test_a_notice_document_is_stored_under_a_key_the_server_builds_and_written_onto_the_notice(notices):
    out = _attach(name="Notice u/s 143(1) (final).pdf")["data"]
    [(_, path, size, content_type)] = [c for c in notices.storage.calls if c[0] == "upload"]
    assert path.startswith(f"{FIRM}/{CLIENT}/notices/n1/") and path.count("/") == 4
    assert path.endswith(".pdf") and " " not in path and "(" not in path
    assert size == len(PDF) and content_type == "application/pdf"
    notice = next(r for r in notices.tables["it_notices"] if r["id"] == "n1")
    assert notice["notice_storage_path"] == path and notice["response_storage_path"] is None
    assert out == {"slot": "notice", "storage_path": path}
    [(args, kwargs)] = notices.events
    assert args[1:4] == ("it_notice", "n1", "attach") and kwargs["actor_id"] == USER["auth_user_id"]


def test_the_reply_fills_its_own_column_and_leaves_the_notice_alone(notices):
    _attach(slot="response", name="reply.docx", data=b"PK\x03\x04 zip container")
    notice = next(r for r in notices.tables["it_notices"] if r["id"] == "n1")
    assert notice["response_storage_path"] and notice["notice_storage_path"] is None


def test_two_files_of_one_name_on_two_notices_do_not_share_a_key(notices):
    _attach("n1")
    notices.tables["it_notices"].append({**NOTICE, "id": "n5"})
    _attach("n5")
    paths = [c[1] for c in notices.storage.calls if c[0] == "upload"]
    assert len(paths) == 2 and paths[0] != paths[1]


def test_a_slot_that_is_already_filled_is_refused_before_anything_is_stored(notices):
    detail = _refused(409, _attach, "n4")
    assert "already has its notice document" in detail
    assert notices.storage.calls == []


def test_a_slot_filled_a_moment_ago_by_someone_else_is_refused_and_the_new_file_is_taken_out_again(monkeypatch, notices):
    """The read saw an empty slot; the conditional update finds it filled (two people attaching at once)."""
    original_execute = _Query.execute
    state = {"first_read_done": False}

    def execute(self):
        res = original_execute(self)
        if self.mode == "select" and not state["first_read_done"]:
            state["first_read_done"] = True
            for r in notices.tables["it_notices"]:
                if r["id"] == "n1":
                    r["notice_storage_path"] = "someone/elses.pdf"
        return res

    monkeypatch.setattr(_Query, "execute", execute)
    detail = _refused(409, _attach, "n1")
    assert "already has its notice document" in detail
    [up] = [c for c in notices.storage.calls if c[0] == "upload"]
    assert ("remove", [up[1]]) in notices.service_storage.calls
    assert next(r for r in notices.tables["it_notices"] if r["id"] == "n1")["notice_storage_path"] == "someone/elses.pdf"


def test_a_notice_that_cannot_be_updated_removes_the_file_and_the_failure_still_reaches_the_caller(notices):
    notices.fail_update = True
    with pytest.raises(RuntimeError, match="update refused"):
        _attach()
    [up] = [c for c in notices.storage.calls if c[0] == "upload"]
    assert ("remove", [up[1]]) in notices.service_storage.calls
    assert notices.events == []


def test_the_clean_up_is_the_servers_because_only_a_partner_may_delete_from_the_bucket(notices):
    """Migration 469's policy let only a Partner delete from the bucket and a denied removal answers an empty list and no error.
    The file an Executive just stored is therefore removed through the server's client, which is now the only one there is."""
    notices.fail_update = True
    with pytest.raises(RuntimeError):
        _attach(user={**USER, "role": "Executive"})
    assert [c[0] for c in notices.storage.calls] == ["upload", "remove"]


def test_a_clean_up_that_removed_nothing_is_reported_and_does_not_hide_the_real_failure(notices, monkeypatch):
    """An empty answer from the removal is a file left behind: it is reported as a soft failure, and the caller still gets
    the failure that caused it."""
    reported: list = []
    monkeypatch.setattr(na, "capture_soft_failure", lambda exc, **kw: reported.append((str(exc), kw)))
    notices.service_storage.remove = lambda paths: []
    notices.fail_update = True
    with pytest.raises(RuntimeError, match="update refused"):
        _attach()
    [(message, kw)] = reported
    assert "was not removed" in message and kw["operation"] == "it_notice.attach_cleanup"


def test_a_storage_failure_writes_nothing_onto_the_notice(notices):
    notices.storage.upload_error = "bucket unavailable"
    assert "bucket unavailable" in _refused(500, _attach)
    assert next(r for r in notices.tables["it_notices"] if r["id"] == "n1")["notice_storage_path"] is None


def test_the_upload_is_bounded_and_typed_by_its_bytes(notices):
    class Spy(io.BytesIO):
        requested: list[int] = []
        def read(self, n=-1):
            self.requested.append(n)
            return super().read(n)

    from core.uploads import DEFAULT_MAX_BYTES
    big = Spy(PDF + b"x" * (DEFAULT_MAX_BYTES + 5))
    big.requested = []
    _refused(413, na.attach_to_notice, "n1", file=UploadFile(filename="big.pdf", file=big), slot="notice", current_user=USER)
    assert big.requested == [DEFAULT_MAX_BYTES + 1]
    _refused(415, _attach, name="fake.pdf", data=b"MZ\x90\x00 not a pdf")
    _refused(415, _attach, name="sheet.xlsx", data=b"PK\x03\x04")  # a type outside the notice allowlist
    assert notices.storage.calls == []


def test_another_firms_an_unassigned_and_a_missing_notice_say_the_same_words_and_store_nothing(notices):
    for notice_id in ("n2", "n3", "missing"):
        assert _refused(404, _attach, notice_id) == "Notice not found"
    assert notices.storage.calls == []


def test_a_link_is_minted_for_the_slot_asked_and_a_slot_with_no_file_is_a_404(notices):
    out = na.notice_attachment_link("n4", slot="notice", current_user=USER)["data"]
    assert out["download_url"] == f"https://signed.example/{FIRM}/{CLIENT}/notices/n4/old.pdf"
    assert out["expires_in_seconds"] == na.LINK_SECONDS
    assert "no response document" in _refused(404, na.notice_attachment_link, "n4", slot="response", current_user=USER)
    for notice_id in ("n2", "n3", "missing"):
        assert _refused(404, na.notice_attachment_link, notice_id, slot="notice", current_user=USER) == "Notice not found"
    notices.storage.sign_fail = True
    _refused(502, na.notice_attachment_link, "n4", slot="notice", current_user=USER)


def test_a_notices_door_is_bound_to_that_notices_own_folder():
    """The route also compares the stored path with the folder before it signs; the door is the second check, and it is the
    only one on the paths the server builds itself (store, take out again)."""
    assert na._storage(FIRM, CLIENT, "n1").folder == f"{FIRM}/{CLIENT}/notices/n1/"
    assert not na._storage(FIRM, CLIENT, "n1").owns(f"{FIRM}/{CLIENT}/notices/n2/x.pdf")
    assert not na._storage(FIRM, CLIENT, "n1").owns(f"{FIRM}/{CLIENT}/x.pdf")


@pytest.mark.parametrize("path", [
    "firm-002/other/secret.pdf",                                  # another firm's object
    f"{FIRM}/{CLIENT}/notices/n9/other.pdf",                      # another notice's file
    f"{FIRM}/{CLIENT}/notices/n4/../n9/other.pdf",                # climbs out of this notice's folder
])
def test_a_path_outside_the_notices_own_folder_is_never_signed(notices, path):
    """The column is writable over PostgREST, so a notice can be made to name somebody else's object."""
    next(r for r in notices.tables["it_notices"] if r["id"] == "n4")["notice_storage_path"] = path
    _refused(502, na.notice_attachment_link, "n4", slot="notice", current_user=USER)
    assert notices.storage.calls == []


# ── in front of the app: the slot is the server's vocabulary, and the tiers are the database's ───────────────────────

@pytest.fixture
def app_world(monkeypatch, dev_header_auth, notices):
    from main import app
    monkeypatch.setattr(na, "can_access_client", lambda user, client: True)
    return TestClient(app, raise_server_exceptions=False), notices


def _h(role):
    return {"X-User-Role": role, "X-Firm-Id": FIRM, "X-User-Id": f"{role}-1"}


def test_a_column_name_is_not_a_slot(app_world):
    client, db = app_world
    r = client.post("/api/income-tax/notices/n1/attachment", headers=_h("Partner"),
                    files={"file": ("n.pdf", io.BytesIO(PDF), "application/pdf")},
                    data={"slot": "firm_id"})
    assert r.status_code == 422, r.text
    assert db.storage.calls == []


@pytest.mark.parametrize("role, status", [("Partner", 200), ("Manager", 200), ("Executive", 200), ("Reviewer", 403)])
def test_an_executive_and_above_attaches_and_a_reviewer_does_not(app_world, role, status):
    client, db = app_world
    r = client.post("/api/income-tax/notices/n1/attachment", headers=_h(role),
                    files={"file": ("n.pdf", io.BytesIO(PDF), "application/pdf")}, data={"slot": "notice"})
    assert r.status_code == status, r.text
    filled = next(x for x in db.tables["it_notices"] if x["id"] == "n1")["notice_storage_path"]
    assert bool(filled) is (status == 200)


def test_every_staff_role_may_ask_for_a_link(app_world):
    client, _ = app_world
    for role in ("Partner", "Manager", "Executive", "Reviewer"):
        r = client.get("/api/income-tax/notices/n4/attachment-url", params={"slot": "notice"}, headers=_h(role))
        assert r.status_code == 200 and r.json()["data"]["download_url"], (role, r.text)
