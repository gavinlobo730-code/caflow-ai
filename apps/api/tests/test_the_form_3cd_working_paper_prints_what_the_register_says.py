"""POST-A-076: the Form 3CD register leaves as a printable working paper, and the paper says what the register says.

WHAT WAS WRONG
    The 44-clause register (`GET /api/income-tax/form-3cd`) had no output at all: a CA who wanted it in front of an auditor took a
    screenshot of a screen with twelve columns of nested figures. The other live reports already leave as a server-made PDF or
    spreadsheet; this one, the working paper a tax audit is built from, did not.

WHAT THIS HOLDS
    * `describe` reads any answer the way a person writes it down and invents nothing: a key under `_paise` is money in Indian
      grouping and one under `_bps` is a percentage in whole-number arithmetic, a figure under any other key is the number it is,
      a float under `_paise` is NOT dressed as money, a stored bigint that arrived as text is still the figure, and the label
      drops a unit suffix only where the unit was applied;
    * the document built from the register the SERVICE returns names every clause once, in the form's own order, with its
      heading, its answer, who answered it (the books, the CA, nobody) and its basis, and a clause nobody answered says so
      rather than printing a blank;
    * the PDF and the spreadsheet carry it: every clause number and heading is on the page, a derived figure is on the page in
      Indian grouping, the CA's recorded answer is marked as the CA's, and the working paper says it is not the portal's form
      and that nothing was filed;
    * a register too long to print is refused in words and is not cut; an empty one is refused;
    * the route builds from the very function the register's endpoint calls (`services.form_3cd_service.build`), asks
      `income_tax:read`, refuses a format it does not offer, and 503s without the database as the other report files do.
"""
from __future__ import annotations

import inspect
import io
import uuid

import pytest

from domain.income_tax import form_3cd as f3cd
from domain.reporting import form_3cd_document as doc_mod
from domain.reporting.export_document import ExportRefused
from domain.reporting.form_3cd_document import describe, form_3cd_document, percent_from_bps
from tests.e2e_harness import FakeDB

FIRM = str(uuid.uuid4())
CLIENT = str(uuid.uuid4())
FY = "2025-26"


# ── describe: any answer, as a person writes it ──────────────────────────────────────────────────────────────────────────────

def test_a_word_is_itself_and_true_and_false_are_yes_and_no():
    assert describe("fifo") == ["fifo"]
    assert describe(True) == ["Yes"] and describe(False) == ["No"]
    assert describe(None) == ["Not stated"]


def test_a_figure_is_money_only_under_a_key_that_says_so():
    assert describe({"remaining_amount_paise": 12_34_567_50}) == ["Remaining amount: 12,34,567.50"]
    assert describe({"loss_paise": -150}) == ["Loss: -1.50"]
    # A bare count is the number it is: it is never given a unit it was not stored with.
    assert describe({"challans_read": 2}) == ["Challans read: 2"]
    assert describe(1_00_000) == ["100000"]


def test_a_stored_bigint_that_arrived_as_text_is_still_the_figure():
    assert describe({"tds_paise": "250000"}) == ["TDS: 2,500.00"]


def test_a_float_under_a_paise_key_is_not_dressed_as_money():
    # Money is never a float; one found here is a defect elsewhere and is printed as it is, under its own key.
    assert describe({"tds_paise": 12.5}) == ["TDS paise: 12.5"]


def test_an_abbreviation_in_a_key_is_written_in_capitals_and_other_words_are_not():
    assert describe({"tan": "MUMB12345A", "total_tds_deducted_paise": 100}) == ["TAN: MUMB12345A", "Total TDS deducted: 1.00"]
    assert describe({"gst_registration_status": "registered"}) == ["GST registration status: registered"]


