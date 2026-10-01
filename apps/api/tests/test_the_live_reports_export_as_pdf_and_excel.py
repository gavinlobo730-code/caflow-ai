"""The live reports leave the product as a PDF or a spreadsheet, and the file is
the screen (accounting-16).

WHAT WAS MISSING

    A CA hands the ledger, the trial balance, the cash flow statement and the
    ageing to a bank or an auditor. Server PDFs existed only for the year-end
    pack, the bank reconciliation, a customer statement, an invoice and a
    payslip; every other report left through the browser's print dialog, and
    cash flow could be exported as a CSV and nothing else.

WHAT THIS HOLDS

    1. THE FILE IS THE SCREEN. Each export's totals are the figures the
       screen's own report function returns, read back out of the finished
       PDF and spreadsheet — not re-derived in the test.
    2. THE FIRM IS NAMED, AND ITS GSTIN IS FOUND WHICHEVER COLUMN HOLDS IT.
       `public.firms` carries it in two columns and only one is ever written.
    3. A SPREADSHEET'S MONEY IS A NUMBER, exact to the paisa, and the number
       format is the browser exports' own string, pinned from this side.
    4. A LEDGER THAT DOES NOT FOOT IS REFUSED, and a read that came back short
       is a refusal rather than a wrong ledger. The paged read is exercised
       with more lines than one page holds.
    5. NO REPORT IS READ A SECOND WAY: each fetcher calls the function the
       screen's endpoint calls, and reads no ledger table itself.
    6. THE DOOR: scope, permission, a refusal in words, and a file that
       travels with its name.
"""
from __future__ import annotations

import ast
import io
import re
from decimal import Decimal
from pathlib import Path

import pytest

from domain.money_text import rupees_paise
from domain.reporting import (
    Account, InMemoryLedgerSource, JournalEntry, JournalLine, ReportingService,
)
from domain.reporting import export_builders as B
from domain.reporting.export_document import ExportRefused
from services import pdf_style
from services import report_export_service as ex

API = Path(__file__).resolve().parents[1]
WEB = API.parents[1] / "apps" / "web"

FIRM, CLIENT = "firm-exp", "client-exp"
START, END = "2026-04-01", "2027-03-31"

ACCOUNTS = [
    Account("bank", "1000", "Bank - HDFC", "Asset", "Bank", system_key="bank"),
    Account("ar", "1100", "Trade Receivables", "Asset", "Receivable", system_key="ar"),
    Account("rev", "4000", "Sales", "Revenue"),
    Account("cap", "3000", "Capital", "Equity", "Capital"),
]


def je(jid, date, lines, *, ref=None, narration=None):
    return JournalEntry(
        id=jid, entry_date=date, client_id=CLIENT, firm_id=FIRM, entry_type="x",
        lines=tuple(JournalLine(*ln) for ln in lines), created_at=f"{date}T00:00:00",
        reference_no=ref or f"INV/{jid}", narration=narration or f"Sale {jid}")


def books():
    """A ledger with figures that exercise Indian grouping (12,34,567.50) and a
    paisa that a float would lose (0.29)."""
    return [
        je("ob", "2026-03-02", [("bank", 5_000_000, 0), ("cap", 0, 5_000_000)]),
        je("e1", "2026-04-10", [("ar", 123_456_750, 0), ("rev", 0, 123_456_750)]),
        je("e2", "2026-05-11", [("ar", 29, 0), ("rev", 0, 29)]),
        je("e3", "2026-06-12", [("bank", 50_000_000, 0), ("ar", 0, 50_000_000)]),
    ]


def svc_for(entries):
    return ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=list(entries)))


class _Q:
    """A query that HONOURS its projection. A fake that returns the whole row
    whatever `.select()` asked for cannot tell a read that names both GSTIN
    columns from one that names only the first — which is exactly the defect
    `domain/firm/identity` records, so the fake must not hide it."""

    def __init__(self, data):
        self._raw, self._cols = data, None

    def select(self, cols="*", *a, **k):
        self._cols = None if cols.strip() == "*" else {c.strip() for c in cols.split(",")}
        return self

    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def maybe_single(self): return self

    @property
    def data(self):
        def project(row):
            if not isinstance(row, dict) or self._cols is None:
                return row
            return {k: v for k, v in row.items() if k in self._cols}
        if isinstance(self._raw, list):
            return [project(r) for r in self._raw]
        return project(self._raw)

    def execute(self):
        return self


