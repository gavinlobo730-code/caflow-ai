r"""A tax invoice's columns fit their own headings and their own figures.

── THE DEFECT ───────────────────────────────────────────────────────────────
Measured 19 September 2026. `_DETAIL_WIDTHS` gave nine columns 180mm and
reportlab's default 6pt-a-side padding took 108pt of that — a fifth of the
table — leaving **seven columns too narrow for what goes in them**:

  heading  `Taxable Value (Rs.)`  needs 73.4pt, column gave 61.7pt
  heading  `GST Rate`             needs 36.0pt, column gave 27.7pt
  figure   `1,23,45,678.90`       needs 53.4pt, Rate / Taxable / Tax gave 50.4pt
  figure   `99` (the 99th line)   needs  8.9pt, `#`  gave  7.8pt
  figure   `99999.999`            needs 37.8pt, Qty  gave 24.9pt

The two HEADINGS overflowed on every detail invoice ever rendered, whatever
the figures were — pdfplumber reads the header band back as one word,
`'(Rs.)GST'`, because "Taxable Value (Rs.)" runs into the next column's
"GST Rate" with no gap at all. The FIGURES overflow on an invoice at crore
scale, which for an Indian manufacturing client is an ordinary Tuesday.

A reportlab Table does not wrap a plain string and does not warn: the text
is simply drawn past the cell edge, over whatever is next to it.

── THE FIX AND WHY IT IS THE PADDING ────────────────────────────────────────
Widening the money columns out of Description was the obvious move and the
wrong one — it buys ~8mm and costs the description its room. The padding is
where the space actually was: at 8pt type, 6pt of whitespace on each side of
nine columns is 38mm of the 180mm. At 4pt a side everything fits with
headroom AND Description keeps 108pt of text against the 116pt it had, which
a wrapping Paragraph absorbs in a line.

── THE RULE ─────────────────────────────────────────────────────────────────
Both layouts' headings and their realistic worst-case figures fit the column
they are drawn in, measured with reportlab's own metrics against the same
three constants the renderer uses — the widths, the headings and the padding.
Not a golden list of nine numbers: change a heading, a width or the padding
and the arithmetic is redone.

The worst-case figures are stated here rather than derived, because a column
width is a judgement about what is PLAUSIBLE and not about what the column
type permits. `quantity` is NUMERIC(10,3), so 9,999,999.999 is storable and
sizing the Qty column for it would waste 10mm on every invoice ever printed.
Each probe below says what it represents.
"""
from __future__ import annotations

import pytest
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth

import services.invoice_pdf_service as I

#: The renderer sets FONTSIZE 8 across the detail table and leaves the plain
#: layout at the stylesheet's 10. Row 0 is Helvetica-Bold, the body Helvetica.
_DETAIL_SIZE = 8
_PLAIN_SIZE = 10

#: Realistic worst case per column. Not the column TYPE's maximum — see the
#: module docstring.
_DETAIL_WORST = {
    "#": ("100", "a hundred-line invoice"),
    "Description": (None, "a wrapping Paragraph — it takes what is left"),
    "HSN/SAC": ("99887766", "the longest HSN is 8 digits; a SAC is 6"),
    "Qty": ("99999.999", "NUMERIC(10,3) at a plausible scale, trailing zeros stripped"),
    "Unit": ("OTH", "every UQC code is 3 characters or fewer"),
    "Rate (Rs.)": ("1,23,45,678.90", "a crore-scale figure under Indian grouping"),
    "Taxable Value (Rs.)": ("1,23,45,678.90", "likewise"),
    "GST Rate": ("28.125%", "the longest _pct_label output plus its sign"),
    "Tax (Rs.)": ("1,23,45,678.90", "likewise"),
}
_PLAIN_WORST = {
    "#": ("100", "a hundred-line invoice"),
    "Description": (None, "a wrapping Paragraph"),
    "SAC": ("99887766", "the longest code"),
    "Taxable Value (Rs.)": ("1,23,45,678.90", "a crore-scale figure"),
}


#: A heading with no stated worst case is reported, never crashed on. The
#: first draft indexed `worst[text]` and a negative control that renamed a
#: heading blew up at COLLECTION with a KeyError — which in a suite this size
#: reads as "the test file is broken", not "that heading no longer fits".
_NO_PROBE = object()


def _cases(header, widths, worst, size):
    for text, width in zip(header, widths):
        probe, why = worst.get(text, (_NO_PROBE, ""))
        yield text, width, probe, why, size


def _avail(width: float) -> float:
    return width - 2 * I._LINE_TABLE_SIDE_PAD


@pytest.mark.parametrize(
    "heading,width,probe,why,size",
    list(_cases(I._DETAIL_HEADER, I._DETAIL_WIDTHS, _DETAIL_WORST, _DETAIL_SIZE))
    + list(_cases(I._PLAIN_HEADER, I._PLAIN_WIDTHS, _PLAIN_WORST, _PLAIN_SIZE)),
    ids=lambda v: str(v)[:26] if isinstance(v, str) else "",
)
def test_a_heading_and_its_worst_figure_fit_the_column(heading, width, probe, why, size):
    avail = _avail(width)
    need_h = stringWidth(heading, "Helvetica-Bold", size)
    assert need_h <= avail, (
        f"the heading {heading!r} needs {need_h:.1f}pt and its column gives "
        f"{avail:.1f}pt, so it is drawn over the column beside it on every "
        f"invoice — widen the column, shorten the heading, or take the room "
        f"out of the padding"
    )
    assert probe is not _NO_PROBE, (
        f"{heading!r} is a column heading with no stated worst-case figure. "
        f"Add one to _DETAIL_WORST / _PLAIN_WORST saying what it represents, "
        f"so the column is sized against something rather than by eye."
    )
    if probe is None:
        return
    need_d = stringWidth(probe, "Helvetica", size)
    assert need_d <= avail, (
        f"{heading!r} column gives {avail:.1f}pt and {probe!r} ({why}) needs "
        f"{need_d:.1f}pt — that figure prints over the next column"
    )


