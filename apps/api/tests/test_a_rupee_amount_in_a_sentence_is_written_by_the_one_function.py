"""A rupee amount inside a sentence a person reads is written by `domain/money_sentence`, and by nothing that glues a unit to a
formatter or divides by a hundred itself (POST-A-346).

WHAT WAS WRONG
    `domain/money_text` says how a figure is GROUPED and deliberately emits no unit (every PDF service calls it). Every sentence
    therefore wrote its own unit: 73 modules glued `"₹"` to `rupees_paise(x)` (which writes "₹-5,000.00" for a negative), 58 glued it
    to `whole_rupees(x)` (which truncates and writes "₹-5"), thirty-odd modules defined a private `_rupees`/`_rs`/`_r`/`_inr`
    whose negative came out five ways ("Rs -5,000.00", "-Rs 5,000.00", "Rs. -5,000.00", "-₹5,000.00", or the sign dropped), and
    about fifteen sentences divided by a hundred themselves: `₹{gap // 100}` (paise dropped), `₹{x / 100:.2f}` (ungrouped, "₹-1.50"
    for a negative), `'₹{:,.2f}'.format(x / 100)` (Western grouping, "386,880"), a local formatter that never groups, a private loop that
    groups by regular expression. The existing grouping guard needed a comma in the format spec, so `{x // 100}` and
    `{x / 100:.2f}` passed it.

    The first review of the sweep then found a THIRD formatter the guard did not know: `amount_words.indian_rupees` (whole rupees,
    "-" inside the sign), glued to the unit at 13 sites in ten modules, and two private copies of the grouping that avoided the
    authority altogether (`divmod(x, 100)` and a regular expression), so the guard now derives the helpers rather than listing them.

WHAT IS HELD
    * (the rule) no production module puts a unit (the rupee sign, "Rs", "Rs.", "minus") directly before a placeholder that calls
      one of the raw formatters (`rupees_paise`, `whole_rupees`, `indian_rupees`, `indian_digits`, `group_indian`) OR any function of
      the tree that calls one of them, or concatenates one to their output. Call `rupee_text(paise, unit)` or
      `rupee_whole_text(paise, unit)`. The allowlist is EMPTY;
    * (the rule) no production module splits paise with `divmod(x, 100)` except the basis-points one named below;
    * (the rule) no text placeholder divides by a hundred except the three families that are not rupees, each named: basis points
      shown as a percent, a financial year's two-digit label, and a file written for a program to read (no grouping on purpose).
      A new one fails until it is either converted or named here with its reason;
    * (the detector) each spelling is shown, and what it must pass.
"""
import ast
import functools
import pathlib
import re

import pytest

API = pathlib.Path(__file__).resolve().parents[1]
ROOTS = ("domain", "routers", "services", "repositories", "core", "jobs", "models", "middleware")
AUTHORITIES = {"domain/money_text.py", "domain/money_sentence.py"}
#: The raw formatters. A unit glued to one of these writes "₹-5" for a negative figure, and to the whole-rupee ones "₹-0" for a few paise.
FORMATTERS = {"rupees_paise", "whole_rupees", "indian_rupees", "indian_digits", "group_indian"}
UNIT_ENDINGS = ("₹", "Rs", "Rs.", "Rs. ", "Rs ", "minus ", "-₹", "-Rs", "-Rs ")
DIVIDES_BY_100 = re.compile(r"(/|//|%)\s*100\b")

