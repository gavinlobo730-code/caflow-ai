"""A document's number takes its financial year from the DOCUMENT, not the clock.

SALES-24, and the sweep it turned out to be. Thirteen modules carried a private
`_current_fy()` / `_current_fy_long()`, each reading
`datetime.now(timezone.utc)`, and six of them built a document NUMBER out of it
— `RCPT-{fy}-0001`, `CN-{fy}-…`, `DN-{fy}-…`, `SDN-{fy}-…`, `PCN-{fy}-…`,
`VPMT-{fy}-…` — while the document's own date sat on the line above.

Year-end is when a CA keys the most documents. Every March-dated receipt
entered in April was numbered `RCPT-2627-…`, into NEXT year's series, and sat
out of order in the year it belongs to. The CA finds out when the year's
receipt register is printed and the numbers do not run. The FY-lock and period
checks used the document date correctly all along; only the number was wrong.

TWO DEFECTS ON ONE LINE, and the second is the reason core.ist_clock exists:
`datetime.now(timezone.utc)` is still on 31 March between 00:00 and 05:30 IST
on 1 April, so even a document dated today was numbered into the old year for
five and a half hours each April.

The timeline events had the same shape and are fixed the same way — an event
about a document belongs in the document's financial year. Where there is
genuinely no document date (a vendor or customer record, a report's default
range) `ist_fy_label()` with no argument is the right answer, and still fixes
the IST half.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]


# ── the behaviour ────────────────────────────────────────────────────────────

def test_a_march_receipt_is_numbered_into_the_year_it_belongs_to():
    """The finding's own probe. It returned RCPT-2627-0001 for a 31 March
    receipt; 31 March 2026 is FY 2025-26."""
    import services.receipt_service as rs

    r = rs.create_receipt_core(
        "firm-1",
        {"client_id": "client-1", "customer_id": "cust-1",
         "receipt_date": "2026-03-31", "amount_paise": 100000,
         "payment_mode": "bank", "allocations": []},
        {"id": "u1", "firm_id": "firm-1", "role": "Partner"}, None)
    assert r["receipt_no"].startswith("RCPT-2526-"), (
        f"{r['receipt_no']} for a receipt dated {r['receipt_date']} — a March "
        f"document numbered into next year's series")


def test_the_first_of_april_is_the_new_year():
    """The other side of the boundary, and the one the UTC clock got wrong for
    five and a half hours a year."""
    import services.receipt_service as rs

    r = rs.create_receipt_core(
        "firm-1",
        {"client_id": "client-1", "customer_id": "cust-1",
         "receipt_date": "2026-04-01", "amount_paise": 100000,
         "payment_mode": "bank", "allocations": []},
        {"id": "u1", "firm_id": "firm-1", "role": "Partner"}, None)
    assert r["receipt_no"].startswith("RCPT-2627-"), r["receipt_no"]


@pytest.mark.parametrize("iso,code", [
    ("2026-03-31", "2526"), ("2026-04-01", "2627"), ("2027-03-31", "2627"),
    ("2025-12-31", "2526"), ("2026-01-01", "2526"),
])
def test_fy_code_is_the_indian_financial_year(iso, code):
    from core.ist_clock import fy_code
    assert fy_code(iso) == code


def test_fy_code_and_the_label_cannot_disagree():
    """`fy_code` is DERIVED from `ist_fy_label` rather than computed again —
    two spellings of one financial year, and only one rule."""
    from datetime import date, timedelta
    from core.ist_clock import fy_code, ist_fy_label

    d = date(2025, 1, 1)
    while d < date(2028, 1, 1):
        label = ist_fy_label(d)                 # '2026-27'
        assert fy_code(d) == f"{label[2:4]}{label[5:7]}", d
        d += timedelta(days=1)


def test_the_helpers_take_the_string_the_database_returns():
    """Every document date in this codebase arrives as an ISO string, from
    PostgREST or a request body. A helper that only took a `date` would be a
    helper callers had to convert for — and forgetting is how the clock came to
    be read instead of the document."""
    from datetime import date, datetime, timezone
    from core.ist_clock import fy_code, ist_fy_label

    assert fy_code("2026-03-31") == fy_code(date(2026, 3, 31))
    assert fy_code("2026-03-31T18:30:00+00:00") == "2526"
    assert ist_fy_label("2026-03-31") == "2025-26"
    assert ist_fy_label(datetime(2026, 3, 31, tzinfo=timezone.utc)) == "2025-26"


# ── the rule, as code ────────────────────────────────────────────────────────

def _code(path: Path) -> str:
    """Comments and docstrings stripped. Both appear below, and a guard whose
    subject is code has to be given code — this project has read its own prose
    as a violation four times now."""
    src = path.read_text()
    src = re.sub(r"#[^\n]*", "", src)
    return re.sub(r'("""|\'\'\')[\s\S]*?\1', "", src)


