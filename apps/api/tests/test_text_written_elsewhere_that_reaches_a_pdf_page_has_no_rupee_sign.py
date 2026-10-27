"""Text written elsewhere that ends on a PDF page carries no rupee sign, because the page cannot draw one.

WHAT WENT WRONG (27-10-2026, found by independent reads of the sweep that put "₹" into the sentences a CA reads)

    ReportLab's core fonts are WinAnsiEncoding and have no glyph for U+20B9: the sign is encoded as a ZapfDingbats "n" and
    prints as a black box ("■10,000.00"). That shipped twice, so `tests/test_no_pdf_renders_the_rupee_sign.py` fails any
    PDF service whose OWN source holds the sign, and the services write "Rs." into their format strings. What that cannot see is
    text WRITTEN ELSEWHERE that a service prints: a sentence a domain module words for a screen (a gap, a caveat, a stored note)
    and text a person typed (a narration, an adjustment's reason, a party's name). The sweep that turned "1000000 paise" into
    "₹10,000.00" sent the sign onto two pages a CA hands out, the year-end pack's notes and the receivables and payables ageing
    report's notes; and the second review found the other half, that a plain string in a TABLE cell never passes through a
    paragraph at all, so the same typed narration read "Rs. 500" when it was long enough to wrap into a paragraph and printed a
    black box when it was short (and had always done, in the bank reconciliation, the statement, the year-end adjustments
    register and the reports).

    So the boundary is the two flowables that carry text: every PDF service builds its paragraphs through
    `services/pdf_style.Paragraph` and its tables through `services/pdf_style.Table`, which write the sign they cannot draw as
    "Rs. " in a paragraph and "Rs." in a cell, wherever the text came from. Not covered, because they cannot carry such text: the
    page furniture draws only "Page N of M", and the document's title and author metadata are never drawn.

WHAT IS HELD
    * (the rule) no PDF service imports reportlab's own `Paragraph` or `Table`: read from the import statements, so a parenthesised
      multi-line import and an aliased one are seen;
    * (the classes) each replaces the sign in a string and leaves other markup, other cells and any non-string alone, and the
      unmodified reportlab classes are shown to put a ZapfDingbats glyph on a page for the same text, so the assertions below are
      about the defect and not about a detector that sees nothing;
    * (the pages) the ageing report (a sentence in its notes and a short narration in a cell), the year-end notes PDF and the
      customer statement (a typed particulars cell and a typed name) each render a ₹-bearing text with no ZapfDingbats glyph.
      The complete pack and the bank reconciliation build their text through the same two classes and are held by the rule above,
      not rendered here.
"""
import ast
import io
import pathlib

import pytest
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph as ReportlabParagraph, SimpleDocTemplate, Table as ReportlabTable

from domain.money_sentence import rupee_text
from services import pdf_style

SERVICES = pathlib.Path(__file__).resolve().parents[1] / "services"
SIGN = "₹"
OWN = {"Paragraph", "Table"}


def _pdf_services():
    return sorted(SERVICES.glob("*pdf*.py"))


def _glyph_fallback(pdf: bytes) -> bool:
    """True when the page asked for the font reportlab falls back to for a character the core fonts lack."""
    return b"ZapfDingbats" in pdf


def _extract(pdf: bytes) -> str:
    pdfplumber = pytest.importorskip("pdfplumber")
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return "\n".join((p.extract_text() or "") for p in doc.pages)


def _build(*flowables) -> bytes:
    buf = io.BytesIO()
    SimpleDocTemplate(buf).build(list(flowables))
    return buf.getvalue()


