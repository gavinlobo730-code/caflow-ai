r"""Every document this product prints says which page you are holding.

── THE DEFECT ───────────────────────────────────────────────────────────────
Measured 19 September 2026, before this module existed:

    $ grep -c 'canvasmaker\|onPage\|pdf:pagecount' services/*pdf*.py
    ... 0 everywhere

Not one of the seven documents numbered its pages, and only three of the
twenty-one tables repeated their column heading when they split. Both matter
on exactly the documents that run to more than one page — a customer
STATEMENT covering a year, a year-end PACK, a sixty-line INVOICE, a bank
RECONCILIATION — and those are the ones that get printed, signed, photocopied
and filed. "Page 3 of 7" is the only thing that tells a reader a page is
missing from the set in front of them; a repeated header is the only thing
that says which column is Taxable Value and which is Tax on page 2.

Rendered before the fix, a sixty-line invoice came out as three pages, the
second and third being unlabelled columns of figures with no page number.

── THE RULE, NOT A SPELLING OF IT ───────────────────────────────────────────
Two limbs, both read off the AST rather than off a grep for one phrasing:

  1. A module that BUILDS a document numbers its pages. For reportlab that
     means the build goes through `pdf_page_furniture.numbered`, never
     `doc.build(...)` — the wrapper exists so there is one place the rule
     lives. For the one xhtml2pdf document the equivalent is a static frame
     carrying `pdf:pagecount`, because that renderer has no canvasmaker.

  2. A TABLE WHOSE ROW 0 IS A HEADER repeats it — `repeatRows`. Header-ness
     is DERIVED: a style command spanning exactly `(0, 0)` to `(-1, 0)` is
     by definition a rule about the first row and nothing else, which is what
     a header is. Following one level of indirection matters here, because
     six of the year-end tables get their style from `_table_style()` and a
     scan that only read the call site would see nothing and pass.

     Deriving it is what keeps the guard honest in BOTH directions. Seven
     tables in these services have no header row at all — two metadata
     blocks, a tie-out of label/value pairs, the invoice letterhead, its
     payment block, the payslip's own header and its Net Pay banner — and
     `repeatRows` on any of them would repeat a line of data. A guard written
     as "every Table takes repeatRows" would have demanded exactly that.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

SERVICES = pathlib.Path(__file__).resolve().parents[1] / "services"

#: The module that DEFINES the rule is not subject to it.
_DEFINER = "pdf_page_furniture.py"


def _pdf_modules() -> list[pathlib.Path]:
    return sorted(p for p in SERVICES.glob("*pdf*.py") if p.name != _DEFINER)


# ── header-ness ──────────────────────────────────────────────────────────────

def _is_row_zero(node: ast.AST) -> bool:
    """`(0, 0)` or `(-1, 0)` — a cell reference on the first row."""
    if not isinstance(node, ast.Tuple) or len(node.elts) != 2:
        return False
    col, row = node.elts
    return _const_int(row) == 0 and _const_int(col) is not None


def _const_int(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _const_int(node.operand)
        return None if inner is None else -inner
    return None


#: The three commands that make a row LOOK like a header. Deliberately not
#: every command whose range happens to be row 0: the invoice's letterhead and
#: the payslip's employee block are two-cell LAYOUT tables that carry a
#: `("BOTTOMPADDING", (0, 0), (-1, 0), 10)` — spacing under the top row, which
#: says nothing about whether that row is a heading. Reading padding as a
#: header (this guard's first draft did) demands `repeatRows` on a table whose
#: first row is the supplier's own address, which would then print at the top
#: of page 2.
_HEADER_COMMANDS = {"BACKGROUND", "FONTNAME", "TEXTCOLOR"}


def _commands_style_row_zero_alone(node: ast.AST) -> bool:
    """True if a style command distinguishes row 0 and nothing else."""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Tuple) or len(sub.elts) < 3:
            continue
        name = sub.elts[0]
        if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
            continue
        if name.value.upper() not in _HEADER_COMMANDS:
            continue
        if _is_row_zero(sub.elts[1]) and _is_row_zero(sub.elts[2]):
            return True
    return False


def _style_arg_is_a_header_style(arg: ast.AST, module: ast.Module) -> bool:
    """Does this `setStyle(...)` argument style the first row on its own?

    Follows ONE level of indirection: `setStyle(_table_style(...))` is looked
    up in the module and its body scanned. Six year-end tables reach their
    style that way, and a guard reading only the call site sees nothing.
    """
    if _commands_style_row_zero_alone(arg):
        return True
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
        for fn in ast.walk(module):
            if isinstance(fn, ast.FunctionDef) and fn.name == arg.func.id:
                return _commands_style_row_zero_alone(fn)
    # `setStyle(TableStyle(style))` where `style` is a local list built a few
    # lines above — the invoice's line table and the reconciliation's BRS both
    # do this, and a scan reading only the call site sees a bare Name and
    # concludes there is no header. That is the same one-level-of-indirection
    # the quantity-door guard follows, for the same reason: refusing to follow
    # it pushes the next author into inlining the style to satisfy a test.
    for name in {n.id for n in ast.walk(arg) if isinstance(n, ast.Name)}:
        for assign in ast.walk(module):
            if (isinstance(assign, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == name
                            for t in assign.targets)
                    and _commands_style_row_zero_alone(assign.value)):
                return True
    return False


def _tables(path: pathlib.Path):
    """Yield (line, has_repeat_rows, has_header_row) per `Table(...)` call."""
    module = ast.parse(path.read_text())

    # name -> the setStyle argument applied to it
    styles: dict[str, ast.AST] = {}
    for node in ast.walk(module):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setStyle"
                and isinstance(node.func.value, ast.Name)
                and node.args):
            styles[node.func.value.id] = node.args[0]

    for node in ast.walk(module):
        if not (isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "Table"):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        repeats = any(kw.arg == "repeatRows" for kw in node.value.keywords)
        style = styles.get(name)
        header = style is not None and _style_arg_is_a_header_style(style, module)
        yield node.lineno, name, repeats, header


# ── limb 1: the pages are numbered ───────────────────────────────────────────

def test_every_module_that_builds_a_pdf_is_scanned():
    """A floor, so a rename cannot make this module vacuous."""
    names = [p.name for p in _pdf_modules()]
    assert len(names) >= 6, names
    for expected in ("invoice_pdf_service.py", "year_end_pdf_service.py",
                     "statement_pdf_service.py", "payslip_pdf_service.py",
                     "bank_reconciliation_pdf_service.py",
                     "engagement_pdf_service.py"):
        assert expected in names, f"{expected} missing from {names}"


@pytest.mark.parametrize("path", _pdf_modules(), ids=lambda p: p.name)
def test_a_reportlab_document_is_built_through_the_one_numbering_wrapper(path):
    """`doc.build(...)` renders a document with no page numbers.

    `pdf_page_furniture.numbered` is the one place that knows the two-pass
    trick, so calling `.build` directly is how a new service silently opts
    out — which is how all six of them came to be unnumbered.
    """
    module = ast.parse(path.read_text())
    builds_a_doc = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id in {"SimpleDocTemplate", "BaseDocTemplate"}
        for n in ast.walk(module)
    )
    if not builds_a_doc:
        pytest.skip(f"{path.name} renders no reportlab document")

    direct = [
        n.lineno for n in ast.walk(module)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "build"
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "doc"
    ]
    assert not direct, (
        f"{path.name}: doc.build() at line(s) {direct} — a document with no "
        f"page numbers. Call numbered(doc, story) from "
        f"services.pdf_page_furniture instead."
    )
    assert "numbered(" in path.read_text(), (
        f"{path.name} builds a reportlab document and never calls numbered()."
    )


def test_the_one_xhtml2pdf_document_numbers_its_pages_its_own_way():
    """xhtml2pdf has no canvasmaker; a static frame is the equivalent.

    Asserted separately rather than folded into the reportlab limb, because
    the MECHANISM genuinely differs — and a shared assertion would have to be
    loose enough to pass on a document that numbers nothing.
    """
    module = ast.parse((SERVICES / "engagement_pdf_service.py").read_text())
    wrapper = None
    for node in ast.walk(module):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_WRAPPER"
                        for t in node.targets)
                and isinstance(node.value, ast.Constant)):
            wrapper = node.value.value
    assert wrapper, "engagement_pdf_service._WRAPPER is not a string constant"

    # Read off the AST rather than the file, because a negative control caught
    # this test passing with the real `<pdf:pagecount>` deleted: the word also
    # appears in the prose comment above the wrapper, and a `in src` scan
    # cannot tell an explanation from the thing it explains. That is the
    # guard-reads-its-own-docstring defect this codebase has now hit four times.
    assert "pdf:pagecount" in wrapper, (
        "the engagement letter runs to several pages and numbers none of them"
    )
    assert "pdf:pagenumber" in wrapper
    assert "-pdf-frame-content" in wrapper, (
        "a pagecount outside a static frame prints on page one only"
    )


# ── limb 2: a header that splits is repeated ─────────────────────────────────

@pytest.mark.parametrize("path", _pdf_modules(), ids=lambda p: p.name)
def test_a_table_with_a_header_row_repeats_it_when_it_splits(path):
    missing = [
        f"{path.name}:{line} ({name})"
        for line, name, repeats, header in _tables(path)
        if header and not repeats
    ]
    assert not missing, (
        "these tables style their first row as a header and do not repeat it, "
        f"so a table that splits leaves page 2 unlabelled: {missing}"
    )


def test_a_table_with_no_header_row_is_left_alone():
    """The rule's other direction, which is what makes deriving it worthwhile.

    Seven tables in these services have no header row — layout blocks, a
    tie-out of label/value pairs, the Net Pay banner. `repeatRows` on any of
    them would repeat a line of DATA at the top of page 2. A guard phrased as
    "every Table takes repeatRows" would have demanded exactly that, so this
    asserts such tables exist and carry none.
    """
    headerless = [
        f"{p.name}:{line}"
        for p in _pdf_modules()
        for line, _name, repeats, header in _tables(p)
        if not header and not repeats
    ]
    assert len(headerless) >= 5, (
        f"expected several headerless layout tables, found {headerless}"
    )

    wrong = [
        f"{p.name}:{line}"
        for p in _pdf_modules()
        for line, _name, repeats, header in _tables(p)
        if not header and repeats
    ]
    assert not wrong, (
        f"these tables have no header row and repeat their first row anyway, "
        f"which puts a line of data at the top of page 2: {wrong}"
    )


def test_the_scan_sees_the_tables_it_is_meant_to_see():
    """A floor on both buckets — the AST walk passing over everything is the
    failure mode a green result cannot distinguish from compliance."""
    found = [(p.name, line, repeats, header)
             for p in _pdf_modules() for line, _n, repeats, header in _tables(p)]
    assert len(found) >= 18, f"only {len(found)} Table() calls seen"
    assert sum(1 for *_, header in found if header) >= 12, (
        "the header-row derivation found almost nothing, which means the "
        "indirection through _table_style() stopped resolving"
    )


# ── the number actually appears, which is a different claim ──────────────────
# The limbs above prove the wrapper is CALLED. They cannot prove reportlab
# emits anything, and the two-pass canvas is the kind of code that compiles,
# runs and silently draws nothing — `showPage` overridden without `_startPage`
# loses every page after the first. So one document of each renderer is built
# for real and its footers read back.

def test_a_multi_page_invoice_numbers_every_page_and_repeats_its_header():
    pdfplumber = pytest.importorskip("pdfplumber")
    import io

    from services.invoice_pdf_service import build_sales_invoice_pdf

    lines = [{"description": f"Consultancy line {i}", "quantity": 1,
              "rate_paise": 100000, "taxable_paise": 100000,
              "gst_rate_percent": 18, "hsn_sac_code": "998311",
              "cgst_paise": 9000, "sgst_paise": 9000, "igst_paise": 0,
              "unit": "NOS"} for i in range(60)]
    pdf = build_sales_invoice_pdf(
        {"invoice_no": "INV/2026-27/0001", "invoice_date": "2026-06-10",
         "place_of_supply": "27", "total_paise": 11800000,
         "taxable_paise": 10000000, "cgst_paise": 900000, "sgst_paise": 900000,
         "igst_paise": 0, "total_gst_paise": 1800000, "lines": lines},
        {"client_name": "Acme Traders", "legal_name": "Acme Traders Pvt Ltd",
         "gstin": "27AAACA1111A1Z4", "address": "Mumbai", "state_code": "27"},
        {"customer_name": "Beta Ltd", "gstin": "27AAACB2222B1Z1",
         "address": "Pune", "state_code": "27"},
    )

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        assert len(doc.pages) >= 2, (
            "sixty lines fitted on one page, so this asserts nothing — "
            "raise the line count"
        )
        total = len(doc.pages)
        for n, page in enumerate(doc.pages, start=1):
            text = page.extract_text() or ""
            assert f"Page {n} of {total}" in text, (
                f"page {n} of {total} carries no page number"
            )
            assert "HSN/SAC" in text, (
                f"page {n} of the line table has no column heading — "
                f"repeatRows is not doing its job"
            )


def test_a_multi_page_engagement_letter_numbers_every_page():
    pdfplumber = pytest.importorskip("pdfplumber")
    pytest.importorskip("xhtml2pdf")
    import io

    from services.engagement_pdf_service import render_engagement_pdf

    body = "<h2>Engagement Letter</h2>" + "".join(
        f"<p>Clause {i}: the practice will prepare and file the returns "
        f"described in the scope above.</p>" for i in range(90))
    pdf, _name = render_engagement_pdf(body, "ENG/2026/001")

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        assert len(doc.pages) >= 2, "ninety clauses fitted on one page"
        total = len(doc.pages)
        for n, page in enumerate(doc.pages, start=1):
            assert f"Page {n} of {total}" in (page.extract_text() or ""), (
                f"page {n} of {total} carries no page number"
            )
