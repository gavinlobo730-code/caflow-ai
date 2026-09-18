"""The book-to-tax bridge takes its figures from the books, not from a form.

WHY (FA-06 ≡ IT-09)
    `domain/income_tax/book_to_tax_bridge.py` and its endpoint have been
    complete for months and `grep -rn "book-to-tax\\|bookToTax" apps/web`
    returned TWO COMMENTS AND NO CALLER. The module's own docstring names why
    its inputs were typed: "Book profit was taken as an INPUT by the
    minimum-tax engine PRECISELY BECAUSE NOTHING DERIVED IT."

    Three of the four now are, and these assert the properties that make that
    safe rather than the fact of it.

THE ONE THAT MATTERS MOST
    `test_a_figure_that_could_not_be_read_makes_the_bridge_incomplete`. A
    figure the books could not produce is passed as ZERO so the arithmetic
    still works, and a bridge that FOOTS on a zero nobody measured is exactly
    what the module refuses to be: "a bridge that reconciles and lies is worse
    than one that refuses to reconcile." `foots` and `is_complete` are two
    different properties and this holds them apart.

NEGATIVE CONTROLS
  * Make a caller's value lose to the derived one and
    `test_a_supplied_figure_wins` fails — which would make the screen useless
    for a client whose accounts were prepared elsewhere.
  * Derive the brought-forward set-off from the single bridge figure and
    `test_the_brought_forward_set_off_is_never_derived` fails: §72/§73(4)/§74/
    §71B each reach only certain HEADS and the bridge holds one number.
  * Drop the `unreadable` limb from `is_complete` and the completeness test
    fails on a bridge that foots perfectly.
"""
from __future__ import annotations

import ast
import inspect

import pytest

import routers.income_tax as it
import services.book_to_tax_service as b2t
from tests._python_source import blank_python_docstrings

FIRM = "11111111-1111-1111-1111-111111111111"
CLIENT = "22222222-2222-2222-2222-222222222222"
FY = "2025-26"
USER = {"firm_id": FIRM, "id": "u1", "role": "Partner"}


# ── what is derived, and what is refused ─────────────────────────────────────

def test_a_supplied_figure_wins_and_says_it_was_supplied():
    """A CA may be bridging a client whose accounts were prepared elsewhere.
    Refusing their figure would make the screen useless for exactly the clients
    whose bridge is hardest."""
    out = b2t.resolve_inputs(object(), FIRM, CLIENT, FY, USER,
                             book_profit_paise=5_000_00,
                             disallowances_paise=1_00_00,
                             depreciation_per_books_paise=2_00_00)
    assert out["book_profit"].value == 5_000_00
    assert out["book_profit"].derived is False
    assert out["book_profit"].source == b2t.CALLER_SUPPLIED
    # And nothing was fetched: a supplied value must not cost a round trip.
    assert out["depreciation_per_books"].value == 2_00_00


def test_a_zero_is_a_figure_and_suppresses_the_derivation():
    """`0` and "nothing said" are different, and only the second derives.

    This is what lets the screen leave a box EMPTY to mean derive: sending 0
    would be a claim that the accounts show nil profit.
    """
    out = b2t.resolve_inputs(object(), FIRM, CLIENT, FY, USER,
                             book_profit_paise=0,
                             disallowances_paise=0,
                             depreciation_per_books_paise=0)
    assert out["book_profit"].value == 0
    assert out["book_profit"].derived is False


def test_an_unreadable_financial_year_derives_nothing_and_says_so():
    out = b2t.resolve_inputs(object(), FIRM, CLIENT, "not-a-year", USER)
    for key in ("book_profit", "disallowances", "depreciation_per_books"):
        assert out[key].value is None
        assert "financial year" in out[key].source


def test_the_brought_forward_set_off_is_never_derived():
    """§72, §73(4), §74 and §71B each let a loss reach only certain HEADS of
    income, and the bridge holds one figure for the whole computation. A
    set-off derived from it would assert a head-wise answer nothing here sees.
    """
    assert "resolve_inputs" in dir(b2t)
    src = blank_python_docstrings(inspect.getsource(b2t.resolve_inputs))
    assert "loss" not in src.lower(), (
        "the resolver must not touch brought-forward losses")
    # And the refusal is a sentence somebody reads, not a silent omission.
    assert "§72" in b2t.BF_LOSS_IS_NOT_DERIVED
    assert "head" in b2t.BF_LOSS_IS_NOT_DERIVED.lower()


def test_none_is_not_zero_on_any_derived_input():
    """A figure that could not be READ and a figure that IS nil are different
    facts. `DerivedInput.value` is Optional for that reason, and every
    unreadable case carries a sentence rather than a number."""
    d = b2t.DerivedInput(None, "could not be read", True)
    assert d.value is None
    assert d.to_dict()["value_paise"] is None


