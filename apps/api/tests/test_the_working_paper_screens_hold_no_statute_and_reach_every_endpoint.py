"""The three working-paper screens hold no statute, and every new endpoint has a
caller (TDS-INCOME-TAX-10, -14, -15).

WHY THIS IS PINNED FROM THE PYTHON SIDE
    A guard in apps/web asserting a browser list against a copy of itself passes
    whenever both drift together — the Schedule III caption lesson, and the
    reason `UNFORESEEN_KINDS_FALLBACK` is pinned here too. Each screen keeps a
    FALLBACK vocabulary for the window where the frontend redeploys ahead of the
    backend; the domain module is the authority and this file compares them.

WHAT IS ASSERTED
    * every option list a screen renders equals the domain vocabulary it stands
      in for, key for key and (where the domain has one) label for label;
    * the screens call the server for every figure — they contain no rate, no
      percentage and no arithmetic on a money value;
    * a screen puts a figure in a computation box only on the CA's click (the
      worksheets) or only into an EMPTY box (the AIS panel) — never over a typed
      figure;
    * the five endpoints this work mounts are each called by a screen, so the
      reachability ratchet (`test_every_mounted_endpoint_has_a_way_in`) does not
      move.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.income_tax import house_property as hp
from domain.income_tax import schedule_s as ss

WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
HP_SRC = (WEB / "components" / "tax" / "HousePropertyWorksheet.tsx").read_text(encoding="utf-8")
SAL_SRC = (WEB / "components" / "tax" / "SalaryWorksheet.tsx").read_text(encoding="utf-8")
AIS_SRC = (WEB / "components" / "tax" / "AisComputationLines.tsx").read_text(encoding="utf-8")
PAGE_SRC = (WEB / "app" / "clients" / "[id]" / "tax" / "computation" / "page.tsx").read_text(encoding="utf-8")
DATA_SRC = (WEB / "lib" / "data" / "income-tax.ts").read_text(encoding="utf-8")


def _options(src: str, name: str) -> list[tuple[str, str]]:
    start = src.index(f"const {name} = [")
    body = src[start:src.index("];", start)]
    pairs = re.findall(r'\{\s*key:\s*"([^"]*)",\s*label:\s*"([^"]*)"\s*\}', body)
    assert pairs, f"parsed nothing from {name} — a selector that matches nothing passes everything"
    return pairs


def _strip_comments(src: str) -> str:
    return re.sub(r"/\*[\s\S]*?\*/|(?<![:\"'])//.*", "", src)


# ══ the fallback vocabularies equal the domain's ═════════════════════════════

def test_the_use_options_are_the_domains_uses():
    assert [k for k, _ in _options(HP_SRC, "USE_OPTIONS")] == list(hp.USES)


def test_the_loan_purpose_options_are_the_domains_plus_not_stated():
    keys = [k for k, _ in _options(HP_SRC, "PURPOSE_OPTIONS")]
    assert keys[0] == "" and keys[1:] == list(hp.PURPOSES)


def test_the_perquisite_options_are_the_domains_kinds_and_labels():
    assert dict(_options(SAL_SRC, "PERQUISITE_OPTIONS")) == ss.PERQUISITE_KINDS


def test_the_exemption_options_are_the_domains_kinds_and_labels():
    assert dict(_options(SAL_SRC, "EXEMPTION_OPTIONS")) == {
        k: v[0] for k, v in ss.EXEMPTION_KINDS.items()}


def test_no_screen_says_which_exemptions_survive_the_new_regime():
    """That is the server's answer and arrives in the working. A boolean in the
    browser would be a second copy of a [S]-graded table."""
    code = _strip_comments(SAL_SRC)
    assert "115BAC" not in code and "newRegimeAllowed" not in code


# ══ they hold no statute ═════════════════════════════════════════════════════

@pytest.mark.parametrize("name,src", [("house property", HP_SRC), ("salary", SAL_SRC), ("ais", AIS_SRC)],
                         ids=["house-property", "salary", "ais"])
def test_a_screen_contains_no_rate_and_no_arithmetic_on_money(name, src):
    code = _strip_comments(src)
    # The one money parser, and nothing that multiplies, divides or rounds.
    assert not re.search(r"Math\.(round|floor|ceil|trunc)\(", code), name
    assert not re.search(r"parseFloat\(|parseInt\(", code), name
    assert not re.search(r"\*\s*100\b|/\s*100\b", code.replace("rupeeInputFromPaise", "")), name
    for rate in ("0.3", "30%", "3000", "200000", "20000000", "5000", "7.5"):
        assert rate not in re.sub(r'"[^"]*"|`[^`]*`', "", code), f"{name}: literal {rate}"
    assert "localStorage" not in code and "sessionStorage" not in code, name


def test_the_screens_read_every_figure_from_the_server():
    assert "getWorksheet" in HP_SRC and "saveWorksheet" in HP_SRC
    assert "getWorksheet" in SAL_SRC and "saveWorksheet" in SAL_SRC
    assert "getAisComputationLines" in AIS_SRC and "decideAisComputationLine" in AIS_SRC


def test_the_worksheets_are_asked_for_the_regime_the_computation_is_on():
    """Nothing derived is stored, so the answer follows the regime picker."""
    assert PAGE_SRC.count('useNewRegime={regime === "new"}') == 2


# ══ they put nothing in a box the CA did not choose ══════════════════════════

@pytest.mark.parametrize("name,src,callback", [
    ("house property", HP_SRC, "onUse"), ("salary", SAL_SRC, "onUse")], ids=["house-property", "salary"])
def test_a_worksheet_calls_back_only_from_a_click(name, src, callback):
    code = _strip_comments(src)
    calls = [m.start() for m in re.finditer(rf"\b{callback}\(", code)]
    assert calls, f"{name}: never calls {callback}"
    for at in calls:
        before = code[max(0, at - 60):at]
        assert "onClick={() =>" in before, f"{name}: {callback} is called outside a click handler"


def test_the_ais_panel_applies_only_to_an_empty_box_and_never_twice_for_one_figure():
    code = _strip_comments(AIS_SRC)
    assert "t.typed_paise === null" in code, "a box that holds a typed figure must never be overwritten"
    assert "applied.current[t.target] !== t.accept_paise" in code
    assert "t.accept_paise > 0" in code


def test_a_differing_typed_figure_is_flagged_and_the_screen_says_it_is_kept():
    assert "differs from the statement" in AIS_SRC and "Your figure is kept" in AIS_SRC


def test_the_page_never_overwrites_a_typed_box_from_the_ais_callback_itself():
    """The callback fills a box; whether the box was empty is the panel's test,
    made on the server's `typed_paise`, which this page sends from the boxes."""
    assert "typedGrossSalary={typedAmount(salary)}" in PAGE_SRC
    assert "typedOtherIncome={typedAmount(otherIncome)}" in PAGE_SRC


