"""The settings screens say only what the invoice PDF prints (POST-A-375).

WHAT WAS WRONG
    The Firm Branding screen saves a logo, a tagline, three colours, a font and four social links, and was headed "Customize your firm's
    visual identity across all documents and client communications". The invoice PDF (`services/invoice_pdf_service.py`), on the
    practice's own fee invoice and on no other document, reads THREE of them: the logo, the tagline and the PRIMARY colour (the colour of the
    title "TAX INVOICE"). Nothing reads the secondary colour, the accent colour, the font, the secondary logo or the social links, and the
    PDF is set in Helvetica whatever is chosen. The preview drew a band in the secondary colour and set its text in the chosen font, so it
    showed a band and a face the real invoice never has (the accent was taken out of it by POST-A-140); it also drew a full-width band in
    the primary colour and the invoice number in it, which the PDF does not have either.

    The independent reads of the fix found the same defect one screen over, and it is fixed with it: the Invoice Templates screen sold
    five layout styles ("bold typography", "ICAI branding guidelines and compliance fields", "numbers and key details only") that nothing
    draws (`template_type` is carried and no property of the layout reads it: only where the logo and the signature sit, and the header and
    footer spacing, change the PDF) and said a template sets "what the footer says" (the footer's words are on another screen); the
    settings hub said the branding is "applied to all client documents" and the layout styles were listed by name; the payment-details
    screen said its details "appear on every invoice" while a client's own invoice carries none of the practice's (`build_sales_invoice_pdf`
    takes no branding on purpose) and the block prints only when a bank name, an account number or a UPI ID is set (the QR picture inside
    it); and the logo the upload accepts (PNG, JPEG, SVG or WebP up to 5 MB) is printed only when it is a PNG, JPEG or WebP of up to
    2,000,000 bytes that the server can fetch within three seconds, because the PDF cannot draw an SVG and gives up on a larger file or a slow
    one, silently. The UPI QR picture is fetched by the same function with the same limits.

    The decision (Claude's, under the owner's standing instructions: it is true, it is safe, it is best for the product) is the one POST-A-140
    took for the accent: the settings stay, because the need behind them is real and a font or a colour band is a decision about a document
    that nobody has asked for, and each screen says in a plain sentence what is kept on file and what is printed. The sentences do not say
    "yet": a word that promises a build is a statement for the coming-soon register, and nothing is planned.

WHAT THIS HOLDS (the side that owns the fact reads the side that says it; a guard written in apps/web would assert the screen against a copy
of itself)
    * THE SET IS MEASURED. The `firm_branding` look columns that the invoice PDF does not read are exactly `KEPT_ON_FILE`. A column that
      starts being printed makes this fail until the screen's sentence for it is taken out, and a new column that nothing prints fails
      until the screen says so.
    * THE READERS ARE MEASURED. The firm's branding is read by the invoice PDF, by the screen that edits it and by nothing else in the API
      (a second reader that printed a column the screen says is kept on file would make that sentence false while the measurement above
      stayed green).
    * THE LAYOUT IS MEASURED. The properties of the layout the PDF reads are named, `template_type` is not one of them, and it is read by
      one reader; the Invoice Templates screen says the style is a name and describes no style.
    * THE PICTURES ARE MEASURED. The 2,000,000 bytes and the three seconds the screens say are the PDF's own limits; an SVG is a file the
      PDF cannot draw while a PNG, a JPEG and a WebP are; the payment block opens on a bank name, an account number or a UPI ID, the
      account holder and the IFSC code are printed only with the bank details, and the QR picture only inside the block.
    * THE SCREEN SAYS IT. Each kept-on-file setting has its sentence on the Branding screen, the preview applies no font and no secondary
      colour to the sample invoice and draws the primary colour once, on the title, and the screens that promised "all documents",
      "client communications", "client documents", "every invoice" or five named styles say what is true instead.

It reads four screens under apps/web, so the `browser contract` CI job selects it for a change that touches only the web app. WHAT IT DOES
NOT SEE: it measures what the PDF READS and not what it draws (a read left in place as dead code is not seen), it reads one source per
screen, and a new screen that makes the same claim is not found until someone adds it to the list.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
API = ROOT / "apps" / "api"
SCREENS = ROOT / "apps" / "web" / "app" / "settings"
BRANDING_PAGE = SCREENS / "branding" / "page.tsx"
TEMPLATES_PAGE = SCREENS / "invoice-templates" / "page.tsx"
HUB_PAGE = SCREENS / "page.tsx"
INVOICE_SETTINGS_PAGE = SCREENS / "invoice-settings" / "page.tsx"
PDF = API / "services" / "invoice_pdf_service.py"
MIGRATIONS = API / "migrations"

#: The look settings no document prints. Equality in both directions with what the measurement finds.
KEPT_ON_FILE = {"secondary_logo_url", "secondary_color", "accent_color", "font_family", "social_links"}
#: …and the three it does.
PRINTED = {"logo_url", "tagline", "primary_color"}
NOT_A_SETTING = {"id", "firm_id", "created_at", "updated_at"}


def _look_columns() -> set[str]:
    """The columns of `firm_branding`: migration 126's table and any later `ALTER TABLE … firm_branding ADD COLUMN`."""
    text = (MIGRATIONS / "126_firm_branding.sql").read_text(encoding="utf-8")
    body = re.search(r"CREATE TABLE IF NOT EXISTS public\.firm_branding \((.*?)\n\);", text, re.S)
    assert body, "migration 126 no longer creates firm_branding in the shape this reads"
    columns = {m.group(1) for m in re.finditer(r"(?m)^\s{4}([a-z_]+)\s+[A-Z]", body.group(1))}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        for m in re.finditer(r"(?is)ALTER TABLE\s+(?:IF EXISTS\s+)?(?:public\.)?firm_branding\s+ADD COLUMN\s+(?:IF NOT EXISTS\s+)?([a-z_]+)", path.read_text(encoding="utf-8")):
            columns.add(m.group(1))
    return columns - NOT_A_SETTING