# ── one definition of each fact ──────────────────────────────────────────────

def test_the_depreciation_charge_is_imported_not_restated():
    """FA-05 records why this must be the LEDGER's posted figure rather than
    the register's theoretical full-year charge, and two readers of one fact
    is how the note and the Reports tab came to disagree.

    A READER IS A QUERY, NOT A MENTION. The first draft banned the string
    "account_period_balances" anywhere in the module and tripped on the
    PROVENANCE SENTENCE — the words shown beside the figure, which name the
    table precisely so a CA can check it. Citing a source is the opposite of
    re-reading it. So this asserts on the calls: no `.table(...)` in this
    module names a table at all, because everything it needs comes from a
    module that already reads it.
    """
    src = blank_python_docstrings(inspect.getsource(b2t))
    assert "posted_depreciation_paise" in src, (
        "vacuity floor: the charge must still come from the one reader")

    tables = [
        n.args[0].value
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "table"
        and n.args and isinstance(n.args[0], ast.Constant)
    ]
    assert tables == [], (
        f"this service fetches through the modules that own each fact; a query "
        f"here is a second reader of one of them: {tables}")


def test_the_43bh_figure_comes_from_the_module_that_decides_it():
    """Its rule is fifteen days, the written agreement, the forty-five day cap
    and the goods receipt. Re-deciding any of it here would be a second
    §43B(h)."""
    src = blank_python_docstrings(inspect.getsource(b2t.section_43bh_disallowance))
    assert "for_financial_year" in src
    for restated in ("45", "fifteen", "msme_status", "agreed_days"):
        assert restated not in src, f"§43B(h)'s own rule was restated: {restated}"


def test_the_book_profit_is_scoped_to_the_caller():
    """ACC-17: a reporting call built without the caller's scope spans the
    whole firm for an Executive, and a bridge is a per-client document."""
    src = blank_python_docstrings(inspect.getsource(b2t.book_profit))
    assert "_reporting_service" in src
    assert "current_user" in src


