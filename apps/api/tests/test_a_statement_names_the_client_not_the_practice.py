"""The statement of account is headed by whose account it is.

WHAT WAS WRONG
    build_statement_pdf took the CA FIRM as its second argument and put
    firm.get("name") in the letterhead, and routers/customer_statements.py's
    email path sent the covering note as firm_name too.

    The customer owes money to the CLIENT. The practice is not a party to the
    debt, and a statement demanding payment under a chartered accountant's name
    misstates who is owed — to the one reader who has no way to know better,
    the client's own customer.

    Same confusion the sales-invoice PDF carried until it was split on
    2026-09-08, and it survived that fix because it is a different file. Lower
    stakes and worth saying why: this is not a Rule 46 document, it carries no
    GSTIN and claims no input credit. What it does carry is a demand for money.
"""
from __future__ import annotations

import io

import pdfplumber
import pytest

from services.statement_pdf_service import build_statement_pdf, load_account_holder


CLIENT = {"id": "CLI", "client_name": "Sharma Textiles", "legal_name": "Sharma Textiles Pvt Ltd"}
FIRM = {"id": "FIRM", "name": "Gupta & Associates, Chartered Accountants"}


def _statement() -> dict:
    return {
        "period": {"start_date": "2026-04-01", "end_date": "2026-06-30"},
        "customer": {"name": "Bharat Retail", "gstin": "27AAACB1234C1ZM",
                     "email": "ap@bharatretail.test"},
        "opening_balance_paise": 1_00_000_00,
        "transactions": [
            {"date": "2026-04-12", "particulars": "Invoice INV-001", "reference": "INV-001",
             "debit_paise": 50_000_00, "credit_paise": 0, "running_balance_paise": 1_50_000_00},
        ],
        "closing_balance_paise": 1_50_000_00,
        "totals": {"invoiced_paise": 50_000_00, "received_paise": 0, "credited_paise": 0},
    }


def _text(pdf: bytes) -> str:
    """The rendered text, not the raw bytes.

    A first draft searched pdf.decode("latin-1"). Reportlab compresses the
    content stream, so nothing matched — and the NEGATIVE assertion below
    ("the practice is not named") passed against a PDF that named it, because
    nothing at all was findable. A guard that cannot see its subject is worse
    than no guard. pdfplumber is what tests/test_sales_invoice_pdf_supplier.py
    already uses for the same reason.
    """
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


def test_the_extractor_can_actually_see_the_text():
    """Vacuity guard for the guard. Without this, every negative assertion in
    this file is satisfied by an unreadable PDF."""
    pdf = build_statement_pdf(_statement(), CLIENT, _statement()["customer"])
    body = _text(pdf)
    assert "Customer Statement of Account" in body
    assert "Bharat Retail" in body


def test_the_letterhead_is_the_client():
    pdf = build_statement_pdf(_statement(), CLIENT, _statement()["customer"])
    assert "Sharma Textiles Pvt Ltd" in _text(pdf)


def test_the_letterhead_is_not_the_practice():
    """The negative half, and the one that matters: naming the client is right
    only if the practice is gone."""
    pdf = build_statement_pdf(_statement(), CLIENT, _statement()["customer"])
    body = _text(pdf)
    assert "Gupta & Associates" not in body
    assert "Chartered Accountants" not in body


def test_the_legal_name_wins_over_the_trading_name():
    """A demand for money should carry the name the client is registered under."""
    pdf = build_statement_pdf(
        _statement(),
        {"client_name": "Sharma Textiles", "legal_name": "Sharma Textiles Pvt Ltd",
         "trade_name": "SharmaTex"},
        _statement()["customer"])
    body = _text(pdf)
    assert "Sharma Textiles Pvt Ltd" in body and "SharmaTex" not in body


def test_a_client_with_only_a_display_name_still_renders():
    """A blank letterhead is the one outcome worse than a wrong name."""
    pdf = build_statement_pdf(_statement(), {"client_name": "Sharma Textiles"},
                              _statement()["customer"])
    assert "Sharma Textiles" in _text(pdf)


# ── the loader refuses rather than defaulting ───────────────────────────────

class _Row:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return _Row(self._data)


class _DB:
    def __init__(self, data):
        self._data = data

    def table(self, name):
        assert name == "clients"
        return _Q(self._data)


def test_the_loader_returns_the_firm_scoped_client():
    holder = load_account_holder(_DB(dict(CLIENT)), "FIRM", "CLI")
    assert holder["legal_name"] == "Sharma Textiles Pvt Ltd"


def test_a_missing_client_is_refused_not_replaced_by_the_firm():
    """Falling back to the firm is exactly what produced the defect. A missing
    client row is a question, not a letterhead."""
    with pytest.raises(ValueError, match="whose account it is"):
        load_account_holder(_DB(None), "FIRM", "CLI")


def test_the_download_path_renders_the_client_end_to_end(monkeypatch):
    """The one that catches the ORIGINAL defect.

    Calling build_statement_pdf directly with a client dict cannot catch it —
    the bug was in the CALLER, which passed _load_firm(firm_id). So this drives
    get_customer_statement_pdf, which is what the download endpoint calls, and
    asserts on what comes out the other end.
    """
    from services import statement_pdf_service as sps

    class _CustQ:
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def maybe_single(self): return self
        def execute(self): return _Row(dict(CLIENT))

    class _StubDB:
        def table(self, name):
            assert name == "clients"
            return _CustQ()

    monkeypatch.setattr(sps.customer_statement_service, "generate",
                        lambda db, f, c, cu, s_, e: _statement())
    # If anything still reaches for the firm on this path, fail loudly rather
    # than rendering the wrong name.
    monkeypatch.setattr(sps, "_load_firm",
                        lambda *_a, **_k: pytest.fail("the statement must not load the firm"),
                        raising=False)

    pdf, filename = sps.get_customer_statement_pdf(
        _StubDB(), "FIRM", "CLI", "CUST", "2026-04-01", "2026-06-30")
    body = _text(pdf)
    assert "Sharma Textiles Pvt Ltd" in body
    assert "Gupta & Associates" not in body
    assert filename.startswith("statement-bharat-retail-")


def test_the_pdf_path_no_longer_loads_the_firm_at_all():
    """The import is the tell. While _load_firm was still reached from this
    module, the wrong party was one line away from coming back."""
    import inspect

    from services import statement_pdf_service as sps

    src = inspect.getsource(sps)
    body = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "_load_firm(" not in body, (
        "statement_pdf_service must not resolve the firm — the account holder "
        "is the client and is passed in"
    )


def test_the_email_path_names_the_client_too():
    """The covering note said 'from <CA firm>' beside a PDF that now says the
    client. Two names for one creditor is worse than either alone."""
    import inspect

    from routers import customer_statements

    src = inspect.getsource(customer_statements.email_statement)
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "load_account_holder" in code
    assert "_load_firm" not in code
    assert "firm_name=holder_name" in code