def _brand_keys_in(node: ast.AST) -> list[str]:
    """Every string key read off the `brand` dict under `node`: `brand.get("x")` and `brand["x"]`, once per read."""
    keys: list[str] = []
    for n in ast.walk(node):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "brand"
                and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
            keys.append(n.args[0].value)
        if (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "brand"
                and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str)):
            keys.append(n.slice.value)
    return keys


def _keys_the_pdf_reads() -> set[str]:
    """Every string key read off the `brand` dict in the invoice PDF service: `brand.get("x")` and `brand["x"]`."""
    return set(_brand_keys_in(ast.parse(PDF.read_text(encoding="utf-8"))))


def _layout_properties_the_pdf_reads() -> set[str]:
    """Every attribute the invoice PDF reads off the layout it is given (`lay.<name>`)."""
    tree = ast.parse(PDF.read_text(encoding="utf-8"))
    return {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "lay"}


def _strip_comments(text: str) -> str:
    """Remove the comments of a TSX source, and nothing else: a line comment (whole-line or trailing), a block comment (mid-line or over several
    lines) and a JSX comment.

    It walks the source and knows when it is inside a string, because the Branding screen's file input has `accept="image/*"` and a URL is
    `https://…`: neither opens a comment, and a regex that treats `/*` or `//` as one deletes the code after it (the hazard
    `no-comment-or-string-hides-code-from-a-guard-by-opening-a-block.test.ts` holds on the web side). A quote that is not closed on its line ends
    with the line: in this code base JSX text spells an apostrophe `&apos;`, so a stray quote is text, and one must not hide the comments of the
    lines after it. A template literal may run over lines."""
    out: list[str] = []
    i, n, quote = 0, len(text), ""
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:                    # an escaped character belongs to the string
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote or (c == "\n" and quote != "`"):
                quote = ""
            i += 1
            continue
        two = text[i:i + 2]
        if two == "//":
            end = text.find("\n", i)
            i = n if end == -1 else end                    # the line break itself stays
            continue
        if two == "/*":
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if c in "'\"`":
            quote = c
        out.append(c)
        i += 1
    return "".join(out)


