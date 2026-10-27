"""A sentence written for a person says an amount in rupees, grouped the Indian way, and never as a count of paise.

THE DEFECT
    Found on 27-10-2026 in a browser, on the Part A screen of an ITR-6: "The fixed-asset register's net block differs from the
    ledger's by 1559996 paise for tangible assets and -1559996 paise for intangible assets". A chartered accountant reads rupees.
    Fifteen lakh, fifty-nine thousand, nine hundred and ninety-six paise is a sum nobody can read at a glance, and "-1559996" is not
    how anyone writes a figure they are about to put in a return. The same shape was in sixty-four sentences across thirty-one modules,
    most of them the explanations a computation gives for its figure (the presumptive schemes, the minimum-tax and interest
    workings, the GSTR-4 and GSTR-8 checks), the refusals a posting or a receipt answers a CA with (an allocation larger than the
    payment, an entry that does not balance) and the notes that say why a year-end statement does not tie.

    `domain/money_text` already says how a rupee figure is written for a person (CLAUDE.md, "A RUPEE FIGURE WRITTEN FOR A PERSON IS
    GROUPED THE INDIAN WAY"): the grouping is universal and the unit is the caller's, which on a screen, in an email and in a 422 is
    the rupee sign (`domain/money_sentence.rupee_text` writes it, and "minus" for a negative amount). This was that rule's other half: nothing stopped a sentence from skipping the formatter and naming the unit "paise".

WHAT IS HELD
    * (the rule) no module of the API puts a formatted value directly before the word "paise" in a string it builds (an f-string, a
      `.format` template or a `%` template). A log line is exempt: a developer reads it, and the unit helps there. Data keys, column
      names and a number of paise a message says the CA must type ("a positive whole number of paise") are not f-strings with a
      value before the word and are not touched. The allowlist is EMPTY.
    * (the detector) it sees each spelling, including an f-string that is split across two lines so that the value ends one line and
      "paise" begins the next, which is how five of the sixty-four were written, and it passes a log line and a message that has no
      value before the word;
    * (the behaviour) a representative sentence from each family now carries ₹ and Indian grouping, and a negative figure is written
      "minus ₹…" and never "₹-…".
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
SKIP_TOP = {"tests", "migrations", "scripts", "venv", ".venv", "node_modules"}

#: Production code that may name the unit after a value, with the reason. EMPTY, and meant to stay so.
ALLOWED: dict[tuple[str, int], str] = {}

_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}
_TEMPLATE = re.compile(r"(\{[^{}]*\}|%[-+ 0-9.]*[sdif])\s?paise\b")
_WORD_AFTER_VALUE = re.compile(r"^\s?paise\b")


def _is_log_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "print"
    if isinstance(func, ast.Attribute) and func.attr in _LOG_METHODS:
        base = ast.unparse(func.value).lower()
        return "log" in base
    return False


def paise_after_a_value(source: str) -> list[int]:
    """The line of each string built here that puts a value straight before the word "paise", other than in a log call."""
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            parts = node.values
            found = any(
                isinstance(v, ast.FormattedValue) and i + 1 < len(parts) and isinstance(parts[i + 1], ast.Constant)
                and isinstance(parts[i + 1].value, str) and _WORD_AFTER_VALUE.match(parts[i + 1].value)
                for i, v in enumerate(parts))
            if found and not _is_log_call(parents.get(node)):
                hits.append(node.lineno)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "paise" in node.value:
            # A plain template ("{} paise", "%d paise") that is formatted later. A JoinedStr's own constants are handled above, and
            # are skipped here because their parent is the JoinedStr.
            if isinstance(parents.get(node), ast.JoinedStr):
                continue
            if _TEMPLATE.search(node.value) and not _is_log_call(parents.get(node)) and not _is_log_call(parents.get(parents.get(node))):
                hits.append(node.lineno)
    return hits


def _production_modules() -> list[Path]:
    return [p for p in sorted(API.rglob("*.py")) if not (set(p.relative_to(API).parts[:1]) & SKIP_TOP)]


def test_no_sentence_names_a_count_of_paise():
    found: list[str] = []
    for path in _production_modules():
        rel = path.relative_to(API).as_posix()
        for line in paise_after_a_value(path.read_text()):
            if (rel, line) not in ALLOWED:
                found.append(f"{rel}:{line}")
    assert not found, (
        "a string built for a person puts a value straight before the word 'paise'. Write the amount as "
        "{rupee_text(x)} (domain.money_sentence), so it is rupees, grouped the Indian way and never '₹-': " + ", ".join(found))


def test_the_probe_still_reaches_the_tree_it_is_about():
    modules = _production_modules()
    assert len(modules) > 300, "the scan found too few modules to be about the API"
    assert any(p.name == "books_schedules.py" for p in modules)


# ── the detector, shown each spelling it must see and each it must pass ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("source", [
    'x = f"short by {diff} paise"',
    'x = f"a {a} paise and a {b} paise"',
    'x = (f"carries IGST ({igst} "\n     f"paise) rather than CGST")',
    'x = "short by {} paise".format(diff)',
    'x = "short by {d} paise".format(d=diff)',
    'x = "short by %d paise" % diff',
    'def f():\n    raise ValueError(f"over by {total} paise")',
    'x = dict(detail=f"over by {total} paise")',
])
def test_the_detector_sees_each_spelling(source):
    assert paise_after_a_value(source), source


@pytest.mark.parametrize("source", [
    'x = "Each allocation is a positive whole number of paise."',
    'x = f"the amount_paise column holds paise, row {i}"',
    'x = f"{rupees_paise(diff)} short"',
    '_logger.warning(f"posted {total} paise for {client}")',
    'logger.info(f"posted {total} paise")',
    'print(f"debug: {total} paise")',
    'x = f"paise are the unit of {name}"',
])
def test_the_detector_passes_what_is_not_the_defect(source):
    assert not paise_after_a_value(source), source


# ── the behaviour ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_trial_balance_that_does_not_balance_is_told_in_rupees():
    from domain.accounting.trial_balance import TrialBalanceError, TrialBalanceRow, validate
    rows = [TrialBalanceRow(account_name="Cash", account_type="asset", debit_paise=12_34_567_00, credit_paise=0),
            TrialBalanceRow(account_name="Capital", account_type="equity", debit_paise=0, credit_paise=10_00_000_00)]
    with pytest.raises(TrialBalanceError) as exc:
        validate(rows)
    text = str(exc.value)
    assert "debits exceed credits by ₹2,34,567.00" in text, text
    assert "total debits ₹12,34,567.00" in text.lower() and "total credits ₹10,00,000.00" in text.lower(), text
    assert "paise" not in text


def test_a_negative_net_amount_is_written_minus_and_never_with_the_sign_inside_the_rupee_sign():
    from domain.gst.gstr8 import SupplyRow, _row_problems
    row = SupplyRow(supplier_gstin="27AABCU9603R1ZM", place_of_supply="27", gross_registered_paise=0, returns_registered_paise=1_500_00,
                    gross_unregistered_paise=0, returns_unregistered_paise=0, igst_paise=0, cgst_paise=90_00, sgst_paise=90_00)
    joined = " ".join(_row_problems(row, "072026", False))
    assert "Net amount liable is minus ₹1,500.00 (nil or negative) but ₹180.00 of tax is recorded as collected." in joined, joined
    assert "₹-" not in joined and "paise" not in joined


def test_the_presumptive_workings_carry_the_rupee_sign_and_indian_grouping():
    from domain.income_tax.presumptive import compute_44ad
    out = compute_44ad(turnover_paise=3_00_00_000_00, digital_turnover_paise=1_00_00_000_00, fy="2025-26", assessee_kind="individual")
    text = " ".join(out.workings + out.reasons)
    assert "₹1,00,00,000.00 received through prescribed banking modes" in text, text
    assert "paise" not in text


def test_a_difference_between_two_figures_is_never_written_as_a_negative_count():
    from domain.income_tax.books_schedules import _register_against_ledger
    assert _register_against_ledger(1_559_996) == "₹15,599.96 higher"
    assert _register_against_ledger(-1_559_996) == "₹15,599.96 lower"
    assert _register_against_ledger(0) == "the same"


# ── the two helpers every sentence now goes through ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("paise,expected", [
    (0, "₹0.00"), (None, "₹0.00"), (1, "₹0.01"), (150, "₹1.50"), (12_34_567_50, "₹12,34,567.50"),
    (-150, "minus ₹1.50"), (-1, "minus ₹0.01"), (-12_34_567_50, "minus ₹12,34,567.50"),
])
def test_rupee_text_writes_the_sign_and_says_minus_for_a_negative_amount(paise, expected):
    from domain.money_sentence import rupee_text
    assert rupee_text(paise) == expected
    assert "₹-" not in rupee_text(paise)


@pytest.mark.parametrize("amount,minor_unit,expected", [
    (150_000, 2, "1,500.00"), (150_000, 0, "1,50,000"), (150_000, 3, "150.000"), (5, 2, "0.05"), (-5, 2, "-0.05"),
    (12_34_567_89, 2, "12,34,567.89"), (0, 3, "0.000"), (None, 2, "0.00"),
])
def test_minor_units_text_uses_the_decimals_the_currency_has(amount, minor_unit, expected):
    from domain.money_text import minor_units_text
    assert minor_units_text(amount, minor_unit) == expected


def test_the_authority_stays_free_of_the_sign_and_the_sentence_module_is_the_one_that_writes_it():
    """`domain/money_text` is re-exported to every PDF service, and a PDF cannot draw the sign."""
    import domain.money_text as authority
    import domain.money_sentence as sentence
    assert "₹" not in Path(authority.__file__).read_text().split('"""', 2)[2]
    assert "₹" in Path(sentence.__file__).read_text()
