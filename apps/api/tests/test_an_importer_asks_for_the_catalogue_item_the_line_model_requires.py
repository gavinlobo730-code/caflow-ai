"""A bulk importer asks for the catalogue item the line model will demand (PRE-A-011).

WHAT WAS WRONG

`InvoiceLineIn`, `SalesInvoiceLineIn` and `PurchaseBillLineIn` (models/invoices.py)
make `service_catalogue_id` mandatory on every line: a line with no Product/Service
is a 422, "Product/Service is required on every line item". The two importers that
build those lines in the BROWSER (`lib/invoices/importMapping.ts` for sales invoices,
`lib/imports/mappers.ts` for purchase bills) marked the `product_service` column
`required: false` and built a line with no catalogue link when it was blank. So a
template filled in as documented, description and rate and GST but no Product/Service,
passed the column check, passed the mapper and showed a clean preview, and then
failed row by row at POST, in the final report, after the CA had already read
"ready to import". The four credit/debit-note importers had asked for the column
since they were written.

WHY THIS TEST IS IN PYTHON AND STATES THE RULE

The server owns the rule (the model validator), so the guard sits on the side that
owns it: a guard written in apps/web would assert the importer against a copy of
itself. The rule is not "these two files": it is that EVERY `product_service` column
anywhere in the browser's code that builds document lines is `required: true`, and
that no importer's built-line type lets a line through without its catalogue id. The
files are found by what they contain, so a seventh line importer written next year is
covered the day it exists.

The scanner reads TypeScript the way the sibling guards do
(test_the_browser_fallback_speaks_the_engines_vocabulary), but strips comments and
steps over string literals first, because the explanation of why a column was once
optional quotes the column.
"""
from __future__ import annotations

import pathlib
import re

import pydantic
import pytest

from models.invoices import InvoiceLineIn, PurchaseBillLineIn, SalesInvoiceLineIn

WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"
SCANNED = ("lib", "components", "app")

# The importers that exist today and have to be found. A floor and not a list: the
# scan finds files by content, and this stops it passing because it found nothing.
#   sales invoices, purchase bills, and the shared credit/debit-note line columns.
FLOOR = 3


# ── reading TypeScript ──────────────────────────────────────────────────────────