class FakeDB:
    """Just the two rows a letterhead reads. `gstin` is empty and the number is
    in the LEGACY column — the row a firm saved before 17-09-2026 has."""

    def __init__(self, firm=None, holder=None):
        self.firm = firm if firm is not None else {
            "id": FIRM, "name": "Sharma & Co.", "gstin": None, "gst_number": "27AABCS1429B1ZU"}
        self.holder = holder if holder is not None else {
            "id": CLIENT, "client_name": "Acme", "legal_name": "Acme Traders Pvt Ltd",
            "gstin": "27AAACA1111A1Z4", "pan": "AAACA1111A"}

    def table(self, name):
        return _Q([self.firm] if name == "firms" else self.holder)


def export(report, fmt, svc=None, db=None, **params):
    return ex.export_report(
        report, fmt, svc=svc or svc_for(books()), db=db or FakeDB(), firm_id=FIRM,
        client_id=CLIENT, params=params, generated_on="2026-10-01")


def pdf_text(content: bytes) -> str:
    pdfplumber = pytest.importorskip("pdfplumber")
    with pdfplumber.open(io.BytesIO(content)) as doc:
        return "\n".join((p.extract_text() or "") for p in doc.pages)


def workbook(content: bytes):
    from openpyxl import load_workbook
    return load_workbook(io.BytesIO(content))


# ── 1. THE FILE IS THE SCREEN ────────────────────────────────────────────────

def test_a_ledger_pdf_carries_the_screens_figures_and_names_the_firm_and_client():
    svc = svc_for(books())
    # What the screen shows: the very function its endpoint calls.
    screen = svc.ledger(FIRM, CLIENT, "ar", START, END, limit=1000, offset=0)
    out = export("ledger", "pdf", svc=svc, account_id="ar", start_date=START, end_date=END)
    text = pdf_text(out.content)

    assert out.media_type == "application/pdf"
    assert out.filename == "ledger-trade-receivables-2026-04-01-2027-03-31.pdf"
    assert "Sharma & Co." in text and "Acme Traders Pvt Ltd" in text
    assert "Trade Receivables (1100)" in text
    # The screen's four headline figures, in the document's own grouping.
    assert f"{rupees_paise(screen['total_debit_paise'])}" in text      # 12,34,567.79
    assert f"{rupees_paise(screen['total_credit_paise'])}" in text      # 5,00,000.00
    assert f"{rupees_paise(screen['closing_balance_paise'])} Dr" in text
    assert f"{rupees_paise(screen['opening_balance_paise'])} Dr" in text
    # Indian grouping, never Western: 12,34,567.50 and not 1,234,567.50.
    assert "12,34,567.50" in text and "1,234,567.50" not in text


def test_the_firms_gstin_is_found_in_whichever_column_holds_it():
    """`firms.gstin` is NULL here and the number is in `gst_number`, which is
    where a firm that saved its profile before 17-09-2026 has it. A reader that
    looks at one column prints a letterhead with no GSTIN on it."""
    out = export("trial-balance", "pdf", as_of_date=END)
    assert "GSTIN 27AABCS1429B1ZU" in pdf_text(out.content)

    both_empty = export("trial-balance", "pdf", as_of_date=END,
                        db=FakeDB(firm={"id": FIRM, "name": "Sharma & Co.",
                                        "gstin": "", "gst_number": None}))
    assert "27AABCS1429B1ZU" not in pdf_text(both_empty.content)
    assert "Sharma & Co." in pdf_text(both_empty.content)


def test_a_trial_balance_pdf_carries_the_screens_totals_in_both_forms():
    svc = svc_for(books())
    inception = svc.trial_balance(FIRM, CLIENT, END, basis="accrual")
    out = export("trial-balance", "pdf", svc=svc, as_of_date=END)
    text = pdf_text(out.content)
    assert rupees_paise(inception["total_debit_paise"]) in text
    assert "The trial balance balances" in text

    periodic = svc.trial_balance(FIRM, CLIENT, END, basis="accrual", start_date=START)
    out = export("trial-balance", "pdf", svc=svc, as_of_date=END, start_date=START)
    text = pdf_text(out.content)
    assert "Opening Dr" in text and "Closing Cr" in text
    assert rupees_paise(periodic["total_debit_paise"]) in text
    pdfplumber = pytest.importorskip("pdfplumber")
    with pdfplumber.open(io.BytesIO(out.content)) as doc:
        page = doc.pages[0]
        assert page.width > page.height, "eight money columns want the width"


