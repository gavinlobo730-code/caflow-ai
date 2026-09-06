"""
Reading a SCANNED statement with a vision model — and the arithmetic that is the
only reason it is allowed to.

CSV and XLSX are parsed deterministically. A text PDF is parsed from real
characters at real coordinates. This path is a model looking at pixels, and it
will sometimes read 8 as 3 or drop a row at a page break. For an invoice that is
tolerable, because a human checks the six fields it produced. For a statement it
is not: nobody reads 300 lines to check them.

So on this path the tie-out is MANDATORY, it is enforced BEFORE anything is
rasterised or sent, and a reading that does not add up to the printed closing
balance is refused rather than imported. Most of what follows is that rule and
the ways round it that must not exist.

No network anywhere. The model is injected, so the real prompt, the real
parsing and the real refusals are all exercised against fabricated replies.
"""
from __future__ import annotations

import io
import json

import pytest
from fastapi import HTTPException

import routers.banking as banking
import routers.customers as cust
import routers.vendors as ven
import services.opening_balance_service as obs
import services.statement_vision as statement_vision
from domain.banking import vision
from domain.banking.normalizer import StatementParseError
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-VIS"
CLIENT = "CLI-VIS"
CALLER = {"firm_id": FIRM, "id": "u-int-1", "auth_user_id": "u1",
          "email": "ca@firm.test", "role": "Partner"}

_ROWS = [
    {"date": "01/04/2026", "description": "UPI ACME TRADERS", "reference": "R1",
     "debit": "", "credit": "50,000.00", "balance": "1,50,000.00"},
    {"date": "02/04/2026", "description": "NEFT SUPPLIER LTD", "reference": "R2",
     "debit": "20,000.00", "credit": "", "balance": "1,30,000.00"},
]


class _Model:
    """A fake vision model that counts how often it was actually called."""
    def __init__(self, reply=None, raises=None):
        self.reply = json.dumps(_ROWS) if reply is None else reply
        self.raises = raises
        self.calls = 0

    def __call__(self, *, image, mime, prompt):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.reply if isinstance(self.reply, str) else self.reply[self.calls - 1]


# ══════════════════════════════════════════════════════════════════════════════
# Reading the model's reply
# ══════════════════════════════════════════════════════════════════════════════

def test_it_parses_amounts_with_the_same_code_every_csv_row_uses():
    """The model is asked to copy what is printed, commas and all. Turning
    "1,50,000.00" into paise is _to_paise's job — the function every CSV and
    XLSX cell already goes through — so a date format or a Dr/Cr suffix is
    understood in ONE place rather than two."""
    txns = vision.read_statement([b"page"], call_model=_Model())
    assert [(t.debit_paise, t.credit_paise) for t in txns] == [
        (0, 50_000_00), (20_000_00, 0)]
    assert [t.balance_paise for t in txns] == [1_50_000_00, 1_30_000_00]
    assert [t.transaction_date for t in txns] == ["2026-04-01", "2026-04-02"]


def test_a_debit_written_with_a_dr_suffix_is_still_a_debit():
    model = _Model(json.dumps([
        {"date": "01/04/2026", "description": "CHQ", "debit": "1,000.00 Dr",
         "credit": "", "balance": "9,000.00"}]))
    txns = vision.read_statement([b"p"], call_model=model)
    assert (txns[0].debit_paise, txns[0].credit_paise) == (1_000_00, 0)


def test_a_fenced_reply_is_still_read():
    """Models wrap JSON in ``` more often than not."""
    model = _Model("```json\n" + json.dumps(_ROWS) + "\n```")
    assert len(vision.read_statement([b"p"], call_model=model)) == 2


@pytest.mark.parametrize("reply", [
    "I'm sorry, I can't read this image.",
    "",
    "{\"rows\": []}",
    "[not json at all",
])
def test_a_reply_that_is_not_a_row_array_is_refused_not_salvaged(reply):
    """A partial reading that then fails the tie-out is harder to act on than a
    clear "it could not read this"."""
    with pytest.raises(StatementParseError) as e:
        vision.read_statement([b"p"], call_model=_Model(reply))
    assert "could not be read" in str(e.value).lower()


