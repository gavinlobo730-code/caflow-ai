"""Six documents from one product look like one product, and the palette is the
product's own.

WHAT THIS PINS

    `services/pdf_style.py` is the only place a PDF colour is decided, and its
    values are the `ps.*` and `state.*` tokens in `apps/web/tailwind.config.ts`
    — the only palette in this repository that has been reasoned about, with a
    recorded contrast audit behind its ink scale.

    THE GUARD IS ON THE PYTHON SIDE DELIBERATELY. One written in `apps/web`
    would assert the browser against a copy of itself and pass whenever both
    drifted together, which is precisely what the Schedule III caption list did
    for months. `test_the_browser_fallback_speaks_the_engines_vocabulary.py`
    states the same rule for the same reason.

WHAT IT DOES NOT PIN, AND WHY

    Not font sizes, and not column widths. T5a-4b measured the invoice's nine
    columns against real worst-case content and found seven too narrow; those
    constants live in the invoice service with their own guard
    (`test_a_column_is_wide_enough_for_what_goes_in_it.py`). A rule here that
    also had opinions about size would be a second authority over the same
    numbers.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from services import pdf_style

API = Path(__file__).resolve().parents[1]
WEB = API.parents[1] / "apps" / "web"
TAILWIND = WEB / "tailwind.config.ts"

#: Every service that renders a PDF with reportlab.
PDF_SERVICES = sorted(
    p for p in (API / "services").glob("*_pdf_service.py")
)

#: Allowed to name a colour without going through the palette, each with its
#: reason. `pdf_page_furniture` is not here: it draws page numbers and takes
#: its colour from the palette like everything else.
_COLOUR_EXEMPT: dict[str, str] = {}


def _source(path: Path) -> str:
    """Source with comments and docstrings removed.

    A rule stated about CODE must not be satisfied — or broken — by prose. Both
    matter here: these modules explain their old palettes in comments, and a
    naive scan would read the explanation as the defect.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body[0].value.value = ""
    return ast.unparse(tree)


def test_the_services_exist_so_this_guard_is_not_vacuous():
    # The glob is a spelling; if a service is renamed this must fail rather
    # than silently check nothing.
    assert len(PDF_SERVICES) >= 6, [p.name for p in PDF_SERVICES]


@pytest.mark.parametrize("service", PDF_SERVICES, ids=lambda p: p.name)
def test_no_pdf_service_decides_its_own_colour(service: Path):
    """A hex literal in a renderer is a colour nobody reasoned about."""
    if service.name in _COLOUR_EXEMPT:
        pytest.skip(_COLOUR_EXEMPT[service.name])
    found = re.findall(r"#[0-9a-fA-F]{6}\b", _source(service))
    assert not found, (
        f"{service.name} names {sorted(set(found))} directly. Take the colour "
        f"from services/pdf_style, or add it there with its tailwind token if "
        f"the palette genuinely lacks the role."
    )


@pytest.mark.parametrize("service", PDF_SERVICES, ids=lambda p: p.name)
def test_no_pdf_service_reaches_for_a_bare_reportlab_colour(service: Path):
    """`colors.grey` is a fifth grey beside the palette's four ink steps."""
    src = _source(service)
    bare = set(re.findall(r"colors\.(?!HexColor|Color\b)([a-z][a-zA-Z]*)", src))
    # `white` is genuinely white on every screen and every printer; it is not a
    # palette decision and the palette re-exports it as C_WHITE anyway.
    bare.discard("white")
    assert not bare, (
        f"{service.name} uses reportlab's own {sorted(bare)}. The palette's ink "
        f"scale has four steps chosen against measured contrast; a stock "
        f"`colors.grey` is a fifth that agrees with none of them."
    )


def test_every_palette_value_names_its_token():
    """A colour with no token is one nobody reasoned about."""
    declared = {
        k for k, v in vars(pdf_style).items()
        if k.isupper() and isinstance(v, str) and re.fullmatch(r"#[0-9A-F]{6}", v)
    }
    assert declared == set(pdf_style._TOKEN_SOURCE), (
        f"declared but untokened: {sorted(declared - set(pdf_style._TOKEN_SOURCE))}; "
        f"tokened but not declared: {sorted(set(pdf_style._TOKEN_SOURCE) - declared)}"
    )


def _tailwind_tokens() -> dict[str, str]:
    """Every `ps.*` and `state.*` hex in the browser's token file.

    Read with a scanner rather than a TS parser, and keyed by SCALE so
    `ps.border` and a same-named key elsewhere cannot collide.
    """
    src = TAILWIND.read_text()
    out: dict[str, str] = {}
    for scale in ("ps", "state"):
        m = re.search(rf"^\s*{scale}:\s*\{{", src, re.M)
        assert m, f"no `{scale}:` scale in {TAILWIND.name}"
        depth, i = 0, m.end() - 1
        while i < len(src):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        block = src[m.end():i]
        for key, val in re.findall(
                r'["\']?([a-z-]+)["\']?\s*:\s*"(#[0-9A-Fa-f]{6})"', block):
            out[f"{scale}.{key}"] = val.upper()
    return out


def test_the_browser_token_file_is_readable_so_this_is_not_vacuous():
    tokens = _tailwind_tokens()
    # A floor, not a spelling: the two scales carry well over twenty values and
    # a scanner that silently matched nothing would make the next test pass.
    assert len(tokens) >= 20, sorted(tokens)
    assert "ps.ink" in tokens and "state.ready" in tokens