def test_a_cash_flow_pdf_and_sheet_carry_the_screens_figures():
    svc = svc_for(books())
    screen = svc.cash_flow_statement(FIRM, CLIENT, START, END, basis="accrual")
    pdf = export("cash-flow", "pdf", svc=svc, start_date=START, end_date=END)
    text = pdf_text(pdf.content)
    assert rupees_paise(screen["closing_cash_paise"]) in text
    assert rupees_paise(screen["net_change_paise"]) in text
    assert "AS-3" in text

    xlsx = export("cash-flow", "xlsx", svc=svc, start_date=START, end_date=END)
    wb = workbook(xlsx.content)
    ws = wb["Cash Flow"]
    by_label = {row[0].value: row[1].value for row in ws.iter_rows(min_row=2)
                if row[0].value}
    closing = by_label["Cash and bank at the end of the period"]
    assert Decimal(str(closing)) == Decimal(screen["closing_cash_paise"]) / 100
    net = by_label["Net increase / (decrease) in cash and bank"]
    assert Decimal(str(net)) == Decimal(screen["net_change_paise"]) / 100
    assert xlsx.filename == "cash-flow-2026-04-01-to-2027-03-31.xlsx"


def test_an_ageing_pdf_is_the_screens_report():
    from services import customer_statement_service as css

    ageing = {
        "as_of": "2026-10-01",
        "buckets": {"not_due": 0, "0-30": 0, "31-60": 1_000_000, "61-90": 0, "90+": 250_050},
        "total_outstanding_paise": 1_250_050,
        "invoices": [
            {"invoice_id": "i1", "invoice_no": "INV/001", "customer_name": "Beta Ltd",
             "invoice_date": "2026-07-01", "outstanding_paise": 250_050,
             "days_overdue": 92, "aging_bucket": "90+"},
            {"invoice_id": "i2", "invoice_no": "INV/002", "customer_name": "Gamma & Sons",
             "invoice_date": "2026-08-10", "outstanding_paise": 1_000_000,
             "days_overdue": 45, "aging_bucket": "31-60"},
        ],
        "advances": [{"document_no": "RCT/9", "party_name": "Beta Ltd",
                      "document_date": "2026-09-01", "unapplied_paise": 100_000,
                      "days_old": 30, "aging_bucket": "0-30"}],
        "total_advances_paise": 100_000, "net_receivable_paise": 1_150_050,
        "advance_gaps": ["Receipt RCT/9: the stored unapplied balance differs."],
    }

    class StubService:
        def ar_aging(self, db, firm_id, client_id, as_of=None):
            assert (firm_id, client_id) == (FIRM, CLIENT)
            return ageing

    css_original = css.customer_statement_service
    css.customer_statement_service = StubService()
    try:
        out = export("ar-ageing", "pdf", as_of="2026-10-01")
    finally:
        css.customer_statement_service = css_original
    text = pdf_text(out.content)
    assert "Accounts Receivable Ageing" in text
    assert "12,500.50" in text                          # the total, the screen's figure
    assert "Net receivable" in text and "11,500.50" in text
    # The longest-open document first, as the screen sorts it.
    assert text.index("INV/001") < text.index("INV/002")
    assert "Receipt RCT/9: the stored unapplied balance differs." in text


def test_an_ageing_whose_rows_do_not_add_to_its_total_is_refused():
    bad = {"as_of": "2026-10-01",
           "buckets": {"not_due": 0, "0-30": 100, "31-60": 0, "61-90": 0, "90+": 0},
           "total_outstanding_paise": 100,
           "invoices": [{"invoice_no": "X", "customer_name": "Y", "invoice_date": "2026-09-01",
                         "outstanding_paise": 90, "days_overdue": 10, "aging_bucket": "0-30"}]}
    with pytest.raises(ExportRefused, match="do not add to its total"):
        B.ageing_document(bad, payable=False)


