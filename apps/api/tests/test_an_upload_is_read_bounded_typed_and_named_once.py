"""An uploaded file is read within a bound, recognised by its bytes, and named by us.

SECURITY-PRIVACY-20

WHAT WAS WRONG
    Nine routes take an UploadFile and each decided for itself. Four (a client
    document, a debit-note attachment, a purchase-credit-note attachment, a
    shared report) did `file.file.read()` with no bound; two put the caller's
    filename into the storage key with only "/" replaced, and the document route
    also put in `document_type` — free text, where the database's own CHECK admits
    nine values. The other five capped the size AFTER reading, so a 500 MB body
    was read whole into memory and then refused. Stored content types were
    whatever the sender's header said.

WHAT THESE PIN
    * the read is bounded: at most `max + 1` bytes are requested, and a file whose
      size is already known to be over is refused without a byte being read;
    * the extension is an allowlist, the BYTES must look like the extension (an
      .exe renamed .pdf is 415), and the stored content type is ours;
    * the names that reach a key cannot hold a separator, `..`, a control or
      bidi character, or a non-ASCII letter; `document_type` is the database's
      own vocabulary;
    * the four routes in the finding use all of it, and a refusal is a status
      code — the note routes wrap their work in a broad `except Exception` and a
      refusal raised inside it would have come back as a 200;
    * a request body over 32 MB is refused before the parser runs, with the CORS
      headers a cross-origin browser needs to read the refusal;
    * the rule, not the four call sites: every route taking an UploadFile goes
      through the helper, and nothing else in apps/api calls an unbounded
      `file.file.read()`.
"""
from __future__ import annotations

import ast
import io
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from core import uploads as up

API_ROOT = Path(__file__).resolve().parents[1]
MB = 1024 * 1024

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
XLSX = b"PK\x03\x04" + b"\x00" * 32
EXE = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64


class _Spy(io.BytesIO):
    """A file that records how much it was ever ASKED for."""

    def __init__(self, data: bytes):
        super().__init__(data)
        self.requested: list[int] = []

    def read(self, n: int = -1):                      # noqa: A003
        self.requested.append(n)
        return super().read(n)


def _file(name="scan.pdf", data=PDF, content_type="application/pdf"):
    spy = _Spy(data)
    f = UploadFile(filename=name, file=spy, headers={"content-type": content_type})
    f._spy = spy                                      # type: ignore[attr-defined]
    return f


def _refused(status, fn, *a, **k):
    with pytest.raises(HTTPException) as ei:
        fn(*a, **k)
    assert ei.value.status_code == status, (ei.value.status_code, ei.value.detail)
    return str(ei.value.detail)


# ── reading ──────────────────────────────────────────────────────────────────

def test_a_read_asks_for_at_most_the_bound_plus_one():
    f = _file(data=b"x" * (3 * MB))
    _refused(413, up.read_limited, f, 2 * MB)
    assert f._spy.requested == [2 * MB + 1]


def test_a_file_under_the_bound_comes_back_whole():
    f = _file(data=PDF)
    assert up.read_limited(f, 1024) == PDF


def test_a_file_exactly_at_the_bound_is_allowed_and_one_byte_over_is_not():
    assert up.read_limited(_file(data=b"x" * 100), 100) == b"x" * 100
    _refused(413, up.read_limited, _file(data=b"x" * 101), 100)


def test_a_file_already_known_to_be_too_large_is_refused_without_a_read():
    class _NoRead(io.BytesIO):
        def read(self, *a, **k):                      # noqa: A003
            raise AssertionError("the file was read although its size was already known")
    f = UploadFile(filename="a.pdf", file=_NoRead(b""), size=50 * MB)
    _refused(413, up.read_limited, f, 10 * MB)


def test_the_sentence_a_route_already_used_can_be_kept():
    detail = _refused(413, up.read_limited, _file(data=b"x" * 50), 10, message="Logo file must be smaller than 5 MB.")
    assert detail == "Logo file must be smaller than 5 MB."