def _blank_comments(src: str) -> str:
    """Replace `//` and `/* */` comments with spaces, stepping over string literals.

    Spaces and not deletion, so offsets and line numbers survive. A `//` inside a
    string (a URL, a hint) is not a comment, which a one-line regex gets wrong.
    """
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in src[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _blank_strings(src: str) -> str:
    """Replace the CONTENT of every string literal with spaces (quotes kept).

    Comments must already be gone. Lets a brace or a key written inside a hint be
    ignored when matching braces.
    """
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(c + " " * (j - i - 1) + (src[j] if j < n else ""))
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _object_literals_keyed(src: str, key: str) -> list[str]:
    """The text of every object literal that has `key: "<key>"` as a property.

    `src` is comment-stripped. The property is found on the code with strings blanked
    (so a key quoted inside a hint is not one), the enclosing braces by matching on
    that same blanked text, and the slice is taken from the real text.
    """
    blanked = _blank_strings(src)
    found: list[str] = []
    for m in re.finditer(r'\bkey\s*:\s*(["\'`])', blanked):
        # `key:` is found on the code with strings blanked, so one quoted inside a
        # hint is not a property; its VALUE is then read from the real text at the
        # same offset (blanking keeps every offset).
        if src[m.end():m.end() + len(key) + 1] != key + m.group(1):
            continue
        start = m.start()
        depth, i = 0, start
        while i >= 0:
            ch = blanked[i]
            if ch == "}":
                depth += 1
            elif ch == "{":
                if depth == 0:
                    break
                depth -= 1
            i -= 1
        if i < 0:
            continue
        depth, j = 0, i
        while j < len(blanked):
            ch = blanked[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        found.append(src[i:j + 1])
    return found


def _is_required(literal: str) -> bool:
    """True when the literal sets `required: true` as a property of its own.

    Strings are blanked first so `required: true` quoted in a hint ("REQUIRED ...")
    does not count, and a nested literal's flag does not stand in for this one's.
    """
    code = _blank_strings(literal)
    # Take only the top level of the literal.
    depth, top = 0, []
    for ch in code:
        if ch == "{":
            depth += 1
            if depth == 1:
                top.append(ch)
                continue
        elif ch == "}":
            depth -= 1
        top.append(ch if depth <= 1 else " ")
    return re.search(r"\brequired\s*:\s*true\b", "".join(top)) is not None


def _source_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for sub in SCANNED:
        root = WEB / sub
        assert root.is_dir(), f"{root} has moved — update this guard, do not delete it"
        for p in root.rglob("*"):
            if p.suffix not in (".ts", ".tsx"):
                continue
            if "node_modules" in p.parts or ".next" in p.parts:
                continue
            if re.search(r"\.(test|spec)\.tsx?$", p.name):
                continue
            files.append(p)
    return sorted(files)


def _product_service_columns() -> list[tuple[pathlib.Path, str]]:
    found: list[tuple[pathlib.Path, str]] = []
    for p in _source_files():
        text = p.read_text(encoding="utf-8")
        if "product_service" not in text:
            continue
        for lit in _object_literals_keyed(_blank_comments(text), "product_service"):
            found.append((p, lit))
    return found


# ── the premise, from the models ────────────────────────────────────────────────

LINE_KWARGS = dict(description="Consulting", hsn_sac="9982", quantity=1,
                   rate_paise=100000, gst_rate_percent=18.0)


@pytest.mark.parametrize("model", [InvoiceLineIn, SalesInvoiceLineIn, PurchaseBillLineIn])
def test_the_server_refuses_a_line_with_no_catalogue_item(model):
    """The premise. If this stops being true the importer's requirement can relax,
    and the rule below should be re-read rather than left asserting a fact the
    server no longer holds."""
    with pytest.raises(pydantic.ValidationError, match="Product/Service is required"):
        model(**LINE_KWARGS)
    ok = model(service_catalogue_id="SVC-1", **LINE_KWARGS)
    assert ok.service_catalogue_id == "SVC-1"


# ── the rule, over the browser's code ───────────────────────────────────────────

def test_the_scan_finds_the_importers_it_is_about():
    found = _product_service_columns()
    assert len(found) >= FLOOR, (
        f"only {len(found)} product_service column literal(s) found under apps/web "
        f"({', '.join(sorted({str(p.relative_to(WEB)) for p, _ in found}))}); expected at "
        f"least {FLOOR} (sales invoice, purchase bill, credit/debit-note lines). "
        "The scan has stopped seeing them — fix the scan, do not lower the floor.")
    files = {p.name for p, _ in found}
    # The two importers this finding is about must be among them by name: finding
    # three of something else is not finding these.
    assert {"importMapping.ts", "mappers.ts"} <= files


def test_every_product_service_column_is_required():
    optional = [str(p.relative_to(WEB)) for p, lit in _product_service_columns()
                if not _is_required(lit)]
    assert not optional, (
        "a product_service column is not `required: true` in " + ", ".join(optional) +
        ". InvoiceLineIn / SalesInvoiceLineIn / PurchaseBillLineIn refuse a line with no "
        "service_catalogue_id, so an importer that lets the column be blank passes its "
        "preview and fails every such row at POST, in the final report (PRE-A-011). "
        "A name the catalogue lacks is the Resolve step's '+ Add'; a blank cell has "
        "nothing to resolve.")


def test_no_importer_built_line_may_leave_its_catalogue_id_optional():
    """The type is the second line of defence: with `service_catalogue_id?: string`
    a mapper edit that lets an unlinked line through compiles; with `: string` it
    does not. Asked of every file that declares a product_service column, so a new
    line importer's built-line type is held the day it is written."""
    offenders: list[str] = []
    for p in sorted({p for p, _ in _product_service_columns()}):
        code = _blank_strings(_blank_comments(p.read_text(encoding="utf-8")))
        for m in re.finditer(r"\bservice_catalogue_id\s*\?\s*:", code):
            line = code.count("\n", 0, m.start()) + 1
            offenders.append(f"{p.relative_to(WEB)}:{line}")
    assert not offenders, (
        "service_catalogue_id is declared optional in " + ", ".join(offenders) +
        " — in a file that builds document lines from a spreadsheet. The server "
        "demands it on every line; declare it `service_catalogue_id: string`.")


# ── the scanner reads what it claims (synthetic source) ─────────────────────────

def _cols(src: str) -> list[str]:
    return _object_literals_keyed(_blank_comments(src), "product_service")


def test_scanner_flags_an_optional_column_and_passes_a_required_one():
    optional = '{ key: "product_service", label: "P", required: false, hint: "x" }'
    required = '{ key: "product_service", label: "P", required: true, hint: "x" }'
    (o,), (r,) = _cols(optional), _cols(required)
    assert not _is_required(o)
    assert _is_required(r)


def test_scanner_treats_a_missing_flag_as_not_required():
    (lit,) = _cols('{ key: "product_service", label: "P" }')
    assert not _is_required(lit)


def test_scanner_does_not_read_the_word_required_out_of_a_hint():
    (lit,) = _cols('{ key: "product_service", label: "P", required: false, hint: "required: true on notes" }')
    assert not _is_required(lit)


def test_scanner_ignores_a_column_named_only_in_a_comment():
    assert _cols('// { key: "product_service", required: false }\nconst x = 1;') == []
    assert _cols('/* { key: "product_service", required: false } */ const x = 1;') == []


def test_scanner_is_not_fooled_by_a_url_in_a_string_that_looks_like_a_comment():
    src = 'const u = "http://x"; const c = { key: "product_service", label: "P", required: true };'
    (lit,) = _cols(src)
    assert _is_required(lit)


def test_scanner_reads_the_right_literal_in_an_array_of_columns():
    src = ('const C = [\n'
           '  { key: "a", required: true },\n'
           '  { key: "product_service", label: "P", required: false },\n'
           '  { key: "b", required: true },\n'
           '];')
    (lit,) = _cols(src)
    assert not _is_required(lit)
    assert 'key: "a"' not in lit and 'key: "b"' not in lit


def test_scanner_does_not_take_a_neighbours_flag():
    src = '[{ key: "product_service", label: "P" }, { key: "q", required: true }]'
    (lit,) = _cols(src)
    assert not _is_required(lit)


def test_optional_id_in_a_synthetic_built_line_type_is_seen():
    code = _blank_strings(_blank_comments("interface L { service_catalogue_id?: string; }"))
    assert re.search(r"\bservice_catalogue_id\s*\?\s*:", code)
    code = _blank_strings(_blank_comments("interface L { service_catalogue_id: string; }"))
    assert not re.search(r"\bservice_catalogue_id\s*\?\s*:", code)