# ── 2. A SPREADSHEET'S MONEY IS A NUMBER ─────────────────────────────────────

def test_a_ledger_sheets_money_is_a_number_exact_to_the_paisa():
    svc = svc_for(books())
    screen = svc.ledger(FIRM, CLIENT, "ar", START, END, limit=1000, offset=0)
    out = export("ledger", "xlsx", svc=svc, account_id="ar", start_date=START, end_date=END)
    ws = workbook(out.content)["Trade Receivables"]
    header = [c.value for c in ws[1]]
    assert header[:5] == ["Date", "Particulars", "Ref", "Debit", "Credit"]
    assert header[5] == "Balance (Dr +, Cr -)"
    assert ws.freeze_panes == "A2"

    debit_col = header.index("Debit") + 1
    cells = [ws.cell(row=r, column=debit_col) for r in range(2, ws.max_row + 1)]
    numeric = [c for c in cells if c.value is not None]
    # Every figure is a number Excel's SUM can add, not text.
    assert numeric and all(c.data_type == "n" for c in numeric)
    assert all(c.number_format == "[>=10000000]##\\,##\\,##\\,##0.00;"
                                  "[>=100000]##\\,##\\,##0.00;##,##0.00" for c in numeric)
    # Σ of the debit column, the total row included once more, is the report's.
    lines = [c for c in cells[1:-2] if c.value is not None]       # drop opening, total, closing
    assert sum(Decimal(str(c.value)) for c in lines) * 100 == screen["total_debit_paise"]
    # 0.29 rupees survives: a float division would have written 0.28999999999999998.
    assert any(Decimal(str(c.value)) == Decimal("0.29") for c in lines)
    # A balance keeps its sign: the closing figure is the report's, debit-positive.
    last_balance = ws.cell(row=ws.max_row, column=6).value
    assert Decimal(str(last_balance)) * 100 == screen["closing_balance_paise"]


def test_the_number_format_is_the_browser_exports_own_string():
    """`lib/export/xlsx.ts` holds `INR_FORMAT` for the exports the browser makes.
    Pinned from THIS side: a guard in apps/web would assert the browser against
    a copy of itself."""
    from services.report_xlsx_service import INR_FORMAT
    src = (WEB / "lib" / "export" / "xlsx.ts").read_text()
    m = re.search(r"export const INR_FORMAT\s*=\s*\n?\s*'((?:[^'\\]|\\.)*)'", src)
    assert m, "INR_FORMAT is no longer a single-quoted literal in lib/export/xlsx.ts"
    assert m.group(1).replace("\\\\", "\\") == INR_FORMAT


def test_the_letterhead_is_on_a_sheet_of_its_own_so_data_sheets_start_at_row_one():
    out = export("ledger", "xlsx", account_id="ar", start_date=START, end_date=END)
    wb = workbook(out.content)
    assert wb.sheetnames == ["Trade Receivables", "Details"]
    details = {r[0].value: r[1].value for r in wb["Details"].iter_rows() if r[0].value}
    assert details["Prepared by"] == "Sharma & Co."
    assert details["Practice GSTIN"] == "27AABCS1429B1ZU"
    assert details["Client"] == "Acme Traders Pvt Ltd"
    assert wb["Trade Receivables"]["A1"].value == "Date"


# ── 3. A LEDGER THAT DOES NOT FOOT IS REFUSED ────────────────────────────────

class PagedStub:
    """Behaves like `public.account_ledger_page`: every page carries the whole
    window's totals, and `total_lines` is what the pager counts against."""

    def __init__(self, n, *, short_after=None):
        self.n, self.short_after, self.calls = n, short_after, []
        self.lines, bal = [], 0
        for i in range(n):
            bal += 100 + i
            self.lines.append({"entry_id": f"e{i}", "entry_date": "2026-04-01",
                               "reference_no": f"R{i}", "narration": f"n{i}",
                               "debit_paise": 100 + i, "credit_paise": 0,
                               "running_balance_paise": bal})
        self.closing = bal
        self.total_debit = sum(ln["debit_paise"] for ln in self.lines)

    def ledger(self, firm_id, client_id, account_id, start, end, limit=None, offset=0):
        self.calls.append((limit, offset))
        page = self.lines[offset: offset + limit]
        if self.short_after is not None and offset >= self.short_after:
            page = []
        return {"account_id": account_id, "account_code": "1100",
                "account_name": "Trade Receivables", "account_type": "Asset",
                "start_date": start, "end_date": end, "opening_balance_paise": 0,
                "closing_balance_paise": self.closing, "total_debit_paise": self.total_debit,
                "total_credit_paise": 0, "lines": page, "total_lines": self.n,
                "limit": limit, "offset": offset}