# ── typing ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,data,ct,ext", [
    ("invoice.pdf", PDF, "application/pdf", "pdf"),
    ("INVOICE.PDF", PDF, "application/pdf", "pdf"),
    ("photo.jpg", JPEG, "image/jpeg", "jpg"),
    ("photo.jpeg", JPEG, "image/jpeg", "jpeg"),
    ("scan.png", PNG, "image/png", "png"),
    ("iphone.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 16, "image/heic", "heic"),
    ("books.xlsx", XLSX, up._XLSX, "xlsx"),
    ("old.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32, "application/vnd.ms-excel", "xls"),
    ("rows.csv", b"date,amount\n2026-04-01,100\n", "text/csv", "csv"),
    ("note.txt", b"hello", "text/plain", "txt"),
])
def test_what_an_attachment_may_be(name, data, ct, ext):
    out = up.accept_upload(_file(name, data, content_type="text/html"))
    assert out.extension == ext
    # OUR content type, not the `text/html` the sender's header claimed.
    assert out.content_type == ct


@pytest.mark.parametrize("name", ["setup.exe", "run.bat", "page.html", "image.svg", "data.xml",
                                  "macro.xlsm", "archive.tar.gz", "script.js", "evil.pdf.exe",
                                  "scan.p df"])
def test_a_kind_that_is_not_on_the_list_is_415(name):
    _refused(415, up.accept_upload, _file(name, PDF))


def test_an_exe_renamed_pdf_is_refused_by_its_bytes():
    detail = _refused(415, up.accept_upload, _file("invoice.pdf", EXE, "application/pdf"))
    assert "not a valid .pdf" in detail


@pytest.mark.parametrize("name,data", [
    ("a.png", PDF), ("a.pdf", PNG), ("a.xlsx", PDF), ("a.jpg", XLSX),
    ("a.csv", b"col1\x00col2"), ("a.xls", XLSX),
])
def test_bytes_that_are_not_what_the_name_says_are_415(name, data):
    _refused(415, up.accept_upload, _file(name, data))


def test_a_file_with_no_extension_is_typed_by_its_bytes_where_they_can_say():
    assert up.accept_upload(_file("scan", PDF)).extension == "pdf"
    assert up.accept_upload(_file("IMG_0042", JPEG)).extension == "jpg"
    # A zip container is an .xlsx or a .zip and the bytes do not say which.
    _refused(415, up.accept_upload, _file("books", XLSX))
    _refused(415, up.accept_upload, _file("mystery", b"just some text"))


def test_a_narrower_route_can_ask_for_a_narrower_list():
    _refused(415, up.accept_upload, _file("a.png", PNG), allowed={"pdf"})
    assert up.accept_upload(_file("a.pdf", PDF), allowed={"pdf"}).extension == "pdf"


def test_too_large_is_asked_before_the_type():
    _refused(413, up.accept_upload, _file("huge.exe", b"x" * 200), max_bytes=100)


# ── naming ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,display,storage", [
    ("scan.pdf", "scan.pdf", "scan.pdf"),
    ("../../etc/passwd.pdf", "passwd.pdf", "passwd.pdf"),
    ("..\\..\\windows\\win.pdf", "win.pdf", "win.pdf"),
    ("C:\\Users\\Raj\\Desktop\\invoice 12.pdf", "invoice 12.pdf", "invoice_12.pdf"),
    ("...hidden.pdf", "hidden.pdf", "hidden.pdf"),
    ("a/b/c.pdf", "c.pdf", "c.pdf"),
    ("bill (final).pdf", "bill (final).pdf", "bill_final.pdf"),
    ("चालान.pdf", "चालान.pdf", "upload.pdf"),
    ("invoice\u202efdp.pdf", "invoicefdp.pdf", "invoicefdp.pdf"),
    ("line\nbreak\x00.pdf", "linebreak.pdf", "linebreak.pdf"),
    ("a..b.pdf", "a.b.pdf", "a.b.pdf"),
])
def test_names_carry_no_path_control_character_or_non_ascii_into_the_key(raw, display, storage):
    out = up.accept_upload(_file(raw, PDF))
    assert out.display_name == display
    assert out.storage_name == storage
    for name in (out.display_name, out.storage_name):
        assert not re.search(r"[\\/\x00-\x1f\u202a-\u202e]", name)
        assert ".." not in name and not name.startswith(".")
    assert re.fullmatch(r"[A-Za-z0-9._-]+", out.storage_name)


