"""Supabase Storage is reached only through `core/storage_door`, and the door is bound to a folder (POST-A-339, the Storage step).

WHAT IS HELD
    * THE RULE, OVER THE SOURCE. No module of `apps/api` outside `core/storage_door.py` reads the `.storage` attribute of a database
      client, whatever the client was called (`db`, `sb`, `svc`, `get_supabase()`, `get_service_supabase()`): found by walking every
      module's syntax tree, so a spelling that does not mention a client's name is the same finding. Before this change nine routers
      reached Storage with the REQUEST's own client, so the policies of migrations 005 and 469 on `storage.objects` decided who could
      open which folder, and a signed-in person with their own token could call Storage by hand and open whatever those policies
      allowed. The policies are dropped by a later migration, which is safe only while this holds.
    * EVERY DOOR IS BOUND TO A CLIENT'S OR A FIRM'S OWN FOLDER. A call to `storage_folder(...)` names at least two folders after the
      bucket, so `storage_folder("Documents", firm_id)` (every client of the firm) is not a thing that can be written without this
      test failing.
    * THE DOOR USES THE SERVER'S CLIENT AND REFUSES A KEY OUTSIDE ITS FOLDER, before any request is made: another firm's, another
      client's, a climb out (`..` or `.` as a path component, not as part of a name), a doubled, leading or trailing separator, a
      backslash, a control or bidirectional character, `?` or `#`, a percent-encoded dot or separator, an empty remainder and a
      value that is not a string. Folder names are held to the pattern `core/uploads` holds a key's folders to.
    * THE VERBS ARE THE ROUTES' VERBS: upload with our content type (and `upsert` only when asked), one signed link, a batch of
      links, a removal and a public link, each refusing a foreign key.

Needs no database and no network: the server's client is a recorder.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import core.storage_door as door
from core.storage_door import FolderStorage, StoragePathRefused, storage_folder

API = Path(__file__).resolve().parents[1]
FIRM, CLIENT, OTHER_CLIENT = "firm-0001", "11111111-2222-3333-4444-555555555555", "99999999-2222-3333-4444-555555555555"


#: The door, and the factory that builds the shared client: `core/supabase_client._force_http1_storage` reads `.storage` once to
#: take the library's HTTP/2 session off it (see the test below). Nothing else may.
FACTORY = "core/supabase_client.py"


def _modules(*, except_factory=True):
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API).as_posix()
        if rel.startswith(("tests/", "migrations/", "scripts/")) or "/__pycache__/" in rel or rel == "core/storage_door.py":
            continue
        if except_factory and rel == FACTORY:
            continue
        yield rel, ast.parse(path.read_text(encoding="utf-8"))


# ── the rule ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_no_module_reaches_storage_except_the_door():
    scanned, offenders = 0, []
    for rel, tree in _modules():
        scanned += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "storage":
                offenders.append(f"{rel}:{node.lineno}")
    assert scanned > 300, f"the scan walked {scanned} modules: it is reading nothing"
    assert not offenders, (
        "these modules read `.storage` of a database client; every file goes through core/storage_door.storage_folder, the "
        f"server's client bound to a folder (POST-A-339): {offenders}")


def test_the_factory_reads_storage_once_and_only_to_take_http2_off_it():
    [(_, tree)] = [(r, t) for r, t in _modules(except_factory=False) if r == FACTORY]
    reads = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "storage"]
    assert len(reads) == 1, "the client factory reads `.storage` for something other than `_force_http1_storage`"
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_force_http1_storage")
    assert reads[0] in list(ast.walk(function))


def test_the_rule_would_see_a_use_it_was_written_to_catch():
    """Negative control: the same walk over source that does what the nine routers did."""
    for src in ("sb = get_supabase()\nsb.storage.from_('Documents').upload(p, b)",
                "get_service_supabase().storage.from_('Documents').remove([p])",
                "def f(db):\n    return db.storage"):
        assert any(isinstance(n, ast.Attribute) and n.attr == "storage" for n in ast.walk(ast.parse(src))), src


def _door_calls():
    for rel, tree in _modules():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "storage_folder"):
                yield rel, node


def test_every_door_a_route_opens_is_bound_to_a_client_or_firm_folder_and_never_to_a_whole_bucket_or_firm():
    seen = list(_door_calls())
    assert len(seen) >= 12, f"only {len(seen)} doors found: the scan is reading nothing"
    thin = [f"{rel}:{call.lineno}" for rel, call in seen if len(call.args) < 3 or call.keywords]
    assert not thin, (
        "a door must name the bucket and at least TWO folders (a firm and a client, or `shared_reports`/`logos` and one), "
        f"positionally: {thin}")


def test_the_two_folder_patterns_are_one():
    import core.uploads as uploads
    assert door._SEGMENT.pattern == uploads._SEGMENT.pattern, (
        "a folder name core/uploads lets into a key must be one the door accepts, and the other way round")


# ── the door ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Bucket:
    def __init__(self, log):
        self.log = log

    def upload(self, path=None, file=None, file_options=None, **kw):
        self.log.append(("upload", path, file, dict(file_options or {})))
        return {"path": path}

    def create_signed_url(self, path, expires_in=60):
        self.log.append(("sign", path, expires_in))
        return {"signedURL": f"https://signed.example/{path}"}

    def create_signed_urls(self, paths, expires_in=60):
        self.log.append(("sign_many", list(paths), expires_in))
        return [{"path": p, "signedURL": f"https://signed.example/{p}"} for p in paths]

    def remove(self, paths):
        self.log.append(("remove", list(paths)))
        return [{"name": p} for p in paths]

    def get_public_url(self, path):
        self.log.append(("public", path))
        return f"https://public.example/{path}"


@pytest.fixture
def server(monkeypatch):
    log: list = []
    asked: list = []
    client = type("S", (), {"storage": type("St", (), {"from_": lambda self, b: (asked.append(b), _Bucket(log))[1]})()})()
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_service_supabase", lambda: client)
    # the caller's own client must never be asked for
    monkeypatch.setattr(sc, "get_supabase", lambda: (_ for _ in ()).throw(AssertionError("the caller's client was used")))
    return type("W", (), {"log": log, "buckets": asked})


def test_a_door_stores_signs_and_removes_under_its_folder_with_the_servers_client(server):
    d = storage_folder("Documents", FIRM, CLIENT)
    key = f"{FIRM}/{CLIENT}/GST_INVOICE/abc_Invoice.pdf"
    d.upload(key, b"%PDF", "application/pdf")
    d.create_signed_url(key, 300)
    d.create_signed_urls([key, f"{FIRM}/{CLIENT}/x.pdf"], 3600)
    d.remove([key])
    assert server.log == [
        ("upload", key, b"%PDF", {"content-type": "application/pdf"}),
        ("sign", key, 300),
        ("sign_many", [key, f"{FIRM}/{CLIENT}/x.pdf"], 3600),
        ("remove", [key]),
    ]
    assert set(server.buckets) == {"Documents"}


def test_an_upsert_is_sent_only_when_asked_for(server):
    d = storage_folder("shared-reports", "shared_reports", CLIENT)
    d.upload(f"shared_reports/{CLIENT}/pl.xlsx", b"x", "application/vnd.ms-excel", upsert=True)
    d.upload(f"shared_reports/{CLIENT}/pl2.xlsx", b"x", "application/vnd.ms-excel")
    assert server.log[0][3] == {"content-type": "application/vnd.ms-excel", "upsert": "true"}
    assert server.log[1][3] == {"content-type": "application/vnd.ms-excel"}


def test_the_public_link_of_a_logo_is_asked_through_the_door_too(server):
    d = storage_folder("firm-assets", "logos", FIRM)
    assert d.get_public_url(f"logos/{FIRM}/logo.png") == f"https://public.example/logos/{FIRM}/logo.png"
    with pytest.raises(StoragePathRefused):
        d.get_public_url("logos/someone-else/logo.png")


FOREIGN = [
    f"other-firm/{CLIENT}/x.pdf",                       # another firm
    f"{FIRM}/{OTHER_CLIENT}/x.pdf",                     # another client of the same firm
    f"{FIRM}/{CLIENT}/../{OTHER_CLIENT}/x.pdf",         # a climb out
    f"{FIRM}/{CLIENT}/a/../../../etc/passwd",
    f"{FIRM}/{CLIENT}//x.pdf",                          # a doubled separator straight after the folder
    f"{FIRM}/{CLIENT}/a//b.pdf",                        # and one inside the remainder
    f"/{FIRM}/{CLIENT}/x.pdf",                          # a leading one
    f"{FIRM}/{CLIENT}/a\\b.pdf",                        # a backslash
    f"{FIRM}/{CLIENT}/x\n.pdf",                         # a control character
    f"{FIRM}/{CLIENT}/x\x7f.pdf",                       # DEL
    f"{FIRM}/{CLIENT}/x\u202e.pdf",                     # a bidirectional override: a name that reads as another
    f"{FIRM}/{CLIENT}/x?y.pdf",                         # the URL would be cut at `?` and name another key
    f"{FIRM}/{CLIENT}/x#y.pdf",                         # and at `#`
    f"{FIRM}/{CLIENT}/%2e%2e/{OTHER_CLIENT}/x.pdf",     # percent-encoded dots
    f"{FIRM}/{CLIENT}/a%2Fb.pdf",                       # an encoded slash, in either case
    f"{FIRM}/{CLIENT}/a%5cb.pdf",                       # an encoded backslash
    f"{FIRM}/{CLIENT}/./x.pdf",                         # a dot component
    f"{FIRM}/{CLIENT}/x/",                              # a trailing separator
    f"{FIRM}/{CLIENT}/",                                # the folder itself
    f"{FIRM}/{CLIENT}",                                 # the folder with no separator
    f"{FIRM}/{CLIENT}-evil/x.pdf",                      # a client whose name merely starts with this one's
    f"{FIRM}x/{CLIENT}/x.pdf",
    "", None, 7, ["a"],
]


#: Keys an older release stored, or a caller named, that are NAMES and not climbs: `..` is refused as a path component, and not as
#: a substring of one. A bill attached as `invoice..pdf` before `core/uploads` named files must still open.
NAMES = [
    f"{FIRM}/{CLIENT}/GST_INVOICE/abc_Invoice.pdf",
    f"{FIRM}/{CLIENT}/purchase_bill/abc_invoice..pdf",
    f"{FIRM}/{CLIENT}/a..b/x...y.pdf",
    f"{FIRM}/{CLIENT}/x y (1) 100%25.pdf",
    f"{FIRM}/{CLIENT}/\u092c\u093f\u0932.pdf",
]


@pytest.mark.parametrize("key", NAMES, ids=[repr(k)[-30:] for k in NAMES])
def test_a_dotted_or_unusual_name_under_the_folder_is_a_name_and_opens(server, key):
    d = storage_folder("Documents", FIRM, CLIENT)
    assert d.owns(key)
    d.create_signed_url(key, 60)
    assert server.log == [("sign", key, 60)]


@pytest.mark.parametrize("key", FOREIGN, ids=[repr(k)[:40] for k in FOREIGN])
def test_a_key_outside_the_folder_is_refused_on_every_verb_before_any_request_is_made(server, key):
    d = storage_folder("Documents", FIRM, CLIENT)
    for call in (lambda: d.upload(key, b"x", "application/pdf"), lambda: d.create_signed_url(key, 60),
                 lambda: d.create_signed_urls([f"{FIRM}/{CLIENT}/ok.pdf", key], 60), lambda: d.remove([key]),
                 lambda: d.get_public_url(key)):
        with pytest.raises(StoragePathRefused):
            call()
    assert server.log == [], "a refused key reached Storage"


def test_a_batch_with_one_foreign_key_signs_none_of_them(server):
    d = storage_folder("Documents", FIRM, CLIENT)
    with pytest.raises(StoragePathRefused):
        d.create_signed_urls([f"{FIRM}/{CLIENT}/a.pdf", f"{FIRM}/{OTHER_CLIENT}/b.pdf"], 60)
    assert server.log == []


@pytest.mark.parametrize("segments", [
    (), ("",), (None,), (FIRM, ""), (FIRM, "a/b"), (FIRM, ".."), (FIRM, "a..b"), (FIRM, "../x"), (FIRM, "a\\b"),
    (FIRM, "x" * 65), (FIRM, "-leading"), (FIRM, "\n"), ("Documents/x", CLIENT),
])
def test_a_folder_that_is_not_a_plain_name_cannot_be_opened(segments):
    with pytest.raises(StoragePathRefused):
        FolderStorage("Documents", *segments)


@pytest.mark.parametrize("bucket", ["", "a/b", "..", None, "a" * 70])
def test_a_bucket_that_is_not_a_plain_name_cannot_be_opened(bucket):
    with pytest.raises(StoragePathRefused):
        FolderStorage(bucket, FIRM, CLIENT)


def test_a_door_with_only_a_firm_is_buildable_but_the_rule_above_forbids_a_route_to_build_one():
    """The class cannot know a layout; `test_every_door_a_route_opens_is_bound_to_...` is what holds the routes to two folders.
    This is here so the two are read together."""
    assert FolderStorage("Documents", FIRM).folder == f"{FIRM}/"