def test_rows_that_are_not_transactions_are_dropped():
    """Sub-headings, wrapped continuation lines and anything with no money."""
    model = _Model(json.dumps([
        {"date": "", "description": "OPENING BALANCE", "debit": "", "credit": "",
         "balance": "1,00,000.00"},
        {"date": "01/04/2026", "description": "", "debit": "", "credit": "1.00"},
        {"date": "01/04/2026", "description": "A SUB HEADING", "debit": "",
         "credit": "", "balance": ""},
        {"date": "01/04/2026", "description": "REAL ONE", "debit": "", "credit": "5.00"},
    ]))
    txns = vision.read_statement([b"p"], call_model=model)
    assert [t.description for t in txns] == ["REAL ONE"]


def test_pages_are_read_in_order_and_concatenated():
    model = _Model([
        json.dumps([_ROWS[0]]),
        json.dumps([_ROWS[1]]),
    ])
    txns = vision.read_statement([b"p1", b"p2"], call_model=model)
    assert model.calls == 2
    assert [t.description for t in txns] == ["UPI ACME TRADERS", "NEFT SUPPLIER LTD"]


def test_a_provider_failure_names_the_page_and_not_the_provider():
    """Which vendor and model this uses is an internal detail and is not
    actionable for a CA — the same rule document_intelligence_v1 follows."""
    model = _Model(raises=RuntimeError("gemini-3.5-flash quota exceeded for project 42"))
    with pytest.raises(StatementParseError) as e:
        vision.read_statement([b"p1"], call_model=model)
    said = str(e.value)
    assert "page 1" in said
    assert "gemini" not in said.lower() and "quota" not in said.lower()


def test_reading_nothing_at_all_is_a_refusal_with_advice():
    with pytest.raises(StatementParseError) as e:
        vision.read_statement([b"p"], call_model=_Model("[]"))
    assert "no transactions" in str(e.value).lower()
    assert "csv" in str(e.value).lower()


def test_an_empty_page_list_is_refused():
    with pytest.raises(StatementParseError):
        vision.read_statement([], call_model=_Model())


# ══════════════════════════════════════════════════════════════════════════════
# Rasterising, and the page cap
# ══════════════════════════════════════════════════════════════════════════════

def _pdf(html: str) -> bytes:
    from xhtml2pdf import pisa
    buf = io.BytesIO()
    pisa.CreatePDF(io.StringIO(html), dest=buf)
    return buf.getvalue()


def _blank_pdf(pages: int) -> bytes:
    body = '<div style="page-break-after: always">.</div>' * pages
    return _pdf(f"<html><body>{body}</body></html>")


def test_pages_become_images():
    images = vision.page_images(_blank_pdf(2))
    assert len(images) == 2
    assert all(im.startswith(b"\x89PNG") for im in images), "not PNG bytes"


def test_too_many_pages_is_refused_with_the_count():
    """A whole year exported as one scan is a large bill the CA never agreed to.
    It is refused BEFORE any page is sent, and the message says how many."""
    many = vision.MAX_PAGES + 2
    with pytest.raises(StatementParseError) as e:
        vision.page_images(_blank_pdf(many))
    assert str(many) in str(e.value)
    assert str(vision.MAX_PAGES) in str(e.value)


def test_a_truncated_pdf_is_a_parse_error_not_a_crash():
    with pytest.raises(StatementParseError) as e:
        vision.page_images(b"%PDF-1.4")
    assert "could not be opened" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════════
# The endpoint — where the mandatory tie-out is enforced
# ══════════════════════════════════════════════════════════════════════════════

def _setup(monkeypatch, *, model=None, available=True):
    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    wire_e2e(monkeypatch, db, [banking, cust, ven, obs])
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM,
                        "financial_year_start": "2026-04-01"})
    seed_standard_coa(db, FIRM, CLIENT)
    model = model or _Model()
    monkeypatch.setattr(statement_vision, "call", model)
    monkeypatch.setattr(statement_vision, "available", lambda: available)
    return db, model


class _Upload:
    def __init__(self, filename, content):
        self.filename, self._content = filename, content

    async def read(self):
        return self._content


def _upload(**kw):
    import asyncio
    return asyncio.run(banking.upload_statement(
        file=_Upload(kw.pop("filename"), kw.pop("content")),
        client_id=CLIENT, bank_name="HDFC Bank", account_number=None,
        bank_account_id=None, column_mapping=None, save_mapping=False,
        opening_balance_paise=kw.pop("opening", None),
        closing_balance_paise=kw.pop("closing", None),
        allow_vision=kw.pop("allow_vision", False),
        current_user=CALLER))


SCAN = property(lambda self: None)


def _scan_pdf() -> bytes:
    """A PDF with no extractable text — what a scan looks like to the parser."""
    return _blank_pdf(1)