def test_a_rate_in_basis_points_is_a_percentage_in_whole_number_arithmetic():
    assert percent_from_bps(675) == "6.75%" and percent_from_bps(5) == "0.05%" and percent_from_bps(-50) == "-0.50%"
    assert describe({"stock_to_turnover_bps": 1250}) == ["Stock to turnover: 12.50%"]


def test_a_list_is_a_line_per_entry_and_a_record_is_one_line_of_pairs():
    assert describe(["a", "b"]) == ["- a", "- b"]
    losses = [{"loss_type": "business", "assessment_year": "2024-25", "remaining_amount_paise": 5_00_000_00}]
    assert describe(losses) == ["- Loss type: business; Assessment year: 2024-25; Remaining amount: 5,00,000.00"]


def test_nesting_is_indented_and_an_empty_thing_says_so():
    lines = describe({"blocks": [{"name": "Plant", "rows": [1, 2]}], "gaps": [], "extra": {}})
    assert lines[0] == "Blocks:"
    assert lines[1].lstrip(" ") == "-" and lines[1].startswith(" ")
    assert any(l.lstrip(" ") == "Name: Plant" for l in lines)
    assert lines[-2:] == ["Gaps: No entries.", "Extra: No entries."]
    assert describe([]) == ["No entries."] and describe({}) == ["No entries."]


# ── the document, built from the register the SERVICE returns ───────────────────────────────────────────────────────────────

def _seed_books(db: FakeDB) -> None:
    db.seed("clients", {"id": CLIENT, "firm_id": FIRM, "client_name": "Mehta Traders", "legal_name": "Mehta Traders Private Limited",
                        "gstin": "27AAAAA0000A1Z5", "pan": "AAAAA0000A", "inventory_costing_method": "fifo"})
    db.seed("firms", {"id": FIRM, "name": "Rao and Associates", "gstin": None, "gst_number": None})
    db.seed("client_statutory_identity", {"firm_id": FIRM, "client_id": CLIENT, "tan": "MUMB12345A"})
    db.seed("tds_deductions", {"firm_id": FIRM, "client_id": CLIENT, "section": "194C", "payment_amount_paise": 12_34_567_00,
                               "tds_paise": 24_691_00, "transaction_date": "2025-05-10"})
    db.seed("tax_audits", {"firm_id": FIRM, "client_id": CLIENT, "financial_year": FY, "turnover_paise": 5_00_00_000_00,
                           "form_type": "3CB-3CD"})


@pytest.fixture()
def register():
    from services.form_3cd_service import build, save_manual_clauses
    db = FakeDB()
    _seed_books(db)
    save_manual_clauses(db, FIRM, CLIENT, FY, {"31": "No loans or deposits were taken in cash this year.",
                                               "1": "Mehta Traders Private Limited"}, status="review")
    out = build(db, FIRM, CLIENT, FY, nature="business")
    return db, out


def _basis(doc) -> dict:
    """code -> the whole basis sentence (a long one is several rows; the continuation rows carry no code)."""
    out, code = {}, None
    for r in doc.tables[1].rows:
        code = r.cells[0] or code
        out[code] = (out.get(code, "") + " " + r.cells[1]).strip()
    return out


def _first_rows(doc):
    return [r.cells for r in doc.tables[0].rows if r.cells[0]]


def test_every_clause_is_named_once_in_the_forms_own_order(register):
    _, out = register
    doc = form_3cd_document(out)
    assert [c[0] for c in _first_rows(doc)] == [c.code for c in f3cd.CLAUSES]
    assert [c[1] for c in _first_rows(doc)] == [c.heading for c in f3cd.CLAUSES]
    assert [r.cells[0] for r in doc.tables[1].rows if r.cells[0]] == [c.code for c in f3cd.CLAUSES]


def test_each_clause_says_who_answered_it(register):
    _, out = register
    by_code = {row[0]: row for row in _first_rows(form_3cd_document(out))}
    assert by_code["14"][3] == "From the books" and by_code["14"][2] == "fifo"
    assert by_code["31"][3] == "Recorded by the CA" and by_code["31"][2].startswith("No loans")
    assert by_code["1"][3] == "Recorded by the CA"
    assert by_code["2"][3] == "Not answered here" and by_code["2"][2] == "Not answered here."