def test_a_ledger_longer_than_one_page_is_read_to_its_last_line():
    stub = PagedStub(2350)
    led = ex.fetch_ledger(stub, FIRM, CLIENT, "ar", START, END, ceiling=10_000)
    assert len(led["lines"]) == 2350
    assert stub.calls == [(1000, 0), (1000, 1000), (1000, 2000)]
    doc = B.ledger_document(led)                 # foots, so it is not refused
    assert len(doc.tables[0].rows) == 2350 + 3   # opening, total, closing


def test_a_read_that_comes_back_short_is_a_refusal_not_a_wrong_ledger():
    stub = PagedStub(2350, short_after=1000)
    led = ex.fetch_ledger(stub, FIRM, CLIENT, "ar", START, END, ceiling=10_000)
    assert len(led["lines"]) == 1000
    with pytest.raises(ExportRefused, match="not printed"):
        B.ledger_document(led)


def test_a_ledger_over_the_ceiling_is_refused_in_words_before_it_is_read_whole():
    stub = PagedStub(3000)
    with pytest.raises(ExportRefused, match=r"3,000 lines.*limited to 2,000"):
        ex.fetch_ledger(stub, FIRM, CLIENT, "ar", START, END, ceiling=2_000)
    assert stub.calls == [(1000, 0)], "refused after ONE page, not after reading them all"


def test_a_ledger_whose_balances_disagree_is_not_printed():
    base = PagedStub(3).ledger(FIRM, CLIENT, "ar", START, END, limit=1000)
    wrong_close = {**base, "closing_balance_paise": base["closing_balance_paise"] + 1}
    with pytest.raises(ExportRefused, match="do not agree"):
        B.ledger_document(wrong_close)
    wrong_total = {**base, "total_debit_paise": base["total_debit_paise"] - 1}
    with pytest.raises(ExportRefused, match="do not add up"):
        B.ledger_document(wrong_total)


def test_an_account_the_client_does_not_have_is_refused_not_printed_blank():
    with pytest.raises(ExportRefused, match="not in this client's chart"):
        export("ledger", "pdf", account_id="no-such-account", start_date=START, end_date=END)


def test_a_missing_client_is_a_refusal_not_somebody_elses_letterhead():
    class NoClient(FakeDB):
        def table(self, name):
            return _Q([self.firm] if name == "firms" else None)

    with pytest.raises(ExportRefused, match="not found"):
        export("trial-balance", "pdf", db=NoClient(), as_of_date=END)


def test_a_format_a_report_does_not_offer_is_refused_in_words():
    with pytest.raises(ExportRefused, match="XLSX button on the Reports tab"):
        export("trial-balance", "xlsx", as_of_date=END)
    with pytest.raises(ExportRefused, match="pdf only"):
        export("ar-ageing", "xlsx")


# ── 4. THE PDF IS IN THE PRODUCT'S STYLE AND IS STABLE ───────────────────────

def _fills(content: bytes) -> set[str]:
    pdfplumber = pytest.importorskip("pdfplumber")
    got = set()
    with pdfplumber.open(io.BytesIO(content)) as doc:
        for page in doc.pages:
            for rect in page.rects:
                v = rect.get("non_stroking_color")
                if isinstance(v, (int, float)):
                    v = (v, v, v)
                if v and len(v) >= 3:
                    got.add("#" + "".join(f"{round(c * 255):02X}" for c in v[:3]))
    return got


def test_the_report_is_painted_in_the_products_palette_and_not_the_old_one():
    out = export("ledger", "pdf", account_id="ar", start_date=START, end_date=END)
    fills = _fills(out.content)
    assert pdf_style.INK in fills, f"the header is not ps.ink; the page paints {sorted(fills)}"
    assert pdf_style.MUTED in fills, "the opening, total and closing rows are not the muted band"
    for old in ("#1F2937", "#0F172A", "#1A3C5E", "#1A1A1A"):
        assert old not in fills, f"{old} is back"