def _page(path: pathlib.Path) -> str:
    return _strip_comments(path.read_text(encoding="utf-8"))


def _preview(page: str) -> str:
    start = page.index("function BrandingPreview")
    return page[start:page.index("export default function BrandingPage", start)]


# ── the set is measured ─────────────────────────────────────────────────────────────────────────────
def test_the_look_settings_the_pdf_does_not_read_are_the_ones_the_screen_says_are_kept_on_file():
    columns = _look_columns()
    assert columns >= PRINTED | KEPT_ON_FILE, f"firm_branding lost a column this measures: {sorted((PRINTED | KEPT_ON_FILE) - columns)}"
    read = _keys_the_pdf_reads()
    assert PRINTED <= read, f"the invoice PDF no longer reads {sorted(PRINTED - read)}: the screen says it prints them"
    unread = columns - read
    assert unread == KEPT_ON_FILE, (
        f"the look settings no document prints are {sorted(unread)}, and the Branding screen says {sorted(KEPT_ON_FILE)} are kept on file. "
        "A setting that started to be printed needs its 'kept on file' sentence taken out; a new one that nothing prints needs one.")


def test_the_firms_branding_is_read_by_the_invoice_pdf_and_the_screen_that_edits_it_and_by_nothing_else():
    readers = set()
    for rel in ("services", "routers", "domain", "jobs", "core", "repositories"):
        for path in (API / rel).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if re.search(r"\.get_branding\(|[\"']firm_branding[\"']", text):
                readers.add(str(path.relative_to(API)).replace("\\", "/"))
    assert readers == {
        "services/invoice_pdf_service.py",         # the fee invoice
        "routers/branding.py",                     # the screen that edits it
        "repositories/branding_repository.py",     # the read itself
    }, (f"the firm's branding is read by {sorted(readers)}: a reader that prints a column the Branding screen says is kept on file makes that sentence false. "
        "Read it, then change the screen's sentence or name the reader here.")


# ── the layout is measured ────────────────────────────────────────────────────────────────────────────
def test_no_property_the_pdf_reads_of_the_layout_depends_on_the_style_name():
    read = _layout_properties_the_pdf_reads()
    assert read, "the measurement found no read of the layout in the invoice PDF: it has gone blind"
    assert "template_type" not in read, ("the invoice PDF now reads the template's style: the Invoice Templates screen says the style is only a name, "
                                         "and says where the logo and the signature sit does change the invoice")
    # the layout's own properties: none may be built from the style name
    tree = ast.parse((API / "domain" / "branding" / "invoice_layout.py").read_text(encoding="utf-8"))
    layout = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "InvoiceLayout")
    for fn in [f for f in layout.body if isinstance(f, ast.FunctionDef) and f.name not in ("to_dict", "statutory_notes")]:
        names = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self"}
        assert "template_type" not in names, f"InvoiceLayout.{fn.name} reads the style name: the screen's 'a style is only a name' is no longer true"


def test_the_invoice_template_is_read_by_the_invoice_pdf_and_by_nothing_that_builds_another_document():
    readers = set()
    for rel in ("services", "routers", "domain", "jobs", "core", "repositories"):
        for path in (API / rel).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if re.search(r"\b(layout_from_row|get_default_invoice_template)\(", text):
                readers.add(str(path.relative_to(API)).replace("\\", "/"))
    assert readers == {
        "services/invoice_pdf_service.py",         # the fee invoice
        "routers/branding.py",                     # the screen that lists the templates (their statutory notes)
        "repositories/branding_repository.py",     # the read itself
        "domain/branding/invoice_layout.py",       # the definition
    }, f"the invoice template is read by {sorted(readers)}: if another document reads it, the Invoice Templates sentence changes with it"


