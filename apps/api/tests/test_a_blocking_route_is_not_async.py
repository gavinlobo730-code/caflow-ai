"""BANK-08 — a route that does blocking work must not be `async def`.

WHAT WAS WRONG
    routers/banking.py's three multipart routes were the router's only
    `async def`s and their bodies were entirely synchronous: pdfplumber, then a
    150-dpi rasterisation of up to twenty pages, then ONE BLOCKING GEMINI CALL
    PER PAGE. FastAPI runs an `async def` route on the event loop itself, so a
    single scanned statement occupied the only worker (apps/api/Dockerfile runs
    one gunicorn process) for as long as twenty vision calls take — stalling
    every other request on the instance, and the 120-second worker timeout then
    dropped THOSE requests rather than only the upload.

    A plain `def` route is run by Starlette in a threadpool instead. The whole
    fix, for nine of them, was deleting the word `async`.

THE FINDING NAMED THREE. THE PATTERN IS ELEVEN.
    The same shape was in branding (logo upload), debit notes and purchase
    credit notes (document upload), documents (upload and parse), the
    withdrawn client copilot — and in document_intelligence_v1's invoice
    extraction, which is a Gemini vision call on the event loop exactly like
    the banking one and is in no finding at all.

WHY THIS IS THE RULE AND NOT A LIST
    "Do not block the event loop" cannot be tested directly. What CAN be
    tested is the tell: a route declared `async` whose every `await` is a read
    of the request body — or which awaits nothing at all — is async for no
    async reason, and everything it does after that read runs on the loop.

    Nothing in this backend is async-native: supabase-py is sync, the AI
    clients are sync, pdfplumber and openpyxl are sync. So the tell is
    reliable here in a way it would not be in a codebase with an async driver.

WHAT THE ANSWER TURNED OUT TO BE: NO EXCEPTIONS AT ALL
    payments.payment_webhook looked like the one route that had to stay async —
    a sync route cannot reach the RAW request body, and the gateway's signature
    is computed over the exact bytes it sent, so re-serialising a parsed
    payload breaks every signature. It is still `async def`, and it no longer
    offends this rule, because staying async was only half an answer: the
    blocking half (verify, read, write) now goes to the threadpool through
    run_in_threadpool, so the route awaits something genuinely asynchronous.

    ALLOWED_ASYNC is therefore EMPTY. It is kept, with its contract, because
    the next such route is easier to register with a reason than to argue
    about — but the rule currently holds outright.
"""
from __future__ import annotations

import ast
import io
import pathlib

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.testclient import TestClient

API = pathlib.Path(__file__).resolve().parent.parent

# Reads of the request body. A route may legitimately await one of these and
# nothing else — but then it should be sync and read the body synchronously,
# unless it is one of the registered exceptions.
_BODY_READS = {"read", "body", "json", "form", "stream"}

#: "<module>.<route>" -> why it must stay `async def` while awaiting nothing
#: but the request body. EMPTY, and that is the current answer rather than an
#: oversight — see the module docstring.
ALLOWED_ASYNC: dict[str, str] = {}


