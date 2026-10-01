"""
accounting-23 — a password-protected PDF statement can be opened, and the password is
used once and kept nowhere.

WHAT WAS WRONG
    Banks commonly email a statement locked with a password built from the
    customer ID or date of birth. `normalizer._pdf_rows` opened every PDF with no
    password, so such a file reached the generic `except Exception` and came back
    as "This file could not be read as a PDF. If it downloaded from net banking,
    try downloading it again" — advice that sends a CA to re-download a perfectly
    good file, and the only way past it was to unlock the PDF in another program.

WHAT THESE PIN
    * no password given → a refusal that says one is needed, with its own CODE
      (`pdf_password_required`) so the screen can ask for it;
    * a password given that does not work → a DIFFERENT refusal
      (`pdf_password_incorrect`), because "a password is needed" said to someone
      who just typed one only gets the same password typed again;
    * the right password → the statement parses to exactly what the unlocked
      file parses to, for the RC4 and AES schemes banks use;
    * a PDF locked only against copying (an owner password, no user password)
      opens with none and never asks;
    * a file that is simply not a PDF is still the generic unreadable sentence
      and carries no password code;
    * all three routes that open a statement (inspect, preview, upload) take the
      password, as a FORM field;
    * THE PASSWORD GOES NOWHERE ELSE: it is in no response body, no log record,
      no exception message, and the model is never reached for a locked file —
      stated as a rule over the source rather than a list of call sites.
"""
from __future__ import annotations

import ast
import io
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domain.banking import normalizer, vision
from domain.banking.normalizer import (
    PdfPasswordError, PdfPasswordIncorrect, PdfPasswordRequired, StatementParseError,
    inspect_statement, parse_statement,
)
from main import app

reportlab = pytest.importorskip("reportlab")
pdfplumber = pytest.importorskip("pdfplumber")

from reportlab.lib import pdfencrypt          # noqa: E402
from reportlab.lib.pagesizes import A4         # noqa: E402
from reportlab.pdfgen import canvas            # noqa: E402

API_ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "AB12cd34-9Z"          # distinctive, so a leak is findable by substring

# Cosmos-style six-column layout, ruled — the shape test_a_bank_statement_pdf_is_
# read_to_its_last_page draws, kept small: this file is about the lock, not the
# layout.
_COLUMNS = (("Date", 40.0, "left"), ("Particulars", 96.0, "left"),
            ("Cheque No", 256.0, "left"), ("Withdrawal", 390.0, "right"),
            ("Deposit", 470.0, "right"), ("Balance", 556.0, "right"))
_GRID_X = (38.0, 92.0, 252.0, 312.0, 392.0, 472.0, 558.0)
_ROWS = [
    ("01/04/2026", "NEFT FROM ACME TRADERS", "", "", "50000.00", "150000.00"),
    ("03/04/2026", "UPI/RENT/APRIL", "", "20000.00", "", "130000.00"),
    ("05/04/2026", "CHQ PAID VENDOR", "000123", "5000.00", "", "125000.00"),
]


def _draw(c) -> None:
    c.setFont("Helvetica", 8)
    y = 780.0
    rows = [tuple(label for label, _x, _a in _COLUMNS)] + _ROWS
    for row in rows:
        for (_label, x, align), text in zip(_COLUMNS, row):
            if not text:
                continue
            (c.drawRightString if align == "right" else c.drawString)(x, y, text)
        y -= 16.0
    top, bottom = 790.0, 780.0 - 16.0 * len(rows) + 6.0
    for x in _GRID_X:
        c.line(x, top, x, bottom)
    for i in range(len(rows) + 1):
        yy = top - i * 16.0
        c.line(_GRID_X[0], yy, _GRID_X[-1], yy)


def _statement_pdf(encrypt=None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, encrypt=encrypt)
    _draw(c)
    c.showPage()
    c.save()
    return buf.getvalue()


def _locked(strength: int = 128, user: str = PASSWORD) -> bytes:
    return _statement_pdf(pdfencrypt.StandardEncryption(
        user, ownerPassword="owner-only-9", canPrint=1, strength=strength))


PLAIN = _statement_pdf()


def _amounts(txns):
    return [(t.transaction_date, t.debit_paise, t.credit_paise, t.balance_paise)
            for t in txns]


# ── the three outcomes ───────────────────────────────────────────────────────

def test_the_unlocked_file_parses_so_the_comparison_below_means_something():
    assert len(parse_statement("s.pdf", PLAIN)) == 3