def test_a_scan_without_asking_for_ai_is_refused_and_says_how(monkeypatch):
    db, model = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf())
    assert e.value.status_code == 422
    assert "scan" in str(e.value.detail).lower()
    assert "opening and closing balances" in str(e.value.detail)
    assert model.calls == 0, "a model was called without being asked for"


def test_asking_for_ai_without_the_balances_is_refused_BEFORE_spending(monkeypatch):
    """The refusal has to come before rasterising and before the model, or it is
    the same refusal, later and dearer."""
    db, model = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True)
    assert e.value.status_code == 422
    assert "proves every line was read" in str(e.value.detail)
    assert model.calls == 0, "it spent money and then refused"


def test_an_unconfigured_deployment_refuses_before_rasterising(monkeypatch):
    db, model = _setup(monkeypatch, available=False)
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True,
                opening=1_00_000_00, closing=1_30_000_00)
    assert "not configured" in str(e.value.detail)
    assert model.calls == 0


def test_a_scan_that_ties_out_imports_and_says_a_model_read_it(monkeypatch):
    db, model = _setup(monkeypatch)
    res = _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True,
                  opening=1_00_000_00, closing=1_30_000_00)
    assert model.calls == 1
    assert res["data"]["tie_out"]["agrees"] is True
    assert res["data"]["read_with_ai"] is True, \
        "a CA reviewing these lines is entitled to know they came off a picture"
    assert db.rows("bank_transactions")
    assert db.rows("bank_statements")[0]["source_format"] == "pdf-scan"


def test_a_scan_that_does_NOT_tie_out_imports_nothing(monkeypatch):
    """The whole control. The model was confident and wrong; the arithmetic is
    what decides."""
    db, model = _setup(monkeypatch)
    with pytest.raises(HTTPException) as e:
        _upload(filename="scan.pdf", content=_scan_pdf(), allow_vision=True,
                opening=1_00_000_00, closing=9_99_999_00)
    assert e.value.status_code == 422
    assert "does not add up" in str(e.value.detail)
    assert not db.rows("bank_transactions"), "a refused scan wrote transactions"
    assert not db.rows("bank_statements")


def test_a_photograph_is_read_and_recorded_as_an_image(monkeypatch):
    db, model = _setup(monkeypatch)
    res = _upload(filename="statement.jpg", content=b"\xff\xd8\xff-not-really-a-jpeg",
                  allow_vision=True, opening=1_00_000_00, closing=1_30_000_00)
    assert model.calls == 1
    assert res["data"]["read_with_ai"] is True
    assert db.rows("bank_statements")[0]["source_format"] == "image"


def test_a_TEXT_pdf_is_never_sent_to_the_model_even_when_ai_is_allowed(monkeypatch):
    """THE ORDERING RULE. A parse from real characters beats a reading of pixels
    and costs nothing, so the deterministic parsers run first and always."""
    db, model = _setup(monkeypatch)
    head = ("<tr><td>Date</td><td>Narration</td><td>Value Dt</td><td>Chq/Ref No</td>"
            "<td>Withdrawal Amt.</td><td>Deposit Amt.</td><td>Closing Balance</td></tr>")
    rows = ("<tr><td>01/04/2026</td><td>UPI ACME TRADERS</td><td>01/04/2026</td>"
            "<td>REF1</td><td></td><td>50000.00</td><td>150000.00</td></tr>"
            "<tr><td>02/04/2026</td><td>NEFT SUPPLIER LTD</td><td>02/04/2026</td>"
            "<td>REF2</td><td>20000.00</td><td></td><td>130000.00</td></tr>")
    res = _upload(filename="stmt.pdf",
                  content=_pdf(f'<html><body><table border="1">{head}{rows}</table></body></html>'),
                  allow_vision=True, opening=1_00_000_00, closing=1_30_000_00)
    assert model.calls == 0, "a readable PDF was sent to a model anyway"
    assert res["data"]["read_with_ai"] is False
    assert db.rows("bank_statements")[0]["source_format"] == "pdf"


def test_a_broken_csv_is_not_rescued_by_the_model(monkeypatch):
    """Vision is for what cannot be parsed, not for what parsed badly. A
    malformed CSV is a malformed CSV and a picture will not help."""
    db, model = _setup(monkeypatch)
    with pytest.raises(HTTPException):
        _upload(filename="stmt.csv", content=b"nonsense,without,any,columns\n1,2,3,4\n",
                allow_vision=True, opening=1, closing=2)
    assert model.calls == 0