def test_a_clients_own_invoice_carries_none_of_the_practices_branding_or_payment_details():
    text = PDF.read_text(encoding="utf-8")
    body = text[text.index("def build_sales_invoice_pdf"):text.index("def get_invoice_pdf")]
    call = body[body.index("return _render_tax_invoice("):]
    assert "branding" not in call and "layout" not in call, "a client's own invoice is rendered with the practice's branding or layout: the payment-details sentence is no longer true"


# ── the pictures and the payment block are measured ────────────────────────────────────────────────
def test_the_logo_the_pdf_prints_is_a_png_jpeg_or_webp_within_its_limits():
    import services.invoice_pdf_service as pdf
    from PIL import Image as PilImage
    from reportlab.platypus import Image

    assert pdf._MAX_IMAGE_BYTES == 2_000_000, "the PDF's limit for a picture moved: the screens say 2,000,000 bytes"
    assert pdf._IMAGE_TIMEOUT_SECONDS == 3.0, "the PDF's wait for a picture moved: the screens say three seconds"
    for fmt in ("PNG", "JPEG", "WEBP"):
        blob = io.BytesIO()
        PilImage.new("RGB", (40, 20), (200, 30, 30)).save(blob, fmt)
        blob.seek(0)
        Image(blob)                                   # draws: raises if the PDF could not
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
    try:
        Image(io.BytesIO(svg))
    except Exception:
        pass
    else:
        raise AssertionError("the PDF can now draw an SVG: the screens say an SVG is left off the invoice")


def test_the_payment_block_opens_on_a_bank_name_an_account_number_or_a_upi_id_and_the_qr_picture_is_only_inside_it():
    tree = ast.parse(PDF.read_text(encoding="utf-8"))
    render = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_render_tax_invoice")

    def appends_a_line(node: ast.AST) -> bool:
        return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "append"
                   and isinstance(n.func.value, ast.Name) and n.func.value.id == "pay_lines" for n in ast.walk(node))

    gates = [n for n in render.body if isinstance(n, ast.If) and appends_a_line(n)]
    assert gates, "the measurement found no condition that opens the payment block: it has gone blind"
    opening = {k for g in gates for k in _brand_keys_in(g.test)}
    assert opening == {"bank_name", "account_number", "upi_id"}, (
        f"the payment block now opens on {sorted(opening)}: the Invoice Settings screen says a bank name, an account number or a UPI ID")
    bank = next(g for g in gates if "bank_name" in _brand_keys_in(g.test))
    inside_the_bank_details = _brand_keys_in(ast.Module(body=bank.body, type_ignores=[]))
    every_read = _brand_keys_in(render)
    for key in ("account_holder", "ifsc_code"):
        assert every_read.count(key) == inside_the_bank_details.count(key) >= 1, (
            f"'{key}' is printed outside the bank details: the screen says the account holder and the IFSC code are printed with them")
    # the block itself is `if pay_lines:` and the QR picture is read there and nowhere else
    block = [n for n in render.body if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "pay_lines"]
    assert len(block) == 1, "the payment block is no longer one `if pay_lines:`"
    assert _brand_keys_in(ast.Module(body=block[0].body, type_ignores=[])).count("upi_qr_url") == 1 == every_read.count("upi_qr_url"), (
        "the UPI QR picture is read outside the payment block: the screen says it is printed with the bank details or the UPI ID, and only then")
    assert "_remote_image(" in ast.get_source_segment(PDF.read_text(encoding="utf-8"), block[0]), (
        "the QR picture is no longer fetched by the function that has the logo's limits: the screen says it has the same ones")


# ── the screens say it ─────────────────────────────────────────────────────────────────────────────
def test_each_setting_that_is_kept_on_file_says_so_on_the_screen():
    page = _page(BRANDING_PAGE)
    for sentence in (
        "Secondary colour: kept on file. The invoice PDF does not print it.",
        "Accent colour: kept on file. The invoice PDF does not print it.",
        "kept on file. The invoice PDF is always set in Helvetica.",
        "Only the primary colour is printed (as the colour of the invoice title). The secondary and accent colours and the font are kept on file.",
        "Kept on file. No document prints these links.",
        "The other settings here are kept on file; no document prints them.",
    ):
        assert sentence in page, f"the Branding screen no longer says: {sentence}"
    for promise in ("no document prints them yet", "No document prints these links yet"):
        assert promise not in page, f"'{promise}': a 'yet' promises a build nobody has planned (and would need a row in the coming-soon register)"