def test_the_columns_still_add_up_to_the_table_they_are_drawn_in():
    """A re-tune that overflows the page is a different bug with the same cause."""
    for name, widths in (("detail", I._DETAIL_WIDTHS), ("plain", I._PLAIN_WIDTHS)):
        assert abs(sum(widths) - 180 * mm) < 0.5, (
            f"{name} columns sum to {sum(widths) / mm:.1f}mm; the renderer's "
            f"frame is 180mm wide"
        )


def test_the_description_column_keeps_room_to_be_a_description():
    """The padding was the place to find room BECAUSE taking it from
    Description is the tempting move and the one that ruins the document.
    A description narrower than about half the table stops being readable
    however well the figures fit."""
    text = _avail(I._DETAIL_WIDTHS[1])
    assert text >= 100, (
        f"Description has {text:.1f}pt of text width; at 8pt that is under "
        f"25 characters a line, and every line item becomes a column of words"
    )


def test_the_padding_is_one_number_the_style_actually_applies():
    """The guard measures against `_LINE_TABLE_SIDE_PAD`; if the TableStyle
    stopped using it, every assertion above would be arithmetic about a
    number nobody applies — which is the shape of a guard that passes on a
    tree full of the defect."""
    import ast
    import pathlib

    src = pathlib.Path(I.__file__).read_text()
    module = ast.parse(src)
    used = [
        n for n in ast.walk(module)
        if isinstance(n, ast.Name) and n.id == "_LINE_TABLE_SIDE_PAD"
    ]
    # one definition + the two padding commands
    assert len(used) >= 3, (
        f"_LINE_TABLE_SIDE_PAD appears {len(used)} time(s); the style must set "
        f"both LEFTPADDING and RIGHTPADDING from it"
    )
    for cmd in ("LEFTPADDING", "RIGHTPADDING"):
        assert f'("{cmd}", (0, 0), (-1, -1), _LINE_TABLE_SIDE_PAD)' in src, (
            f"the line table does not set {cmd} from the constant this test "
            f"measures against, so reportlab's own default 6 applies instead"
        )


def test_the_rendered_header_row_stays_inside_its_own_column():
    """The arithmetic above says the headings fit. This says so on the page.

    It is what caught the defect: the extracted header band read `'(Rs.)GST'`
    — one word made of two column headings — because "Taxable Value (Rs.)"
    was drawn past its edge and into "GST Rate".

    The test is a BOUNDARY comparison, not a look for suspicious words. The
    first draft searched the extracted text for run-together strings and was
    wrong twice over: it missed `'(Rs.)GST'` (its own motivating example,
    excluded by a `startswith("(")` clause) and it could only ever find
    collisions that happen to merge into one word. Column edges are derived
    from `_DETAIL_WIDTHS`, so a word is in its column or it is not.
    """
    pdfplumber = pytest.importorskip("pdfplumber")
    import io

    pdf = I.build_sales_invoice_pdf(
        {"invoice_no": "INV/2026-27/0001", "invoice_date": "2026-06-10",
         "place_of_supply": "27", "total_paise": 145600000,
         "taxable_paise": 123400000, "cgst_paise": 11100000,
         "sgst_paise": 11100000, "igst_paise": 0, "total_gst_paise": 22200000,
         "lines": [{"description": "Plant and machinery supplied", "quantity": 2,
                    "rate_paise": 61700000, "taxable_amount_paise": 123400000,
                    "gst_rate_percent": 18, "hsn_sac": "84581100",
                    "cgst_paise": 11100000, "sgst_paise": 11100000,
                    "igst_paise": 0, "unit": "NOS"}]},
        {"client_name": "Acme", "legal_name": "Acme Traders Private Limited",
         "gstin": "27AAACA1111A1Z4", "address": "Mumbai", "state_code": "27"},
        {"customer_name": "Beta Ltd", "gstin": "27AAACB2222B1Z1",
         "address": "Pune", "state_code": "27"},
    )
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        words = doc.pages[0].extract_words()

    anchor = [w for w in words if w["text"] == "HSN/SAC"]
    assert anchor, "the detail header was not rendered"
    top = anchor[0]["top"]
    row = sorted((w for w in words if abs(w["top"] - top) < 1),
                 key=lambda w: w["x0"])
    assert len(row) >= 8, f"only {len(row)} heading words: {[w['text'] for w in row]}"

    # Column edges, anchored on the HSN/SAC column whose left edge we can find
    # from the rendered word itself: it is the third column, left-aligned.
    edges = [0.0]
    for w in I._DETAIL_WIDTHS:
        edges.append(edges[-1] + w)
    left0 = anchor[0]["x0"] - I._LINE_TABLE_SIDE_PAD - edges[2]

    strays = []
    for w in row:
        lo, hi = w["x0"] - left0, w["x1"] - left0
        # Which column does this word START in?
        col = max(i for i in range(len(I._DETAIL_WIDTHS)) if edges[i] <= lo + 0.5)
        if hi > edges[col + 1] + 0.5:
            strays.append(
                f"{w['text']!r} starts in column {col} "
                f"({I._DETAIL_HEADER[col]!r}) and ends {hi - edges[col + 1]:.1f}pt "
                f"past its right edge"
            )
    assert not strays, (
        "a column heading is drawn outside its own column, over the heading "
        "beside it:\n  " + "\n  ".join(strays)
    )