@pytest.mark.parametrize("name,token", sorted(pdf_style._TOKEN_SOURCE.items()))
def test_the_pdf_palette_is_the_products_palette(name: str, token: str):
    tokens = _tailwind_tokens()
    assert token in tokens, (
        f"pdf_style.{name} claims token `{token}`, which is not in "
        f"{TAILWIND.name}. Either the token was renamed or the claim is wrong."
    )
    assert getattr(pdf_style, name).upper() == tokens[token], (
        f"pdf_style.{name} is {getattr(pdf_style, name)} but `{token}` is now "
        f"{tokens[token]}. The browser moved and the documents did not — which "
        f"is the drift this guard exists to catch, not a reason to edit the "
        f"expectation."
    )


def test_the_header_fill_is_one_colour_across_every_document():
    """The defect this module was written for, stated directly.

    Four header fills across six documents: #0F172A, #1f2937, #1a3c5e and
    #1a1a1a — and the navy was on the year-end pack, the set a CA signs.
    """
    style = pdf_style.data_table_style(font_size=8, padding=3)
    backgrounds = [cmd for cmd in style if cmd[0] == "BACKGROUND"]
    assert backgrounds, style
    assert backgrounds[0][3] == pdf_style.C_INK


def test_a_table_style_will_not_invent_a_size():
    """`font_size` and `padding` have no defaults, so converting a service
    cannot silently renormalise what T5a-4b measured."""
    with pytest.raises(TypeError):
        pdf_style.data_table_style()  # type: ignore[call-arg]


def test_the_zebra_stripe_is_a_palette_colour():
    style = pdf_style.data_table_style(font_size=8, padding=3)
    zebra = [cmd for cmd in style if cmd[0] == "ROWBACKGROUNDS"]
    assert zebra, style
    assert zebra[0][3] == [pdf_style.C_SURFACE, pdf_style.C_PAGE_BG]


def test_a_verdict_reads_as_ready_or_problem_and_never_as_a_hover():
    ok = pdf_style.verdict_fill(0, True)
    bad = pdf_style.verdict_fill(0, False)
    assert ok[3] == pdf_style.C_READY_SURFACE
    assert bad[3] == pdf_style.C_PROBLEM_SURFACE
    # state.ready-hover means "a ready row under the cursor", which a printed
    # page does not have. Mapping by nearest hex would have chosen it.
    assert pdf_style.READY_SURFACE != "#DCFCE7"


def _fill_hex(value) -> str | None:
    """A reportlab fill as #RRGGBB, whatever colour space it was written in."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = (value, value, value)
    if len(value) == 4:                                   # CMYK
        cyan, magenta, yellow, black = value
        value = (1 - min(1.0, cyan + black),
                 1 - min(1.0, magenta + black),
                 1 - min(1.0, yellow + black))
    if len(value) < 3:
        return None
    return "#" + "".join(f"{round(v * 255):02X}" for v in value[:3])


def test_a_rendered_invoice_carries_the_palettes_header_and_not_the_old_one():
    """The claim above, read back out of a real document.

    Every other test here reads SOURCE. A service can import `pdf_style`,
    satisfy every scan, and still paint the old colour through a branch none of
    them look at — so this renders an invoice and reads the fills back. The
    invoice is the one chosen because it is the document a CLIENT'S CUSTOMER
    receives, and because its title colour has a live override (the firm's own
    branding accent, SALES-13) that must keep working.
    """
    pdfplumber = pytest.importorskip("pdfplumber")
    import io

    from services.invoice_pdf_service import build_sales_invoice_pdf

    lines = [{"description": f"Consultancy line {i}", "quantity": 1,
              "rate_paise": 100000, "taxable_paise": 100000,
              "gst_rate_percent": 18, "hsn_sac_code": "998311",
              "cgst_paise": 9000, "sgst_paise": 9000, "igst_paise": 0,
              "unit": "NOS"} for i in range(5)]
    pdf = build_sales_invoice_pdf(
        {"invoice_no": "INV/2026-27/0001", "invoice_date": "2026-06-10",
         "place_of_supply": "27", "total_paise": 590000, "taxable_paise": 500000,
         "cgst_paise": 45000, "sgst_paise": 45000, "igst_paise": 0,
         "total_gst_paise": 90000, "lines": lines},
        {"client_name": "Acme Traders", "legal_name": "Acme Traders Pvt Ltd",
         "gstin": "27AAACA1111A1Z4", "address": "Mumbai", "state_code": "27"},
        {"customer_name": "Beta Ltd", "gstin": "27AAACB2222B1Z1",
         "address": "Pune", "state_code": "27"},
    )

    fills = set()
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        for page in doc.pages:
            for rect in page.rects:
                got = _fill_hex(rect.get("non_stroking_color"))
                if got:
                    fills.add(got)

    assert fills, "no filled rectangle at all — the render changed shape"
    assert pdf_style.INK in fills, (
        f"the summary table's header is not ps.ink ({pdf_style.INK}); the "
        f"document paints {sorted(fills)}"
    )
    # The four header fills this replaced. Naming them individually means a
    # partial revert fails on the colour it reverted to, not on a set mismatch.
    for old in ("#1F2937", "#0F172A", "#1A3C5E", "#1A1A1A"):
        assert old not in fills, f"{old} is back on the invoice"