def test_the_limits_the_screens_give_for_a_picture_are_the_pdfs_own():
    import services.invoice_pdf_service as pdf

    assert pdf._IMAGE_TIMEOUT_SECONDS == 3.0, "the PDF's wait for a picture moved: the screens say three seconds"
    size = f"up to {pdf._MAX_IMAGE_BYTES:,} bytes (about {round(pdf._MAX_IMAGE_BYTES / 1_000_000)} MB)"
    for name, page in (("Branding (the logo)", _page(BRANDING_PAGE)), ("Invoice Settings (the UPI QR picture)", _page(INVOICE_SETTINGS_PAGE))):
        assert size in page, f"the {name} sentence does not say '{size}', the PDF's own limit"
        assert "within three seconds" in page, f"the {name} sentence does not say the server waits three seconds for the picture"
        assert "An SVG, a larger file or one that does not answer in time" in page, f"the {name} sentence does not say what is left off"
    assert "PNG, JPEG or WebP" in _page(BRANDING_PAGE) and "PNG, JPEG or WebP" in _page(INVOICE_SETTINGS_PAGE)


def test_the_preview_is_the_top_of_the_invoice_pdf_and_draws_nothing_the_pdf_does_not():
    preview = _preview(_page(BRANDING_PAGE))
    assert "fontFamily" not in preview, "the preview sets text in the chosen font: the invoice PDF is always Helvetica"
    uses = [m.start() for m in re.finditer(r"branding\.secondary_color", preview)]
    assert len(uses) == 1, "the secondary colour is used for more than its swatch in the preview"
    around = preview[max(0, uses[0] - 200):uses[0] + 40]
    assert 'aria-hidden="true"' in around and "backgroundColor: branding.secondary_color" in around, "the secondary colour is not drawn as a swatch"
    # the primary colour is the colour of the title and of nothing else: no band, no coloured invoice number
    assert preview.count("branding.primary_color") == 1, "the primary colour is drawn somewhere the PDF does not draw it (the PDF uses it for the title only)"
    assert re.search(r'<p className="text-base font-bold" style=\{\{ color: branding\.primary_color \}\}>TAX INVOICE</p>', preview), "the primary colour is not the colour of the title"
    assert "backgroundColor: branding.primary_color" not in preview, "the preview draws a band in the primary colour: the PDF has none"
    assert "branding.tagline ||" not in preview, "the preview prints a tagline the firm did not set: the PDF prints none then"
    assert "branding.tagline &&" in preview, "the preview no longer prints the tagline a firm set"
    # the sample is in the PDF's own words and currency: its labels are "Bill To" and "Invoice No", and its amounts are "Rs." (Helvetica has no rupee sign)
    assert "₹" not in preview, "the sketch shows a rupee sign: the invoice PDF prints 'Rs.' because its font has no rupee glyph"


def test_neither_screen_promises_a_document_that_does_not_read_it():
    branding = _page(BRANDING_PAGE)
    for promise in ("all documents", "client communications", "client documents"):
        assert promise not in branding, f"the Branding screen promises '{promise}': only the practice's own fee invoice reads it"
    hub = _page(HUB_PAGE)
    assert "applied to all client documents" not in hub, "the settings hub says the branding is applied to all client documents"
    assert "Layout styles: Classic, Modern, Professional CA, Corporate, Minimal." not in hub, "the settings hub lists five layout styles by name"
    assert "Logo, tagline and primary colour for your practice&apos;s own invoices; the other settings are kept on file." in hub
    assert "Where the logo and the signature sit on your practice&apos;s own invoices." in hub
    settings = _page(INVOICE_SETTINGS_PAGE)
    assert "appear on every invoice" not in settings, "the payment details are said to appear on every invoice: a client's own invoice carries none"
    assert "A client&apos;s own invoices do not carry them." in settings
    assert "when a bank name, an account number or a UPI ID is filled in" in settings, "the payment-details sentence no longer says when the block is printed"
    assert "The account holder and the IFSC code are printed with the bank details, and the QR picture with either." in settings