_SCANNED = sorted(
    [p for p in (API_ROOT / "routers").glob("*.py")]
    + [p for p in (API_ROOT / "services").glob("*.py")]
)


def test_no_module_keeps_a_private_financial_year_helper():
    """THE RULE, not a spelling of it. `core.ist_clock` is the one place that
    knows what a financial year is; thirteen private copies is how six of them
    came to be wrong in the same way at the same time, and how nobody noticed.

    `services/compliance_obligation_service.py` keeps its own — it is the
    module ist_clock's own docstring names as the origin, it is about an
    OBLIGATION PERIOD rather than a document, and it is exempted by name here
    rather than by the check being loosened.
    """
    EXEMPT = {"compliance_obligation_service.py"}
    offenders = []
    for p in _SCANNED:
        if p.name in EXEMPT:
            continue
        if re.search(r"^def _current_fy(_long)?\(", _code(p), re.M):
            offenders.append(p.name)
    assert not offenders, (
        f"private financial-year helpers are back in {offenders}. Use "
        f"core.ist_clock.fy_code(document_date) for a document NUMBER and "
        f"core.ist_clock.ist_fy_label(date) for a label — a copy is free to "
        f"read the clock instead of the document, which is what SALES-24 was.")


def test_every_document_number_asks_for_a_date():
    """`fy_code()` with no argument is today, which is exactly the defect. Any
    module that builds a document number must PASS the document's date.

    Found by parsing, not by regex: an `ast` walk finds every call to `fy_code`
    and checks it carries an argument, so a new call site cannot slip in with a
    spelling this file did not anticipate."""
    bare = []
    for p in _SCANNED:
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:                      # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "fy_code"
                    and not node.args and not node.keywords):
                bare.append(f"{p.name}:{node.lineno}")
    assert not bare, (
        f"fy_code() called with no date at {bare} — that is today's financial "
        f"year on a document that has its own. A March document keyed in April "
        f"lands in next year's series.")


def test_the_six_numbering_modules_number_from_the_document():
    """Named individually, because each is a series a CA reads in order and
    each was wrong. The assertion is on the CALL — `fy_code(<something>)` — so
    it survives a rename of the local variable but not a return to the clock."""
    MODULES = {
        "services/receipt_service.py":            "RCPT",
        "services/purchase_payment_service.py":   "VPMT",
        "routers/purchase_payments.py":           "VPMT",
        "routers/credit_notes.py":                "CN",
        "routers/debit_notes.py":                 "DN",
        "routers/sales_debit_notes.py":           "SDN",
        "routers/purchase_credit_notes.py":       "PCN",
    }
    for rel, prefix in MODULES.items():
        code = _code(API_ROOT / rel)
        assert re.search(r"fy_code\(\s*\w", code), (
            f"{rel} builds {prefix}-numbers and no longer derives the "
            f"financial year from a date")
        assert not re.search(r"datetime\.now\([^)]*\)\s*\n?\s*if .*month", code), (
            f"{rel} is computing a financial year off the clock again")
