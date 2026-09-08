"""The payslip is headed by who employs the person reading it.

WHAT WAS WRONG
    build_payslip_pdf took the CA FIRM as its fourth argument and put
    `firm.get("name")` in the letterhead. Both callers passed `_load_firm(...)`,
    and `run["client_id"]` — the employer — was selected from the database and
    thrown away.

    So an employee of Acme Manufacturing received a payslip stating that their
    employer was the accountancy practice that keeps Acme's books. §192 makes
    the person "responsible for paying" the salary the deductor, and that is the
    client. This is the document with the widest readership in the whole
    product: every employee of every client gets one every month, and it is what
    they show a bank for a loan, a landlord for a tenancy, and a new employer as
    proof of what they earned.

    Same defect as the customer statement (fixed 2026-09-08) and the sales
    invoice before it, in a third file. Three files, one confusion: the firm is
    who operates the software, never who the document is from.
"""
from __future__ import annotations

import io

import pdfplumber
import pytest

from services.payslip_pdf_service import build_payslip_pdf, load_employer


EMPLOYER = {"id": "CLI", "client_name": "Acme Manufacturing",
            "legal_name": "Acme Manufacturing Private Limited"}
PRACTICE = {"id": "FIRM", "name": "Gupta & Associates, Chartered Accountants"}

SLIP = {"id": "S1", "month": 7, "year": 2026, "gross_paise": 50_000_00,
        "basic_paise": 25_000_00, "hra_paise": 12_500_00,
        "pf_employee_paise": 1_800_00, "esi_employee_paise": 0,
        "pt_paise": 200_00, "tds_paise": 1_950_00, "net_paise": 46_050_00,
        "working_days": 26, "days_present": 26, "lop_days": 0}
EMPLOYEE = {"name": "Asha Kumar", "pan": "ABCPK1234F",
            "designation": "Fitter", "department": "Assembly"}
RUN = {"month": "2026-07", "firm_id": "FIRM", "client_id": "CLI"}


def _text(pdf: bytes) -> str:
    """The rendered text, not the raw bytes — reportlab compresses the content
    stream, so a `.decode("latin-1")` search finds nothing and the NEGATIVE
    assertion below would pass against a PDF that names the practice."""
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


class _Row:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, row):
        self._row = row
        self.filters: dict = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self.filters[k] = v
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return _Row(self._row)


class _DB:
    def __init__(self, row):
        self._row = row
        self.q: _Q | None = None

    def table(self, name):
        assert name == "clients", f"the payslip must read the employer, not {name}"
        self.q = _Q(self._row)
        return self.q


# ── the renderer ────────────────────────────────────────────────────────────

def test_the_letterhead_is_the_employer():
    body = _text(build_payslip_pdf(SLIP, EMPLOYEE, RUN, EMPLOYER))
    assert "Acme Manufacturing Private Limited" in body
    # The vacuity guard: if pdfplumber returned nothing the negative assertion
    # below would pass against a payslip that named the practice.
    assert "Asha Kumar" in body, "nothing was extracted from the PDF at all"


def test_the_practice_is_not_named_anywhere_on_it():
    body = _text(build_payslip_pdf(SLIP, EMPLOYEE, RUN, EMPLOYER))
    assert "Gupta & Associates" not in body
    assert "Chartered Accountants" not in body


def test_a_firms_row_still_renders_rather_than_going_blank():
    """`name` is the shape a firms row uses, and it is kept as the last
    fallback: a caller that has not been converted renders a wrong name rather
    than an empty letterhead, which is the one outcome worse. load_employer is
    what stops that path being reachable in the product."""
    body = _text(build_payslip_pdf(SLIP, EMPLOYEE, RUN, {"name": "Some Employer Ltd"}))
    assert "Some Employer Ltd" in body


def test_the_legal_name_wins_over_the_trading_name():
    """The same order the customer statement uses, so one client is named the
    same way on every document that leaves the platform."""
    body = _text(build_payslip_pdf(
        SLIP, EMPLOYEE, RUN,
        {"client_name": "Acme", "trade_name": "Acme Works",
         "legal_name": "Acme Manufacturing Private Limited"}))
    assert "Acme Manufacturing Private Limited" in body
    assert "Acme Works" not in body


# ── the loader ──────────────────────────────────────────────────────────────

def test_the_employer_is_read_from_clients_and_is_firm_scoped(monkeypatch):
    from services import payslip_pdf_service as pps
    db = _DB(dict(EMPLOYER))
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    got = load_employer("FIRM", "CLI")
    assert got["legal_name"] == "Acme Manufacturing Private Limited"
    assert db.q is not None
    assert db.q.filters == {"id": "CLI", "firm_id": "FIRM"}, (
        "an unscoped read would let one firm's payslip name another firm's client")
    assert pps is not None


def test_a_missing_client_is_refused_not_replaced_by_the_practice(monkeypatch):
    """Falling back to the firm is exactly what produced the defect. A missing
    client row is a question, not a letterhead."""
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: _DB(None))
    with pytest.raises(ValueError, match="who the employer is"):
        load_employer("FIRM", "CLI")


def test_a_run_with_no_client_is_refused_before_any_query():
    """`run["client_id"]` was selected and discarded for months. If it is ever
    absent the answer is a refusal, not the firm."""
    with pytest.raises(ValueError, match="which employer issued"):
        load_employer("FIRM", None)


def test_the_payslip_path_no_longer_loads_the_firm_at_all():
    """The import is the tell. While _load_firm was still reachable from this
    module, the wrong party was one line away from coming back."""
    import inspect

    from services import payslip_pdf_service as pps

    src = inspect.getsource(pps)
    body = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "_load_firm" not in body, (
        "payslip_pdf_service must not resolve the firm — the employer is the "
        "client the run belongs to"
    )
    assert 'table("firms")' not in body