def reportlab_names_imported(source: str) -> list[str]:
    """Each `Paragraph` / `Table` a module imports from reportlab, by the statement's own AST, aliases included."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("reportlab"):
            for alias in node.names:
                if alias.name in OWN:
                    found.append(f"{node.module}.{alias.name}")
    return found


# ── the rule ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_scan_still_finds_the_pdf_services():
    names = {p.name for p in _pdf_services()}
    for expected in ("report_pdf_service.py", "year_end_pdf_service.py", "statement_pdf_service.py",
                     "bank_reconciliation_pdf_service.py", "payslip_pdf_service.py", "invoice_pdf_service.py"):
        assert expected in names, expected


def test_no_pdf_service_imports_reportlabs_own_paragraph_or_table():
    offenders = {}
    for path in _pdf_services():
        if path.name == "pdf_style.py":
            continue                                   # the one module that defines the classes and so imports reportlab's
        names = reportlab_names_imported(path.read_text())
        if names:
            offenders[path.name] = names
    assert not offenders, (
        "a PDF service builds text with reportlab's own flowable, so a rupee sign written elsewhere prints as a black box: "
        f"{offenders}. Import Paragraph and Table from services.pdf_style.")


def test_every_service_that_builds_either_takes_it_from_the_page_module():
    for path in _pdf_services():
        if path.name == "pdf_style.py":
            continue
        src = path.read_text()
        tree = ast.parse(src)
        for name in OWN:
            if f"{name}(" in src:
                taken = any(isinstance(n, ast.ImportFrom) and n.module == "services.pdf_style"
                            and any(a.name == name for a in n.names) for n in ast.walk(tree))
                assert taken or f"pdf_style.{name}(" in src, f"{path.name} builds a {name} that does not come from pdf_style"


@pytest.mark.parametrize("source,expected", [
    ("from reportlab.platypus import Paragraph", ["reportlab.platypus.Paragraph"]),
    ("from reportlab.platypus import (\n    Spacer,\n    Paragraph,\n)", ["reportlab.platypus.Paragraph"]),
    ("from reportlab.platypus import Table as T", ["reportlab.platypus.Table"]),
    ("from reportlab.platypus.paragraph import Paragraph", ["reportlab.platypus.paragraph.Paragraph"]),
    ("from reportlab.platypus import Spacer, TableStyle, ParagraphStyle", []),
    ("from services.pdf_style import Paragraph, Table", []),
])
def test_the_detector_reads_every_spelling_of_the_import(source, expected):
    assert reportlab_names_imported(source) == expected


# ── the classes ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_unmodified_classes_really_do_put_the_glyph_fallback_on_the_page():
    """The control: without this the assertions below could pass because the detector sees nothing."""
    style = getSampleStyleSheet()["Normal"]
    assert _glyph_fallback(_build(ReportlabParagraph(f"short by {SIGN}10,000.00", style)))
    assert _glyph_fallback(_build(ReportlabTable([[f"paid {SIGN}500"]])))
    assert not _glyph_fallback(_build(ReportlabParagraph("short by Rs. 10,000.00", style)))


def test_the_page_paragraph_writes_the_sign_it_cannot_draw_as_rs():
    style = getSampleStyleSheet()["Normal"]
    pdf = _build(pdf_style.Paragraph(f"short by {SIGN}10,000.00 and {rupee_text(-5_000_00)}", style))
    assert not _glyph_fallback(pdf)
    text = _extract(pdf)
    assert "Rs. 10,000.00" in text and "minus Rs. 5,000.00" in text, text


def test_the_page_table_writes_the_sign_in_a_plain_cell_and_leaves_flowables_and_numbers_alone():
    style = getSampleStyleSheet()["Normal"]
    paragraph = pdf_style.Paragraph(f"boxed {SIGN}7", style)
    table = pdf_style.Table([["Particulars", f"Paid {SIGN}500 to vendor"], [paragraph, 12]])
    pdf = _build(table)
    assert not _glyph_fallback(pdf)
    text = _extract(pdf)
    assert "Paid Rs.500 to vendor" in text and "boxed Rs. 7" in text and "12" in text, text
    assert table._cellvalues[1][1] == 12, "a number is not turned into a string"


def test_it_leaves_other_markup_alone():
    para = pdf_style.Paragraph("<b>bold</b> text", getSampleStyleSheet()["Normal"])
    assert "bold" in para.text and "Rs." not in para.text


# ── the pages ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_ageing_report_prints_the_advances_gaps_and_a_short_typed_cell_without_the_sign():
    from datetime import date

    from domain.reporting.export_builders import ageing_document
    from domain.reporting.export_document import Column, ReportDocument, Row, TEXT, Table as DocTable
    from domain.reporting.party_advances import AdvanceInput, unapplied_advances
    from services.report_pdf_service import build_report_pdf

    pos = unapplied_advances(
        [AdvanceInput(document_id="r1", document_no="RCPT-1", party_id="p1", party_name="Acme", document_date="2026-06-01",
                      settlement_paise=10_000, unallocated_paise=-5_000, allocated_paise=15_000)],
        today=date(2026, 10, 1), document_label="receipt")
    assert pos.gaps and SIGN in pos.gaps[0], "the sentence under test must carry the sign, or this proves nothing"
    doc = ageing_document({"invoices": [], "total_outstanding_paise": 0, "buckets": {}, "advance_gaps": pos.gaps,
                           "as_of": "2026-10-01"}, payable=False)
    pdf = build_report_pdf(doc, holder={"client_name": "Acme"}, firm={"name": "Firm"}, generated_on="2026-10-01")
    assert not _glyph_fallback(pdf)
    assert "minus Rs. 50.00" in _extract(pdf)

    # A short narration stays a plain-string cell (a long one becomes a paragraph), so the two paths are both held.
    narration = ReportDocument(
        report_id="x", title="Ledger", subject="", period="", notes=(),
        tables=(DocTable(columns=(Column("d", "Particulars", TEXT, 2.0),), rows=(Row(cells=(f"Paid {SIGN}500 to vendor",)),)),))
    pdf = build_report_pdf(narration, holder={"client_name": "Acme"}, firm={"name": "Firm"}, generated_on="2026-10-01")
    assert not _glyph_fallback(pdf)
    assert "Paid Rs.500 to vendor" in _extract(pdf)


def test_the_year_end_notes_pdf_prints_a_stored_sentence_without_the_sign():
    from services import year_end_pdf_service as pdf_service
    note = {"title": "Share Capital", "sequence_no": 1, "content": f"This note shows {SIGN}10,000.00 more than the balance sheet.",
            "note_data": {}}
    pdf = pdf_service.generate_notes_pdf({"client_name": "Acme Pvt Ltd", "financial_year": "2025-26", "status": "draft"}, [note])
    assert not _glyph_fallback(pdf)
    assert "Rs. 10,000.00 more than the balance sheet" in _extract(pdf)


def test_the_customer_statement_prints_a_typed_particulars_cell_and_a_typed_name_without_the_sign():
    from services.statement_pdf_service import build_statement_pdf

    statement = {
        "period": {"start_date": "2026-04-01", "end_date": "2026-06-30"},
        "customer": {"name": f"Bharat {SIGN} Retail", "gstin": "27AAACB1234C1ZM", "email": "ap@bharatretail.test"},
        "opening_balance_paise": 1_00_000_00,
        "transactions": [{"date": "2026-04-12", "particulars": f"Receipt {SIGN}500 advance", "reference": "UTR1",
                          "debit_paise": 50_000_00, "credit_paise": 0, "running_balance_paise": 1_50_000_00}],
        "closing_balance_paise": 1_50_000_00,
        "totals": {"invoiced_paise": 50_000_00, "received_paise": 0, "credited_paise": 0},
    }
    client = {"id": "CLI", "client_name": "Sharma Textiles", "legal_name": "Sharma Textiles Pvt Ltd"}
    pdf = build_statement_pdf(statement, client, statement["customer"])
    assert not _glyph_fallback(pdf)
    text = _extract(pdf)
    assert "Receipt Rs.500 advance" in text and "Bharat Rs. Retail" in text, text