#: (file, expression) -> why this division by a hundred is not a rupee amount in a sentence. Meant to stay small; a rupee figure
#: never belongs here.
ALLOWED_DIVISIONS: dict[tuple[str, str], str] = {}
_BPS = "basis points shown as a percent, not money"
_FY = "a financial year's two-digit label (2026-27), not money"
_FILE = "a file a program reads (a register, a bank upload, a return): no grouping on purpose, so a parser reads one rupee as one"
for _file, _exprs, _why in (
    ("domain/ai/statutory_brief.py", ("r.individual_rate_bps / 100", "r.company_rate_bps / 100"), _BPS),
    ("domain/banking/candidate_search.py", ("hit.tds_rate_bps / 100",), _BPS),
    ("domain/banking/matcher.py", ("whole + frac / 100",), _BPS),
    ("domain/gst/late_filing.py", ("SECTION_50_3_NOTIFIED_RATE_BPS / 100", "SECTION_50_3_CEILING_BPS / 100"), _BPS),
    ("domain/income_tax/house_property.py", ("p.share_bps / 100",), _BPS),
    ("domain/inventory_service.py", ("gst_rate_bps / 100",), _BPS),
    ("domain/payroll/bonus.py", ("rate_bps / 100", "rate / 100"), _BPS),
    ("domain/payroll/ecr.py", ("rate_bps // 100", "rate_bps % 100"), _BPS),
    ("domain/payroll/perquisites.py", ("bps / 100", "sbi_rate_bps_on_first_day / 100"), _BPS),
    ("domain/sales/late_interest.py", ("bps // 100", "bps % 100"), _BPS),
    ("routers/assistant.py", ("r.individual_rate_bps / 100", "r.company_rate_bps / 100"), _BPS),
    ("services/vendor_tds.py", ("cert.rate_bps / 100",), _BPS),
    ("domain/demo/fixture.py", ("(fy_year + 1) % 100",), _FY),
    ("domain/income_tax/section_43b_h.py", ("(d.year + 1) % 100", "d.year % 100"), _FY),
    ("domain/tds/undeposited.py", ("(start + 1) % 100",), _FY),
    ("services/form_3cd_service.py", ("(int(start[:4]) + 1) % 100",), _FY),
    ("services/payroll_report_service.py", ("str((start + 1) % 100).zfill(2)",), _FY),
    ("domain/payroll/annexure2.py", ("p // 100", "p % 100"), _FILE),
    ("domain/payroll/bank_advice.py", ("p // 100", "p % 100"), _FILE),
    ("domain/payroll/form24q.py", ("p // 100", "p % 100"), _FILE),
    ("domain/payroll/register.py", ("p // 100", "p % 100"), _FILE),
    ("services/bank_reconciliation_service.py", ("p / 100",), _FILE),
):
    for _e in _exprs:
        ALLOWED_DIVISIONS[(_file, _e)] = _why


#: (file, argument) -> why this `divmod(x, 100)` is not a rupee amount in a sentence.
ALLOWED_DIVMOD: dict[tuple[str, str], str] = {
    ("domain/banking/matcher.py", "int(rate_bps)"): "basis points shown as a percent, not money",
}