def test_two_identical_renders_are_byte_identical_so_a_comparison_means_something(monkeypatch):
    """The headline tests above read text, not bytes; this is the PREMISE that
    would let a future one compare bytes. ReportLab stamps a creation date and a
    document id on every render, so `rl_config.invariant` pins both."""
    import reportlab.rl_config as rl
    monkeypatch.setattr(rl, "invariant", 1)
    a = export("trial-balance", "pdf", as_of_date=END).content
    b = export("trial-balance", "pdf", as_of_date=END).content
    assert a == b


def test_a_long_ledger_repeats_its_header_and_numbers_its_pages():
    stub = PagedStub(300)
    led = ex.fetch_ledger(stub, FIRM, CLIENT, "ar", START, END, ceiling=10_000)
    from services.report_pdf_service import build_report_pdf
    pdf = build_report_pdf(B.ledger_document(led), holder=FakeDB().holder, firm=FakeDB().firm,
                           generated_on="2026-10-01")
    pdfplumber = pytest.importorskip("pdfplumber")
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        assert len(doc.pages) > 1
        with_rows = 0
        for i, page in enumerate(doc.pages, start=1):
            text = page.extract_text() or ""
            assert f"Page {i} of {len(doc.pages)}" in text
            if re.search(r"\bR\d+\b", text):          # a page that carries ledger lines
                with_rows += 1
                assert "Particulars" in text, f"page {i} lost its column headings"
        assert with_rows > 1, "the table never split, so this proved nothing"


def test_no_rupee_sign_reaches_a_page_or_a_sheet_cell_as_text():
    out = export("ledger", "pdf", account_id="ar", start_date=START, end_date=END)
    assert "₹" not in pdf_text(out.content)
    assert "Amounts in INR" in pdf_text(out.content)


# ── 5. NO REPORT IS READ A SECOND WAY ────────────────────────────────────────

