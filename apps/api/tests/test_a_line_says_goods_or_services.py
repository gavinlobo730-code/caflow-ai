"""
A SAC IS CHAPTER 99, AND THE RULE LIVED ONLY IN THE BROWSER.

`apps/web/lib/invoices/compliance.isServiceCode` has classified a line as goods
or services off the tariff chapter since the e-way split was built, and had NO
PYTHON TWIN — the same defect SALES-17 (the e-way threshold, measured on the
pre-GST taxable value) and SALES-18 (the Rule 48(4) scope test) were. A
statutory classification living in one place, in the browser, with nothing
pinning it.

`domain/gst/goods_or_services.py` is the twin and `tests/fixtures/
goods_or_services.json` holds the two together — the same shape as
`tests/fixtures/invoice_number.json` and `shared/gst-parity-vectors.json`.

WHY IT MATTERS NOW. Migration 411 gave a sales invoice line an `is_service`,
and the e-invoice portal makes quantity and Unit Quantity Code mandatory for
GOODS and optional for services. Reading the stored column alone would report
"nobody said" against a line whose own code reads `998313` — so the column is
an OVERRIDE and the code is the source, which is the relationship
`account_group_mappings` should have had to `schedule_line_for_account` and did
not.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from domain.gst import goods_or_services as gs

FIXTURE = Path(__file__).parent / "fixtures" / "goods_or_services.json"
CASES = json.loads(FIXTURE.read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["code"] or "<empty>" for c in CASES])
def test_the_code_answers_as_the_fixture_says(case):
    assert gs.is_service_code(case["code"]) is case["python"], case["why"]


def test_the_third_state_is_NOT_false():
    """"This is not a service" and "nobody can tell" send a CA to different
    places, and an empty `hsn_sac` means the second."""
    assert gs.is_service_code("") is None
    assert gs.is_service_code(None) is None
    assert gs.is_service_code("8471") is False


# ── the resolver ─────────────────────────────────────────────────────────────

def test_a_RECORDED_value_wins_over_the_code():
    """The whole point of migration 411's column.

    The reverse order would make it unwritable in practice: every line carrying
    an HSN would ignore what the CA said.
    """
    assert gs.resolve(recorded=True, hsn_sac_code="8471") == (True, gs.SOURCE_RECORDED)
    assert gs.resolve(recorded=False, hsn_sac_code="998313") == (False, gs.SOURCE_RECORDED)


def test_the_CODE_answers_where_nothing_was_recorded():
    assert gs.resolve(recorded=None, hsn_sac_code="998313") == (True, gs.SOURCE_CODE)
    assert gs.resolve(recorded=None, hsn_sac_code="8471") == (False, gs.SOURCE_CODE)


def test_NEITHER_is_its_own_answer_and_the_source_says_so():
    assert gs.resolve(recorded=None, hsn_sac_code="") == (None, gs.SOURCE_UNKNOWN)
    assert gs.resolve(recorded=None, hsn_sac_code="SAC998") == (None, gs.SOURCE_UNKNOWN)


def test_the_SOURCE_travels_because_the_two_facts_are_different():
    """"A service because the CA said so" survives them changing the code;
    "a service because the code is 9983" does not."""
    _, a = gs.resolve(recorded=True, hsn_sac_code="998313")
    _, b = gs.resolve(recorded=None, hsn_sac_code="998313")
    assert a != b


# ── the browser is pinned FROM HERE ──────────────────────────────────────────

def test_the_browser_copy_matches_the_fixture():
    """Pinned from the PYTHON side, the Schedule III caption lesson: a guard
    written in `apps/web` asserts the browser against a copy of itself and
    passes whenever both drift together.

    The browser returns a BOOLEAN and folds the third state into false, which
    is right for its own caller — the e-way split counts unclassified lines on
    the code being ABSENT, not on this function. The fixture records that
    difference rather than either side being bent to match.
    """
    web = (Path(__file__).resolve().parents[3] / "apps" / "web"
           / "lib" / "invoices" / "compliance.ts").read_text()
    body = web.split("export function isServiceCode")[1].split("\n}")[0]
    assert '"99"' in body, "the browser no longer tests the service chapter"
    assert "slice(0, 2)" in body
    assert "length >= 2" in body
    assert "/^\\d+$/" in body, "the browser no longer requires a numeric code"
    for case in CASES:
        assert isinstance(case["browser"], bool), \
            f"{case['code']!r}: the browser column must be a boolean"
        if case["python"] is not None:
            assert case["browser"] is case["python"], \
                (f"{case['code']!r}: the two disagree on a code BOTH can read — "
                 f"that is a real divergence, not the third state")


def test_nothing_here_moves_a_rupee():
    """The tax on a line comes from its own rate. Goods-or-services changes the
    PLACE OF SUPPLY rules (IGST §§10-13), which is a question about the
    transaction and is deliberately not answered here.

    DOCSTRINGS STRIPPED FIRST — the module's own header explains all of that,
    so a scan over the raw source finds every word it forbids and fails on the
    documentation rather than on the code. Same lesson as the dead-master guard
    and the panel scans: strip the prose before asserting about the code.
    """
    import ast
    tree = ast.parse(inspect.getsource(gs))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.unparse(tree)
    body = "\n".join(l for l in code.splitlines()
                      if not l.lstrip().startswith("#")).lower()
    for forbidden in ("paise", "cgst", "sgst", "igst", "_rate", "rate_"):
        assert forbidden not in body, f"{forbidden} — this module decides no money"
    assert "is_service_code" in body, "the strip did not leave the code behind"