def test_the_invoice_templates_screen_sells_no_style_and_says_what_changes_the_invoice():
    templates = _page(TEMPLATES_PAGE)
    for promise in ("engagement documents", "bold typography", "ICAI branding guidelines", "numbers and key details only", "Traditional layout", "Formal layout",
                    "what the footer says", "Layout Style"):
        assert promise not in templates, f"the Invoice Templates screen still says '{promise}'"
    assert "desc:" not in templates and "info.desc" not in templates, "a layout style has a description again: no style changes how the invoice is drawn"
    assert "The style is a name for the template and does not change how the invoice is drawn. Where the logo and the signature sit does." in templates
    assert "Choose where the logo and the signature sit on the invoices your practice issues to its own clients. Engagement letters and your clients' own invoices do not use it." in templates
    assert "A template sets where the logo and the signature sit on the invoices your practice issues to its own clients." in templates


# ── the guard is not blind ────────────────────────────────────────────────────────────────────────────
def test_the_measurement_sees_a_key_read_by_get_and_by_subscript_and_a_layout_property(tmp_path, monkeypatch):
    p = tmp_path / "pdf.py"
    p.write_text('def f(brand, lay):\n    a = brand.get("x")\n    b = brand["y"]\n    c = other.get("z")\n    return a, b, c, lay.logo_alignment, lay.template_type, other.nope\n', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "PDF", p)
    assert _keys_the_pdf_reads() == {"x", "y"}
    assert _layout_properties_the_pdf_reads() == {"logo_alignment", "template_type"}


def test_the_preview_cutter_finds_the_preview_and_stops_before_the_page():
    page = _page(BRANDING_PAGE)
    preview = _preview(page)
    assert preview.startswith("function BrandingPreview") and "export default function BrandingPage" not in preview and "Secondary colour" in preview


def test_the_comment_stripper_removes_comments_and_only_comments():
    source = (
        'const a = 1; // a trailing line comment\n'
        'const b = 2; /* a mid-line block comment */ const c = 3;\n'
        '{/* a JSX comment */}<p>words in JSX</p>\n'
        '<input accept="image/*" /> <p>words after the accept</p>\n'
        'const url = "https://example.com/x"; const d = 4;\n'
        'const e = `a // b ${f}`; const g = 5;\n'
        '/* a block comment\n   over two lines */\n'
        '<p>Don&apos;t lose this</p>\n'
        "<p>a stray apostrophe: don't</p>\n"
        '// a whole-line comment\n'
        '<p>last words</p>\n'
    )
    out = _strip_comments(source)
    for gone in ("a trailing line comment", "a mid-line block comment", "a JSX comment", "a block comment", "over two lines", "a whole-line comment"):
        assert gone not in out, f"the stripper left a comment: {gone}"
    for kept in ("const a = 1;", "const c = 3;", "words in JSX", 'accept="image/*"', "words after the accept", "https://example.com/x", "const d = 4;",
                 "a // b", "const g = 5;", "Don&apos;t lose this", "don't", "last words"):
        assert kept in out, f"the stripper removed what is not a comment: {kept}"


def test_a_sentence_moved_into_a_trailing_comment_is_not_on_the_screen():
    # the hole a reviewer found: a sentence deleted from the screen and left in a comment at the end of a code line counted as present
    sentence = "Kept on file. No document prints these links."
    page = f'<p>{sentence}</p>\nconst FONTS = ["Inter"];'
    assert sentence in _strip_comments(page)
    hidden = f'<p></p>\nconst FONTS = ["Inter"]; // {sentence}'
    assert sentence not in _strip_comments(hidden)
    block = f'<p></p>\nconst FONTS = ["Inter"]; /* {sentence} */'
    assert sentence not in _strip_comments(block)