def test_the_basis_of_an_unanswered_clause_is_the_reason_the_register_gives(register):
    _, out = register
    doc = form_3cd_document(out)
    basis = _basis(doc)
    assert basis["2"] == next(c for c in out["clauses"] if c["code"] == "2")["note"]
    assert "registered address" in basis["2"]
    assert "Recorded by the CA" in basis["31"]


def test_the_meta_counts_agree_with_the_register(register):
    _, out = register
    doc = form_3cd_document(out)
    meta = dict(doc.meta)
    assert meta["Financial year"] == FY and meta["Checklist"] == "In review"
    derived = sum(1 for c in out["clauses"] if c["derived"])
    recorded = sum(1 for c in out["clauses"] if not c["derived"] and c["value"] is not None)
    assert meta["Clauses"] == f"{derived} from the books, {recorded} recorded by the CA, {len(out['clauses']) - derived - recorded} not answered, of {len(out['clauses'])}"


def test_a_clause_with_a_long_answer_is_one_row_per_line_and_the_heading_is_not_repeated(register):
    _, out = register
    doc = form_3cd_document(out)
    c34 = next(c for c in out["clauses"] if c["code"] == "34")
    assert c34["derived"] and isinstance(c34["value"], dict)
    start = next(i for i, r in enumerate(doc.tables[0].rows) if r.cells[0] == "34")
    block = []
    for r in doc.tables[0].rows[start:]:
        if r is not doc.tables[0].rows[start] and r.cells[0]:
            break
        block.append(r.cells)
    assert len(block) == len(describe(c34["value"])) and len(block) > 1
    assert all(cells[0] == "" and cells[1] == "" and cells[3] == "" for cells in block[1:])


def test_no_cell_holds_a_line_break_because_the_page_would_run_the_lines_together(register):
    _, out = register
    for table in form_3cd_document(out).tables:
        for row in table.rows:
            assert all("\n" not in (cell or "") for cell in row.cells)


def test_an_empty_register_is_refused_in_words():
    with pytest.raises(ExportRefused, match="no clauses"):
        form_3cd_document({"financial_year": FY, "clauses": []})


def test_a_register_too_long_to_print_is_refused_and_not_cut(register, monkeypatch):
    _, out = register
    monkeypatch.setattr(doc_mod, "MAX_LINES", 10)
    with pytest.raises(ExportRefused, match="not cut short"):
        form_3cd_document(out)


# ── the files ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _pdf_text(content: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


def test_the_pdf_has_every_clause_number_and_heading_and_the_figures_in_indian_grouping(register):
    db, out = register
    from services.report_export_service import export_form_3cd
    file = export_form_3cd(out, "pdf", db=db, firm_id=FIRM, client_id=CLIENT, generated_on="2026-11-20")
    assert file.media_type == "application/pdf" and file.filename.endswith(".pdf") and "form-3cd" in file.filename
    text = " ".join(_pdf_text(file.content).split())
    assert "Mehta Traders Private Limited" in text and "Rao and Associates" in text
    for clause in f3cd.CLAUSES:
        assert f" {clause.code} " in f" {text} ", clause.code
        # A heading wraps inside its cell, so it is compared word by word.
        for word in clause.heading.split()[:3]:
            assert word in text, (clause.code, word)
    assert "12,34,567.00" in text, "the clause 34 figure is printed in Indian grouping"
    assert "Recorded by the CA" in text and "From the books" in text and "Not answered here" in text
    assert "No loans or deposits were taken in cash this year." in text
    assert "not Form 3CD as the Income Tax portal takes it" in text and "nothing here has been filed" in text