def test_a_three_hundred_character_name_is_capped_and_keeps_its_extension():
    out = up.accept_upload(_file("x" * 300 + ".pdf", PDF))
    assert out.storage_name.endswith(".pdf") and len(out.storage_name) <= 105
    assert len(out.display_name) <= 105


@pytest.mark.parametrize("ok", ["OTHER", "client-001", "11111111-2222-3333-4444-555555555555",
                                "GST_INVOICE", "Form 16.2026"])
def test_a_folder_name_that_is_safe_passes_unchanged(ok):
    assert up.safe_path_segment(ok, field="f") == ok


@pytest.mark.parametrize("bad", ["../x", "a/b", "a\\b", "..", ".hidden", "-lead", "", None, "x" * 65,
                                 "a\nb", "a\u202eb", "a%2fb"[:0] + "a/../b", "a..b", " lead"])
def test_a_value_that_would_become_a_folder_is_refused_when_it_could_traverse(bad):
    _refused(422, up.safe_path_segment, bad, field="document_type")


# ── the four routes ──────────────────────────────────────────────────────────

USER = {"firm_id": "F1", "id": "u1", "auth_user_id": "a1", "email": "ca@f.test", "role": "Partner"}
CLIENT = "11111111-2222-3333-4444-555555555555"


class _Bucket:
    def __init__(self, sink):
        self.sink = sink

    def upload(self, path=None, file=None, file_options=None, **kw):
        self.sink.append({"path": path, "size": len(file), "options": file_options})
        return {"path": path}

    def create_signed_url(self, *a, **k):
        return {"signedURL": "https://signed.example/x"}


class _Storage:
    def __init__(self, sink):
        self.sink = sink

    def from_(self, _bucket):
        return _Bucket(self.sink)


class _Supabase:
    def __init__(self, sink):
        self.storage = _Storage(sink)


@pytest.fixture
def stored(monkeypatch):
    """Route the live (non-mock) storage path at a recorder."""
    sink: list[dict] = []
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: _Supabase(sink))
    return sink