def _called_names(path: Path) -> set[str]:
    return {n.func.attr for n in ast.walk(ast.parse(path.read_text()))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


def test_each_export_calls_the_function_the_screens_endpoint_calls():
    """The five calls, by name, in BOTH files: the export service and the router
    each screen's endpoint lives in. If the screen's report is renamed this
    fails, which is the point — the export would otherwise keep calling a
    function the screen no longer does."""
    export_calls = _called_names(API / "services" / "report_export_service.py")
    screen_calls = (_called_names(API / "routers" / "accounting.py")
                    | _called_names(API / "routers" / "customers.py")
                    | _called_names(API / "routers" / "vendors.py"))
    for name in ("ledger", "trial_balance", "cash_flow_statement", "ar_aging", "ap_aging"):
        assert name in export_calls, f"the export no longer calls {name}"
        assert name in screen_calls, f"no screen endpoint calls {name} any more"


def test_the_export_reads_no_ledger_table_itself():
    """A fetcher that did its own `.table("journal_lines")` would be a second
    reader that could disagree with the screen, and the unbounded kind
    CLAUDE.md's reporting rule forbids."""
    src = (API / "services" / "report_export_service.py").read_text()
    tables = set(re.findall(r"""\.table\(\s*["']([a-z_]+)["']""", src))
    assert tables == {"firms"}, (
        f"the export reads {sorted(tables)} directly; only the practice's own "
        "row (for the letterhead) is read here — the books come from the report "
        "functions")


def test_the_scope_is_the_screens_scope():
    src = (API / "routers" / "report_exports.py").read_text()
    assert "_reporting_service(current_user)" in src, (
        "the report must be built from the caller's own scope, as the screen's is")
    assert "assert_client_access(current_user, client_id)" in src


def test_the_pdf_service_is_named_so_the_one_style_guards_scan_it():
    """`test_one_pdf_style_and_every_document_shares_it` and the two-page guard
    find PDF services by glob; a renderer outside the glob is a palette nobody
    checks."""
    names = {p.name for p in (API / "services").glob("*_pdf_service.py")}
    assert "report_pdf_service.py" in names


# ── 6. THE DOOR ──────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException            # noqa: E402
from fastapi.testclient import TestClient              # noqa: E402

import routers.report_exports as door                  # noqa: E402
from core.auth import get_current_user                 # noqa: E402

PARTNER = {"id": "u1", "firm_id": FIRM, "role": "Partner", "email": "p@f.test",
           "auth_user_id": "auth-1"}
REVIEWER = {**PARTNER, "id": "u2", "role": "Reviewer"}


def _http(monkeypatch, user=PARTNER, *, db=object()):
    app = FastAPI()
    app.include_router(door.router)
    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(door, "_prod_db", lambda: db)
    return TestClient(app, raise_server_exceptions=False)


def test_a_file_travels_with_its_name_and_the_callers_own_firm(monkeypatch):
    seen = {}

    def fake(report, fmt, **kw):
        seen.update(report=report, fmt=fmt, **kw)
        return ex.ExportedFile(b"%PDF-1.4 stub", "ledger-x.pdf", "application/pdf")

    monkeypatch.setattr(door.exports, "export_report", fake)
    r = _http(monkeypatch).get(
        "/api/report-exports/ledger",
        params={"client_id": CLIENT, "account_id": "ar", "start_date": START,
                "end_date": END})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="ledger-x.pdf"'
    assert r.content == b"%PDF-1.4 stub"
    # The firm is the CALLER's, never a parameter.
    assert seen["firm_id"] == FIRM and seen["client_id"] == CLIENT
    assert seen["report"] == "ledger" and seen["fmt"] == "pdf"
    assert seen["params"]["account_id"] == "ar" and seen["params"]["start_date"] == START


def test_a_refusal_reaches_the_ca_in_words(monkeypatch):
    def fake(*a, **kw):
        raise ExportRefused("This ledger has 9,999 lines in the period.")

    monkeypatch.setattr(door.exports, "export_report", fake)
    r = _http(monkeypatch).get("/api/report-exports/ledger",
                               params={"client_id": CLIENT, "account_id": "ar"})
    assert r.status_code == 422
    assert "9,999 lines" in r.json()["detail"]


def test_a_client_outside_the_callers_scope_is_refused_before_anything_is_read(monkeypatch):
    def deny(user, client_id):
        raise HTTPException(status_code=404, detail="Not found")

    called = []
    monkeypatch.setattr(door, "assert_client_access", deny)
    monkeypatch.setattr(door.exports, "export_report", lambda *a, **k: called.append(1))
    r = _http(monkeypatch).get("/api/report-exports/cash-flow", params={"client_id": "theirs"})
    assert r.status_code == 404 and not called


def test_a_role_without_accounting_read_cannot_export(monkeypatch):
    r = _http(monkeypatch, REVIEWER).get("/api/report-exports/cash-flow",
                                         params={"client_id": CLIENT})
    assert r.status_code == 403


def test_no_database_is_a_503_not_an_empty_pdf(monkeypatch):
    r = _http(monkeypatch, db=None).get("/api/report-exports/cash-flow",
                                        params={"client_id": CLIENT})
    assert r.status_code == 503
    assert "database" in r.json()["detail"]


def test_a_client_is_required_and_a_date_must_be_a_date(monkeypatch):
    http = _http(monkeypatch)
    assert http.get("/api/report-exports/cash-flow").status_code == 422
    r = http.get("/api/report-exports/cash-flow",
                 params={"client_id": CLIENT, "start_date": "01/04/2026"})
    assert r.status_code == 422
    assert http.get("/api/report-exports/not-a-report",
                    params={"client_id": CLIENT}).status_code == 422


def test_an_unoffered_format_is_a_422_through_the_real_service(monkeypatch):
    r = _http(monkeypatch).get("/api/report-exports/trial-balance",
                               params={"client_id": CLIENT, "format": "xlsx"})
    assert r.status_code == 422
    assert "XLSX button" in r.json()["detail"]


def test_the_router_is_mounted_behind_the_client_guard():
    from main import app
    paths = {r.path for r in app.routes}
    assert "/api/report-exports/{report}" in paths
    src = (API / "main.py").read_text()
    assert re.search(r"include_router\(report_exports_router,\s*dependencies=_CLIENT_GUARD\)", src)