def test_no_password_says_one_is_needed_and_carries_a_code():
    with pytest.raises(PdfPasswordRequired) as ei:
        parse_statement("s.pdf", _locked())
    assert ei.value.code == "pdf_password_required"
    assert isinstance(ei.value, StatementParseError), (
        "it must stay a StatementParseError so every existing handler turns it "
        "into a 422")
    assert "password" in str(ei.value).lower()


def test_a_wrong_password_is_a_different_refusal_from_a_missing_one():
    with pytest.raises(PdfPasswordIncorrect) as ei:
        parse_statement("s.pdf", _locked(), pdf_password="not-the-one")
    assert ei.value.code == "pdf_password_incorrect"
    needed = str(PdfPasswordRequired(normalizer._PDF_NEEDS_PASSWORD))
    assert str(ei.value) != needed, (
        "telling someone who typed a password that one is needed only gets the "
        "same password typed again")


@pytest.mark.parametrize("strength", [40, 128])
def test_the_right_password_parses_to_what_the_unlocked_file_parses_to(strength):
    got = parse_statement("s.pdf", _locked(strength), pdf_password=PASSWORD)
    assert _amounts(got) == _amounts(parse_statement("s.pdf", PLAIN))


@pytest.mark.parametrize("algorithm", ["AES-128", "AES-256", "RC4-128"])
def test_the_schemes_a_bank_actually_uses_open(algorithm):
    """AES-128 and AES-256 are what current bank statements are locked with.
    reportlab cannot write AES-256 here (it needs a package this project does
    not carry), so these are written by pypdf, which can."""
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(PLAIN))
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(PASSWORD, algorithm=algorithm)
    out = io.BytesIO()
    writer.write(out)
    locked = out.getvalue()
    with pytest.raises(PdfPasswordRequired):
        parse_statement("s.pdf", locked)
    got = parse_statement("s.pdf", locked, pdf_password=PASSWORD)
    assert _amounts(got) == _amounts(parse_statement("s.pdf", PLAIN))


def test_a_pdf_locked_only_against_copying_never_asks():
    """An owner password and no user password: the file opens with the empty one,
    which is what a reader without a password supplies. Asking for a password
    here would block a file nothing is wrong with."""
    owner_only = _locked(user="")
    assert _amounts(parse_statement("s.pdf", owner_only)) == _amounts(
        parse_statement("s.pdf", PLAIN))


def test_an_empty_password_box_is_no_password():
    with pytest.raises(PdfPasswordRequired):
        parse_statement("s.pdf", _locked(), pdf_password="")


def test_a_password_is_not_trimmed():
    """A password may begin or end with a space; trimming it would turn the
    right one into a wrong one."""
    spaced = " " + PASSWORD + " "
    data = _locked(user=spaced)
    assert parse_statement("s.pdf", data, pdf_password=spaced)
    with pytest.raises(PdfPasswordIncorrect):
        parse_statement("s.pdf", data, pdf_password=PASSWORD)


def test_a_file_that_is_not_a_pdf_is_still_just_unreadable():
    with pytest.raises(StatementParseError) as ei:
        parse_statement("s.pdf", b"this is not a pdf at all")
    assert not isinstance(ei.value, PdfPasswordError)
    assert "could not be read as a PDF" in str(ei.value)
    # ...and a password does not turn it into a password problem.
    with pytest.raises(StatementParseError) as ei2:
        parse_statement("s.pdf", b"this is not a pdf at all", pdf_password=PASSWORD)
    assert not isinstance(ei2.value, PdfPasswordError)


def test_inspect_asks_the_same_question():
    """The column-mapping screen opens the file too."""
    locked = _locked()
    with pytest.raises(PdfPasswordRequired):
        inspect_statement("s.pdf", locked)
    info = inspect_statement("s.pdf", locked, pdf_password=PASSWORD)
    assert info["headers"][0] == "Date"


def test_a_csv_ignores_a_password():
    csv = (b"Date,Particulars,Chq,Withdrawal Amt,Deposit Amt,Closing Bal\n"
           b"01/04/2025,UPI/DR/1234/RAMESH K,,5000.00,,95000.00\n")
    assert parse_statement("s.csv", csv, pdf_password=PASSWORD)


# ── the routes ───────────────────────────────────────────────────────────────

pytestmark_routes = pytest.mark.usefixtures("dev_header_auth")
client = TestClient(app)
HEADERS = {"X-User-Role": "partner", "X-Firm-Id": "firm-001", "X-User-Id": "user-001"}
MAPPING = {"date": 0, "desc": 1, "ref": 2, "debit": 3, "credit": 4, "balance": 5}


def _post(path, pdf, **form):
    return client.post(path, headers=HEADERS,
                       files={"file": ("locked.pdf", pdf, "application/pdf")},
                       data={"client_id": "client-001", "bank_account_id": "ba-1", **form})