def test_the_service_computes_no_statutory_rule_of_its_own():
    """It fetches. Every rule stays in its own domain module."""
    tree = ast.parse(blank_python_docstrings(inspect.getsource(b2t)))
    called = {getattr(n.func, "attr", getattr(n.func, "id", ""))
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "build_bridge" not in called, (
        "the bridge is built by the ROUTER from these inputs; building it here "
        "would put two assemblers on one statement")


# ── the endpoint ─────────────────────────────────────────────────────────────

def test_the_three_derivable_inputs_are_optional_on_the_request():
    """An omitted field is what tells the server to derive. Required-with-a-
    default-of-zero would make every blank box a claim that the figure is nil.
    """
    fields = it.BookToTaxBridgeRequest.model_fields
    for name in ("book_profit_paise", "disallowances_paise",
                 "depreciation_per_books_paise"):
        assert fields[name].default is None, f"{name} must default to None"
    assert fields["brought_forward_loss_set_off_paise"].default == 0, (
        "the set-off is never derived, so zero is the right default there")


def _endpoint_with(monkeypatch, resolved, *, section_32_complete: bool):
    """The endpoint, with §32 and the resolver both under our control.

    §32 MUST BE COMPLETE for the unreadable-input assertion to mean anything.
    A withheld §32 figure makes `build_bridge` incomplete ON ITS OWN, so a
    fixture without it asserts False for a reason that has nothing to do with
    what is being tested -- which is exactly what the first draft did, and the
    negative control PASSED because of it.
    """
    monkeypatch.setattr(it, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(it, "_db", lambda: object())
    monkeypatch.setattr(b2t, "resolve_inputs", lambda *a, **k: resolved)
    monkeypatch.setattr(
        "services.section_32_service.section_32_service.assemble",
        lambda *a, **k: {"is_complete": section_32_complete,
                         "allowance_paise": 4_00_000})
    return it.book_to_tax_bridge(
        req=it.BookToTaxBridgeRequest(client_id=CLIENT, fy=FY),
        current_user=USER)["data"]


def _readable(book=10_00_000, disallow=1_00_000, depn=3_00_000):
    return {
        "book_profit": b2t.DerivedInput(book, "from the P&L", True),
        "disallowances": b2t.DerivedInput(disallow, "§43B(h)", True),
        "depreciation_per_books": b2t.DerivedInput(depn, "from the ledger", True),
    }


def test_a_readable_bridge_with_section_32_is_complete(monkeypatch):
    """The control case, and the reason the next test proves anything: with
    every figure read and §32 supplied, nothing is outstanding."""
    data = _endpoint_with(monkeypatch, _readable(), section_32_complete=True)
    assert data["foots"] is True
    assert data["is_complete"] is True


def test_a_figure_that_could_not_be_read_makes_the_bridge_incomplete(monkeypatch):
    """THE ONE THAT MATTERS. An unreadable figure is passed as zero so the
    arithmetic still works -- and a bridge that FOOTS on a zero nobody measured
    is what the module exists to refuse: "a bridge that reconciles and lies is
    worse than one that refuses to reconcile."

    §32 is COMPLETE here, so the only thing that can make this incomplete is
    the unreadable input. The previous version left §32 withheld and passed
    whatever the endpoint did.
    """
    unreadable = {k: b2t.DerivedInput(None, "could not be read", True)
                  for k in ("book_profit", "disallowances",
                            "depreciation_per_books")}
    data = _endpoint_with(monkeypatch, unreadable, section_32_complete=True)
    assert data["foots"] is True, "the arithmetic still works on zeros"
    assert data["is_complete"] is False, (
        "but the bridge must not claim completeness on figures nobody read")
    assert any("could not be read" in r for r in data["reasons"])


def test_one_unreadable_figure_is_enough(monkeypatch):
    """Not all three. Any single figure nobody could read leaves the statement
    resting on a zero that is not a measurement."""
    partial = _readable()
    partial["depreciation_per_books"] = b2t.DerivedInput(
        None, "the Depreciation Expense account could not be resolved", True)
    data = _endpoint_with(monkeypatch, partial, section_32_complete=True)
    assert data["is_complete"] is False
    assert any("Depreciation Expense" in r for r in data["reasons"])


def test_the_endpoint_reports_where_every_input_came_from(monkeypatch):
    monkeypatch.setattr(it, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(it, "_db", lambda: None)   # mock mode
    req = it.BookToTaxBridgeRequest(client_id=CLIENT, fy=FY,
                                    book_profit_paise=10_00_000)
    out = it.book_to_tax_bridge(req=req, current_user=USER)
    inputs = out["data"]["inputs"]
    assert set(inputs) == {"book_profit", "disallowances",
                           "depreciation_per_books"}
    assert inputs["book_profit"]["value_paise"] == 10_00_000
    assert inputs["book_profit"]["derived"] is False


def test_the_set_off_refusal_is_on_every_answer(monkeypatch):
    monkeypatch.setattr(it, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(it, "_db", lambda: None)
    req = it.BookToTaxBridgeRequest(client_id=CLIENT, fy=FY)
    out = it.book_to_tax_bridge(req=req, current_user=USER)
    assert b2t.BF_LOSS_IS_NOT_DERIVED in out["data"]["reasons"]


def test_the_endpoint_is_client_scoped(monkeypatch):
    seen = {}
    monkeypatch.setattr(it, "assert_client_access",
                        lambda user, cid: seen.setdefault("cid", cid))
    monkeypatch.setattr(it, "_db", lambda: None)
    it.book_to_tax_bridge(
        req=it.BookToTaxBridgeRequest(client_id=CLIENT, fy=FY),
        current_user=USER)
    assert seen["cid"] == CLIENT


def test_the_endpoint_says_it_files_nothing():
    src = inspect.getsource(it.book_to_tax_bridge)
    assert "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT" in src


# ── and it finally has a reader ──────────────────────────────────────────────

def test_the_browser_reaches_the_bridge():
    """The whole finding: the engine and the endpoint were complete and
    nothing called them."""
    from pathlib import Path
    web = Path(__file__).resolve().parents[3] / "apps" / "web"
    page = web / "app" / "income-tax" / "book-to-tax" / "page.tsx"
    assert page.exists(), "the bridge needs a screen; that IS the finding"
    body = page.read_text()
    assert "/api/income-tax/book-to-tax-bridge" in body
    # …and it is reachable, not an orphan route.
    hub = (web / "app" / "income-tax" / "page.tsx").read_text()
    assert "/income-tax/book-to-tax" in hub, (
        "a screen nothing links to is the same defect one layer up")


def test_the_screen_computes_no_part_of_the_bridge():
    """CLAUDE.md: zero business logic in the frontend. Every figure, `foots`
    and `is_complete` come off the response."""
    from pathlib import Path
    web = Path(__file__).resolve().parents[3] / "apps" / "web"
    body = (web / "app" / "income-tax" / "book-to-tax" / "page.tsx").read_text()
    import re
    code = re.sub(r"/\*[\s\S]*?\*/", " ", body)
    code = re.sub(r"(^|[^:])//[^\n]*", r"\1", code)
    for forbidden in ("taxable_income_paise =", "book_profit_paise +",
                      "signed_paise", "reduce("):
        assert forbidden not in code, f"the screen computed {forbidden}"
    # A typed amount goes through the one parser, never a bare parseFloat.
    assert "paiseFromRupeeInput" in code
    assert "parseFloat" not in code