def _callee(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        f = node.func
        return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
    return ""


@functools.lru_cache(maxsize=None)
def helper_names(source: str) -> frozenset[str]:
    """The functions of one module whose body calls a raw formatter: `_rupees`, `_r`, `_fmt_rupees` and whatever the next author calls it."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(_callee(c) in FORMATTERS for c in ast.walk(node) if isinstance(c, ast.Call)):
                names.add(node.name)
    return frozenset(names)


@functools.lru_cache(maxsize=None)
def glued_units(source: str, helpers: frozenset[str] = frozenset()) -> list[int]:
    """Lines where a unit sits directly before a placeholder that calls a raw formatter or one of `helpers`, or is concatenated to it."""
    bad = FORMATTERS | set(helpers)
    tree = ast.parse(source)
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            parts = node.values
            for i, v in enumerate(parts):
                if (isinstance(v, ast.FormattedValue) and _callee(v.value) in bad and i > 0
                        and isinstance(parts[i - 1], ast.Constant) and isinstance(parts[i - 1].value, str)
                        and parts[i - 1].value.endswith(UNIT_ENDINGS)):
                    hits.append(node.lineno)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            for a, b in ((node.left, node.right), (node.right, node.left)):
                if (isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.strip() in {"₹", "Rs", "Rs.", "-₹"}
                        and _callee(b) in bad):
                    hits.append(node.lineno)
    return hits


@functools.lru_cache(maxsize=None)
def divmods_by_100(source: str) -> list[tuple[int, str]]:
    """(line, first argument) of each `divmod(x, 100)`: a hand-made split of paise into rupees and a remainder."""
    out = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and _callee(node) == "divmod" and len(node.args) == 2
                and isinstance(node.args[1], ast.Constant) and node.args[1].value == 100):
            out.append((node.lineno, ast.unparse(node.args[0])))
    return out


_LINES = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")


def _segment(lines: list[str], node: ast.AST) -> str:
    """The source text of `node`, as `ast.get_source_segment` returns it, from lines split once (that function re-splits the whole
    module on every call, which made this scan quadratic)."""
    first, last = node.lineno - 1, node.end_lineno - 1
    if first == last:
        return lines[first].encode()[node.col_offset:node.end_col_offset].decode()
    head = lines[first].encode()[node.col_offset:].decode()
    tail = lines[last].encode()[:node.end_col_offset].decode()
    return "".join([head, *lines[first + 1:last], tail])


@functools.lru_cache(maxsize=None)
def divisions_in_text(source: str) -> list[tuple[int, str]]:
    """(line, expression) of each f-string placeholder or `.format` argument that divides by a hundred."""
    tree = ast.parse(source)
    lines = _LINES.findall(source)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        exprs: list[str] = []
        if isinstance(node, ast.JoinedStr):
            exprs = [_segment(lines, v.value) for v in node.values if isinstance(v, ast.FormattedValue)]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            exprs = [_segment(lines, a) for a in node.args]
        for e in exprs:
            if DIVIDES_BY_100.search(e):
                out.append((node.lineno, " ".join(e.split())))
    return out


def _production_modules() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for root in ROOTS:
        found += sorted((API / root).rglob("*.py"))
    return [p for p in found if p.relative_to(API).as_posix() not in AUTHORITIES]


def test_the_scan_still_reaches_the_tree():
    modules = _production_modules()
    assert len(modules) > 300
    assert sum("rupee_text(" in p.read_text() for p in modules) >= 40, "the sweep has been reverted, or the scan reads nothing"


def _tree_helpers() -> frozenset[str]:
    names: set[str] = set()
    for p in _production_modules():
        names |= helper_names(p.read_text())
    return frozenset(names)


def test_no_module_glues_a_unit_to_the_formatter():
    helpers = _tree_helpers()
    found = []
    for p in _production_modules():
        for line in glued_units(p.read_text(), helpers):
            found.append(f"{p.relative_to(API).as_posix()}:{line}")
    assert not found, (
        "a unit is glued to a raw formatter or to a helper that calls one, which writes it before a minus sign ('₹-5,000.00'). "
        "Call domain.money_sentence.rupee_text(paise, unit) / rupee_whole_text(paise, unit): " + ", ".join(found))


def test_no_module_splits_paise_by_hand():
    found = []
    for p in _production_modules():
        rel = p.relative_to(API).as_posix()
        for line, arg in divmods_by_100(p.read_text()):
            if (rel, arg) not in ALLOWED_DIVMOD:
                found.append(f"{rel}:{line}  divmod({arg}, 100)")
    assert not found, (
        "paise are split into rupees and a remainder by hand, which is how a private copy of the grouping starts (two were found "
        "that way). Call domain.money_sentence / domain.money_text: " + "; ".join(found))


def test_every_allowed_divmod_still_exists_so_the_list_only_shrinks():
    present = set()
    for p in _production_modules():
        rel = p.relative_to(API).as_posix()
        present |= {(rel, arg) for _, arg in divmods_by_100(p.read_text())}
    stale = sorted(set(ALLOWED_DIVMOD) - present)
    assert not stale, f"these allowed divmods no longer exist and must be deleted from the list: {stale}"


def test_no_text_placeholder_divides_a_rupee_figure_by_a_hundred():
    found = []
    for p in _production_modules():
        rel = p.relative_to(API).as_posix()
        for line, expr in divisions_in_text(p.read_text()):
            if (rel, expr) not in ALLOWED_DIVISIONS:
                found.append(f"{rel}:{line}  {{{expr}}}")
    assert not found, (
        "a placeholder divides by a hundred inside text. A rupee amount is written by domain.money_sentence (it groups the Indian "
        "way, keeps the paise and writes a negative as 'minus ₹x'); if this is not rupees (basis points, a financial-year label, a "
        "file a program reads) name it in ALLOWED_DIVISIONS with the reason: " + "; ".join(found))


def test_every_allowed_division_still_exists_so_the_list_only_shrinks():
    present = set()
    for p in _production_modules():
        rel = p.relative_to(API).as_posix()
        present |= {(rel, expr) for _, expr in divisions_in_text(p.read_text())}
    stale = sorted(set(ALLOWED_DIVISIONS) - present)
    assert not stale, f"these allowed divisions no longer exist and must be deleted from the list: {stale}"


# ── the detector ────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("source", [
    'x = f"short by ₹{rupees_paise(d)}"',
    'x = f"short by Rs {rupees_paise(d)}"',
    'x = f"short by Rs.{whole_rupees(d)}"',
    'x = f"it is minus {rupees_paise(d)}"',
    'x = "₹" + rupees_paise(d)',
    'x = whole_rupees(d) + "₹"[:0] or "Rs " + whole_rupees(d)',
    'x = f"AIS reports ₹{indian_rupees(d)}"',
    'x = f"differs by ₹{indian_digits(d)}"',
    'x = f"fee ₹{group_indian(str(d))}"',
])
def test_the_detector_sees_each_gluing(source):
    assert glued_units(source), source


def test_the_detector_follows_a_private_helper_that_calls_a_formatter():
    helper = "def _r(p):\n    return f'{rupees_paise(p)}'\n"
    use = 'x = f"short by ₹{_r(d)}"'
    assert helper_names(helper) == frozenset({"_r"})
    assert glued_units(use) == [], "without the helper set the use is invisible, which is why the set is derived"
    assert glued_units(use, frozenset({"_r"})) == [1]


@pytest.mark.parametrize("source,count", [
    ("whole, part = divmod(abs(p), 100)", 1), ("x = divmod(int(rate_bps), 100)", 1), ("x = divmod(p, 1000)", 0), ("x = divmod(a, b)", 0),
])
def test_the_divmod_detector(source, count):
    assert len(divmods_by_100(source)) == count


@pytest.mark.parametrize("source", [
    'x = f"short by {rupee_text(d)}"',
    'x = f"short by {rupees_paise(d)} rupees"',
    'x = f"₹{some_other(d)}"',
    'x = f"{rupees_paise(d)}"',
    'x = rupee_text(d, "Rs ")',
])
def test_the_detector_passes_what_is_not_the_defect(source):
    assert not glued_units(source), source


@pytest.mark.parametrize("source,count", [
    ('x = f"₹{gap // 100}"', 1), ('x = f"₹{amount / 100:.2f}"', 1), ('x = "₹{:,.2f}".format(p / 100)', 1),
    ('x = f"{p // 100}.{p % 100:02d}"', 2), ('x = f"{rate_bps / 100:g}%"', 1),
    ('x = f"{rupee_text(p)}"', 0), ('x = f"{p / 1000}"', 0), ('y = p / 100', 0),
])
def test_the_division_detector_reads_each_spelling(source, count):
    assert len(divisions_in_text(source)) == count


def test_a_rupee_figure_is_never_on_the_allowed_list():
    banned = ("paise", "amount", "gap", "balance", "relief", "total")
    names = [e for (_, e) in ALLOWED_DIVISIONS if any(w in e.lower() for w in banned) and "bps" not in e.lower()]
    assert not names, f"an allowed division reads as money: {names}"