def test_the_spreadsheet_has_the_same_two_tables_and_the_notes(register):
    db, out = register
    from openpyxl import load_workbook
    from services.report_export_service import export_form_3cd
    file = export_form_3cd(out, "xlsx", db=db, firm_id=FIRM, client_id=CLIENT, generated_on="2026-11-20")
    wb = load_workbook(io.BytesIO(file.content))
    assert wb.sheetnames[:2] == ["Statement of particulars", "Basis of each answer"]
    details = " ".join(str(c.value) for row in wb["Details"].iter_rows() for c in row if c.value)
    assert "not Form 3CD as the Income Tax portal takes it" in details and "Previous year 2025-26" in details
    first = wb["Statement of particulars"]
    assert [c.value for c in first[1]] == ["Clause", "Particulars", "Answer", "Source"]
    codes = [row[0].value for row in first.iter_rows(min_row=2) if row[0].value]
    assert codes == [c.code for c in f3cd.CLAUSES]


def test_a_list_item_that_starts_with_a_dash_stays_text_in_the_spreadsheet(register):
    db, out = register
    from openpyxl import load_workbook
    from services.report_export_service import export_form_3cd
    out = {**out, "clauses": [{**c, "value": ["a", "b"], "derived": True} if c["code"] == "14" else c for c in out["clauses"]]}
    wb = load_workbook(io.BytesIO(export_form_3cd(out, "xlsx", db=db, firm_id=FIRM, client_id=CLIENT).content))
    cells = [row[2] for row in wb["Statement of particulars"].iter_rows(min_row=2) if row[2].value in ("- a", "- b")]
    assert len(cells) == 2 and all(c.data_type == "s" for c in cells)


def test_a_format_it_does_not_offer_is_refused(register):
    db, out = register
    from services.report_export_service import export_form_3cd
    with pytest.raises(ExportRefused, match="pdf or xlsx"):
        export_form_3cd(out, "csv", db=db, firm_id=FIRM, client_id=CLIENT)


def test_a_client_that_is_not_the_firms_is_not_given_a_letterhead(register):
    db, out = register
    from services.report_export_service import export_form_3cd
    with pytest.raises(ExportRefused, match="not found"):
        export_form_3cd(out, "pdf", db=db, firm_id=FIRM, client_id=str(uuid.uuid4()))


# ── the route ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def route(monkeypatch):
    import routers.income_tax as it
    db = FakeDB()
    _seed_books(db)
    monkeypatch.setattr(it, "_db", lambda: db)
    asked = []
    monkeypatch.setattr(it, "assert_client_access", lambda user, client_id: asked.append(client_id))
    user = {"id": str(uuid.uuid4()), "firm_id": FIRM, "role": "Executive", "permission_overrides": {}}

    def call(**kw):
        params = {"client_id": CLIENT, "fy": FY, "format": "pdf", "nature": None, "bank_rate_bps": None, "current_user": user}
        params.update(kw)
        return it.form_3cd_working_paper(**params)

    call.db, call.asked, call.module = db, asked, it
    return call


def test_the_route_returns_the_file_with_a_download_name(route):
    response = route(nature="business")
    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].startswith('attachment; filename="form-3cd-working-paper-2025-26')
    assert route.asked == [CLIENT], "the caller's access to the client is asked first"
    assert "Statement of particulars" in _pdf_text(response.body)


def test_the_route_builds_from_the_function_the_registers_endpoint_calls():
    import routers.income_tax as it
    assert "from services.form_3cd_service import build" in inspect.getsource(it.form_3cd_working_paper)
    assert "build(" in inspect.getsource(it.form_3cd_working_paper)
    assert "from services.form_3cd_service import build" in inspect.getsource(it.form_3cd_register)


def test_the_route_asks_the_read_permission_and_not_a_write():
    import routers.income_tax as it
    default = inspect.signature(it.form_3cd_working_paper).parameters["current_user"].default
    assert default.dependency.__name__ == "rbac_income_tax_read"