def _routes(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        deco = " ".join(ast.unparse(d) for d in node.decorator_list)
        if "router." in deco or "app." in deco:
            yield node


def _awaits_only_the_body(node: ast.AsyncFunctionDef) -> bool:
    for n in ast.walk(node):
        if not isinstance(n, ast.Await):
            continue
        call = n.value
        if not (isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr in _BODY_READS):
            return False
    return True


def _offenders() -> list[str]:
    out = []
    for path in sorted((API / "routers").glob("*.py")):
        for node in _routes(path):
            if not _awaits_only_the_body(node):
                continue
            key = f"{path.stem}.{node.name}"
            if key in ALLOWED_ASYNC:
                continue
            out.append(f"{path.name}:{node.lineno} {node.name}")
    return out


def test_no_route_is_async_for_no_async_reason():
    bad = _offenders()
    assert not bad, (
        "These routes are `async def` and await nothing but the request body, "
        "so everything they do after that read runs ON THE EVENT LOOP and "
        "stalls every other request on the worker. Make them plain `def` — "
        "Starlette then runs them in its threadpool — and read an upload with "
        "`file.file.read()` instead of `await file.read()`. If one genuinely "
        "must stay async, register it in ALLOWED_ASYNC with the reason:\n  "
        + "\n  ".join(bad))


def test_every_allowed_exception_says_why():
    """A guard whose exceptions are unexplained is a guard that gets widened."""
    for key, reason in ALLOWED_ASYNC.items():
        assert len(reason.strip()) > 40, f"{key}: the reason is too thin to check"


def test_no_allowed_exception_is_stale():
    """An entry that no longer offends must go, or the list becomes a place
    routes are parked rather than fixed."""
    live = set()
    for path in sorted((API / "routers").glob("*.py")):
        for node in _routes(path):
            if _awaits_only_the_body(node):
                live.add(f"{path.stem}.{node.name}")
    stale = sorted(set(ALLOWED_ASYNC) - live)
    assert not stale, f"ALLOWED_ASYNC entries that no longer offend: {stale}"


def test_the_payment_webhook_hands_its_blocking_half_to_the_threadpool():
    """The one route that genuinely has to stay async.

    It needs the RAW body — the gateway signs the exact bytes it sent, and a
    sync route cannot reach them. Staying async is only half an answer though:
    process_webhook verifies a signature, reads the database and writes a
    receipt, all synchronously, and on the event loop that stalls every other
    request on the worker while a payment gateway is being talked to.
    """
    src = (API / "routers" / "payments.py").read_text(encoding="utf-8")
    assert "run_in_threadpool" in src
    assert "await run_in_threadpool(\n        payment_service.process_webhook" in src


def test_an_upload_route_reads_its_file_synchronously():
    """`await file.read()` in a sync route is a coroutine nobody awaits — it
    would reach the parser as a coroutine object and fail at runtime, not at
    import. Pin the spelling that goes with a sync route."""
    for name in ("banking", "branding", "debit_notes", "documents",
                 "purchase_credit_notes", "document_intelligence_v1"):
        src = (API / "routers" / f"{name}.py").read_text(encoding="utf-8")
        assert "await file.read()" not in src, (
            f"routers/{name}.py still awaits file.read() in a sync route")


def test_the_vision_paths_are_the_ones_this_protects():
    """Name the two worst, so a future reader knows what the rule is for: a
    scanned bank statement is up to twenty blocking vision calls, and an
    invoice extraction is one — both on the event loop before this."""
    for module, route in (("banking", "def upload_statement("),
                          ("document_intelligence_v1", "def extract_invoice(")):
        src = (API / "routers" / f"{module}.py").read_text(encoding="utf-8")
        assert route in src
        assert f"async {route}" not in src


_probe_app = FastAPI()


@_probe_app.post("/probe")
def _probe(file: UploadFile = File(...), note: str = Form("")):
    """A sync route reading its upload exactly as every converted one does."""
    content = file.file.read()
    return {"bytes": len(content), "head": content[:4].decode(), "note": note}


def test_a_real_multipart_upload_still_reaches_a_sync_route():
    """The doubles in the other test modules cannot prove this.

    `UploadFile.file` is a SpooledTemporaryFile, and reading it in a sync route
    is the documented way — but "documented" is not "verified", and a route
    that cannot read its own upload fails at RUNTIME rather than at import. So
    one genuine multipart POST goes through Starlette's own parsing.
    """
    res = TestClient(_probe_app).post(
        "/probe",
        files={"file": ("statement.csv", io.BytesIO(b"DATE,NARRATION,DR,CR\n"), "text/csv")},
        data={"note": "sync"})
    assert res.status_code == 200, res.text
    assert res.json() == {"bytes": 21, "head": "DATE", "note": "sync"}