# ══ every endpoint this work mounts has a caller ═════════════════════════════

def _live_text() -> str:
    return "\n".join([HP_SRC, SAL_SRC, AIS_SRC, DATA_SRC])


@pytest.mark.parametrize("fragment", [
    "/api/income-tax/worksheets/${kind}",
    "/api/ais/computation-lines?",
    "/api/ais/computation-lines/${encodeURIComponent(lineKey)}/decision",
])
def test_every_new_endpoint_has_a_url_literal_a_screen_reaches(fragment):
    assert fragment in DATA_SRC
    # ...and the data-layer function holding it is NAMED by a component, which
    # is what the reachability scan counts as a caller.
    holder = {"/api/income-tax/worksheets/${kind}": ("getWorksheet", "saveWorksheet"),
              "/api/ais/computation-lines?": ("getAisComputationLines",),
              "/api/ais/computation-lines/${encodeURIComponent(lineKey)}/decision": ("decideAisComputationLine",)}[fragment]
    components = HP_SRC + SAL_SRC + AIS_SRC
    for name in holder:
        assert name in components, f"{name} is named by no screen"


def test_the_page_mounts_all_three_panels_under_one_working_papers_section():
    for tag in ("<AisComputationLinesPanel", "<HousePropertyWorksheet", "<SalaryWorksheet"):
        assert tag in PAGE_SRC, tag
    assert 'toggle("worksheets")' in PAGE_SRC and 'activeSection === "worksheets"' in PAGE_SRC