def test_a_format_the_route_does_not_know_is_not_accepted_by_its_signature():
    import routers.income_tax as it
    annotation = inspect.signature(it.form_3cd_working_paper).parameters["format"].annotation
    assert "pdf" in str(annotation) and "xlsx" in str(annotation) and "csv" not in str(annotation)


def test_without_a_database_the_route_says_so(monkeypatch):
    import routers.income_tax as it
    from fastapi import HTTPException
    monkeypatch.setattr(it, "_db", lambda: None)
    monkeypatch.setattr(it, "assert_client_access", lambda *a, **k: None)
    with pytest.raises(HTTPException) as err:
        it.form_3cd_working_paper(client_id=CLIENT, fy=FY, format="pdf", nature=None, bank_rate_bps=None,
                                  current_user={"id": "u", "firm_id": FIRM, "role": "Partner"})
    assert err.value.status_code == 503 and "without the database" in err.value.detail


def test_a_refusal_is_a_422_in_words(route, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(doc_mod, "MAX_LINES", 3)
    with pytest.raises(HTTPException) as err:
        route()
    assert err.value.status_code == 422 and "not cut short" in err.value.detail


# ── what the independent review of the first version found (20-11-2026) ──────────────────────────────────────────────────────────

def _register_with(manual: dict, derived: dict | None = None) -> dict:
    return f3cd.build_register(client_id=CLIENT, financial_year=FY, derived=derived or {}, manual=manual).to_dict()


def _answer_rows(doc, code: str) -> list:
    rows = doc.tables[0].rows
    start = next(i for i, r in enumerate(rows) if r.cells[0] == code)
    out = [rows[start].cells]
    for r in rows[start + 1:]:
        if r.cells[0]:
            break
        out.append(r.cells)
    return out


def test_an_answer_typed_over_several_lines_is_several_rows_and_not_one_run_together():
    doc = form_3cd_document(_register_with({"31": "Line one\nLine two\r\nLine three"}))
    rows = _answer_rows(doc, "31")
    assert [r[2] for r in rows] == ["Line one", "Line two", "Line three"]
    assert rows[0][3] == "Recorded by the CA" and all(r[0] == "" and r[3] == "" for r in rows[1:])


def test_a_word_soft_break_is_a_line_boundary_and_other_controls_are_dropped():
    doc = form_3cd_document(_register_with({"31": "before\x0bafter\x07 bell\tTabbed"}))
    assert [r[2] for r in _answer_rows(doc, "31")] == ["before", "after bell Tabbed"]


def test_a_line_break_inside_a_record_keeps_the_records_indent():
    lines = describe({"gaps": ["first\nsecond"]})
    assert lines[0] == "Gaps:" and lines[1].endswith("- first") and lines[2].lstrip("\u00a0") == "second"
    assert lines[2].startswith("\u00a0")


@pytest.mark.parametrize("answer", [
    pytest.param(("word " * 1100).strip(), id="prose"),
    pytest.param("x" * 3500, id="one unbroken string"),
    pytest.param("\n".join(["a line of an auditor's narrative"] * 200), id="many lines"),
])
def test_a_long_answer_is_cut_into_rows_and_the_pdf_is_made(answer, register):
    db, out = register
    from services.report_export_service import export_form_3cd
    from services.form_3cd_service import save_manual_clauses
    save_manual_clauses(db, FIRM, CLIENT, FY, {"31": answer}, status="review")
    from services.form_3cd_service import build
    long_register = build(db, FIRM, CLIENT, FY, nature="business")
    doc = form_3cd_document(long_register)
    assert all(len(r.cells[2]) <= doc_mod.ROW_CHARS for r in doc.tables[0].rows), "no row is longer than the limit"
    assert len(_answer_rows(doc, "31")) > 1
    pdf = export_form_3cd(long_register, "pdf", db=db, firm_id=FIRM, client_id=CLIENT).content
    assert pdf.startswith(b"%PDF")
    # A cut falls where the page wraps, so the text is compared with its white space removed.
    assert "".join(answer.split())[:200] in "".join(_pdf_text(pdf).split())


def test_the_pieces_of_a_cut_answer_say_the_same_thing_as_the_whole():
    answer = ("alpha beta gamma delta " * 80).strip()
    doc = form_3cd_document(_register_with({"31": answer}))
    pieces = [r[2] for r in _answer_rows(doc, "31")]
    assert " ".join(" ".join(pieces).split()) == answer
    assert all(len(p) <= doc_mod.ROW_CHARS for p in pieces)


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_a_cleared_box_is_not_an_answer(blank):
    out = _register_with({"31": blank})
    doc = form_3cd_document(out)
    row = next(r for r in _first_rows(doc) if r[0] == "31")
    assert row[3] == "Not answered here" and row[2] == "Not answered here."
    assert dict(doc.meta)["Clauses"].startswith("0 from the books, 0 recorded by the CA, 50 not answered")


def test_a_register_with_only_a_blank_in_a_derivable_clause_prints_it_as_unanswered():
    out = _register_with({}, derived={"14": ("", "no policy")})
    row = next(r for r in _first_rows(form_3cd_document(out)) if r[0] == "14")
    assert row[3] == "Not answered here"


def test_a_control_character_in_a_recorded_answer_still_makes_the_spreadsheet(register):
    db, _ = register
    from openpyxl import load_workbook
    from services.report_export_service import export_form_3cd
    out = _register_with({"1": "ok\x0b", "31": "bell\x07 and \x00 nul"})
    wb = load_workbook(io.BytesIO(export_form_3cd(out, "xlsx", db=db, firm_id=FIRM, client_id=CLIENT).content))
    answers = [row[2].value for row in wb["Statement of particulars"].iter_rows(min_row=2)]
    assert "ok" in answers and "bell and  nul" in answers


def test_the_spreadsheet_writer_drops_an_illegal_character_from_any_report_text(register):
    """The same defect was in every report: a ledger narration with a vertical tab made the whole download a 500."""
    db, _ = register
    from domain.reporting.export_document import Column, ReportDocument, Row, Table, TEXT
    from services.report_xlsx_service import build_report_xlsx
    doc = ReportDocument(report_id="x", title="T\x0b", subject="", period="p", notes=("note\x07",),
                         tables=(Table(columns=(Column("a", "A", TEXT),), rows=(Row(("nar\x0brative",)),)),))
    content = build_report_xlsx(doc, holder={"legal_name": "Mehta\x0cTraders"}, firm={"name": "Firm\x01"})
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(content))
    assert wb.active["A2"].value == "narrative" or wb.worksheets[0]["A2"].value == "narrative"


def test_a_row_the_page_cannot_hold_is_refused_in_words_and_not_a_500(register, monkeypatch):
    db, out = register
    from reportlab.platypus.doctemplate import LayoutError
    import services.report_export_service as svc
    monkeypatch.setattr(svc, "build_report_pdf", lambda *a, **k: (_ for _ in ()).throw(LayoutError("too large")))
    with pytest.raises(ExportRefused, match="taller than one page"):
        svc.export_form_3cd(out, "pdf", db=db, firm_id=FIRM, client_id=CLIENT)


def test_the_notes_define_the_labels_the_way_the_code_uses_them(register):
    _, out = register
    notes = " ".join(form_3cd_document(out).notes)
    # A derivable clause that could not be resolved this time prints "Not answered here", so the note says so.
    assert "could not resolve it this time" in notes
    # A default the module applied, and "No entries", are said to be what the books held and not a confirmation.
    assert "a default was applied" in notes and "not that anyone confirmed" in notes
    assert "neither holds nor derives" not in notes