@pytest.mark.usefixtures("dev_header_auth")
@pytest.mark.parametrize("path,extra", [
    ("/api/banking/statements/inspect", {}),
    ("/api/banking/statements/preview", {"column_mapping": json.dumps(MAPPING)}),
    ("/api/banking/statements/upload", {}),
])
def test_every_route_that_opens_a_statement_asks_for_the_password(path, extra):
    locked = _locked()

    res = _post(path, locked, **extra)
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "pdf_password_required"
    assert "password" in detail["message"].lower()

    res = _post(path, locked, pdf_password="wrong-one", **extra)
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["code"] == "pdf_password_incorrect"

    res = _post(path, locked, pdf_password=PASSWORD, **extra)
    assert res.status_code == 200, res.text


@pytest.mark.usefixtures("dev_header_auth")
def test_an_ordinary_parse_failure_is_still_a_plain_string_detail():
    res = _post("/api/banking/statements/inspect", b"not a pdf")
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], str), (
        "only a password refusal carries a code; every other 422 keeps its shape")


@pytest.mark.usefixtures("dev_header_auth")
def test_the_password_is_in_nothing_the_server_sends_back(caplog):
    caplog.set_level(logging.DEBUG)
    bodies = []
    for pw in (None, "wrong-" + PASSWORD, PASSWORD):
        extra = {"pdf_password": pw} if pw else {}
        res = _post("/api/banking/statements/upload", _locked(), **extra)
        bodies.append(res.text)
    # a corrupt file with a password in play — the branch that logs
    res = _post("/api/banking/statements/upload", b"%PDF-1.4 truncated", pdf_password=PASSWORD)
    bodies.append(res.text)
    for body in bodies:
        assert PASSWORD not in body
    assert not any(PASSWORD in r.getMessage() for r in caplog.records), (
        "the password reached a log record")
    assert not any(PASSWORD in repr(getattr(r, "args", "")) for r in caplog.records)


def test_the_corrupt_file_branch_logs_only_the_exception_type(caplog):
    caplog.set_level(logging.WARNING, logger="caflow.banking.normalizer")
    with pytest.raises(StatementParseError):
        parse_statement("s.pdf", b"%PDF-1.4 truncated", pdf_password=PASSWORD)
    messages = [r.getMessage() for r in caplog.records]
    assert messages, "the failure should still be logged, type only"
    # exactly "<prefix>: <TypeName>" — no second colon-separated text
    assert all(m.count(":") == 1 for m in messages), messages


# ── a locked scan never reaches a model without its owner's say-so, and the
#    password never reaches one at all ────────────────────────────────────────

def _locked_scan(strength=128) -> bytes:
    """A PDF with a picture on it and no text layer, locked."""
    from PIL import Image
    img = Image.new("RGB", (200, 80), "white")
    png = io.BytesIO()
    img.save(png, format="PNG")
    png.seek(0)
    from reportlab.lib.utils import ImageReader
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, encrypt=pdfencrypt.StandardEncryption(
        PASSWORD, ownerPassword="owner-only-9", canPrint=1, strength=strength))
    c.drawImage(ImageReader(png), 50, 700, width=200, height=80)
    c.showPage()
    c.save()
    return buf.getvalue()


def test_a_locked_scan_is_rasterised_with_the_password_and_sent_as_pictures(monkeypatch):
    from routers import banking as rb
    sent: list[tuple] = []

    def call(image, mime, prompt):
        sent.append((image, mime, prompt))
        return "[]"

    monkeypatch.setattr(rb.statement_vision, "available", lambda: True)
    monkeypatch.setattr(rb.statement_vision, "call", call)

    scan = _locked_scan()
    # Without the password: refused for the password, and the model is untouched.
    with pytest.raises(PdfPasswordRequired):
        rb._read_statement_file("s.pdf", scan, None, allow_vision=True,
                                has_balances=True, pdf_password=None)
    assert sent == []

    # With it, the pages are rasterised — and only PNGs and the prompt go out.
    try:
        rb._read_statement_file("s.pdf", scan, None, allow_vision=True,
                                has_balances=True, pdf_password=PASSWORD)
    except StatementParseError:
        pass                       # the blank page has no rows; that is not the point
    assert sent, "the locked scan should have been read once the password opened it"
    for image, mime, prompt in sent:
        assert image[:8] == b"\x89PNG\r\n\x1a\n", "what leaves is a picture of a page"
        assert mime == "image/png"
        assert PASSWORD not in prompt
        assert PASSWORD.encode() not in image