def _documents(monkeypatch, *, mock):
    import routers.documents as docs
    monkeypatch.setattr(docs, "_USE_MOCK", mock)
    monkeypatch.setattr(docs, "assert_partner_for_internal_id", lambda *a, **k: None)
    monkeypatch.setattr(docs, "assert_client_access", lambda *a, **k: None)
    repo = MagicMock()
    repo.create.side_effect = lambda row: {"id": "doc-1", **row}
    monkeypatch.setattr(docs, "document_repo", repo)
    monkeypatch.setattr(docs, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(docs, "log_activity", lambda *a, **k: None)
    return docs, repo


def test_the_document_route_refuses_a_50_mb_file_after_reading_at_most_the_bound(monkeypatch):
    docs, _ = _documents(monkeypatch, mock=True)
    f = _file("big.pdf", PDF + b"x" * (50 * MB))
    _refused(413, docs.upload_document, file=f, document_type="OTHER", client_id=CLIENT, current_user=USER)
    assert f._spy.requested == [up.DEFAULT_MAX_BYTES + 1]


def test_the_document_route_refuses_an_exe(monkeypatch):
    docs, repo = _documents(monkeypatch, mock=True)
    _refused(415, docs.upload_document, file=_file("setup.exe", EXE),
             document_type="OTHER", client_id=CLIENT, current_user=USER)
    repo.create.assert_not_called()


@pytest.mark.parametrize("bad", ["../../other-firm", "a/b", "..", "PAN", "", "other", "OTHER/../x"])
def test_the_document_route_refuses_a_document_type_the_database_would_not_take(monkeypatch, bad):
    docs, repo = _documents(monkeypatch, mock=True)
    detail = _refused(422, docs.upload_document, file=_file(), document_type=bad,
                      client_id=CLIENT, current_user=USER)
    assert "document_type must be one of" in detail
    repo.create.assert_not_called()


def test_the_document_route_builds_the_key_and_type_itself(monkeypatch, stored):
    docs, repo = _documents(monkeypatch, mock=False)
    out = docs.upload_document(
        file=_file("../../secret/Invoice 7.pdf", PDF, content_type="text/html"),
        document_type="GST_INVOICE", client_id=CLIENT, current_user=USER)
    [put] = stored
    assert re.fullmatch(rf"F1/{CLIENT}/GST_INVOICE/[0-9a-f-]{{36}}_Invoice_7\.pdf", put["path"]), put["path"]
    assert put["options"] == {"content-type": "application/pdf"}
    row = repo.create.call_args.args[0]
    assert row["file_name"] == "Invoice 7.pdf" and row["storage_path"] == put["path"]
    assert out["success"] is True


def test_the_document_types_are_the_databases_own():
    from routers.documents import DOCUMENT_TYPES
    schema = (API_ROOT / "migrations" / "001_initial_schema.sql").read_text(encoding="utf-8")
    block = re.search(r"document_type TEXT NOT NULL CHECK \(document_type IN \((.*?)\)\)", schema, re.S)
    assert block, "migration 001's document_type CHECK was not found"
    assert DOCUMENT_TYPES == set(re.findall(r"'([A-Z0-9_]+)'", block.group(1)))
    for path in (API_ROOT / "migrations").glob("*.sql"):
        if path.name.startswith("001_"):
            continue
        assert "documents_document_type_check" not in path.read_text(encoding="utf-8", errors="replace"), (
            f"{path.name} changes the documents.document_type CHECK — update routers/documents.DOCUMENT_TYPES")


def _note_routes(monkeypatch):
    import routers.debit_notes as dn
    import routers.purchase_credit_notes as pcn
    for mod in (dn, pcn):
        monkeypatch.setattr(mod, "assert_client_access", lambda *a, **k: None)
    return [("debit_note", dn, dn.upload_debit_note_document),
            ("purchase_credit_note", pcn, pcn.upload_purchase_credit_note_document)]


@pytest.mark.parametrize("which", [0, 1], ids=["debit_note", "purchase_credit_note"])
def test_a_note_attachment_over_the_bound_is_a_413_not_a_200_with_a_shrug(monkeypatch, which):
    """Both routes wrap their work in `except Exception` and answer
    `api_response(False, ...)` with a 200. A refusal raised INSIDE that try would
    have been swallowed into it — which is why it is raised outside."""
    kind, mod, route = _note_routes(monkeypatch)[which]
    monkeypatch.setattr(mod, "_USE_MOCK", True)
    f = _file("big.pdf", PDF + b"x" * (50 * MB))
    _refused(413, route, file=f, client_id=CLIENT, current_user=USER)
    assert f._spy.requested == [up.DEFAULT_MAX_BYTES + 1]


@pytest.mark.parametrize("which", [0, 1], ids=["debit_note", "purchase_credit_note"])
def test_a_note_attachment_that_is_an_exe_is_415(monkeypatch, which):
    _, mod, route = _note_routes(monkeypatch)[which]
    monkeypatch.setattr(mod, "_USE_MOCK", True)
    _refused(415, route, file=_file("payload.exe", EXE), client_id=CLIENT, current_user=USER)


@pytest.mark.parametrize("which", [0, 1], ids=["debit_note", "purchase_credit_note"])
def test_a_note_attachment_is_keyed_and_typed_by_us(monkeypatch, stored, which):
    kind, mod, route = _note_routes(monkeypatch)[which]
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    out = route(file=_file("..\\..\\x/Scan 1.pdf", PDF, content_type="text/html"),
                client_id=CLIENT, current_user=USER)
    [put] = stored
    assert re.fullmatch(rf"F1/{CLIENT}/{kind}/[0-9a-f-]{{36}}_Scan_1\.pdf", put["path"]), put["path"]
    assert put["options"] == {"content-type": "application/pdf"}
    assert out["data"]["document_url"] == put["path"]


@pytest.mark.parametrize("which", [0, 1], ids=["debit_note", "purchase_credit_note"])
def test_a_client_id_that_is_a_path_is_refused_before_it_reaches_a_key(monkeypatch, stored, which):
    _, mod, route = _note_routes(monkeypatch)[which]
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    _refused(422, route, file=_file(), client_id="../other-firm", current_user=USER)
    assert stored == []


def _share(**over):
    import routers.shared_reports as sr
    kw = dict(file=UploadFile(filename="trial.xlsx", file=_Spy(XLSX + b"rest"),
                              headers={"content-type": up._XLSX}),
              client_id=CLIENT, report_id="trial", report_label="Trial Balance",
              financial_year="2025-26", current_user=USER)
    kw.update(over)
    return sr.share_report_to_portal(**kw)


def test_a_shared_report_over_the_bound_is_refused_after_reading_at_most_the_bound():
    spy = _Spy(XLSX + b"x" * (50 * MB))
    f = UploadFile(filename="trial.xlsx", file=spy, headers={"content-type": up._XLSX})
    _refused(413, _share, file=f)
    from domain.reporting.shared_report import MAX_BYTES
    assert spy.requested == [MAX_BYTES + 1]


def test_a_shared_report_that_is_not_a_workbook_is_refused_by_its_bytes():
    f = UploadFile(filename="trial.xlsx", file=_Spy(EXE), headers={"content-type": up._XLSX})
    detail = _refused(422, _share, file=f)
    assert "xlsx" in detail


def test_a_real_workbook_is_still_shared():
    assert _share()["success"] is True


# ── in front of the app ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_client():
    from main import app
    return TestClient(app, raise_server_exceptions=False), app


def test_a_body_over_the_limit_is_refused_before_the_parser_runs(app_client):
    client, _ = app_client
    from middleware.body_limit import MAX_REQUEST_BODY_BYTES
    body = b"x" * (MAX_REQUEST_BODY_BYTES + 1)
    res = client.post("/api/documents/upload", content=body,
                      headers={"content-type": "multipart/form-data; boundary=zzz",
                               "origin": "http://localhost:3000"})
    assert res.status_code == 413
    assert res.json() == {"success": False, "data": None,
                          "error": "That request is too large (the limit is 32 MB)."}
    # The API is cross-origin from the web app: a refusal without this header is
    # "Failed to fetch" in the browser, not a sentence.
    assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_a_chunked_body_with_no_content_length_is_refused_through_the_real_app(app_client):
    """No Content-Length to check, so the bytes are counted as they arrive. The
    status is 413 from a route that reads its own body, and FastAPI's 400 "error
    parsing the body" where the exception crosses BaseHTTPMiddleware's task group
    (see middleware/body_limit.py) — both are refusals, and the route never runs.
    (Starlette's TestClient reads a whole request body before handing it over, so
    whether consumption STOPS is asserted one layer down, below.)"""
    client, _ = app_client
    from middleware.body_limit import MAX_REQUEST_BODY_BYTES
    boundary = "zzz"
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="a.pdf"\r\n\r\n').encode()

    def chunks():
        yield head
        for _ in range(MAX_REQUEST_BODY_BYTES // MB + 2):
            yield b"x" * MB

    res = client.post("/api/documents/upload", content=chunks(),
                      headers={"content-type": f"multipart/form-data; boundary={boundary}"})
    assert res.status_code in (400, 413), (res.status_code, res.text[:200])


def test_the_counter_stops_the_read_at_the_limit_and_the_app_sees_a_413():
    import asyncio
    from middleware.body_limit import BodySizeLimitMiddleware

    reads = 0
    raised: list[HTTPException] = []

    async def receive():
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": b"x" * MB, "more_body": True}

    async def app(scope, receive, send):
        try:
            while True:
                await receive()
        except HTTPException as exc:
            raised.append(exc)

    async def send(_message):
        raise AssertionError("nothing is answered from the counter: the app's own read raises")

    asyncio.run(BodySizeLimitMiddleware(app, max_bytes=4 * MB)(
        {"type": "http", "headers": []}, receive, send))

    assert reads == 5, f"{reads} chunks were pulled; the fifth crosses 4 MB and must be the last"
    assert len(raised) == 1 and raised[0].status_code == 413


def test_a_lying_content_length_does_not_buy_an_unbounded_body():
    """A header that says 1 KB over a body that is not: the counter is the answer."""
    import asyncio
    from middleware.body_limit import BodySizeLimitMiddleware

    reads = 0
    raised: list[HTTPException] = []

    async def receive():
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": b"x" * MB, "more_body": True}

    async def app(scope, receive, send):
        try:
            while True:
                await receive()
        except HTTPException as exc:
            raised.append(exc)

    asyncio.run(BodySizeLimitMiddleware(app, max_bytes=2 * MB)(
        {"type": "http", "headers": [(b"content-length", b"1024")]}, receive, lambda m: None))
    assert reads == 3 and raised and raised[0].status_code == 413


def test_an_ordinary_request_passes_through_untouched(app_client):
    client, _ = app_client
    assert client.get("/health").status_code == 200
    small = client.post("/api/public/demo-request", json={"name": "x"})
    assert small.status_code != 413


def test_the_limiter_sits_inside_cors(app_client):
    """`user_middleware[0]` is the outermost. A 413 built outside CORSMiddleware
    carries no Access-Control-Allow-Origin header."""
    _, app = app_client
    names = [m.cls.__name__ for m in app.user_middleware]
    assert names.index("CORSMiddleware") < names.index("BodySizeLimitMiddleware"), names


# ── the rule, not the call sites ─────────────────────────────────────────────

def _upload_routes():
    found = []
    for path in sorted((API_ROOT / "routers").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            params = [a.arg for a in fn.args.args + fn.args.kwonlyargs
                      if a.annotation is not None and "UploadFile" in ast.unparse(a.annotation)]
            if params:
                found.append((path.name, fn, params))
    return found


def test_every_route_that_takes_an_upload_goes_through_the_helper():
    routes = _upload_routes()
    assert len(routes) >= 9, f"the scan found only {len(routes)} UploadFile routes"
    helpers = {"accept_upload", "read_limited"}
    offenders = []
    for fname, fn, params in routes:
        calls = {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        touches = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id in params
                   and isinstance(n.ctx, ast.Load)}
        if touches and not (calls & helpers):
            offenders.append(f"{fname}::{fn.name}")
    assert not offenders, (
        f"these routes read an UploadFile without core.uploads.read_limited/accept_upload: {offenders}")


def test_no_unbounded_read_of_an_upload_survives_anywhere():
    bad = []
    for path in API_ROOT.rglob("*.py"):
        if set(path.parts) & {"tests", ".venv", "venv", "__pycache__", "migrations", "node_modules"}:
            continue
        if path.name == "uploads.py" and path.parent.name == "core":
            continue
        code = re.sub(r'"""(?:.|\n)*?"""', "", path.read_text(encoding="utf-8", errors="replace"))
        code = "\n".join(l.split("#", 1)[0] for l in code.splitlines())
        if re.search(r"\bfile\.file\.read\(\s*\)", code) or re.search(r"await\s+file\.read\(\s*\)", code):
            bad.append(path.relative_to(API_ROOT).as_posix())
    assert not bad, f"an unbounded upload read remains in: {bad}"