def test_page_images_refuses_a_locked_file_for_its_password():
    with pytest.raises(PdfPasswordRequired):
        vision.page_images(_locked_scan())
    with pytest.raises(PdfPasswordIncorrect):
        vision.page_images(_locked_scan(), password="nope")
    assert vision.page_images(_locked_scan(), password=PASSWORD)


# ── the rule, not the call sites ─────────────────────────────────────────────

_SOURCES = ("routers/banking.py", "domain/banking/normalizer.py",
            "domain/banking/vision.py")
_NAMES = {"password", "pdf_password"}
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


def _tree(rel):
    return ast.parse((API_ROOT / rel).read_text(encoding="utf-8"))


def _mentions(node) -> bool:
    return any(isinstance(n, ast.Name) and n.id in _NAMES for n in ast.walk(node))


def _callee(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def test_the_password_is_never_an_argument_to_a_log_call_an_error_or_a_response():
    """A password that reaches a logger, an exception message, an f-string or a
    payload is a password somebody can read later. The rule is stated over every
    place those are built in the three modules that handle the file, so a
    fourth call written next month is covered the day it is written."""
    offences = []
    for rel in _SOURCES:
        for node in ast.walk(_tree(rel)):
            if isinstance(node, ast.JoinedStr) and _mentions(node):
                offences.append(f"{rel}:{node.lineno} f-string")
            if isinstance(node, ast.Call):
                name = _callee(node)
                is_log = name in _LOG_METHODS
                is_error = name.endswith(("Error", "Exception", "Required", "Incorrect")) \
                    or name in {"HTTPException", "api_response"}
                if (is_log or is_error) and any(
                        _mentions(a) for a in list(node.args) + [k.value for k in node.keywords]):
                    # `password_refusal_for(e, password)` is a FUNCTION returning an
                    # error, not an error constructor carrying the text.
                    offences.append(f"{rel}:{node.lineno} {name}(...)")
            if isinstance(node, (ast.Dict,)) and _mentions(node):
                offences.append(f"{rel}:{node.lineno} dict literal")
    assert not offences, offences


def test_the_router_hands_the_password_to_four_things_and_to_no_model():
    """The password may be a parameter and an argument to the functions that OPEN
    the file. Any other use — in particular any call into the vision model
    (`statement_vision.call`, `vision.read_statement`, `read_printed_totals`) —
    fails, because the password is for one decrypt and a model is a third party."""
    allowed = {"inspect_statement", "parse_statement_detailed", "_read_statement_file",
               "page_images"}
    tree = _tree("routers/banking.py")
    parents = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            parents[c] = p
    found = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "pdf_password":
            found += 1
            cur, call = node, None
            while cur in parents:
                cur = parents[cur]
                if isinstance(cur, ast.Call):
                    call = cur
                    break
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    break
            if call is None:
                # `if pdf_password:` style tests are fine; a bare read is not an offence
                # unless it is an assignment target elsewhere. There are none here.
                continue
            assert _callee(call) in allowed, (
                f"routers/banking.py:{node.lineno} passes pdf_password to "
                f"{_callee(call)}(...)")
    assert found >= 8, "the rule found almost nothing to check — has it gone blind?"


def test_the_password_is_a_form_field_and_never_a_query_parameter():
    """A query string is written to every access log between the browser and this
    process; a multipart body is not."""
    tree = _tree("routers/banking.py")
    seen = 0
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        args = fn.args.args + fn.args.kwonlyargs
        defaults = ([None] * (len(fn.args.args) - len(fn.args.defaults)) + list(fn.args.defaults)
                    + list(fn.args.kw_defaults))
        for a, d in zip(args, defaults):
            if a.arg == "pdf_password" and isinstance(d, ast.Call):
                seen += 1
                assert getattr(d.func, "id", "") == "Form", (
                    f"{fn.name}: pdf_password must be a Form field, not "
                    f"{getattr(d.func, 'id', '?')}")
    assert seen == 3, f"expected the three statement routes, found {seen}"


def test_the_browser_asks_on_the_codes_the_server_sends():
    """The two code strings are this side's vocabulary and the browser holds a
    copy of them for its dialog. A guard in apps/web would assert that copy
    against itself and pass whenever both drifted together, so it is pinned from
    here — the Schedule III caption lesson."""
    ts = (API_ROOT.parent / "web" / "lib" / "banking" / "pdfPassword.ts").read_text(
        encoding="utf-8")
    assert f'PDF_PASSWORD_REQUIRED = "{PdfPasswordRequired.code}"' in ts
    assert f'PDF_PASSWORD_INCORRECT = "{PdfPasswordIncorrect.code}"' in ts
    assert PdfPasswordRequired.code != PdfPasswordIncorrect.code
